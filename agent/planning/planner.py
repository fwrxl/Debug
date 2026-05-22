"""规划模块 - 制定分析计划"""
from typing import Dict, List, Any, Optional

class PlanningModule:
    """
    规划模块
    负责制定分析计划，决定先做什么后做什么
    """

    # 各 capability 的描述，用于 enrichment
    CAPABILITY_DESCRIPTIONS = {
        "situation_analysis": "情景分析 - 分析测试失败的情景，提取关键信息",
        "log_localization": "日志定位 - 从失败日志中定位错误类型、错误消息、堆栈跟踪",
        "owner_identification": "负责人识别 - 从问题描述和日志中识别问题模块，从 xlsx 表格查找负责人信息（姓名、open_id）",
        "feishu_notification": "飞书通知 - 向负责人发送飞书消息，需要先知道 owner_name 和 owner_open_id",
    }

    # Diagnostic 和 Finalization capabilities 分离
    DIAGNOSTIC_CAPABILITIES = {"situation_analysis", "log_localization"}
    FINALIZATION_CAPABILITIES = {"owner_identification", "feishu_notification"}

    def __init__(self, config: Dict[str, Any] = None, capabilities: Dict[str, Any] = None):
        self.config = config or {}
        self._steps: List[str] = []
        self.capabilities = capabilities or {}

