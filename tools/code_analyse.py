"""
Code Analyse Tool —— 独立实现，分析测试失败并定位 Bug。

内联了原 capabilities/code_analyse/analyzer.py 和 utils/json_parser.py 的核心逻辑，
不依赖项目根目录下的旧模块。
"""
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ========== env helper ==========

def _load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    env = {}
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# ========== JSON parser helpers (from utils/json_parser.py) ==========

def _clean_response(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.replace("\"", "\"").replace("\"", "\"")
    cleaned = cleaned.strip()
    return cleaned


def _fix_common_json_errors(text: str) -> str:
    if not text:
        return text
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    if open_braces > 0:
        text += "}" * open_braces
    if open_brackets > 0:
        text += "]" * open_brackets
    return text


def _extract_json_by_bracket_balance(text: str) -> List[str]:
    results = []
    in_string = False
    escape_next = False
    string_char = None
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch in ('"', "'"):
            if not in_string:
                in_string = True
                string_char = ch
            elif string_char == ch:
                in_string = False
                string_char = None
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : i + 1]
                try:
                    json.loads(candidate)
                    results.append(candidate)
                except json.JSONDecodeError:
                    pass
                start = None
    return results


def _parse_json(text: str, required_fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    cleaned = _clean_response(text)
    if not cleaned:
        return None

    def _is_valid(obj: Any) -> bool:
        if not isinstance(obj, dict):
            return False
        if required_fields:
            if not all(k in obj for k in required_fields):
                return False
        return True

    decoder = json.JSONDecoder()
    try:
        result, idx = decoder.raw_decode(cleaned)
        if _is_valid(result):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        result = json.loads(cleaned)
        if _is_valid(result):
            return result
    except json.JSONDecodeError:
        pass

    fixed = _fix_common_json_errors(cleaned)
    if fixed != cleaned:
        try:
            result = json.loads(fixed)
            if _is_valid(result):
                return result
        except json.JSONDecodeError:
            pass
        try:
            result, idx = decoder.raw_decode(fixed)
            if _is_valid(result):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    candidates = _extract_json_by_bracket_balance(cleaned)
    if not candidates:
        candidates = _extract_json_by_bracket_balance(fixed)

    if candidates:
        parsed_candidates = []
        for candidate in candidates:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    parsed_candidates.append(obj)
            except json.JSONDecodeError:
                continue
        if required_fields:
            parsed_candidates.sort(
                key=lambda o: sum(1 for f in required_fields if f in o), reverse=True
            )
        for obj in parsed_candidates:
            if _is_valid(obj):
                return obj
        if parsed_candidates:
            return parsed_candidates[0]
    return None


# ========== OpenCode caller ==========

class CodeAnalyseCapability:
    def __init__(self, opencode_cmd: str = "opencode"):
        self.opencode_cmd = opencode_cmd
        self.env_vars = _load_env()

    def execute(
        self, situation: str, failed_log: str, target_repo_path: str
    ) -> Dict[str, Any]:
        if not os.path.isdir(target_repo_path):
            return {
                "status": "failed",
                "error": f"Target repo path does not exist: {target_repo_path}",
                "report": None,
                "raw_output": "",
            }

        prompt = self._build_prompt(situation, failed_log, target_repo_path)
        opencode_result = self._call_opencode(prompt, target_repo_path)

        if opencode_result.get("error"):
            return {
                "status": "failed",
                "error": opencode_result["error"],
                "report": None,
                "raw_output": opencode_result.get("stdout", ""),
            }

        parsed = self._parse_opencode_output(opencode_result.get("stdout", ""))
        return {
            "status": "success" if parsed.get("report") else "partial",
            "report": parsed.get("report"),
            "raw_output": opencode_result.get("stdout", ""),
            "error": parsed.get("error"),
        }

    def _build_prompt(self, situation: str, failed_log: str, target_repo_path: str) -> str:
        truncated_log = failed_log
        if len(failed_log) > 40000:
            truncated_log = failed_log[:3000] + "\n...[middle truncated]...\n" + failed_log[-3000:]
        return (
            f"请使用 code-analyse skill 分析以下测试失败并定位 Bug。\n\n"
            f"目标仓库: {target_repo_path}\n\n"
            f"## 测试失败场景\n{situation}\n\n"
            f"## 测试失败日志\n```\n{truncated_log}\n```\n\n"
            f"## 任务要求\n"
            f"1. 按照 code-analyse skill 的流程执行分析\n"
            f"2. 使用 gitnexus 工具查询代码结构、调用关系\n"
            f"3. 结合错误日志，精确定位 Bug 根因和代码位置\n"
            f"4. 输出严格 JSON 格式，不要 Markdown，不要解释性前后缀\n\n"
            f"## 输出格式（必须严格遵守以下 JSON Schema）\n"
            f"{{\n"
            f'  "error_cause": "错误根因的详细说明",\n'
            f'  "bug_location": {{\n'
            f'    "file": "相对路径/to/file.py",\n'
            f'    "function": "函数名或类.方法",\n'
            f'    "lines": "45-52"\n'
            f'  }},\n'
            f'  "suggested_fix": "修复建议或代码片段",\n'
            f'  "confidence": 0.92,\n'
            f'  "reasoning": "逐步推理：如何定位到这个 Bug"\n'
            f'}}\n\n'
            f"## 重要约束\n"
            f"- 键名必须完全匹配上面的字段名\n"
            f"- bug_location 中的 file 必须是相对路径，function 可以是空字符串\n"
            f"- confidence 范围 0.0~1.0，无法定位时 < 0.5\n"
            f"- 不要输出 Markdown 代码块，只输出纯 JSON\n"
            f"- 不要输出任何解释性文字或思考过程"
        )

    def _call_opencode(self, prompt: str, target_repo_path: str) -> Dict[str, Any]:
        env = os.environ.copy()
        env.update(self.env_vars)
        try:
            proc = subprocess.run(
                [
                    self.opencode_cmd,
                    "run",
                    prompt,
                    "--format", "json",
                    "--dir", target_repo_path,
                    "--dangerously-skip-permissions",
                ],
                capture_output=True,
                text=True,
                timeout=None,
                env=env,
            )
            if proc.returncode != 0:
                return {
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "error": f"Opencode 调用失败 (rc={proc.returncode}): {proc.stderr[:500]}",
                }
            return {"stdout": proc.stdout, "stderr": proc.stderr, "error": None}
        except FileNotFoundError:
            return {
                "stdout": "",
                "stderr": "",
                "error": f"找不到 Opencode 可执行文件: {self.opencode_cmd}",
            }
        except Exception as e:
            return {"stdout": "", "stderr": "", "error": f"Opencode 调用异常: {e}"}

    # ---------- parser ----------

    def _parse_opencode_output(self, output: str) -> Dict[str, Any]:
        if not output or not output.strip():
            return {"report": None, "error": "OpenCode 输出为空"}

        cleaned = _clean_response(output)
        all_dicts = []
        text_event_contents = []

        for line in cleaned.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    all_dicts.append(obj)
                    part = obj.get("part", {})
                    if isinstance(part, dict) and part.get("type") == "text" and "text" in part:
                        text_str = part["text"]
                        if isinstance(text_str, str):
                            text_event_contents.append(text_str)
            except json.JSONDecodeError:
                continue

        # 优先解析 text 事件里的 JSON
        for text_str in text_event_contents:
            try:
                inner = json.loads(text_str.strip())
                if isinstance(inner, dict) and self._is_valid_report(inner):
                    return {"report": inner, "error": None}
            except (json.JSONDecodeError, ValueError):
                pass

            parsed = _parse_json(text_str, required_fields=["error_cause", "bug_location"])
            if parsed is not None:
                return {"report": parsed, "error": None}

            extracted = self._extract_json_from_text(text_str)
            if extracted["report"] is not None:
                return extracted

        # 从所有行内 dict 中匹配
        for d in all_dicts:
            if self._is_valid_report(d):
                return {"report": d, "error": None}

        # Markdown 文本提取兜底
        for text_str in text_event_contents:
            markdown_report = self._extract_from_markdown(text_str)
            if markdown_report:
                return {"report": markdown_report, "error": None}

        # 全局兜底 — 括号平衡法
        for candidate in _extract_json_by_bracket_balance(cleaned):
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict) and self._is_valid_report(obj):
                    return {"report": obj, "error": None}
            except json.JSONDecodeError:
                continue

        return {
            "report": None,
            "error": f"无法从 OpenCode 输出中解析有效报告。Raw:\n{output[:500]}",
        }

    def _is_valid_report(self, data: Dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        core_fields = {"error_cause", "bug_location", "suggested_fix", "confidence", "reasoning"}
        if not any(f in data for f in core_fields):
            return False
        has_content = False
        for v in data.values():
            if v is not None and v != "" and v != {} and v != []:
                has_content = True
                break
        return has_content

    def _extract_json_from_text(self, text: str) -> Dict[str, Any]:
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict) and self._is_valid_report(data):
                return {"report": data, "error": None}
        except (json.JSONDecodeError, ValueError):
            pass

        for candidate in _extract_json_by_bracket_balance(text):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and self._is_valid_report(data):
                    return {"report": data, "error": None}
            except json.JSONDecodeError:
                continue

        return {"report": None, "error": None}

    def _extract_from_markdown(self, text: str) -> Optional[Dict[str, Any]]:
        if not text or "##" not in text:
            return None

        report = {
            "error_cause": "",
            "bug_location": {"file": "", "function": "", "lines": ""},
            "suggested_fix": "",
            "confidence": 0.5,
            "reasoning": "",
        }

        cause_match = re.search(
            r"(?:##?\s*(?:Root\s*)?Cause|根因|错误原因|问题原因)[:：]\s*(.+?)(?:\n##|\n\n|$)",
            text, re.DOTALL | re.IGNORECASE
        )
        if cause_match:
            report["error_cause"] = cause_match.group(1).strip().replace("\n", " ")

        fix_match = re.search(
            r"(?:##?\s*(?:Fixes?\s*Required|修复建议|Suggested\s*Fix))[:：]?\s*(.+?)(?:\n##|\n\n|$)",
            text, re.DOTALL | re.IGNORECASE
        )
        if fix_match:
            report["suggested_fix"] = fix_match.group(1).strip()

        file_match = re.search(
            r"(?:文件|file|File)\s*[:：]\s*`?([^`\n:]+?)`?(?::(\d+(?:-\d+)?))?",
            text, re.IGNORECASE
        )
        if file_match:
            report["bug_location"]["file"] = file_match.group(1).strip()
            if file_match.group(2):
                report["bug_location"]["lines"] = file_match.group(2)

        line_matches = re.findall(r"`([^`]+\.py):(\d+(?:-\d+)?)`", text)
        if line_matches:
            report["bug_location"]["file"] = line_matches[0][0]
            report["bug_location"]["lines"] = line_matches[0][1]

        conf_match = re.search(
            r"(?:confidence|置信度|可信度)[:：]?\s*(\d+(?:\.\d+)?)",
            text, re.IGNORECASE
        )
        if conf_match:
            report["confidence"] = float(conf_match.group(1))

        if not report["error_cause"] and not report["bug_location"]["file"]:
            return None

        report["reasoning"] = text[:500].replace("\n", " ")
        return report


# ========== report helpers ==========

def _build_markdown_report(situation: str, failed_log: str, report: Dict[str, Any]) -> str:
    """构建完整的 Markdown 分析报告。"""
    bug_loc = report.get("bug_location", {})
    return f"""# Code Analysis Report

**Generated at:** {datetime.now().isoformat()}

## Situation
{situation}

## Failed Log
```
{failed_log[:3000]}{"\n... (truncated)" if len(failed_log) > 3000 else ""}
```

## Root Cause
{report.get("error_cause", "N/A")}

## Bug Location
- **File:** `{bug_loc.get("file", "N/A")}`
- **Function:** `{bug_loc.get("function", "N/A")}`
- **Lines:** `{bug_loc.get("lines", "N/A")}`

## Suggested Fix
{report.get("suggested_fix", "N/A")}

## Confidence
{report.get("confidence", "N/A")}

## Reasoning
{report.get("reasoning", "N/A")}
"""


def _save_report(situation: str, failed_log: str, report: Dict[str, Any]) -> Path:
    """保存完整报告到 reports/ 目录，返回报告文件路径。"""
    report_dir = Path(__file__).resolve().parent.parent / "reports"
    report_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"analysis_{timestamp}.md"
    report_path.write_text(_build_markdown_report(situation, failed_log, report), encoding="utf-8")
    return report_path


def _save_raw_report(situation: str, failed_log: str, raw_output: str, error_msg: str = "") -> Path:
    """当解析失败时，将原始输出直接保存为 Markdown 报告。"""
    report_dir = Path(__file__).resolve().parent.parent / "reports"
    report_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"analysis_{timestamp}.md"

    content = f"""# Code Analysis Report (Raw Output)

**Generated at:** {datetime.now().isoformat()}

## Situation
{situation}

## Failed Log
```
{failed_log[:3000]}{"\n... (truncated)" if len(failed_log) > 3000 else ""}
```

## Raw Analysis Output
```
{raw_output[:8000]}{"\n... (truncated)" if len(raw_output) > 8000 else ""}
```
"""
    if error_msg:
        content += f"\n## Parse Error\n{error_msg}\n"

    report_path.write_text(content, encoding="utf-8")
    return report_path


# ========== 便捷入口 ==========

def run(situation: str, failed_log: str, target_repo_path: str = None) -> str:
    """
    调用 code_analyse 能力分析测试失败并定位 Bug。
    完整报告保存到 reports/ 目录，返回紧凑摘要供主 Agent 决策。
    如果 JSON 解析失败，兜底保存原始输出为 .md 文件，确保飞书通知仍能发送。
    """
    env = _load_env()
    repo_path = target_repo_path or env.get("DEBUG_PROJECT_PATH")

    if not repo_path:
        return "[Error] 未提供目标仓库路径，且 .env 中未配置 DEBUG_PROJECT_PATH"

    if not Path(repo_path).exists():
        return f"[Error] 目标仓库路径不存在: {repo_path}"

    capability = CodeAnalyseCapability()
    result = capability.execute(
        situation=situation,
        failed_log=failed_log,
        target_repo_path=repo_path,
    )

    status = result.get("status", "unknown")
    report = result.get("report")
    error = result.get("error")
    raw = result.get("raw_output", "")

    if status == "success" and report:
        report_path = _save_report(situation, failed_log, report)
        bug_loc = report.get("bug_location", {})
        # 紧凑摘要，确保在 300 字符截断限制内保留核心信息
        rel_path = f"reports/{report_path.name}"
        return (
            f"分析完成 | 置信度: {report.get('confidence', 'N/A')} | "
            f"根因: {report.get('error_cause', 'N/A')[:80]}... | "
            f"位置: {bug_loc.get('file', 'N/A')}:{bug_loc.get('lines', 'N/A')} | "
            f"报告路径: {rel_path}"
        )

    # 兜底：解析失败时，保存原始输出为 .md 文件，让飞书通知仍能发送
    report_path = _save_raw_report(situation, failed_log, raw, error_msg=error or "")
    rel_path = f"reports/{report_path.name}"
    return f"分析完成（原始输出） | 报告路径: {rel_path}"
