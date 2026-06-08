# Agent Web 界面设计文档

日期: 2026-06-02

## 目标

将现有的 CLI Agent Demo（`znew/`）扩展为前后端分离的 Web 应用：
- **前端**：React + Vite Chat 界面，左侧历史记录，右侧对话区
- **后端**：FastAPI HTTP 入口，调用现有的 `agent_loop` 让 Agent 自主决策
- 保留原有 Agent 决策链（`code_analyse` → 生成报告 → `feishu_notify`）不变

## 项目结构

```
znew/
├── backend/                    # 新增 FastAPI
│   ├── main.py                 # FastAPI 入口，CORS，挂载路由
│   └── api/
│       └── routes.py           # /api/chat, /api/reports/*
├── frontend/                   # 新增 React (Vite)
│   ├── src/
│   │   ├── App.tsx             # 左右分栏布局
│   │   ├── components/
│   │   │   ├── Sidebar.tsx     # 历史会话列表
│   │   │   ├── ChatWindow.tsx  # 消息渲染区域
│   │   │   ├── MessageInput.tsx # 双输入框表单
│   │   │   └── ReportCard.tsx  # 报告预览 + 飞书状态
│   │   ├── services/
│   │   │   └── api.ts          # axios 封装调用后端
│   │   ├── stores/
│   │   │   └── history.ts      # localStorage 读写
│   │   └── types.ts            # TypeScript 类型定义
│   └── package.json
├── tools/                      # 保留（code_analyse.py, feishu_notify.py）
├── agent.py                    # 保留 CLI 入口；抽离 agent_loop 供后端导入
├── reports/                    # 保留报告输出目录
├── .env                        # 保留现有配置
├── design.md                   # 原设计文档
└── plan.md                     # 原实现计划
```

## API 设计

### POST /api/chat

启动 Agent 循环，由 Agent 自主调用工具链。

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "情景：...\n失败日志：..."}
  ]
}
```

**Response:**
```json
{
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": [{"type": "tool_use", "name": "code_analyse", ...}]},
    {"role": "user", "content": [{"type": "tool_result", ...}]},
    {"role": "assistant", "content": [{"type": "tool_use", "name": "feishu_notify", ...}]},
    {"role": "user", "content": [{"type": "tool_result", ...}]},
    {"role": "assistant", "content": [{"type": "text", "text": "分析完成..."}]}
  ]
}
```

后端行为：
1. 接收 `messages` 数组
2. 调用 `agent_loop(messages)`（复用现有 `agent.py` 逻辑）
3. 返回完整 `messages` 数组给前端

### GET /api/reports

列出 `reports/` 目录下所有报告文件名。

**Response:**
```json
{"reports": ["analysis_20260602_153247.md", "analysis_20260602_153941.md"]}
```

### GET /api/reports/{filename}

获取单个报告文件的原始 Markdown 内容。

**Response:** 纯文本 Markdown

## 后端改造点

### 1. `agent.py` 抽离核心逻辑

现有 `agent.py` 的 `agent_loop()` 函数需要改造成可被 FastAPI 导入的纯函数：
- 移除 `if __name__ == "__main__"` 块中的 CLI 循环逻辑（保留 CLI 入口，但抽离核心循环）
- `agent_loop(messages: list)` 保持签名不变，只是不再打印到 stdout
- 环境变量加载、Anthropic 客户端初始化保持原样

### 2. `backend/main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router

app = FastAPI(title="znew Agent Web")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
```

### 3. `backend/api/routes.py`

```python
from fastapi import APIRouter
from pydantic import BaseModel
from agent import agent_loop  # 复用现有 agent_loop

router = APIRouter()

class ChatRequest(BaseModel):
    messages: list

@router.post("/chat")
def chat(req: ChatRequest):
    agent_loop(req.messages)
    return {"messages": req.messages}

@router.get("/reports")
def list_reports():
    ...

@router.get("/reports/{filename}")
def get_report(filename: str):
    ...
```

## 前端设计

### 组件职责

| 组件 | 职责 |
|------|------|
| `App.tsx` | 左右分栏布局（Sidebar + ChatWindow），管理当前选中的 session |
| `Sidebar.tsx` | 显示 `localStorage` 中的历史会话列表（按时间倒序），支持点击切换 |
| `ChatWindow.tsx` | 渲染当前 session 的所有消息，区分用户/Agent/工具调用 |
| `MessageInput.tsx` | 两个 textarea（情景 + 失败日志）+ 提交按钮，提交时拼接内容并 POST /api/chat |
| `ReportCard.tsx` | 当检测到 Agent 返回了报告路径时，展示报告摘要 + "查看完整报告" 链接 |

### 数据类型

```typescript
// types.ts
export interface Message {
  role: "user" | "assistant";
  content: string | Array<TextBlock | ToolUseBlock | ToolResultBlock>;
}

export interface Session {
  id: string;
  title: string;      // 从第一条 user 消息提取前 20 字
  createdAt: string;
  messages: Message[];
}
```

### 状态管理

使用 React `useState` + `useContext` 足够（不需要 Redux/Zustand）：
- `sessions`: `Session[]`，从 `localStorage` 初始化
- `activeSessionId`: 当前激活的 session ID
- `isLoading`: 请求中状态，用于显示 loading spinner

### localStorage 结构

```typescript
localStorage.setItem("znew_sessions", JSON.stringify([
  { id: "uuid", title: "ZeroDivisionError...", createdAt: "2026-06-02T10:00:00", messages: [...] }
]));
```

## 数据流

1. 用户在 `MessageInput` 输入情景 + 失败日志，点击提交
2. 前端拼接成一条 user message，POST `/api/chat`
3. 后端调用 `agent_loop(messages)`，Agent 内部：
   - 调用 `code_analyse` → 生成报告 → 保存到 `reports/`
   - 调用 `feishu_notify` → 发送飞书通知
   - 返回最终文本总结
4. 后端返回完整 `messages` 数组（包含 tool_use / tool_result / text 全部过程）
5. 前端更新 `sessions[activeSessionId].messages`，并写入 `localStorage`
6. `ChatWindow` 重新渲染，显示完整对话过程

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| 后端 `agent_loop` 异常 | FastAPI try/except 捕获，返回 `{"success": false, "error": "..."}`，前端显示错误提示 |
| 网络请求失败 | Axios interceptor 统一处理，显示 toast/alert |
| 飞书发送失败 | Agent 会收到 tool_result 中的 error 信息，前端正常展示 |
| localStorage 满 | 保留最近 50 条 session，自动清理旧数据 |

## 启动方式

### 开发模式（同时启动前后端）

```bash
# 后端
python -m uvicorn backend.main:app --reload --port 8000

# 前端（新终端）
cd frontend && npm run dev
```

### 生产模式（可选，本地打包）

```bash
cd frontend && npm run build
# FastAPI 通过 `StaticFiles` 挂载 `frontend/dist`，单端口 8000 服务全部
```

> 本次实现以开发模式为主，生产打包作为可选后续。

## 依赖

### 后端新增
- `fastapi`
- `uvicorn`
- `python-multipart`

### 前端
- `react`
- `react-dom`
- `vite`
- `typescript`
- `axios`
- `tailwindcss`（用于快速样式，可选）

## 成功标准

- [ ] `python -m uvicorn backend.main:app --reload` 启动后端，FastAPI docs 可访问
- [ ] `npm run dev` 启动前端，页面显示左右分栏 Chat 界面
- [ ] 输入情景和失败日志，点击提交，Agent 完整执行工具链
- [ ] ChatWindow 正确渲染整个对话过程（包括 tool_use 提示）
- [ ] 飞书通知成功发送
- [ ] 关闭页面后重新打开，历史会话列表仍然存在
- [ ] 原有 `python znew/agent.py` CLI 模式仍可正常运行
