"""日志定位能力 - 从日志中深入分析问题，定位到具体模块的具体部分"""
from typing import Dict, Any, List, Optional

from integrations.llm_client import get_llm_client


class LogLocator:
    """
    日志定位能力

    从失败日志中深入分析问题，定位到：
    1. 具体是哪个模块出现问题
    2. 模块中具体哪个部分出了问题（如某个函数、某个判断逻辑）
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.llm_client = get_llm_client()

    async def execute(
        self,
        situation: str,
        failed_log: str,
        memory: Any,
        suspicious_module: str = None,
    ) -> Dict[str, Any]:
        """
        执行日志定位

        深入分析日志，定位问题模块和具体位置。

        Args:
            situation: 情景描述
            failed_log: 失败日志
            memory: 记忆模块
            suspicious_module: 可疑模块，包含 module, reason, confidence

        Returns:
            定位结果，包含 failed_module, failed_component, error_location, root_cause
        """
        analysis_result = self._analyze_log(situation, failed_log, suspicious_module)
        return analysis_result

    def _analyze_log(
        self,
        situation: str,
        failed_log: str,
        suspicious_module: str = None,
    ) -> Dict[str, Any]:
        """使用 LLM 深入分析日志"""
        llm_prompt = ""
        llm_response = ""

        # 定义系统模块和组件
        module_components = {
            "rejection_classifier": ["filter", "safe_check", "toxic_detect"],
            "intent_classifier": ["classify", "ensemble", "裁决", "conf_threshold"],
            "instruction_rewriter": ["rewrite", "ES_search", "LLM_process"],
            "command_store": ["vector_search", "text_search", "merge_results"],
            "parameter_extractor": ["regex_match", "capture", "default_fallback"],
            "protocol_builder": ["template_match", "param_substitute"],
        }

        # 构建可疑模块信息
        suspicious_module_str = ""
        target_module_id = "unknown"
        target_module_components = []

        if suspicious_module:
            # suspicious_module 现在只接受 str（模块名字符串）
            target_module_id = suspicious_module
            reason = ""
            conf = 0.0
            target_module_components = module_components.get(target_module_id, [])
            components_str = ", ".join(target_module_components) if target_module_components else "未知组件"

            suspicious_module_str = f"""
## 待验证模块

模块名称: {target_module_id}
模块置信度: {conf}
怀疑原因: {reason}

模块内部组件: {components_str}

**你必须只分析这个模块，不要分析其他模块。**
**通过日志验证该模块是否确实存在问题，并定位到具体的组件。**
"""

        prompt = f"""## 任务

你是机器人控制 Pipeline 的日志分析专家。验证可疑模块是否存在问题，定位到具体的组件。

{suspicious_module_str}
## 输入信息

情景描述: {situation}


失败日志:
{failed_log[:5000]}

## 分析要求

1. **只分析上述待验证模块**：不要分析其他模块，即使日志中提到了其他模块
2. **分析该模块的日志表现**：查看该模块在日志中的输出
3. **定位问题组件**：找出该模块中具体哪个组件出了问题
4. **如果该模块没有问题**：返回 root_cause = "verified_no_issue"
5. **计算置信度**：根据日志证据的充分性和问题定位的确定性，给出 confidence (0.0~1.0)

## 输出格式

必须返回纯 JSON 对象，禁止包含任何 Markdown 标记、思考过程或解释文字：

{{
  "failed_module": "{target_module_id}",
  "failed_component": "该模块内的具体组件名称",
  "error_location": "日志中的具体错误位置",
  "root_cause": "根本原因分析，或 'verified_no_issue' 表示该模块没有问题",
  "confidence": 确认是当前模块出问题的置信度，0.0~1.0 的数字。
}}

## Few-Shot 示例

### 示例 1：模块存在问题
输入：待验证模块=intent_classifier，模块组件=["classify", "ensemble", "裁决", "conf_threshold"]
日志：
```
[IntentEnsemble] 裁决完成 intent=2 conf=0.42
[Ensemble] trace rule_fast: intent=2 conf=0.8
[Ensemble] trace llm_cmd: intent=1 conf=0.7
⚠️  裁决失败: 意图=2 但 rule_fast+llm_cmd 都命中指令
```
输出：
{{
  "failed_module": "intent_classifier",
  "failed_component": "裁决",
  "error_location": "[IntentEnsemble] 裁决完成 intent=2 conf=0.42",
  "root_cause": "裁决组件在 rule_fast(0.8)和 llm_cmd(0.7)都识别为指令时仍输出闲聊 intent=2",
  "confidence": 0.9
}}

### 示例 2：模块没有问题
输入：待验证模块=command_store，模块组件=["vector_search", "text_search", "merge_results"]
日志：
```
[CommandStoreClient] vector_search k=5 score=0.72
[CommandStoreClient] matched_command: {{"id": "cmd_001"}}
✅ ES搜索成功: 匹配 cmd_001
```
输出：
{{
  "failed_module": "command_store",
  "failed_component": "N/A",
  "error_location": "N/A",
  "root_cause": "verified_no_issue",
  "confidence": 0.95
}}

## 重要约束

1. **只输出 JSON**：禁止输出 ```json、```、解释文字或思考过程
2. **failed_module**：必须返回 "{target_module_id}"
3. **root_cause**：如果该模块没有问题，必须返回 "verified_no_issue" 此时confidence：必须返回 0.0
4. **confidence**：必须返回 0.0~1.0 的数字，表示日志证据支持"问题在该模块"的置信度
5. **只分析待验证模块**：不要分析其他模块
6. **所有字段必须完整**：输出必须包含全部 5 个字段，缺一不可"""

        try:
            messages = [
                {"role": "system", "content": "你是一个 JSON 输出机器。只返回纯 JSON，不要输出任何其他内容。"},
                {"role": "user", "content": prompt}
            ]
            llm_prompt = prompt
            response = self.llm_client.chat(messages, max_tokens=1000)
            llm_response = response

            result = self._parse_llm_response(response)
            result["llm_prompt"] = llm_prompt
            result["llm_response"] = llm_response
            return result

        except Exception as e:
            return {
                "failed_module": target_module_id,
                "failed_component": "unknown",
                "error_location": "unknown",
                "root_cause": f"分析失败: {str(e)}",
                "confidence": 0.0,
                "llm_prompt": llm_prompt,
                "llm_response": str(e)
            }

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 响应

        解析策略：
        1. 移除所有 <think>... 标签（re.DOTALL 模式）
        2. 移除 markdown code fences
        3. 尝试直接 json.loads
        4. 如果失败，使用括号平衡法提取最大可解析 JSON
        """
        import json
        import re

        # 步骤1：移除所有 <think>... 标签
        cleaned = re.sub(r'<think>.*?', '', response, flags=re.DOTALL)

        # 步骤2：移除 markdown code fences
        cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned)

        # 步骤3：尝试直接解析
        cleaned = cleaned.strip()
        try:
            result = json.loads(cleaned)
            if self._has_log_fields(result):
                # 确保 confidence 字段存在
                if 'confidence' not in result:
                    result['confidence'] = 0.5
                return result
        except json.JSONDecodeError:
            pass

        # 步骤4：括号平衡法提取 JSON
        json_candidate = self._extract_json_by_bracket_balance(cleaned)
        if json_candidate:
            try:
                result = json.loads(json_candidate)
                if self._has_log_fields(result):
                    # 确保 confidence 字段存在
                    if 'confidence' not in result:
                        result['confidence'] = 0.5
                    return result
            except json.JSONDecodeError:
                pass

        # 解析失败，返回 fallback
        return {
            "failed_module": "unknown",
            "failed_component": "unknown",
            "error_location": "unknown",
            "root_cause": "LLM 返回格式错误",
            "confidence": 0.0
        }

    def _has_log_fields(self, obj: Dict[str, Any]) -> bool:
        """检查是否包含日志定位必要字段"""
        required = ['failed_module', 'failed_component', 'error_location', 'root_cause']
        return all(k in obj for k in required)

    def _extract_json_by_bracket_balance(self, text: str) -> str:
        """使用括号平衡法从文本中提取 JSON 字符串

        从第一个 '{' 开始，使用括号平衡找到最外层的 {} 对，
        然后验证该 JSON 是否包含必要字段。
        """
        import json

        start_idx = text.find('{')
        if start_idx == -1:
            return ""

        # 使用栈来跟踪括号平衡
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
            # 验证是否能解析
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        return ""