# AC-19 文档与变更治理

状态：`PLANNED`  
阶段：Phase 0–5 / Continuous Governance  
前置依赖：全部工作包持续接入

## 1. ADR

### 背景

仓库中同时存在 Blueprint、设计方案、阶段实施报告、历史“current/final”报告、测试证明和当前状态文档。若这些文档使用相同语气，后续 Claude Code、Codex、开发者和审计者容易把目标设计、代码存在和真实生产证明混为一体，形成错误开发基线。

### 决策

固定文档类型、权威顺序和变更纪律：

```text
Code and current migrations/tests
> Current State and Active Architecture
> Accepted ADR
> Active Implementation Plan
> Design Proposal
> Historical Report
```

文档类型职责：

- Blueprint：最终产品目标；
- Architecture：当前已接受的稳定结构；
- ADR：不可逆决策和原因；
- Design：尚未完整实现的方案；
- Plan/Epic：工作顺序、依赖和 Gate；
- Current State：当前代码事实和证明标志；
- Report：某次审计、测试或执行结果；
- Archive：历史材料。

任何文档不得仅因“代码路径存在”就宣称 production verified。

## 2. 元数据规范

当前/架构/计划文档顶部至少记录：

```text
title
updated_at
status
branch
code_baseline_sha
document_owner
evidence_level
supersedes
related_adrs
related_work_packages
```

执行报告还必须记录命令、环境、commit SHA、测试数量、跳过项、失败项和 artifact references。

## 3. 证明语言

统一状态：

```text
architecture_defined
implementation_present
locally_verified
integration_proven
deployment_verified
external_execution_proven
longform_proven
multi_book_proven
production_verified
```

不得使用模糊的“已完成”“生产级”“最终闭环”替代具体证明等级。Fixture、scripted provider 和历史测试必须明确标注限制。

## 4. 变更治理

以下变更必须同步文档：

| 变更 | 必须更新 |
|---|---|
| Authority ownership | Context map、data ownership、ADR、current state |
| Operation/Saga/Attempt | AC-05、API/Event、tests、module map |
| AssetVersion | AC-06、schema、affected domain docs |
| Plan hierarchy | AC-07、Book Supervisor、blueprint traceability |
| StoryState/Canon | AC-08、Context、longform tests |
| ContextManifest | AC-09、Provider、Agent、Quality |
| Provider/Route/Cost | AC-12、deployment、test matrix |
| Public API/Event | AC-15、OpenAPI、frontend client |
| Deployment/Security | AC-16、env examples、runbook |
| Legacy removal | AC-17、current state、migration report |

PR 模板必须包含：Architecture Impact、ADR、Migration、Backward Compatibility、Rollback/Forward Fix、Evidence、Docs Updated。

## 5. 代码与文档位置

### 当前入口

- `docs/README.md`
- `docs/project-current-state.md`
- `docs/architecture/`
- `docs/product/capability-map.md`
- `docs/quality/regression-tests.md`
- `docs/roadmap/current-roadmap.md`
- `docs/reports/current-engineering-state.md`
- `docs/reports/2026-08-01-code-audit-and-documentation-rebaseline.md`

### 本 Epic 入口

- `docs/architecture-closure/README.md`
- `docs/architecture-closure/autonomous-novel-os-architecture-closure-epic.md`
- `docs/architecture-closure/ac-00...ac-19`

### 目标新增

- `docs/adr/README.md`
- `docs/runbooks/`
- `docs/contracts/`
- `docs/reports/evidence/`
- `scripts/docs/check_document_metadata.py`
- `scripts/docs/check_current_links.py`
- `scripts/docs/check_evidence_claims.py`
- `.github/pull_request_template.md`
- `.github/CODEOWNERS`

## 6. 迁移脚本设计

本工作包不新增业务数据库 migration。文档迁移脚本：

```text
scripts/docs/inventory_documents.py
scripts/docs/classify_documents.py
scripts/docs/generate_current_index.py
scripts/docs/check_duplicate_current_claims.py
scripts/docs/check_broken_links.py
scripts/docs/check_code_path_references.py
scripts/docs/archive_superseded_documents.py
```

归档不得删除历史报告；应移动或加显著 historical/superseded 标记并保留原提交历史。

## 7. 实施计划

1. 建立文档 taxonomy、metadata schema 和 evidence language。
2. 将 Architecture Closure 设为下一阶段 Epic 入口。
3. 建立 ADR index、contract index、runbook index 和 evidence report index。
4. 标记历史“current/final/complete”文档为 historical/superseded。
5. 在 PR 模板加入架构与文档检查。
6. 建立链接、路径、metadata 和 evidence claim CI。
7. 每个 AC 完成时更新工作包状态、current state 和 acceptance report。
8. 每个 milestone 生成一个绑定 SHA 的证据报告，不覆盖旧报告。

## 8. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Metadata | Active 文档缺 baseline/status | CI 失败 |
| Link | 入口引用不存在文档 | CI 失败 |
| Code path | Active architecture 引用不存在路径 | CI 失败或标记 planned |
| Evidence claim | fixture 文档写 production_verified=true | CI 失败 |
| Duplicate current | 多个 current state 未互相 supersede | CI 失败 |
| ADR relation | 架构文档改变核心决策无 ADR | CI 失败 |
| PR checklist | Authority/migration 变更未更新 docs | required check 失败 |
| Archive | 历史报告仍在首选阅读路径 | index test 失败 |

## 9. Acceptance Gate

```text
document_taxonomy_active=true
current_document_entrypoints_unique=true
architecture_closure_epic_linked=true
adr_and_evidence_indexes_active=true
document_metadata_ci_active=true
evidence_claim_ci_active=true
historical_current_claims_superseded=true
pr_architecture_documentation_governance_active=true
```

## 10. 工作包关闭规则

任何 AC 不得仅通过合并代码关闭。关闭必须包含：

1. 实现 commit SHA；
2. migration identifiers；
3. test commands/results/counts；
4. deployment/external evidence（如适用）；
5. remaining limitations；
6. rollback/forward-fix strategy；
7. current state、module map、capability map 和 roadmap 更新；
8. 独立 Acceptance Report。

## 11. 风险

- 文档维护成本过高：只对 active/current/ADR/contract/runbook 强制元数据，历史文档不批量重写。
- 自动证据扫描误判自然语言：优先扫描标准状态字段和报告 front matter。
- 文档成为实现阻塞：提供模板和生成脚本，但不降低证据要求。
- AI Agent 读取错误入口：`docs/README.md`、`CLAUDE.md` 和 Epic index 必须保持唯一推荐阅读顺序。