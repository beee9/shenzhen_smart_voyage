from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState

# 定义代理卡片
weather_card = AgentCard(
    name="WeatherAgentServer",
    description="天气查询代理",
    url="http://127.0.0.1:5011",
    skills=[AgentSkill(name="query_weather", description="查询城市天气")]
)

# 模拟的天气数据，实际可来自 MCP 模块或第三方天气 API
WEATHER_DATA = {
    "北京": "晴，18~26℃，东南风3级，空气质量良",
    "上海": "多云转小雨，21~28℃，东风2级，注意带伞",
    "深圳": "雷阵雨，26~32℃，南风4级，湿度较大",
    "广州": "阴，25~31℃，微风，体感闷热",
}

# 自定义 A2AServer 子类
class WeatherServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=weather_card)

    def handle_task(self, task):
        print("收到A2A任务的task:=>", task)
        # 默认写法：获取任务内容
        query = (task.message or {}).get("content", {}).get("text", "")

        # 从提问中匹配城市
        city = next((c for c in WEATHER_DATA if c in query), None)
        if city:
            weather_result = f"{city}今天的天气：{WEATHER_DATA[city]}"
        else:
            weather_result = f"暂未收录该城市的天气，目前支持：{'、'.join(WEATHER_DATA)}"

        # task中添加 产物artifacts 和更新status
        task.artifacts = [{"parts": [{"type": "text", "text": weather_result}]}]
        task.status = TaskStatus(state=TaskState.COMPLETED)
        print(f"[{self.agent_card.name} 日志] 任务处理完毕")
        print(f"[{self.agent_card.name} 日志] 输出结果task: {task}")
        print(f"[{self.agent_card.name} 日志] 输出结果task.artifacts: {task.artifacts}")
        return task

# 启动服务器
if __name__ == "__main__":
    server = WeatherServer()
    print(f"[{server.agent_card.name}] 启动成功，服务地址: {server.agent_card.url}")
    run_server(server, host="127.0.0.1", port=5011, debug=True)
