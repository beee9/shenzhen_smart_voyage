# langgraph_case vs a2a_case 实现对比

两份代码解决的是同一个问题：**用户提一个旅行相关的问题，系统判断该交给哪个专家处理，然后返回结果。**

- `agent_learn/A2A_base/a2a_case/` —— 用 python-a2a 框架，多进程 + HTTP 协议
- `langgraph_case/` —— 用 LangGraph，单进程 + 状态图

下面按"跑起来的样子"、"代码结构"、"各自的坑"三层来对照。

---

## 1. 跑起来的样子

### a2a_case：要开四个终端

```
终端 1  python agent_learn/A2A_base/a2a_case/weather_agent.py           # 127.0.0.1:5008
终端 2  python agent_learn/A2A_base/a2a_case/ticket_agent.py            # 127.0.0.1:5009
终端 3  python agent_learn/A2A_base/a2a_case/router_A2Aagent_Server.py  # 127.0.0.1:5555
终端 4  python agent_learn/A2A_base/a2a_case/main.py                    # 主控
```

主控发一次请求，实际发生 2 次 HTTP 往返：先问 5555 的 LLM 服务"派给谁"，
再把 Task 打成 JSON 发给 5008 或 5009。前三个服务少起一个，主控就报
`无法连接到代理`。

### langgraph_case：一条命令

```
cd shenzhen_smart_voyage
python -m langgraph_case.main
```

LLM 在进程内直接调用，专家是普通函数调用，零网络往返。

---

## 2. 代码结构对照

| 概念 | a2a_case | langgraph_case |
|------|----------|----------------|
| 任务载体 | `Task` 对象，跨进程序列化成 JSON | `TravelState`（TypedDict），进程内传引用 |
| 能力注册 | `AgentNetwork.add(name, url)` + 各服务的 `AgentCard` | `router.py` 里的 `AGENT_REGISTRY` 字典 |
| 路由决策 | `AIAgentRouter` 走 A2A 协议问 5555 的 LLM | `router_node()` 直接 `llm.invoke()` |
| 专家实现 | `class WeatherAgentServer(A2AServer)` 的 `handle_task` | `def weather_agent(state) -> dict` |
| 跳转控制 | 主控 `if agent_name:` 后手动 `network.get_agent()` | `add_conditional_edges` + `route_decide()` |
| 结果格式 | `task.artifacts = [{"parts": [...]}]` | 同一格式，由 `make_artifact()` 生成 |
| 状态标记 | `TaskStatus(state=TaskState.COMPLETED)` | `status = "completed"` 字符串常量 |
| 执行轨迹 | 无，只能翻四个终端的 print | `state["logs"]`，`Annotated[list, operator.add]` 自动累加 |

artifacts 结构是故意保持一致的，方便两边对着看输出。

### 一个关键的结构差异：决策和跳转是否分离

a2a_case 的主控把两件事写在一起：

```python
agent_name, confidence = router.route_query(query)
if agent_name:
    agent_client = network.get_agent(agent_name)   # 决策结果直接拿来建连接
```

langgraph_case 把它拆成两步：`router_node` 只往 state 里写
`agent_name`，`route_decide` 再读 state 决定下一跳。

```python
def route_decide(state: TravelState) -> str:
    return _ROUTE_TABLE.get(state.get("agent_name", ""), NODE_FALLBACK)
```

好处是路由逻辑可以脱离图单独测（喂一个 dict 进去，断言返回的节点名），
而 a2a_case 想测路由就得先把 5555 起来。

---

## 3. 各自的优点

### a2a_case 的优点

**天然的服务边界。** 每个 Agent 是独立进程、独立端口、独立部署。天气服务
挂了不影响票务服务，可以单独重启、单独扩容、单独换语言实现。这是
langgraph_case 完全没有的能力——单进程里一个节点抛未捕获异常，整张图就停了。

**跨团队、跨语言协作。** `AgentCard` 是对外的能力契约，
别的团队只要认 A2A 协议就能接进来，不需要知道你用 Python 还是 Go：

```python
agent_card = AgentCard(
    name="WeatherAgentServer",
    description="一个天气预报查询的专家 Agent",
    url="http://127.0.0.1:5008",
    skills=[AgentSkill(name="query", description="接受天气查询查询", examples=["天气北京"])]
)
```

**动态发现。** `AgentNetwork` 运行时可以增删 Agent，
新上线一个专家不用改主控代码、不用重启。langgraph_case 加一个专家要改
`AGENT_REGISTRY`、加节点、加路由表项，然后重新编译图。

**协议是标准的。** A2A 是公开规范，`Task` / `Message` / `artifacts` /
`TaskState` 这套结构不是某个库的私有约定，换框架时概念能迁移。

### langgraph_case 的优点

**调试成本低一个数量级。** 单进程意味着断点能一路跟到底，
栈是完整的，print 全在一个终端里按顺序输出。a2a_case 排查一次
路由错误要在四个终端之间来回翻日志。

**显式的执行轨迹。** `logs` 字段用累加器收集全链路：

```python
logs: Annotated[list[str], operator.add]
```

每个节点 `return {"logs": [...]}` 都追加而不覆盖，最后一次性打出来：

```
1. Router[LLM] -> WeatherAgent (0.95)
2. WeatherAgent 处理完毕 -> 北京：{'温度': 30, '天气': '晴天'}
```

**图结构可见、可画。** `app.get_graph().draw_ascii()` 直接把拓扑打出来
（装了 grandalf 的话）。a2a_case 的调用关系散落在主控的 if-else 里，
只能靠读代码脑补。

**兜底路径是设计出来的，不是漏出来的。** 见下一节。

**没有序列化损耗。** state 在节点间传引用，不用把每个 Task 编码成 JSON 再解开。
单机场景下这是纯粹的开销节省。

---

## 4. a2a_case 里几个值得注意的实现问题

这些不是 A2A 协议的问题，是那份示例代码本身的。

### 4.1 artifacts 里塞了 dict，不是 str

`weather_agent.py:27`：

```python
weather_result = {"温度": 30, "天气": "晴天"}
task.artifacts = [{"parts": [{"type": "text", "text": weather_result}]}]
```

`"type": "text"` 却给了个 dict。JSON 层面能过（dict 可序列化），
但下游任何按 `str` 处理 `text` 的代码都会出问题。
langgraph_case 里统一走 `make_artifact(result)`，进去的必须是字符串。

### 4.2 裸 except 吞掉所有错误

`main.py:55`：

```python
except:
    print("[主控日志] 错误：无法连接到代理")
```

不带异常类型的 `except` 会连 `KeyboardInterrupt` 和 `SystemExit` 一起吃掉，
而且不管真实原因是什么（超时、404、JSON 解析失败、鉴权失败）都报同一句
"无法连接到代理"，等于把排查线索全丢了。

langgraph_case 的对应写法保留了异常类型：

```python
except Exception as exc:
    print(f"[Router 日志] LLM 调用失败({exc.__class__.__name__})，退到关键词路由")
```

### 4.3 路由不到就静默跳过

`main.py:35` 的 `if agent_name:` —— 假的话什么都不做，用户等半天没有任何回应。
langgraph_case 补了 `fallback_agent` 节点，因为图必须有明确出口，
这反而逼出了一个更完整的设计：任何输入都有响应。

### 4.4 没有 LLM 兜底

5555 服务一挂，`route_query` 就失败，整个流程终止。langgraph_case 有关键词兜底：

```python
def _keyword_route(query: str) -> tuple[str, float]:
    if "天气" in query:
        return NAME_WEATHER, 0.6
    if any(k in query for k in ("票", "预订", "订票")):
        return NAME_TICKET, 0.6
    return NAME_FALLBACK, 0.0
```

置信度给 0.6（LLM 正常时是 0.9+），从输出就能看出这次走的是降级路径。

### 4.5 `sleep(5)` 在 async 函数里

`main.py:52` 用的是 `time.sleep`，不是 `asyncio.sleep`。这会阻塞整个事件循环，
在 async 函数里属于典型错误。而且这个 sleep 本身看起来也没有必要——
`send_task_async` 已经 await 过了。

### 4.6 LLM 服务开了 streaming 却没人用

`router_A2Aagent_Server.py:15` 设了 `streaming=True`，
但 `AIAgentRouter.route_query` 要的是一次性的完整答案，流式在这里没有意义。

---

## 5. 怎么选

**选 A2A（多进程）的场景：**
- 多个团队各自维护自己的 Agent，需要独立发布
- Agent 之间要跨语言、跨机器
- 需要单独给某个 Agent 扩容（比如天气查询 QPS 特别高）
- 要接入外部组织的 Agent

**选 LangGraph（单进程状态图）的场景：**
- 一个团队维护整个流程
- 流程本身有复杂控制流：分支、循环、多轮、需要人工介入
- 需要 checkpoint / 断点续跑 / 时间旅行调试（LangGraph 内置，A2A 要自己实现）
- 单机能扛住负载

**实际项目里常常是两者叠加：** 用 LangGraph 编排一个 Agent 内部的思考流程，
再把整个图用 A2A 协议包装成一个服务对外提供能力。
两者不是替代关系，解决的是不同层面的问题——
LangGraph 管**一个 Agent 内部怎么想**，A2A 管**多个 Agent 之间怎么说话**。

---

## 6. 文件对照速查

| a2a_case | langgraph_case | 说明 |
|----------|----------------|------|
| `main.py` | `main.py` | 入口。原版要先起三个服务，新版直接跑 |
| `router_A2Aagent_Server.py` | `router.py` | 从"独立 LLM 服务"变成"进程内节点" |
| `weather_agent.py` | `agents.py` 的 `weather_agent()` | 从 A2AServer 变成普通函数 |
| `ticket_agent.py` | `agents.py` 的 `ticket_agent()` | 同上 |
| （无） | `agents.py` 的 `fallback_agent()` | 新增兜底 |
| （无，靠 AgentNetwork） | `graph.py` | 显式的拓扑定义 |
| `Task` 对象 | `state.py` 的 `TravelState` | 任务载体 |
