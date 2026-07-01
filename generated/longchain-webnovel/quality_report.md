# Long-chain Web Novel Quality Report

- Project: `real-longchain-webnovel`
- Target: 400 chapters x 5000 chars = 2000000 chars
- Observed: 87 chapters, 602660 chars, avg 6927.13
- Completion: 21.75%
- Warning count: 18
- Recommendation: continue
- Pressure acceptance: warning / continue_with_watch
- Acceptance report: `data/runs/long-chain-acceptance-report-long-chain-acceptance-400-chapters-73168c60.json`

## Pressure Coverage

- cost drift via model_call_log usage and cost_ledger
- quality drift via heuristic review score trend
- foreshadow lifecycle via series_bible.long_hooks
- feedback backflow via pressure feedback_backflow_plan

## Pressure Metrics

- Cost drift: warning; model calls 181, provider calls 94, tokens 1870920, token drift ratio 2.441
- Quality drift: passed; trend improving, score delta 1.7, char drift ratio 0.9633
- Foreshadow lifecycle: passed; due 0, overdue 0
- Feedback backflow: passed; plans 1, proposals 2

## Latest Chapter Scores

- Chapter 84: 100 (no warnings)
- Chapter 85: 100 (no warnings)
- Chapter 86: 100 (no warnings)
- Chapter 87: 100 (no warnings)
