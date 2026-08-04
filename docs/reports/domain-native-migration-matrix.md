# Domain-Native Migration Matrix

The source of truth is `DEFAULT_CODEC_REGISTRY`. A codec describes source
classification; only a successful domain adapter, independent decision,
activation command, projection and reconciliation upgrades an item from
`ARCHIVAL_NATIVE` to `DOMAIN_NATIVE`.

## Domain-native core types

| Source types | Adapter | Native proof | Important boundary |
|---|---|---|---|
| `project_workspace_state` | Project Authority path | project, workspace, binding, scope, current version | project shell can be created, but imported business content still requires review |
| `book`, `book_record`, `book_design`, `book_design_candidate` | Book/BookDesign Authority | candidate, decision, active design, unique root, expected version | activation follows migration approval and typed Authority commands |
| `story_design`, `story_design_candidate` | StoryDesign Authority | candidate, decision, active projection, version | candidate generation never self-activates |
| `book_plan`, `outline_version`, `volume_plan`, `arc_plan`, `chapter_group_plan`, `chapter_plan`, `chapter_plan_version` | Hierarchical Planning Authority | story-design dependency, parent and active binding, containment edge, replacement evidence, expected version | Arc is an overlay; containment remains Book to Volume to ChapterGroup to Chapter |
| `source_document` | Source Authority | rights, governance, verified blob receipt, hash/object key, projection | absent or invalid blob evidence quarantines; no active SourceDocument is fabricated |
| `knowledge_card_candidate`, `knowledge_card`, `knowledge_pack` | MKAOS Authority | candidate/approval/knowledge/pack projections and version references | fixture activation is marked fixture-only and is not real-provider proof |

Count: **18 DOMAIN_NATIVE source types**.

## Archival-native types

The remaining **41 source types** are safely stored as immutable Authority
AssetVersions with `IMPORTED`, `PENDING_EVALUATION`, and `NEEDS_REVIEW`. They do
not claim a domain projection:

```text
agent_checkpoint, agent_contract, agent_run, analysis_report,
canon_database, canon_graph_snapshot, character_card, cleaned_text,
context_build_plan, context_bundle, continuity_bible, draft, draft_chapter,
draft_diff_report, editor_patch, fact_ledger, faction_card,
feedback_import_batch, feedback_insight, location_card, material_card,
publication_record, publish_gate_report, publishing_log, publishing_plan,
reader_outcome, reader_sentiment_report, release_package, review_issue,
review_report, revised_draft, revision_plan, revision_task, rule_card,
source_chunk, story_state_snapshot, template_card, topic_seed,
workflow_definition, workflow_run, world_bible
```

`material_card`, `rule_card`, and `template_card` remain archival because the
current MKAOS Authority does not expose corresponding typed projections. This
is a deliberate remaining domain-migration gap, not an alias to `knowledge_card`.

## Fail-closed outcomes

- Unknown registry type: `UNSUPPORTED` and quarantine.
- Missing/cross-project/ambiguous required reference: `QUARANTINED` or
  `CONFLICT`.
- Missing Source blob receipt or unsafe rights/governance: `QUARANTINED`.
- Domain validation without independent approval: remains `NEEDS_REVIEW`.
- Rebuildable generated data: `REBUILDABLE`, never imported as business truth.
