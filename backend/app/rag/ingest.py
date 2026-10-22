"""知识库批量与增量构建脚本"""

import hashlib
import json
from pathlib import Path
from typing import Dict, List
from loguru import logger
from app.config import get_settings
from app.rag.loader import load_documents_from_directory
from app.rag.splitter import split_documents
from app.rag.vector_store import get_vector_store


def calculate_file_hash(path: Path) -> str:
    """计算单个文件的 MD5 摘要"""
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def should_reindex(path: Path, cache: Dict[str, str]) -> bool:
    """检查文件是否发生变化需要重新索引"""
    current_hash = calculate_file_hash(path)
    return cache.get(str(path)) != current_hash


def run_ingest(force: bool = False) -> dict:
    """运行知识库构建流水线"""
    settings = get_settings()
    vector_dir = settings.get_vector_store_path()
    vector_dir.mkdir(parents=True, exist_ok=True)
    cache_file = vector_dir / ".index_cache.json"

    cache: Dict[str, str] = {}
    if cache_file.exists() and not force:
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # 扫描 resource/tourism_knowledge_documents 和 backend/data/knowledge
    base_dir = Path(__file__).resolve().parent.parent.parent
    resource_docs_dir = base_dir.parent / "resource" / "tourism_knowledge_documents"
    resource_meta_json = base_dir.parent / "resource" / "tourism_kb_sources.json"
    custom_docs_dir = base_dir / "data" / "knowledge"

    sources = [
        (resource_docs_dir, resource_meta_json),
        (custom_docs_dir, None),
    ]

    all_raw_docs = []
    files_to_index = []
    updated_cache = dict(cache)

    for doc_dir, meta_file in sources:
        if not doc_dir.exists():
            continue
        for f in doc_dir.iterdir():
            if f.is_file() and f.suffix.lower() in [".pdf", ".doc", ".docx", ".txt", ".md"]:
                if force or should_reindex(f, cache):
                    files_to_index.append(f)
                    updated_cache[str(f)] = calculate_file_hash(f)

    if not files_to_index and not force:
        logger.info("所有文档均未发生变更，跳过增量索引。")
        return {"status": "unchanged", "indexed_files": 0, "total_chunks": 0}

    logger.info(f"发现 {len(files_to_index)} 个需要索引的文档...")
    for doc_dir, meta_file in sources:
        docs = load_documents_from_directory(doc_dir, meta_file)
        all_raw_docs.extend(docs)

    splits = split_documents(all_raw_docs)
    logger.info(f"切分生成 {len(splits)} 个知识切片，正在写入 Chroma 向量库...")

    vector_store = get_vector_store()
    vector_store.add_documents(documents=splits)

    # 写入缓存
    cache_file.write_text(json.dumps(updated_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("知识库增量索引构建完成！")
    return {
        "status": "success",
        "indexed_files": len(files_to_index),
        "total_chunks": len(splits),
    }


if __name__ == "__main__":
    run_ingest()
