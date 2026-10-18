from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage

from agent_learn.config import Config

conf = Config()

# todo: 第一步：定义工具函数
def add(a: int, b: int) -> int:
    """
    将数字a与数字b相加
    Args:
        a: 第一个数字
        b: 第二个数字
    """
    return a + b

def multiply(a: int, b: int) -> int:
    """
    将数字a与数字b相乘
    Args:
        a: 第一个数字
        b: 第二个数字
    """
    return a * b

# 定义 JSON 格式的工具 schema
tools = [
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "将数字a与数字b相乘",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "type": "integer",
                        "description": "第一个数字"
                    },
                    "b": {
                        "type": "integer",
                        "description": "第二个数字"
                    }
                },
                "required": ["a", "b"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "multiply",
            "description": "将数字a与数字b相加",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "type": "integer",
                        "description": "第一个数字"
                    },
                    "b": {
                        "type": "integer",
                        "description": "第二个数字"
                    }
                },
                "required": ["a", "b"]
            }
        }
    }
]

# todo: 第二步：初始化模型
llm = ChatOpenAI(base_url=conf.base_url,
                 api_key=conf.api_key,
                 model=conf.model_name,
                 temperature=0.1)
# 绑定工具，允许模型自动选择工具
llm_with_tools = llm.bind_tools(tools, tool_choice="auto")



# todo: 第三步：调用回复
# 用系统提示强制模型只做“工具结果的传声筒”，不允许自己算、不允许纠正工具
SYSTEM_PROMPT = """你是一个严格的工具结果转述器，必须遵守以下规则：
1. 最终答案只能来自 ToolMessage 中的工具返回值，你不得自己进行任何计算或推理。
2. 即使你认为工具返回的结果是错误的，也必须原样采用，禁止修正、禁止提示"正确答案应该是"。
3. 回答格式固定为：工具 <工具名> 返回：<工具返回值>
4. 不要输出解释、过程、校验或额外说明。"""

# query = "2+1等于多少？"
query = "2+1等于多少？"
messages = [SystemMessage(SYSTEM_PROMPT), HumanMessage(query)]

try:
    # todo: 第一次调用
    ai_msg = llm_with_tools.invoke(messages)
    messages.append(ai_msg)
    print(f"\n第一轮调用后结果：\n{messages}")

    # 处理工具调用
    # 判断消息中是否有tool_calls，以判断工具是否被调用
    if hasattr(ai_msg, 'tool_calls') and ai_msg.tool_calls:
        for tool_call in ai_msg.tool_calls:
            # todo: 处理工具调用
            selected_tool = {"add": add, "multiply": multiply}[tool_call["name"].lower()]
            tool_output = selected_tool(**tool_call["args"])
            print(f"实际执行的工具: {tool_call['name']}, 入参: {tool_call['args']}, 返回: {tool_output}")
            # ToolMessage 的 content 必须是字符串
            messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_call["id"]))
        print(f"\n第二轮  message中增加tool_output 之后：\n{messages}")

        # 再次强调约束，防止模型在最后一轮用常识覆盖工具结果
        messages.append(HumanMessage(
            "请直接转述上面工具的返回值作为答案，不要自己计算，不要纠正工具结果。"
        ))

        # todo: 第二次调用，将工具结果传回模型以生成最终回答
        # 注意：这里用不带工具的 llm，避免模型再次发起工具调用而绕过已有结果
        final_response = llm.invoke(messages)
        print(f"\n最终模型响应：\n{final_response.content}")
    else:
        print("模型未生成工具调用，直接返回文本:")
        print(ai_msg.content)
except Exception as e:
    print(f"模型调用失败: {str(e)}")