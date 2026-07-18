# OperationDefinition Supersession Matrix

| Old definition | Relationship | Replacement | Reason | Removal policy |
|---|---|---|---|---|
| `production.draft.generate` | superseded | `chapter.draft.generate` | Chapter Authority owns frozen-context draft generation | legacy adapter development-only |
| `production.chapter.export` | alias | `chapter.export.render` | historical name for the same Authority render node | retain catalog alias |
| `production.chapter_plan.generate` | candidate | none | materialization does not prove plan generation | keep until Generator Authority exists |
| `production.topic.generate` | candidate | none | validator/topic services do not prove Authority generation | keep |
| `production.outline.generate` | candidate | none | existing outline services are not this Authority generator | keep |

No historical record is deleted. Supersession fields include replacement,
reason, migration status, replacement entrypoints and compatibility horizon.
