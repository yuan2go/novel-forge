# V1 Chapter Sequence Slow Acceptance

Generated at: `2026-07-07T16:44:54+00:00`
Workspace root: `/Users/yuan/projects/novel-forge/.local/v1-chapter-sequence-acceptance-run3`
Model provider: `mock`
Requested chapters: `10`
Completed chapters: `10`
Status: `succeeded`
Duration seconds: `1460.716`
Acceptance report asset: `data/runs/long-chain-acceptance-v1-sequence-project-v1-slow-acceptance-project-5f0b8da2-10-2026-07-07t16-44-54-00-00-45cccb48.json`

## Runtime Summary

```json
{
  "started_at": "2026-07-07T16:20:34+00:00",
  "finished_at": "2026-07-07T16:44:54+00:00",
  "duration_seconds": 1460.001,
  "average_chapter_seconds": 146.0,
  "asset_counts_before": {
    "raw": 0,
    "cleaned": 0,
    "decompositions": 0,
    "analysis": 0,
    "knowledge": 0,
    "materials": 0,
    "platforms": 0,
    "genres": 0,
    "topics": 0,
    "worlds": 0,
    "characters": 0,
    "continuity": 0,
    "styles": 0,
    "quality_standards": 0,
    "templates": 0,
    "contexts": 0,
    "outlines": 1,
    "chapter_plans": 0,
    "drafts": 0,
    "reviews": 0,
    "publishing": 0,
    "feedback": 0,
    "loops": 0,
    "training": 0,
    "image_prompts": 0,
    "workspaces": 1,
    "runs": 0
  },
  "asset_counts_after": {
    "raw": 0,
    "cleaned": 0,
    "decompositions": 0,
    "analysis": 0,
    "knowledge": 0,
    "materials": 0,
    "platforms": 68,
    "genres": 1,
    "topics": 1,
    "worlds": 0,
    "characters": 0,
    "continuity": 232,
    "styles": 21,
    "quality_standards": 19,
    "templates": 0,
    "contexts": 225,
    "outlines": 11,
    "chapter_plans": 42,
    "drafts": 120,
    "reviews": 316,
    "publishing": 10,
    "feedback": 0,
    "loops": 80,
    "training": 0,
    "image_prompts": 0,
    "workspaces": 1,
    "runs": 6470
  },
  "asset_count_delta": {
    "analysis": 0,
    "chapter_plans": 42,
    "characters": 0,
    "cleaned": 0,
    "contexts": 225,
    "continuity": 232,
    "decompositions": 0,
    "drafts": 120,
    "feedback": 0,
    "genres": 1,
    "image_prompts": 0,
    "knowledge": 0,
    "loops": 80,
    "materials": 0,
    "outlines": 10,
    "platforms": 68,
    "publishing": 10,
    "quality_standards": 19,
    "raw": 0,
    "reviews": 316,
    "runs": 6470,
    "styles": 21,
    "templates": 0,
    "topics": 1,
    "training": 0,
    "workspaces": 0,
    "worlds": 0
  },
  "total_asset_delta": 7615
}
```

## Chapter Coverage

| Chapter | Status | Coverage | Duration seconds | Run | Missing outputs |
|---:|---|---|---:|---|---|
| 1 | succeeded | passed | 22.571 | `data/runs/chapter-production-run-chapter-1-production-bus-22140a5b.json` |  |
| 2 | succeeded | passed | 41.27 | `data/runs/chapter-production-run-chapter-2-production-bus-80a14301.json` |  |
| 3 | succeeded | passed | 64.21 | `data/runs/chapter-production-run-chapter-3-production-bus-4bf0d995.json` |  |
| 4 | succeeded | passed | 89.316 | `data/runs/chapter-production-run-chapter-4-production-bus-fc74ca3d.json` |  |
| 5 | succeeded | passed | 116.961 | `data/runs/chapter-production-run-chapter-5-production-bus-61a94f0c.json` |  |
| 6 | succeeded | passed | 150.978 | `data/runs/chapter-production-run-chapter-6-production-bus-87bcfdcd.json` |  |
| 7 | succeeded | passed | 184.579 | `data/runs/chapter-production-run-chapter-7-production-bus-e9e498a5.json` |  |
| 8 | succeeded | passed | 221.253 | `data/runs/chapter-production-run-chapter-8-production-bus-ffaf1525.json` |  |
| 9 | succeeded | passed | 261.886 | `data/runs/chapter-production-run-chapter-9-production-bus-5f71e267.json` |  |
| 10 | succeeded | passed | 306.933 | `data/runs/chapter-production-run-chapter-10-production-bus-8649dc59.json` |  |

## Output Counts

```json
{
  "chapter_plan_path": 10,
  "context_bundle_path": 10,
  "draft_v0_path": 10,
  "review_path": 10,
  "revision_plan_path": 10,
  "final_draft_path": 10,
  "chapter_state_path": 10,
  "fact_ledger_path": 10,
  "character_state_ledger_path": 10,
  "foreshadowing_graph_path": 10,
  "reward_ledger_path": 10,
  "review_score_system_report_path": 10,
  "longform_recap_report_path": 10,
  "export_package_path": 10,
  "export_markdown_path": 10,
  "next_chapter_plan_path": 10
}
```

## Failures

```json
[]
```

## Progress Events

```json
[
  {
    "event": "chapter_started",
    "chapter": 1,
    "index": 1,
    "total": 10,
    "started_at": "2026-07-07T16:20:34+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 1,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-1-production-bus-22140a5b.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-1-plan-8ac80743.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-1-plan-8ac80743-5268d4f7.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-1-draft-v0-236877e4.json",
      "review_path": "data/reviews/review-report-review-for-chapter-1-draft-v0-ae262abf.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-1-draft-v0-b006aa4d.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-1-draft-v0-final-78cf9049.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-1-state-package-5fd59051.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-1-fact-ledger-e52f5506.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-1-character-state-ledger-6525f073.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-1-foreshadowing-graph-e7873a20.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-1-reward-ledger-f64c437b.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-1-draft-v0-final-4093d677.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-1-1-2026-07-07t16-20-52-00-00-8ea36bff.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-1-draft-chapter-chapter-1-draft-v0-final-78cf9049-734921dc.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-1.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-2-plan-96fb4bc3.json"
    },
    "started_at": "2026-07-07T16:20:34+00:00",
    "finished_at": "2026-07-07T16:20:56+00:00",
    "duration_seconds": 22.571,
    "index": 1,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 2,
    "index": 2,
    "total": 10,
    "started_at": "2026-07-07T16:20:56+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 2,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-2-production-bus-80a14301.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-2-plan-96fb4bc3.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-2-plan-96fb4bc3-2ae9218b.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-2-draft-v0-f2bae555.json",
      "review_path": "data/reviews/review-report-review-for-chapter-2-draft-v0-f384d5fa.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-2-draft-v0-6b34d8a8.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-2-draft-v0-final-345e171f.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-2-state-package-202064f4.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-2-fact-ledger-f0315222.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-2-character-state-ledger-69306402.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-2-foreshadowing-graph-a58be942.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-2-reward-ledger-d3416ce7.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-2-draft-v0-final-5ea9c44a.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-2-2-2026-07-07t16-21-31-00-00-fd464721.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-2-draft-chapter-chapter-2-draft-v0-final-345e171f-b6307a52.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-2.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-3-plan-8a3255b4.json"
    },
    "started_at": "2026-07-07T16:20:56+00:00",
    "finished_at": "2026-07-07T16:21:37+00:00",
    "duration_seconds": 41.27,
    "index": 2,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 3,
    "index": 3,
    "total": 10,
    "started_at": "2026-07-07T16:21:37+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 3,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-3-production-bus-4bf0d995.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-3-plan-8a3255b4.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-3-plan-8a3255b4-76e4e985.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-3-draft-v0-55d31e1f.json",
      "review_path": "data/reviews/review-report-review-for-chapter-3-draft-v0-9b16ecc1.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-3-draft-v0-1832a610.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-3-draft-v0-final-50226b44.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-3-state-package-2db052bb.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-3-fact-ledger-6b9dab84.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-3-character-state-ledger-e796d177.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-3-foreshadowing-graph-5e781a83.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-3-reward-ledger-be790bcb.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-3-draft-v0-final-aa11386c.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-3-3-2026-07-07t16-22-31-00-00-985421f6.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-3-draft-chapter-chapter-3-draft-v0-final-50226b44-bcddd1c4.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-3.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-4-plan-3e6526af.json"
    },
    "started_at": "2026-07-07T16:21:37+00:00",
    "finished_at": "2026-07-07T16:22:42+00:00",
    "duration_seconds": 64.21,
    "index": 3,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 4,
    "index": 4,
    "total": 10,
    "started_at": "2026-07-07T16:22:42+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 4,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-4-production-bus-fc74ca3d.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-4-plan-3e6526af.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-4-plan-3e6526af-0c27526f.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-4-draft-v0-bb9b1d1d.json",
      "review_path": "data/reviews/review-report-review-for-chapter-4-draft-v0-e2e49e56.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-4-draft-v0-ff3d30d1.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-4-draft-v0-final-6a3b54aa.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-4-state-package-04519ba5.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-4-fact-ledger-375ec987.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-4-character-state-ledger-ee684300.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-4-foreshadowing-graph-aed28756.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-4-reward-ledger-ddaf741e.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-4-draft-v0-final-f87e09f1.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-4-4-2026-07-07t16-23-57-00-00-57e858d0.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-4-draft-chapter-chapter-4-draft-v0-final-6a3b54aa-0194865d.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-4.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-5-plan-7c1853ff.json"
    },
    "started_at": "2026-07-07T16:22:42+00:00",
    "finished_at": "2026-07-07T16:24:11+00:00",
    "duration_seconds": 89.316,
    "index": 4,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 5,
    "index": 5,
    "total": 10,
    "started_at": "2026-07-07T16:24:11+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 5,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-5-production-bus-61a94f0c.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-5-plan-7c1853ff.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-5-plan-7c1853ff-b3e5739e.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-5-draft-v0-b7102ef0.json",
      "review_path": "data/reviews/review-report-review-for-chapter-5-draft-v0-1efc1e94.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-5-draft-v0-7475bebb.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-5-draft-v0-final-3bf9427a.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-5-state-package-f2d86bc9.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-5-fact-ledger-874bbf33.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-5-character-state-ledger-b33e74c5.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-5-foreshadowing-graph-15dd41df.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-5-reward-ledger-f7b26a20.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-5-draft-v0-final-e4301e43.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-5-5-2026-07-07t16-25-50-00-00-e3c129a5.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-5-draft-chapter-chapter-5-draft-v0-final-3bf9427a-fb379f87.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-5.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-6-plan-d3964438.json"
    },
    "started_at": "2026-07-07T16:24:11+00:00",
    "finished_at": "2026-07-07T16:26:08+00:00",
    "duration_seconds": 116.961,
    "index": 5,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 6,
    "index": 6,
    "total": 10,
    "started_at": "2026-07-07T16:26:08+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 6,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-6-production-bus-87bcfdcd.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-6-plan-d3964438.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-6-plan-d3964438-8c2d76a0.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-6-draft-v0-b88a3983.json",
      "review_path": "data/reviews/review-report-review-for-chapter-6-draft-v0-6a22c5d5.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-6-draft-v0-cdbd654c.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-6-draft-v0-final-0f65d316.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-6-state-package-f9e4b0ce.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-6-fact-ledger-898f0aea.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-6-character-state-ledger-2cf88f07.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-6-foreshadowing-graph-c79595a2.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-6-reward-ledger-4bb34526.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-6-draft-v0-final-c2aa1ae6.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-6-6-2026-07-07t16-28-16-00-00-8dc703b7.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-6-draft-chapter-chapter-6-draft-v0-final-0f65d316-b7a67835.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-6.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-7-plan-eb1f4236.json"
    },
    "started_at": "2026-07-07T16:26:08+00:00",
    "finished_at": "2026-07-07T16:28:39+00:00",
    "duration_seconds": 150.978,
    "index": 6,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 7,
    "index": 7,
    "total": 10,
    "started_at": "2026-07-07T16:28:39+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 7,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-7-production-bus-e9e498a5.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-7-plan-eb1f4236.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-7-plan-eb1f4236-32936061.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-7-draft-v0-4837712a.json",
      "review_path": "data/reviews/review-report-review-for-chapter-7-draft-v0-16bc9f3d.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-7-draft-v0-9d358878.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-7-draft-v0-final-315a9912.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-7-state-package-74ba9aee.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-7-fact-ledger-66a3955d.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-7-character-state-ledger-0872a8da.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-7-foreshadowing-graph-3061abcf.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-7-reward-ledger-1425c009.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-7-draft-v0-final-182a4fd7.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-6-7-2026-07-07t16-31-16-00-00-d4ba755a.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-7-draft-chapter-chapter-7-draft-v0-final-315a9912-7db37e60.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-7.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-8-plan-1cb7b5bf.json"
    },
    "started_at": "2026-07-07T16:28:39+00:00",
    "finished_at": "2026-07-07T16:31:43+00:00",
    "duration_seconds": 184.579,
    "index": 7,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 8,
    "index": 8,
    "total": 10,
    "started_at": "2026-07-07T16:31:43+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 8,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-8-production-bus-ffaf1525.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-8-plan-1cb7b5bf.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-8-plan-1cb7b5bf-2f6b0fee.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-8-draft-v0-27505f05.json",
      "review_path": "data/reviews/review-report-review-for-chapter-8-draft-v0-8bc84cf0.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-8-draft-v0-21c6293e.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-8-draft-v0-final-c2d30381.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-8-state-package-74e33d71.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-8-fact-ledger-4335dfa9.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-8-character-state-ledger-2b4972ce.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-8-foreshadowing-graph-4048db77.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-8-reward-ledger-d928cd32.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-8-draft-v0-final-39df0c19.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-7-8-2026-07-07t16-34-52-00-00-bdd46fd4.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-8-draft-chapter-chapter-8-draft-v0-final-c2d30381-6025b8e4.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-8.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-9-plan-7f4de849.json"
    },
    "started_at": "2026-07-07T16:31:43+00:00",
    "finished_at": "2026-07-07T16:35:25+00:00",
    "duration_seconds": 221.253,
    "index": 8,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 9,
    "index": 9,
    "total": 10,
    "started_at": "2026-07-07T16:35:25+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 9,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-9-production-bus-5f71e267.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-9-plan-7f4de849.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-9-plan-7f4de849-f495f127.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-9-draft-v0-36cb4612.json",
      "review_path": "data/reviews/review-report-review-for-chapter-9-draft-v0-141e862e.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-9-draft-v0-7497c772.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-9-draft-v0-final-5602bf44.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-9-state-package-5f343ac1.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-9-fact-ledger-8cbb791d.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-9-character-state-ledger-c65f6fe2.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-9-foreshadowing-graph-ad477faf.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-9-reward-ledger-a9b91b1e.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-9-draft-v0-final-bd8d66d0.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-8-9-2026-07-07t16-39-09-00-00-50e6ebe8.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-9-draft-chapter-chapter-9-draft-v0-final-5602bf44-96662ee9.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-9.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-10-plan-3f21794e.json"
    },
    "started_at": "2026-07-07T16:35:25+00:00",
    "finished_at": "2026-07-07T16:39:47+00:00",
    "duration_seconds": 261.886,
    "index": 9,
    "total": 10
  },
  {
    "event": "chapter_started",
    "chapter": 10,
    "index": 10,
    "total": 10,
    "started_at": "2026-07-07T16:39:47+00:00"
  },
  {
    "event": "chapter_completed",
    "chapter": 10,
    "status": "succeeded",
    "run_path": "data/runs/chapter-production-run-chapter-10-production-bus-8649dc59.json",
    "current_step": "next_chapter_plan",
    "coverage": {
      "status": "passed",
      "observed": 16,
      "expected": 16,
      "missing_outputs": []
    },
    "outputs": {
      "chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-10-plan-3f21794e.json",
      "context_bundle_path": "data/contexts/context-bundle-context-bundle-for-chapter-plan-chapter-plan-chapter-10-plan-3f21794e-8d6497f1.json",
      "draft_v0_path": "data/drafts/draft-chapter-chapter-10-draft-v0-d4b2eb76.json",
      "review_path": "data/reviews/review-report-review-for-chapter-10-draft-v0-badaa7c9.json",
      "revision_plan_path": "data/reviews/revision-plan-revision-plan-for-review-for-chapter-10-draft-v0-ee5ab6a4.json",
      "final_draft_path": "data/drafts/draft-chapter-chapter-10-draft-v0-final-e7898635.json",
      "chapter_state_path": "data/continuity/chapter-state-chapter-10-state-package-245d2083.json",
      "fact_ledger_path": "data/continuity/fact-ledger-chapter-10-fact-ledger-1be6ebc6.json",
      "character_state_ledger_path": "data/continuity/character-state-ledger-chapter-10-character-state-ledger-1e28f17e.json",
      "foreshadowing_graph_path": "data/continuity/foreshadowing-graph-chapter-10-foreshadowing-graph-1a3ba45f.json",
      "reward_ledger_path": "data/continuity/reward-ledger-chapter-10-reward-ledger-db983da8.json",
      "review_score_system_report_path": "data/reviews/review-score-system-report-review-score-gate-for-chapter-10-draft-v0-final-ea06162e.json",
      "longform_recap_report_path": "data/continuity/longform-recap-report-project-v1-slow-acceptance-project-5f0b8da2-9-10-2026-07-07t16-44-08-00-00-563961ee.json",
      "export_package_path": "data/publishing/v1-export-package-project-v1-slow-acceptance-project-5f0b8da2-10-draft-chapter-chapter-10-draft-v0-final-e7898635-36e5153b.json",
      "export_markdown_path": "data/exports/v1/project-v1-slow-acceptance-project-5f0b8da2-chapter-10.md",
      "next_chapter_plan_path": "data/chapter_plans/chapter-plan-chapter-11-plan-c527db8e.json"
    },
    "started_at": "2026-07-07T16:39:47+00:00",
    "finished_at": "2026-07-07T16:44:54+00:00",
    "duration_seconds": 306.933,
    "index": 10,
    "total": 10
  },
  {
    "event": "sequence_finished",
    "status": "succeeded",
    "requested_chapter_count": 10,
    "completed_chapters": 10,
    "duration_seconds": 1460.716,
    "acceptance_report_path": "data/runs/long-chain-acceptance-v1-sequence-project-v1-slow-acceptance-project-5f0b8da2-10-2026-07-07t16-44-54-00-00-45cccb48.json"
  }
]
```

## Next Step

Repeat with `--chapter-count 30` after reviewing runtime and artifact growth.
