# Docker 环境说明

配套文件：`docker/docker-compose.yml`

项目依赖的中间件全部容器化，一条命令拉起。

## 一、服务清单

| 服务 | 容器名 | 宿主机端口 | 用途 |
|---|---|---|---|
| `mysql` | `smart-mysql` | **3306** | 业务库 `travel_rag`，9 张表 |
| `standalone` | `milvus-standalone` | **19530** / 9091 | Milvus 向量库，`tour_groups` collection |
| `attu` | `milvus-attu` | **8000** | Milvus 可视化界面 → http://localhost:8000 |
| `etcd` | `milvus-etcd` | 不暴露 | Milvus 元数据存储（内部组件） |
| `minio` | `milvus-minio` | 不暴露 | Milvus 对象存储（内部组件） |
| `redis` | `milvus-redis` | 6379 | 缓存，密码 `1234` |

`etcd` 和 `minio` 是 Milvus 的依赖，不用直接打交道，但**必须跟着起**——Milvus 存元数据靠 etcd、存向量文件靠 MinIO，缺一个就起不来。

## 二、⚠️ 启动前必须先停本机 MySQL

容器映射的是 `3306:3306`，而本机装的 MySQL 服务也占着 3306，**端口冲突会导致容器起不来**。

```powershell
# 查服务名
sc query | findstr -i mysql

# 停掉（服务名按上一步查到的填，常见是 MySQL57 / MySQL80 / MySQL）
net stop MySQL57
```

需要 `net stop` 报权限错误时，用管理员身份开 PowerShell。

想让两个 MySQL 并存也可以：把 compose 里 mysql 的端口改成 `"3307:3306"`，
然后在 `config.py` 里加 `self.port = 3307`，并在 `mysql.connector.connect(...)` 调用处传 `port=conf.port`
（目前三个 `*Service.__init__` 都没传 port，默认 3306，所以改端口要同步改代码）。

## 三、启动

```powershell
cd "D:\我的备课\prepare_smart_voyage\docker"
docker-compose up -d
```

首次启动要拉镜像（约 1-2 GB），耐心等。之后启动只需十几秒，但 **Milvus 就绪要 30-60 秒**
（要等 etcd 和 MinIO 先健康）。

看状态：

```powershell
docker-compose ps                    # 全部应为 Up / healthy
docker-compose logs -f standalone    # 跟踪 Milvus 启动日志，Ctrl+C 退出
```

## 四、常用命令

```powershell
docker-compose stop        # 停止但保留容器和数据
docker-compose start       # 再启动
docker-compose restart     # 重启
docker-compose down        # 删除容器（volumes/ 里的数据仍在，重新 up 数据还在）
docker-compose ps          # 状态
docker-compose logs mysql  # 看某个服务的日志
```

数据全部落在 `docker/volumes/` 下（`mysql/`、`milvus/`、`etcd/`、`minio/`、`redis/`），
`down` 不会删。**要彻底清空重来才需要手动删这个目录**——注意这会丢掉所有数据。

## 五、灌 MySQL 数据

容器首次启动时 `MYSQL_DATABASE: travel_rag` 只建了**空库**，表和数据要自己导。

### 先从原本机 MySQL 导出

停掉本机 MySQL 之前先导，否则连不上：

```powershell
cd "D:\我的备课\prepare_smart_voyage\docker"

# 导出结构 + 数据（用原本机的 root 账号）
mysqldump -h 127.0.0.1 -P 3306 -uroot -p123456 --default-character-set=utf8mb4 travel_rag > backup.sql
```

`mysqldump` 不在 PATH 里的话用完整路径，例如
`"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysqldump.exe"`。

### 再导入容器

```powershell
# 确认容器已 Up 且 healthy
docker-compose ps

# 导入（注意是 <，用 smart_yoyage 账号）
docker exec -i smart-mysql mysql -usmart_yoyage -p123456 --default-character-set=utf8mb4 travel_rag < backup.sql
```

验证：

```powershell
docker exec -it smart-mysql mysql -usmart_yoyage -p123456 -e "USE travel_rag; SHOW TABLES;"
```

预期 9 张表：`car_rentals`、`concert_tickets`、`flight_tickets`、`insurances`、
`query_history`、`short_term_messages`、`train_tickets`、`user_profiles`、`weather_data`。

### 另一种方式：自动初始化

把 `.sql` 文件放进 `docker/mysql-init/`，容器**首次**启动时会自动按文件名顺序执行
（`/docker-entrypoint-initdb.d` 机制）。

注意"首次"两个字：这个目录只在数据卷为空时生效。已经启动过再放文件不会执行，
得先 `docker-compose down` 并删掉 `volumes/mysql/` 才行。

## 六、Attu：Milvus 可视化界面

浏览器打开 **http://localhost:8000**，连接地址填 `standalone:19530`（默认已通过
`MILVUS_URL` 环境变量配好，一般直接点连接即可）。

能做的事：看 collection 列表和 schema、浏览数据、建/删索引、跑向量检索、看分区。
排查 `query_tour_group` 返回 `no_data` 时特别有用——先在 Attu 里确认
`tour_groups` collection 存在、有数据、且索引已建好。

**为什么环境变量是 `standalone:19530` 而不是 `localhost:19530`**：
Attu 自己也在容器里，`localhost` 指的是 Attu 容器自身。容器之间通信要用**服务名**，
Docker 内置 DNS 会把 `standalone` 解析到 Milvus 容器的内网 IP。
同理 Milvus 连 etcd 用的是 `ETCD_ENDPOINTS=etcd:2379`。

而你的 Python 代码跑在**宿主机**上，所以 `config.py` 里用 `localhost:19530` 是对的
——走的是端口映射。

## 七、认证说明

**Milvus 不需要用户名密码。** 2.x 默认 `authorizationEnabled=false`，
`connections.connect(host="localhost", port=19530)` 直接就能连。
这跟 MySQL 完全不同，容易让人以为漏配了什么。

compose 里出现的两组凭据都跟 Python 客户端无关：

| 凭据 | 属于谁 | 谁在用 |
|---|---|---|
| `minioadmin` / `minioadmin` | MinIO | Milvus 内部访问对象存储 |
| `1234` | Redis | 缓存客户端 |
| `smart_yoyage` / `123456` | MySQL | `config.py` 里的业务库连接 |
| （无） | Milvus | 不需要 |

## 八、和 config.py 的对应关系

`SmartVoyage/config.py` 是唯一配置入口，与 compose 的对应：

```python
# MySQL —— 对应 compose 的 MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
self.host = 'localhost'
self.user = 'smart_yoyage'
self.password = '123456'
self.database = 'travel_rag'

# Milvus —— 对应 standalone 服务的 19530 端口映射
self.milvus_host = 'localhost'
self.milvus_port = 19530
self.tour_group_collection = 'tour_groups'
```

改了 compose 里的用户名、密码、库名、端口，**必须同步改 `config.py`**，
反之亦然。这两处不一致是最常见的"明明启动了却连不上"。

## 九、排查

| 现象 | 原因 | 处理 |
|---|---|---|
| mysql 容器反复重启 | 3306 被本机 MySQL 占用 | `net stop MySQL57` |
| `Fail connecting to server on localhost:19530` | Milvus 没起来或还没就绪 | `docker-compose ps` 看 standalone 是否 Up；等 60 秒 |
| standalone 起不来 | etcd 或 minio 挂了 | `docker-compose logs etcd minio` |
| `Access denied for user 'smart_yoyage'` | 容器是旧数据卷，没建这个用户 | `down` 后删 `volumes/mysql/` 重新 up |
| Attu 连不上 | 填了 `localhost:19530` | 改成 `standalone:19530` |
| 中文乱码 | 字符集不是 utf8mb4 | 导入导出都加 `--default-character-set=utf8mb4` |
| `Exited (255)` | 宿主机或 Docker 重启导致 | `docker-compose up -d` 重新拉起 |

看具体错误优先用 `docker-compose logs <服务名>`，比猜快得多。
