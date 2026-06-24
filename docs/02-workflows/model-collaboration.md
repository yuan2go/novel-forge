# Model Collaboration

| Model | Role | Adapter Status |
|---|---|---|
| Claude Code | chief editor, workflow controller, audit owner | external/manual |
| Codex | engineering editor and implementation reviewer | external/manual |
| ChatGPT | advanced review and multidisciplinary synthesis | future adapter |
| DeepSeek | long-form draft generation | future adapter |
| MockModel | deterministic tests and demo output | implemented |
| LocalRuleEngine | rule-based validation | implemented |

Business workflows call adapter methods instead of provider-specific APIs: `generate`, `analyze`, `review`, `revise`, `batch`, and `health_check`.
