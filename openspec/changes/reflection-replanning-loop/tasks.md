## Tasks

任务拆分遵循原则：每步可测试、可回滚、可验证。

---

## Phase 0: OpenSpec 文档对齐与确认

- [x] 0.1 确认 spec.md 中 Reflection 作为 Decision Gate 的定义
- [x] 0.2 确认 capability phase separation（Diagnostic vs Finalization）
- [x] 0.3 确认 memory._bug_module 语义约束（只能保存最终确认模块）
- [x] 0.4 确认 auto-chain 约束（不能根据中间 failed_module 触发 finalization）
- [x] 0.5 确认 multi-branch 流程（分支内禁止执行 finalization capabilities）
- [x] 0.6 确认 Reflection 输出包含 decision semantics
- [x] 0.7 确认 replanning loop limit（max_reflection_iterations）
- [x] 0.8 确认 feishu_notification 必须使用最终总结

**验收标准**：
- OpenSpec 文档完整描述新架构
- 所有架构约束已在文档中明确

---

## Phase 1: situation_analysis 输出扩展

- [ ] 1.1 扩展 situation_analysis 输出结构，从 `possible_modules: List[str]` 扩展为带 `initial_confidence` 的候选模块列表
- [ ] 1.2 删除 situation_analysis 输出中的 `reason` 字段
- [ ] 1.3 删除 situation_analysis 输出中的 `evidence` 字段
- [ ] 1.4 删除 situation_analysis 输出中的 `source` 字段
- [ ] 1.5 确认 situation_analysis 只输出 `module` 和 `initial_confidence`

**新 candidate_modules 结构**：
```json
{
  "candidate_modules": [
    {"module": "intent_classifier", "initial_confidence": 0.75},
    {"module": "parameter_extractor", "initial_confidence": 0.45}
  ]
}
```

**验收标准**：
- situation_analysis 输出 candidate_modules 列表
- 每个候选项只包含 module 和 initial_confidence
- 不包含 reason、evidence、source 字段

---

## Phase 2: situation_analysis 执行时机调整

- [ ] 2.1 确认 situation_analysis 是全局 capability，只在分支外执行一次
- [ ] 2.2 在 executor 或 agent 流程中明确 situation_analysis 不在分支内执行
- [ ] 2.3 调整 branch 创建逻辑，基于 situation_analysis 的 candidate_modules
- [ ] 2.4 为每个 candidate_module 创建独立 branch memory，并设置 initial_confidence

**验收标准**：
- situation_analysis 只执行一次（在分支创建前）
- branch 内不允许执行 situation_analysis
- 每个 branch memory 保存 initial_confidence

---

## Phase 3: Branch 内能力置信度输出

- [ ] 3.1 扩展 log_localization 输出，添加对 candidate_module 的置信度贡献字段
  - 添加 `confidence_delta` 或 `evidence_score`
  - 添加 `log_supports_candidate` (bool)
  - 添加 `related_log_snippets`
  - 添加 `reasons`
- [ ] 3.2 扩展 module_execution 输出，添加对 candidate_module 的置信度贡献字段
  - 添加 `confidence_delta` 或 `evidence_score`
  - 添加 `execution_supports_candidate` (bool)
  - 添加 `suspicious` (bool)
  - 添加 `reasons`
- [ ] 3.3 如果项目存在 code_localization，扩展其输出添加置信度贡献字段

**验收标准**：
- log_localization 输出包含对候选模块的置信度贡献
- module_execution 输出包含对候选模块的置信度贡献
- 每个输出包含 `confidence_delta` 或 `evidence_score`

---

## Phase 4: Confidence Accumulation Model

- [ ] 4.1 在 MemoryModule 中新增 `set_initial_confidence()` 和 `get_initial_confidence()`
- [ ] 4.2 在 MemoryModule 中新增 `set_candidate_module()` 和 `get_candidate_module()`
- [ ] 4.3 实现置信度累积计算：initial_confidence + Σ(delta)
- [ ] 4.4 在 ReflectionModule.reflect() 中实现置信度累积逻辑
- [ ] 4.5 实现 Reflection 最终校准

**置信度累积公式**：
```
final_confidence = initial_confidence
                 + log_localization_delta
                 + module_execution_delta
                 + code_localization_delta

限制在 0.0 到 1.0 范围内
```

**验收标准**：
- 分支内置信度正确累积
- Reflection.reflect() 输出 final_confidence
- final_confidence 基于累积模型，而非单次覆盖

---

## Phase 5: ReflectionModule.reflect() 增强

- [ ] 5.1 增强 reflect() 输入 branch_memory，包含 initial_confidence
- [ ] 5.2 增强 reflect() 输出，包含 confidence_updates 列表
- [ ] 5.3 确认 reflect() 输出 decision (proceed/replan/stop)
- [ ] 5.4 确认 reflect() 输出 final_confidence（累积后的置信度）
- [ ] 5.5 确认 reflect() 输出 excluded 字段

**reflect() 新输出结构**：
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

**验收标准**：
- reflect() 综合所有 confidence_updates
- final_confidence 基于累积模型
- decision 阈值：≥0.7 proceed, 0.4-0.7 replan, <0.4 stop

---

## Phase 6: BranchResult 结构调整

- [ ] 6.1 调整 BranchResult，新增 `initial_confidence` 字段
- [ ] 6.2 调整 BranchResult，新增 `confidence_updates` 字段
- [ ] 6.3 调整 BranchResult，将 `confidence` 重命名为 `final_confidence`
- [ ] 6.4 确认 BranchResult 包含 `module`, `initial_confidence`, `confidence_updates`, `final_confidence`, `excluded`, `decision`, `evidence_chain`, `reflection_summary`

**新 BranchResult 结构**：
```python
@dataclass
class BranchResult:
    module: str
    initial_confidence: float
    confidence_updates: List[Dict]  # [{source, delta, evidence_score, reason, evidence}]
    final_confidence: float
    excluded: bool
    decision: str  # proceed / replan / stop
    evidence_chain: List[Dict]
    reflection_summary: str
    verification_result: Dict
```

**验收标准**：
- BranchResult 包含所有新字段
- confidence_updates 记录每个能力的置信度贡献

---

## Phase 7: merge_and_sort_results 调整

- [ ] 7.1 调整 merge_and_sort_results 排序逻辑，基于 final_confidence
- [ ] 7.2 确认排除 excluded=True 的分支
- [ ] 7.3 实现多证据优先排序（同 confidence 时，优先 evidence 多的分支）
- [ ] 7.4 实现阈值保护（confidence < 0.7 时不 proceed）
- [ ] 7.5 确认 final_decision 来自 merge 结果

**排序原则**：
1. 排除 excluded=True
2. 优先 final_confidence 高
3. 同 confidence 时，优先 evidence 多
4. < 0.7 阈值：不 proceed，改为 replan 或 stop

**验收标准**：
- merge_and_sort_results 正确排序
- final_decision 来自 merge，不是中间 failed_module

---

## Phase 8: Finalization 执行约束

- [ ] 8.1 确认 owner_identification 只在 final_decision 后执行
- [ ] 8.2 确认 feishu_notification 只在 owner_identification 后执行
- [ ] 8.3 确认分支内不执行 owner_identification
- [ ] 8.4 确认分支内不执行 feishu_notification
- [ ] 8.5 实现阈值保护（confidence < 0.7 时不发送通知）
- [ ] 8.6 实现有效模块检查（不在列表中不发送通知）
- [ ] 8.7 实现负责人映射检查（无映射时不发送通知）

**验收标准**：
- Finalization 严格按顺序执行
- 低置信度、模块无效、无负责人映射时不允许发送通知

---

## Phase 9: Memory 存储规则

- [ ] 9.1 全局 memory 保存 situation_analysis 结果（包含 candidate_modules）
- [ ] 9.2 全局 memory 保存 final_decision
- [ ] 9.3 全局 memory 保存 merge_and_sort_results 结果
- [ ] 9.4 全局 memory 保存 owner_identification 结果
- [ ] 9.5 全局 memory 保存 feishu_notification 结果
- [ ] 9.6 branch memory 保存 candidate_module 和 initial_confidence
- [ ] 9.7 branch memory 保存 log_localization 结果（含 confidence_delta）
- [ ] 9.8 branch memory 保存 module_execution 结果（含 confidence_delta）
- [ ] 9.9 branch memory 保存 code_localization 结果（含 confidence_delta，如果存在）
- [ ] 9.10 branch memory 保存 reflection 结果

**验收标准**：
- 全局 memory 和 branch memory 存储内容明确分离
- 各阶段数据正确存储在对应 memory 中

---

## Phase 10: 测试覆盖

- [ ] 10.1 新增 test_situation_analysis_output.py：测试 situation_analysis 只输出 module 和 initial_confidence
- [ ] 10.2 新增 test_situation_analysis_single_execution.py：测试 situation_analysis 只执行一次
- [ ] 10.3 新增 test_branch_no_situation_analysis.py：测试 branch 内不执行 situation_analysis
- [ ] 10.4 新增 test_confidence_accumulation.py：测试置信度累积模型
- [ ] 10.5 新增 test_confidence_delta_output.py：测试 branch 内能力输出 confidence_delta
- [ ] 10.6 新增 test_branch_result_structure.py：测试 BranchResult 包含所有新字段
- [ ] 10.7 新增 test_merge_sort_by_confidence.py：测试 merge_and_sort_results 排序逻辑
- [ ] 10.8 新增 test_finalization_constraints.py：测试 Finalization 执行顺序和约束
- [ ] 10.9 运行全部单元测试确认不破坏现有功能

**验收标准**：
- 所有新增测试通过
- 现有测试不被破坏

---

## 新执行流程图

```
                         TestFeedbackAgent
                                │
                                ├── memory: MemoryModule
                                │      │
                                │      └── 全局记忆
                                │          - situation_analysis 结果
                                │          - final_decision
                                │          - owner_identification 结果
                                │          - feishu_notification 结果
                                ▼
                    ┌─────────────────────────────┐
                    │  situation_analysis          │
                    │  (全局，只执行一次)           │
                    │  输出:                       │
                    │  candidate_modules = [       │
                    │    {module, initial_conf}   │
                    │  ]                          │
                    └────────────┬────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
          ┌──────────┐    ┌──────────┐    ┌──────────┐
          │ Branch 1 │    │ Branch 2 │    │ Branch 3 │
          │          │    │          │    │          │
          │ module=a  │    │ module=b  │    │ module=c  │
          │ init=0.75 │    │ init=0.45 │    │ init=0.30 │
          │          │    │          │    │          │
          │ ┌──────┐ │    │ ┌──────┐ │    │ ┌──────┐ │
          │ │ log_ │ │    │ │ log_ │ │    │ │ log_ │ │
          │ │locali │ │    │ │locali │ │    │ │locali │ │
          │ │zation │ │    │ │zation │ │    │ │zation │ │
          │ │ Δ=+0.2│ │    │ │ Δ=-0.3│ │    │ │ Δ=0.0 │ │
          │ └──────┘ │    │ └──────┘ │    │ └──────┘ │
          │ ┌──────┐ │    │ ┌──────┐ │    │ ┌──────┐ │
          │ │ mod_ │ │    │ │ mod_ │ │    │ │ mod_ │ │
          │ │execu │ │    │ │execu │ │    │ │execu │ │
          │ │tion  │ │    │ │tion  │ │    │ │tion  │ │
          │ │ Δ=+0.2│ │    │ │ Δ=0.0 │ │    │ │ Δ=+0.1│ │
          │ └──────┘ │    │ └──────┘ │    │ └──────┘ │
          │ ┌──────┐ │    │ ┌──────┐ │    │ ┌──────┐ │
          │ │reflect│ │    │ │reflect│ │    │ │reflect│ │
          │ │final=│ │    │ │final=│ │    │ │final=│ │
          │ │ 0.85 │ │    │ │ 0.15 │ │    │ │ 0.40 │ │
          │ │dec=  │ │    │ │dec=  │ │    │ │dec=  │ │
          │ │procd │ │    │ │stop  │ │    │ │repln │ │
          │ └──────┘ │    │ └──────┘ │    │ └──────┘ │
          │    │     │    │    │     │    │    │     │
          │    ▼     │    │    ▼     │    │    ▼     │
          │ Branch   │    │ Branch   │    │ Branch   │
          │ Result_1 │    │ Result_2 │    │ Result_3 │
          └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
                │                │                │
                └────────────────┼────────────────┘
                                   ▼
                        ┌─────────────────────────┐
                        │   merge_and_sort_results │
                        │   选择 final_decision    │
                        │   root_module=a           │
                        │   final_conf=0.85        │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │   Reflection Gate       │
                        │   decision = proceed   │
                        └────────────┬─────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
              ┌──────────┐   ┌──────────┐    ┌──────────┐
              │ PROCEED  │   │ REPLAN   │    │ STOP     │
              │(≥0.7)    │   │(0.4-0.7) │    │ (<0.4)   │
              └────┬─────┘   └────┬─────┘    └────┬─────┘
                   │              │               │
                   ▼              │               ▼
         ┌─────────────────┐     │     ┌─────────────────┐
         │ owner_identify  │     │     │ 总结报告生成     │
         │ (final_decision)│     │     │（不发送通知）   │
         └────────┬────────┘     │     └─────────────────┘
                  │              │
                  ▼              │
         ┌─────────────────┐     │
         │ feishu_notify   │     │
         │ (最终总结)      │     │
         └─────────────────┘     │
                  │              │
                  └──────────────┘
                         │
                         ▼
              ┌─────────────────┐
              │ Planner 生成    │
              │ 补充计划        │
              │ (max_iter=3)   │
              └────────┬────────┘
                       │
                       └──回到 Reflection Gate
```

---

## 架构约束检查清单

| 约束 ID | 描述 | 验证任务 |
|---------|------|---------|
| C-1 | situation_analysis 只在分支外执行一次 | 10.2 |
| C-2 | situation_analysis 输出只包含 module 和 initial_confidence | 10.1 |
| C-3 | branch 内不执行 situation_analysis | 10.3 |
| C-4 | branch 内不执行 owner_identification | 10.8 |
| C-5 | branch 内不执行 feishu_notification | 10.8 |
| C-6 | owner_identification 只在 final_decision 后执行 | 10.8 |
| C-7 | feishu_notification 只在 owner_identification 后执行 | 10.8 |
| C-8 | confidence 只能累积，不能单次覆盖 | 10.4 |
| C-9 | final_decision 来自 merge_and_sort_results | 10.7 |
| C-10 | root_module 必须在有效模块列表中才能通知 | 10.8 |
| C-11 | confidence < 0.7 时不能 proceed | 10.7, 10.8 |
| C-12 | 分支内存互不干扰，独立执行 | 10.3 |

---

## 回滚策略

| Phase | 回滚操作 |
|-------|----------|
| Phase 1-2 | 恢复 situation_analysis 旧输出（List[str]） |
| Phase 3 | 删除 confidence_delta 字段，恢复旧输出 |
| Phase 4 | 删除 Confidence Accumulation Model，恢复单次覆盖 |
| Phase 5 | 恢复 reflect() 旧输出（无 confidence_updates） |
| Phase 6 | 恢复 BranchResult 旧结构（无 confidence_updates） |
| Phase 7 | 恢复 merge_and_sort_results 旧排序（基于 suspicious 字段） |
| Phase 8 | 恢复 Finalization 旧流程（不检查阈值和有效模块） |
