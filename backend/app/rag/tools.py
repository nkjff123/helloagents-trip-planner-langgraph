"""LangChain 标准工具定义"""

from langchain.tools import tool
from loguru import logger
from app.rag.vector_store import get_retriever


@tool
def search_tourism_knowledge(query: str) -> str:
    """检索文化和旅游部官方旅游法规、投诉处理办法、旅游安全手册、示范合同与避坑指南。
    适合回答旅游纠纷索赔、跟团游退改、安全事故应对、景区服务规范等专业问题。"""
    try:
        retriever = get_retriever(k=4)
        docs = retriever.invoke(query)
        if not docs:
            return "未检索到相关的官方旅游知识库条目。"

        formatted_results = []
        for i, doc in enumerate(docs, 1):
            title = doc.metadata.get("title", "未命名文档")
            category = doc.metadata.get("category", "综合")
            page = doc.metadata.get("page", 1)
            content = doc.page_content.strip()
            formatted_results.append(
                f"[参考{i}] 来源：《{title}》（分类：{category}，第 {page} 页）\n{content}"
            )
        return "\n\n".join(formatted_results)
    except Exception as e:
        logger.error(f"知识库检索失败: {e}")
        return f"知识库检索遇到临时异常: {e}"
