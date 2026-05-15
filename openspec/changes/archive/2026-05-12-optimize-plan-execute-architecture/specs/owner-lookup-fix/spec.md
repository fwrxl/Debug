## ADDED Requirements

### Requirement: log_localization 仅输出已知有效模块 ID

`LogLocator._analyze_log()` 确保其返回 evidence 中的 `failed_module` 是以下已知有效模块 ID 之一：`rejection_classifier`、`intent_classifier`、`instruction_rewriter`、`command_store`、`parameter_extractor`、`protocol_builder`。必须从提示词的 `module_components` 字典中移除 `emqx_client` 条目，使 LLM 不会将其输出。

**实现说明：** 要从 log_localization 提示词中移除 `emqx_client`，需要修改 `LogLocator._analyze_log()`（locator.py 第 52-59 行附近）中用于构建提示词的 `module_components` 字典，删除其中的 `emqx_client` 条目。

### Requirement: owner_identification 优雅处理找不到负责人的情况

当 `owner_identification` 调用 `_get_owner(bug_module)` 结果为 `None` 时，它必须：
1. 将 `has_owner` 设为 `false`，`owner_info` 设为 `null`
2. 不抛出异常；capability 正常执行完成但报告未找到负责人

结果 dict 必须始终包含 `bug_module`、`owner_info` 和 `has_owner` 字段。

#### Scenario: log_localization 输出有效模块
- **WHEN** `log_localization` 返回 `evidence={"failed_module": "intent_classifier", ...}`
- **THEN** `owner_identification` 调用 `ModuleOwnerTable.get_owner("intent_classifier")` 并返回正确的负责人

#### Scenario: log_localization 输出 emqx_client
- **WHEN** `log_localization` 返回 `evidence={"failed_module": "emqx_client", ...}`
- **THEN** `emqx_client` 不在提示词的有效模块列表中，因此此场景不会发生

#### Scenario: owner_identification 处理找不到负责人的情况
- **WHEN** `log_localization` 返回的 `failed_module` 不在 xlsx 中
- **THEN** `owner_identification` 返回 `{"bug_module": <module>, "owner_info": null, "has_owner": false}`，不抛出异常