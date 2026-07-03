# Phase 1 RAG / Source Leakage Report

生成时间：2026-07-03

## 1. 目标

Phase 1 先补 MKAOS 最危险的防回退测试，防止后续 Context Builder、Publish、Recap 和 Agent Center 扩展时把 `source_chunk.raw_text` 或 MKAOS runtime asset 带入 generation RAG 或生成提示上下文。

## 2. 读取与分析

| 范围 | 结论 | 证据 |
| -- | -- | -- |
| RAG bucket isolation | 已有 `GENERATION_RAG_BLOCKED_TYPES`，但缺 `source_chunk` 类型级阻断。 | `src/novel_forge/storage/rag_context.py` |
| MKAOS source isolation | Source Chunk metadata 已设 `use_in_generation_rag=false`；Prose Pack 只携带 `source_chunk_ids`。 | `src/novel_forge/modules/mkaos/service.py::rebuild_source_chunks`、`build_knowledge_pack` |
| Prompt preview | `pack_prompt_preview` 已阻止 prose preview 出现 `raw_text` 字符串。 | `src/novel_forge/modules/mkaos/service.py::pack_prompt_preview` |
| Chapter prompt | ChapterOutline service 会把 `_pack_content(mkaos_pack)` 传入模型上下文。 | `src/novel_forge/modules/chapter_plan/service.py::generate_chapter_plan` |
| Publish pack | 当前没有 MKAOS publish adapter；现有 release package 从 draft text 和 publish gate 生成。 | `src/novel_forge/modules/audit/service.py::create_release_package` |
| Recap context | 当前没有 Longform Recap Agent；可用 Context Builder manual selection 作为 recap-context test seam。 | `src/novel_forge/modules/context_builder/service.py::create_context_bundle` |
| Project lineage | `build_knowledge_pack` 原先按 flow 取绑定，未按 requested `project_id` 排除其他项目 knowledge。 | `src/novel_forge/modules/mkaos/service.py::_pack_item_from_binding` |

## 3. 实现变更

| 文件 | 变更 |
| -- | -- |
| `src/novel_forge/storage/rag_context.py` | 将 `source_chunk` 加入 `GENERATION_RAG_BLOCKED_TYPES`，让 generation RAG 类型级拒绝 source chunks，而不只依赖 metadata。 |
| `src/novel_forge/modules/mkaos/service.py` | `build_knowledge_pack` 调用 `_pack_item_from_binding` 时传入 `project_id`；`_pack_item_from_binding` 增加 binding/knowledge project scope 过滤，避免跨项目知识进入 pack。 |
| `tests/unit/test_mkaos_isolation.py` | 新增 MKAOS RAG/source leakage 专项回归。 |

## 4. 新增测试覆盖

| 测试 | 覆盖点 |
| -- | -- |
| `test_prose_pack_prompt_preview_and_chapter_prompt_do_not_leak_source_chunk_raw_text` | `source_chunk.raw_text` 不进入 Prose Pack、prompt preview、ChapterOutline 生成上下文中的 MKAOS pack。 |
| `test_publish_package_and_recap_context_seam_do_not_leak_source_chunk_raw_text` | release package 不泄露 source raw text；Context Builder recap seam 手工选 source chunk 时被 policy rejection 拒绝。 |
| `test_generation_rag_rejects_mkaos_runtime_assets_and_source_chunks` | `source_chunk`、`knowledge_pack`、`knowledge_usage_event`、`agent_run` 不能进入 generation RAG，且出现在 filtered assets 中。 |
| `test_mkaos_pack_budget_and_project_scoped_lineage` | Prose pack budget 限制可验证；其他项目 knowledge 不进入当前项目 pack 或 lineage references。 |

## 5. 验收结果

| 命令 | 结果 |
| -- | -- |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | 4 tests OK，用时约 4.9s |
| `python3 -m unittest tests/unit/test_mkaos.py` | 5 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 1 test OK，用时 260.210s |

## 6. 取舍

1. 本阶段没有实现完整 `publish` / `recap` MKAOS adapter；它们属于后续 Phase 4/7/10。当前用 release package 和 Context Builder manual selection 建立最小 test seam，先防止 raw source leakage。
2. Project scope 过滤允许 `local-system` 或空项目资产作为全局知识继续复用；显式项目资产之间不能跨项目污染。
3. `source_chunk` 类型级进入 RAG blocklist 是防御性加固，和原有 metadata `use_in_generation_rag=false` 不冲突。

## 7. 剩余风险

| 风险 | 后续 Phase |
| -- | -- |
| publish/recap 还没有正式 MKAOS adapter。 | Phase 4 / Phase 7 / Phase 10 |
| Context Builder 尚未正式包含 MKAOS pack 字段。 | Phase 4 |
| release package 还不能由 ReviewIssue blocking 系统统一阻断。 | Phase 5 / Phase 10 |
| Canon conflict 仍是基础检查。 | Phase 3 |
