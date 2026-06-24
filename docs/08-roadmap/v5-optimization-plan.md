# V5 Optimization Plan

## Current Test Readiness

V5 can run local tests and validation today:

```bash
make lint
make test
make validate
make sync-skills-dry-run
```

The current pipeline is a local mock pipeline. It is suitable for engineering verification, schema validation, workflow validation, and demo runs. It is not yet a production-grade long-form novel factory because real model adapters, strict validation, task recovery, logs, and retrieval are still limited.

## P0: Stability Before Scale

| ID | Task | Goal | Acceptance |
|---|---|---|---|
| V5-OPT-P0-001 | Type-level asset validation | Validate required content/top-level fields by asset type, not only common fields. | `make validate` fails for malformed assets and passes for current sample assets. |
| V5-OPT-P0-002 | Module service split | Move pipeline step logic from centralized `pipeline.py` into module services without changing CLI behavior. | Existing CLI/tests pass; services have direct unit tests. |
| V5-OPT-P0-003 | Task and run status records | Record pending/running/completed/failed status, input/output paths, and error messages. | Pipeline writes status assets and tests cover failure status. |
| V5-OPT-P0-004 | Run logs and failure recovery | Add run logs and resumable or at least diagnosable failure handling. | Failed step produces clear run log and recovery instruction. |
| V5-OPT-P0-005 | Deterministic demo mode | Prevent repeated `make demo` from polluting sample data with duplicate random assets. | Demo can run in clean/fixed-output mode. |

## P1: Production Efficiency

| ID | Task | Goal | Acceptance |
|---|---|---|---|
| V5-OPT-P1-001 | Real model adapter contracts | Add provider adapter skeletons while keeping tests on MockModel. | Adapter health checks and mocked tests pass. |
| V5-OPT-P1-002 | Richer material ingestion | Support batch text/markdown inputs, source metadata, and better import errors. | CLI can ingest a directory fixture. |
| V5-OPT-P1-003 | Cleaning improvements | Remove boilerplate, OCR noise, repeated watermarks, and detect chapters. | Cleaning tests cover noisy fixture text. |
| V5-OPT-P1-004 | Material tags and search | Make `material-curation` actionable through tag metadata and local search. | CLI or workflow can list/filter assets by tags. |
| V5-OPT-P1-005 | Topic and training workflows | Add CLI workflow steps for `topic-development` and `training-exercise`. | Commands produce schema-backed assets. |

## P2: Quality And Scale

| ID | Task | Goal | Acceptance |
|---|---|---|---|
| V5-OPT-P2-001 | Local retrieval and vector index | Add local text/tag index, relevance ranking, and hash-vector search before external vector database. | Search and vector-search tests pass without external services. |
| V5-OPT-P2-002 | Multi-model review comparison | Compare review outputs from multiple adapters. | Mock comparison report generated. |
| V5-OPT-P2-003 | Long project workspace | Support multi-chapter project state and memory. | Sample project can track multiple chapters. |
| V5-OPT-P2-004 | Feedback trend analysis | Track feedback signals across chapters and time. | Feedback insight includes trend fields. |

## Current Priority

All P0 optimization items, `V5-OPT-P1-001` through `V5-OPT-P1-005`, and `V5-OPT-P2-001` through `V5-OPT-P2-004` are complete. The current optimization pool is complete; next work should define a new P3 or production-integration task pool.
