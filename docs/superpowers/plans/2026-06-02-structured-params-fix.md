# 结构化参数修复计划

**目标：** 前端直接传 {situation, failed_log}，后端拼接成 Prompt 传给 agent_loop，保留 LLM 灵活决策能力。

---

## 修改点

### 1. 后端新增 `/api/analyze` 端点

**文件：** `backend/api/routes.py`

新增：
```python
class AnalyzeRequest(BaseModel):
    situation: str
    failed_log: str

@router.post("/analyze")
def analyze(req: AnalyzeRequest):
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
        messages.append({"role": "assistant", "content": f"[Error] {type(e).__name__}: {e}"})
    return {"messages": _to_serializable(messages)}
```

### 2. 前端 API 层新增 analyze 函数

**文件：** `frontend/src/services/api.ts`

新增：
```typescript
export async function analyze(situation: string, failedLog: string): Promise<Message[]> {
  const res = await client.post("/analyze", { situation, failed_log: failedLog });
  return res.data.messages as Message[];
}
```

### 3. 前端 App.tsx 调用新 API

**文件：** `frontend/src/App.tsx`

修改 `handleSubmit`：
- 不再拼接字符串
- 直接调用 `analyze(situation, failedLog)`
- 拿到完整 messages 后更新 session

---

## 验证

1. 前端输入情景 + 日志，点击提交
2. 浏览器 Network 面板确认 POST body 是 `{situation, failed_log}`
3. 后端响应包含完整 Agent 执行过程
4. reports/ 目录生成新报告
5. 飞书通知发送成功
