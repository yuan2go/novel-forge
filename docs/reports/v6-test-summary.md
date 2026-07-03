# Novel OS v6 Test Summary

生成时间：2026-07-03

## Phase 1

| 命令 | 目的 | 结果 |
| -- | -- | -- |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | MKAOS RAG/source leakage、runtime asset isolation、pack budget、project scope lineage 专项回归。 | 4 tests OK，用时约 4.9s |
| `python3 -m unittest tests/unit/test_mkaos.py` | MKAOS P0 原有单测回归。 | 5 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 旧 pipeline 集成链路不回归。 | 1 test OK，用时 260.210s |

## Phase 2

| 命令 | 目的 | 结果 |
| -- | -- | -- |
| `python3 -m unittest tests/unit/test_mkaos_os_envelope.py` | MKAOS OS Envelope production fail-closed、metadata/trace、sample bypass、Query/Convert service/API。 | 5 tests OK，用时约 0.94s |
| `python3 -m unittest tests/unit/test_mkaos.py` | MKAOS P0 原有单测回归。 | 5 tests OK |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | Phase 1 隔离回归不退化。 | 4 tests OK，用时约 5.0s |
| `python3 -m unittest tests/unit/test_product_api_routes.py` | Product API 路由烟测，包括新增 MKAOS Query/Convert 路由注册。 | 1 test OK，用时约 16.8s |
| `python3 -m unittest tests.integration.test_pipeline` | 旧 pipeline 集成链路不回归。 | 1 test OK，用时 255.089s |

## Phase 3

| 命令 | 目的 | 结果 |
| -- | -- | -- |
| `python3 -m unittest tests/unit/test_mkaos_selector_canon.py` | MKAOS selector quality/feedback/weight/risk/project scope、Canon structured result 和 issue candidate。 | 3 tests OK |
| `python3 -m unittest tests/unit/test_mkaos.py` | MKAOS P0 原有单测回归。 | 5 tests OK |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | RAG/source leakage 和 source isolation 回归不退化。 | 4 tests OK，用时约 5.1s |
| `python3 -m unittest tests/unit/test_mkaos_os_envelope.py` | OS Envelope 强制与 Query/Convert 回归不退化。 | 5 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 旧 pipeline 集成链路不回归。 | 1 test OK，用时 257.578s |

## Phase 4

| 命令 | 目的 | 结果 |
| -- | -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/context_builder src/novel_forge/modules/outline src/novel_forge/modules/chapter_plan src/novel_forge/modules/drafting src/novel_forge/modules/review` | Context Builder 与四个接入服务语法/导入检查。 | OK |
| `python3 -m unittest tests/unit/test_context_builder_mkaos_flow.py` | 统一 Context Builder 注入 MKAOS Pack，并证明 Outline/ChapterOutline/Prose/Review 输出引用 ContextBundle。 | 2 tests OK，用时约 12.3s |
| `python3 -m unittest tests/unit/test_context_and_production_chain.py` | Context Builder 与生产链路回归。 | 12 tests OK，用时约 62.9s |
| `python3 -m unittest tests/unit/test_module_services.py` | 主模块服务链路回归。 | 10 tests OK，用时约 60.1s |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | MKAOS source isolation 回归。 | 4 tests OK，用时约 7.7s |
| `python3 -m unittest tests/unit/test_mkaos.py` | MKAOS P0 原有单测回归。 | 5 tests OK |
| `python3 -m unittest tests/unit/test_mkaos_os_envelope.py` | OS Envelope 回归。 | 5 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 旧 pipeline 集成链路不回归。 | 1 test OK，用时 406.239s |

## Phase 5

| 命令 | 目的 | 结果 |
| -- | -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/review_issue src/novel_forge/modules/review src/novel_forge/modules/audit src/novel_forge/modules/editor src/novel_forge/schemas src/novel_forge/api/routers/reviews.py` | ReviewIssue 相关模块语法/导入检查。 | OK |
| `python3 -m unittest tests/unit/test_review_issue.py` | MKAOS/Canon issue 持久化，release package 和 canonical/final draft 阻断证明。 | 3 tests OK |
| `python3 -m unittest tests/unit/test_schemas.py` | 新 `review_issue` schema 注册与通用 schema 回归。 | 17 tests OK |
| `python3 -m unittest tests/unit/test_product_api_routes.py` | API 路由注册回归。 | 1 test OK |
| `python3 -m unittest tests/unit/test_mkaos.py` | MKAOS P0 回归。 | 5 tests OK |
| `python3 -m unittest tests/unit/test_module_services.py` | 主模块服务链路回归。 | 10 tests OK，用时约 59.0s |
| `python3 -m unittest tests/unit/test_context_builder_mkaos_flow.py` | Context Builder / MKAOS flow 回归。 | 2 tests OK |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | source isolation 回归。 | 4 tests OK |
| `python3 -m unittest tests/unit/test_postgres_migrations.py` | migration chain 回归。 | 2 tests OK |
| `python3 -m unittest tests/unit/test_publishing_center.py` | publishing center 无阻断旧路径回归。 | 1 test OK |
| `python3 -m unittest tests/unit/test_longform_stability.py` | longform publish gate 回归。 | 8 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 旧 pipeline 集成链路不回归。 | 1 test OK，用时 405.552s |

## Phase 6

| 命令 | 目的 | 结果 |
| -- | -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/loop_kernel src/novel_forge/schemas src/novel_forge/api/routers/loops.py src/novel_forge/api/routers/__init__.py` | Loop Kernel、schema、API router 语法/导入检查。 | OK |
| `python3 -m unittest tests/unit/test_loop_kernel.py` | LoopRun/LoopStep/Checkpoint/Report、Context Builder 接入、ReviewIssue 阻断、budget stop、OS Envelope fail closed。 | 4 tests OK |
| `python3 -m unittest tests/unit/test_schemas.py` | 新 Loop 资产 schema 注册与通用 schema 回归。 | 17 tests OK |
| `python3 -m unittest tests/unit/test_product_api_routes.py` | Product API 路由注册回归。 | 1 test OK |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | RAG/source leakage 回归；Loop runtime assets 不进入 generation RAG。 | 4 tests OK |
| `python3 -m unittest tests/unit/test_context_builder_mkaos_flow.py tests/unit/test_mkaos.py tests/unit/test_review_issue.py` | Context Builder/MKAOS/ReviewIssue 相邻回归。 | 10 tests OK |
| `python3 -m unittest tests/unit/test_workflow_executor.py` | 旧 workflow executor 回归，确认 Loop Kernel 未替换或破坏 workflow 层。 | 27 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 旧 pipeline 集成链路不回归。 | 1 test OK，用时 410.099s |

## Phase 7

| 命令 | 目的 | 结果 |
| -- | -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/longform_recap src/novel_forge/modules/context_builder src/novel_forge/modules/longform_stability src/novel_forge/schemas src/novel_forge/api/routers/longform_recap.py src/novel_forge/api/routers/__init__.py` | Longform Recap Agent、Context Builder、Longform Stability、schema、API router 语法/导入检查。 | OK |
| `python3 -m unittest tests/unit/test_longform_recap_agent.py` | 12 章 recap 触发、Loop/Context/ReviewIssue/MKAOS 接入、治理写回、下一章 context 读取和 raw_text 隔离。 | 2 tests OK，用时约 14.8s |
| `python3 -m unittest tests/unit/test_schemas.py` | 新 `longform_recap_report` schema 注册与通用 schema 回归。 | 17 tests OK |
| `python3 -m unittest tests/unit/test_product_api_routes.py` | Product API 路由注册回归。 | 1 test OK |
| `python3 -m unittest tests/unit/test_longform_stability.py tests/unit/test_loop_kernel.py` | 既有 longform stability 和 Loop Kernel 回归。 | 12 tests OK |
| `python3 -m unittest tests/unit/test_context_builder_mkaos_flow.py tests/unit/test_mkaos_isolation.py` | Context Builder/MKAOS source isolation 回归。 | 6 tests OK |
| `python3 -m unittest tests.integration.test_longform_quality_gate_e2e` | 既有 longform quality gate E2E 回归。 | 1 test OK |

## 待最终全量运行

最终 Phase 12 必须重新运行：

```bash
python3 -m unittest tests/unit/test_mkaos.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest tests.integration.test_pipeline
npm --prefix web/admin test
npm --prefix web/admin run build
```

并追加 longform / loop / publish gate / provider hard-stop 新增测试命令。
