# Long-chain Web Novel Quality Report

- Project: `real-longchain-webnovel`
- Target: 100 chapters x 5000 chars = 500000 chars
- Observed: 30 chapters, 203289 chars, avg 6776.3
- Completion: 30.00%
- Warning count: 7
- Recommendation: continue
- Pressure acceptance: warning / continue_with_watch
- Acceptance report: `data/runs/long-chain-acceptance-report-long-chain-acceptance-100-chapters-e2160dd4.json`

## Pressure Coverage

- cost drift via model_call_log usage and cost_ledger
- quality drift via heuristic review score trend
- foreshadow lifecycle via series_bible.long_hooks
- feedback backflow via pressure feedback_backflow_plan

## Pressure Metrics

- Cost drift: warning; model calls 67, provider calls 37, tokens 641421, token drift ratio 2.4442
- Quality drift: passed; trend improving, score delta 1.7, char drift ratio 0.9718
- Foreshadow lifecycle: passed; due 0, overdue 0
- Feedback backflow: passed; plans 1, proposals 2

## Latest Chapter Scores

- Chapter 6: 100 (no warnings)
- Chapter 7: 100 (no warnings)
- Chapter 8: 100 (no warnings)
- Chapter 9: 100 (no warnings)
- Chapter 10: 95.75 (chapter ending punctuation is weak)
- Chapter 11: 100 (no warnings)
- Chapter 12: 100 (no warnings)
- Chapter 13: 100 (no warnings)
- Chapter 14: 95.75 (chapter ending punctuation is weak)
- Chapter 15: 95.75 (chapter ending punctuation is weak)
- Chapter 16: 100 (no warnings)
- Chapter 17: 100 (no warnings)
- Chapter 18: 100 (no warnings)
- Chapter 19: 100 (no warnings)
- Chapter 20: 100 (no warnings)
- Chapter 21: 95.75 (chapter ending punctuation is weak)
- Chapter 22: 95.75 (chapter ending punctuation is weak)
- Chapter 23: 100 (no warnings)
- Chapter 24: 100 (no warnings)
- Chapter 25: 100 (no warnings)
- Chapter 26: 100 (no warnings)
- Chapter 27: 100 (no warnings)
- Chapter 28: 100 (no warnings)
- Chapter 29: 100 (no warnings)
- Chapter 30: 100 (no warnings)
