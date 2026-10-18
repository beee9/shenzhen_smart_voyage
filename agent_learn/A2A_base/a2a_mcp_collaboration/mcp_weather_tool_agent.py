import uvicorn
from python_a2a.mcp import FastMCP, create_fastapi_app

mcp = FastMCP(name="WeatherTool")

@mcp.tool(name="get_weather", description="获取城市天气")
def get_weather(city: str) -> str:
    print(f"[MCP 工具 Agent 日志] 收到工具调用，查询城市: {city}")
    if city == "北京":
        return "北京今天阳光明媚，29°C"
    return f"找不到 {city} 的天气"

if __name__ == "__main__":
    app = create_fastapi_app(mcp)
    print("[MCP 工具 Agent] 已启动，在 http://127.0.0.1:6005")
    uvicorn.run(app, host="127.0.0.1", port=6005)