"""代码定位能力真实 Opencode 测试

使用真实数据调用 Opencode Agent（已配置 gitnexus MCP 工具），
测试对 intent_classifier 模块的代码定位能力。

用法:
    DEBUG_PROJECT_PATH=/Users/rxl/Documents/demo1/super_agent \
    python tests/test_code_localization_real.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_env_path)

# 如果没有在 .env 中设置，则使用命令行传入的环境变量
DEBUG_PROJECT_PATH = os.environ.get("DEBUG_PROJECT_PATH", "/Users/rxl/Documents/demo1/super_agent")

from capabilities.code_localization.locator import CodeLocator


async def main():
    input_data = {
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
    }

    module_name = "intent_classifier"

    print("=" * 70)
    print("真实 Opencode 代码定位测试")
    print("=" * 70)
    print(f"模块: {module_name}")
    print(f"项目路径: {DEBUG_PROJECT_PATH}")
    print(f"情景: {input_data['situation']}")
    print()

    locator = CodeLocator()

    start = time.time()
    result = await locator.execute(
        situation=input_data["situation"],
        failed_log=input_data["failed_log"],
        memory=None,
        module_name=module_name,
        debug_project_path=DEBUG_PROJECT_PATH,
    )
    elapsed = time.time() - start

    print(f"耗时: {elapsed:.1f}s")
    print()
    print("=" * 70)
    print("结果:")
    print("=" * 70)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()

    # 格式验证
    print("=" * 70)
    print("格式验证")
    print("=" * 70)
    required_keys = {"module", "confidence", "evidence", "explanation"}
    evidence_keys = {"file_path", "line_numbers", "code_snippets"}
    has_all = required_keys.issubset(result.keys())
    evidence_ok = isinstance(result.get("evidence"), dict) and evidence_keys.issubset(
        result.get("evidence", {}).keys()
    )
    confidence_ok = isinstance(result.get("confidence"), (int, float)) and 0.0 <= result.get("confidence", -1) <= 1.0

    print(f"  包含全部字段: {has_all}")
    print(f"  evidence 结构正确: {evidence_ok}")
    print(f"  confidence 范围合法: {confidence_ok}")

    if has_all and evidence_ok and confidence_ok:
        print("\n✅ 测试通过")
        return 0
    else:
        print("\n❌ 测试失败")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
