import asyncio
from python_a2a import A2AClient

async def main():
    # 创建客户端
    agent_client = A2AClient("http://127.0.0.1:8005")
    print("[主客户端日志] 准备向天气 Agent 发送任务...")

    # 发起 A2A 调用
    query = "请帮我查一下北京的天气"
    #ask 可以从Task对象中解析出来artifacts 中的值
    result = agent_client.ask(query)
    print(f"[主客户端日志] 收到最终结果: '{result}'")

if __name__ == "__main__":
    # 请确保 mcp_weather_tool_agent.py 和 a2a_weather_agent.py 正在运行...
    asyncio.run(main())