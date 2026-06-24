# CLAUDE.md

This file defines project-level operating rules for Claude Code, Codex, and other coding agents working in Novel Forge V5.

## Project Goal

Novel Forge V5 is an industrialized AI writing system for long-term novel production. It turns source materials, abstracted reference analysis, multidisciplinary knowledge, and reader feedback into reusable story assets and controlled fiction outputs.

## Current Architecture

- Python 3.11+.
- CLI-first workflow.
- Markdown and JSON local assets.
- Dataclass schemas in `src/novel_forge/schemas/`.
- Local filesystem storage in `data/`.
- Mock model adapter for tests.
- No external API calls in tests.

## Agent Responsibilities

- Claude Code: product owner, project editor, workflow controller, audit owner.
- Codex: engineering editor, code implementation, tests, CLI, schema consistency.
- ChatGPT: advanced reviewer, multidisciplinary synthesis, commercial logic review.
- DeepSeek: future long-form draft producer behind a model adapter.
- MockModel: deterministic test adapter only.
- LocalRuleEngine: schema and quality rule checks.

## Required Commands

```bash
make test
make lint
make validate
make demo
```

## Forbidden Actions

- Do not copy expression from popular novels into generated output.
- Do not mix raw text, decompositions, generated drafts, and feedback assets.
- Do not mark untested functionality as complete.
- Do not hard-code external model providers in business logic.
- Do not add external dependencies without an ADR.
- Do not delete user data.

## Acceptance Standard

A feature is complete only when it has a CLI entry, schema-backed input/output, local storage path, tests or executable validation, error handling, documentation, and progress/status visibility.
