# znew Agent Demo 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 Anthropic SDK + ReAct 工具调用循环，实现 CLI 交互式 Agent Demo，集成 code_analyse 和 feishu_notify 两个真实能力。

**Architecture:** agent.py 作为 LLM 循环和工具分发的中枢；tools/ 下的两个模块分别封装项目已有的 `capabilities/code_analyse/analyzer.py` 和 `integrations/feishu_client.py`，通过 sys.path 注入实现跨包 import。LLM 自主决策调用顺序。

**Tech Stack:** Python 3.10+, anthropic SDK, python-dotenv, requests

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `znew/.env` | 独立环境变量配置 |
| `znew/agent.py` | Anthropic 客户端、ReAct 循环、CLI 入口 |
| `znew/tools/__init__.py` | tools 包入口，导出 tool schema 和 handlers |
| `znew/tools/code_analyse.py` | 封装 `analyzer.execute()`，转换为同步函数 |
| `znew/tools/feishu_notify.py` | 封装 `send_text_message()`，转换为同步函数 |

---

### Task 1: 创建 .env 配置文件

**Files:**
- Create: `znew/.env`

- [ ] **Step 1: 创建 .env 文件**

写入以下内容（用户需要自行替换为真实值）：

```bash
# Anthropic / OpenAI 兼容配置
ANTHROPIC_API_KEY=sk-your-key-here
ANTHROPIC_BASE_URL=https://api.minimaxi.com/v1
MODEL_ID=MiniMax-M2.7

# 飞书配置
FEISHU_APP_ID=cli_a976e6631eb55bc0
FEISHU_APP_SECRET=OwI3cVGw7QObtwDhHL0sEtqPVVKWGxJn
FEISHU_OPEN_BASE_URL=https://open.feishu.cn
receive_id=ou_da6f41f726b64bd84672ca958390b282

# 代码分析目标仓库路径
DEBUG_PROJECT_PATH=/Users/rxl/Documents/demo1/demo2
```

---

### Task 2: 实现 code_analyse 工具封装

**Files:**
- Create: `znew/tools/code_analyse.py`

- [ ] **Step 1: 编写 tools/code_analyse.py**

```python
"""封装 capabilities/code_analyse/analyzer.py 为同步工具函数"""
import os
from pathlib import Path


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


def run(situation: str, failed_log: str, target_repo_path: str = None) -> str:
    """
    调用 code_analyse 能力分析测试失败并定位 Bug。

    Args:
        situation: 测试场景描述
        failed_log: 测试失败日志
        target_repo_path: 目标仓库路径，默认从 .env 读取 DEBUG_PROJECT_PATH

    Returns:
        格式化字符串：包含分析结果或错误信息
    """
    env = _load_env()
    repo_path = target_repo_path or env.get("DEBUG_PROJECT_PATH")

    if not repo_path:
        return "[Error] 未提供目标仓库路径，且 .env 中未配置 DEBUG_PROJECT_PATH"

    if not Path(repo_path).exists():
        return f"[Error] 目标仓库路径不存在: {repo_path}"

    # 延迟 import，避免 sys.path 未设置时失败
    from capabilities.code_analyse.analyzer import execute

    result = execute(
        situation=situation,
        failed_log=failed_log,
        target_repo_path=repo_path,
    )

    status = result.get("status", "unknown")
    report = result.get("report")
    error = result.get("error")
    raw = result.get("raw_output", "")

    if status == "success" and report:
        return (
            f"分析完成 (confidence={report.get('confidence', 'N/A')})\n"
            f"根因: {report.get('error_cause', 'N/A')}\n"
            f"位置: {report.get('bug_location', {})}\n"
            f"修复建议: {report.get('suggested_fix', 'N/A')}\n"
            f"推理过程: {report.get('reasoning', 'N/A')}\n"
        )
    elif status == "partial":
        return (
            f"[Partial] 分析部分成功，可能未完全解析。\n"
            f"Report: {report}\n"
            f"Error: {error}\n"
            f"Raw (前 500 字): {raw[:500]}"
        )
    else:
        return (
            f"[Failed] 分析失败。\n"
            f"Error: {error}\n"
            f"Raw (前 500 字): {raw[:500]}"
        )
```

---

### Task 3: 实现 feishu_notify 工具封装

**Files:**
- Create: `znew/tools/feishu_notify.py`

- [ ] **Step 1: 编写 tools/feishu_notify.py**

```python
"""封装 integrations/feishu_client.py 为同步工具函数"""
import os
from pathlib import Path


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


def run(text: str, receive_id: str = None) -> str:
    """
    调用飞书能力发送文本消息通知。

    Args:
        text: 消息内容
        receive_id: 接收者 open_id，默认从 .env 读取 receive_id

    Returns:
        格式化字符串：发送结果或错误信息
    """
    env = _load_env()
    rid = receive_id or env.get("receive_id")

    if not rid:
        return "[Error] 未提供 receive_id，且 .env 中未配置 receive_id"

    # 延迟 import，避免 sys.path 未设置时失败
    from integrations.feishu_client import send_text_message

    result = send_text_message(
        receive_id=rid,
        text=text,
        receive_id_type="open_id",
    )

    if result.get("success"):
        return (
            f"飞书消息发送成功。\n"
            f"message_id: {result.get('data', {}).get('message_id', 'N/A')}"
        )
    else:
        return (
            f"[Error] 飞书消息发送失败。\n"
            f"code: {result.get('code')}\n"
            f"msg: {result.get('msg')}"
        )
```

---

### Task 4: 创建 tools 包入口

**Files:**
- Create: `znew/tools/__init__.py`

- [ ] **Step 1: 编写 tools/__init__.py**

```python
"""znew Agent 工具包

导出 tool schemas 和 handlers，供 agent.py 使用。
"""
from . import code_analyse, feishu_notify

# Tool schema 定义（Anthropic SDK 格式）
TOOLS = [
    {
        "name": "code_analyse",
        "description": (
            "分析测试失败日志，定位代码库中的 Bug。"
            "输入：测试场景描述 (situation) 和失败日志 (failed_log)。"
            "输出：错误根因、Bug 位置、修复建议、置信度。"
            "如果未提供 target_repo_path，将自动使用 .env 中配置的 DEBUG_PROJECT_PATH。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "situation": {
                    "type": "string",
                    "description": "测试场景描述，例如：用户说'往前走'但机器人没有移动",
                },
                "failed_log": {
                    "type": "string",
                    "description": "测试失败日志的完整内容",
                },
                "target_repo_path": {
                    "type": "string",
                    "description": "可选。目标代码仓库的绝对路径，默认从 .env 读取",
                },
            },
            "required": ["situation", "failed_log"],
        },
    },
    {
        "name": "feishu_notify",
        "description": (
            "发送飞书文本消息通知给指定接收人。"
            "输入：消息内容 (text)。"
            "输出：发送结果（成功/失败）。"
            "如果未提供 receive_id，将自动使用 .env 中配置的 receive_id。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要发送的飞书消息文本内容",
                },
                "receive_id": {
                    "type": "string",
                    "description": "可选。接收者的飞书 open_id，默认从 .env 读取",
                },
            },
            "required": ["text"],
        },
    },
]

# Tool handler 映射
TOOL_HANDLERS = {
    "code_analyse": code_analyse.run,
    "feishu_notify": feishu_notify.run,
}
```

---

### Task 5: 实现 agent.py（LLM 循环 + CLI 入口）

**Files:**
- Create: `znew/agent.py`

- [ ] **Step 1: 编写 znew/agent.py**

```python
"""
znew Agent Demo

基于 Anthropic SDK + ReAct 工具调用循环。
集成两个真实能力：
1. code_analyse —— 分析测试失败日志，定位 Bug
2. feishu_notify —— 发送飞书消息通知

运行：python znew/agent.py
"""
import os
import sys
from pathlib import Path

# 将仓库根目录加入 sys.path，以便 import capabilities / integrations
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from dotenv import load_dotenv

# 加载 znew/.env
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()

# 环境变量检查
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL_ID = os.environ.get("MODEL_ID")
if not ANTHROPIC_API_KEY:
    print("[Fatal] 环境变量 ANTHROPIC_API_KEY 未设置，请在 znew/.env 中配置。")
    sys.exit(1)
if not MODEL_ID:
    print("[Fatal] 环境变量 MODEL_ID 未设置，请在 znew/.env 中配置。")
    sys.exit(1)

from anthropic import Anthropic
from tools import TOOLS, TOOL_HANDLERS

client = Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "You have two tools: code_analyse (analyse test failures) and feishu_notify (send Feishu messages). "
    "Use tools to solve tasks. Act, don't explain."
)


def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL_ID,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=4096,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                if handler:
                    try:
                        output = handler(**block.input)
                    except Exception as e:
                        output = f"[Error] Tool {block.name} failed: {type(e).__name__}: {e}"
                else:
                    output = f"[Error] No handler for tool {block.name}"
                # 截断过长输出，避免 token 爆炸
                print(str(output)[:300])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("znew Agent Demo")
    print("输入问题，回车发送。输入 q 退出。\n")
    history = []
    while True:
        try:
            query = input("\033[36mznew >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
```

---

### Task 6: 运行验证

**Files:**
- Test: 手动 CLI 验证

- [ ] **Step 1: 检查环境变量**

Run: `cat znew/.env | grep -E "ANTHROPIC|MODEL_ID|receive_id"`
Expected: 三行均非空

- [ ] **Step 2: 启动 Agent**

Run: `cd /Users/rxl/Documents/test_failure_notification_agent_final_ && python znew/agent.py`
Expected: 输出 `znew Agent Demo` 和提示符 `znew >>`

- [ ] **Step 3: 输入一个完整分析请求**

输入示例：
```
测试场景：用户说"往前走"但机器人没有移动。失败日志：regex='往<方向>走' no match in '往前走'
请分析这个测试失败并通知负责人
```

Expected:
1. Agent 调用 `code_analyse`，输出分析结果（含 confidence / bug_location）
2. Agent 调用 `feishu_notify`，输出 `飞书消息发送成功`
3. Agent 汇总回复

- [ ] **Step 4: 确认飞书消息真实送达**

检查 receive_id 对应的飞书账号是否收到消息。

---

## Self-Review

| Spec 要求 | 对应 Task |
|-----------|-----------|
| znew 独立 .env | Task 1 |
| agent.py: Anthropic SDK + ReAct 循环 + CLI | Task 5 |
| tools/code_analyse.py: 真实调用 analyzer.execute() | Task 2 |
| tools/feishu_notify.py: 真实调用 send_text_message() | Task 3 |
| sys.path 注入，能 import capabilities/integrations | Task 5 Step 1 |
| LLM 自主决策调用顺序 | Task 5 SYSTEM prompt + tool schema |
| 错误处理（环境缺失、调用失败） | Task 2, 3, 5 |
| CLI 交互式运行 | Task 5 `__main__` |

**Placeholder scan:** 无 TBD、无 TODO、所有代码完整展示。

**Type consistency:**
- `code_analyse.run()` 签名: `(situation: str, failed_log: str, target_repo_path: str = None) -> str`
- `feishu_notify.run()` 签名: `(text: str, receive_id: str = None) -> str`
- `TOOL_HANDLERS` 映射与 schema 中的 `"name"` 完全一致

---

**Plan complete and saved to `znew/plan.md`. Two execution options:**

1. **Subagent-Driven (recommended)** - 我逐 task 调度子代理执行，每步 review
2. **Inline Execution** - 在当前会话里直接实现，快速推进

**Which approach?**
