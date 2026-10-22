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
