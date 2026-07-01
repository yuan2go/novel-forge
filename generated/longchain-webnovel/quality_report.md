# Long-chain Web Novel Quality Report

- Project: `real-longchain-webnovel`
- Target: 400 chapters x 5000 chars = 2000000 chars
- Observed: 99 chapters, 680005 chars, avg 6868.74
- Completion: 24.75%
- Warning count: 21
- Recommendation: continue
- Pressure acceptance: warning / continue_with_watch
- Acceptance report: `data/runs/long-chain-acceptance-report-long-chain-acceptance-400-chapters-194f0fc9.json`

## Pressure Coverage

- cost drift via model_call_log usage and cost_ledger
- quality drift via heuristic review score trend
- foreshadow lifecycle via series_bible.long_hooks
- feedback backflow via pressure feedback_backflow_plan

## Pressure Metrics

- Cost drift: warning; model calls 205, provider calls 106, tokens 2122430, token drift ratio 2.3698
- Quality drift: passed; trend stable, score delta 0.0, char drift ratio 0.873
- Foreshadow lifecycle: passed; due 0, overdue 0
- Feedback backflow: passed; plans 1, proposals 2

## Latest Chapter Scores

- Chapter 96: 100 (no warnings)
- Chapter 97: 95.75 (chapter ending punctuation is weak)
- Chapter 98: 100 (no warnings)
- Chapter 99: 100 (no warnings)
