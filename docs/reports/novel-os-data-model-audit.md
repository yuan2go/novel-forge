# Novel OS Data Model Audit

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：核心领域对象、schema、资产形态、版本、来源、状态机、审计字段。  

## 总体判断

Novel OS 数据模型已经覆盖大量 asset type，并通过 `schemas/base.py` 的 required fields 和 storage 层形成文件优先的资产系统。问题在于：领域对象行为仍偏浅，许多能力以 JSON asset 方式表达，状态机和 provenance 约束并非每个域都一样硬。

## 领域对象审计

| 对象 | 当前证据 | 成熟度 | 主要缺口 |
| --- | --- | ---: | --- |
| NovelProject | API/project/workspace 相关 service | 6 | workspace path、project id、runtime root 约束需更硬 |
| Genre | `data/genres/`、topic/platform strategy | 5 | market/platform 证据和 version 需更结构化 |
| Material | `modules/materials/`、MKAOS ingestion | 7 | lineage/confidence 已有但使用强度需统一 |
| KnowledgeAsset | `modules/mkaos/`、`schemas/assets.py` | 8 | service 过大，quality signal 需模块化 |
| Worldview | `modules/worldbuilding/` | 6 | 与 continuity graph 强绑定不足 |
| Character | `modules/characters/`、`character_state` | 6 | character state ledger 与章节 gate 需强制 |
| Outline | `modules/outline/`、`long_planning` | 6 | beat/canon seeds 可更结构化 |
| DetailedOutline | `modules/chapter_plan/` | 6 | conflict/payoff/hook gate 可更硬 |
| Chapter | `modules/drafting/`、`editor` | 6 | draft candidate、accepted version、rollback lineage 需统一审计 |
| ReviewIssue | `modules/review_issue/` | 8 | 需禁止自由文本阻断旁路 |
| Canon | `modules/canon_graph/` | 7 | CanonPatch 应成为所有更新唯一入口 |
| Foreshadowing | `modules/continuity_graph/`、schemas | 6 | payoff 状态和 publish gate 连接需强化 |
| Arc | `longform_stability`、`longform_recap` | 6 | arc plan 与 character/canon graph 需统一 |
| AgentRun | `modules/agent_runs/` | 8 | 业务 operation coverage 需扩大 |
| WorkflowRun | `workflow_nodes`、`loop_kernel` | 7 | 状态机拆分和 tests 需加强 |
| EvalCase | `modules/evaluation_center/` | 5 | 与 provider/release hard-stop 联动不足 |
| EvalResult | `modules/evaluation_center/` | 5 | score/confidence/regression gate 需应用到主链 |
| ReaderFeedback | `modules/feedback/` | 6 | PII 边界和 backflow 变更任务化需继续 |
| ReleasePackage | `modules/audit/service.py` | 7 | publishing facade 边界需清晰 |
| OS Envelope | `modules/os_envelope/` | 8 | 所有 model-producing operation coverage 需证明 |
| Context Bundle | `modules/context_builder/` | 8 | 性能、去重、budget telemetry 需加强 |

## 数据结构风险

1. `schemas/base.py` 作为集中 required field registry，短期高效，长期会导致 schema drift 和大文件风险。
2. 许多 domain 对象以 asset JSON 表达，缺少更强行为模型和状态转换类型。
3. 文件存储优先使本地开发快速，但百万字长篇需要更明确的分页、索引、查询边界和压缩策略。
4. `ReviewIssue`、`AgentRun`、`OS Envelope` 已成熟，应作为其他数据模型收敛的参考。
5. Eval/Release/Feedback 的状态机还不如 AgentRun/ReviewIssue 明确。

## 不建议立即做的事

- 不应一次性替换文件资产模型为数据库 ORM。
- 不应破坏已有 `.local` workspace 和 local-first 约定。
- 不应为每个对象新增平行 schema。应先从现有 `schemas` 中拆分域模块。

