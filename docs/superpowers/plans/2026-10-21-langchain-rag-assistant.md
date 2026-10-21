# LangChain RAG Conversational Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a conversational AI travel assistant with LangChain-powered Agentic RAG, indexing 15 official regulatory and safety documents from `resource/tourism_knowledge_documents/`, streaming SSE responses, and dynamically enriching queries with the user's current trip plan context.

**Architecture:** A decoupled RAG domain module (`backend/app/rag/`) handles document loading (`pypdf`, `docx2txt`), chunking (`RecursiveCharacterTextSplitter`), embedding/vector storage (`langchain-openai`, `langchain-chroma`), and an Agentic RAG engine with a custom `@tool` retriever. The FastAPI backend exposes `/api/chat/stream` via Server-Sent Events, and the Vue 3 frontend renders a persistent floating assistant (`ChatAssistant.vue`) with typewriter streaming and source citation tags.

**Tech Stack:** Python 3.11, LangChain (`langchain`, `langchain-core`, `langchain-openai`, `langchain-chroma`, `langchain-text-splitters`), ChromaDB, FastAPI, SSE (`StreamingResponse`), Vue 3, TypeScript, Ant Design Vue.

**Spec:** `docs/superpowers/specs/2026-10-21-langchain-rag-assistant-design.md`

## Global Constraints

- Python interpreter: `D:\anaconda3\envs\agent\python.exe` (Windows) / `/d/anaconda3/envs/agent/python.exe` (Git Bash).
- Node & npm: `D:\nodejs\node.exe` & `D:\nodejs\npm.cmd`.
- Test command: `D:\anaconda3\envs\agent\python.exe -m unittest <test_module>` executed from `backend/`.
- Frontend build command: `npm run build` executed from `frontend/`.
- Vector store data directory: `backend/data/vector_store/` (must be ignored in `.gitignore`).
- No hallucinated retrieval: retrieval tool must return structured citations with document title, category, and page.
- Streaming responses must use standard SSE lines: `data: <json>\n\n`.

## Review Focus

1. **Non-existent or corrupted document files in ingestion pipeline**: Loader must log warnings and continue parsing remaining valid files rather than crashing the batch process.
2. **Missing or empty OpenAI API key**: RAG services and endpoints must fail gracefully with descriptive 503/400 errors instead of unhandled 500 exceptions.
3. **Empty or purely conversational queries**: Agent must respond politely without forcing unnecessary retrieval tool calls when the user simply says "你好" or "谢谢".
4. **SSE client abort / connection dropped**: Streaming response generator must handle client disconnection (`asyncio.CancelledError`) cleanly without leaking memory or open connections.
5. **Trip context injection when no active trip exists**: Context builder must seamlessly handle null or empty `current_trip_context` and fall back to general travel consultant persona.

---

### Task 1: Backend Dependencies & Configuration Extension

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/config.py`
- Modify: `.gitignore`
- Create: `backend/tests/test_rag_config.py`

**Interfaces:**
- Consumes: `pydantic_settings.BaseSettings`
- Produces:
  - `Settings.embedding_model: str` (default: `"text-embedding-3-small"`)
  - `Settings.vector_store_dir: str` (default: `"data/vector_store"`)
  - `Settings.get_vector_store_path() -> Path`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_rag_config.py
import unittest
from pathlib import Path
from app.config import Settings


class TestRAGConfig(unittest.TestCase):
    """验证 RAG 与 Embedding 配置项"""

    def test_rag_settings_defaults(self):
        settings = Settings(
            openai_api_key="test-key",
            amap_api_key="test-amap",
        )
        self.assertEqual(settings.embedding_model, "text-embedding-3-small")
        self.assertEqual(settings.vector_store_dir, "data/vector_store")
        vector_path = settings.get_vector_store_path()
        self.assertIsInstance(vector_path, Path)
        self.assertTrue(str(vector_path).endswith("vector_store"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_rag_config` (from `backend/`)
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'embedding_model'`

- [ ] **Step 3: Add dependencies and configuration**

Update `backend/requirements.txt` to append:
```txt
# LangChain 与 RAG 核心依赖
langchain>=0.3.0
langchain-core>=0.3.0
langchain-openai>=0.2.0
langchain-chroma>=0.1.4
langchain-text-splitters>=0.3.0

# 文档解析支持
pypdf>=5.0.0
docx2txt>=0.8
```

Update `backend/app/config.py`:
```python
    # RAG 与 向量库配置
    embedding_model: str = "text-embedding-3-small"
    vector_store_dir: str = "data/vector_store"

    def get_vector_store_path(self) -> Path:
        """获取向量数据库持久化目录路径"""
        base_dir = Path(__file__).resolve().parent.parent
        return base_dir / self.vector_store_dir
```

Ensure `backend/data/vector_store/` is added to `.gitignore`.
Install the new requirements in conda agent environment:
`D:\anaconda3\envs\agent\python.exe -m pip install -r backend/requirements.txt`

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_rag_config`
Expected: PASS (1 test, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/tests/test_rag_config.py .gitignore
git commit -m "feat(rag): add langchain dependencies and rag configuration"
```

---

### Task 2: Document Loading & Metadata Ingestion Module

**Files:**
- Create: `backend/app/rag/__init__.py`
- Create: `backend/app/rag/loader.py`
- Create: `backend/tests/test_rag_loader.py`

**Interfaces:**
- Consumes: `resource/tourism_knowledge_documents/*`, `resource/tourism_kb_sources.json`
- Produces:
  - `load_documents_from_directory(dir_path: str | Path, meta_json_path: str | Path | None = None) -> list[Document]`
  - `Document.page_content: str`
  - `Document.metadata: dict` with keys `{"doc_id", "title", "category", "year", "source", "page", "file_name"}`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_rag_loader.py
import json
import tempfile
import unittest
from pathlib import Path
from app.rag.loader import load_documents_from_directory


class TestRAGLoader(unittest.TestCase):
    """测试多格式文档加载与元数据注入"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 写入测试 txt
        txt_file = self.dir_path / "sample_tips.txt"
        txt_file.write_text("去西安旅游一定要提前预约陕历博门票。", encoding="utf-8")

        # 写入测试 json 映射
        self.meta_json = self.dir_path / "metadata.json"
        meta_data = [
            {
                "file_name": "sample_tips.txt",
                "id": 99,
                "title": "西安避坑指南",
                "category": "城市攻略",
                "year": 2026,
                "source": "官方推荐",
            }
        ]
        self.meta_json.write_text(json.dumps(meta_data, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_documents_with_metadata(self):
        docs = load_documents_from_directory(self.dir_path, self.meta_json)
        self.assertGreaterEqual(len(docs), 1)
        doc = docs[0]
        self.assertIn("提前预约陕历博", doc.page_content)
        self.assertEqual(doc.metadata["title"], "西安避坑指南")
        self.assertEqual(doc.metadata["category"], "城市攻略")
        self.assertEqual(doc.metadata["doc_id"], 99)

    def test_corrupted_or_empty_file_handled_gracefully(self):
        bad_file = self.dir_path / "corrupted.pdf"
        bad_file.write_bytes(b"not a valid pdf binary content")
        docs = load_documents_from_directory(self.dir_path, self.meta_json)
        # 应该依然能解析出 sample_tips.txt，不抛异常崩溃
        self.assertTrue(any("陕历博" in d.page_content for d in docs))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_rag_loader`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rag.loader'`

- [ ] **Step 3: Implement `backend/app/rag/loader.py`**

```python
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


def load_doc_file(file_path: Path, base_meta: Dict[str, Any]) -> List[Document]:
    """使用 docx2txt 加载 DOC/DOCX 文本"""
    if docx2txt is None:
        logger.error("未安装 docx2txt，跳过 DOC 解析")
        return []
    try:
        text = docx2txt.process(str(file_path)) or ""
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
    except Exception as e:
        logger.warning(f"解析 DOC 失败 {file_path.name}: {e}")
        return []


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_rag_loader`
Expected: PASS (2 tests, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/loader.py backend/app/rag/__init__.py backend/tests/test_rag_loader.py
git commit -m "feat(rag): implement multi-format document loader and metadata parser"
```

---

### Task 3: Text Splitting, Vector Store & Incremental Ingestion

**Files:**
- Create: `backend/app/rag/splitter.py`
- Create: `backend/app/rag/vector_store.py`
- Create: `backend/app/rag/ingest.py`
- Create: `backend/tests/test_rag_indexing.py`

**Interfaces:**
- Consumes: `load_documents_from_directory()`, `Settings.get_vector_store_path()`
- Produces:
  - `split_documents(docs: list[Document]) -> list[Document]`
  - `get_vector_store() -> Chroma`
  - `get_retriever(k: int = 4) -> VectorStoreRetriever`
  - `run_ingest(force: bool = False) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_rag_indexing.py
import unittest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document
from app.rag.splitter import split_documents
from app.rag.ingest import calculate_file_hash, should_reindex


class TestRAGIndexing(unittest.TestCase):
    """测试文本切分与增量哈希计算"""

    def test_split_documents_preserves_metadata(self):
        long_content = "第1条 旅游者享有合法权益。" * 50
        doc = Document(
            page_content=long_content,
            metadata={"title": "旅游法", "category": "法规", "page": 1},
        )
        splits = split_documents([doc], chunk_size=200, chunk_overlap=30)
        self.assertGreater(len(splits), 1)
        for s in splits:
            self.assertEqual(s.metadata["title"], "旅游法")
            self.assertEqual(s.metadata["category"], "法规")
            self.assertIn("start_index", s.metadata)

    def test_file_hash_diff(self):
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content v1")
            temp_path = Path(f.name)

        hash1 = calculate_file_hash(temp_path)
        self.assertFalse(should_reindex(temp_path, {str(temp_path): hash1}))

        # 改变文件内容
        temp_path.write_bytes(b"content v2")
        self.assertTrue(should_reindex(temp_path, {str(temp_path): hash1}))
        temp_path.unlink()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_rag_indexing`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rag.splitter'`

- [ ] **Step 3: Implement `splitter.py`, `vector_store.py`, and `ingest.py`**

Create `backend/app/rag/splitter.py`:
```python
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
```

Create `backend/app/rag/vector_store.py`:
```python
"""Chroma 向量数据库管理模块"""

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
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
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
```

Create `backend/app/rag/ingest.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_rag_indexing`
Expected: PASS (2 tests, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/splitter.py backend/app/rag/vector_store.py backend/app/rag/ingest.py backend/tests/test_rag_indexing.py
git commit -m "feat(rag): add text splitter, chroma vector store, and incremental ingest pipeline"
```

---

### Task 4: Tourism Knowledge Tool & Agentic RAG Engine

**Files:**
- Create: `backend/app/rag/tools.py`
- Create: `backend/app/rag/agent.py`
- Create: `backend/tests/test_rag_agent.py`

**Interfaces:**
- Consumes: `get_retriever()`
- Produces:
  - `@tool search_tourism_knowledge(query: str) -> str`
  - `generate_chat_stream(message: str, conversation_id: str, trip_context: dict | None = None) -> AsyncGenerator[dict, None]`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_rag_agent.py
import unittest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document
from app.rag.tools import search_tourism_knowledge


class TestRAGAgent(unittest.TestCase):
    """测试知识库检索 Tool 与 Prompt 组装"""

    @patch("app.rag.tools.get_retriever")
    def test_search_tourism_knowledge_tool(self, mock_get_retriever):
        mock_retriever = MagicMock()
        mock_doc = Document(
            page_content="【中华人民共和国旅游法】第35条 旅行社不得指定具体购物场所。",
            metadata={"title": "旅游法", "category": "法规", "page": 12},
        )
        mock_retriever.invoke.return_value = [mock_doc]
        mock_get_retriever.return_value = mock_retriever

        result = search_tourism_knowledge.invoke({"query": "强制购物如何维权"})
        self.assertIn("旅游法", result)
        self.assertIn("第35条", result)
        self.assertIn("第 12 页", result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_rag_agent`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rag.tools'`

- [ ] **Step 3: Implement `tools.py` and `agent.py`**

Create `backend/app/rag/tools.py`:
```python
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
```

Create `backend/app/rag/agent.py`:
```python
"""基于 LangChain/LangGraph 的 Agentic RAG 对话引擎"""

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
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
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
    messages = [SystemMessage(content=system_prompt)]
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
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})
                yield {
                    "type": "tool_start",
                    "content": f"正在查阅旅游知识库: {tool_args.get('query', '')}",
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
            # 模拟流式吐出或直接吐出
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_rag_agent`
Expected: PASS (1 test, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/tools.py backend/app/rag/agent.py backend/tests/test_rag_agent.py
git commit -m "feat(rag): implement search_tourism_knowledge tool and agentic rag engine"
```

---

### Task 5: FastAPI SSE Chat Stream Endpoints

**Files:**
- Create: `backend/app/api/routes/chat.py`
- Modify: `backend/app/api/main.py`
- Create: `backend/tests/test_api_chat.py`

**Interfaces:**
- Consumes: `generate_chat_stream()`, `get_vector_store()`
- Produces:
  - `POST /api/chat/stream -> text/event-stream`
  - `GET /api/rag/status -> JSON`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api_chat.py
import json
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.api.main import app


class TestChatAPI(unittest.TestCase):
    """测试聊天流式接口与知识库状态接口"""

    def setUp(self):
        self.client = TestClient(app)

    @patch("app.api.routes.chat.get_vector_store")
    def test_rag_status_endpoint(self, mock_get_store):
        mock_store = mock_get_store.return_value
        mock_col = mock_store._collection
        mock_col.count.return_value = 120

        resp = self.client.get("/api/rag/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["total_chunks"], 120)

    @patch("app.api.routes.chat.generate_chat_stream")
    def test_chat_stream_endpoint(self, mock_stream):
        async def fake_stream(*args, **kwargs):
            yield {"type": "token", "content": "你好！"}
            yield {"type": "done"}

        mock_stream.side_effect = fake_stream

        payload = {
            "message": "你好",
            "conversation_id": "test-conv-1",
        }
        resp = self.client.post("/api/chat/stream", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.headers["content-type"])
        content = resp.text
        self.assertIn("data:", content)
        self.assertIn("你好！", content)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_api_chat`
Expected: FAIL with 404 Not Found for `/api/rag/status`

- [ ] **Step 3: Implement `backend/app/api/routes/chat.py` and mount in `main.py`**

Create `backend/app/api/routes/chat.py`:
```python
"""AI 对话与 RAG 助手路由模块"""

import json
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
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
```

In `backend/app/api/main.py`:
- Import `from .routes import trip, poi, chat, map as map_routes`
- Add: `app.include_router(chat.router, prefix="/api/chat", tags=["AI 智能助手与 RAG 问答"])`
- Also add a route alias: `app.include_router(chat.router, prefix="/api/rag", tags=["RAG 状态与管理"])` for `/api/rag/status`.

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest tests.test_api_chat`
Expected: PASS (2 tests, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/chat.py backend/app/api/main.py backend/tests/test_api_chat.py
git commit -m "feat(api): add /api/chat/stream and /api/rag/status endpoints"
```

---

### Task 6: Frontend Global Chat Assistant Component

**Files:**
- Create: `frontend/src/components/ChatAssistant.vue`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/chat.test.mjs`

**Interfaces:**
- Consumes: `/api/chat/stream`, `/api/rag/status`
- Produces: Floating assistant widget mounted in `App.vue` responding to user queries and trip context.

- [ ] **Step 1: Write the failing frontend test**

```javascript
// frontend/tests/chat.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSSELine } from '../src/utils/sse.js';

test('parseSSELine parses standard SSE json data', () => {
  const line = 'data: {"type":"token","content":"您好"}';
  const parsed = parseSSELine(line);
  assert.deepEqual(parsed, { type: 'token', content: '您好' });
});

test('parseSSELine ignores non-data lines', () => {
  assert.equal(parseSSELine(': keepalive'), null);
  assert.equal(parseSSELine(''), null);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\nodejs\node.exe --experimental-strip-types --test frontend/tests/chat.test.mjs`
Expected: FAIL with Cannot find module `../src/utils/sse.js`

- [ ] **Step 3: Implement SSE parser, API client, and `ChatAssistant.vue`**

Create `frontend/src/utils/sse.ts`:
```typescript
/**
 * 解析 Server-Sent Events 单行数据
 */
export function parseSSELine(line: string): any | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) {
    return null;
  }
  const payload = trimmed.slice(5).trim();
  if (!payload || payload === "[DONE]") {
    return { type: "done" };
  }
  try {
    return JSON.parse(payload);
  } catch {
    return null;
  }
}
```

Update `frontend/src/services/api.ts` to export chat stream request function:
```typescript
export async function streamChatMessage(
  message: string,
  conversationId: string,
  tripContext: any,
  onEvent: (event: any) => void,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      current_trip_context: tripContext,
    }),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`请求失败: HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const parsed = parseSSELine(line);
      if (parsed) {
        onEvent(parsed);
      }
    }
  }
}
```

Create `frontend/src/components/ChatAssistant.vue`:
- A fixed floating trigger button in the bottom right corner (`z-index: 999`).
- A popup/card panel with header ("AI 旅游顾问 · 知识库助手") and minimize/close button.
- Message list showing user messages and assistant messages with markdown paragraphs and copy-paste support.
- Status bubble when `tool_start` occurs ("📚 正在检索旅游法规与避坑知识库...").
- Quick prompt chips:
  - "跟团游被强制购物如何维权？"
  - "酒店线上预订被拒入住怎么办？"
  - "高山徒步发生失温如何自救？"
  - "景区导游讲解收费有行业标准吗？"
- Reads current trip plan from `sessionStorage` or route params to populate `tripContext`.

Mount `ChatAssistant` in `frontend/src/App.vue`:
```vue
<script setup lang="ts">
import ChatAssistant from "@/components/ChatAssistant.vue";
// ...
</script>
<template>
  <a-config-provider ...>
    <div class="app-shell">
      ...
      <ChatAssistant />
    </div>
  </a-config-provider>
</template>
```

- [ ] **Step 4: Run test and build to verify it passes**

Run: `D:\nodejs\node.exe --experimental-strip-types --test frontend/tests/chat.test.mjs`
Expected: PASS (2 tests)

Run: `D:\nodejs\npm.cmd run build` (from `frontend/`)
Expected: Vite build succeeds with 0 errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/sse.ts frontend/src/components/ChatAssistant.vue frontend/src/services/api.ts frontend/src/App.vue frontend/tests/chat.test.mjs
git commit -m "feat(frontend): implement ChatAssistant floating component with SSE streaming"
```

---

### Task 7: Knowledge Base Ingestion & End-to-End Verification

**Files:**
- Execute: `python -m app.rag.ingest`
- Test: Full backend test discovery & frontend type-check

- [ ] **Step 1: Run knowledge base ingestion**

Run: `D:\anaconda3\envs\agent\python.exe -m app.rag.ingest` (from `backend/`)
Expected: Successfully scans `resource/tourism_knowledge_documents/` (15 documents), extracts text, builds chunks, and writes into `backend/data/vector_store/`. Output shows `status: success`.

- [ ] **Step 2: Run all backend tests**

Run: `D:\anaconda3\envs\agent\python.exe -m unittest discover` (from `backend/`)
Expected: All test suites (`test_rag_config`, `test_rag_loader`, `test_rag_indexing`, `test_rag_agent`, `test_api_chat`, plus existing tests) PASS with 0 errors and 0 failures.

- [ ] **Step 3: Run frontend build check**

Run: `D:\nodejs\npm.cmd run build` (from `frontend/`)
Expected: Type-check and Vite production build pass cleanly.

- [ ] **Step 4: Final commit & git status verification**

```bash
git status
git commit -am "chore(rag): complete knowledge ingestion and end-to-end integration"
```
