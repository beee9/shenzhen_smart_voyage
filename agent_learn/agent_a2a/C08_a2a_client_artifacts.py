import asyncio
from python_a2a import A2AClient

async def main():
    ticket_client = A2AClient("http://127.0.0.1:5010")

    #预订火车票
    ticket_query = "预订一张从北京到上海的火车票"
    print(f"[主控客户端日志]预订票务 -> '{ticket_query}'")
    ticket_result = ticket_client.ask(ticket_query)
    print(f"[主控客户端日志] 收到票务预订结果: {ticket_result}")

if __name__ == "__main__":
    asyncio.run(main())