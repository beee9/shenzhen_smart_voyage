# A2A + MCP 协作示例说明

这个文件夹演示一件事:**一个 Agent 怎么一边对外提供 A2A 服务,一边在内部调用 MCP 工具干活。**

三个文件,三个角色:

| 文件 | 角色 | 端口 | 协议身份 |
|------|------|------|----------|
| `mcp_weather_tool_agent.py` | 最底层的"工具" | 6005 | MCP 服务端 |
| `a2a_weather_agent.py` | 中间的"办事员" | 8005 | A2A 服务端 + MCP 客户端 |
| `main_client.py` | 最上层的"提需求的人" | 无 | A2A 客户端 |

## 整体调用链

```
  main_client.py                a2a_weather_agent.py           mcp_weather_tool_agent.py
  (A2A 客户端)                   (A2A 服务端 + MCP 客户端)         (MCP 服务端 / 工具)
       |                                  |                                |
       |  ① ask("请帮我查一下北京的天气")   |                                |
       |--------------------------------->|                                |
       |         A2A 协议 :8005           |                                |
       |                                  | ② 判断: 文本里有"天气"           |
       |                                  |    → 需要调用工具               |
       |                                  |                                |
       |                                  | ③ call_tool("get_weather",     |
       |                                  |             city="北京")        |
       |                                  |------------------------------->|
       |                                  |        MCP 协议 :6005          |
       |                                  |                                | ④ 执行函数
       |                                  |                                |   查天气
       |                                  | ⑤ "北京今天阳光明媚,29°C"       |
       |                                  |<-------------------------------|
       |                                  |                                |
       |                                  | ⑥ 结果塞进 task.artifacts       |
       |                                  |    状态改成 COMPLETED          |
       |  ⑦ 返回 Task 对象                 |                                |
       |<---------------------------------|                                |
       |                                  |                                |
       | ⑧ ask() 自动从 artifacts          |                                |
       |    里取出文本并打印               |                                |
```

一句话总结:**客户端只认识 A2A,工具只认识 MCP,中间那个 Agent 负责翻译和转发。**

## 逐个文件说明

### 1. `mcp_weather_tool_agent.py` — 工具层

用 `FastMCP` 把一个普通 Python 函数变成可远程调用的工具。

```python
@mcp.tool(name="get_weather", description="获取城市天气")
def get_weather(city: str) -> str:
    ...
```

- `@mcp.tool` 装饰器 = 对外注册一个工具,别人可以按名字 `get_weather` 调用它。
- `create_fastapi_app(mcp)` 把 MCP 包成一个 FastAPI 应用,再用 uvicorn 跑在 6005 端口。
- 它自己不做任何判断,只负责"给我城市名,我还你天气字符串"。目前只有北京有数据,其他城市返回找不到。

### 2. `a2a_weather_agent.py` — 中间 Agent(整个示例的核心)

它有两个身份,同时存在:

```
        ┌─────────────────────────────────────────┐
        │        WeatherServer (端口 8005)         │
        │                                         │
  A2A   │  身份一: A2AServer                       │
  请求 ─┼─→ handle_task(task)  ← 接活的入口        │
        │        │                                │
        │        ↓ 决策                            │
        │  身份二: MCPClient("...:6005")           │   MCP
        │      self.mcp_client.call_tool(...) ─────┼──→ 请求
        │                                         │
        └─────────────────────────────────────────┘
```

`handle_task` 的四步:

1. **取输入** — `task.message["content"]["text"]`,拿到用户原话。
2. **做决策** — 文本里包含"天气"就走工具分支,否则直接返回"无法理解的任务"。城市这里是写死的 `"北京"`(示例简化,真实项目应该用 LLM 或正则抽取)。
3. **调工具** — `asyncio.run(self.mcp_client.call_tool("get_weather", city=city))`。因为 `handle_task` 是同步方法,而 MCP 调用是异步的,所以用 `asyncio.run` 把异步跑完再往下走。整段套了 try/except,工具挂了就把错误信息当结果返回,不让服务崩掉。
4. **交作业** — 结果写进 `task.artifacts`,状态置为 `TaskState.COMPLETED`,`return task`。

这里有个要点:**A2A 里"计算产物"统一放 `artifacts`,不是放 message。** 格式固定:

```python
task.artifacts = [{"parts": [{"type": "text", "text": 结果字符串}]}]
```

### 3. `main_client.py` — 发起方

```python
agent_client = A2AClient("http://127.0.0.1:8005")
result = agent_client.ask("请帮我查一下北京的天气")
```

`ask()` 做了三件事:发任务 → 等 Task 返回 → 自动从 `artifacts` 里把文本抽出来。所以 `result` 直接就是 `"北京今天阳光明媚,29°C"`,不用自己解析嵌套结构。

注意 `main()` 声明了 `async`,但 `ask()` 其实是同步的,这里的 `asyncio.run` 只是包了个壳,不影响运行。

## 怎么跑

按顺序开三个终端,**必须先起下游再起上游**,否则调用会连不上:

```bash
# 终端 1:先起 MCP 工具
python agent_learn/A2A_base/a2a_mcp_collaboration/mcp_weather_tool_agent.py

# 终端 2:再起 A2A Agent
python agent_learn/A2A_base/a2a_mcp_collaboration/a2a_weather_agent.py

# 终端 3:最后跑客户端
python agent_learn/A2A_base/a2a_mcp_collaboration/main_client.py
```

预期输出(终端 3):

```
[主客户端日志] 准备向天气 Agent 发送任务...
[主客户端日志] 收到最终结果: '北京今天阳光明媚,29°C'
```

同时终端 2 会打印决策日志,终端 1 会打印 `收到工具调用,查询城市: 北京`。三个终端的日志连起来看,就是上面那张时序图。

## 为什么要分成两层

刚接触时容易觉得"直接让客户端调 MCP 工具不就行了",分层的意义在于:

- **MCP 管工具,A2A 管协作。** MCP 工具是无脑执行的能力单元;A2A Agent 才有"理解意图、选哪个工具、怎么组合"的决策能力。
- **可替换。** 换天气数据源只改 6005 那个文件,上层完全不动。
- **可组合。** 中间 Agent 可以挂多个 MCP 工具,也可以再作为 MCP/A2A 客户端去调别的 Agent,链路可以一直往下接。

## 示例的简化之处

练手代码,以下几点真实项目里需要补:

- 城市名写死为"北京",没有做真正的实体抽取。
- 只有"天气"这一个关键词判断,没有用 LLM 做意图识别。
- MCP 地址、端口硬编码在代码里,应该走配置。
- 两个服务都没有鉴权,只绑 `127.0.0.1`,仅供本机学习使用。
