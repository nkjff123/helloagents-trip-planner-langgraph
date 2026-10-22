"""知识库多格式文档加载与元数据解析模块"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger
from langchain_core.documents import Document

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import docx2txt
except ImportError:
    docx2txt = None


def load_metadata_map(meta_json_path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """加载元数据配置映射表"""
    if not meta_json_path or not meta_json_path.exists():
        return {}
    try:
        with open(meta_json_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        meta_map = {}
        for item in items:
            fname = item.get("file_name", "")
            if fname:
                meta_map[fname] = item
        return meta_map
    except Exception as e:
        logger.warning(f"读取元数据文件失败 {meta_json_path}: {e}")
        return {}


def load_pdf_file(file_path: Path, base_meta: Dict[str, Any]) -> List[Document]:
    """使用 pypdf 加载 PDF 文档并记录页码"""
    if pypdf is None:
        logger.error("未安装 pypdf，跳过 PDF 解析")
        return []
    docs = []
    try:
        reader = pypdf.PdfReader(str(file_path))
        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = text.strip()
            if not text:
                continue
            meta = {
                **base_meta,
                "source": base_meta.get("source", str(file_path)),
                "file_name": file_path.name,
                "page": page_idx + 1,
            }
            docs.append(Document(page_content=text, metadata=meta))
    except Exception as e:
        logger.warning(f"解析 PDF 失败 {file_path.name}: {e}")
    return docs


def _extract_binary_doc_text(data: bytes) -> str:
    """针对 Word 97-2003 二进制 .doc 提取中文与文本片段"""
    import re
    chars = []
    for i in range(0, len(data) - 1, 2):
        chunk = data[i:i+2]
        try:
            ch = chunk.decode("utf-16le")
            if "一" <= ch <= "鿿" or ch.isalnum() or ch in "，。！？、；：“”‘’（）《》【】\n\r\t ":
                chars.append(ch)
            else:
                chars.append(" ")
        except Exception:
            chars.append(" ")
    raw_text = "".join(chars)
    raw_text = re.sub(r" {3,}", "\n", raw_text)
    meaningful_lines = [
        line.strip()
        for line in raw_text.splitlines()
        if len(line.strip()) > 8 and any("一" <= c <= "鿿" for c in line)
    ]
    return "\n".join(meaningful_lines)


def load_doc_file(file_path: Path, base_meta: Dict[str, Any]) -> List[Document]:
    """使用 docx2txt 加载 DOC/DOCX 文本，若为老旧二进制 .doc 则降级通过字节流解析"""
    text = ""
    if docx2txt is not None:
        try:
            text = docx2txt.process(str(file_path)) or ""
        except Exception:
            text = ""

    # 若 docx2txt 未解析出内容（如经典的 Word 97-2003 .doc），采用二进制文本提取
    if not text.strip():
        try:
            raw_bytes = file_path.read_bytes()
            text = _extract_binary_doc_text(raw_bytes)
        except Exception as e:
            logger.warning(f"二进制解析 DOC 失败 {file_path.name}: {e}")

    text = text.strip()
    if not text:
        return []

    meta = {
        **base_meta,
        "source": base_meta.get("source", str(file_path)),
        "file_name": file_path.name,
        "page": 1,
    }
    return [Document(page_content=text, metadata=meta)]


def load_text_file(file_path: Path, base_meta: Dict[str, Any]) -> List[Document]:
    """加载纯文本或 Markdown 文档"""
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            return []
        meta = {
            **base_meta,
            "source": base_meta.get("source", str(file_path)),
            "file_name": file_path.name,
            "page": 1,
        }
        return [Document(page_content=text, metadata=meta)]
    except Exception as e:
        logger.warning(f"解析文本文件失败 {file_path.name}: {e}")
        return []


def load_documents_from_directory(
    dir_path: str | Path,
    meta_json_path: Optional[str | Path] = None,
) -> List[Document]:
    """扫描并解析目录下所有 PDF、DOC、TXT、MD 文件，并附带结构化元数据"""
    path = Path(dir_path)
    if not path.exists():
        logger.warning(f"指定目录不存在: {path}")
        return []

    meta_json = Path(meta_json_path) if meta_json_path else None
    meta_map = load_metadata_map(meta_json)

    documents: List[Document] = []
    for file_path in path.iterdir():
        if not file_path.is_file():
            continue
        fname = file_path.name
        matched_meta = meta_map.get(fname, {})
        base_meta = {
            "doc_id": matched_meta.get("id", 0),
            "title": matched_meta.get("title", file_path.stem),
            "category": matched_meta.get("category", "综合攻略"),
            "year": matched_meta.get("year", 2026),
            "source": matched_meta.get("source", "知识库文档"),
        }

        ext = file_path.suffix.lower()
        if ext == ".pdf":
            documents.extend(load_pdf_file(file_path, base_meta))
        elif ext in [".doc", ".docx"]:
            documents.extend(load_doc_file(file_path, base_meta))
        elif ext in [".txt", ".md"]:
            documents.extend(load_text_file(file_path, base_meta))

    logger.info(f"目录 {path} 成功加载 {len(documents)} 个原始文档切片")
    return documents
