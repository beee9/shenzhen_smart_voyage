import asyncio

from SmartVoyage import memory, chat_service
from SmartVoyage.create_logger import logger

import asyncio
import atexit
import os
import re
import socket
import subprocess
import sys
import time

from SmartVoyage.chat_service import ChatService
from SmartVoyage.config import project_root
from SmartVoyage.create_logger import logger

# 本机服务之间的调用一律不走系统代理。
# 开着系统代理（如 Clash 的 7890）时，httpx 会把 127.0.0.1 也发给代理，代理转发不了
# 回环地址就返回 502 Bad Gateway。httpx 读注册表的 ProxyServer，却不认 ProxyOverride
# 里的 `127.*` / `<local>` 绕过规则，所以必须显式排除。
#
# 代码层面已经在各 httpx 客户端上设了 trust_env=False（见 utils/http_client.py），
# 这里的环境变量是兜底，覆盖那些改不到的地方 —— 主要是 python_a2a 库内部的 requests
# 调用。_spawn() 的 Popen 没传 env=，所以 6 个子进程都会继承到这两个变量。
#
# 大小写都设：httpx 只认小写 no_proxy，requests 两种都认。
# 用 setdefault 避免覆盖用户已有的配置。
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

# 全局状态，由 initialize_system() 填充
chat_service = None
memory = None

# 本次由 main.py 拉起的子进程，退出时统一回收（不含启动前已在运行的服务）
_procs = []

# 服务启动顺序：先起 MCP 工具服务器，再起依赖它们的 A2A 代理服务器
MCP_SERVICES = [
    ("ticket MCP", "SmartVoyage.mcp_server.mcp_ticket_server", 8001),
    ("weather MCP", "SmartVoyage.mcp_server.mcp_weather_server", 8002),
    ("trip MCP", "SmartVoyage.mcp_server.mcp_trip_server", 8003),
]

A2A_SERVICES = [
    ("weather A2A", "SmartVoyage.a2a_server.weather_server", 5005),
    ("ticket A2A", "SmartVoyage.a2a_server.ticket_server", 5006),
    ("trip A2A", "SmartVoyage.a2a_server.trip_server", 5007),
]

LOG_DIR = os.path.join(project_root, "SmartVoyage", "logs")


# ==================== 服务进程管理 ==================== #

def _port_open(port: int, timeout: float = 1.0) -> bool:
    """检测本机端口是否已有服务在监听"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout):
            return True
    except OSError:
        return False


def _wait_port(port: int, timeout: float = 40.0) -> bool:
    """轮询等待端口就绪，超时返回 False"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.5)
    return False


def _spawn(name: str, module: str, port: int):
    """
    以子进程方式启动一个服务模块。

    端口已被占用时视为服务已在运行，跳过启动（这样重复执行 main.py 不会撞端口，
    也不会误关别人已经起好的服务）。日志分文件写入 logs/，避免 6 个进程的输出
    糊在同一个终端里。
    """
    if _port_open(port):
        print(f"  [跳过] {name} (端口 {port} 已在运行)")
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{module.rsplit('.', 1)[-1]}.log")
    log_file = open(log_path, "a", encoding="utf-8")

    kwargs = {}
    if os.name == "nt":
        # Windows 下独立进程组，避免 Ctrl+C 直接打断子进程、绕过清理逻辑
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        cwd=os.path.abspath(project_root),
        stdout=log_file, stderr=subprocess.STDOUT,
        **kwargs
    )
    _procs.append((name, proc, log_file))

    if _wait_port(port):
        print(f"  [就绪] {name} (端口 {port})")
    else:
        # 启动失败不中断整体流程，其余服务仍可用
        print(f"  [警告] {name} 启动超时，请查看 {log_path}")
        logger.warning(f"{name} 启动超时，端口 {port} 未就绪")


def _kill_tree(proc):
    """
    结束进程及其所有子进程。

    Windows 上 uvicorn / run_server 会派生孙进程持有监听套接字，
    只 terminate 父进程会留下占用端口的孤儿进程，因此按进程树回收。
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _shutdown():
    """回收本次拉起的子进程"""
    if not _procs:
        return
    print("\n正在关闭服务进程...")
    for name, proc, log_file in _procs:
        if proc.poll() is None:
            _kill_tree(proc)
        try:
            log_file.close()
        except Exception:
            pass
    _procs.clear()


def initialize_system():
    """启动全部服务进程，并初始化 ChatService 与记忆"""
    global chat_service, memory

    atexit.register(_shutdown)

    print("正在启动 MCP 工具服务器...")
    for name, module, port in MCP_SERVICES:
        _spawn(name, module, port)

    print("正在启动 A2A 代理服务器...")
    for name, module, port in A2A_SERVICES:
        _spawn(name, module, port)

    print("正在初始化对话服务...")
    chat_service = ChatService()
    memory = chat_service.memory
    print("初始化完成。\n")
# ==================== 调试命令 ==================== #

def display_agent_cards():
    """打印所有子代理的 AgentCard 信息"""
    print("\n" + "=" * 60)
    print("子代理列表")
    print("=" * 60)

    for card in chat_service.get_agent_cards():
        status = "在线" if card["reachable"] else "不可达"
        print(f"\n[{status}] {card['name']}  {card['url']}")
        if card["description"]:
            print(f"  描述: {card['description']}")
        if not card["reachable"]:
            print(f"  错误: {card.get('error', '未知')}")
            continue
        print(f"  技能 ({len(card['skills'])} 个):")
        for skill in card["skills"]:
            print(f"    - {skill['name']}: {skill['description']}")
            if skill["examples"]:
                print(f"      示例: {' / '.join(skill['examples'][:3])}")
    print("\n" + "=" * 60)


def display_memory():
    """查看当前记忆状态"""
    state = chat_service.get_memory_state()

    print("\n" + "=" * 60)
    print("记忆状态")
    print("=" * 60)

    messages = state["short_term_messages"]
    print(f"\n短期对话 ({len(messages)} 条):")
    if messages:
        for msg in messages:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"].replace("\n", " ")
            if len(content) > 80:
                content = content[:80] + "..."
            print(f"  [{msg.get('timestamp', '')}] {role}: {content}")
    else:
        print("  (空)")

    profile = state["user_profile"]
    print(f"\n用户偏好 ({len(profile)} 项):")
    if profile:
        for key, value in profile.items():
            print(f"  {key}: {value}")
    else:
        print("  (无已知偏好)")

    task = state["current_task"]
    print("\n当前任务上下文:")
    print(f"  {task if task else '(空)'}")

    entities = state["entity_history"]
    print(f"\n历史查询实体 (共 {len(entities)} 条，显示最近 5 条):")
    if entities:
        for item in entities[-5:]:
            print(f"  [{item.get('timestamp', '')}] {item.get('type', '')}: {item.get('query', '')}")
    else:
        print("  (空)")
    print("\n" + "=" * 60)


def display_trace():
    """
    回放最近一次请求的链路。

    从 app.log 里倒着找最后一个 "===== 新请求" 标记，把该 trace id 的所有
    节点按顺序打出来。课堂上问完一句就敲 trace，能直接看到这次提问走了哪几层。
    """
    log_path = os.path.join(LOG_DIR, "app.log")
    if not os.path.exists(log_path):
        print("暂无日志文件。")
        return

    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # 定位最后一次请求的起始行
    start = None
    for i in range(len(lines) - 1, -1, -1):
        if "===== 新请求" in lines[i]:
            start = i
            break

    if start is None:
        print("还没有可回放的链路，先问一个问题试试。")
        return

    # 取出该次请求的 trace id，只显示属于它的节点
    match = re.search(r"\[trace ([0-9a-f]{8})\]", lines[start])
    tid = match.group(1) if match else None

    print("\n" + "=" * 60)
    print(f"最近一次请求的链路  (trace {tid})")
    print("=" * 60)
    for line in lines[start:]:
        if tid and f"[trace {tid}]" in line:
            # 剥掉 logger 前缀和 trace id，只留「① 节点名 | 详情」
            body = line.split(f"[trace {tid}]", 1)[-1].strip()
            print("  " + body)
    print("=" * 60)
    print("提示：子代理和 MCP 侧的详细日志见 logs/ 下对应服务的 .log 文件")


def process_user_input(user_input: str):
    """把用户输入分发给 ChatService 处理并打印回复"""
    print("\n处理中，请稍候...")
    try:
        # ChatService.chat 是协程，需要用 asyncio.run 驱动
        response = asyncio.run(chat_service.chat(user_input))
        print(f"\n助手: {response}")
    except KeyboardInterrupt:
        print("\n已取消本次查询。")
    except Exception as e:
        # 单次查询失败不退出交互循环
        logger.error(f"处理用户输入失败: {e}")
        print(f"\n处理失败: {e}\n请重试或换个说法。")


if __name__ == "__main__":
    initialize_system()
    print("基于A2A的SmartVoyage旅行智能助手")
    print("输入问题，按回车提交；")
    print("输入'quit'退出；输入'cards'查看代理卡片；输入'memory'查看记忆状态。")

    display_agent_cards()

    while True:
        user_input = input("\n请输入您的问题: ").strip()
        if user_input.lower() == 'quit':
            print("感谢使用SmartVoyage！再见！")
            break
        elif user_input.lower() == 'cards':
            display_agent_cards()
        elif user_input.lower() == 'memory':
            display_memory()
        elif user_input.lower() == 'clear':
            memory.clear()
            print("记忆已清空。")
        elif user_input:
            process_user_input(user_input)