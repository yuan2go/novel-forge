
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.edition_joint_evidence_support import require_reselection_receipts


def require_joint_actor_reselection(database_url, *, project_id, book_id, book_run_id):
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT e.external_effect_id,e.operation_id,e.request_payload->>'stage',e.status,
            o.status,o.causation_operation_id,g.repair_of_operation_id,g.repair_result_asset_version_id,
            count(DISTINCT d.dispatch_id),count(DISTINCT receipt.external_receipt_id),
            count(DISTINCT budget.reservation_id),bool_and(budget.status='SETTLED'),sum(DISTINCT budget.estimated_tokens)
            FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
            JOIN authority_story_planning_generation g USING(operation_id)
            JOIN authority_external_effect_dispatch d USING(external_effect_id)
            JOIN authority_external_receipt receipt USING(dispatch_id)
            JOIN authority_budget_reservation budget USING(external_effect_id)
            WHERE e.project_id=%s AND e.request_payload->>'stage' LIKE 'world_candidates.actor_%%'
            GROUP BY e.external_effect_id,o.operation_id,g.operation_id,g.repair_of_operation_id,g.repair_result_asset_version_id ORDER BY e.created_at""", [project_id])
        columns = ["effect_id", "operation_id", "stage", "effect_status", "operation_status", "causation_operation_id",
                   "repair_of_operation_id", "repair_source_id", "dispatch_count", "receipt_count", "reservation_count", "budget_settled", "estimated_tokens"]
        effects = [dict(zip(columns, row, strict=True)) for row in uow.cursor.fetchall()]
        for effect in effects:
            effect["estimated_tokens"] = int(effect["estimated_tokens"])
        assert len(effects) == 8
        parents = {row["operation_id"] for row in effects if row["repair_of_operation_id"] is None}
        children = {row["operation_id"] for row in effects if row["repair_of_operation_id"] is not None}
        assert len(parents) == len(children) == 2 and parents.isdisjoint(children)
        for operation in parents | children:
            owned = [row for row in effects if row["operation_id"] == operation]
            assert {row["stage"] for row in owned} == {"world_candidates.actor_0", "world_candidates.actor_1"}
            assert len(owned) == 2
            for row in owned:
                assert row["effect_status"] == "SUCCEEDED" and row["budget_settled"]
                assert row["dispatch_count"] == row["receipt_count"] == row["reservation_count"] == 1
                if operation in children:
                    assert row["operation_status"] == "SUCCEEDED" and row["repair_source_id"]
                    assert row["causation_operation_id"] == row["repair_of_operation_id"] and row["repair_of_operation_id"] in parents
                else:
                    assert row["operation_status"] == "FAILED_FINAL" and row["causation_operation_id"] is None
        uow.cursor.execute("""SELECT plan.content->'constraint_envelope'->'world_preparation'->'action'->'generation'
            FROM authority_book_chapter_acceptance accepted JOIN authority_book_chapter_request request USING(chapter_request_id)
            JOIN authority_asset_version plan ON plan.asset_version_id=request.chapter_plan_version
            WHERE accepted.project_id=%s AND accepted.book_run_id=%s ORDER BY accepted.chapter_number""", [project_id, book_run_id])
        accepted_owners = []
        for (reference,) in uow.cursor.fetchall():
            document = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=reference["asset_version_id"])
            assert document.content_hash == reference["content_hash"]
            accepted_owners.append(document.content["contract"]["evidence"]["operation_id"])
        assert len(accepted_owners) == 2 and set(accepted_owners) == children
        uow.cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content->'narrative_intelligence'
            FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s AND v.content ? 'narrative_intelligence' ORDER BY v.created_at""", [project_id])
        contexts = [dict(zip(("asset_version_id", "content_hash", "selection"), row, strict=True)) for row in uow.cursor.fetchall()]
    receipts = require_reselection_receipts(database_url, book={"project_id": project_id, "book_id": book_id}, contexts=contexts)
    assert {row["source_operation_id"] for row in receipts} == parents
    assert {row["repair_operation_id"] for row in receipts} == children
    assert len(receipts) == 2
    return {"contract_version": "scripted-joint-actor-reselection-proof.v1", "effects": effects,
            "accepted_planning_operations": accepted_owners, "reselection_receipts": receipts,
            "estimated_reserved_tokens_total": sum(row["estimated_tokens"] for row in effects),
            "cost_basis": "SCRIPTED_FIXTURE_RECEIPT_NO_REAL_PROVIDER_USAGE", "real_authorization_pool_used": False}
