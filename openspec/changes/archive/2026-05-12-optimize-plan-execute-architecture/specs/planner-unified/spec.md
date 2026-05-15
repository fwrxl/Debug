## ADDED Requirements

### Requirement: LLM 规划提示词由单一函数构造

`LLMClient._build_plan_prompt()` 方法是构造 LLM 规划提示词的**唯一**负责函数。禁止在 debug 脚本或 agent 代码中内联定义任何 capability 描述、决策规则或提示词模板。

### Requirement: PlanningModule.create_plan() 返回丰富的计划步骤

`PlanningModule.create_plan()` 返回计划步骤字典列表。每个步骤**至少**包含：
- `name`：字符串，capability 标识符（例如 "situation_analysis"）
- `description`：字符串，步骤的人类可读描述
- `input`：字典，描述步骤需要从 memory/context 获取的内容
- `output_key`：字符串，结果存储在 memory 中的 key（例如 "situation_result"）
- `dependencies`：列表，必须在此步骤之前完成的步骤名
- `status`：字符串，"pending" | "running" | "done" | "failed" 之一
- `error`：可选字符串，状态为 "failed" 时的错误信息
- `evidence`：可选任意类型，capability 执行返回的结果

### Requirement: TestFeedbackAgent 将规划委托给 PlanningModule

`TestFeedbackAgent` 调用 `PlanningModule.create_plan()` 生成执行计划。`TestFeedbackAgent` 不得直接调用 `llm_client.plan()`。`PlanningModule` 实例必须对 Agent 可访问（通过属性或依赖注入）。

### Requirement: debug_robot_scenario.py 使用 PlanningModule 进行规划

`debug_robot_scenario.py` 必须使用 `PlanningModule.create_plan()` 生成计划，而不是构造内联提示词并以 `custom_prompt` 参数直接调用 `llm_client.plan()`。

### Requirement: PlanningModule 优雅处理 LLM 解析失败

当 `LLMClient.plan()` 返回空或无效计划时，`PlanningModule.create_plan()` 必须 fallback 到默认 pipeline：`["situation_analysis", "log_localization", "owner_identification", "feishu_notification"]`。Fallback 计划步骤以丰富步骤格式返回，包含 description、input、output_key、dependencies 的默认值，status="pending"。

### Requirement: 计划步骤顺序遵循依赖关系并在返回前修正

当 LLM 返回计划时，`PlanningModule.create_plan()` 必须重排步骤以满足：
1. 有依赖的步骤只在所有依赖完成后才执行
2. `owner_identification` 必须排在 `situation_analysis` 和 `log_localization` 之后（如果这些在计划中）——因为它需要它们产生的 `failed_module`
3. `feishu_notification` 必须排在 `owner_identification` 之后——因为它需要后者提供的 `owner_open_id`

检测到循环依赖时，保留未参与循环的步骤的原始 LLM 提供相对顺序。

#### Scenario: LLM 返回部分计划
- **WHEN** LLM 返回 `["situation_analysis", "log_localization"]`
- **THEN** `create_plan()` 返回带有正确设置 `dependencies` 的丰富步骤（situation_analysis 无依赖，log_localization 依赖 situation_analysis 完成后）

#### Scenario: LLM 返回包含未知步骤的计划
- **WHEN** LLM 返回 `["situation_analysis", "unknown_capability", "owner_identification"]`
- **THEN** `create_plan()` 过滤掉 `unknown_capability` 并只返回有效步骤及其正确的依赖关系

#### Scenario: LLM 返回空计划
- **WHEN** LLM 返回空列表或无有效步骤的列表
- **THEN** `create_plan()` 以丰富步骤格式返回默认 fallback 计划

#### Scenario: debug_robot_scenario.py 请求计划
- **WHEN** `debug_robot_scenario.py` 调用 `PlanningModule.create_plan()` 并传入 situation 和 failed_log
- **THEN** 返回的步骤为丰富格式，`debug_robot_scenario.py` 使用 `name` 字段遍历步骤

#### Scenario: LLM 返回步骤顺序违反依赖
- **WHEN** LLM 返回 `["owner_identification", "situation_analysis", "log_localization"]`
- **THEN** `create_plan()` 重排为 `["situation_analysis", "log_localization", "owner_identification"]`（`owner_identification` 始终在后两步之后）