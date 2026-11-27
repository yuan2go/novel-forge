from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    acquire_effect_dispatch,
    plan_external_effect,
    prepare_effect_dispatch,
    submit_effect_dispatch_result,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


def _context() -> EffectCommandContext:
    ensure_migrated()
    operation_id, project_id = identifier("effect-contract"), identifier("effect-project")
    with transaction() as connection, connection.cursor() as cursor:
        definition = identifier("effect-contract-definition")
        insert_definition(cursor, definition)
        insert_operation(
            cursor, operation_id=operation_id, definition_name=definition,
            project_id=project_id, status="EXECUTING",
        )
    return EffectCommandContext(operation_id, project_id, "contract-test", identifier("trace"), identifier("correlation"))


def _plan(context: EffectCommandContext, key: str, payload: dict):
    return plan_external_effect(
        DATABASE_URL, context, effect_type="model.invoke", provider="contract-route",
        capability="model.draft", stable_idempotency_key=key, request_payload=payload,
        max_attempts=2, reversible=False,
    )


def test_durable_intent_replay_preserves_one_identity_and_rejects_request_drift():
    context = _context()
    key = identifier("effect-intent")
    first = _plan(context, key, {"input_hash": "first"})
    replay = _plan(context, key, {"input_hash": "first"})
    assert first["external_effect_id"] == replay["external_effect_id"]
    with pytest.raises(KernelError):
        _plan(context, key, {"input_hash": "changed"})
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM authority_external_effect WHERE operation_id=%s",
            [context.operation_id],
        )
        assert cursor.fetchone()[0] == 1


def test_unknown_dispatch_result_requires_reconciliation_without_new_generation():
    context = _context()
    effect = _plan(context, identifier("unknown-intent"), {"input_hash": "frozen"})
    effect_id = effect["external_effect_id"]
    dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect_id)
    lease = acquire_effect_dispatch(
        DATABASE_URL, context, dispatch_id=dispatch["dispatch_id"],
        worker_id="contract-worker", lease_seconds=30,
    )
    submit_effect_dispatch_result(
        DATABASE_URL, context, dispatch_id=dispatch["dispatch_id"],
        worker_id="contract-worker", fencing_token=int(lease["fencing_token"]),
        outcome="unknown", evidence={"reason": "transport outcome unavailable"},
    )
    with pytest.raises(KernelError):
        prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect_id)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*), MAX(generation) FROM authority_external_effect_dispatch WHERE external_effect_id=%s",
            [effect_id],
        )
        assert cursor.fetchone() == (1, 1)


@pytest.mark.parametrize("status", ["EXECUTING", "CANCELLATION_REQUESTED"])
def test_dispatch_receipt_retains_database_owner_with_valid_fence(status):
    from dataclasses import replace

    context = _context()
    effect = _plan(context, identifier("receipt-owner"), {"input_hash": "frozen"})
    dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect["external_effect_id"])
    lease = acquire_effect_dispatch(DATABASE_URL, context, dispatch_id=dispatch["dispatch_id"],
        worker_id="owner-worker", lease_seconds=30)
    other_id = identifier("wrong-owner")
    with transaction() as connection, connection.cursor() as cursor:
        definition = identifier("other-owner-definition")
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=other_id, definition_name=definition,
            project_id=context.project_id, status=status)
    args = dict(dispatch_id=dispatch["dispatch_id"], worker_id="owner-worker",
        fencing_token=int(lease["fencing_token"]), outcome="success", evidence={"result": "retained"})
    with pytest.raises(KernelError, match="EFFECT_OPERATION_MISMATCH"):
        submit_effect_dispatch_result(DATABASE_URL, replace(context, operation_id=other_id), **args)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status FROM authority_external_effect WHERE external_effect_id=%s", [effect["external_effect_id"]])
        assert cursor.fetchone() == ("DISPATCHING",)
        cursor.execute("SELECT count(*) FROM authority_external_receipt WHERE dispatch_id=%s", [dispatch["dispatch_id"]])
        assert cursor.fetchone() == (0,)
    submit_effect_dispatch_result(DATABASE_URL, context, **args)
