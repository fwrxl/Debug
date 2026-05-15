"""规划模块 - 制定分析计划"""
from typing import Dict, List, Any, Optional

from integrations.llm_client import get_llm_client


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
        self.llm_client = get_llm_client()

    def create_plan(
        self,
        situation: Dict[str, Any],
        failed_log: str,
    ) -> List[Dict[str, Any]]:
        """
        创建分析计划

        Args:
            situation: 情景描述
            failed_log: 失败日志

        Returns:
            丰富步骤字典列表，每个字典包含 name, description, input, output_key, dependencies, status, error, evidence
        """
        available_steps = list(self.capabilities.keys())

        # 调用 LLMClient.plan() 获取步骤名列表
        step_names = self.llm_client.plan(
            situation=situation,
            failed_log=failed_log,
            available_steps=available_steps,
        )

        # 如果 LLM 返回空或无效，使用 fallback
        if not step_names or not isinstance(step_names, list) or len(step_names) < 2:
            step_names = [
                "situation_analysis",
                "log_localization",
                "owner_identification",
                "feishu_notification",
            ]

        # 转换为丰富步骤
        enriched = []
        for i, name in enumerate(step_names):
            if name in self.capabilities:
                enriched.append(self._enrich_step(name, i))

        # 如果全部被过滤掉，使用 fallback
        if not enriched:
            step_names = [
                "situation_analysis",
                "log_localization",
                "owner_identification",
                "feishu_notification",
            ]
            for i, name in enumerate(step_names):
                enriched.append(self._enrich_step(name, i))

        # 确保 situation_analysis 和 log_localization 始终在计划中（最前面）
        required_steps = ["situation_analysis", "log_localization"]
        existing_names = [s["name"] for s in enriched]

        for req in required_steps:
            if req not in existing_names and req in self.capabilities:
                # 在最前面插入缺失的必需步骤
                idx = required_steps.index(req)
                enriched.insert(idx, self._enrich_step(req, idx))

        # 修正依赖顺序
        enriched = self._fix_step_order(enriched)

        return enriched

    def _enrich_step(self, step_name: str, step_index: int) -> Dict[str, Any]:
        """
        将步骤名字符串转换为丰富的步骤字典

        Args:
            step_name: 步骤名（如 "situation_analysis"）
            step_index: 步骤在原始列表中的索引

        Returns:
            丰富的步骤字典
        """
        description = self.CAPABILITY_DESCRIPTIONS.get(
            step_name, f"执行 {step_name}"
        )

        return {
            "name": step_name,
            "description": description,
            "input": {},  # 当前设计中 input 从 context/memory 获取，此处留空
            "output_key": f"{step_name}_result",
            "dependencies": [],
            "status": "pending",
            "error": None,
            "evidence": None,
        }

    def _fix_step_order(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        修正步骤顺序，确保 owner_identification 在 situation_analysis 和 log_localization 之后，
        feishu_notification 在 owner_identification 之后

        Args:
            steps: 原始步骤列表

        Returns:
            修正后的步骤列表
        """
        step_names = [s["name"] for s in steps]

        # 不在这两个列表中的步骤保持原相对顺序
        ordered_steps = []
        others = []

        for s in steps:
            name = s["name"]
            if name in ("situation_analysis", "log_localization", "owner_identification", "feishu_notification"):
                ordered_steps.append(s)
            else:
                others.append(s)

        # 按规则重排：
        # 1. situation_analysis 和 log_localization 在最前（保持相对顺序）
        # 2. owner_identification 在它们之后
        # 3. feishu_notification 在 owner_identification 之后

        final_order = []

        # 收集 ordered_steps 中的各类
        sa_log = [s for s in ordered_steps if s["name"] in ("situation_analysis", "log_localization")]
        oi = [s for s in ordered_steps if s["name"] == "owner_identification"]
        fn = [s for s in ordered_steps if s["name"] == "feishu_notification"]

        final_order.extend(sa_log)
        final_order.extend(oi)
        final_order.extend(fn)
        final_order.extend(others)

        return final_order

    @staticmethod
    def get_step_names(plan: List[Dict[str, Any]]) -> List[str]:
        """
        从丰富步骤列表中提取步骤名列表（向后兼容用）

        Args:
            plan: 丰富步骤字典列表

        Returns:
            步骤名字符串列表
        """
        return [s["name"] for s in plan]

    def get_next_step(self) -> str:
        """获取下一步（未使用，当前保留）"""
        return self._steps[0] if self._steps else None

    def mark_step_completed(self, step: str):
        """标记步骤完成（未使用，当前保留）"""
        if step in self._steps:
            self._steps.remove(step)

    def get_steps(self) -> List[str]:
        """获取所有步骤（未使用，当前保留）"""
        return self._steps.copy()

    def create_replan(
        self,
        situation: Dict[str, Any],
        failed_log: str,
        reflection_result: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        根据 reflection_result 生成补充计划

        当 Reflection 输出 REPLAN decision 时调用此方法，
        根据证据缺口生成针对性的额外诊断步骤。

        Args:
            situation: 情景描述
            failed_log: 失败日志
            reflection_result: ReflectionModule.reflect() 的结果

        Returns:
            补充步骤字典列表（只包含 Diagnostic capabilities）
        """
        additional_steps = []
        decision = reflection_result.get("decision", "stop")
        confidence = reflection_result.get("confidence", 0.0)
        evidence_consistency = reflection_result.get("evidence_consistency", 0.0)
        evidence_chain = reflection_result.get("evidence_chain", [])

        # 如果置信度低，可能需要更多验证
        if confidence < 0.7:
            # 再次执行 log_localization 获取更多证据
            if "log_localization" not in [s.get("name") for s in []]:
                step = self._enrich_step("log_localization", len(additional_steps))
                additional_steps.append(step)

        # 如果 evidence_consistency 低，说明证据来源不统一，可以再次执行 log_localization
        if evidence_consistency < 0.5:
            if "log_localization" not in [s.get("name") for s in additional_steps]:
                step = self._enrich_step("log_localization", len(additional_steps))
                additional_steps.append(step)

        return additional_steps