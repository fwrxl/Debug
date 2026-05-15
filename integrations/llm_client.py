"""LLM 客户端封装 (OpenAI 兼容)"""
import os
from typing import Optional, List, Dict, Any

from openai import OpenAI


class LLMClient:
    """LLM 客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = model or os.environ.get("OPENAI_MODEL", "MiniMax-M2.7")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        发送对话请求

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            LLM 回复内容
        """
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens

        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content
# 全局单例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client