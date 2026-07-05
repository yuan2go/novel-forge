# Novel OS Final Change Report

日期：2026-07-05  
基线 commit：`8733acf`
本轮继续治理基线 commit：`2f1f0bc`
分支：`backup/v6-post-mkaos-industrialization-20260705`  

## 本轮完成

本轮完成完整工程体检的第一批交付：代码地图、功能清单、Agent 审计、架构审计、目标架构、代码质量审计、临时方案登记、数据模型审计、性能可靠性审计、Novel OS 完成度评估、Skill 使用日志、优化执行日志。

同时完成一个低风险 P0 代码修复：项目源 Skill 到 Agent runtime profile 的映射全部显式化，并为目标 Agent 名称增加 alias。

追加执行了第二批 P1 硬化：Longform Recap 真实注册为 Longform Recap Agent operation；EvaluationGate/PublishGate 接入 provider runtime hard-stop；生产调用迁移到 publishing facade；为 MKAOS/product/workflow 大服务建立 characterization seam；Postgres/local fallback 改为显式策略。

继续完成第三批关键修复：Platform Compliance 和 Training 注册为可调度 Agent operation；provider runtime policy 增加成功 guard/model_call 证据要求；release package 自身校验 EvaluationGate、ProviderRuntimeGate、PlatformStrategyGate；运行时版本命名统一为 Novel Forge v6 / Novel OS；新增 exception policy 并接入高风险扫描路径。

继续完成第四批 P1 工程治理：在 characterization tests 保护下继续拆 `mkaos/service.py`、`product.py`、`workflow_nodes/service.py`，新增统一资产扫描 seam、MKAOS asset index、Product asset index、Workflow query 模块；分批治理 Product/Workflow/MKAOS 中扫描类 broad exception，MKAOS 目标 service 内 `except Exception` 已清零。

继续完成第五批 P0/P1 治理：补 release package production-ready 正向 fixture；修复 Agent Scheduler release runner 没有传递 production runtime policy 的差异；抽出 agent scheduler publishing runner seam；audit reference lookup 接入 `core.asset_scan`。

继续完成第八批 P0/P1 治理：PublishGate 主实现迁入 `modules.publishing.publish_gate`，ReleasePackage 主实现迁入 `modules.publishing.release_package`；production-ready release fixture 改为通过 `create_publish_gate_report(...)` 自然生成 ready gate；Agent Scheduler 继续拆出 `scheduler_tick`、`recovery_runner`、`rollback_runner`、`execution_runner`；ModelRouter production route resolution 增加 provider allowlist、mock denylist、审批证据和 resolution 记录。

## 代码变更

| 文件 | 变更 |
| --- | --- |
| `src/novel_forge/agents/runtime.py` | 新增 `platform_strategy`、`longform_recap`、`training` runtime profile；新增 `AGENT_PROFILE_ALIASES`；扩展所有 root Skill 的 `SKILL_AGENT_MAP` |
| `src/novel_forge/agents/__init__.py` | 导出 `AGENT_PROFILE_ALIASES` |
| `src/novel_forge/modules/publishing/service.py` | 保留 publishing-domain facade，委托 publishing 内部 `publish_gate`/`release_package` 主实现 |
| `src/novel_forge/modules/publishing/__init__.py` | 导出 publishing facade |
| `src/novel_forge/modules/agent_scheduler/service.py` | `run-longform-recap` 改由 `longform_recap` Agent 执行；修复 `local-system` metadata 覆盖 evidence project_id 的问题；publish runner 改用 publishing facade；release runner 传递 environment/envelope/source_policy |
| `src/novel_forge/modules/agent_scheduler/publishing_runners.py` | 新增 publishing runner seam，封装 publish gate/release package scheduler 调用 |
| `src/novel_forge/modules/agent_scheduler/queue_lifecycle.py` | 新增 Agent dispatch queue lifecycle seam，封装 dispatch id、queue path、resolve、lease expiry、claim、status update、row projection |
| `src/novel_forge/modules/agent_scheduler/operation_registry.py` | 新增 Agent operation registry catalog seam，封装 operation spec、contract、tool resolution |
| `src/novel_forge/modules/agent_scheduler/dead_letter_runner.py` | 新增 dead-letter runner seam，封装 retry/dead-letter 状态转换和 failure report 副作用隔离 |
| `src/novel_forge/modules/agent_scheduler/scheduler_tick.py` | 新增 scheduler tick/loop orchestration seam |
| `src/novel_forge/modules/agent_scheduler/recovery_runner.py` | 新增 manual dispatch recovery seam |
| `src/novel_forge/modules/agent_scheduler/rollback_runner.py` | 新增 rollback report 和 output asset rollback seam |
| `src/novel_forge/modules/agent_scheduler/execution_runner.py` | 新增 dispatch execution result 分类 seam |
| `src/novel_forge/modules/evaluation_center/service.py` | EvaluationGate 增加 provider runtime policy 摘要和 required block 选项 |
| `src/novel_forge/modules/audit/service.py` | 保留原创性/章节审稿实现；PublishGate/ReleasePackage 同名 API 降级为 publishing wrapper；修复原创性空 plot/role 签名误判 |
| `src/novel_forge/modules/publishing/release_gate.py` | 新增 release package gate evidence 策略，生产环境要求 EvaluationGate、ProviderRuntimeGate、PlatformStrategyGate 状态和证据路径 |
| `src/novel_forge/modules/publishing/publish_gate.py` | 新增 PublishGate 主实现，负责 Context Bundle、MKAOS、Longform Stability、EvaluationGate、ProviderRuntimeGate、PlatformStrategyGate、ReviewIssue 汇总 |
| `src/novel_forge/modules/publishing/release_package.py` | 新增 ReleasePackage 主实现，负责 production gate evidence hard-stop、ReviewIssue clear、OS Envelope、rollback snapshot |
| `src/novel_forge/modules/model_router/service.py` | Production route resolution 强制 provider allowlist、mock denylist、approval evidence，并把 policy/evidence 写入 resolution |
| `src/novel_forge/modules/runtime_policy/service.py` | publish gate runtime policy 增加 `evaluation_gate` 与 `provider_runtime_guard` 必要 gate |
| `src/novel_forge/core/exception_policy.py` | 新增资产扫描异常分类策略 |
| `src/novel_forge/core/asset_scan.py` | 新增统一 JSON 资产扫描 helper，坏 JSON/编码/FileNotFound 可跳过，权限/系统错误 fail-closed |
| `pyproject.toml`、`src/novel_forge/__init__.py`、`src/novel_forge/api/app.py`、`src/novel_forge/cli/__init__.py` | 运行时版本和描述统一到 Novel Forge v6 / Novel OS |
| `src/novel_forge/api/services/postgres_fallback_policy.py` | 新增 Postgres/local read fallback 显式策略 |
| `src/novel_forge/api/services/product_asset_index.py` | 从 Product facade 抽出 asset binding/list/id lookup 只读索引 seam |
| `src/novel_forge/api/services/product.py` | 迁移 asset index 调用；source/workspace/reference/task archive/draft version 扫描接入 `read_json_for_scan`；Postgres read fallback 接入显式环境策略；qdrant preview 仅降级缺失/无效资产 |
| `src/novel_forge/modules/mkaos/asset_index.py` | 从 MKAOS service 抽出 `_find_asset`、`_list_assets`、asset row 只读索引 seam |
| `src/novel_forge/modules/mkaos/risk_policy.py` | 从 MKAOS 大 service 抽出风险等级/惩罚/原因规则 |
| `src/novel_forge/modules/mkaos/service.py` | 迁移 asset index 调用；收窄 artifact read、float parse、optional dependency import、canon graph import 异常 |
| `src/novel_forge/modules/workflow_nodes/query.py` | 从 workflow_nodes service 抽出 list node runs/workflow definitions/workflow runs query seam |
| `src/novel_forge/modules/workflow_nodes/publishing_ops.py` | 从 workflow_nodes 大 service 抽出 publish gate/release package operation seam |
| `src/novel_forge/modules/workflow_nodes/control.py` | 从 workflow_nodes 大 service 抽出 pause/cancel/retry control payload use-case seam |
| `src/novel_forge/modules/workflow_nodes/service.py` | 迁移 query 调用；resolver/checkpoint/input/report/context/scheduler scan 接入 `read_json_for_scan`；resume/node lookup 和 asset refs 收窄异常类型 |
| `src/novel_forge/api/services/product_tasks.py` | 从 Product facade 抽出 task control、queue pressure、dead-letter retry use-case seam |
| `src/novel_forge/modules/mkaos/quality.py` | 从 MKAOS 大 service 抽出 quality history、low quality、high copyright risk 查询 seam |
| `src/novel_forge/modules/model_router/service.py`、`src/novel_forge/api/routers/os_capabilities.py`、`web/admin/app/features/os/*` | 增加 provider approval evidence ops report、API endpoint 和 OS Console 可视化 |
| `tests/unit/test_agent_runtime_profiles.py` | 新增 Agent alias 和 Skill map 防漂移单测 |
| `tests/unit/test_publishing_center.py` | 发布中心测试改用 publishing facade 创建 gate/package |
| `tests/unit/test_agent_registry_scheduler_integration.py` | 新增 Longform Recap Agent scheduler 执行级测试 |
| `tests/unit/publishing_fixtures.py` | production-ready release fixture 改为准备真实 evidence 后调用 `create_publish_gate_report(...)` 自然生成 ready gate |
| `tests/unit/test_provider_hard_stop_proof.py` | 新增 production provider allowlist/mock denylist/approval evidence 测试 |
| `tests/unit/test_large_service_seams.py` | 新增三类大 service seam characterization tests |
| `tests/unit/test_asset_scan_seams.py` | 新增 core/product/MKAOS/workflow asset scan characterization tests |
| `tests/unit/test_evaluation_center_general.py`、`tests/unit/test_publish_feedback_loop.py` | 增加 provider runtime hard-stop gate、provider success fixture、release gate evidence hard-stop 测试 |
| `tests/unit/test_exception_policy.py` | 新增异常策略单测 |
| `docs/reports/novel-os-*.md` | 新增本轮要求的审计和执行报告 |

## 当前系统判断

Novel Forge 已经形成 Novel OS 第一生产片：OS Envelope、Context Builder、ReviewIssue、AgentRun、Scheduler、MKAOS、Continuity、Eval、Publish Gate 和 UI 管理台都有真实实现。

仍未达到完整 Novel Operating System：Agent operation coverage、Eval hard-stop、longform recap Agent 化、publish/rollback 闭环、大 service 拆分、长篇压力测试和 UI 可操作深度仍是主要差距。

## 已修复临时方案

- `TEMP-011`：Agent Skill map drift。已通过代码和测试修复。
- `TEMP-010`：Publishing 边界分散。PublishGate 和 ReleasePackage 主实现已迁入 publishing，audit 只保留兼容 wrapper。
- `TEMP-008`：Mock provider 生产风险。Production ModelRouter route 已强制 allowlist、mock denylist、approval evidence，mock 仅允许显式 fixture/test mode。
- `TEMP-009`：Longform Recap 半接入。已将 scheduler operation 绑定到 Longform Recap Agent，并用执行级测试覆盖。
- `TEMP-005`：Postgres/local fallback。已新增显式 fail-open/fail-closed policy，API `/assets` strict mode 不再 silent fallback。

## 尚未修复的最高风险

1. `api/services/product.py`、`modules/mkaos/service.py`、`modules/workflow_nodes/service.py`、`modules/agent_scheduler/service.py` 仍过大，但 Product/MKAOS/Workflow 已有第一批只读 seam。
2. Publish Gate 和 Release Package 主实现已迁入 publishing；后续风险转为 publishing `service.py`、adapter、plan/log 的继续拆分。
3. 大 service 拆分仍处于 seam 阶段，scheduler tick/recovery/rollback 已迁出，但 operation runners、workflow resume、workflow executor/gate、MKAOS ingestion/quality/lineage、Product search/task-control 仍需继续拆。
4. Product/Workflow 部分外部系统与副作用路径 broad exception 仍存在，已建立策略但需要继续逐模块接入；MKAOS 目标 service 本轮已清零。
5. Release package 已有 publish gate generator 端到端 ready fixture；后续应扩展到 scheduler release runner 的 full positive fixture 和 UI/ops 可观测性。
6. Provider approval evidence 已进入 OS Console 和 `/product/os/model-router/provider-approval-report`；下一步风险是审批录入/变更的 lifecycle 审计，而不是只读可观测性。

## 测试结果

已通过：

- `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_runtime_profiles`
- `python3 -m compileall -q src/novel_forge/agents tests/unit/test_agent_runtime_profiles.py`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_runtime_profiles tests.unit.test_agent_registry tests.unit.test_agent_operation_mkaos_coverage`
- `python3 -m compileall -q src tests/unit/test_agent_runtime_profiles.py`
- `make check-skills`
- `PYTHONPATH=src python3 -m novel_forge.cli validate --root /private/tmp/novel-forge-full-audit-validate`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_claude_handoff tests.unit.test_product_api.ProductApiTests.test_binding_batch_handoff_output_auto_continues_item tests.unit.test_agent_runtime_profiles`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_publishing_center tests.unit.test_agent_runtime_profiles tests.unit.test_review_issue tests.unit.test_publish_feedback_loop`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_large_service_seams tests.unit.test_agent_registry_scheduler_integration tests.unit.test_agent_operation_mkaos_coverage tests.unit.test_evaluation_center_general tests.unit.test_publish_feedback_loop`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_publishing_center tests.unit.test_review_issue tests.unit.test_mkaos_isolation tests.unit.test_mkaos_agent_context_contract tests.unit.test_longform_stability tests.unit.test_workflow_executor tests.unit.test_agent_scheduler tests.unit.test_loop_kernel`
- `PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_12_chapter_industrial_pressure`
- `make test`
- `git diff --check`
- `PYTHONPATH=src python3 -m compileall -q src tests`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop tests.unit.test_provider_hard_stop_proof tests.unit.test_runtime_policy`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_registry_scheduler_integration tests.unit.test_agent_operation_mkaos_coverage tests.unit.test_exception_policy tests.unit.test_cli`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_asset_scan_seams tests.unit.test_large_service_seams`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_asset_scan_seams tests.unit.test_large_service_seams tests.unit.test_product_api`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_workflow_executor tests.unit.test_agent_workflow_and_impact tests.unit.test_agent_scheduler`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_professional_book_import tests.unit.test_mkaos_canon_semantic_graph tests.unit.test_mkaos_quality_score tests.unit.test_mkaos_longitudinal_learning`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop.PublishFeedbackLoopTests.test_release_package_production_ready_fixture_creates_ready_package tests.unit.test_agent_registry_scheduler_integration.AgentRegistrySchedulerIntegrationTests.test_scheduler_release_package_preserves_production_runtime_policy`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop tests.unit.test_agent_registry_scheduler_integration tests.unit.test_asset_scan_seams tests.unit.test_large_service_seams`
- `python3 -m py_compile src/novel_forge/modules/agent_scheduler/service.py src/novel_forge/modules/agent_scheduler/queue_lifecycle.py src/novel_forge/modules/audit/service.py src/novel_forge/modules/publishing/release_gate.py src/novel_forge/modules/publishing/__init__.py src/novel_forge/modules/workflow_nodes/service.py src/novel_forge/api/services/product.py`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_agent_registry_scheduler_integration tests.unit.test_publish_feedback_loop tests.unit.test_workflow_executor tests.unit.test_product_api tests.unit.test_large_service_seams tests.unit.test_asset_scan_seams`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop tests.unit.test_publishing_center tests.unit.test_review_issue tests.unit.test_provider_hard_stop_proof tests.unit.test_runtime_policy tests.unit.test_workflow_executor tests.unit.test_provider_fallback_policy`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_agent_registry_scheduler_integration`
- `PYTHONPATH=src python3 -m compileall -q src tests`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop tests.unit.test_publishing_center tests.unit.test_review_issue tests.unit.test_provider_hard_stop_proof tests.unit.test_runtime_policy tests.unit.test_workflow_executor tests.unit.test_provider_fallback_policy tests.unit.test_agent_scheduler tests.unit.test_agent_registry_scheduler_integration`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_agent_registry_scheduler_integration tests.unit.test_publish_feedback_loop tests.unit.test_publishing_center tests.unit.test_review_issue tests.unit.test_mkaos_isolation tests.unit.test_large_service_seams`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_agent_registry_scheduler_integration tests.unit.test_publish_feedback_loop tests.unit.test_workflow_executor tests.unit.test_product_api tests.unit.test_large_service_seams tests.unit.test_asset_scan_seams`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_use_case_service_seams tests.unit.test_provider_hard_stop_proof`
- `npm --prefix web/admin test -- --runInBand`
- `python3 -m compileall -q src/novel_forge/api/services/product_tasks.py src/novel_forge/modules/workflow_nodes/control.py src/novel_forge/modules/mkaos/quality.py src/novel_forge/modules/model_router/service.py src/novel_forge/api/routers/os_capabilities.py src/novel_forge/api/models.py`
- `PYTHONPATH=src python3 -m unittest tests.unit.test_product_api.ProductApiTests.test_task_control_config_and_health_shape tests.unit.test_workflow_executor.WorkflowExecutorTests.test_pause_retry_and_cancel_workflow_run_controls tests.unit.test_mkaos_quality_score`
- `make test`

`make test` 结果：Python 505 tests OK，2 skipped；Web admin node tests 10 passed，1 optional Playwright smoke skipped。

本轮 focused regression 结果：新增 seam/provider 11 tests OK；既有 Product/Workflow/MKAOS focused 5 tests OK；Web admin node tests OK；新增模块 compileall OK；全量 `make test` OK。

## 验证中纠正的问题

第一轮全量测试发现 `hot-novel-deconstruction` 不应映射到 Analysis Agent。复查 Skill 后确认它的 schema-backed 产物是 `decomposition_report`，且需要 `write_decomposition_report` 权限；因此映射回 Knowledge Agent，并保留完整 Skill map 和 alias 防漂移测试。
