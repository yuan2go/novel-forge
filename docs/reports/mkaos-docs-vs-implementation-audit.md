# MKAOS 原始设计 vs 当前实现审计

生成时间：2026-07-03

## 1. 审计基线

原始设计基线：

- 主设计：`docs/multidisciplinary-knowledge-asset-os.md`
- 数据模型：`docs/mkaos-database-schema.md`
- Agent/API 协议：`docs/mkaos-agent-api-protocol.md`
- P0 切片：`docs/mkaos-p0-implementation-plan.md`

当前实现重点文件：

- `src/novel_forge/modules/mkaos/service.py`
- `src/novel_forge/api/routers/mkaos.py`
- `src/novel_forge/storage/migrations/versions/v20260702_0003_mkaos_p0.py`
- `web/admin/app/features/mkaos/MkaosConsolePage.tsx`
- `tests/unit/test_mkaos.py`

补充搜索路径：

- 调用点：`src/novel_forge/modules/outline/service.py`、`src/novel_forge/modules/chapter_plan/service.py`、`src/novel_forge/modules/drafting/service.py`、`src/novel_forge/modules/review/service.py`
- RAG / Context：`src/novel_forge/storage/rag_context.py`、`src/novel_forge/modules/context_builder/service.py`
- API/UI 注册：`src/novel_forge/api/routers/__init__.py`、`web/admin/app/mkaos/page.tsx`、`web/admin/app/shared/navigation.tsx`
- 测试：`tests/unit/test_mkaos.py`、`tests/unit/test_context_and_production_chain.py`、`tests/integration/test_pipeline.py`

## 2. 测试结果

| 命令 | 结果 |
| -- | -- |
| `python3 -m unittest tests/unit/test_mkaos.py` | 5 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 1 test OK，用时约 263s |
| `python3 -m unittest discover -s tests -p 'test_*.py'` | 266 tests OK，skipped=1，用时约 537s |
| `npm --prefix web/admin test` | 通过，7 pass，1 skip：Playwright 未安装 |
| `npm --prefix web/admin run build` | 通过，Next.js build 路由包含 `/mkaos` |

## 3. 总体判断

当前实现基本符合 `docs/mkaos-p0-implementation-plan.md` 的最小闭环目标：来源导入、chunk、Knowledge Card、Usage Binding、Rule/Template Card、Knowledge Pack、四个核心 Flow Adapter、usage event、基础 feedback、最小 UI、土地兼并 fixture 和回归测试均存在。

但它尚未完全符合全量主设计和 Post-MKAOS 工业化设计。主要缺口集中在：Query/Convert API、标准响应 envelope、真实 Canon/长篇稳定性冲突检测、统一 Context Builder 入口、MKAOS mutation 的 OS Envelope、Recap/Revision/Publish/Feedback adapters、RAG isolation 专项回归、数据模型列级完整度和质量/反馈闭环深度。

## 4. 逐项对比矩阵

| 模块 | 原设计要求 | 当前实现 | 证据文件/函数/API/测试 | 一致性判断 | 问题说明 | 严重级别 | 建议处理 |
| -- | ----- | ---- | -------------- | ----- | ---- | ---- | ---- |
| 产品定位 | MKAOS 是知识中枢、规则中枢、审稿中枢和反馈学习中枢，不是普通资料库或 RAG 层。 | 当前是 local-first JSON asset + API + UI 的 P0 知识底座，已进入四个生产服务。 | `docs/multidisciplinary-knowledge-asset-os.md`；`service.py::build_knowledge_pack`；四个服务直接接入。 | PARTIAL | P0 闭环成立，但还不是“所有 Agent 不可绕过”的知识/规则/反馈中枢。 | P1_HIGH | Post-MKAOS 阶段通过 Context Builder、OS Envelope、Agent Center 强化为生产底座。 |
| P0 最小闭环 | 来源导入 → 知识卡 → 绑定 → Pack → 大纲/细纲/正文/审稿 → usage → feedback。 | `run_minimal_acceptance_fixture()` 生成土地兼并来源、知识卡、绑定、规则、模板、四类 pack、usage、feedback。 | `service.py::run_minimal_acceptance_fixture`；`tests/unit/test_mkaos.py::test_minimal_acceptance_fixture_proves_closed_loop`。 | MATCH | P0 样例闭环满足。 | INFO | 保持 fixture，后续加入更多回归样例。 |
| 全量核心对象 | Source、Knowledge、Asset、Runtime、Evolution 多层；含素材卡、冲突卡、世界观卡、人物资产卡、关系、反馈事件、回归用例。 | P0 实现 10 类最小对象；未实现 P1 对象。 | `schemas/assets.py`；`core/constants.py`；`v20260702_0003_mkaos_p0.py`。 | PARTIAL | P0 表清单匹配；全量对象缺失属于 P1/P2，不是 P0 失败。 | P2_MEDIUM | Phase 2/后续按需要补 relation、asset cards、feedback events、regression cases。 |
| 数据模型：P0 表 | P0 必须实现 `source_documents`、`source_chunks`、`knowledge_cards`、`knowledge_usage_bindings`、`rule_cards`、`template_cards`、`knowledge_packs`、`knowledge_pack_items`、`knowledge_usage_events`、`knowledge_quality_scores`。 | migration 已创建上述表；schema registry 也有对应 asset types。 | `v20260702_0003_mkaos_p0.py`；`tests/unit/test_schemas.py::test_required_schema_count`。 | MATCH | 表名与 P0 清单一致。 | INFO | 后续避免重复建表。 |
| 数据模型：字段完整度 | schema 文档要求丰富列字段，例如 aliases、core_explanation、prompt_fragment、constraint_text、review_result、reader_feedback、quality 子分数。 | 许多字段存在于 JSON asset content 中，但 Postgres projection 表较薄，部分列缺失。 | `service.py::create_knowledge_card`；`service.py::create_usage_binding`；`v20260702_0003_mkaos_p0.py`。 | PARTIAL | local-first asset 可接受，但数据库查询、约束和审计会受限。 | P1_HIGH | 明确 Postgres projection 策略：要么扩列，要么建立 JSONB 查询索引和 validation 报告。 |
| 数据模型：枚举 | 原设计有 source_type、knowledge_type、knowledge_status、flow、usage_granularity、rule_type、severity。 | schema validator 主要硬限制 `flow` 为四个 P0 flow，校验 rule severity；其他枚举未严格验证。 | `schemas/base.py::_validate_mkaos_content`；`service.py::_valid_flow`。 | PARTIAL | P0 可运行，但状态值如 `active/needs_review` 与设计枚举 `extracted/flow_bound/...` 不一致。 | P2_MEDIUM | 设计状态映射或迁移枚举，避免后续统计混乱。 |
| 数据模型：索引/约束 | 原设计要求关键字段索引、唯一约束、外键、项目作用域、lineage。 | migration 有基础索引；source chunk 有唯一 `(source_document_id, content_hash)`；bindings 对 knowledge 没有真实 FK；asset references 保存 lineage。 | `v20260702_0003_mkaos_p0.py`；`service.py` metadata/references。 | PARTIAL | 本地 JSON 和 Postgres projection 双轨导致数据库约束不完整。 | P1_HIGH | 增加 projection 同步测试、FK/唯一约束决策、lineage 验证。 |
| Source Document 导入 | 支持专业书、网文拆解、名著拆解、平台规则、反馈等来源，保存权利元信息和清洗状态。 | 支持文本 payload 导入，写 `SourceDocument`，metadata 含 rights、`use_in_generation_rag=false`。 | `service.py::import_source_document`；`web/admin/app/features/mkaos/api.ts::importMkaosSource`。 | PARTIAL | P0 文本导入满足；pdf/异步导入、清洗任务重试、MinIO 边界未做。 | P2_MEDIUM | 放入来源清洗 P1，不阻塞 P0。 |
| Source Chunk / 证据 span | 原设计要求 raw_text/cleaned_text、章节、页码、证据追溯；source chunk 是证据层，不给正文 Agent。 | chunk 包含 `raw_text`、`clean_text`、`source_document_id`、`chunk_index`、hash；无 page/span 字段；API 可给管理端查看 chunks。 | `service.py::rebuild_source_chunks`；`api/routers/mkaos.py` chunk endpoints。 | PARTIAL | 证据层存在，但 evidence span 粒度不足；管理端可读 raw_text 合理，但生产链路必须隔离。 | P1_HIGH | 增加 span/page 元数据；加 source leakage 专项测试。 |
| Source isolation | 正文 Agent 不直接读取 source chunk；Prose Pack 不暴露 raw chunk。 | Pack content 只带 `source_chunk_ids`；validator 禁止 prose pack 出现 `raw_text`；单测覆盖。 | `service.py::_pack_item_from_binding`；`schemas/base.py::_validate_mkaos_content`；`tests/unit/test_mkaos.py`。 | MATCH | P0 Prose Pack 隔离满足。 | INFO | 后续加 API/RAG/Context Builder 端到端泄漏测试。 |
| Knowledge Card 字段 | 应包含学科、类型、解释、来源、置信度、可靠性、适用题材/平台、风险、状态、质量、权重。 | 这些字段大多在 `content` 和 metadata 中存在。 | `service.py::create_knowledge_card`。 | PARTIAL | 缺 version 状态、质量分子维度、设计状态枚举统一；人工创建可无 source chunk。 | P2_MEDIUM | Phase 2 增加版本、质量维度、状态迁移策略。 |
| 反百科化 | 原设计要求知识转为冲突/行动/场景，禁止百科化，Review 可命中。 | 默认规则含反百科化；`validate_artifact` 有启发式检查；测试覆盖明显反例/正例。 | `DEFAULT_RULES`；`service.py::_anti_encyclopedia_issues`；`tests/unit/test_mkaos.py::test_flow_adapters_validate_and_feedback`。 | MATCH | P0 规则能运行；算法仍是 heuristic。 | P2_MEDIUM | 后续接 ReviewIssue 和更严格文本评测。 |
| Usage Binding | 一条知识可绑定多个流程，P0 flow 为 outline/chapter_outline/prose/review。 | 支持创建/更新/禁用绑定；flow 限定四个 P0 flow。 | `service.py::create_usage_binding`；`service.py::list_usage_bindings`；`tests/unit/test_mkaos.py` 禁用绑定测试。 | MATCH | P0 满足。 | INFO | 保持兼容。 |
| Usage Binding 粒度 | 原设计 usage_granularity 是 L1-L7；绑定粒度要支持不同流程形态。 | 默认写 `project/chapter`，接受任意字符串但未校验 L1-L7。 | `service.py::create_usage_binding`；`schemas/base.py`。 | PARTIAL | 粒度较粗，后续难以做精准 Context Builder 和统计。 | P2_MEDIUM | 引入 L1-L7 枚举或映射。 |
| 缺失 flow：recap/revision/publish/feedback | Post-MKAOS 要补 recap、revision、publish、feedback pack/adapters。 | `MKAOS_FLOWS` 仅四个 P0 flow；未搜索到这些 MKAOS adapters。 | `service.py::MKAOS_FLOWS`；`rg build_knowledge_pack` 仅四个服务。 | MISSING | 不是 P0 缺口，但阻碍长篇复盘、发布、反馈闭环。 | P1_HIGH | Phase 2 增加 adapters，并通过 Context Builder 消费。 |
| Rule Card | 支持 generation/review/canon/platform/style/anti-encyclopedia/logic/safety 等规则，Review 可复用。 | 有默认 8 条规则和 CRUD，Review Pack 会注入 rule rows。 | `DEFAULT_RULES`；`service.py::create_rule_card`；`build_knowledge_pack`；`_review_adapter`。 | PARTIAL | rule_type 未完全按设计枚举；没有统一 ReviewIssue/阻断策略。 | P1_HIGH | 接 Eval / Review Issue；规则卡补强类型和 blocking policy。 |
| Template Card | 原设计有 input_fields、output_structure、example、success_score、风险等。 | 当前 template card 用 `structure`、`usage_constraints`、`anti_copy_rules`，更偏本地资产模板。 | `service.py::create_template_card`；`docs/mkaos-database-schema.md`。 | PARTIAL | P0 可用；和数据库设计字段不完全一致。 | P2_MEDIUM | 决策是否兼容原字段或保留当前更适合创作模板的结构。 |
| Knowledge Pack Builder：基础选择 | 按 flow/task_goal、genre/platform/discipline、deprecated 排除、required/optional/forbidden、rules、budget、canon、risk 生成 pack。 | 按 flow、enabled binding、genre/platform、deprecated、priority、weight、预算生成；注入 rules/canon/risk/output_contract。 | `service.py::build_knowledge_pack`；`service.py::_pack_item_from_binding`。 | PARTIAL | 未按 task_goal/discipline 搜索；quality_score 未直接参与排序；risk 只警示不过滤。 | P1_HIGH | Phase 2 增加 selector policy、discipline/task_goal 匹配、质量/风险权重。 |
| Knowledge Pack 预算 | 设计要求 token/知识预算，正文每章核心知识 1-3 个。 | `_knowledge_budget` 为 prose 默认 3，限制 optional 数量；没有 token 估算。 | `service.py::_knowledge_budget`；`build_knowledge_pack`。 | PARTIAL | 知识点预算满足；上下文 token 预算需要 Context Builder 统一。 | P1_HIGH | 并入 Context Builder。 |
| Knowledge Pack 持久化 | Pack 和 pack items 要持久化、可预览。 | 写入 `contexts`，生成 `knowledge_pack_item`，提供 prompt-preview。 | `service.py::build_knowledge_pack`；`service.py::_write_pack_item_assets`；`api/routers/mkaos.py`。 | MATCH | P0 满足。 | INFO | 后续补 Pack diff/debugger。 |
| Pack 构造失败策略 | 协议错误码中 `PACK_BUILD_FAILED` blocking=true；Post-MKAOS 允许 compat warning，但生产需 policy 化。 | 四个服务 `_build_mkaos_pack` 捕获异常返回 warning，不破坏旧流程。 | `outline/service.py::_build_mkaos_pack` 等四处。 | EXTRA_VALID | 向后兼容合理，但生产路径未 fail-closed，可能让 Agent 绕过知识底座。 | P1_HIGH | OS Envelope/runtime policy 区分 dev/sample/production。 |
| Flow Adapter：P0 四类 | P0 要 outline/chapter_outline/prose/review 四个 adapter。 | `adapt_pack_for_flow` 和四个私有 adapter 已实现。 | `service.py::adapt_pack_for_flow`；`_outline_adapter`；`_chapter_outline_adapter`；`_prose_adapter`；`_review_adapter`。 | MATCH | P0 满足。 | INFO | 保持单测快照。 |
| Flow Adapter：通过 Context Builder | 后续工业化要求所有 Agent 不自行拼上下文，MKAOS Pack 必须进入 Context Bundle。 | outline/chapter/review 直接构造 pack；draft 先构造 context bundle，再单独构造 MKAOS pack，未成为 bundle 正式组成。 | `outline/service.py`；`chapter_plan/service.py`；`drafting/service.py`; `context_builder/service.py` 无 MKAOS pack 字段。 | MISSING | 这是架构缺口，不是 MKAOS 本体缺失。 | P1_HIGH | Phase 3 将 MKAOS Pack Builder 接入 Context Builder task policy。 |
| Validate Artifact | 原设计要求返回 passed/score/issues/usage_assessment，包含 canon、logic、anti_encyclopedia、knowledge_usage、platform。 | 返回这些字段；支持反百科化、canon、knowledge usage、logic/platform 简单规则。 | `service.py::validate_artifact`；`api/routers/mkaos.py`。 | PARTIAL | P0 可用；仍是 heuristic，没有统一 ReviewIssue 或真实平台规则。 | P1_HIGH | 接 Eval / Review Issue，增加可阻断 gate。 |
| Canon Conflict | 原设计要求真实 Canon Checker 阻断 Canon 冲突，并给总编决策建议。 | 支持 payload/canon_database 的简单 facts/entities 比对和存活/死亡文本检查；无 Character/Arc/Foreshadowing/FactLedger/Motif/Villain 接入。 | `service.py::_canon_context`；`service.py::validate_canon_conflict`；`docs/design/...` 标明 stub 风险。 | PARTIAL | 比纯 stub 强，但治理能力不足，容易形成“有 API 但不具备真实 Canon 审计”的错觉。 | P1_HIGH | 接 continuity_graph、chapter_state、FactLedger、Arc、Foreshadowing。 |
| Usage Event | 原设计要求记录 knowledge_id、pack、project、flow、artifact、chapter、agent、used_as、span、review、feedback、effect_score。 | 大多字段记录；`prompt_context` 仅 dict，服务调用默认 effect_score=0；四服务生成后记录。 | `service.py::record_usage_event`；`record_pack_usage_for_artifact`；四个服务 `_record_mkaos_usage`。 | PARTIAL | P0 留痕成立；output_span/prompt_context 质量不足，coverage 未量化。 | P2_MEDIUM | 增加 usage coverage 统计和 span 采集。 |
| Feedback / 权重闭环 | 原设计要求审稿/人工/读者反馈影响权重，低效降权/废弃。 | `record_review_feedback` 只写 quality score；`apply_weight_update` 才改 knowledge weight/status；Pack 排序使用 weight。 | `service.py::record_review_feedback`；`service.py::apply_weight_update`；`_feedback_delta`。 | PARTIAL | 有闭环但分两步；reader feedback/deep attribution 未接入；质量分没有自动进入 pack selection。 | P1_HIGH | 明确 feedback pipeline：review issue/reader feedback -> quality score -> weight -> pack selector。 |
| RAG 与知识隔离 | MKAOS 不是 RAG 层；运行资产、source chunk、usage、Agent runtime 不得污染 generation RAG。 | RAG blocklist 包含 source_document、agent_run、knowledge_pack、usage event、quality score等；MKAOS assets metadata 多设 `use_in_generation_rag=false`。 | `storage/rag_context.py::GENERATION_RAG_BLOCKED_TYPES`；`_copyright_assessment`；`service.py` metadata。 | PARTIAL | 策略存在；缺 MKAOS 专项回归，`knowledge_card` 本身仍可进入 knowledge_cards bucket。 | P1_HIGH | 加 `knowledge_pack/usage/source_chunk/agent_run` isolation regression。 |
| Context Builder | 原设计/后续要求统一上下文包、可预览、预算、去重压缩、风险说明。 | Context Builder 已有独立实现，但 MKAOS Pack 不在其 bundle schema 中。 | `modules/context_builder/service.py::create_context_build_plan/create_context_bundle`；`drafting/service.py`。 | PARTIAL | Context Builder 本身存在；MKAOS 未统一接入。 | P1_HIGH | 将 MKAOS pack 作为 bundle `mkaos` 字段和 task policy。 |
| Agent / Workflow 消费 | 原设计要求所有 Agent 通过统一 API/Pack；P0 至少四个服务接入。 | Outline/ChapterOutline/Prose/Review 接入；Longform Recap、Publishing、Feedback、Revision 未接。 | 四服务 import `build_knowledge_pack`；`rg` 未发现其他 adapter。 | PARTIAL | P0 满足；Novel OS 工业化消费路径不足。 | P1_HIGH | Phase 2/3 增加缺失生产链路。 |
| API 覆盖 | 原协议含 Query、Pack、Convert、Validate、Feedback；标准响应含 success/request_id/trace_id。 | 实现 CRUD、Pack、adapter、validate、usage/feedback、risks、acceptance；缺 `/query/knowledge`、`/convert/assets`、`/convert/rules` 和统一响应 envelope。 | `api/routers/mkaos.py`；`mkaos-agent-api-protocol.md`。 | PARTIAL | P0 核心 API 足够；协议完整性不足。 | P1_HIGH | 增补 Query/Convert 或明确推迟；OS Envelope 统一 response/trace。 |
| API 权限/错误码 | 原协议要求 PERMISSION_DENIED、PACK_BUILD_FAILED、DIRECT_SOURCE_CHUNK_FORBIDDEN 等错误码。 | FastAPI 直接 400/404 detail；没有 agent header/permission 模型。 | `api/routers/mkaos.py`。 | MISSING | 生产治理不足。 | P1_HIGH | 并入 OS Envelope + runtime policy。 |
| UI：P0 管理台 | P0 UI 要知识总览、来源、知识卡、绑定、Pack 预览、规则库、使用记录、风险列表。 | `/mkaos` 覆盖这些区域，并能运行 P0 fixture；route 和 nav 已注册。 | `MkaosConsolePage.tsx`；`web/admin/app/mkaos/page.tsx`；`navigation.tsx`；Next build。 | MATCH | P0 UI 满足。 | INFO | 保持路由。 |
| UI：全量/后续能力 | 原设计还要知识图谱、资产转换台、使用地图、回归测试、权重演化；后续要血缘、版本、Pack 影响分析、RAG policy。 | 当前没有血缘图、质量评分编辑、版本管理、Pack 使用影响分析、RAG policy 展示。 | `MkaosConsolePage.tsx`；`api.ts`。 | MISSING | 属 UI P1/P2，不阻塞 P0。 | P2_MEDIUM | UI P1/P2 分批补。 |
| 测试：P0 单元 | P0 要 CRUD、Pack、Adapter、Usage、Feedback 测试。 | `tests/unit/test_mkaos.py` 覆盖来源、chunk dedupe、knowledge/binding/pack、adapter、validate、usage、feedback、fixture、API smoke。 | `tests/unit/test_mkaos.py`。 | MATCH | P0 单测较完整。 | INFO | 增加 snapshot/negative tests。 |
| 测试：集成/专项 | P0 计划要求集成链路、10 个回归样例、指标；后续要求 RAG isolation/source leakage/budget/lineage。 | 全量 discover 和 pipeline 通过；MKAOS 专项只有土地兼并，未见 10 样例、指标统计、RAG isolation 专项。 | `tests/integration/test_pipeline.py`；`tests/unit/test_context_and_production_chain.py`。 | PARTIAL | 当前测试证明能跑，不证明所有设计指标。 | P1_HIGH | 增加 MKAOS integration suite、10 fixtures、指标断言。 |
| P0/P1/P2 边界 | P0 不要求完整图谱、深度归因、多平台表现、100 章压力、全自动权重演化。 | 当前基本保持 P0，但额外做了 overview/adapter endpoint/risks/acceptance/minimal。 | `api/routers/mkaos.py`；`MkaosConsolePage.tsx`。 | EXTRA_VALID | 超前 API 合理，未偏离设计。 | INFO | 文档中标明这些是辅助 API。 |
| Novel OS 工业化路线 | MKAOS 应支撑 OS Envelope、Context Builder、Eval/ReviewIssue、Loop、Longform Recap、Agent Center、发布反馈闭环。 | 当前有 knowledge_pack_id 写入部分资产；未统一进 envelope/context/review issue/loop/agent center。 | `docs/design/novel-os-v6-industrialization-design.md`；四服务 metadata。 | PARTIAL | 可作为底座，但工业化接入未完成。 | P1_HIGH | 按 remediation plan 进入 Post-MKAOS 阶段。 |

## 5. 搜索未命中说明

以下设计要求在当前实现中未找到完整实现，已搜索 `src/`、`web/`、`tests/`：

| 要求 | 已搜索证据 | 结论 |
| -- | -- | -- |
| `/api/mkaos/query/knowledge` | `rg query/knowledge src web tests`、读取 `api/routers/mkaos.py` | 未实现。 |
| `/api/mkaos/convert/assets`、`/api/mkaos/convert/rules` | 读取 `api/routers/mkaos.py`、`modules/mkaos/service.py` | 未实现；当前可直接创建 rule/template，但没有 Convert API。 |
| `recap` / `revision` / `publish` / `feedback` MKAOS adapters | `rg build_knowledge_pack src/novel_forge/modules` | 只有 outline、chapter_plan、drafting、review 四处直接接入。 |
| MKAOS Pack 作为 Context Bundle 正式字段 | 读取 `modules/context_builder/service.py`、`drafting/service.py` | Context Builder 独立存在，但未把 MKAOS pack 纳入 bundle schema。 |
| MKAOS 专项 RAG isolation 测试 | `rg knowledge_pack|usage_event|source_chunk tests` | 通用 RAG/版权过滤测试存在；未见 MKAOS 运行资产专项回归。 |
| 标准响应 `success/request_id/trace_id` | 读取 `api/routers/mkaos.py` | 当前直接返回业务 payload 或 HTTPException。 |

## 6. 结论

当前实现可以视为“有条件完成 MKAOS P0”：它满足最小闭环和核心 P0 DoD，但不能宣称完成全量 MKAOS 或生产级 Novel OS 知识底座。条件是：明确 Canon conflict 仍是 P1 加固项、Pack warning fallback 仅适合兼容/dev/sample 路径、MKAOS 尚未统一接入 Context Builder/OS Envelope/ReviewIssue，且必须补 RAG/source leakage、lineage、budget、API envelope 等回归。
