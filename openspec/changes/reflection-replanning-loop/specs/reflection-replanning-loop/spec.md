# Reflection-Replanning-Loop Spec

## Schema
spec-driven

## ADDED Requirements

### Requirement: situation_analysis Global Single Execution

**situation_analysis 是全局 capability**：
- 只在分支外执行一次
- 为整个分析流程提供初始候选模块列表
- 不在分支内执行

**输出结构**：

situation_analysis 输出包含 `candidate_modules` 列表：

```json
{
  "command": "往前走",
  "expected_action": "机器人向前移动",
  "unexpected_incident": "机器人没有反应",
  "candidate_modules": [
    {"module": "intent_classifier", "initial_confidence": 0.75},
    {"module": "parameter_extractor", "initial_confidence": 0.45}
  ],
  "bug_hint": "意图分类裁决逻辑可能存在问题"
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| command | string | 是 | 用户下达的具体指令 |
| expected_action | string | 是 | 期望的系统行为 |
| unexpected_incident | string | 是 | 实际发生的意外情况 |
| candidate_modules | list | 是 | 候选模块列表 |
| candidate_modules[].module | string | 是 | 模块名称，必须在有效列表中 |
| candidate_modules[].initial_confidence | float | 是 | 初始置信度，范围 0.0-1.0 |
| bug_hint | string | 否 | 基于情景分析的 bug 线索提示 |

**约束**：
- candidate_modules 每个元素**只**包含 `module` 和 `initial_confidence`
- **不包含** `reason`、`evidence`、`source` 字段
- **不包含** `possible_modules` 旧格式

**有效模块列表**：
```
rejection_classifier, intent_classifier, instruction_rewriter,
command_store, parameter_extractor, protocol_builder
```

**注意**：emqx_client 不在有效模块列表中，不能作为 candidate_module。

### Requirement: Branch Execution Without situation_analysis

**Branch 执行规则**：
- 每个 branch 基于一个 candidate_module 创建
- branch 内**不允许**执行 situation_analysis
- branch 内执行 diagnostic capabilities 来验证当前 candidate_module

**Branch 内允许执行的 capabilities**：

| Capability | 作用 |
|-----------|------|
| log_localization | 针对 candidate_module 分析日志证据 |
| module_execution | 针对 candidate_module 验证可疑性 |
| code_localization | 针对 candidate_module 检查代码证据（如果存在） |

**Branch 内不允许执行的 capabilities**：

| Capability | 原因 |
|-----------|------|
| situation_analysis | 已在全局执行完毕 |
| owner_identification | 属于 finalization |
| feishu_notification | 属于 finalization |

### Requirement: Confidence Delta Output

**Branch 内 capability 输出要求**：

每个 capability 必须输出对 candidate_module 的置信度贡献：

#### log_localization 输出

```json
{
  "candidate_module": "intent_classifier",
  "log_supports_candidate": true,
  "confidence_delta": 0.20,
  "evidence_score": 0.75,
  "related_log_snippets": ["[IntentEnsemble] 裁决失败: intent=2 conf=0.42"],
  "reasons": ["日志证据支持该模块"]
}
```

#### module_execution 输出

```json
{
  "candidate_module": "intent_classifier",
  "execution_supports_candidate": true,
  "confidence_delta": 0.25,
  "evidence_score": 0.80,
  "suspicious": true,
  "reasons": ["模块验证发现异常"]
}
```

**必需字段**：
- `confidence_delta` 或 `evidence_score`（二选一或同时）
- `log_supports_candidate` 或 `execution_supports_candidate`（bool）

### Requirement: Confidence Accumulation Model

**置信度累积公式**：

```
final_confidence = initial_confidence
                 + log_localization_delta
                 + module_execution_delta
                 + code_localization_delta
                 + reflection_adjustment

限制在 0.0 到 1.0 范围内
```

**调整规则示例**：

| 能力结果 | Delta 范围 |
|---------|-----------|
| log_localization 明确支持当前模块 | +0.15 ~ +0.25 |
| log_localization 明确反驳当前模块 | -0.20 ~ -0.30 |
| module_execution 验证当前模块可疑 | +0.20 ~ +0.30 |
| module_execution 未发现异常 | -0.15 ~ -0.25 |

**约束**：
- 单一来源惩罚：只有单一 capability 提供置信度提升时，最终置信度需要打折
- 有效模块限制：candidate_module 不在有效列表时，最终置信度不能超过 0.5

### Requirement: Reflection as Confidence Calibration

**ReflectionModule.reflect() 职责**：
- 读取 branch memory 中的 initial_confidence
- 读取 branch memory 中的 confidence_updates（各能力的 delta）
- 综合计算 final_confidence
- 判断 proceed / replan / stop

**Decision 阈值**：

| Confidence | Decision |
|------------|----------|
| >= 0.7 | `proceed` |
| 0.4-0.7 | `replan` |
| < 0.4 | `stop` |

**reflect() 输出**：

```python
{
    "decision": "proceed",
    "confidence": 0.85,
    "final_confidence": 0.85,
    "initial_confidence": 0.75,
    "confidence_updates": [
        {"source": "log_localization", "delta": 0.15, "evidence_score": 0.75},
        {"source": "module_execution", "delta": -0.05, "evidence_score": 0.70}
    ],
    "excluded": False,
    "evidence_chain": [...],
    "reasons": [...],
    "summary": "..."
}
```

### Requirement: BranchResult with Confidence Updates

```python
@dataclass
class BranchResult:
    module: str                           # 该分支负责验证的模块
    initial_confidence: float             # situation_analysis 给出的初始置信度
    confidence_updates: List[Dict]        # 各能力的置信度贡献
        # 每项包含: source, delta 或 evidence_score, reason, evidence
    final_confidence: float              # 累积后的最终置信度
    excluded: bool                       # 是否被排除
    decision: str                        # proceed / replan / stop
    evidence_chain: List[Dict]           # 证据链
    reflection_summary: str               # 反思总结
    verification_result: Dict            # 验证结果详情
```

### Requirement: merge_and_sort_results with Confidence Priority

**排序原则**：
1. 排除 excluded=True 的分支
2. 优先 final_confidence 高的分支
3. final_confidence 相近时，优先 evidence 多的分支
4. 最高分 < 0.7 时不 proceed

**merge_and_sort_results 输出**：

```python
{
    "root_module": "intent_classifier",
    "confidence": "HIGH",
    "confidence_score": 0.85,
    "final_decision": "proceed",
    "branch_results": [...],
    "total_branches": 3,
    "total_reflection_count": 3
}
```

### Requirement: Finalization Execution Constraints

**执行条件**：
- final_decision = "proceed"
- confidence_score >= 0.7
- root_module 在有效模块列表中
- root_module 有负责人映射

**执行顺序**：
```
final_decision = proceed
        ↓
set_final_bug_module(root_module)
        ↓
owner_identification(root_module)
        ↓
set_owner_open_id(owner_info.open_id)
        ↓
feishu_notification(root_module, owner_info)
```

**约束**：
- owner_identification 只在 final_decision 后执行
- feishu_notification 只在 owner_identification 后执行
- 分支内不允许执行 owner_identification 或 feishu_notification
- 不允许多个分支分别通知多个负责人

### Requirement: Memory Storage Boundaries

**全局 Memory (Agent.memory)**：

| 数据 | 存储位置 |
|------|---------|
| situation_analysis 结果 | iteration.attempts |
| final_decision | context.conversation |
| root_module | _bug_module |
| owner_info | _owner_open_id |
| feishu_notification 结果 | iteration.attempts |

**分支 Memory (每个 branch_memory)**：

| 数据 | 存储位置 |
|------|---------|
| candidate_module | branch_memory._candidate_module |
| initial_confidence | branch_memory._initial_confidence |
| log_localization 结果 | iteration.attempts |
| module_execution 结果 | iteration.attempts |
| code_localization 结果 | iteration.attempts（如果存在） |
| reflection 结果 | context.conversation |

---

## Scenarios

### Scenario: situation_analysis 输出多个候选模块
- **WHEN** situation_analysis 返回 `candidate_modules: [{module: a, init: 0.75}, {module: b, init: 0.45}]`
- **THEN** 创建 Branch 1 验证 module=a，Branch 2 验证 module=b

### Scenario: Branch 1 置信度累积后达到 proceed
- **WHEN** Branch 1: initial_confidence=0.75, log_localization_delta=+0.15, module_execution_delta=-0.05
- **THEN** final_confidence = 0.75 + 0.15 - 0.05 = 0.85
- **THEN** decision = proceed

### Scenario: Branch 2 置信度累积后仍为 replan
- **WHEN** Branch 2: initial_confidence=0.45, log_localization_delta=-0.30, module_execution_delta=0.0
- **THEN** final_confidence = 0.45 - 0.30 = 0.15
- **THEN** decision = stop

### Scenario: 所有分支都排除或低置信度
- **WHEN** 所有分支的 excluded=True 或 final_confidence < 0.4
- **THEN** merge_and_sort_results 返回 stop decision
- **THEN** 不发送通知

### Scenario: confidence < 0.7 阈值保护
- **WHEN** merge_and_sort_results 最高分 final_confidence = 0.65
- **THEN** final_decision = replan（而非 proceed）
- **THEN** Planner 生成补充计划

### Scenario: 无 candidate_modules
- **WHEN** situation_analysis 返回空的 candidate_modules
- **THEN** 输出 low-confidence final report，不执行分支

---

## 接口对齐说明

| Spec 中使用的名称 | 说明 |
|-----------------|------|
| `candidate_modules` | 本次新增，situation_analysis 输出结构 |
| `candidate_modules[].module` | 本次新增，模块名字符串 |
| `candidate_modules[].initial_confidence` | 本次新增，初始置信度 0.0-1.0 |
| `confidence_delta` | 本次新增，capability 对置信度的贡献 |
| `confidence_updates` | 本次新增，置信度更新列表 |
| `branch_memory._candidate_module` | 本次新增 |
| `branch_memory._initial_confidence` | 本次新增 |
| `ReflectionModule.reflect()` | 本次增强，新增 final_confidence 和 confidence_updates 输出 |
| `BranchResult.initial_confidence` | 本次新增 |
| `BranchResult.confidence_updates` | 本次新增 |
| `BranchResult.final_confidence` | 本次新增（替代旧的 confidence 字段语义） |
| `merge_and_sort_results()` | 本次调整，排序基于 final_confidence |

如实际接口与此 spec 不一致，应以实际代码为准，在实现阶段修正 spec。
