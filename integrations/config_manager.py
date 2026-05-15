"""配置管理模块 - 从 .env 加载配置"""
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

# 尝试加载 dotenv
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass


class FeishuConfig(BaseModel):
    """飞书配置"""
    open_base_url: str = "https://open.feishu.cn"
    tenant_access_token: str = ""
    app_id: str = ""
    app_secret: str = ""
    spreadsheet_token: str = ""
    module_owner_table: str = "data/module_owner_mapping.xlsx"
    default_receive_id_type: str = "open_id"
    default_msg_type: str = "text"


class LLMConfig(BaseModel):
    """LLM 配置"""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


class Config(BaseModel):
    """应用配置"""
    feishu: FeishuConfig = FeishuConfig()
    llm: LLMConfig = LLMConfig()


def load_config() -> Config:
    """从环境变量加载配置"""
    return Config(
        feishu=FeishuConfig(
            open_base_url=os.environ.get("FEISHU_OPEN_BASE_URL", "https://open.feishu.cn"),
            tenant_access_token=os.environ.get("FEISHU_TENANT_ACCESS_TOKEN", ""),
            app_id=os.environ.get("FEISHU_APP_ID", ""),
            app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
            spreadsheet_token=os.environ.get("FEISHU_SPREADSHEET_TOKEN", ""),
            module_owner_table=os.environ.get("MODULE_OWNER_TABLE", "data/module_owner_mapping.xlsx"),
            default_receive_id_type=os.environ.get("FEISHU_DEFAULT_RECEIVE_ID_TYPE", "open_id"),
            default_msg_type=os.environ.get("FEISHU_DEFAULT_MSG_TYPE", "text"),
        ),
        llm=LLMConfig(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )
    )


_config: Optional[Config] = None


def get_config() -> Config:
    """获取配置单例"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    """重新加载配置"""
    global _config
    _config = None
    return get_config()                                                                                                               
