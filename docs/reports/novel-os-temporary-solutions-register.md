# Novel OS Temporary Solutions Register

审计日期：2026-07-05  
基线 commit：`8733acf`
本轮继续治理基线 commit：`2f1f0bc`
范围：临时方案、fallback、mock、placeholder、兼容层、技术债。  

| ID | 位置 | 类型 | 当前实现 | 风险 | 推荐最优方案 | 优先级 | 是否已修复 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TEMP-001 | `src/novel_forge/api/services/product.py` | 过大 facade | 一个文件承载大量 product API use cases | API/domain 边界不清，回归成本高 | 按 project/assets/agent/mkaos/publish 拆 application service | P1 | 部分：已新增 Postgres fallback policy seam 和 `product_asset_index` 只读索引 seam |
| TEMP-002 | `src/novel_forge/modules/mkaos/service.py` | 过大 service | MKAOS 多职责集中 | 知识资产核心难维护 | 拆 ingestion、selection、quality、lineage、asset writer | P1 | 部分：已抽出 risk policy seam 和 `mkaos.asset_index` |
| TEMP-003 | `src/novel_forge/modules/workflow_nodes/service.py` | 过大 service | workflow node 执行和恢复集中 | 状态机错误难隔离 | 拆 executor、state transition、recovery、gate runner | P1 | 部分：已抽出 publishing ops seam 和 `workflow_nodes.query` |
| TEMP-004 | `src/novel_forge/modules/agent_scheduler/service.py` | 过大 service | execution/rollback orchestration 仍集中，queue lifecycle、registry catalog、dead-letter runner 已开始迁出 | 调度变更风险高 | 拆 queue lifecycle、registry、runner、dead-letter policy | P1 | 部分：已补 Platform/Training operation coverage，并抽出 publishing runner seam、`queue_lifecycle`、`operation_registry`、`dead_letter_runner` |
| TEMP-005 | `src/novel_forge/api/app.py` | fallback | Postgres list 失败可 fallback 到 local asset list | 严格环境可能掩盖 DB 故障 | 按环境策略显式 fail-open/fail-closed，并记录 ReviewIssue/audit event | P1 | 部分：API read fallback 已显式策略化 |
| TEMP-006 | `pyproject.toml`、`api/app.py` | 版本漂移 | 包版本/API title 曾保留 V5 命名 | 文档和运行面沟通不一致 | 统一 v6/Novel OS runtime 标识，保留兼容版本说明 | P1 | 是：API、CLI、包版本已统一 v6/Novel OS |
| TEMP-007 | `modules/*/__init__.py` | placeholder | 若干包说明仍是占位式 | 低风险但影响导航 | 改为真实模块职责说明 | P2 | 是：运行时模块占位文案已改为 v6 module 描述 |
| TEMP-008 | `model_adapters/mock.py`、`mkaos_model_extraction/provider_runner.py` | mock/offline | mock provider 可生成 deterministic response | 若进入生产主链会产生伪结果 | provider runtime policy 生产 fail-closed；测试显式 mock | P0/P1 | 部分：provider policy 现在要求 hard-stop 四维证据 + 成功 guard/model_call 证据 |
| TEMP-009 | `modules/longform_recap/service.py` | 半接入 | 复盘可 writeback，但顶层未完全 AgentOperation 化 | trace/cost/retry/checkpoint 不统一 | 包装为 Longform Recap Agent operation | P1 | 是：scheduler operation 已绑定 Longform Recap Agent |
| TEMP-010 | `modules/audit/service.py`、`modules/publishing/service.py` | 边界分散 | publish gate 主实现仍在 audit，release package 主实现已迁入 publishing | 发布 Agent 职责不直观 | publishing module 拥有 gate/package 实现，audit 仅保留审计报告 | P1 | 部分：生产调用已迁移，release gate evidence 和 release package 主实现已迁到 publishing；publish gate 主 implementation 仍在 audit |
| TEMP-011 | `agents/runtime.py` | runtime drift | root Skills 原先未全部显式映射 Agent profile | Agent 权限/职责 fallback 到 Quality Agent | 所有 root Skill 显式 mapping + alias test | P0 | 是 |
| TEMP-012 | `storage/*`、`workflow_nodes/*`、`product.py`、`agent_scheduler/*` | broad exception | 多处宽异常捕获，外部系统/副作用隔离路径仍需分批治理 | 可能静默失败 | 分类异常、记录 trace、按 policy fail | P1/P2 | 部分：新增 `core.exception_policy` 和 `core.asset_scan`，已接入 storage/audit/publishing/agent scan、audit reference lookup、Product/Workflow/MKAOS 只读资产扫描；qdrant preview、workflow scheduler scan、asset refs、scheduler dead-letter 副作用已收窄；`mkaos/service.py` 目标 broad exception 已清零 |
| TEMP-013 | `workflows/pipeline.py` | compatibility facade | 生产步骤 wrapper 保留兼容入口 | 可能成为第二套生产链路 | wrapper 只委托唯一 application service，并加 coverage test | P1 | 否 |

## 当前统计

- 登记临时方案：13 项。
- 已修复：`TEMP-006`、`TEMP-007`、`TEMP-009`、`TEMP-011`。
- 部分修复：`TEMP-001`、`TEMP-002`、`TEMP-003`、`TEMP-004`、`TEMP-005`、`TEMP-008`、`TEMP-010`、`TEMP-012`。
- 剩余 P0/P1 风险：主要集中在大 service 继续拆分、audit publish gate 主实现迁移、mock provider 生产禁用策略深化、Product/Workflow 外部系统与副作用路径 broad exception 后续分批治理。
