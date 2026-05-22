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

    @staticmethod
    def _strip_think_tags(content: str) -> str:
        """移除 LLM 返回中的 <think>...</think> 标签及其内容。"""
        import re
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """
        发送对话请求

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他额外参数（如 thinking={"type": "enabled"}）

        Returns:
            LLM 回复内容

        Raises:
            RuntimeError: 当 API 调用失败时，包含详细的错误信息
        """
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        # 默认关闭内部思考标签（MiniMax 格式），通过 extra_body 透传非标准参数
        extra_body = kwargs.pop("extra_body", {})
        if "thinking" in kwargs:
            extra_body["thinking"] = kwargs.pop("thinking")
        elif "thinking" not in extra_body:
            extra_body["thinking"] = {"type": "disabled"}
        if extra_body:
            params["extra_body"] = extra_body
        if kwargs:
            params.update(kwargs)

        try:
            response = self.client.chat.completions.create(**params)
            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError("LLM 返回空内容 (content is None)")
            return self._strip_think_tags(content)
        except Exception as e:
            raise RuntimeError(f"LLM API 调用失败: {type(e).__name__}: {str(e)}") from e
# 全局单例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client