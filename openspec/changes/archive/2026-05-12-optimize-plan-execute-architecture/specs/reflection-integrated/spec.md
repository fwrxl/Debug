## ADDED Requirements

### Requirement: 所有 capability 步骤完成后调用 ReflectionModule.summarize()

`ExecutionModule` 完成所有计划步骤（包括自动链路步骤）的执行后，必须调用一次 `ReflectionModule.summarize(situation, findings, steps)`，并将结果附加到执行结果中 key 为 `"reflection_report"` 的位置。

`situation` 参数是原始输入的 situation dict。`findings` 参数是从所有计划步骤的 non-null `evidence` 规范化的 findings 列表。`steps` 参数是带最终 `status` 和 `evidence` 的计划步骤列表。

**关于当前 ReflectionModule 行为的重要说明：** 现有 `ReflectionModule.summarize()`（位于 `agent/reflection/reflector.py`）从包含 `type="bug_location"`、`module`、`description`、`owner` 字段的 findings 中提取信息。Capability 返回的 evidence dict（如 `{"error_type": ..., "failed_module": ..., ...}`）**不包含** `type` 字段。Executor **必须**在调用 `summarize()` 之前将 findings 规范化为以下格式：对于每个包含 `failed_module` 的 evidence，构造 `{"type": "bug_location", "module": <failed_module>, "description": <root_cause or bug_hint or error_type>, "owner": null}` 并添加到传递给 `summarize()` 的 findings 列表中。

### Requirement: ReflectionModule 生成确定性诊断报告

`summarize()` 从 `findings` 中提取：
- `bug_module`：从任何包含 `failed_module` 或 `bug_module` 的 finding
- `error_type`：从任何包含 `error_type` 的 finding
- `root_cause`：从任何包含 `root_cause` 的 finding

返回的报告 dict 包含：
- `summary`：dict，包含 `situation`、`bug_module`、`bug_description`、`owner`、`findings_count`、`steps_executed` — 与当前 `ReflectionModule.summarize()` 输出结构完全匹配
- `findings`：输入的 findings 列表
- `steps`：输入的 steps 列表
- `recommendation`：由 `_generate_recommendation(bug_module, owner)` 生成的字符串

### Requirement: ReflectionModule.format_report() 生成人类可读输出

`ReflectionModule.format_report(summary)` 返回包含以下内容的格式化字符串报告：
- Bug 模块和描述
- 根本原因
- 负责人（如找到）
- 执行的步骤及其结果

#### Scenario: ReflectionModule 收到空 findings
- **WHEN** `findings` 是空列表（所有 capabilities 返回无 evidence）
- **THEN** `summarize()` 返回 `bug_module=null` 且 `"recommendation": "未能定位到具体 bug，建议人工介入分析"` 的报告

#### Scenario: ReflectionModule 生成建议
- **WHEN** `bug_module="intent_classifier"` 且 `owner="李四"`
- **THEN** `recommendation` 为 `"建议联系 李四 修复 intent_classifier 模块的问题"`

#### Scenario: Reflection report 附加到执行结果
- **WHEN** `ExecutionModule.execute_plan()` 完成所有步骤
- **THEN** 返回的 dict 包含 `"reflection_report"`，带有 `ReflectionModule.summarize()` 的完整 summary