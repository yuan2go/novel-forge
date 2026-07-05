# Novel OS Optimization Execution Log

审计日期：2026-07-05  
基线 commit：`534d195`  
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
| `make test` | 通过 | Python 485 tests OK，2 skipped；Web admin node tests 10 passed，1 optional Playwright smoke skipped |
| `git diff --check` | 通过 | 无 whitespace error |

## Correction During Validation

第一轮 `make test` 暴露 `hot-novel-deconstruction` 被误映射到 Analysis Agent 后，`decomposition_report` handoff 失去 `write_decomposition_report` 权限。复查 `skills/hot-novel-deconstruction/SKILL.md` 后确认该 Skill 的工程产物是 `decomposition_report`，且 Skill 自身标注 Agent 为 Knowledge/Material/Chief Editor。已将该 Skill 映射回 Knowledge Agent，并保留其他新增 profile/alias/map 覆盖。

## Next

1. 把 Platform Compliance、Training 纳入 operation registry coverage。
2. 将 provider runtime guard 真实成功证据纳入 release readiness fixture。
3. 继续迁移非 publish gate 的 audit 调用边界，保留 audit 为 implementation detail。
4. 在已有 seam tests 保护下继续拆 MKAOS/product/workflow/scheduler 大 service。
5. 将 Postgres fallback policy 暴露到 health/system diagnostics。
