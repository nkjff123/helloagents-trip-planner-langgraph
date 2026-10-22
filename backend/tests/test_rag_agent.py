import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage, SystemMessage
from app.rag.tools import search_tourism_knowledge
from app.rag.agent import generate_chat_stream, CONVERSATION_HISTORY


class TestRAGAgent(unittest.TestCase):
    """测试知识库检索 Tool 与 Prompt 组装与流式对话逻辑"""

    def setUp(self):
        CONVERSATION_HISTORY.clear()

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

    def test_generate_chat_stream_multiple_tool_calls(self):
        """测试多工具调用（并行 Tool Calls）下消息列表组装符合 OpenAI 规范"""
        mock_llm = MagicMock()
        tc1 = {"name": "search_tourism_knowledge", "args": {"query": "酒店退订"}, "id": "call_1"}
        tc2 = {"name": "search_tourism_knowledge", "args": {"query": "消费者权益"}, "id": "call_2"}
        mock_resp = AIMessage(content="", tool_calls=[tc1, tc2])

        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm.bind_tools.return_value = mock_bound

        passed_messages = []

        async def fake_astream(messages):
            passed_messages.extend(messages)
            chunk = MagicMock()
            chunk.content = "根据规定，酒店不可单方面取消..."
            yield chunk

        mock_llm.astream = fake_astream

        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(return_value="相关法条")

        async def run_test():
            events = []
            async for ev in generate_chat_stream(
                message="酒店线上预订被临时取消怎么办？",
                conversation_id="test_conv_parallel",
            ):
                events.append(ev)
            return events

        with patch("app.rag.agent.get_chat_model", return_value=mock_llm), \
             patch("app.rag.agent.search_tourism_knowledge", mock_tool):
            events = asyncio.run(run_test())

        # 验证输出事件
        tool_starts = [e for e in events if e.get("type") == "tool_start"]
        self.assertEqual(len(tool_starts), 2)
        tokens = [e for e in events if e.get("type") == "token"]
        self.assertTrue(len(tokens) > 0)
        dones = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(dones), 1)

        # 关键验证：验证传入 astream 的 messages 是否符合 OpenAI 规范：
        # 1. 带有 tool_calls 的 AIMessage 必须只出现一次
        # 2. 紧接着必须是对应每一个 tool_call_id 的 ToolMessage
        # 3. 不能出现 AIMessage 重复插入或穿插在 ToolMessage 之间
        ai_messages_with_tools = [
            m for m in passed_messages
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
        ]
        self.assertEqual(
            len(ai_messages_with_tools),
            1,
            "带 tool_calls 的 AIMessage 只能出现一次，不能在循环中重复添加",
        )

        # 找到该 AIMessage 的索引
        ai_idx = passed_messages.index(ai_messages_with_tools[0])
        # 其后紧跟的必须是两个 ToolMessage
        tool_msg_1 = passed_messages[ai_idx + 1]
        tool_msg_2 = passed_messages[ai_idx + 2]
        self.assertIsInstance(tool_msg_1, ToolMessage)
        self.assertIsInstance(tool_msg_2, ToolMessage)
        self.assertEqual(tool_msg_1.tool_call_id, "call_1")
        self.assertEqual(tool_msg_2.tool_call_id, "call_2")

    def test_generate_chat_stream_tool_exception_handled(self):
        """测试工具抛出异常时依然补齐 ToolMessage，避免 OpenAI 报 400"""
        mock_llm = MagicMock()
        tc = {"name": "search_tourism_knowledge", "args": {"query": "测试"}, "id": "call_err"}
        mock_resp = AIMessage(content="", tool_calls=[tc])

        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm.bind_tools.return_value = mock_bound

        passed_messages = []

        async def fake_astream(messages):
            passed_messages.extend(messages)
            chunk = MagicMock()
            chunk.content = "兜底回复"
            yield chunk

        mock_llm.astream = fake_astream

        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(side_effect=RuntimeError("Retriever connection timeout"))

        async def run_test():
            events = []
            async for ev in generate_chat_stream(
                message="查询超时测试",
                conversation_id="test_conv_err",
            ):
                events.append(ev)
            return events

        with patch("app.rag.agent.get_chat_model", return_value=mock_llm), \
             patch("app.rag.agent.search_tourism_knowledge", mock_tool):
            events = asyncio.run(run_test())

        # 验证不会抛出未捕获异常导致中断，且传入了 ToolMessage
        tokens = [e for e in events if e.get("type") == "token"]
        self.assertTrue(len(tokens) > 0)
        tool_messages = [m for m in passed_messages if isinstance(m, ToolMessage)]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].tool_call_id, "call_err")
        self.assertIn("检索失败", tool_messages[0].content)

    def test_generate_chat_stream_missing_tool_call_id(self):
        """测试模型返回缺失 id 的 tool_call 时自动补齐合法 id 且前后一致"""
        mock_llm = MagicMock()
        tc = {"name": "search_tourism_knowledge", "args": {"query": "无id测试"}, "id": None}
        mock_resp = AIMessage(content="", tool_calls=[tc])

        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm.bind_tools.return_value = mock_bound

        passed_messages = []

        async def fake_astream(messages):
            passed_messages.extend(messages)
            chunk = MagicMock()
            chunk.content = "回复"
            yield chunk

        mock_llm.astream = fake_astream

        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(return_value="检索结果")

        async def run_test():
            events = []
            async for ev in generate_chat_stream(
                message="无id测试",
                conversation_id="test_conv_noid",
            ):
                events.append(ev)
            return events

        with patch("app.rag.agent.get_chat_model", return_value=mock_llm), \
             patch("app.rag.agent.search_tourism_knowledge", mock_tool):
            events = asyncio.run(run_test())

        ai_msg = [m for m in passed_messages if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)][0]
        tool_msg = [m for m in passed_messages if isinstance(m, ToolMessage)][0]
        self.assertTrue(bool(ai_msg.tool_calls[0]["id"]))
        self.assertEqual(ai_msg.tool_calls[0]["id"], tool_msg.tool_call_id)

    def test_stream_tag_filter(self):
        """测试 StreamTagFilter 能够过滤 think 标签与 DSML 标签，且保留正常文本"""
        from app.rag.agent import StreamTagFilter

        f = StreamTagFilter()
        chunks = [
            "<th", "ink>正在思考如何解答维权问题...</", "think>",
            "根据《中华人民共和国民法典》",
            "<｜｜DSML｜｜ calls>junk</｜｜DSML｜｜ calls>",
            "，当发生违约时，2 < 5 成立。",
        ]
        out = []
        for ch in chunks:
            res = f.feed(ch)
            if res:
                out.append(res)
        rem = f.flush()
        if rem:
            out.append(rem)

        result_text = "".join(out)
        self.assertNotIn("<think>", result_text)
        self.assertNotIn("DSML", result_text)
        self.assertIn("根据《中华人民共和国民法典》", result_text)
        self.assertIn("2 < 5 成立。", result_text)

    def test_generate_chat_stream_dsml_text_fallback(self):
        """测试模型在 content 中直接吐出 DSML 文本时，系统能够兜底解析并调用知识检索，且输出干净文本"""
        mock_llm = MagicMock()
        dsml_content = (
            '<｜｜DSML｜｜ calls>\n'
            '<｜｜DSML｜｜ invoke name="search_tourism_knowledge">\n'
            '<｜｜DSML｜｜ parameter name="query" string="false">["酒店订单取消 违约责任", "在线旅游平台 维权"]</｜｜DSML｜｜ parameter>\n'
            '</｜｜DSML｜｜ invoke>\n'
            '</｜｜DSML｜｜ calls>'
        )
        # 模拟模型第一阶段在 content 中直接吐出 DSML，且 tool_calls 为空
        mock_resp = AIMessage(content=dsml_content, tool_calls=[])

        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm.bind_tools.return_value = mock_bound

        passed_messages = []

        async def fake_astream(messages):
            passed_messages.extend(messages)
            chunk = MagicMock()
            chunk.content = "【维权指南】根据《在线旅游平台住宿预订服务规范》，平台需协助安排同等标准住宿或退款赔偿。"
            yield chunk

        mock_llm.astream = fake_astream

        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(return_value="【相关规范条款】违约时应当退还全额房款并进行赔付。")

        async def run_test():
            events = []
            async for ev in generate_chat_stream(
                message="酒店线上预订被临时取消怎么办？",
                conversation_id="test_conv_dsml",
            ):
                events.append(ev)
            return events

        with patch("app.rag.agent.get_chat_model", return_value=mock_llm), \
             patch("app.rag.agent.search_tourism_knowledge", mock_tool):
            events = asyncio.run(run_test())

        # 验证产生了 tool_start 事件
        tool_starts = [e for e in events if e.get("type") == "tool_start"]
        self.assertEqual(len(tool_starts), 1)
        self.assertIn("酒店订单取消", tool_starts[0]["content"])

        # 验证工具被实际调用
        mock_tool.ainvoke.assert_called_once()
        tool_arg_query = mock_tool.ainvoke.call_args[0][0]["query"]
        self.assertIn("酒店订单取消", tool_arg_query)

        # 验证最终给 astream 传入的消息中包含知识库检索结果
        system_msgs = [m for m in passed_messages if isinstance(m, SystemMessage)]
        has_knowledge_in_system = any("知识库检索结果" in m.content for m in system_msgs)
        self.assertTrue(has_knowledge_in_system, "应当通过 SystemMessage 将知识检索结果注入到模型合成阶段")

        # 验证输出的 token 中不含 DSML 标签
        tokens = [e["content"] for e in events if e.get("type") == "token"]
        full_output = "".join(tokens)
        self.assertNotIn("DSML", full_output)
        self.assertIn("维权指南", full_output)


if __name__ == "__main__":
    unittest.main()
