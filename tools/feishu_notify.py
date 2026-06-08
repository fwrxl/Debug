"""
Feishu Notify Tool —— 独立实现，发送飞书文本消息通知。

内联了原 integrations/feishu_client.py 的核心逻辑，
不依赖项目根目录下的旧模块。
"""
import json
import time
import uuid
from pathlib import Path
from typing import Optional

import requests


# ========== env helper ==========

def _load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    env = {}
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# ========== Feishu client ==========

class FeishuClient:
    def __init__(
        self,
        tenant_access_token: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        open_base_url: Optional[str] = None,
    ):
        env = _load_env()
        config = {
            "app_id": app_id or env.get("FEISHU_APP_ID"),
            "app_secret": app_secret or env.get("FEISHU_APP_SECRET"),
            "open_base_url": open_base_url or env.get("FEISHU_OPEN_BASE_URL", "https://open.feishu.cn"),
            "tenant_access_token": tenant_access_token or env.get("FEISHU_TENANT_ACCESS_TOKEN"),
        }

        self.app_id = config["app_id"]
        self.app_secret = config["app_secret"]
        self.open_base_url = config["open_base_url"]
        self._tenant_access_token = config["tenant_access_token"]
        self._token_expires_at: Optional[float] = None

        self._message_url = f"{self.open_base_url}/open-apis/im/v1/messages"
        self._token_url = f"{self.open_base_url}/open-apis/auth/v3/tenant_access_token/internal"

    def _refresh_token(self) -> bool:
        try:
            response = requests.post(
                self._token_url,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=30,
            )
            result = response.json()
            if result.get("code") == 0:
                self._tenant_access_token = result["tenant_access_token"]
                self._token_expires_at = time.time() + result.get("expire", 7200) - 300
                return True
            return False
        except Exception:
            return False

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _ensure_token(self) -> bool:
        if self._token_expires_at is None or time.time() >= self._token_expires_at:
            return self._refresh_token()
        return True

    def send_text_message(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "open_id",
    ) -> dict:
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
            return {"success": False, "code": -1, "msg": "Request timeout", "data": {}}
        except requests.exceptions.ConnectionError as e:
            return {"success": False, "code": -1, "msg": f"Connection error: {e}", "data": {}}
        except Exception as e:
            return {"success": False, "code": -1, "msg": f"Request failed: {type(e).__name__}: {e}", "data": {}}

        if response.status_code != 200:
            return {"success": False, "code": response.status_code, "msg": f"HTTP error: {response.status_code}", "data": result}
        if result.get("code") != 0:
            return {"success": False, "code": result.get("code"), "msg": result.get("msg", "Unknown error"), "data": result}

        return {"success": True, "code": 0, "msg": "success", "data": result.get("data", {})}


# ========== Tool entry ==========

def run(report_path: str, receive_id: str = None) -> str:
    """
    调用飞书能力发送报告文件内容作为文本消息通知。

    Args:
        report_path: 报告文件路径（绝对路径或相对于项目根目录），
                     文件内容直接作为消息正文发送。
        receive_id: 接收者 open_id，默认从 .env 读取。
    """
    env = _load_env()
    rid = receive_id or env.get("receive_id")

    if not rid:
        return "[Error] 未提供 receive_id，且 .env 中未配置 receive_id"

    report_file = Path(report_path)
    if not report_file.exists():
        # 尝试相对于项目根目录解析
        repo_root = Path(__file__).resolve().parent.parent
        report_file = repo_root / report_path
    if not report_file.exists():
        # 再尝试 reports/ 子目录
        report_file = repo_root / "reports" / report_path
    if not report_file.exists():
        return f"[Error] 报告文件未找到: {report_path}"

    text = report_file.read_text(encoding="utf-8")
    # 飞书单条文本消息建议控制在 4000 字以内
    if len(text) > 4000:
        text = text[:3950] + "\n... (报告已截断)"

    client = FeishuClient()
    result = client.send_text_message(
        receive_id=rid,
        text=text,
        receive_id_type="open_id",
    )

    if result.get("success"):
        return (
            f"飞书消息发送成功。\n"
            f"message_id: {result.get('data', {}).get('message_id', 'N/A')}\n"
            f"receive_id: {rid}"
        )
    else:
        return (
            f"[Error] 飞书消息发送失败。\n"
            f"code: {result.get('code')}\n"
            f"msg: {result.get('msg')}"
        )
