from openai import base_url
from python_a2a import AIAgentRouter, AgentNetwork, OpenAIA2AClient
from langchain_openai import ChatOpenAI
from agent_learn.config import Config

conf=Config()

# 创建网络
network = AgentNetwork(name="MyNetwork")
network.add("TicketAgent", "http://127.0.0.1:5010")
network.add("WeatherServer","http://127.0.0.1:5011")

# 创建模型
# llm = ChatOpenAI(base_url=conf.base_url,
#                  api_key=conf.api_key,
#                  model=conf.model_name,
#                  temperature=0.1)

# todo: 错误写法，已注释：
#  AIAgentRouter.route_query内部走LLM路由分支时会调用 self.llm.send_message(message)，
#  这要求llm_client实现python_a2a.client.base.BaseA2AClient接口（有send_message方法）。
#  但ChatOpenAI（langchain_openai）没有send_message，调用会抛AttributeError，
#  被route_query内的except Exception悄悄吞掉，直接降级到_fallback_routing这套关键词打分兜底逻辑。
#  兜底逻辑按空格切词匹配，中文查询"预订票"和描述"票务代理"之间没有空格分词，
#  永远算不出关键词命中分数，score恒为0，代码里把score=0映射为固定confidence=0.1，
#  这就是"置信度只有0.1"的真正原因——根本没调用大模型，不是模型判断"没把握"。
# from langchain_openai import ChatOpenAI
# llm = ChatOpenAI(base_url=conf.base_url,
#                  api_key=conf.api_key,
#                  model=conf.model_name,
#                  temperature=0.1)
# # router = AIAgentRouter(llm_client=llm, agent_network=network)

# # todo: 正确写法：改用python_a2a自带的OpenAIA2AClient（实现了send_message），
# #  它是按OpenAI官方SDK构造的，不支持在构造函数里传base_url，
# #  所以先用api_key/model初始化，再手动覆盖内部client.base_url指向DashScope的兼容endpoint，
# #  这样route_query才能真正把路由请求发给qwen-plus，走到confidence=0.9这条正常分支。
llm = OpenAIA2AClient(api_key=conf.api_key, model=conf.model_name, temperature=0.1)
llm.client.base_url = conf.base_url

# 创建路由器
router = AIAgentRouter(llm_client=llm, agent_network=network)
#agent的名称  ,置信度
agent_name, confidence = router.route_query("查下火车票")
print(agent_name, confidence)