## ADDED Requirements

### Requirement: 自动链路规则集中在 ExecutionModule

`owner_identification` 和 `feishu_notification` 的自动链路规则**只能**在 `ExecutionModule._check_auto_chain(step_results, memory)` 中实现。其他任何模块、脚本或文件不得包含这两个 capabilities 的自动链路逻辑。该函数返回要执行的额外步骤名列表（可能为空）。

### Requirement: 找到 bug_module 时触发 owner_identification 的自动链路

`ExecutionModule._check_auto_chain()` 在以下情况触发 `owner_identification`：
1. 任何已执行步骤产生了包含 `failed_module` 或 `bug_module` 的 evidence，**且**
2. `owner_identification` 尚未在当前计划中执行

检查从 `memory.iteration.get_attempts_by_step("log_localization")[-1]["evidence"]["failed_module"]` 读取 `failed_module`（如果 `log_localization` attempt 存在），否则从任何步骤的 evidence 读取。

### Requirement: owner_open_id 可用时触发 feishu_notification 的自动链路

`ExecutionModule._check_auto_chain()` 在以下情况触发 `feishu_notification`：
1. `owner_identification` 已执行且其 evidence 包含 `owner_info.open_id`，**且**
2. `feishu_notification` 尚未在当前计划中执行

检查从 `memory.get_owner_open_id()` 读取 `owner_open_id`（这是 MemoryModule 的新增辅助方法——注意：`memory.get_context()` 不存在）。

### Requirement: 自动链路步骤追加到计划并按顺序执行

当自动链路条件满足时，`ExecutionModule`：
1. 为触发的 capability 创建新的计划步骤字典
2. 将其追加到计划的步骤列表
3. 在继续下一个原计划步骤之前执行它

自动链路步骤出现在返回结果的 `auto_chained_steps` 列表中。

### Requirement: 自动链路逻辑可独立测试

`ExecutionModule._check_auto_chain(step_results, memory)` 必须能够用 mock 的 `step_results` 和 `memory` 对象调用，在不需要完整执行流程的情况下返回确定性结果。

#### Scenario: log_localization 后自动链路触发 owner_identification
- **WHEN** 计划是 `["situation_analysis", "log_localization"]`，log_localization 完成且 `evidence={"failed_module": "intent_classifier", ...}`
- **THEN** `_check_auto_chain` 返回 `["owner_identification"]`，Executor 追加并执行它

#### Scenario: 如果 owner_identification 已运行则不会重复自动链路
- **WHEN** 计划已包含 `["situation_analysis", "log_localization", "owner_identification"]`
- **THEN** `_check_auto_chain` **不会**再次返回 `["owner_identification"]`（无重复）

#### Scenario: owner_identification 后自动链路触发 feishu_notification
- **WHEN** 计划包含 `["situation_analysis", "log_localization", "owner_identification"]` 且 owner_identification 完成且 `evidence={"owner_info": {"open_id": "ou_xxx", ...}, ...}`
- **THEN** `_check_auto_chain` 返回 `["feishu_notification"]`，Executor 追加并执行它

#### Scenario: 每个步骤后检查自动链路条件
- **WHEN** 步骤 1（situation_analysis）完成
- **THEN** 在继续步骤 2 之前，用包含步骤 1 evidence 的 `step_results` 调用 `_check_auto_chain`

#### Scenario: 自动链路隔离可测试
- **WHEN** 用 `step_results=[{"name": "log_localization", "evidence": {"failed_module": "intent_classifier"}}]` 和 memory（attempts 中无 owner_identification）调用 `_check_auto_chain`
- **THEN** 它确定性返回 `["owner_identification"]`