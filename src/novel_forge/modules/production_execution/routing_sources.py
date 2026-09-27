from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.versioned_policy_repository import policy_hash


VERSION = "routing-benchmark-export.v1"
_DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_TEXT = {"type": "string", "minLength": 1, "maxLength": 256}
_SCOPE = {
    "contract_version": {"const": VERSION}, "export_id": _TEXT,
    "source_project_id": _TEXT, "target_project_id": _TEXT, "target_work_id": _TEXT,
    "task_type": _TEXT, "candidate_id": _TEXT, "provider": _TEXT, "model": _TEXT,
    "reasoning": {"type": "string", "maxLength": 64}, "model_revision": _TEXT,
    "producer_contract_hash": _DIGEST, "campaign_id": _TEXT, "manifest_hash": _DIGEST,
    "campaign_expires_at": _TEXT, "expires_at": _TEXT, "reason": _TEXT,
    "observations": {"type": "array", "minItems": 1, "maxItems": 200,
        "items": {"type": "object", "additionalProperties": False,
            "required": ["asset_version_id", "content_hash"],
            "properties": {"asset_version_id": _TEXT, "content_hash": _DIGEST}}},
}
EXPORT_SCHEMA = {"type": "object", "additionalProperties": False, "required": list(_SCOPE), "properties": _SCOPE}
SOURCE_POLICY_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["policy_version", "content_hash", "operation_id"],
    "properties": {"policy_version": _TEXT, "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "operation_id": _TEXT}}
BINDING_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["export", "source_policy"], "properties": {"export": EXPORT_SCHEMA, "source_policy": SOURCE_POLICY_SCHEMA}}


def _fail(message: str) -> None:
    raise KernelError("ROUTING_BENCHMARK_SOURCE_INVALID", message)


def validate_source_fields(content: Mapping[str, Any]) -> None:
    from novel_forge.modules.command_kernel.service import _validate_json_schema

    for field in ("benchmark_exports", "benchmark_source_bindings"):
        if not isinstance(content.get(field, []), list) or len(content.get(field, [])) > 16:
            _fail("benchmark source policy must contain at most sixteen explicit entries")
    for binding in content.get("benchmark_source_bindings", []):
        _validate_json_schema(BINDING_SCHEMA, binding)
        source = binding["source_policy"]
        if any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in source.values()) or not re.fullmatch(r"[0-9a-f]{64}", source["content_hash"]):
            _fail("source policy requires an exact immutable version, hash and native Operation")
    identities = set()
    for row in [*content.get("benchmark_exports", []), *(item["export"] for item in content.get("benchmark_source_bindings", []))]:
        _validate_json_schema(EXPORT_SCHEMA, row)
        if row["contract_version"] != VERSION or any(not isinstance(row[key], str) or len(row[key]) > 256
            or (key != "reasoning" and not row[key].strip()) for key in _SCOPE if key != "observations"):
            _fail("benchmark export identity fields must be complete and bounded")
        if any(not re.fullmatch(r"sha256:[0-9a-f]{64}", row[key]) for key in ("producer_contract_hash", "manifest_hash")):
            _fail("benchmark scope requires exact producer and manifest hashes")
        identity = (row["source_project_id"], row["export_id"])
        if identity in identities or row["source_project_id"] == row["target_project_id"]:
            _fail("exports require distinct Projects and unique exact identities")
        identities.add(identity)
        for key in ("expires_at", "campaign_expires_at"):
            if datetime.fromisoformat(row[key]).tzinfo is None:
                _fail("benchmark source expiry must include a timezone")
        refs = row["observations"]
        if not 1 <= len(refs) <= 200:
            _fail("benchmark export requires one to two hundred exact observation versions")
        for ref in refs:
            _validate_json_schema(_SCOPE["observations"]["items"], ref)
            if not ref["asset_version_id"].strip() or len(ref["asset_version_id"]) > 256 or not re.fullmatch(r"sha256:[0-9a-f]{64}", ref["content_hash"]):
                _fail("observation identity must contain an exact asset version and hash")
        if len({item["asset_version_id"] for item in refs}) != len(refs):
            _fail("an observation version may occur only once in an export")
        from .cost_routing import task_policy
        task_policy(row["task_type"])


def require_source_permissions(principal, *, project_id: str, content: Mapping[str, Any]) -> None:
    for row in content.get("benchmark_exports", []):
        if row["source_project_id"] != project_id:
            _fail("only the source Project may approve its observation export")
        principal.require("book.authority.execute", row["target_project_id"])
    for binding in content.get("benchmark_source_bindings", []):
        row = binding["export"]
        if row["target_project_id"] != project_id:
            _fail("a source binding must name its exact target Project")
        principal.require("book.authority.execute", row["source_project_id"])


def _policies(cursor, project_id: str):
    cursor.execute("""SELECT content,content_hash FROM authority_runtime_policy_version
        WHERE owner='PROVIDER_ROUTING' AND project_id=%s""", [project_id])
    result = []
    for content, digest in cursor.fetchall():
        if policy_hash(content) != digest:
            _fail("source policy integrity failed")
        result.append(content)
    return result


def _validate_export(cursor, row: Mapping[str, Any], *, now: datetime) -> None:
    if datetime.fromisoformat(row["expires_at"]) <= now:
        _fail("the approved benchmark export has expired")
    policies = _policies(cursor, row["source_project_id"])
    grants = [grant for policy in policies for grant in policy.get("bootstrap_authorizations", [])]
    for policy in policies:
        for prior in policy.get("benchmark_exports", []):
            if prior["export_id"] == row["export_id"] and prior != row:
                _fail("an approved export identity cannot be redefined")
    refs = {item["asset_version_id"]: item["content_hash"] for item in row["observations"]}
    cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content,e.request_payload,
                             v.lifecycle,v.governance
        FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
        JOIN authority_external_effect e ON e.external_effect_id=COALESCE(v.content->'provider_evidence',v.content)
            #>> '{production_execution,execution_request,external_effect_id}' AND e.project_id=a.project_id
        WHERE a.project_id=%s AND a.asset_type='model_call_log' AND v.asset_version_id=ANY(%s)""",
        [row["source_project_id"], list(refs)])
    records = cursor.fetchall()
    if len(records) != len(refs):
        _fail("every exported observation must be an exact native source model-call asset")
    for asset_id, digest, content, request, lifecycle, governance in records:
        route = request.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
        grant = route.get("bootstrap_authorization", {}).get("authorization", {})
        campaign = grant.get("campaign", {})
        candidate = route.get("selected", {}).get("candidate", {})
        evidence = content.get("provider_evidence", content)
        if (refs[asset_id] != digest or lifecycle != "ACTIVE" or governance != "CLEAR"
            or route.get("status") != "BENCHMARK_SELECTED" or route.get("mode") != "BENCHMARK_CHALLENGER"
            or route.get("production_eligible") is not False or grant not in grants
            or grant.get("purpose") not in {"BENCHMARK_CHALLENGER", "REFERENCE_EVALUATION"}
            or grant.get("task_type") != row["task_type"] or request.get("stage") != row["task_type"]
            or any(grant.get(key) != row[key] for key in ("candidate_id", "model_revision"))
            or (grant.get("producer_contract_hash") is not None and grant["producer_contract_hash"] != row["producer_contract_hash"])
            or route.get("task", {}).get("producer_contract_hash") != row["producer_contract_hash"]
            or any(candidate.get(key) != row[key] for key in ("candidate_id", "provider", "model", "reasoning", "model_revision"))
            or any(campaign.get(key) != row[key] for key in ("campaign_id", "manifest_hash"))
            or campaign.get("expires_at") != row["campaign_expires_at"]
            or evidence.get("provider_id") != row["provider"] or evidence.get("model_id") != row["model"]):
            _fail("observation differs from the approved exact campaign, producer, model or native sampling authorization")


def validate_binding(cursor, binding: Mapping[str, Any], *, now: datetime) -> None:
    row, source = binding["export"], binding["source_policy"]
    cursor.execute("""SELECT v.content,v.content_hash,v.created_by_operation_id,v.actor_id,
               o.status,o.definition_name,o.actor_id,o.command_payload,
               current.content,current.content_hash
        FROM authority_runtime_policy_version v JOIN authority_operation o ON o.operation_id=v.created_by_operation_id
        JOIN authority_runtime_policy_selection s ON s.owner=v.owner AND s.project_id=v.project_id
        JOIN authority_runtime_policy_version current ON (current.owner,current.project_id,current.policy_version)
            =(s.owner,s.project_id,s.policy_version)
        WHERE v.owner='PROVIDER_ROUTING' AND v.project_id=%s AND v.policy_version=%s""",
        [row["source_project_id"], source["policy_version"]])
    found = cursor.fetchone()
    if found is None:
        _fail("benchmark export approval has no native policy Operation")
    policy, digest, operation, actor, status, definition, operation_actor, payload, current, current_hash = found
    if (digest != source["content_hash"] or policy_hash(policy) != digest or policy_hash(current) != current_hash
        or operation != source["operation_id"] or status != "SUCCEEDED"
        or definition != "provider.routing_policy.configure" or actor != operation_actor
        or payload.get("policy") != policy or payload.get("project_id") != row["source_project_id"]
        or row not in policy.get("benchmark_exports", []) or row not in current.get("benchmark_exports", [])):
        _fail("source export approval was changed, revoked or does not match its native policy decision")
    _validate_export(cursor, row, now=now)


def validate_sources_in_uow(cursor, *, project_id: str, content: Mapping[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    for row in content.get("benchmark_exports", []):
        if row["source_project_id"] != project_id:
            _fail("export source Project mismatch")
        _validate_export(cursor, row, now=now)
    for binding in content.get("benchmark_source_bindings", []):
        if binding["export"]["target_project_id"] != project_id:
            _fail("binding target Project mismatch")
        validate_binding(cursor, binding, now=now)


def matching_bindings(policy: Mapping[str, Any], *, project_id: str, work_id: str,
                      task_type: str, candidate, producer_contract_hash: str | None):
    matched = [binding for binding in policy.get("benchmark_source_bindings", [])
        if all(binding["export"][key] == value for key, value in {
            "target_project_id": project_id, "target_work_id": work_id, "task_type": task_type,
            "candidate_id": candidate.candidate_id, "provider": candidate.provider,
            "model": candidate.model, "reasoning": candidate.reasoning,
            "model_revision": candidate.model_revision, "producer_contract_hash": producer_contract_hash,
        }.items())]
    sources: dict[str, set[str]] = {}
    for binding in matched:
        row = binding["export"]
        sources.setdefault(row["source_project_id"], set()).update(item["asset_version_id"] for item in row["observations"])
    if any(len(refs) > 200 for refs in sources.values()):
        raise KernelError("ROUTING_BENCHMARK_SOURCE_SCOPE_EXCEEDED", "matched source exports exceed the complete two-hundred-observation read scope; narrow the explicit binding")
    return matched
