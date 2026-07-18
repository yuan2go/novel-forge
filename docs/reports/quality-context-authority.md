# Quality Context Authority

The five Quality groups receive independent minimal views rather than one expanding
bundle:

| Group | Governed inputs |
|---|---|
| Structural | revision, word/paragraph/dialogue/readability/mobile/format policy |
| Commercial | ChapterPlan, promise/reward, protagonist/antagonist, suspense/emotion, hook/bridge |
| Source/originality | Manifest and source-isolation evidence, allowed use, copyright/style/originality policy |
| Long-form | nine state kinds, volume arc, recap/arc progress, current plan and Canon proposal |
| Platform | compiled concrete length/format/safety/AI/opening/rhythm/metadata rules |

`QualityPolicyCompiler` and `PlatformPolicyCompiler` produce deterministic, hashable,
lineage-bound policy views from frozen profile AssetVersions. Source views never
contain raw protected expression. Compression preserves identity and required state
facts. Responses remain `PROVIDER_UNCALIBRATED` unless separate calibration evidence
qualifies them.

Evidence: `chapter_quality_authority/context_views.py`, `policy_compiler.py`, and
the quality context/unit plus Chapter Saga PostgreSQL tests.
