# V5 Task Pool

| ID | Phase | Task | Status | Acceptance |
|---|---|---|---|---|
| V5-P0-001 | 0 | Review V4 and write migration audits | done | audit docs exist |
| V5-P0-002 | 1 | Build project skeleton and CLI | done | `./novel-forge --help` works |
| V5-P0-003 | 2 | Implement schemas and local storage | done | schema/storage tests pass |
| V5-P0-004 | 3 | Implement ingest and clean | done | commands produce raw/cleaned JSON |
| V5-P0-005 | 4 | Implement decomposition, knowledge, materials | done | commands produce abstract assets |
| V5-P0-006 | 5 | Implement creative generation chain | done | topic through draft assets produced |
| V5-P0-007 | 6 | Implement review, revision, feedback | done | review/revision/feedback assets produced |
| V5-P0-008 | 7 | Implement end-to-end pipeline | done | `make demo` produces run summary |
| V5-P0-009 | 8 | Add reusable Skills system | done | 8 core Skills exist and validate through `make validate` and `make test` |
| V5-P0-010 | 8 | Add Skill runtime sync and second-stage Skills | done | sync dry-run works; 11 Skills validate |
| V5-P0-011 | 8 | Add topic, material, and training Skills | done | topic-development, material-curation, and training-exercise validate |
| V5-OPT-P0-001 | optimization | Strengthen type-level asset validation | done | malformed assets fail validation; sample assets pass |
| V5-OPT-P0-002 | optimization | Split workflow step logic into module services | done | CLI behavior unchanged; direct module service tests pass |
| V5-OPT-P0-003 | optimization | Add task and run status records | done | Pipeline writes TaskStatus/WorkflowRun status assets; failure status is tested |
| V5-OPT-P0-004 | optimization | Add run logs and failure recovery | done | Failed step produces clear run log and recovery instruction |
| V5-OPT-P0-005 | optimization | Add deterministic demo mode | done | Demo can run in clean sample mode without duplicate random assets |
| V5-P1-001 | later | Add real model adapters | partially done | provider contracts exist; real API implementations still deferred |
| V5-P1-002 | later | Add richer schema validation | pending | strict validation suite |
| V5-P1-003 | later | Automate Claude Code runtime Skill refresh in agent workflow | pending | agent workflow invokes sync command when needed |
| V5-P2-001 | later | Add vector retrieval | done | local hash-vector index and vector-search tests pass |
| V5-OPT-P1-001 | optimization | Add real model adapter contracts | done | Adapter health checks and mocked tests pass |
| V5-OPT-P1-002 | optimization | Add richer material ingestion | done | CLI can ingest directory fixtures for `.txt`, `.md`, `.epub`, `.mobi`, and `.azw3` |
| V5-OPT-P1-003 | optimization | Improve cleaning rules | done | Cleaning tests cover noisy fixture text |
| V5-OPT-P1-004 | optimization | Add material tags and local search | done | CLI and storage search list/filter assets by category, type, tags, and keyword |
| V5-OPT-P1-005 | optimization | Add topic and training workflows | done | `topic-development` and `training-exercise` produce schema-backed assets |
| V5-OPT-P2-001 | optimization | Add local retrieval, relevance rank, and hash-vector search | done | `build-index`, `search --rank relevance`, `build-vector-index`, and `vector-search` pass without external services |
| V5-OPT-P2-002 | optimization | Add multi-model review comparison | done | `compare-reviews` generates mock review-comparison report |
| V5-OPT-P2-003 | optimization | Add long project workspace state | done | `ProjectWorkspaceState` tracks multiple chapters and workspace status |
| V5-OPT-P2-004 | optimization | Add feedback trend analysis | done | FeedbackInsight includes chapter trends, retention risk, sentiment signals, and plot adjustment plan |
| V5-RISK-001 | risk-reduction | Reduce remaining deterministic/local workflow risks | done | Semantic validators, Skill drift check, and sample workspace auto-update pass tests |
| V5-RISK-002 | risk-reduction | Add external Claude Code resource intake gate | done | Local evaluation command and intake policy exist; tests and validation pass |
| V5-RISK-003 | risk-reduction | Add industrialization safeguards for storage, rights, creative gates, and long fixtures | done | Atomic writes, backups, SQLite manifest, rights metadata, creative gates, and long-project fixture tests pass |

## Auto Optimization Analysis

| ID | Impact Scope | Risk | Priority | Suggested Order |
|---|---|---|---|---|
| V5-OPT-P0-001 | Schema validation and project validation | medium | P0 | 1 |
| V5-OPT-P0-002 | Workflow/module boundary and tests | medium | P0 | 2 |
| V5-OPT-P0-003 | Pipeline orchestration, TaskStatus, WorkflowRun, tests | medium | P0 | 3 |
| V5-OPT-P0-004 | Pipeline diagnostics, operations docs, failure handling | medium | P0 | 4 |
| V5-OPT-P0-005 | Demo command, sample outputs, storage cleanup policy | medium | P0 | 5 |
| V5-OPT-P1-001 | Model adapter contracts | medium | P1 | 6 |
| V5-OPT-P1-002 | Ingestion CLI/services/tests | medium | P1 | 7 |
| V5-OPT-P1-003 | Cleaning service/tests | low | P1 | 8 |
| V5-OPT-P1-004 | Storage listing/filtering, material metadata | medium | P1 | 9 |
| V5-OPT-P1-005 | CLI and schemas for topic/training extensions | medium | P1 | 10 |
| V5-OPT-P2-001 | Retrieval index and search tests | medium | P2 | 11 |
| V5-OPT-P2-002 | Review orchestration | low | P2 | 12 |
| V5-OPT-P2-003 | Workspace state model | high | P2 | 13 |
| V5-OPT-P2-004 | Feedback analytics | medium | P2 | 14 |

## Optimization Task Queue

| ID | Goal | Files | Change Type | Risk | Preconditions | Acceptance | Rollback |
|---|---|---|---|---|---|---|---|
| V5-OPT-P0-003 | Record task/run status for pipeline execution and failures. | `src/novel_forge/workflows/status.py`, `src/novel_forge/workflows/pipeline.py`, `src/novel_forge/schemas/base.py`, tests, roadmap docs | code + tests + docs | medium | P0-001 and P0-002 complete | `make test` covers success and failure status; `make validate` passes | Revert status wrapper, schema status checks, and tests |
| V5-OPT-P0-004 | Add run logs and recovery guidance. | workflow/status modules, operations docs, tests | code + tests + docs | medium | P0-003 complete | Failed run has clear log and recovery instruction | Revert run log/recovery note additions and docs |
| V5-OPT-P0-005 | Make demo deterministic or cleanable. | pipeline sample cleanup, tests, docs | code + tests + docs | medium | P0-003 status records stable | repeated demo does not accumulate duplicate random sample assets | Revert sample cleanup function and summary fields |
| V5-OPT-P1-001 | Add real model adapter contracts. | `src/novel_forge/model_adapters/`, tests, model collaboration docs | code + tests + docs | medium | P0 status/logging stable | Provider skeleton health checks pass; operations fail closed without external API calls | Revert provider skeletons, exports, tests, and docs |
| V5-OPT-P1-002 | Add richer material ingestion. | `src/novel_forge/modules/ingestion/service.py`, CLI, tests, docs | code + tests + docs | medium | P1-001 complete | Directory fixture import supports `.txt`, `.md`, `.epub`, `.mobi`, `.azw3`; CLI/service tests pass | Revert ingestion reader/discovery changes, CLI batch output changes, tests, and docs |
| V5-OPT-P1-003 | Improve cleaning rules. | `src/novel_forge/modules/cleaning/service.py`, tests, docs | code + tests + docs | low | P1-002 complete | Cleaning removes noisy fixture lines, normalizes OCR noise, collapses blanks, detects chapters; tests pass | Revert cleaning rule helpers, cleaning tests, and docs |
| V5-OPT-P1-004 | Add material tags and local search. | `src/novel_forge/storage/search.py`, `src/novel_forge/modules/materials/service.py`, CLI, tests, docs | code + tests + docs | medium | P1-003 complete | CLI/storage search can filter by category, type, tag, and keyword; material tags are searchable; tests pass | Revert search service, CLI search command, material tag additions, tests, and docs |
| V5-OPT-P1-005 | Add topic and training workflows. | `src/novel_forge/modules/topics/service.py`, `src/novel_forge/modules/training/service.py`, pipeline, CLI, tests, docs | code + tests + docs | medium | P1-004 complete | `topic-development` and `training-exercise` commands write valid `TopicSeed` and `TrainingExercise` assets | Revert topic/training service changes, CLI command additions, tests, and docs |
| V5-OPT-P2-001 | Add local retrieval index, relevance ranking, and hash-vector search. | `src/novel_forge/storage/retrieval_index.py`, `src/novel_forge/storage/vector_index.py`, `src/novel_forge/model_adapters/embeddings.py`, search, pipeline, CLI, tests, docs | code + tests + docs | medium | P1-005 complete | `build-index`, indexed search, relevance ranking, vector index, and vector search tests pass without external services | Revert retrieval/vector index modules, embedding adapter, CLI flags/commands, search delegation, tests, and docs |
| V5-OPT-P2-002 | Add multi-model review comparison. | `src/novel_forge/modules/review/service.py`, pipeline, CLI, tests, docs | code + tests + docs | low | P2-001 complete | `compare-reviews` writes a schema-backed `ReviewReport` containing mock reviewer outputs, score summary, consensus, disagreements, and revision priorities | Revert compare review service, pipeline/CLI entries, tests, and docs |
| V5-OPT-P2-003 | Add long project workspace state. | `src/novel_forge/modules/workspace/service.py`, schemas, constants, pipeline, CLI, tests, docs | code + tests + docs | high | P2-002 complete | `init-workspace`, `update-workspace`, and `workspace-status` track multiple chapters, continuity hooks, memory, and open issues | Revert workspace schema, data directory, workspace service, CLI/pipeline entries, tests, and docs |
| V5-OPT-P2-004 | Add feedback trend analysis. | `src/novel_forge/modules/feedback/service.py`, tests, docs | code + tests + docs | medium | P2-003 complete | `FeedbackInsight` includes per-chapter trends, retention risk, sentiment signals, and next-generation plot constraints | Revert feedback trend helper functions, tests, and docs |
| V5-RISK-001 | Reduce remaining deterministic/local workflow risks. | schema validation, `scripts/sync_claude_skills.py`, `Makefile`, sample pipeline, tests, docs | code + tests + docs | medium | P2 complete | High-risk asset semantic validators pass; Skill runtime drift can be detected; sample pipeline auto-updates workspace | Revert semantic validators, skill check mode, pipeline workspace run steps, tests, and docs |
| V5-RISK-002 | Add external Claude Code resource intake gate. | `.claude/commands/evaluate-claude-resource.md`, `docs/09-skills/external-resource-intake.md`, constants, tests, roadmap docs | docs + tests | low | Skill runtime sync and risk reduction complete | External resource review command is read-only and validated; docs classify adopt/adapt/defer/reject decisions | Revert command template, intake doc, constants entry, and test |
| V5-RISK-003 | Add industrialization safeguards for storage, rights, creative gates, and long fixtures. | storage, ingestion, review, schemas, CLI, tests, docs | code + tests + docs | medium | V5-RISK-002 complete | `make test`, `make validate`, `build-manifest`, and long fixture tests pass | Revert storage lock/manifest, rights metadata, creative gate, long fixture, and docs if contracts need redesign |

## Latest Auto Execution Report

| Item | Result |
|---|---|
| Batch | P0 optimization batch 3 |
| Completed | `V5-OPT-P0-004`, `V5-OPT-P0-005` |
| Modified Reason | Status records were in place; the next blockers were diagnosable failures and clean repeatable sample runs. |
| Tests | `make lint`, `make test`, `make validate`, two temp-root sample CLI runs |
| Result | `make lint` pass; `make test` pass with 19 tests; `make validate` pass; repeated temp demo did not accumulate duplicate sample assets |
| Unfinished | all P1/P2 optimization tasks |
| Key Risk | Sample cleanup only removes files referenced by the previous `pipeline-summary.json`; older untracked sample artifacts not listed in summary are left untouched by design. |
| Rollback Advice | Revert `workflows/status.py` run log helpers, `pipeline.py` sample cleanup/recovery fields, and related tests/docs if cleanup or recovery behavior causes compatibility issues. |

## P1 Execution Report

| Item | Result |
|---|---|
| Batch | P1 optimization batch 1 |
| Completed | `V5-OPT-P1-001` |
| Modified Reason | Real model integration needs stable contracts before any provider dependency or secret handling is introduced. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 21 tests; `make validate` pass |
| Unfinished | `V5-OPT-P1-002` through `V5-OPT-P1-005`, all P2 tasks |
| Key Risk | Provider skeletons are not production model integrations; they intentionally fail closed for generation/review operations. |
| Rollback Advice | Revert `model_adapters/providers.py`, base config/error additions, adapter exports, contract tests, and docs if the contract shape needs redesign. |

## P1 Execution Report 2

| Item | Result |
|---|---|
| Batch | P1 optimization batch 2 |
| Completed | `V5-OPT-P1-002` |
| Modified Reason | Batch source ingestion is required before scalable material curation, cleaning, and local search can be useful. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 24 tests; `make validate` pass |
| Unfinished | `V5-OPT-P1-003` through `V5-OPT-P1-005`, all P2 tasks |
| Key Risk | MOBI/AZW3 support is fixture-level text extraction without proprietary ebook parsing dependencies. |
| Rollback Advice | Revert ingestion format readers, `ingest_many`, CLI batch output, fixture tests, and docs if ingestion contract needs redesign. |

## P1 Execution Report 3

| Item | Result |
|---|---|
| Batch | P1 optimization batch 3 |
| Completed | `V5-OPT-P1-003` |
| Modified Reason | Better cleaning is required before batch-imported materials can be decomposed reliably. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 26 tests; `make validate` pass |
| Unfinished | `V5-OPT-P1-004`, `V5-OPT-P1-005`, all P2 tasks |
| Key Risk | Rules are conservative and deterministic; they do not replace full OCR correction or semantic boilerplate detection. |
| Rollback Advice | Revert cleaning helpers, metadata/content additions, tests, and docs if cleaning behavior becomes too aggressive. |

## P1 Execution Report 4

| Item | Result |
|---|---|
| Batch | P1 optimization batch 4 |
| Completed | `V5-OPT-P1-004` |
| Modified Reason | Searchable material tags are needed before the素材库 can support production reuse at scale. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 28 tests; `make validate` pass |
| Unfinished | `V5-OPT-P1-005`, all P2 tasks |
| Key Risk | At completion time search was still linear; this was later superseded by `V5-OPT-P2-001`. |
| Rollback Advice | Revert `storage/search.py`, search CLI, material tag facets, search tests, and docs if search contract needs redesign. |

## P1 Execution Report 5

| Item | Result |
|---|---|
| Batch | P1 optimization batch 5 |
| Completed | `V5-OPT-P1-005` |
| Modified Reason | Topic and training Skills needed runnable CLI workflows that write schema-backed assets, not only Markdown instructions. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 29 tests; `make validate` pass |
| Unfinished | all P2 tasks |
| Key Risk | Training exercises are deterministic local prompts and rubrics; they are not full adaptive education workflows yet. |
| Rollback Advice | Revert `training.service`, topic-development enrichment, pipeline/CLI entries, tests, and docs if command contracts need redesign. |

## P2 Execution Report 1

| Item | Result |
|---|---|
| Batch | P2 optimization batch 1 |
| Completed | `V5-OPT-P2-001` |
| Modified Reason | Linear search was usable for small fixtures but not reusable enough for larger local asset libraries. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 30 tests; `make validate` pass |
| Unfinished | `V5-OPT-P2-002` through `V5-OPT-P2-004` |
| Key Risk | The first retrieval index was lexical only; semantic-style ranking and hash-vector plumbing were added in the extension report below. |
| Rollback Advice | Revert `storage/retrieval_index.py`, search index delegation, CLI build/index flags, tests, and docs if index format needs redesign. |

## P2 Execution Report 2

| Item | Result |
|---|---|
| Batch | P2 optimization batch 1 extension |
| Completed | `V5-OPT-P2-001` semantic/vector extension |
| Modified Reason | The first local index removed linear scans but did not provide semantic-style ranking or vector retrieval plumbing. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 33 tests; `make validate` pass |
| Unfinished | `V5-OPT-P2-002` through `V5-OPT-P2-004` |
| Key Risk | Hash-vector retrieval is deterministic and local, not a real embedding model or vector database. |
| Rollback Advice | Revert `model_adapters/embeddings.py`, `storage/vector_index.py`, relevance ranking changes, vector CLI commands, tests, and docs if retrieval contracts need redesign. |

## P2 Execution Report 3

| Item | Result |
|---|---|
| Batch | P2 optimization batch 2 |
| Completed | `V5-OPT-P2-002` |
| Modified Reason | Single-pass review could not compare reviewer perspectives or expose consensus/disagreement for quality gates. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 34 tests; `make validate` pass |
| Unfinished | `V5-OPT-P2-003`, `V5-OPT-P2-004` |
| Key Risk | Review comparison uses deterministic mock reviewer profiles, not real Claude/ChatGPT/DeepSeek reviewers. |
| Rollback Advice | Revert review comparison service, `compare-reviews` CLI, pipeline wrapper, tests, and docs if report shape needs redesign. |

## P2 Execution Report 4

| Item | Result |
|---|---|
| Batch | P2 optimization batch 3 |
| Completed | `V5-OPT-P2-003` |
| Modified Reason | Multi-chapter production needs a durable project memory and continuity state instead of isolated chapter assets. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 36 tests; `make validate` pass |
| Unfinished | `V5-OPT-P2-004` |
| Key Risk | Workspace state is local JSON and manually updated by CLI; it is not yet automatically integrated into every pipeline step. |
| Rollback Advice | Revert `ProjectWorkspaceState`, `data/workspaces/`, workspace service, CLI/pipeline wrappers, tests, and docs if state shape needs redesign. |

## P2 Execution Report 5

| Item | Result |
|---|---|
| Batch | P2 optimization batch 4 |
| Completed | `V5-OPT-P2-004` |
| Modified Reason | Feedback analysis needed cross-chapter trend, retention risk, and actionable next-generation constraints instead of single-batch average rating. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 37 tests; `make validate` pass |
| Unfinished | none in current P2 optimization pool |
| Key Risk | Trend analysis uses deterministic keyword and rating rules; it is not yet statistically robust or model-assisted. |
| Rollback Advice | Revert feedback trend functions and related tests/docs if feedback insight shape needs redesign. |

## Risk Reduction Report 1

| Item | Result |
|---|---|
| Batch | post-P2 risk reduction |
| Completed | `V5-RISK-001` |
| Modified Reason | Remaining risks included weak semantic validation, runtime Skill drift, and workspace state not being automatically created by the sample pipeline. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 40 tests; `make validate` pass |
| Remaining Strategic Risks | real LLM adapters, real semantic embeddings/vector DB, full ebook parsing, model-assisted feedback interpretation |
| Key Risk | Risk reduction is still local and deterministic; external-provider risks require ADR, dependency policy, and secret policy. |
| Rollback Advice | Revert semantic validators, skill sync `--check`, sample pipeline workspace steps, tests, and docs if contracts need redesign. |

## Risk Reduction Report 2

| Item | Result |
|---|---|
| Batch | external Claude Code resource intake |
| Completed | `V5-RISK-002` |
| Modified Reason | `awesome-claude-code` is valuable as an ecosystem reference, but Novel Forge needs a safety gate before importing Skills, commands, hooks, agents, plugins, or scripts. |
| Tests | `make lint`, `make test`, `make validate` |
| Result | `make lint` pass; `make test` pass with 41 tests; `make validate` pass |
| Remaining Strategic Risks | Future hook/plugin/MCP adoption still requires ADR, explicit opt-in, and executable tests. |
| Key Risk | This pass adds governance and command templates only; it does not verify arbitrary third-party repositories automatically. |
| Rollback Advice | Revert `.claude/commands/evaluate-claude-resource.md`, `docs/09-skills/external-resource-intake.md`, constants, and test additions if the intake policy needs redesign. |

## Risk Reduction Report 3

| Item | Result |
|---|---|
| Batch | industrialization safeguards |
| Completed | `V5-RISK-003` |
| Modified Reason | JSON-only storage, unrecorded source rights, weak creative gates, and small fixture tests were the next blockers before larger functional testing. |
| Tests | `make lint`, `make test`, `make validate`, `make demo`, `build-manifest`, `manifest-status` |
| Result | `make lint` pass; `make test` pass with 50 tests; `make validate` pass; sample demo and manifest build pass |
| Remaining Strategic Risks | Real database/vector services, real LLM providers, full proprietary ebook parsing, and large real-world corpus tests still require ADR and deployment policy. |
| Key Risk | SQLite manifest, local locks, and backups reduce single-user/local risks but are not yet a distributed production storage backend. |
| Rollback Advice | Revert storage lock/manifest, rights metadata validation, creative gate, long fixture, CLI/docs/tests if the industrialization contracts need redesign. |
