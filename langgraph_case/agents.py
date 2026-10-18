"""两个专家节点，对应 a2a_case 里的两个 A2AServer。

原案例里它们是独立进程（weather_agent.py:5008 / ticket_agent.py:5009），
这里变成图中的两个普通函数节点。函数签名统一为：

    def node(state: TravelState) -> dict     # 返回要更新到 state 的字段

LangGraph 会把返回的字典合并进全局 state，不用手动改 state。
"""

from .state import STATUS_COMPLETED, TravelState, make_artifact

# 模拟的天气数据，真实项目里这里应该换成 MCP 工具或第三方 API
WEATHER_DATA = {
    "北京": {"温度": 30, "天气": "晴天"},
    "上海": {"温度": 28, "天气": "小雨"},
    "深圳": {"温度": 32, "天气": "雷阵雨"},
}

NAME_WEATHER = "WeatherAgent"
NAME_TICKET = "TicketAgent"
NAME_FALLBACK = "Fallback"


def weather_agent(state: TravelState) -> dict:
    """天气专家节点，对应 weather_agent.py 的 handle_task。"""
    query = state["query"]
    print(f"[{NAME_WEATHER} 日志] 收到任务: '{query}'")

    city = next((c for c in WEATHER_DATA if c in query), None)
    if city:
        result = f"{city}：{WEATHER_DATA[city]}"
        print(f"[{NAME_WEATHER} 日志] 查询成功: {result}")
    else:
        result = f"暂未收录该城市，目前支持：{'、'.join(WEATHER_DATA)}"
        print(f"[{NAME_WEATHER} 日志] 未匹配到城市")

    return {
        "artifacts": make_artifact(result),
        "status": STATUS_COMPLETED,
        "logs": [f"{NAME_WEATHER} 处理完毕 -> {result}"],
    }


def ticket_agent(state: TravelState) -> dict:
    """票务专家节点，对应 ticket_agent.py 的 handle_task。"""
    query = state["query"]
    print(f"[{NAME_TICKET} 日志] 收到任务: '{query}'")

    if "上海" in query and "北京" in query:
        result = "上海到北京的火车票已经预订成功！ G1001, 10车1A"
    else:
        result = "请输入明确的出发地和目的地。"

    print(f"[{NAME_TICKET} 日志] 返回结果: {result}")
    return {
        "artifacts": make_artifact(result),
        "status": STATUS_COMPLETED,
        "logs": [f"{NAME_TICKET} 处理完毕 -> {result}"],
    }


def fallback_agent(state: TravelState) -> dict:
    """兜底节点。

    原案例里路由不到 agent 就直接跳过，什么也不返回；
    图里必须有明确的出口，所以补一个兜底节点，保证任何输入都有响应。
    """
    print(f"[{NAME_FALLBACK} 日志] 无法处理: '{state['query']}'")
    result = "暂时无法处理这个请求，目前只支持天气查询和火车票预订。"
    return {
        "artifacts": make_artifact(result),
        "status": STATUS_COMPLETED,
        "logs": [f"{NAME_FALLBACK} 兜底处理"],
    }
