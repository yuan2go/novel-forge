from dataclasses import replace

import pytest

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.capability_packs.validation_deployment import install_chapter_validation_pack
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness, ROOT
from tests.unit.test_creative_execution_template import template


@pytest.mark.parametrize("owner", ["source", "successor", "grandchild"])
@pytest.mark.parametrize("blocker", ["RESERVED", "HELD_UNKNOWN", "HELD_LEASE"])
def test_result_admission_blocks_unsettled_lineage_before_materialization(owner, blocker):
    import psycopg
    from novel_forge.modules.story_planning_runtime.result_admission import require_settled_failed_lineage

    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("CREATE TEMP TABLE authority_story_planning_generation (operation_id text, repair_of_operation_id text)")
        connection.execute("CREATE TEMP TABLE authority_operation (operation_id text, status text)")
        connection.execute("CREATE TEMP TABLE authority_external_effect (operation_id text, status text)")
        connection.execute("CREATE TEMP TABLE authority_budget_reservation (operation_id text, status text, cost_status text)")
        connection.execute("CREATE TEMP TABLE authority_attempt (attempt_id text, operation_id text)")
        connection.execute("CREATE TEMP TABLE authority_lease_acquisition (attempt_id text, status text)")
        connection.execute("INSERT INTO authority_story_planning_generation VALUES ('source',NULL),('successor','source'),('grandchild','successor'),('unrelated',NULL)")
        for operation in ("source", "successor", "grandchild"):
            connection.execute("INSERT INTO authority_operation VALUES (%s,'FAILED_FINAL')", [operation])
            connection.execute("INSERT INTO authority_external_effect VALUES (%s,'SUCCEEDED')", [operation])
            connection.execute("INSERT INTO authority_budget_reservation VALUES (%s,'SETTLED','UNKNOWN')", [operation])
            connection.execute("INSERT INTO authority_attempt VALUES (%s,%s)", [operation + ":attempt", operation])
            connection.execute("INSERT INTO authority_lease_acquisition VALUES (%s,'RELEASED')", [operation + ":attempt"])
        connection.execute("INSERT INTO authority_operation VALUES ('unrelated','UNKNOWN')")
        connection.execute("INSERT INTO authority_external_effect VALUES ('unrelated','UNKNOWN')")
        connection.execute("INSERT INTO authority_budget_reservation VALUES ('unrelated','HELD_UNKNOWN','UNKNOWN')")
        with connection.cursor() as cursor:
            require_settled_failed_lineage(cursor, source_operation_id="source")
            if blocker == "HELD_LEASE":
                cursor.execute("UPDATE authority_lease_acquisition SET status='HELD' WHERE attempt_id=%s", [owner + ":attempt"])
            else:
                cursor.execute("INSERT INTO authority_budget_reservation VALUES (%s,%s,'UNKNOWN')", [owner, blocker])
            cursor.execute("SELECT operation_id,status,cost_status FROM authority_budget_reservation ORDER BY operation_id,status")
            retained_budgets = cursor.fetchall()
            cursor.execute("SELECT attempt_id,status FROM authority_lease_acquisition ORDER BY attempt_id")
            retained_leases = cursor.fetchall()
            with pytest.raises(KernelError, match="PLANNING_RESULT_ADMISSION_RECONCILIATION_REQUIRED"):
                require_settled_failed_lineage(cursor, source_operation_id="source")
            cursor.execute("SELECT operation_id,status,cost_status FROM authority_budget_reservation ORDER BY operation_id,status")
            assert cursor.fetchall() == retained_budgets
            cursor.execute("SELECT attempt_id,status FROM authority_lease_acquisition ORDER BY attempt_id")
            assert cursor.fetchall() == retained_leases
            cursor.execute("SELECT status FROM authority_operation WHERE operation_id<>'unrelated'")
            assert cursor.fetchall() == [("FAILED_FINAL",)] * 3


def test_frozen_template_configuration_definition_survives_v2_successor(monkeypatch):
    from copy import deepcopy
    import novel_forge.modules.authority_handler_runtime.policy_commands as module
    harness = CapabilityPackPostgresHarness("creative-definition-successor")
    operator = replace(harness.compiler, permissions=harness.compiler.permissions | {"book.authority.execute"})
    value = template(harness.book_ids[0])
    arguments = dict(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=harness.project_id,
        workspace_id=harness.workspace_id, principal=operator, application_build_id=harness.application_build_id,
        commit_sha=harness.release_sha, trace_id=harness.project_id, correlation_id=harness.project_id)
    current_definition = module.owned_policy_definition

    def frozen_definition(**kwargs):
        definition = deepcopy(current_definition(**kwargs))
        definition.update(definition_version="1.6.0", command_schema_version="provider.routing_policy.configure.command.v6",
            result_schema_version="provider.routing_policy.configure.result.v6")
        for key in ("command_schema", "result_schema", "input_contract"):
            schema = definition[key]["properties"]["policy"]["properties"]["execution_templates"]["items"]
            schema["$defs"].pop("RepairRoutingConfiguration", None)
            schema["properties"].pop("repair_routing", None)
            schema["properties"]["version"].pop("enum", None)
            schema["properties"]["version"]["const"] = "creative-execution-template.v1"
        return definition

    with monkeypatch.context() as legacy:
        legacy.setattr(module, "owned_policy_definition", frozen_definition)
        old = module.configure_owned_policy(**arguments, idempotency_key=harness.project_id+":v1",
            content={"policy_version":"v1", "reason":"frozen historical contract", "task_overrides":[], "execution_templates":[value]})
        old = deepcopy(old)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT definition_hash FROM authority_operation_definition WHERE name='provider.routing_policy.configure' AND definition_version='1.6.0'")
        digest = uow.cursor.fetchone()[0]
    value.update(version="creative-execution-template.v2", repair_routing={"version":"native-repair-routing.v1", "max_same_route_repairs":2})
    module.configure_owned_policy(**arguments, idempotency_key=harness.project_id+":v2",
        content={"policy_version":"v2", "reason":"explicit bounded repair successor", "task_overrides":[], "execution_templates":[value]})
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT definition_hash FROM authority_operation_definition WHERE name='provider.routing_policy.configure' AND definition_version='1.6.0'")
        assert uow.cursor.fetchone()[0] == digest
        uow.cursor.execute("SELECT content FROM authority_runtime_policy_version WHERE project_id=%s AND owner='PROVIDER_ROUTING' AND policy_version='v1'", [harness.project_id])
        assert uow.cursor.fetchone()[0] == old["policy"]
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [harness.project_id])
        assert uow.cursor.fetchone()[0] == 0


def test_native_pack_template_admission_has_no_human_approval_and_cannot_enter_production():
    harness = CapabilityPackPostgresHarness("creative-admission")
    book = harness.book_ids[0]
    operator = replace(harness.compiler, permissions=harness.compiler.permissions | {"book.authority.execute", "agent.authority.admin"})
    configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING",
        content={"policy_version": "creative.v1", "task_overrides": [], "reason": "isolated native contract test",
                 "execution_templates": [template(book)]}, project_id=harness.project_id, workspace_id=harness.workspace_id,
        idempotency_key=harness.project_id + ":template", trace_id=harness.project_id, correlation_id=harness.project_id,
        application_build_id=harness.application_build_id, commit_sha=harness.release_sha, principal=operator)
    result = install_chapter_validation_pack(DATABASE_URL, repository_root=ROOT, project_id=harness.project_id,
        workspace_id=harness.workspace_id, book_id=book, application_build_id=harness.application_build_id,
        commit_sha=harness.release_sha, compiler=operator, approver=operator, agent_admin=operator,
        pack_id_override=harness.pack_id)
    assert result["approval"]["checks"]["human_pack_approval"]["status"] == "NOT_RUN"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_capability_pack_approval WHERE compilation_id=%s", [result["compilation_id"]])
        assert uow.cursor.fetchone()[0] == 0
    with pytest.raises(KernelError):
        harness.execute("capability_pack.deployment.create", principal=operator, pack_version="1.0.0",
            compilation_id=result["compilation_id"], deployment_id=harness.project_id + ":production",
            payload={"target_scope_type": "BOOK", "project_id": harness.project_id, "workspace_id": harness.workspace_id,
                     "book_id": book, "environment": "production", "runtime_profile": "production", "rollout_policy_ref": "rollout:stable-sha256:v1"})
    configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING",
        content={"policy_version": "creative.v2", "task_overrides": [], "reason": "explicit human approval objective",
                 "execution_templates": [template(book, require_pack_human_approval=True)]}, project_id=harness.project_id, workspace_id=harness.workspace_id,
        idempotency_key=harness.project_id + ":human-objective", trace_id=harness.project_id, correlation_id=harness.project_id,
        application_build_id=harness.application_build_id, commit_sha=harness.release_sha, principal=operator)
    from novel_forge.modules.capability_pack_authority.validation_admission import require_validation_admission
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        compilation = uow.repositories.capability_packs.require_compilation(result["compilation_id"])
        assert require_validation_admission(uow.repositories.capability_packs, compilation, environment="validation", book_id=book) is None
