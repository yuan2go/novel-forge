# Long-chain Web Novel Quality Report

- Project: `real-longchain-webnovel`
- Target: 400 chapters x 5000 chars = 2000000 chars
- Observed: 63 chapters, 428963 chars, avg 6808.94
- Completion: 15.75%
- Warning count: 11
- Recommendation: continue
- Pressure acceptance: warning / continue_with_watch
- Acceptance report: `data/runs/long-chain-acceptance-report-long-chain-acceptance-400-chapters-faed998d.json`

## Pressure Coverage

- cost drift via model_call_log usage and cost_ledger
- quality drift via heuristic review score trend
- foreshadow lifecycle via series_bible.long_hooks
- feedback backflow via pressure feedback_backflow_plan

## Pressure Metrics

- Cost drift: warning; model calls 133, provider calls 70, tokens 1348117, token drift ratio 2.4263
- Quality drift: passed; trend improving, score delta 1.7, char drift ratio 0.9478
- Foreshadow lifecycle: passed; due 0, overdue 0
- Feedback backflow: passed; plans 1, proposals 2

## Latest Chapter Scores

- Chapter 60: 100 (no warnings)
- Chapter 61: 100 (no warnings)
- Chapter 62: 100 (no warnings)
- Chapter 63: 100 (no warnings)
