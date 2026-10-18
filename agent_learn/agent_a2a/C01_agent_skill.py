from python_a2a import  AgentSkill
# 定义一个代理技能, 技能的小卡片
ticket_skill = AgentSkill(
    name="book_ticket",
    description="预订火车票的技能",
    examples=["预订从上海到北京的火车票"],
    input_modes=["text/plain"],
    output_modes=["text/plain"]
)

print(ticket_skill)
print(ticket_skill.to_dict())