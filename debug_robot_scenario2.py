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
import json
from pathlib import Path
from datetime import datetime

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
    """
    print("=" * 60)
    print("多分支诊断流程")
    print("=" * 60)

    situation_str = input_data.get("situation", "")
    failed_log = input_data.get("failed_log", "")

    print(f"\n情景: {situation_str}")
    print(f"失败日志长度: {len(failed_log)}")

    executor = ExecutionModule()
    result = await executor.execute_plan_with_branches(
        situation=situation_str,
        failed_log=failed_log,
    )

    return result, executor.memory


# ========== 格式化工具函数 ==========

def _indent(text: str, prefix: str = "  ") -> str:
    """为多行文本添加缩进."""
    lines = text.splitlines()
    return "\n".join(prefix + line for line in lines)


def _fmt_dict(data: dict, indent: int = 0) -> str:
    """将字典格式化为易读的多行文本，字符串中的 \\n 会真正换行."""
    spaces = "  " * indent
    lines = []
    for k, v in data.items():
        if isinstance(v, str) and "\n" in v:
            lines.append(f"{spaces}{k}:")
            lines.append(_indent(v, spaces + "  "))
        elif isinstance(v, dict):
            lines.append(f"{spaces}{k}:")
            lines.append(_fmt_dict(v, indent + 1))
        elif isinstance(v, list):
            lines.append(f"{spaces}{k}:")
            for item in v:
                if isinstance(item, dict):
                    lines.append(f"{spaces}  -")
                    lines.append(_fmt_dict(item, indent + 2))
                else:
                    lines.append(f"{spaces}  - {item}")
        else:
            lines.append(f"{spaces}{k}: {v}")
    return "\n".join(lines)


def _fmt_conversation(entry: dict, indent: int = 0) -> str:
    """格式化单条 conversation 记录."""
    spaces = "  " * indent
    step = entry.get("step", "unknown")
    role = entry.get("role", "unknown")
    ts = entry.get("timestamp", "")
    content = entry.get("content", "")
    lines = [f"{spaces}[{step}] {role}  {ts}"]
    if content:
        lines.append(_indent(content, spaces + "  "))
    return "\n".join(lines)


def _fmt_attempt(att: dict, indent: int = 0) -> str:
    """格式化单条 attempt 记录."""
    spaces = "  " * indent
    step = att.get("step", "unknown")
    success = att.get("success", False)
    target = att.get("target_module", "N/A")
    conf = att.get("confidence", 0.0)
    ts = att.get("timestamp", "")
    evidence = att.get("evidence", {})
    status = "✅" if success else "❌"
    lines = [
        f"{spaces}{status} step={step} target={target} confidence={conf}  {ts}",
    ]
    if evidence:
        lines.append(_fmt_dict(evidence, indent + 1))
    return "\n".join(lines)


# ========== 输出核心函数 ==========

def print_memory(memory, result=None):
    """在终端打印完整的记忆内容."""
    print("\n" + "=" * 60)
    print("完整记忆内容")
    print("=" * 60)

    # --- 全局 iteration ---
    print("\n## 全局 iteration attempts")
    for att in memory.iteration.attempts:
        print(_fmt_attempt(att))
        print()

    # --- possible_modules ---
    print("\n## possible_modules")
    for pm in memory.possible_modules:
        print(f"  - module: {pm.module}, confidence: {pm.confidence:.2f}, explanation: {pm.explanation}")

    # --- 全局 context ---
    print("\n## 全局 context conversation")
    for conv in memory.context.conversation:
        print(_fmt_conversation(conv))
        print()

    # --- branch_memories ---
    print("\n## branch_memories")
    for module_name, branch_mem in memory.branch_memories.items():
        print(f"\n### [{module_name}]")
        print("\n#### context conversation")
        for conv in branch_mem["context"].conversation:
            print(_fmt_conversation(conv, indent=1))
            print()
        print("\n#### iteration attempts")
        for att in branch_mem["iteration"].attempts:
            print(_fmt_attempt(att, indent=1))
            print()

    # --- 最终结果 ---
    if result:
        print("\n" + "=" * 60)
        print(f"最终结果: success={result.get('success')}")
        print("=" * 60)


def _memory_to_dict(memory, result=None) -> dict:
    """将 MemoryModule 序列化为完整 JSON 字典."""
    data = {
        "meta": {
            "exported_at": datetime.now().isoformat(),
            "created_at": getattr(memory, "created_at", ""),
        },
        "global_iteration": [],
        "possible_modules": [],
        "global_context": [],
        "branch_memories": {},
    }

    # 全局 iteration attempts
    if hasattr(memory, "iteration") and hasattr(memory.iteration, "attempts"):
        data["global_iteration"] = list(memory.iteration.attempts)

    # possible_modules
    if hasattr(memory, "possible_modules"):
        data["possible_modules"] = [
            {"module": pm.module, "confidence": pm.confidence, "explanation": pm.explanation}
            for pm in memory.possible_modules
        ]

    # 全局 context
    if hasattr(memory, "context") and hasattr(memory.context, "conversation"):
        data["global_context"] = list(memory.context.conversation)

    # branch_memories
    if hasattr(memory, "branch_memories"):
        for module_name, branch_mem in memory.branch_memories.items():
            branch_data = {}
            if "context" in branch_mem and hasattr(branch_mem["context"], "conversation"):
                branch_data["context"] = list(branch_mem["context"].conversation)
            if "iteration" in branch_mem and hasattr(branch_mem["iteration"], "attempts"):
                branch_data["iteration"] = list(branch_mem["iteration"].attempts)
            data["branch_memories"][module_name] = branch_data

    # 附加字段
    if hasattr(memory, "_bug_module"):
        data["bug_module"] = memory._bug_module
    if hasattr(memory, "_owner_open_id"):
        data["owner_open_id"] = memory._owner_open_id

    return data


def _format_value(obj, indent=0):
    """类 JSON 格式化，字符串中的 \\n 显示为真实换行."""
    spaces = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = []
        for k, v in obj.items():
            formatted_v = _format_value(v, indent + 1)
            items.append(f'{spaces}  "{k}": {formatted_v}')
        return "{\n" + ",\n".join(items) + f"\n{spaces}}}"
    elif isinstance(obj, list):
        if not obj:
            return "[]"
        items = []
        for item in obj:
            formatted_item = _format_value(item, indent + 1)
            items.append(f"{spaces}  {formatted_item}")
        return "[\n" + ",\n".join(items) + f"\n{spaces}]"
    elif isinstance(obj, str):
        if "\n" in obj or '"' in obj:
            escaped = obj.replace('"""', '""\"')
            return f'"""{escaped}"""'
        return json.dumps(obj, ensure_ascii=False)
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif obj is None:
        return "null"
    else:
        return str(obj)


def save_memory_to_md(memory, result=None, filename="123.md"):
    """将完整记忆保存为类 JSON 文件，value 中的 \\n 显示为真实换行."""
    data = _memory_to_dict(memory, result)
    content = _format_value(data)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n结果已保存到: {filename}")


# ========== main ==========

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="多分支诊断流程")
    parser.add_argument("--log-file", type=str, help="失败日志文件路径")
    args = parser.parse_args()

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
    try:
        result, memory = asyncio.run(main())
        # print_memory(memory, result)  # 详细内容已保存到文件，终端仅输出进度
        save_memory_to_md(memory, result)
        print(f"\n结果已保存到文件，success={result.get('success')}")
        sys.exit(0 if result.get("success") else 1)
    except Exception as e:
        print(f"\n执行失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
