# Novel OS Final Change Report

日期：2026-07-05  
基线 commit：`8733acf`
分支：`backup/v6-post-mkaos-industrialization-20260705`  

## 本轮完成

本轮完成完整工程体检的第一批交付：代码地图、功能清单、Agent 审计、架构审计、目标架构、代码质量审计、临时方案登记、数据模型审计、性能可靠性审计、Novel OS 完成度评估、Skill 使用日志、优化执行日志。

同时完成一个低风险 P0 代码修复：项目源 Skill 到 Agent runtime profile 的映射全部显式化，并为目标 Agent 名称增加 alias。

追加执行了第二批 P1 硬化：Longform Recap 真实注册为 Longform Recap Agent operation；EvaluationGate/PublishGate 接入 provider runtime hard-stop；生产调用迁移到 publishing facade；为 MKAOS/product/workflow 大服务建立 characterization seam；Postgres/local fallback 改为显式策略。

继续完成第三批关键修复：Platform Compliance 和 Training 注册为可调度 Agent operation；provider runtime policy 增加成功 guard/model_call 证据要求；release package 自身校验 EvaluationGate、ProviderRuntimeGate、PlatformStrategyGate；运行时版本命名统一为 Novel Forge v6 / Novel OS；新增 exception policy 并接入高风险扫描路径。

## 代码变更

| 文件 | 变更 |
| --- | --- |
| `src/novel_forge/agents/runtime.py` | 新增 `platform_strategy`、`longform_recap`、`training` runtime profile；新增 `AGENT_PROFILE_ALIASES`；扩展所有 root Skill 的 `SKILL_AGENT_MAP` |
| `src/novel_forge/agents/__init__.py` | 导出 `AGENT_PROFILE_ALIASES` |
| `src/novel_forge/modules/publishing/service.py` | 新增 publish gate 和 release package 的 publishing-domain facade，委托现有 audit implementation |
| `src/novel_forge/modules/publishing/__init__.py` | 导出 publishing facade |
| `src/novel_forge/modules/agent_scheduler/service.py` | `run-longform-recap` 改由 `longform_recap` Agent 执行；修复 `local-system` metadata 覆盖 evidence project_id 的问题；publish runner 改用 publishing facade |
| `src/novel_forge/modules/evaluation_center/service.py` | EvaluationGate 增加 provider runtime policy 摘要和 required block 选项 |
| `src/novel_forge/modules/audit/service.py` | PublishGate 增加 provider runtime gate，生产环境缺失/失败 provider hard-stop evidence 时阻断 |
| `src/novel_forge/modules/runtime_policy/service.py` | publish gate runtime policy 增加 `evaluation_gate` 与 `provider_runtime_guard` 必要 gate |
| `src/novel_forge/core/exception_policy.py` | 新增资产扫描异常分类策略 |
| `pyproject.toml`、`src/novel_forge/__init__.py`、`src/novel_forge/api/app.py`、`src/novel_forge/cli/__init__.py` | 运行时版本和描述统一到 Novel Forge v6 / Novel OS |
| `src/novel_forge/api/services/postgres_fallback_policy.py` | 新增 Postgres/local read fallback 显式策略 |
| `src/novel_forge/modules/mkaos/risk_policy.py` | 从 MKAOS 大 service 抽出风险等级/惩罚/原因规则 |
| `src/novel_forge/modules/workflow_nodes/publishing_ops.py` | 从 workflow_nodes 大 service 抽出 publish gate/release package operation seam |
| `tests/unit/test_agent_runtime_profiles.py` | 新增 Agent alias 和 Skill map 防漂移单测 |
| `tests/unit/test_publishing_center.py` | 发布中心测试改用 publishing facade 创建 gate/package |
| `tests/unit/test_agent_registry_scheduler_integration.py` | 新增 Longform Recap Agent scheduler 执行级测试 |
| `tests/unit/test_large_service_seams.py` | 新增三类大 service seam characterization tests |
| `tests/unit/test_evaluation_center_general.py`、`tests/unit/test_publish_feedback_loop.py` | 增加 provider runtime hard-stop gate、provider success fixture、release gate evidence hard-stop 测试 |
| `tests/unit/test_exception_policy.py` | 新增异常策略单测 |
| `docs/reports/novel-os-*.md` | 新增本轮要求的审计和执行报告 |

## 当前系统判断

Novel Forge 已经形成 Novel OS 第一生产片：OS Envelope、Context Builder、ReviewIssue、AgentRun、Scheduler、MKAOS、Continuity、Eval、Publish Gate 和 UI 管理台都有真实实现。

仍未达到完整 Novel Operating System：Agent operation coverage、Eval hard-stop、longform recap Agent 化、publish/rollback 闭环、大 service 拆分、长篇压力测试和 UI 可操作深度仍是主要差距。

## 已修复临时方案

- `TEMP-011`：Agent Skill map drift。已通过代码和测试修复。
- `TEMP-010`：Publishing 边界分散。已新增 publishing facade，并迁移生产调用和相关测试；audit 内部仍保留实现委托。
- `TEMP-009`：Longform Recap 半接入。已将 scheduler operation 绑定到 Longform Recap Agent，并用执行级测试覆盖。
- `TEMP-005`：Postgres/local fallback。已新增显式 fail-open/fail-closed policy，API `/assets` strict mode 不再 silent fallback。

## 尚未修复的最高风险

1. `api/services/product.py`、`modules/mkaos/service.py`、`modules/workflow_nodes/service.py`、`modules/agent_scheduler/service.py` 过大。
2. Publish Gate 实现仍在 audit module，publishing facade 已成为生产入口，但后续可继续把实现迁出 audit。
3. 大 service 拆分仍处于 seam 阶段，尚未完成结构性拆解。
4. 部分 broad exception 仍存在，已建立策略但需要继续逐模块接入。
5. Release package 已有负向证据 hard-stop，后续还应补完整 production-ready 正向 package fixture。

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

`make test` 结果：Python 490 tests OK，2 skipped；Web admin node tests 10 passed，1 optional Playwright smoke skipped。

## 验证中纠正的问题

第一轮全量测试发现 `hot-novel-deconstruction` 不应映射到 Analysis Agent。复查 Skill 后确认它的 schema-backed 产物是 `decomposition_report`，且需要 `write_decomposition_report` 权限；因此映射回 Knowledge Agent，并保留完整 Skill map 和 alias 防漂移测试。
