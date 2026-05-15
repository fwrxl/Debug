## Context

TestFeedbackAgent 当前实现了 Plan-and-Execute 模式，但存在以下几个结构性问题：

- `PlanningModule` 位于 `agent/planning/planner.py` 但从未被调用——规划是通过 debug 脚本中的 `LLMClient.plan()` 内联完成的
- `ExecutionModule` 位于 `agent/execution/executor.py` 但不是主要的执行路径——`TestFeedbackAgent` 直接调用 capabilities
- `ReflectionModule` 定义在 `agent/reflection/reflector.py` 但从未在执行流程中被调用
- LLM 规划提示词存在于两处：`LLMClient._build_plan_prompt()` 和 `debug_robot_scenario.py` 中的内联定义，导致行为不一致
- 自动链路规则（自动运行 `owner_identification` / `feishu_notification`）在 `test_feedback_agent.py` 和 `debug_robot_scenario.py` 中重复
- `module_execution` capability 定义了但未在 `TestFeedbackAgent.capabilities` 中注册
- Memory 读写是隐式的——capabilities 写入 `memory.iteration.attempts`，但 `bug_module` 和 `owner_open_id` 通过 `memory.get_context()` 调用读取，而 `MemoryModule` 实际上没有这个方法，导致状态流动不可预测

**约束条件：**
- 不能删除或重写现有业务代码
- 必须在现有模块基础上增量工作
- 不能将其改造为完全不同的架构（如 Memory-driven Agentic Loop）
- 每个变更必须可独立测试和回滚

## Goals / Non-Goals

**Goals:**
- 以 `PlanningModule` 为唯一规划入口，替换所有内联 LLM 规划调用
- 将 LLM 提示词构造统一到 `LLMClient._build_plan_prompt()`
- 赋予每个计划步骤丰富的结构化元数据
- 使 `ExecutionModule` 成为驱动所有 capabilities 并管理步骤生命周期的统一执行引擎
- 建立 Memory 读写契约，使状态流动可预测
- 将 `ReflectionModule` 集成为后置执行的诊断报告生成器
- 解决 `module_execution` 的模糊状态（注册或禁用）
- 通过具体策略修复 `emqx_client` 负责人查找失败问题
- 将自动链路规则集中在 Executor 中

**Non-Goals:**
- 将 agent 重构为纯 memory-driven loop
- 删除任何现有的 capability 实现
- 完全重写 `debug_robot_scenario.py`（可以增量更新）
- 更换 LLM 客户端库（OpenAI 兼容客户端即可）

## Decisions

### Decision 1: Planner 集成 — Agent 调用 PlanningModule，而非直接调用 LLMClient

**方案：** `TestFeedbackAgent.run()` 委托给 `PlanningModule.create_plan()`，后者内部调用 `LLMClient.plan()`。Agent 永不直接调用 `llm_client.plan()`。`TestFeedbackAgent` 还拥有 `self.planner` 属性指向 `PlanningModule` 实例。

**当前状态：** `PlanningModule.create_plan()` 存在于 `agent/planning/planner.py`，返回 `List[str]`（步骤名列表）。它未被 `TestFeedbackAgent` 调用——该代码路径从未被接入。

**变更内容：** `create_plan()` signature 保持不变（接收 `situation, failed_log`），但现在内部传递 `available_steps`（所有注册的 capabilities）给 `LLMClient.plan()`，并将返回的字符串列表转换为带丰富元数据的步骤字典后返回。提供 `get_step_names()` 辅助方法以备向后兼容。

**决策理由：** 这将所有规划逻辑封装在 `PlanningModule` 中。如果需要改变计划生成方式（添加验证、后处理、回退策略），只需修改 `PlanningModule`。当前 `TestFeedbackAgent` 直接调用 `llm_client.plan()`，完全绕过了 planner。

**备选方案考虑：**
- 保持 Agent 直接调用 `LLMClient.plan()` 并添加包装器——不能解决"planner 存在但未使用"的问题
- 创建新的 `AgentPlanner` 类——当 `PlanningModule` 已存在时添加不必要的间接层

### Decision 2: 单一 LLM 提示词来源 — 移除 debug 脚本中的内联提示词

**方案：** `debug_robot_scenario.py` 使用 `PlanningModule.create_plan()`（内部调用 `LLMClient._build_plan_prompt()`）来生成计划，而不是自行构造内联提示词并以 `custom_prompt` 参数调用 `llm_client.plan()`。

**决策理由：** 当前 `debug_robot_scenario.py` 构造自定义提示字符串并以 `custom_prompt` 传给 `llm_client.plan()`。这重复了 capability 描述和决策规则，容易产生偏差。单一提示词来源意味着一个更新点、一种行为可测试。

**备选方案考虑：**
- 保留两个提示词并添加测试验证它们产生相同输出——增加维护负担
- 完全移除 `custom_prompt` 参数——破坏现有 debug 脚本，步子迈得太大

### Decision 3: PlanStep 数据结构

**方案：** 计划列表中的每个步骤变为包含以下字段的字典：
```python
{
    "name": str,              # 例如 "situation_analysis"
    "description": str,       # 例如 "分析测试失败的情景"
    "input": Dict[str, Any],  # 该步骤需要从 memory/context 获取的内容
    "output_key": str,         # 结果存储在 memory 中的 key（例如 "situation_result"）
    "dependencies": List[str], # 必须在此步骤之前完成的步骤名列表
    "status": str,             # "pending" | "running" | "done" | "failed"
    "error": Optional[str],     # 失败时的错误信息
    "evidence": Optional[Any],  # capability 执行返回的结果
}
```

**决策理由：** 当前计划只是步骤名字符串列表。缺乏 Executor 需要了解步骤需要什么、产生什么、如何跟踪状态的元数据。丰富的步骤对象使 Executor 能够管理依赖、确定性存储结果、优雅处理失败。

**备选方案考虑：**
- 使用 Pydantic 类——增加依赖且更刚性；普通 dict 对此用例足够灵活
- 所有内容存在 Memory 中——会使 Executor 紧耦合到 Memory 结构；将步骤元数据与计划放在一起更可移植

### Decision 4: ExecutionModule 成为统一的 Executor

**方案：** `ExecutionModule.execute_plan()` 驱动完整的 capability 执行循环：
1. 按依赖顺序遍历计划中的每个步骤，调用 capability
2. 将结果以步骤名为 key 存储在 `memory.iteration.attempts`
3. 每个步骤完成后检查自动链路规则
4. 所有步骤完成后调用 `ReflectionModule.summarize()` 生成最终报告
5. 返回包含 reflection report 的完整结果字典

**决策理由：** 当前 `TestFeedbackAgent.run()` 在内部实现执行循环。将此逻辑移入 `ExecutionModule` 将所有执行关注点（调用 capabilities、自动链路、结果存储）集中在一处。`TestFeedbackAgent` 成为委托给 `ExecutionModule` 的薄 facade。

**备选方案考虑：**
- 保持执行在 `TestFeedbackAgent` 中并只在末尾添加 `ReflectionModule` 调用——不能解决"分散的自动链路逻辑"问题
- 创建新的 `CapabilityRunner` 类——当 `ExecutionModule` 已存在且为此设计时添加新概念

### Decision 5: Memory 读写契约

**方案：** 建立以下规则：
- **新增方法（将在 MemoryModule 中添加）：**
  - `set_bug_module(module_name: str)` — 将 `bug_module` 存入 `memory.context`，同时写入最近一次 attempt 的 evidence 供自动链路查找
  - `get_bug_module() -> Optional[str]` — 从 context 读取
  - `set_owner_open_id(open_id: str)` — 将 `owner_open_id` 存入 `memory.context`
  - `get_owner_open_id() -> Optional[str]` — 从 context 读取
  - `get_latest_attempt(step_name: str) -> Optional[Dict]` — 从 `memory.iteration.attempts` 返回某步骤的最新一次 attempt
- **写入规则：**
  - `situation_analysis` 结果 → `memory.iteration.attempts["situation_analysis"]["evidence"]`
  - `log_localization` 结果 → `memory.iteration.attempts["log_localization"]["evidence"]`
  - `owner_identification` 在填充结果后调用 `memory.set_bug_module()` 和 `memory.set_owner_open_id()`
  - `feishu_notification` 将 `message_sent`、`message_id` 写入 attempt evidence
- **读取规则（用于自动链路）：**
  - `owner_identification` 的自动链路：从 `memory.iteration.get_latest_attempt("log_localization")["evidence"]["failed_module"]` 读取
  - `feishu_notification` 的自动链路：从 `memory.get_owner_open_id()` 读取
  - Planner 从 `memory.iteration.attempts` 读取先前结果以构建上下文

**决策理由：** 当前 `memory.get_context("bug_module")` 在 `test_feedback_agent.py` 中被调用，但 `MemoryModule` 中没有 `get_context()` 方法。状态流动不可预测。明确的读写契约使数据流动具有确定性和可测试性。

**备选方案考虑：**
- 添加正式的 `MemoryStore` 类和类型化 getter/setter——更健壮但增加复杂度；对此项目 dict 类型的契约足够
- 所有状态存入 `memory.context`——更简单但混淆了步骤结果和运行时状态；将 attempts 分开更清晰

### Decision 6: ReflectionModule 集成

**方案：** `ExecutionModule.execute_plan()` 在所有 capability 步骤（包括自动链路步骤）执行完成后调用 `ReflectionModule.summarize(situation, findings, steps)`，将结果附加到执行结果中 key 为 `"reflection_report"` 的位置。

**重要说明：** 现有 `ReflectionModule.summarize()` 从包含 `type="bug_location"` 和 `module`/`description`/`owner` 字段的 findings 中提取信息。Capability 返回的 evidence dict（如 `{"error_type": ..., "failed_module": ..., ...}`）不包含 `type` 字段。Executor 在调用 `summarize()` 之前必须将 findings 规范化为以下格式：对于每个包含 `failed_module` 或 `bug_module` 的 evidence，构造 `{"type": "bug_location", "module": <module>, "description": <root_cause or bug_hint or error_type>, "owner": null}` 并添加到传递给 `summarize()` 的 findings 列表中。

**决策理由：** `ReflectionModule` 已存在并有 `summarize()` 和 `format_report()` 方法。当前从未被调用。在执行流程末尾集成它将分散的 debug-print 汇总变为结构化、可复用的报告。

**备选方案考虑：**
- 保持汇总打印在 `debug_robot_scenario.py` 中——维持现状，不使用 ReflectionModule
- 让每个 capability 追加到共享报告——破坏关注点分离；ReflectionModule 应该拥有报告职责

### Decision 7: module_execution 状态解决

**方案：** 在 `TestFeedbackAgent.capabilities` 中注册 `module_execution`，使其与其他四个 capability 同为一线成员。其 `execute()` 方法保持不变。

**决策理由：** 该 capability 存在，有定义的用途（启发式模块验证），但未注册。注册它使 capability 系统一致——所有定义的 capability 均可被发现。如果实践中不应使用，由 Planner 决定不将其纳入计划，这是正确的抽象。

**备选方案考虑：**
- 删除该 capability——违反"不删除业务代码"
- 在配置中标记为"disabled"——添加特殊处理；如果它被定义，就应该是可用的

### Decision 8: emqx_client 负责人查找修复

**方案：** 从 `LogLocator._analyze_log()` 的 `module_components` 字典中移除 `emqx_client`，使 LLM 永远不会将其输出为 `failed_module`。这从根本上消除了问题——无需查询 xlsx。

**决策理由：** `log_localization` 之所以能输出 `emqx_client`，是因为它在提示词的 valid module 列表中。由于 `emqx_client` 不是 pipeline 模块而是通信层，不应被视为独立的 bug 模块。从提示词中移除它从根源上防止了问题，比 alias mapping 或 xlsx 添加更简洁。

**备选方案考虑：**
- 添加 `emqx_client` 到 xlsx 并附占位符 owner——可行但需要维护数据条目
- 在 `ModuleOwnerTable` 中添加 alias mapping——增加复杂度；当模块永远不会被输出时没有必要
- 不做处理——让 bug 持续存在

### Decision 9: 自动链路规则集中化

**方案：** 自动链路逻辑作为显式的后置步骤检查存在于 `ExecutionModule.execute_plan()` 中：
1. 任何步骤设置了 `evidence["failed_module"]` 或 `evidence["bug_module"]` 后，检查 `owner_identification` 是否已运行；如未运行且找到了模块，自动运行它
2. `owner_identification` 后，如设置了 `evidence["owner_info"]["open_id"]` 且 `feishu_notification` 未运行，自动运行它

**决策理由：** 这用单一、可测试的位置替换了 `test_feedback_agent.py` 和 `debug_robot_scenario.py` 中分散的自动链路代码。规则是显式和确定性的。

**备选方案考虑：**
- 将自动链路放在 `PlanningModule`——规划是错误的执行决策阶段
- 使用事件/回调——对这个用例过度设计；简单条件检查足够

## Risks / Trade-offs

- **[Risk]** `memory.get_context()` 在当前 `MemoryModule` 中不存在——spec 新增了辅助方法 `set_bug_module`、`get_bug_module`、`set_owner_open_id`、`get_owner_open_id`、`get_latest_attempt`
  → **缓解措施：** 任务 3.x 明确添加这些为新方法；调用 `memory.get_context("owner_open_id")` 的现有代码（如 `test_feedback_agent.py:100`）将更新为使用新辅助方法

- **[Risk]** `PlanningModule.create_plan()` 当前返回 `List[str]`；改为返回 `List[PlanStep]` 对任何调用它的代码是破坏性变更
  → **缓解措施：** 添加迁移路径——`create_plan()` 可以返回带丰富步骤的结果，只需要步骤名的现有调用方使用辅助方法提取

- **[Risk]** `module_execution` capability 具有基于启发式的逻辑，可能误识别模块
  → **缓解措施：** 它被注册但 Planner 不强制包含它；只在计划显式调用时才调用

- **[Trade-off]** 将自动链路集中在 Executor 中意味着 `debug_robot_scenario.py` 失去其内联自动链路——必须使用 `ExecutionModule` 才能获得该行为
  → **缓解措施：** `debug_robot_scenario.py` 可以更新为使用 `ExecutionModule.execute_plan()` 而不是手动 capability 循环，或者自动链路可以作为两者都可调用的工具函数保留

## Migration Plan

**Phase 1（任务 1）：Foundation — Prompt 和 Planner**
1. 更新 `PlanningModule.create_plan()` 内部调用 `LLMClient.plan()`；实现 `_enrich_step()` 辅助方法；返回 `List[Dict]`；实现自己的 fallback；添加依赖顺序修正

**Phase 2（任务 2-3）：执行集中化**
2. 更新 `ExecutionModule.execute_plan()` 实现自动链路规则；调用 `ReflectionModule.summarize()`
3. 在 `MemoryModule` 中添加读写辅助方法

**Phase 3（任务 4-5）：集成和状态解决**
4. 注册 `module_execution` 到 `TestFeedbackAgent.capabilities`
5. 从 `LogLocator._analyze_log()` 提示词中移除 `emqx_client`

**Phase 4（任务 6）：Reflection 和 Reporting**
6. 将 `ReflectionModule.summarize()` 集成到 `ExecutionModule.execute_plan()` 作为最后步骤

**Phase 5（任务 7）：Tests**
7. 为每个 phase 添加单元测试；验证向后兼容性

每个 phase 可独立测试。可通过回滚每个 phase 更改的文件来回滚。

## Open Questions

1. **`debug_robot_scenario.py` 是否应重构为使用 `ExecutionModule`？** 设计假设它将更新为使用 `ExecutionModule`，但如果有理由保持独立，自动链路逻辑需要在那里重复

2. **`PlanningModule` 是否应支持计划验证？** 例如确保所有依赖都在计划中。当前如果 LLM 产生包含某步骤依赖但该依赖不在计划中的计划，Executor 会失败。验证步骤可以捕获此问题（注意：任务 1.5 添加了顺序修正，部分解决了此问题）