"""调试脚本 - 直接引用 ExecutionModule 的多分支诊断流程

流程:
1. 输入 situation + failed_log
2. ExecutionModule.execute_plan_with_branches 统一处理：
   - situation_analysis 获取候选模块
   - 多分支并行执行（每分支 LLM 决策 + Reflection）
   - 汇总排序
   - Finalization（owner_identification + feishu_notification）
"""
import os
import asyncio
import sys
from pathlib import Path

# 设置环境变量（从 .env 读取，不硬编码）
project_root = Path(__file__).parent
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value

sys.path.insert(0, str(project_root))

from agent.execution.executor import ExecutionModule


async def run_agent_driven_test(input_data: dict):
    """
    运行多分支诊断流程（直接调用 ExecutionModule）

    Args:
        input_data: 输入数据
    """
    print("=" * 60)
    print("多分支诊断流程")
    print("=" * 60)

    situation_str = input_data.get("situation", "")
    failed_log = input_data.get("failed_log", "")

    print(f"\n情景: {situation_str}")
    print(f"失败日志长度: {len(failed_log)}")

    # 创建 ExecutionModule
    executor = ExecutionModule()

    # 执行多分支诊断流程
    result = await executor.execute_plan_with_branches(
        situation=situation_str,
        failed_log=failed_log,
    )
 ###你是干什么的？
    # ========== 输出完整报告 ==========
    print("\n" + "=" * 60)
    print("完整执行报告")
    print("=" * 60)

    print(f"\n【输入】")
    print(f"情景: {situation_str}")
    print(f"候选模块: {result.get('candidate_modules', [])}")

    print(f"\n【分支执行】")
    for br in result.get("branch_results", []):
        print(f"\nBranch {br['branch_id']} ({br['module']}):")
        print(f"  reflection_confidence: {br['reflection_confidence']:.2f}")
        print(f"  reflection_reason: {br['reflection_reason'][:60]}...")
        print(f"  执行了: {[s['capability'] for s in br['step_results']]}")

    print(f"\n【最终决策】")
    print(f"best_module: {result.get('best_module')}")
    print(f"best_confidence: {result.get('best_confidence', 0.0):.2f}")
    print(f"final_action: {'notify' if result.get('notification_sent') else 'no_notify'}")

    print(f"\n【通知结果】")
    print(f"notification_sent: {result.get('notification_sent')}")
    print(f"recipient: {result.get('recipient')}")

    return result, executor.memory


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="多分支诊断流程")
    parser.add_argument(
        "--log-file",
        type=str,
        help="失败日志文件路径"
    )
    args = parser.parse_args()

    # 输入数据
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

    # 如果提供了日志文件，读取内容
    if args.log_file:
        log_path = Path(args.log_file)
        if log_path.exists():
            with open(log_path, "r") as f:
                input_data["failed_log"] = f.read()
            print(f"已从文件读取日志: {args.log_file}")
        else:
            print(f"⚠️  日志文件不存在: {args.log_file}")

    return await run_agent_driven_test(input_data)


if __name__ == "__main__":
    result, memory = asyncio.run(main())

    # ========== 输出记忆内容 ==========
    print("\n" + "=" * 60)
    print("全局记忆内容")
    print("=" * 60)
    print(f"\n全局 iteration attempts:")
    for att in memory.iteration.attempts:
        print(f"  - step: {att.get('step')}, target: {att.get('target_module')}, confidence: {att.get('confidence')}")

    print(f"\npossible_modules:")
    for pm in memory.possible_modules:
        print(f"  - module: {pm.module}, confidence: {pm.confidence}")

    print(f"\n全局 context conversation:")
    for conv in memory.context.conversation:
        print(f"  - step: {conv.get('step')}, role: {conv.get('role')}")

    print(f"\nbranch_memories:")
    for module_name, branch_mem in memory.branch_memories.items():
        print(f"\n  [{module_name}]:")
        print(f"    context conversation:")
        for conv in branch_mem["context"].conversation:
            print(f"      - step: {conv.get('step')}, role: {conv.get('role')}")
        print(f"    iteration attempts:")
        for att in branch_mem["iteration"].attempts:
            print(f"      - step: {att.get('step')}, target: {att.get('target_module')}, confidence: {att.get('confidence')}")

    print("\n" + "=" * 60)
    print(f"最终结果: success={result.get('success')}")
    print("=" * 60)

    sys.exit(0 if result.get("success") else 1)