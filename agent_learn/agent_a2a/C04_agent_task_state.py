from python_a2a import TaskState  # 只需相关导入
#TaskState是一个枚举类型
# 检查任务状态
if TaskState.COMPLETED == "completed":
    print("任务完成")
state = TaskState.CANCELED
print("转换后的状态值：", state.value)
print(state)