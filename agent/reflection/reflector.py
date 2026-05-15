"""反思模块 - 每个分支调用 LLM 进行反思，输出该分支模块的置信度"""
from typing import Dict, Any, List, Optional
from enum import Enum
from agent.memory.memory import MemoryModule
from integrations.llm_client import get_llm_client


class Decision(Enum):
    """保留用于兼容，不用于新逻辑"""
    PROCEED = "proceed"
    REPLAN = "replan"
    STOP = "stop"


class ReflectionModule:
    """
    反思模块（LLM 驱动版）

    每个分支执行完后，Reflection 调用 LLM 对当前分支进行反思。

    职责：
    - 反思当前分支的执行流程和中间结果
    - 评估"问题是否属于当前分支的模块"
    - 输出该模块的置信度（0.0-1.0）

    禁止：
    - 输出 decision 字段
    - 输出 final_module 字段
    - 输出 stop/notify/send_notification 等字段
    - 写"停止通知"
    - 影响全局流程是否结束
    """

    # 有效模块列表
    VALID_MODULES = {
        "rejection_classifier", "intent_classifier", "instruction_rewriter",
        "command_store", "parameter_extractor", "protocol_builder"
    }

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.llm_client = get_llm_client()

    def reflect(
        self,
        memory: MemoryModule,
        branch_module: str,
        situation: Any,
        failed_log: str,
    ) -> Dict[str, Any]:
        """
        对当前分支进行 LLM 反思

        Args:
            memory: 该分支的独立记忆模块
            branch_module: 当前分支负责的模块名
            situation: 情景描述（字符串或 dict）
            failed_log: 失败日志

        Returns:
            反思结果 dict，包含:
            - module: 当前分支模块名（固定为输入的 branch_module）
            - confidence: 0.0-1.0，该模块是问题根因的置信度
            - reason: 反思理由
            - evidence: 证据列表
            - uncertainty: 仍不确定的地方
            - llm_prompt: 反思使用的 prompt
            - llm_response: LLM 返回的原始响应
        """
        # 获取当前分支的 attempts（优先从分支记忆读取，否则回退到全局）
        if hasattr(memory, 'branch_memories') and branch_module in memory.branch_memories:
            attempts = memory.branch_memories[branch_module]["iteration"].attempts
        else:
            attempts = memory.iteration.attempts

        # 构建当前分支的执行摘要
        execution_summary = self._build_execution_summary(attempts, branch_module)

        # 调用 LLM 进行反思
        reflection_result = self._llm_reflect(
            branch_module=branch_module,
            situation=situation,
            failed_log=failed_log,
            execution_summary=execution_summary,
        )

        # 规范化结果
        normalized = self._normalize_reflection_result(reflection_result, branch_module)

        # 添加 LLM 对话记录
        normalized["llm_prompt"] = reflection_result.get("llm_prompt", "")
        normalized["llm_response"] = reflection_result.get("llm_response", "")

        return normalized

    def _build_execution_summary(self, attempts: List[Dict], branch_module: str) -> str:
        """构建当前分支执行摘要"""
        lines = [f"当前分支模块: {branch_module}", ""]

        for i, attempt in enumerate(attempts):
            step = attempt.get("step", "unknown")
            evidence = attempt.get("evidence", {})
            confidence = attempt.get("confidence", 0.0)

            lines.append(f"--- 步骤 {i+1}: {step} ---")
            lines.append(f"置信度: {confidence}")

            if step == "log_localization":
                failed_module = evidence.get("failed_module", "unknown")
                failed_component = evidence.get("failed_component", "unknown")
                root_cause = evidence.get("root_cause", "unknown")
                lines.append(f"failed_module: {failed_module}")
                lines.append(f"failed_component: {failed_component}")
                lines.append(f"root_cause: {root_cause}")
            elif step == "situation_analysis":
                possible = evidence.get("possible_modules", [])
                if possible:
                    lines.append(f"候选模块: {[p.get('module') if isinstance(p, dict) else p for p in possible]}")

            lines.append("")

        return "\n".join(lines)

    def _llm_reflect(
        self,
        branch_module: str,
        situation: Any,
        failed_log: str,
        execution_summary: str,
    ) -> Dict[str, Any]:
        """调用 LLM 进行单分支反思"""
        situation_desc = situation

        prompt = f"""## 任务

你是当前诊断分支的反思器。
你只负责评估"问题是否属于当前分支的模块"。
你不能决定是否通知。
你不能决定流程是否停止。
你不能选择其他模块作为最终模块。

## 当前分支模块

{branch_module}

## 情景描述

{situation_desc}

## 失败日志

{failed_log[:3000]}

## 当前分支执行摘要

{execution_summary}

## 反思要求

1. 基于上述执行摘要和失败日志，评估"问题是否属于 {branch_module} 模块"
2. 给出置信度分数（0.0-1.0），表示"问题根因在该模块"的可信程度
3. 列出关键证据支持你的判断
4. 指出仍不确定的地方

## 输出格式

必须返回纯 JSON 对象，禁止包含任何 Markdown 标记：

{{
  "module": "{branch_module}",
  "confidence": 0.0 到 1.0 的数字，
  "reason": "为什么问题属于或不属于当前模块",
  "evidence": ["证据1", "证据2"],
  "uncertainty": "仍然不确定的地方"
}}

## 重要约束

1. module 字段必须等于 "{branch_module}"，不要改成其他模块
2. confidence 必须是 0.0 到 1.0 的数字
3. 不要输出 decision、final_module、stop、notify 等字段
4. 不要写"停止通知"、"跳过 Finalization"等文字
5. 只反思当前模块，不要与其他模块比较"""

        try:
            messages = [
                {"role": "system", "content": "你是分支反思专家，只返回纯 JSON。"},
                {"role": "user", "content": prompt}
            ]
            response = self.llm_client.chat(messages, max_tokens=800)

            # 解析 LLM 返回的 JSON
            result = self._parse_llm_response(response)
            result["llm_prompt"] = prompt
            result["llm_response"] = response
            return result

        except Exception as e:
            return {
                "module": branch_module,
                "confidence": 0.0,
                "reason": f"反思失败: {str(e)}",
                "evidence": [],
                "uncertainty": "反思过程出现异常"
            }

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 响应"""
        import json
        import re

        # 移除 <think> 标签
        cleaned = re.sub(r'<think>.*?', '', response, flags=re.DOTALL)

        # 移除 markdown code fences
        cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()

        # 尝试直接解析
        try:
            result = json.loads(cleaned)
            if self._has_required_fields(result):
                return result
        except json.JSONDecodeError:
            pass

        # 括号平衡法提取
        json_candidate = self._extract_json_by_bracket_balance(cleaned)
        if json_candidate:
            try:
                result = json.loads(json_candidate)
                if self._has_required_fields(result):
                    return result
            except json.JSONDecodeError:
                pass

        return {}

    def _has_required_fields(self, obj: Dict[str, Any]) -> bool:
        """检查是否包含必要字段"""
        return 'module' in obj and 'confidence' in obj

    def _extract_json_by_bracket_balance(self, text: str) -> str:
        """使用括号平衡法提取 JSON 字符串"""
        start_idx = text.find('{')
        if start_idx == -1:
            return ""

        depth = 0
        start = None
        end = None

        for i in range(start_idx, len(text)):
            ch = text[i]
            if ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        if start is not None and end is not None:
            return text[start:end]

        return ""

    def _normalize_reflection_result(
        self,
        result: Dict[str, Any],
        branch_module: str,
    ) -> Dict[str, Any]:
        """
        规范化反思结果

        强制：
        - module = branch_module
        - confidence 在 0.0-1.0 之间
        - evidence 是 list
        """
        normalized = {
            "module": branch_module,
            "confidence": 0.0,
            "reason": "",
            "evidence": [],
            "uncertainty": "",
        }

        if isinstance(result, dict):
            try:
                confidence = float(result.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0

            # 强制 confidence 在 0.0-1.0 之间
            normalized["confidence"] = max(0.0, min(1.0, confidence))
            normalized["reason"] = str(result.get("reason", ""))
            normalized["uncertainty"] = str(result.get("uncertainty", ""))

            evidence = result.get("evidence", [])
            if isinstance(evidence, list):
                normalized["evidence"] = [str(item) for item in evidence]
            else:
                normalized["evidence"] = []

        return normalized

    def summarize(
        self,
        situation: str,
        findings: List[Dict[str, Any]],
        steps: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """总结分析结果（用于最终报告生成）"""
        bug_module = None
        bug_description = None
        owner = None

        for finding in findings:
            if finding.get("type") == "bug_location":
                bug_module = finding.get("module")
                bug_description = finding.get("description")
                owner = finding.get("owner")

        situation_desc = situation

        return {
            "summary": {
                "situation": situation_desc,
                "bug_module": bug_module,
                "bug_description": bug_description,
                "owner": owner,
                "findings_count": len(findings),
                "steps_executed": len(steps),
            },
            "findings": findings,
            "steps": steps,
            "recommendation": self._generate_recommendation(bug_module, owner),
        }

    def _generate_recommendation(self, bug_module: str, owner: str) -> str:
        """生成建议"""
        if not bug_module:
            return "未能定位到具体 bug，建议人工介入分析"

        return f"建议联系 {owner or '负责人'} 修复 {bug_module} 模块的问题"