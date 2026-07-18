# Quality Authority Real Gate

Date: 2026-07-18. “Real” means honest domain decisions, not a paid Provider run.

## Authority topology

After Canon, the scheduler admits five independent Operations together:

1. `chapter.quality.structural.evaluate`
2. `chapter.quality.commercial.evaluate`
3. `chapter.quality.source_originality.evaluate`
4. `chapter.quality.longform.evaluate`
5. `chapter.quality.platform.evaluate`

They have independent Attempts/retries. `chapter.quality.evaluate` is the fan-in and
cannot execute until all five succeed. It materializes 41 target-bound evidence
dimensions plus `ChapterQualityAggregate`.

Deterministic checks decide only observable properties such as readability,
paragraph structure, duplicate sentences, Context source isolation, copyright
boundary, and Canon conflicts. Commercial semantics, originality, Anti-AI, style,
long-form semantics, and platform conformance require calibrated, current-Revision
evidence. Missing or weak evidence returns `INSUFFICIENT_EVIDENCE`,
`REQUIRES_PROVIDER_JUDGE`, or `REQUIRES_HUMAN_REVIEW`; it never becomes PASSED from
a keyword or fixture flag.

For a configured production route, each of the five groups invokes exactly one
ExternalEffect-backed Provider judge (not one call per dimension). The response must
cover the frozen dimension set exactly, with typed status, confidence, and evidence
locations; missing, duplicate, or extra dimensions fail the model response and cannot
materialize eligible Quality evidence. These Provider results remain
`PROVIDER_UNCALIBRATED` until calibrated against a golden set or human decisions.

Evidence statuses are `PASSED`, `PASSED_WITH_WARNINGS`, `FAILED`, `UNCALIBRATED`,
`INSUFFICIENT_EVIDENCE`, `REQUIRES_PROVIDER_JUDGE`,
`REQUIRES_HUMAN_REVIEW`, and `WAIVED_BY_APPROVAL`. Reports bind Revision,
QualityProfile, PlatformProfile, calibration/source, and verification flags.
Wrong-target production evidence is rejected. A narrowly marked
`fixture_protocol_only` input exists solely to prove the fan-in/release protocol and
always keeps `production_verified=false`.

Publish Gate fails closed for source leakage, originality, Anti-AI, critical Canon,
blocking Re-review, platform rules, target mismatch, and missing checklist. The
current release class is `INTERNAL_REVIEW_RELEASE`; external publish remains false.

Evidence: commits `6100ef2`, `e4f1571`, `7773189`, `14b2f1c`; unit quality/domain/model-contract tests; PostgreSQL quality fan-out,
fan-in, retry/release slice tests. `real_provider_proven=false` and
`production_verified=false`.
