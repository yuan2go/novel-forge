from __future__ import annotations

import hashlib
from collections.abc import Mapping


def retain_model_result(record, store, *, raw_text: str, complete: bool, source: Mapping) -> str:
    request = record.request
    payload = {
        "contract_version": "retained-model-result.v1",
        "project_id": request.project_id,
        "book_id": request.book_id,
        "operation_id": request.operation_id,
        "attempt_id": request.attempt_id,
        "fencing_token": request.fencing_token,
        "external_effect_id": request.external_effect_id,
        "request_contract_hash": request.contract_hash,
        "stage": request.stage,
        "raw_text": raw_text,
        "raw_sha256": "sha256:" + hashlib.sha256(raw_text.encode()).hexdigest(),
        "source": dict(source),
        "completeness": "COMPLETE_SOURCE_RESULT" if complete else "FRAGMENT",
        "structural_status": "NOT_VALIDATED",
        "review_status": "NOT_REVIEWED",
        "selection_status": "REVOKED" if source.get("commit_rights") == "REVOKED" else "NOT_SELECTED",
        "acceptance_status": "NOT_ACCEPTED",
        "accounting_status": "UNRECONCILED",
    }
    ref = store.put_evidence("model-result", request.execution_id, payload)
    record.raw_evidence["retained_model_result_ref"] = ref
    store.save_record(record)
    try:
        from .codex_configuration import strict_codex_json_loads
        parsed = strict_codex_json_loads(raw_text)
    except (ValueError, RecursionError):
        return ref
    if complete and request.stage in {"draft", "revision"} and isinstance(parsed, dict):
        from .codex_configuration import decode_codex_output
        try:
            parsed, _ = decode_codex_output(parsed, schema_ref=str(
                record.frozen_output_contract.get("output_schema_version") or ""
            ))
        except (ValueError, TypeError, RecursionError):
            return ref
        text = parsed.get("text")
        if not isinstance(text, str) or not text.strip():
            artifacts = parsed.get("scene_artifacts")
            if (not isinstance(artifacts, list) or not artifacts
                    or any(not isinstance(item, dict) or not isinstance(item.get("text"), str)
                           or not item["text"].strip() for item in artifacts)):
                return ref
            from novel_forge.text_slots import serialize_text_slots
            try:
                text = serialize_text_slots(artifacts, parsed.get("scene_separators"))
            except ValueError:
                return ref
        candidate = {**payload, "raw_result_ref": ref, "text": text,
                     "text_sha256": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                     "completeness": "COMPLETE_SOURCE_PROSE"}
        record.raw_evidence["retained_prose_candidate_ref"] = store.put_evidence(
            "prose-candidate", request.execution_id, candidate
        )
        store.save_record(record)
    return ref
