# MKAOS 缺口与风险登记

生成时间：2026-07-03

## 1. 设计缺口清单

| ID | 缺口 | 证据 | 优先级 | 建议 |
| -- | -- | -- | -- | -- |
| DG-01 | Query API 未实现：`/api/mkaos/query/knowledge`。 | `docs/mkaos-agent-api-protocol.md` 定义 Query；`src/novel_forge/api/routers/mkaos.py` 无对应路由。 | P1_HIGH | Phase 2 增补或在设计中明确推迟；至少提供按 flow/discipline/genre/platform 查询的只读 API。 |
| DG-02 | Convert API 未实现：`/api/mkaos/convert/assets`、`/api/mkaos/convert/rules`。 | 协议文档第 7 节；当前仅有 `create_rule_card`、`create_template_card`。 | P2_MEDIUM | 并入资产转换台或 Material/Knowledge Agent，不阻塞 P0。 |
| DG-03 | 全量 MKAOS 对象缺失：knowledge_relations、material/conflict/world/character asset cards、feedback_events、regression_cases/runs。 | `docs/mkaos-database-schema.md` P1 清单；当前 P0 migration 仅 10 表。 | P2_MEDIUM | 作为 P1/P2，不回填到 P0。 |
| DG-04 | 标准 API 响应和错误码未实现。 | `docs/mkaos-agent-api-protocol.md` 要求 `success/request_id/trace_id` 和错误码；router 直接返回 payload/HTTPException。 | P1_HIGH | 并入 OS Envelope，不做局部临时格式。 |
| DG-05 | Recap / Revision / Publish / Feedback adapters 未实现。 | `docs/design/novel-os-v6-industrialization-design.md` Phase 2；`MKAOS_FLOWS` 仅四个 P0 flow。 | P1_HIGH | Phase 2 新增 adapter policy，Phase 3 统一由 Context Builder 调用。 |

## 2. 实现偏差清单

| ID | 偏差 | 证据 | 风险 | 优先级 | 建议 |
| -- | -- | -- | -- | -- | -- |
| ID-01 | `knowledge_status` 使用 `active/needs_review`，与原始枚举 `extracted/flow_bound/runtime_used/...` 不一致。 | `service.py::create_knowledge_card` 默认 `active`；`docs/mkaos-database-schema.md` 枚举。 | 后续统计和迁移语义不稳定。 | P2_MEDIUM | 定义兼容映射，避免硬迁移破坏现有资产。 |
| ID-02 | Postgres projection 表字段比设计薄，许多业务字段只在 JSON asset content 中。 | `v20260702_0003_mkaos_p0.py` vs `docs/mkaos-database-schema.md`。 | SQL 查询、索引、约束、审计难做。 | P1_HIGH | 明确 projection 设计：扩列或 JSONB 索引 + validator。 |
| ID-03 | Pack selector 未按 `task_goal`、discipline、quality_score 做明确匹配。 | `service.py::build_knowledge_pack`、`_pack_item_from_binding`。 | Pack 相关性和质量稳定性不足。 | P1_HIGH | 增加 selector policy 和 pack scoring。 |
| ID-04 | `record_review_feedback` 只写质量分，不自动更新权重；`apply_weight_update` 才影响 pack 排序。 | `service.py::record_review_feedback`、`apply_weight_update`。 | feedback 看似闭环但容易停在日志层。 | P1_HIGH | 设计 feedback pipeline，明确何时自动/人工应用权重。 |
| ID-05 | Canon validator 不是完整 Canon/Character/Arc/Foreshadowing 检测。 | `service.py::_canon_context`、`validate_canon_conflict`。 | API 形态可能误导为已有真实正典治理。 | P1_HIGH | 接 continuity graph 和 longform stability assets。 |

## 3. 架构风险清单

| ID | 风险 | 涉及文件 | 优先级 | 预估改动范围 | 修复建议 |
| -- | -- | -- | -- | -- | -- |
| AR-01 | MKAOS Pack 由各生产服务单独构造，未通过统一 Context Builder。 | `outline/service.py`、`chapter_plan/service.py`、`drafting/service.py`、`review/service.py`、`context_builder/service.py` | P1_HIGH | 中 | 把 MKAOS pack 放入 Context Bundle schema 和 task policy，服务只消费 bundle。 |
| AR-02 | Pack 构造失败 warning 降级适合兼容路径，但生产路径应 fail policy 化。 | 四个服务 `_build_mkaos_pack` | P1_HIGH | 小-中 | OS Envelope/runtime policy 增加 `mkaos_pack_required`、`compat_warning_allowed`。 |
| AR-03 | MKAOS mutation API 未纳入 OS Envelope/trace/runtime policy。 | `api/routers/mkaos.py` | P1_HIGH | 中 | Phase 1 统一 envelope，不在 MKAOS router 内单独发明格式。 |
| AR-04 | MKAOS 校验 issue 尚未统一为 ReviewIssue。 | `review/service.py` 把 MKAOS issues 合并进 review issues；未持久化统一 issue asset。 | P1_HIGH | 中 | Eval / Review Issue 阶段接入 `mkaos_conflict`、blocking policy。 |

## 4. 数据模型风险

| ID | 风险 | 证据 | 优先级 | 预估改动范围 | 修复建议 |
| -- | -- | -- | -- | -- | -- |
| DM-01 | 数据库 FK 不完整，例如 binding/pack item 对 knowledge_id 没有强外键。 | `v20260702_0003_mkaos_p0.py` | P1_HIGH | 中 | 若使用 Postgres 生产索引，增加 FK 或同步一致性检查。 |
| DM-02 | P0 表使用 `TEXT` id，而设计文档使用 UUID。 | migration 文件 | P3_LOW | 小 | local-first 资产 id 可接受；只需在文档中记录偏差。 |
| DM-03 | `knowledge_quality_scores` 仅存 delta/reason，缺原设计子维度。 | `v20260702_0003_mkaos_p0.py`、`service.py::_record_quality_score` | P2_MEDIUM | 中 | 增加 quality dimension content 或 projection。 |
| DM-04 | Source chunk 缺 page/chapter/section/evidence span 字段。 | `service.py::rebuild_source_chunks` | P2_MEDIUM | 小-中 | 扩充 chunk metadata，导入器逐步填充。 |
| DM-05 | lineage 主要靠 asset references，缺 DB 级 lineage audit。 | `service.py` references；`filter_project_safe_references` | P1_HIGH | 中 | 增加 lineage validator 和 report。 |

## 5. 生产链路风险

| ID | 风险 | 证据 | 优先级 | 预估改动范围 | 修复建议 |
| -- | -- | -- | -- | -- | -- |
| PL-01 | Outline/Chapter/Review 没有 Context Bundle 证据，只有 MKAOS pack metadata。 | `outline/service.py`、`chapter_plan/service.py`、`review/service.py` | P1_HIGH | 中 | 统一生产调用必须有 `context_bundle_id` + `knowledge_pack_id`。 |
| PL-02 | Review 注入 MKAOS issues，但 blocking 与 rollback 没有进入统一 gate。 | `review/service.py`、`service.py::validate_artifact` | P1_HIGH | 中 | 由 ReviewIssue/gate 统一阻断 canonical output。 |
| PL-03 | usage event coverage 未量化，服务中 `_record_mkaos_usage` 静默吞异常。 | 四个服务 `_record_mkaos_usage` | P2_MEDIUM | 小 | 生产模式下记录失败 warning/gate；测试覆盖 failure path。 |
| PL-04 | Pack selector 失败时可空 pack 继续生成。 | `build_knowledge_pack` warnings；服务 warning 降级。 | P1_HIGH | 小-中 | 按任务类型设置 fail-open/fail-closed。 |

## 6. RAG / Source Leakage 风险

| ID | 风险 | 证据 | 优先级 | 预估改动范围 | 修复建议 |
| -- | -- | -- | -- | -- | -- |
| RS-01 | 策略已阻止 `knowledge_pack`、`knowledge_usage_event`、`agent_run` 等进入 generation RAG，但缺 MKAOS 专项回归。 | `storage/rag_context.py::GENERATION_RAG_BLOCKED_TYPES`；`tests/unit/test_context_and_production_chain.py` 只有通用过滤。 | P1_HIGH | 小 | 增加测试：手工选 MKAOS pack/usage/source_chunk/agent_run 时必须被拒绝。 |
| RS-02 | Source chunk asset 存 `raw_text`，管理 API 可读；生产链路必须持续证明不泄漏。 | `service.py::rebuild_source_chunks`、`api/routers/mkaos.py` chunk endpoints。 | P1_HIGH | 小-中 | 增加 source leakage API/pack/context tests。 |
| RS-03 | `knowledge_card` 可进入 `knowledge_cards` bucket，需证明其内容是抽象知识而非 raw expression。 | `storage/rag_context.py::TYPE_BUCKETS` 包含 `knowledge_card`。 | P2_MEDIUM | 中 | Knowledge Card 创建/更新增加 raw-expression lint 和 source span audit。 |

## 7. Context Builder 集成风险

| ID | 风险 | 证据 | 优先级 | 预估改动范围 | 修复建议 |
| -- | -- | -- | -- | -- | -- |
| CB-01 | MKAOS pack 不属于 `ContextBundle.content` 的正式字段。 | `context_builder/service.py::create_context_bundle` | P1_HIGH | 中 | 增加 `mkaos: {knowledge_pack_id,path,flow,items,budget,warnings}`。 |
| CB-02 | draft 同时有 context bundle 和独立 MKAOS pack，预算可能分裂。 | `drafting/service.py` | P1_HIGH | 中 | Context Builder 统一 token/knowledge budget。 |
| CB-03 | outline/chapter/review 仍使用 planning/production context 而非统一 context bundle。 | 三个服务 | P1_HIGH | 中-大 | 分阶段迁移；先记录 bundle，再切换 prompt 输入。 |

## 8. Agent 消费路径风险

| ID | 风险 | 证据 | 优先级 | 预估改动范围 | 修复建议 |
| -- | -- | -- | -- | -- | -- |
| AG-01 | 只有四个生产服务消费 MKAOS；Longform Recap、Publishing、Feedback、Revision 缺路径。 | `rg build_knowledge_pack src/novel_forge/modules` | P1_HIGH | 中 | Phase 2 新增 flow policies；Phase 6 Longform Recap 使用 `recap_context`。 |
| AG-02 | Agent Center 目前未形成按 Agent run 查询 Knowledge Pack / Context Bundle / ReviewIssue 的完整证据链。 | `docs/design/...` Phase 7；当前 metadata 分散在资产中。 | P1_HIGH | 中 | Agent Center 聚合 `agent_run_path`、`context_bundle_id`、`knowledge_pack_id`。 |
| AG-03 | Agent API 权限模型未落到 MKAOS router。 | `docs/mkaos-agent-api-protocol.md` vs `api/routers/mkaos.py`。 | P1_HIGH | 中 | 通过 OS Envelope 和 runtime policy 统一授权。 |

## 9. UI / 可维护性风险

| ID | 风险 | 证据 | 优先级 | 预估改动范围 | 修复建议 |
| -- | -- | -- | -- | -- | -- |
| UI-01 | `/mkaos` 是最小 console，缺质量评分、版本、血缘、使用地图、Pack debugger。 | `MkaosConsolePage.tsx` | P2_MEDIUM | 中 | UI P1/P2 分页增强。 |
| UI-02 | UI API 只调用 overview/source/knowledge/binding/pack/acceptance，未覆盖 feedback weight、rules/templates 创建。 | `web/admin/app/features/mkaos/api.ts` | P2_MEDIUM | 小-中 | 补齐操作入口或标为只读。 |
| UI-03 | 来源 raw_text 管理端可显示，需明确 operator-only 边界。 | source detail/chunks endpoint | P2_MEDIUM | 小 | UI 加版权/证据层提示和权限 envelope。 |

## 10. 测试覆盖风险

| ID | 风险 | 证据 | 优先级 | 预估改动范围 | 修复建议 |
| -- | -- | -- | -- | -- | -- |
| TS-01 | P0 要至少 10 个回归样例，当前核心 MKAOS 单测主要围绕土地兼并。 | `tests/unit/test_mkaos.py` | P1_HIGH | 中 | 新增 10 fixtures：因果链、伏笔、创伤、证词、百科化正/反例、Canon 冲突等。 |
| TS-02 | 缺 MKAOS API contract negative tests。 | 当前 API smoke 只测 happy path。 | P1_HIGH | 小 | 测 invalid flow、missing knowledge、prose raw_text、disabled binding。 |
| TS-03 | 缺 RAG isolation regression for MKAOS runtime assets。 | `tests/unit/test_context_and_production_chain.py` 通用过滤。 | P1_HIGH | 小 | 增加手动选择 MKAOS 运行资产被拒绝测试。 |
| TS-04 | 缺 pack build failure policy 测试。 | 四服务 fallback 未被专门断言。 | P2_MEDIUM | 小 | Mock `build_knowledge_pack` 异常，验证 compat/prod 行为。 |
| TS-05 | 全量 discover 用时约 537s，反馈慢。 | 本次测试记录。 | P2_MEDIUM | 小 | 建立 MKAOS focused integration suite，避免每次依赖长 pipeline。 |

## 11. 当前最大风险排序

1. **Context Builder 未统一接入 MKAOS Pack**：会影响后续所有模型调用的上下文可追踪性和预算治理。
2. **Canon conflict 能力不足**：API 存在但不是完整 Canon/Character/Arc/Foreshadowing 检测。
3. **OS Envelope / API 标准响应缺失**：MKAOS mutation 还没有统一 trace、permission、runtime policy。
4. **RAG/source leakage 缺专项回归**：策略存在，但 MKAOS 运行资产隔离没有专门防回退测试。
5. **Feedback 闭环较浅**：记录和权重应用分离，reader feedback/ReviewIssue/quality score 没形成生产闭环。
