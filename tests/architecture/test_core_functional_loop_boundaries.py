from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "src" / "novel_forge" / "modules"
MIGRATION = (
    ROOT
    / "src"
    / "novel_forge"
    / "storage"
    / "migrations"
    / "versions"
    / "v20260806_0073_core_functional_loops.py"
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_planning_generators_share_capability_pack_pep_candidate_runtime() -> (
    None
):
    domain = _read("src/novel_forge/modules/story_planning_runtime/domain.py")
    binder = _read("src/novel_forge/modules/story_planning_runtime/binder.py")
    application = _read("src/novel_forge/modules/story_planning_runtime/application.py")
    for generator in (
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    ):
        assert generator in domain
    assert "CapabilityPackAttemptSnapshot" in binder
    assert "PlanningCapabilityBinding" in binder
    assert "AgentWorkOrder" not in binder
    assert "agent_collaboration" not in binder
    assert "DomainExecutionCommand" in binder
    assert "production_execution_gateway_backed" in binder
    assert "external_effect_backed" in binder
    assert "story_planning.candidate" in application
    assert "activate_candidate" in application


def test_planning_candidate_and_commit_authority_boundaries_are_explicit() -> None:
    binder = _read("src/novel_forge/modules/story_planning_runtime/binder.py")
    assert "Planning Capability can only submit a Candidate" in binder
    assert '"STORY_DESIGN_AUTHORITY"' in binder
    assert '"HIERARCHICAL_PLANNING_AUTHORITY"' in binder
    assert '"PLAN_CHANGE_AUTHORITY"' in binder
    for authority in (
        "BOOK_DESIGN_AUTHORITY",
        "STORY_DESIGN_AUTHORITY",
        "HIERARCHICAL_PLANNING_AUTHORITY",
        "CHAPTER_AUTHORITY",
        "READER_JUDGE_AUTHORITY",
        "BOOK_FOLLOWUP_AUTHORITY",
        "PLAN_CHANGE_AUTHORITY",
    ):
        assert authority in _read(
            "src/novel_forge/modules/capability_packs/validator.py"
        )


def test_book_supervisor_uses_authorities_and_owns_no_execution_runtime() -> None:
    supervisor = _read("src/novel_forge/modules/book_authority/supervisor.py")
    assert "PostgresChapterGroupAuthority" in supervisor
    assert "StoryPlanningGenerationApplication" in supervisor
    assert "PostgresBookAuthorityScheduler" in supervisor
    assert "PostgresBookProductionQuery" in supervisor
    assert "advance_supervisor_checkpoint" in supervisor
    for forbidden in (
        "AuthorityUnitOfWork",
        "execute_transaction_command",
        "ProviderAdapter",
        "plan_external_effect",
        "create_attempt",
        "acquire_lease",
        "fencing_token=",
    ):
        assert forbidden not in supervisor


def test_api_and_worker_share_the_canonical_book_production_composition() -> None:
    dependencies = _read("src/novel_forge/api/authority_dependencies.py")
    api = _read("src/novel_forge/api/authority_app.py")
    router = _read("src/novel_forge/api/routers/book_authority.py")
    worker = _read("src/novel_forge/workers/book_authority.py")
    query = _read("src/novel_forge/modules/book_authority/queries.py")
    composition = _read("src/novel_forge/modules/book_authority/composition.py")
    real_provider_proof = _read("scripts/run_short_longform_runtime_proof.py")

    assert "def build_book_production_composition(" in dependencies
    assert "BookProductionComposition(" in dependencies
    assert "build_book_production_composition(" in api
    assert "build_book_production_composition(" in worker
    assert "return ctx.services.book_production" in router
    assert "getattr(" not in router
    assert "def approve_replan(" in composition
    assert "self.replan.approve(" in composition
    assert "RESOLVED_AUTHORITY_INPUT" in query
    assert "build_book_production_composition(" in real_provider_proof
    assert "PostgresBookProductionSupervisor(" not in real_provider_proof


def test_replan_has_no_implicit_approval_path_and_worker_stops_pending() -> None:
    coordinator = _read("src/novel_forge/modules/book_replan/coordinator.py")
    supervisor = _read("src/novel_forge/modules/book_authority/supervisor.py")
    worker = _read("src/novel_forge/workers/book_authority.py")

    command_block = coordinator.split("class CoordinateBookReplanCommand:", 1)[1]
    command_block = command_block.split("class BookReplanCoordinator:", 1)[0]
    assert "auto_approve_low_risk" not in command_block
    assert "WAIT_REPLAN_APPROVAL" in supervisor
    assert "if before == BookProductionState.REPLAN_APPROVAL_PENDING.value" in supervisor
    assert "self.replan.approve" not in worker


def test_book_run_and_replan_bind_immutable_input_snapshots() -> None:
    production = _read("src/novel_forge/modules/book_authority/production.py")
    resolver = _read("src/novel_forge/modules/book_authority/input_resolver.py")
    replan = _read("src/novel_forge/modules/book_replan/coordinator.py")
    assert "RESOLVED_AUTHORITY_INPUT" in production
    assert "BOOK_PRODUCTION_LEGACY_INPUT_FORBIDDEN" in production
    assert "authority_book_production_input_binding" in production
    assert "BOOK_PRODUCTION_PLAN_STALE" in resolver
    assert "bind_replanned_input_snapshot" in replan
    assert "book.production_input.replan_bind" in production
    assert "execute_transaction_command" in replan


def test_book_durable_mutations_use_transaction_commands_not_attempt_runtime() -> None:
    production = _read("src/novel_forge/modules/book_authority/production.py")
    assert 'BOOK_MUTATION_DEFINITION = "book.authority.mutate"' in production
    assert "def _execute_mutation(" in production
    assert "execute_transaction_command(" in production
    assert '"cas_required": True' in production
    assert '"business_event_required": True' in production
    assert '"attempt_runtime_forbidden": True' in production
    for event_type in (
        "book.production.started",
        "book.chapter_request.reserved",
        "book.chapter_request.linked",
        "book.chapter.accepted",
        "book.chapter.status_reconciled",
        "book.production.paused",
        "book.production.resumed",
        "book.production.aborted",
        "book.supervisor.checkpoint.advanced",
        "book.followup.linked",
    ):
        assert event_type in production
    assert "book.checkpoint.advanced" in production
    followup_definitions = _read(
        "src/novel_forge/modules/book_followup_authority/definitions.py"
    )
    assert "book_followup.{name}.materialized" in followup_definitions
    assert "book.followup.completed" not in production


def test_chapter_group_arc_and_ending_business_evidence_is_acceptance_bound() -> None:
    production = _read("src/novel_forge/modules/book_authority/production.py")
    checkpoint = _read("src/novel_forge/modules/book_production/checkpoints.py")
    assert "parent_group_version_id" in production
    assert "authority_book_chapter_acceptance" in checkpoint
    assert "authority_arc_actual_state" in checkpoint
    assert "authority_arc_checkpoint_v2" in checkpoint
    assert "authority_arc_contribution" not in checkpoint
    assert "actual_arc_contributions) or" not in checkpoint
    assert "chapter_acceptance_operation_id" in checkpoint
    assert "authority_book_volume_checkpoint" in checkpoint
    assert "authority_book_arc_checkpoint" not in checkpoint
    assert "authority_ending_reachability_report" in checkpoint
    assert "execute_transaction_command" in checkpoint


def test_replan_is_future_only_and_activates_through_plan_change_authority() -> None:
    coordinator = _read("src/novel_forge/modules/book_replan/coordinator.py")
    plan_change = _read("src/novel_forge/modules/plan_change_authority/application.py")
    assert "BOOK_REPLAN_EXECUTED_PLAN_FORBIDDEN" in coordinator
    assert "future_only" in coordinator
    assert "self.plan_change.propose" in coordinator
    assert "self.plan_change.activate" in coordinator
    assert "record_impacts" in plan_change
    assert "replacement_approved=True" in plan_change


def test_reader_judge_is_fail_closed_candidate_only_and_bounded() -> None:
    authority = _read("src/novel_forge/modules/reader_judge_authority/application.py")
    handler = _read("src/novel_forge/modules/book_followup_authority/handlers.py")
    assert "NO_ACTIVE_QUALIFIED_JUDGE" in authority
    assert "READER_JUDGE_FIXTURE_QUALIFICATION_FORBIDDEN" in _read(
        "src/novel_forge/modules/reader_calibration/domain.py"
    )
    assert '"publish_blocking": False' in authority
    assert '"direct_plan_mutation_forbidden": True' in authority
    assert "maximum_adjustment_chapters" in handler
    assert '"candidate_only": True' in handler
    assert '"ending_mutation_allowed": False' in handler
    assert "body_mutation_allowed" in handler


def test_new_migration_adds_facts_without_duplicate_kernel_runtime() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    for table in (
        "authority_story_planning_generation",
        "authority_book_production_input_snapshot",
        "authority_arc_contribution",
        "authority_book_replan",
        "authority_reader_judge_version",
        "authority_reader_judge_active",
    ):
        assert f"CREATE TABLE {table}" in migration
    for duplicate in (
        "authority_story_planning_attempt",
        "authority_book_supervisor_attempt",
        "authority_reader_judge_attempt",
        "authority_book_replan_lease",
        "authority_reader_judge_fence",
    ):
        assert duplicate not in migration
    assert "novel_forge_reject_immutable_mutation" in migration
    assert "authority_book_acceptance_contribution_identity_unique" in migration
    assert "project_id, judge_version_id, qualification_decision_id" in migration
    assert "novel_forge_story_planning_generation_identity_guard" in migration


def test_required_modules_are_registered_and_local_json_is_not_authority() -> None:
    manifest = _read("architecture/manifests/module-manifest.yaml")
    for module in (
        "production-execution",
        "story-design-authority",
        "hierarchical-planning",
        "chapter-group-authority",
        "plan-change-authority",
        "reader-calibration",
        "reader-judge-authority",
        "book-followup-authority",
    ):
        assert f'"name": "{module}"' in manifest
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for package in (
            "story_planning_runtime",
            "book_production",
            "book_replan",
            "reader_judge_authority",
        )
        for path in (MODULES / package).glob("*.py")
    )
    assert "localStorage" not in combined
    assert "json.dump(" not in combined
