# Novel OS v6 Final Implementation Matrix

日期：2026-07-03

| 模块 | 当前实现 | 证据 | 状态 | 遗留问题 |
| -- | -- | -- | -- | -- |
| MKAOS | Source/Chunk、KnowledgeCard、UsageBinding、Rule/Template、Pack、Query/Convert、Usage/Feedback、8 flow 枚举 | `src/novel_forge/modules/mkaos/service.py`, `tests/unit/test_mkaos.py` | COMPLETE_P0 | Canon 深度语义治理仍是 P1 |
| OS Envelope | MKAOS production mutation/query/convert、Loop、Publish Gate/Release Package 纳入 envelope | `src/novel_forge/modules/os_envelope`, `tests/unit/test_mkaos_os_envelope.py` | CORE_COMPLETE | legacy direct paths 仍需继续迁移 |
| RAG / Source Isolation | runtime assets 不进 generation RAG，raw source sentinel 不进 prose/prompt/publish/recap | `tests/unit/test_mkaos_isolation.py`, `tests/integration/test_novel_os_12_chapter_industrial_pressure.py` | COMPLETE_P0 | 真实外部语料接入仍需 operator 权限治理 |
| Context Builder | Outline/ChapterOutline/Prose/Review 统一取 ContextBundle；revision/recap/publish/feedback adapter seam | `src/novel_forge/modules/context_builder/service.py`, `tests/unit/test_context_builder_mkaos_flow.py` | CORE_COMPLETE | UI 精调和所有 legacy prompt surface 继续收敛 |
| ReviewIssue | MKAOS/Canon/Review issue 统一，阻断 final/canonical draft 和 release package | `src/novel_forge/modules/review_issue/service.py`, `tests/unit/test_review_issue.py` | COMPLETE_P0 | issue lifecycle UI 和批量修复仍是 P1 |
| Loop Engineering | LoopRun/Step/Checkpoint/Report、budget/blocking/provider/human stop | `src/novel_forge/modules/loop_kernel/service.py`, `tests/unit/test_loop_kernel.py` | CORE_COMPLETE | 尚未替换所有人工 workflow loop |
| Longform Recap Agent | 12 章触发、ContextBundle、Loop、ReviewIssue、MKAOS、治理回写 | `src/novel_forge/modules/longform_recap/service.py`, `tests/unit/test_longform_recap_agent.py` | CORE_COMPLETE | 真实语义质量依赖后续模型/Canon 深化 |
| Agent Center | AgentTask/Run/Handoff/registry/snapshot/API/UI，issue 可派发 revision task | `src/novel_forge/modules/agent_scheduler`, `web/admin/app/features/os/EditableAssetConsolePage.tsx` | MINIMAL_COMPLETE | operation coverage、hard-stop UI、rollback depth 仍是 P1 |
| UI Editable Console | Canon/Character/Arc/Foreshadowing/ReviewIssue/Recap/Loop/Agent/Publish/Feedback routes | `web/admin/app/*`, `web/admin/tests/feature-architecture.test.mjs` | MINIMAL_COMPLETE | 领域专用表单、血缘图、批量治理仍是 P1/P2 |
| Publish / Feedback Loop | Publish gate + release package + source isolation + feedback backflow + MKAOS weight update | `src/novel_forge/modules/audit/service.py`, `src/novel_forge/modules/feedback/service.py`, `tests/unit/test_publish_feedback_loop.py` | CORE_COMPLETE | 平台反馈强 schema 和外部平台 adapter 是 P1/P2 |
| Provider Hard-stop | token/cost/timeout/cancel proof，no silent retry/fallback | `tests/unit/test_provider_hard_stop_proof.py`, `src/novel_forge/modules/runtime_policy/service.py` | COMPLETE_P0 | 自动 fallback 策略需要显式 operator/Agent policy |
| 12 章压力测试 | MKAOS、Context Builder、ReviewIssue、LoopRun、Recap、Gate、Release、source isolation 同测 | `tests/integration/test_novel_os_12_chapter_industrial_pressure.py` | COMPLETE_P0 | 更长 50/100 章仍应保持 opt-in 慢测试 |
