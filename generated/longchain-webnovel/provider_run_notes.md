# Long-chain Provider Run Notes

- Updated at: 2026-07-01
- Export: `generated/longchain-webnovel`
- Target: 400 chapters x 5000 Chinese characters, about 2,000,000 characters.
- Current generated scope: chapters 001-035.
- Provider path: `CODEX_HOME=~/.codex-claude codex` through `ClaudeCodeAdapter` and `GuardedModelAdapter`.
- CLI used for successful continuation: `/Users/yuan/.local/share/fnm/node-versions/v22.22.2/installation/bin/codex` (`codex-cli 0.142.3`).
- Model selection: explicit `codex5.4` was tested first, but the account rejected it as unsupported. The successful chapter generation used the Codex CLI default model from the same `CODEX_HOME`.
- Runtime evidence: agent run, model call log, cost ledger, draft version, review report, continuity/context acceptance assets, and long-chain acceptance report were rebuilt by `scripts/run_long_chain_webnovel.py`.
- Source boundary: generated chapters use abstract story mechanics and multidisciplinary knowledge only. They must not copy protected reference expression, named characters, scene sequence, setting combinations, or jokes.

## Current Pressure Result

- Observed: 35 chapters, 237,032 characters, average 6,772.34 characters.
- Completion against 400 chapters: 8.75%.
- Pressure acceptance: warning / continue_with_watch.
- Watch item: chapter 33 scored 86.75 by the heuristic quality scorer despite no blocking warning; later batches should watch dialogue density, final hook strength, and sustained payoff pressure.
