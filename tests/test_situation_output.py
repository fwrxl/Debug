"""简单测试情景分析输出"""
import sys
sys.path.insert(0, '/Users/rxl/Documents/test_failure_notification_agent')

import asyncio
from capabilities.situation_analysis.analyzer import SituationAnalyzer


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

# === 阶段2: 指令重写 ===
✅ 改写成功: "往前走" → "往前走"

# === 阶段3: ES双搜 ===
✅ ES搜索成功: 匹配 cmd_001

# === 阶段4: 参数提取 ===
⚠️  参数提取失败: 缺少"方向"参数，回退到默认"前"

# === 阶段5: MQTT发送 ===
[EMQXClient] ❌ 重试耗尽，设备无响应
        """
    }

    analyzer = SituationAnalyzer()
    result = await analyzer.execute(
        input_data["situation"],
        input_data["failed_log"],
        None
    )

    print("=" * 60)
    print("情景分析输出:")
    print("=" * 60)
    print(f"confidence: {result.get('confidence')}")
    print(f"reasoning: {result.get('reasoning')}")
    print(f"\npossible_modules ({len(result.get('possible_modules', []))} 个):")
    for i, m in enumerate(result.get('possible_modules', []), 1):
        print(f"  [{i}] {m.get('module')} (confidence={m.get('confidence')})")
        print(f"      reason: {m.get('reason')}")


if __name__ == "__main__":
    asyncio.run(main())