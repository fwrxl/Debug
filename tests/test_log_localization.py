"""日志分析能力测试"""
import sys
sys.path.insert(0, '/Users/rxl/Documents/test_failure_notification_agent')

import asyncio
from capabilities.log_localization.locator import LogLocator


async def main():
    input_data = {
        "situation": {
            "description": "用户说往前走但机器人没有反应",
            "target": "端到端测试"
        },
        "failed_log": """
# === 阶段1: 意图分类 ===
[IntentEnsemble] 裁决完成 intent=2 conf=0.42 cost=127ms
[Ensemble] trace rule_fast: intent=2 conf=0.8 cost=1ms reasons=['chat_pattern']
[Ensemble] trace llm_light: intent=1 conf=0.65 cost=120ms reasons=['llm_light']
[Ensemble] trace llm_cmd: intent=1 conf=0.7 cost=115ms reasons=['llm_cmd']
[Ensemble] trace mem_intent: intent=2 conf=0.3 cost=0ms reasons=['mem_default']
[Ensemble] trace safety: intent=2 conf=0.1 cost=0ms reasons=['safe_pass']
⚠️  裁决失败: 意图=2(闲聊) 但 rule_fast+llm_cmd 都命中指令

# === 阶段2: 指令重写 (旁路) ===
[InstructionRewriter] rewrite: "往前走"
[PreProcessor] ES召回: k=5 score_threshold=0.5, 找到 2 个候选
[PreProcessor] 候选: ["往前移动", "往前走一步"]
[LLM] input_tokens=156 output_tokens=89
[LLM] raw_response: {"rewritten_text": ["往前走"], "bot_reply": "好的，我往前走"}
✅ 改写成功: "往前走" → "往前走"

# === 阶段3: ES双搜 ===
[CommandStoreClient] vector_search k=5 score=0.72
[CommandStoreClient] text_search multi_match="往前走"
[CommandStoreClient] merge_results: vector=1 text=1
[CommandStoreClient] matched_command: {
  "id": "cmd_001",
  "command": "往前走",
  "pattern": "往<方向>走",
  "protocol": "move_forward",
  "capture_items": ["方向"]
}
✅ ES搜索成功: 匹配 cmd_001

# === 阶段4: 参数提取 ===
[ParameterExtractor] regex="往<方向>走" no match in "往前走"
[ParameterExtractor] capture_items: ["方向"] but text="往前走" missing "方向" value
⚠️  参数提取失败: 缺少"方向"参数，回退到默认"前"

# === 阶段5: 协议生成 ===
[ProtocolBuilder] template="move_forward" found
[ProtocolBuilder] params={"direction": "前", "distance": 1.0}
[ProtocolBuilder] generated: {"action": "move", "direction": "前", "distance": 1.0, "device_id": "robot_001"}
✅ 协议生成成功

# === 阶段6: MQTT发送 ===
[EMQXClient] publishing to topic: robot/robot_001/control
[EMQXClient] payload: {"action": "move", "direction": "前", "distance": 1.0}
[EMQXClient] wait_for_callback timeout=5000ms
[EMQXClient] ⚠️  未收到设备回调，尝试重试第1次...
[EMQXClient] ⚠️  未收到设备回调，尝试重试第2次...
[EMQXClient] ❌ 重试耗尽，设备无响应
        """,
        "suspicious_module": {
            "module": "intent_classifier",
            "reason": "意图分类将指令误判为闲聊(intent=2)，rule_fast和llm_cmd都识别为指令但被裁决覆盖",
            "confidence": 0.85
        }
    }

    locator = LogLocator()
    result = await locator.execute(
        input_data["situation"],
        input_data["failed_log"],
        None,
        input_data["suspicious_module"]
    )

    print("=" * 60)
    print("日志分析输出:")
    print("=" * 60)
    print(f"failed_module: {result.get('failed_module')}")
    print(f"failed_component: {result.get('failed_component')}")
    print(f"error_location: {result.get('error_location')}")
    print(f"root_cause: {result.get('root_cause')}")
    print(f"confidence: {result.get('confidence')}")


if __name__ == "__main__":
    asyncio.run(main())