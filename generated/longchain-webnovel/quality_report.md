# Long-chain Web Novel Quality Report

- Project: `real-longchain-webnovel`
- Target: 400 chapters x 5000 chars = 2000000 chars
- Observed: 35 chapters, 237032 chars, avg 6772.34
- Completion: 8.75%
- Warning count: 7
- Recommendation: continue
- Pressure acceptance: warning / continue_with_watch
- Acceptance report: `data/runs/long-chain-acceptance-report-long-chain-acceptance-400-chapters-795bf659.json`

## Pressure Coverage

- cost drift via model_call_log usage and cost_ledger
- quality drift via heuristic review score trend
- foreshadow lifecycle via series_bible.long_hooks
- feedback backflow via pressure feedback_backflow_plan

## Pressure Metrics

- Cost drift: warning; model calls 77, provider calls 42, tokens 747996, token drift ratio 2.4427
- Quality drift: passed; trend stable, score delta -0.95, char drift ratio 0.9624
- Foreshadow lifecycle: warning; due 1, overdue 0
- Feedback backflow: passed; plans 1, proposals 2

## Latest Chapter Scores

- Chapter 32: 100 (no warnings)
- Chapter 33: 86.75 (no warnings)
- Chapter 34: 100 (no warnings)
- Chapter 35: 100 (no warnings)
