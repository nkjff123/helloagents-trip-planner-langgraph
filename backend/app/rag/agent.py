"""基于 LangChain 的 Agentic RAG 对话引擎"""

import os
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional
from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from app.config import get_settings
from app.rag.tools import search_tourism_knowledge

# 简单的进程内会话记忆
CONVERSATION_HISTORY: Dict[str, List[Any]] = {}


def get_chat_model() -> ChatOpenAI:
    """获取聊天模型实例"""
    settings = get_settings()
    api_key = (
        os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or settings.openai_api_key
        or "sk-placeholder"
    )
    base_url = (
        os.getenv("LLM_BASE_URL")
        or settings.openai_base_url
        or "https://api.openai.com/v1"
    )
    model = (
        os.getenv("LLM_MODEL_ID")
        or settings.openai_model
        or "gpt-4"
    )
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
        streaming=True,
    )


def build_system_prompt(trip_context: Optional[Dict[str, Any]] = None) -> str:
    """构建系统提示词，支持动态注入当前行程上下文"""
    base_prompt = (
        "你是一个专业的智能旅游咨询助手与旅游权益顾问。\n"
        "你可以为用户解答行程规划疑问、旅游避坑建议、紧急安全自救常识，以及依据国家文旅部法规进行维权指导。\n"
        "当用户询问具体的法律法规、维权流程、合同纠纷、安全守则或行业标准时，请务必调用知识库检索工具获取权威条款，并在回答中明确指出引用来源（如《旅游法》、《旅游安全实务手册》）。\n"
        "如果用户的输入仅仅是日常问候（如'你好'、'谢谢'），请礼貌友好地直接回答，不要调用检索工具。\n"
    )
    if trip_context:
        city = trip_context.get("destination", trip_context.get("city", ""))
        days = trip_context.get("days", "")
        pois = trip_context.get("poi_names", [])
        poi_str = "、".join(pois) if isinstance(pois, list) else str(pois)
        trip_info = (
            f"\n【当前用户正在浏览的行程背景】\n"
            f"- 目的地：{city}\n"
            f"- 行程天数：{days}天\n"
            f"- 包含景点/地点：{poi_str}\n"
            "如果用户的提问与当前行程相关，请结合当前行程进行分析与建议；如果是独立问题，请专注回答问题本身。\n"
        )
        base_prompt += trip_info
    return base_prompt


async def generate_chat_stream(
    message: str,
    conversation_id: str,
    trip_context: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """生成流式对话事件"""
    if conversation_id not in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[conversation_id] = []

    history = CONVERSATION_HISTORY[conversation_id]
    system_prompt = build_system_prompt(trip_context)

    # 组装消息列表
    messages: List[Any] = [SystemMessage(content=system_prompt)]
    messages.extend(history[-6:])  # 保留最近 3 轮对话
    user_msg = HumanMessage(content=message)
    messages.append(user_msg)

    llm = get_chat_model()
    llm_with_tools = llm.bind_tools([search_tourism_knowledge])

    try:
        # 第一阶段：判断是否需要调用工具
        response = await llm_with_tools.ainvoke(messages)

        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_args = tool_call.get("args", {})
                query_str = tool_args.get("query", "")
                yield {
                    "type": "tool_start",
                    "content": f"正在查阅旅游知识库: {query_str}",
                }

                # 执行工具
                tool_result = await search_tourism_knowledge.ainvoke(tool_args)
                tool_msg = ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_call.get("id", "call_1"),
                )
                messages.append(response)
                messages.append(tool_msg)

            # 第二阶段：结合检索结果流式生成最终回复
            full_content = ""
            async for chunk in llm.astream(messages):
                token = chunk.content
                if token:
                    full_content += token
                    yield {"type": "token", "content": token}

            history.append(user_msg)
            history.append(AIMessage(content=full_content))
            yield {"type": "done"}
        else:
            # 直接回复，无需检索
            full_content = response.content or ""
            # 流式逐字/逐词模拟吐出，或直接吐出
            yield {"type": "token", "content": full_content}
            history.append(user_msg)
            history.append(AIMessage(content=full_content))
            yield {"type": "done"}

    except asyncio.CancelledError:
        logger.info(f"客户端取消连接: {conversation_id}")
    except Exception as e:
        logger.error(f"对话生成异常: {e}")
        yield {"type": "error", "content": f"对话生成遇到异常: {str(e)}"}
        yield {"type": "done"}
