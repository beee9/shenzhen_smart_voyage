import asyncio
import logging
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# 定义服务器地址
server_url = "http://127.0.0.1:8001/mcp"

# 定义mcp客户端
mcp_client = None

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,  # 提高日志级别以捕获更多信息
    format='[客户端] %(asctime)s - %(levelname)s - %(message)s'
)

async def main():
    global mcp_client
    logging.info(f"准备连接到 Streamable-HTTP 服务器: {server_url}")
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client(server_url) as (read, write, _):
            logging.info("连接已成功建立！")
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    logging.info("会话初始化成功，可以开始调用工具。")
                    # 动态创建一个临时类 MCPClientHolder，把 session 放进去。这样就可以在函数外部通过 mcp_client.session 调用 MCP 工具
                    mcp_client = type("MCPClientHolder", (), {"session": session})()

                    # 从 session 自动获取 MCP server 提供的工具列表。
                    tools = await load_mcp_tools(session)
                    # print(f"tools-->{tools}")

                    # 调用远程工具
                    logging.info("--> 正在调用工具: query_high_frequency_question")
                    response = await session.call_tool("query_high_frequency_question", {})
                    print(f"response-->{response}")
                    logging.info(f"<-- 收到响应: {response}")

                    print("-" * 30)

                    logging.info("--> 正在调用工具: get_weather")
                    response = await session.call_tool("get_weather", {})
                    print(f"response-->{response}")
                    logging.info(f"<-- 收到响应: {response}")
                except Exception as e:
                    logging.error(f"调用工具时发生错误: {e}", exc_info=True)
                    raise
    except Exception as e:
        logging.error(f"连接或会话初始化时发生错误: {e}", exc_info=True)
        logging.error("请确认服务端脚本已启动并运行在 http://127.0.0.1:8001/mcp")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"客户端运行失败: {e}", exc_info=True)