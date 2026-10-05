from dataclasses import replace
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
from tests.integration.authority_postgres_support import transaction
from tests.integration.test_provider_routing_postgres import (
    scope as imported_scope,
    feedback_effect,
    write_asset,
)
from tests.unit.test_cost_aware_routing import NOW, samples


@pytest.fixture
def scope():
    return imported_scope.__wrapped__()


@pytest.mark.parametrize("log_order", ["failure_first", "failure_last", "retried"])
@pytest.mark.parametrize(
    "terminal,real_flag",
    [("SUCCEEDED", True), ("FAILED_FINAL", True), ("SUCCEEDED", False)],
)
def test_every_native_fidelity_attempt_and_failed_context_retains_its_denominator(
    scope, terminal, real_flag, log_order
):
    # Synthetic PostgreSQL intent/receipt projection only: OFFLINE, not real qualification.
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
            scope, {"stage": stage, "input": {"context_compression_task": frozen_task}}
        )
        execution = {
            "execution_request": {
                "operation_id": scope[1],
                "project_id": scope[0],
                "external_effect_id": identity,
            }
        }
        evidence = {
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
    observations = [
        replace(
            row,
            sample_identity=str(index),
            domain_gate_accepted=outcomes[identity]["accepted"],
        )
        for index, (row, identity) in enumerate(zip(samples(n=3), ids, strict=True))
    ]
    snapshot = benchmark_snapshot(
        observations, now=NOW, policy=task_policy("context_fidelity")
    )
    assert snapshot["domain_gate_sample_count"] == 3
    assert snapshot["predicted_quality"] <= 1 / 3
