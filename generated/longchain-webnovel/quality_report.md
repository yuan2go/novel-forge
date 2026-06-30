# Long-chain Web Novel Quality Report

- Project: `real-longchain-webnovel`
- Target: 400 chapters x 5000 chars = 2000000 chars
- Observed: 47 chapters, 322332 chars, avg 6858.13
- Completion: 11.75%
- Warning count: 9
- Recommendation: continue
- Pressure acceptance: warning / continue_with_watch
- Acceptance report: `data/runs/long-chain-acceptance-report-long-chain-acceptance-400-chapters-985e1454.json`

## Pressure Coverage

- cost drift via model_call_log usage and cost_ledger
- quality drift via heuristic review score trend
- foreshadow lifecycle via series_bible.long_hooks
- feedback backflow via pressure feedback_backflow_plan

## Pressure Metrics

- Cost drift: warning; model calls 101, provider calls 54, tokens 1008268, token drift ratio 2.4704
- Quality drift: passed; trend improving, score delta 1.7, char drift ratio 0.9837
- Foreshadow lifecycle: passed; due 0, overdue 0
- Feedback backflow: passed; plans 1, proposals 2

## Latest Chapter Scores


