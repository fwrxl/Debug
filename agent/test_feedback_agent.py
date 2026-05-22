"""测试反馈分析 Agent - 主入口（Agent 直接决定和调用）"""
from typing import Dict, Any, List

from agent.base import AgentBase
from agent.memory.memory import MemoryModule
from agent.execution.executor import ExecutionModule
from capabilities.owner_identification.identifier import OwnerIdentifier
from capabilities.feishu_notification.notifier import FeishuNotifier
from capabilities.situation_analysis.analyzer import SituationAnalyzer
from capabilities.log_localization.locator import LogLocator
from capabilities.code_localization.locator import CodeLocator

class TestFeedbackAgent(AgentBase):
    """
    测试反馈分析 Agent

    输入：机器人 Agent 的测试反馈（情景描述）+ 失败日志
    输出：定位到的 bug 模块 + 负责人通知

    Agent 作为大脑，主动决定调用哪些能力
    """

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.memory = MemoryModule()
        self.owner_identifier = OwnerIdentifier(config)
        self.feishu_notifier = FeishuNotifier(config)
        self.situation_analyzer = SituationAnalyzer(config)
        self.log_locator = LogLocator(config)
        self.code_locator = CodeLocator(config)

        # 可用的能力
        self.capabilities = {
            "owner_identification": self.owner_identifier,
            "feishu_notification": self.feishu_notifier,
            "situation_analysis": self.situation_analyzer,
            "log_localization": self.log_locator,
            "code_localization": self.code_locator,
        }

        # 执行器（统一执行入口）
        self.executor = ExecutionModule(config)

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Agent 逻辑

        委托给 ExecutionModule 执行计划

        Args:
            input_data: {
                "situation": "...",
                "failed_log": "..."
            }

        Returns:
            分析结果报告
        """
        situation = input_data.get("situation", "")
        failed_log = input_data.get("failed_log", "")

        print(f"\n{'='*60}")
        print(f"Agent 开始分析")
        print(f"{'='*60}")
        print(f"情景: {situation}")
        print(f"失败日志: {failed_log[:100]}...")

        # 委托给 Executor 执行多分支诊断流程
        result = await self.executor.execute_plan_with_branches(
            situation=situation,
            failed_log=failed_log,
        )

        print(f"\n{'='*60}")
        print(f"Agent 分析完成")
        print(f"{'='*60}")
        print(f"通知发送: {result.get('notification_sent', False)}")
        print(f"最佳模块: {result.get('best_module')}")
        print(f"最佳置信度: {result.get('best_confidence')}")

        return result

