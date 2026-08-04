# Track C BookDesign, StoryDesign, Content And Planning Convergence Review

- Branch: `feat/v7-content-intelligence-and-longform-proof`
- Implementation evidence SHA: `8d0c49973ad3f58ca325e3d39941fd89cb5d5f5e`
- Date: 2026-08-04
- Decision record: ADR 0003 (Accepted)
- C1 status: **not started**

## Modules reviewed

The review followed code, registrations, migrations, applications, repositories,
and PostgreSQL tests for:

- `book_design_authority` and `book_authority`;
- `story_design_authority` and `content_authority`;
- `hierarchical_planning`, `story_plan_binding`, and
  `active_story_plan_version`;
- `planning_horizon` and `story_production_cursor`;
- PlanChange and production-execution composition paths.

## Convergence decision

1. **BookDesign is the only whole-book design root.** Theme, Reader Promise,
   Ending, World Constraints, Character Core, Core Conflict, and Commercial
   Positioning are activated through the typed BookDesign Authority. Other
   modules may produce proposals or evidence, not a second active root.
2. **StoryDesign owns candidate generation and qualification.** It retains
   GeneratorDefinition, structural/semantic validation, repair, qualification,
   and approval lifecycle. Its output becomes a candidate for Planning; it does
   not duplicate BookDesign activation.
3. **Content Authority is a deterministic handler runtime.** It executes typed
   handlers through the shared Command Kernel and does not own another workflow
   engine or scheduler authority.
4. **Existing hierarchical planning remains Plan Authority.** No third
   BookPlan/Planning system is introduced.
5. **Arc is an orthogonal narrative track.** Containment is
   `Book → Volume → ChapterGroup → Chapter`; Arc contributions/dependencies can
   cross groups, chapters, and volumes.
6. **Cross-domain reads use query/projection/snapshot contracts.** Planning,
   Context, Quality, and Book Coordinator may not import another domain's
   concrete repository to read or mutate its private state.

## Formal Plan commit correction

`planning.binding.activate` now has an independent Transaction Command with:

- Principal and Project/Book scope;
- idempotency digest and expected active AssetVersion;
- replacement decision evidence;
- its own Operation and completion result;
- binding, active projection, audit and outbox in one transaction;
- causation pointing to the StoryDesign/PlanChange Operation.

`created_by_operation_id` and `activated_by_operation_id` therefore represent
the Planning state transition, not the older StoryDesign operation. Replay
returns the same Planning Operation; a fault after outbox insertion rolls back
all Planning and Operation rows; successful commands have zero Attempts.

Migration 0052 rejects cross-Project, cross-Book, Workspace/Book and
AssetVersion scope contamination at the database boundary. Planning integration
tests include cross-book rejection and the selected orthogonal Arc semantics.

## Remaining convergence constraint

Older StoryDesign and PlanChange lifecycle facades still call worker-classified
Content operations synchronously. They are not declared as new C1 production
HTTP entries and must not be exposed that way. Before C1 promotion they must
either be admitted for a real worker claim or be explicitly reclassified as
pure Transaction Commands. This does not justify a new Planning or StoryDesign
subsystem.

## C1 Gate

```text
transaction_command_atomicity_proven=true
inflight_command_recovery_semantics_proven=true
execution_classification_consistent=true  # declared formal production entries
architecture_fitness_scope_hardened=true
asset_scope_database_constraints_proven=true

real_provider_auth_proven=false
provider_request_receipt_proven=false
provider_usage_proven=false
provider_cost_proven=false
provider_timeout_query_cancel_behavior_recorded=false
unknown_reconciliation_proven=false
provider_restart_recovery_proven=false

book_design_planning_convergence_adr_accepted=true
```

Overall C1 Gate: **false**. The exact blocker is the unexecuted real-provider
D0-A through D0-F evidence set. The legacy StoryDesign/PlanChange facade
constraint must also be resolved before promoting those paths as C1 production
entries.

## Evidence classification

```text
architecture_defined=true
implementation_present=true
unit_verified=true
postgres_integration_verified=true
local_deployment_verified=VALIDATION_PENDING
external_execution_proven=false
longform_proven=false
production_verified=false
```

The next permitted action is to execute and persist D0 real-provider scenarios
after credentials are supplied. `Track C1 — Active BookDesign → Active
BookPlan` is not yet authorized.
