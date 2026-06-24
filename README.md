# Novel Forge V5

Novel Forge V5 is a file-based, testable AI novel production system rebuilt from the V4 documentation and audit assets. It focuses on industrialized long-form fiction production instead of one-off chapter generation.

Core pipeline:

```text
source material -> cleaned text -> decomposition -> knowledge/material assets -> topic -> world -> characters -> outline -> chapter plan -> draft -> review -> revision -> feedback insight
```

## Principles

- Extract structure, rhythm, hooks, conflict mechanics, emotional curves, and commercial logic from reference works.
- Do not copy original expression, character combinations, settings, or plot sequences from copyrighted works.
- Keep raw sources, decomposition reports, generated assets, and final drafts in separate directories.
- Use deterministic mock adapters for tests; real model adapters are pluggable and deferred.

## Quick Start

```bash
make test
make validate
make demo
./novel-forge --help
```

## Core Commands

```bash
./novel-forge init
./novel-forge ingest examples/sample_inputs/sample_novel.txt
./novel-forge clean --input data/raw/<file>.json
./novel-forge decompose --input data/cleaned/<file>.json
./novel-forge extract-knowledge --input data/decompositions/<file>.json
./novel-forge build-materials
./novel-forge generate-topic
./novel-forge generate-world
./novel-forge generate-characters
./novel-forge generate-outline
./novel-forge generate-chapter-plan
./novel-forge draft
./novel-forge review --input data/drafts/<file>.json
./novel-forge revise --input data/reviews/<file>.json
./novel-forge import-feedback examples/sample_inputs/sample_feedback.csv
./novel-forge analyze-feedback
./novel-forge run-pipeline --sample
./novel-forge status
./novel-forge validate
```

## Current Implementation Scope

V5 Phase 1 uses Python standard library, dataclass schemas, local JSON storage, a deterministic mock model adapter, and `unittest` tests. This keeps the project runnable without installing external dependencies. Pytest/Pydantic can be introduced later by ADR once dependency installation is allowed.
