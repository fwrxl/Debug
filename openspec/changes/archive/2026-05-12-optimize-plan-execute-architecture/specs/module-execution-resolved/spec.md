## ADDED Requirements

### Requirement: module_execution 注册到 TestFeedbackAgent.capabilities

`TestFeedbackAgent.capabilities` 包含 `module_execution`，与其他四个 capabilities（situation_analysis、log_localization、owner_identification、feishu_notification）同级。`ModuleExecutor` 实例在 `TestFeedbackAgent.__init__()` 中创建，并存储在 key `"module_execution"` 下。

### Requirement: module_execution 可供规划使用但不会自动触发

`module_execution` 是一个有效的步骤名，`PlanningModule` 可以将其包含在计划中（例如 `["situation_analysis", "log_localization", "module_execution", "owner_identification", "feishu_notification"]`）。`ExecutionModule` 中的自动链路规则**不会**自动触发 `module_execution`——它只在 LLM 规划器显式将其纳入计划时才执行。

### Requirement: ModuleExecutor.execute() 将结果写入 memory.iteration.attempts

当调用 `ModuleExecutor.execute(situation, failed_log, memory)` 时，它将结果存储在 `memory.iteration.attempts` 中，key 为步骤名 `"module_execution"`。结果 dict 包含 `modules_checked`、`suspicious_modules` 和 `conclusion`。

#### Scenario: module_execution 在计划中
- **WHEN** `PlanningModule.create_plan()` 返回包含 `"module_execution"` 的计划
- **THEN** `ExecutionModule.execute_plan()` 执行 `ModuleExecutor` 并将结果存储在 `memory.iteration.attempts["module_execution"]`

#### Scenario: module_execution 不在计划中
- **WHEN** 计划不包含 `"module_execution"`
- **THEN** `ExecutionModule` 不执行 `ModuleExecutor`（无自动触发）