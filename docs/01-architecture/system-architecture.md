# System Architecture

## Architecture

V5 is a CLI-first Python system using local filesystem storage and schema-backed JSON assets.

```text
CLI -> workflows -> schemas -> local storage
              -> model adapters
              -> evaluation rules
```

## Why This Architecture

V4 documented a large industrial writing system but implementation was scattered and mostly skeletal. V5 uses a smaller executable core so each module can be tested before adding external systems.

## Extension Points

- Model adapters for Claude, Codex, ChatGPT, DeepSeek, MockModel, and local rules.
- Storage adapter can later support database/vector stores.
- Workflow runner can later support queues and retries.

## Model Adapter Boundary

`MockModelAdapter` and `LocalRuleEngine` are executable locally. Claude Code, Codex, ChatGPT, and DeepSeek provider adapters are contract skeletons only: `health_check()` is safe, but generation operations intentionally fail closed until real provider code, dependency policy, and secret handling are approved.
