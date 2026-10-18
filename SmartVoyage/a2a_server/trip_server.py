import json
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_tool_calling_agent, AgentExecutor

from SmartVoyage.config import Config
from SmartVoyage.create_logger import logger
from SmartVoyage.utils.http_client import (
    no_proxy_async_client,
    no_proxy_mcp_client,
    no_proxy_sync_client,
)
from datetime import datetime
import pytz

conf = Config()

# http_client / http_async_client 固定直连，不读系统代理（详见 utils/http_client.py）
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=conf.temperature,
    http_client=no_proxy_sync_client(),
    http_async_client=no_proxy_async_client()
)

# MCP 服务器运行在 8003 端口
MCP_URL = "http://127.0.0.1:8003/mcp"

#定义可以更具用户问题选择工具执行任务的普通方法
async def query_trip(conversation: str) -> dict:
    """通过 LangChain Agent + MCP Tools 执行行程查询或预订"""
    try:
        # httpx_client_factory 必传：默认工厂会读系统代理，把 127.0.0.1 也发给代理，
        # 代理转发不了回环地址就返回 502（详见 utils/http_client.py）
        async with streamablehttp_client(
            MCP_URL, httpx_client_factory=no_proxy_mcp_client
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await load_mcp_tools(session)

                prompt = ChatPromptTemplate.from_messages([
                    ("system", """你是一个行程管家助手，能够调用工具来完成租车查询/预定、旅游团查询/报名、保险查询/购买。
你需要仔细分析用户的问题，从问题中提取工具需要的参数，然后调用对应的工具。
如果用户提供的信息不足以提取到调用工具所有必要参数，则向用户追问。不能自己编造参数。

注意：
- query_tour_group 使用语义搜索，query_text 参数是用户的自然语言查询描述。
- query_car_rental 需要取车城市、还车城市、日期。
- query_insurance 可以直接调用，不传 insurance_type 会返回所有保险。

当前日期是{current_date}。"""),
                    ("human", "{input}"),
                    ("placeholder", "{agent_scratchpad}"),
                ])

                agent = create_tool_calling_agent(llm, tools, prompt)
                agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

                current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')

                response = await agent_executor.ainvoke({
                    "input": conversation,
                    "current_date": current_date
                })

                return {"status": "success", "message": response["output"]}

    except ExceptionGroup as eg:
        first_exc = eg.exceptions[0] if eg.exceptions else eg
        logger.error(f"行程 MCP 查询出错：{first_exc}")
        return {"status": "error", "message": f"行程 MCP 查询出错：{first_exc}"}
    except BaseException as e:
        logger.error(f"行程 MCP 查询出错：{str(e)}")
        return {"status": "error", "message": f"行程 MCP 查询出错：{str(e)}"}


agent_card = AgentCard(
    name="TripAssistant",
    description="基于 LangChain 提供行程管家服务的统一助手，支持租车、旅游团、保险的查询与预订",
    url="http://localhost:5007",
    version="1.0.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(name="query car rental", description="查询租车信息", examples=["租车 北京 上海 2025-08-01"]),
        AgentSkill(name="query tour group", description="通过语义搜索查询旅游团信息", examples=["想看雪山的地方"]),
        AgentSkill(name="query insurance", description="查询旅行保险产品", examples=["旅行保险"]),
        AgentSkill(name="order car rental", description="预订租车服务", examples=["预订租车 2025-08-01 SUV 1辆"]),
        AgentSkill(name="order tour group", description="报名旅游团", examples=["报名丽江三日游 2人"]),
        AgentSkill(name="order insurance", description="购买旅行保险", examples=["购买综合型保险"])
    ]
)

class TripQueryServer(A2AServer):
    """行程管家 A2A 服务器"""

    def __init__(self):
        super().__init__(agent_card=agent_card)

    def handle_task(self, task):
        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"用户查询: {conversation}")

        try:
            trip_result = asyncio.run(query_trip(conversation))
            logger.info(f"MCP 查询返回: {trip_result}")

            if trip_result.get("status") == "success":
                result_text = trip_result.get("message", "")
                if "请提供" in result_text or "请确认" in result_text:
                    task.status = TaskStatus(
                        state=TaskState.INPUT_REQUIRED,
                        message={"role": "agent", "content": {"text": result_text}}
                    )
                else:
                    task.artifacts = [{"parts": [{"type": "text", "text": result_text}]}]
                    task.status = TaskStatus(state=TaskState.COMPLETED)

            elif trip_result.get("status") == "error":
                task.status = TaskStatus(
                    state=TaskState.FAILED,
                    message={"role": "agent", "content": {"text": trip_result.get("message", "查询失败，请重试。")}}
                )
            else:
                task.status = TaskStatus(
                    state=TaskState.FAILED,
                    message={"role": "agent", "content": {"text": "查询失败，请重试或提供更多细节。"}}
                )

            return task

        except Exception as e:
            logger.error(f"查询失败: {str(e)}")
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"text": f"查询失败: {str(e)} 请重试。"}}
            )
            return task

if __name__ == "__main__":
    trip_server = TripQueryServer()
    print("\n=== 服务器信息 ===")
    print(f"名称: {trip_server.agent_card.name}")
    print(f"描述: {trip_server.agent_card.description}")
    print("\n技能:")
    for skill in trip_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    run_server(trip_server, host="127.0.0.1", port=5007)