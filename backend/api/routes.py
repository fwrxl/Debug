from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pathlib import Path
import json

from agent import agent_loop, agent_loop_stream

router = APIRouter()


class AnalyzeRequest(BaseModel):
    situation: str
    failed_log: str


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    """接收结构化参数，拼接成 Prompt 传给 agent_loop，让 LLM 自主调用工具链。（同步版本）"""
    prompt = (
        f"请分析以下测试失败并通知负责人。\n\n"
        f"【测试情景】\n{req.situation}\n\n"
        f"【失败日志】\n```\n{req.failed_log}\n```\n\n"
        f"请调用 code_analyse 工具进行分析，然后调用 feishu_notify 发送报告。"
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        agent_loop(messages)
    except Exception as e:
        messages.append({"role": "assistant", "content": f"[Error] Agent loop failed: {type(e).__name__}: {e}"})
    return {"messages": messages}


@router.post("/analyze/stream")
async def analyze_stream(req: AnalyzeRequest):
    """接收结构化参数，流式返回 Agent 每轮对话结果（SSE）。"""
    prompt = (
        f"请分析以下测试失败并通知负责人。\n\n"
        f"【测试情景】\n{req.situation}\n\n"
        f"【失败日志】\n```\n{req.failed_log}\n```\n\n"
        f"请调用 code_analyse 工具进行分析，然后调用 feishu_notify 发送报告。"
    )
    messages = [{"role": "user", "content": prompt}]

    async def event_generator():
        try:
            async for msg in agent_loop_stream(messages):
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'role': 'error', 'content': f'{type(e).__name__}: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.get("/reports")
def list_reports():
    reports_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    if not reports_dir.exists():
        return {"reports": []}
    files = [f.name for f in sorted(reports_dir.iterdir()) if f.suffix == ".md"]
    return {"reports": files}


@router.get("/reports/{filename}")
def get_report(filename: str):
    reports_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    file_path = reports_dir / filename
    # 安全检查：防止目录遍历
    try:
        file_path.resolve().relative_to(reports_dir.resolve())
    except ValueError:
        return {"error": "Invalid filename"}

    if not file_path.exists() or not file_path.is_file():
        return {"error": "Report not found"}

    return {"content": file_path.read_text(encoding="utf-8")}
