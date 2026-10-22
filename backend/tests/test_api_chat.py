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
        mock_col.name = "travel_knowledge"

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
