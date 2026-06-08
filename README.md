# znew Agent Web

基于 Anthropic SDK + ReAct 工具调用循环的调试 Agent Web 应用。

## 功能

- **测试失败分析**：输入测试情景和失败日志，Agent 自动分析代码定位 Bug
- **飞书通知**：分析报告自动生成并发送至飞书
- **会话历史**：所有分析记录保存在浏览器 localStorage，刷新不丢失
- **Chat 界面**：左侧历史列表 + 右侧对话区，直观展示 Agent 执行过程

## 技术栈

- **后端**：FastAPI + Python 3.12
- **前端**：React 19 + TypeScript + Vite + TailwindCSS
- **AI**：Anthropic SDK（Claude/MiniMax 等兼容模型）
- **通知**：飞书 Open API

## 项目结构

```
znew/
├── backend/                    # FastAPI
│   ├── main.py                 # 应用入口
│   └── api/
│       └── routes.py           # /api/analyze, /api/reports
├── frontend/                   # React + Vite
│   └── src/
│       ├── App.tsx             # 主布局 + 状态管理
│       ├── components/         # Sidebar, ChatWindow, MessageInput
│       ├── services/api.ts     # Axios 封装
│       ├── stores/history.ts   # localStorage CRUD
│       └── types.ts            # TypeScript 类型
├── tools/                      # Agent 工具
│   ├── code_analyse.py         # 代码分析
│   └── feishu_notify.py        # 飞书通知
├── agent.py                    # Agent 核心循环（CLI + HTTP 共用）
└── reports/                    # 分析报告输出目录
```

## 环境配置

在项目根目录创建 `.env` 文件：

```ini
# Anthropic API（或兼容提供商）
ANTHROPIC_API_KEY=sk-xxx
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
MODEL_ID=MiniMax-M2.5

# 飞书配置
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_OPEN_BASE_URL=https://open.feishu.cn
receive_id=ou_xxx

# 代码分析目标仓库
DEBUG_PROJECT_PATH=/path/to/repo
```

## 安装

```bash
# 1. 后端依赖（FastAPI, Anthropic SDK 等）
pip install fastapi uvicorn python-multipart anthropic python-dotenv requests

# 2. 前端依赖
cd frontend && npm install
```

或者一键安装：
```bash
npm run install:all
```

## 启动

```bash
# 同时启动前后端
cd /Users/rxl/Documents/znew
npm run dev
```

- 前端：http://localhost:5173
- 后端：http://localhost:8000

也可以分别启动：
```bash
# 后端
npm run dev:backend

# 前端（新终端）
npm run dev:frontend
```

## 使用

1. 打开 http://localhost:5173
2. 点击 **"+ 新建会话"**
3. 填写**测试情景**和**失败日志**
4. 点击 **"提交分析"**
5. 等待 Agent 执行（约 30-60 秒）：
   - 调用 `code_analyse` 分析代码
   - 生成报告到 `reports/` 目录
   - 调用 `feishu_notify` 发送通知
6. 查看飞书消息确认报告送达

## CLI 模式

除了 Web 界面，也可以直接命令行使用：

```bash
python agent.py
```

输入问题后 Agent 会交互式分析。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/analyze` | 接收 `situation` + `failed_log`，返回完整 Agent 执行记录 |
| GET | `/api/reports` | 列出所有报告文件名 |
| GET | `/api/reports/{filename}` | 获取单个报告内容 |
| GET | `/health` | 健康检查 |

## 注意事项

- Agent 分析需要调用 LLM，请确保 API Key 有效且有余额
- `code_analyse` 工具依赖 `opencode` 可执行文件，需提前安装
- 飞书通知需要配置正确的 `app_id`、`app_secret` 和 `receive_id`
- 分析报告保存在 `reports/` 目录，不会自动清理
