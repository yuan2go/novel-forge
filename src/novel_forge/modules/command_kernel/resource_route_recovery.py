from __future__ import annotations

from typing import Any

from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .errors import KernelError


def cancel_unreserved_paid_intent(database_url: str, request: Any) -> bool:
    from .external_effect_runtime import EffectCommandContext, _record
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        effect = repository.get_for_update(request.external_effect_id)
        if effect["project_id"] != request.project_id or effect["operation_id"] != request.operation_id:
            raise KernelError("RESOURCE_ROUTE_SCOPE_MISMATCH", request.external_effect_id)
        uow.cursor.execute("SELECT 1 FROM authority_effect_resource_denial WHERE external_effect_id=%s", [request.external_effect_id])
        if uow.cursor.fetchone():
            return True
        uow.cursor.execute("SELECT 1 FROM authority_budget_reservation WHERE external_effect_id=%s", [request.external_effect_id])
        if uow.cursor.fetchone() or effect["status"] != "READY":
            return False
        uow.cursor.execute("SELECT 1 FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [request.external_effect_id])
        if uow.cursor.fetchone():
            return False
        if not repository.cancel_proven_never_sent(effect, reason="PAID_WORK_BUDGET_EXHAUSTED"):
            return False
        uow.cursor.execute("SELECT actor_id,trace_id,correlation_id FROM authority_operation WHERE operation_id=%s", [request.operation_id])
        actor, trace, correlation = uow.cursor.fetchone()
        uow.cursor.execute("""INSERT INTO authority_effect_resource_denial(external_effect_id,project_id,operation_id,reason)
            VALUES (%s,%s,%s,'PAID_WORK_BUDGET_EXHAUSTED')""", [request.external_effect_id, request.project_id, request.operation_id])
        _record(repository, EffectCommandContext(request.operation_id, request.project_id, actor, trace, correlation),
            request.external_effect_id, "external_effect.resource_route_denied", {"version": "unsent-resource-route-successor.v1",
                "reason": "PAID_WORK_BUDGET_EXHAUSTED", "request_sent": False, "reservation_created": False})
        uow.commit()
        return True


def next_resource_effect_key(database_url: str, *, project_id: str, operation_id: str, stable_key: str) -> str:
    with AuthorityUnitOfWork(database_url) as uow:
        for _ in range(4):
            uow.cursor.execute("""SELECT effect.external_effect_id,effect.status,denial.reason
                FROM authority_external_effect effect LEFT JOIN authority_effect_resource_denial denial USING(external_effect_id)
                WHERE effect.project_id=%s AND effect.operation_id=%s AND effect.effect_type='model.invoke' AND effect.stable_idempotency_key=%s""",
                [project_id, operation_id, stable_key])
            row = uow.cursor.fetchone()
            if not row or row[1] != "CANCELLED" or row[2] != "PAID_WORK_BUDGET_EXHAUSTED":
                return stable_key
            stable_key += ":resource-successor:" + row[0]
    raise KernelError("RESOURCE_ROUTE_REPLAN_EXHAUSTED", operation_id)
