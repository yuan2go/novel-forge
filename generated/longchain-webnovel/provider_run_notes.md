# Long-chain Provider Run Notes

- Updated at: 2026-07-01
- Export: `generated/longchain-webnovel`
- Target: 400 chapters x 5000 Chinese characters, about 2,000,000 characters.
- Current generated scope: chapters 001-099.
- Provider path: `CODEX_HOME=~/.codex-claude codex` through `ClaudeCodeAdapter` and `GuardedModelAdapter`.
- CLI used for successful continuation: `/Users/yuan/.local/share/fnm/node-versions/v22.22.2/installation/bin/codex` (`codex-cli 0.142.3`).
- Model selection: explicit `codex5.4` was tested first, but the account rejected it as unsupported. The successful chapter generation used the Codex CLI default model from the same `CODEX_HOME`.
- Runtime evidence: agent run, model call log, cost ledger, draft version, review report, continuity/context acceptance assets, foreshadow evidence spans, and long-chain acceptance report were rebuilt by `scripts/run_long_chain_webnovel.py`.
- Source boundary: generated chapters use abstract story mechanics and multidisciplinary knowledge only. They must not copy protected reference expression, named characters, scene sequence, setting combinations, or jokes.

## Current Pressure Result

- Observed: 99 chapters, 680,005 characters, average 6,868.74 characters.
- Completion against 400 chapters: 24.75%.
- Pressure acceptance: warning / continue_with_watch.
- Watch item: cost drift remains above the warning threshold. `ledger_origin` briefly hit a false overdue condition at chapter 47 because the previous lifecycle check did not read chapter payoff evidence; it now resolves through evidence spans from chapters 35, 36, 40, 42, and 47.
