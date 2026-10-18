# 任务编排 badcase 修复说明

> 关联文件：`bug_任务_编排的badcase`（问题现场输出）
> 涉及改动：`main_prompts.py`、`chat_service.py`
> 日期：2026-08-23

## 一、问题现象

跑 `test_planning_agent()` 的 6 个用例，输出与预期严重不符：

| 用例 | 期望 | 实际 |
|---|---|---|
| 单意图-天气 | `need_plan=false` | `need_plan=true`，还拆出 1 个步骤 |
| 双意图独立（天气+机票） | `need_plan=false` | `need_plan=true`，2 个步骤 |
| 三意图（机票+天气+景点） | 无假依赖 | 景点 `depends_on=2`（依赖天气） |
| 国庆四意图 | 只有预订依赖查询 | 保险 `depends_on=1`（依赖机票），串成一条链 |
| 所有用例 | 使用真实 agent 名 | 大量编造名称 |

`need_plan` 除了空意图那条，其余全是 `true`。

## 二、根因分析

这不是代码逻辑 bug，是**提示词缺约束**。四个现象对应四个具体原因。

### 原因 1：判断标准写在 docstring 里，大模型看不到

原 `planning_prompt()` 的 docstring 里写了判断标准：

```
判断标准：
    - 简单任务：只有一个意图，直接就能执行
    - 复杂任务：多个意图且有关联、需要多步推理、步骤间有依赖关系
```

但 docstring 是给人看的，`ChatPromptTemplate.from_template()` 只把三引号里的正文发给模型。
正文里**没有任何一句**说明什么时候该返回 `false`。

更糟的是，正文末尾的输出格式示例把值硬编码成了 `true`：

```
输出严格为JSON，不要添加额外文本：{{"need_plan": true, "reason": "原因", ...}}
```

模型看到一个 `true` 的模板，就照抄 `true`。空意图那条返回 `false` 纯属运气——没意图可拆，
硬填 steps 也填不出来。

### 原因 2：没给可用 agent 清单，模型按意图名造名字

输出里出现的这些 agent，**一个都不存在**：

```
FlightQueryAssistant            TrainQueryAssistant
AttractionRecommendationAssistant   TicketBookingAssistant
InsuranceQueryAssistant         TripOrderAssistant
```

`config.py:55` 的真实映射只有三个 agent：

```python
self.intent = {
    "weather": "WeatherQueryAssistant",
    "flight": "TicketAssistant",   "train": "TicketAssistant",
    "concert": "TicketAssistant",  "order": "TicketAssistant",
    "car_rental": "TripAssistant", "tour_group": "TripAssistant",
    "insurance": "TripAssistant",  "trip_order": "TripAssistant",
}
```

`attraction` 不走 agent，由本地大模型直接生成（`chat_service.py:232`）。

原 prompt 只在字段说明里给了一个例子「如"调用WeatherQueryAssistant查询北京天气"」，
模型于是照这个构词法给每个意图都造了个 `XxxAssistant`。

这个问题当前**不会导致运行时报错**——`execute_step()` 用的是 `step["intent"]` 而不是
`action` 里的 agent 名，`action` 只当描述用。但它是个定时炸弹：一旦以后按 `action` 派发，
或者把 `action` 展示给用户，就直接出错。

### 原因 3：没定义"依赖"是什么，模型把执行顺序当成了依赖

原 prompt 对 `depends_on` 的全部说明只有一行：

```
- depends_on: 依赖的前置步骤序号（无依赖则为0）
```

没说"依赖"指数据依赖。模型就按叙述顺序标：用户说"先查机票，再看天气，推荐景点"，
它就标成链式。结果出现两个假依赖：

- `attraction depends_on=2`（景点依赖天气）——景点推荐不需要天气数据
- `insurance depends_on=1`（保险依赖机票）——保险查询不需要航班数据

代价是性能。`react_loop()` 按 `depends_on` 分组，同值的并行执行：

```python
dep_groups.setdefault(dep, []).append(step)   # chat_service.py:140
```

假依赖把本可并行的 4 步串成 4 组，响应时间翻几倍。

### 原因 4：输出看着乱序 —— 这个不是 bug

案例 2 的「规划响应」日志出现在案例 3 的段落里，看着像串了。实际是流没同步：

- `logger` 的 `StreamHandler()` 默认写 **stderr**（`create_logger.py:20`）
- `print()` 写 **stdout**

两个流各自缓冲，交错落盘。用 `python -u` 跑就对齐了。功能没问题。

## 三、改动一：提示词（`main_prompts.py` → `planning_prompt()`）

### 改之前

正文一共 15 行，这是全部内容：

```
系统提示：您是一位任务规划专家，负责评估用户请求的复杂度并制定执行计划。

将任务拆解为有序步骤，每个步骤指定：
- step: 步骤序号（从1开始）
- action: 具体动作（如"调用WeatherQueryAssistant查询北京天气"）
- intent: 对应的意图（如weather/flight/train/concert/order/attraction）
- depends_on: 依赖的前置步骤序号（无依赖则为0）

对话历史：{conversation_history}
当前用户查询：{query}
识别到的意图：{intents}
用户查询改写：{user_queries}

输出严格为JSON，不要添加额外文本：{{"need_plan": true, "reason": "原因", "steps": [{{"step": 1, "action": "...", "intent": "...", "depends_on": 0}}, ...]}}
```

三个致命点：
1. 开头就说"将任务拆解为有序步骤"——等于命令模型必须拆，没给不拆的选项
2. 全文没有一处说明 `need_plan=false` 的条件
3. 输出示例硬编码 `"need_plan": true`

### 改之后

补了五节。核心是把原来只存在于 docstring 的规则搬进正文，并补上原来根本没有的约束。

**第一节 —— 可用执行单元（对应原因 2）**

给出真实的 4 个执行单元和 intent 白名单，明确禁止编造：

```
- WeatherQueryAssistant：天气查询。对应意图 weather
- TicketAssistant：票务查询与预订。对应意图 flight / train / concert / order
- TripAssistant：旅行服务。对应意图 car_rental / tour_group / insurance / trip_order
- 本地大模型：景点推荐，无需调用外部服务。对应意图 attraction

intent 字段只能取以下值之一，必须来自"识别到的意图"列表，不得新增或改写：
weather / flight / train / concert / order / attraction /
car_rental / tour_group / insurance / trip_order
```

**第二节 —— need_plan 判断规则（对应原因 1）**

`false` 的三种情形写在前面，`true` 收窄到只剩数据依赖一种：

```
返回 need_plan=false（steps 必须为空数组 []）的情况：
1. 意图列表为空
2. 只有 1 个意图
3. 多个意图但彼此独立：每个意图各查各的，谁都不需要等别人的结果

返回 need_plan=true 的情况，仅限于：
- 存在真实的数据依赖：某一步必须拿到前一步的结果才能执行
  典型场景：先查车次/航班，再用查到的班次去下单（order / trip_order 依赖前置查询）

注意：意图多 ≠ 需要规划。"看看天气和机票"是两个独立查询，need_plan=false。
```

最后那句"意图多 ≠ 需要规划"是专门针对双意图和三意图那两个 badcase 写的——
模型原来的错误推理就是"有 3 个意图，所以复杂"。

**第三节 —— depends_on 规则（对应原因 3）**

直接把 badcase 里出现过的假依赖列成反例：

```
- 只有当本步骤真的需要消费前一步的输出时，才填写那一步的 step 序号
- 以下都不构成依赖，必须填 0：
  * 天气 → 景点（景点推荐不需要天气数据）
  * 机票 → 保险（保险查询不需要航班数据）
  * 机票 → 天气、天气 → 机票（互不相关）
- 真正构成依赖的：查询类 → 预订类（order / trip_order 需要先拿到可选班次或行程）
- 不要制造链式依赖来表达"执行顺序"，顺序由 step 序号表达，依赖只表达数据流
```

最后一句是关键——它点明了模型原来的误解：把叙述顺序当成了依赖。

**第五节 —— 示例（对应原因 1）**

给三个正例，其中两个是 `false`，把"多意图也可以不拆"演示出来：

```
意图 ["weather"] → {"need_plan": false, "reason": "单意图，直接查询即可", "steps": []}

意图 ["weather", "flight"]（"看看天气和机票"）
→ {"need_plan": false, "reason": "两个意图互相独立，无数据依赖，可直接分别查询", "steps": []}

意图 ["train", "order"]（"查高铁，合适就订一张"）
→ {"need_plan": true, "reason": "订票需要先拿到车次查询结果，存在数据依赖", "steps": [...]}
```

**输出格式 —— 两种都给，不再只给 true**

```
need_plan=false 时格式：{"need_plan": false, "reason": "原因", "steps": []}
need_plan=true  时格式：{"need_plan": true, "reason": "原因", "steps": [{...}]}
```

同时把 docstring 里的判断标准同步成了新规则，并留了一句「改一处要改两处」的提醒，
避免以后又出现文档和正文脱节。

## 四、改动二：新增 `_sanitize_plan()`（`chat_service.py`）

### 为什么改了 prompt 还要加代码

提示词是**软约束**。模型温度虽然是 0.1，但仍有概率违反规则，而且违反的后果不对称：

- `need_plan` 多判一次 `true` → 白跑一遍 ReAct，性能损失
- `intent` 编造一个 → `execute_step()` 里 `conf.intent.get(intent)` 返回 `None`，
  走到 `chat_service.py:271` 返回"暂不支持此意图"，用户直接看到无效回复
- `depends_on` 指向自身或后面的步骤 → `react_loop()` 分组后依赖永远等不到，逻辑上是个环

所以在 prompt 之后加一道确定性校验，把不合法的输出纠正回来。

### 改之前

解析完直接返回，没有任何校验：

```python
planning_response = re.sub(r'^```json\s*|\s*```$', '', planning_response).strip()
plan = json.loads(planning_response)
return plan
```

顺带一个小问题：正则只能剥掉 ` ```json `，剥不掉不带语言标记的 ` ``` `。
badcase 里两种包裹都出现过，后者会直接 `JSONDecodeError`。

### 改之后

```python
# 去掉 markdown 代码块包裹（```json ... ``` 或 ``` ... ```）
planning_response = re.sub(r'^```(?:json)?\s*|\s*```$', '', planning_response).strip()
plan = json.loads(planning_response)
return _sanitize_plan(plan, intents)
```

新增的 `_sanitize_plan(plan, intents)` 做四件事：

**1. 丢弃越界 intent，用意图识别结果当白名单**

```python
allowed = set(intents)
for step in steps:
    if step.get("intent", "") not in allowed:
        logger.warning(f"规划步骤 intent 越界，已丢弃: {intent}")
        continue
    cleaned.append(dict(step))
```

用 `intents` 而不是 `conf.intent` 的键做白名单——规划不该凭空引入意图识别没识别出的意图。

**2. 重排 step 序号，并同步修正 depends_on**

丢弃步骤会让序号出现空洞（比如删了 step2，剩下 1、3）。所以重排序号，
同时建映射把旧序号翻译成新序号，否则 `depends_on` 会指错：

```python
old_to_new = {}
for new_num, step in enumerate(cleaned, start=1):
    old_to_new[step.get("step")] = new_num
    step["step"] = new_num
```

**3. 非预订类意图的依赖一律压平为 0**

这条直接消掉了「景点依赖天气」「保险依赖机票」这类假依赖：

```python
booking_intents = {"order", "trip_order"}

if step.get("intent") not in booking_intents:
    step["depends_on"] = 0
    continue
```

判断依据是业务事实：本系统里只有下单类意图需要消费查询结果，
其余意图都是独立查询。这个假设写死在代码里，比让模型每次推断更可靠。

**4. 拒绝非法依赖，并在无真实依赖时降级**

```python
new_dep = old_to_new.get(dep, 0)
if new_dep >= step["step"]:          # 依赖必须指向前面的步骤
    logger.warning(f"步骤{step['step']} 依赖非法({dep})，已置 0")
    new_dep = 0
```

压平之后如果一条依赖都不剩，说明这些意图本来就能并行，没必要走 ReAct，
直接降级成 `need_plan=false` 交给简单分支：

```python
has_real_dep = any(s.get("depends_on", 0) for s in cleaned)
if not cleaned:
    return {"need_plan": False, "reason": plan.get("reason", "无有效步骤"), "steps": []}
if not has_real_dep:
    return {"need_plan": False, "reason": ..., "steps": []}
```

这一步是 `need_plan` 的最后一道兜底：**即使模型仍然坚持返回 `true`，
只要拆出来的步骤之间没有真实依赖，也会被强制改回 `false`**。

## 五、改动三：修默认值 bug（`chat_service.py:302`）

排查过程中顺手发现的，和 badcase 无关。

### 改之前

```python
for intent in intents:
    query_str = user_queries.get(intent, {})
    result = await self._call_agent_intent(intent, query_str)
```

默认值是 `{}`，但 `query_str` 下游是当字符串用的——会被塞进 prompt 模板，
或者拼进 `chat_history`（`chat_service.py:246`）。改写缺失时用户会看到一个 `{}`。

### 改之后

```python
for intent in intents:
    # 改写缺失时退回原始输入，不能传 {}（会把 dict 塞进 prompt）
    query_str = user_queries.get(intent) or user_input
    result = await self._call_agent_intent(intent, query_str)
```

用 `or` 而不是 `get` 的默认值，这样空字符串也能被兜住。退回 `user_input` 比退回空串好——
至少 agent 还能拿到用户原话。

## 六、验证

### 第一轮：纯内存验证 `_sanitize_plan()`

把 badcase 里模型的原始错误输出直接喂给校验函数，不打大模型：

| 输入（badcase 原样） | 校验后 |
|---|---|
| 单意图 weather，`true` + 1 步 | `false`，steps 空 |
| 双意图独立，`true` + 2 步 | `false`，steps 空 |
| 三意图，景点 `dep=2` | `false`，steps 空 |
| train+order，`dep=1` | `true` 保留，`dep=1` 保留 |
| 四意图，保险 `dep=1`、预订 `dep=3` | `true`，前 3 步 `dep=0`，仅预订保留依赖 |
| 编造 `intent=hotel` | hotel 丢弃，序号重排为 1、2，依赖跟着修正 |

真依赖（`train→order`）没被误伤，假依赖全部压平。

### 第二轮：真实链路

`python -u -m SmartVoyage.chat_service`，6 个用例全部符合预期：

| 用例 | 修复前 | 修复后 |
|---|---|---|
| 单意图-天气 | `true` + 1 步 | `false`，steps 空 |
| 双意图独立 | `true` + 2 步 | `false`，steps 空 |
| 三意图（含假依赖） | `true`，景点依赖天气 | `false`，steps 空 |
| train+order | `true`，agent 名编造 | `true`，`TicketAssistant`，`dep=1` 正确 |
| 国庆四意图 | `true`，保险假依赖、串成链 | `true`，前 3 步 `dep=0` 可并行，仅 trip_order `dep=1` |
| 空意图 | `false` | `false` |

Agent 名字回到真实的三个：`TicketAssistant`、`TripAssistant`、"本地大模型"（景点）。

注：要用 `-m` 方式跑。直接 `python SmartVoyage/chat_service.py` 会因为
`sys.path` 指向 `SmartVoyage/` 而不是项目根目录，报 `No module named 'SmartVoyage'`。
加 `-u` 关掉缓冲，stdout / stderr 才对齐。

## 七、遗留项

**多意图串行执行。** 简单分支（`chat_service.py:300`）里多个独立意图是 `for` 循环顺序
执行的，每个都 `await` 完才轮到下一个：

```python
for intent in intents:
    result = await self._call_agent_intent(intent, query_str)
```

独立意图本可以 `asyncio.gather` 并行，和 `react_loop()` 里的做法一致。
这次改动让更多用例走进了这个分支（原来它们错误地走 ReAct），所以这个点的收益比以前更明显。
不在本次范围内，没动。

## 八、经验

1. **写在 docstring 里的规则等于没写。** 提示词的约束必须在发给模型的正文里。
2. **输出格式示例会被当成默认值。** 示例里硬编码 `"need_plan": true`，模型就倾向于返回 true。
   有分支的字段，两种取值的示例都要给。
3. **让模型选择时，要把可选项列全。** 不给 agent 清单，它就按构词法造名字。
4. **业务事实写进代码，不要让模型每次推断。** "只有下单类需要前置查询"是确定的规则，
   写在 `_sanitize_plan()` 里比写在 prompt 里可靠。
5. **提示词约束之后要有确定性校验兜底。** 尤其当错误输出会直接暴露给用户时。
6. **先确认现象是不是 bug。** 「输出乱序」花了时间排查，最后发现只是 stdout / stderr 缓冲。




