## 1. Foundation — 统一 Planner 和 Prompt

- [x] 1.1 更新 `PlanningModule.create_plan()` 内部调用 `LLMClient.plan(situation, failed_log, available_steps)`，其中 `available_steps` = 所有注册的 capabilities（包括后续任务 4 中注册的 module_execution）；`PlanningModule` 现在是 `LLMClient.plan()` 的唯一调用方
- [x] 1.2 添加辅助方法 `PlanningModule._enrich_step(step_name: str, step_index: int)`，将步骤名字符串转换为带以下字段的丰富步骤字典：`name`、`description`（来自 capability docs）、`input`、`output_key`、`dependencies`、`status="pending"`、`error=null`、`evidence=null`
- [x] 1.3 更新 `PlanningModule.create_plan()` 返回 `List[Dict]`（丰富步骤）而非 `List[str]`；对 `LLMClient.plan()` 返回的每个步骤名应用 `_enrich_step()`；添加 `get_step_names(plan: List[Dict]) -> List[str]` 静态方法以备向后兼容
- [x] 1.4 实现 `PlanningModule.create_plan()` 自己的 fallback：当 `LLMClient.plan()` 返回空/无效计划时，不使用其内部 fallback `["owner_identification", "feishu_notification"]`；而是以丰富步骤格式返回完整的 4 步 fallback：`["situation_analysis", "log_localization", "owner_identification", "feishu_notification"]`
- [x] 1.5 在 `PlanningModule.create_plan()` 中添加依赖顺序验证： enrichment 后，如果任何步骤的 `dependencies` 不全在计划的步骤名中，移除无效的依赖引用；然后重排计划使 `situation_analysis` 和 `log_localization` 始终排在 `owner_identification` 之前（这两步必须在它之前）。`feishu_notification` 必须排在 `owner_identification` 之后。LLM 可以返回任意顺序，但 Executor 期望 `owner_identification` 在 `situation_analysis` 和 `log_localization` 之后运行，`feishu_notification` 在 `owner_identification` 之后运行
- [x] 1.6 更新 `debug_robot_scenario.py` 调用 `PlanningModule.create_plan(situation, failed_log)` 而不是自行构造内联提示词并调用 `llm_client.plan(custom_prompt=...)`；使用每个步骤字典的 `name` 字段遍历步骤
- [x] 1.7 移除 `debug_robot_scenario.py` 中的内联 `capability_descriptions` 变量和 `llm_input_prompt`——所有提示词构造都通过 `PlanningModule.create_plan()` 进行，后者调用 `LLMClient._build_plan_prompt()`

**验收标准：**
- 运行 `debug_robot_scenario.py`——输出计划应来自 `PlanningModule.create_plan()` 且步骤应带丰富字段
- `PlanningModule.create_plan()` 返回包含以下 key 的字典列表：name、description、input、output_key、dependencies、status、error、evidence
- `owner_identification` 在 `situation_analysis` 和 `log_localization` 之后
- `feishu_notification` 在 `owner_identification` 之后
- 当 LLM 返回空计划时，fallback 是完整的 4 步

## 2. ExecutionModule 作为统一 Executor

- [x] 2.1 更新 `ExecutionModule.execute_plan()` signature 接收 `plan_steps: List[Dict]`（丰富步骤）和 `memory: MemoryModule`
- [x] 2.2 在 `ExecutionModule.execute_plan()` 中实现步骤执行循环：遍历 `plan_steps`，调用 `capabilities[step["name"]].execute(situation, failed_log, memory)`，更新 `step["evidence"]` 和 `step["status"]`
- [x] 2.3 实现 `ExecutionModule._check_auto_chain(step_results, memory) -> List[str]`，检查自动链路条件并返回要执行的额外步骤名列表（无条件满足时为空列表）
- [x] 2.4 添加自动链路执行：当 `_check_auto_chain` 返回步骤时，将其追加到计划并在继续之前执行
- [x] 2.5 更新 `TestFeedbackAgent.__init__()` 创建并存储 `ExecutionModule` 实例；更新 `TestFeedbackAgent.run()` 委托给 `self.executor.execute_plan(situation, failed_log, plan_steps, self.memory)`

**验收标准：**
- `ExecutionModule.execute_plan()` 返回包含以下 key 的 dict：success、steps、auto_chained_steps、reflection_report、notification_sent、recipient
- 当 `log_localization` 找到 `failed_module` 时触发 `owner_identification` 的自动链路
- 当 `owner_identification` 提供 `open_id` 时触发 `feishu_notification` 的自动链路
- 如果步骤已在计划中则不会重复自动链路

## 3. Memory 读写契约

- [x] 3.1 添加 `MemoryModule.set_bug_module(module_name: str)` 和 `MemoryModule.get_bug_module() -> Optional[str]`
- [x] 3.2 添加 `MemoryModule.set_owner_open_id(open_id: str)` 和 `MemoryModule.get_owner_open_id() -> Optional[str]`
- [x] 3.3 添加 `MemoryModule.get_latest_attempt(step_name: str) -> Optional[Dict]`
- [x] 3.4 更新 `owner_identification` capability 在填充结果后调用 `memory.set_bug_module()` 和 `memory.set_owner_open_id()`
- [x] 3.5 确保 `ExecutionModule._check_auto_chain()` 从 `memory.iteration.get_latest_attempt("log_localization")["evidence"]["failed_module"]` 读取 `failed_module`，从 `memory.get_owner_open_id()` 读取 `owner_open_id`
- [x] 3.6 确保所有 capabilities 通过 `ExecutionModule`（而非直接从 capabilities）将结果写入 `memory.iteration.attempts`

**验收标准：**
- `memory.get_bug_module()` 返回最近一次 `set_bug_module()` 调用设置的值
- `memory.get_owner_open_id()` 返回 `owner_identification` 设置的值
- `memory.get_latest_attempt("log_localization")` 返回带有 evidence 的 log_localization attempt dict

## 4. ReflectionModule 集成

- [x] 4.1 在 `ExecutionModule.execute_plan()` 中添加 findings 规范化步骤：在调用 `summarize()` 之前，对每个步骤的 evidence 执行规范化——对于每个包含 `failed_module` 的 evidence，构造规范化的 finding dict：`{"type": "bug_location", "module": <failed_module>, "description": <root_cause or bug_hint or error_type>, "owner": null}`，并将其添加到传递给 `summarize()` 的 findings 列表
- [x] 4.2 将 `ReflectionModule.summarize()` 结果附加到执行结果 dict 的 key `"reflection_report"` 下
- [x] 4.3 验证 `debug_robot_scenario.py` 从执行结果打印 reflection report

**验收标准：**
- 执行结果包含 `"reflection_report"` key，带有 `ReflectionModule.summarize()` 的完整 summary
- `reflection_report` 中的 `summary` 字段匹配当前 `ReflectionModule.summarize()` 输出结构（situation、bug_module、bug_description、owner、findings_count、steps_executed）

## 5. module_execution 状态解决

- [x] 5.1 将 `ModuleExecutor` 导入添加到 `agent/test_feedback_agent.py`
- [x] 5.2 在 `TestFeedbackAgent.__init__()` 中创建 `ModuleExecutor` 实例
- [x] 5.3 在 `TestFeedbackAgent.capabilities` dict 中注册 `module_execution`
- [x] 5.4 验证 `module_execution` 不出现在自动链路触发中（它只在计划中显式包含时才执行）

**验收标准：**
- `TestFeedbackAgent.capabilities` keys 包含 `module_execution`
- `ExecutionModule._check_auto_chain()` 中的自动链路规则只触发 `owner_identification` 和 `feishu_notification`
- 当计划包含 `module_execution` 时运行 `debug_robot_scenario.py` 会执行它

## 6. owner-lookup-fix — 从 log_localization 提示词中移除 emqx_client

- [x] 6.1 从 `LogLocator._analyze_log()` 提示词的 `module_components` 字典中移除 `emqx_client` 条目（locator.py 第 52-59 行附近），使 LLM 不会在 `failed_module` 的有效模块列表中包含它
- [x] 6.2 验证 `LogLocator` 在测试运行中不再输出 `emqx_client`

**验收标准：**
- `log_localization` capability 返回的 `failed_module` 仅来自：`rejection_classifier`、`intent_classifier`、`instruction_rewriter`、`command_store`、`parameter_extractor`、`protocol_builder`
- 运行 `debug_robot_scenario.py` 产生的 `failed_module` 存在于 `module_owner_mapping.xlsx` 中

## 7. 测试覆盖

- [x] 7.1 新增 `tests/unit/test_planner.py`：测试 `PlanningModule.create_plan()` 返回丰富步骤、对空 LLM 响应 fallback、过滤未知步骤、修正 `owner_identification` 顺序（它在 `situation_analysis`/`log_localization` 之后）、`feishu_notification` 在 `owner_identification` 之后
- [x] 7.2 新增 `tests/unit/test_executor.py`：用 mock `step_results` 和 `memory` 测试 `ExecutionModule._check_auto_chain()`；测试依赖顺序执行；测试自动链路不重复
- [x] 7.3 新增 `tests/unit/test_memory_contract.py`：测试 `set_bug_module/get_bug_module`、`set_owner_open_id/get_owner_open_id`、`get_latest_attempt`、`reset()`
- [x] 7.4 新增 `tests/unit/test_reflection.py`：测试 `ReflectionModule.summarize()` 对空/非空 findings；测试 `format_report()`
- [x] 7.5 新增 `tests/unit/test_owner_identifier.py`：测试模块不在 xlsx 时的降级（返回 `has_owner: false`）；测试 `log_localization` 不再输出 `emqx_client`
- [x] 7.6 新增 `tests/unit/test_capabilities_registration.py`：测试 `TestFeedbackAgent.capabilities` 包含全部 5 个 capabilities（situation_analysis、log_localization、module_execution、owner_identification、feishu_notification）

**验收标准：**
- 所有新测试通过 `python -m pytest tests/unit/ -v`
- 现有测试（`test_llm_client.py`、`test_feishu_client.py`）仍然通过