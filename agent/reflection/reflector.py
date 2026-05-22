"""反思模块 - 每个分支调用 LLM 进行反思，输出该分支模块的置信度"""
from typing import Dict, Any, List, Optional
from agent.memory.memory import MemoryModule
from integrations.llm_client import get_llm_client


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
        "command_store", "parameter_extractor", "protocol_builder", "emqx_client"
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
            - explanation: 反思结论
            - evidence: 证据列表
            - llm_prompt: 反思使用的 prompt
            - llm_response: LLM 返回的原始响应
        """
        # 获取完整分支记忆（优先使用 get_branch_summary，否则回退到旧逻辑）
        branch_summary = ""
        if hasattr(memory, 'get_branch_summary'):
            try:
                branch_summary = memory.get_branch_summary(branch_module)
            except Exception:
                branch_summary = ""

        if not branch_summary or branch_summary == "[暂无记忆]":
            # 回退：从分支记忆读取 attempts 构建简单摘要
            if hasattr(memory, 'branch_memories') and branch_module in memory.branch_memories:
                attempts = memory.branch_memories[branch_module]["iteration"].attempts
            else:
                attempts = memory.iteration.attempts
            branch_summary = self._build_execution_summary(attempts, branch_module)

        # 调用 LLM 进行反思
        reflection_result = self._llm_reflect(
            branch_module=branch_module,
            situation=situation,
            failed_log=failed_log,
            branch_summary=branch_summary,
        )

        # 规范化结果
        normalized = self._normalize_reflection_result(reflection_result, branch_module)

        # 附加 debug 字段，供 conversation 记录完整对话
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
                explanation = evidence.get("explanation", "unknown")
                lines.append(f"failed_module: {failed_module}")
                lines.append(f"failed_component: {failed_component}")
                lines.append(f"explanation: {explanation}")
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
        branch_summary: str,
    ) -> Dict[str, Any]:
        """调用 LLM 进行单分支反思"""
        situation_desc = situation

        prompt = f"""## 任务

你是当前诊断分支的反思器。你的唯一任务是：基于分支内已执行的能力结果和失败日志，评估"问题根因是否属于当前分支的模块 {branch_module}"。

你禁止执行任何其他判断，包括但不限于：
- 禁止决定是否发送通知
- 禁止决定整个诊断流程是否停止
- 禁止将其他模块指定为问题模块
- 禁止输出任何与 JSON 格式无关的思考过程或解释文字

## 当前分支模块

{branch_module}

## 情景描述

{situation_desc}

## 失败日志

{failed_log[:3000]}

## 当前分支完整记忆（包含决策对话和能力执行结果）

{branch_summary}

## 反思要求

1. **评估问题归属**：基于上述完整分支记忆（包括 Agent 的决策过程、各能力执行结果、对话历史）和失败日志，严格评估"问题根因是否属于 {branch_module} 模块"。判断时必须同时依据：
   - 失败日志中该模块的直接异常记录
   - 分支内已执行能力（如 log_localization / code_localization）对该模块的具体分析结论
   禁止仅凭直觉或情景描述打分，禁止考虑其他分支模块的表现。

2. **给出置信度**：confidence 必须是 0.0-1.0 的纯数字，表示"**问题根因在该模块**"的可信程度，不是"该模块工作质量评分"。
   - 模块确实有问题 → confidence 越高越确信（0.5~1.0）
   - 模块没有问题 → confidence 必须接近 0.0，表示"问题在该模块"的概率为零
   严禁出现"模块无问题"但 confidence 很高（如 >0.5）的矛盾输出。
   打分规则：
   - 0.90-1.00：日志和分支能力均明确指向该模块存在根因，证据链完整
   - 0.70-0.89：日志或分支能力有较强的指向性，但存在少量可解释的异常
   - 0.40-0.69：证据模棱两可，既有支持也有反驳的线索
   - 0.10-0.39：证据倾向于排除该模块，但无法完全确认
   - 0.00-0.09：日志和分支能力均表明该模块无问题，或问题已被充分排除

   **上下游影响规则（必须严格遵守）**：
   Pipeline 顺序：rejection_classifier → intent_classifier → instruction_rewriter → command_store → parameter_extractor → protocol_builder → emqx_client。
   - 如果当前模块的异常可以被更上游模块的错误**完全解释**（如上游输出错误数据导致当前模块处理失败），则当前模块的 confidence 必须 ≤ 0.3，因为这是"症状"不是"根因"
   - 只有当当前模块存在**独立缺陷**（与上游无关）时，confidence 才应 ≥ 0.5
   - 严禁因为"当前模块确实报错了"就给高分——必须判断报错是自身缺陷还是上游污染导致的症状

3. **列出关键证据**：evidence 数组中的每条证据必须引用日志原文或能力执行结果中的具体信息（如具体的错误日志行、具体的组件名、具体的根因描述），禁止输出空洞的概括性语句（如"模块表现异常"、"日志显示有问题"）。

## 输出格式

必须且只返回一个纯 JSON 对象，禁止包含 Markdown 代码块标记（```json）、解释文字、思考过程或任何其他内容：

{{
  "module": "{branch_module}",
  "confidence": 0.0-1.0,
  "explanation": "为什么问题属于或不属于当前模块",
  "evidence": ["证据1", "证据2"]
}}

## Few-Shot 示例

### 示例 1：确认当前模块有问题（独立根因）
输入分支模块：intent_classifier
日志证据："[IntentEnsemble] 裁决完成 intent=2 conf=0.42"，"⚠️ 裁决失败: 意图=2 但 rule_fast+llm_cmd 都命中指令"
分支能力结论：log_localization 定位到 failed_component="裁决"

输出：
{{
  "module": "intent_classifier",
  "confidence": 0.92,
  "explanation": "日志和分支能力均明确指向该模块的裁决组件：rule_fast(0.8)和llm_cmd(0.7)均识别为指令，但裁决仍输出闲聊intent=2",
  "evidence": [
    "日志行：'[IntentEnsemble] 裁决完成 intent=2 conf=0.42'",
    "日志行：'⚠️ 裁决失败: 意图=2 但 rule_fast+llm_cmd 都命中指令'",
    "log_localization 结果：failed_component='裁决'"
  ]
}}

### 示例 2：排除当前模块（自身无问题）
输入分支模块：command_store
日志证据："[CommandStoreClient] vector_search k=5 score=0.72"，"✅ ES搜索成功: 匹配 cmd_001"
分支能力结论：log_localization 返回 explanation="verified_no_issue"

输出：
{{
  "module": "command_store",
  "confidence": 0.02,
  "explanation": "日志显示 vector_search 成功匹配 cmd_001，ES搜索无异常；log_localization 已验证该模块无问题",
  "evidence": [
    "日志行：'[CommandStoreClient] vector_search k=5 score=0.72'",
    "日志行：'✅ ES搜索成功: 匹配 cmd_001'",
    "log_localization 结果：explanation='verified_no_issue'"
  ]
}}

### 示例 3：上游污染导致下游症状（非根因模块）
输入分支模块：parameter_extractor
日志证据："[IntentEnsemble] 裁决完成 intent=2 conf=0.42"（上游已误判），"[ParameterExtractor] regex='往<方向>走' no match in '往前走'"
分支能力结论：log_localization 定位到 regex_match 失败

输出：
{{
  "module": "parameter_extractor",
  "confidence": 0.18,
  "explanation": "当前模块的 regex_match 确实匹配失败，但该异常发生在上游 intent_classifier 将指令误判为闲聊之后。上游错误导致当前模块接收到了异常输入，regex 匹配失败是症状而非独立根因。根因在上游 intent_classifier 的裁决组件。",
  "evidence": [
    "日志行：'[IntentEnsemble] 裁决完成 intent=2 conf=0.42' - 上游在阶段1已误判为闲聊",
    "日志行：'[ParameterExtractor] regex=\"往<方向>走\" no match in \"往前走\"' - 匹配失败确实发生",
    "因果关系：上游误判 → 下游收到异常输入 → regex 匹配失败是症状，不是独立缺陷"
  ]
}}

**重要**：示例3 中 confidence 为 0.18（低分），因为当前模块的异常可以被更上游的错误完全解释。严禁因为"当前模块确实出现了报错"就给高分。

## 重要约束

1. module 字段必须严格等于 "{branch_module}"，任何其他值（包括大小写差异）均视为无效输出，会导致解析失败。
2. confidence 必须是 0.0 到 1.0 之间的纯数字，禁止使用字符串形式，禁止超出此范围。
3. 禁止输出 decision、final_module、stop、notify、action 等额外字段。
4. 禁止在 JSON 中输出"停止通知"、"跳过 Finalization"、"通知某某"等流程控制文字。
4. 只反思当前模块 {branch_module}，禁止在 explanation 或 evidence 中与其他模块进行比较或引用其他模块的结论。
6. 禁止在 JSON 前后输出任何 ``` 标记或自然语言解释。"""

        try:
            messages = [
                {"role": "system", "content": "你是分支反思专家，只返回纯 JSON。"},
                {"role": "user", "content": prompt}
            ]
            response = self.llm_client.chat(messages)

            # 解析 LLM 返回的 JSON
            result = self._parse_llm_response(response)
            result["llm_prompt"] = prompt
            result["llm_response"] = response
            return result

        except Exception as e:
            return {
                "module": branch_module,
                "confidence": 0.0,
                "explanation": f"反思失败: {str(e)}",
                "evidence": [],
                "llm_prompt": prompt,
                "llm_response": str(e)
            }

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 响应

        解析策略：
        1. 移除 <think> 标签和 markdown code fences
        2. 使用 json.JSONDecoder.raw_decode 自动跳过前导垃圾文本
        3. 回退到括号平衡法提取
        4. 失败时返回带标记的结构，便于上层感知并处理
        """
        import json
        import re

        # 步骤1：清理标签和 fences
        cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
        cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()

        # 步骤2：使用 raw_decode 自动跳过前导文本
        decoder = json.JSONDecoder()
        try:
            result, idx = decoder.raw_decode(cleaned)
            if isinstance(result, dict) and self._has_required_fields(result):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        # 步骤3：括号平衡法兜底
        json_candidate = self._extract_json_by_bracket_balance(cleaned)
        if json_candidate:
            try:
                result = json.loads(json_candidate)
                if isinstance(result, dict) and self._has_required_fields(result):
                    return result
            except json.JSONDecodeError:
                pass

        # 步骤4：解析失败，返回带标记的结构
        return {
            "__parse_failed__": True,
            "module": "",
            "confidence": 0.0,
            "explanation": "",
            "evidence": [],
            "raw_response_snippet": response[:500],
        }

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
            "explanation": "",
            "evidence": [],
        }

        if isinstance(result, dict):
            # 如果解析失败但带了原始响应片段，记录失败标记
            if result.get("__parse_failed__"):
                normalized["explanation"] = f"JSON 解析失败，原始响应片段: {result.get('raw_response_snippet', '')[:200]}"
                return normalized

            try:
                confidence = float(result.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0

            # 强制 confidence 在 0.0-1.0 之间
            normalized["confidence"] = max(0.0, min(1.0, confidence))
            normalized["explanation"] = str(result.get("explanation", "") or result.get("reason", ""))

            evidence = result.get("evidence", [])
            if isinstance(evidence, list):
                normalized["evidence"] = [str(item) for item in evidence]
            else:
                normalized["evidence"] = []

        return normalized

    def global_reflect(
        self,
        situation: str,
        failed_log: str,
        branch_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        全局反思 — 在所有分支执行结束后，基于 Pipeline 顺序和因果链分析，
        找出最前端的根因模块。

        Args:
            situation: 情景描述
            failed_log: 失败日志
            branch_results: 各分支 reflection 结果列表，每项包含:
                - module: 分支模块名
                - confidence: 分支反思置信度
                - explanation: 分支反思理由
                - evidence: 分支反思证据

        Returns:
            {
                "root_cause_module": "最可能的根因模块名",
                "confidence": 0.92,
                "explanation": "完整诊断报告（包含因果链分析、证据引用、症状说明）"
            }
        """
        # 构建分支结论摘要
        branch_summary_lines = []
        for br in branch_results:
            mod = br.get("module", "unknown")
            conf = br.get("reflection_confidence", 0.0)
            reason = br.get("reflection_reason", "")
            evidence = br.get("reflection_evidence", [])
            branch_summary_lines.append(f"- {mod}: confidence={conf:.2f}, reason={reason}")
            if evidence:
                for ev in evidence:
                    branch_summary_lines.append(f"  - evidence: {ev}")

        branch_summary = "\n".join(branch_summary_lines)

        prompt = f"""## 任务

你是全局诊断专家。所有分支已独立完成分析，你的任务是基于 Pipeline 执行顺序和各分支结论，找出**最前端的根因模块**。

## Pipeline 执行顺序（一条直线）

机器人控制 Pipeline 的模块按以下严格顺序执行：

```
rejection_classifier → intent_classifier → instruction_rewriter → command_store → parameter_extractor → protocol_builder → emqx_client
```

数据流是单向的：前一个模块的输出直接作为后一个模块的输入。因此，**上游模块的错误会直接导致下游模块的异常表现**。

## 核心原则：因果覆盖分析

1. **上游错误导致下游症状**：如果上游模块 X 的错误输出可以逻辑上解释下游模块 Y 的异常行为，则 Y 的异常是 X 的"症状"，不是独立根因。
2. **前端优先**：在因果链中，最靠近错误起点的模块优先级最高。
3. **证据独立性**：只有当两个模块的异常无法用因果关系解释时，才保留多个候选（但输出时只选一个最前端的）。
4. **置信度不是唯一标准**：一个下游模块的分支 reflection confidence 很高，但如果它的异常可以被更上游的模块错误完全解释，则上游模块才是根因。

## 各分支独立分析结论

{branch_summary}

## 失败日志

{failed_log[:3000]}

## 情景描述

{situation}

## 分析要求

1. **识别最前端异常**：查看日志，找出 Pipeline 中哪个模块最先出现异常输出或错误行为。
2. **因果链验证**：判断后续模块的异常是否可以用该最前端模块的错误来解释。
3. **给出根因模块**：必须是 Pipeline 中的一个有效模块名。
4. **给出置信度**：confidence 必须是 0.0-1.0 的纯数字，表示对根因判断的确信程度。
5. **撰写诊断报告**：explanation 必须包含：
   - 根因模块的具体错误
   - 该错误如何导致后续症状
   - 被判定为"症状"的模块有哪些
   - 关键证据引用（日志原文或分支结论）

## 输出格式

必须且只返回一个纯 JSON 对象，禁止包含 Markdown 代码块标记（```json）、解释文字、思考过程或任何其他内容：

{{
  "root_cause_module": "最可能的根因模块名",
  "confidence": 0.0-1.0,
  "explanation": "完整诊断报告，包含因果链分析、症状说明和关键证据",
  "symptom_modules": ["症状模块1", "症状模块2"]
}}

## Few-Shot 示例

### 示例 1：上游误判导致下游症状
各分支结论：
- intent_classifier: confidence=0.92, reason="裁决组件错误输出闲聊意图"
- parameter_extractor: confidence=0.60, reason="正则匹配失败"
- protocol_builder: confidence=0.30, reason="协议生成基于错误参数"

日志："[IntentEnsemble] 裁决完成 intent=2 conf=0.42"，"[ParameterExtractor] regex 匹配失败，回退默认值"

分析：intent_classifier 在 Pipeline 最前端将指令误判为闲聊，导致后续 parameter_extractor 和 protocol_builder 均基于错误意图执行。parameter_extractor 的匹配失败是因为输入已被错误分类。

输出：
{{
  "root_cause_module": "intent_classifier",
  "confidence": 0.94,
  "explanation": "根因：intent_classifier 的裁决组件将用户指令'往前走'误判为闲聊(intent=2)，置信度仅0.42。该错误发生在 Pipeline 最前端(阶段1)，直接导致后续所有模块处理的是闲聊意图而非移动指令。parameter_extractor 的正则匹配失败和 protocol_builder 的协议偏差均为该根因的连锁症状——它们接收到的输入已被上游错误污染。证据：1) 日志'[IntentEnsemble] 裁决完成 intent=2 conf=0.42'；2) 分支 reflection 显示 intent_classifier confidence=0.92；3) parameter_extractor 的分支 confidence=0.60 但发生在 intent_classifier 之后。",
  "symptom_modules": ["parameter_extractor", "protocol_builder"]
}}

### 示例 2：独立错误，根因即本身
各分支结论：
- intent_classifier: confidence=0.15, reason="输出正确，无异常"
- parameter_extractor: confidence=0.88, reason="正则未覆盖'往左走'语法，方向参数丢失"

日志："[ParameterExtractor] regex='往<方向>走' no match in '往左走'"

分析：intent_classifier 正常输出指令意图，parameter_extractor 独立出现正则匹配缺陷，与上游无关。

输出：
{{
  "root_cause_module": "parameter_extractor",
  "confidence": 0.90,
  "explanation": "根因：parameter_extractor 的正则表达式 '往<方向>走' 未能覆盖 '往左走' 的语法变体，导致方向参数提取失败并回退默认值。该错误是模块自身的逻辑缺陷，与上游 intent_classifier 无关（intent_classifier 已正确识别为指令意图）。无下游症状模块。证据：1) 日志'[ParameterExtractor] regex=... no match in 往左走'；2) 分支 reflection 显示 parameter_extractor confidence=0.88；3) intent_classifier 分支已排除该模块(confidence=0.15)。",
  "symptom_modules": []
}}

## 重要约束

1. root_cause_module 必须是 Pipeline 中的有效模块名之一。
2. confidence 必须是 0.0 到 1.0 之间的纯数字。
3. explanation 必须包含因果链分析：说明为什么该模块是根因，以及哪些后续模块的异常是它的症状。
5. 禁止在 JSON 前后输出任何 ``` 标记或自然语言解释。"""

        try:
            messages = [
                {"role": "system", "content": "你是全局诊断专家，只返回纯 JSON。"},
                {"role": "user", "content": prompt}
            ]
            response = self.llm_client.chat(messages)

            result = self._parse_global_response(response)
            result["llm_prompt"] = prompt
            result["llm_response"] = response
            return result

        except Exception as e:
            return {
                "root_cause_module": "",
                "confidence": 0.0,
                "explanation": f"全局反思失败: {str(e)}",
                "llm_prompt": prompt,
                "llm_response": str(e)
            }

    def _parse_global_response(self, response: str) -> Dict[str, Any]:
        """解析全局反思的 LLM 响应

        解析策略（与 _parse_llm_response 保持一致）：
        1. 移除 <think> 标签和 markdown code fences
        2. 使用 json.JSONDecoder.raw_decode 自动跳过前导垃圾文本
        3. 回退到括号平衡法提取
        4. 失败时返回带标记的结构
        """
        import json
        import re

        # 步骤1：清理标签和 fences
        cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
        cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()

        # 步骤2：使用 raw_decode 自动跳过前导文本
        decoder = json.JSONDecoder()
        try:
            result, idx = decoder.raw_decode(cleaned)
            if isinstance(result, dict) and self._has_global_fields(result):
                return self._normalize_global_result(result)
        except (json.JSONDecodeError, ValueError):
            pass

        # 步骤3：括号平衡法兜底
        json_candidate = self._extract_json_by_bracket_balance(cleaned)
        if json_candidate:
            try:
                result = json.loads(json_candidate)
                if isinstance(result, dict) and self._has_global_fields(result):
                    return self._normalize_global_result(result)
            except json.JSONDecodeError:
                pass

        # 步骤4：解析失败，返回显式标记
        return {
            "root_cause_module": "",
            "confidence": 0.0,
            "explanation": f"无法解析全局反思响应，原始响应片段: {response[:500]}",
        }

    def _has_global_fields(self, obj: Dict[str, Any]) -> bool:
        """检查全局反思结果是否包含必要字段"""
        return 'root_cause_module' in obj and 'confidence' in obj and 'explanation' in obj

    def _normalize_global_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """规范化全局反思结果"""
        normalized = {
            "root_cause_module": "",
            "confidence": 0.0,
            "explanation": "",
            "symptom_modules": [],
        }

        if isinstance(result, dict):
            normalized["root_cause_module"] = str(result.get("root_cause_module", ""))
            try:
                confidence = float(result.get("confidence", 0.0))
                normalized["confidence"] = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                normalized["confidence"] = 0.0
            normalized["explanation"] = str(result.get("explanation", "") or result.get("diagnosis", ""))
            symptom_modules = result.get("symptom_modules", [])
            if isinstance(symptom_modules, list):
                normalized["symptom_modules"] = [str(item) for item in symptom_modules]
            else:
                normalized["symptom_modules"] = []

        return normalized

