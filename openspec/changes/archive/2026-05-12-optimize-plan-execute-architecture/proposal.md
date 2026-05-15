## Why

现有 TestFeedbackAgent 实现了 Plan-and-Execute 模式，但实现是碎片化的：`PlanningModule` 存在但未被使用，`Executor` 与 Agent 直接执行并存，自动链路逻辑分散在 debug 脚本和 Agent 代码中，LLM 规划提示词在两处重复且不一致。这使得系统难以维护、测试和理解。

## What Changes

- **统一 Planner 使用方式**：`TestFeedbackAgent` 通过 `LLMClient` 调用 `PlanningModule.create_plan()`，而不是绕过它
- **统一 LLM 规划提示词**：`LLMClient._build_plan_prompt()` 是提示词的唯一来源，移除 debug 脚本中的内联提示词
- **丰富 Plan 和 PlanStep 结构**：每个计划步骤包含 `name`、`description`、`input`、`dependencies`、`status`、`error`、`evidence` 等字段
- **强化 Executor**：`agent/execution/executor.py` 成为统一的执行入口，负责逐步执行 capability、记录状态、处理失败、保存结果
- **统一 Memory 读写规则**：明确 `bug_module`、`owner_open_id`、`analysis_result`、`log_result` 等上下文信息的写入和读取位置
- **集成 ReflectionModule**：`agent/reflection/reflector.py` 在所有 capability 执行完成后由 Executor 调用，负责生成最终诊断报告
- **明确 module_execution capability**：正式注册到 capabilities 或标记为暂不启用，不再处于"已定义但未集成"的模糊状态
- **集中化自动链路规则**：`owner_identification` 和 `feishu_notification` 的自动触发规则统一放在 Planner 或 Executor 的规则中，不再分散在多个文件
- **修复 emqx_client 模块负责人匹配问题**：从 `LogLocator` 的提示词中移除 `emqx_client`，使其不会被输出为 `failed_module`
- **增加测试覆盖**：为 `Planner`、`Executor`、`Memory`、`Reflection`、capabilities 注册、owner 识别失败降级等场景添加单元测试

## Capabilities

### New Capabilities
- `planner-unified`：标准化 `PlanningModule` 的调用方式和 LLM 提示词的构造方式
- `executor-standardized`：使 `ExecutionModule` 成为统一的执行引擎，具备统一的步骤状态管理和结果存储
- `memory-contract`：定义上下文数据（`bug_module`、`owner_open_id` 等）的读写契约，使状态流动可预测
- `reflection-integrated`：将 `ReflectionModule.summarize()` 接入执行流程，作为最终的诊断报告生成器
- `module-execution-resolved`：将 `module_execution` 注册到 capabilities 注册表，或明确标记为暂不启用
- `owner-lookup-fix`：确保 `log_localization` 输出的 `failed_module` 始终能在 `module_owner_mapping.xlsx` 中找到对应的负责人

### Modified Capabilities
<!-- 当前没有需要修改 Requirement 的已有 spec，所有都是新增 -->

## Impact

- `agent/test_feedback_agent.py`：委托规划给 `PlanningModule`，委托执行给 `ExecutionModule`；自动链路逻辑移至 Executor
- `agent/planning/planner.py`：接收由 LLM 驱动的带完整元数据的计划步骤；`create_plan()` signature 可能改变
- `agent/execution/executor.py`：成为主要的执行驱动器；当前利用率不足
- `agent/reflection/reflector.py`：当前未使用；将在执行完成后被调用以生成报告
- `integrations/llm_client.py`：`_build_plan_prompt()` 成为唯一的提示词来源；可能需要更丰富的步骤元数据
- `capabilities/log_localization/locator.py`：从 `_analyze_log()` 的 `module_components` 中移除 `emqx_client`
- `capabilities/module_execution/executor.py`：注册到 `TestFeedbackAgent.capabilities`
- 新增测试文件：`tests/unit/test_planner.py`、`tests/unit/test_executor.py`、`tests/unit/test_memory_contract.py`、`tests/unit/test_reflection.py`