# PostgreSQL Domain Migration Matrix

| Capability | Before | Authority definition / handler | Inputs → output | Completion / projection | Current state | Commit |
|---|---|---|---|---|---|---|
| Context | manifest-only bundle + LocalStorage service | `chapter.context.build` / context domain | frozen governed AssetVersions → Manifest + Segments + Stage View | eligible active bundle; digest covers content | integration_proven | `1f7154f` |
| ReviewIssue | provider-shaped report only | `chapter.review.evaluate` / review domain | Draft + ContextBundle → ReviewReport with issue records | qualified report; Review Center projection | integration_proven | `cf5ef1e` |
| Revision/Re-review | model self-certified resolution | `chapter.revision.apply` + `chapter.revision.review` | Draft + initial Review + Revision + Context → independent ReReviewReport | latest passed report and zero blockers | integration_proven | `1f7154f` |
| Canon | optional revision-side assertion | `chapter.canon.extract` + `chapter.canon.update` | Revision + historical Context state → extraction + CanonPatch | typed conflicts + snapshot candidates | integration_proven | `70c2434` |
| Quality | fixed score 100 | `chapter.quality.evaluate` / aggregate domain | Revision + Re-review + Canon + Context evidence → ChapterQualityAggregate | blocking dimensions pass; missing calibration explicit | integration_proven, uncalibrated | `1f7154f` |
| Publish Gate | absent from chapter slice | `chapter.publishing.prepare_release` / publishing domain | five evidence versions → PublishGateReport | latest review/canon/source/originality/quality evidence | integration_proven | `cf5ef1e` |
| Export | quality-only render | `chapter.export.render` | Revision + PublishGate → ReleasePackage/Blob | verified Blob + ExternalEffect receipt | integration_proven | `cf5ef1e` |
| Content intelligence | callable domain functions only | 22 definitions under `content_authority` | exact frozen AssetVersions + typed payload → domain assets/reports | qualification + audit + outbox + Completion | integration_proven | `d442767` |
| ChapterProductionRun | LocalStorage execution authority | `ChapterProductionAuthorityAdapter` | Authority commands/queries → rebuildable projection | projection never satisfies Completion | legacy production blocked; dev compatibility remains | `9895b70` |

`ChapterProductionRun`, Review display models, and dashboards are projections; chapter Completion reads Operation/Attempt/Saga/AssetVersion/qualification/audit/outbox/blob/effect evidence, not those projections. Legacy Chapter Production Bus remains a compatibility orchestrator and is not yet fully converted into an Authority-only adapter.
