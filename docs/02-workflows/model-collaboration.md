# Model Collaboration

| Model | Role | Adapter Status |
|---|---|---|
| Claude Code | chief editor, workflow controller, audit owner | manual runtime contract skeleton |
| Codex | engineering editor and implementation reviewer | manual runtime contract skeleton |
| ChatGPT | advanced review and multidisciplinary synthesis | external provider contract skeleton |
| DeepSeek | long-form draft generation | external provider contract skeleton |
| MockModel | deterministic tests and demo output | implemented |
| LocalRuleEngine | rule-based validation | implemented |

Business workflows call adapter methods instead of provider-specific APIs: `generate`, `analyze`, `review`, `revise`, `batch`, and `health_check`.

Skills define reusable capability workflows that Agents should follow before or while using model adapters. Skills do not replace adapters; they define input requirements, process, output shape, quality bar, and forbidden behavior.

## Provider Contract Boundary

Provider skeletons live in `src/novel_forge/model_adapters/providers.py`.

They expose the same adapter contract and safe `health_check()` metadata, but generation/review operations fail closed with `AdapterNotConfiguredError` until a real implementation is added. Tests must not call real external APIs or require secrets.

Real provider implementation requires:

- ADR for dependency and provider choice.
- Secret policy for required environment variables.
- Mocked unit tests and no-network CI behavior.
- Explicit workflow routing so production calls do not silently replace `MockModel`.
