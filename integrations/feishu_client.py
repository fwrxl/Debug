"""飞书客户端模块 - 实现发送消息功能"""
import json
import time
import uuid
from typing import Optional

import requests

from .config_manager import get_config


class FeishuClient:
    """飞书客户端，用于发送消息"""

    def __init__(
        self,
        tenant_access_token: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        open_base_url: Optional[str] = None,
    ):
        """
        初始化飞书客户端

        Args:
            tenant_access_token: tenant访问令牌
            app_id: 应用ID
            app_secret: 应用密钥
            open_base_url: 飞书开放平台基础URL
        """
        config = get_config().feishu

        self.app_id = app_id or config.app_id
        self.app_secret = app_secret or config.app_secret
        self.open_base_url = open_base_url or config.open_base_url

        self._tenant_access_token = tenant_access_token or config.tenant_access_token
        self._token_expires_at: Optional[float] = None

        self._message_url = f"{self.open_base_url}/open-apis/im/v1/messages"
        self._token_url = f"{self.open_base_url}/open-apis/auth/v3/tenant_access_token/internal"

    def _refresh_token(self) -> bool:
        """刷新 tenant_access_token"""
        try:
            response = requests.post(
                self._token_url,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=30,
            )
            result = response.json()

            if result.get("code") == 0:
                self._tenant_access_token = result["tenant_access_token"]
                # 飞书 token 有效期约 2 小时，这里提前 5 分钟过期
                self._token_expires_at = time.time() + result.get("expire", 7200) - 300
                return True
            return False
        except Exception:
            return False

    def _get_headers(self) -> dict:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _ensure_token(self) -> bool:
        """确保 token 有效，必要时刷新"""
        if self._token_expires_at is None or time.time() >= self._token_expires_at:
            return self._refresh_token()
        return True

    def send_text_message(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "open_id",
    ) -> dict:
        """
        发送文本消息

        Args:
            receive_id: 接收者ID
            text: 消息内容
            receive_id_type: 接收者ID类型 (open_id, union_id, user_id, email, chat_id)

        Returns:
            API响应结果
        """
        msg_content = json.dumps({"text": text})
        return self.send_message(
            receive_id=receive_id,
            msg_type="text",
            content=msg_content,
            receive_id_type=receive_id_type,
        )

    def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: str,
        receive_id_type: str = "open_id",
        uuid_str: Optional[str] = None,
    ) -> dict:
        """
        发送消息

        Args:
            receive_id: 接收者ID
            msg_type: 消息类型 (text, post, interactive, etc.)
            content: 消息内容 (JSON序列化后的字符串)
            receive_id_type: 接收者ID类型
            uuid_str: 唯一请求ID，用于去重

        Returns:
            API响应结果
        """
        # 确保 token 有效
        self._ensure_token()

        if uuid_str is None:
            uuid_str = str(uuid.uuid4())

        params = {"receive_id_type": receive_id_type}

        payload = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content,
            "uuid": uuid_str,
        }

        try:
            response = requests.post(
                self._message_url,
                params=params,
                headers=self._get_headers(),
                json=payload,
                timeout=30,
            )
            result = response.json()
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "code": -1,
                "msg": "Request timeout",
                "data": {},
            }
        except requests.exceptions.ConnectionError as e:
            return {
                "success": False,
                "code": -1,
                "msg": f"Connection error: {str(e)}",
                "data": {},
            }
        except Exception as e:
            return {
                "success": False,
                "code": -1,
                "msg": f"Request failed: {type(e).__name__}: {str(e)}",
                "data": {},
            }

        # 检查响应
        if response.status_code != 200:
            return {
                "success": False,
                "code": response.status_code,
                "msg": f"HTTP error: {response.status_code}",
                "data": result,
            }

        # 检查API返回的成功码
        if result.get("code") != 0:
            return {
                "success": False,
                "code": result.get("code"),
                "msg": result.get("msg", "Unknown error"),
                "data": result,
            }

        return {
            "success": True,
            "code": 0,
            "msg": "success",
            "data": result.get("data", {}),
        }


# 快捷函数
def send_text_message(
    receive_id: str,
    text: str,
    receive_id_type: str = "open_id",
) -> dict:
    """
    快捷函数：发送文本消息

    Args:
        receive_id: 接收者ID
        text: 消息内容
        receive_id_type: 接收者ID类型

    Returns:
        API响应结果
    """
    client = FeishuClient()
    return client.send_text_message(receive_id, text, receive_id_type)