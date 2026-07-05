# Novel OS Final Change Report

日期：2026-07-05  
基线 commit：`534d195`  
分支：`backup/v6-post-mkaos-industrialization-20260705`  

## 本轮完成

本轮完成完整工程体检的第一批交付：代码地图、功能清单、Agent 审计、架构审计、目标架构、代码质量审计、临时方案登记、数据模型审计、性能可靠性审计、Novel OS 完成度评估、Skill 使用日志、优化执行日志。

同时完成一个低风险 P0 代码修复：项目源 Skill 到 Agent runtime profile 的映射全部显式化，并为目标 Agent 名称增加 alias。

## 代码变更

| 文件 | 变更 |
| --- | --- |
| `src/novel_forge/agents/runtime.py` | 新增 `platform_strategy`、`longform_recap`、`training` runtime profile；新增 `AGENT_PROFILE_ALIASES`；扩展所有 root Skill 的 `SKILL_AGENT_MAP` |
| `src/novel_forge/agents/__init__.py` | 导出 `AGENT_PROFILE_ALIASES` |
| `src/novel_forge/modules/publishing/service.py` | 新增 publish gate 和 release package 的 publishing-domain facade，委托现有 audit implementation |
| `src/novel_forge/modules/publishing/__init__.py` | 导出 publishing facade |
| `tests/unit/test_agent_runtime_profiles.py` | 新增 Agent alias 和 Skill map 防漂移单测 |
| `tests/unit/test_publishing_center.py` | 发布中心测试改用 publishing facade 创建 gate/package |
| `docs/reports/novel-os-*.md` | 新增本轮要求的审计和执行报告 |

## 当前系统判断

Novel Forge 已经形成 Novel OS 第一生产片：OS Envelope、Context Builder、ReviewIssue、AgentRun、Scheduler、MKAOS、Continuity、Eval、Publish Gate 和 UI 管理台都有真实实现。

仍未达到完整 Novel Operating System：Agent operation coverage、Eval hard-stop、longform recap Agent 化、publish/rollback 闭环、大 service 拆分、长篇压力测试和 UI 可操作深度仍是主要差距。

## 已修复临时方案

- `TEMP-011`：Agent Skill map drift。已通过代码和测试修复。
- `TEMP-010`：Publishing 边界分散。已新增 publishing facade，仍需后续迁移其他内部调用方。

## 尚未修复的最高风险

1. `api/services/product.py`、`modules/mkaos/service.py`、`modules/workflow_nodes/service.py`、`modules/agent_scheduler/service.py` 过大。
2. Publish Gate 实现仍在 audit module，虽然已加 publishing facade，但其他调用方仍需逐步迁移。
3. Longform Recap 仍需完整进入 AgentRun/operation registry。
4. Eval 与 provider routing/release gate 的 hard-stop 闭环不足。
5. 部分 fallback/broad exception 可能掩盖严格环境故障。

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
- `make test`
- `git diff --check`

`make test` 结果：Python 480 tests OK，2 skipped；Web admin node tests 10 passed，1 optional Playwright smoke skipped。

## 验证中纠正的问题

第一轮全量测试发现 `hot-novel-deconstruction` 不应映射到 Analysis Agent。复查 Skill 后确认它的 schema-backed 产物是 `decomposition_report`，且需要 `write_decomposition_report` 权限；因此映射回 Knowledge Agent，并保留完整 Skill map 和 alias 防漂移测试。
