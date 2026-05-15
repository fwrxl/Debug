"""测试反馈分析 Agent - 主入口（Agent 直接决定和调用）"""
from typing import Dict, Any, List

from agent.base import AgentBase
from agent.memory.memory import MemoryModule
from agent.execution.executor import ExecutionModule
from capabilities.owner_identification.identifier import OwnerIdentifier
from capabilities.feishu_notification.notifier import FeishuNotifier
from capabilities.situation_analysis.analyzer import SituationAnalyzer
from capabilities.log_localization.locator import LogLocator
from integrations.llm_client import get_llm_client


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
        self.llm_client = get_llm_client()

        # 可用的能力
        self.capabilities = {
            "owner_identification": self.owner_identifier,
            "feishu_notification": self.feishu_notifier,
            "situation_analysis": self.situation_analyzer,
            "log_localization": self.log_locator,
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

        # 使用 PlanningModule 创建计划
        from agent.planning.planner import PlanningModule
        planner = PlanningModule(config=self.config, capabilities=self.capabilities)
        plan_steps = planner.create_plan(situation=situation, failed_log=failed_log)

        print(f"计划步骤: {[s['name'] for s in plan_steps]}")

        # 委托给 Executor 执行
        result = await self.executor.execute_plan(
            situation=situation,
            failed_log=failed_log,
            plan_steps=plan_steps,
            memory=self.memory,
        )

        print(f"\n{'='*60}")
        print(f"Agent 分析完成")
        print(f"{'='*60}")
        print(f"通知发送: {result.get('notification_sent', False)}")
        print(f"自动链路步骤: {result.get('auto_chained_steps', [])}")

        return result

    async def validate(self, input_data: Dict[str, Any]) -> bool:
        """验证输入数据"""
        return "situation" in input_data and "failed_log" in input_data

    async def notify_owner(
        self,
        module_id: str,
        situation: str,
        failed_log: str,
    ):
        """
        直接通知负责人（由 Agent 主动调用）

        Args:
            module_id: 模块 ID
            situation: 情景描述
            failed_log: 失败日志
        """
        # 1. 获取负责人信息
        owner_info = self.owner_identifier._get_owner(module_id)

        if not owner_info:
            print(f"未找到模块 {module_id} 的负责人")
            return {"success": False, "msg": "Owner not found"}

        # 2. 构建通知消息（从 xlsx 提取的信息）
        owner_name = owner_info.get("name", "")
        owner_open_id = owner_info.get("open_id", "")

        # 获取模块名称
        module_name = owner_info.get("name", module_id)  # 临时用 name 作为 module_name

        # 3. 构建自然语言通知
        message = self._build_notification_message(
            module_id=module_id,
            module_name=module_name,
            owner_name=owner_name,
            situation=situation,
            failed_log=failed_log,
        )

        # 4. 发送飞书消息
        from integrations.feishu_client import send_text_message
        send_result = send_text_message(
            receive_id=owner_open_id,
            text=message,
            receive_id_type="open_id",
        )

        return {
            "success": send_result.get("success", False),
            "message_id": send_result.get("data", {}).get("message_id"),
            "recipient": owner_open_id,
        }

    def _build_notification_message(
        self,
        module_id: str,
        module_name: str,
        owner_name: str,
        situation: str,
        failed_log: str,
    ) -> str:
        """构建通知消息"""
        situation_desc = situation

        lines = [
            "测试反馈分析通知",
            "",
            f"📦 模块ID: {module_id}",
            f"📋 模块名称: {module_name}",
            f"👤 负责人: {owner_name}",
            "",
            "📝 问题描述:",
            situation_desc,
            "",
            "🔍 失败日志摘要:",
            failed_log[:300] + "..." if len(failed_log) > 300 else failed_log,
            "",
            "请及时处理！",
        ]
        return "\n".join(lines)