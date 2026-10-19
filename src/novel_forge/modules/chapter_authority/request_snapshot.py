from collections.abc import Mapping

from novel_forge.modules.production_execution.provider_admission import ProviderRequestEnvelope
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


def request_snapshot_required(stage, provider_data):
    if stage == "working_memory_extract":
        return True
    pending = [provider_data]
    while pending:
        value = pending.pop()
        if isinstance(value, Mapping):
            if value.get("delivery_contract") == "source-bound-full-provider-request.v1":
                return True
            policy = value.get("projection_policy")
            if isinstance(policy, Mapping) and policy.get("version") == "working-prose-projection.v10":
                return True
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    return False


def freeze_provider_request(envelope):
    body = {"version": "provider-request-snapshot.v1", "envelope": envelope.to_dict(),
        "envelope_hash": envelope.envelope_hash,
        "boundary": "APPLICATION_VISIBLE_REQUEST_INTENT_DISPATCH_AND_RECEIPTS_ARE_SEPARATE"}
    return {**body, "snapshot_hash": canonical_hash(body)}


def validate_provider_request_snapshot(snapshot, *, identity, envelope_hash):
    if (not isinstance(snapshot, Mapping) or snapshot.get("version") != "provider-request-snapshot.v1"
            or snapshot.get("snapshot_hash") != canonical_hash({key: value for key, value in snapshot.items() if key != "snapshot_hash"})):
        raise ValueError("PROVIDER_REQUEST_SNAPSHOT_INVALID")
    envelope = ProviderRequestEnvelope(**snapshot["envelope"])
    if (envelope.to_identity_dict() != identity or envelope.envelope_hash != envelope_hash
            or snapshot.get("envelope_hash") != envelope_hash):
        raise ValueError("PROVIDER_REQUEST_SNAPSHOT_IDENTITY_DRIFT")
    return envelope


def admission_with_request_snapshot(contract, *, stage, frozen_inputs, envelope, frozen_context=None):
    if not request_snapshot_required(stage, {"frozen_inputs": frozen_inputs, "frozen_context": frozen_context}):
        return dict(contract)
    return {**contract, "schema_version": "novelos.provider_request_admission.v2",
        "provider_request_snapshot": freeze_provider_request(envelope)}
