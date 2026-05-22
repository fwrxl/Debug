"""情景分析能力 - 分析测试失败情景，定位可能的问题模块"""
from typing import Dict, Any, List

from integrations.llm_client import get_llm_client


class SituationAnalyzer:
    """
    情景分析能力

    通过分析测试失败情景和日志，帮助定位 bug 可能位于哪些模块。
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.llm_client = get_llm_client()

    async def execute(
        self,
        situation: str,
        failed_log: str,
        memory: Any,
    ) -> Dict[str, Any]:
        """
        执行情景分析

        Args:
            situation: 情景描述（字符串）
            failed_log: 失败日志（字符串）
            memory: 记忆模块

        Returns:
            分析结果，包含 possible_modules, confidence, reasoning
        """
        analysis_result = self._analyze_situation(situation, failed_log)
        return analysis_result

    def _build_prompt(self, situation: str, failed_log: str) -> str:
        """构建提示词"""
        return """## 任务

分析以下测试失败情景，从中发现 bug 的线索，判断最可能出现问题的模块。

## 有效模块列表

机器人控制 Pipeline 包含以下有效模块，输出时**只能使用这些名称**：

- rejection_classifier（拒绝分类器）
- intent_classifier（意图分类器）
- instruction_rewriter（指令改写器）
- command_store（命令存储）
- parameter_extractor（参数提取器）
- protocol_builder（协议构建器）
- emqx_client（MQTT 客户端）

## Pipeline 执行顺序（数据流方向）

```
rejection_classifier → intent_classifier → instruction_rewriter → command_store → parameter_extractor → protocol_builder → emqx_client
```

上游模块的输出直接作为下游模块的输入。因此：
- **上游模块出错 → 下游模块会出现"症状性异常"**
- 症状性异常不是下游模块的独立根因
- 分析时必须判断：当前模块的异常是**自身缺陷**还是**上游污染导致的症状**

严禁：因为"当前模块在日志中有异常输出"就给高分。必须判断异常是自身缺陷还是上游污染。

## 输入信息

情景描述:
""" + situation + """

失败日志:
""" + failed_log[:4000] + """

## 输出格式

返回纯 JSON 对象（不要包含 ```json 或任何 Markdown 标记）：

{
  "possible_modules": [
    {"module": "模块ID", "explanation": "为什么这个模块可能出问题", "confidence": 0.9},
    {"module": "模块ID", "explanation": "分析依据", "confidence": 0.6}
  ]
}

## 字段说明

- possible_modules: 模块列表，按置信度从高到低排序，每个包含：
  - module: 必须是有效模块ID之一
  - explanation: 为什么这个模块可能出问题，**必须说明是自身缺陷还是上游污染导致的症状**，包含因果链
  - confidence: **该模块是独立根因模块**的置信度，0.0~1.0，不是"工作质量评分"
    - 0.70-1.00：模块存在独立缺陷，与上游无关，证据链完整
    - 0.50-0.69：模块可能有问题，但证据不够充分，需要进一步验证
    - 0.20-0.49：模块出现异常，但异常更可能是上游污染导致的症状（根因在上游）
    - 0.00-0.19：模块工作正常，或被上游波及但无独立缺陷
    严禁给"工作正常但被上游影响"的模块打高分。
    **重要原则**：如果当前模块的异常可以被更上游模块的错误完全解释，即使该模块自身有表现异常，confidence 也必须 ≤ 0.3。

## 示例

### 示例 1：指令误判
输入：
情景：用户说"往前走100步"，测试指令改写功能
日志：意图分类器将"往前走100步"识别为"闲聊"，返回"好的，请问您要去哪里？"

输出：
{
  "possible_modules": [
    {"module": "intent_classifier", "explanation": "将指令误判为闲聊，导致后续流程错误", "confidence": 0.9},
    {"module": "instruction_rewriter", "explanation": "指令改写器未收到有效指令", "confidence": 0.3}
  ]
}

### 示例 2：参数提取失败
输入：
情景：用户说"往左走"，机器人未执行转向
日志：[ParameterExtractor] regex="往<方向>走" no match in "往左走"，回退默认"前"

输出：
{
  "possible_modules": [
    {"module": "parameter_extractor", "explanation": "正则匹配失败导致方向参数丢失，回退默认值", "confidence": 0.88},
    {"module": "protocol_builder", "explanation": "参数错误可能导致协议生成偏差", "confidence": 0.2}
  ]
}

### 示例 3：上游污染导致下游症状
输入：
情景：用户说"往前走"，机器人未执行移动
日志：
```
[IntentEnsemble] 裁决完成 intent=2 conf=0.42
⚠️  裁决失败: 意图=2 但 rule_fast+llm_cmd 都命中指令
[ParameterExtractor] regex="往<方向>走" no match in "往前走"
⚠️  参数提取失败: 缺少"方向"参数，回退到默认"前"
```

输出：
{
  "possible_modules": [
    {"module": "intent_classifier", "explanation": "裁决组件将指令误判为闲聊(intent=2)，这是后续所有异常的根因", "confidence": 0.92},
    {"module": "parameter_extractor", "explanation": "regex_match 确实匹配失败，但该异常发生在上游 intent_classifier 将指令误判为闲聊之后。当前模块接收到的输入已被上游错误污染（'往前走'被误判为闲聊意图，导致 regex 模式不匹配）。这是上游错误导致的症状，不是 parameter_extractor 的独立根因。", "confidence": 0.25}
  ]
}

## 约束

1. possible_modules 中的 module 必须是以下之一：
   rejection_classifier, intent_classifier, instruction_rewriter, command_store, parameter_extractor, protocol_builder, emqx_client
2. explanation 必须包含因果链：如果判定为上游污染，必须指出是哪个上游模块的错误导致了当前模块的症状
3. 信息不足时 confidence 可以适当降低
"""

    def _analyze_situation(
        self,
        situation: str,
        failed_log: str,
    ) -> Dict[str, Any]:
        """使用 LLM 分析情景"""
        prompt = self._build_prompt(situation, failed_log)

        try:
            messages = [
                {"role": "system", "content": "你是一个测试反馈分析专家。你必须只返回纯 JSON 对象，不要包含任何 Markdown 格式（如 ```json 或 ```），不要包含思考过程，不要包含任何非 JSON 内容。"},
                {"role": "user", "content": prompt}
            ]
            response = self.llm_client.chat(messages)

            result = self._parse_llm_response(response)
            return result

        except Exception:
            return {
                "possible_modules": [],
            }

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 响应"""
        import json
        import re

        # 移除 <think>...</think> 标签
        cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)

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

        # 括号平衡法提取 JSON
        json_candidate = self._extract_json_by_bracket_balance(cleaned)
        if json_candidate:
            try:
                result = json.loads(json_candidate)
                if self._has_required_fields(result):
                    return result
            except json.JSONDecodeError:
                pass

        # 正则表达式兜底：从文本中提取字段
        fallback_result = self._extract_by_regex(cleaned)
        if fallback_result:
            return fallback_result

        # 解析失败，返回 fallback
        return {
            "possible_modules": [],
        }

    def _extract_by_regex(self, text: str) -> Dict[str, Any] | None:
        """使用正则表达式从文本中提取字段作为兜底"""
        import re

        # 提取 possible_modules
        modules = []
        # 匹配 "module": "xxx" 或 'module': 'xxx'
        module_matches = re.findall(r'["\']module["\']\s*:\s*["\']([^"\']+)["\']', text)
        if not module_matches:
            # 尝试其他格式
            module_matches = re.findall(r'"module"\s*:\s*"([^"]+)"', text)

        # 如果找不到 module，说明不是目标格式
        if not module_matches:
            return None

        # 构建模块列表（缺少 explanation 和 individual confidence，用占位符）
        for module in module_matches:
            modules.append({
                "module": module,
                "explanation": "",
                "confidence": 0.5  # 默认置信度
            })

        result = {
            "possible_modules": modules,
        }

        return result if self._has_required_fields(result) else None

    def _has_required_fields(self, obj: Dict[str, Any]) -> bool:
        """检查是否包含必要字段"""
        return 'possible_modules' in obj

    def _extract_json_by_bracket_balance(self, text: str) -> str:
        """使用括号平衡法从文本中提取 JSON 字符串"""
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
            candidate = text[start:end]
            try:
                import json
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        return ""