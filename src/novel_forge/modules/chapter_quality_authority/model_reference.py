"""SECURITY: model consensus requires native provider receipts and cannot assume human identity."""

from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash


MODEL_REFERENCE_PROTOCOL = "model-reference-consensus.v1"
MODEL_REFERENCE_EVALUATION = "quality.model_reference_evaluation.record"
MODEL_REFERENCE_ADJUDICATION = "quality.model_reference_adjudication.record"
MODEL_REFERENCE_VERSION = "2.5.0"
_RECORD_FIELDS = {"subject", "author_baseline", "policy_hash", "producer_contract_hash",
    "protocol_version", "evaluation_version", "dimension", "scope", "model_call", "judgment",
    "recording_actor_id", "operation_id", "attempt_id", "external_effect_id", "provider_id",
    "model_id", "session_id", "model_call_asset_version_id"}


def _invalid(message: str) -> KernelError:
    return KernelError("MODEL_REFERENCE_PROVENANCE_INVALID", message)


def _canonical_provider_evidence(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult

    try:
        return ModelProviderResult.from_evidence(value).to_evidence()
    except (KernelError, TypeError, ValueError):
        return None


def require_native_model_call(cursor: Any, *, project_id: str, binding: Mapping[str, str],
                              expected: Mapping[str, Any], role: str) -> dict[str, Any]:
    """SECURITY: caller supplied model metadata is never accepted as execution evidence."""
    if not isinstance(binding, Mapping) or set(binding) != {"asset_version_id", "content_hash"}:
        raise _invalid("model call requires one exact frozen asset")
    cursor.execute("""SELECT log.content,log.content_hash,operation.operation_id,operation.input_asset_snapshot,
        effect.external_effect_id,effect.request_payload,effect.request_hash,effect.model_id,attempt.attempt_id,
        dispatch.generation,dispatch.evidence,dispatch.receipt_id,
        receipt.receipt_id,receipt.payload,receipt.payload_hash
        FROM authority_asset_version log JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=log.asset_version_id
          AND output.content_hash=log.content_hash AND output.role='model_evidence'
        JOIN authority_operation operation ON operation.operation_id=output.operation_id
          AND operation.project_id=asset.project_id AND operation.status='SUCCEEDED'
        JOIN authority_external_effect effect ON effect.operation_id=operation.operation_id
          AND effect.project_id=asset.project_id AND effect.status='SUCCEEDED'
        JOIN authority_external_effect_dispatch dispatch ON dispatch.external_effect_id=effect.external_effect_id
          AND dispatch.status='SUCCEEDED'
        JOIN authority_external_receipt receipt ON receipt.dispatch_id=dispatch.dispatch_id
          AND receipt.status='VERIFIED'
        JOIN authority_attempt attempt ON attempt.operation_id=operation.operation_id
          AND attempt.status='SUCCEEDED'
        WHERE asset.project_id=%s AND asset.asset_type='model_call_log'
          AND log.asset_version_id=%s AND log.lifecycle='ACTIVE' AND log.governance='CLEAR'
          AND operation.definition_name=%s AND operation.definition_version='1.0.0'""",
        [project_id, binding["asset_version_id"],
         "quality.model_reference.evaluate" if role == "BLIND_EVALUATION" else "quality.model_reference.adjudicate"])
    matches = []
    stage = "model_reference_evaluate" if role == "BLIND_EVALUATION" else "model_reference_adjudicate"
    for (content, digest, operation_id, inputs, effect_id, request, request_hash, model_id, attempt_id,
         generation, dispatch_evidence, dispatch_receipt_id, receipt_id, receipt_payload, receipt_hash) in cursor.fetchall():
        evidence = content.get("provider_evidence") if isinstance(content, dict) else None
        execution = evidence.get("production_execution") if isinstance(evidence, dict) else None
        native = execution.get("execution_request") if isinstance(execution, dict) else None
        handle = execution.get("execution_handle") if isinstance(execution, dict) else None
        process = execution.get("process_evidence") if isinstance(execution, dict) else None
        result_receipt = execution.get("execution_result") if isinstance(execution, dict) else None
        route = execution.get("route_snapshot") if isinstance(execution, dict) else None
        manifest = execution.get("input_manifest") if isinstance(execution, dict) else None
        provider_input = request.get("input") if isinstance(request, dict) else None
        frozen = provider_input.get("model_reference") if isinstance(provider_input, dict) else None
        if not isinstance(content, dict) or not isinstance(evidence, dict) or not isinstance(execution, dict):
            continue
        if not isinstance(inputs, list):
            continue
        frozen_ids = {(item.get("asset_version_id"), item.get("content_hash")) for item in inputs if isinstance(item, dict)}
        allowed_inputs = {tuple(item[key] for key in ("asset_version_id", "content_hash"))
                          for item in (expected["subject"], expected["author_baseline"],
                                       *expected.get("source_evaluations", []))}
        process_receipt_id = process.get("local_execution_receipt_id") if isinstance(process, dict) else None
        model_authority = process.get("model_authority") if isinstance(process, dict) else None
        if (not isinstance(native, dict) or digest != binding["content_hash"] or digest != authorization_hash(content)
            or content.get("operation_id") != operation_id or content.get("attempt_id") != attempt_id
            or content.get("external_effect_id") != effect_id or content.get("project_id") != project_id
            or content.get("stage") != stage or native.get("stage") != stage
            or content.get("fixture") or content.get("fixture_protocol_only")
            or evidence.get("real_model_call") is not True or evidence.get("fixture_protocol_only")
            or request_hash != authorization_hash(request)
            or receipt_hash != authorization_hash(dispatch_evidence)
            or dispatch_receipt_id != receipt_id or receipt_id != process_receipt_id
            or not isinstance(receipt_payload, dict) or receipt_payload.get("outcome") != "success"
            or receipt_payload.get("generation") != generation or receipt_payload.get("evidence") != dispatch_evidence
            or _canonical_provider_evidence(dispatch_evidence) != evidence
            or not isinstance(result_receipt, dict) or result_receipt.get("outcome") != "SUCCEEDED"
            or result_receipt.get("operation_id") != operation_id or result_receipt.get("attempt_id") != attempt_id
            or not result_receipt.get("normalized_output_ref") or not result_receipt.get("output_manifest_ref")
            or not result_receipt.get("validation_report_ref")
            or not isinstance(execution.get("output_manifest"), dict)
            or not isinstance(execution.get("validation_manifest"), dict)
            or any(native.get(key) != value for key, value in (("project_id", project_id),
                ("operation_id", operation_id), ("attempt_id", attempt_id), ("external_effect_id", effect_id)))
            or evidence.get("model_id") != model_id or not evidence.get("provider_id")
            or not isinstance(handle, dict) or not isinstance(process, dict)
            or handle.get("operation_id") != operation_id or handle.get("attempt_id") != attempt_id
            or not process_receipt_id or handle.get("local_execution_receipt_id") != process_receipt_id
            or handle.get("backend_execution_id") != process_receipt_id
            or handle.get("transport") != "LOCAL_CLI_REMOTE_INFERENCE"
            or process.get("transport") != "LOCAL_CLI_REMOTE_INFERENCE"
            or not isinstance(model_authority, dict)
            or model_authority.get("local_user_config_ignored") is not True
            or not isinstance(route, dict) or not isinstance(manifest, dict)
            or route.get("operation_id") != operation_id or route.get("attempt_id") != attempt_id
            or route.get("model_provider") != evidence.get("provider_id") or route.get("model_id") != model_id
            or route.get("reasoning_effort") != model_authority.get("invocation_reasoning_effort")
            or model_authority.get("invocation_model") != model_id
            or not route.get("model_profile_hash") or not route.get("route_policy_hash")
            or not route.get("prompt_bundle_ref") or not route.get("skill_bundle_ref")
            or not route.get("output_schema_ref") or not route.get("context_bundle_ref")
            or not isinstance(frozen, dict) or frozen != {**expected, "role": role}
            or frozen_ids != allowed_inputs):
            continue
        matches.append({"operation_id": operation_id, "attempt_id": attempt_id,
            "external_effect_id": effect_id, "provider_id": evidence["provider_id"], "model_id": model_id,
            "session_id": process_receipt_id,
            "provider_input": request.get("input"),
            "result": evidence.get("result")})
    if len(matches) != 1 or not matches[0]["session_id"] or not isinstance(matches[0]["result"], dict):
        raise _invalid("model judgment requires one successful native Effect, session and ModelCallLog")
    from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization

    grant_snapshot = load_bootstrap_authorization(cursor, project_id=project_id,
        operation_id=matches[0]["operation_id"], check_expiry=False)
    grant = grant_snapshot.get("authorization") if isinstance(grant_snapshot, Mapping) else None
    if (not isinstance(grant, Mapping) or grant.get("purpose") != "MODEL_REFERENCE_CREATION"
        or grant.get("model_reference") != {**expected, "role": role}):
        raise _invalid("model reference call lacks its exact native creation grant")
    from .model_reference_execution import validate_model_reference_effect_inputs

    validate_model_reference_effect_inputs(cursor, project_id=project_id,
        frozen={**expected, "role": role}, provider_input=matches[0]["provider_input"],
        operation_id=matches[0]["operation_id"], attempt_id=matches[0]["attempt_id"])
    matches[0].pop("provider_input")
    return matches[0]


def validate_panel(evaluations: list[Mapping[str, Any]], adjudication: Mapping[str, Any]) -> dict[str, Any]:
    """INVARIANT: two blind calls and a third independent call form one correlated model panel."""
    if len(evaluations) != 2 or any(item.get("blind") is not True for item in evaluations):
        raise _invalid("model panel requires two blind evaluations")
    sources = [*evaluations, adjudication]
    for field in ("subject", "author_baseline", "policy_hash", "producer_contract_hash",
                  "protocol_version", "evaluation_version", "dimension", "scope"):
        if len({authorization_hash(item.get(field)) for item in sources}) != 1:
            raise _invalid("model panel source scope differs")
    for field in ("operation_id", "attempt_id", "external_effect_id", "session_id", "model_call_asset_version_id"):
        if len({item.get(field) for item in sources}) != 3 or any(not item.get(field) for item in sources):
            raise _invalid("model panel executions are not independent")
    if adjudication.get("source_evaluation_asset_version_ids") != [item.get("asset_version_id") for item in evaluations]:
        raise _invalid("adjudication source evaluations differ")
    model_keys = {(item.get("provider_id"), item.get("model_id")) for item in sources}
    return {"reference_basis": "MODEL_CONSENSUS", "same_model_correlated": len(model_keys) != 3,
            "human_verified": False, "human_preference_evidence": False}


def require_model_reference_annotation(cursor: Any, *, project_id: str, definition_name: str,
                                       payload: Mapping[str, Any], actor_id: str,
                                       input_assets: list[Mapping[str, str]]) -> str:
    from .reference_subject import require_reference_subject

    if definition_name not in {MODEL_REFERENCE_EVALUATION, MODEL_REFERENCE_ADJUDICATION}:
        raise _invalid("model reference requires its own versioned Content command")
    record = payload.get("model_reference")
    if not isinstance(record, Mapping) or record.get("recording_actor_id") != actor_id:
        raise _invalid("model reference author differs from authenticated operation")
    permitted = (_RECORD_FIELDS | {"blind"}) if definition_name == MODEL_REFERENCE_EVALUATION else (
        _RECORD_FIELDS | {"source_evaluations", "source_evaluation_asset_version_ids"})
    if set(record) != permitted:
        raise _invalid("model reference record has missing or unrecognized fields")
    required = {"subject", "author_baseline", "policy_hash", "producer_contract_hash",
                "protocol_version", "evaluation_version", "dimension", "scope"}
    if not required.issubset(record) or record["protocol_version"] != MODEL_REFERENCE_PROTOCOL:
        raise _invalid("model reference contract is incomplete")
    subject = require_reference_subject(cursor, project_id=project_id, binding=record["subject"],
        allowed_types=frozenset({"chapter_provider_sample", "world_provider_sample", "planning_generation_candidate"}))
    frozen = {(item.get("asset_version_id"), item.get("content_hash")) for item in input_assets}
    if (subject["asset_version_id"], subject["content_hash"]) not in frozen:
        raise _invalid("model reference subject is not frozen")
    for name in ("subject", "author_baseline", "model_call"):
        binding = record.get(name)
        if (not isinstance(binding, Mapping) or set(binding) != {"asset_version_id", "content_hash"}
            or (binding["asset_version_id"], binding["content_hash"]) not in frozen):
            raise _invalid("model reference input binding is not frozen")
    expected = {key: record[key] for key in required}
    role = "BLIND_EVALUATION" if definition_name == MODEL_REFERENCE_EVALUATION else "ADJUDICATION"
    if role == "ADJUDICATION":
        sources = record.get("source_evaluations")
        if (not isinstance(sources, list) or len(sources) != 2
            or any(not isinstance(item, Mapping) or set(item) != {"asset_version_id", "content_hash"}
                   or (item["asset_version_id"], item["content_hash"]) not in frozen for item in sources)
            or [item["asset_version_id"] for item in sources] != record.get("source_evaluation_asset_version_ids")):
            raise _invalid("adjudication must freeze two exact model evaluation versions")
        expected["source_evaluations"] = sources
    elif "source_evaluations" in record:
        raise _invalid("blind evaluation cannot read previous judgments")
    native = require_native_model_call(cursor, project_id=project_id, binding=record["model_call"], expected=expected, role=role)
    if native["result"] != record.get("judgment"):
        raise _invalid("recorded judgment differs from native Provider result")
    for key in ("operation_id", "attempt_id", "external_effect_id", "provider_id", "model_id", "session_id"):
        if record.get(key) != native[key]:
            raise _invalid("recorded execution identity differs from native ModelCallLog")
    if record.get("model_call_asset_version_id") != record["model_call"]["asset_version_id"]:
        raise _invalid("recorded ModelCallLog identity differs from frozen input")
    if definition_name == MODEL_REFERENCE_EVALUATION and record.get("blind") is not True:
        raise _invalid("model reference evaluations must be blind")
    if definition_name == MODEL_REFERENCE_ADJUDICATION:
        ids = record.get("source_evaluation_asset_version_ids")
        if not isinstance(ids, list) or len(ids) != 2 or len(set(ids)) != 2:
            raise _invalid("adjudication requires two frozen blind evaluations")
        for asset_id in ids:
            if asset_id not in {item.get("asset_version_id") for item in input_assets}:
                raise _invalid("adjudication source evaluation is not frozen")
        require_model_panel_reference(cursor, project_id=project_id,
            binding={"protocol_version": MODEL_REFERENCE_PROTOCOL,
                     "adjudications": [{"asset_version_id": record.get("adjudication_asset_version_id", ""),
                                        "content_hash": record.get("adjudication_content_hash", "")}]},
            pending_adjudication={**record, **native})
    return subject["asset_version_id"]


def _native_record(cursor: Any, *, project_id: str, asset_version_id: str, asset_type: str,
                   operation_name: str) -> dict[str, Any]:
    cursor.execute("""SELECT version.content,version.content_hash,operation.actor_id
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
          AND output.content_hash=version.content_hash AND output.role='primary'
        JOIN authority_operation operation ON operation.operation_id=output.operation_id
          AND operation.project_id=asset.project_id AND operation.status='SUCCEEDED'
        WHERE asset.project_id=%s AND version.asset_version_id=%s AND asset.asset_type=%s
          AND version.lifecycle='ACTIVE' AND version.governance='CLEAR'
          AND operation.definition_name=%s AND operation.definition_version=%s""",
        [project_id, asset_version_id, asset_type, operation_name, MODEL_REFERENCE_VERSION])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise _invalid("model reference record requires one native Content output")
    content, digest, actor = rows[0]
    if digest != authorization_hash(content) or content.get("recording_actor_id") != actor:
        raise _invalid("model reference record content or actor differs")
    return {**content, "asset_version_id": asset_version_id, "content_hash": digest}


def require_model_panel_reference(cursor: Any, *, project_id: str, binding: Mapping[str, Any],
                                  pending_adjudication: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if (not isinstance(binding, Mapping) or set(binding) != {"protocol_version", "adjudications"}
        or binding["protocol_version"] != MODEL_REFERENCE_PROTOCOL
        or not isinstance(binding["adjudications"], list) or len(binding["adjudications"]) != 1):
        raise _invalid("model reference binding requires one native adjudication")
    bound = binding["adjudications"][0]
    if pending_adjudication is None:
        adjudication = _native_record(cursor, project_id=project_id,
            asset_version_id=bound["asset_version_id"], asset_type="model_reference_adjudication",
            operation_name=MODEL_REFERENCE_ADJUDICATION)
        if adjudication["content_hash"] != bound["content_hash"]:
            raise _invalid("model adjudication hash differs")
    else:
        adjudication = dict(pending_adjudication)
    ids = adjudication.get("source_evaluation_asset_version_ids")
    if not isinstance(ids, list) or len(ids) != 2 or len(set(ids)) != 2:
        raise _invalid("model adjudication lacks two source evaluations")
    evaluations = [_native_record(cursor, project_id=project_id, asset_version_id=asset_id,
        asset_type="model_reference_evaluation", operation_name=MODEL_REFERENCE_EVALUATION) for asset_id in ids]
    for item, role in [(evaluations[0], "BLIND_EVALUATION"), (evaluations[1], "BLIND_EVALUATION"),
                       (adjudication, "ADJUDICATION")]:
        expected = {key: item[key] for key in ("subject", "author_baseline", "policy_hash",
            "producer_contract_hash", "protocol_version", "evaluation_version", "dimension", "scope")}
        if role == "ADJUDICATION":
            expected["source_evaluations"] = item["source_evaluations"]
            if expected["source_evaluations"] != [
                {"asset_version_id": source["asset_version_id"], "content_hash": source["content_hash"]}
                for source in evaluations]:
                raise _invalid("adjudication source hashes differ from frozen native evaluations")
        native = require_native_model_call(cursor, project_id=project_id, binding=item["model_call"], expected=expected, role=role)
        if native["result"] != item.get("judgment") or any(item.get(key) != native[key] for key in
            ("operation_id", "attempt_id", "external_effect_id", "provider_id", "model_id", "session_id")):
            raise _invalid("model reference record differs from its native execution")
    panel = validate_panel(evaluations, adjudication)
    return {**panel, "binding": dict(binding), "labels": [{"dimension": adjudication["dimension"],
        "status": adjudication["judgment"].get("status"),
        "score_range": adjudication["judgment"].get("score_range"),
        "adjudication_asset_version_id": bound["asset_version_id"],
        "evaluation_version": adjudication["evaluation_version"]}],
        "target_asset_version_id": adjudication["subject"]["asset_version_id"],
        "target_content_hash": adjudication["subject"]["content_hash"],
        "scope": adjudication["scope"],
        "producer_contract_hash": adjudication["producer_contract_hash"],
        "policy_hash": adjudication["policy_hash"],
        "adjudicated_judgment": adjudication["judgment"],
        "evidence_refs": ["asset-version:" + bound["asset_version_id"],
            *("asset-version:" + item["asset_version_id"] for item in evaluations),
            *("asset-version:" + item["model_call_asset_version_id"] for item in [*evaluations, adjudication]),
            *("external-effect:" + item["external_effect_id"] for item in [*evaluations, adjudication])]}
