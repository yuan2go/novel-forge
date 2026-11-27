from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_design_authority import BookDesignAuthorityApplication
from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
from novel_forge.modules.project_authority.query import ProjectAuthorityQuery
from scripts.creation_pilot import prepare_pilot_book
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, transaction
from tests.integration.test_creative_experiment_budget_postgres import BUILD_ID, COMMIT_SHA, BudgetFixture
from tests.unit.test_creation_comparison import comparison_identities


@pytest.mark.parametrize("partial_start", [False, True], ids=["full-grant", "partial-grant"])
def test_native_grant_update_resumes_same_book_without_rewriting_semantics_or_ledger(tmp_path, partial_start):
    ensure_migrated()
    budget = BudgetFixture(native_project_only=True)
    project, workspace, book_id = budget.projects["A"], budget.workspaces["A"], budget.books["A"]
    initial_project = ProjectAuthorityQuery(DATABASE_URL).require_project(project)
    frozen = comparison_identities(tmp_path)[0]["frozen_configuration"]
    frozen["comparison_budget"] = deepcopy(budget.plan)
    frozen["run_key"] = project + ":creation"
    frozen["runtime_identity"].update(project_id=project, workspace_id=workspace, book_id=book_id, run_key=frozen["run_key"])
    limits = frozen["runtime_settings"]
    limits["NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT"] = "6"
    limits["NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT"] = "6000"
    frozen["creation_policy"]["profiles"]["production_profile"]["content"]["knowledge_access_policy"] = {
        "mode": "DENY_ALL", "allowed_knowledge_card_asset_version_ids": [],
    }
    application = BookDesignAuthorityApplication(DATABASE_URL, application_build_id=BUILD_ID, commit_sha=COMMIT_SHA)
    composition = SimpleNamespace(formation=SimpleNamespace(generation=SimpleNamespace(book_design=application)))

    def initialize(binding, *, configuration=None, create=True):
        return prepare_pilot_book(
            composition=composition, principal=budget.principal,
            project_id=project, workspace_id=workspace, book_id=book_id, run_key=frozen["run_key"],
            title="Synthetic configuration; no literary or Provider execution evidence",
            frozen=configuration or frozen, initialize=create, budget_binding=binding,
        )

    def configure(version, *, source_only=False, partial=False):
        policy = budget.policy(version=version)
        if source_only:
            for phase in ("CREATION", "REPAIR"):
                policy["authorization"]["authorized_cumulative_caps"][phase] = {"calls": 0, "tokens": 0}
        elif partial:
            policy["authorization"]["authorized_cumulative_caps"]["CREATION"] = {"calls": 1, "tokens": 500}
            policy["authorization"]["authorized_cumulative_caps"]["REPAIR"] = {"calls": 0, "tokens": 0}
        budget.configure(policy)
        binding = get_creative_budget(DATABASE_URL, project)["budget_binding"]
        reference = binding["authorization"]["authorization_ref"]
        frozen["cost_accounting"]["authorization_ref"] = reference
        limits["NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF"] = reference
        return binding

    source_grant = configure("fixture-source-stage-v1", source_only=True)
    with pytest.raises(ValueError, match="requires positive CREATION calls and tokens"):
        initialize(source_grant)
    with transaction() as connection:
        assert connection.execute("SELECT count(*) FROM authority_book WHERE project_id=%s", [project]).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [project]).fetchone()[0] == 0

    creative_grant = configure("fixture-creation-v2", partial=partial_start)
    book = initialize(creative_grant)
    assert initialize(creative_grant) == book
    created_project = ProjectAuthorityQuery(DATABASE_URL).require_project(project)
    for field in ("version", "asset_version_id", "created_by_operation_id", "last_operation_id"):
        assert created_project[field] == initial_project[field]
    _, reservation = budget.reserve("CREATION", 100)
    with transaction() as connection:
        ledger_before = connection.execute("SELECT to_jsonb(r) FROM authority_budget_reservation r WHERE reservation_id=%s", [reservation["reservation_id"]]).fetchone()[0]
    usage_before = budget.usage()
    assert usage_before["creation_opportunity"]["policy_hash"] == creative_grant["policy_hash"]
    assert usage_before["creation_opportunity"]["authorized_cumulative_caps"] == creative_grant["authorization"]["authorized_cumulative_caps"]

    resumed_grant = configure("fixture-renewed-same-opportunity-v3")
    assert resumed_grant["policy_hash"] != creative_grant["policy_hash"]
    assert initialize(resumed_grant) == book
    assert budget.usage() == usage_before
    assert ProjectAuthorityQuery(DATABASE_URL).require_project(project) == created_project
    with transaction() as connection:
        assert connection.execute("SELECT to_jsonb(r) FROM authority_budget_reservation r WHERE reservation_id=%s", [reservation["reservation_id"]]).fetchone()[0] == ledger_before
        assert connection.execute("SELECT count(*) FROM authority_book WHERE project_id=%s", [project]).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM authority_operation WHERE project_id=%s AND definition_name='book.create'", [project]).fetchone()[0] == 1

    for field in ("model", "input", "context"):
        changed = deepcopy(frozen)
        if field == "model":
            changed["models"]["draft"]["model_profile"]["model_id"] = "different-fixture-model"
        elif field == "input":
            changed["input_snapshot"]["files"]["brief"]["content_hash"] = "sha256:" + "d" * 64
        else:
            changed["runtime_settings"]["NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET"] = "64000"
        with pytest.raises(ValueError, match="differs from the registered Book"):
            initialize(resumed_grant, configuration=changed, create=False)
    unbound = deepcopy(frozen)
    unbound["cost_accounting"]["authorization_ref"] = "fixture-unregistered-grant"
    with pytest.raises(ValueError, match="exact budget authorization binding"):
        initialize(resumed_grant, configuration=unbound, create=False)
    assert initialize(resumed_grant, create=False) == book
    assert budget.usage() == usage_before
