## ADDED Requirements

### Requirement: MemoryModule 为上下文数据提供类型化的读写辅助方法

`MemoryModule` 为跨 capabilities 共享的上下文数据提供显式读写方法：

- `set_bug_module(module_name: str)` — 将 `bug_module` 存入 `memory.context`，同时写入最近一次 attempt 的 evidence 以供自动链路查找
- `get_bug_module() -> Optional[str]` — 返回 `memory.context["bug_module"]`
- `set_owner_open_id(open_id: str)` — 将 `owner_open_id` 存入 `memory.context`
- `get_owner_open_id() -> Optional[str]` — 返回 `memory.context["owner_open_id"]`
- `get_latest_attempt(step_name: str) -> Optional[Dict]` — 从 `memory.iteration.attempts` 返回给定步骤名的最近一次 attempt

**注意：** `memory.get_context()` 在当前 `MemoryModule` 中**不存在**，本 spec 不新增此方法。上述辅助方法明确指定了各自存储和读取的具体字段。

### Requirement: Capability 结果以步骤名为 key 存储在 iteration attempts 中

当 capability 返回结果字典 `r` 时，`ExecutionModule` 将其存储在 `memory.iteration.attempts` 中，格式为：
```python
{
    "step": step_name,
    "evidence": r,
    "success": r.get("success", True),
    "timestamp": "<current ISO timestamp>"
}
```

结果可通过 `memory.iteration.get_attempts_by_step(step_name)` 检索。

### Requirement: 自动链路从最新的 log_localization attempt 读取 failed_module

`owner_identification` 的自动链路规则从以下位置读取 `failed_module`：
`memory.iteration.get_attempts_by_step("log_localization")[-1]["evidence"]["failed_module"]`

如果不存在 `log_localization` attempt，自动链路**不触发**。

### Requirement: 自动链路从 memory context 读取 owner_open_id

`feishu_notification` 的自动链路规则从 `memory.get_owner_open_id()` 读取 `owner_open_id`（这是 MemoryModule 的新增辅助方法——注意：`memory.get_context()` 不存在）。

`owner_identification` capability 在填充结果后调用 `memory.set_owner_open_id(evidence["owner_info"]["open_id"])`。

### Requirement: MemoryModule.reset() 清空 context 和 iteration memory

当调用 `memory.reset()`（新输入开始时），`context`（current_step、confidence、conversation）和 `iteration`（attempts）都被清空。`created_at` 时间戳被刷新。

#### Scenario: 存储和检索 bug_module
- **WHEN** `log_localization` 返回 `evidence={"failed_module": "intent_classifier", ...}`
- **THEN** `memory.set_bug_module("intent_classifier")` 将其存入 context，`memory.get_bug_module()` 立即返回 `"intent_classifier"` 且在后续步骤之后仍然返回

#### Scenario: 自动链路从正确来源读取
- **WHEN** `ExecutionModule` 检查 `owner_identification` 的自动链路
- **THEN** 它从最新的 `log_localization` attempt 的 evidence 读取 `failed_module`，**不是**从 `memory.context`

#### Scenario: Memory reset 清空所有状态
- **WHEN** 在两次分析运行之间调用 `memory.reset()`
- **THEN** 第二次运行的 `memory.get_bug_module()` 返回 `None`，`memory.get_owner_open_id()` 返回 `None`（无第一次运行的状态渗透）