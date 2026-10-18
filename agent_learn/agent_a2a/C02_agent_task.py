from python_a2a import Task, Message, MessageRole, TextContent

# 创建任务
message = Message(content=TextContent(text="查询天气"), role=MessageRole.USER)
task = Task(message=message.to_dict())
print(task)