"""
需求：只灌数据，不动表结构 —— 执行 insert_may01_data.sql

和隔壁 run_sql_file.py 的分工：
    run_sql_file.py     建库建表（DDL），会 DROP DATABASE，要 root，破坏性
    run_insert_data.py  只灌数据（DML），不碰表结构，用业务账号，可重复跑

思路：
1. 复用 run_sql_file.py 里的 split_statements()，不重复写那套引号状态机
2. 用 config.py 的业务账号连接（不是 root，理由见第 1 步）
3. 按 --mode 把 INSERT 改写成幂等写法，重复跑不炸（理由见第 2 步）
4. 执行前后各数一次行数，把"这次实际新增了多少"算出来
5. 收尾抽查几条真实数据，确认不只是"插进去了"而是"能查出来"

⚠️ 本脚本不会删表也不会删库。唯一的数据变更是 INSERT，
   --mode replace 会覆盖同唯一键的旧行，这是三种模式里唯一会改动已有数据的。

前置条件：表必须已经存在。没建表先跑：
    PYTHONPATH=. python SmartVoyage/docker/data_init/run_sql_file.py create_all_tables.sql

用法（在仓库根目录）：
    # 默认 ignore 模式，重复跑安全，已存在的行自动跳过
    PYTHONPATH=. python SmartVoyage/docker/data_init/run_insert_data.py

    # 覆盖模式：同唯一键的旧行被新数据替换（改价格、改余票后重灌用这个）
    PYTHONPATH=. python SmartVoyage/docker/data_init/run_insert_data.py --mode replace

    # 严格模式：原样 INSERT，撞唯一键就报 1062。课上用来演示"为什么需要前两种"
    PYTHONPATH=. python SmartVoyage/docker/data_init/run_insert_data.py --mode strict

    # 换个数据文件
    PYTHONPATH=. python SmartVoyage/docker/data_init/run_insert_data.py insert_may01_data.sql
"""

import os
import re
import sys

import mysql.connector

# 三层向上才是仓库根目录：data_init -> docker -> SmartVoyage -> prepare_smart_voyage
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', '..')))
# 把脚本自己所在目录也加上，才能 import 隔壁的 run_sql_file
sys.path.insert(0, HERE)

from SmartVoyage.config import Config

# todo: 第0步：复用而不是复制
# split_statements() 那套"只在引号外才认分号"的状态机有 50 多行，
# 隔壁 run_sql_file.py 已经写好并验证过了，直接 import。
# 复制一份的代价是：以后修一个 SQL 解析的坑要记得改两处，迟早漏。
from run_sql_file import split_statements, brief

conf = Config()

DEFAULT_SQL = 'insert_may01_data.sql'

# insert_may01_data.sql 实际会写入的 6 张表，按文件里出现的顺序
# 另外 3 张（user_profiles / query_history / short_term_messages）是
# 应用运行时才写的，本脚本不碰
DATA_TABLES = [
    'train_tickets',
    'flight_tickets',
    'concert_tickets',
    'car_rentals',
    'insurances',
    'weather_data',
]

# 见 run_sql_file.py 第 3 步：本机等锁上限是一年，不压掉的话
# 撞上未提交的连接就是无限期假死
LOCK_WAIT_TIMEOUT = 10

MODES = ('ignore', 'replace', 'strict')


def parse_args(argv: list) -> tuple:
    """
    手工解析命令行，不引 argparse

    返回值：
        tuple: (sql 文件名, 模式)
    """
    mode = 'ignore'
    files = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--mode':
            if i + 1 >= len(argv):
                raise SystemExit("--mode 后面要跟 " + " / ".join(MODES))
            mode = argv[i + 1]
            i += 2
            continue
        if a.startswith('--mode='):
            mode = a.split('=', 1)[1]
            i += 1
            continue
        if a.startswith('-'):
            i += 1
            continue
        files.append(a)
        i += 1

    if mode not in MODES:
        raise SystemExit(f"未知模式 {mode!r}，可选：{' / '.join(MODES)}")

    return (files[0] if files else DEFAULT_SQL), mode


def rewrite_insert(stmt: str, mode: str) -> str:
    """
    按模式改写 INSERT 语句，让它可以重复执行

    参数：
        stmt (str): 原始语句
        mode (str): ignore / replace / strict

    返回值：
        str: 改写后的语句

    todo: 第2步：为什么必须改写 INSERT
    6 张表每张都有唯一键（train_tickets 是 unique_train，weather_data 是
    unique_city_date，insurances 是 name……）。直接原样重跑 insert_may01_data.sql，
    第二次就会撞唯一键报 1062 Duplicate entry，整个文件白跑。

    三种模式对应三种态度，课上正好拿来讲"幂等"：
      strict  原样不动。撞了就报错 —— 这是最原始的行为，用来演示问题本身
      ignore  INSERT IGNORE：已存在的行悄悄跳过，只补缺的。最安全，作默认
      replace REPLACE INTO：同唯一键的旧行先删再插，用新数据覆盖。
              注意它是"删+插"，所以自增 id 会变，created_at 也会刷新 ——
              改了价格 / 余票想让数据生效，用这个

    只改写 INSERT，USE 之类的语句原样放过。
    """
    if mode == 'strict':
        return stmt

    upper = stmt.upper()
    if not upper.startswith('INSERT'):
        return stmt

    if mode == 'ignore':
        # INSERT INTO ... -> INSERT IGNORE INTO ...
        # 用 re 保证只替换开头那一个 INSERT，别碰数据里可能出现的同名文字
        return re.sub(r'^INSERT\s+INTO\b', 'INSERT IGNORE INTO', stmt,
                      count=1, flags=re.IGNORECASE)

    # replace: INSERT INTO ... -> REPLACE INTO ...
    return re.sub(r'^INSERT\s+INTO\b', 'REPLACE INTO', stmt,
                  count=1, flags=re.IGNORECASE)


def target_table(stmt: str) -> str:
    """从 INSERT / REPLACE 语句里抠出表名，用于打印和计数"""
    m = re.match(r'^(?:INSERT(?:\s+IGNORE)?|REPLACE)\s+INTO\s+`?(\w+)`?',
                 stmt, flags=re.IGNORECASE)
    return m.group(1) if m else ''


def count_rows(cursor) -> dict:
    """
    数一遍 6 张数据表当前的行数

    todo: 第3步：执行前后各数一次，才知道"这次到底加了多少"
    cursor.rowcount 在 INSERT IGNORE 下只报实际插入的行数，跳过的不算，
    看着容易误解成"少插了"。所以用前后差值来说明变化，比单看 rowcount 直观。
    """
    counts = {}
    for t in DATA_TABLES:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM `{t}`")
            counts[t] = cursor.fetchone()[0]
        except mysql.connector.Error:
            # 表不存在就记成 None，后面统一提示先去建表
            counts[t] = None
    return counts


def connect():
    """
    用业务账号连接 travel_rag

    todo: 第1步：为什么这里可以用 smart_yoyage，而 run_sql_file.py 必须用 root
    权限只要够用就好，不要习惯性上 root。实测 smart_yoyage 的授权是
        GRANT ALL PRIVILEGES ON `travel_rag`.* TO 'smart_yoyage'@'%'
    库内的 INSERT / DELETE / SELECT 全都够。
    run_sql_file.py 用 root 是因为它头两句是 DROP DATABASE / CREATE DATABASE，
    那是**库级**操作，超出了 travel_rag.* 的范围，业务账号做不了。

    这里也可以直接指定 database=travel_rag —— 本脚本不会删库，
    连接不会像 run_sql_file.py 那样中途悬空。
    """
    conn = mysql.connector.connect(
        host=conf.host,
        user=conf.user,
        password=conf.password,
        database=conf.database,
        charset='utf8mb4',
        collation='utf8mb4_unicode_ci',
    )
    cursor = conn.cursor()
    cursor.execute(f"SET SESSION lock_wait_timeout = {LOCK_WAIT_TIMEOUT}")
    cursor.execute(f"SET SESSION innodb_lock_wait_timeout = {LOCK_WAIT_TIMEOUT}")
    return conn, cursor


def sample_check(cursor):
    """
    抽查几条真实数据

    todo: 第6步：行数对了不等于数据对了
    COUNT(*) 只能说明"有行"，说明不了"内容能用"。这里按下游 Agent
    真正会发的查询抽几条看看 —— 中文没乱码、金额没被截断、日期是 5-01，
    这三样确认了才算数据真的可用。
    """
    print("\n===== 抽查（模拟下游查询）=====")

    checks = [
        ("北京→成都 5/1 最便宜的二等座",
         "SELECT train_number, departure_time, price FROM train_tickets "
         "WHERE departure_city='北京' AND arrival_city='成都' "
         "AND seat_type='二等座' ORDER BY price LIMIT 3"),
        ("成都 5/1 天气",
         "SELECT city, fx_date, temp_min, temp_max, text_day FROM weather_data "
         "WHERE city='成都' AND fx_date='2026-05-01'"),
        ("成都 5/1 的演唱会",
         "SELECT artist, venue, start_time, price FROM concert_tickets "
         "WHERE city='成都' ORDER BY start_time LIMIT 3"),
    ]

    for title, sql in checks:
        print(f"\n  {title}")
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            if not rows:
                print("    （没查到数据）")
            for r in rows:
                print(f"    {r}")
        except mysql.connector.Error as e:
            print(f"    查询失败：{e}")


def run(sql_path: str, mode: str):
    """
    主流程：读文件 -> 改写 -> 执行 -> 对比行数 -> 抽查

    参数：
        sql_path (str): .sql 文件绝对路径
        mode (str): ignore / replace / strict
    """
    statements = split_statements(open(sql_path, encoding='utf-8').read())
    if not statements:
        print("文件里没有可执行的语句")
        return

    print(f"文件：{os.path.basename(sql_path)}")
    print(f"模式：{mode}")
    print(f"账号：{conf.user}@{conf.host}/{conf.database}")
    print(f"语句：{len(statements)} 条")

    conn, cursor = connect()

    try:
        # todo: 第4步：先确认表在，再往里插
        # 表不存在时报的 1146 Table doesn't exist 一条条刷屏，
        # 不如提前一次说清"你还没建表"。
        before = count_rows(cursor)
        missing = [t for t, n in before.items() if n is None]
        if missing:
            print(f"\n以下表不存在：{'、'.join(missing)}")
            print("先建表：PYTHONPATH=. python SmartVoyage/docker/data_init/"
                  "run_sql_file.py create_all_tables.sql")
            return

        print("\n===== 执行前行数 =====")
        for t in DATA_TABLES:
            print(f"  {t:20s} {before[t]:6d} 行")

        print(f"\n===== 开始执行（{mode} 模式）=====")
        ok, failed = 0, 0
        for idx, raw in enumerate(statements, 1):
            stmt = rewrite_insert(raw, mode)
            try:
                cursor.execute(stmt)
                if cursor.with_rows:
                    cursor.fetchall()
                ok += 1
                tbl = target_table(stmt)
                # rowcount 在 REPLACE 下会把"删一行+插一行"算成 2，这里只作参考，
                # 真正的净变化看后面的前后差值
                note = f"影响 {cursor.rowcount} 行" if tbl else ''
                print(f"  [{idx}/{len(statements)}] OK   {brief(stmt)}  {note}")
            except mysql.connector.Error as e:
                failed += 1
                print(f"  [{idx}/{len(statements)}] FAIL {brief(stmt)}")
                print(f"       → {e}")
                # 1062 是撞唯一键。strict 模式下这是预期中的演示效果，
                # 顺手把解法提示出来，省得课上再翻文档
                if e.errno == 1062 and mode == 'strict':
                    print("       → strict 模式就是会这样。改用 --mode ignore "
                          "跳过重复，或 --mode replace 覆盖")
                elif e.errno == 1205:
                    raise RuntimeError(
                        "拿不到表锁，说明还有连接占着这些表。"
                        "先停掉业务应用（Streamlit / FastAPI）再重跑。"
                    ) from e

        # todo: 第5步：这一句不能省
        # 本机 @@autocommit 是 0（实测），不 commit 的话连接一断
        # 上面插的数据全部回滚，表面上"跑成功了"其实一行没留下。
        conn.commit()
        print(f"\n执行完毕：成功 {ok} 条，失败 {failed} 条")

        after = count_rows(cursor)
        print("\n===== 行数变化 =====")
        total_delta = 0
        for t in DATA_TABLES:
            delta = after[t] - before[t]
            total_delta += delta
            flag = f"+{delta}" if delta > 0 else ('0' if delta == 0 else str(delta))
            print(f"  {t:20s} {before[t]:6d} -> {after[t]:6d}  ({flag})")
        print(f"  {'合计':20s} 净增 {total_delta} 行")

        if total_delta == 0 and failed == 0:
            print("\n净增 0 行：数据本来就已经全在库里了（ignore 模式跳过了全部重复行）")
            print("  想用文件里的新数据覆盖旧行，用 --mode replace")

        sample_check(cursor)
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    sql_name, mode = parse_args(sys.argv[1:])
    sql_path = sql_name if os.path.isabs(sql_name) else os.path.join(HERE, sql_name)

    if not os.path.isfile(sql_path):
        print(f"找不到文件：{sql_path}")
        sys.exit(1)

    try:
        run(sql_path, mode)
    except mysql.connector.Error as e:
        print(f"\n数据库连接失败：{e}")
        print("检查一下：容器起了吗（docker-compose ps）、3306 是否被本机 MySQL 占用、"
              f"{conf.user} 的密码对不对")
    except Exception as e:
        print(f"\n执行出错：{e}")
