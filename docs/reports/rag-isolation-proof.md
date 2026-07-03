# RAG Isolation Proof

生成时间：2026-07-03

## 1. 证明对象

本报告证明 Phase 1 后，以下资产不会进入 generation RAG：

```text
source_chunk
knowledge_pack
knowledge_usage_event
agent_run
```

同时证明 `source_chunk.raw_text` 不进入：

```text
Prose Knowledge Pack
MKAOS prompt preview
ChapterOutline prompt payload中的 MKAOS pack
Release package
Recap context test seam
```

## 2. 类型级隔离

`src/novel_forge/storage/rag_context.py::GENERATION_RAG_BLOCKED_TYPES` 现在包含：

```text
source_document
source_chunk
knowledge_usage_binding
rule_card
template_card
knowledge_pack
knowledge_pack_item
knowledge_usage_event
knowledge_quality_score
agent_run
agent_checkpoint
agent_budget
agent_gate
agent_metric
agent_dispatch_queue
agent_contract
trace_span
model_call_log
cost_ledger
workflow_run
task_status
```

`generation_context_policy()` 对这些类型返回 `eligible=false`，原因包含 `blocked_asset_type`。`source_chunk` 还保留 metadata `use_in_generation_rag=false`，作为第二道防线。

## 3. 回归证明

新增测试 `tests/unit/test_mkaos_isolation.py` 构造带有哨兵文本 `RAW_MKAOS_SOURCE_SENTINEL_DO_NOT_LEAK_7F3C` 的 MKAOS source chunk，并验证：

| 路径 | 断言 |
| -- | -- |
| Prose pack | content 不含哨兵文本，不含 `raw_text` 键。 |
| Prompt preview | preview 不含哨兵文本，不含 `raw_text` 字符串。 |
| ChapterOutline prompt payload | 生成出的 chapter plan 中 `mkaos_knowledge_pack` 不含哨兵文本和 `raw_text` 键。 |
| Release package | release package content 不含哨兵文本和 `raw_text` 键。 |
| Recap context seam | 手工选择 source chunk 会进入 `policy_rejections`，不会进入 `selected_assets` 或 `actual_context`。 |
| Generation RAG | selected items 不包含 `source_chunk`、`knowledge_pack`、`knowledge_usage_event`、`agent_run`；filtered assets 包含这些类型。 |

## 4. Project Scope Proof

`tests/unit/test_mkaos_isolation.py::test_mkaos_pack_budget_and_project_scoped_lineage` 证明：

1. `p-budget` 项目构造 outline pack 时不会引入 `p-other` 的 knowledge card。
2. pack references 不包含跨项目 knowledge id。
3. Prose pack 的 optional knowledge 受 `max_core_knowledge=3` 预算约束。

## 5. 测试命令

```bash
python3 -m unittest tests/unit/test_mkaos_isolation.py
# 4 tests OK

python3 -m unittest tests/unit/test_mkaos.py
# 5 tests OK

python3 -m unittest tests.integration.test_pipeline
# 1 test OK, 260.210s
```

## 6. 结论

Phase 1 的隔离证明达到 Post-MKAOS 继续工业化的最低要求：MKAOS evidence/runtime assets 不再依赖单一 metadata 约束，source chunk 类型进入 generation RAG blocked set，并有专项回归覆盖关键生成、发布和 recap test seam。
