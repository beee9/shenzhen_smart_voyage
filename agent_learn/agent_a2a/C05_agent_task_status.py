from python_a2a import TaskStatus, TaskState

status_completed = TaskStatus(
    state=TaskState.COMPLETED,
    message={"info": "任务成功完成"}
)

status_failed = TaskStatus(
    state=TaskState.FAILED,
    message={"error": "无法处理请求"}
)

# 打印字典表示
print("完成状态：", status_completed.to_dict())
print("失败状态：", status_failed.to_dict())