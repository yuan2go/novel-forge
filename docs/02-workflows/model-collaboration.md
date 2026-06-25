# Model Collaboration

| Model | Role | Adapter Status |
|---|---|---|
| Claude Code | chief editor, workflow controller, audit owner | manual runtime contract skeleton |
| Codex | engineering editor and implementation reviewer | manual runtime contract skeleton |
| ChatGPT | advanced review and multidisciplinary synthesis | OpenAI-compatible JSON chat provider |
| DeepSeek | long-form draft generation | OpenAI-compatible JSON chat provider |
| MockModel | deterministic tests and demo output | implemented |
| LocalRuleEngine | rule-based validation | implemented |

Business workflows call adapter methods instead of provider-specific APIs: `generate`, `analyze`, `review`, `revise`, `batch`, and `health_check`.

Skills define reusable capability workflows that Agents should follow before or while using model adapters. Skills do not replace adapters; they define input requirements, process, output shape, quality bar, and forbidden behavior.

## Provider Boundary

Provider adapters live in `src/novel_forge/model_adapters/providers.py`.

They expose the same adapter contract and safe `health_check()` metadata. ChatGPT and DeepSeek are real OpenAI-compatible JSON chat adapters, but they only call external APIs when explicitly selected through environment variables and configured with API keys. Missing secrets fail closed with `AdapterNotConfiguredError`. Tests must not call real external APIs or require secrets.

Claude Code is the exception only in the narrow sense that it can create manual handoff packets through `ClaudeCodeAdapter.create_handoff_packet()`. A handoff packet is not an automated model call. It tells the current Claude Code operator which project files to read, which schema-backed asset to produce, and which validation command to run.

Use this mode when the task needs current Claude Code judgment but must remain auditable:

```text
business workflow -> ClaudeCodeAdapter.create_handoff_packet()
  -> Claude Code operator reads files and writes asset
  -> CLI/storage validation checks output
```

Do not call the current Claude Code session from business code as if it were a stable API.

## Claude Code + Codex Analysis Handoffs

Two high-judgment analysis workflows are routed through Claude Code handoffs instead of direct provider APIs:

- `claude-deconstruct`: reads a cleaned web-novel source by path and asks Claude Code to use Codex with `skills/hot-novel-deconstruction` plus `skills/anti-copy-abstraction`; expected output is a `DecompositionReport` under `data/decompositions/`.
- `claude-knowledge`: reads a source/cleaned professional knowledge asset by path and asks Claude Code to use Codex with `skills/multidisciplinary-knowledge`; expected output is a `KnowledgeCard` under `data/knowledge/`.

Both commands write `ClaudeCodeHandoff` assets under `data/runs/`. The handoff records source asset identity, source path, required skill files, expected output type, acceptance checks, and `make validate` as the validation command. It intentionally does not embed source text, so reference works and domain materials stay behind the existing storage boundary.

Provider implementation changes require:

- ADR for dependency and provider choice.
- Secret policy for required environment variables.
- Mocked unit tests and no-network CI behavior.
- Explicit workflow routing so production calls do not silently replace `MockModel`.
