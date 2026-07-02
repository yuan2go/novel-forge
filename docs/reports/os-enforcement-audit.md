# OS Enforcement Audit

Surface evidence status: `blocked`
Surface score: `43`

Note: the matrix below audits code-path enforcement. `Strict Blockers` records current local-workspace evidence gaps for operations that have not been exercised in this run.

| Path | Type | Mutates Production | Calls Model | Has OS Envelope | Has Trace | Has Cost Ledger | Has Publishing Gate | Status | Required Fix |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| API /product/production/generation-run | draft generation service | yes | yes | yes | yes | yes | yes | enforced | none |
| API /product/reviews/run | review service | yes | yes | yes | yes | yes | yes | enforced | none |
| API /product/revisions/rework-loop | revision service | yes | yes | yes | yes | yes | yes | enforced | none |
| API /product/publishing/gate | publishing gate | yes | no | yes | yes | yes | yes | enforced | none |
| API /product/publishing/release-package | release packaging | yes | no | no | yes | yes | yes | enforced | none |
| API /product/longform-stability/extract | model assisted extraction | yes | yes | yes | yes | yes | yes | enforced | none |
| API /product/feedback/backflow-apply | feedback mutation | yes | no | yes | yes | yes | no | compatible | keep read-only/manual mutation boundary documented |
| CLI pipeline draft/review/revise | CLI workflow wrapper | yes | yes | yes | yes | yes | yes | enforced | none |
| Workflow processor release_package | workflow processor | yes | no | no | yes | yes | yes | enforced | none |
| Agent Scheduler registered operations | agent task | yes | yes | yes | yes | yes | yes | enforced | none |
| Import services ingest/clean | import service | no | no | no | yes | yes | no | compatible | keep read-only/manual mutation boundary documented |
| Asset metadata/content editor | manual asset mutation | yes | no | no | yes | yes | no | compatible | keep read-only/manual mutation boundary documented |
| Novel KG semantic extraction | KG extraction | yes | yes | yes | yes | yes | no | enforced | none |
| Publishing adapter release | platform adapter | yes | no | yes | yes | yes | yes | enforced | none |
| Rollback rehearsal/apply | rollback operation | yes | no | yes | yes | yes | no | compatible | keep read-only/manual mutation boundary documented |
| Pgvector migration/ops | ops path | no | no | yes | yes | yes | no | compatible | keep read-only/manual mutation boundary documented |

## Strict Blockers

- runtime evidence missing: analysis_convert
- runtime evidence missing: analysis_run
- runtime evidence missing: develop_topic
- runtime evidence missing: draft
- runtime evidence missing: draft_chapter
- runtime evidence missing: editor_patch
- runtime evidence missing: feedback_backflow
- runtime evidence missing: feedback_cluster
- runtime evidence missing: generate_chapter_plan
- runtime evidence missing: generate_draft
- runtime evidence missing: generate_outline
- runtime evidence missing: handoff_review
- runtime evidence missing: model_assisted_longform_extraction
- runtime evidence missing: model_benchmark
- runtime evidence missing: publish_gate_report
- runtime evidence missing: publishing_log
- runtime evidence missing: publishing_plan
- runtime evidence missing: review
- runtime evidence missing: review_rework_loop
- runtime evidence missing: revise
- runtime evidence missing: semantic_kg_extract

## Required Fixes

- none
