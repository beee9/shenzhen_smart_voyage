from python_a2a import AgentNetwork
network = AgentNetwork(name="MyNetwork")
network.add("TicketAgent", "http://127.0.0.1:5010")

print(f"agent network-->{network.agent_cards}")
print('*'*80)

# 调用
client = network.get_agent("TicketAgent")
print(client.ask("预订一张从北京到上海的火车票"))