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
