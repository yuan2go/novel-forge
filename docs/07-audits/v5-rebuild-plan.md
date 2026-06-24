# V5 Rebuild Plan

## Adopted From V4

- File-project discipline.
- Copyright boundary rules.
- Multi-model role separation.
- Main production pipeline from import to feedback.
- Need for schemas, tests, progress logs, and acceptance reports.

## Rebuilt In V5

- Directory structure.
- CLI command system.
- Schema layer.
- Storage layer.
- Mock model adapter.
- End-to-end sample pipeline.

## Architecture Reason

A small executable CLI core gives the project a stable operational spine before adding databases, vector search, web UI, or real LLM integrations.
