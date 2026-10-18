import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

from SmartVoyage.chat_service import ChatService

app = FastAPI(title="SmartVoyage API", description="基于A2A的旅行智能助手")
chat_service = ChatService()


class ChatRequest(BaseModel):
    message: str


class ProfileRequest(BaseModel):
    profile: dict


async def sse_generator(message: str):
    """
    SSE 流式生成器。

    注意：ChatService.chat 没有提供真正的流式接口（内部要等子代理返回后才能汇总），
    这里是拿到完整回复后按片段下发的伪流式，仅为适配前端的 SSE 消费方式。
    """
    try:
        response = await chat_service.chat(message)
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    chunk_size = 20
    for i in range(0, len(response), chunk_size):
        chunk = response[i:i + chunk_size]
        yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """发送消息，获取回复"""
    response = await chat_service.chat(request.message)
    return {"status": "success", "message": response}


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """发送消息，流式获取回复（SSE）"""
    return StreamingResponse(sse_generator(request.message), media_type="text/event-stream")


@app.get("/api/memory")
async def get_memory():
    """获取记忆状态"""
    return {"status": "success", "data": chat_service.get_memory_state()}


@app.post("/api/memory/profile")
async def update_profile(request: ProfileRequest):
    """更新用户偏好"""
    chat_service.update_user_profile(request.profile)
    return {"status": "success", "message": "用户偏好已更新"}


@app.post("/api/memory/clear")
async def clear_memory():
    """清空全部记忆（短期对话、偏好、任务上下文、查询历史）"""
    chat_service.clear_memory()
    return {"status": "success", "message": "记忆已清空"}


@app.get("/api/agents")
async def get_agents():
    """获取代理卡片信息"""
    return {"status": "success", "data": chat_service.get_agent_cards()}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8088, log_level="info")