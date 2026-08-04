# Domain-Native Migration Matrix

The registry is closed at 59 types. The 18 rows below are the only
`DOMAIN_NATIVE` core in this release. IDs are runtime facts and therefore appear
in PostgreSQL/CI evidence, not in this checked-in matrix.

| Source type | Domain adapter | Server validator | Projection authority | Alias identity |
|---|---|---|---|---|
| `project_workspace_state` | `ProjectWorkspaceMigrationAdapter` | `project_authority.domain_validator.v1` | Project Authority | canonical |
| `book` | `BookDesignMigrationAdapter` | `book_design_authority.domain_validator.v1` | Book Authority | `book_record` |
| `book_record` | `BookDesignMigrationAdapter` | `book_design_authority.domain_validator.v1` | Book Authority | `book` |
| `book_design` | `BookDesignMigrationAdapter` | `book_design_authority.domain_validator.v1` | BookDesign Authority | `book_design_candidate` |
| `book_design_candidate` | `BookDesignMigrationAdapter` | `book_design_authority.domain_validator.v1` | BookDesign Authority | `book_design` |
| `story_design` | `StoryDesignMigrationAdapter` | `StoryDesignValidatorSuite@1.0.0` | Story Design Authority | `story_design_candidate` |
| `story_design_candidate` | `StoryDesignMigrationAdapter` | `StoryDesignValidatorSuite@1.0.0` | Story Design Authority | `story_design` |
| `book_plan` | `HierarchicalPlanningMigrationAdapter` | `hierarchical_planning.domain_validator.v1` | PlanChange Authority | `outline_version` |
| `outline_version` | `HierarchicalPlanningMigrationAdapter` | `hierarchical_planning.domain_validator.v1` | PlanChange Authority | `book_plan` |
| `volume_plan` | `HierarchicalPlanningMigrationAdapter` | `hierarchical_planning.domain_validator.v1` | PlanChange Authority | canonical |
| `arc_plan` | `HierarchicalPlanningMigrationAdapter` | `hierarchical_planning.domain_validator.v1` | PlanChange Authority | canonical |
| `chapter_group_plan` | `HierarchicalPlanningMigrationAdapter` | `hierarchical_planning.domain_validator.v1` | PlanChange Authority | canonical |
| `chapter_plan` | `HierarchicalPlanningMigrationAdapter` | `hierarchical_planning.domain_validator.v1` | PlanChange Authority | `chapter_plan_version` |
| `chapter_plan_version` | `HierarchicalPlanningMigrationAdapter` | `hierarchical_planning.domain_validator.v1` | PlanChange Authority | `chapter_plan` |
| `source_document` | `SourceDocumentMigrationAdapter` | `source_authority.domain_validator.v1` | Source Authority | canonical |
| `knowledge_card_candidate` | `MkaosMigrationAdapter` | `mkaos_authority.domain_validator.v1` | MKAOS Authority | `knowledge_card` |
| `knowledge_card` | `MkaosMigrationAdapter` | `mkaos_authority.domain_validator.v1` | MKAOS Authority | `knowledge_card_candidate` |
| `knowledge_pack` | `MkaosMigrationAdapter` | `mkaos_authority.domain_validator.v1` | MKAOS Pack Authority | canonical |

## Proof contract per source type

Each core type is covered by scanner/import/reference/validation/decision/
activation/projection/reconciliation flows. Shared adversarial suites additionally
prove replay and crash resume, same-hash duplicate idempotency, different-hash and
expected-version conflict, cross-project rejection, explicit rejection, stale
validation, stale decision, and dependency invalidation. A Domain pass requires
zero pending items and zero validation, reconciliation or required-reference
failure.

Alias groups converge on one business identity. The unique business identity and
content hash policy makes same-content replay idempotent and different-content
aliases conflict. Two aliases for the same business key in one snapshot cannot
create duplicate projections and fail closed when their content conflicts.

## Special fail-closed boundaries

- Story Design produces versioned receipts for schema, structural, semantic,
  generator-contract and planning-scope checks. The migration adapter cannot
  assert success.
- SourceDocument activation requires an object-store Blob receipt and exact
  hash, size, object key and rights state.
- MKAOS candidates require execution evidence resolving to SourceChunk
  AssetVersions, independent approval, activated card versions and explicit pack
  selections. Fixture lineage remains marked fixture and non-production.
- The other 41 registry entries remain `ARCHIVAL_NATIVE`; no domain activation
  claim is made for them.
