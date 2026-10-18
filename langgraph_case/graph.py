"""把节点组装成图。

图的形状：

              START
                |
                v
            [ router ]          ← LLM 判断意图
                |
        条件边 route_decide
        /       |       \
       v        v        v
 [weather]  [ticket]  [fallback]
       \        |        /
        \       |       /
         v      v      v
                END
"""

from langgraph.graph import END, START, StateGraph

from .agents import (
    NAME_FALLBACK,
    NAME_TICKET,
    NAME_WEATHER,
    fallback_agent,
    ticket_agent,
    weather_agent,
)
from .router import router_node
from .state import TravelState

# 节点名（图内部标识）
NODE_ROUTER = "router"
NODE_WEATHER = "weather_agent"
NODE_TICKET = "ticket_agent"
NODE_FALLBACK = "fallback_agent"

# 路由器输出的 agent_name -> 图节点名
_ROUTE_TABLE = {
    NAME_WEATHER: NODE_WEATHER,
    NAME_TICKET: NODE_TICKET,
    NAME_FALLBACK: NODE_FALLBACK,
}


def route_decide(state: TravelState) -> str:
    """条件边的判断函数：读 state 决定下一个节点。

    只做"读状态 -> 返回节点名"，不修改 state。
    这是 LangGraph 条件边的约定。
    """
    return _ROUTE_TABLE.get(state.get("agent_name", ""), NODE_FALLBACK)


def build_graph():
    """构建并编译图，返回可执行的 app。"""
    builder = StateGraph(TravelState)

    # 1. 注册节点
    builder.add_node(NODE_ROUTER, router_node)
    builder.add_node(NODE_WEATHER, weather_agent)
    builder.add_node(NODE_TICKET, ticket_agent)
    builder.add_node(NODE_FALLBACK, fallback_agent)

    # 2. 入口：START -> router
    builder.add_edge(START, NODE_ROUTER)

    # 3. 条件边：router 之后按 route_decide 的返回值分叉
    builder.add_conditional_edges(
        NODE_ROUTER,
        route_decide,
        # 这个映射表只是给可视化用的，键值同名表示直接对应
        {
            NODE_WEATHER: NODE_WEATHER,
            NODE_TICKET: NODE_TICKET,
            NODE_FALLBACK: NODE_FALLBACK,
        },
    )

    # 4. 三个专家节点执行完都直接结束
    for node in (NODE_WEATHER, NODE_TICKET, NODE_FALLBACK):
        builder.add_edge(node, END)

    return builder.compile()
