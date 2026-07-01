# Long-chain Web Novel Quality Report

- Project: `real-longchain-webnovel`
- Target: 400 chapters x 5000 chars = 2000000 chars
- Observed: 75 chapters, 516256 chars, avg 6883.41
- Completion: 18.75%
- Warning count: 17
- Recommendation: continue
- Pressure acceptance: warning / continue_with_watch
- Acceptance report: `data/runs/long-chain-acceptance-report-long-chain-acceptance-400-chapters-f9bbb8ca.json`

## Pressure Coverage

- cost drift via model_call_log usage and cost_ledger
- quality drift via heuristic review score trend
- foreshadow lifecycle via series_bible.long_hooks
- feedback backflow via pressure feedback_backflow_plan

## Pressure Metrics

- Cost drift: warning; model calls 157, provider calls 82, tokens 1610048, token drift ratio 2.4791
- Quality drift: passed; trend stable, score delta -0.85, char drift ratio 1.0123
- Foreshadow lifecycle: passed; due 0, overdue 0
- Feedback backflow: passed; plans 1, proposals 2

## Latest Chapter Scores

- Chapter 72: 95.75 (chapter ending punctuation is weak)
- Chapter 73: 100 (no warnings)
- Chapter 74: 95.75 (chapter ending punctuation is weak)
- Chapter 75: 100 (no warnings)
