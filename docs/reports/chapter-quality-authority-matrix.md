# Chapter Quality Authority Matrix

Date: 2026-07-18. Quality evidence targets the accepted Revision AssetVersion.

| Dimension | Evidence source in this round | Calibration | Blocking policy |
|---|---|---|---|
| readability | deterministic/fixture evaluator | FIXTURE_UNCALIBRATED | profile-controlled |
| golden opening | deterministic/fixture evaluator | FIXTURE_UNCALIBRATED | profile-controlled |
| chapter economy | deterministic/fixture evaluator | FIXTURE_UNCALIBRATED | profile-controlled |
| reader promise | Authority context/canon evidence | FIXTURE_UNCALIBRATED | yes |
| reward/pleasure | Authority context/canon evidence | FIXTURE_UNCALIBRATED | profile-controlled |
| toxic point | deterministic/fixture evaluator | FIXTURE_UNCALIBRATED | yes |
| protagonist charm | deterministic/fixture evaluator | FIXTURE_UNCALIBRATED | profile-controlled |
| antagonist pressure | Canon semantic evidence | FIXTURE_UNCALIBRATED | profile-controlled |
| mobile reading | deterministic structure evidence | DETERMINISTIC | profile-controlled |
| style drift | StylePolicy/Revision evidence | FIXTURE_UNCALIBRATED | yes |
| originality | source/originality evidence | FIXTURE_UNCALIBRATED | non-waivable |
| source leakage | governed Context/source evidence | DETERMINISTIC | non-waivable |
| anti-AI | evidence or valid approval | PROVIDER_UNCALIBRATED when supplied | yes |
| platform rules | target platform evidence/approval | FIXTURE_UNCALIBRATED | yes |
| long-form stability | Canon/long-form evidence | FIXTURE_UNCALIBRATED | yes |

The Quality Operation materializes one `ChapterQualityAggregate` plus 15 qualified,
versioned `chapter_quality_evidence` outputs. Completion requires every evidence
output. Publish Gate rejects stale/wrong-target/missing/blocking evidence; fixture
evidence never sets `production_verified=true`. Originality and source leakage are
not waivable. A later slice may convert the 15 evaluators into parallel child
Operations and a fan-in Saga; that topology is not claimed here.
