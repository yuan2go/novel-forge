# Evaluation Center

日期：2026-07-04

## 功能目标

Evaluation Center 从模型 benchmark 扩展为 Novel OS 持续质量评估体系，覆盖内容质量、长篇一致性、工程质量和平台适配。它服务 Agent Registry、Prompt Registry、Model Router、ReviewIssue、Publish Gate、Longform Recap 和 Analytics。

## 当前实现

核心模块：

- `src/novel_forge/modules/evaluation_center/service.py`
- `src/novel_forge/api/routers/evaluation.py`
- `web/admin/app/features/evaluation/EvaluationCenterPage.tsx`

保留能力：

- `model_profile`
- `model_benchmark_task`
- `model_benchmark_run`
- `model_comparison_report`
- `model_routing_policy`
- `prompt_version`
- `prompt_regression_report`

新增能力：

- `evaluation_suite`
- `evaluation_case`
- `evaluation_run`
- `evaluation_result`
- `evaluation_metric`
- `evaluation_gate`
- `evaluation_regression_report`
- `evaluation_dashboard_snapshot`

## 评测维度

内容质量：

- readability
- hook_strength
- emotional_curve
- conflict_density
- plot_progress
- character_motivation
- scene_vividness
- dialogue_quality
- ai_flavor_risk
- originality_risk

长篇一致性：

- canon_consistency
- character_drift
- arc_progress
- foreshadowing_tracking
- power_scale_consistency
- timeline_consistency
- world_rule_consistency

工程质量：

- schema_validity
- context_adherence
- source_isolation
- os_envelope_coverage
- trace_coverage
- cost_budget
- latency
- failure_rate
- rollback_readiness

平台适配：

- opening_gate
- chapter_rhythm
- platform_retention_risk
- publish_compliance
- feedback_backflow_quality

## API

- `GET /product/evaluation/suites`
- `POST /product/evaluation/suite`
- `POST /product/evaluation/case`
- `POST /product/evaluation/run-suite`
- `POST /product/evaluation/evaluate-asset`
- `POST /product/evaluation/evaluate-agent-run`
- `POST /product/evaluation/evaluate-workflow-run`
- `POST /product/evaluation/evaluate-context`
- `POST /product/evaluation/evaluate-longform`
- `POST /product/evaluation/evaluate-platform-fit`
- `POST /product/evaluation/evaluation-gate`
- `POST /product/evaluation/regression-report`
- `GET /product/evaluation/dashboard`

原有 model/prompt benchmark API 保持兼容。

## UI

- `/evaluation`

页面已展示通用 EvaluationResult 和 EvaluationGate，不再只看模型 benchmark。

## 测试

- `tests/unit/test_evaluation_center_general.py`
- `tests/integration/test_novel_os_governance_loop.py`

## 当前限制

- 当前评分器是 deterministic local heuristic，不调用真实模型。
- Evaluation Gate 已可生成 ReviewIssue，但 Publish Gate 对 EvaluationGate 的读取仍可继续深化。

## 后续扩展

- 为 Agent Registry active promotion 加强制 EvaluationGate。
- Prompt 发布前强制 regression gate。
- 将 EvaluationResult 投影到 ClickHouse 并形成长期质量趋势。
