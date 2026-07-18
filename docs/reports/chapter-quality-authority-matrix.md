# Chapter Quality Authority Matrix

Date: 2026-07-18. Quality evidence targets the accepted Revision AssetVersion.

| Authority group | Covered dimensions | Decision source | Fail-closed rule |
|---|---|---|---|
| Structural | readability, mobile reading, chapter economy, prose/scene/paragraph integrity, balance, repetition, summary-like prose | deterministic evidence where observable; calibrated evidence otherwise | blocking failure or insufficient required evidence |
| Commercial | opening, promise, reward, protagonist charm, antagonist pressure, toxic point, hook, suspense, emotion, serialization | ChapterPlan/ledger/Canon/Review plus provider or human calibration slot | weak keyword evidence never passes |
| Source/Originality | leakage, originality, Anti-AI, style drift, copyright boundary | Context lineage/source governance plus calibrated originality/style evidence | leakage, originality and Anti-AI fail closed |
| Long-form | Canon, motivation, relationships, timeline, foreshadow, promise debt, world rules, power, patterns, arc | Canon Snapshots and long-form reports | critical conflict or missing required coverage blocks |
| Platform | length, format, sensitive-content, AI policy, opening/rhythm, metadata | versioned QualityProfile and PlatformProfile | missing/incorrect profile or rule evidence blocks |

The five groups execute as independent Operations and Attempts after Canon. The
`chapter.quality.evaluate` fan-in waits for every group and materializes 41 qualified,
versioned evidence outputs plus `ChapterQualityAggregate`.

Statuses are `PASSED`, `PASSED_WITH_WARNINGS`, `FAILED`, `UNCALIBRATED`,
`INSUFFICIENT_EVIDENCE`, `REQUIRES_PROVIDER_JUDGE`,
`REQUIRES_HUMAN_REVIEW`, and `WAIVED_BY_APPROVAL`. Production-calibrated evidence
must target the current Revision AssetVersion; stale or wrong-target evidence is
ignored. Protocol fixtures require `fixture_protocol_only=true` and never set
`production_verified=true`.

When configured, each group uses one governed model ExternalEffect and requires the
Provider response to cover the exact frozen dimension contract. Provider evidence is
target-bound but remains `PROVIDER_UNCALIBRATED`; fixture evidence cannot promote it
to production verification.

Publish Gate rejects blocking/missing/stale/wrong-target evidence and emits an
internal release class only. External publishing remains disabled. Detailed evidence
is in `quality-authority-real-gate.md`.
