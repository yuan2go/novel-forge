"""TEST: Source-to-Card transactions for an explicitly scripted cooling-rule fixture."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.mkaos_authority import (
    ApproveKnowledgeCandidateCommand,
    CommitKnowledgeCandidateCommand,
    KnowledgeEvidenceSpan,
    MkaosAuthorityApplication,
    MkaosAuthorityQuery,
)
from novel_forge.modules.source_authority import (
    CommitDeconstructionObservationCommand,
    CommitSourceTransformCommand,
    ObservationEvidenceSpan,
    ObservationScope,
    RegisterSourceDocumentCommand,
    SourceAuthorityApplication,
    SourceChunkCandidate,
    default_analyzer_contracts,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


COOLING_SOURCE_TEXT = (
    "Original synthetic resource-system fixture. Cooling consumes exactly one existing "
    "water token. Without a token, cooling cannot occur. A contaminated token cannot "
    "produce cooling. This defines only a fictional token model, not real-world thermodynamics."
)


def _hash(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _fixture_inputs(database_url: str, project_id: str, prefix: str) -> tuple[str, str]:
    """TEST: Use the existing MKAOS tests' Blob/execution fixture boundary only."""
    source_bytes = COOLING_SOURCE_TEXT.encode("utf-8")
    blob_id, execution_id = f"{prefix}:blob", f"{prefix}:execution"
    execution_version_id = f"{execution_id}:v1"
    source_hash = _hash(source_bytes)
    object_key = f"knowledge-closure/{project_id}/{blob_id}"
    execution = {
        "execution_id": execution_id,
        "gateway": "ProductionExecutionGateway",
        "fixture_protocol_only": True,
        "real_provider_proven": False,
        "production_verified": False,
        "provider_calls": 0,
        "semantic_evidence": "SCRIPTED_FIXTURE_OBSERVATION",
        "source_content_hash": source_hash,
    }
    execution_hash = _hash(json.dumps(execution, sort_keys=True, separators=(",", ":")).encode())
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            INSERT INTO authority_blob (
                blob_id, project_id, provider, object_key, expected_hash,
                expected_size, media_type, actual_object_key, actual_hash,
                actual_size, receipt_provider, status
            ) VALUES (%s, %s, 'fixture_object_store', %s, %s, %s,
                      'text/plain', %s, %s, %s, 'fixture_object_store', 'AVAILABLE')
            """,
            [blob_id, project_id, object_key, source_hash, len(source_bytes),
             object_key, source_hash, len(source_bytes)],
        )
        uow.cursor.execute(
            "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s,%s,'model_call_log')",
            [execution_id, project_id],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_asset_version (
                asset_version_id, asset_id, version_number, lifecycle,
                eligibility, governance, content, content_hash, schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'integration-fixture.v1')
            """,
            [execution_version_id, execution_id, Jsonb(execution), execution_hash],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_asset_qualification (
                qualification_id, asset_version_id, policy_version, decision, evidence
            ) VALUES (%s,%s,'integration-fixture-v1','ELIGIBLE',%s)
            """,
            [f"{execution_version_id}:qualification", execution_version_id,
             Jsonb({"fixture_protocol_only": True, "production_verified": False})],
        )
        uow.commit()
    return blob_id, execution_version_id


def create_approved_cooling_card(
    *, database_url: str, project_id: str, workspace_id: str
) -> dict:
    """TEST: Existing Project scope; no migrations, cleanup, Provider calls or Canon writes."""
    prefix = f"knowledge-closure-{uuid4()}"
    principal = Principal(
        principal_id=f"{prefix}:operator",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"source.authority.execute", "mkaos.authority.execute",
                               "mkaos.authority.approve", "mkaos.authority.query"}),
        project_scope=frozenset({project_id}), authentication_source="integration-test",
    )

    def command_fields(stage: str) -> dict:
        return {"project_id": project_id, "workspace_id": workspace_id,
                "actor_id": principal.principal_id, "idempotency_key": f"{prefix}:{stage}",
                "trace_id": f"{prefix}:trace", "correlation_id": prefix}

    source_bytes = COOLING_SOURCE_TEXT.encode("utf-8")
    source_hash = _hash(source_bytes)
    blob_id, execution_version_id = _fixture_inputs(database_url, project_id, prefix)
    source = SourceAuthorityApplication(
        database_url, application_build_id="knowledge-closure-scripted-integration",
        commit_sha="f" * 40, allow_fixture_observations=True,
    )
    registered = source.execute(RegisterSourceDocumentCommand(
        **command_fields("source"), blob_id=blob_id, title="Original fictional cooling-token rule",
        source_kind="licensed_research", source_uri=f"urn:test:{prefix}",
        rights_authorization="owned", license_name="CC0-1.0",
        copyright_boundary="Original synthetic fixture; abstract mechanism only; no source prose in creative context",
    ), principal=principal)
    assert registered["status"] == "SUCCEEDED", registered
    transformed = source.execute_transform(CommitSourceTransformCommand(
        **command_fields("transform"), source_document_id=registered["source_document_id"],
        normalization_version="identity-utf8.v1", chunking_version="single-complete-rule.v1",
        chunking_policy_hash=_hash(b"knowledge-closure:single-complete-rule:v1"),
        normalized_blob_id=blob_id, normalized_content_hash=source_hash,
        normalized_byte_size=len(source_bytes),
        chunks=(SourceChunkCandidate(
            chunk_index=0, blob_id=blob_id, content_hash=source_hash, byte_size=len(source_bytes),
            character_count=len(COOLING_SOURCE_TEXT), token_count=len(COOLING_SOURCE_TEXT.split()),
            source_byte_start=0, source_byte_end=len(source_bytes),
        ),),
    ), principal=principal)
    assert transformed["status"] == "SUCCEEDED", transformed
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT asset_version_id FROM authority_source_chunk WHERE source_transform_id=%s AND chunk_index=0",
            [transformed["source_transform_id"]],
        )
        chunk_version_id = str(uow.cursor.fetchone()[0])
    span = ObservationEvidenceSpan(
        source_chunk_asset_version_id=chunk_version_id,
        chunk_byte_start=0, chunk_byte_end=len(source_bytes), evidence_hash=source_hash,
    )
    analyzer = replace(
        default_analyzer_contracts()["hook"], analyzer_id="knowledge-closure.causal-constraints",
        dimension="causal_constraints", prompt_id="knowledge-closure.causal-observation",
        skill_id="multidisciplinary-knowledge", recommended_scales=("DOCUMENT_SECTION",),
    )
    observation = source.execute_observation(CommitDeconstructionObservationCommand(
        **command_fields("observation"), execution_asset_version_id=execution_version_id,
        scope=ObservationScope(scale="DOCUMENT_SECTION", range_start=1, range_end=1,
                               source_document_ids=(registered["source_document_id"],),
                               label="complete-fictional-cooling-rule"),
        analyzer=analyzer, observation={
            "findings": [{"finding_code": "cooling.resource.cost",
                          "statement": "A fictional cooling action spends one available clean resource unit; absent or contaminated input cannot yield the benefit.",
                          "epistemic_status": "TEXT_EXPLICIT", "evidence_span_ids": [span.evidence_span_id]}],
            "confidence": 0.8, "originality_risk": "LOW_AFTER_ABSTRACTION",
            "knowledge_status": "NOT_ABSTRACTED",
            "scope_limitations": ["Scripted observation of an original fictional axiom; no real-world validity or Provider semantic quality is established."],
        }, evidence_spans=(span,), input_observation_asset_version_ids=(), evidence_class="FIXTURE",
    ), principal=principal)
    assert observation["status"] == "SUCCEEDED", observation
    abstract = {
        "concept_name": "Cooling under a finite water-token budget",
        "discipline": "fictional resource-system design", "knowledge_kind": "DOMAIN_INTELLIGENCE",
        "semantic_family": "PROFESSIONAL_CAUSAL_MECHANISM",
        "abstract_principle": "A benefit requiring a consumable input is feasible only while a valid unit remains, and consumption reduces future options.",
        "mechanism": "Each successful cooling action reduces the previously available clean water-token balance by one; no token or contamination prevents the benefit.",
        "constraints": ["Account for one existing clean water token before each cooling action."],
        "conflict_generators": ["Spend scarce water on immediate cooling or preserve the remaining rescue options."],
        "review_checks": ["Locate the cooling choice and its before/after token balance in prose; a spent or contaminated token cannot silently fund a later action."],
        "copyright_boundaries": ["Use the abstract cost relation only; do not copy the fixture's source wording."],
        "applicability": ["The fictional world uses discrete water tokens and cooling consumes exactly one."],
        "preconditions": ["At least one previously available clean water token remains."],
        "exceptions": ["A contaminated token cannot produce cooling."],
        "failure_conditions": ["No token remains, or contamination invalidates the attempted cooling."],
        "misuse_risks": ["Do not present the fictional token rule as real-world thermodynamics."],
        "source_finding_codes": ["cooling.resource.cost"], "epistemic_status": "TEXT_EXPLICIT",
        "usage_role": "MECHANISM",
        "applicability_contract": {"schema_version": "knowledge-applicability.v1", "usage_role": "MECHANISM",
                                   "prerequisites": [], "exceptions": [], "hard_conflicts": []},
        "selection_tags": {"genre": [], "conflict": ["water", "cooling", "resource scarcity"], "reader_effect": [], "theme": []},
        "repetition_key": "cooling-consumes-available-clean-water",
        "originality_boundary": {"source_specific_sequence_reusable": False,
                                 "named_entity_substitution_allowed": False, "expression_reuse_allowed": False},
    }
    mkaos = MkaosAuthorityApplication(
        database_url, application_build_id="knowledge-closure-scripted-integration",
        commit_sha="f" * 40, allow_fixture_activation=True,
    )
    candidate = mkaos.execute_candidate(CommitKnowledgeCandidateCommand(
        **command_fields("candidate"), execution_asset_version_id=execution_version_id,
        candidate=abstract, evidence_spans=(KnowledgeEvidenceSpan(
            source_chunk_asset_version_id=chunk_version_id, chunk_byte_start=0,
            chunk_byte_end=len(source_bytes), evidence_hash=source_hash,
        ),), abstraction_policy_version="anti-copy-abstraction:v1",
        observation_asset_version_ids=(observation["asset_version_id"],),
    ), principal=principal)
    assert candidate["status"] == "SUCCEEDED", candidate
    approval = mkaos.execute_approval(ApproveKnowledgeCandidateCommand(
        **command_fields("approve"), candidate_asset_version_id=candidate["asset_version_id"],
        policy_version="knowledge-closure-fixture-review.v1",
        rationale="Scripted fixture approval verifies abstract shape and exact Source/Observation lineage only; it is neither human review nor real-Provider evidence.",
    ), principal=principal)
    assert approval["status"] == "SUCCEEDED", approval
    card = next(item for item in MkaosAuthorityQuery(database_url).list_cards(project_id=project_id)
                if item["candidate_asset_version_id"] == candidate["asset_version_id"])
    assert (card["card_status"], card["lifecycle"], card["eligibility"], card["governance"], card["operation_status"]) == (
        "ACTIVE", "ACTIVE", "ELIGIBLE", "CLEAR", "SUCCEEDED",
    ), card
    return {
        "card_asset_version_id": card["asset_version_id"], "content_hash": card["content_hash"],
        "candidate_asset_version_id": candidate["asset_version_id"],
        "observation_asset_version_id": observation["asset_version_id"],
        "source_document_id": registered["source_document_id"],
        "source_asset_version_id": registered["asset_version_id"],
        "source_chunk_asset_version_id": chunk_version_id,
        "execution_asset_version_id": execution_version_id, "source_content_hash": source_hash,
        "approval_operation_id": approval["operation_id"],
        "knowledge_access_policy": {"policy_id": "knowledge-closure-fixture-treatment", "policy_version": 1,
                                    "mode": "ALLOW_ONLY", "allowed_knowledge_card_asset_version_ids": [card["asset_version_id"]]},
        "proof_ceiling": "SCRIPTED_FIXTURE_SOURCE_TO_CARD_TRANSACTIONS", "provider_calls": 0,
    }
