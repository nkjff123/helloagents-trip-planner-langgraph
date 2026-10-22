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
