# Design: Reflection-Before-Notification Architecture

## 1. 架构概述

```
输入: situation + failed_log
        ↓
┌─────────────────────────────────────────────────────┐
│ 阶段 1: situation_analysis (全局，只执行一次)          │
│ - 分析情景描述、失败现象、整体日志                     │
│ - 输出候选模块列表，每个包含 initial_confidence        │
└─────────────────────────────────────────────────────┘
        ↓
candidate_modules: [{module, initial_confidence}, ...]
        ↓
┌─────────────────────────────────────────────────────┐
│ 阶段 2: 多分支并行验证                               │
│ - 为每个 candidate_module 创建独立 branch memory     │
│ - 各分支独立执行 diagnostic capabilities             │
│ - 各分支独立执行 Reflection                          │
└─────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────┐
│ 阶段 3: merge_and_sort_results                      │
│ - 按 final_confidence 排序                          │
│ - 选择最优分支作为 final_decision                    │
└─────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────┐
│ 阶段 4: Reflection Gate (Decision Gate)             │
│ - final_decision = proceed / replan / stop          │
└─────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────┐
│ 阶段 5: Finalization                                │
│ - proceed → owner_identification → feishu_notify    │
│ - replan → 补充执行 → 回到 Reflection Gate           │
│ - stop → 生成报告，不发送通知                        │
└─────────────────────────────────────────────────────┘
```

---

## 2. Confidence Accumulation Model

### 2.1 概述

置信度采用累积模型，而非单次覆盖模型。每个 candidate_module 的置信度变化如下：

```
final_confidence = initial_confidence
                 + Σ(confidence_delta from each capability)
                 + reflection_adjustment
```

### 2.2 初始置信度

`situation_analysis` 为每个 candidate_module 输出 `initial_confidence`（范围 0.0-1.0）。

这是该模块在全局分析层面的初始可信度。

### 2.3 分支内置信度调整

分支内每个 capability 根据其对 candidate_module 的验证结果，对置信度进行调整。

#### 调整规则

| Capability | 证据结果 | Delta 范围 | 说明 |
|------------|---------|-----------|------|
| log_localization | 支持当前模块 | +0.15 ~ +0.25 | 日志证据指向该模块 |
| log_localization | 反驳当前模块 | -0.20 ~ -0.30 | 日志证据不支持该模块 |
| log_localization | 无明确结论 | 0.0 | 日志无法提供判断 |
| module_execution | 模块可疑 | +0.20 ~ +0.30 | 执行验证发现异常 |
| module_execution | 模块正常 | -0.15 ~ -0.25 | 执行验证未发现异常 |
| code_localization | 找到相关代码 | +0.15 ~ +0.25 | 代码证据支持该模块 |
| code_localization | 无相关代码 | -0.10 ~ -0.15 | 代码证据不支持该模块 |

#### 调整约束

1. **单一来源惩罚**：如果只有单一 capability 提供置信度提升（其他都是 0.0），最终置信度需要打折或要求 replan
2. **跨模块冲突**：如果 log_localization 和 module_execution 对同一模块的判断冲突，需要 Reflection 综合判断
3. **有效模块限制**：如果 candidate_module 不在有效模块列表中，最终置信度不能超过 0.5

### 2.4 Reflection 综合校准

ReflectionModule.reflect() 综合分支内所有 confidence_updates，计算 final_confidence：

```python
def reflect(branch_memory) -> Dict:
    initial_confidence = branch_memory.get_initial_confidence()

    confidence_updates = []
    total_delta = 0.0

    for attempt in branch_memory.iteration.attempts:
        delta = attempt.get("confidence_delta", 0.0)
        total_delta += delta
        confidence_updates.append({
            "source": attempt["step"],
            "delta": delta,
            "evidence_score": attempt.get("evidence_score", 0.0),
            "reason": attempt.get("reason", ""),
            "evidence": attempt.get("evidence", {})
        })

    # 累积置信度
    final_confidence = initial_confidence + total_delta
    final_confidence = max(0.0, min(1.0, final_confidence))

    # 决策判断
    if final_confidence >= 0.7:
        decision = "proceed"
    elif final_confidence >= 0.4:
        decision = "replan"
    else:
        decision = "stop"

    return {
        "decision": decision,
        "final_confidence": final_confidence,
        "confidence_updates": confidence_updates,
        "initial_confidence": initial_confidence,
        "excluded": decision == "stop",
        "evidence_chain": [...],
        "summary": "..."
    }
```

### 2.5 置信度等级

| Confidence Score | Level | 说明 |
|------------------|-------|------|
| >= 0.85 | HIGH | 多源证据强烈支持，可直接 proceed |
| 0.70-0.84 | MEDIUM-HIGH | 有证据支持，可以 proceed |
| 0.40-0.69 | MEDIUM | 证据不足，需要 replan |
| 0.0-0.39 | LOW | 证据不足，stop |

---

## 3. situation_analysis 输出规范

### 3.1 输出结构

situation_analysis 输出一个包含 candidate_modules 列表的结果：

```json
{
  "command": "往前走",
  "expected_action": "机器人向前移动",
  "unexpected_incident": "机器人没有反应",
  "candidate_modules": [
    {"module": "intent_classifier", "initial_confidence": 0.75},
    {"module": "parameter_extractor", "initial_confidence": 0.45},
    {"module": "protocol_builder", "initial_confidence": 0.30}
  ],
  "bug_hint": "意图分类裁决逻辑可能存在问题"
}
```

### 3.2 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| command | string | 是 | 用户下达的具体指令 |
| expected_action | string | 是 | 期望的系统行为 |
| unexpected_incident | string | 是 | 实际发生的意外情况 |
| candidate_modules | list | 是 | 候选模块列表 |
| candidate_modules[].module | string | 是 | 模块名称，必须在有效列表中 |
| candidate_modules[].initial_confidence | float | 是 | 初始置信度，范围 0.0-1.0 |
| bug_hint | string | 否 | 基于情景分析的 bug 线索提示 |

### 3.3 有效模块列表

```
rejection_classifier, intent_classifier, instruction_rewriter,
command_store, parameter_extractor, protocol_builder
```

**注意**：emqx_client 不在有效模块列表中，不能作为 candidate_module。

### 3.4 约束

- **不输出 reason**：situation_analysis 不需要解释为什么是这个模块
- **不输出 evidence**：证据来自分支内的 log_localization 等能力
- **不输出 source**：source 是后续分支验证能力的职责
- **只执行一次**：situation_analysis 是全局 capability，在分支外执行

---

## 4. Branch 执行规范

### 4.1 Branch 创建

基于 situation_analysis 输出的 candidate_modules，为每个候选模块创建一个独立 branch：

```python
for candidate in candidate_modules:
    branch_memory = MemoryModule()
    branch_memory.set_candidate_module(candidate.module)
    branch_memory.set_initial_confidence(candidate.initial_confidence)
    # 创建分支...
```

### 4.2 Branch 内 Capabilities

**允许执行的 capabilities**：

| Capability | 作用 |
|-----------|------|
| log_localization | 针对 candidate_module 分析日志证据 |
| module_execution | 针对 candidate_module 验证可疑性 |
| code_localization | 针对 candidate_module 检查代码证据（如果存在） |

**不允许执行的 capabilities**：

| Capability | 原因 |
|-----------|------|
| situation_analysis | 已在全局执行完毕，分支不应重复执行 |
| owner_identification | 属于 finalization，只在全局 final_decision 后执行 |
| feishu_notification | 属于 finalization，只在全局 final_decision 后执行 |

### 4.3 Branch 内能力输出要求

每个 branch 内 capability 必须输出置信度贡献信息：

#### log_localization 输出

```json
{
  "candidate_module": "intent_classifier",
  "log_supports_candidate": true,
  "confidence_delta": 0.20,
  "evidence_score": 0.75,
  "related_log_snippets": ["[IntentEnsemble] 裁决失败: intent=2 conf=0.42"],
  "reasons": ["日志显示意图分类裁决失败，与预期不符"]
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
  "reasons": ["意图分类器在测试场景下行为异常"]
}
```

### 4.4 Branch Memory 数据存储

```python
branch_memory = MemoryModule()

# 初始设置
branch_memory.set_candidate_module("intent_classifier")
branch_memory.set_initial_confidence(0.75)

# 能力执行结果
branch_memory.add_attempt(
    step="log_localization",
    evidence={
        "candidate_module": "intent_classifier",
        "log_supports_candidate": true,
        "confidence_delta": 0.20,
        "evidence_score": 0.75,
        "related_log_snippets": [...],
        "reasons": [...]
    },
    success=True
)

branch_memory.add_attempt(
    step="module_execution",
    evidence={
        "candidate_module": "intent_classifier",
        "execution_supports_candidate": true,
        "confidence_delta": 0.25,
        "evidence_score": 0.80,
        "suspicious": true,
        "reasons": [...]
    },
    success=True
)

# Reflection 结果
reflection_result = reflector.reflect(branch_memory)
branch_memory.add_conversation(
    step="reflection",
    role="assistant",
    content=reflection_result.get("summary", "")
)
```

---

## 5. BranchResult 结构

### 5.1 数据类定义

```python
@dataclass
class BranchResult:
    module: str                           # 验证的模块
    initial_confidence: float              # situation_analysis 给出的初始置信度
    confidence_updates: List[Dict]        # 各能力的置信度贡献
    final_confidence: float               # 累积后的最终置信度
    excluded: bool                       # 是否被排除
    decision: str                         # proceed / replan / stop
    evidence_chain: List[Dict]           # 完整证据链
    reflection_summary: str               # 反思总结
    verification_result: Dict             # 验证结果详情
```

### 5.2 confidence_updates 项结构

```python
{
    "source": "log_localization",          # 能力来源
    "delta": 0.20,                         # 置信度变化
    "evidence_score": 0.75,                 # 该能力的证据评分
    "reason": "日志证据支持该模块",         # 变化原因
    "evidence": {                          # 详细证据
        "related_log_snippets": [...],
        "suspicious": true
    }
}
```

---

## 6. merge_and_sort_results 规范

### 6.1 输入

```python
branch_results: List[BranchResult]
```

### 6.2 输出

```python
{
    "root_module": "intent_classifier",    # 置信度最高的非排除模块
    "confidence": "HIGH",                 # HIGH / MEDIUM / LOW / UNKNOWN
    "confidence_score": 0.85,             # 具体置信度分数
    "final_decision": "proceed",          # proceed / replan / stop
    "branch_results": [...],               # 所有分支结果
    "total_branches": 3,                 # 总分支数
    "total_reflection_count": 3           # 总反思次数
}
```

### 6.3 排序算法

```python
def merge_and_sort_results(branch_results: List[BranchResult]) -> Dict:

    # 1. 过滤 excluded=True 的分支
    valid_branches = [br for br in branch_results if not br.excluded]

    # 2. 按 final_confidence 降序排序
    sorted_branches = sorted(
        valid_branches,
        key=lambda br: (br.final_confidence, len(br.confidence_updates)),
        reverse=True
    )

    if not sorted_branches:
        return {
            "root_module": None,
            "confidence": "UNKNOWN",
            "confidence_score": 0.0,
            "final_decision": "stop",
            "branch_results": branch_results,
            "total_branches": len(branch_results),
            "total_reflection_count": len(branch_results)
        }

    # 3. 取最优分支
    best_branch = sorted_branches[0]

    # 4. 确定置信度等级
    confidence_score = best_branch.final_confidence
    if confidence_score >= 0.85:
        confidence_level = "HIGH"
    elif confidence_score >= 0.70:
        confidence_level = "MEDIUM-HIGH"
    elif confidence_score >= 0.40:
        confidence_level = "MEDIUM"
    else:
        confidence_level = "LOW"

    # 5. 确定 final_decision
    final_decision = best_branch.decision

    # 6. 如果置信度过低（< 0.7），改为 replan 或 stop
    if confidence_score < 0.7:
        if confidence_score >= 0.4:
            final_decision = "replan"
        else:
            final_decision = "stop"

    return {
        "root_module": best_branch.module,
        "confidence": confidence_level,
        "confidence_score": confidence_score,
        "final_decision": final_decision,
        "branch_results": branch_results,
        "total_branches": len(branch_results),
        "total_reflection_count": len(branch_results)
    }
```

### 6.4 排序原则

1. **排除 excluded=True**：被 Reflection 判定为 stop 的分支直接排除
2. **优先高置信度**：final_confidence 高的分支优先
3. **多证据优先**：final_confidence 相近时，优先 confidence_updates 数量多的分支
4. **阈值保护**：最高分 < 0.7 时，不 proceed，改为 replan 或 stop

---

## 7. Finalization 流程

### 7.1 执行条件

finalization 只在以下条件满足时执行：
- final_decision = "proceed"
- confidence_score >= 0.7
- root_module 在有效模块列表中
- root_module 有负责人映射

### 7.2 执行顺序

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

### 7.3 约束

- **owner_identification** 只执行一次，在 final_decision 之后
- **feishu_notification** 只在 owner_identification 成功后执行
- **不允许**分支内执行 owner_identification 或 feishu_notification
- **不允许**多个分支分别通知多个负责人

---

## 8. Memory 存储边界

### 8.1 全局 Memory (Agent.memory / ExecutionModule.memory)

| 数据 | 存储位置 | 说明 |
|------|---------|------|
| situation_analysis 结果 | iteration.attempts | 包含 candidate_modules |
| final_decision | context.conversation | merge_and_sort 结果 |
| root_module | _bug_module | 只在 final_decision 后设置 |
| owner_info | _owner_open_id | 只在 owner_identification 后设置 |
| feishu_notification 结果 | iteration.attempts | 包含 message_id, recipient |

### 8.2 分支 Memory (每个 branch_memory)

| 数据 | 存储位置 | 说明 |
|------|---------|------|
| candidate_module | branch_memory._candidate_module | 绑定到该分支的候选模块 |
| initial_confidence | branch_memory._initial_confidence | 初始置信度 |
| log_localization 结果 | iteration.attempts | 包含 confidence_delta |
| module_execution 结果 | iteration.attempts | 包含 confidence_delta |
| code_localization 结果 | iteration.attempts | 如果存在 |
| reflection 结果 | context.conversation | 包含 final_confidence |

---

## 9. 架构约束汇总

| 约束 ID | 描述 |
|---------|------|
| C-1 | situation_analysis 只在分支外执行一次 |
| C-2 | situation_analysis 输出只包含 module 和 initial_confidence |
| C-3 | branch 内不执行 situation_analysis |
| C-4 | branch 内不执行 owner_identification |
| C-5 | branch 内不执行 feishu_notification |
| C-6 | owner_identification 只在 final_decision 后执行 |
| C-7 | feishu_notification 只在 owner_identification 后执行 |
| C-8 | confidence 只能累积，不能单次覆盖 |
| C-9 | final_decision 来自 merge_and_sort_results |
| C-10 | root_module 必须在有效模块列表中才能通知 |
| C-11 | confidence < 0.7 时不能 proceed |
| C-12 | 分支内存互不干扰，独立执行 |
