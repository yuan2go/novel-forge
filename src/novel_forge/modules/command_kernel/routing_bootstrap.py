from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from novel_forge.storage.versioned_policy_repository import policy_hash

from .errors import KernelError


SOURCE_BOOTSTRAP_TASKS = {
    "source.import.document.profile": "source.content.classify",
    "source.import.deconstruction.execute": "source.deconstruction.observe",
    "source.import.mkaos.extract": "source.mkaos.extract",
}

CHAPTER_GENERATOR_TASKS = {
    "chapter.memo.generate": "memo",
    "chapter.draft.generate": "draft",
    "chapter.revision.apply": "revision",
    "chapter.canon.extract": "canon_extraction",
}
CHAPTER_REFERENCE_TASKS = {
    "chapter.canon.propose_changes": "canon_support",
    "chapter.review.evaluate": "review",
    "chapter.revision.review": "rereview",
    **{"chapter.quality." + group + ".evaluate": "quality_" + group
       for group in ("structural", "commercial", "source_originality", "longform", "platform")},
}
CHAPTER_BOOTSTRAP_TASKS = {**CHAPTER_GENERATOR_TASKS, **CHAPTER_REFERENCE_TASKS}
CHAPTER_LEGACY_SAMPLE_DEFINITION_VERSION = "1.0.0"
CHAPTER_SAMPLE_DEFINITION_VERSION = "2.4.0"
CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE = "book:chapter-provider-sample"
CHAPTER_SAMPLE_SOURCE_VERSION = "3.4.1"
SCREENPLAY_SAMPLE_TASKS = {"screenplay_generate", "screenplay_review", "screenplay_revision"}
WORLD_SAMPLE_TASKS = {"world_candidates.generate", "world_candidates.evaluate", *("world_candidates.actor_" + str(index) for index in range(3))}
WORLD_SAMPLE_IDEMPOTENCY_SCOPE = "book:world-provider-sample"
WORLD_SAMPLE_DEFINITION_VERSION = "1.0.0"
PLANNING_BOOTSTRAP_SOURCE_VERSIONS = frozenset({"1.16.0", "1.17.0", "1.18.0", "1.19.0"})
CHAPTER_LEGACY_REFERENCE_SAMPLE_VERSION = "1.1.0"
CHAPTER_REFERENCE_SAMPLE_VERSION = "2.5.0"
CHAPTER_REFERENCE_SAMPLE_SOURCES = {"review": "chapter.draft.generate", "rereview": "chapter.revision.apply"}

CHAPTER_SAMPLE_DEFINITION_VERSIONS = frozenset({CHAPTER_LEGACY_SAMPLE_DEFINITION_VERSION, "2.0.0", "2.2.0", CHAPTER_SAMPLE_DEFINITION_VERSION})
CHAPTER_REFERENCE_SAMPLE_VERSIONS = frozenset({CHAPTER_LEGACY_REFERENCE_SAMPLE_VERSION, "2.1.0", "2.3.0", CHAPTER_REFERENCE_SAMPLE_VERSION})
CHAPTER_SAMPLE_READABLE_VERSIONS = tuple(sorted(CHAPTER_SAMPLE_DEFINITION_VERSIONS | CHAPTER_REFERENCE_SAMPLE_VERSIONS))


def chapter_sample_definition_supported(name: str, version: str, *, reference_samples: bool | None = None) -> bool:
    ordinary = version in CHAPTER_SAMPLE_DEFINITION_VERSIONS and name in {
        chapter_sample_definition_name(stage) for stage in CHAPTER_BOOTSTRAP_TASKS.values()
    }
    reference = version in CHAPTER_REFERENCE_SAMPLE_VERSIONS and name in {
        chapter_sample_definition_name(stage) for stage in CHAPTER_REFERENCE_SAMPLE_SOURCES
    }
    return reference if reference_samples is True else ordinary if reference_samples is False else ordinary or reference


def chapter_sample_source_version_supported(version: Any) -> bool:
    from novel_forge.modules.chapter_authority.definitions import CHAPTER_MODEL_EFFECT_DEFINITION_VERSION, CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS

    return isinstance(version, str) and version in {CHAPTER_MODEL_EFFECT_DEFINITION_VERSION, *CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS, "3.8.0-author-input.v2", "3.9.0-author-input.v2"}


def chapter_sample_definition_name(task_type: str) -> str:
    if task_type not in CHAPTER_BOOTSTRAP_TASKS.values():
        raise ValueError("CHAPTER_SAMPLE_TASK_UNSUPPORTED")
    return "chapter.provider.sample." + task_type


def authorization_hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def bootstrap_command_hash(payload: Mapping[str, Any]) -> str:
    return authorization_hash(
        {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "routing_bootstrap_authorization",
                "routing_bootstrap_authorization_id",
            }
        }
    )


def validate_bootstrap_authorization(grant: Mapping[str, Any]) -> None:
    strings = {
        "authorization_id",
        "reason",
        "environment",
        "book_id",
        "task_type",
        "logical_key",
        "generation_idempotency_key",
        "input_versions_hash",
        "command_hash",
        "candidate_id",
        "model_revision",
        "expires_at",
        "currency",
        "purpose",
    }
    if set(grant) - {"campaign", "reference_evaluation", "model_reference", "producer_contract_hash", "accounting_basis", "cost_authorization_ref"} != strings | {
        "maximum_calls",
        "maximum_tokens",
        "maximum_amount",
        "production_eligible",
    }:
        raise ValueError("ROUTING_BOOTSTRAP_CONTRACT_INVALID")
    if any(
        not isinstance(grant[key], str) or not grant[key].strip() for key in strings
    ):
        raise ValueError("ROUTING_BOOTSTRAP_IDENTITY_REQUIRED")
    if (
        grant["environment"] != "validation"
        or grant["purpose"] not in {"BENCHMARK_CHALLENGER", "REFERENCE_EVALUATION", "MODEL_REFERENCE_CREATION"}
        or grant["production_eligible"] is not False
    ):
        raise ValueError("ROUTING_BOOTSTRAP_BOUNDARY_INVALID")
    basis = grant.get("accounting_basis", "PRICED")
    if basis == "ACCOUNT_ENTITLEMENT":
        if (grant["maximum_amount"] is not None or grant["currency"] != "UNKNOWN"
            or not isinstance(grant.get("cost_authorization_ref"), str)
            or not grant["cost_authorization_ref"].strip() or "campaign" not in grant):
            raise ValueError("ROUTING_BOOTSTRAP_ENTITLEMENT_INVALID")
        amount = None
    elif basis == "PRICED":
        if (not isinstance(grant["maximum_amount"], str) or not grant["maximum_amount"].strip()
            or grant["currency"] != "USD" or "cost_authorization_ref" in grant):
            raise ValueError("ROUTING_BOOTSTRAP_ACCOUNTING_INVALID")
        amount = Decimal(grant["maximum_amount"])
        if not amount.is_finite() or amount <= 0:
            raise ValueError("ROUTING_BOOTSTRAP_LIMIT_INVALID")
    else:
        raise ValueError("ROUTING_BOOTSTRAP_ACCOUNTING_INVALID")
    reference = grant.get("reference_evaluation")
    model_reference = grant.get("model_reference")
    if grant["purpose"] == "REFERENCE_EVALUATION":
        if model_reference is not None:
            raise ValueError("ROUTING_REFERENCE_SCOPE_INVALID")
        if grant["task_type"] not in {"narrative_semantic_evaluation", "world_candidates.evaluate", "longform_prose_review", "screenplay_review", *CHAPTER_REFERENCE_TASKS.values()} or "campaign" not in grant:
            raise ValueError("ROUTING_REFERENCE_SCOPE_INVALID")
        validate_reference_evaluation_binding(reference)
        adjudications_required = (grant["task_type"] in {*CHAPTER_REFERENCE_TASKS.values(), "world_candidates.evaluate"}
            or reference.get("basis") == "MODEL_CONSENSUS" and grant["task_type"] == "narrative_semantic_evaluation")
        if adjudications_required != ("adjudications" in reference):
            raise ValueError("ROUTING_REFERENCE_SCOPE_INVALID")
    elif grant["purpose"] == "MODEL_REFERENCE_CREATION":
        if (reference is not None or grant["task_type"] not in {"model_reference_evaluate", "model_reference_adjudicate"}
            or "campaign" not in grant):
            raise ValueError("ROUTING_MODEL_REFERENCE_SCOPE_INVALID")
        validate_model_reference_creation_binding(model_reference)
        if model_reference["producer_contract_hash"] != grant.get("producer_contract_hash"):
            raise ValueError("ROUTING_MODEL_REFERENCE_PRODUCER_INVALID")
        expected_role = ("BLIND_EVALUATION" if grant["task_type"] == "model_reference_evaluate" else "ADJUDICATION")
        if model_reference["role"] != expected_role:
            raise ValueError("ROUTING_MODEL_REFERENCE_SCOPE_INVALID")
    elif reference is not None or model_reference is not None or grant["task_type"] in {"narrative_semantic_evaluation", "world_candidates.evaluate", "longform_prose_review", "screenplay_review", *CHAPTER_REFERENCE_TASKS.values()}:
        raise ValueError("ROUTING_REFERENCE_AUTHORIZATION_REQUIRED")
    if grant["task_type"] in SOURCE_BOOTSTRAP_TASKS.values() and "campaign" not in grant:
        raise ValueError("ROUTING_SOURCE_CAMPAIGN_REQUIRED")
    if grant["task_type"] in CHAPTER_BOOTSTRAP_TASKS.values() and "campaign" not in grant:
        raise ValueError("ROUTING_CHAPTER_CAMPAIGN_REQUIRED")
    if grant["task_type"] in SCREENPLAY_SAMPLE_TASKS and "campaign" not in grant:
        raise ValueError("ROUTING_SCREENPLAY_CAMPAIGN_REQUIRED")
    if grant["task_type"] in WORLD_SAMPLE_TASKS and "campaign" not in grant:
        raise ValueError("ROUTING_WORLD_CAMPAIGN_REQUIRED")
    if any(
        type(grant[key]) is not int or grant[key] <= 0
        for key in ("maximum_calls", "maximum_tokens")
    ):
        raise ValueError("ROUTING_BOOTSTRAP_QUOTA_INVALID")
    if datetime.fromisoformat(grant["expires_at"]).tzinfo is None:
        raise ValueError("ROUTING_BOOTSTRAP_LIMIT_INVALID")
    for digest in (grant["input_versions_hash"], grant["command_hash"], *(
        (grant["producer_contract_hash"],) if "producer_contract_hash" in grant else ()
    )):
        if (
            not isinstance(digest, str) or len(digest) != 71
            or not digest.startswith("sha256:")
            or any(c not in "0123456789abcdef" for c in digest[7:])
        ):
            raise ValueError("ROUTING_BOOTSTRAP_INPUT_IDENTITY_INVALID")
    if "campaign" in grant:
        validate_bootstrap_campaign(grant["campaign"])
        campaign = grant["campaign"]
        if (
            grant["maximum_calls"] > campaign["maximum_calls"]
            or grant["maximum_tokens"] > campaign["maximum_tokens"]
            or amount is not None and amount > Decimal(campaign["maximum_amount"])
            or datetime.fromisoformat(grant["expires_at"])
            > datetime.fromisoformat(campaign["expires_at"])
        ):
            raise ValueError("ROUTING_CAMPAIGN_GRANT_EXCEEDS_TOTAL")


def bootstrap_candidate_accounting_matches(grant: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    pricing = candidate.get("pricing") or {}
    basis = grant.get("accounting_basis", "PRICED")
    if pricing.get("accounting_basis") != basis or pricing.get("currency") != grant["currency"]:
        return False
    if basis == "ACCOUNT_ENTITLEMENT":
        from novel_forge.modules.production_execution.cost_routing import authorized_codex_entitlement
        return (authorized_codex_entitlement(candidate)
                and candidate.get("authorization_ref") == grant["cost_authorization_ref"])
    return candidate.get("provider") == "deepseek"


def validate_bootstrap_producer(
    grant: Mapping[str, Any], task: Mapping[str, Any], *, require_bound: bool = True,
) -> None:
    expected = grant.get("producer_contract_hash")
    if not expected and not require_bound:
        return
    contract = task.get("producer_contract")
    if (not expected or not isinstance(contract, Mapping) or not contract
        or task.get("producer_contract_hash") != expected
        or authorization_hash(contract) != expected):
        raise KernelError(
            "ROUTING_BOOTSTRAP_PRODUCER_DRIFT",
            "sampling requires the producer contract frozen before authorization",
        )


def validate_reference_evaluation_binding(reference: Any) -> None:
    if isinstance(reference, Mapping) and "basis" in reference:
        if (set(reference) != {"basis", "protocol_version", "adjudications"}
            or reference["basis"] != "MODEL_CONSENSUS"
            or reference["protocol_version"] != "model-reference-consensus.v1"
            or not isinstance(reference["adjudications"], list)
            or not reference["adjudications"]):
            raise ValueError("ROUTING_REFERENCE_BINDING_INVALID")
        validate_reference_evaluation_binding({
            "protocol_version": reference["protocol_version"],
            "adjudications": reference["adjudications"],
        })
        return
    if isinstance(reference, Mapping) and "adjudicated_reference" in reference:
        native = reference["adjudicated_reference"]
        if (set(reference) != {"asset_version_id", "content_hash", "protocol_version", "adjudicated_reference"}
            or not isinstance(native, Mapping) or set(native) != {"adjudications", "scope"}
            or not isinstance(native["scope"], Mapping) or set(native["scope"]) != {"scope_type", "chapter_start", "chapter_end"}):
            raise ValueError("ROUTING_REFERENCE_BINDING_INVALID")
        scope = native["scope"]
        if (scope["scope_type"] not in {"CHAPTER", "ARC"}
            or any(type(scope[key]) is not int or scope[key] <= 0 for key in ("chapter_start", "chapter_end"))
            or scope["chapter_start"] > scope["chapter_end"]
            or (scope["scope_type"] == "CHAPTER" and scope["chapter_start"] != scope["chapter_end"])):
            raise ValueError("ROUTING_REFERENCE_BINDING_INVALID")
        validate_reference_evaluation_binding({key: value for key, value in reference.items() if key != "adjudicated_reference"})
        validate_reference_evaluation_binding({"protocol_version": reference["protocol_version"], "adjudications": native["adjudications"]})
        return
    if isinstance(reference, Mapping) and "adjudications" in reference:
        if set(reference) != {"protocol_version", "adjudications"} or not isinstance(reference["protocol_version"], str) or not reference["protocol_version"].strip():
            raise ValueError("ROUTING_REFERENCE_BINDING_INVALID")
        entries = reference["adjudications"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("ROUTING_REFERENCE_BINDING_INVALID")
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry) != {"asset_version_id", "content_hash"}:
                raise ValueError("ROUTING_REFERENCE_BINDING_INVALID")
            validate_reference_evaluation_binding({**entry, "protocol_version": reference["protocol_version"]})
        if len({item["asset_version_id"] for item in entries}) != len(entries):
            raise ValueError("ROUTING_REFERENCE_BINDING_INVALID")
        return
    if not isinstance(reference, Mapping) or set(reference) != {
        "asset_version_id", "content_hash", "protocol_version",
    } or any(not isinstance(value, str) or not value.strip() for value in reference.values()):
        raise ValueError("ROUTING_REFERENCE_BINDING_INVALID")
    digest = reference["content_hash"]
    if len(digest) != 71 or not digest.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in digest[7:]
    ):
        raise ValueError("ROUTING_REFERENCE_HASH_INVALID")


def validate_model_reference_creation_binding(binding: Any) -> None:
    required = {"subject", "author_baseline", "policy_hash", "producer_contract_hash",
                "protocol_version", "evaluation_version", "dimension", "scope", "role"}
    if not isinstance(binding, Mapping) or set(binding) not in (required, required | {"source_evaluations"}):
        raise ValueError("ROUTING_MODEL_REFERENCE_BINDING_INVALID")
    if (binding["protocol_version"] != "model-reference-consensus.v1"
        or binding["role"] not in {"BLIND_EVALUATION", "ADJUDICATION"}
        or any(not isinstance(binding[key], str) or not binding[key].strip()
               for key in ("evaluation_version", "dimension"))):
        raise ValueError("ROUTING_MODEL_REFERENCE_BINDING_INVALID")
    scope = binding["scope"]
    chapter_scope = (isinstance(scope, Mapping)
        and set(scope) == {"scope_type", "chapter_start", "chapter_end"}
        and scope["scope_type"] == "CHAPTER"
        and type(scope["chapter_start"]) is int and scope["chapter_start"] > 0
        and scope["chapter_end"] == scope["chapter_start"])
    book_scope = (isinstance(scope, Mapping)
        and set(scope) == {"scope_type", "book_id"}
        and scope["scope_type"] == "BOOK"
        and isinstance(scope["book_id"], str) and bool(scope["book_id"].strip()))
    if not (chapter_scope or book_scope):
        raise ValueError("ROUTING_MODEL_REFERENCE_BINDING_INVALID")
    for key in ("subject", "author_baseline"):
        validate_reference_evaluation_binding({**binding[key], "protocol_version": binding["protocol_version"]})
    for key in ("policy_hash", "producer_contract_hash"):
        digest = binding[key]
        if (not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in digest[7:])):
            raise ValueError("ROUTING_MODEL_REFERENCE_BINDING_INVALID")
    sources = binding.get("source_evaluations")
    if binding["role"] == "BLIND_EVALUATION":
        if sources is not None:
            raise ValueError("ROUTING_MODEL_REFERENCE_BLINDNESS_INVALID")
    elif not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("ROUTING_MODEL_REFERENCE_SOURCES_INVALID")
    else:
        for source in sources:
            validate_reference_evaluation_binding({**source, "protocol_version": binding["protocol_version"]})
        if sources[0]["asset_version_id"] == sources[1]["asset_version_id"]:
            raise ValueError("ROUTING_MODEL_REFERENCE_SOURCES_INVALID")


def validate_bootstrap_campaign(campaign: Mapping[str, Any]) -> None:
    if not isinstance(campaign, Mapping) or set(campaign) != {
        "campaign_id", "manifest_hash", "sample_id", "group_id", "partition",
        "maximum_calls", "maximum_tokens", "maximum_amount", "expires_at",
    }:
        raise ValueError("ROUTING_CAMPAIGN_CONTRACT_INVALID")
    for key in ("campaign_id", "sample_id", "group_id", "manifest_hash", "expires_at", "maximum_amount"):
        if not isinstance(campaign[key], str) or not campaign[key].strip():
            raise ValueError("ROUTING_CAMPAIGN_IDENTITY_REQUIRED")
    digest = campaign["manifest_hash"]
    if len(digest) != 71 or not digest.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in digest[7:]
    ):
        raise ValueError("ROUTING_CAMPAIGN_MANIFEST_IDENTITY_INVALID")
    if campaign["partition"] not in {"DEVELOPMENT", "CALIBRATION", "HOLDOUT"}:
        raise ValueError("ROUTING_CAMPAIGN_PARTITION_INVALID")
    if any(type(campaign[key]) is not int or campaign[key] <= 0
           for key in ("maximum_calls", "maximum_tokens")):
        raise ValueError("ROUTING_CAMPAIGN_QUOTA_INVALID")
    amount = Decimal(campaign["maximum_amount"])
    if not amount.is_finite() or amount < 0 or datetime.fromisoformat(
        campaign["expires_at"]
    ).tzinfo is None:
        raise ValueError("ROUTING_CAMPAIGN_LIMIT_INVALID")


def campaign_contract(campaign: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in campaign.items()
            if key not in {"sample_id", "group_id", "partition"}}


def validate_bootstrap_history(
    grants: list[Mapping[str, Any]], previous: list[Mapping[str, Any]],
    *, authorized_campaign_contracts: tuple[Mapping[str, Any], ...] = (),
) -> None:
    identities: dict[str, Mapping[str, Any]] = {}
    campaigns: dict[str, Mapping[str, Any]] = {}
    groups: dict[tuple[str, str], str] = {}
    samples: dict[tuple[str, str], tuple[Any, ...]] = {}
    inputs: dict[tuple[str, str], tuple[str, str]] = {}
    for grant in [*previous, *grants]:
        key = grant["authorization_id"]
        if key in identities and identities[key] != grant:
            raise KernelError("ROUTING_BOOTSTRAP_AUTHORIZATION_REDEFINED",
                              "an authorization retains its original scope and quota")
        identities[key] = grant
        campaign = grant.get("campaign")
        if campaign is None:
            continue
        identity = campaign["campaign_id"]
        contract = campaign_contract(campaign)
        if (identity in campaigns and campaigns[identity] != contract
            and not (campaigns[identity] in authorized_campaign_contracts and contract in authorized_campaign_contracts)):
            raise KernelError("ROUTING_CAMPAIGN_REDEFINED",
                              "a campaign retains its frozen manifest and cumulative quota")
        campaigns[identity] = contract
        group = (identity, campaign["group_id"])
        partition = campaign["partition"]
        if group in groups and groups[group] != partition:
            raise KernelError("ROUTING_CAMPAIGN_HOLDOUT_LEAKAGE",
                              "a data group cannot cross experiment partitions")
        groups[group] = partition
        sample = (identity, campaign["sample_id"])
        binding = (campaign["group_id"], grant["task_type"], grant["input_versions_hash"],
                   grant.get("producer_contract_hash"), grant.get("reference_evaluation"), grant.get("model_reference"))
        if sample in samples and samples[sample] != binding:
            raise KernelError("ROUTING_CAMPAIGN_SAMPLE_REDEFINED",
                              "a sample retains its data group, task, producer and input versions")
        samples[sample] = binding
        source = (identity, grant["input_versions_hash"])
        if source in inputs and inputs[source][1] != partition:
            raise KernelError("ROUTING_CAMPAIGN_HOLDOUT_LEAKAGE",
                              "identical inputs cannot acquire a new partition by renaming")
        if source in inputs and inputs[source][0] != campaign["group_id"]:
            raise KernelError("ROUTING_CAMPAIGN_INPUT_GROUP_REDEFINED",
                              "identical inputs cannot become independent by renaming their data group")
        inputs[source] = (campaign["group_id"], partition)
    if len(campaigns) > 1:
        raise KernelError("ROUTING_CAMPAIGN_PROJECT_REBIND_FORBIDDEN",
                          "a campaign project cannot reset usage by changing campaign identity")
    historical_ids = {grant["authorization_id"] for grant in previous}
    if campaigns and any(not grant.get("campaign") and grant["authorization_id"] not in historical_ids
                         for grant in grants):
        raise KernelError("ROUTING_CAMPAIGN_MEMBERSHIP_REQUIRED",
                          "new sampling grants must retain the project's campaign budget")


def validate_bootstrap_policy_in_uow(
    cursor: Any, *, project_id: str, content: Mapping[str, Any]
) -> None:
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ["routing-bootstrap-policy:" + project_id],
    )
    cursor.execute(
        "SELECT content,content_hash FROM authority_runtime_policy_version WHERE owner='PROVIDER_ROUTING' AND project_id=%s",
        [project_id],
    )
    previous = []
    for policy, digest in cursor.fetchall():
        if policy_hash(policy) != digest:
            raise KernelError("RUNTIME_POLICY_HASH_MISMATCH", "policy integrity failed")
        previous.extend(policy.get("bootstrap_authorizations", []))
    from .creative_budget_runtime import provider_campaign_contract_lineage

    validate_bootstrap_history(list(content.get("bootstrap_authorizations", [])), previous,
                               authorized_campaign_contracts=provider_campaign_contract_lineage(cursor, project_id))


def validate_bootstrap_scope(
    snapshot: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    check_expiry: bool = True,
) -> Mapping[str, Any]:
    try:
        grant = snapshot["authorization"]
        validate_bootstrap_authorization(grant)
        if (
            snapshot["authorization_hash"] != authorization_hash(grant)
            or snapshot["project_id"] != payload["project_id"]
            or snapshot["environment"] != "validation"
        ):
            raise ValueError("snapshot identity differs")
        expected = {
            "authorization_id": payload.get("routing_bootstrap_authorization_id"),
            "book_id": payload.get("book_id"),
            "task_type": "narrative_semantic_evaluation" if payload.get("reference_evaluation") and not (payload.get("chapter_sampling") or payload.get("world_sampling") or payload.get("prose_sampling") or payload.get("screenplay_sampling")) else payload.get("generator_operation_name"),
            "logical_key": payload.get("logical_key"),
            "generation_idempotency_key": payload.get("idempotency_key"),
            "input_versions_hash": authorization_hash(payload.get("input_versions")),
            "command_hash": bootstrap_command_hash(payload),
        }
        if any(grant[key] != value for key, value in expected.items()):
            raise ValueError("command identity differs")
        if grant.get("reference_evaluation") != payload.get("reference_evaluation"):
            raise ValueError("reference identity differs")
        if grant.get("model_reference") != payload.get("model_reference"):
            raise ValueError("model reference identity differs")
    except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
        raise KernelError(
            "ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
            "benchmark authorization does not match its admitted task",
        ) from exc
    if check_expiry and datetime.now(timezone.utc) >= datetime.fromisoformat(
        grant["expires_at"]
    ):
        raise KernelError(
            "ROUTING_BOOTSTRAP_EXPIRED", "benchmark authorization has expired"
        )
    return grant


def validate_chapter_sample_origin(
    payload: Mapping[str, Any], origin: Any, *, project_id: str,
) -> None:
    try:
        if not origin or len(origin) != 4:
            raise ValueError("source operation is absent")
        definition, version, command, inputs = origin
        sample_binding = (payload.get("chapter_sampling") or {}).get("generation_sample")
        expected_stage = payload.get("generator_operation_name") if sample_binding is not None else CHAPTER_BOOTSTRAP_TASKS.get(definition)
        if sample_binding is not None and CHAPTER_REFERENCE_SAMPLE_SOURCES.get(expected_stage) != definition:
            raise ValueError("reference sample uses the wrong generator task")
        expected_inputs = [*inputs, sample_binding] if sample_binding is not None else inputs
        metadata = {
            "project_id", "generator_operation_name", "logical_key", "idempotency_key",
            "input_versions", "chapter_sampling", "chapter_predecessor_operation_id",
            "routing_bootstrap_authorization_id",
        }
        if "routing_bootstrap_authorization" in payload:
            metadata.add("routing_bootstrap_authorization")
        if "reference_evaluation" in payload:
            metadata.add("reference_evaluation")
        if (
            definition not in CHAPTER_BOOTSTRAP_TASKS or not chapter_sample_source_version_supported(version)
            or not isinstance(command, Mapping) or not command.get("book_id")
            or any(key in command for key in ("chapter_sampling", "routing_bootstrap_authorization_id"))
            or payload.get("project_id") != project_id
            or payload.get("generator_operation_name") != expected_stage
            or payload.get("input_versions") != expected_inputs
            or payload.get("chapter_sampling") != {
                "source_operation_id": payload.get("logical_key"),
                "source_command_hash": authorization_hash(command),
                **({"generation_sample": sample_binding} if sample_binding is not None else {}),
            }
            or payload != {**command, **{key: payload[key] for key in metadata}}
        ):
            raise ValueError("frozen source contract differs")
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
                          "Chapter sample differs from its frozen native task") from exc


def validate_world_sample_origin(cursor: Any, *, project_id: str, operation_id: str,
                                 payload: Mapping[str, Any]) -> None:
    metadata = payload["world_sampling"]
    cursor.execute("""SELECT definition_name,definition_version,command_payload->'payload',input_asset_snapshot
        FROM authority_operation WHERE project_id=%s AND operation_id=%s""", [project_id, metadata.get("source_operation_id")])
    origin = cursor.fetchone()
    if (not origin or origin[0] != "story_planning.generate" or origin[1] not in PLANNING_BOOTSTRAP_SOURCE_VERSIONS
        or origin[2].get("generator_operation_name") != "chapter_plan.generate"
        or not origin[2].get("world_preparation_request") or origin[2].get("routing_bootstrap_authorization_id")
        or origin[2].get("book_id") != payload.get("book_id")
        or metadata.get("source_operation_id") != payload.get("logical_key")
        or metadata.get("source_command_hash") != authorization_hash(origin[2])):
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World sample must bind its original native ChapterPlan")
    frozen_context = {}
    for kind, asset_type in (("context", "context_bundle"), ("source", "world_preparation_source")):
        binding = metadata.get(kind) or {}
        cursor.execute("""SELECT version.content FROM authority_operation_output_asset output
            JOIN authority_asset_version version USING(asset_version_id)
            JOIN authority_asset asset ON asset.asset_id=version.asset_id
            WHERE output.operation_id=%s AND asset.project_id=%s AND asset.asset_type=%s
              AND output.asset_version_id=%s AND output.content_hash=%s AND version.content_hash=output.content_hash
              AND version.lifecycle='ACTIVE' AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'""",
            [metadata["source_operation_id"], project_id, asset_type, binding.get("asset_version_id"), binding.get("content_hash")])
        rows = cursor.fetchall()
        if len(rows) != 1 or authorization_hash(rows[0][0]) != binding.get("content_hash"):
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World sample evidence differs from its native origin")
        context_hash = metadata.get("base_stage_hash") if metadata.get("generation_sample") else metadata.get("stage_hash")
        if kind == "context" and authorization_hash(rows[0][0].get("world_preparation")) != context_hash:
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World sample role task differs from frozen Context")
        if kind == "context":
            frozen_context = rows[0][0]["world_preparation"]
    cursor.execute("SELECT input_snapshot,input_snapshot_hash FROM authority_story_planning_generation WHERE project_id=%s AND operation_id=%s",
                   [project_id, metadata["source_operation_id"]])
    typed = cursor.fetchone()
    if not typed or typed[1] != authorization_hash(typed[0]):
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World source lacks its immutable typed Planning inputs")
    expected_inputs = [{key: item[key] for key in ("asset_version_id", "content_hash")} for item in typed[0]]
    for binding in (metadata["context"], metadata["source"]):
        if binding not in expected_inputs:
            expected_inputs.append(binding)
    if payload["generator_operation_name"] == "world_candidates.evaluate":
        if metadata.get("generation_sample"):
            from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject

            subject = require_reference_subject(cursor, project_id=project_id, binding=metadata["generation_sample"],
                allowed_types=frozenset({"world_provider_sample"}))
            if (subject["content"].get("source_operation_id") != metadata["source_operation_id"]
                or subject["content"].get("context") != metadata["context"]
                or subject["content"].get("source") != metadata["source"]
                or frozen_context.get("role") != "WORLD_REASONER"):
                raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World reference target must retain its generator origin")
            expected_inputs.append(metadata["generation_sample"])
        else:
            expected_inputs.append(frozen_context.get("generation_ref"))
    if payload.get("input_versions") != expected_inputs:
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World sample cannot replace or omit original Planning dependencies")
    cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s",
                   [project_id, operation_id])
    admitted = cursor.fetchone()
    fields = ("asset_version_id", "content_hash")
    if not admitted or [tuple(item.get(key) for key in fields) for item in admitted[0]] != [
        tuple(item.get(key) for key in fields) for item in payload.get("input_versions", [])]:
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World sample input bindings differ from its grant")


def load_bootstrap_authorization(
    cursor: Any, *, project_id: str, operation_id: str, check_expiry: bool = True
) -> Mapping[str, Any] | None:
    cursor.execute(
        "SELECT command_payload->'payload',definition_name,definition_version,idempotency_scope,idempotency_key FROM authority_operation WHERE project_id=%s AND operation_id=%s",
        [project_id, operation_id],
    )
    row = cursor.fetchone()
    payload = (row[0] if row else None) or {}
    snapshot = payload.get("routing_bootstrap_authorization")
    if not snapshot:
        if payload.get("routing_bootstrap_authorization_id"):
            raise KernelError(
                "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED",
                "admitted benchmark task lacks its immutable grant",
            )
        return None
    contract = (
        "story_design.semantic_evaluate", "1.0.0", "book:narrative-semantic-evaluation",
    ) if payload.get("reference_evaluation") else (
        "story_planning.generate",
        row[2] if row and row[2] in PLANNING_BOOTSTRAP_SOURCE_VERSIONS else "1.16.0",
        "book:story-planning-generation",
    )
    if payload.get("source_sampling"):
        contract = (row[1], "1.4.0", "project:source-import")
        if SOURCE_BOOTSTRAP_TASKS.get(row[1]) != payload.get("generator_operation_name"):
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "Source sampling requires its native task contract")
    if payload.get("chapter_sampling"):
        try:
            name = chapter_sample_definition_name(payload.get("generator_operation_name"))
            if not chapter_sample_definition_supported(name, row[2], reference_samples=payload["chapter_sampling"].get("generation_sample") is not None):
                raise ValueError("unsupported sample version")
            contract = (name, row[2], CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE)
        except ValueError as exc:
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "Chapter sampling requires its native task contract") from exc
    if payload.get("world_sampling"):
        stage = payload.get("generator_operation_name")
        if stage not in WORLD_SAMPLE_TASKS:
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World sampling requires its native task contract")
        reference_sample = payload["world_sampling"].get("generation_sample") is not None
        if reference_sample and stage != "world_candidates.evaluate":
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "only a reference evaluator may read a World generator sample")
        contract = ("world.provider.sample." + stage.rsplit(".", 1)[1], "1.1.0" if reference_sample else WORLD_SAMPLE_DEFINITION_VERSION,
                    WORLD_SAMPLE_IDEMPOTENCY_SCOPE)
    if payload.get("prose_sampling"):
        from novel_forge.modules.book_followup_authority.prose_sampling import PROSE_SAMPLE_DEFINITION, PROSE_SAMPLE_VERSION, PROSE_SAMPLE_SCOPE

        contract = (PROSE_SAMPLE_DEFINITION, PROSE_SAMPLE_VERSION, PROSE_SAMPLE_SCOPE)
    if payload.get("screenplay_sampling"):
        from novel_forge.modules.book_followup_authority.screenplay_sampling import sample_definition_name, SCREENPLAY_SAMPLE_VERSION, SCREENPLAY_SAMPLE_SCOPE
        contract = (sample_definition_name(payload.get("generator_operation_name")), SCREENPLAY_SAMPLE_VERSION, SCREENPLAY_SAMPLE_SCOPE)
    if payload.get("model_reference"):
        from novel_forge.modules.chapter_quality_authority.model_reference_execution import (
            MODEL_REFERENCE_ADJUDICATE, MODEL_REFERENCE_EVALUATE, MODEL_REFERENCE_EXECUTION_VERSION,
        )
        name = (MODEL_REFERENCE_EVALUATE if payload.get("generator_operation_name") == "model_reference_evaluate"
                else MODEL_REFERENCE_ADJUDICATE if payload.get("generator_operation_name") == "model_reference_adjudicate"
                else "")
        if not name:
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "model reference requires its formal task")
        contract = (name, MODEL_REFERENCE_EXECUTION_VERSION, "book:model-reference-creation")
    if tuple(row[1:4]) != contract or row[4] != payload.get("idempotency_key"):
        raise KernelError(
            "ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
            "benchmark authorization requires its exact admitted native operation contract",
        )
    grant = validate_bootstrap_scope(snapshot, payload, check_expiry=check_expiry)
    if grant["task_type"] in {"screenplay_generate", "screenplay_review", "screenplay_revision"} or payload.get("screenplay_sampling"):
        from novel_forge.modules.book_followup_authority.screenplay_sampling import validate_screenplay_sample_origin, sample_purpose
        if not payload.get("screenplay_sampling") or grant["purpose"] != sample_purpose(grant["task_type"]):
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "Screenplay grants require their exact native sampling task")
        validate_screenplay_sample_origin(cursor, project_id=project_id, payload=payload)
        cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project_id, operation_id])
        inputs = cursor.fetchone()
        if not inputs or inputs[0] != [{"project_id": project_id, **binding} for binding in payload["input_versions"]]:
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "Screenplay sample inputs differ from their frozen grant")
    if grant["task_type"] == "longform_prose_review" or payload.get("prose_sampling"):
        from novel_forge.modules.book_followup_authority.prose_sampling import validate_prose_sample_origin

        if grant["task_type"] != "longform_prose_review" or not payload.get("prose_sampling"):
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "prose reviewer grant requires its native sampling operation")
        validate_prose_sample_origin(cursor, project_id=project_id, payload=payload)
        cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project_id, operation_id])
        inputs = cursor.fetchone()
        if not inputs or inputs[0] != payload["input_versions"]:
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "prose sample input bindings differ from the grant")
    if grant["task_type"] in SOURCE_BOOTSTRAP_TASKS.values() and not payload.get("source_sampling"):
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "Source grant requires a Source sampling operation")
    if grant["task_type"] in CHAPTER_BOOTSTRAP_TASKS.values() and not payload.get("chapter_sampling"):
        raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "Chapter grant requires a Chapter sampling operation")
    if grant["task_type"] in WORLD_SAMPLE_TASKS:
        if not payload.get("world_sampling"):
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "World grant requires a World sampling operation")
        validate_world_sample_origin(cursor, project_id=project_id, operation_id=operation_id, payload=payload)
    if payload.get("chapter_sampling"):
        cursor.execute(
            "SELECT definition_name,definition_version,command_payload,input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s",
            [project_id, payload["chapter_sampling"].get("source_operation_id")],
        )
        origin = cursor.fetchone()
        validate_chapter_sample_origin(payload, origin, project_id=project_id)
        if row[2] in {CHAPTER_LEGACY_SAMPLE_DEFINITION_VERSION, CHAPTER_LEGACY_REFERENCE_SAMPLE_VERSION} and origin[1] != CHAPTER_SAMPLE_SOURCE_VERSION:
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "legacy samples require their original published source version")
        if payload["chapter_sampling"].get("generation_sample") is not None:
            from novel_forge.modules.chapter_quality_authority.reference_subject import require_chapter_sample_target

            require_chapter_sample_target(cursor, project_id=project_id, payload=payload)
        cursor.execute(
            "SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s",
            [project_id, operation_id],
        )
        admitted_inputs = cursor.fetchone()
        fields = ("asset_version_id", "content_hash")
        if not admitted_inputs or [
            tuple(item.get(field) for field in fields) for item in admitted_inputs[0]
        ] != [tuple(item.get(field) for field in fields) for item in payload["input_versions"]]:
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "Chapter sample input bindings differ from its authorized source")
    if payload.get("source_sampling"):
        source = payload["source_sampling"]
        cursor.execute(
            "SELECT definition_name,definition_version,command_payload->'payload',input_asset_snapshot FROM authority_operation WHERE project_id=%s AND operation_id=%s",
            [project_id, source.get("source_operation_id")],
        )
        origin = cursor.fetchone()
        if (
            not origin or tuple(origin[:2]) != tuple(row[1:3])
            or origin[2].get("routing_bootstrap_authorization_id")
            or source != {"source_operation_id": payload.get("logical_key"),
                          "source_command_hash": authorization_hash(origin[2])}
            or payload.get("book_id") != f"source-corpus:{project_id}"
            or grant["purpose"] != "BENCHMARK_CHALLENGER" or not grant.get("campaign")
            or payload.get("input_versions") != origin[3]
            or payload != {**origin[2], **{key: payload[key] for key in (
                "project_id", "book_id", "generator_operation_name", "logical_key", "idempotency_key",
                "input_versions", "source_sampling", "routing_bootstrap_authorization_id", "routing_bootstrap_authorization",
                "source_predecessor_operation_id",
            )}}
        ):
            raise KernelError("ROUTING_BOOTSTRAP_SCOPE_MISMATCH", "Source sample differs from its frozen original task")
    cursor.execute(
        "SELECT content,content_hash,actor_id,created_by_operation_id FROM authority_runtime_policy_version WHERE owner='PROVIDER_ROUTING' AND project_id=%s AND policy_version=%s",
        [project_id, snapshot.get("policy_version")],
    )
    policy = cursor.fetchone()
    if (
        not policy
        or policy_hash(policy[0]) != policy[1]
        or policy[1] != snapshot.get("policy_hash")
        or policy[2] != snapshot.get("policy_actor_id")
        or policy[3] != snapshot.get("policy_operation_id")
        or grant not in policy[0].get("bootstrap_authorizations", [])
    ):
        raise KernelError(
            "ROUTING_BOOTSTRAP_POLICY_INTEGRITY_FAILURE",
            "benchmark grant does not match its immutable policy version",
        )
    return snapshot


def _verified_effect(
    cursor: Any, *, external_effect_id: str, project_id: str, check_expiry: bool
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    cursor.execute(
        "SELECT operation_id,request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE external_effect_id=%s AND project_id=%s",
        [external_effect_id, project_id],
    )
    row = cursor.fetchone()
    if not row:
        return None
    decision = row[1] or {}
    snapshot = load_bootstrap_authorization(
        cursor, project_id=project_id, operation_id=row[0], check_expiry=check_expiry
    )
    if snapshot is None:
        if decision.get("status") == "BENCHMARK_SELECTED" or decision.get(
            "bootstrap_authorization"
        ):
            raise KernelError(
                "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED",
                "benchmark route lacks admitted authorization",
            )
        return None
    grant = snapshot["authorization"]
    candidate = (decision.get("selected") or {}).get("candidate") or {}
    task = decision.get("task") or {}
    validate_bootstrap_producer(grant, task, require_bound=check_expiry)
    if (
        decision.get("status") != "BENCHMARK_SELECTED"
        or decision.get("mode") != "BENCHMARK_CHALLENGER"
        or decision.get("production_eligible") is not False
        or decision.get("bootstrap_authorization") != snapshot
        or task.get("task_type") != grant["task_type"]
        or task.get("work_id") != grant["book_id"]
        or task.get("operation_id") != row[0]
        or task.get("project_id") != project_id
        or candidate.get("candidate_id") != grant["candidate_id"]
        or candidate.get("model_revision") != grant["model_revision"]
        or not bootstrap_candidate_accounting_matches(grant, candidate)
    ):
        raise KernelError(
            "ROUTING_BOOTSTRAP_DECISION_CONFLICT",
            "benchmark decision differs from its admitted authorization",
        )
    content = {
        key: value
        for key, value in decision.items()
        if key not in {"asset_version_id", "decision_id"}
    }
    if (
        decision.get("decision_id")
        != "routing-decision:" + authorization_hash(content)[7:]
    ):
        raise KernelError(
            "ROUTING_DECISION_INTEGRITY_FAILURE", "benchmark decision hash differs"
        )
    cursor.execute(
        """SELECT asset.asset_type,version.content,version.content_hash
           FROM authority_asset_version version JOIN authority_asset asset ON asset.asset_id=version.asset_id
           WHERE asset.project_id=%s AND version.asset_version_id=%s""",
        [project_id, decision.get("asset_version_id")],
    )
    persisted = cursor.fetchone()
    frozen_content = {
        key: value for key, value in decision.items() if key != "asset_version_id"
    }
    if (
        not persisted
        or persisted[0] != "routing_decision"
        or persisted[1] != frozen_content
        or persisted[2] != authorization_hash(frozen_content)
    ):
        raise KernelError(
            "ROUTING_DECISION_INTEGRITY_FAILURE",
            "benchmark decision differs from its immutable routing asset",
        )
    return snapshot, grant


def verify_routing_bootstrap_budget(
    cursor: Any, request: Any, amount: Decimal | None, *, check_usage: bool = True
) -> None:
    verified = _verified_effect(
        cursor,
        external_effect_id=request.external_effect_id,
        project_id=request.project_id,
        check_expiry=check_usage,
    )
    if verified is None:
        return
    _, grant = verified
    basis = grant.get("accounting_basis", "PRICED")
    entitlement = basis == "ACCOUNT_ENTITLEMENT"
    if (request.accounting_basis != basis or request.currency != grant["currency"]
        or entitlement and (amount is not None or request.provider != "codex-cli"
                            or request.cost_authorization_ref != grant["cost_authorization_ref"])
        or not entitlement and (amount is None or request.provider != "deepseek")):
        raise KernelError(
            "ROUTING_BOOTSTRAP_ACCOUNTING_INVALID",
            "benchmark accounting must retain its exact authorized Provider lane",
        )
    if entitlement:
        from .creative_budget_runtime import require_provider_campaign_entitlement

        require_provider_campaign_entitlement(cursor, project_id=request.project_id, grant=grant)
    if not check_usage:
        return
    from .budget_runtime import provider_usage_accounted_sql

    prefix = ["_production_execution", "capability_runtime", "routing_decision",
              "bootstrap_authorization", "authorization"]
    scopes = [(grant, prefix + ["authorization_id"], grant["authorization_id"], "BOOTSTRAP")]
    if campaign := grant.get("campaign"):
        scopes.append((campaign, prefix + ["campaign", "campaign_id"], campaign["campaign_id"], "CAMPAIGN"))
    for quota, path, identity, label in scopes:
        cursor.execute(
            f"""SELECT count(*),COALESCE(sum(CASE WHEN b.accounting_basis='PRICED' THEN
                greatest(COALESCE((b.evidence->>'actual_amount')::numeric,0),
                    CASE WHEN b.status='SETTLED' THEN b.settled_amount ELSE b.reserved_amount END) ELSE 0 END),0),
                COALESCE(sum(greatest(b.actual_tokens,COALESCE((b.evidence->>'actual_tokens')::bigint,0),
                    CASE WHEN b.status='SETTLED' THEN 0 ELSE b.estimated_tokens END)),0),
                bool_or(b.status IN ('RESERVED','HELD_UNKNOWN'))
            FROM (SELECT * FROM authority_budget_reservation WHERE {provider_usage_accounted_sql()}) b JOIN authority_external_effect e USING(external_effect_id)
            WHERE b.project_id=%s AND e.request_payload #>> %s::text[]=%s""",
            [request.project_id, path, identity],
        )
        calls, spent, tokens, pending = cursor.fetchone()
        cursor.execute(
            """SELECT EXISTS (
                SELECT 1 FROM authority_budget_reservation b
                JOIN authority_external_effect e USING(external_effect_id)
                WHERE b.project_id=%s AND b.status<>'REJECTED'
                  AND e.status IN ('UNKNOWN','SENT_UNKNOWN','UNKNOWN_AMBIGUOUS','RECONCILIATION_REQUIRED')
                  AND e.request_payload #>> %s::text[]=%s
            )""",
            [request.project_id, path, identity],
        )
        unknown = bool(cursor.fetchone()[0])
        if pending or unknown:
            raise KernelError(
                f"ROUTING_{label}_RECONCILIATION_REQUIRED",
                "earlier benchmark execution must resolve first",
            )
        if (
            int(calls) + 1 > quota["maximum_calls"]
            or int(tokens) + request.estimated_tokens > quota["maximum_tokens"]
            or quota["maximum_amount"] is not None
            and Decimal(spent) + (amount if amount is not None else Decimal(0)) > Decimal(quota["maximum_amount"])
        ):
            raise KernelError(
                f"ROUTING_{label}_QUOTA_EXCEEDED",
                "cumulative benchmark authorization quota would be exceeded",
            )


def verify_routing_bootstrap_dispatch(
    cursor: Any, *, external_effect_id: str, project_id: str
) -> None:
    _verified_effect(
        cursor,
        external_effect_id=external_effect_id,
        project_id=project_id,
        check_expiry=True,
    )
