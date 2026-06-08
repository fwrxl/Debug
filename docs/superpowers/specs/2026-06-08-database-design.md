# znew Agent 数据库设计方案

## 背景

当前系统使用浏览器 localStorage 存储会话历史，存在以下问题：
- 数据无法跨设备同步
- 无法支持团队协作（共享分析报告）
- 报告文件散落在文件系统中，无权限管理
- 飞书通知发送记录无法追溯

本设计将数据迁移到 SQLite 数据库，支持飞书 OAuth 登录、个人/团队数据隔离。

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 数据库 | SQLite + SQLAlchemy | 零配置、文件存储、以后可无缝迁移到 PostgreSQL |
| 身份认证 | 飞书 OAuth | 已有飞书通知功能，集成自然；用户无需额外注册 |
| 共享粒度 | 按 Session（会话）共享 | 一次分析任务 = 一个完整会话，符合使用直觉 |
| 团队成员 | 飞书组织架构自动同步 + 手动白名单 | 兼顾自动化和可控性 |

## 数据库表结构

### users — 飞书登录用户

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, auto | 内部自增ID |
| feishu_open_id | VARCHAR(64) | UNIQUE, NOT NULL | 飞书 open_id |
| name | VARCHAR(128) | | 姓名 |
| avatar_url | VARCHAR(512) | | 头像URL |
| department_id | VARCHAR(64) | | 飞书部门ID |
| department_name | VARCHAR(128) | | 部门名称 |
| is_admin | BOOLEAN | DEFAULT FALSE | 是否管理员 |
| created_at | DATETIME | DEFAULT now | 首次登录时间 |

### sessions — 分析会话

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(32) | PK | UUIDv4 |
| user_id | INTEGER | FK → users.id, NOT NULL | 创建者 |
| title | VARCHAR(128) | NOT NULL | 会话标题（首条消息摘要）|
| status | VARCHAR(16) | DEFAULT 'active' | active / archived |
| visibility | VARCHAR(16) | DEFAULT 'private' | private（仅自己）/ team（团队可见）|
| created_at | DATETIME | DEFAULT now | 创建时间 |

### messages — 会话消息

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, auto | 自增ID |
| session_id | VARCHAR(32) | FK → sessions.id, NOT NULL, INDEX | 所属会话 |
| role | VARCHAR(16) | NOT NULL | user / assistant / tool_use / tool_result |
| content | TEXT | NOT NULL | 消息内容（JSON 字符串或纯文本）|
| tool_name | VARCHAR(64) | | 仅 role='tool_use' 时有值 |
| tool_input | TEXT | | 仅 role='tool_use' 时有值，JSON 参数 |
| tool_use_id | VARCHAR(64) | | 关联 tool_use 和 tool_result |
| created_at | DATETIME | DEFAULT now | 时间 |

**索引**：session_id + created_at（按会话查询消息时按时间排序）

### reports — 报告元数据

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, auto | 自增ID |
| session_id | VARCHAR(32) | FK → sessions.id, NOT NULL | 所属会话 |
| filename | VARCHAR(256) | NOT NULL | 文件名 |
| file_path | VARCHAR(512) | NOT NULL | 磁盘绝对路径 |
| created_at | DATETIME | DEFAULT now | 生成时间 |

### notifications — 飞书通知发送记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, auto | 自增ID |
| session_id | VARCHAR(32) | FK → sessions.id, NOT NULL | 所属会话 |
| report_id | INTEGER | FK → reports.id | 关联的报告（可选）|
| sender_id | INTEGER | FK → users.id | 发送者 |
| receiver_open_id | VARCHAR(64) | NOT NULL | 接收者飞书ID |
| receiver_name | VARCHAR(128) | | 接收者姓名 |
| status | VARCHAR(16) | NOT NULL | success / failed |
| message_id | VARCHAR(64) | | 飞书返回的 message_id |
| error_msg | TEXT | | 失败原因 |
| sent_at | DATETIME | DEFAULT now | 发送时间 |

### team_members — 手动维护的团队白名单

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, auto | 自增ID |
| user_id | INTEGER | FK → users.id, UNIQUE | 用户ID |
| added_by | INTEGER | FK → users.id | 添加者 |
| added_at | DATETIME | DEFAULT now | 添加时间 |

## 数据流

```
用户登录
  └─► 飞书 OAuth 回调
      └─► 查/创 users 记录
          └─► 发 JWT Token

创建会话
  └─► sessions 插入记录（visibility=private）
      └─► messages 插入 user 消息
          └─► Agent 流式回复逐条入 messages
              └─► tool_use / tool_result 入 messages
                  └─► 生成 report → reports 插入 + 文件系统存 .md
                      └─► 飞书通知 → notifications 插入记录

共享会话
  └─► 修改 sessions.visibility = 'team'
      └─► 同部门 + team_members 白名单中的用户可见
```

## 权限规则

| 场景 | 可见条件 |
|------|---------|
| 查看自己创建的会话 | `sessions.user_id == 当前用户.id` |
| 查看团队共享的会话 | `sessions.visibility == 'team' AND (同 department_id OR 在 team_members 中)` |
| 维护白名单 | `users.is_admin == TRUE` |

## API 变更

### 新增接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/auth/feishu/callback` | 飞书 OAuth 回调 |
| GET | `/auth/me` | 获取当前登录用户信息 |
| GET | `/api/sessions` | 查询当前用户的会话列表 |
| POST | `/api/sessions` | 创建新会话 |
| GET | `/api/sessions/{id}` | 获取会话详情（含消息）|
| POST | `/api/sessions/{id}/messages` | 发送消息（触发 Agent 分析）|
| PATCH | `/api/sessions/{id}/visibility` | 修改会话可见性（private/team）|
| GET | `/api/team-members` | 获取团队成员列表 |
| POST | `/api/team-members` | 添加团队成员（管理员）|
| DELETE | `/api/team-members/{id}` | 移除团队成员（管理员）|

### 变更接口

| 方法 | 路径 | 变更 |
|------|------|------|
| POST | `/api/analyze` | 改为 `/api/sessions/{id}/messages` 的一部分 |
| POST | `/api/analyze/stream` | 同上，流式消息发送 |
| GET | `/api/reports` | 增加过滤：只看自己有权限访问的会话的报告 |

## 前端变更

1. **登录页**：新增飞书扫码登录入口
2. **路由守卫**：未登录跳转登录页，已登录自动跳首页
3. **API 层**：所有请求自动带 JWT Token（Authorization: Bearer <token>）
4. **历史管理**：从 localStorage 迁移到 `/api/sessions` REST API
5. **共享按钮**：Session 详情页增加"设为团队可见/私有"切换

## 迁移策略

1. 数据库文件：`data/znew.db`（SQLite）
2. 自动建表：后端启动时 SQLAlchemy 自动 create_all
3. 历史数据：localStorage 中的旧数据可以导出为 JSON，提供一次性的"导入旧数据"功能
4. 报告文件：保留在 `reports/` 目录，数据库只存元数据

## 未来扩展

- 统计仪表盘：查询 notifications 表，统计"本周分析了多少 Bug"、"通知成功率"
- 审计日志：记录谁看了谁的报告
- 数据归档：将旧 sessions 标记为 archived，清理 messages 中的大文本
- PostgreSQL 迁移：只改数据库连接字符串，模型层零改动
