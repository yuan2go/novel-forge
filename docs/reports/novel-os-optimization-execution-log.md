# Novel OS Optimization Execution Log

审计日期：2026-07-05  
基线 commit：`8733acf`
本轮继续治理基线 commit：`2f1f0bc`
分支：`backup/v6-post-mkaos-industrialization-20260705`  

## Scan

已扫描：

- `src/novel_forge/agents/runtime.py`
- `src/novel_forge/modules/agent_runs/service.py`
- `src/novel_forge/modules/agent_scheduler/service.py`
- `src/novel_forge/modules/os_envelope/service.py`
- `src/novel_forge/modules/context_builder/service.py`
- `src/novel_forge/modules/mkaos_production_gate/service.py`
- `src/novel_forge/modules/review_issue/service.py`
- `src/novel_forge/modules/audit/service.py`
- `src/novel_forge/modules/publishing/service.py`
- `src/novel_forge/modules/longform_recap/service.py`
- `src/novel_forge/schemas/base.py`
- `src/novel_forge/workflows/pipeline.py`
- `web/admin/app/features/*`
- `skills/*/SKILL.md`

## Implemented Changes

| ID | 优先级 | 问题 | 变更 | 文件 | 验收 |
| --- | --- | --- | --- | --- | --- |
| P0-AGENT-RUNTIME-001 | P0 | root `skills/` 与 Agent runtime profile 映射漂移；目标 Agent 名称无法直接解析 | 新增 runtime profiles、alias、完整 Skill map、单测 | `src/novel_forge/agents/runtime.py`、`src/novel_forge/agents/__init__.py`、`tests/unit/test_agent_runtime_profiles.py` | 单测覆盖所有 root Skill 显式映射，禁止默认 Quality fallback |
| P1-AGENT-PUBLISH-001 | P1 | Publish Gate 和 Release Package 的 operation 名称属于 publishing，但调用入口主要暴露在 `modules.audit` | 在 `modules.publishing` 新增 publish gate/release package facade，并让 publishing center 测试改用该入口 | `src/novel_forge/modules/publishing/service.py`、`src/novel_forge/modules/publishing/__init__.py`、`tests/unit/test_publishing_center.py` | 发布中心测试可通过 publishing facade 创建 gate/package |
| P1-AGENT-LONGFORM-001 | P1 | `run-longform-recap` 已注册但仍按 Workflow Agent profile 执行 | 将 operation spec 改为 `longform_recap` Agent，required tool 改为 `write_longform_recap_report`，修复 metadata 为 `local-system` 时 evidence project_id 被忽略的问题 | `src/novel_forge/modules/agent_scheduler/service.py`、`tests/unit/test_agent_registry_scheduler_integration.py`、`tests/unit/test_agent_operation_mkaos_coverage.py` | scheduler tick 可执行 Longform Recap Agent 并产出 `longform_recap_report` |
| P1-EVAL-PROVIDER-001 | P1 | Eval gate 与 provider runtime hard-stop 证据连接不够硬 | EvaluationGate 增加 provider runtime policy 摘要和可选 required block；PublishGate 增加 provider runtime gate，生产环境缺失/失败时阻断 | `src/novel_forge/modules/evaluation_center/service.py`、`src/novel_forge/modules/audit/service.py`、`src/novel_forge/modules/runtime_policy/service.py`、相关测试 | 生产 publish gate 暴露并阻断 missing provider runtime evidence |
| P1-PUBLISH-FACADE-002 | P1 | 生产代码和测试仍直接从 `modules.audit` 导入 publish gate/release package | 迁移 `agent_scheduler`、`revision`、`loop_kernel`、`workflow_nodes` 和相关测试到 `modules.publishing` facade | 多个 `src/novel_forge/modules/*` 与 publish tests | `rg` 只剩 `modules.publishing.service` 内部委托 audit |
| P1-SERVICE-SEAMS-001 | P1 | `mkaos/service.py`、`product.py`、`workflow_nodes/service.py` 过大，缺少先测后拆 seam | 新增 Postgres fallback policy、MKAOS risk policy、workflow publishing ops seam，并补 characterization tests | `api/services/postgres_fallback_policy.py`、`modules/mkaos/risk_policy.py`、`modules/workflow_nodes/publishing_ops.py`、`tests/unit/test_large_service_seams.py` | seam 单测通过，原服务通过新 seam 调用 |
| P0-AGENT-RUNTIME-002 | P0 | Platform Compliance / Training 只有 runtime profile，没有 operation coverage | 新增 `create-platform-strategy-pack`、`generate-training-exercise` operation specs、scheduler runners、MKAOS contract aliases、执行级测试 | `src/novel_forge/modules/agent_scheduler/service.py`、`tests/unit/test_agent_registry_scheduler_integration.py`、`tests/unit/test_agent_operation_mkaos_coverage.py` | scheduler tick 可分别执行 Platform Compliance Agent 和 Training Agent 并产出 schema-backed assets |
| P1-EVAL-PROVIDER-002 | P1 | provider hard-stop 只能证明失败阻断，缺成功样本 | `provider_hard_stop_evidence_report` 要求 hard-stop 四维覆盖 + 至少一次成功 provider guard/model_call；publish gate 增加 production success fixture | `src/novel_forge/modules/runtime_policy/service.py`、`tests/unit/test_provider_hard_stop_proof.py`、`tests/unit/test_publish_feedback_loop.py` | provider report/publish gate 均能区分 missing、warning、passed |
| P1-PUBLISH-GATE-003 | P1 | release package 只依赖 publish gate decision | release package 自身校验 EvaluationGate、ProviderRuntimeGate、PlatformStrategyGate 的状态与证据路径，production 缺失即阻断 | `src/novel_forge/modules/audit/service.py`、`tests/unit/test_publish_feedback_loop.py` | 即使 publish gate decision 被改成 ready，缺 gate evidence 仍阻断 |
| P1-RUNTIME-NAMING-001 | P1 | runtime 仍暴露 V5 命名 | API/CLI/包版本/模块占位文案统一为 v6/Novel OS | `pyproject.toml`、`src/novel_forge/api/app.py`、`src/novel_forge/__init__.py`、`src/novel_forge/modules/*/__init__.py` | `rg "5.0.0|Novel Forge V5|V5 workflows" src tests pyproject.toml` 无命中 |
| P1-EXCEPTION-POLICY-001 | P1 | broad exception 会静默掩盖扫描/存储故障 | 新增 `core.exception_policy` 并接入 storage reference scan、publishing scan、audit scan、agent scheduler scan helper | `src/novel_forge/core/exception_policy.py`、`src/novel_forge/storage/local.py`、`src/novel_forge/modules/publishing/service.py`、`src/novel_forge/modules/audit/service.py`、`src/novel_forge/modules/agent_scheduler/service.py` | exception policy 单测通过，非 recoverable 错误不再被吞 |
| P1-SERVICE-SEAMS-002 | P1 | `mkaos/service.py`、`product.py`、`workflow_nodes/service.py` 仍承担大量只读扫描/query/index 职责，且扫描类 broad exception 仍会吞掉权限/系统错误 | 新增统一资产扫描 seam、MKAOS asset index、Product asset index、Workflow query 模块；Product/Workflow/MKAOS 扫描类异常改为 recoverable-only policy，Postgres read fallback 接入显式环境策略 | `src/novel_forge/core/asset_scan.py`、`src/novel_forge/modules/mkaos/asset_index.py`、`src/novel_forge/api/services/product_asset_index.py`、`src/novel_forge/modules/workflow_nodes/query.py`、三处 service、`tests/unit/test_asset_scan_seams.py` | characterization tests 通过；MKAOS 目标 service `except Exception` 清零；Product/Workflow 扫描类异常不再吞 Permission/OSError |
| P0-RELEASE-PACKAGE-004 | P0 | release package 缺完整 production-ready 正向样本 | 新增 schema-backed ready publish gate fixture，覆盖 production envelope、passed EvaluationGate、passed ProviderRuntimeGate、PlatformStrategyPack、clean MKAOS risk、ReviewIssue clear，最终 release package `status=ready` | `tests/unit/publishing_fixtures.py`、`tests/unit/test_publish_feedback_loop.py` | 正向 release package fixture 通过 |
| P0-SCHEDULER-RELEASE-001 | P0 | Agent Scheduler release runner 没有把 environment/envelope/source_policy 传入 publishing facade | `_run_release_package` 传入 production runtime policy；新增 scheduler 测试断言 release package 使用 evidence 中的 `asset_type=release_package` envelope 和 source policy marker | `src/novel_forge/modules/agent_scheduler/service.py`、`tests/unit/test_agent_registry_scheduler_integration.py` | scheduler release package production policy 测试通过 |
| P1-SERVICE-SEAMS-003 | P1 | `agent_scheduler/service.py` runner 逻辑继续集中在主 service | 新增 `agent_scheduler.publishing_runners`，先抽 publish gate/release package runner seam | `src/novel_forge/modules/agent_scheduler/publishing_runners.py`、`src/novel_forge/modules/agent_scheduler/service.py` | scheduler/publish focused tests 通过 |
| P1-EXCEPTION-POLICY-002 | P1 | audit asset reference lookup 仍有扫描类 broad exception | `_asset_by_reference` 接入 `core.asset_scan.read_json_for_scan`，非 recoverable 错误 fail-closed | `src/novel_forge/modules/audit/service.py` | publish/audit focused tests 通过 |
| P1-SCHEDULER-SEAMS-004 | P1 | `agent_scheduler/service.py` 仍直接承担 queue claim/lease/status projection | 新增 `agent_scheduler.queue_lifecycle`，迁出 dispatch id、queue path、resolve、lease expiry、claim、status update、row projection；`_fail_queue_item` 保留 orchestration 但收窄 dead-letter/failure-report 副作用异常 | `src/novel_forge/modules/agent_scheduler/queue_lifecycle.py`、`src/novel_forge/modules/agent_scheduler/service.py` | scheduler focused tests 通过 |
| P1-PUBLISH-FACADE-004 | P1 | release package gate evidence 判定仍沉在 audit implementation | 新增 `publishing.release_gate.release_package_gate_evidence` 并由 audit release package 调用，发布阻断证据策略开始迁入 publishing module | `src/novel_forge/modules/publishing/release_gate.py`、`src/novel_forge/modules/publishing/__init__.py`、`src/novel_forge/modules/audit/service.py` | publish feedback tests 通过 |
| P1-EXCEPTION-POLICY-003 | P1 | Product/Workflow 展示和调度扫描路径仍有可收窄 broad exception | qdrant preview 只降级缺失/无效资产；workflow scheduler candidates/prepared agent scan 接入 `read_json_for_scan`；resume/node lookup 和 asset refs 改为 FileNotFound/ValueError-only | `src/novel_forge/api/services/product.py`、`src/novel_forge/modules/workflow_nodes/service.py` | workflow/product focused tests 通过 |

## Test Log

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_runtime_profiles` | 通过 | 3 个单测通过 |
| `python3 -m compileall -q src/novel_forge/agents tests/unit/test_agent_runtime_profiles.py` | 通过 | Agent runtime 和新增测试语法检查通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_runtime_profiles tests.unit.test_agent_registry tests.unit.test_agent_operation_mkaos_coverage` | 通过 | 10 个 Agent runtime/registry/MKAOS coverage 测试通过 |
| `python3 -m compileall -q src tests/unit/test_agent_runtime_profiles.py` | 通过 | 全 `src` 语法检查通过 |
| `make check-skills` | 通过 | `skills/` 与 `.claude/skills/` runtime copy 无 drift |
| `PYTHONPATH=src python3 -m novel_forge.cli validate --root /private/tmp/novel-forge-full-audit-validate` | 通过 | 干净临时 workspace validation passed |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_claude_handoff tests.unit.test_product_api.ProductApiTests.test_binding_batch_handoff_output_auto_continues_item tests.unit.test_agent_runtime_profiles` | 通过 | 纠正 `hot-novel-deconstruction` Agent 归属后，handoff/product/runtime 定向回归通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_publishing_center tests.unit.test_agent_runtime_profiles tests.unit.test_review_issue tests.unit.test_publish_feedback_loop` | 通过 | 15 个 publishing facade、review issue、publish feedback、runtime 回归测试通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_large_service_seams tests.unit.test_agent_registry_scheduler_integration tests.unit.test_agent_operation_mkaos_coverage tests.unit.test_evaluation_center_general tests.unit.test_publish_feedback_loop` | 通过 | 24 个本轮新增/受影响测试通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_publishing_center tests.unit.test_review_issue tests.unit.test_mkaos_isolation tests.unit.test_mkaos_agent_context_contract tests.unit.test_longform_stability tests.unit.test_workflow_executor tests.unit.test_agent_scheduler tests.unit.test_loop_kernel` | 通过 | 60 个 publishing/workflow/agent/MKAOS 相关回归通过 |
| `PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_12_chapter_industrial_pressure` | 通过 | 12 章 Novel OS 压力切片通过 |
| `make test` | 通过 | Python 496 tests OK，2 skipped；Web admin node tests 10 passed，1 optional Playwright smoke skipped |
| `git diff --check` | 通过 | 无 whitespace error |
| `PYTHONPATH=src python3 -m compileall -q src tests` | 通过 | 全源码和测试语法检查通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop tests.unit.test_provider_hard_stop_proof tests.unit.test_runtime_policy` | 通过 | 19 个 publish/provider/runtime policy 测试通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_registry_scheduler_integration tests.unit.test_agent_operation_mkaos_coverage tests.unit.test_exception_policy tests.unit.test_cli` | 通过 | 21 个 Agent operation、MKAOS coverage、exception policy、CLI 测试通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_asset_scan_seams tests.unit.test_large_service_seams` | 通过 | 7 个 service seam/asset scan characterization tests 通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_asset_scan_seams tests.unit.test_large_service_seams tests.unit.test_product_api` | 通过 | 45 个 Product/API/seam 回归通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_workflow_executor tests.unit.test_agent_workflow_and_impact tests.unit.test_agent_scheduler` | 通过 | 38 个 workflow/scheduler 回归通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_professional_book_import tests.unit.test_mkaos_canon_semantic_graph tests.unit.test_mkaos_quality_score tests.unit.test_mkaos_longitudinal_learning` | 通过 | 7 个受影响 MKAOS 回归通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop.PublishFeedbackLoopTests.test_release_package_production_ready_fixture_creates_ready_package tests.unit.test_agent_registry_scheduler_integration.AgentRegistrySchedulerIntegrationTests.test_scheduler_release_package_preserves_production_runtime_policy` | 通过 | P0 release positive fixture 与 scheduler production policy 测试通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop tests.unit.test_agent_registry_scheduler_integration tests.unit.test_asset_scan_seams tests.unit.test_large_service_seams` | 通过 | 24 个 publishing/scheduler/seam 回归通过 |
| `python3 -m py_compile src/novel_forge/modules/agent_scheduler/service.py src/novel_forge/modules/agent_scheduler/queue_lifecycle.py src/novel_forge/modules/audit/service.py src/novel_forge/modules/publishing/release_gate.py src/novel_forge/modules/publishing/__init__.py src/novel_forge/modules/workflow_nodes/service.py src/novel_forge/api/services/product.py` | 通过 | 本轮新增/修改模块语法检查通过 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_agent_registry_scheduler_integration tests.unit.test_publish_feedback_loop tests.unit.test_workflow_executor tests.unit.test_product_api tests.unit.test_large_service_seams tests.unit.test_asset_scan_seams` | 通过 | 99 个 scheduler/publishing/workflow/product/seam focused regression 通过 |

## Correction During Validation

第一轮 `make test` 暴露 `hot-novel-deconstruction` 被误映射到 Analysis Agent 后，`decomposition_report` handoff 失去 `write_decomposition_report` 权限。复查 `skills/hot-novel-deconstruction/SKILL.md` 后确认该 Skill 的工程产物是 `decomposition_report`，且 Skill 自身标注 Agent 为 Knowledge/Material/Chief Editor。已将该 Skill 映射回 Knowledge Agent，并保留其他新增 profile/alias/map 覆盖。

## Next

1. 继续迁移非 publish gate 的 audit 调用边界，保留 audit 为 implementation detail。
2. 在已有 seam tests 保护下继续拆 MKAOS/product/workflow/scheduler 大 service；下一批优先 agent scheduler registry/dead-letter runner、Product task control/search storage、Workflow gate/rollback helpers。
3. 将 Postgres fallback policy 暴露到 health/system diagnostics。
4. 分批治理 `workflow_nodes/service.py`、`product.py` 内剩余 broad exception；`mkaos/service.py` 本轮已清零目标文件内 `except Exception`。
5. 将 release package 正向 production-ready fixture 扩展到 end-to-end publish gate generator，而不只使用 ready publish gate fixture。
