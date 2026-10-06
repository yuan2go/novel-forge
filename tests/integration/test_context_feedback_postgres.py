from dataclasses import asdict, replace
from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from novel_forge.modules.command_kernel.external_effect_runtime import _hash

import pytest

from novel_forge.modules.authority_handler_runtime.context_feedback import (
    context_gate_outcomes,
)
from novel_forge.modules.production_execution.cost_routing import (
    benchmark_snapshot,
    task_policy,
)
from tests.integration.authority_postgres_support import DATABASE_URL, identifier, insert_definition, insert_operation, transaction
from tests.integration.test_provider_routing_postgres import (
    scope as imported_scope,
    feedback_effect,
    write_asset,
)
from tests.unit.test_cost_aware_routing import candidate, task as routing_task
from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter



@pytest.fixture
def scope():
    return imported_scope.__wrapped__()


def _assert_native_feedback_chain(
    scope, terminal, real_flag, log_order
):
    # WHY: synthetic real-call flags exercise native projection; no Provider is invoked.
    model = candidate()
    task = {
        "source_binding": {
            "asset_version_id": "source:v1",
            "content_hash": "sha256:source",
        },
        "units": [{"unit_id": "u0"}, {"unit_id": "u1"}],
        "required_unit_ids": [],
    }

    def receipt(stage, frozen_task, output):
        identity = feedback_effect(
            scope, {"stage": stage, "input": {"context_compression_task": frozen_task},
                "_production_execution": {"capability_runtime": {"routing_decision": {
                    "status": "SELECTED", "selected": {"candidate": asdict(model)},
                    "task": {"producer_contract_hash": "sha256:context-native-producer", "input_hash": _hash(frozen_task), "chain_id": "context-feedback-chain"},
                    "policy": {"risk": "HIGH"},
                }}}}
        )
        execution = {
            "execution_request": {
                "operation_id": scope[1],
                "project_id": scope[0],
                "external_effect_id": identity,
            }
        }
        execution.update({"execution_result": {"outcome": "SUCCEEDED"},
            "route_snapshot": {"reasoning_effort": model.reasoning},
            "process_evidence": {"served_model_identity_hash": "sha256:synthetic-cohort"}})
        evidence = {"provider_id": model.provider, "model_id": model.model,
            "real_model_call": real_flag,
            "result": output,
            "production_execution": execution,
        }
        stale = {**evidence, "result": {"failed": True}}

        def stale_log():
            write_asset(
                scope,
                "model_call_log",
                {"operation_id": scope[1], "stage": stage, "provider_evidence": stale},
            )

        if log_order == "failure_first":
            stale_log()
        write_asset(
            scope,
            "model_call_log",
            {"operation_id": scope[1], "stage": stage, "provider_evidence": evidence},
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO authority_external_effect_dispatch
                (dispatch_id,external_effect_id,generation,status,payload_hash,evidence)
                VALUES(%s,%s,2,'SUCCEEDED',%s,%s)""",
                [identity, identity, _hash(evidence), Jsonb(evidence)],
            )
            cursor.execute(
                """INSERT INTO authority_external_receipt(provider,receipt_id,dispatch_id,payload_hash,payload,status)
                VALUES('OFFLINE',%s,%s,%s,%s,'VERIFIED')""",
                [identity, identity, _hash(evidence), Jsonb({"evidence": evidence})],
            )
        if log_order in {"failure_last", "retried"}:
            stale_log()
        if log_order == "retried":
            failed_id = identity + ":failed"
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO authority_external_effect_dispatch
                    (dispatch_id,external_effect_id,generation,status,payload_hash,evidence)
                    VALUES(%s,%s,1,'FAILED_RETRYABLE',%s,%s)""",
                    [failed_id, identity, _hash(stale), Jsonb(stale)],
                )
                cursor.execute(
                    """INSERT INTO authority_external_receipt(provider,receipt_id,dispatch_id,payload_hash,payload,status)
                    VALUES('OFFLINE',%s,%s,%s,%s,'VERIFIED')""",
                    [failed_id, failed_id, _hash(stale), Jsonb({"evidence": stale})],
                )
        return identity, execution

    comp, c_execution = receipt("context_compress", task, {"selected_unit_ids": ["u0"]})
    fidelity = []
    assessments = []
    for selected in [["u0"], ["u0", "u1"]]:
        passed = terminal == "SUCCEEDED" and "u1" in selected
        verdict = {
            "supported": True,
            "coverage_complete": passed,
            "missing_unit_ids": [] if passed else ["u1"],
            "distorted_unit_ids": [],
        }
        fid, f_execution = receipt(
            "context_fidelity", {**task, "selected_unit_ids": selected}, verdict
        )
        fidelity.append(fid)
        assessments.append(
            {
                "task": task,
                "selected_unit_ids": ["u0"],
                "fidelity_selected_unit_ids": selected,
                "fidelity": verdict,
                "compressor_evidence": c_execution,
                "fidelity_evidence": f_execution,
            }
        )
    if terminal == "SUCCEEDED":
        write_asset(
            scope,
            "context_bundle",
            {
                "task_context_receipt": {
                    "compression_trace": [
                        {
                            "source_asset_version_id": "source:v1",
                            "source_content_hash": "sha256:source",
                            "routing_assessments": assessments,
                        }
                    ]
                }
            },
        )
    ids = [comp, *fidelity]
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE authority_operation SET status=%s WHERE operation_id=%s",
            [terminal, scope[1]],
        )
        outcomes = context_gate_outcomes(cursor, project_id=scope[0], effect_ids=ids)
    if not real_flag:
        assert outcomes == {}
        return
    assert set(outcomes) == set(ids)
    assert outcomes[comp]["accepted"] is False
    assert outcomes[ids[1]]["accepted"] is False
    assert outcomes[ids[2]]["accepted"] == (
        terminal == "SUCCEEDED" and log_order != "retried"
    )
    assert all(
        len(row["native_dispatch_history"]) == (2 if log_order == "retried" else 1)
        for row in outcomes.values()
    )
    registry = PostgresRoutingRegistry(DATABASE_URL,
        outcome_projection=context_gate_outcomes)
    for stage, count in (("context_compress", 1), ("context_fidelity", 2)):
        observations = registry.observations(project_id=scope[0], task_type=stage,
            candidate=model, producer_contract_hash="sha256:context-native-producer")
        assert len(observations) == count
        snapshot = benchmark_snapshot(observations, now=datetime.now(timezone.utc), policy=task_policy(stage))
        expected_samples = count
        if stage == "context_fidelity" and terminal == "SUCCEEDED" and log_order != "retried":
            expected_samples = 1
        assert snapshot["domain_gate_sample_count"] == expected_samples, snapshot
        assert snapshot["predicted_quality"] <= 1 / 2
        decision = CostAwareRouter().explain(
            replace(routing_task(), task_type=stage), [model],
            {model.candidate_id: observations}, now=datetime.now(timezone.utc),
        ).to_dict()
        assert decision["status"] == "BLOCKED"
        assert decision["policy"]["quality_metric"] == "DOMAIN_GATE_ACCEPTANCE"
    return ids


@pytest.mark.parametrize("log_order", ["failure_first", "failure_last", "retried"])
@pytest.mark.parametrize("terminal,real_flag", [("SUCCEEDED", True), ("FAILED_FINAL", True), ("SUCCEEDED", False)])
def test_every_native_fidelity_attempt_and_failed_context_retains_its_denominator(scope, terminal, real_flag, log_order):
    _assert_native_feedback_chain(scope, terminal, real_flag, log_order)


@pytest.mark.parametrize("effect_status", ["SUCCEEDED", "UNKNOWN"])
def test_unknown_generation_cannot_reuse_old_positive_gate(scope, effect_status):
    ids = _assert_native_feedback_chain(scope, "SUCCEEDED", True, "failure_first")
    identity = ids[-1]
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE authority_external_effect SET status=%s WHERE external_effect_id=%s", [effect_status, identity])
        cursor.execute("INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,status,payload_hash,evidence) VALUES(%s,%s,3,'UNKNOWN','pending','{}')", [identity + ":unknown", identity])
        outcomes = context_gate_outcomes(cursor, project_id=scope[0], effect_ids=ids)
    assert outcomes.get(identity, {}).get("accepted") is not True
    registry = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=context_gate_outcomes)
    observations = registry.observations(project_id=scope[0], task_type="context_fidelity", candidate=candidate(), producer_contract_hash="sha256:context-native-producer")
    assert all(row.domain_gate_accepted is not True for row in observations)
    if effect_status == "UNKNOWN":
        from tests.unit.test_cost_aware_routing import NOW, samples

        history = registry.history(project_id=scope[0], operation_id=scope[1],
                                   task_type="context_fidelity", chain_id="context-feedback-chain")
        assert any(row["failure_class"] == "UNKNOWN_EXTERNAL_OUTCOME" for row in history)
        qualified = [replace(row, sample_identity=row.evidence_ref)
                     for row in samples(n=150, domain_gate_accepted=True)]
        decision = CostAwareRouter().explain(
            replace(routing_task(), task_type="context_fidelity", history=history),
            [candidate()], {"flash": qualified}, now=NOW,
        ).to_dict()
        assert decision["status"] == "BLOCKED"
    # WHY: completing native reconciliation appends a verified generation; the UNKNOWN remains history.
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE authority_external_effect SET status='SUCCEEDED' WHERE external_effect_id=%s", [identity])
        cursor.execute("""INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,status,payload_hash,evidence)
            SELECT %s,external_effect_id,4,'SUCCEEDED',payload_hash,evidence FROM authority_external_effect_dispatch WHERE external_effect_id=%s AND generation=2""", [identity + ":reconciled", identity])
        cursor.execute("""INSERT INTO authority_external_receipt(provider,receipt_id,dispatch_id,payload_hash,payload,status)
            SELECT 'OFFLINE',%s,%s,payload_hash,payload,'VERIFIED' FROM authority_external_receipt WHERE dispatch_id=%s""", [identity + ":reconciled", identity + ":reconciled", identity])
        outcomes = context_gate_outcomes(cursor, project_id=scope[0], effect_ids=ids)
        assert outcomes[identity]["accepted"] is True
        cursor.execute("SELECT status FROM authority_external_effect_dispatch WHERE dispatch_id=%s", [identity + ":unknown"])
        assert cursor.fetchone()[0] == "UNKNOWN"


@pytest.mark.parametrize("drift", ["dispatch_hash", "receipt_hash", "project", "operation", "effect", "source_version", "source_hash", "selected_units"])
def test_native_feedback_identity_drift_cannot_qualify_context(scope, drift):
    ids = _assert_native_feedback_chain(scope, "SUCCEEDED", True, "failure_first")
    identity = ids[-1]
    recovery_operation = identifier("feedback-recovery")
    definition = identifier("feedback-recovery-definition")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=recovery_operation, definition_name=definition,
                         project_id=scope[0], status="EXECUTING")
    with transaction() as connection, connection.cursor() as cursor:
        if drift == "dispatch_hash":
            cursor.execute("UPDATE authority_external_effect_dispatch SET payload_hash='sha256:drift' WHERE external_effect_id=%s", [identity])
        elif drift == "receipt_hash":
            cursor.execute("UPDATE authority_external_receipt SET payload_hash='sha256:drift' WHERE dispatch_id=%s", [identity])
        elif drift in {"project", "operation", "effect"}:
            cursor.execute("SELECT evidence FROM authority_external_effect_dispatch WHERE dispatch_id=%s", [identity])
            evidence = cursor.fetchone()[0]
            evidence["production_execution"]["execution_request"][drift + "_id" if drift != "effect" else "external_effect_id"] = "other-identity"
            cursor.execute("UPDATE authority_external_effect_dispatch SET evidence=%s,payload_hash=%s WHERE dispatch_id=%s", [Jsonb(evidence), _hash(evidence), identity])
            cursor.execute("UPDATE authority_external_receipt SET payload=%s,payload_hash=%s WHERE dispatch_id=%s", [Jsonb({"evidence": evidence}), _hash(evidence), identity])
            write_asset((scope[0], recovery_operation), "model_call_log", {"operation_id": scope[1], "stage": "context_fidelity", "provider_evidence": evidence})
        else:
            cursor.execute("SELECT request_payload FROM authority_external_effect WHERE external_effect_id=%s", [identity])
            payload = cursor.fetchone()[0]
            task = payload["input"]["context_compression_task"]
            if drift == "selected_units":
                task["selected_unit_ids"] = ["u0"]
            else:
                task["source_binding"]["asset_version_id" if drift == "source_version" else "content_hash"] = "other-source"
            cursor.execute("UPDATE authority_external_effect SET request_payload=%s,request_hash=%s WHERE external_effect_id=%s", [Jsonb(payload), _hash(payload), identity])
        outcomes = context_gate_outcomes(cursor, project_id=scope[0], effect_ids=ids)
    assert outcomes.get(identity, {}).get("accepted") is not True
    registry = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=context_gate_outcomes)
    observations = registry.observations(project_id=scope[0], task_type="context_fidelity", candidate=candidate(), producer_contract_hash="sha256:context-native-producer")
    assert all(row.domain_gate_accepted is not True for row in observations)
    assert registry.observations(project_id=scope[0], task_type="context_fidelity", candidate=candidate(), producer_contract_hash="sha256:other-producer") == []
    assert registry.observations(project_id=scope[0], task_type="context_fidelity", candidate=candidate(model_revision="other-revision")) == []
