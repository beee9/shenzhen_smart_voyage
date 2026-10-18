# 排障记录：test_query_tour_group 失败，报 `'data'`

## 现象

```
SmartVoage - INFO  - 查询旅游团: query='想看雪山的地方', city='None'
SmartVoage - ERROR - 旅游团 RAG 查询错误: 'data'
AssertionError: 'error' != 'success'
```

日志里那句 `旅游团 RAG 查询错误: 'data'` 是全部线索。它长得像"没有 data 字段"，
但更准确的读法是：**这是一个 `KeyError`，被 `except Exception as e` 抓住后用
`str(e)` 打印了出来。`KeyError` 的 `str()` 只有键名，所以你只看到一个孤零零的 `'data'`。**

Milvus 那三条 `PyMilvusDeprecationWarning` 是无关噪音，只是提醒 ORM 风格 API 将在
PyMilvus 3.1 移除。protobuf 的版本警告同理。**它们都不是失败原因。**

## 根因

`SmartVoyage/mcp_server/mcp_trip_server.py:28`，`get_embedding()` 里把
**模型名填成了 URL**：

```python
payload = {
    "model": conf.embedding_url,     # ← 错。这里是 embeddings 接口地址
    "input": [text],
    "dimensions": conf.embedding_dim
}
response = requests.post(conf.embedding_url, headers=headers, json=payload, timeout=30)
return response.json()["data"][0]["embedding"]      # ← KeyError 在这一行爆
```

`conf.embedding_url` 和 `conf.embedding_model` 是两个不同的配置项
（`SmartVoyage/config.py:40-41`）：

```python
self.embedding_url   = 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings'
self.embedding_model = 'text-embedding-v3'
```

`model` 字段应该用 `embedding_model`。现在传了 URL 进去，DashScope 认不出这个模型名，
返回 **HTTP 404**：

```json
{
  "error": {
    "message": "The model `https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings` does not exist or you do not have access to it.",
    "type": "invalid_request_error",
    "code": "model_not_found"
  },
  "request_id": "..."
}
```

响应体里只有 `error` 和 `request_id`，没有 `data`。代码不看状态码直接
`response.json()["data"]` → `KeyError: 'data'` → 被外层捕获 → 测试拿到
`status == "error"` → 断言失败。

改成 `"model": conf.embedding_model` 后同一个请求返回 HTTP 200，响应体带
`data / object / model / usage / id`，`data[0]["embedding"]` 正常取到 1024 维向量。
（已实测验证过两种写法的返回。）

## 为什么初始化脚本没这个问题

`SmartVoyage/docker/data_init/init_tour_group_rag.py:322-327` 的同名函数是对的：

```python
payload = {
    "model": conf.embedding_model,   # ← 正确
    "input": [text],
    "dimensions": conf.embedding_dim
}
response = requests.post(EMBEDDING_URL, headers=headers, json=payload, timeout=30)
```

两处逻辑重复但只改对了一处，是这个 bug 的由来。**入库时用 `text-embedding-v3`，
查询时如果换成别的模型，向量空间不一致，检索结果会毫无意义** —— 所以这两处必须严格一致，
最好抽成一个共享函数，而不是各写一遍。

## 修复

`mcp_trip_server.py:28` 一行：

```python
-    "model": conf.embedding_url,
+    "model": conf.embedding_model,
```

## 顺带值得改的两点

这次调试之所以费劲，是因为错误信息把线索藏起来了。两个可以改进的地方：

**1. 不检查 HTTP 状态码。** 加一行 `raise_for_status()`，错误就会自己说话：

```python
response = requests.post(conf.embedding_url, headers=headers, json=payload, timeout=30)
response.raise_for_status()      # 404 会抛出带 URL 和状态码的异常
return response.json()["data"][0]["embedding"]
```

更好的做法是把接口返回的 `error.message` 也带上，那句话直接点名了问题：

```python
data = response.json()
if "data" not in data:
    raise RuntimeError(f"Embedding API 调用失败: {data.get('error', data)}")
return data["data"][0]["embedding"]
```

**2. 日志丢了异常类型。** 现在打的是 `str(e)`，`KeyError` 就只剩键名。
换成 `repr(e)` 能看到 `KeyError('data')`，至少知道是哪一类错：

```python
logger.error(f"旅游团 RAG 查询错误: {repr(e)}")
```

配 `logger.exception(...)` 打完整栈更好，能直接定位到是哪一行取 `["data"]` 失败的。

## 复现与验证

单独验证 embedding 接口（不依赖 Milvus）：

```bash
python -c "
import requests
from SmartVoyage.config import Config
conf = Config()
h = {'Authorization': f'Bearer {conf.api_key}', 'Content-Type': 'application/json'}
r = requests.post(conf.embedding_url, headers=h,
                  json={'model': conf.embedding_model, 'input': ['测试'],
                        'dimensions': conf.embedding_dim}, timeout=30)
print(r.status_code, list(r.json().keys()))
"
# 期望: 200 ['data', 'object', 'model', 'usage', 'id']
```

再跑测试：

```bash
python -m unittest SmartVoyage.tests.test_mcp_servers_02.TestTripMCPIntegration.test_query_tour_group -v
```

如果改完 `model` 还是失败，按这个顺序往下查：

| 报错 | 断在哪 | 查什么 |
|------|--------|--------|
| `KeyError: 'data'` 仍在 | embedding 接口 | key 是否过期、余额、`DASHSCOPE_API_KEY` 环境变量是否设了 |
| `collection not found` | Milvus | `tour_groups` 集合建了吗，跑过 `init_tour_group_rag.py` 没有 |
| 检索结果为空 | Milvus 数据 | 集合建了但没插数据，或 `city` 过滤条件没匹配上 |
| 连接超时 | Milvus 服务 | `docker ps --filter name=milvus-standalone` |
| 相似度结果离谱 | 向量空间 | 入库和查询用的 embedding 模型/维度是否一致 |
