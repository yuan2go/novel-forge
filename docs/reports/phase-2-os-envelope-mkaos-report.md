# Phase 2 OS Envelope / MKAOS Report

生成时间：2026-07-03

## 1. 目标

Phase 2 建立标准 OS Envelope，并将 MKAOS production mutation、pack build、usage、feedback、Query / Convert 路径纳入 envelope，解决审计指出的“Query / Convert API 和标准 envelope 缺失”问题。

## 2. 读取与分析

| 范围 | 结论 |
| -- | -- |
| `runtime_policy` | 已有 OperationPolicy、RuntimePolicyEnvelope、trace/gate/model/cost enforcement，但没有 MKAOS 专用 envelope payload。 |
| `runtime_ledger` | 已有 `record_trace_span`、`record_gate_result`、`record_model_call_log`、`record_cost_ledger`，可复用 trace_span。 |
| MKAOS router | CRUD/Pack/Validate/Feedback 已有，缺 Query/Convert 和标准响应 envelope。 |
| MKAOS service | Mutation 没有 production envelope guard；compat 路径需要保持不破坏 P0 和 pipeline。 |

## 3. 实现

| 文件 | 变更 |
| -- | -- |
| `src/novel_forge/modules/os_envelope/service.py` | 新增 OS Envelope 标准化、production enforcement、metadata 写回、标准响应。 |
| `src/novel_forge/modules/os_envelope/__init__.py` | 导出 envelope API。 |
| `src/novel_forge/modules/mkaos/service.py` | MKAOS source/knowledge/binding/rule/template/pack/usage/feedback/weight/query/convert 接入 envelope；production 缺 envelope fail closed；资产 metadata 写入 envelope。 |
| `src/novel_forge/modules/mkaos/__init__.py` | 导出 Query / Convert service。 |
| `src/novel_forge/api/routers/mkaos.py` | 新增 `/mkaos/query/knowledge`、`/mkaos/convert/assets`、`/mkaos/convert/rules`。 |
| `tests/unit/test_mkaos_os_envelope.py` | 新增 production fail closed、metadata/trace、sample bypass、Query/Convert service/API 测试。 |

## 4. 行为规则

1. production mutation 缺 envelope 会抛出 `ValueError("OS envelope required ...")`，API 转为 HTTP 400。
2. production envelope 缺必要字段会 fail closed。
3. dev/test/sample/compat 保持旧流程；sample bypass 必须带 `bypass_reason` 才会记录 bypass envelope。
4. Query / Convert API 返回 `success/request_id/trace_id/envelope/data/error` 标准响应。
5. MKAOS assets 写入 `os_envelope_id`、`trace_id` 和 `source_policy` metadata。

## 5. 验收结果

| 命令 | 结果 |
| -- | -- |
| `python3 -m unittest tests/unit/test_mkaos_os_envelope.py` | 5 tests OK，用时约 0.94s |
| `python3 -m unittest tests/unit/test_mkaos.py` | 5 tests OK |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | 4 tests OK，用时约 5.0s |
| `python3 -m unittest tests/unit/test_product_api_routes.py` | 1 test OK，用时约 16.8s |
| `python3 -m unittest tests.integration.test_pipeline` | 1 test OK，用时 255.089s |

## 6. 取舍

1. 未新增数据库表；Phase 2 先用 schema-backed metadata 和 `trace_span` 落地 envelope，符合当前 local-first JSON asset 架构。
2. 现有 CRUD API 保持兼容返回，避免破坏 UI；新增 Query/Convert API 使用标准 envelope 响应。
3. `context_bundle_id` 字段已进入 envelope，但 Phase 4 才会强制 Context Builder 统一入口。
4. production fail closed 由显式 `environment=production` 触发，避免旧 pipeline 和 sample fixture 立即破坏。

## 7. 剩余风险

| 风险 | 后续处理 |
| -- | -- |
| 不是所有 Novel OS production write path 都已接入 OS Envelope。 | Phase 5/10 和最终 enforcement audit 继续扩大覆盖。 |
| Context Builder 尚未统一提供 `context_bundle_id`。 | Phase 4。 |
| ReviewIssue blocking 尚未使用 envelope gate。 | Phase 5。 |
| Query selector 仍是轻量评分，不替代 Phase 3 selector 加固。 | Phase 3。 |
