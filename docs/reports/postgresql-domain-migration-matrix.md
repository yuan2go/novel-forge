# PostgreSQL Domain Migration Matrix

| Capability | Before | Authority definition / handler | Inputs → output | Completion / projection | Current state | Commit |
|---|---|---|---|---|---|---|
| Context | simplified chapter rule + LocalStorage service | `chapter.context.build` / context domain | ChapterPlan AssetVersion → ContextBundle | eligible active bundle; ChapterProductionRun projection | integration_proven in chapter slice | `8fdb326` |
| ReviewIssue | provider-shaped report only | `chapter.review.evaluate` / review domain | Draft + ContextBundle → ReviewReport with issue records | qualified report; Review Center projection | integration_proven | `cf5ef1e` |
| Revision | phrase-dependent fixture rule | `chapter.revision.apply` / revision domain | Draft + Review + Context → DraftVersion | all eligible blockers resolved | integration_proven | `cf5ef1e` |
| Canon | fixed sentence extraction | `chapter.canon.update` / canon domain | Revision + Context → CanonPatch | conflict-free qualified patch | integration_proven | `cf5ef1e` |
| Quality | fixed sentence score | `chapter.quality.evaluate` / quality domain | Revision + Review + Canon + Context → QualityReport | all evidence checks pass | integration_proven | `cf5ef1e` |
| Publish Gate | absent from chapter slice | `chapter.publishing.prepare_release` / publishing domain | five evidence versions → PublishGateReport | latest review/canon/source/originality/quality evidence | integration_proven | `cf5ef1e` |
| Export | quality-only render | `chapter.export.render` | Revision + PublishGate → ReleasePackage/Blob | verified Blob + ExternalEffect receipt | integration_proven | `cf5ef1e` |
| Content intelligence | catalog candidates | 22 definitions under `content_authority` | versioned payloads → domain assets/reports | eligible active AssetVersion required | handler_bound, disabled | `5aa2a89` |

`ChapterProductionRun`, Review display models, and dashboards are projections; chapter Completion reads Operation/Attempt/Saga/AssetVersion/qualification/audit/outbox/blob/effect evidence, not those projections. Legacy Chapter Production Bus remains a compatibility orchestrator and is not yet fully converted into an Authority-only adapter.
