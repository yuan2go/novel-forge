from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    read_completed_operation_success,
    read_succeeded_external_effect,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def completed_reader_result(database_url: str, *, effect_id: str, project_id: str):
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT owner.operation_id,owner.actor_id,owner.trace_id,owner.correlation_id,owner.status
            FROM authority_external_effect effect JOIN authority_operation owner USING(operation_id)
            WHERE effect.external_effect_id=%s AND effect.project_id=%s AND owner.project_id=%s
              AND owner.definition_name='reader_outcome.evaluate' AND owner.definition_version='1.4.0'""",
            [effect_id, project_id, project_id],
        )
        row = uow.cursor.fetchone()
    if not row:
        return False, None
    context = EffectCommandContext(
        operation_id=row[0],
        project_id=project_id,
        actor_id=row[1],
        trace_id=row[2],
        correlation_id=row[3],
    )
    reader = (
        read_completed_operation_success
        if row[4] == "SUCCEEDED"
        else read_succeeded_external_effect
    )
    receipt = reader(database_url, context, effect_id=effect_id)
    if receipt is None:
        return True, None
    if receipt["budget_reservation_status"] != "SETTLED":
        raise KernelError(
            "READER_RESULT_ACCOUNTING_UNSETTLED",
            "Retain the exact settled original Reader receipt",
        )
    from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult

    return True, ModelProviderResult.from_evidence(receipt["provider_evidence"])
