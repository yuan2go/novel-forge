from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
import psycopg

from novel_forge.modules.book_design_authority import BookDesignAuthorityCommand
from novel_forge.modules.book_design_authority.formation import StartStoryFormationCommand, StoryFormationApplication
from novel_forge.modules.book_design_authority.formation_domain import StoryFormationInput
from novel_forge.modules.command_kernel.creative_budget_runtime import configure_creative_budget, get_creative_budget
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority.application import ContentAuthorityApplication, ContentOperationRequest
from novel_forge.modules.content_authority.codecs import CONTENT_CODECS
from novel_forge.modules.project_authority import ProjectAuthorityApplication, ProjectAuthorityCommand, ProjectAuthorityQuery
from scripts.creation_pilot import prepare_pilot_book
from tests.integration.authority_postgres_support import DATABASE_URL, identifier, transaction
from tests.integration import test_creation_pilot_shared_project_postgres as pilot_support
from tests.unit.test_creation_comparison import comparison_identities
from tests.unit.test_production_book_budget_contract import production_book_policy
from tests.unit.test_single_book_budget_contract import single_book_policy


pilot_project = pilot_support.pilot_project


def workspace_command(scope, workspace_id, **changes):
    project_id, primary, principal, _app, _composition, _source = scope
    project = ProjectAuthorityQuery(DATABASE_URL).require_project(project_id)
    return ProjectAuthorityCommand(**{
        "definition_name": "project_workspace.create", "project_id": project_id, "workspace_id": primary,
        "actor_id": principal.principal_id, "idempotency_key": "create:" + workspace_id,
        "trace_id": "trace:" + workspace_id, "correlation_id": project_id,
        "expected_version": project["version"], "expected_current_asset_version_id": project["asset_version_id"],
        "payload": {"workspace_id": workspace_id}, **changes,
    })


def test_secondary_workspace_is_atomic_replayable_and_preserves_primary(pilot_project):
    project, primary, principal, application, _composition, _source = pilot_project
    secondary = identifier("secondary-workspace")
    with transaction() as connection:
        before = connection.execute("SELECT to_jsonb(p) FROM authority_project p WHERE project_id=%s", [project]).fetchone()[0]
        primary_before = connection.execute("SELECT to_jsonb(w) FROM authority_workspace w WHERE workspace_id=%s", [primary]).fetchone()[0]
    command = workspace_command(pilot_project, secondary)
    result = application.execute(command, principal=principal)
    replay = application.execute(command, principal=principal)
    assert replay["operation_id"] == result["operation_id"] and replay["replayed"] is True
    workspace = ProjectAuthorityQuery(DATABASE_URL).require_workspace(project_id=project, workspace_id=secondary)
    assert workspace["status"] == "ACTIVE" and workspace["book_id"] == ""
    assert workspace["asset_version_id"] == result["asset_version_id"]
    with transaction() as connection:
        assert connection.execute("SELECT to_jsonb(p) FROM authority_project p WHERE project_id=%s", [project]).fetchone()[0] == before
        assert connection.execute("SELECT to_jsonb(w) FROM authority_workspace w WHERE workspace_id=%s", [primary]).fetchone()[0] == primary_before
        assert connection.execute("SELECT COUNT(*) FROM authority_operation_output_asset WHERE operation_id=%s AND output_key='workspace.record' AND role='secondary_workspace'", [result["operation_id"]]).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM outbox_event WHERE payload->>'operation_id'=%s AND topic='authority.project_workspace.create.committed'", [result["operation_id"]]).fetchone()[0] == 1
    with pytest.raises(KernelError, match="WORKSPACE_SCOPE_CONFLICT"):
        application.execute(replace(command, idempotency_key=identifier("duplicate")), principal=principal)


@pytest.mark.parametrize("fault", ["project_cas", "primary_scope", "existing_primary", "foreign_principal", "foreign_query"])
def test_secondary_workspace_rejects_stale_or_foreign_scope(pilot_project, fault):
    project, primary, principal, application, _composition, _source = pilot_project
    command = workspace_command(pilot_project, identifier("rejected-workspace"))
    if fault == "foreign_query":
        with pytest.raises(KernelError, match="WORKSPACE_SCOPE_CONFLICT"):
            ProjectAuthorityQuery(DATABASE_URL).require_workspace(project_id="other-project", workspace_id=primary)
        return
    if fault == "project_cas":
        command = replace(command, expected_version=command.expected_version + 1)
    elif fault == "primary_scope":
        command = replace(command, workspace_id=identifier("foreign-primary"))
    elif fault == "existing_primary":
        command = replace(command, payload={"workspace_id": primary})
    else:
        principal = replace(principal, project_scope=frozenset({"other-project"}))
    with pytest.raises((KernelError, PermissionError)):
        application.execute(command, principal=principal)
    with transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM authority_workspace WHERE project_id=%s", [project]).fetchone()[0] == 1


@pytest.mark.parametrize("checkpoint", ["after_asset_version_insert", "after_business_projection_update", "after_outbox_insert"])
def test_secondary_workspace_failure_rolls_back_only_new_workspace(pilot_project, checkpoint):
    project, _primary, principal, _application, _composition, _source = pilot_project
    secondary = identifier("rollback-workspace")
    def fail(point):
        if point == checkpoint:
            raise RuntimeError("synthetic workspace transaction failure")
    application = ProjectAuthorityApplication(DATABASE_URL, application_build_id="shared-pilot-fixture", commit_sha="b" * 40,
                                              fault_injector=fail)
    with pytest.raises(RuntimeError, match="synthetic workspace"):
        application.execute(workspace_command(pilot_project, secondary), principal=principal)
    with transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM authority_workspace WHERE project_id=%s", [project]).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM authority_asset WHERE asset_id=%s", ["workspace:" + secondary]).fetchone()[0] == 0


@pytest.mark.parametrize("workspace_exists", [False, True])
def test_v3_initialization_reaches_content_and_formation_in_independent_workspace(pilot_project, tmp_path, workspace_exists):
    project, primary, original_principal, _project_app, composition, _source = pilot_project
    first = pilot_support._initialize(pilot_project, run_key="old-book")
    principal = replace(original_principal, permissions=original_principal.permissions | {
        "book.authority.execute", "content.authority.execute", "content.operation:creative.brief.create",
    })
    previous = single_book_policy()
    previous["comparison_budget"]["experiment_id"] = identifier("shared-lifetime")
    previous["comparison_budget"]["arms"][0].update(project_id=project, book_id=first["book_id"])
    previous["authorization"].update(project_id=project, book_id=first["book_id"])
    def configure(policy):
        return configure_creative_budget(database_url=DATABASE_URL, policy=policy, project_id=project, workspace_id=primary,
            principal=principal, application_build_id="shared-pilot-fixture", commit_sha="b" * 40,
            idempotency_key=identifier("budget-grant"), trace_id="trace:workspace-budget", correlation_id=project)
    configure(previous)
    policy = production_book_policy(previous)
    configure(policy)
    native_budget = get_creative_budget(DATABASE_URL, project)
    secondary, book_id = identifier("volume-workspace"), policy["authorization"]["book_id"]
    frozen = deepcopy(comparison_identities(Path(tmp_path))[0]["frozen_configuration"])
    frozen.update(comparison_budget=policy["comparison_budget"], run_key=identifier("new-book-run"))
    frozen["runtime_identity"].update(project_id=project, workspace_id=secondary, book_id=book_id, run_key=frozen["run_key"])
    frozen["runtime_settings"].update(NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT="480", NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT="12000000",
                                      NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF=policy["authorization"]["authorization_ref"])
    frozen["cost_accounting"]["authorization_ref"] = policy["authorization"]["authorization_ref"]
    def initialize():
        return prepare_pilot_book(composition=composition, principal=principal, project_id=project, workspace_id=secondary,
            book_id=book_id, run_key=frozen["run_key"], title="Synthetic independent workspace fixture", frozen=frozen,
            initialize=True, budget_binding=native_budget["budget_binding"])
    if workspace_exists:
        _project_app.execute(workspace_command(pilot_project, secondary), principal=principal)
        with transaction() as connection:
            connection.execute("UPDATE authority_workspace SET status='PAUSED' WHERE workspace_id=%s", [secondary])
        with pytest.raises(ValueError, match="ACTIVE workspace"):
            initialize()
        with transaction() as connection:
            connection.execute("UPDATE authority_workspace SET status='ACTIVE' WHERE workspace_id=%s", [secondary])
    book = initialize()
    assert initialize() == book
    assert book["workspace_id"] == secondary
    assert ProjectAuthorityQuery(DATABASE_URL).require_project(project)["workspace_id"] == primary
    content = ContentAuthorityApplication(DATABASE_URL, application_build_id="shared-pilot-fixture", commit_sha="b" * 40,
                                          integration_proven=CONTENT_CODECS, trusted_only=True)
    brief = content.execute(ContentOperationRequest(
        definition_name="creative.brief.create", project_id=project, workspace_id=secondary, actor_id=principal.principal_id,
        idempotency_key="brief:" + book_id, trace_id="trace:secondary-brief", correlation_id=book_id,
        payload={"input_selection": {"contract_version": "creative-input-selection.v1", "book_id": book_id, "source_kind": "CURRENT_AUTHOR_INPUT", "purpose": "WORK_PRODUCTION", "intent_ref": "explicit-test-case"}, "brief": {"creative_brief_contract_version": "creative-brief-v2", "idea": "An original young swordsman rescues his teacher.",
                           "genre": "guofeng xuanhuan", "audience": "adult adventure readers", "constraints": ["Bounded powers"],
                           "source_boundaries": ["Original expression only"]}},
    ), principal=principal)
    formation = StoryFormationApplication(DATABASE_URL, application_build_id="shared-pilot-fixture", commit_sha="b" * 40)
    command = StartStoryFormationCommand(project_id=project, workspace_id=secondary, book_id=book_id,
        actor_id=principal.principal_id, expected_book_version=book["version"], stable_idempotency_key="formation:" + book_id,
        trace_id="trace:secondary-formation", correlation_id=book_id, frozen_input=StoryFormationInput(
            creative_brief_asset_version_id=brief.asset_version_id, creative_brief_content_hash=brief.content_hash,
            generation_policy={"contract_version": "formation-generation.v2", "approval_mode": "REVIEW_PLAN", "creative_candidates": 2,
                               "target_chapters": 120, "title": "Synthetic independent workspace fixture"}))
    admitted = formation.admit(command, principal=principal)
    assert formation.admit(command, principal=principal).formation_run_id == admitted.formation_run_id
    run = formation.require(admitted.formation_run_id)
    assert run["workspace_id"] == secondary and run["book_id"] == book_id and run["lifecycle"] == "ADMITTED"
    assert get_creative_budget(DATABASE_URL, project) == native_budget
    with transaction() as connection:
        assert connection.execute("SELECT book_id FROM authority_workspace WHERE workspace_id=%s", [primary]).fetchone()[0] == first["book_id"]
        assert connection.execute("SELECT COUNT(*) FROM authority_book WHERE project_id=%s", [project]).fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM authority_external_effect WHERE project_id=%s", [project]).fetchone()[0] == 0


def test_concurrent_books_cannot_both_claim_new_workspace(pilot_project):
    project, _primary, principal, application, composition, _source = pilot_project
    secondary = identifier("contended-workspace")
    application.execute(workspace_command(pilot_project, secondary), principal=principal)
    book_application = composition.formation.generation.book_design
    books = [identifier("competing-book") for _ in range(2)]
    def create(book_id):
        try:
            result = book_application.execute(BookDesignAuthorityCommand(
                definition_name="book.create", project_id=project, workspace_id=secondary, book_id=book_id,
                actor_id=principal.principal_id, service_identity="workspace-fixture", idempotency_key="create:" + book_id,
                trace_id="trace:" + book_id, correlation_id=project,
                payload={"title": "Synthetic concurrent Book", "production_profile": {}, "runtime_policy": {}, "release_identity": "fixture-only"},
            ), principal=principal)
            return result["status"]
        except (KernelError, psycopg.Error):
            return "REJECTED"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, books))
    assert sorted(results) == ["REJECTED", "SUCCEEDED"]
    with transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM authority_book WHERE workspace_id=%s", [secondary]).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM authority_book b JOIN authority_workspace w ON w.book_id=b.book_id AND w.workspace_id=b.workspace_id WHERE b.workspace_id=%s", [secondary]).fetchone()[0] == 1


def test_current_selection_requires_native_author_and_exact_parent(pilot_project):
    from novel_forge.modules.authority_security import PrincipalType
    project, workspace, operator, *_ = pilot_project
    book = pilot_support._initialize(pilot_project, run_key="selected-input")
    principal = replace(operator, permissions=operator.permissions | {
        "content.authority.execute", "content.operation:creative.brief.create"})
    app = ContentAuthorityApplication(DATABASE_URL, application_build_id="shared-pilot-fixture",
        commit_sha="b" * 40, integration_proven=CONTENT_CODECS, trusted_only=True)
    selection = {"contract_version": "creative-input-selection.v1", "book_id": book["book_id"],
        "source_kind": "CURRENT_AUTHOR_INPUT", "purpose": "WORK_PRODUCTION", "intent_ref": "current-intent"}
    brief = {"creative_brief_contract_version": "creative-brief-v2", "idea": "A cook learns to share flour.",
        "genre": "fantasy cooking", "audience": "adult readers", "constraints": ["Actions change relationships"],
        "source_boundaries": ["Original selected work only"]}
    request = ContentOperationRequest(definition_name="creative.brief.create", project_id=project,
        workspace_id=workspace, actor_id=principal.principal_id, idempotency_key="selected-brief",
        trace_id="trace:input", correlation_id=book["book_id"], payload={"brief": brief})
    with pytest.raises(KernelError, match="CREATIVE_INPUT_SELECTION_REQUIRED"):
        app.admit(request, principal=principal)
    request = replace(request, payload={"brief": brief, "input_selection": selection})
    machine = replace(principal, principal_type=PrincipalType.SERVICE)
    with pytest.raises(PermissionError, match="authenticated author"):
        app.admit(request, principal=machine)
    root = app.execute(request, principal=principal)
    assert app.execute(request, principal=principal).asset_version_id == root.asset_version_id
    derived = {**selection, "source_kind": "TASK_GENERATED", "parent_input": {
        "asset_version_id": root.asset_version_id, "content_hash": root.content_hash}}
    child_request = replace(request, idempotency_key="derived-brief", input_assets=(derived["parent_input"],),
        payload={"brief": {**brief, "idea": "The cook must decide how to price a failed pastry."}, "input_selection": derived})
    assert app.execute(child_request, principal=machine).asset_version_id != root.asset_version_id
    with pytest.raises(KernelError, match="CREATIVE_INPUT_BOOK_MISMATCH"):
        app.admit(replace(child_request, idempotency_key="foreign-derived", payload={
            **child_request.payload, "input_selection": {**derived, "book_id": "other-book"}}), principal=machine)
    with pytest.raises(KernelError, match="CREATIVE_INPUT_USE_FORBIDDEN"):
        app.admit(replace(request, idempotency_key="old-sample", payload={"brief": brief,
            "input_selection": {**selection, "source_kind": "HISTORICAL_TEST_SAMPLE"}}), principal=principal)


def test_same_project_inputs_cannot_bind_another_books_workspace(pilot_project):
    project, workspace, operator, project_app, composition, _ = pilot_project
    first = pilot_support._initialize(pilot_project, run_key="first-input-book")
    secondary = identifier("input-isolation-workspace")
    project_app.execute(workspace_command(pilot_project, secondary), principal=operator)
    second = {"book_id": identifier("second-input-book")}
    composition.formation.generation.book_design.execute(BookDesignAuthorityCommand(
        definition_name="book.create", project_id=project, workspace_id=secondary, book_id=second["book_id"],
        actor_id=operator.principal_id, service_identity="workspace-fixture", idempotency_key="create:" + second["book_id"],
        trace_id="trace:second-input-book", correlation_id=project,
        payload={"title": "Independent second Book", "production_profile": {}, "runtime_policy": {}, "release_identity": "fixture-only"}), principal=operator)
    principal = replace(operator, permissions=operator.permissions | {
        "content.authority.execute", "content.operation:creative.brief.create"})
    app = ContentAuthorityApplication(DATABASE_URL, application_build_id="shared-pilot-fixture",
        commit_sha="b" * 40, integration_proven=CONTENT_CODECS, trusted_only=True)
    selection = {"contract_version": "creative-input-selection.v1", "book_id": first["book_id"],
        "source_kind": "CURRENT_AUTHOR_INPUT", "purpose": "WORK_PRODUCTION", "intent_ref": "current-book-task"}
    brief = {"creative_brief_contract_version": "creative-brief-v2", "idea": "A village choir prepares a concert.",
        "genre": "ensemble comedy", "audience": "adult readers", "constraints": ["Use the selected concert conflict"], "source_boundaries": ["Original expression"]}
    request = ContentOperationRequest(definition_name="creative.brief.create", project_id=project,
        workspace_id=workspace, actor_id=principal.principal_id, idempotency_key="current-book-brief",
        trace_id="trace:input-scope", correlation_id=first["book_id"], payload={"brief": brief, "input_selection": selection})
    original = app.execute(request, principal=principal)
    with pytest.raises(KernelError, match="CREATIVE_INPUT_BOOK_MISMATCH"):
        app.admit(replace(request, idempotency_key="mislabelled-input",
            payload={"brief": brief, "input_selection": {**selection, "book_id": second["book_id"]}}), principal=principal)
    derived = {**selection, "book_id": second["book_id"], "source_kind": "TASK_GENERATED", "parent_input": {
        "asset_version_id": original.asset_version_id, "content_hash": original.content_hash}}
    with pytest.raises(KernelError, match="CREATIVE_INPUT_BOOK_MISMATCH"):
        app.admit(replace(request, workspace_id=secondary, idempotency_key="foreign-parent",
            input_assets=(derived["parent_input"],), payload={"brief": brief, "input_selection": derived}), principal=principal)
    own = app.execute(replace(request, workspace_id=secondary, idempotency_key="second-own-input",
        payload={"brief": {**brief, "idea": "A cook opens a mountain bakery."},
            "input_selection": {**selection, "book_id": second["book_id"], "intent_ref": "second-current-task"}}), principal=principal)
    assert own.asset_version_id != original.asset_version_id
    with transaction() as connection:
        assert connection.execute("SELECT count(*) FROM authority_book WHERE project_id=%s", [project]).fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [project]).fetchone()[0] == 0
