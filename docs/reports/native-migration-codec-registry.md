# Native Migration Codec Registry

Evidence code SHA: `53b10b896bb934298d1ca11571aa01f24f00a812`

The source of truth is `DEFAULT_CODEC_REGISTRY` in
`src/novel_forge/modules/legacy_migration/codecs.py`. The registry is closed:
unknown types are quarantined rather than wrapped indefinitely in a generic
`legacy_import_candidate`.

Every codec declares source type, native target Asset type, schema version,
stable business identity, scope/reference resolution, conversion, validation,
qualification and activation policy, rebuildability, quarantine rules and
reconciliation rules. All 58 currently registered codecs are non-rebuildable
business records; rebuildable inventory rows are handled by explicit rebuild
policy rather than native import.

| Source type | Native target | Schema version |
|---|---|---|
| `agent_checkpoint` | `agent_checkpoint` | `agent_checkpoint.authority.v1` |
| `agent_contract` | `agent_contract` | `agent_contract.authority.v1` |
| `agent_run` | `agent_run_snapshot` | `agent_run_snapshot.authority.v1` |
| `analysis_report` | `analysis_report` | `analysis_report.authority.v1` |
| `arc_plan` | `arc_plan` | `arc_plan.authority.v1` |
| `book`, `book_record` | `book_record` | `book_record.authority.v1` |
| `book_design`, `book_design_candidate` | `book_design` | `book_design.authority.v1` |
| `book_plan`, `outline_version` | `book_plan` | `book_plan.authority.v1` |
| `canon_database` | `canon_snapshot` | `canon_snapshot.authority.v1` |
| `canon_graph_snapshot` | `canon_graph_snapshot` | `canon_graph_snapshot.authority.v1` |
| `chapter_plan`, `chapter_plan_version` | `chapter_plan` | `chapter_plan.authority.v1` |
| `character_card` | `character_card` | `character_card.authority.v1` |
| `cleaned_text` | `cleaned_text` | `cleaned_text.authority.v1` |
| `context_build_plan` | `context_build_plan` | `context_build_plan.authority.v1` |
| `context_bundle` | `context_bundle` | `context_bundle.authority.v1` |
| `continuity_bible` | `continuity_bible` | `continuity_bible.authority.v1` |
| `draft`, `draft_chapter` | `draft_chapter` | `draft_chapter.authority.v1` |
| `draft_diff_report` | `draft_diff_report` | `draft_diff_report.authority.v1` |
| `editor_patch` | `editor_patch` | `editor_patch.authority.v1` |
| `fact_ledger` | `fact_ledger` | `fact_ledger.authority.v1` |
| `faction_card` | `faction_card` | `faction_card.authority.v1` |
| `feedback_import_batch` | `feedback_import_batch` | `feedback_import_batch.authority.v1` |
| `feedback_insight` | `feedback_insight` | `feedback_insight.authority.v1` |
| `knowledge_card` | `knowledge_card` | `knowledge_card.authority.v1` |
| `knowledge_card_candidate` | `knowledge_card_candidate` | `knowledge_card_candidate.authority.v1` |
| `knowledge_pack` | `knowledge_pack` | `knowledge_pack.authority.v1` |
| `location_card` | `location_card` | `location_card.authority.v1` |
| `material_card` | `material_card` | `material_card.authority.v1` |
| `project_workspace_state` | `project_record` | `project_record.authority.v1` |
| `publication_record` | `publication_record` | `publication_record.authority.v1` |
| `publish_gate_report` | `publish_gate_report` | `publish_gate_report.authority.v1` |
| `publishing_log` | `publishing_log` | `publishing_log.authority.v1` |
| `publishing_plan` | `publishing_plan` | `publishing_plan.authority.v1` |
| `reader_outcome` | `reader_outcome` | `reader_outcome.authority.v1` |
| `reader_sentiment_report` | `reader_sentiment_report` | `reader_sentiment_report.authority.v1` |
| `release_package` | `release_package` | `release_package.authority.v1` |
| `review_issue` | `review_issue` | `review_issue.authority.v1` |
| `review_report` | `review_report` | `review_report.authority.v1` |
| `revised_draft` | `revised_draft` | `revised_draft.authority.v1` |
| `revision_plan` | `revision_plan` | `revision_plan.authority.v1` |
| `revision_task` | `revision_task` | `revision_task.authority.v1` |
| `rule_card` | `rule_card` | `rule_card.authority.v1` |
| `source_chunk` | `source_chunk` | `source_chunk.authority.v1` |
| `source_document` | `source_document` | `source_document.authority.v1` |
| `story_design`, `story_design_candidate` | `story_design` | `story_design.authority.v1` |
| `story_state_snapshot` | `story_state_snapshot` | `story_state_snapshot.authority.v1` |
| `template_card` | `template_card` | `template_card.authority.v1` |
| `topic_seed` | `topic_seed` | `topic_seed.authority.v1` |
| `volume_plan` | `volume_plan` | `volume_plan.authority.v1` |
| `workflow_definition` | `workflow_definition` | `workflow_definition.authority.v1` |
| `workflow_run` | `workflow_run_snapshot` | `workflow_run_snapshot.authority.v1` |
| `world_bible` | `world_bible` | `world_bible.authority.v1` |

## Safety policy

- Original snapshots are immutable and hash-addressed.
- Missing and cross-project references quarantine the record.
- Same identity with a different content hash is a conflict, not an overwrite.
- Unclear source rights prevent automatic activation.
- Large blobs require object key, hash and size evidence; they are not inlined.
- Replay reuses the stable operation and business identity and reconciles the
  existing immutable AssetVersion.
