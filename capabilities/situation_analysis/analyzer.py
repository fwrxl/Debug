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

## 输入信息

情景描述:
""" + situation + """

失败日志:
""" + failed_log[:4000] + """

## 输出格式

返回纯 JSON 对象（不要包含 ```json 或任何 Markdown 标记）：

{
  "possible_modules": [
    {"module": "模块ID", "reason": "为什么这个模块可能出问题", "confidence": 0.9},
    {"module": "模块ID", "reason": "分析依据", "confidence": 0.6}
  ],
  "confidence": 0.7,
  "reasoning": "简要分析思路（30字以内）"
}

## 字段说明

- possible_modules: 模块列表，按置信度从高到低排序，每个包含：
  - module: 必须是有效模块ID之一
  - reason: 为什么这个模块可能出问题
  - confidence: 该模块是问题根源的置信度 0.0~1.0
- confidence: 整体分析的置信度 0.0~1.0
- reasoning: 分析思路简述，30字以内

## 示例

输入：
情景：用户说"往前走100步"，测试指令改写功能
日志：意图分类器将"往前走100步"识别为"闲聊"，返回"好的，请问您要去哪里？"

输出：
{
  "possible_modules": [
    {"module": "intent_classifier", "reason": "将指令误判为闲聊，导致后续流程错误", "confidence": 0.9},
    {"module": "instruction_rewriter", "reason": "指令改写器未收到有效指令", "confidence": 0.3}
  ],
  "confidence": 0.85,
  "reasoning": "闲聊回复说明意图分类误判"
}

## 约束

1. possible_modules 中的 module 必须是以下之一：
   rejection_classifier, intent_classifier, instruction_rewriter, command_store, parameter_extractor, protocol_builder
2. reasoning 控制在30字以内
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
            response = self.llm_client.chat(messages, max_tokens=800)

            result = self._parse_llm_response(response)
            return result

        except Exception as e:
            return {
                "possible_modules": [],
                "confidence": 0.0,
                "reasoning": f"分析失败: {str(e)}"
            }

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 响应"""
        import json
        import re

        # 移除 <think>... 标签
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
            "confidence": 0.0,
            "reasoning": "JSON 解析失败"
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

        # 提取 confidence 和 reasoning
        confidence_match = re.search(r'"confidence"\s*:\s*([\d.]+)', text)
        reasoning_match = re.search(r'"reasoning"\s*:\s*"([^"]+)"', text)

        # 如果找不到 module，说明不是目标格式
        if not module_matches:
            return None

        # 构建模块列表（缺少 reason 和 individual confidence，用占位符）
        for module in module_matches:
            modules.append({
                "module": module,
                "reason": "",
                "confidence": 0.5  # 默认置信度
            })

        result = {
            "possible_modules": modules,
            "confidence": float(confidence_match.group(1)) if confidence_match else 0.5,
            "reasoning": reasoning_match.group(1) if reasoning_match else "正则提取"
        }

        return result if self._has_required_fields(result) else None

    def _has_required_fields(self, obj: Dict[str, Any]) -> bool:
        """检查是否包含必要字段"""
        return 'possible_modules' in obj and 'confidence' in obj and 'reasoning' in obj

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