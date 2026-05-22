"""代码定位能力单元测试 (TDD)

测试策略：
- 使用 mock 模拟 subprocess.run，避免实际调用 Opencode（慢且依赖环境）。
- 先写测试，再让 locator 实现通过全部断言。
"""
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from capabilities.code_localization.locator import CodeLocator


# ---------- 测试夹具 ----------

@pytest.fixture
def locator():
    return CodeLocator()


@pytest.fixture
def sample_input():
    return {
        "situation": "用户说往前走但机器人没有反应",
        "failed_log": """
# === 阶段1: 意图分类 ===
[IntentEnsemble] 裁决完成 intent=2 conf=0.42 cost=127ms
[Ensemble] trace rule_fast: intent=2 conf=0.8 cost=1ms reasons=['chat_pattern']
[Ensemble] trace llm_light: intent=1 conf=0.65 cost=120ms reasons=['llm_light']
[Ensemble] trace llm_cmd: intent=1 conf=0.7 cost=115ms reasons=['llm_cmd']
⚠️  裁决失败: 意图=2(闲聊) 但 rule_fast+llm_cmd 都命中指令

# === 阶段2: 指令重写 (旁路) ===
[InstructionRewriter] rewrite: "往前走"
✅ 改写成功: "往前走" → "往前走"

# === 阶段3: ES双搜 ===
[CommandStoreClient] vector_search k=5 score=0.72
✅ ES搜索成功: 匹配 cmd_001

# === 阶段4: 参数提取 ===
[ParameterExtractor] regex="往<方向>走" no match in "往前走"
⚠️  参数提取失败: 缺少"方向"参数，回退到默认"前"

# === 阶段5: 协议生成 ===
[ProtocolBuilder] template="move_forward" found
✅ 协议生成成功

# === 阶段6: MQTT发送 ===
[EMQXClient] publishing to topic: robot/robot_001/control
[EMQXClient] wait_for_callback timeout=5000ms
[EMQXClient] ❌ 重试耗尽，设备无响应
        """,
        "module_name": "intent_classifier",
        "debug_project_path": "/Users/rxl/Documents/demo1/super_agent",
    }


@pytest.fixture
def valid_opencode_output():
    """Opencode 正常返回的 JSON（多行格式）"""
    return json.dumps({
        "module": "intent_classifier",
        "confidence": 0.82,
        "explanation": "rule_fast 的 early return 导致 llm_cmd 的正确识别被跳过",
        "evidence": [
            {
                "file_path": "super_agent/intent/ensemble.py",
                "line_numbers": [152, 406, 362],
                "code_snippets": [
                    "if chat_pattern_hit: return self._to_intent_result(rule_hit, [rule_hit])",
                    "rule_fast 命中时直接 return，跳过所有 LLM 分类器",
                ],
            }
        ],
    })


# ---------- 正常路径测试 ----------

@pytest.mark.asyncio
async def test_code_locator_returns_correct_format(locator, sample_input, valid_opencode_output):
    """F1: Opencode 返回正确 JSON 时，CodeLocator 应返回规范格式的结果"""
    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=valid_opencode_output,
            stderr="",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    # 必须包含 4 个顶级字段
    assert "module" in result
    assert "confidence" in result
    assert "evidence" in result
    assert "explanation" in result

    # evidence 必须是数组
    evidence = result["evidence"]
    assert isinstance(evidence, list)
    assert len(evidence) > 0
    first_evidence = evidence[0]
    assert "file_path" in first_evidence
    assert "line_numbers" in first_evidence
    assert "code_snippets" in first_evidence

    # 值类型检查
    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(first_evidence["line_numbers"], list)
    assert isinstance(first_evidence["code_snippets"], list)


@pytest.mark.asyncio
async def test_code_locator_propagates_module_name_and_confidence(locator, sample_input, valid_opencode_output):
    """F2: 结果中的 module 和 confidence 应与 Opencode 输出一致"""
    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=valid_opencode_output,
            stderr="",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["module"] == "intent_classifier"
    assert result["confidence"] == pytest.approx(0.82)
    assert "rule_fast" in result["explanation"]


# ---------- 输入校验测试 ----------

@pytest.mark.asyncio
async def test_missing_debug_project_path_returns_error(locator, sample_input):
    """F3: 未提供 DEBUG_PROJECT_PATH 时应返回错误结果"""
    # 清除环境变量
    with patch.dict(os.environ, {}, clear=True):
        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
        )

    assert result["confidence"] == 0.0
    assert "DEBUG_PROJECT_PATH" in result["explanation"]


@pytest.mark.asyncio
async def test_missing_module_name_returns_error(locator, sample_input):
    """F4: 未提供 module_name 时应返回错误结果"""
    result = await locator.execute(
        situation=sample_input["situation"],
        failed_log=sample_input["failed_log"],
        memory=None,
        module_name=None,
        debug_project_path=sample_input["debug_project_path"],
    )

    assert result["confidence"] == 0.0
    assert "module_name" in result["explanation"]


# ---------- Opencode 异常路径测试 ----------

@pytest.mark.asyncio
async def test_opencode_not_found_returns_error(locator, sample_input):
    """F5: Opencode 命令不存在时应返回 FileNotFoundError 错误"""
    with patch("capabilities.code_localization.locator.subprocess.run", side_effect=FileNotFoundError("No such file")):
        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["confidence"] == 0.0
    assert "Opencode" in result["explanation"] or "找不到" in result["explanation"]


@pytest.mark.asyncio
async def test_opencode_nonzero_exit_returns_error(locator, sample_input):
    """F6: Opencode 返回非零退出码时应返回错误结果"""
    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="some error occurred",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["confidence"] == 0.0
    assert "Opencode 调用失败" in result["explanation"]


@pytest.mark.asyncio
async def test_opencode_timeout_returns_error(locator, sample_input):
    """F7: Opencode 超时时应返回超时错误"""
    with patch("capabilities.code_localization.locator.subprocess.run", side_effect=subprocess.TimeoutExpired("opencode", 300)):
        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["confidence"] == 0.0
    assert "超时" in result["explanation"]


@pytest.mark.asyncio
async def test_opencode_unparseable_output_returns_error(locator, sample_input):
    """F8: Opencode 输出无法解析时应返回解析错误"""
    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="this is not json at all",
            stderr="",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["confidence"] == 0.0
    assert "解析" in result["explanation"] or "JSON" in result["explanation"]


# ---------- SSE / 括号平衡解析测试 ----------

@pytest.mark.asyncio
async def test_sse_format_parsing(locator, sample_input):
    """F9: Opencode 以 SSE data: 格式输出时应能正确解析"""
    sse_output = (
        'data: {"type":"start"}\n'
        'data: {"module":"intent_classifier","confidence":0.75,"evidence":{"file_path":"a.py","line_numbers":[1],"code_snippets":["x=1"]},"explanation":"ok"}\n'
        'data: {"type":"end"}\n'
    )

    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=sse_output,
            stderr="",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["module"] == "intent_classifier"
    assert result["confidence"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_bracket_balance_fallback_parsing(locator, sample_input):
    """F10: 当行解析失败时，应使用括号平衡法从整块输出中提取 JSON"""
    mixed_output = (
        "Some random text before\n"
        '{"module":"intent_classifier","confidence":0.9,"evidence":{"file_path":"b.py","line_numbers":[2],"code_snippets":["y=2"]},"explanation":"found it"}\n'
        "Some random text after\n"
    )

    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=mixed_output,
            stderr="",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["module"] == "intent_classifier"
    assert result["confidence"] == pytest.approx(0.9)


# ---------- Opencode 事件流解析测试 ----------

@pytest.mark.asyncio
async def test_opencode_event_stream_parsing(locator, sample_input):
    """F11: Opencode --format json 输出事件流时，应从 type=text 事件的 part.text 中提取答案"""
    # 模拟 Opencode 事件流输出（真实格式）
    event_stream = (
        '{"type":"step_start","timestamp":1,"sessionID":"ses_1","part":{"type":"step-start"}}\n'
        '{"type":"tool_use","timestamp":2,"sessionID":"ses_1","part":{"type":"tool","tool":"read","state":{"status":"completed"}}}\n'
        '{"type":"text","timestamp":3,"sessionID":"ses_1","part":{"type":"text","text":"{\\n  \\"module\\": \\"intent_classifier\\",\\n  \\"confidence\\": 0.85,\\n  \\"evidence\\": {\\n    \\"file_path\\": \\"ensemble.py\\",\\n    \\"line_numbers\\": [163],\\n    \\"code_snippets\\": [\\"x=1\\"]\\n  },\\n  \\"explanation\\": \\"found in event stream\\"\\n}"}}\n'
        '{"type":"step_finish","timestamp":4,"sessionID":"ses_1","part":{"type":"step-finish","reason":"stop"}}\n'
    )

    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=event_stream,
            stderr="",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["module"] == "intent_classifier"
    assert result["confidence"] == pytest.approx(0.85)
    assert result["evidence"][0]["file_path"] == "ensemble.py"
    assert "found in event stream" in result["explanation"]


# ---------- 宽容解析测试 ----------

@pytest.mark.asyncio
async def test_markdown_code_block_parsing(locator, sample_input):
    """F11: Opencode 输出被 Markdown code fence 包裹时应能解析"""
    fenced_output = (
        '```json\n'
        '{"module":"intent_classifier","confidence":0.88,"explanation":"md block","evidence":[{"file_path":"c.py","line_numbers":[3],"code_snippets":["z=3"]}]}\n'
        '```\n'
    )

    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=fenced_output,
            stderr="",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["module"] == "intent_classifier"
    assert result["confidence"] == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_field_alias_mapping(locator, sample_input):
    """F12: 当 Opencode 使用 suspect_module 等别名时应能映射到标准字段"""
    alias_output = json.dumps({
        "suspect_module": "intent_classifier",
        "confidence": 0.77,
        "evidence": {"file_path": "d.py", "line_numbers": [4], "code_snippets": ["w=4"]},
        "summary": "mapped from summary",
    })

    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=alias_output,
            stderr="",
        )

        result = await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

    assert result["module"] == "intent_classifier"
    assert result["confidence"] == pytest.approx(0.77)
    assert "mapped from summary" in result["explanation"]


# ---------- Prompt 构建测试 ----------

@pytest.mark.asyncio
async def test_prompt_contains_module_constraint(locator, sample_input):
    """F13: 构建的 prompt 必须包含'只搜索当前模块'约束和 JSON Schema"""
    with patch("capabilities.code_localization.locator.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({
                "module": "intent_classifier",
                "confidence": 0.5,
                "evidence": {"file_path": "", "line_numbers": [], "code_snippets": []},
                "explanation": "test",
            }),
            stderr="",
        )

        await locator.execute(
            situation=sample_input["situation"],
            failed_log=sample_input["failed_log"],
            memory=None,
            module_name=sample_input["module_name"],
            debug_project_path=sample_input["debug_project_path"],
        )

        # 获取实际传入的 prompt
        call_args = mock_run.call_args[0][0]
        prompt = call_args[2]  # "run" 后面的参数是 prompt

        assert "只搜索和分析 'intent_classifier' 模块的代码" in prompt
        assert "不要搜索其他模块的代码" in prompt
        assert "JSON Schema" in prompt
        assert "键名必须完全匹配上面的字段名" in prompt
        assert sample_input["situation"] in prompt
        assert "[IntentEnsemble] 裁决完成" in prompt
