# A2A 还是 LangGraph：生产场景选型手册

配套 [COMPARISON.md](./COMPARISON.md)。那份文档讲两种实现的差异，这份只回答一个问题：
**具体到某个真实需求，我该用哪个。**

---

## 判断依据只有一条

选型不是技术能力问题，两边都能"跑通"。真正的分界线是：

> **这两段逻辑，需不需要各自独立发布、独立扩容、独立追责？**

- 需要 → 拆成 A2A 服务
- 不需要 → 放进一张 LangGraph 图

其他的一切（语言、协议、性能）都是这条线的推论。下面全是具体例子。

---

## 一、该用 A2A 的场景

### 场景 1：保险理赔——两个团队，两种语言，两种硬件

某财险公司的车险理赔流程：

```
用户上传事故照片
    ↓
[定损 Agent]   Python + PyTorch，跑在 A10 GPU 机器上，识别车损部位和程度
    ↓
[核价 Agent]   Java + Drools 规则引擎，算赔付金额，接公司 30 年的核价规则库
    ↓
[反欺诈 Agent] Python + XGBoost，查历史索赔关联图谱
```

**为什么必须 A2A：**

核价规则库是 Java 团队十几年的资产，几万条 Drools 规则，重写成 Python 不现实
也没人敢签字。定损模型要 GPU，核价规则引擎要的是大内存 CPU 机器。
这三个东西塞进一个 LangGraph 进程，意味着你要在同一台机器上同时装
PyTorch、CUDA 和 JVM，并且按最大公约数配机型——GPU 机器上跑规则引擎，
每小时烧的钱是纯 CPU 机器的十几倍。

**A2A 契约长这样：**

```python
AgentCard(
    name="DamageAssessmentAgent",
    description="根据事故照片识别车辆损伤部位与程度",
    url="https://damage.claims.internal:8443",
    version="2.3.1",
    skills=[AgentSkill(
        name="assess",
        description="输入照片 URL 列表，输出损伤部位、程度、置信度",
        examples=["评估 s3://claims/2026/img_001.jpg"],
    )],
)
```

Java 团队只要认这个 HTTP 契约，内部怎么实现没人管。

### 场景 2：券商投研——每个 Agent 的合规审计边界不同

某券商的投研助手，看起来是"一个"AI 助手，实际拆了五个服务：

| Agent | 部署位置 | 为什么单独 |
|-------|---------|-----------|
| 行情查询 | 内网，接 Wind/万得 | 数据有 license，调用量要按席位计费审计 |
| 研报摘要 | 内网 GPU | 只读公开研报，风险最低 |
| 持仓分析 | **合规隔离区** | 触碰客户持仓，所有调用要留痕 7 年 |
| 下单执行 | **交易内网，物理隔离** | 走券商柜台，要过双人复核 |
| 舆情监控 | 公网出口 | 唯一允许访问外网的服务 |

**为什么必须 A2A：**

不是技术选择，是**监管要求**。"下单执行"和"舆情监控"按规定不能在同一个
进程、同一台机器、甚至同一个网段——一个要碰真金白银，一个要连公网。
证监会检查的时候要能证明这两条路径物理隔离。

单进程 LangGraph 在这里直接违规，讨论都不用讨论。

**另一个现实约束：** 持仓分析的调用必须逐条落审计日志，含操作人、时间、
查询范围、返回摘要。A2A 的 `Task` 天然带 `id`，在服务入口做一层
中间件就能全量留痕。单进程内的函数调用要做到同等审计粒度，得手工在每个函数里埋点。

### 场景 3：SaaS 多租户——一个客户的 Agent 不能拖垮别人

做企业知识库 SaaS，客户里有 3 个大客户占了 70% 的流量：

```
                    ┌── tenant-A 专属 RAG Agent（独立 pod，8C16G，QPS 200）
API 网关 → 路由 ────┼── tenant-B 专属 RAG Agent（独立 pod，4C8G，QPS 50）
                    └── 共享 RAG Agent（小客户共用，autoscale 2~20 pod）
```

**为什么必须 A2A：**

大客户签了 SLA：99.9% 可用性、P99 延迟 800ms。小客户免费版没有 SLA。
如果所有租户共用一个 LangGraph 进程，某个免费用户上传一个 500MB 的 PDF
触发 OOM，付费客户一起挂——然后你赔钱。

拆成独立服务后：
- 大客户 pod 单独扩容，`resources.limits` 隔离内存
- 免费版 pod 挂了自动重启，不影响付费租户
- 大客户要求"我们的数据只能在自己的 VPC 里处理"时，直接把它的 pod
  部署到客户 VPC，A2A 走 VPC Peering——这是单进程架构做不到的

### 场景 4：接入外部组织的 Agent

企业差旅系统要接航司和酒店的 Agent：

```
[企业差旅编排] ──A2A──> 携程商旅 Agent（对方公司维护）
                ──A2A──> 某航司订票 Agent（对方公司维护）
                ──A2A──> 内部差旅报销 Agent（自己维护）
```

**为什么必须 A2A：**

你根本没有对方的代码。能拿到的只有一个 URL 和一份 AgentCard。
这种跨组织协作只可能靠协议，不可能靠"把对方的函数 import 进来"。

这也是 A2A 协议存在的最初动机——它是公开规范，不是某个库的私有约定。

---

## 二、该用 LangGraph 的场景

### 场景 5：合同审查——需要循环，而且要能人工介入

法务的合同审查流程，这是 LangGraph 的主场：

```
        ┌─────────────────────────────────┐
        ↓                                 │
   [提取条款] → [风险识别] → [判断严重度]  │
                                 │        │
                    ┌────────────┼────────┤
                    ↓            ↓        │
              严重度 < 3     严重度 ≥ 3   │
                    ↓            ↓        │
              [自动改写] → [人工复核] ────┘  ← 律师改完可能要求重新识别风险
                    ↓
              [生成审查意见]
```

**为什么必须 LangGraph：**

**1. 循环。** 律师复核后可能要求"再看一遍第 3 条的关联风险"，
流程要回到风险识别节点。A2A 是请求-响应模型，主控里想实现这个循环
得自己写 while 循环 + 状态管理 + 每轮重新序列化 Task，
而 LangGraph 的条件边天然支持回边：

```python
builder.add_conditional_edges(
    "human_review",
    lambda s: "risk_scan" if s["need_rescan"] else "generate_opinion",
)
```

**2. 断点续跑（这是关键）。** 律师复核要等两天。用 A2A，主控进程不可能
挂着两天等一个 HTTP 响应。LangGraph 的 checkpointer 直接解决：

```python
from langgraph.checkpoint.postgres import PostgresSaver

app = builder.compile(
    checkpointer=PostgresSaver.from_conn_string(DSN),
    interrupt_before=["human_review"],       # 跑到这里自动暂停，状态落库
)

# 周一：跑到 human_review 前停下
app.invoke({"contract_id": "C-2026-0817"}, config={"configurable": {"thread_id": "C-2026-0817"}})

# 周三：律师批完，从断点继续，不重跑前面的节点
app.invoke(Command(resume={"approved": True}), config={"configurable": {"thread_id": "C-2026-0817"}})
```

这套 checkpoint + interrupt 机制是 LangGraph 内置的。A2A 要实现等价能力，
你得自己设计状态表、自己做序列化、自己处理"从第 N 步恢复"的逻辑——
基本等于重写一个工作流引擎。

**3. 时间旅行调试。** 合同审查出错时，法务会问"为什么第 7 条被判成高风险"。
LangGraph 能把任意一步的 state 快照捞出来重放：

```python
for snapshot in app.get_state_history(config):
    print(snapshot.next, snapshot.values["risk_items"])
```

### 场景 6：客服工单——ReAct 循环，工具调用次数不确定

电商客服 Agent 处理"我的订单还没到":

```
用户: 我上周买的鞋子还没收到

[思考] 需要订单号 → 调 query_orders(user_id)
[观察] 找到 3 个未完成订单
[思考] 哪个是鞋子 → 调 get_order_detail(order_id) ×3
[观察] 订单 B 是鞋子，物流状态"运输中"
[思考] 查物流详情 → 调 track_logistics("SF1234567")
[观察] 卡在中转站 4 天
[思考] 超过承诺时效 → 调 create_compensation(order_id, reason)
[回复] 已为您申请 20 元补偿券，预计明天送达
```

**为什么必须 LangGraph：**

工具调用次数**事先不知道**。可能 1 次就够（用户只有一个订单），
也可能 8 次（多个订单要逐个排查）。这是个动态循环，
循环次数由 LLM 每轮的判断决定。

A2A 的模型是"主控决定调用谁，调一次，拿结果"。要实现这种
不定次数的 ReAct 循环，主控里得写：

```python
# A2A 版本要手写的东西
while not done and steps < MAX_STEPS:
    decision = await llm_client.ask(build_prompt(history))   # 一次网络往返
    tool_name, args = parse(decision)                        # 自己解析
    result = await network.get_agent(tool_name).send_task_async(  # 又一次往返
        Task(id=str(uuid4()), message=...)                   # 每轮重新构造 Task
    )
    history.append((decision, result))                       # 自己维护历史
    steps += 1
```

每轮两次 HTTP 往返，8 轮就是 16 次网络调用。LangGraph 里这些全在进程内，
`add_messages` 累加器自动维护对话历史：

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]     # 自动累加，不用手工 append
```

延迟差距在生产上很直观：单次工具调用 P50 从 ~180ms（含两次内网 HTTP + 序列化）
降到 ~15ms（纯函数调用），8 轮下来省掉一秒多。客服场景用户是在等着的。

### 场景 7：财报生成——扇出扇入，需要并行

季度财报生成，要同时从 6 个数据源取数再汇总：

```
              ┌→ [营收分析] ─┐
              ├→ [成本分析] ─┤
[准备期间] ───┼→ [现金流]  ─┼──→ [交叉校验] → [生成 PPT]
              ├→ [应收账款] ─┤
              ├→ [同业对比] ─┤
              └→ [风险披露] ─┘
```

**为什么用 LangGraph：**

LangGraph 的图结构里，六个节点连到同一个下游节点就自动并行执行，
超步（superstep）机制保证六个都跑完才进 `交叉校验`：

```python
for node in ("revenue", "cost", "cashflow", "receivable", "peer", "risk"):
    builder.add_edge("prepare", node)
    builder.add_edge(node, "cross_check")     # 自动 fan-in，等全部完成
```

而且 `交叉校验` 需要同时看到六份结果做一致性检查（比如营收和应收账款
的口径对不对得上）。共享 state 让这件事很自然——六个节点写各自的字段，
校验节点读全部。

A2A 版本要自己 `asyncio.gather` 六个请求、自己处理部分失败
（其中一个超时怎么办：重试？降级？整体失败？）、
自己把六份 JSON 拼成一个上下文喂给校验逻辑。

### 场景 8：不该拆的时候别拆

一个反面例子。某团队把 RAG 流程拆成了四个 A2A 服务：

```
[查询重写 Agent:8001] → [向量检索 Agent:8002] → [重排 Agent:8003] → [生成 Agent:8004]
```

**这是过度设计。** 理由：

1. 这四步是**同一个团队**维护的，同一个 git repo，同一个发布节奏
2. 四步**永远一起调用**，没有任何场景只调其中一个
3. 拆开后每次问答多了 4 次 HTTP + 8 次 JSON 序列化，P99 延迟从 1.2s 涨到 2.1s
4. 排查"为什么这个问题检索不到"要翻四个服务的日志
5. 四个服务的 k8s deployment、监控看板、告警规则都要各配一套

后来合并成一张 LangGraph 图，代码量少了 40%，延迟回到 1.3s，
运维配置从四套变一套。

**判断方法：** 问自己"这两个节点会不会有一天需要不同的发布节奏、
不同的机型、或者被不同的团队负责"。答案是"不会"就别拆。

---

## 三、两者叠加：真实生产架构长什么样

最常见的不是二选一,而是**A2A 做外层服务边界,LangGraph 做每个服务的内部编排**。

某银行智能信贷审批系统的真实分层：

```
                        ┌─────────────────────────────────┐
   客户端 ──HTTP──>     │  信贷编排服务                    │
                        │  内部是一张 LangGraph 图：        │
                        │    收件 → 资料校验 → 并行调三方   │
                        │      → 综合评分 → 人工复核(可中断) │
                        │      → 出具结论                  │
                        └───┬─────────┬─────────┬──────────┘
                            │A2A      │A2A      │A2A
                            ↓         ↓         ↓
                    ┌───────────┐ ┌────────┐ ┌──────────┐
                    │征信查询   │ │反欺诈  │ │抵押物估值│
                    │(风控团队) │ │(算法团)│ │(资产团队)│
                    │Java       │ │Python  │ │Python+GIS│
                    └───────────┘ └────────┘ └──────────┘
```

**分工非常清楚：**

- **A2A 管跨团队边界**：征信查询是风控团队的服务，有自己的发布流程、
  自己的 SLA、自己的 oncall。它挂了信贷编排要能降级（用缓存的征信快照）。
- **LangGraph 管编排服务内部**：那个"人工复核可中断"必须靠
  checkpointer，那个"并行调三方"必须靠图的 fan-out，
  那个"评分不通过退回补资料"必须靠条件回边。

**一句话总结这个分层：**
LangGraph 管**一个 Agent 内部怎么想**，A2A 管**多个 Agent 之间怎么说话**。

### 落地时的一个实用技巧

LangGraph 图可以直接包成 A2A 服务对外提供，两者不冲突：

```python
from python_a2a import A2AServer, AgentCard, AgentSkill, TaskStatus, TaskState, run_server
from .graph import build_graph
from .state import read_artifact_text

class CreditOrchestratorServer(A2AServer):
    """外面看是一个 A2A Agent，里面是一整张 LangGraph 图。"""

    def __init__(self):
        super().__init__(agent_card=AgentCard(
            name="CreditOrchestrator",
            description="信贷审批全流程编排",
            url="https://credit.bank.internal:8443",
            skills=[AgentSkill(name="approve", description="提交信贷申请并获得审批结论")],
        ))
        self.app = build_graph()          # 编译一次，复用

    def handle_task(self, task):
        query = (task.message or {}).get("content", {}).get("text", "")
        # thread_id 用 task.id，这样 checkpointer 能按任务续跑
        final = self.app.invoke(
            {"query": query, "logs": []},
            config={"configurable": {"thread_id": task.id}},
        )
        task.artifacts = final["artifacts"]      # 两边的 artifacts 结构本来就一致
        task.status = TaskStatus(state=TaskState.COMPLETED)
        return task
```

注意 `thread_id` 用了 `task.id`——这让 A2A 的任务标识和 LangGraph 的
checkpoint 线程对齐，外部重新提交同一个 task.id 就能从断点续跑。

---

## 四、决策速查表

按你的实际情况找对应行：

| 你的情况 | 选择 | 理由 |
|---------|------|------|
| 两段逻辑由不同团队维护，发布节奏不同 | **A2A** | 独立发布是硬需求 |
| 其中一段要 GPU，另一段只要 CPU | **A2A** | 混部会按最贵机型付钱 |
| 有段逻辑必须部署在隔离网段（合规） | **A2A** | 单进程直接违规 |
| 要接入其他公司的 Agent | **A2A** | 拿不到对方代码，只能靠协议 |
| 某个租户/客户需要独立的资源配额和故障隔离 | **A2A** | 避免免费用户拖垮付费客户 |
| 已有 Java/Go 资产不能重写 | **A2A** | 跨语言只能走协议 |
| 流程里有循环、回退、重试分支 | **LangGraph** | 条件边天然支持，A2A 要手写状态机 |
| 需要人工审批，中间要等几小时或几天 | **LangGraph** | checkpointer + interrupt 内置 |
| 工具调用次数由 LLM 动态决定（ReAct） | **LangGraph** | 不定轮次循环，A2A 每轮两次网络往返 |
| 需要并行扇出再汇总 | **LangGraph** | fan-out/fan-in 自动，共享 state 方便交叉校验 |
| 需要复盘"当时第 N 步的状态是什么" | **LangGraph** | `get_state_history()` 时间旅行 |
| 同团队、同 repo、永远一起调用的几个步骤 | **LangGraph** | 拆开纯亏延迟和运维成本（见场景 8）|
| 延迟敏感，每次多一跳都心疼 | **LangGraph** | 进程内调用，零序列化 |

---

## 五、三个容易踩的坑

**1. 用 A2A 拆得太细。** 见场景 8。判断标准是"会不会有不同的发布节奏"，
不是"看起来是不是两个概念"。概念上可分 ≠ 部署上该分。

**2. 用 LangGraph 硬扛跨团队协作。** 把别的团队的逻辑 import 进自己的图里，
结果他们改一行代码你的服务就得跟着发版，两个团队被焊在一起。
这种耦合出现时，说明边界该用 A2A 划。

**3. 单进程图不做异常隔离。** LangGraph 里一个节点抛未捕获异常整张图就停。
生产环境每个节点都该有自己的兜底，就像本项目 `router.py` 里做的那样：

```python
except Exception as exc:
    print(f"[Router 日志] LLM 调用失败({exc.__class__.__name__})，退到关键词路由")
    agent_name, confidence = _keyword_route(query)      # 降级而不是崩掉
```

这是单进程架构必须自己补的功课——A2A 里一个服务挂了别的还活着，
单进程里没有这层天然保护。
