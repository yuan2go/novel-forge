from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft import (
    CRAFT_ORIGINAL_POLICY, craft_candidate, craft_hash, craft_semantic_hash, require_core_mechanism, validate_craft_mechanism,
)
from novel_forge.modules.mkaos_authority.definitions import (
    MKAOS_CRAFT_AUTHOR_DEFINITION_VERSION, MKAOS_CRAFT_AUTHOR_HANDLER_KEY, MKAOS_CRAFT_AUTHOR_OPERATION,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.mkaos_authority_repositories import MkaosAuthorityRepository


@dataclass(frozen=True, slots=True)
class AuthorCoreCraftCommand:
    project_id: str
    workspace_id: str
    mechanism_id: str
    catalog_hash: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    supersedes_card_asset_version_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.supersedes_card_asset_version_id, str) or len(self.supersedes_card_asset_version_id) > 1000:
            raise ValueError("Original Craft predecessor must be a bounded Card identity")
        if any(not isinstance(getattr(self, name), str) or not getattr(self, name).strip()
               for name in self.__dataclass_fields__ if name != "supersedes_card_asset_version_id"):
            raise ValueError("Original Craft authoring requires explicit identity and reviewed catalog hash")


def validate_craft_lineage(cursor: Any, project_id: str, candidate: Mapping[str, Any], observation_ids: tuple[str, ...], *, original: bool = False) -> dict[str, Any]:
    if "craft_mechanism" not in candidate:
        return {}
    mechanism = validate_craft_mechanism(candidate["craft_mechanism"])
    provenance = mechanism["provenance"]
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        [f"mkaos-craft-identity:{project_id}:{mechanism['mechanism_id']}"])
    if original != (provenance["origin"] == "REPOSITORY_ORIGINAL") or set(provenance["source_observation_asset_version_ids"]) != set(observation_ids):
        raise KernelError("MKAOS_CRAFT_PROVENANCE_CONFLICT", "Craft origin and Observation identities must match the canonical authoring path")
    cursor.execute(
        """SELECT candidate.craft_mechanism_id, candidate.craft_mechanism_version,
                  candidate.craft_mechanism_hash, version.content->'candidate'->'craft_mechanism'
           FROM authority_mkaos_knowledge_candidate candidate
           JOIN authority_asset_version version ON version.asset_version_id=candidate.asset_version_id
           WHERE candidate.project_id=%s AND candidate.craft_mechanism_id IS NOT NULL
           FOR SHARE OF candidate""", [project_id],
    )
    prior_candidates = cursor.fetchall()
    for identity, version, content_hash, stored in prior_candidates:
        if identity == mechanism["mechanism_id"] and version == mechanism["version"] and content_hash != craft_hash(mechanism):
            raise KernelError("MKAOS_CRAFT_VERSION_CONFLICT", "An immutable Craft identity/version already has different content; author a new version")
        if identity != mechanism["mechanism_id"] and stored and " ".join(stored["abstract_mechanism"].split()) == " ".join(mechanism["abstract_mechanism"].split()):
            raise KernelError("MKAOS_CRAFT_DUPLICATE_MECHANISM", "Identical abstraction already exists; merge provenance into an explicit next version of that mechanism")
    predecessor = provenance["supersedes_card_asset_version_id"]
    if predecessor:
        cursor.execute(
            """SELECT version.content->'abstract_content'->'craft_mechanism', card.status,
                      version.lifecycle, version.eligibility, version.governance
               FROM authority_mkaos_knowledge_card card
               JOIN authority_asset_version version ON version.asset_version_id=card.asset_version_id
               WHERE card.project_id=%s AND card.asset_version_id=%s FOR SHARE OF card,version""",
            [project_id, predecessor],
        )
        row = cursor.fetchone()
        if not row or not row[0] or row[0]["mechanism_id"] != mechanism["mechanism_id"] or row[0]["version"] + 1 != mechanism["version"] or row[1:] != ("ACTIVE", "ACTIVE", "ELIGIBLE", "CLEAR"):
            raise KernelError("MKAOS_CRAFT_PREDECESSOR_INVALID", "Craft revision requires the immediately preceding active governed version in this project")
    elif (not original and mechanism["version"] != 1) or any(
        identity == mechanism["mechanism_id"] and version != mechanism["version"]
        for identity, version, _, _ in prior_candidates
    ):
        raise KernelError("MKAOS_CRAFT_PREDECESSOR_INVALID", "Existing Craft revisions require an explicit immediate predecessor")
    if original and not predecessor:
        cursor.execute("""SELECT operation_id FROM authority_operation
            WHERE project_id=%s AND definition_name='mkaos.craft.original.author'
              AND command_payload->'payload'->>'mechanism_id'=%s
              AND command_payload->'payload'->'candidate'->'craft_mechanism'->>'version' <> %s
            LIMIT 1""", [project_id, mechanism["mechanism_id"], str(mechanism["version"])])
        if cursor.fetchone():
            raise KernelError("MKAOS_CRAFT_PREDECESSOR_INVALID", "An earlier admitted mechanism identity requires recovery and an explicit immediate predecessor")
    resolved_evidence = {}
    for evidence in mechanism["validation_evidence"] + mechanism["effect_evidence"]:
        cursor.execute(
            """SELECT asset.asset_type,version.content,version.governance
               FROM authority_asset_version version JOIN authority_asset asset ON asset.asset_id=version.asset_id
               WHERE asset.project_id=%s AND version.asset_version_id=%s""",
            [project_id, evidence["asset_version_id"]],
        )
        row = cursor.fetchone()
        if not row or row[2] != "CLEAR":
            raise KernelError("MKAOS_CRAFT_EVIDENCE_INVALID", "Craft evidence must resolve to an immutable clear asset in the same project")
        content = dict(row[1] or {})
        resolved_evidence[evidence["asset_version_id"]] = content
        if evidence["kind"] in {"HUMAN_READER", "EDITORIAL", "CONTROLLED_COMPARISON"} and content.get("evidence_class") != evidence["kind"]:
            raise KernelError("MKAOS_CRAFT_EVIDENCE_CLASS_INVALID", "Evidence cannot upgrade a model judgment to independent human or comparison evidence")
    for binding in mechanism.get("affinity_evidence", []):
        expected = {"mechanism_id": mechanism["mechanism_id"], "dimension": binding["dimension"],
            "value": binding["value"], "applicability_conditions": mechanism["applicability_conditions"],
            "mechanism_semantic_hash": craft_semantic_hash(mechanism)}
        if expected not in resolved_evidence[binding["asset_version_id"]].get("craft_affinity_claims", []):
            raise KernelError("MKAOS_CRAFT_AFFINITY_EVIDENCE_INVALID", "Affinity evidence must attest this exact mechanism, dimension, value and applicability scope")
    return {"craft_mechanism_id": mechanism["mechanism_id"], "craft_mechanism_version": mechanism["version"], "craft_mechanism_hash": craft_hash(mechanism)}


def _original_template_hash(mechanism: Mapping[str, Any]) -> str:
    template = deepcopy(dict(mechanism))
    template["provenance"]["supersedes_card_asset_version_id"] = ""
    return craft_hash(template)


def _bind_original_template(template: Mapping[str, Any], predecessor: str) -> dict[str, Any]:
    mechanism = validate_craft_mechanism(template)
    if mechanism["provenance"]["origin"] != "REPOSITORY_ORIGINAL" or mechanism["provenance"]["supersedes_card_asset_version_id"]:
        raise KernelError("MKAOS_CRAFT_PROVENANCE_CONFLICT", "Original catalog templates must be independent of project Card identities")
    if predecessor and mechanism["version"] == 1:
        raise KernelError("MKAOS_CRAFT_PREDECESSOR_INVALID", "Original Craft first versions forbid a predecessor")
    mechanism["provenance"]["supersedes_card_asset_version_id"] = predecessor
    return validate_craft_mechanism(mechanism)


def _frozen_original_candidate(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    mechanism = validate_craft_mechanism(payload["candidate"]["craft_mechanism"])
    candidate = craft_candidate(mechanism)
    candidate_hash = craft_hash({"origin": "REPOSITORY_ORIGINAL", "candidate": candidate, "catalog_hash": payload["catalog_hash"]})
    if (
        mechanism["provenance"]["origin"] != "REPOSITORY_ORIGINAL"
        or mechanism["provenance"]["abstraction_policy_version"] != CRAFT_ORIGINAL_POLICY
        or mechanism["mechanism_id"] != payload["mechanism_id"]
        or candidate != payload["candidate"]
        or candidate_hash != payload["candidate_hash"]
        or (mechanism["version"] > 1 and not payload.get("catalog_template_hash"))
        or payload.get("catalog_template_hash", _original_template_hash(mechanism)) != _original_template_hash(mechanism)
    ):
        raise KernelError("MKAOS_CRAFT_CATALOG_DRIFT", "Frozen original Craft identity or content changed after admission")
    return mechanism, candidate, candidate_hash


def admit_core_craft(application: Any, command: AuthorCoreCraftCommand, *, principal: Any = None) -> dict[str, Any]:
    actor = application._actor(command.actor_id, principal, "mkaos.authority.execute", command.project_id)
    with AuthorityUnitOfWork(application.database_url) as uow:
        repository = MkaosAuthorityRepository(uow.cursor)
        repository.require_scope(project_id=command.project_id, workspace_id=command.workspace_id)
        uow.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            [f"mkaos-craft-identity:{command.project_id}:{command.mechanism_id}"])
        admitted = repository.existing_original_craft_admission(project_id=command.project_id,
            mechanism_id=command.mechanism_id, catalog_hash=command.catalog_hash)
        if not admitted:
            mechanism = _bind_original_template(
                require_core_mechanism(command.mechanism_id, command.catalog_hash), command.supersedes_card_asset_version_id)
            admitted = repository.existing_original_craft_mechanism_admission(project_id=command.project_id,
                mechanism=mechanism)
        if admitted:
            command_payload = admitted["command_payload"]
            mechanism, candidate, candidate_hash = _frozen_original_candidate(command_payload["payload"])
            if mechanism["provenance"]["supersedes_card_asset_version_id"] != command.supersedes_card_asset_version_id:
                raise KernelError("MKAOS_CRAFT_PREDECESSOR_INVALID", "Replay must preserve the frozen project predecessor")
        else:
            candidate = craft_candidate(mechanism)
            candidate_hash = craft_hash({"origin": "REPOSITORY_ORIGINAL", "candidate": candidate, "catalog_hash": command.catalog_hash})
            command_payload = {"project_id": command.project_id, "workspace_id": command.workspace_id,
                "payload": {"candidate": candidate, "candidate_hash": candidate_hash, "catalog_hash": command.catalog_hash,
                            "catalog_template_hash": _original_template_hash(mechanism),
                            "mechanism_id": command.mechanism_id, "client_idempotency_key": command.idempotency_key,
                            "authoring_build_id": application.application_build_id, "authoring_commit_sha": application.commit_sha}}
        existing = repository.existing_candidate(project_id=command.project_id, candidate_hash=candidate_hash)
        if not existing:
            existing = repository.existing_craft_candidate(project_id=command.project_id,
                mechanism_id=mechanism["mechanism_id"], version=mechanism["version"])
        if existing:
            original = repository.candidate_for_approval(project_id=command.project_id, asset_version_id=existing["asset_version_id"])
            if original["content"]["candidate"]["craft_mechanism"] != mechanism:
                raise KernelError("MKAOS_CRAFT_VERSION_CONFLICT", "An immutable Craft identity/version already has different content; author a new version")
            frozen = original["content"]["original_authoring"]
            existing.update({"catalog_hash": frozen["catalog_hash"], "mechanism_hash": frozen["mechanism_hash"],
                             "candidate_hash": original["candidate_hash"]})
        else:
            validate_craft_lineage(uow.cursor, command.project_id, candidate, (), original=True)
        if existing:
            if existing["operation_status"] != "SUCCEEDED":
                raise KernelError("MKAOS_CANDIDATE_RECOVERY_REQUIRED", "Original Craft candidate Operation requires recovery")
            return {**existing, "project_id": command.project_id, "status": "SUCCEEDED", "replayed": True, "duplicate": True}
        return application._admit(
            definition_name=MKAOS_CRAFT_AUTHOR_OPERATION, definition_version=MKAOS_CRAFT_AUTHOR_DEFINITION_VERSION,
            handler_key=MKAOS_CRAFT_AUTHOR_HANDLER_KEY, permission="mkaos.authority.execute",
            project_id=command.project_id, workspace_id=command_payload["workspace_id"], actor_id=actor,
            idempotency_scope="project:mkaos-craft-original", idempotency_key=f"craft-original:{command.project_id}:{candidate_hash}",
            trace_id=command.trace_id, correlation_id=command.correlation_id, causation_id=command_payload["payload"]["catalog_hash"],
            command_payload=command_payload,
            input_assets=[], ready_reason="Repository original Craft requires a separate exact-catalog governance approval",
        )


def execute_core_craft_fenced(application: Any, worker: Any) -> dict[str, Any]:
    with AuthorityUnitOfWork(application.database_url) as uow:
        require_current_fence(uow, worker)
        operation = uow.repositories.chapter_authority.operation_execution(worker.causation_id, worker.project_id)
        command = dict(operation["command_payload"])
        payload = dict(command["payload"])
        repository = MkaosAuthorityRepository(uow.cursor)
        repository.require_scope(project_id=worker.project_id, workspace_id=command["workspace_id"])
        mechanism, candidate, expected_hash = _frozen_original_candidate(payload)
        identity = validate_craft_lineage(uow.cursor, worker.project_id, candidate, (), original=True)
        candidate_id = f"knowledge-candidate:{worker.project_id}:{expected_hash.removeprefix('sha256:')}"
        asset_version_id = f"{candidate_id}:v1"
        proof = {"fixture_protocol_only": False, "real_provider_proven": False, "production_verified": False}
        content = {
            "schema_version": "mkaos-knowledge-candidate.v1", "knowledge_candidate_id": candidate_id,
            "project_id": worker.project_id, "workspace_id": command["workspace_id"], "candidate": candidate,
            "evidence_spans": [], "observation_asset_version_ids": [], "lineage_mode": "REPOSITORY_ORIGINAL",
            "abstraction_policy_version": CRAFT_ORIGINAL_POLICY,
            "execution_evidence": {"asset_version_id": None, "proof": proof, "execution_kind": "NO_PROVIDER_CALL"},
            "original_authoring": {"catalog_hash": payload["catalog_hash"], "mechanism_hash": craft_hash(mechanism),
                "catalog_template_hash": payload.get("catalog_template_hash", _original_template_hash(mechanism)),
                "authoring_build_id": payload["authoring_build_id"], "authoring_commit_sha": payload["authoring_commit_sha"],
                "operator_id": operation["actor_id"] if "actor_id" in operation else "", "evidence_ceiling": "ORIGINAL_ABSTRACTION_NOT_CREATIVE_QUALITY"},
            "source_policy": {"raw_source_expression_included": False, "generation_eligible": False,
                "authority_approval_required": True, "fixture_protocol_only": False},
            "lineage": {"created_by_operation_id": worker.causation_id, "source_chunk_asset_version_ids": [], "observation_asset_version_ids": []},
        }
        created = uow.repositories.chapter_authority.materialize_output(
            operation_id=worker.causation_id, project_id=worker.project_id, asset_id=candidate_id,
            asset_version_id=asset_version_id, qualification_id=f"{asset_version_id}:qualification:v1",
            asset_type="knowledge_card_candidate", output_key="mkaos.knowledge.candidate", role="candidate",
            content=content, content_hash=craft_hash(content), qualification_policy="mkaos-original-craft-isolation-v1",
            qualification_evidence={"operation_id": worker.causation_id, "attempt_id": worker.attempt_id,
                "fencing_token": worker.fencing_token, "catalog_hash": payload["catalog_hash"],
                "origin": "REPOSITORY_ORIGINAL", "real_provider_proven": False, "production_verified": False},
            lifecycle="CANDIDATE", eligibility="PENDING_EVALUATION", governance="CLEAR",
        )
        if created:
            repository.register_candidate({"knowledge_candidate_id": candidate_id, "project_id": worker.project_id,
                "workspace_id": command["workspace_id"], "asset_version_id": asset_version_id,
                "execution_asset_version_id": None, "created_by_operation_id": worker.causation_id,
                "candidate_hash": expected_hash, "abstraction_policy_version": CRAFT_ORIGINAL_POLICY,
                "origin_kind": "REPOSITORY_ORIGINAL", **identity})
            application._event(uow, worker, aggregate_type="authority_mkaos_knowledge_candidate",
                aggregate_id=candidate_id, event_type="authority.mkaos.knowledge_candidate.committed",
                causation_id=payload["catalog_hash"], payload={"knowledge_candidate_id": candidate_id,
                    "asset_version_id": asset_version_id, "candidate_hash": expected_hash,
                    "origin_kind": "REPOSITORY_ORIGINAL", "status": "NEEDS_REVIEW"})
        uow.commit()
    return {"knowledge_candidate_id": candidate_id, "asset_version_id": asset_version_id, "candidate_hash": expected_hash}


def original_craft_approval(candidate: Mapping[str, Any], *, project_id: str, workspace_id: str, policy_version: str, reviewer_id: str, approval_class: str) -> dict[str, Any] | None:
    content = candidate["content"]
    if content.get("lineage_mode") != "REPOSITORY_ORIGINAL":
        return None
    authoring = dict(content.get("original_authoring") or {})
    catalog_hash = str(authoring.get("catalog_hash") or "")
    mechanism = validate_craft_mechanism(content["candidate"]["craft_mechanism"])
    _frozen_original_candidate({"candidate": content["candidate"], "catalog_hash": catalog_hash,
        "mechanism_id": mechanism["mechanism_id"], "candidate_hash": candidate["candidate_hash"],
        **({"catalog_template_hash": authoring["catalog_template_hash"]} if "catalog_template_hash" in authoring else {})})
    if craft_hash(mechanism) != authoring.get("mechanism_hash") or candidate.get("execution_asset_version_id") is not None:
        raise KernelError("MKAOS_CRAFT_PROVENANCE_CONFLICT", "Original Craft provenance does not match its frozen catalog mechanism")
    if approval_class != "PRODUCTION" or policy_version != f"{CRAFT_ORIGINAL_POLICY}:{catalog_hash}":
        raise KernelError("MKAOS_CRAFT_EXACT_APPROVAL_REQUIRED", "Original Craft approval must explicitly bind the reviewed exact catalog hash")
    return {"schema_version": "mkaos-approval-contract.v1", "approval_class": "PRODUCTION",
        "review_class": "ORIGINAL_CATALOG_OPERATOR_APPROVAL", "activation_scope": {"kind": "PROJECT", "project_id": project_id, "workspace_id": workspace_id},
        "project_id": project_id, "workspace_id": workspace_id, "policy_version": policy_version,
        "reviewer_id": reviewer_id, "production_context_eligible": True, "experimental_context_eligible": False,
        "catalog_hash": catalog_hash, "mechanism_hash": authoring["mechanism_hash"],
        **({"catalog_template_hash": authoring["catalog_template_hash"]} if "catalog_template_hash" in authoring else {}),
        "evidence_ceiling": "ORIGINAL_GOVERNED_KNOWLEDGE_NOT_CREATIVE_QUALITY"}
