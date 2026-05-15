## ADDED Requirements

### Requirement: ExecutionModule 是统一的执行引擎

`ExecutionModule.execute_plan(situation, failed_log, plan_steps, memory)` 是执行 capabilities 的主要入口。它接收 `PlanningModule.create_plan()` 产生的丰富计划步骤并按依赖顺序执行。`TestFeedbackAgent` 委托给 `ExecutionModule` 而非直接调用 capabilities。

### Requirement: ExecutionModule 跟踪步骤状态并存储 evidence

对于每个已执行的计划步骤，`ExecutionModule` 必须：
1. 调用 capability 前将步骤 `status` 设为 "running"
2. 以 `(situation, failed_log, memory)` 调用 capability
3. 将返回的结果存储在 `step["evidence"]`
4. 成功时将 `status` 设为 "done"，异常时设为 "failed"
5. 使用步骤的 `name` 作为 key 将 attempt 记录到 `memory.iteration.attempts`

### Requirement: ExecutionModule 实现自动链路规则

每个步骤完成后，`ExecutionModule.execute_plan()` 必须检查以下自动链路条件：

**自动链路 1 — owner_identification：**
- **WHEN** 任何步骤产生了包含 `evidence["failed_module"]` 或 `evidence["bug_module"]` 的结果，**且** `owner_identification` 尚未在当前计划中执行
- **THEN** `ExecutionModule` 自动以相同参数 `(situation, failed_log, memory)` 执行 `owner_identification` capability，并将其记录为计划中的额外步骤

**自动链路 2 — feishu_notification：**
- **WHEN** `owner_identification` 产生了包含 `evidence["owner_info"]["open_id"]` 的结果，**且** `feishu_notification` 尚未在当前计划中执行
- **THEN** `ExecutionModule` 自动以相同参数执行 `feishu_notification` capability，并将其记录为计划中的额外步骤

自动链路规则必须实现为单一可测试的函数 `ExecutionModule._check_auto_chain(step_results, memory)`，返回要执行的额外步骤名列表。

### Requirement: 所有步骤完成后 ExecutionModule 调用 ReflectionModule

所有计划步骤（包括自动链路步骤）执行完成后，`ExecutionModule.execute_plan()` 调用 `ReflectionModule.summarize(situation, findings, steps)`，其中：
- `situation`：输入的 situation dict
- `findings`：从所有步骤的 non-null `evidence` 规范化的 findings 列表
- `steps`：带最终状态的计划列表

返回的 summary dict 附加到执行结果的 key `"reflection_report"` 下。

### Requirement: ExecutionModule 返回结构化结果

`ExecutionModule.execute_plan()` 返回包含以下内容的 dict：
- `success`：bool，指示整体执行是否成功
- `steps`：所有计划步骤列表，带最终状态和 evidence
- `auto_chained_steps`：自动链路步骤名列表
- `reflection_report`：`ReflectionModule.summarize()` 返回的结果
- `notification_sent`：bool，指示是否发送了 feishu_notification
- `recipient`：通知接收者的 open_id（如发送）

### Requirement: 步骤执行遵循依赖顺序

`ExecutionModule` 按遵循 `dependencies` 字段的顺序执行步骤。无依赖的步骤先执行。某步骤只有在其所有依赖都有 `status="done"` 时才执行。如果某依赖失败，该依赖步骤的 `status` 设为 "failed" 并附上适当错误信息，且该依赖步骤**不执行**。

#### Scenario: 按依赖顺序执行步骤
- **WHEN** 计划有步骤：`[{"name": "log_localization", "dependencies": ["situation_analysis"]}, {"name": "situation_analysis", "dependencies": []}]`
- **THEN** `ExecutionModule` 先执行 `situation_analysis`，只有在它以 status="done" 完成后才执行 `log_localization`

#### Scenario: 当找到 failed_module 时自动链路触发 owner_identification
- **WHEN** `log_localization` 完成且 `evidence={"failed_module": "intent_classifier", ...}`，**且** `owner_identification` 尚未执行
- **THEN** `ExecutionModule` 自动执行 `owner_identification` 并将其追加到计划

#### Scenario: 当 owner_open_id 可用时自动链路触发 feishu_notification
- **WHEN** `owner_identification` 完成且 `evidence={"owner_info": {"open_id": "ou_xxx", ...}, ...}`，**且** `feishu_notification` 尚未执行
- **THEN** `ExecutionModule` 自动执行 `feishu_notification` 并将其追加到计划

#### Scenario: 依赖失败阻止依赖步骤
- **WHEN** 步骤 A（步骤 B 的依赖）的 `status="failed"` 且 `error="module not found"`
- **THEN** 步骤 B 的 `status` 设为 "failed" 且 `error="dependency step A failed"`，步骤 B 不执行

#### Scenario: 执行结果包含 reflection report
- **WHEN** 所有步骤（包括自动链路）完成
- **THEN** 返回的 dict 包含 `"reflection_report"`，带有 `ReflectionModule.summarize()` 的完整 summary