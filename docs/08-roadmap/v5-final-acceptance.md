# V5 Final Acceptance

## Current Capability

V5 provides a runnable CLI-first local novel production pipeline using mock model outputs and schema-backed JSON files.

## Main Pipeline

The P0 pipeline is implemented and verified:

```text
source material -> cleaned text -> decomposition -> knowledge -> materials -> topic -> world -> characters -> outline -> chapter plan -> draft -> review -> revision plan -> feedback insight
```

## Completed P0

- Project skeleton and clean directory layout.
- Product, architecture, workflow, schema, module, testing, operations, audit, and roadmap docs.
- 26 dataclass schemas with common traceability fields.
- Local JSON storage and data lifecycle separation.
- CLI command set required by the V5 brief.
- Mock model adapter and local rule engine.
- Review report and revision plan outputs.
- Feedback import and analysis.
- End-to-end sample pipeline.
- Repository-level Skills system with 14 reusable creative/review/planning/material/training capabilities.
- Pipeline TaskStatus records for pending/running/completed/failed step visibility.
- Run log summaries and recovery instructions on pipeline failures.
- Clean sample pipeline mode that removes the previous summary-referenced sample outputs before rerun.
- Fail-closed provider adapter contract skeletons for Claude Code, Codex, ChatGPT, and DeepSeek.
- Directory batch ingestion for `.txt`, `.md`, `.epub`, `.mobi`, and `.azw3` fixtures.
- Enhanced cleaning for OCR-style spacing noise, conservative ad/watermark removal, repeated blank collapse, and chapter detection.
- Searchable material tags and local asset search/list/filter by category, schema type, tag, and keyword.
- Schema-backed `topic-development` and `training-exercise` CLI workflows for differentiated topic assets and reusable writing practice assets.
- Reusable local retrieval index at `data/indexes/retrieval-index.json`, with explicit `build-index`, default indexed search, stale-index auto-refresh, and direct scan fallback.
- Local relevance ranking and hash-vector retrieval through `search --rank relevance`, `build-vector-index`, and `vector-search`.
- Multi-model mock review comparison through `compare-reviews`, producing schema-backed `ReviewReport` assets with model reviews, score summary, consensus, disagreements, and revision priorities.
- Long-project workspace state through `ProjectWorkspaceState`, `init-workspace`, `update-workspace`, and `workspace-status`.
- Feedback trend analysis in `FeedbackInsight`, including chapter trends, retention risk, sentiment signals, plot adjustment plan, and next-generation constraints.
- Risk reduction pass: stricter semantic validation for high-risk assets, runtime Skill drift detection, and automatic sample pipeline workspace updates.
- External Claude Code resource intake gate with a read-only local evaluation command and documented adopt/adapt/defer/reject policy.

## Current Commands

```bash
make test
make lint
make validate
make demo
make check-skills
./novel-forge --help
./novel-forge init --root .
./novel-forge topic-development --root .
./novel-forge training-exercise --root .
./novel-forge build-index --root .
./novel-forge build-vector-index --root .
./novel-forge vector-search --query "chapter hook obligation" --root .
./novel-forge compare-reviews --root .
./novel-forge init-workspace --title "Echo Clock Project" --root .
./novel-forge update-workspace --input data/drafts/example.json --chapter 1 --root .
./novel-forge workspace-status --root .
./novel-forge status --root .
```

## Test Coverage

- 41 unittest tests pass.
- Tests cover schema, storage, model adapter, CLI, workflow steps, module services, pipeline status records, failure status records, Skills structure, and end-to-end pipeline.
- Topic/training tests cover both direct service calls and CLI commands that write valid `TopicSeed` and `TrainingExercise` JSON assets.
- Retrieval tests cover index build, default indexed search, stale-index auto-refresh, CLI build-index, and direct JSON scan fallback.
- Vector/relevance tests cover deterministic hash embeddings, relevance ranking, vector index build, vector-search scoring, and CLI vector commands.
- Review comparison tests cover mock reviewer profiles, comparison report content, and CLI `compare-reviews`.
- Workspace tests cover schema validation, service-level multi-chapter tracking, CLI initialization, CLI updates, and status summary.
- Feedback trend tests cover cross-chapter rating decline, retention risk level, sentiment signals, and next-generation constraints.
- Risk-reduction tests cover semantic validation, Skill runtime drift detection, and automatic workspace output from sample pipeline.
- External resource intake tests cover read-only command boundaries, execution-surface review sections, import decisions, and Novel Forge runtime boundaries.
- Sample pipeline tests generate a full run in a temporary project root.
- Repeated sample pipeline runs clean the previous summary-referenced sample outputs before generating the next sample run.

## Expected Clean Sample Asset Counts

| Directory | Count |
|---|---:|
| raw | 1 |
| cleaned | 1 |
| decompositions | 1 |
| knowledge | 1 |
| materials | 1 |
| topics | 1 |
| worlds | 1 |
| characters | 1 |
| outlines | 1 |
| chapter_plans | 1 |
| drafts | 1 |
| reviews | 2 |
| feedback | 2 |
| training | 0 |
| image_prompts | 0 |
| workspaces | 1 |
| runs | 55 |

## Remaining Risks

- Real LLM adapters are not implemented yet.
- Provider adapter contracts exist, but external API calls remain intentionally unimplemented.
- Review comparison uses local mock reviewer profiles, not real external reviewers.
- MOBI/AZW3 ingestion is fixture-level text extraction without full proprietary ebook parsing.
- Cleaning is deterministic and conservative; it does not replace full OCR correction or semantic boilerplate detection.
- Local vector retrieval uses deterministic hash embeddings, not a real semantic embedding model or vector database.
- Schema validation now includes deterministic semantic checks for selected high-risk assets, but full Pydantic-style validation remains deferred.
- Module service files now hold P0 workflow step logic, but deeper domain-specific production logic remains mock/simple.
- Retrieval/vector/database layers are intentionally deferred.
- Training has a minimal schema-backed CLI workflow, but adaptive reader/writer training remains deferred.
- Image prompt modules have schemas/directories but not full workflows.
- Workspace state is auto-updated by the sample pipeline for draft/review, but custom long-form flows still need explicit workspace update calls.
- Feedback trend analysis uses deterministic rating and keyword rules, not statistical modeling or external LLM interpretation.
- `.claude/skills` runtime output can still drift if edited manually, but `make check-skills` now detects drift.
- External Claude Code resource intake is documented and bounded, but future hooks/plugins/MCP adoption still requires ADR, opt-in, and executable tests.
