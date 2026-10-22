"""AI 对话与 RAG 助手路由模块"""

import json
from typing import Any, Dict, Optional
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger
from app.rag.agent import generate_chat_stream
from app.rag.vector_store import get_vector_store

router = APIRouter()


class ChatStreamRequest(BaseModel):
    """对话请求模型"""
    message: str = Field(..., min_length=1, description="用户提问内容")
    conversation_id: str = Field(..., min_length=1, description="会话唯一标识")
    current_trip_context: Optional[Dict[str, Any]] = Field(
        None, description="当前页面行程上下文（目的地、天数、POI列表等）"
    )


@router.post("/stream", summary="发送消息并流式接收回复 (SSE)")
async def chat_stream(request: ChatStreamRequest):
    """以 Server-Sent Events (SSE) 格式流式输出 AI 思考、知识检索与回答 Token"""
    async def event_generator():
        try:
            async for event in generate_chat_stream(
                message=request.message,
                conversation_id=request.conversation_id,
                trip_context=request.current_trip_context,
            ):
                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as e:
            logger.error(f"SSE 流式推送异常: {e}")
            err_payload = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"data: {err_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status", summary="获取知识库状态统计")
async def get_rag_status():
    """返回当前已持久化的知识库切片数与状态"""
    try:
        store = get_vector_store()
        total_chunks = store._collection.count()
        return {
            "status": "ready",
            "total_chunks": total_chunks,
            "collection_name": store._collection.name,
        }
    except Exception as e:
        logger.warning(f"获取知识库状态失败: {e}")
        return {
            "status": "not_initialized",
            "total_chunks": 0,
            "error": str(e),
        }
