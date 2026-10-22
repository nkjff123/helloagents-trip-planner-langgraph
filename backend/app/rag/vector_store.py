"""Chroma 向量数据库管理模块"""

import os
from functools import lru_cache
from typing import Optional
from loguru import logger
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from app.config import get_settings

COLLECTION_NAME = "travel_knowledge"


def get_embeddings() -> OpenAIEmbeddings:
    """初始化 OpenAI 兼容 Embedding 模型"""
    settings = get_settings()
    api_key = (
        os.getenv("EMBEDDING_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or settings.openai_api_key
        or "sk-placeholder"
    )
    base_url = (
        os.getenv("EMBEDDING_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or settings.openai_base_url
        or "https://api.openai.com/v1"
    )
    return OpenAIEmbeddings(
        model=settings.embedding_model,
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
