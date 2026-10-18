# https://www.mcpworld.com/zh/detail/QAnqmCLZLfyYNp3wpWXeMD
# https://open.mcd.cn/mcp
"""
麦当劳官方 MCP Server 探查脚本（streamable HTTP 传输）

两段式：
  1. 列出 server 暴露的全部工具及入参 schema
  2. 把只读工具喂给 qwen-plus，做成可对话的 Agent

对照 ../stdio/ 下的本地 stdio 示例，这里演示远程 HTTP MCP 的接法。
"""
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../../.."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asyncio

from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI

from agent_learn.config import Config

conf = Config()

# todo: 第一步：配置 MCP server 连接信息
MCD_MCP_URL = "https://mcp.mcd.cn/mcp-servers/mcd-mcp"
MCD_MCP_TOKEN = "PabRSQ0QmqtbAgceOPkdGMoJgP3DsePq"

# 写操作工具：会真的下单 / 真的往账户绑券，Agent 模式下剔除，避免模型误触发
WRITE_TOOLS = {
    "create-order",         # 创建麦当劳订单
    "mall-create-order",    # 创建商城订单
    "party-order-create",   # 创建派对订单
    "auto-bind-coupons",    # 自动绑定优惠券到账户
}

# langchain_mcp_adapters 的连接配置，等价于 mcp.json 里的 mcpServers 那一段
MCD_CONNECTION = {
    "mcd-mcp": {
        "transport": "streamable_http",
        "url": MCD_MCP_URL,
        "headers": {"Authorization": f"Bearer {MCD_MCP_TOKEN}"},
    }
}


# todo: 第二步：列出 server 的全部工具
async def print_tools(session):
    """调用 MCP 协议的 tools/list，打印工具名、描述和入参 schema"""
    result = await session.list_tools()
    tools = result.tools

    print("=" * 70)
    print(f"麦当劳 MCP Server 工具清单（共 {len(tools)} 个）")
    print("=" * 70)

    for i, tool in enumerate(tools, 1):
        flag = "  [写操作]" if tool.name in WRITE_TOOLS else ""
        # description 原文是多行的（含 When 使用场景），这里只取首行做概览
        desc = (tool.description or "").strip().splitlines()
        summary = desc[0] if desc else "(无描述)"
        print(f"\n{i}. {tool.name}{flag}")
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

    write_cnt = sum(1 for t in tools if t.name in WRITE_TOOLS)
    print("\n" + "=" * 70)
    print(f"合计 {len(tools)} 个工具：只读 {len(tools) - write_cnt} 个，写操作 {write_cnt} 个")
    print("=" * 70)


# todo: 第三步：把只读工具接给模型，做成可对话的 Agent
async def run_agent(session):
    """load_mcp_tools 把 MCP 工具转成 LangChain 工具，再交给 tool calling agent"""
    all_tools = await load_mcp_tools(session)
    # 只保留只读工具，防止模型误触发真实下单 / 绑券
    tools = [t for t in all_tools if t.name not in WRITE_TOOLS]
    print(f"\nAgent 已加载 {len(tools)} 个只读工具"
          f"（已剔除 {len(all_tools) - len(tools)} 个写操作工具）")

    llm = ChatOpenAI(base_url=conf.base_url,
                     api_key=conf.api_key,
                     model=conf.model_name,
                     temperature=0.1)

    prompt_template = ChatPromptTemplate.from_messages([
        ("system",
         "你是麦当劳中国的智能助手，可以调用工具查询门店、菜单、优惠券、活动和订单信息。"
         "请先调用工具获取真实数据，再基于工具返回结果回答，不要凭记忆编造门店、价格或优惠信息。"
         "你只负责查询，不要尝试为用户下单或修改账户数据。"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt_template)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    print("\nMCP 客户端已就绪，输入 'quit' 退出")
    print("示例提问：现在几点 / 深圳附近有什么麦当劳 / 我有哪些优惠券 / 这个月有什么活动")
    while True:
        query = input("\nQuery: ").strip()
        if query.lower() == "quit":
            break
        if not query:
            continue
        try:
            response = await agent_executor.ainvoke({"input": query})
            print(f"\n最终回答：{response['output']}")
        except Exception as e:
            # 打印真实异常，方便定位是 token 失效、参数缺失还是模型侧问题
            print(f"调用失败: {repr(e)}")


async def main():
    # 一个连接复用给两段：先列清单，再进 Agent 交互
    client = MultiServerMCPClient(MCD_CONNECTION)
    async with client.session("mcd-mcp") as session:
        await print_tools(session)

        if not conf.api_key:
            print("\n未检测到环境变量 DASHSCOPE_API_KEY，跳过 Agent 交互（仅列出工具清单）。")
            return
        await run_agent(session)


if __name__ == "__main__":
    asyncio.run(main())
