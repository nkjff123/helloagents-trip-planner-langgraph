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
