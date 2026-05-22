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
from capabilities.code_localization.locator import CodeLocator
from capabilities.owner_identification.identifier import OwnerIdentifier
from capabilities.feishu_notification.notifier import FeishuNotifier
from integrations.llm_client import get_llm_client
import os


# 分支结果数据类
@dataclass
class BranchResult:
    """分支执行结果"""
    branch_id: int
    module: str
    reflection_confidence: float = 0.0
    reflection_explanation: str = ""
    reflection_evidence: List[str] = field(default_factory=list)
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
            "code_localization": CodeLocator(config),
            "owner_identification": OwnerIdentifier(config),
            "feishu_notification": FeishuNotifier(config),
        }
        self.debug_project_path = os.environ.get("DEBUG_PROJECT_PATH", "")

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
        print("[阶段1] 开始执行情景分析...")
        situation_capability = self.capabilities["situation_analysis"]
        try:
            situation_result = await situation_capability.execute(situation, failed_log, self.memory)
        except Exception as e:
            situation_result = {
                "possible_modules": [],
                "confidence": 0.0,
                "reasoning": f"情景分析异常: {str(e)}"
            }
        print(f"[阶段1] 情景分析完成，候选模块: {[m.get('module') if isinstance(m, dict) else m for m in situation_result.get('possible_modules', [])]}")

        sit_evidence = {k: v for k, v in situation_result.items() if k not in ("llm_prompt", "llm_response")}
        self.memory.add_attempt(
            step="situation_analysis",
            evidence=sit_evidence,
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

        # ========== 阶段 1.5: 创建分支记忆（只初始化空结构）==========
        self.memory.branch_memories = {}
        for module in possible_modules:
            module_name = module.module if hasattr(module, 'module') else module
            self.memory.branch_memories[module_name] = {
                "context": ContextMemory(),
                "iteration": IterationMemory(),
            }

        # 限制分支数量
        possible_modules = possible_modules[:self.MAX_BRANCHES]

        # 构建上下文
        context = {
            "possible_modules": possible_modules,
            "situation_result": situation_result,
        }

        # ========== 阶段 2: Agent 驱动的多分支执行 ==========
        print(f"[阶段2] 开始并行执行 {len(possible_modules)} 个分支...")
        branch_tasks = [
            self.execute_branch(
                branch_id=i,
                candidate_module=module.module,
                situation=situation,
                failed_log=failed_log,
                context=context,
            )
            for i, module in enumerate(possible_modules)
        ]
        branch_raw_results = await asyncio.gather(*branch_tasks, return_exceptions=True)
        branch_results: List[BranchResult] = []
        for i, res in enumerate(branch_raw_results):
            if isinstance(res, Exception):
                print(f"[阶段2] 分支 {i} 执行异常: {res}")
                # 构造一个失败的 BranchResult，避免整体流程中断
                module_name = possible_modules[i].module if hasattr(possible_modules[i], 'module') else str(possible_modules[i])
                branch_results.append(BranchResult(
                    branch_id=i,
                    module=module_name,
                    reflection_confidence=0.0,
                    reflection_explanation=f"分支执行异常: {str(res)}",
                    reflection_evidence=[],
                    step_results=[],
                    decision="stop",
                ))
            else:
                branch_results.append(res)
        print("[阶段2] 所有分支执行完成")

        # ========== 阶段 3: 全局反思（跨分支因果覆盖分析）==========
        print("[阶段3] 开始全局反思...")
        reflector = ReflectionModule(self.config)
        branch_results_for_global = [
            {
                "module": br.module,
                "reflection_confidence": br.reflection_confidence,
                "reflection_explanation": br.reflection_explanation,
                "reflection_evidence": br.reflection_evidence,
            }
            for br in branch_results
        ]
        global_result = reflector.global_reflect(
            situation=situation,
            failed_log=failed_log,
            branch_results=branch_results_for_global,
        )
        print(f"[阶段3] 全局反思完成，根因模块: {global_result.get('root_cause_module', '')}，confidence: {global_result.get('confidence', 0.0)}")

        # 记录全局反思到全局 iteration（剔除 llm_prompt/llm_response）
        clean_global = {k: v for k, v in global_result.items() if k not in ("llm_prompt", "llm_response")}
        self.memory.add_attempt(
            step="global_reflection",
            evidence=clean_global,
            success=True,
            target_module=global_result.get("root_cause_module", ""),
            confidence=global_result.get("confidence", 0.0),
        )

        # 用全局反思结果更新模块得分：根因模块加分，其他模块不变
        root_cause = global_result.get("root_cause_module", "")
        global_confidence = global_result.get("confidence", 0.0)
        if root_cause and global_confidence > 0:
            for candidate in self.memory.possible_modules:
                if candidate.module == root_cause:
                    candidate.confidence += global_confidence
                    break

        # ========== 阶段 4: 重新排序 ==========
        sorted_modules = self.memory.get_sorted_modules()
        best_module = sorted_modules[0].module if sorted_modules else None
        best_confidence = sorted_modules[0].confidence if sorted_modules else 0.0
        print(f"[阶段4] 模块排序完成，最佳模块: {best_module}，累积置信度: {best_confidence:.2f}")

        # ========== 阶段 5: Finalization ==========
        print("[阶段5] 开始 Finalization...")
        notification_sent = False
        recipient = None

        if best_module and best_confidence > 0:
            try:
                # 执行 owner_identification
                print("[阶段5] 开始执行 owner_identification...")
                owner_capability = self.capabilities["owner_identification"]
                owner_result = await owner_capability.execute(situation, failed_log, self.memory)
                print(f"[阶段5] owner_identification 完成，has_owner={owner_result.get('has_owner', False)}")

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
                    print(f"[阶段5] 通知阈值判断: best_confidence={best_confidence:.2f}, should_send={should_send}")

                    if should_send:
                        print("[阶段5] 开始发送飞书通知...")
                        feishu_capability = self.capabilities["feishu_notification"]
                        # 构建分支结果字典传递给 notifier
                        branch_results_dicts = [
                            {
                                "module": br.module,
                                "confidence": br.reflection_confidence,
                                "explanation": br.reflection_explanation,
                                "evidence": br.reflection_evidence,
                                "step_results": br.step_results,
                            }
                            for br in branch_results
                        ]
                        feishu_result = await feishu_capability.execute(
                            situation, failed_log, self.memory, branch_results_dicts
                        )
                        notification_sent = feishu_result.get("message_sent", False)
                        recipient = feishu_result.get("recipient")
                        print(f"[阶段5] 飞书通知发送完成，sent={notification_sent}, recipient={recipient}")
                else:
                    print("[阶段5] 未找到负责人，跳过通知")
            except Exception as e:
                print(f"[阶段5] Finalization 异常: {e}")
        else:
            print("[阶段5] 无最佳模块或置信度为0，跳过 Finalization")

        return {
            "success": notification_sent,
            "candidate_modules": [pm.module for pm in possible_modules],
            "branch_results": [
                {
                    "branch_id": br.branch_id,
                    "module": br.module,
                    "reflection_confidence": br.reflection_confidence,
                    "reflection_explanation": br.reflection_explanation,
                    "reflection_evidence": br.reflection_evidence,
                    "step_results": br.step_results,
                }
                for br in branch_results
            ],
            "global_reflection": global_result,
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
        # 从全局 branch_memories 获取或创建分支记忆
        if candidate_module not in self.memory.branch_memories:
            self.memory.branch_memories[candidate_module] = {}
        branch_mem = self.memory.branch_memories[candidate_module]
        if "context" not in branch_mem:
            branch_mem["context"] = ContextMemory()
        if "iteration" not in branch_mem:
            branch_mem["iteration"] = IterationMemory()
        branch_context = branch_mem["context"]
        branch_iteration = branch_mem["iteration"]
        print(f"\n[分支 {branch_id}] 开始执行，模块: {candidate_module}")

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
        max_iterations = 5
        iteration_count = 0
        while iteration_count < max_iterations:
            iteration_count += 1
            executed_caps = [a.get('step') for a in branch_iteration.attempts]
            print(f"  [分支 {branch_id} 循环 {iteration_count}/{max_iterations}] 已执行: {executed_caps if executed_caps else '无'}")

            # 调用 LLM 决策，记录对话到分支记忆
            print(f"  [分支 {branch_id}] 调用 LLM 决策...")
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

            end_signal = decision.get("end_signal", False)
            chosen_cap = decision.get("capability")
            if end_signal:
                print(f"  [分支 {branch_id}] LLM 决策: end_signal=true，结束循环")
            elif chosen_cap:
                print(f"  [分支 {branch_id}] LLM 决策: 执行能力 '{chosen_cap}'，理由: {decision.get('reason', '无')}")
            else:
                print(f"  [分支 {branch_id}] LLM 决策: capability 为空，结束循环")

            # 硬性约束：每个分支至少执行一次定位能力
            has_localized = any(
                a.get('step') in ('log_localization', 'code_localization')
                for a in branch_iteration.attempts
            )
            if decision.get("end_signal") and not has_localized:
                decision["end_signal"] = False
                decision["capability"] = "log_localization"
                if suspicious_module:
                    decision["reason"] = "强制规则：分支尚未执行任何定位能力，不能结束，优先执行 log_localization"
                else:
                    decision["reason"] = "强制规则：分支尚未执行任何定位能力，不能结束"
                print(f"  [分支 {branch_id}] 强制规则: 尚未执行定位能力，改为执行 log_localization")

            if decision.get("end_signal"):
                break

            cap_name = decision.get("capability")
            if not cap_name:
                break

            # 硬性约束：每个 capability 最多执行 2 次，超过则跳过本次执行
            cap_count = executed_caps.count(cap_name)
            if cap_count >= 2:
                print(f"  [分支 {branch_id}] 能力 '{cap_name}' 已执行 {cap_count} 次，达到上限，跳过本次执行")
                continue

            capability = self.capabilities.get(cap_name)
            if not capability:
                print(f"  [分支 {branch_id}] 未知 capability: {cap_name}，终止分支")
                break

            print(f"  [分支 {branch_id}] 开始执行能力 '{cap_name}'...")
            cap_confidence = 0.0
            try:
                if cap_name == "log_localization" and suspicious_module:
                    result = await capability.execute(
                        situation, failed_log, self.memory, suspicious_module
                    )
                elif cap_name == "code_localization":
                    result = await capability.execute(
                        situation, failed_log, self.memory,
                        module_name=candidate_module,
                        debug_project_path=self.debug_project_path,
                    )
                else:
                    result = await capability.execute(situation, failed_log, self.memory)

                # 记录 capability 调用的完整 LLM 对话
                if result.get("llm_prompt"):
                    branch_context.add_conversation(
                        step=f"{cap_name}_llm", role="user", content=result["llm_prompt"]
                    )
                if result.get("llm_response"):
                    branch_context.add_conversation(
                        step=f"{cap_name}_llm", role="assistant", content=result["llm_response"]
                    )

                cap_confidence = float(result.get("confidence", 0.0))
                cap_success = result.get("success", True)
                explanation = result.get("explanation", "")
                print(f"  [分支 {branch_id}] 能力 '{cap_name}' 执行完成，confidence={cap_confidence:.2f}, success={cap_success}")

                # 精简 evidence：剔除 llm_prompt / llm_response 避免冗余
                clean_evidence = {
                    k: v for k, v in result.items()
                    if k not in ("llm_prompt", "llm_response")
                }

                # 直接写入分支记忆
                branch_iteration.add_attempt(
                    step=cap_name,
                    evidence=clean_evidence,
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
                print(f"  [分支 {branch_id}] 能力 '{cap_name}' 执行异常: {e}")
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

            # 不再根据置信度自动结束分支，由 LLM 决策控制

        print(f"  [分支 {branch_id}] 循环结束，共执行 {iteration_count} 轮")

        # ========== Branch 独立 Reflection（调用 LLM） ==========
        print(f"  [分支 {branch_id}] 开始 Reflection...")
        reflector = ReflectionModule(self.config)
        reflection_result = reflector.reflect(
            memory=self.memory,
            branch_module=candidate_module,
            situation=situation,
            failed_log=failed_log,
        )

        # 记录 Reflection 的完整 LLM 对话到分支 context
        if reflection_result.get("llm_prompt"):
            branch_context.add_conversation(
                step="reflection_llm", role="user", content=reflection_result["llm_prompt"]
            )
        if reflection_result.get("llm_response"):
            branch_context.add_conversation(
                step="reflection_llm", role="assistant", content=reflection_result["llm_response"]
            )

        reflection_confidence = float(reflection_result.get("confidence", 0.0))
        reflection_explanation = reflection_result.get("explanation", "")
        reflection_evidence = reflection_result.get("evidence", [])

        # 将 reflection 结构化结果写入分支 iteration 记忆
        branch_iteration.add_attempt(
            step="reflection",
            evidence={
                "confidence": reflection_confidence,
                "explanation": reflection_explanation,
                "evidence": reflection_evidence,
                "module": candidate_module,
            },
            success=True,
            target_module=candidate_module,
            confidence=reflection_confidence,
        )

        # 用 Reflection 输出的 confidence 更新共享 memory 的模块累积分数
        if candidate_module and reflection_confidence > 0:
            self.memory.update_module_confidence(candidate_module, reflection_confidence)

        print(f"  [分支 {branch_id}] Reflection 完成，confidence={reflection_confidence:.2f}")
        print(f"[分支 {branch_id}] 执行结束，模块: {candidate_module}\n")

        return BranchResult(
            branch_id=branch_id,
            module=candidate_module,
            reflection_confidence=reflection_confidence,
            reflection_explanation=reflection_explanation,
            reflection_evidence=reflection_evidence,
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

        last_confidence = 0.0
        cap_attempts = [a for a in attempts if a.get('step') in ('log_localization', 'code_localization', 'situation_analysis')]
        if cap_attempts:
            last_confidence = cap_attempts[-1].get('confidence', 0.0)

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

## 置信度语义（严格遵守）

当前分支的置信度表示「**当前模块是否为问题根因模块**」的判断强度，不是"工作质量评分"，也不是"继续分析的必要性"。

- 0.0：可以确定「当前模块不是问题根因模块」
- 1.0：可以确定「当前模块就是问题根因模块」
- 越接近 0，越倾向于排除当前模块
- 越接近 1，越倾向于确认当前模块
- 越接近 0.5，表示当前证据仍然不充分，无法判断

**严禁出现以下矛盾：**
- 模块日志显示工作正常、explanation="verified_no_issue"，但 confidence > 0.3
- 模块被上游错误污染导致异常，但 confidence 打高分（应打低分，因为根因在上游）

## 可用 capabilities

当前分支内允许使用以下两种 capability，每次只能选一个：

- **log_localization**：从失败日志中验证当前模块是否存在异常，并定位当前模块内部可能的问题点。
  - 适用场景：日志中已经能看到明显的错误堆栈、异常输出、或模块行为矛盾，证据比较清晰
  - 优点：快，基于日志直接判断
  - 局限：当日志只显示症状、没有暴露代码逻辑本身时，可能无法定位根因

- **code_localization**：调用 Opencode（已配置 gitnexus MCP 工具）对当前模块的代码进行系统级分析。
  - 适用场景：日志证据模糊、只看到结果值不对、或需要看代码才能确认根本原因（如早期返回逻辑错误、正则匹配顺序问题、权重配置问题等）
  - 优点：能深入代码逻辑，找到日志看不出的根因
  - 局限：慢（需要 300-600 秒），只在必要时使用

## 上下游影响分析

Pipeline 各模块按严格顺序执行：rejection_classifier → intent_classifier → instruction_rewriter → command_store → parameter_extractor → protocol_builder → emqx_client。上游模块的输出直接作为下游模块的输入。

**关键原则**：
- 上游错误会导致下游模块出现**症状性异常**（如下游收到错误输入后报错），但根因在上游不在下游
- 当当前模块的异常可以被更上游的错误完全解释时，confidence 必须打低分（≤0.3），因为根因不在当前模块
- 当前模块自身有独立缺陷（与上游无关）时，confidence 才应打高分（≥0.7）

## 决策规则

1. 每个诊断分支**至少**要执行一次能力验证（log_localization 或 code_localization）。
2. **优先选择 log_localization**：
   - 如果日志中已有明确的错误信息、异常堆栈、或模块行为矛盾 → 选 log_localization
3. **log_localization 之后，根据 confidence 决定下一步**：
   - last_confidence <= 0.3：基本可以排除当前模块，结束分支
   - last_confidence > 0.3 且 < 0.5：证据不够充分，需要 code_localization 深入代码确认
   - last_confidence >= 0.5：怀疑程度较高，为了进一步定位到代码级根因，推荐执行 code_localization 进行深层确认
   - 如果日志中没有直接暴露代码逻辑错误，只有症状（如"返回值不对"但不知道哪行代码导致的）→ 即使 confidence 不高也应选 code_localization
4. **不要重复执行同一种 capability，每种 capability 最多执行两次**。
5. **code_localization 最多执行两次**。
6. 只要当前证据已经比较明确地支持「确认当前模块」或「排除当前模块」，就应该结束当前分支。
7. 不允许因为"还想更确定"而重复执行已经执行过的 capability。
8. 如果没有可执行的新 capability，必须 end_signal=true。

## 输出格式

必须只返回纯 JSON 对象，禁止包含 Markdown、解释文字或代码块。

当需要继续执行 capability 时，输出示例：

示例1（优先用日志定位）：
{{
  "capability": "log_localization",
  "end_signal": false,
  "reason": "日志中已出现该模块的异常输出，先用 log_localization 验证"
}}

示例2（日志模糊，需要代码定位）：
{{
  "capability": "code_localization",
  "end_signal": false,
  "reason": "日志只显示症状但无明确代码错误，需要 code_localization 深入代码逻辑"
}}

当应该结束当前分支时，输出：

{{
  "capability": null,
  "end_signal": true,
  "reason": "已执行过定位能力，当前证据已足够支持确认或排除当前模块，结束分支进入 Reflection"
}}"""

        try:
            messages = [
                {"role": "system", "content": "你是诊断分支规划专家，只返回纯 JSON。"},
                {"role": "user", "content": prompt}
            ]
            response = self.llm_client.chat(messages)
            result = self._parse_capability_decision(response)

            if not result:
                result = self._default_capability_decision(executed_set)
            return {
                "decision": result,
                "prompt": prompt,
                "response": response
            }

        except Exception as e:
            return {
                "decision": self._default_capability_decision(executed_set, reason=f"异常: {str(e)}"),
                "prompt": prompt,
                "response": str(e)
            }

    def _parse_capability_decision(self, response: str) -> dict:
        """解析 LLM 返回的 capability 决策"""
        cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
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

    def _default_capability_decision(self, executed_set: set, reason: str = "解析失败，使用默认行为") -> dict:
        """默认回退决策：优先 log_localization，其次 code_localization"""
        if "log_localization" not in executed_set:
            return {
                "capability": "log_localization",
                "end_signal": False,
                "reason": reason
            }
        if "code_localization" not in executed_set:
            return {
                "capability": "code_localization",
                "end_signal": False,
                "reason": reason
            }
        return {
            "capability": None,
            "end_signal": True,
            "reason": reason
        }

    