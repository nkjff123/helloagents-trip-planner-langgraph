"""单元测试：LLM 服务与结构化提取测试 (test_llm_service)

测试范围:
1. extract_json_string: 纯 JSON、Markdown 代码块、思考标签 (<think>) 剥离、前缀后缀文本
2. OpenAILLMClient: 单例创建、参数初始化与平滑降级
3. generate_structured: 结构化解析成功、Pydantic 校验失败定向自愈修补、超限异常抛出
"""

import unittest
from unittest.mock import MagicMock, patch
from pydantic import BaseModel, Field

from app.services.llm_service import (
    OpenAILLMClient,
    get_llm,
    reset_llm,
    extract_json_string,
    generate_structured,
)


class SampleModel(BaseModel):
    name: str
    count: int = Field(default=1)


class TestLLMService(unittest.TestCase):
    """LLM 服务与结构化提取测试"""

    def setUp(self):
        reset_llm()

    def tearDown(self):
        reset_llm()

    def test_extract_json_string_pure(self):
        """测试提取纯 JSON"""
        raw = '{"name": "杭州", "count": 2}'
        self.assertEqual(extract_json_string(raw), raw)

    def test_extract_json_string_markdown(self):
        """测试提取 Markdown 代码块包裹的 JSON"""
        raw = '```json\n{"name": "北京", "count": 3}\n```'
        expected = '{"name": "北京", "count": 3}'
        self.assertEqual(extract_json_string(raw), expected)

    def test_extract_json_string_with_think_tags(self):
        """测试自动剥离 <think> 思考标签 (DeepSeek/Qwen 等推理模型)"""
        raw = (
            "<think>\n用户询问杭州景点，我需要返回合规的 JSON。\n"
            "需要注意不能输出非法字符。\n</think>\n"
            '```json\n{"name": "西湖", "count": 1}\n```'
        )
        expected = '{"name": "西湖", "count": 1}'
        self.assertEqual(extract_json_string(raw), expected)

    def test_extract_json_string_with_unclosed_think_tags(self):
        """测试自动剥离因长度截断未闭合的 <think> 思考标签"""
        # 如果模型先输出 JSON，末尾因某种原因附带了未闭合标签或先思考后输出
        raw = (
            "<thought>这里是思考过程，模型未正常闭合</thought>\n"
            '{"name": "千岛湖", "count": 2}'
        )
        expected = '{"name": "千岛湖", "count": 2}'
        self.assertEqual(extract_json_string(raw), expected)

    def test_extract_json_string_with_reasoning_tags(self):
        """测试自动剥离 <reasoning> 思考标签"""
        raw = (
            "<reasoning>\n分析景点信息...\n</reasoning>\n"
            '{"name": "灵隐寺", "count": 1}'
        )
        expected = '{"name": "灵隐寺", "count": 1}'
        self.assertEqual(extract_json_string(raw), expected)

    def test_extract_json_string_with_outer_text(self):
        """测试提取带有前后说明文字的 JSON"""
        raw = '这是一些前缀说明：\n{"name": "苏州", "count": 5}\n这是一些后缀说明。'
        expected = '{"name": "苏州", "count": 5}'
        self.assertEqual(extract_json_string(raw), expected)

    def test_extract_json_string_empty_raises(self):
        """测试空输入抛出 ValueError"""
        with self.assertRaises(ValueError):
            extract_json_string("")

    @patch("app.services.llm_service.OpenAI")
    def test_client_invoke_success(self, mock_openai_cls):
        """测试 OpenAILLMClient invoke 调用成功"""
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '{"name": "成都", "count": 4}'
        mock_completion.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_completion
        mock_openai_cls.return_value = mock_client

        client = OpenAILLMClient(model="gpt-test", api_key="sk-test", base_url="https://api.test.com/v1")
        res = client.invoke([{"role": "user", "content": "hello"}])
        self.assertEqual(res, '{"name": "成都", "count": 4}')
        mock_client.chat.completions.create.assert_called_once()

    @patch("app.services.llm_service.get_llm")
    def test_generate_structured_success(self, mock_get_llm):
        """测试 generate_structured 一次性生成成功"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = '```json\n{"name": "西安", "count": 3}\n```'
        mock_get_llm.return_value = mock_llm

        res = generate_structured(SampleModel, [{"role": "user", "content": "test"}])
        self.assertEqual(res.name, "西安")
        self.assertEqual(res.count, 3)

    @patch("app.services.llm_service.get_llm")
    def test_generate_structured_self_healing_retry(self, mock_get_llm):
        """测试 generate_structured 首次格式不合规时自愈修补成功"""
        mock_llm = MagicMock()
        # 第一次返回格式不符合 SampleModel (缺少 name 或类型错误)
        # 第二次自愈重试返回合法格式
        mock_llm.invoke.side_effect = [
            '{"invalid_field": 123}',
            '{"name": "南京", "count": 2}',
        ]
        mock_get_llm.return_value = mock_llm

        res = generate_structured(SampleModel, [{"role": "user", "content": "test"}], max_retries=2)
        self.assertEqual(res.name, "南京")
        self.assertEqual(res.count, 2)
        self.assertEqual(mock_llm.invoke.call_count, 2)

    @patch("app.services.llm_service.get_llm")
    def test_generate_structured_max_retries_exceeded(self, mock_get_llm):
        """测试超过重试上限时显式抛出 ValueError"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = "非 JSON 废话文本"
        mock_get_llm.return_value = mock_llm

        with self.assertRaises(ValueError) as ctx:
            generate_structured(SampleModel, [{"role": "user", "content": "test"}], max_retries=1)

        self.assertIn("LLM 结构化输出重试", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
