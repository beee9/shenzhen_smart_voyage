# 从零搭一个 12306 火车票 Agent（MCP + streamable HTTP）

配套代码：`client_12306.py`

跟着走完，你会得到一个能回答"明天深圳到武汉有哪些高铁"的 Agent。它自己不懂火车，
所有数据都来自一个跑在 Docker 里的 MCP server。

## 这个案例在教什么

三个角色，别搞混：

| 角色 | 是谁 | 干什么 |
|------|------|--------|
| MCP server | `drfccv/mcp-server-12306` 容器 | 提供 7 个查询工具，真去请求 12306 官网 |
| MCP client | `client_12306.py` | 连上 server，把工具列出来、翻译成 LangChain 工具 |
| LLM | 通义千问 `qwen-plus` | 读用户的话，决定调哪个工具、传什么参数 |

调用链：

```
你输入"明天深圳到武汉的票价"
      |
      v
client_12306.py  --(1) 把 7 个工具的名字/描述/参数 schema 发给模型
      |
      v
qwen-plus        --(2) 模型决定：先调 get-current-time
      |
      v
client_12306.py  --(3) 通过 MCP 协议(HTTP POST /mcp)调用容器里的工具
      |
      v
MCP server       --(4) 执行，返回 {"date": "2026-08-20", ...}
      |
      v
qwen-plus        --(5) 算出明天=08-21，再调 query-ticket-price
      |                （循环 3~5 直到模型觉得信息够了）
      v
最终中文回答
```

关键认知：**模型没有联网能力，也不知道今天几号。它的全部能力来自你给它的工具清单。**
工具描述写得烂，模型就调错；描述写得清楚，模型自己会串联多步。

## 第 0 步：环境准备

需要的包（`requirements.txt` 里已经有了，确认一下）：

```
mcp                    1.18.0     # MCP 协议官方 SDK
langchain-mcp-adapters 0.1.11     # 把 MCP 工具转成 LangChain 工具
langchain              0.3.26
langchain-openai       0.3.28     # 用 OpenAI 兼容接口调通义千问
httpx                  0.28.1
```

API Key 走环境变量，不要写进代码：

```bash
# Windows PowerShell（永久）
setx DASHSCOPE_API_KEY "sk-你的key"
# 设完要重开终端才生效
```

`agent_learn/config.py` 读的就是这个变量：

```python
API_KEY = os.getenv('DASHSCOPE_API_KEY')
class Config:
    def __init__(self):
        self.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        self.api_key = API_KEY
        self.model_name = 'qwen-plus'
```

通义千问提供 OpenAI 兼容端点，所以能直接用 `ChatOpenAI`，只要把 `base_url` 换掉。

验证：

```bash
python -c "import os; print(bool(os.getenv('DASHSCOPE_API_KEY')))"   # True
```

## 第 1 步：把 MCP server 跑起来

```bash
docker run -d -p 8080:8000 \
  -e SERVER_HOST=0.0.0.0 -e SERVER_PORT=8000 \
  --name mcp-server-12306 drfccv/mcp-server-12306:latest
```

`-p 8080:8000` 是端口映射：容器内监听 8000，宿主机用 8080 访问。
`SERVER_HOST=0.0.0.0` 必须设 —— 如果服务只绑 `127.0.0.1`，那是容器内部的
localhost，宿主机映射进去也连不上。

确认在跑：

```bash
curl http://127.0.0.1:8080/
```

正常输出（这就是健康检查，记住 `mcp_endpoint` 和 `tools`）：

```json
{"name":"mcp-server-12306","version":"0.5.0.post20260807","status":"running",
 "mcp_endpoint":"/mcp",
 "transport":"Streamable HTTP (mcp SDK v2)",
 "stations_loaded":3382,
 "tools":["query-tickets","query-ticket-price","search-stations","query-transfer",
          "get-train-route-stations","get-train-no-by-train-code","get-current-time"]}
```

`stations_loaded: 3382` 说明车站库加载好了。7 个工具全是只读查询，没有下单接口，
所以这个案例不用像调用公网 MCP 那样防写操作。

## 第 2 步：写连接配置（含那个必踩的坑）

MCP 有三种常见传输方式，这个 server 用的是 **streamable HTTP**：

| 传输 | 端点形态 | 适用 |
|------|----------|------|
| stdio | 启子进程，管道通信 | 本地脚本工具 |
| SSE | `/sse` | 老式远程（已逐步淘汰） |
| streamable_http | `/mcp` | 现在的远程标准 |

**这个 server 只有 `/mcp`，没有 `/sse`。按 SSE 接会 404。**

```python
MCP_12306_URL = "http://127.0.0.1:8080/mcp"

MCP_12306_CONNECTION = {
    "mcp-12306": {                                  # 这个名字后面 session() 要用
        "transport": "streamable_http",
        "url": MCP_12306_URL,
        "httpx_client_factory": _no_proxy_httpx_client,   # ← 关键，见下
    }
}
```

### 坑：本机代理劫持 localhost，报 502

不加 `httpx_client_factory` 的话，如果你开着代理软件（Clash 之类），会看到：

```
httpx.HTTPStatusError: Server error '502 Bad Gateway'
for url 'http://127.0.0.1:8080/mcp'
```

反直觉的地方在于：`curl` 打同一个地址返回 200，Python 却 502，而且
`docker logs` 里根本没有这条请求 —— 说明请求压根没到容器。

原因：`httpx` 默认 `trust_env=True`，会读系统代理设置，把 `127.0.0.1:8080`
也发给代理，代理转发本地地址失败就返回 502。`curl` 不读 Windows 的 WinINET 设置，
所以一直正常。

确认是不是这个问题：

```bash
python -c "import urllib.request; print(urllib.request.getproxies())"
# 输出 {'http': 'http://127.0.0.1:7890', ...} → 系统代理开着，就是它
# 输出 {} → 不是这个原因，往下看第 6 节
```

解法就是自己造一个不读环境的客户端：

```python
def _no_proxy_httpx_client(headers=None, timeout=None, auth=None):
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        trust_env=False,     # ← 就这一行解决问题
    )
```

签名必须是 `(headers, timeout, auth)` 三个参数，这是 mcp SDK 的
`McpHttpClientFactory` 协议规定的，少一个会 `TypeError`。

## 第 3 步：先别急着上 Agent，把工具清单打出来

这是最重要的调试习惯。**先确认 MCP 连通、工具能列出来，再接模型。**
不然出问题你分不清是连接问题还是模型问题。

```python
async def print_tools(session):
    result = await session.list_tools()      # MCP 协议的 tools/list
    tools = result.tools

    for i, tool in enumerate(tools, 1):
        desc = (tool.description or "").strip().splitlines()
        print(f"\n{i}. {tool.name}")
        print(f"   说明: {desc[0] if desc else '(无描述)'}")

        schema = tool.inputSchema or {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        for name, spec in props.items():
            mark = "必填" if name in required else "可选"
            print(f"     - {name} ({spec.get('type','any')}) {mark}")
```

跑起来（还没配 key 也能跑到这一步）：

```bash
python agent_learn/mcp_base/http/client_12306.py
```

7 个工具和它们的真实参数名：

| 工具 | 必填参数 | 可选参数 |
|------|----------|----------|
| `get-current-time` | 无 | `timezone`, `format` |
| `search-stations` | `query` | `limit` |
| `query-tickets` | `from_station`, `to_station`, `train_date` | — |
| `query-ticket-price` | `from_station`, `to_station`, `train_date` | `train_code`, `purpose_codes` |
| `query-transfer` | `from_station`, `to_station`, `train_date` | `middle_station`, `isShowWZ`, `purpose_codes` |
| `get-train-no-by-train-code` | `train_code`, `from_station`, `to_station`, `train_date` | — |
| `get-train-route-stations` | `train_no`, `from_station`, `to_station`, `train_date` | — |

注意最后两个的区别，这是这个 server 的设计陷阱：

- `train_code` = 你看到的车次号，比如 `G101`
- `train_no` = 内部编号，形如 `240000G1010A`

查经停站要的是 `train_no`，所以必须**先用 `get-train-no-by-train-code` 换一次**。
模型不知道这件事，得你在提示词里告诉它。

### 想手动调一个工具试试

绕过模型直接调，用来验证工具本身好不好使：

```python
import asyncio, httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

def f(headers=None, timeout=None, auth=None):
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, trust_env=False)

CONN = {"m": {"transport": "streamable_http",
              "url": "http://127.0.0.1:8080/mcp",
              "httpx_client_factory": f}}

async def main():
    async with MultiServerMCPClient(CONN).session("m") as s:
        r = await s.call_tool("search-stations", {"query": "武汉"})
        print(r.content[0].text)

asyncio.run(main())
```

参数名写错了会返回 `{"success": false, "error": "..."}`，不会抛异常 ——
比如把 `query` 写成 `keyword`，报的是"请提供搜索关键词"。看到这种错先回去核对 schema。

## 第 4 步：提示词是这个案例的技术核心

工具接上了不等于能用。模型最容易在两件事上犯错：**编日期**和**站名歧义**。
提示词就是专门按死这两件事的：

```python
SYSTEM_PROMPT = (
    "你是 12306 火车票查询助手，可以调用工具查询余票、票价、车站、中转方案和车次经停站。"
    "请遵守以下规则：\n"
    "1. 日期：你不知道今天是几号。遇到「今天」「明天」「下周五」这类相对日期，"
    "必须先调用 get-current-time 拿到真实当前日期，再推算出具体日期。"
    "绝对不要凭记忆猜测当前日期。train_date 参数格式为 YYYY-MM-DD。\n"
    "2. 站名：站名支持中文、拼音、三字码。如果用户给的地名不确定或可能有多个站"
    "（比如「武汉」有武汉站/汉口站/武昌站），先调用 search-stations 确认。\n"
    "3. 查车次经停站时，get-train-route-stations 需要的是 train_no"
    "（形如 240000G1010A），不是车次号 G101。要先用 get-train-no-by-train-code 换。\n"
    "4. 余票、票价、时刻必须来自工具返回结果，绝对不要编造车次号、价格或余票数。"
    "工具没返回的信息就说没查到。\n"
    "5. 回答用中文，把车次、出发到达时间、历时、余票和价格整理清楚，不要堆原始 JSON。"
)
```

逐条讲为什么：

**规则 1（日期）** 最关键。模型的训练数据有截止时间，它对"今天"的认知是错的。
不写这条，它会自信地把 `train_date` 填成一个去年的日期，查出来是空的。
写了这条，你能在 `verbose` 日志里看到它老老实实先调 `get-current-time`。

**规则 2（站名）** 防的是歧义。"武汉"在 12306 里有武汉站、汉口站、武昌站，
用户说"到武汉"到底是哪个？让模型先查再定。

**规则 3（train_no）** 补的是 server 的设计细节，模型无从得知。

**规则 4（禁止编造）** 是 RAG/工具类 Agent 的通用护栏。票价和余票这种事实性数据，
模型编一个出来看着极其合理，但会害人误事。明确要求"查不到就说查不到"。

**规则 5（输出格式）** 不写的话它会把工具返回的原始 JSON 直接贴给用户。

## 第 5 步：组装 Agent

```python
def _build_agent(tools):
    llm = ChatOpenAI(
        base_url=conf.base_url,      # 通义千问的 OpenAI 兼容端点
        api_key=conf.api_key,
        model=conf.model_name,       # qwen-plus
        temperature=0.1,             # 查询类任务要稳定，不要发挥
    )

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),   # ← 必须有
    ])

    agent = create_tool_calling_agent(llm, tools, prompt_template)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)
```

三个容易忽略的点：

- `{agent_scratchpad}` 是多轮工具调用的记事本，存"调了什么工具、返回了什么"。
  漏掉这个占位符，`create_tool_calling_agent` 直接报错。
- `temperature=0.1`：查票是确定性任务，温度高了模型会瞎发挥。
- `verbose=True`：教学场景必开。能看到模型每一步调了哪个工具、传了什么参数，
  这是理解 Agent 行为唯一的窗口。

工具怎么从 MCP 变成 LangChain 能用的：

```python
tools = await load_mcp_tools(session)     # 一行，adapters 帮你转好了
```

它把每个 MCP 工具的 `name` / `description` / `inputSchema` 翻译成 LangChain
`BaseTool`，模型侧看到的就是标准的 function calling 定义。

### 连接复用

注意 `main()` 的结构 —— 一个 session 复用给"列清单"和"跑 Agent"两段：

```python
client = MultiServerMCPClient(MCP_12306_CONNECTION)
async with client.session("mcp-12306") as session:
    await print_tools(session)
    ...
    await run_demo(session)      # 或 run_chat(session)
```

`session("mcp-12306")` 里的名字必须和配置字典的 key 对上。
每次 `call_tool` 重新建连接会很慢，而且 streamable HTTP 是有会话状态的
（还记得健康检查里的 `active_sessions` 吗）。

## 第 6 步：跑起来

```bash
# 固定演示，不用手输
python agent_learn/mcp_base/http/client_12306.py

# 交互问答
python agent_learn/mcp_base/http/client_12306.py --chat
```

一次成功的 `verbose` 输出长这样（注意模型自己串了两步）：

```
> Entering new AgentExecutor chain...
Invoking: `get-current-time` with `{'format': 'YYYY-MM-DD'}`
responded: 我需要先获取明天的具体日期，然后查询深圳到武汉的二等座票价。

{"success": true, "date": "2026-08-20", "time": "11:41:01", ...}

Invoking: `query-ticket-price` with
  `{'from_station': '深圳', 'to_station': '武汉', 'train_date': '2026-08-21'}`
responded: 明天是2026-08-21。现在我来查询深圳到武汉的二等座票价。
...
> Finished chain.
```

规则 1 生效了：它没有猜日期，先查了当前时间，算出 08-21 再传给查价工具。

## 第 7 步：排障对照表

按"报错现象 → 断在哪一层"来查。先分清三层：**宿主机→容器**、**容器→12306官网**、**模型侧**。

### A. `502 Bad Gateway`，docker logs 里没有这条请求

宿主机→容器这一层断了。本机代理劫持了 localhost，见第 2 步。
检查 `_no_proxy_httpx_client` 是不是被改动了、`trust_env=False` 还在不在。

### B. 工具返回 `{"success": false, "error": "网络请求失败 (已重试3次)"}`

容器→12306官网这一层断了。**注意：MCP 连接是好的**，工具被成功调用了，
是工具内部去请求 12306 失败。区分办法：`get-current-time` 和 `search-stations`
能正常返回（它们不联外网，用的是本地车站库），但 `query-tickets` /
`query-ticket-price` 全挂。

最常见的原因是 Docker 守护进程配了代理，但代理没在跑。确认方法：

```bash
docker exec mcp-server-12306 python -c "
import urllib.request
print(urllib.request.urlopen('http://www.baidu.com', timeout=8).status)"
```

如果报这样的错，就是它：

```
HTTP Error 500: writing response to www.baidu.com:80:
connecting to 127.0.0.1:7890: dial tcp 127.0.0.1:7890:
connectex: No connection could be made because the target machine actively refused it.
```

注意 `127.0.0.1:7890` 这个地址是从 Docker 守护进程注入的，容器内 `env | grep -i proxy`
是空的，`urllib.request.getproxies()` 也返回 `{}` —— 所以别在容器里找，找不到。
另一个佐证：这时候 `docker pull` 任何新镜像也会失败，报同一个 7890 地址。

解决：

1. 把代理软件开起来（Clash / v2ray 等，确认监听端口就是 7890）；或者
2. 关掉 Docker Desktop 的代理：Settings → Resources → Proxies，
   关掉 "Manual proxy configuration"，然后 Apply & Restart。

改完 Docker Desktop 设置要 **重启 Docker Desktop**，光 `docker restart 容器` 没用
（代理是守护进程层面注入的，重启容器不会重读）。

顺带说明：Windows 注册表里的 `ProxyEnable=0`（系统代理关闭）不影响 Docker，
这俩是两套独立配置。所以会出现"宿主机 Python 直连 12306 官网 200 正常，
容器里却出不去"的情况。

### C. `未检测到环境变量 DASHSCOPE_API_KEY`

工具清单能列出来说明 MCP 通了，只是没配 key，Agent 那段被跳过。回第 0 步。
`setx` 之后必须重开终端。

### D. 中文显示成乱码 `�人`

Windows 控制台编码问题。脚本开头已经处理了：

```python
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

如果是你自己写的调试脚本乱码，补上这行。

### E. 打 `/sse` 返回 404

这个 server 只有 `/mcp`。`transport` 要写 `"streamable_http"`。

### F. 其他

```bash
docker ps --filter name=mcp-server-12306     # 服务在跑吗
curl http://127.0.0.1:8080/                  # 端点通吗
docker logs --tail 50 mcp-server-12306       # server 侧看到请求了吗
```

`main()` 里的 `except` 就是把这三条打出来，别让人对着一个 502 发呆：

```python
except Exception as e:
    print(f"\n连接 MCP server 失败: {repr(e)}")
```

用 `repr(e)` 而不是 `str(e)` —— 能看到异常类型，区分是 key 失效、参数缺失、
服务没起还是模型侧问题。捕获异常时不要吞成"好像有点问题"这种没线索的提示。

## 自己动手改

按顺序做，难度递增：

1. 往 `DEMO_QUERIES` 里加一条 `"G101 途经哪些站"`，看模型会不会自己先调
   `get-train-no-by-train-code` 换 `train_no`。如果它直接把 `G101` 当
   `train_no` 传了，说明提示词规则 3 的表述还不够硬，改改看。
2. 把 `SYSTEM_PROMPT` 规则 1 整条删掉，重跑"明天深圳到武汉"。观察模型编了个什么日期出来。
   这是理解"为什么要写提示词"最直接的实验。
3. 加中转查询：问"深圳到拉萨怎么中转"，看它怎么用 `query-transfer`。
4. 把 `temperature` 调到 `0.9` 重跑几次，看回答稳定性的变化。
5. 接第二个 MCP server：`MultiServerMCPClient` 的配置字典本来就支持多个 key，
   加一个天气 server，让 Agent 能同时查票和查目的地天气。

## 和同目录 client_mcd.py 的对照

| | `client_12306.py` | `client_mcd.py` |
|---|---|---|
| server 位置 | 本地 Docker | 公网远程 |
| 协议 | HTTP 无鉴权 | HTTPS + Bearer token |
| 工具性质 | 7 个全只读 | 含写操作 |
| 额外防护 | 不需要 | 要维护写操作黑名单 |
| 主要坑 | 本机代理劫持 localhost | token 过期、误触写接口 |

先把这个跑通，再去看 `client_mcd.py` 怎么处理鉴权和写操作防护。

