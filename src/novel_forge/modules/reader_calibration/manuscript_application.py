from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.generation_policy import reference_prose_generation
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .manuscript_blind import (
    MANUSCRIPT_PROTOCOL, build_unassigned_manuscript_pack, content_digest,
    extract_manuscript_chapter, validate_manuscript_human_response, normalize_manuscript_model_diagnosis,
    require_manuscript_reading_input,
)


def _load_chapter(authority, project_id: str, book_id: str, source: dict[str, Any]) -> dict[str, Any]:
    with AuthorityUnitOfWork(authority.database_url) as uow:
        doc = uow.repositories.asset_documents.require(
            project_id=project_id, asset_version_id=source["parent_asset_version_id"],
        )
        if doc.content_hash != source["parent_content_hash"]:
            raise KernelError("MANUSCRIPT_SOURCE_HASH_DRIFT", "Reading must bind the exact saved prose parent")
        uow.cursor.execute("""SELECT o.operation_id,o.definition_name,o.status,o.command_payload
            FROM authority_operation_output_asset binding JOIN authority_operation o USING(operation_id)
            WHERE binding.asset_version_id=%s AND o.project_id=%s""", [doc.asset_version_id, project_id])
        producer = uow.cursor.fetchone()
        retained = None
        if doc.asset_type == "retained_working_prose":
            retained = uow.cursor.execute("SELECT c.proof FROM authority_book_retained_working_continuation c JOIN authority_book_production b USING(book_run_id) WHERE c.working_asset_version_id=%s AND c.working_content_hash=%s AND b.project_id=%s AND b.book_id=%s AND c.created_by_operation_id=%s", [doc.asset_version_id, doc.content_hash, project_id, book_id, producer[0] if producer else None]).fetchone()
            if (not retained or producer[1] != "book.authority.mutate" or producer[3].get("payload", {}).get("action") != "retained_working_continue"
                    or retained[0] != doc.content.get("retained_working_provenance")):
                raise KernelError("MANUSCRIPT_RETAINED_SOURCE_INVALID", "Retained reading requires its exact native working-use decision")
        if not producer or producer[2] != "SUCCEEDED" or (not retained and producer[3].get("book_id") != book_id):
            raise KernelError("MANUSCRIPT_PRODUCER_SCOPE_INVALID", "Reading sources must have a completed native producer in the declared Book")
        if doc.asset_type == "execution_evidence" and not reference_prose_generation(uow.cursor, producer[0], project_id):
            raise KernelError("MANUSCRIPT_REFERENCE_PROOF_REQUIRED", "Reference body requires its sealed controlled-generation producer")
        if doc.asset_type == "draft_chapter" and not producer[1].startswith("chapter."):
            raise KernelError("MANUSCRIPT_PRODUCER_SCOPE_INVALID", "Draft source requires Chapter ownership")
        chapter = extract_manuscript_chapter(asset_type=doc.asset_type, content=doc.content,
            chapter_number=source["chapter_number"], selector=source["selector"])
    return {**chapter, "book_id": book_id, "parent_asset_version_id": doc.asset_version_id,
        "parent_content_hash": doc.content_hash, "selector": source["selector"],
        "producer_operation_id": producer[0], "source_kind": doc.asset_type}


def export_manuscript_pack(authority, *, project_id: str, workspace_id: str, pack_key: str,
                           blind_secret: str, manuscripts: list[dict[str, Any]], principal) -> dict[str, Any]:
    principal.require("book.authority.execute", project_id)
    if not isinstance(manuscripts, list) or len(manuscripts) < 2:
        raise ValueError("MANUSCRIPT_COMPARISON_SCOPE_INVALID")
    book_ids = [row["book_id"] for row in manuscripts]
    if any(not isinstance(book_id, str) or not book_id for book_id in book_ids) or len(set(book_ids)) != len(book_ids):
        raise ValueError("INDEPENDENT_MANUSCRIPT_BOOKS_REQUIRED")
    loaded = [{"manuscript_key": row["manuscript_key"], "chapters": [
        _load_chapter(authority, project_id, row["book_id"], source) for source in row["chapters"]
    ]} for row in manuscripts]
    public, private = build_unassigned_manuscript_pack(loaded, secret=blind_secret, pack_key=pack_key)
    source_ids = tuple(dict.fromkeys(chapter["parent_asset_version_id"] for row in loaded for chapter in row["chapters"]))
    private_op = authority._execute("reader.manuscript.mapping.record", project_id=project_id,
        workspace_id=workspace_id, idempotency_key=f"{pack_key}:mapping", principal=principal,
        input_assets=authority._resolve(project_id, source_ids), payload={
            "project_id": project_id, "workspace_id": workspace_id,
            "blind_secret_hash": content_digest(blind_secret), **private,
        })
    private_output = authority._output(private_op, "reader.manuscript.mapping")
    public_op = authority._execute("reader.manuscript.pack.export", project_id=project_id,
        workspace_id=workspace_id, idempotency_key=f"{pack_key}:public", principal=principal,
        input_assets=authority._resolve(project_id, (private_output["asset_version_id"],)),
        payload={"public": public, "public_content_hash": content_digest(public),
            "human_feedback_status": "PENDING_HUMAN_FEEDBACK"})
    return {"public": authority._output(public_op, "reader.manuscript.pack"), "mapping": private_output,
        "pack_token": public["pack_token"], "public_content_hash": content_digest(public),
        "human_feedback_status": "PENDING_HUMAN_FEEDBACK", "chapter_count": sum(len(row["chapters"]) for row in loaded)}


def require_manuscript_pack(authority, *, project_id: str, pack_id: str, principal) -> dict[str, Any]:
    principal.require("book.authority.execute", project_id)
    with AuthorityUnitOfWork(authority.database_url) as uow:
        doc = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=pack_id)
    public = doc.content.get("public")
    if (doc.asset_type != "manuscript_blind_evaluation_pack" or not isinstance(public, dict)
            or public.get("protocol_version") != MANUSCRIPT_PROTOCOL
            or content_digest(public) != doc.content.get("public_content_hash")):
        raise KernelError("MANUSCRIPT_BLIND_PACK_INVALID", "Only a hash-bound public manuscript pack can enter reading feedback")
    return public


def manuscript_reading_view(authority, *, project_id: str, pack_id: str, principal) -> dict[str, Any]:
    public = require_manuscript_pack(authority, project_id=project_id, pack_id=pack_id, principal=principal)
    with AuthorityUnitOfWork(authority.database_url) as uow:
        row = uow.cursor.execute("""SELECT o.workspace_id FROM authority_operation_output_asset binding
            JOIN authority_operation o USING(operation_id)
            WHERE binding.asset_version_id=%s AND o.project_id=%s AND o.status='SUCCEEDED'
            AND o.definition_name='reader.manuscript.pack.export'""", [pack_id, project_id]).fetchone()
    if not row:
        raise KernelError("MANUSCRIPT_PACK_PRODUCER_REQUIRED", "Reading requires the pack's completed native producer")
    return {"public": public, "workspace_id": row[0]}


def record_manuscript_feedback(authority, *, project_id: str, workspace_id: str, pack_id: str,
                               public_content_hash: str, feedback_id: str,
                               response: dict[str, Any], principal) -> dict[str, Any]:
    public = require_manuscript_pack(authority, project_id=project_id, pack_id=pack_id, principal=principal)
    if not feedback_id or public_content_hash != content_digest(public):
        raise KernelError("MANUSCRIPT_FEEDBACK_SNAPSHOT_DRIFT", "Feedback must identify its frozen reading pack")
    feedback = validate_manuscript_human_response(public, response)
    op = authority._execute("reader.manuscript.feedback.record", project_id=project_id,
        workspace_id=workspace_id, idempotency_key=f"{pack_id}:feedback:{feedback_id}", principal=principal,
        input_assets=authority._resolve(project_id, (pack_id,)), payload={
            "project_id": project_id, "feedback_id": feedback_id, **feedback,
        })
    return {**authority._output(op, "reader.manuscript.feedback"), "operation_id": op,
        "evaluator_origin": "HUMAN_SUBMISSION", "identity_verification": "DECLARED_NOT_INDEPENDENTLY_VERIFIED"}


def manuscript_feedback_status(authority, *, project_id: str, pack_id: str, principal) -> dict[str, Any]:
    public = require_manuscript_pack(authority, project_id=project_id, pack_id=pack_id, principal=principal)
    with AuthorityUnitOfWork(authority.database_url) as uow:
        uow.cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content
            FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            JOIN authority_operation_output_asset binding USING(asset_version_id)
            JOIN authority_operation o USING(operation_id)
            WHERE a.project_id=%s AND a.asset_type IN ('human_manuscript_reading_feedback','model_manuscript_reading_diagnosis')
            AND v.content->>'pack_token'=%s AND v.content->>'public_content_hash'=%s
            AND o.project_id=a.project_id AND o.status='SUCCEEDED'
            AND o.command_payload->'input_asset_version_ids' ? %s
            AND ((a.asset_type='human_manuscript_reading_feedback' AND o.definition_name='reader.manuscript.feedback.record')
              OR (a.asset_type='model_manuscript_reading_diagnosis' AND o.definition_name='reader.manuscript.diagnosis.record'))
            ORDER BY v.created_at,v.asset_version_id""", [project_id, public["pack_token"], content_digest(public), pack_id])
        rows = uow.cursor.fetchall()
    human, model = [], []
    for aid, digest, content in rows:
        result = {"asset_version_id": aid, "content_hash": digest, "content": content}
        if content.get("evaluator_origin") == "HUMAN_SUBMISSION":
            human.append(result)
        elif content.get("evaluator_origin") == "MODEL_AUXILIARY_DIAGNOSIS":
            model.append({**result, "input_consumption_status":
                "ACTUAL_PROVIDER_INPUT_VERIFIED" if (content.get("input_consumption_proof") or {}).get("status")
                == "ACTUAL_PROVIDER_INPUT_VERIFIED" else "HISTORICAL_MODEL_OUTPUT_CLAIM_INPUT_NOT_VERIFIED"})
    return {"pack_token": public["pack_token"], "human_feedback_status":
            "HUMAN_DECLARATIONS_RECEIVED" if human else "PENDING_HUMAN_FEEDBACK",
        "human_submissions": human, "model_diagnoses": model,
        "independently_verified_human_count": 0, "author_acceptance": False,
        "writing_export_or_continuation_blocked": False}


def record_manuscript_model_diagnosis(authority, *, project_id: str, workspace_id: str,
                                     pack_id: str, diagnosis_id: str, normalized_asset_version_id: str,
                                     normalized_content_hash: str, principal) -> dict[str, Any]:
    public = require_manuscript_pack(authority, project_id=project_id, pack_id=pack_id, principal=principal)
    doc, producer_id, input_proof = require_controlled_model_result(authority, project_id=project_id,
        normalized_asset_version_id=normalized_asset_version_id, normalized_content_hash=normalized_content_hash,
        public=public, pack_id=pack_id)
    diagnosis = normalize_manuscript_model_diagnosis(public, doc.content["payload"]["final_response"])
    if not diagnosis_id:
        raise ValueError("MODEL_READING_DIAGNOSIS_ID_REQUIRED")
    op = authority._execute("reader.manuscript.diagnosis.record", project_id=project_id,
        workspace_id=workspace_id, idempotency_key=f"{pack_id}:diagnosis:{diagnosis_id}", principal=principal,
        input_assets=authority._resolve(project_id, (pack_id, normalized_asset_version_id)), payload={
            "project_id": project_id, "diagnosis_id": diagnosis_id,
            "normalized_asset_version_id": normalized_asset_version_id,
            "normalized_content_hash": normalized_content_hash, "model_producer_operation_id": producer_id,
            "input_consumption_proof": input_proof, **diagnosis,
        })
    return {**authority._output(op, "reader.manuscript.diagnosis"), "operation_id": op,
        "evaluator_origin": "MODEL_AUXILIARY_DIAGNOSIS"}


def require_controlled_model_result(authority, *, project_id: str, normalized_asset_version_id: str,
                                    normalized_content_hash: str, public: dict[str, Any], pack_id: str):
    from novel_forge.modules.agent_runtime.queries import require_completed_reference_input
    with AuthorityUnitOfWork(authority.database_url) as uow:
        doc = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=normalized_asset_version_id)
        if (doc.asset_type != "execution_evidence" or doc.content_hash != normalized_content_hash
                or doc.content.get("kind") != "normalized-output" or doc.content.get("payload", {}).get("action") != "FINAL"):
            raise KernelError("MODEL_READING_SOURCE_INVALID", "Diagnosis requires an exact normalized Provider result")
        uow.cursor.execute("""SELECT binding.operation_id FROM authority_operation_output_asset binding
            JOIN authority_operation o USING(operation_id)
            WHERE binding.asset_version_id=%s AND o.project_id=%s AND o.status='SUCCEEDED'""",
            [normalized_asset_version_id, project_id])
        producer = uow.cursor.fetchone()
        if not producer or not reference_prose_generation(uow.cursor, producer[0], project_id):
            raise KernelError("MODEL_READING_PRODUCER_INVALID", "Auxiliary reading requires its sealed controlled model producer")
    instruction, proof = require_completed_reference_input(authority.database_url,
        project_id=project_id, operation_id=producer[0], execution_id=doc.content.get("execution_id"),
        normalized_result=doc.content["payload"])
    require_manuscript_reading_input(instruction, public, pack_id)
    if proof["task_purpose"] != "MANUSCRIPT_READING":
        raise KernelError("MODEL_READING_PURPOSE_REQUIRED", "Auxiliary reading requires its explicitly frozen reading purpose")
    return doc, producer[0], {**proof, "public_pack_asset_version_id": pack_id,
        "public_content_hash": content_digest(public),
        "chapter_count": sum(len(row["chapters"]) for row in public["manuscripts"])}
