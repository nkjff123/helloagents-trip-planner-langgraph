"""文本分块模块"""

from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def split_documents(
    docs: List[Document],
    chunk_size: int = 600,
    chunk_overlap: int = 80,
) -> List[Document]:
    """使用递归字符切分器拆分文档，保留元数据与字符偏移"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
        add_start_index=True,
    )
    splits = splitter.split_documents(docs)
    for split in splits:
        # 为切片前缀补充来源标题，提升语义搜索精准度
        title = split.metadata.get("title", "")
        if title and not split.page_content.startswith(f"【{title}】"):
            split.page_content = f"【{title}】\n{split.page_content}"
    return splits
