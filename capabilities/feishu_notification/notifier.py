"""飞书通知能力 - 文档写入和消息通知"""
from typing import Dict, Any, Optional, List

from integrations.feishu_client import FeishuClient, send_text_message


class FeishuNotifier:
    """
    飞书通知能力
    负责发送飞书消息通知和写入飞书文档
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.feishu_client = FeishuClient()

    async def execute(
        self,
        situation: str,
        failed_log: str,
        memory: Any,
        branch_results: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行飞书通知

        Args:
            situation: 情景描述
            failed_log: 失败日志
            memory: 记忆模块
            branch_results: 分支结果列表（可选，用于增强通知）

        Returns:
            通知结果
        """
        # 首先尝试从 memory 获取 owner_open_id（由 Finalization 阶段设置）
        owner_open_id = memory.get_owner_open_id() if hasattr(memory, 'get_owner_open_id') else None
        bug_module = memory.get_bug_module() if hasattr(memory, 'get_bug_module') else None

        # 如果 memory 中没有，尝试从 attempts 中获取 owner_identification 结果
        if not owner_open_id:
            owner_attempts = memory.iteration.get_attempts_by_step("owner_identification") if hasattr(memory, 'iteration') else []
            owner_result = owner_attempts[-1]["evidence"] if owner_attempts else {}

            if owner_result.get("owner_info"):
                owner_open_id = owner_result.get("owner_info", {}).get("open_id")
                owner_name = owner_result.get("owner_info", {}).get("name")
            else:
                owner_name = None

            if not bug_module:
                bug_module = owner_result.get("bug_module")
        else:
            # owner_open_id 存在，从 memory 中获取 owner_name
            owner_name = None  # 需要从 owner_identification 结果中获取

        # 构建通知消息
        situation_desc = situation

        message = self._build_notification_message(
            situation=situation_desc,
            bug_module=bug_module,
            owner_name=owner_name,
            branch_results=branch_results or [],
        )

        # 发送飞书消息
        send_result = None
        if owner_open_id:
            send_result = send_text_message(
                receive_id=owner_open_id,
                text=message,
                receive_id_type="open_id",
            )

        result = {
            "message_sent": send_result.get("success") if send_result else False,
            "recipient": owner_open_id,
            "message_id": send_result.get("data", {}).get("message_id") if send_result else None,
            "document_written": False,  # 文档写入暂未实现
        }

        return result

    def _build_notification_message(
        self,
        situation: str,
        bug_module: Optional[str],
        owner_name: Optional[str],
        branch_results: List[Dict[str, Any]] = None,
    ) -> str:
        """构建通知消息"""
        situation_desc = situation

        lines = [
            "测试反馈分析通知",
            "",
            "问题模块: {}".format(bug_module or "未知"),
            "",
        ]

        # 如果有分支结果，添加增强信息
        if branch_results:
            lines.append("分支调查结果:")
            lines.append("")
            for i, branch in enumerate(branch_results, 1):
                module = branch.get("module", "未知")
                confidence = branch.get("confidence", 0.0)
                excluded = branch.get("excluded", False)
                reflection_summary = branch.get("reflection_summary", "")
                capabilities_used = branch.get("capabilities_used", [])

                # 结果状态
                if excluded:
                    status = "排除"
                elif confidence >= 0.8:
                    status = "确认"
                elif confidence >= 0.6:
                    status = "基本确认"
                else:
                    status = "待验证"

                lines.append("Branch {} - 模块 {}:".format(i, module))
                lines.append("  结果: {}".format(status))
                lines.append("  置信度: {}".format(confidence))
                lines.append("  使用能力: {}".format(", ".join(capabilities_used) if capabilities_used else "N/A"))
                lines.append("  反思: {}".format(reflection_summary or "N/A"))
                lines.append("")

            lines.append("总分支数: {}".format(len(branch_results)))

        if owner_name:
            lines.append("")
            lines.append("负责人: {}".format(owner_name))
            lines.append("")
            lines.append("请及时处理！")

        return "\n".join(lines)

    def send_card_message(
        self,
        receive_id: str,
        title: str,
        content: str,
        receive_id_type: str = "open_id",
    ) -> Dict[str, Any]:
        """
        发送卡片消息

        Args:
            receive_id: 接收者 ID
            title: 卡片标题
            content: 卡片内容
            receive_id_type: ID 类型

        Returns:
            发送结果
        """
        card = self.feishu_client.build_text_card(content, title)
        return self.feishu_client.send_card_message(receive_id, card, receive_id_type)