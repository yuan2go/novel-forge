# V5 Test Log

| Time | Command | Result | Notes |
|---|---|---|---|
| 2026-06-24 | `make test` | pass | 9 unittest tests passed. |
| 2026-06-24 | `make lint` | pass | Python sources and tests compile. |
| 2026-06-24 | `./novel-forge --help` | pass | CLI lists all required commands. |
| 2026-06-24 | `./novel-forge init --root .` | pass | Local directories initialized. |
| 2026-06-24 | `make validate` | pass | Structure and JSON assets validate. |
| 2026-06-24 | `make demo` | pass | Sample end-to-end pipeline produced a WorkflowRun. |
| 2026-06-24 | `make validate` after demo | pass | Generated JSON assets validate. |
| 2026-06-24 | final `make test` | pass | 9 unittest tests passed after demo generation. |
| 2026-06-24 | `make test` after Skills | pass | 12 unittest tests passed, including Skills structure tests. |
| 2026-06-24 | `make validate` after Skills | pass | Project docs, JSON assets, and 8 core Skills validate. |
| 2026-06-24 | `make sync-skills-dry-run` | pass | Runtime Skill mapping preview writes nothing. |
| 2026-06-24 | `make test` after topic/material/training Skills | pass | 14 Skills are covered by structure tests. |
| 2026-06-24 | `make validate` after topic/material/training Skills | pass | 14 Skills validate through project validation. |
| 2026-06-24 | `make test` after type-level validation | pass | 16 unittest tests passed, including malformed asset validation. |
| 2026-06-24 | `make validate` after type-level validation | pass | Current sample assets pass stricter type-level validation. |
| 2026-06-24 | `make lint` after type-level validation | pass | Python sources and tests compile. |
| 2026-06-24 | `make lint` after module service split | pass | Python sources and tests compile after service extraction. |
| 2026-06-24 | `make test` after module service split | pass | 17 unittest tests passed, including direct module service coverage. |
| 2026-06-24 | `make validate` after module service split | pass | Project docs, JSON assets, and 14 Skills validate after service extraction. |
| 2026-06-24 | `make lint` after task status records | pass | Python sources and tests compile after adding workflow status records. |
| 2026-06-24 | `make test` after task status records | pass | 19 unittest tests passed, including pipeline status and failure status coverage. |
| 2026-06-24 | `make validate` after task status records | pass | Project docs, JSON assets, and 14 Skills validate after status schema changes. |
| 2026-06-24 | `make lint` after run logs and sample cleanup | pass | Python sources and tests compile after recovery and cleanup changes. |
| 2026-06-24 | `make test` after run logs and sample cleanup | pass | 19 unittest tests passed, including run log, recovery note, and repeated sample cleanup assertions. |
| 2026-06-24 | `make validate` after run logs and sample cleanup | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-24 | `PYTHONPATH=src python3 -m novel_forge.cli run-pipeline --sample --root /private/tmp/novel-forge-demo-check` twice | pass | Temp-root repeated sample pipeline ran twice; summary cleanup removed prior sample outputs before the second run. |
| 2026-06-24 | `make lint` after provider adapter contracts | pass | Python sources and tests compile after adding provider skeletons. |
| 2026-06-24 | `make test` after provider adapter contracts | pass | 21 unittest tests passed, including provider skeleton health checks and fail-closed behavior. |
| 2026-06-24 | `make validate` after provider adapter contracts | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-24 | `make lint` after batch ingestion | pass | Python sources and tests compile after adding source format readers. |
| 2026-06-24 | `make test` after batch ingestion | pass | 24 unittest tests passed, including service and CLI directory fixture import. |
| 2026-06-24 | `make validate` after batch ingestion | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-24 | `make lint` after cleaning improvements | pass | Python sources and tests compile after adding cleaning rules. |
| 2026-06-24 | `make test` after cleaning improvements | pass | 26 unittest tests passed, including noisy text cleaning and chapter metadata coverage. |
| 2026-06-24 | `make validate` after cleaning improvements | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-24 | `make lint` after local search | pass | Python sources and tests compile after adding storage search and CLI command. |
| 2026-06-24 | `make test` after local search | pass | 28 unittest tests passed, including storage search, material tags, and CLI search. |
| 2026-06-24 | `make validate` after local search | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-24 | `make lint` after topic/training workflows | pass | Python sources and tests compile after adding topic-development and training-exercise services. |
| 2026-06-24 | `make test` after topic/training workflows | pass | 29 unittest tests passed, including service and CLI coverage for schema-backed topic/training assets. |
| 2026-06-24 | `make validate` after topic/training workflows | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-24 | `make lint` after retrieval index | pass | Python sources and tests compile after adding local retrieval index. |
| 2026-06-24 | `make test` after retrieval index | pass | 30 unittest tests passed, including index build, indexed search, stale-index refresh, and CLI build-index coverage. |
| 2026-06-24 | `make validate` after retrieval index | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-25 | `make lint` after vector/relevance retrieval | pass | Python sources and tests compile after adding hash embeddings, vector index, and relevance ranking. |
| 2026-06-25 | `make test` after vector/relevance retrieval | pass | 33 unittest tests passed, including deterministic embeddings, relevance ranking, vector index, vector-search, and CLI coverage. |
| 2026-06-25 | `make validate` after vector/relevance retrieval | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-25 | `make lint` after multi-model review comparison | pass | Python sources and tests compile after adding compare-reviews. |
| 2026-06-25 | `make test` after multi-model review comparison | pass | 34 unittest tests passed, including service and CLI coverage for schema-backed review comparison reports. |
| 2026-06-25 | `make validate` after multi-model review comparison | pass | Current repository docs, JSON assets, and 14 Skills validate. |
| 2026-06-25 | `make lint` after workspace state | pass | Python sources and tests compile after adding ProjectWorkspaceState and workspace CLI. |
| 2026-06-25 | `make test` after workspace state | pass | 36 unittest tests passed, including schema, service, and CLI coverage for multi-chapter workspace state. |
| 2026-06-25 | `make validate` after workspace state | pass | Current repository docs, JSON assets, workspaces directory, and 14 Skills validate. |
| 2026-06-25 | `make lint` after feedback trend analysis | pass | Python sources and tests compile after adding trend and retention helpers. |
| 2026-06-25 | `make test` after feedback trend analysis | pass | 37 unittest tests passed, including service and CLI feedback trend coverage. |
| 2026-06-25 | `make validate` after feedback trend analysis | pass | Current repository docs, JSON assets, workspaces directory, and 14 Skills validate. |
| 2026-06-25 | `make lint` after risk reduction | pass | Python sources and tests compile after adding semantic validators, Skill drift check, and pipeline workspace updates. |
| 2026-06-25 | `make test` after risk reduction | pass | 40 unittest tests passed, including semantic validation, Skill drift detection, and pipeline workspace output. |
| 2026-06-25 | `make validate` after risk reduction | pass | Current repository docs, JSON assets, workspaces directory, and 14 Skills validate. |
| 2026-06-25 | `make lint` after external resource intake | pass | Python sources and tests compile after adding Claude Code resource intake docs and command template. |
| 2026-06-25 | `make test` after external resource intake | pass | 41 unittest tests passed, including read-only external resource command boundary coverage. |
| 2026-06-25 | `make validate` after external resource intake | pass | Current repository docs, JSON assets, workspaces directory, and 14 Skills validate with external intake doc required. |
