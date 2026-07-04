# ClickHouse Analytics

日期：2026-07-04

## 功能目标

ClickHouse Analytics 是可选 OLAP 统计层，只承接分析事件，不写回业务主数据。它不替代 PostgreSQL、LocalStorage、pgvector 或 Qdrant。默认 offline，不影响 `make local-up` 和默认测试。

## 当前实现

核心模块：

- `src/novel_forge/modules/clickhouse_analytics/service.py`
- `src/novel_forge/api/routers/clickhouse_analytics.py`
- `web/admin/app/features/governance/GovernancePages.tsx`

能力：

- ClickHouse capabilities。
- schema plan。
- migration dry-run。
- LocalStorage -> analytics_event projection。
- offline dashboard snapshot。
- quality / agent / evaluation / cost / feedback metrics。
- online sync opt-in。

## 数据资产

- `analytics_event`
- `analytics_sync_job`
- `analytics_dashboard_snapshot`
- `analytics_metric_definition`

## 事件来源

- AgentRun / AgentEvent / AgentBudget / AgentFailureReport / AgentRollbackReport。
- TraceSpan / GateResult / ModelCallLog / CostLedger。
- ReviewIssue。
- EvaluationResult / EvaluationRun / EvaluationGate / ModelBenchmarkRun。
- ContextBundle / RagQualityReport / HybridRetrievalReport。
- PublishGateReport / ReleasePackage。
- FeedbackInsight / ReaderSentimentReport / ReaderFeedbackBackflowReport。
- LoopRun / LoopStep / LoopReport。
- LongformRecapReport / QualityScoreReport / ChapterAuditReport。

## API

- `GET /product/analytics/capabilities`
- `POST /product/analytics/schema-plan`
- `POST /product/analytics/migrate`
- `POST /product/analytics/sync`
- `GET /product/analytics/quality-trends`
- `GET /product/analytics/agent-metrics`
- `GET /product/analytics/evaluation-metrics`
- `GET /product/analytics/cost-metrics`
- `GET /product/analytics/feedback-metrics`
- `POST /product/analytics/dashboard-snapshot`

## 环境变量

- `NOVEL_FORGE_CLICKHOUSE_URL`
- `NOVEL_FORGE_CLICKHOUSE_DATABASE`
- `NOVEL_FORGE_CLICKHOUSE_USER`
- `NOVEL_FORGE_CLICKHOUSE_PASSWORD`
- `NOVEL_FORGE_CLICKHOUSE_ONLINE`
- `NOVEL_FORGE_CLICKHOUSE_STRICT`

## 本地 Docker 验证

`docker-compose.yml` 增加了可选 `analytics` profile 下的 ClickHouse：

```bash
make online-backends-up
make online-backends-smoke
```

等价手动命令：

```bash
docker compose --profile analytics up -d postgres clickhouse
NOVEL_FORGE_CLICKHOUSE_ONLINE=1 \
NOVEL_FORGE_CLICKHOUSE_URL=http://localhost:8123 \
NOVEL_FORGE_CLICKHOUSE_DATABASE=novel_forge \
NOVEL_FORGE_CLICKHOUSE_USER=novel_forge \
NOVEL_FORGE_CLICKHOUSE_PASSWORD=novel_forge \
PYTHONPATH=src python3 scripts/verify_online_backends.py --project-id local-online --require-online
```

## UI

- `/analytics`

默认展示 offline projection 指标，并可手动 sync / snapshot。

## 测试

- `tests/unit/test_clickhouse_analytics.py`
- `tests/integration/test_novel_os_governance_loop.py`

## 当前限制

- 默认只生成本地 analytics_event，不连接真实 ClickHouse；本地 Docker online proof 需要显式开启环境变量。
- online HTTP 写入是 PoC，不包含复杂分区、TTL、物化视图和权限。

## 后续扩展

- 增加 ClickHouse online migrate/sync/query smoke。
- 增加 Editor-in-Chief 趋势图和 SLA dashboard。
