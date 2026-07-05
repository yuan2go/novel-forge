# Novel OS Temporary Solutions Register

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：临时方案、fallback、mock、placeholder、兼容层、技术债。  

| ID | 位置 | 类型 | 当前实现 | 风险 | 推荐最优方案 | 优先级 | 是否已修复 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TEMP-001 | `src/novel_forge/api/services/product.py` | 过大 facade | 一个文件承载大量 product API use cases | API/domain 边界不清，回归成本高 | 按 project/assets/agent/mkaos/publish 拆 application service | P1 | 否 |
| TEMP-002 | `src/novel_forge/modules/mkaos/service.py` | 过大 service | MKAOS 多职责集中 | 知识资产核心难维护 | 拆 ingestion、selection、quality、lineage、asset writer | P1 | 否 |
| TEMP-003 | `src/novel_forge/modules/workflow_nodes/service.py` | 过大 service | workflow node 执行和恢复集中 | 状态机错误难隔离 | 拆 executor、state transition、recovery、gate runner | P1 | 否 |
| TEMP-004 | `src/novel_forge/modules/agent_scheduler/service.py` | 过大 service | registry、lease、retry、dead-letter 集中 | 调度变更风险高 | 拆 queue lease、registry、runner、dead-letter policy | P1 | 否 |
| TEMP-005 | `src/novel_forge/api/app.py` | fallback | Postgres list 失败可 fallback 到 local asset list | 严格环境可能掩盖 DB 故障 | 按环境策略显式 fail-open/fail-closed，并记录 ReviewIssue/audit event | P1 | 否 |
| TEMP-006 | `pyproject.toml`、`api/app.py` | 版本漂移 | 包版本/API title 仍有 V5 命名 | 文档和运行面沟通不一致 | 统一 v6/Novel OS runtime 标识，保留兼容版本说明 | P1 | 否 |
| TEMP-007 | `modules/*/__init__.py` | placeholder | 若干包说明仍是占位式 | 低风险但影响导航 | 改为真实模块职责说明 | P2 | 否 |
| TEMP-008 | `model_adapters/mock.py`、`mkaos_model_extraction/provider_runner.py` | mock/offline | mock provider 可生成 deterministic response | 若进入生产主链会产生伪结果 | provider runtime policy 生产 fail-closed；测试显式 mock | P0/P1 | 否 |
| TEMP-009 | `modules/longform_recap/service.py` | 半接入 | 复盘可 writeback，但顶层未完全 AgentOperation 化 | trace/cost/retry/checkpoint 不统一 | 包装为 Longform Recap Agent operation | P1 | 否 |
| TEMP-010 | `modules/audit/service.py`、`modules/publishing/service.py` | 边界分散 | publish gate 在 audit，publishing 处理 plan/log | 发布 Agent 职责不直观 | publishing facade 委托 audit gate implementation | P1 | 部分：facade 已新增，调用方迁移待做 |
| TEMP-011 | `agents/runtime.py` | runtime drift | root Skills 原先未全部显式映射 Agent profile | Agent 权限/职责 fallback 到 Quality Agent | 所有 root Skill 显式 mapping + alias test | P0 | 是 |
| TEMP-012 | `storage/*`、`workflow_nodes/*` | broad exception | 多处宽异常捕获 | 可能静默失败 | 分类异常、记录 trace、按 policy fail | P1/P2 | 否 |
| TEMP-013 | `workflows/pipeline.py` | compatibility facade | 生产步骤 wrapper 保留兼容入口 | 可能成为第二套生产链路 | wrapper 只委托唯一 application service，并加 coverage test | P1 | 否 |

## 当前统计

- 登记临时方案：13 项。
- 本轮修复：1 项，`TEMP-011`。
- 剩余 P0/P1 风险：主要集中在 provider mock hard-stop、fallback 策略、Agent operation 覆盖、大 service 拆分。
