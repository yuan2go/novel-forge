# Novel OS Full Codebase Map

审计日期：2026-07-05  
基线 commit：`534d195`  
分支：`backup/v6-post-mkaos-industrialization-20260705`  
范围：源码、测试、脚本、配置、Web 控制台、docs、Skills、数据目录结构。  

## 主要结论

当前代码库已经不是单点 prompt 工具，而是一个文件优先、可扩展到 Postgres/vector/object/graph 后端的 Novel OS 工程。核心运行面包括 `OS Envelope`、`Context Builder`、`ReviewIssue`、`AgentRun`、`Agent Scheduler`、`MKAOS`、`Eval Center`、`Publish Gate`、Web 管理台和测试资产。

主要结构风险不是“能力缺失”，而是实现集中度过高、兼容层较厚、部分入口存在 fallback/旁路路径，导致长期维护和 acceptance 闭环验证成本偏高。

## 顶层结构

| 路径 | 职责 | 审计判断 |
| --- | --- | --- |
| `src/novel_forge/api/` | FastAPI 应用、路由、DTO、产品服务 facade | 可用，但 `api/services/product.py` 过大，路由绑定层仍有过渡性质 |
| `src/novel_forge/modules/` | Novel OS 主要应用服务和领域能力 | 覆盖全面，存在大 service 和局部重复 orchestration |
| `src/novel_forge/schemas/` | 资产 schema、校验、类型声明 | schema 覆盖广，但 `schemas/base.py` 集中度高 |
| `src/novel_forge/storage/` | local/Postgres/vector/object/RAG/graph 存储适配 | 后端边界较清晰，异常处理和 fallback 策略需继续收敛 |
| `src/novel_forge/workflows/` | 生产链路 pipeline 和工业化 workflow 适配 | 仍承担兼容 facade，需减少绕过 Agent/Envelope 的直接入口 |
| `src/novel_forge/workers/` | worker、queue、dispatcher 相关执行 | 已有调度基础，需扩大真实任务覆盖 |
| `web/admin/` | Next.js 管理台 | 覆盖 Agent、MKAOS、Governance、Production Control 等页面；部分页面偏大 |
| `tests/` | unit/integration/acceptance/fixtures | 测试面较广，但大服务拆分前仍需围绕核心状态机加强回归 |
| `scripts/` | 验证、同步、smoke、本地运维 | `make sync-skills`、`make validate` 等是治理入口 |
| `skills/` | 项目源 Skill，Novel OS 业务能力源 | 源头目录，runtime copies 应由 `make sync-skills` 生成 |
| `.claude/skills/` | Claude runtime Skill copy | 不应作为源头修改 |
| `docs/` | 架构、治理、报告、路线图 | 文档丰富，但存在阶段报告堆叠，需要索引和状态归并 |
| `data/` | 示例/生产形态数据目录 | 覆盖 materials、contexts、runs、reviews、continuity、knowledge 等 |

## 模块边界

当前实际依赖方向大体为：

`web/admin -> api/routers -> api/services/product.py -> modules/* -> schemas/storage`

运行时 Agent 链路为：

`agent_scheduler -> agent_runs -> operation registry -> modules/* -> os_envelope/context_builder/review_issue/mkaos/publish/eval`

文档和 Skill 约束为：

`skills/ -> make sync-skills -> .claude/skills/ -> agents/runtime.py Skill map -> Agent profile`

合理点：

- `OS Envelope`、`Context Builder`、`ReviewIssue`、`AgentRun` 已有独立 module。
- local/Postgres/vector/object/graph 存储已通过 adapter 分层。
- Web 管理台没有直接写底层文件，主要走 API。

问题点：

- `api/services/product.py` 仍是横跨 API 和应用服务的聚合 facade。
- `workflows/pipeline.py` 保留大量兼容 wrapper，容易成为旁路入口。
- 部分 module 同时承担 domain、application、validation、persistence orchestration。
- Publish Gate 的真实实现位于 `modules/audit/service.py`，而 `modules/publishing/service.py` 主要处理 plan/log，命名边界不够直观。

## 大文件和集中度风险

| 文件 | 行数 | 风险 |
| --- | ---: | --- |
| `src/novel_forge/modules/mkaos/service.py` | 7415 | MKAOS ingestion、asset、quality、lineage 职责过度集中 |
| `src/novel_forge/api/services/product.py` | 5762 | API facade 过大，路由和领域服务演进成本高 |
| `src/novel_forge/modules/workflow_nodes/service.py` | 4820 | Workflow node 执行器过重，错误恢复和测试难以局部化 |
| `src/novel_forge/modules/agent_scheduler/service.py` | 3740 | 调度、lease、retry、dead-letter、operation coverage 集中 |
| `src/novel_forge/modules/longform_stability/service.py` | 2333 | 长篇稳定性逻辑需继续拆为 canon/arc/recap 子域 |
| `src/novel_forge/modules/feedback/service.py` | 2066 | feedback backflow 和 analytics 需分层 |
| `src/novel_forge/schemas/base.py` | 1957 | schema 注册和通用校验集中，未来迁移风险高 |
| `web/admin/app/features/assets/AssetsCenterPage.tsx` | 593 | UI 页面偏大，后续可拆 query/view/editor |
| `web/admin/app/features/mkaos/MkaosConsolePage.tsx` | 575 | 控制台页面逻辑和视图混合 |
| `web/admin/app/features/os/AgentDispatchCenterPage.tsx` | 547 | Agent Center 页面可继续拆表格、详情、actions |

## 遗留和重复信号

- `src/novel_forge/api/routers/README.md` 明确 `_bindings.py` 和 product API service facade 是过渡结构。
- `workflows/pipeline.py` 仍作为 compatibility facade 暴露大量生产步骤。
- 多个 module `__init__.py` 仍有 placeholder 描述，如 `modules/topics/__init__.py`、`modules/review/__init__.py`、`modules/knowledge/__init__.py`。
- `.local/` 和 `data/` 同时存在运行数据，需在文档中持续强调 `.local` 为本地 runtime workspace，`data` 为示例/资产目录。

## 依赖方向建议

目标方向：

`API/UI -> Application Services -> Agent/Workflow Orchestration -> Domain Services -> Storage Adapters -> File/DB/Vector/Object/Graph`

治理要求：

- 新功能不得绕过 `OS Envelope`、`Context Builder`、`ReviewIssue` 和 AgentRun 记录。
- 大 service 拆分时优先保持外部 API 稳定，用内部 coordinator 分离。
- 兼容入口只允许调用同一 production service，不允许保留第二套 prompt、schema 或 fallback 主路径。

