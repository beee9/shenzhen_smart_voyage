"""图的共享状态定义。

对应 a2a_case 里的 Task 对象：
    Task.message.content.text  ->  state["query"]
    Task.artifacts             ->  state["artifacts"]
    Task.status                ->  state["status"]

区别在于 A2A 的 Task 是跨进程传输的 JSON，而这里的 State 只是
一个进程内的字典，节点之间直接传引用，没有网络开销。
"""

from typing import Annotated, Any, TypedDict
import operator


class TravelState(TypedDict):
    """在图中流转的状态。"""

    # 用户原始问题（入口写入，全程只读）
    query: str

    # 路由结果：选中的专家节点名 + 置信度
    agent_name: str
    confidence: float

    # 最终产物，沿用 A2A 的 artifacts 结构，方便和原案例对照：
    # [{"parts": [{"type": "text", "text": "..."}]}]
    artifacts: list[dict[str, Any]]

    # 任务状态，对应 A2A 的 TaskState
    status: str

    # 执行轨迹。Annotated + operator.add 表示"累加"而不是"覆盖"，
    # 每个节点 return {"logs": [...]} 都会追加到列表尾部。
    logs: Annotated[list[str], operator.add]


# 与 A2A 的 TaskState 对齐的几个常量
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def make_artifact(text: str) -> list[dict[str, Any]]:
    """把一段文本包装成 A2A artifacts 格式。"""
    return [{"parts": [{"type": "text", "text": text}]}]


def read_artifact_text(artifacts: list[dict[str, Any]]) -> str:
    """从 artifacts 里取出第一段文本，等价于 A2AClient.ask() 内部做的事。"""
    if not artifacts:
        return ""
    parts = artifacts[0].get("parts", [])
    if not parts:
        return ""
    return str(parts[0].get("text", ""))
