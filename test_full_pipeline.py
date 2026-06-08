"""
完整链路测试脚本

模拟一次用户查询，让 Agent 真实调用：
1. code_analyse —— 分析测试失败
2. feishu_notify —— 发送飞书通知（使用 .env 中的 receive_id）

运行：python znew/test_full_pipeline.py
"""
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

receive_id = os.environ.get("receive_id")
if not receive_id:
    raise RuntimeError("receive_id not found in .env")
print(f"[Test] 从 .env 读取到 receive_id: {receive_id}")
from znew.agent import agent_loop
messages = [
    {
        "role": "user",
        "content": (
            '测试场景：用户输入"10 / 0"后程序直接崩溃。'
            '失败日志：ZeroDivisionError: float division by zero in term() line 44。'
            "请分析这个测试失败并通知负责人。"
        ),
    }
]
print("[Test] 启动 Agent Loop，开始完整链路测试...\n")
try:
    agent_loop(messages)
except Exception as e:
    print(f"[Test] Agent Loop 异常: {type(e).__name__}: {e}")
    sys.exit(1)

# 打印最终回复
last_content = messages[-1]["content"]
if isinstance(last_content, list):
    for block in last_content:
        if getattr(block, "type", None) == "text":
            print("\n=== Agent 最终回复 ===")
            print(block.text)
else:
    print("\n=== Agent 最终回复 ===")
    print(last_content)

print("\n[Test] 完整链路测试结束")
