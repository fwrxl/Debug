# Agent Web 界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 CLI Agent Demo 扩展为前后端分离的 Web 应用，前端 React Chat 界面，后端 FastAPI HTTP 入口，保留原有 Agent 自主决策链。

**Architecture:** FastAPI 后端做 HTTP 适配层，复用现有 `agent_loop` 让 Agent 自主调用 `code_analyse` → `feishu_notify`；React 前端渲染 Chat 界面，历史记录存 localStorage。

**Tech Stack:** FastAPI + Uvicorn (后端), React + TypeScript + Vite + Axios + TailwindCSS (前端)

---

## File Structure

```
znew/
├── backend/
│   ├── main.py              # FastAPI 入口，CORS，挂载路由
│   └── api/
│       └── routes.py        # /api/chat, /api/reports
├── frontend/
│   ├── package.json         # vite react-ts 模板生成
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js   # TailwindCSS 配置
│   ├── postcss.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx         # React 根挂载
│       ├── App.tsx          # 左右分栏布局 + session 管理
│       ├── index.css        # Tailwind 导入
│       ├── types.ts         # Message, Session 类型
│       ├── services/
│       │   └── api.ts       # axios 封装，POST /api/chat
│       ├── stores/
│       │   └── history.ts   # localStorage CRUD，保留最近 50 条
│       └── components/
│           ├── Sidebar.tsx      # 历史会话列表
│           ├── ChatWindow.tsx   # 消息气泡渲染
│           ├── MessageInput.tsx # 双 textarea + 提交
│           └── ReportCard.tsx   # 报告预览卡片
├── tools/                   # 保留现有
│   ├── __init__.py
│   ├── code_analyse.py
│   └── feishu_notify.py
├── agent.py                 # 抽离 agent_loop，保留 CLI __main__
├── reports/                 # 保留现有
├── .env                     # 保留现有
└── package.json (root)      # concurrently 启动脚本
```

---

### Task 1: 安装后端依赖并创建目录结构

**Files:**
- Create: `backend/main.py`
- Create: `backend/api/__init__.py`
- Create: `backend/api/routes.py`

- [ ] **Step 1: 安装 FastAPI 和 Uvicorn**

```bash
cd /Users/rxl/Documents/znew
pip install fastapi uvicorn python-multipart
```

- [ ] **Step 2: 创建目录**

```bash
mkdir -p backend/api
```

- [ ] **Step 3: 创建 backend/api/__init__.py**

```python
# backend/api/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/
git commit -m "chore: add backend directory and install fastapi"
```

---

### Task 2: 改造 agent.py 抽离可复用的 agent_loop

**Files:**
- Modify: `agent.py`（整体重构，保留 CLI 入口但抽离核心逻辑到可被 FastAPI 导入的函数）

**目标：** 将现有 `agent_loop()` 改造成纯函数，不依赖 `print` 和 `input`。FastAPI 可以 `from agent import agent_loop` 直接调用。

- [ ] **Step 1: 备份现有 agent.py**

```bash
cp /Users/rxl/Documents/znew/agent.py /Users/rxl/Documents/znew/agent.py.bak
```

- [ ] **Step 2: 重写 agent.py**

完整替换 `agent.py` 内容：

```python
"""
znew Agent Demo —— CLI + HTTP 共用入口

基于 Anthropic SDK + ReAct 工具调用循环。
集成两个真实能力：
1. code_analyse —— 分析测试失败日志，定位 Bug
2. feishu_notify —— 发送飞书消息通知

CLI 运行：python znew/agent.py
HTTP 导入：from agent import agent_loop
"""
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

WORKDIR = Path.cwd()

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
```

- [ ] **Step 3: 验证 CLI 仍可运行**

```bash
cd /Users/rxl/Documents/znew
python agent.py <<'EOF'
q
EOF
```

**Expected:** 打印 "znew Agent Demo" 和提示符后退出。

- [ ] **Step 4: 验证可被导入**

```bash
cd /Users/rxl/Documents/znew
python -c "from agent import agent_loop; print('import ok')"
```

**Expected:** `import ok`

- [ ] **Step 5: Commit**

```bash
git add agent.py
git commit -m "refactor(agent): extract agent_loop for reuse by FastAPI"
```

---

### Task 3: 创建 FastAPI 后端

**Files:**
- Create: `backend/main.py`
- Create: `backend/api/routes.py`

- [ ] **Step 1: 编写 backend/api/routes.py**

```python
from fastapi import APIRouter
from pydantic import BaseModel
from pathlib import Path
import json

from agent import agent_loop

router = APIRouter()


class ChatRequest(BaseModel):
    messages: list


class ChatResponse(BaseModel):
    messages: list


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    messages = req.messages
    try:
        agent_loop(messages)
    except Exception as e:
        # 即使出错也返回当前已累积的 messages，方便前端展示
        messages.append({"role": "assistant", "content": f"[Error] Agent loop failed: {type(e).__name__}: {e}"})
    return {"messages": messages}


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
```

- [ ] **Step 2: 编写 backend/main.py**

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


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 3: 启动后端并测试 health 接口**

```bash
cd /Users/rxl/Documents/znew/backend
python -m uvicorn main:app --reload --port 8000 &
UV_PID=$!
sleep 2
curl -s http://localhost:8000/health
kill $UV_PID
```

**Expected:** `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
cd /Users/rxl/Documents/znew
git add backend/
git commit -m "feat(backend): add FastAPI with /api/chat, /api/reports endpoints"
```

---

### Task 4: 初始化前端项目

**Files:**
- Create: `frontend/`（vite 模板生成全部文件）
- Modify: `frontend/package.json`（添加 axios, tailwindcss 依赖）
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`

- [ ] **Step 1: 使用 Vite 创建 React + TypeScript 项目**

```bash
cd /Users/rxl/Documents/znew
npm create vite@latest frontend -- --template react-ts
```

**Expected:** `frontend/` 目录生成，包含 `package.json`, `src/`, `index.html`, `vite.config.ts`, `tsconfig.json` 等。

- [ ] **Step 2: 安装额外依赖**

```bash
cd /Users/rxl/Documents/znew/frontend
npm install axios
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

- [ ] **Step 3: 配置 TailwindCSS**

替换 `frontend/tailwind.config.js`：

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

替换 `frontend/src/index.css`：

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen',
    'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue',
    sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

- [ ] **Step 4: 验证前端能启动**

```bash
cd /Users/rxl/Documents/znew/frontend
npm run dev &
FE_PID=$!
sleep 5
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173
kill $FE_PID
```

**Expected:** `200`

- [ ] **Step 5: Commit**

```bash
cd /Users/rxl/Documents/znew
git add frontend/
git commit -m "chore(frontend): init vite react-ts project with tailwindcss"
```

---

### Task 5: 前端类型定义 + API 封装 + 历史记录 Store

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/services/api.ts`
- Create: `frontend/src/stores/history.ts`

- [ ] **Step 1: 编写 types.ts**

```typescript
// frontend/src/types.ts

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: string;
}

export type MessageContent = string | Array<TextBlock | ToolUseBlock | ToolResultBlock>;

export interface Message {
  role: "user" | "assistant";
  content: MessageContent;
}

export interface Session {
  id: string;
  title: string;
  createdAt: string;
  messages: Message[];
}
```

- [ ] **Step 2: 编写 api.ts**

```typescript
// frontend/src/services/api.ts
import axios from "axios";
import type { Message } from "../types";

const API_BASE = "http://localhost:8000/api";

const client = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

export async function chat(messages: Message[]): Promise<Message[]> {
  const res = await client.post("/chat", { messages });
  return res.data.messages as Message[];
}

export async function listReports(): Promise<string[]> {
  const res = await client.get("/reports");
  return res.data.reports as string[];
}

export async function getReport(filename: string): Promise<string> {
  const res = await client.get(`/reports/${encodeURIComponent(filename)}`);
  return res.data.content as string;
}
```

- [ ] **Step 3: 编写 history.ts**

```typescript
// frontend/src/stores/history.ts
import type { Session } from "../types";

const STORAGE_KEY = "znew_sessions";
const MAX_SESSIONS = 50;

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function getSessions(): Session[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as Session[];
  } catch {
    return [];
  }
}

export function saveSessions(sessions: Session[]): void {
  const trimmed = sessions.slice(-MAX_SESSIONS);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
}

export function createSession(firstUserContent: string): Session {
  return {
    id: generateId(),
    title: firstUserContent.slice(0, 20) + (firstUserContent.length > 20 ? "..." : ""),
    createdAt: new Date().toISOString(),
    messages: [{ role: "user", content: firstUserContent }],
  };
}

export function updateSession(sessions: Session[], session: Session): Session[] {
  const idx = sessions.findIndex((s) => s.id === session.id);
  if (idx >= 0) {
    const next = [...sessions];
    next[idx] = session;
    return next;
  }
  return [...sessions, session];
}
```

- [ ] **Step 4: Commit**

```bash
cd /Users/rxl/Documents/znew
git add frontend/src/types.ts frontend/src/services/api.ts frontend/src/stores/history.ts
git commit -m "feat(frontend): add types, api client, and history store"
```

---

### Task 6: 创建 Sidebar 组件

**Files:**
- Create: `frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: 编写 Sidebar.tsx**

```tsx
// frontend/src/components/Sidebar.tsx
import type { Session } from "../types";

interface SidebarProps {
  sessions: Session[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export default function Sidebar({ sessions, activeId, onSelect, onNew }: SidebarProps) {
  return (
    <div className="w-64 bg-gray-100 border-r border-gray-200 flex flex-col h-full">
      <div className="p-4 border-b border-gray-200">
        <h1 className="text-lg font-bold text-gray-800">znew Agent</h1>
        <button
          onClick={onNew}
          className="mt-3 w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 transition"
        >
          + 新建会话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {[...sessions].reverse().map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`w-full text-left px-3 py-2 rounded text-sm truncate transition ${
              s.id === activeId
                ? "bg-blue-100 text-blue-800 font-medium"
                : "text-gray-700 hover:bg-gray-200"
            }`}
          >
            <div className="truncate">{s.title}</div>
            <div className="text-xs text-gray-400 mt-0.5">
              {new Date(s.createdAt).toLocaleString()}
            </div>
          </button>
        ))}
        {sessions.length === 0 && (
          <div className="text-gray-400 text-sm text-center py-8">暂无历史会话</div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/rxl/Documents/znew
git add frontend/src/components/Sidebar.tsx
git commit -m "feat(frontend): add Sidebar component"
```

---

### Task 7: 创建 ChatWindow 组件

**Files:**
- Create: `frontend/src/components/ChatWindow.tsx`
- Create: `frontend/src/components/ReportCard.tsx`（ChatWindow 会引用，可一起写）

- [ ] **Step 1: 编写 ChatWindow.tsx**

```tsx
// frontend/src/components/ChatWindow.tsx
import type { Message, MessageContent, ToolUseBlock, ToolResultBlock } from "../types";

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
}

function isToolUse(content: MessageContent): boolean {
  if (typeof content === "string") return false;
  return content.some((block) => block.type === "tool_use");
}

function getToolName(content: MessageContent): string {
  if (typeof content === "string") return "";
  const tool = content.find((block): block is ToolUseBlock => block.type === "tool_use");
  return tool?.name ?? "";
}

function isToolResult(content: MessageContent): boolean {
  if (typeof content === "string") return false;
  return content.some((block) => block.type === "tool_result");
}

function getToolResultText(content: MessageContent): string {
  if (typeof content === "string") return content;
  const result = content.find((block): block is ToolResultBlock => block.type === "tool_result");
  return typeof result?.content === "string" ? result.content : "";
}

function getTextContent(content: MessageContent): string {
  if (typeof content === "string") return content;
  const textBlock = content.find((block) => block.type === "text");
  return textBlock && "text" in textBlock ? textBlock.text : "";
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";

  if (isToolUse(msg.content)) {
    const name = getToolName(msg.content);
    return (
      <div className="flex justify-center my-2">
        <div className="bg-yellow-50 text-yellow-800 text-xs px-3 py-1 rounded-full border border-yellow-200">
          🔧 Agent 正在调用工具: <strong>{name}</strong>
        </div>
      </div>
    );
  }

  if (isToolResult(msg.content)) {
    const text = getToolResultText(msg.content);
    const isError = text.includes("[Error]") || text.includes("失败");
    return (
      <div className="flex justify-center my-2">
        <div
          className={`text-xs px-3 py-1 rounded-full border ${
            isError
              ? "bg-red-50 text-red-800 border-red-200"
              : "bg-green-50 text-green-800 border-green-200"
          }`}
        >
          {isError ? "❌" : "✅"} 工具执行结果（已截断显示）
        </div>
      </div>
    );
  }

  const text = getTextContent(msg.content);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} my-3`}>
      <div
        className={`max-w-[80%] px-4 py-2 rounded-lg whitespace-pre-wrap ${
          isUser
            ? "bg-blue-600 text-white rounded-br-none"
            : "bg-white text-gray-800 border border-gray-200 rounded-bl-none shadow-sm"
        }`}
      >
        {text}
      </div>
    </div>
  );
}

export default function ChatWindow({ messages, isLoading }: ChatWindowProps) {
  return (
    <div className="flex-1 flex flex-col h-full bg-gray-50">
      <div className="flex-1 overflow-y-auto p-4">
        {messages.map((msg, idx) => (
          <MessageBubble key={idx} msg={msg} />
        ))}
        {isLoading && (
          <div className="flex justify-start my-3">
            <div className="bg-white border border-gray-200 rounded-lg rounded-bl-none px-4 py-2 shadow-sm">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 编写 ReportCard.tsx（可选增强组件）**

```tsx
// frontend/src/components/ReportCard.tsx
interface ReportCardProps {
  reportPath: string;
  summary?: string;
}

export default function ReportCard({ reportPath, summary }: ReportCardProps) {
  const filename = reportPath.split("/").pop() ?? reportPath;
  return (
    <div className="bg-white border border-blue-200 rounded-lg p-3 my-2 shadow-sm">
      <div className="text-sm font-medium text-blue-800 mb-1">📄 分析报告</div>
      {summary && <div className="text-xs text-gray-600 mb-2">{summary}</div>}
      <a
        href={`http://localhost:8000/api/reports/${encodeURIComponent(filename)}`}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs text-blue-600 hover:underline"
      >
        查看完整报告 →
      </a>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/rxl/Documents/znew
git add frontend/src/components/ChatWindow.tsx frontend/src/components/ReportCard.tsx
git commit -m "feat(frontend): add ChatWindow and ReportCard components"
```

---

### Task 8: 创建 MessageInput 组件

**Files:**
- Create: `frontend/src/components/MessageInput.tsx`

- [ ] **Step 1: 编写 MessageInput.tsx**

```tsx
// frontend/src/components/MessageInput.tsx
import { useState } from "react";

interface MessageInputProps {
  onSubmit: (situation: string, failedLog: string) => void;
  disabled: boolean;
}

export default function MessageInput({ onSubmit, disabled }: MessageInputProps) {
  const [situation, setSituation] = useState("");
  const [failedLog, setFailedLog] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!situation.trim() || !failedLog.trim() || disabled) return;
    onSubmit(situation.trim(), failedLog.trim());
    setSituation("");
    setFailedLog("");
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white border-t border-gray-200 p-4 space-y-3"
    >
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          测试情景
        </label>
        <textarea
          value={situation}
          onChange={(e) => setSituation(e.target.value)}
          placeholder="描述测试失败的情景..."
          rows={2}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm resize-none"
          disabled={disabled}
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          失败日志
        </label>
        <textarea
          value={failedLog}
          onChange={(e) => setFailedLog(e.target.value)}
          placeholder="粘贴测试失败日志..."
          rows={4}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm resize-none font-mono"
          disabled={disabled}
        />
      </div>
      <button
        type="submit"
        disabled={disabled || !situation.trim() || !failedLog.trim()}
        className="w-full bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition text-sm font-medium"
      >
        {disabled ? "Agent 处理中..." : "提交分析"}
      </button>
    </form>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/rxl/Documents/znew
git add frontend/src/components/MessageInput.tsx
git commit -m "feat(frontend): add MessageInput component"
```

---

### Task 9: 组装 App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`（确保正确挂载）

- [ ] **Step 1: 重写 App.tsx**

```tsx
// frontend/src/App.tsx
import { useState, useCallback } from "react";
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import MessageInput from "./components/MessageInput";
import { getSessions, saveSessions, createSession, updateSession } from "./stores/history";
import { chat } from "./services/api";
import type { Session, Message } from "./types";

export default function App() {
  const [sessions, setSessions] = useState<Session[]>(() => getSessions());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const activeSession = sessions.find((s) => s.id === activeId) ?? null;

  const handleNew = useCallback(() => {
    const newSession = createSession("新会话");
    const next = [...sessions, newSession];
    setSessions(next);
    saveSessions(next);
    setActiveId(newSession.id);
  }, [sessions]);

  const handleSelect = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const handleSubmit = useCallback(
    async (situation: string, failedLog: string) => {
      const content = `情景：${situation}\n失败日志：${failedLog}`;

      let session: Session;
      let nextSessions: Session[];

      if (activeSession) {
        session = {
          ...activeSession,
          messages: [...activeSession.messages, { role: "user", content }],
        };
        nextSessions = updateSession(sessions, session);
      } else {
        session = createSession(content);
        session.messages = [{ role: "user", content }];
        nextSessions = [...sessions, session];
        setActiveId(session.id);
      }

      setSessions(nextSessions);
      saveSessions(nextSessions);
      setIsLoading(true);

      try {
        const updatedMessages = await chat(session.messages);
        const finalSession = { ...session, messages: updatedMessages };
        const finalSessions = updateSession(nextSessions, finalSession);
        setSessions(finalSessions);
        saveSessions(finalSessions);
      } catch (err) {
        const errorSession = {
          ...session,
          messages: [
            ...session.messages,
            {
              role: "assistant",
              content: `[Error] 请求失败: ${err instanceof Error ? err.message : String(err)}`,
            },
          ],
        };
        const errorSessions = updateSession(nextSessions, errorSession);
        setSessions(errorSessions);
        saveSessions(errorSessions);
      } finally {
        setIsLoading(false);
      }
    },
    [activeSession, sessions]
  );

  return (
    <div className="h-screen w-screen flex bg-gray-50">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={handleSelect}
        onNew={handleNew}
      />
      <div className="flex-1 flex flex-col h-full">
        <ChatWindow messages={activeSession?.messages ?? []} isLoading={isLoading} />
        <MessageInput onSubmit={handleSubmit} disabled={isLoading} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 检查 main.tsx**

确保 `frontend/src/main.tsx` 内容如下（vite 模板默认已生成，仅需确认）：

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 3: Commit**

```bash
cd /Users/rxl/Documents/znew
git add frontend/src/App.tsx frontend/src/main.tsx
git commit -m "feat(frontend): assemble App with session management and API integration"
```

---

### Task 10: 添加根目录启动脚本

**Files:**
- Create: `/Users/rxl/Documents/znew/package.json`（根目录）

- [ ] **Step 1: 编写根目录 package.json**

```json
{
  "name": "znew-agent-web",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "concurrently \"npm run dev:backend\" \"npm run dev:frontend\"",
    "dev:backend": "cd backend && python -m uvicorn main:app --reload --port 8000",
    "dev:frontend": "cd frontend && npm run dev",
    "build": "cd frontend && npm run build",
    "install:all": "npm install && cd frontend && npm install"
  },
  "devDependencies": {
    "concurrently": "^9.0.0"
  }
}
```

- [ ] **Step 2: 安装 concurrently**

```bash
cd /Users/rxl/Documents/znew
npm install
```

- [ ] **Step 3: 测试启动脚本**

```bash
cd /Users/rxl/Documents/znew
npm run dev &
DEV_PID=$!
sleep 5
curl -s http://localhost:8000/health
FE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5173)
echo "Frontend status: $FE_STATUS"
kill $DEV_PID
```

**Expected:** `{"status":"ok"}` 和 `Frontend status: 200`

- [ ] **Step 4: Commit**

```bash
cd /Users/rxl/Documents/znew
git add package.json package-lock.json
git commit -m "chore: add root package.json with concurrently dev script"
```

---

### Task 11: 端到端验证

**Files:**
- 无新增文件，仅运行验证

- [ ] **Step 1: 启动前后端**

```bash
cd /Users/rxl/Documents/znew
npm run dev
```

在浏览器打开 http://localhost:5173

- [ ] **Step 2: 手动验证流程**

1. 点击 "+ 新建会话"
2. 在"测试情景"输入：`用户输入 10/0 后程序崩溃`
3. 在"失败日志"输入：`ZeroDivisionError: float division by zero in term() line 44`
4. 点击"提交分析"
5. **Expected:** ChatWindow 显示：
   - 用户消息气泡
   - "🔧 Agent 正在调用工具: code_analyse"
   - "✅ 工具执行结果"
   - "🔧 Agent 正在调用工具: feishu_notify"
   - "✅ 工具执行结果"
   - Agent 最终总结文本气泡
6. **Expected:** 飞书消息成功送达
7. 刷新页面，左侧 Sidebar 仍显示该历史会话
8. 点击历史会话，右侧恢复完整对话记录

- [ ] **Step 3: 验证 CLI 模式未被破坏**

```bash
cd /Users/rxl/Documents/znew
python agent.py <<'EOF'
q
EOF
```

**Expected:** 正常启动并退出。

- [ ] **Step 4: Commit**

```bash
cd /Users/rxl/Documents/znew
git add -A
git commit -m "feat: complete Agent Web UI with React + FastAPI"
```

---

## Plan Self-Review

### Spec Coverage Check

| Spec 要求 | 对应 Task |
|-----------|-----------|
| FastAPI HTTP 入口 | Task 3 |
| `/api/chat` 端点调用 agent_loop | Task 3 |
| `/api/reports` 列表 | Task 3 |
| `/api/reports/{filename}` 获取 | Task 3 |
| agent_loop 可被 FastAPI 导入 | Task 2 |
| React Chat 界面 | Task 4-9 |
| 左侧历史记录 Sidebar | Task 6 |
| localStorage 持久化 | Task 5, 9 |
| 保留 CLI 入口 | Task 2 |
| 同时启动脚本 | Task 10 |

### Placeholder Scan

- ✅ 无 TBD/TODO
- ✅ 无 "implement later"
- ✅ 每个 step 都有完整代码或命令
- ✅ 无 "similar to Task N"

### Type Consistency

- ✅ `Message`, `Session`, `MessageContent` 类型在 Task 5 定义，Task 6-9 一致使用
- ✅ API 函数签名与 types.ts 一致
- ✅ `agent_loop` 签名前后端一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-02-agent-web-plan.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — 每个 Task 由独立子代理执行，我负责 review 和衔接

**2. Inline Execution** — 在当前会话中按顺序执行所有 Task

**Which approach?**
