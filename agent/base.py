"""Agent 核心模块"""
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod


class AgentBase(ABC):
    """Agent 基类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.state: Dict[str, Any] = {}

    @abstractmethod
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行 Agent 逻辑"""
        pass

    def get_name(self) -> str:
        return self.__class__.__name__