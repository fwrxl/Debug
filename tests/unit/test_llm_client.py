"""测试 LLMClient 的 thinking 参数透传"""
import unittest
from unittest.mock import Mock, patch
from integrations.llm_client import LLMClient


class TestLLMClientThinking(unittest.TestCase):
    """验证 MiniMax thinking 参数是否正确传递给 API"""

    def setUp(self):
        self.mock_response = Mock()
        self.mock_response.choices = [Mock(message=Mock(content="test response"))]

    @patch("integrations.llm_client.OpenAI")
    def test_default_thinking_disabled(self, mock_openai_class):
        """默认情况下，thinking 应该为 {"type": "disabled"}"""
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = self.mock_response
        mock_openai_class.return_value = mock_client

        client = LLMClient(api_key="test-key", base_url="https://test.com", model="test-model")
        result = client.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(result, "test response")
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["extra_body"]["thinking"], {"type": "disabled"})

    @patch("integrations.llm_client.OpenAI")
    def test_thinking_override_enabled(self, mock_openai_class):
        """通过 kwargs 显式覆盖 thinking 为 enabled"""
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = self.mock_response
        mock_openai_class.return_value = mock_client

        client = LLMClient(api_key="test-key", base_url="https://test.com", model="test-model")
        result = client.chat(
            [{"role": "user", "content": "hello"}],
            thinking={"type": "enabled"},
        )

        self.assertEqual(result, "test response")
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["extra_body"]["thinking"], {"type": "enabled"})

    @patch("integrations.llm_client.OpenAI")
    def test_thinking_override_custom(self, mock_openai_class):
        """通过 kwargs 自定义 thinking 参数"""
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = self.mock_response
        mock_openai_class.return_value = mock_client

        client = LLMClient(api_key="test-key", base_url="https://test.com", model="test-model")
        result = client.chat(
            [{"role": "user", "content": "hello"}],
            thinking={"type": "enabled", "budget_tokens": 1000},
        )

        self.assertEqual(result, "test response")
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["extra_body"]["thinking"], {"type": "enabled", "budget_tokens": 1000})

    @patch("integrations.llm_client.OpenAI")
    def test_other_kwargs_pass_through(self, mock_openai_class):
        """其他 kwargs 也能正常透传"""
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = self.mock_response
        mock_openai_class.return_value = mock_client

        client = LLMClient(api_key="test-key", base_url="https://test.com", model="test-model")
        result = client.chat(
            [{"role": "user", "content": "hello"}],
            max_tokens=500,
            temperature=0.5,
            top_p=0.9,
        )

        self.assertEqual(result, "test response")
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["extra_body"]["thinking"], {"type": "disabled"})
        self.assertEqual(call_kwargs["max_tokens"], 500)
        self.assertEqual(call_kwargs["temperature"], 0.5)
        self.assertEqual(call_kwargs["top_p"], 0.9)

    @patch("integrations.llm_client.OpenAI")
    def test_max_tokens_none_not_included(self, mock_openai_class):
        """max_tokens 为 None 时不应出现在请求参数中"""
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = self.mock_response
        mock_openai_class.return_value = mock_client

        client = LLMClient(api_key="test-key", base_url="https://test.com", model="test-model")
        client.chat([{"role": "user", "content": "hello"}])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertNotIn("max_tokens", call_kwargs)


if __name__ == "__main__":
    unittest.main()
