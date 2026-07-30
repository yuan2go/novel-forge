# Reader Calibration Progress

Status:

```text
human_preference_flow_implemented=true
human_preference_anchored=false
behavior_pipeline_implemented=true
behavior_calibrated=false
causal_experiment_validated=false
real_reader_data_proven=false
production_verified=false
```

## Implemented contracts

Human preference now has PostgreSQL contracts for task, blinded pair, B/A
reversal, multi-reviewer decision, golden set and agreement report. Decisions
support A, B, Tie, Reject Both, evidence spans, confidence, reviewer group and
annotation reason. Finalization records position bias, reversal consistency,
pairwise agreement, reader/editor disagreement and sample coverage.

Reader behavior now requires:

```text
Pseudonymized ReaderSession
→ ReaderExposure denominator
→ ReaderOutcomeEvent
```

Outcome events cannot be stored without an eligible exposure. Project,
Book, platform and reader-segment scope are copied from the exposure instead of
trusted from the event caller.

Calibration Profile resolution uses platform, genre, subgenre, chapter type,
reader segment, judge profile and model version, choosing the most specific
valid profile with sufficient samples. Runs store sample count, Brier score,
log loss and calibration error. Schema space exists for confidence intervals,
segment residuals and validity/drift evidence.

Severe model, prompt, platform, genre, segment, behavior or calibration
residual drift forces the Judge to `SHADOW`. Canon, safety, originality,
compliance and blocking quality gates always precede Reader Outcome evidence.

## Evidence boundary

Fixture annotations and behavior rows never become real calibration proof.
`evidence_level=FIXTURE` is database-constrained to `judge_mode=SHADOW`.
Even a caller requesting `BEHAVIOR_CALIBRATED` cannot produce a valid profile
unless the PostgreSQL exposure/outcome denominator reaches the minimum sample
size. Insufficient or drifted profiles cannot expose behavior probabilities;
scores remain `RAW_SCORE`.

Evidence:

- `tests.unit.test_reader_calibration`
- `tests.integration.test_reader_calibration_postgres`
- blind A/B and B/A reversal;
- agreement and position-bias calculation;
- missing-exposure rejection;
- project/segment-scoped outcome event;
- insufficient-data calibration and severe-drift downgrade.
