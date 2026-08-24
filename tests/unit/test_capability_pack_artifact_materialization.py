from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_forge.modules.capability_pack_authority.domain import (
    CapabilityPackExecutionSnapshot,
    ScopeType,
    canonical_hash,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    materialize_registered_pack_version,
)
from novel_forge.modules.capability_packs.artifacts import (
    ArtifactKind,
    default_chapter_artifact_resolver,
)
from novel_forge.modules.capability_packs.loader import load_capability_pack_payload
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.execution_gateway import (
    _materialize_chapter_codex_prompt,
)
from novel_forge.modules.production_execution import ExecutionRuntimeClass
from tests.unit.test_production_execution_gateway import contracts


ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64
RELEASE_SHA = "b" * 40
CHAPTER_MODEL_POLICY_KEYS = (
    "prose-chapter-draft",
    "review-chapter-evaluate",
    "revision-chapter-revise",
    "canon-extract",
    "quality-intrinsic-judge",
    "quality-originality-judge",
    "quality-platform-judge",
)


def _registered_version_and_snapshot():
    manifest_payload = json.loads(
        (ROOT / "config/capability_packs/chapter_generation_pack.json").read_text()
    )
    manifest = load_capability_pack_payload(manifest_payload)
    manifest_dict = manifest.to_dict()
    resolver = default_chapter_artifact_resolver(ROOT)
    catalog = {
        "schema_version": "novelos.capability_pack.artifact_catalog.v1",
        "artifacts": [item.to_dict() for item in resolver.artifacts()],
    }
    system = resolver.resolve(
        ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
        str(manifest.prompt_binding.system_instruction_ref),
        str(manifest.prompt_binding.system_instruction_version),
    )
    template = resolver.resolve(
        ArtifactKind.PROMPT_TEMPLATE,
        str(manifest.prompt_binding.template_ref),
        str(manifest.prompt_binding.template_version),
    )
    skill = resolver.resolve(
        ArtifactKind.SKILL,
        "prose-generation",
        "prose-generation-v1",
    )
    context = resolver.resolve(
        ArtifactKind.CONTEXT_POLICY,
        str(manifest.context_sources.policy_id),
        "v1",
    )
    tool = resolver.resolve(
        ArtifactKind.TOOL_POLICY,
        str(manifest.tool_permissions.policy_id),
        "v1",
    )
    snapshot = CapabilityPackExecutionSnapshot(
        deployment_id="deployment-1",
        activation_version=1,
        selected_scope_type=ScopeType.PROJECT,
        selection_reason="PROJECT deployment selected",
        pack_id=str(manifest.identity.pack_id),
        pack_version=str(manifest.identity.version),
        manifest_hash=manifest.manifest_hash,
        compilation_id="compilation-1",
        compilation_hash=HASH,
        catalog_snapshot_hash=HASH,
        binding_set_id="binding-set-1",
        binding_set_hash=HASH,
        workflow_definition_ref="chapter_authority_slice@2.3.1",
        workflow_node_id="draft",
        operation_definition_ref="chapter.draft.generate@2.3.1",
        operation_definition_hash=HASH,
        agent_definition_ref="chapter-draft-agent@1",
        agent_definition_hash=HASH,
        capability_ref="prose.chapter.draft@1",
        capability_hash=HASH,
        execution_capability_id="prose.chapter.draft",
        execution_capability_hash=HASH,
        prompt_bundle_ref=system.ref,
        prompt_bundle_hash=system.content_hash,
        skill_bundle_ref="prose-generation@prose-generation-v1",
        skill_bundle_hash=skill.content_hash,
        tool_policy_ref=tool.ref,
        tool_policy_hash=canonical_hash(manifest_dict["tool_permissions"]),
        context_policy_ref=context.ref,
        context_policy_hash=canonical_hash(manifest_dict["context_sources"]),
        evaluation_policy_ref="evaluation:chapter-generation-pack:v1",
        evaluation_policy_hash=HASH,
        route_policy_ref="chapter.stage.route.policy:v1",
        route_policy_hash=HASH,
        approval_policy_ref="approval:chapter-domain-authority:v1",
        approval_policy_hash=HASH,
        budget_policy_ref="budget:chapter-generation-pack:v1",
        budget_policy_hash=HASH,
        input_contract_ref="schema:execution-input:prose-chapter-draft:v1",
        output_contract_ref="schema:execution-output:prose-chapter-draft:v1",
        domain_acceptance_policy_ref="approval:chapter-domain-authority:v1",
        commit_authority="CHAPTER_AUTHORITY",
        release_sha=RELEASE_SHA,
        prompt_system_instruction_ref=f"{system.ref}@{system.version}",
        prompt_system_instruction_hash=system.content_hash,
        prompt_template_ref=f"{template.ref}@{template.version}",
        prompt_template_hash=template.content_hash,
        prompt_compiler_version="chapter-prompt-compiler:v1",
        skill_ref=skill.ref,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        context_policy_payload_json=json.dumps(
            manifest_dict["context_sources"], sort_keys=True
        ),
        tool_policy_payload_json=json.dumps(
            manifest_dict["tool_permissions"], sort_keys=True
        ),
        evaluation_policy_payload_json="{}",
    )
    registered = {
        "pack_id": snapshot.pack_id,
        "pack_version": snapshot.pack_version,
        "manifest_hash": snapshot.manifest_hash,
        "artifact_catalog_hash": canonical_hash(catalog),
        "manifest": manifest.to_dict(),
        "artifact_catalog": catalog,
    }
    return registered, snapshot


def test_materializes_exact_provider_content_from_registered_pack_version() -> None:
    registered, snapshot = _registered_version_and_snapshot()

    result = materialize_registered_pack_version(snapshot, registered)

    assert (
        "admitted Chapter Authority stage" in result.system_instruction.content["text"]
    )
    assert "{{context_bundle}}" in result.prompt_template.content["text"]
    assert "prose-generation" in result.skill.ref
    assert result.context_policy.ref == snapshot.context_policy_ref
    assert result.tool_policy.ref == snapshot.tool_policy_ref
    assert result.output_schema.ref == snapshot.output_contract_ref
    assert [item.ref for item in result.required_knowledge] == [
        "knowledge:chapter-causal-cost:v1"
    ]
    assert result.materialization_hash.startswith("sha256:")


@pytest.mark.parametrize("policy_key", CHAPTER_MODEL_POLICY_KEYS)
def test_catalog_contains_each_chapter_model_execution_contract(
    policy_key: str,
) -> None:
    resolver = default_chapter_artifact_resolver(ROOT)

    for direction in ("input", "output"):
        artifact = resolver.resolve(
            ArtifactKind.SCHEMA,
            f"schema:execution-{direction}:{policy_key}:v1",
            "v1",
        )
        assert json.loads(artifact.content_json)["type"] == "object"
        assert artifact.content_hash.startswith("sha256:")


def test_materialization_rejects_registered_catalog_content_hash_drift() -> None:
    registered, snapshot = _registered_version_and_snapshot()
    registered["artifact_catalog"]["artifacts"][0]["content"] = {"changed": True}

    with pytest.raises(KernelError) as raised:
        materialize_registered_pack_version(snapshot, registered)

    assert raised.value.code == "CAPABILITY_PACK_ARTIFACT_HASH_DRIFT"


def test_materialization_rejects_missing_required_knowledge() -> None:
    registered, snapshot = _registered_version_and_snapshot()
    catalog = deepcopy(registered["artifact_catalog"])
    catalog["artifacts"] = [
        item
        for item in catalog["artifacts"]
        if item["ref"] != "knowledge:chapter-causal-cost:v1"
    ]
    registered["artifact_catalog"] = catalog
    registered["artifact_catalog_hash"] = canonical_hash(catalog)

    with pytest.raises(KernelError) as raised:
        materialize_registered_pack_version(snapshot, registered)

    assert raised.value.code == "CAPABILITY_PACK_REQUIRED_ASSET_MISSING"


def test_materialization_rejects_snapshot_version_mismatch() -> None:
    registered, snapshot = _registered_version_and_snapshot()
    registered["pack_version"] = "2.0.0"

    with pytest.raises(KernelError) as raised:
        materialize_registered_pack_version(snapshot, registered)

    assert raised.value.code == "CAPABILITY_PACK_VERSION_MISMATCH"


def test_codex_prompt_materializes_typed_target_scope_as_json() -> None:
    *_, request = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    prompt, evidence = _materialize_chapter_codex_prompt(
        request=request,
        stage="draft",
        inputs={"chapter": 1, "nested": {"value": "consecutive JSON braces"}},
        materialization={
            "materialization_hash": HASH,
            "pack_artifacts": {
                "system_instruction": {
                    "ref": "system",
                    "version": "v1",
                    "content_hash": HASH,
                    "content": {"text": "System instruction."},
                },
                "prompt_template": {
                    "ref": "template",
                    "version": "v1",
                    "content_hash": HASH,
                    "content": {
                        "text": (
                            "{{stage}} {{target_scope}} {{input_manifest}} "
                            "{{context_bundle}} {{output_schema_ref}}"
                        )
                    },
                },
                "skill": {
                    "ref": "skill",
                    "version": "v1",
                    "content_hash": HASH,
                    "content": {"text": "Skill body."},
                },
            },
            "context_selection": [
                {"asset_version_id": "context:v1", "content": {"segments": []}}
            ],
            "knowledge_selection": [
                {"content_hash": HASH, "content": {"rules": ["cost"]}}
            ],
            "tool_permissions": {
                "allowed": ["model.provider.invoke"],
                "denied": ["storage.object.put"],
            },
            "output_schema": {
                "ref": "schema:draft:v1",
                "content_hash": HASH,
                "content": {"type": "object"},
            },
        },
    )

    assert '"scope_kind":"chapter"' in prompt
    assert evidence["fully_rendered_prompt_hash"].startswith("sha256:")


def test_codex_prompt_projects_governed_context_once_without_runtime_evidence() -> None:
    *_, request = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    context = {
        "project_id": "project-1",
        "book_id": "book-1",
        "stage": "draft",
        "chapter": 1,
        "goal": "Open the investigation.",
        "context_digest": HASH,
        "token_budget": 16_000,
        "estimated_tokens": 120,
        "context_segments": [
            {
                "asset_version_id": "plan:v1",
                "asset_type": "chapter_plan",
                "safe_summary": "SEMANTIC-CONTEXT-ONCE",
                "structured_facts": [{"kind": "objective", "value": "investigate"}],
                "content_digest": HASH,
                "allowed_use": "generation",
            }
        ],
        "stage_context_view": {
            "stage": "draft",
            "segments": [
                {
                    "asset_version_id": "plan:v1",
                    "asset_type": "chapter_plan",
                    "safe_summary": "SEMANTIC-CONTEXT-ONCE",
                    "structured_facts": [
                        {"kind": "objective", "value": "investigate"}
                    ],
                    "content_digest": HASH,
                    "allowed_use": "generation",
                }
            ],
            "rendered_safe_context": "SEMANTIC-CONTEXT-ONCE",
            "token_count": 120,
        },
        "actual_context": {
            "premise": "A ledger vanishes.",
            "stage_context_view": {
                "segments": [
                    {
                        "safe_summary": "SEMANTIC-CONTEXT-ONCE",
                    }
                ]
            },
        },
        "context_manifest": {
            "authority_state_boundary": {"accepted_through_chapter": 0},
            "selected_inputs": [{"asset_version_id": "plan:v1"}],
        },
    }
    prompt, evidence = _materialize_chapter_codex_prompt(
        request=request,
        stage="draft",
        inputs={
            "chapter": 1,
            "context": context,
            "draft": {
                "text": "The rain started.",
                "provider_evidence": {"receipt": "RUNTIME-EVIDENCE-MUST-NOT-RENDER"},
            },
        },
        materialization=_prompt_materialization(context),
    )

    assert prompt.count("SEMANTIC-CONTEXT-ONCE") == 1
    assert "RUNTIME-EVIDENCE-MUST-NOT-RENDER" not in prompt
    assert '"context_digest":"' + HASH + '"' in prompt
    assert evidence["provider_prompt_projection_version"] == "provider-prompt-projection-v1"
    assert evidence["rendered_prompt_bytes"] == len(prompt.encode("utf-8"))
    assert evidence["rendered_prompt_estimated_tokens"] > 0


def test_quality_prompt_uses_budgeted_quality_view_not_full_context_bundle() -> None:
    *_, request = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    context = {
        "project_id": "project-1",
        "book_id": "book-1",
        "stage": "draft",
        "chapter": 1,
        "context_digest": HASH,
        "context_segments": [
            {"safe_summary": "GENERIC-CONTEXT-MUST-NOT-RENDER-FOR-QUALITY"}
        ],
    }
    prompt, _ = _materialize_chapter_codex_prompt(
        request=request,
        stage="quality_longform",
        inputs={
            "revision": {"text": "The revised chapter."},
            "quality_context": {
                "type": "LongformQualityContextView",
                "revision_text": "The revised chapter.",
                "previous_state_snapshots": {
                    "canon_snapshot": {
                        "ledger": [{"structured_facts": ["QUALITY-SEMANTIC-STATE"]}]
                    }
                },
                "token_budget": 28_000,
                "coverage_report": {"critical_facts_preserved": True},
            },
            "dimensions": ["canon_consistency"],
        },
        materialization=_prompt_materialization(context),
    )

    assert "QUALITY-SEMANTIC-STATE" in prompt
    assert "GENERIC-CONTEXT-MUST-NOT-RENDER-FOR-QUALITY" not in prompt


def test_reader_outcome_prompt_projects_semantics_without_authority_lineage() -> None:
    *_, request = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    prompt, _ = _materialize_chapter_codex_prompt(
        request=request,
        stage="reader_outcome",
        inputs={
            "chapter": 1,
            "assets": {
                "draft_version": {
                    "text": "READER-VISIBLE-CHAPTER",
                    "provider_evidence": {"receipt": "DRAFT-RECEIPT-NOISE"},
                },
                "quality_score_report": {
                    "gate": "PASSED",
                    "dimensions": [{"dimension": "hook", "score": 0.9}],
                    "evidence_reports": ["QUALITY-AUDIT-NOISE"],
                },
                "story_state_snapshot": {
                    "state_hash": HASH,
                    "accepted_through_chapter": 1,
                    "current_state": {
                        "character_state": [
                            {
                                "state_kind": "character_state",
                                "identity": {"entity_id": "protagonist"},
                                "mutation": {"status": "cornered"},
                                "provenance": {"receipt": "STATE-PROVENANCE-NOISE"},
                                "evidence": {"trace": "STATE-EVIDENCE-NOISE"},
                            }
                        ]
                    },
                    "reducer_applications": ["REDUCER-AUDIT-NOISE"],
                },
                "chapter_outcome": {
                    "chapter_number": 1,
                    "state_events": [
                        {
                            "state_kind": "relationship_state",
                            "identity": {"entity_id": "pair"},
                            "mutation": {"trust": "lower"},
                            "provenance": {"receipt": "EVENT-PROVENANCE-NOISE"},
                        }
                    ],
                    "cost_receipt_refs": ["COST-RECEIPT-NOISE"],
                },
            },
        },
        materialization=_prompt_materialization(
            {
                "project_id": "project-1",
                "context_digest": HASH,
                "context_segments": [{"safe_summary": "GENERIC-READER-CONTEXT-NOISE"}],
            }
        ),
    )

    assert "READER-VISIBLE-CHAPTER" in prompt
    assert '"status":"cornered"' in prompt
    assert '"trust":"lower"' in prompt
    for excluded in (
        "DRAFT-RECEIPT-NOISE",
        "QUALITY-AUDIT-NOISE",
        "STATE-PROVENANCE-NOISE",
        "STATE-EVIDENCE-NOISE",
        "REDUCER-AUDIT-NOISE",
        "EVENT-PROVENANCE-NOISE",
        "COST-RECEIPT-NOISE",
        "GENERIC-READER-CONTEXT-NOISE",
    ):
        assert excluded not in prompt


def _prompt_materialization(context: dict[str, object]) -> dict[str, object]:
    return {
        "materialization_hash": HASH,
        "pack_artifacts": {
            "system_instruction": {
                "ref": "system",
                "version": "v1",
                "content_hash": HASH,
                "content": {"text": "System instruction."},
            },
            "prompt_template": {
                "ref": "template",
                "version": "v1",
                "content_hash": HASH,
                "content": {
                    "text": (
                        "{{stage}} {{target_scope}} {{input_manifest}} "
                        "{{context_bundle}} {{output_schema_ref}}"
                    )
                },
            },
            "skill": {
                "ref": "skill",
                "version": "v1",
                "content_hash": HASH,
                "content": {"text": "Skill body."},
            },
        },
        "context_selection": [
            {"asset_version_id": "context:v1", "content": context}
        ],
        "knowledge_selection": [
            {"content_hash": HASH, "content": {"rules": ["causal cost"]}}
        ],
        "tool_permissions": {
            "allowed": ["model.provider.invoke"],
            "denied": ["storage.object.put"],
        },
        "output_schema": {
            "ref": "schema:stage:v1",
            "content_hash": HASH,
            "content": {"type": "object"},
        },
    }
