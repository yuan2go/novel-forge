# Long-chain Web Novel Quality Report

- Project: `real-longchain-webnovel`
- Target: 400 chapters x 5000 chars = 2000000 chars
- Observed: 119 chapters, 815882 chars, avg 6856.15
- Completion: 29.75%
- Warning count: 25
- Recommendation: continue
- Pressure acceptance: warning / continue_with_watch
- Acceptance report: `data/runs/long-chain-acceptance-report-long-chain-acceptance-400-chapters-3dbae35b.json`

## Pressure Coverage

- cost drift via model_call_log usage and cost_ledger
- quality drift via heuristic review score trend
- foreshadow lifecycle via series_bible.long_hooks
- feedback backflow via pressure feedback_backflow_plan

## Pressure Metrics

- Cost drift: warning; model calls 249, provider calls 128, tokens 2589242, token drift ratio 2.3606
- Quality drift: passed; trend stable, score delta 0.0, char drift ratio 0.9298
- Foreshadow lifecycle: passed; due 0, overdue 0
- Feedback backflow: passed; plans 1, proposals 2

## Latest Chapter Scores

- Chapter 119: 100 (no warnings)
