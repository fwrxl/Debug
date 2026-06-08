# znew Agent Demo 设计文档

日期: 2026-06-02

## 目标

基于 Anthropic SDK + ReAct 工具调用循环，实现一个 CLI 交互式 Agent Demo。Agent 集成两个真实能力：
1. `code_analyse` —— 分析测试失败日志，定位 Bug
2. `feishu_notify` —— 发送飞书消息通知

## 文件结构

```
znew/
├── .env                  # znew 独立配置（ANTHROPIC、飞书、项目路径等）
├── design.md             # 本文档
├── agent.py              # Anthropic SDK 客户端 + ReAct 工具循环 + CLI 交互
└── tools/
    ├── __init__.py
    ├── code_analyse.py   # 封装调用 capabilities/code_analyse/analyzer.py
    └── feishu_notify.py  # 封装调用 integrations/feishu_client.py 真实发消息
```

## 组件职责

### agent.py
- 加载 `.env` 环境变量
- 初始化 Anthropic 客户端
- 定义 TOOLS schema（code_analyse + feishu_notify）
- 实现 `agent_loop()`：LLM 对话循环，处理 tool_use / tool_result
- CLI 交互：逐行读取用户输入，输入 q 退出
- 启动时自动将 znew 的父目录（本仓库根目录）加入 `sys.path`，确保能 import 到 `capabilities` 和 `integrations`

### tools/code_analyse.py
- `run(situation: str, failed_log: str, target_repo_path: str = None) -> str`
- 调用 `capabilities.code_analyse.analyzer.execute()`
- `target_repo_path` 未提供时，默认从 `.env` 读取 `DEBUG_PROJECT_PATH`
- 返回格式化字符串（包含 error_cause、bug_location、suggested_fix、confidence）

### tools/feishu_notify.py
- `run(text: str, receive_id: str = None) -> str`
- 调用 `integrations.feishu_client.send_text_message()`
- `receive_id` 未提供时，默认从 `.env` 读取 `receive_id`
- 返回发送结果（success / message_id / error）

## 数据流

1. 用户输入问题（如"分析这个测试失败并通知负责人"）
2. LLM 自主决策：先调用 `code_analyse`（传入 situation + failed_log）
3. tool handler 真实执行 `analyzer.execute()`，返回 Bug 分析报告
4. LLM 拿到报告后，再调用 `feishu_notify`（传入分析报告摘要）
5. tool handler 真实调用 `send_text_message()`，飞书消息真实发送
6. LLM 汇总结果回复用户

## 环境变量（.env）

```
ANTHROPIC_API_KEY=sk-xxx
ANTHROPIC_BASE_URL=https://api.anthropic.com  # 可选，如果用代理
MODEL_ID=claude-sonnet-4-6

FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_OPEN_BASE_URL=https://open.feishu.cn
receive_id=ou_xxx

DEBUG_PROJECT_PATH=/path/to/repo
```

## 错误处理

- **code_analyse 失败**（opencode 未安装、路径不存在、解析失败）：try/except 捕获，返回错误信息字符串给 LLM，由 LLM 决定重试或告知用户
- **feishu 发送失败**（token 过期、网络错误、HTTP 非 200）：返回具体 API 错误信息给 LLM
- **环境变量缺失**：`agent.py` 启动时检查 `ANTHROPIC_API_KEY` 和 `MODEL_ID`，缺失则打印明确提示并退出
- **import 失败**：`agent.py` 自动将父目录加入 `sys.path`，确保能 import 到项目的能力模块

## 成功标准

- [ ] 启动 `python znew/agent.py` 后进入交互式 CLI
- [ ] 输入测试场景和失败日志后，Agent 能真实调用 `code_analyse` 并得到分析报告
- [ ] Agent 能真实调用 `feishu_notify` 并发送飞书消息
- [ ] 飞书消息确实送达指定 receive_id
