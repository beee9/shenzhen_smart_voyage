# https://github.com/drfccv/mcp-server-12306
"""
12306 火车票 MCP Server 调用脚本（streamable HTTP 传输）

和同目录 client_mcd.py 的对照：
  client_mcd.py    公网远程 MCP，HTTPS + Bearer token，有写操作要防
  client_12306.py  本地 Docker 起的 MCP，HTTP 无鉴权，7 个工具全是只读查询

前置：先把服务跑起来
    docker run -d -p 8080:8000 \
      -e SERVER_HOST=0.0.0.0 -e SERVER_PORT=8000 \
      --name mcp-server-12306 drfccv/mcp-server-12306:latest

    # 确认在跑（会返回工具清单和已加载的车站数）
    curl http://127.0.0.1:8080/

运行：
    python agent_learn/mcp_base/http/client_12306.py           # 工具清单 + 固定演示
    python agent_learn/mcp_base/http/client_12306.py --chat    # 工具清单 + 交互问答

------------------------------------------------------------------------
踩坑记录：本机代理会劫持 localhost，导致 502 Bad Gateway
------------------------------------------------------------------------
如果不做特殊处理，连本地服务会报：

    httpx.HTTPStatusError: Server error '502 Bad Gateway'
    for url 'http://127.0.0.1:8080/mcp'

现象很反直觉：curl 打同一个地址是 200，Python 却 502，
而且 docker logs 里根本看不到这条请求（说明请求没到容器）。

原因：本机开了 7890 端口的代理，httpx 默认 trust_env=True 会读系统代理设置，
把 127.0.0.1:8080 也发给代理，代理转发失败就返回 502。
curl 不读 WinINET 设置，所以一直正常。

排查时可以这样确认（注意别写成 >>> 开头，否则 PyCharm 会把这里当 doctest 跑）：
    python -c "import urllib.request; print(urllib.request.getproxies())"
    # 有输出 {'http': 'http://127.0.0.1:7890', ...} 就说明系统代理是开着的

解法见下面的 _no_proxy_httpx_client()。
"""
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../../.."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asyncio

import httpx
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI

from agent_learn.config import Config

conf = Config()

# todo: 第一步：配置 MCP server 连接信息
# 容器内监听 8000，宿主映射到 8080；端点固定是 /mcp
# 注意：这个服务只有 /mcp，没有 /sse（打 /sse 会 404），别按 SSE 传输接
MCP_12306_URL = "http://127.0.0.1:8080/mcp"


def _no_proxy_httpx_client(headers=None, timeout=None, auth=None):
    """构造绕开系统代理的 httpx 客户端。

    trust_env=False 是这里的关键：不读环境变量和系统代理设置，直连 127.0.0.1。
    删掉这个工厂就会踩文件头写的那个 502 坑。

    签名必须是 (headers, timeout, auth)，这是 mcp SDK 的
    McpHttpClientFactory 协议要求的，少一个参数会 TypeError。
    """
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        trust_env=False,
    )


# langchain_mcp_adapters 的连接配置，等价于 mcp.json 里的 mcpServers 那一段
MCP_12306_CONNECTION = {
    "mcp-12306": {
        "transport": "streamable_http",
        "url": MCP_12306_URL,
        "httpx_client_factory": _no_proxy_httpx_client,
    }
}

# 固定演示用的查询。故意把"明天"这种相对日期放进去，
# 观察模型会不会先调 get-current-time 拿真实日期再算。
DEMO_QUERIES = [
    # "现在几点了？今天是几号？",
    # "明天深圳到武汉有哪些高铁？挑几趟有票的说一下",
    "明天深圳到武汉的二等座票价大概多少",
    # "明天深圳到拉萨怎么中转比较合适",
]


# todo: 第二步：列出 server 的全部工具
async def print_tools(session):
    """调用 MCP 协议的 tools/list，打印工具名、描述和入参 schema。

    这个 server 的 7 个工具全是只读查询（查余票/票价/车站/中转/经停/时间），
    没有下单类接口，所以不像 client_mcd.py 那样需要维护写操作黑名单。
    """
    result = await session.list_tools()
    tools = result.tools

    print("=" * 70)
    print(f"12306 MCP Server 工具清单（共 {len(tools)} 个，全部只读）")
    print(f"服务地址: {MCP_12306_URL}")
    print("=" * 70)

    for i, tool in enumerate(tools, 1):
        # description 是多行的（含【智能筛选】等用法说明），概览只取首行
        desc = (tool.description or "").strip().splitlines()
        summary = desc[0] if desc else "(无描述)"
        print(f"\n{i}. {tool.name}")
        print(f"   说明: {summary}")

        schema = tool.inputSchema or {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not props:
            print("   入参: （无入参）")
            continue

        print("   入参:")
        for name, spec in props.items():
            mark = "必填" if name in required else "可选"
            ptype = spec.get("type", "any")
            pdesc = (spec.get("description") or "").strip().splitlines()
            pdesc = pdesc[0] if pdesc else ""
            print(f"     - {name} ({ptype}) {mark} — {pdesc}")

    print("\n" + "=" * 70)


# 提示词。重点是把日期和站名两件事按死，这俩最容易出错。
SYSTEM_PROMPT = (
    "你是 12306 火车票查询助手，可以调用工具查询余票、票价、车站、中转方案和车次经停站。"
    "请遵守以下规则：\n"
    "1. 日期：你不知道今天是几号。遇到「今天」「明天」「下周五」这类相对日期，"
    "必须先调用 get-current-time 拿到真实当前日期，再推算出具体日期。"
    "绝对不要凭记忆猜测当前日期。train_date 参数格式为 YYYY-MM-DD。\n"
    "2. 站名：站名支持中文、拼音、三字码。如果用户给的地名不确定或可能有多个站"
    "（比如「武汉」有武汉站/汉口站/武昌站），先调用 search-stations 确认。\n"
    "3. 查车次经停站时，get-train-route-stations 需要的是 train_no"
    "（形如 240000G1010A），不是车次号 G101。要先用 get-train-no-by-train-code 换。\n"
    "4. 余票、票价、时刻必须来自工具返回结果，绝对不要编造车次号、价格或余票数。"
    "工具没返回的信息就说没查到。\n"
    "5. 回答用中文，把车次、出发到达时间、历时、余票和价格整理清楚，不要堆原始 JSON。"
)


def _build_agent(tools):
    """把 MCP 工具接给模型，构造 tool calling agent。"""
    llm = ChatOpenAI(
        base_url=conf.base_url,
        api_key=conf.api_key,
        model=conf.model_name,
        temperature=0.1,
    )

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt_template)
    # verbose=True 能看到模型实际调了哪个工具、传了什么参数，教学场景很有用
    return AgentExecutor(agent=agent, tools=tools, verbose=True)


async def _ask(agent_executor, query: str) -> None:
    """问一次，打印结果。异常保留原始类型，方便定位问题。"""
    try:
        response = await agent_executor.ainvoke({"input": query})
        print(f"\n最终回答：{response['output']}")
    except Exception as e:
        # 不要吞成"解析有问题"这种没线索的提示：
        # repr 能区分是 key 失效、参数缺失、服务没起还是模型侧问题
        print(f"调用失败: {repr(e)}")


# todo: 第三步（默认）：跑固定演示查询，不需要人工输入
async def run_demo(session):
    tools = await load_mcp_tools(session)
    print(f"\nAgent 已加载 {len(tools)} 个工具，开始跑演示查询")
    print("（想自己提问用 --chat 参数）\n")

    agent_executor = _build_agent(tools)
    for i, query in enumerate(DEMO_QUERIES, 1):
        print("\n" + "=" * 70)
        print(f"演示 {i}/{len(DEMO_QUERIES)}: {query}")
        print("=" * 70)
        await _ask(agent_executor, query)

    print("\n演示跑完。")


# todo: 第四步（--chat）：交互问答
async def run_chat(session):
    tools = await load_mcp_tools(session)
    agent_executor = _build_agent(tools)

    print(f"\nAgent 已加载 {len(tools)} 个工具，输入 'quit' 退出")
    print("示例提问：")
    print("  明天深圳到广州的高铁还有票吗")
    print("  下周一北京到上海最快的车次是哪趟")
    print("  G101 途经哪些站")
    print("  深圳到乌鲁木齐怎么中转")
    while True:
        query = input("\nQuery: ").strip()
        if query.lower() == "quit":
            break
        if not query:
            continue
        await _ask(agent_executor, query)


async def main():
    use_chat = "--chat" in sys.argv

    # 一个连接复用给两段：先列清单，再执行
    client = MultiServerMCPClient(MCP_12306_CONNECTION)
    try:
        async with client.session("mcp-12306") as session:
            await print_tools(session)

            if not conf.api_key:
                print("\n未检测到环境变量 DASHSCOPE_API_KEY，"
                      "跳过 Agent（仅列出工具清单）。")
                print("上面能列出工具说明 MCP 连接本身是通的。")
                return

            if use_chat:
                await run_chat(session)
            else:
                await run_demo(session)
    except Exception as e:
        # 连不上的话给点排查方向，别让人对着 502 发呆
        print(f"\n连接 MCP server 失败: {repr(e)}")
        print("排查一下：")
        print("  1. 服务在跑吗:  docker ps --filter name=mcp-server-12306")
        print("  2. 端点通吗:    curl http://127.0.0.1:8080/")
        print("  3. 如果是 502，看文件头的代理说明"
              "（_no_proxy_httpx_client 是不是被改了）")


if __name__ == "__main__":
    asyncio.run(main())


