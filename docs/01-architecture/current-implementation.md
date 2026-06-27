# Novel Forge V5 当前实现功能说明

更新时间：2026-06-26

本文档基于当前代码实现整理，不描述尚未落地的愿景。它用于回答三个问题：

1. Novel Forge V5 现在已经实现了哪些产品功能。
2. 后端、存储、任务、RAG、Agent、Web 管理台分别做到什么程度。
3. 当前距离正式本地生产使用还存在哪些边界和优化项。

## 1. 当前定位

Novel Forge V5 已经从单次脚本式小说生成，升级为一个本地运行的小说生产平台雏形。当前实现具备：

- 项目空间和项目生命周期管理。
- 多文件上传、导入、清洗、拆书、知识卡和素材卡生产。
- Claude Code / Codex handoff 人工执行包，用于网文拆解和多学科知识解析。
- 稿件阅读、编辑、保存、版本、diff、导出和发布记录。
- 审稿、问题状态、修订计划、修订执行和评分对比。
- 任务中心、任务事件日志、失败恢复、dead-letter、队列和 worker 健康检查。
- RAG 上下文构建，按项目检索人物、世界观、前文摘要、知识卡、伏笔和素材卡。
- Qdrant 真实向量检索，MinIO 对象存储同步，PostgreSQL 索引和 strict local-prod 检查。
- Next.js Web 管理台，支持中英文切换，并提供一个面向创作闭环的 Studio 页面。

当前系统的主工作模式仍是本地单人使用。运行态资产在 `.local/workspace/`，不再把真实运行数据纳入 Git。仓库保留 deterministic sample fixture 和测试夹具。

## 2. 总体架构

核心链路：

```text
source material
  -> cleaned text
  -> decomposition report
  -> knowledge card
  -> material card
  -> topic / world / character / outline / chapter plan
  -> draft chapter
  -> review report
  -> revision plan
  -> revised draft / export / publish record
```

工业化服务链路：

```text
Next.js Web Admin
  -> FastAPI Product API
  -> Local JSON Asset Store
  -> PostgreSQL index/write-through
  -> Redis + Celery workers
  -> Qdrant semantic retrieval
  -> MinIO object storage
```

主要代码位置：

| 层级 | 代码位置 | 说明 |
|---|---|---|
| Web 管理台 | `web/admin/app/page.tsx` | Studio、项目、任务、资产、handoff、批处理、稿件、审稿页面 |
| Web 样式 | `web/admin/app/globals.css` | 管理台布局、表格、工作台、响应式样式 |
| FastAPI 入口 | `src/novel_forge/api/app.py` | API app 创建、基础 API、请求模型 |
| Product API | `src/novel_forge/api/product.py` | 产品级项目、任务、资产、handoff、批处理、稿件、审稿、健康接口 |
| CLI | `src/novel_forge/cli/__init__.py` | 本地命令入口 |
| Pipeline | `src/novel_forge/workflows/pipeline.py` | 主流程编排、validate、workspace 更新 |
| Schemas | `src/novel_forge/schemas/` | 资产 schema 和校验 |
| Local storage | `src/novel_forge/storage/local.py` | JSON 资产读写、备份、Postgres write-through、项目写入防护 |
| PostgreSQL | `src/novel_forge/storage/postgres.py` | 资产、版本、任务、项目索引 |
| Qdrant | `src/novel_forge/storage/qdrant_index.py` | 真实向量索引、collection 兼容检查、缓存、批量 embedding |
| RAG | `src/novel_forge/storage/rag_context.py` | 项目级上下文检索构建 |
| MinIO | `src/novel_forge/storage/object_store.py` | 对象命名、上传同步 |
| Celery | `src/novel_forge/workers/` | worker、任务分发、dead-letter、post-task sync |
| Agent runtime | `src/novel_forge/agents/runtime.py` | Agent permission profile、tool allowlist、输出类型限制 |
| Handoff | `src/novel_forge/modules/handoff/service.py` | Claude Code / Codex 执行包生成 |
| 设置 | `src/novel_forge/infrastructure/settings.py` | 环境变量、服务配置、可选依赖状态 |

## 3. Web 管理台

Web 管理台是当前产品化闭环的主入口。它由 Next.js 实现，默认访问地址是 `http://localhost:3000`。

### 3.1 Studio 页面

当前首页是 Studio / 创作台，目标是让用户在一个页面中完成：

- 直接阅读小说稿件。
- 直接编辑正文。
- 保存手工修改并生成新草稿版本。
- 生成或重新生成章节草稿。
- 导出 Markdown、DOCX、EPUB。
- 查看小说生成链路。
- 查看资料来源和拆解结果。
- 区分 GitHub 拉取资料、本地上传资料、项目内部资料。
- 查看各类 Agent 当前在做什么、产出了什么、是否失败、是否等待人工确认。

Studio 页面展示的核心区域：

| 区域 | 已实现内容 |
|---|---|
| 章节选择 | 选择 chapter plan、draft、workspace |
| 阅读区 | 分段展示当前 draft 正文 |
| 编辑区 | 标题和正文 textarea，可保存为新版本 |
| 生成控制 | 生成草稿、保存草稿、导出 Markdown/DOCX/EPUB |
| 生产链路 | 展示上传、清洗、拆解、知识、素材、草稿、审稿、修订等步骤 |
| 资料来源 | GitHub source、上传源文件、batch item、handoff、资产来源 |
| 多学科知识 | 将知识卡按 GitHub 来源和本地/上传来源分组 |
| Agent 工作板 | 展示 Chief Editor、Knowledge、Material、Draft、Review、Quality、Engineering 等角色状态 |
| 系统状态 | Postgres、Qdrant、MinIO、worker、pending handoff 等摘要 |

### 3.2 其他页面

管理台保留多个专业页：

| 页面 | 功能 |
|---|---|
| Projects | 项目列表、项目配置、生命周期、项目资产 |
| Health | 项目健康、Postgres strict、Qdrant、MinIO、备份、scope audit |
| Tasks | 最新状态表、完整 timeline、过滤、分页、失败恢复、dead-letter、队列压力 |
| Assets | 资产列表、资产详情、typed panel、metadata/content/typed edit、版本、引用图谱、集合 |
| Handoffs | 创建拆书和知识 handoff、GitHub source handoff、验收、绑定输出、重试 |
| Batch | 多文件上传、版权确认、导入队列、自动拆书、Claude Code 解析模式、失败 item 重跑 |
| Drafts | 稿件生成、正文编辑、保存、版本、导出 |
| Reviews | 审稿、问题状态、修订计划、修订预览和确认 |

### 3.3 中英文切换

`web/admin/app/page.tsx` 内置中英文 copy map。页面标签、按钮、状态文案支持 English / 中文切换。

## 4. 项目空间

项目实体使用 `project_workspace_state` schema，同时 Product API 在此基础上实现了更完整的项目生命周期。

已实现：

- 项目列表。
- 创建项目。
- 项目配置更新。
- 归档、暂停、恢复。
- 软删除。
- 复制项目。
- series / 多书项目分组。
- 项目级资产列表。
- 项目级 scope audit。
- 项目健康汇总。
- 项目 ID 和 workspace path 继承。
- 跨项目 lineage 写入拒绝。
- `make validate` 执行 project-scope audit。

项目配置支持的典型字段包括：

- 题材。
- 目标字数。
- 更新频率。
- 目标平台。
- 质量阈值。
- 系列信息。

项目隔离的实现点：

- `LocalStorage._enforce_project_scope_write` 在写入时检查引用资产是否跨项目。
- `project_scope_audit` 扫描无项目资产、跨项目 lineage、handoff 输出错绑。
- `pipeline.validate_project` 默认执行 project-scope audit。
- Handoff 和 batch 产物会继承当前 `project_id`、`workspace_id`、`workspace_path`。

边界：

- 当前没有用户登录、角色权限和多租户账号隔离。Agent 权限是工作流权限，不是 Web 用户权限。
- JSON 文件仍是主要资产载体，PostgreSQL 是索引和严格同步路径，不是所有正文 payload 的唯一物理存储。

## 5. 资产系统

所有核心产物都落为 schema-backed JSON asset。共同字段由 `BaseAsset` 定义：

- `id`
- `type`
- `title`
- `name`
- `source`
- `tags`
- `created_at`
- `updated_at`
- `version`
- `content`
- `metadata`
- `references`

当前 schema 类型：

| 资产类型 | 目录 | 用途 |
|---|---|---|
| `source_document` | `data/raw` | 原始上传或导入源 |
| `cleaned_text` | `data/cleaned` | 清洗后文本和章节信息 |
| `decomposition_report` | `data/decompositions` | 网文结构、商业模式、冲突、节奏拆解 |
| `knowledge_card` | `data/knowledge` | 多学科知识、机制、约束、审稿检查 |
| `material_card` | `data/materials` | 可复用素材卡 |
| `asset_collection` | `data/materials` | 搜索结果或任务输入集 |
| `topic_seed` | `data/topics` | 选题和差异化方向 |
| `world_bible` | `data/worlds` | 世界观规则 |
| `character_card` | `data/characters` | 人物设计 |
| `outline` | `data/outlines` | 长纲 |
| `chapter_plan` | `data/chapter_plans` | 章节计划 |
| `draft_chapter` | `data/drafts` | 正文草稿 |
| `review_report` | `data/reviews` | 审稿报告 |
| `revision_plan` | `data/reviews` | 修订计划 |
| `reader_feedback` | `data/feedback` | 读者反馈导入 |
| `feedback_insight` | `data/feedback` | 反馈分析 |
| `training_exercise` | `data/training` | 写作训练 |
| `image_prompt` | `data/image_prompts` | 图像提示词 |
| `project_workspace_state` | `data/workspaces` | 项目空间状态 |
| `claude_code_handoff` | `data/runs` | Claude Code / Codex 执行包 |
| `workflow_run` | `data/runs` | 流程运行记录 |
| `task_status` | `data/runs` | 任务状态事件 |
| `task_dead_letter` | `data/runs` | 死信任务 |
| `batch_task_item` | `data/runs` | 批处理 item 级状态 |

资产工作台已实现：

- 资产详情。
- 摘要、payload、metadata、lineage。
- typed panel 专用展示。
- metadata 安全编辑。
- content 编辑并重新校验 schema。
- typed edit 表单。
- 版本和备份查看。
- 引用图谱。
- 资产集合创建。
- Handoff 专用可操作工作台。

边界：

- decomposition、knowledge、material、draft、review、revision 都已有类型化摘要和基础编辑，但还不是每种资产都拥有深度领域编辑器。

## 6. 来源合规和资料获取

系统已经把来源合规作为入库和生成前置条件。

### 6.1 上传和导入

Web 批处理页面支持：

- 浏览器多文件上传。
- 多文件预览。
- 文件格式识别。
- 去重提示。
- 版权/授权确认。
- `rights.authorization` 记录。
- `license`、`copyright_boundary` 记录。
- `allow_downstream_generation` 开关。
- MinIO 上传尝试和本地 fallback 状态记录。

CLI ingest 同样要求记录：

- `--rights`
- `--license`
- `--copyright-note`
- `--source-url`
- `--allow-downstream-generation`

`source_document` schema 校验会要求 `metadata.rights` 存在，并检查授权状态和版权边界。

### 6.2 GitHub 和外部资料

`modules/source_intake` 维护外部来源策略和 GitHub source registry。管理台可以展示 GitHub sources，并基于 `allowed_pipeline` 筛选可用于 knowledge card extraction 的来源。

当前原则：

- 能使用官方数据包的，不爬网页。
- API 优先于普通网页抓取。
- GitHub 资源先作为研究参考和知识卡输入，不直接当正文素材。
- 高风险来源必须保留 license risk 和 allowed pipeline。
- Handoff 和知识卡生成要保留来源、可信度、边界和项目上下文。

Studio 页面会把多学科知识分成：

- GitHub 来源知识。
- 本地上传或项目内部知识。

边界：

- 对老资产，来源分类依赖 metadata、handoff、batch 记录的启发式判断。新增资产应显式记录 `source_origin`、`source_policy`、`license_risk`、`allowed_pipeline`。

## 7. 批量拆书

批处理已从单一 pipeline 升级为 item/step 级模型。

### 7.1 自动模式

默认自动流程：

```text
ingest -> clean -> decompose -> extract-knowledge -> build-materials
```

已实现：

- batch 记录。
- item 级 `batch_task_item`。
- step 状态。
- item output paths。
- error message。
- 失败 item 重跑。
- 批量失败 item 重跑。
- 清洗质量和结果预览。
- 拆书结果审核 gate。
- item 级 review decision。

### 7.2 Claude Code 解析模式

Claude Code 模式用于“网文解析交给 Claude Code 调 Codex”这一工作方式。

流程：

```text
ingest -> clean -> generate handoff -> waiting_handoff
  -> operator creates DecompositionReport / KnowledgeCard
  -> bind output
  -> validate acceptance
  -> auto continue build-materials
```

已实现：

- 自动清洗后为每个 item 生成 handoff。
- item 状态停在 `waiting_handoff`。
- handoff 指向源文件、技能文件、指令、验收项、期望输出。
- 人工绑定 decomposition / knowledge 输出。
- 绑定后校验 expected output type。
- schema/type/boundary/引用校验。
- semantic review provider / rubric 质量检查。
- 验收项逐条确认。
- 失败原因记录。
- handoff 标记失败。
- 重新生成 handoff。
- 作废 handoff。
- 绑定输出后自动推进 batch item。

## 8. Claude Code / Codex Handoff

Handoff 是当前系统中对 Claude Code 的正式接入方式。它不是在后端直接调用 Claude Code API，而是生成一个边界清晰的人工执行包，由操作者在 Claude Code 中读取输入资产和技能文件，使用 Codex 完成分析，然后回填 schema-backed 输出资产。

支持的 handoff 类型：

| 类型 | skill | 期望输出 |
|---|---|---|
| 网文拆解 | `hot-novel-deconstruction` | `decomposition_report` |
| 多学科知识解析 | `multidisciplinary-knowledge` | `knowledge_card` |
| GitHub 知识解析 | `multidisciplinary-knowledge` | `knowledge_card` |

Handoff asset 记录：

- operation。
- runtime：`claude-code`。
- runtime_model：`codex`。
- skill。
- agent runtime。
- permission profile。
- tool allowlist。
- input files。
- source asset summary。
- expected output type。
- expected output directory。
- instructions。
- acceptance checks。
- validation command。
- handoff packet。
- manual execution 信息。

Handoff 工作台已实现：

- 专用渲染，不再只是普通 JSON。
- 显示源文件路径、技能、指令、验收项、期望输出、校验命令。
- 一键复制执行提示。
- 打开源资产。
- 填写输出路径。
- 校验输出。
- 绑定输出。
- 逐条验收。
- 失败标记。
- 重试生成。
- 输出绑定后自动继续 batch。

Agent 边界：

- Handoff 会记录 `agent_runtime`。
- `agents/runtime.py` 定义每类 Agent 的 allowed tools 和 allowed write types。
- 绑定输出时会检查输出类型和 Agent 权限边界。
- AGENTS.md 明确禁止复制受保护文本、绕过 schema 校验、混淆原始来源和生成资产。

## 9. RAG 和检索

代码中已经有 RAG。

核心实现是 `RagContextBuilder`：

```text
src/novel_forge/storage/rag_context.py
```

RAG 目标是为 draft、review、knowledge 等模型步骤构建项目级上下文，而不是全局混合检索。

检索范围包括：

- 人物卡。
- 世界观。
- 前文摘要。
- 知识卡。
- 素材卡。
- 伏笔和 continuity threads。
- 项目内相关资产。

检索 backend：

| backend | 行为 |
|---|---|
| `qdrant` | 强制使用 Qdrant 真实向量检索，失败则报错 |
| `local` | 使用本地索引和启发式排序 |
| `auto` | 优先 Qdrant，可用时使用 Qdrant，不可用时 fallback 到 local，并记录 backend attempts |

RAG metadata 会记录：

- `retrieved_context`
- `retrieval_query`
- `retrieval_top_k`
- `retrieval_ranker`
- `retrieval_backend`
- `retrieval_requested_backend`
- `retrieval_backend_attempts`
- `retrieval_source_asset_ids`

当前已接入：

- `modules/drafting/service.py`
- `modules/review/service.py`
- `modules/knowledge/service.py`

边界：

- 若 Qdrant 或 embedding provider 未配置，`auto` 会降级到 local。严格语义检索需要设置真实 embedding provider。
- 本地 hash vector index 保留为测试和离线 plumbing，不应视为真实语义检索。

## 10. Qdrant 向量检索

Qdrant 已经从占位接口升级为真实向量后端。

已实现：

- `qdrant-index` CLI。
- `qdrant-search` CLI。
- Web 健康页 Qdrant index/search 操作。
- FastAPI `/product/qdrant/index`。
- FastAPI `/product/qdrant/search`。
- OpenAI-compatible embedding provider。
- 禁止默认用 hash embedding 写入 Qdrant。
- collection 是否存在检查。
- vector dimension 检查。
- embedding provider / model metadata 记录。
- incompatible collection 报错并提示 `--recreate`。
- batch embedding。
- vector cache。
- resume。
- force re-embed。
- retry。
- project_id / workspace_path payload 和过滤。
- 搜索命中解释。

配置项：

- `NOVEL_FORGE_EMBEDDING_PROVIDER=openai`
- `OPENAI_API_KEY`
- `OPENAI_EMBEDDING_MODEL`
- `OPENAI_EMBEDDING_DIMENSIONS`
- `OPENAI_EMBEDDINGS_URL`
- `NOVEL_FORGE_QDRANT_URL`
- `NOVEL_FORGE_QDRANT_COLLECTION`

边界：

- 默认本地环境没有 API key 时，Qdrant 语义检索会显示未就绪。
- `NOVEL_FORGE_ALLOW_HASH_QDRANT=true` 只适合测试，不建议真实使用。

## 11. 稿件工作台

稿件工作台已从“生成草稿并查看资产”升级为基本写作编辑器。

已实现：

- 选择 chapter plan。
- 生成 draft。
- 选择 draft。
- 读取 draft 正文。
- 页面内编辑标题和正文。
- 手工保存。
- 保存为新版本。
- draft version index。
- draft status。
- diff。
- 导出 Markdown。
- 导出 DOCX。
- 导出 EPUB。
- publish record。
- 一键生成下一版草稿。
- RAG 上下文记录。

草稿资产会记录：

- 输入 chapter plan。
- retrieved context。
- provider。
- model。
- prompt/schema 相关 metadata。
- references。
- project/workspace metadata。

边界：

- 当前编辑器是 textarea 级正文编辑，不是富文本/章节级专业排版编辑器。
- DOCX/EPUB 导出是本地产品化版本，复杂排版、封面、目录、发布渠道适配仍可继续加强。

## 12. 审稿和修订流

审稿/修订已经形成闭环。

已实现：

- 运行 review。
- review report schema。
- 多模型 review comparison。
- rubric、summary、score、issues、risk level。
- issue 状态：`open`、`accepted`、`ignored`、`fixed`。
- revision plan。
- revision preview。
- 根据 revision plan 生成修订稿。
- 修订前后评分字段。
- 人工确认 gate。
- review after revision。
- Review 页面问题列表操作。

当前修订执行方式：

- 读取原 draft。
- 读取 review。
- 读取 revision plan。
- 生成修订稿或预览。
- 将处理记录附加到修订稿。
- 可选择再次 review。

边界：

- 修订执行目前是结构化计划驱动的产品闭环，不等同于复杂语义级逐句重写编辑器。
- 高质量审稿依赖真实 provider 配置；mock/local rules 只适合测试和本地演示。

## 13. 任务中心和长任务

任务中心已实现“最新状态 + 事件日志”双视图，解决 append-only task status 容易误读的问题。

已实现：

- 默认表格展示每个 task/step 最新状态。
- 单独 timeline 展示完整事件日志。
- handoff 任务进入任务中心。
- 状态过滤。
- step 过滤。
- task type 过滤。
- 时间范围过滤。
- 分页。
- 任务取消。
- 任务重试。
- 失败步骤恢复。
- SSE task events。
- queue pressure。
- worker health。
- Redis queue length。
- dead-letter 列表。
- dead-letter retry。
- failure recovery workbench。
- batch item failure list。
- waiting handoff item list。
- 并发上限配置。

任务相关资产：

- `task_status`
- `workflow_run`
- `task_dead_letter`
- `batch_task_item`
- `claude_code_handoff`

Celery worker 行为：

- Redis broker。
- Redis result backend。
- soft time limit。
- hard time limit。
- worker prefetch multiplier = 1。
- reject on worker lost。
- post-task PostgreSQL sync。
- strict mode 下 post-task sync 失败会 fail-closed。
- 非 strict mode 下同步失败会写 dead-letter。

边界：

- 队列压力趋势已经有基础数据和 UI 展示，但还不是完整监控系统。
- 本地单机 worker 适合 Mac 本地生产，不等同于多节点云调度平台。

## 14. PostgreSQL

PostgreSQL 用于替代/补强 JSON 资产索引、任务状态、版本记录和项目索引。

已实现：

- optional dependency：`psycopg[binary]`。
- `postgres-init` CLI。
- `postgres-sync` CLI。
- `PostgresAssetStore`。
- schema migration registry。
- `nf_schema_migrations`。
- `nf_assets`。
- `nf_asset_versions`。
- `nf_task_statuses`。
- `nf_projects`。
- local JSON write-through。
- API 启动 strict check。
- strict local-prod 检查。
- migration 检查。
- backfill / sync 检查。
- strict 下禁止静默 fallback。
- worker post-task sync fail-closed 或写 dead-letter。
- Web 健康页显示 Postgres 状态。

strict local-prod 要求：

- `NOVEL_FORGE_DATABASE_URL` 或 `DATABASE_URL` 存在。
- `NOVEL_FORGE_POSTGRES_WRITE_THROUGH=true`。
- migration 已执行。
- local assets 已回填。
- Postgres 初始化可用。

边界：

- 当前不是“所有资产 payload 只存在 Postgres”的架构。JSON 文件仍是主资产载体，Postgres 是主索引、同步、任务和版本路径。
- 如果要升级到真正数据库主写，需要进一步把资产 payload 写入事务化表，并把 JSON 文件降级为导出/备份格式。

## 15. Redis + Celery

Redis + Celery 已作为长任务基础设施接入。

已实现：

- Celery app。
- Worker CLI。
- Redis broker。
- Redis result backend。
- 任务分发。
- pipeline task。
- single step task。
- batch deconstruct task。
- batch item step task。
- qdrant index task。
- dead-letter。
- worker lost dead-letter drill。
- queue length 查询。
- worker ping。
- 并发配置。

本地启动：

```bash
make worker
```

Docker 本地生产启动：

```bash
make local-up
```

边界：

- 当前没有复杂的队列分级策略和多 worker 池隔离。
- 任务幂等依赖任务记录、路径和 item step 状态，仍可继续强化全链路 idempotency key。

## 16. MinIO

MinIO 用于大文件、原始素材、导出稿件和资产对象存储。

已实现：

- `minio-sync` CLI。
- `MinioObjectStore`。
- object name 保留项目相对路径。
- artifact bucket sync。
- raw upload 尝试。
- export/object status。
- Web MinIO 对象状态。
- Web 重新同步按钮。
- 本地备份 manifest 中记录 MinIO 边界。

默认桶：

- `novel-forge-raw`
- `novel-forge-artifacts`
- `novel-forge-exports`

边界：

- 当前 MinIO 更多是本地对象副本和状态可见，不是所有资产读写的唯一后端。
- bucket 级备份建议用 MinIO/mc mirror 或快照，系统内置备份只记录本地数据和对象状态边界。

## 17. Neo4j

Neo4j 当前是可选项，默认关闭。

设计原则：

- 人物关系、世界观图谱、伏笔网络复杂到普通 JSON lineage 和引用图谱吃力时再启用。
- 本地生产默认不需要 Neo4j。
- Docker Compose 中提供 `graph` profile。
- `neo4j-status` CLI 和 health status 可显示启用状态。

边界：

- 当前没有完整 Neo4j 图谱写入和查询工作台。

## 18. Agent 边界

AGENTS.md 和 `agents/runtime.py` 共同定义 Agent 边界。

当前 Agent classes：

| Agent | 主要输出 | 核心禁止事项 |
|---|---|---|
| Chief Editor | 计划、验收、决策 | 未测试就宣称完成 |
| Engineering | 代码、测试、流程胶水 | 静默破坏 schema 兼容 |
| Knowledge | decomposition、knowledge card | 复制原文、混合原始来源和生成资产 |
| Material | material card | 复制特定角色、设定、情节 |
| Draft | draft chapter | 复制受保护文本、读未批准原始来源 |
| Review | review report、revision plan | 直接覆盖 draft、忽略风险 |
| Quality | validation、risk report | 压制告警、绕过校验 |

权限控制已实现：

- runtime permission profile。
- tool allowlist。
- allowed write types。
- `validate_tool_allowed`。
- `validate_write_type_allowed`。
- `enforce_agent_action`。
- handoff 记录 Agent runtime。
- handoff 输出绑定时检查 expected output type 和权限边界。

对用户提出的 Agent 工业化要求的当前状态：

| 要求 | 当前状态 |
|---|---|
| 边界是否清楚 | 清楚。AGENTS.md、skills、schema、source rights、资产目录和 handoff packet 都定义了边界 |
| 工具是否可控 | 基本可控。handoff 和 runtime profile 已有 allowlist，后端执行器层有输出类型检查 |
| 权限是否收敛 | 对 Agent 工作流收敛。对 Web 用户没有登录/角色系统，因为当前定位是本地单人 |
| 状态是否持久化 | 是。JSON asset、Postgres index、task status、workflow run、dead-letter、backup |
| 过程是否可观测 | 是。Studio agent board、任务中心、timeline、health、queue、worker、RAG metadata |
| 错误是否可恢复 | 是。retry、dead-letter、batch item retry、handoff retry、failure drill |
| 结果是否可验收 | 是。schema 校验、handoff acceptance、review issue status、source gate、make validate |

## 19. 模型 Provider 和输出校验

默认测试和本地演示使用 `MockModelAdapter`，真实 provider 需要显式配置。

已实现 provider：

- `claude-code`：manual handoff only。
- `codex`：manual runtime marker。
- `chatgpt`：OpenAI-compatible JSON chat。
- `deepseek`：OpenAI-compatible JSON chat。

已实现输出约束：

- provider health。
- operation-specific prompt。
- JSON object response format。
- model output parse。
- model output schema validation。
- invalid output fail closed。
- operation metadata。
- prompt/context trace。

常用配置：

```bash
export NOVEL_FORGE_MODEL_PROVIDER=chatgpt
export OPENAI_API_KEY=...
```

或：

```bash
export NOVEL_FORGE_DRAFT_PROVIDER=deepseek
export NOVEL_FORGE_REVISION_PROVIDER=deepseek
export DEEPSEEK_API_KEY=...
```

边界：

- 真实模型调用依赖网络和 API key。
- Claude Code 当前不是后端 API 调用，而是人工执行包。

## 20. 本地生产环境

当前项目已支持一键本地生产环境。

命令：

```bash
make local-up
```

它会：

- 创建 `.local/workspace/`。
- 如果没有 `.env`，从 `.env.example` 复制。
- 启动 PostgreSQL、Redis、Qdrant、MinIO。
- build API、worker、web 镜像。
- 初始化 Postgres schema。
- 同步本地资产到 Postgres。
- 启动 API、worker、web。
- 执行 smoke check。

常用地址：

| 服务 | 地址 |
|---|---|
| Web console | `http://localhost:3000` |
| FastAPI | `http://localhost:8000` |
| MinIO console | `http://localhost:9001` |
| Qdrant | `http://localhost:6333` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

运行态边界：

- `.local/workspace/` 是本地运行数据目录。
- `data/` 运行数据已经从 Git 管理中剥离。
- `examples/sample_inputs/` 和 `tests/fixtures/` 保留 deterministic fixture。

## 21. CLI

CLI 覆盖主要本地操作。

核心命令：

```bash
novel-forge init
novel-forge ingest
novel-forge clean
novel-forge decompose
novel-forge extract-knowledge
novel-forge build-materials
novel-forge generate-topic
novel-forge topic-development
novel-forge generate-world
novel-forge generate-characters
novel-forge generate-outline
novel-forge generate-chapter-plan
novel-forge draft
novel-forge review
novel-forge compare-reviews
novel-forge revise
novel-forge import-feedback
novel-forge analyze-feedback
novel-forge claude-deconstruct
novel-forge claude-knowledge
novel-forge run-pipeline
novel-forge validate
```

索引和工业化命令：

```bash
novel-forge search
novel-forge build-index
novel-forge build-manifest
novel-forge manifest-status
novel-forge build-vector-index
novel-forge vector-search
novel-forge industrial-status
novel-forge postgres-init
novel-forge postgres-sync
novel-forge qdrant-index
novel-forge qdrant-search
novel-forge minio-sync
novel-forge neo4j-status
novel-forge serve-api
novel-forge worker
```

Workspace 命令：

```bash
novel-forge init-workspace
novel-forge update-workspace
novel-forge workspace-status
```

## 22. API 能力

API 分基础 API 和 product API。

基础 API：

- `/health`
- `/assets`
- `/assets/{asset_path}`
- `/vector/search`
- `/pipeline/run`
- `/tasks/run-step`
- `/tasks/{task_id}`

Product API 分组：

| 分组 | 典型能力 |
|---|---|
| Projects | list/create/detail/config/archive/pause/restore/delete/duplicate/series/assets/audit |
| Tasks | latest/timeline/events/retry/cancel/control/recovery/dead-letter |
| Assets | detail/edit/content/typed/versions/graph/collections |
| Handoffs | list/create/validate/bind/acceptance/fail/retry |
| Sources | policies/github registry |
| Batch | upload/deconstruct/items/retry/bulk retry/review/continue/handoff regenerate/void |
| Drafts | workbench/editor/generate/save/diff/export |
| Reviews | run/issues/revision plan/apply revision |
| System | health/postgres strict/backups/restore/events archive |
| Qdrant | index/search |
| MinIO | sync/object status |

边界：

- `src/novel_forge/api/product.py` 已经非常大，后续维护应拆为 `projects.py`、`tasks.py`、`assets.py`、`handoffs.py`、`batch.py`、`drafts.py`、`reviews.py`、`health.py` 等模块。

## 23. 测试和验证

测试使用 Python `unittest`，覆盖单元和集成。

当前测试目录：

- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`

覆盖领域：

- CLI。
- schema。
- storage。
- task status。
- model adapter。
- source intake。
- skills sync。
- industrial integration。
- product API。
- Claude handoff。
- module services。
- pipeline integration。

常用命令：

```bash
make test
make lint
make validate
make demo
make failure-drill
```

`make validate` 会检查：

- runtime data 目录。
- 必需文档。
- 所有 JSON asset 的 common fields。
- asset type required content。
- source rights。
- handoff required fields。
- task/dead-letter/batch item schema。
- review/workspace schema。
- skills 文件结构。
- project-scope audit。

## 24. 故障演练和备份恢复

已实现：

- `scripts/failure_drill.py`。
- task failure recovery drill。
- failed task 是否进入任务中心。
- retry 是否完成。
- worker lost dead-letter drill。
- Postgres strict missing database URL drill。
- Redis short outage drill。
- Qdrant dimension mismatch drill。
- MinIO unavailable drill。
- API health probe。

本地备份：

- Web `/product/system/backups`。
- 创建 local-prod zip。
- 列出 backups。
- confirmed restore。
- backup manifest 记录 Postgres、MinIO、Qdrant 边界。

边界：

- 内置备份主要覆盖本地运行目录和配置边界。
- 数据库级备份仍建议使用 `pg_dump`。
- MinIO bucket 级备份建议使用 `mc mirror` 或 MinIO 快照。
- Qdrant 大规模生产备份建议使用 Qdrant snapshot。

## 25. 当前已满足的平台化程度

| 维度 | 当前状态 |
|---|---|
| 平台化 | 已具备项目、资产、任务、工作台、健康页、批处理、审稿修订等平台骨架 |
| 服务化 | 已有 FastAPI、Celery、Postgres、Redis、Qdrant、MinIO、Docker Compose |
| Web 产品 | 已有可使用的 Next.js 管理台和 Studio 页面 |
| 本地生产 | 已支持 Mac 本地 Docker 一键启动 |
| 多项目 | 有项目隔离、scope audit、project_id/workspace_path 继承 |
| 多用户 | 未实现，当前定位本地单人 |
| 权限 | Agent 工作流权限已实现，Web 用户权限未实现 |
| RAG | 已实现项目级 RAG，Qdrant 优先，local fallback |
| 长任务 | 已实现 Celery、task center、dead-letter、retry、worker health |
| 验收 | 已实现 schema、handoff acceptance、review issue、validate |

## 26. 仍需注意的限制和优化项

### 26.1 架构限制

- JSON 文件仍是主要资产载体，PostgreSQL 不是全系统唯一事实源。
- Product API 文件过大，后续需要模块化拆分。
- Web 用户登录、角色、权限、多租户没有实现，因为当前目标是本地 Mac 单人使用。
- Neo4j 只做了可选启用和状态检查，没有完整图谱工作台。

### 26.2 Web 产品限制

- Studio 已经能阅读、编辑、追踪生成和查看来源，但还可以继续加强为真正的章节级编辑器。
- typed asset panels 已有第一版，但各类资产仍缺深度领域表单。
- 任务中心已有分页、过滤、timeline、队列压力基础展示，但不是完整 APM/监控系统。

### 26.3 模型和 RAG 限制

- 高质量 draft/review/knowledge 依赖真实 provider。
- Qdrant 语义检索依赖真实 embedding API key。
- `auto` backend 会在 Qdrant 不可用时 fallback 到 local，需要通过 metadata 判断实际 backend。
- Handoff semantic review 已有 provider/rubric 接口，但质量取决于 provider 配置。

### 26.4 数据和合规限制

- 外部资料的合规判断需要持续维护 source policy。
- 老资产如果缺 source metadata，Web 分类只能启发式判断。
- 非商业许可资料不应直接进入商业正文生成依赖。
- 系统已提供合规 gate，但操作者仍需要保证授权信息真实。

## 27. 推荐使用路径

本地 Mac 正式使用建议路径：

1. 启动本地生产栈：

```bash
make local-up
```

2. 打开 Web 管理台：

```text
http://localhost:3000
```

3. 创建项目，填写题材、目标字数、平台、质量阈值。

4. 通过 Batch 上传本地资料，完成版权/授权确认。

5. 对网文或复杂多学科资料选择 Claude Code 解析模式。

6. 在 Handoff 工作台复制提示，在 Claude Code 中使用 Codex 产出 decomposition 或 knowledge card。

7. 回到 Web 管理台绑定输出，逐条验收，自动推进 batch item。

8. 在 Studio 查看资料来源、拆解结果、Agent 工作过程和当前稿件。

9. 生成或编辑 draft，保存版本。

10. 运行 review，处理 issue 状态。

11. 生成 revision plan，预览并确认修订。

12. 导出 Markdown/DOCX/EPUB，形成发布记录。

13. 使用 Health 和 Tasks 页面处理失败任务、scope audit、Qdrant/MinIO/Postgres 状态。

## 28. 结论

当前 Novel Forge V5 已经具备“本地单人小说生产平台”的主要闭环：

```text
项目 -> 来源 -> 拆解 -> 知识/素材 -> RAG -> 草稿 -> 审稿 -> 修订 -> 导出 -> 任务恢复 -> 健康审计
```

它已经不是单纯 CLI 或 demo pipeline，而是有 Web 管理台、服务端 API、异步任务、向量检索、对象存储、项目隔离、handoff 验收和本地生产启动方案的产品化系统。

下一阶段最有价值的优化方向是：

- 把 Product API 拆模块。
- 把 PostgreSQL 从主索引升级为更强的主写事务层。
- 把 Studio 编辑器升级为章节级专业编辑器。
- 为每类资产补深度编辑表单。
- 强化真实 provider 下的语义审稿和质量趋势。
- 完善数据库、MinIO、Qdrant 的生产级备份恢复。
