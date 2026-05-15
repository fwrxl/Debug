"""执行模块 - Agent 驱动的多分支诊断流程（基于 debug_robot_scenario2.py）
"""
import json
import re
from typing import Dict, Any, List
from dataclasses import dataclass, field
import asyncio
from agent.memory.memory import MemoryModule, ContextMemory, IterationMemory
from agent.reflection.reflector import ReflectionModule
from capabilities.situation_analysis.analyzer import SituationAnalyzer
from capabilities.log_localization.locator import LogLocator
from capabilities.owner_identification.identifier import OwnerIdentifier
from capabilities.feishu_notification.notifier import FeishuNotifier
from integrations.llm_client import get_llm_client


# 分支结果数据类
@dataclass
class BranchResult:
    """分支执行结果"""
    branch_id: int
    module: str
    reflection_confidence: float = 0.0
    reflection_reason: str = ""
    reflection_evidence: List[str] = field(default_factory=list)
    reflection_uncertainty: str = ""
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    decision: str = "stop"  # stop / proceed


class ExecutionModule:
    """
    执行模块
    Agent 驱动的多分支诊断流程
    """

    MAX_BRANCHES = 10  # 最大分支数限制

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.memory = MemoryModule()
        self.llm_client = get_llm_client()
        # 初始化各能力
        self.capabilities = {
            "situation_analysis": SituationAnalyzer(config),
            "log_localization": LogLocator(config),
            "owner_identification": OwnerIdentifier(config),
            "feishu_notification": FeishuNotifier(config),
        }

    async def execute_plan_with_branches(
        self,
        situation: str,
        failed_log: str,
    ) -> Dict[str, Any]:
        """
        Agent 驱动的多分支诊断流程

        流程：
        1. 执行 situation_analysis 获取候选模块，初始化 memory.possible_modules
        2. 为每个候选模块创建独立 branch_memory
        3. 每个 branch 执行 log_localization（带 suspicious_module）
        4. 每个 branch 执行完后调用 Reflection 进行 LLM 反思
        5. 每个 branch 用 Reflection 输出的 confidence 更新 memory.possible_modules 的累积分数
        6. 汇总所有 branch 的结果，按累积分数排序
        7. Finalization 根据最终排序结果决定是否 owner_identification 和 feishu_notification

        Args:
            situation: 情景描述（字符串）
            failed_log: 失败日志

        Returns:
            执行结果 dict
        """
        # ========== 阶段 1: situation_analysis 获取候选模块 ==========
        situation_capability = self.capabilities["situation_analysis"]
        situation_result = await situation_capability.execute(situation, failed_log, self.memory)

        self.memory.add_attempt(
            step="situation_analysis",
            evidence=situation_result,
            success=True,
            target_module="N/A",
            confidence=situation_result.get("confidence", 0.0)
        )

        # 初始化共享的 possible_modules
        self.memory.initialize_candidates(situation_result.get("possible_modules", []))

        possible_modules = self.memory.get_candidate_modules()
        if not possible_modules:
            # 没有候选模块，返回失败
            return {
                "success": False,
                "candidate_modules": [],
                "branch_results": [],
                "best_module": None,
                "best_confidence": 0.0,
                "notification_sent": False,
                "recipient": None,
            }

        # ========== 阶段 1.5: 创建分支记忆（situation_analysis 之后直接初始化）==========
        # 获取 situation_analysis 的 attempt（用于复制到每个分支）
        global_attempts = self.memory.iteration.attempts if hasattr(self.memory.iteration, 'attempts') else []
        sit_attempt = None
        for att in global_attempts:
            if att.get("step") == "situation_analysis":
                sit_attempt = att
                break

        # 初始化分支记忆
        self.memory.branch_memories = {}
        for module in possible_modules:
            module_name = module.module if hasattr(module, 'module') else module
            branch_iteration = IterationMemory()
            # 把 situation_analysis 的 attempt 复制到每个分支，让 reflection 能看到完整历史
            if sit_attempt:
                branch_iteration.attempts.append(sit_attempt)
            self.memory.branch_memories[module_name] = {
                "context": ContextMemory(),
                "iteration": branch_iteration,
            }

        # 限制分支数量
        possible_modules = possible_modules[:self.MAX_BRANCHES]

        # 构建上下文
        context = {
            "possible_modules": possible_modules,
            "situation_result": situation_result,
        }

        # ========== 阶段 2: Agent 驱动的多分支执行 ==========
        branch_results = await asyncio.gather(*[
            self.execute_branch(
                branch_id=i,
                candidate_module=module.module,
                situation=situation,
                failed_log=failed_log,
                context=context,
            )
            for i, module in enumerate(possible_modules)
        ])

        # ========== 阶段 3: 汇总所有分支的 Reflection 结果 ==========
        sorted_modules = self.memory.get_sorted_modules()

        best_module = sorted_modules[0].module if sorted_modules else None
        best_confidence = sorted_modules[0].confidence if sorted_modules else 0.0

        # ========== 阶段 4: Finalization ==========
        notification_sent = False
        recipient = None

        if best_module and best_confidence > 0:
            # 执行 owner_identification
            owner_capability = self.capabilities["owner_identification"]
            owner_result = await owner_capability.execute(situation, failed_log, self.memory)

            owner_info = owner_result.get("owner_info", {})
            has_owner = owner_result.get("has_owner", False)

            if has_owner and owner_info.get("open_id"):
                self.memory.set_owner_open_id(owner_info["open_id"])
                self.memory.set_bug_module(best_module)

                # 全局通知阈值判断
                NOTIFY_THRESHOLD = 0.5
                should_send = (
                    best_confidence >= NOTIFY_THRESHOLD and
                    best_module in ReflectionModule.VALID_MODULES
                )

                if should_send:
                    feishu_capability = self.capabilities["feishu_notification"]
                    feishu_result = await feishu_capability.execute(situation, failed_log, self.memory)
                    notification_sent = feishu_result.get("message_sent", False)
                    recipient = feishu_result.get("recipient")

        return {
            "success": notification_sent,
            "candidate_modules": [pm.module for pm in possible_modules],
            "branch_results": [
                {
                    "branch_id": br.branch_id,
                    "module": br.module,
                    "reflection_confidence": br.reflection_confidence,
                    "reflection_reason": br.reflection_reason,
                    "reflection_evidence": br.reflection_evidence,
                    "reflection_uncertainty": br.reflection_uncertainty,
                    "step_results": br.step_results,
                }
                for br in branch_results
            ],
            "best_module": best_module,
            "best_confidence": best_confidence,
            "notification_sent": notification_sent,
            "recipient": recipient,
        }

    async def execute_branch(
        self,
        branch_id: int,
        candidate_module: str,
        situation: str,
        failed_log: str,
        context: dict,
    ) -> BranchResult:
        """
        Agent 驱动的单分支执行

        Args:
            branch_id: 分支 ID
            candidate_module: 该分支负责的候选模块
            situation: 情景描述
            failed_log: 失败日志
            context: 共享上下文

        Returns:
            BranchResult
        """
        # 从全局 branch_memories 获取分支记忆
        branch_mem = self.memory.branch_memories.get(candidate_module, {})
        branch_context = branch_mem.get("context", ContextMemory())
        branch_iteration = branch_mem.get("iteration", IterationMemory())

        # 记录上下文到分支 memory
        branch_context.add_conversation(
            step="context",
            role="system",
            content=f"Branch {branch_id} 负责验证模块: {candidate_module}\n"
                    f"主流程 situation_analysis 结果: {context.get('situation_result', {})}"
        )

        # 构建可疑模块信息（用于 log_localization）
        situation_result = context.get("situation_result", {})
        suspicious_module = None
        for pm in situation_result.get("possible_modules", []):
            module_name = pm.get("module") if isinstance(pm, dict) else (pm.module if hasattr(pm, 'module') else None)
            if module_name == candidate_module:
                suspicious_module = module_name
                break

        step_results = []

        # ========== Agent 驱动循环：每步调用 LLM 决定下一步 ==========
        while True:
            # 调用 LLM 决策，记录对话到分支记忆
            decision_result = self._agent_decides_capabilities(
                candidate_module, situation, failed_log, self.memory, suspicious_module
            )
            decision = decision_result["decision"]
            llm_prompt = decision_result.get("prompt", "")
            llm_response = decision_result.get("response", "")

            # 记录 LLM 对话到分支 context
            if llm_prompt:
                branch_context.add_conversation(
                    step="llm_decision", role="user", content=llm_prompt
                )
            if llm_response:
                branch_context.add_conversation(
                    step="llm_decision", role="assistant", content=llm_response
                )

            if decision.get("end_signal"):
                break

            cap_name = decision.get("capability")
            if not cap_name:
                break

            capability = self.capabilities.get(cap_name)
            if not capability:
                break

            cap_confidence = 0.0
            try:
                if cap_name == "log_localization" and suspicious_module:
                    result = await capability.execute(
                        situation, failed_log, self.memory, suspicious_module
                    )
                else:
                    result = await capability.execute(situation, failed_log, self.memory)

                # 记录 capability 调用的 LLM 对话
                if result.get("llm_prompt"):
                    branch_context.add_conversation(
                        step=f"{cap_name}_llm", role="user", content=result["llm_prompt"]
                    )
                if result.get("llm_response"):
                    branch_context.add_conversation(
                        step=f"{cap_name}_llm", role="assistant", content=result["llm_response"]
                    )

                cap_confidence = result.get("confidence", 0.0)
                cap_success = result.get("success", True)

                # 直接写入分支记忆
                branch_iteration.add_attempt(
                    step=cap_name,
                    evidence=result,
                    success=cap_success,
                    target_module=candidate_module,
                    confidence=cap_confidence
                )

                step_results.append({
                    "capability": cap_name,
                    "result": result,
                    "success": cap_success,
                    "confidence": cap_confidence
                })

            except Exception as e:
                branch_iteration.add_attempt(
                    step=cap_name,
                    evidence={"error": str(e)},
                    success=False,
                    target_module=candidate_module,
                    confidence=0.0
                )
                step_results.append({
                    "capability": cap_name,
                    "result": {"error": str(e)},
                    "success": False,
                    "confidence": 0.0
                })

            # 置信度 >= 0.8 时自动结束
            if cap_confidence >= 0.8:
                break

        # ========== Branch 独立 Reflection（调用 LLM） ==========
        reflector = ReflectionModule(self.config)
        reflection_result = reflector.reflect(
            memory=self.memory,
            branch_module=candidate_module,
            situation=situation,
            failed_log=failed_log,
        )

        # 记录 Reflection 的 LLM 对话到分支 context
        if reflection_result.get("llm_prompt"):
            branch_context.add_conversation(
                step="reflection_llm", role="user", content=reflection_result["llm_prompt"]
            )
        if reflection_result.get("llm_response"):
            branch_context.add_conversation(
                step="reflection_llm", role="assistant", content=reflection_result["llm_response"]
            )

        reflection_confidence = reflection_result.get("confidence", 0.0)
        reflection_reason = reflection_result.get("reason", "")
        reflection_evidence = reflection_result.get("evidence", [])
        reflection_uncertainty = reflection_result.get("uncertainty", "")

        # 用 Reflection 输出的 confidence 更新共享 memory 的模块累积分数
        if candidate_module and reflection_confidence > 0:
            self.memory.update_module_confidence(candidate_module, reflection_confidence)

        return BranchResult(
            branch_id=branch_id,
            module=candidate_module,
            reflection_confidence=reflection_confidence,
            reflection_reason=reflection_reason,
            reflection_evidence=reflection_evidence,
            reflection_uncertainty=reflection_uncertainty,
            step_results=step_results,
            decision="stop" if reflection_confidence < 0.5 else "proceed",
        )

    def _agent_decides_capabilities(
        self,
        candidate_module: str,
        situation: str,
        failed_log: str,
        memory: MemoryModule,
        suspicious_module: str = None,
    ) -> dict:
        """
        LLM 决定当前分支下一步执行哪个 capability（单步决策）

        Args:
            candidate_module: 该分支负责的候选模块
            situation: 情景描述
            failed_log: 失败日志
            memory: 分支独立的记忆模块
            suspicious_module: 可疑模块名称

        Returns:
            {
                "capability": "log_localization",  # str 或 None
                "end_signal": False,               # True = 停止执行
                "reason": "决策理由"
            }
        """
        # 优先从分支记忆读取 attempts，否则回退到全局
        if hasattr(memory, 'branch_memories') and candidate_module in memory.branch_memories:
            attempts = memory.branch_memories[candidate_module]["iteration"].attempts
        else:
            attempts = memory.iteration.attempts if hasattr(memory, 'iteration') else []
        executed_caps = [a.get('step') for a in attempts]
        executed_set = set(executed_caps)

        last_confidence = attempts[-1].get('confidence', 0.0) if attempts else 0.0

        executed_summary = f"已执行: {', '.join(executed_caps)}" if executed_caps else "尚未执行任何 capability"

        module_info = f"- branch_module: {candidate_module}"
        situation_desc = situation

        prompt = f"""你是 DebugAgent 诊断分支中的「分支规划专家」。

你的任务不是诊断问题本身，而是决定当前诊断分支下一步是否还需要执行 capability，或者是否应该结束当前分支并进入 Reflection。

## 当前分支信息
{module_info}

## 情景描述
{situation_desc}

## 失败日志摘要
{failed_log[:3000]}

## 已执行的 capabilities
{executed_summary}

## 当前分支最新置信度
{last_confidence}

## 置信度语义

当前分支的置信度表示：

- 0.0：可以确定「当前模块不是问题模块」
- 1.0：可以确定「当前模块就是问题模块」
- 越接近 0，越倾向于排除当前模块
- 越接近 1，越倾向于确认当前模块
- 越接近 0.5，表示当前证据仍然不充分，无法判断

注意：
置信度不是"继续分析的必要性"，而是"当前模块是否为问题模块"的判断强度。

## 可用 capabilities

当前分支内只允许使用以下 capability：

- log_localization：从失败日志中验证当前模块是否存在异常，并定位当前模块内部可能的问题点。

## 决策规则

1. 每个诊断分支必须至少执行一次 log_localization。
2. 如果 log_localization 尚未执行，则必须选择执行 log_localization。
3. 如果 log_localization 已经执行过，则不要重复执行。
4. 当前分支只有 log_localization 一个能力，因此一旦它已经执行过，就必须判断是否结束分支。
5. 只要当前证据已经比较明确地支持「确认当前模块」或「排除当前模块」，就应该结束当前分支。
6. 当 last_confidence 明显偏离 0.5 时，应设置 end_signal=true。
   - last_confidence <= 0.35：基本可以排除当前模块，应结束分支
   - last_confidence >= 0.65：基本可以确认当前模块，应结束分支
7. 只有在 log_localization 尚未执行时，才允许 end_signal=false。
8. 不允许因为"还想更确定"而重复执行已经执行过的 capability。
9. 如果没有可执行的新 capability，必须 end_signal=true。

## 输出格式

必须只返回纯 JSON 对象，禁止包含 Markdown、解释文字或代码块。

当需要继续执行 capability 时，输出：

{{
  "capability": "log_localization",
  "end_signal": false,
  "reason": "log_localization 是当前分支的关键验证能力，尚未执行，必须先执行"
}}

当应该结束当前分支时，输出：

{{
  "capability": null,
  "end_signal": true,
  "reason": "log_localization 已执行，当前证据已足够支持确认或排除当前模块，结束分支进入 Reflection"
}}"""

        try:
            messages = [
                {"role": "system", "content": "你是诊断分支规划专家，只返回纯 JSON。"},
                {"role": "user", "content": prompt}
            ]
            response = self.llm_client.chat(messages, max_tokens=500)
            result = self._parse_capability_decision(response)

            if not result:
                result = {
                    "capability": "log_localization" if "log_localization" not in executed_set else None,
                    "end_signal": "log_localization" in executed_set,
                    "reason": "解析失败，使用默认行为"
                }
            return {
                "decision": result,
                "prompt": prompt,
                "response": response
            }

        except Exception as e:
            return {
                "decision": {
                    "capability": "log_localization" if "log_localization" not in executed_set else None,
                    "end_signal": "log_localization" in executed_set,
                    "reason": f"异常: {str(e)}"
                },
                "prompt": prompt,
                "response": str(e)
            }

    def _parse_capability_decision(self, response: str) -> dict:
        """解析 LLM 返回的 capability 决策"""
        cleaned = re.sub(r'<think>.*?', '', response, flags=re.DOTALL)
        cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()

        try:
            result = json.loads(cleaned)
            if self._validate_capability_decision(result):
                return result
        except json.JSONDecodeError:
            pass

        json_candidate = self._extract_json_by_bracket_balance(cleaned)
        if json_candidate:
            try:
                result = json.loads(json_candidate)
                if self._validate_capability_decision(result):
                    return result
            except json.JSONDecodeError:
                pass

        return {}

    def _validate_capability_decision(self, result: dict) -> bool:
        """验证 capability 决策结构"""
        if not isinstance(result, dict):
            return False
        capability = result.get("capability")
        if capability is not None and not isinstance(capability, str):
            return False
        if not isinstance(result.get("end_signal"), bool):
            return False
        return True

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

    