# Novel OS v6 Test Summary

生成时间：2026-07-03

## Phase 1

| 命令 | 目的 | 结果 |
| -- | -- | -- |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | MKAOS RAG/source leakage、runtime asset isolation、pack budget、project scope lineage 专项回归。 | 4 tests OK，用时约 4.9s |
| `python3 -m unittest tests/unit/test_mkaos.py` | MKAOS P0 原有单测回归。 | 5 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 旧 pipeline 集成链路不回归。 | 1 test OK，用时 260.210s |

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
