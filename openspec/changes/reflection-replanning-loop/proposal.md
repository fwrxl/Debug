# Proposal: Reflection-Before-Notification with Confidence Accumulation

## Context

当前架构的问题：
1. situation_analysis 输出过于简单，只返回 possible_modules: List[str]
2. 分支执行中重复执行 situation_analysis，造成冗余
3. 置信度没有累积模型，每个 capability 独立判断
4. candidate_modules 中包含 reason、evidence、source 等冗余字段

## 目标

实现基于置信度累积的多分支诊断流程：
- situation_analysis 只执行一次，输出带 initial_confidence 的候选模块
- 分支内不重复执行 situation_analysis
- 分支内能力围绕当前 candidate_module 输出置信度贡献（delta 或 evidence_score）
- 置信度在分支内累积，最终由 Reflection 综合校准

## 数据流设计

```
situation_analysis (全局，只执行一次)
        ↓
candidate_modules: [
  {
    "module": str,
    "initial_confidence": float  # 范围 0.0-1.0
  }
]
        ↓
为每个 candidate_module 创建独立 branch memory
        ↓
每个 branch 内执行（围绕当前 candidate_module）：
  1. log_localization(candidate_module)
     - 输出 log_supports_candidate
     - 输出 confidence_delta 或 evidence_score
     - 输出 related_log_snippets
     - 输出 reasons

  2. module_execution(candidate_module)
     - 输出 execution_supports_candidate
     - 输出 confidence_delta 或 evidence_score
     - 输出 suspicious / not_suspicious
     - 输出 reasons

  3. code_localization(candidate_module)，如果当前项目有该能力
     - 输出 code_supports_candidate
     - 输出 confidence_delta 或 evidence_score
     - 输出 related_code_evidence
     - 输出 reasons

  4. ReflectionModule.reflect(branch_memory)
     - 读取 initial_confidence
     - 读取 confidence_updates（log_localization / module_execution / code_localization 的贡献）
     - 综合计算 final_confidence
     - 判断 proceed / replan / stop
     - 输出 reflection_summary

        ↓
merge_and_sort_results
        ↓
选择 final_decision
        ↓
owner_identification
        ↓
feishu_notification
```

## 关键约束

| 约束 | 说明 |
|------|------|
| situation_analysis 是全局 capability | 只在分支外执行一次 |
| situation_analysis 输出简洁 | 只包含 module 和 initial_confidence |
| branch 内不执行 situation_analysis | 分支目标不是重新理解情景 |
| 每个能力输出置信度贡献 | confidence_delta 或 evidence_score |
| 置信度累积模型 | initial_confidence + 各能力 delta |
| owner_identification 在 final_decision 后 | 不允许分支内执行 |
| feishu_notification 在 owner_identification 后 | 不允许分支内执行 |

## 候选模块输出结构

### 旧结构（需删除）

```json
{
  "possible_modules": [
    {"module": "intent_classifier", "reason": "...", "evidence": "...", "source": "..."},
    {"module": "parameter_extractor", "reason": "...", "evidence": "...", "source": "..."}
  ]
}
```

### 新结构

```json
{
  "candidate_modules": [
    {"module": "intent_classifier", "initial_confidence": 0.75},
    {"module": "parameter_extractor", "initial_confidence": 0.45}
  ]
}
```

**注意**：
- 不再包含 reason、evidence、source 字段
- 如果需要证据链，来自分支内的 log_localization、module_execution、code_localization

## 分支能力置信度输出

### log_localization 输出

```json
{
  "candidate_module": "intent_classifier",
  "log_supports_candidate": true,
  "confidence_delta": 0.15,
  "evidence_score": 0.80,
  "related_log_snippets": ["[IntentEnsemble] 裁决失败: 意图=2 conf=0.42"],
  "reasons": ["日志中明确显示意图分类裁决失败"]
}
```

### module_execution 输出

```json
{
  "candidate_module": "intent_classifier",
  "execution_supports_candidate": true,
  "confidence_delta": 0.20,
  "evidence_score": 0.70,
  "suspicious": true,
  "reasons": ["意图分类器在测试用例中表现异常"]
}
```

## 置信度累积规则

```
branch_confidence = initial_confidence
                 + log_localization_delta
                 + module_execution_delta
                 + code_localization_delta
                 + reflection_adjustment

最终限制在 0.0 到 1.0 范围内
```

### 调整规则示例

| 能力结果 | Delta 范围 |
|---------|-----------|
| log_localization 明确支持当前模块 | +0.15 到 +0.25 |
| log_localization 明确反驳当前模块 | -0.20 到 -0.30 |
| module_execution 验证当前模块可疑 | +0.20 到 +0.30 |
| module_execution 未发现异常 | -0.15 到 -0.25 |
| code_localization 找到相关代码证据 | +0.15 到 +0.25 |
| 单一来源证据 | 降低最终置信度或要求 replan |
| 模块不在有效模块列表 | 不能直接 proceed |

## BranchResult 结构

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
    evidence_chain: List[Dict]          # 证据链
    reflection_summary: str              # 反思总结
    verification_result: Dict            # 验证结果详情
```

## Memory 存储规则

### 全局 Agent.memory / ExecutionModule.memory

- situation_analysis 结果（含 candidate_modules）
- final_decision
- merge_and_sort_results 结果
- owner_identification 结果
- feishu_notification 结果

### 每个 branch memory

- 当前 candidate_module 和 initial_confidence
- log_localization 结果 → branch_memory.iteration.attempts
- module_execution 结果 → branch_memory.iteration.attempts
- code_localization 结果 → branch_memory.iteration.attempts（如存在）
- reflection 结果 → branch_memory.context.conversation

## merge_and_sort_results 规则

排序原则：
1. 排除 excluded=True 的分支
2. 优先 final_confidence 高的分支
3. final_confidence 接近时，优先证据来源更多的分支
4. 最高分低于阈值（0.7）则不通知，改为 replan 或 stop
5. final_decision 来自 merge 结果，不是某个中间 failed_module

## OpenSpec 变更清单

| 文件 | 变更内容 |
|------|---------|
| proposal.md | 更新数据流设计、约束、输出结构 |
| design.md | 新增 Confidence Accumulation Model 章节 |
| tasks.md | 调整任务列表，新增相关任务 |
| spec.md | 更新 situation_analysis 输出、branch 执行流程、BranchResult 结构 |
