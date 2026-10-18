from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState

# 定义代理卡片
ticket_card = AgentCard(
    name="TicketAgentServer",
    description="票务代理",
    url="http://127.0.0.1:5010",
    skills=[AgentSkill(name="book_ticket", description="预订票务")]
)

# 自定义 A2AServer 子类
class TicketServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=ticket_card)

    def handle_task(self, task):
        print("收到A2A任务的task:=>", task)
        #默认写法：获取任务内容
        query = (task.message or {}).get("content", {}).get("text", "")

        if "上海" in query and "北京" in query:
        # 这里的结果可以来自于 MCP 模块，这里我们直接模拟结果
            train_result = "上海到北京的火车票已经预订成功！  G1001,10车1A "
        else:
            train_result = "请输入明确的出发地和目的地。"
        # task中添加 产物artifacts 和更新status
        task.artifacts = [{"parts": [{"type": "text", "text": train_result}]}]
        task.status = TaskStatus(state=TaskState.COMPLETED)
        print(f"[{self.agent_card.name} 日志] 任务处理完毕")
        print(f"[{self.agent_card.name} 日志] 输出结果task: {task}")
        print(f"[{self.agent_card.name} 日志] 输出结果task.artifacts: {task.artifacts}")
        return task

# 启动服务器
if __name__ == "__main__":
    server = TicketServer()
    print(f"[{server.agent_card.name}] 启动成功，服务地址: {server.agent_card.url}")
    run_server(server, host="127.0.0.1", port=5010, debug=True)