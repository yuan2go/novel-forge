from contextlib import contextmanager

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_zero_send_context_guards_postgres import _insert


@contextmanager
def _fixture():
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            tables = ("authority_operation", "authority_story_planning_runtime_continuation", "authority_story_planning_generation",
                      "authority_attempt", "authority_attempt_capability_pack_snapshot", "authority_story_formation_run",
                      "authority_story_creation_cancellation", "authority_operation_output_asset", "authority_asset_version", "authority_asset",
                      "authority_external_effect", "authority_external_effect_dispatch", "authority_external_receipt", "authority_budget_reservation",
                      "authority_lease_acquisition", "authority_worker_cancel_signal", "authority_book_production",
                      "authority_book_production_input_binding", "authority_book_production_input_snapshot", "active_story_plan_version",
                      "story_plan_binding", "authority_book_chapter_acceptance", "authority_story_design_version_state",
                      "authority_story_planning_validation_report")
            for table in tables:
                connection.execute(sql.SQL("CREATE TEMP TABLE {} AS SELECT * FROM public.{} WITH NO DATA").format(sql.Identifier(table), sql.Identifier(table)))
            def insert(table, **values):
                _insert(connection, table, **values)
            command = {"project_id": "project", "workspace_id": "workspace", "book_id": "book", "execution_contract_version": "1.21.0",
                       "generator_operation_name": "chapter_plan.generate", "opening_execution_binding": {"opening_run_id": "opening"}}
            child = {**command, "runtime_continuation_id": "runtime", "idempotency_key": "child"}
            for op, status, definition, payload, cause in (("source", "FAILED_FINAL", "story_planning.generate", command, None),
                    ("child", "ADMITTED", "story_planning.generate", child, "source"),
                    ("registration", "SUCCEEDED", "story_planning.runtime_continuation.register", {}, None),
                    ("reference", "SUCCEEDED", "story_planning.generate", command, None)):
                insert("authority_operation", operation_id=op, status=status, definition_name=definition, definition_version="1.21.0",
                       actor_id="owner", project_id="project", workspace_id="workspace", command_payload={"payload": payload}, causation_operation_id=cause)
            for op in ("source", "reference"):
                insert("authority_story_planning_generation", operation_id=op, project_id="project", workspace_id="workspace", book_id="book",
                       generator_operation_name="chapter_plan.generate", logical_key="chapter:1", planning_scope="CHAPTER", repair_number=0,
                       input_snapshot=[], input_snapshot_hash="snapshot")
            pack = {key: key for key in ("prompt_bundle_hash", "route_policy_hash", "context_policy_hash", "skill_bundle_hash", "tool_policy_hash")}
            identity = {key: key for key in ("model_provider", "model_id", "reasoning_effort", "runtime_class", "model_backend_id", "cost_accounting_basis")}
            identity.update(account={"entitlement": {"authorization_ref": "grant"}}, pack_snapshot=pack)
            failure = {"error_code": "PROGRAMMING_BUG", "failure_class": "programming_bug", "error_message": "canceling statement due to statement timeout"}
            decision = {"formation_run_id": "formation", "recovery_kind": "planning-unsent-context-query-recovery.v1",
                        "database_failure": {"source_failure": failure, "source_operation_id": "source", "source_attempt_id": "attempt",
                         "project_id": "project", "workspace_id": "workspace", "book_id": "book", "pack_snapshot_id": "pack", "pack_snapshot_hash": "pack-hash"},
                        "unsent_context_query_diagnostic": {"contract_version": "planning-unsent-context-query-recovery.v1", "source_operation_id": "source",
                         "source_attempt_id": "attempt", "query_owner": "mkaos_authority.list_planning_usage", "revalidation_status": "PASS_NO_PROVIDER_NO_OUTPUT"},
                        "original_stage_runtime": {"continuation_id": "reference-runtime", "operation_id": "reference"}}
            for key, successor in (("runtime", "child"), ("reference-runtime", "reference")):
                insert("authority_story_planning_runtime_continuation", continuation_id=key, source_operation_id="source", successor_operation_id=successor,
                       registered_by_operation_id="registration", project_id="project", workspace_id="workspace", book_id="book", chain_depth=2,
                       source_command=command, successor_command=child, target_runtime=identity, decision_evidence=decision)
            insert("authority_attempt", operation_id="source", attempt_id="attempt", attempt_number=1, status="FAILED_FINAL", result=failure)
            insert("authority_attempt_capability_pack_snapshot", operation_id="source", attempt_id="attempt", snapshot_id="pack", snapshot_hash="pack-hash", snapshot_payload=pack)
            insert("authority_story_formation_run", formation_run_id="formation", project_id="project", workspace_id="workspace", book_id="book",
                   frozen_stage_inputs={"generation_policy": {"auto_authorization": {"authorized_by_principal_id": "owner"}}})
            insert("authority_external_effect", operation_id="reference", external_effect_id="reference-effect", status="SUCCEEDED", request_payload={"stage": "chapter_plan.generate"})
            yield connection, insert, command, child, identity, decision
        finally:
            connection.rollback()


@pytest.mark.parametrize("kind", ["query", "book-query", "schema", "planning-host", "planning-host-arc"])
def test_public_dispatch_predicate_positive_negative_and_replay(kind):
    with _fixture() as (connection, insert, command, child, target, decision):
        if kind == "book-query":
            command.pop("opening_execution_binding")
            child.pop("opening_execution_binding")
            command.update(input_versions={"chapter_group_plan": "parent"}, world_preparation_request={"accepted_through_chapter": 0,
                           "book_run_id": "book-run", "story_state_version_id": "", "canon_version_id": "", "input_snapshot_id": "input"})
            child.update(command)
            decision["original_stage_runtime"].update(reference_kind="BOOK_SUPERVISOR_FIRST_CHAPTER_PLAN",
                evidence_boundary="SAME_BOOK_ACTIVE_PARENT_GROUP_REFERENCE_NOT_SOURCE_PROVIDER_INPUT", book_scope={
                    "scope_version": "book-supervisor-first-chapter-query-recovery.v1", "book_run_id": "book-run", "book_version_at_recovery": "3",
                    "input_binding_id": "input-binding", "input_binding_version": "1", "input_snapshot_id": "input", "input_snapshot_hash": "input-hash",
                    "parent_binding_id": "parent-binding", "parent_binding_version": "2", "parent_asset_version_id": "parent", "parent_content_hash": "parent-hash"})
            connection.execute("UPDATE authority_story_planning_generation SET generator_operation_name='chapter_group_plan.generate',status='ACTIVE',candidate_asset_version_id='parent' WHERE operation_id='reference'")
            connection.execute("UPDATE authority_external_effect SET request_payload='{\"stage\":\"chapter_group_plan.generate\"}'")
            insert("authority_book_production", book_run_id="book-run", project_id="project", workspace_id="workspace", book_id="book", version=3,
                   stable_idempotency_key="formation:production", input_mode="RESOLVED_AUTHORITY_INPUT", state="CHAPTER_PLAN_REQUIRED", current_chapter=0, accepted_through_chapter=0)
            insert("authority_book_production_input_binding", book_run_id="book-run", project_id="project", book_id="book", binding_id="input-binding", binding_version=1, snapshot_id="input")
            insert("authority_book_production_input_snapshot", snapshot_id="input", project_id="project", workspace_id="workspace", book_id="book", snapshot_hash="input-hash")
            insert("active_story_plan_version", project_id="project", book_id="book", binding_id="parent-binding", asset_version_id="parent")
            insert("story_plan_binding", project_id="project", book_id="book", binding_id="parent-binding", asset_version_id="parent", contract_type="CHAPTER_GROUP", freshness="CURRENT", version=2)
            insert("authority_asset_version", asset_version_id="parent", content_hash="parent-hash", content={"chapter_range": [1, 3]})
        elif kind == "schema":
            evidence = {"stage": "chapter_plan.generate", "production_execution": {"process_evidence": {"failure_code": "PROVIDER_SCHEMA_REJECTED",
                        "provider_schema_contract": {"equivalent_projection": "codex-nullable-shared-types.v2", "canonical_hash": "canonical", "provider_hash": "old-wire"}}}}
            target["provider_schema_correction"] = {"model_call_log_asset_version_id": "log", "model_call_log_content_hash": "log-hash", "external_effect_id": "effect",
                "wire_correction": {"contract_version": "codex-nullable-shared-types.v3", "reversible_equivalence": "EXACT", "canonical_hash": "canonical", "previous_wire_hash": "old-wire", "corrected_wire_hash": "new-wire"}}
            insert("authority_operation_output_asset", operation_id="source", asset_version_id="log")
            insert("authority_asset_version", asset_version_id="log", content_hash="log-hash", content=evidence)
            insert("authority_external_effect", operation_id="source", external_effect_id="effect", project_id="project", effect_type="model.invoke", status="FAILED_FINAL")
            insert("authority_external_effect_dispatch", external_effect_id="effect", status="FAILED_FINAL", evidence={"production_execution": evidence["production_execution"]})
        elif kind.startswith("planning-host"):
            arc = kind.endswith("-arc")
            mode = "PLANNING_ARC_SCOPE_SUCCESSOR" if arc else "PLANNING_REFERENCE_CONTRACT_SUCCESSOR"
            command.update(execution_contract_version="1.20.0" if arc else "1.19.0", generator_operation_name="chapter_group_plan.generate", logical_key="group", repair_number=0)
            child.update(command, execution_contract_version="1.21.0", repair_reason=mode)
            connection.execute("UPDATE authority_operation SET status='SUCCEEDED',definition_version=%s,definition_snapshot='{\"definition_hash\":\"source-definition\"}' WHERE operation_id='source'", [command['execution_contract_version']])
            connection.execute("UPDATE authority_operation SET definition_version='2.0.0' WHERE operation_id='registration'")
            connection.execute("UPDATE authority_story_planning_generation SET generator_operation_name='chapter_group_plan.generate',logical_key='group',planning_scope='CHAPTER_GROUP',status='REJECTED',candidate_asset_version_id='candidate' WHERE operation_id='source'")
            connection.execute("UPDATE authority_attempt SET status='SUCCEEDED'")
            connection.execute("UPDATE authority_story_planning_runtime_continuation SET chain_depth=3 WHERE continuation_id='runtime'")
            connection.execute("UPDATE authority_story_planning_runtime_continuation SET successor_operation_id='source',target_runtime='{\"planning_capacity\":{\"context_revalidation\":{}}}' WHERE continuation_id='reference-runtime'")
            target["planning_reference_contract"] = {"contract_version": "planning-reference-contract-successor.v2", "source_candidate_hash": "candidate-hash",
                "validation_report_hash": "report-hash", "source_book_frontier": None, "source_external_effect_id": "host-effect"}
            decision["changed_contract"] = "planning-host-source-selectors.v2"
            insert("authority_asset_version", asset_version_id="candidate", content_hash="candidate-hash", content={})
            insert("authority_story_design_version_state", project_id="project", asset_version_id="candidate", lifecycle="REJECTED", qualification="FAILED", approval="PENDING", freshness="CURRENT", created_by_operation_id="source")
            insert("authority_story_planning_validation_report", validation_report_id="report", generation_operation_id="source", candidate_asset_version_id="candidate",
                   project_id="project", status="FAIL", report={"error_code": "NARRATIVE_REALIZATION_ARC_SCOPE_INVALID" if arc else "WORLD_REALIZATION_REFERENCE_INVALID"}, report_hash="report-hash")
            insert("authority_external_effect", operation_id="source", external_effect_id="host-effect", status="SUCCEEDED")
            insert("authority_budget_reservation", operation_id="source", external_effect_id="host-effect", status="SETTLED")
            if arc:
                target['planning_host_revalidation'] = {**target.pop('planning_reference_contract'), 'contract_version': 'planning-arc-scope-revalidation.v2',
                    'source_definition_hash': 'source-definition', 'source_release_sha': 'a' * 40, 'historical_source_sha': 'c9c7fc1d9a6d8a2dde715890105990d02a37d657'}
                decision.update(planning_host_revalidation='planning-arc-scope-revalidation.v2', provider_dispatch_authorized=False)
                connection.execute("UPDATE authority_story_planning_runtime_continuation SET chain_depth=4,source_release_sha=%s WHERE continuation_id='runtime'", ['a' * 40])
                connection.execute("UPDATE authority_story_planning_runtime_continuation SET chain_depth=3,decision_evidence='{\"changed_contract\":\"planning-host-source-selectors.v1\"}',target_runtime='{\"planning_reference_contract\":{\"contract_version\":\"planning-reference-contract-successor.v1\"}}' WHERE continuation_id='reference-runtime'")
        connection.execute("UPDATE authority_operation SET command_payload=%s WHERE operation_id='source'", [Jsonb({"payload": command})])
        connection.execute("UPDATE authority_operation SET command_payload=%s WHERE operation_id='child'", [Jsonb({"payload": child})])
        connection.execute("UPDATE authority_story_planning_runtime_continuation SET source_command=%s,successor_command=%s,target_runtime=%s,decision_evidence=%s,source_evidence_asset_version_id=%s WHERE continuation_id='runtime'",
                           [Jsonb(command), Jsonb(child), Jsonb(target), Jsonb(decision), "candidate" if kind.startswith("planning-host") else None])
        generation = connection.execute("SELECT to_jsonb(g) FROM authority_story_planning_generation g WHERE operation_id='source'").fetchone()[0]
        generation.update(candidate_asset_version_id=None)
        if kind.startswith("planning-host"):
            generation.update(runtime_continuation_id="runtime", repair_reason=mode)
        names = {"query": "authority_unsent_query_continuation_permitted", "book-query": "authority_book_unsent_query_continuation_permitted",
                 "schema": "authority_schema_continuation_permitted", "planning-host": "authority_planning_host_continuation_permitted", "planning-host-arc": "authority_planning_host_continuation_permitted"}
        def accepted(value=generation):
            return connection.execute(sql.SQL("SELECT {}('runtime','child',%s)").format(sql.Identifier(names[kind])), [Jsonb(value)]).fetchone()[0]
        assert accepted() is True
        assert accepted() is True
        if kind == 'planning-host-arc':
            connection.execute("SAVEPOINT frozen_definition")
            connection.execute("UPDATE authority_operation SET definition_snapshot='{}' WHERE operation_id='source'")
            assert not accepted()
            connection.execute("ROLLBACK TO SAVEPOINT frozen_definition")
            connection.execute("UPDATE authority_operation SET definition_snapshot='{\"definition_hash\":\"wrong\"}' WHERE operation_id='source'")
            assert not accepted()
            connection.execute("ROLLBACK TO SAVEPOINT frozen_definition")
            connection.execute("RELEASE SAVEPOINT frozen_definition")
        for key in ("book_id", "logical_key", "input_snapshot_hash"):
            assert not accepted({**generation, key: None})
            assert not accepted({**generation, key: "foreign"})
        for mutation in ("UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='child'",
                         "UPDATE authority_operation SET status='FAILED_FINAL' WHERE operation_id='registration'",
                         "INSERT INTO authority_lease_acquisition(attempt_id,status) VALUES('attempt','HELD')",
                         "UPDATE authority_story_planning_runtime_continuation SET source_command='{}' WHERE continuation_id='runtime'"):
            connection.execute("SAVEPOINT rejected")
            connection.execute(mutation)
            assert not accepted(), mutation
            connection.execute("ROLLBACK TO SAVEPOINT rejected")
            connection.execute("RELEASE SAVEPOINT rejected")
        assert accepted() is True
