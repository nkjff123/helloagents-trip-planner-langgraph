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
