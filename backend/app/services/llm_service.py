"""LLM 服务模块 (支持结构化 Pydantic 模型安全生成与自愈校验)"""

import json
import re
from typing import Type, TypeVar, List, Dict, Any, Optional
from pydantic import BaseModel, ValidationError
from loguru import logger
from hello_agents import HelloAgentsLLM
from ..config import get_settings

T = TypeVar("T", bound=BaseModel)

# 全局 LLM 实例
_llm_instance: Optional[HelloAgentsLLM] = None


def get_llm() -> HelloAgentsLLM:
    """获取 LLM 实例 (单例模式)"""
    global _llm_instance

    if _llm_instance is None:
        settings = get_settings()

        # HelloAgentsLLM 会自动从环境变量读取配置 (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_ID 等)
        _llm_instance = HelloAgentsLLM()

        logger.info(
            f"LLM 服务初始化成功 | 提供商: {_llm_instance.provider} | 模型: {_llm_instance.model}"
        )

    return _llm_instance


def reset_llm():
    """重置 LLM 实例 (用于测试或重新配置)"""
    global _llm_instance
    _llm_instance = None


def extract_json_string(text: str) -> str:
    """从大模型原始回复中稳健提取合法 JSON 字符串

    支持:
    - 纯 JSON 文本
    - ```json ... ``` 形式的代码块
    - 前后包含推理文字或换行符的多行内容
    """
    if not text:
        raise ValueError("LLM 返回空响应，无法提取 JSON")

    trimmed = text.strip()

    # 1. 优先匹配 markdown json 代码块
    json_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", trimmed, re.IGNORECASE)
    if json_block_match:
        candidate = json_block_match.group(1).strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            return candidate
        if candidate.startswith("[") and candidate.endswith("]"):
            return candidate

    # 2. 匹配最外层花括号 {...} 或方括号 [...]
    first_brace = trimmed.find("{")
    last_brace = trimmed.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return trimmed[first_brace : last_brace + 1].strip()

    first_bracket = trimmed.find("[")
    last_bracket = trimmed.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        return trimmed[first_bracket : last_bracket + 1].strip()

    return trimmed


def generate_structured(
    schema: Type[T],
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    max_retries: int = 2,
    **kwargs
) -> T:
    """调用 LLM 生成符合指定 Pydantic 模式的结构化数据

    保证:
    1. 动态注入 JSON Schema 与输出约束指令
    2. 使用 response_format={"type": "json_object"} 强制 JSON 格式
    3. 自动清洗 Markdown 与杂质字符
    4. 内置 Pydantic 校验与失败自愈修补循环 (Self-Correction Loop)

    Args:
        schema: 目标 Pydantic 数据模型类
        messages: 初始提示词消息列表 [{"role": "...", "content": "..."}]
        temperature: 采样温度 (默认 0.2 以保障遵循度)
        max_retries: 校验失败最大修补重试次数

    Returns:
        解析后的 Pydantic 模型实例
    """
    llm = get_llm()
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)

    # 构造强约束 Schema 系统要求
    schema_instruction = (
        "\n\n【输出格式铁律】\n"
        "你必须且只能输出严格符合以下 JSON Schema 的单一合法 JSON 对象。\n"
        "禁止输出任何 Markdown 代码块标记（如 ```json），禁止包含任何前后解释文字、说明或思考过程。\n"
        f"目标 JSON Schema:\n{schema_json}\n"
    )

    call_messages = list(messages)
    # 将格式要求附加到最后一条消息中
    if call_messages:
        last_msg = dict(call_messages[-1])
        last_msg["content"] = last_msg["content"] + schema_instruction
        call_messages[-1] = last_msg
    else:
        call_messages = [{"role": "user", "content": schema_instruction}]

    current_retries = 0
    last_raw_response = ""
    last_error: Optional[Exception] = None

    while current_retries <= max_retries:
        try:
            logger.debug(f"执行结构化输出调用 (尝试 {current_retries + 1}/{max_retries + 1})...")

            # 调用底层模型，尝试开启 json_object 模式
            raw_response = llm.invoke(
                messages=call_messages,
                temperature=temperature,
                response_format={"type": "json_object"},
                **kwargs
            )
            last_raw_response = raw_response

            # 清洗并提取纯 JSON 字符串
            clean_json = extract_json_string(raw_response)

            # 使用 Pydantic 严格反序列化校验
            validated_obj = schema.model_validate_json(clean_json)
            return validated_obj

        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_error = e
            current_retries += 1
            logger.warning(
                f"结构化输出校验未通过 (尝试 {current_retries}/{max_retries + 1}): {str(e)}"
            )

            if current_retries > max_retries:
                break

            # 自愈反馈消息：将具体校验报错精准反馈给大模型进行定向纠错
            error_feedback = (
                f"你上一次输出的内容未通过校验，具体错误信息如下：\n"
                f"{str(e)}\n\n"
                f"请仔细对照目标 JSON Schema，纠正错误并重新输出完整的纯 JSON 对象："
            )

            call_messages.append({"role": "assistant", "content": last_raw_response})
            call_messages.append({"role": "user", "content": error_feedback})

    error_msg = f"LLM 结构化输出重试 {max_retries} 次后仍失败: {str(last_error)}"
    logger.error(error_msg)
    logger.error(f"最后一次原始响应: {last_raw_response[:500]}...")
    raise ValueError(error_msg) from last_error
