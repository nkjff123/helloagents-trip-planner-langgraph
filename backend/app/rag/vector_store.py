"""Chroma 向量数据库管理模块"""

import os
from functools import lru_cache
from typing import Optional
from loguru import logger
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from app.config import get_settings

COLLECTION_NAME = "travel_knowledge"


def get_embeddings():
    """初始化 Embedding 模型（支持 OpenAI 兼容 API，并在 DeepSeek 等无 embedding 接口场景智能降级为本地确定性向量）"""
    settings = get_settings()
    emb_api_key = os.getenv("EMBEDDING_API_KEY")
    emb_base_url = os.getenv("EMBEDDING_BASE_URL")
    emb_model = os.getenv("EMBEDDING_MODEL") or settings.embedding_model

    llm_base_url = (os.getenv("LLM_BASE_URL") or settings.openai_base_url or "").lower()

    # 如果显式配置了 EMBEDDING_BASE_URL，直接使用
    if emb_base_url:
        return OpenAIEmbeddings(
            model=emb_model,
            api_key=emb_api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "sk-placeholder",
            base_url=emb_base_url,
        )

    # 如果当前主要 LLM 是 deepseek，而又没有单独指定 EMBEDDING_BASE_URL
    if "deepseek.com" in llm_base_url:
        logger.warning(
            "当前 LLM 为 DeepSeek（无官方 Embedding 接口），且未配置 EMBEDDING_BASE_URL。"
            "已自动启用本地确定性向量 (DeterministicFakeEmbedding) 进行安全向量化。"
            "如需商用级在线语义检索，建议在 .env 中设置 EMBEDDING_BASE_URL 与 EMBEDDING_API_KEY (如 SiliconFlow/DashScope/OpenAI)。"
        )
        from langchain_core.embeddings import DeterministicFakeEmbedding
        return DeterministicFakeEmbedding(size=1536)

    api_key = (
        emb_api_key
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or settings.openai_api_key
        or "sk-placeholder"
    )
    base_url = os.getenv("LLM_BASE_URL") or settings.openai_base_url or "https://api.openai.com/v1"
    return OpenAIEmbeddings(
        model=emb_model,
        api_key=api_key,
        base_url=base_url,
    )


@lru_cache(maxsize=1)
def get_vector_store(persist_directory: Optional[str] = None) -> Chroma:
    """获取或初始化 Chroma 向量数据库实例"""
    settings = get_settings()
    dir_path = persist_directory or str(settings.get_vector_store_path())
    embeddings = get_embeddings()
    logger.info(f"初始化 Chroma 向量库: {dir_path}, Collection: {COLLECTION_NAME}")
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=dir_path,
    )


def get_retriever(k: int = 4):
    """获取标准检索器实例"""
    store = get_vector_store()
    return store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )
