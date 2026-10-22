"""基于 LangChain 的 Agentic RAG 对话引擎"""

import os
import re
import json
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional
from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from app.config import get_settings
from app.rag.tools import search_tourism_knowledge

# 简单的进程内会话记忆
CONVERSATION_HISTORY: Dict[str, List[Any]] = {}


class StreamTagFilter:
    """流式过滤 <think> 与 <｜...｜> 等模型内部控制标记的缓冲过滤器"""

    def __init__(self):
        self.buffer = ""
        self.tag_patterns = [
            re.compile(r"<think>.*?</think>", re.DOTALL),
            re.compile(
                r"<[|｜]{1,2}DSML[|｜]{1,2}\s+calls>.*?</[|｜]{1,2}DSML[|｜]{1,2}\s+calls>",
                re.DOTALL,
            ),
            re.compile(
                r"<[|｜]{1,2}(?:tool_call|tool_calls)[|｜]{1,2}>.*?</?[|｜]{1,2}/?(?:tool_call|tool_calls)[|｜]{1,2}>",
                re.DOTALL,
            ),
            re.compile(r"<[|｜]{1,2}.*?[|｜]{1,2}>", re.DOTALL),
            re.compile(r"</[|｜]{1,2}.*?[|｜]{1,2}>", re.DOTALL),
        ]
        self.tag_starters = ["<think", "<|", "<｜", "</|", "</｜", "<tool_call"]

    def feed(self, chunk: str) -> str:
        self.buffer += chunk
        for pat in self.tag_patterns:
            self.buffer = pat.sub("", self.buffer)

        earliest_start = -1
        for starter in self.tag_starters:
            idx = self.buffer.find(starter)
            if idx != -1:
                if earliest_start == -1 or idx < earliest_start:
                    earliest_start = idx

        if earliest_start != -1:
            safe_text = self.buffer[:earliest_start]
            self.buffer = self.buffer[earliest_start:]
            return safe_text
        else:
            last_lt = self.buffer.rfind("<")
            if last_lt != -1:
                tail = self.buffer[last_lt:]
                is_prefix = any(s.startswith(tail) for s in self.tag_starters)
                if is_prefix:
                    safe_text = self.buffer[:last_lt]
                    self.buffer = self.buffer[last_lt:]
                    return safe_text

            safe_text = self.buffer
            self.buffer = ""
            return safe_text

    def flush(self) -> str:
        text = self.buffer
        self.buffer = ""
        for pat in self.tag_patterns:
            text = pat.sub("", text)
        text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL)
        text = re.sub(r"<[|｜]{1,2}.*$", "", text, flags=re.DOTALL)
        text = re.sub(r"</[|｜]{1,2}.*$", "", text, flags=re.DOTALL)
        return text


def parse_dsml_tool_calls(text: str) -> List[Dict[str, Any]]:
    """从文本中解析模型直接输出的 DeepSeek DSML 或 XML 格式工具调用标记"""
    tool_calls = []

    # 1. 匹配 DeepSeek DSML 标记: <｜｜DSML｜｜ invoke name="...">...</｜｜DSML｜｜ invoke>
    invoke_pattern = re.compile(
        r"<[|｜]{1,2}DSML[|｜]{1,2}\s+invoke\s+name=[\"\'](.*?)[\"\']\s*>(.*?)</[|｜]{1,2}DSML[|｜]{1,2}\s+invoke>",
        re.DOTALL,
    )
    param_pattern = re.compile(
        r"<[|｜]{1,2}DSML[|｜]{1,2}\s+parameter\s+name=[\"\'](.*?)[\"\'](?:\s+string=[\"\'](.*?)[\"\'])?\s*>(.*?)</[|｜]{1,2}DSML[|｜]{1,2}\s+parameter>",
        re.DOTALL,
    )

    invokes = invoke_pattern.findall(text)
    for idx, (tool_name, invoke_body) in enumerate(invokes):
        args: Dict[str, Any] = {}
        params = param_pattern.findall(invoke_body)
        for param_name, _, param_val in params:
            param_val = param_val.strip()
            try:
                parsed_val = json.loads(param_val)
                args[param_name] = parsed_val
            except Exception:
                args[param_name] = param_val

        if "query" in args and isinstance(args["query"], list):
            args["query"] = " ".join(str(q) for q in args["query"])

        tool_calls.append({
            "name": tool_name,
            "args": args,
            "id": f"call_dsml_{idx + 1}",
            "type": "tool_call",
        })

    # 2. 备用兜底：匹配常规 XML <tool_call> 格式
    if not tool_calls:
        xml_call_pattern = re.compile(
            r"<(?:tool_call|tool_calls)>(.*?)</(?:tool_call|tool_calls)>",
            re.DOTALL,
        )
        xml_calls = xml_call_pattern.findall(text)
        for idx, block in enumerate(xml_calls):
            name_m = re.search(r"<name>(.*?)</name>", block)
            tool_name = name_m.group(1).strip() if name_m else "search_tourism_knowledge"
            query_m = re.search(r"<query>(.*?)</query>", block)
            query_val = query_m.group(1).strip() if query_m else ""
            if not query_val:
                arg_m = re.search(r"<arguments>(.*?)</arguments>", block, re.DOTALL)
                if arg_m:
                    try:
                        args = json.loads(arg_m.group(1).strip())
                    except Exception:
                        args = {"query": arg_m.group(1).strip()}
                else:
                    args = {"query": ""}
            else:
                args = {"query": query_val}
            tool_calls.append({
                "name": tool_name,
                "args": args,
                "id": f"call_xml_{idx + 1}",
                "type": "tool_call",
            })

    return tool_calls


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
        "当用户询问具体的法律法规、维权流程、合同纠纷、安全守则或行业标准时，请务必调用知识库检索工具获取权威条款，并在回答中明确指出引用来源（如《旅游法》、《在线旅游平台住宿预订服务规范》）。\n"
        "如果用户的输入仅仅是日常问候（如'你好'、'谢谢'），请礼貌友好地直接回答，不要调用检索工具。\n"
        "【输出格式规范】严禁在文本中直接输出任何底层工具调用标签（例如 <｜｜DSML｜｜ calls>、<｜tool_calls｜> 等内部控制标记）。\n"
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

        has_native_tool_calls = bool(response.tool_calls)
        dsml_tool_calls = []
        if not has_native_tool_calls and (
            "DSML" in (response.content or "") or "<tool_call" in (response.content or "")
        ):
            dsml_tool_calls = parse_dsml_tool_calls(response.content)

        if has_native_tool_calls:
            # 路径 1: 模型返回了原生的 OpenAI tool_calls
            # 确保每一个 tool_call 均有有效 ID，避免部分模型返回空 ID 导致协议不匹配
            for idx, tool_call in enumerate(response.tool_calls):
                if not tool_call.get("id"):
                    tool_call["id"] = f"call_{idx + 1}"

            # 关键：带有 tool_calls 的 assistant 消息必须仅追加一次，并位于所有 tool 消息之前
            messages.append(response)

            for tool_call in response.tool_calls:
                tool_args = tool_call.get("args", {})
                query_str = tool_args.get("query", "")
                yield {
                    "type": "tool_start",
                    "content": f"正在查阅旅游知识库: {query_str}",
                }

                # 执行工具并兜底异常，确保每个 tool_call_id 都有对应的 ToolMessage 回复
                tool_id = tool_call.get("id", "call_1")
                try:
                    tool_result = await search_tourism_knowledge.ainvoke(tool_args)
                except Exception as tool_err:
                    logger.warning(f"知识库检索执行失败: {tool_err}")
                    tool_result = f"检索失败: {tool_err}"

                tool_msg = ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id,
                )
                messages.append(tool_msg)

            # 第二阶段引导语：明确告知模型检索完成，避免二次输出 DSML 标签
            messages.append(
                SystemMessage(
                    content=(
                        "【知识库检索已完成】请结合上述检索结果以及权威旅游法规与民法典常识，"
                        "为用户生成全面、专业、实用的步骤化解答。严禁输出任何工具调用标签（包括 <｜｜DSML｜｜>）或代码。"
                    )
                )
            )

            # 第二阶段：结合检索结果流式生成最终回复并经过 StreamTagFilter 过滤
            tag_filter = StreamTagFilter()
            full_content = ""
            async for chunk in llm.astream(messages):
                raw_token = chunk.content
                if isinstance(raw_token, list):
                    token = "".join(
                        part.get("text", "")
                        for part in raw_token
                        if isinstance(part, dict) and "text" in part
                    )
                else:
                    token = str(raw_token) if raw_token else ""

                if token:
                    clean_token = tag_filter.feed(token)
                    if clean_token:
                        full_content += clean_token
                        yield {"type": "token", "content": clean_token}

            rem = tag_filter.flush()
            if rem:
                full_content += rem
                yield {"type": "token", "content": rem}

            history.append(user_msg)
            history.append(AIMessage(content=full_content))
            yield {"type": "done"}

        elif dsml_tool_calls:
            # 路径 2: 模型在文本 content 中直接输出了 DSML/XML 格式，将其解析并转为检索
            logger.info(f"解析到模型输出的内联工具调用标记: {len(dsml_tool_calls)} 个")
            knowledge_snippets = []
            for tool_call in dsml_tool_calls:
                tool_args = tool_call.get("args", {})
                query_str = tool_args.get("query", "")
                yield {
                    "type": "tool_start",
                    "content": f"正在查阅旅游知识库: {query_str}",
                }
                try:
                    tool_result = await search_tourism_knowledge.ainvoke(tool_args)
                    knowledge_snippets.append(str(tool_result))
                except Exception as tool_err:
                    logger.warning(f"知识库检索执行失败: {tool_err}")
                    knowledge_snippets.append(f"检索失败: {tool_err}")

            combined_knowledge = "\n\n".join(knowledge_snippets)
            synthesis_messages = [
                *messages,
                SystemMessage(
                    content=(
                        f"【知识库检索结果】\n{combined_knowledge}\n\n"
                        "【回答要求】请结合上述检索到的旅游法规与行业规范，为用户的问题提供专业、清晰、权威的步骤化解答。"
                        "明确引用具体法规或规范条款（如《旅游法》、《在线旅游平台住宿预订服务规范》）。严禁输出任何工具调用标签（包括 <｜｜DSML｜｜>）或代码。"
                    )
                ),
            ]

            tag_filter = StreamTagFilter()
            full_content = ""
            async for chunk in llm.astream(synthesis_messages):
                raw_token = chunk.content
                if isinstance(raw_token, list):
                    token = "".join(
                        part.get("text", "")
                        for part in raw_token
                        if isinstance(part, dict) and "text" in part
                    )
                else:
                    token = str(raw_token) if raw_token else ""

                if token:
                    clean_token = tag_filter.feed(token)
                    if clean_token:
                        full_content += clean_token
                        yield {"type": "token", "content": clean_token}

            rem = tag_filter.flush()
            if rem:
                full_content += rem
                yield {"type": "token", "content": rem}

            history.append(user_msg)
            history.append(AIMessage(content=full_content))
            yield {"type": "done"}

        else:
            # 路径 3: 直接回复，无需检索
            raw_content = response.content or ""
            tag_filter = StreamTagFilter()
            clean_token = tag_filter.feed(raw_content)
            rem = tag_filter.flush()
            full_content = (clean_token + rem).strip()
            if not full_content:
                full_content = "您好！我是您的智能旅游顾问，请问有什么可以为您解答的吗？"

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
