"""代码定位能力 - 对可疑模块进行代码级分析，确定是否由该模块导致错误"""
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional


class CodeLocator:
    """
    代码定位能力

    针对情景分析后输出的可疑模块，调用 Opencode Agent（已配置 gitnexus MCP 工具）
    进行代码级分析，判断是否是该模块导致的错误。

    设计原则：只负责调用 Opencode 并解析结果，不自行做代码收集或 LLM 分析。
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.opencode_path = os.environ.get("OPENCODE_PATH", "opencode")

    async def execute(
        self,
        situation: str,
        failed_log: str,
        memory: Any,
        module_name: str = None,
        debug_project_path: str = None,
    ) -> Dict[str, Any]:
        """
        执行代码定位

        Args:
            situation: 失败情景的自然语言描述
            failed_log: 错误日志内容
            memory: 记忆模块（包含之前能力执行结果）
            module_name: 当前需要分析的可疑模块名
            debug_project_path: 需要被 Debug 的项目本地地址

        Returns:
            定位结果，包含 module, confidence, evidence, explanation
        """
        project_path = debug_project_path or os.environ.get("DEBUG_PROJECT_PATH", "")
        if not project_path:
            return self._error_result(module_name, "未提供 DEBUG_PROJECT_PATH")

        if not module_name:
            return self._error_result("unknown", "未提供 module_name")

        # 获取分支记忆摘要（如果 memory 支持）
        branch_summary = ""
        if memory is not None and hasattr(memory, 'get_branch_summary'):
            try:
                branch_summary = memory.get_branch_summary(module_name)
            except Exception:
                branch_summary = ""

        return self._call_opencode(module_name, situation, failed_log, project_path, branch_summary)

    def _call_opencode(
        self,
        module_name: str,
        situation: str,
        failed_log: str,
        project_path: str,
        branch_summary: str = "",
    ) -> Dict[str, Any]:
        """
        调用本地 Opencode Agent 进行代码分析。
        Opencode 已配置 gitnexus MCP 工具，会自动使用 gitnexus 查询代码。
        """
        prompt = self._build_opencode_prompt(module_name, situation, failed_log, branch_summary)

        try:
            result = subprocess.run(
                [
                    self.opencode_path,
                    "run",
                    prompt,
                    "--format", "json",
                    "--dir", project_path,
                    "--dangerously-skip-permissions",
                ],
                capture_output=True,
                text=True,
                timeout=30000,
            )

            if result.returncode != 0:
                return self._error_result(
                    module_name,
                    f"Opencode 调用失败 (rc={result.returncode}): {result.stderr[:500]}"
                )

            parsed = self._parse_opencode_output(result.stdout, module_name)
            if parsed is None:
                return self._error_result(
                    module_name,
                    "无法从 Opencode 输出中解析有效 JSON"
                )
            return parsed

        except subprocess.TimeoutExpired:
            return self._error_result(module_name, "Opencode 调用超时")
        except FileNotFoundError:
            return self._error_result(
                module_name,
                f"找不到 Opencode 可执行文件: {self.opencode_path}"
            )
        except Exception as e:
            return self._error_result(module_name, f"Opencode 调用异常: {str(e)}")

    def _build_opencode_prompt(self, module_name: str, situation: str, failed_log: str, branch_summary: str = "") -> str:
        """构建给 Opencode 的指令 prompt"""
        memory_block = ""
        if branch_summary and branch_summary != "[暂无记忆]":
            memory_block = f"## 当前分支记忆\n\n{branch_summary}\n\n"

        return (
            f"你是一个代码分析专家。请使用你配置的 gitnexus MCP 工具，"
            f"对项目中的 '{module_name}' 模块进行系统分析。\n\n"
            f"## 失败情景\n{situation}\n\n"
            f"## 错误日志\n{failed_log[:3000]}\n\n"
            f"{memory_block}"
            f"## 任务要求\n"
            f"1. 只搜索和分析 '{module_name}' 模块的代码，不要搜索其他模块的代码\n"
            f"2. 使用 gitnexus 工具查询该模块的代码结构、调用关系和影响范围\n"
            f"3. 结合错误日志，判断是否是该模块导致的错误\n"
            f"4. 输出严格 JSON 格式，不要 Markdown，不要解释性前后缀\n\n"
            f"## 输出格式（必须严格遵守以下 JSON Schema）\n"
            f"{{\n"
            f'  "module": "{module_name}",          // 字符串，当前分析的模块名\n'
            f'  "confidence": 0.0,                   // 数字，范围 0.0~1.0。1.0=确定是该模块问题，0.0=确定不是\n'
            f'  "explanation": "",                   // 字符串，自然语言解释\n'
            f'  "evidence": [                        // 数组，每个元素对应一个文件的错误证据\n'
            f'    {{\n'
            f'      "file_path": "",                 // 字符串，相关代码文件路径\n'
            f'      "line_numbers": [],              // 数组，该文件内的具体行号列表\n'
            f'      "code_snippets": []              // 数组，该文件内的相关代码片段字符串列表\n'
            f'    }}\n'
            f'  ]\n'
            f'}}\n\n'
            f"## confidence 语义（必须严格遵守）\n\n"
            f"confidence 表示\"**问题根因在该模块**\"的可信程度，不是\"该模块工作质量评分\"。\n\n"
            f"- 模块**确实有问题** → confidence 越高表示越确信（0.5~1.0）\n"
            f"- 模块**没有问题** → confidence **必须为 0.0**，表示\"问题在该模块\"的概率为零\n"
            f"严禁出现模块无问题但 confidence > 0 的矛盾输出。\n\n"
            f"## Few-Shot 示例\n\n"
            f"### 示例 1：代码逻辑错误\n"
            f"输入：模块 parameter_extractor，日志：正则匹配失败，回退默认值\n"
            f"输出：\n"
            f'{{\n'
            f'  "module": "parameter_extractor",\n'
            f'  "confidence": 0.92,\n'
            f'  "explanation": "正则表达式未覆盖"往左走"语法，导致匹配失败并回退默认值",\n'
            f'  "evidence": [\n'
            f'    {{\n'
            f'      "file_path": "src/extractors/regex_extractor.py",\n'
            f'      "line_numbers": [42, 43],\n'
            f'      "code_snippets": ["pattern = r\'往<方向>走\'", "match = re.search(pattern, text)"]\n'
            f'    }}\n'
            f'  ]\n'
            f'}}\n\n'
            f"### 示例 2：模块确认无问题\n"
            f"输入：模块 protocol_builder，日志：协议生成成功\n"
            f"输出：\n"
            f'{{\n'
            f'  "module": "protocol_builder",\n'
            f'  "confidence": 0.0,\n'
            f'  "explanation": "日志显示协议生成成功，该模块无明显代码缺陷",\n'
            f'  "evidence": [\n'
            f'    {{\n'
            f'      "file_path": "",\n'
            f'      "line_numbers": [],\n'
            f'      "code_snippets": []\n'
            f'    }}\n'
            f'  ]\n'
            f'}}\n\n'
            f"## 重要约束\n"
            f"- 键名必须完全匹配上面的字段名（module / confidence / evidence / explanation）\n"
            f"- 不要输出 Markdown 代码块（```json），只输出纯 JSON\n"
            f"- 不要输出任何解释性文字或思考过程\n"
            f"- confidence 是\"问题根因在该模块\"的置信度，不是\"工作质量评分\"\n"
            f"- 模块无问题则 confidence 必须为 0.0"
        )

    def _parse_opencode_output(self, stdout: str, module_name: str) -> Optional[Dict[str, Any]]:
        """
        解析 opencode --format json 的输出。
        Opencode 的 json 输出是事件流，每行一个事件对象。
        最终答案通常嵌在 type="text" 事件的 part.text 字段里（字符串形式的 JSON）。

        解析策略：
        1. 逐行解析事件对象
        2. 对 type="text" 的事件，尝试解析 part["text"] 为 JSON（这是最终答案）
        3. 对普通 dict，按老逻辑匹配 module + confidence
        4. 兜底：括号平衡法提取所有 JSON 对象再匹配
        """
        # 步骤1：清理 markdown fences
        cleaned = re.sub(r"```(?:json)?\s*", "", stdout)
        cleaned = re.sub(r"```\s*", "", cleaned)

        all_dicts = []
        text_event_contents = []

        # 步骤2：逐行解析事件对象
        for line in cleaned.splitlines():
            line = line.strip()
            if not line:
                continue

            # 处理 SSE 格式: data: {...}
            if line.startswith("data:"):
                line = line[5:].strip()

            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    all_dicts.append(obj)
                    # Opencode 事件流：type="text" 的 part.text 里存的是最终答案字符串
                    if obj.get("type") == "text":
                        part = obj.get("part", {})
                        if isinstance(part, dict) and "text" in part:
                            text_str = part["text"]
                            if isinstance(text_str, str):
                                text_event_contents.append(text_str)
            except json.JSONDecodeError:
                continue

        # 步骤3：优先解析 text 事件里的 JSON 字符串（这是 Opencode 的最终回答）
        for text_str in text_event_contents:
            try:
                inner = json.loads(text_str)
                if isinstance(inner, dict):
                    # 检查是否是我们要的格式
                    if "module" in inner and "confidence" in inner:
                        return self._normalize_result(inner, module_name)
                    if "confidence" in inner:
                        mapped = {
                            "module": inner.get("module") or inner.get("suspect_module") or inner.get("target_module") or module_name,
                            "confidence": inner.get("confidence", 0.0),
                            "evidence": inner.get("evidence", {}),
                            "explanation": inner.get("explanation", "") or inner.get("summary", "") or inner.get("reason", ""),
                        }
                        return self._normalize_result(mapped, module_name)
            except json.JSONDecodeError:
                continue

        # 步骤4：从所有行内 dict 中匹配
        # 4a: 同时有 module + confidence
        for d in all_dicts:
            if "module" in d and "confidence" in d:
                return self._normalize_result(d, module_name)

        # 4b: 有 confidence（可能字段名是 suspect_module 等）
        for d in all_dicts:
            if "confidence" in d:
                mapped = {
                    "module": d.get("module") or d.get("suspect_module") or d.get("target_module") or module_name,
                    "confidence": d.get("confidence", 0.0),
                    "evidence": d.get("evidence", {}),
                    "explanation": d.get("explanation", "") or d.get("summary", "") or d.get("reason", ""),
                }
                return self._normalize_result(mapped, module_name)

        # 4c: 有 module 但没有 confidence（给默认 0.5）
        for d in all_dicts:
            if "module" in d:
                d.setdefault("confidence", 0.5)
                return self._normalize_result(d, module_name)

        # 步骤5：兜底 — 括号平衡法提取所有 JSON 对象
        bracket_dicts = self._extract_all_json_objects(cleaned)
        for d in bracket_dicts:
            if "module" in d and "confidence" in d:
                return self._normalize_result(d, module_name)

        return None

    def _extract_all_json_objects(self, text: str) -> List[Dict[str, Any]]:
        """使用括号平衡法从文本中提取所有 JSON 对象"""
        results = []
        i = 0
        while i < len(text):
            start_idx = text.find("{", i)
            if start_idx == -1:
                break

            depth = 0
            start = None
            end = None
            for j in range(start_idx, len(text)):
                ch = text[j]
                if ch == "{":
                    if depth == 0:
                        start = j
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = j + 1
                        break

            if start is not None and end is not None:
                candidate = text[start:end]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        results.append(obj)
                except json.JSONDecodeError:
                    pass
                i = end
            else:
                break
        return results

    def _normalize_result(self, result: Dict[str, Any], module_name: str) -> Dict[str, Any]:
        """规范化结果，确保字段完整"""
        evidence = result.get("evidence", [])
        if isinstance(evidence, str):
            evidence = [{"file_path": evidence, "line_numbers": [], "code_snippets": []}]
        elif isinstance(evidence, dict):
            # 兼容旧格式的单对象证据
            evidence = [evidence]
        elif not isinstance(evidence, list):
            evidence = []

        # 规范化每个证据条目
        normalized_evidence = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            normalized_evidence.append({
                "file_path": item.get("file_path", ""),
                "line_numbers": item.get("line_numbers", []),
                "code_snippets": item.get("code_snippets", []),
            })

        return {
            "module": result.get("module", module_name),
            "confidence": float(result.get("confidence", 0.0)),
            "explanation": result.get("explanation", ""),
            "evidence": normalized_evidence,
        }

    def _error_result(self, module_name: str, reason: str) -> Dict[str, Any]:
        """构造错误结果"""
        return {
            "module": module_name or "unknown",
            "confidence": 0.0,
            "explanation": reason,
            "evidence": [],
        }
