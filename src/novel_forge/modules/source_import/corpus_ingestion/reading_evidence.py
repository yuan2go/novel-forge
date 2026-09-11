from __future__ import annotations

import hashlib

from novel_forge.modules.source_authority.corpus import corpus_hash


def materialized_input_manifest(inputs: dict, request: dict, policy: dict) -> dict:
    context = inputs.get("reading_context", {})
    segments = []
    for segment in inputs.get("source_segments", []):
        content = segment["content"].encode("utf-8")
        segments.append(
            {
                "source_chunk_asset_version_id": segment[
                    "source_chunk_asset_version_id"
                ],
                "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
                "byte_start": 0,
                "byte_end": len(content),
                "byte_size": len(content),
                "role": "TARGET_TEXT",
            }
        )
    manifest = {
        "schema_version": "source-actual-input.v1",
        "reading_identity": context.get("reading_identity"),
        "processing_id": context.get("processing_id"),
        "source_transform_id": context.get("source_transform_id"),
        "target_units": context.get("unit_versions", []),
        "unit_bindings": context.get("unit_bindings", []),
        "actual_text_inputs": segments,
        "lower_observation_inputs": [
            i["asset_version_id"] for i in inputs.get("input_observations", [])
        ],
        "lower_observation_manifest": [
            {
                "asset_version_id": i["asset_version_id"],
                "content_hash": i.get("content_hash"),
                "observation_hash": corpus_hash(i["observation"]),
            }
            for i in inputs.get("input_observations", [])
        ],
        "context_roles": {
            k: corpus_hash(inputs[k])
            for k in ("reading_context", "review_target", "narrative_contract")
            if k in inputs
        },
        "materialized_input_hash": corpus_hash(inputs),
        "request": request,
        "policy": policy,
        "read_mode": "FULL_TARGET_UNIT_TEXT" if segments else "VERIFIED_OBSERVATIONS",
        "understanding_claim": False,
    }
    manifest["manifest_hash"] = corpus_hash(manifest)
    return manifest


def receipt_input_evidence(records: list[dict], payload: dict) -> dict:
    calls = []
    confirmed = []
    for record in records:
        manifest = record.get("manifest")
        returned = bool(record.get("returned"))
        state = (
            "CONFIRMED_RETURNED"
            if returned
            else "UNKNOWN"
            if record.get("status")
            in {
                "DISPATCHING",
                "DISPATCHED",
                "OUTCOME_UNKNOWN",
                "UNKNOWN",
                "RECONCILIATION_REQUIRED",
                "WAITING_EXTERNAL_RESULT",
            }
            else "PREPARED"
        )
        if not manifest:
            state = "NOT_RECORDED"
        calls.append(
            {
                **{
                    k: record.get(k)
                    for k in (
                        "effect_id",
                        "receipt_id",
                        "origin_operation_id",
                        "diagnostic_refs",
                        "admission_asset_version_id",
                    )
                },
                "state": state,
                "reused": record.get("reused", False),
                "manifest": manifest,
            }
        )
        if returned and manifest:
            confirmed.append(manifest)
    plan = payload["narrative_reading"]
    latest = confirmed[-1] if confirmed else {}
    coverage = {
        **latest,
        "reading_identity": plan["identity"],
        "processing_id": plan["processing_id"],
        "target_units": latest.get("target_units", []),
        "actual_text_inputs": latest.get("actual_text_inputs", []),
        "lower_observation_inputs": latest.get("lower_observation_inputs", []),
        "allowed_context_not_read": [
            u["source_unit_version_id"]
            for u in plan["units"]
            if u["role"] == "ALLOWED_CONTEXT"
        ],
        "understanding_claim": False,
        "input_state": "CONFIRMED_RETURNED"
        if confirmed
        else calls[-1]["state"]
        if calls
        else "NOT_RECORDED",
        "receipt_reused": any(
            r["reused"] for r in calls if r["state"] == "CONFIRMED_RETURNED"
        ),
    }
    return {"coverage": coverage, "input_receipts": calls}
