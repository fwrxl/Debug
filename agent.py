"""
znew Agent Demo —— CLI + HTTP 共用入口

基于 Anthropic SDK + ReAct 工具调用循环。
集成两个真实能力：
1. code_analyse —— 分析测试失败日志，定位 Bug
2. feishu_notify —— 发送飞书消息通知

CLI 运行：python znew/agent.py
HTTP 导入：from agent import agent_loop
"""
import asyncio
import os
import sys
from pathlib import Path

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

WORKDIR = os.environ.get("DEBUG_PROJECT_PATH","/Users/rxl/Documents/qian/demo1/demo2") 

# 环境变量检查
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL_ID = os.environ.get("MODEL_ID")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("[Fatal] 环境变量 ANTHROPIC_API_KEY 未设置，请在 znew/.env 中配置。")
if not MODEL_ID:
    raise RuntimeError("[Fatal] 环境变量 MODEL_ID 未设置，请在 znew/.env 中配置。")

from anthropic import Anthropic
from tools import TOOLS, TOOL_HANDLERS

client = Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

SYSTEM = (
    f"You are a debug agent at {WORKDIR}. "
    "You have two tools: code_analyse (analyse test failures) and feishu_notify (send Feishu messages). "
    "When the user asks to analyse a failure and notify someone, you MUST: "
    "1) call code_analyse first, 2) then call feishu_notify with the report_path returned by code_analyse. "
    "Use tools to solve tasks. Act, don't explain."
)


def _to_serializable(obj):
    """递归将 Anthropic SDK 的 Pydantic 模型转为可 JSON 序列化的纯 Python 对象。"""
    if hasattr(obj, "model_dump"):
        return _to_serializable(obj.model_dump())
    if isinstance(obj, list):
        return [_to_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    return obj


def agent_loop(messages: list):
    """Agent 核心循环。可被 FastAPI 直接调用。

    Args:
        messages: Anthropic messages 格式的 list，会被就地修改，追加 assistant 回复。
    """
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
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output[:2000] if len(str(output)) > 2000 else output,
                })
        messages.append({"role": "user", "content": results})


async def agent_loop_stream(messages: list):
    """Agent 核心循环的流式版本（异步生成器）。

    每轮对话结束后 yield 当前最新消息，供 SSE 推送到前端。
    """
    while True:
        response = await asyncio.to_thread(
            client.messages.create,
            model=MODEL_ID,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=4096,
        )

        assistant_msg = {"role": "assistant", "content": _to_serializable(response.content)}
        messages.append(assistant_msg)
        yield assistant_msg

        if response.stop_reason != "tool_use":
            yield {"role": "done"}
            return

        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                if handler:
                    try:
                        output = await asyncio.to_thread(handler, **block.input)
                    except Exception as e:
                        output = f"[Error] Tool {block.name} failed: {type(e).__name__}: {e}"
                else:
                    output = f"[Error] No handler for tool {block.name}"
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output[:2000] if len(str(output)) > 2000 else output,
                })

        user_msg = {"role": "user", "content": results}
        messages.append(user_msg)
        yield user_msg


# ========== CLI 入口 ==========

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
