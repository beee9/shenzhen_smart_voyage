"""路由节点，替代原案例的 router_A2Aagent_Server.py + AIAgentRouter。

原案例需要单独起一个 5555 端口的 LLM 服务，再由 AIAgentRouter 通过 A2A
协议去问它"该派给谁"。在 LangGraph 里，LLM 直接在进程内调用，
少了一个服务和一次网络往返。

路由结果不直接决定走向，而是写进 state["agent_name"]，
再由 graph.py 里的条件边读取它来决定下一跳。这样"决策"和"跳转"分离，
决策逻辑可以单独测试。
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent_learn.config import Config

from .agents import NAME_FALLBACK, NAME_TICKET, NAME_WEATHER
from .state import TravelState

# 能力清单，等价于 AgentNetwork 里注册的 AgentCard 集合
AGENT_REGISTRY = {
    NAME_WEATHER: "查询指定城市的天气情况，比如温度、阴晴雨雪",
    NAME_TICKET: "预订火车票，需要出发地和目的地",
}

ROUTE_PROMPT = """你是一个任务路由器。根据用户的问题，从下面的候选 Agent 中选出最合适的一个。

候选 Agent：
{registry}

只输出 JSON，不要输出任何解释或代码块标记，格式如下：
{{"agent_name": "候选名称或 {fallback}", "confidence": 0.0到1.0之间的小数}}

如果没有任何 Agent 能处理，agent_name 填 "{fallback}"。"""


def _build_llm() -> ChatOpenAI:
    conf = Config()
    return ChatOpenAI(
        base_url=conf.base_url,
        api_key=conf.api_key,
        model=conf.model_name,
        temperature=0,
    )


def _keyword_route(query: str) -> tuple[str, float]:
    """关键词兜底路由。

    LLM 不可用（没配 key、网络不通、返回格式坏了）时退到这里，
    保证图仍然能跑通。置信度给 0.6 以示区分。
    """
    if "天气" in query:
        return NAME_WEATHER, 0.6
    if any(k in query for k in ("票", "预订", "订票")):
        return NAME_TICKET, 0.6
    return NAME_FALLBACK, 0.0


def _parse_route(raw: str) -> tuple[str, float] | None:
    """解析 LLM 返回的 JSON。解析失败或名字不在清单里就返回 None。"""
    text = raw.strip()
    # 模型有时会裹一层 ```json ... ```，这里做个清理
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None

    name = data.get("agent_name")
    if name not in AGENT_REGISTRY and name != NAME_FALLBACK:
        return None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return name, confidence


def router_node(state: TravelState) -> dict:
    """图的第一个节点：决定这个问题交给哪个专家。"""
    query = state["query"]
    print(f"[Router 日志] 用户查询: '{query}'")

    registry_text = "\n".join(f"- {n}: {d}" for n, d in AGENT_REGISTRY.items())
    prompt = ROUTE_PROMPT.format(registry=registry_text, fallback=NAME_FALLBACK)

    try:
        llm = _build_llm()
        reply = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=query),
        ])
        parsed = _parse_route(reply.content)
        if parsed is None:
            print(f"[Router 日志] LLM 返回无法解析，退到关键词路由。原文: {reply.content!r}")
            agent_name, confidence = _keyword_route(query)
            source = "关键词兜底"
        else:
            agent_name, confidence = parsed
            source = "LLM"
    except Exception as exc:  # 网络/鉴权等问题都走兜底，不让图崩掉
        print(f"[Router 日志] LLM 调用失败({exc.__class__.__name__})，退到关键词路由")
        agent_name, confidence = _keyword_route(query)
        source = "关键词兜底"

    print(f"[Router 日志] 路由结果: {agent_name} (置信度 {confidence}, 来源 {source})")
    return {
        "agent_name": agent_name,
        "confidence": confidence,
        "logs": [f"Router[{source}] -> {agent_name} ({confidence})"],
    }
