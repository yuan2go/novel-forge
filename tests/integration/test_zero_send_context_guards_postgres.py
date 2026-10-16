import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations.versions import (
    v20261012_0202_prepared_planning_continuation as prepared,
    v20261015_0219_world_exact_context_convergence as world,
    v20261015_0220_chapter_prior_audit_convergence as chapter,
)
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated


def _insert(connection, table, **values):
    connection.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, values)),
        sql.SQL(",").join(sql.Placeholder() for _ in values)),
        [Jsonb(value) if isinstance(value, (dict, list)) else value for value in values.values()])


@pytest.mark.parametrize("kind", ["world", "chapter", "world-legacy", "chapter-legacy"])
def test_exact_context_sql_preserves_zero_send_and_verified_preparation_boundaries(kind):
    ensure_migrated()
    is_world = kind.startswith("world")
    legacy = kind.endswith("legacy")
    tables = ("authority_operation", "authority_story_planning_runtime_continuation",
              "authority_story_planning_generation", "authority_attempt", "authority_attempt_capability_pack_snapshot",
              "authority_story_formation_run", "authority_operation_output_asset", "authority_asset_version",
              "authority_asset", "authority_story_creation_cancellation", "authority_external_effect",
              "authority_budget_reservation", "authority_lease_acquisition", "authority_worker_cancel_signal",
              "authority_book_production", "authority_generation_isolation", "authority_external_effect_dispatch",
              "authority_external_receipt")
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in tables:
                connection.execute(sql.SQL("CREATE TEMP TABLE {} AS SELECT * FROM public.{} WITH NO DATA").format(
                    sql.Identifier(table), sql.Identifier(table)))
            for statement in (prepared._WORLD, world.UPGRADE_STATEMENTS[0], chapter.UPGRADE_STATEMENTS[0]):
                connection.execute(statement.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
            def insert(table, **values):
                _insert(connection, table, **values)
            source = {"project_id": "project", "workspace_id": "workspace", "book_id": "book",
                      "execution_contract_version": "1.21.0", "generator_operation_name": "chapter_plan.generate",
                      "runtime_continuation_id": "previous", "world_preparation_request": {"request": "exact"}}
            child = {**source, "runtime_continuation_id": "runtime", "idempotency_key": "child"}
            failure = ({"error_code": "PROGRAMMING_BUG", "failure_class": "programming_bug",
                        "error_message": "PROTECTED_CONTEXT_BUDGET_EXCEEDED: world-source exceeds TOTAL_CONTEXT_LIMIT; requires=20, available=10, used=30, total=40"}
                       if is_world else {"error_code": "CONTEXT_CAPACITY_EXCEEDED", "failure_class": "retryable",
                        "error_message": "CONTEXT_CAPACITY_EXCEEDED: Complete input leaves no model context for generation"})
            contract = "world-protected-context-accounting.v1" if is_world else "chapter-prior-method-audits.v1"
            proof = {"contract_version": contract, "source_operation_id": "source", "source_failure": failure,
                     "source_operation_status": "FAILED_FINAL" if is_world else "FAILED_RETRYABLE",
                     "context_asset_version_id": "context", "context_content_hash": "context-hash",
                     "prior_runtime_continuation_id": "previous", "world_source_asset_version_id": "world-source",
                     "world_source_content_hash": "world-source-hash", "world_source_output_key": "production_execution.contract.world_preparation_source.exact"}
            identity = {key: "frozen-" + key for key in ("model_provider", "model_id", "reasoning_effort", "runtime_class", "model_backend_id", "cost_accounting_basis")}
            identity["account"] = {"entitlement": {"authorization_ref": "original", "account": "exact"}}
            pack = {key: key for key in ("prompt_bundle_hash", "route_policy_hash", "context_policy_hash", "skill_bundle_hash", "tool_policy_hash")}
            target = {**identity, "pack_snapshot": pack, "planning_capacity": {"external_intents_at_source": 0 if is_world else 2, "context_revalidation": proof}}
            for op, status, definition, payload, cause in (("source", "FAILED_FINAL", "story_planning.generate", source, None),
                    ("child", "ADMITTED", "story_planning.generate", child, "source"),
                    ("registration", "SUCCEEDED", "story_planning.runtime_continuation.register", {}, None)):
                insert("authority_operation", operation_id=op, status=status, definition_name=definition,
                       actor_id="owner", project_id="project", workspace_id="workspace", command_payload={"payload": payload}, causation_operation_id=cause)
            for key, successor, runtime in (("previous", "source", identity), ("runtime", "child", target)):
                insert("authority_story_planning_runtime_continuation", continuation_id=key, successor_operation_id=successor,
                       source_operation_id="source", registered_by_operation_id="registration", chain_depth=2,
                       project_id="project", workspace_id="workspace", book_id="book", source_command=source,
                       successor_command=child, target_runtime=runtime, decision_evidence={"formation_run_id": "formation"})
            insert("authority_story_planning_generation", operation_id="source", project_id="project", workspace_id="workspace",
                   book_id="book", generator_operation_name="chapter_plan.generate", logical_key="chapter:5", planning_scope="CHAPTER",
                   input_snapshot=[], input_snapshot_hash="snapshot", repair_number=0)
            generation = connection.execute("SELECT to_jsonb(g) FROM authority_story_planning_generation g").fetchone()[0]
            insert("authority_attempt", operation_id="source", attempt_id="attempt", attempt_number=1,
                   status="FAILED_FINAL" if is_world else "FAILED_RETRYABLE", result=failure)
            insert("authority_attempt_capability_pack_snapshot", operation_id="source", attempt_id="attempt", snapshot_payload=pack)
            insert("authority_story_formation_run", formation_run_id="formation", project_id="project", workspace_id="workspace",
                   book_id="book", frozen_stage_inputs={"generation_policy": {"auto_authorization": {"authorized_by_principal_id": "owner"}}})
            context = {"project_id": "project", "workspace_id": "workspace", "book_id": "book", "planning_scope": "CHAPTER",
                       "knowledge_access_policy": {"craft_candidate_review_version": "explicit-allowlist-craft-review.v1", "usage_scope": "EXPERIMENTAL_VALIDATION", "mode": "ALLOW_ONLY"},
                       "narrative_intelligence": {"selected": ["method"]},
                       **({"world_method_scope_projection_version": "world-method-scope-projection.v1"} if is_world else {"planning_chapter_method_scope_projection_version": "chapter-method-scope-projection.v1"})}
            if legacy:
                context.pop("world_method_scope_projection_version" if is_world else "planning_chapter_method_scope_projection_version")
                proof["contract_version"] = "world-method-scope-projection.v1" if is_world else "chapter-method-scope-projection.v1"
                connection.execute("UPDATE authority_story_planning_runtime_continuation SET target_runtime=%s WHERE continuation_id='runtime'", [Jsonb(target)])
            def asset(key, content, asset_type):
                insert("authority_asset", asset_id=key, asset_type=asset_type, project_id="project")
                insert("authority_asset_version", asset_version_id=key, asset_id=key, content_hash=key + "-hash", content=content)
            asset("context", context, "context_bundle")
            insert("authority_operation_output_asset", operation_id="source", output_key="planning.context_bundle", asset_version_id="context", content_hash="context-hash")
            if is_world:
                asset("world-source", {"contract": {"request": source["world_preparation_request"], "fact_mutation_allowed": False,
                      "reality": {"project_id": "project", "book_id": "book"}}}, "world_preparation_source")
                insert("authority_operation_output_asset", operation_id="source", output_key=proof["world_source_output_key"], asset_version_id="world-source", content_hash="world-source-hash")
            else:
                refs = {key: {"asset_version_id": key, "content_hash": key + "-hash"} for key in ("source", "generation", "evaluation")}
                action = {"project_id": "project", "book_id": "book", "actor_id": "owner", "fact_mutation_allowed": False, "world_plan": {"disposition": "ELIGIBLE"}, **refs}
                asset("action", {"contract": action}, "narrative_governance_action")
                asset("materialization", {"contract": {"tool_permissions": {"default": "DENY", "allowed": ["model.provider.invoke"]}}}, "capability_materialization_manifest")
                target["planning_capacity"]["retained_world_action"] = {"source_operation_id": "source", "world_action": {"asset_version_id": "action", "content_hash": "action-hash", **refs}}
                connection.execute("UPDATE authority_story_planning_runtime_continuation SET target_runtime=%s WHERE continuation_id='runtime'", [Jsonb(target)])
                for key, stage in (("generation", "world_candidates.generate"), ("evaluation", "world_candidates.evaluate")):
                    output = {"text": key}
                    evidence = {"result": output}
                    asset(key, {"contract": {"source": refs["source"], "output": output, "evidence": {"external_receipt_ref": key}}}, "world_result")
                    insert("authority_external_effect", operation_id="source", external_effect_id=key, project_id="project", request_hash="request-hash", effect_type="model.invoke", status="SUCCEEDED",
                           request_payload={"stage": stage, "_production_execution": {"capability_runtime": {"materialization_asset_version_id": "materialization", "materialization_content_hash": "materialization-hash"}}})
                    insert("authority_external_effect_dispatch", external_effect_id=key, dispatch_id=key, status="SUCCEEDED", evidence=evidence)
                    insert("authority_external_receipt", dispatch_id=key, status="VERIFIED", payload={"evidence": evidence})
            function = (("authority_unsent_world_context_continuation_permitted" if is_world else "authority_prepared_chapter_context_continuation_permitted") if legacy else ("authority_unsent_world_exact_context_continuation_permitted" if is_world else "authority_chapter_prior_audit_continuation_permitted"))
            def accepted(value=generation):
                return connection.execute(sql.SQL("SELECT {}(%s,%s,%s)").format(sql.Identifier(function)), ["runtime", "child", Jsonb(value)]).fetchone()[0]
            assert accepted() is True
            assert accepted() is True
            for key in ("project_id", "workspace_id", "book_id", "input_snapshot_hash", "generator_operation_name"):
                assert not accepted({**generation, key: "foreign"})
                assert not accepted({**generation, key: None})
            mutations = ["UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='child'",
                         "UPDATE authority_asset_version SET content_hash='changed' WHERE asset_version_id='context'",
                         "DELETE FROM authority_attempt_capability_pack_snapshot",
                         "INSERT INTO authority_lease_acquisition(attempt_id,status) VALUES('attempt','HELD')",
                         "INSERT INTO authority_worker_cancel_signal(operation_id) VALUES('source')",
                         "INSERT INTO authority_story_creation_cancellation(formation_run_id) VALUES('formation')",
                         "UPDATE authority_story_planning_runtime_continuation SET target_runtime='{}' WHERE continuation_id='previous'",
                         "UPDATE authority_attempt SET attempt_number=2,status='EXECUTING'",
                         "INSERT INTO authority_book_production(project_id,book_id,state) VALUES('project','book','CANCELLED')",
                         "INSERT INTO authority_budget_reservation(operation_id,status) VALUES('source','HELD_UNKNOWN')"]
            mutations += (["INSERT INTO authority_external_effect(operation_id,status) VALUES('source','UNKNOWN')",
                           "UPDATE authority_asset_version SET content_hash='changed' WHERE asset_version_id='world-source'"] if is_world else
                          ["UPDATE authority_external_effect SET status='UNKNOWN' WHERE external_effect_id='generation'",
                           "UPDATE authority_external_receipt SET status='REJECTED'",
                           "DELETE FROM authority_external_receipt",
                           "UPDATE authority_external_receipt SET payload='{}'",
                           "INSERT INTO authority_generation_isolation(external_effect_id,operation_id,project_id,workspace_id,request_hash,proof) VALUES('generation','source','project','workspace','request-hash','{\"contract_version\":\"pure-generation-isolation.v1\"}')"])
            for mutation in mutations:
                connection.execute("SAVEPOINT denied_boundary")
                connection.execute(mutation)
                assert not accepted(), mutation
                connection.execute("ROLLBACK TO SAVEPOINT denied_boundary")
                connection.execute("RELEASE SAVEPOINT denied_boundary")
            assert accepted() is True
        finally:
            connection.rollback()
