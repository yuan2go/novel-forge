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
    exact_ref_version,
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
    "retrieval-embed",
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
        "prose-generation-v4",
    )
    context = resolver.resolve(
        ArtifactKind.CONTEXT_POLICY,
        str(manifest.context_sources.policy_id),
        exact_ref_version(str(manifest.context_sources.policy_id)),
    )
    tool = resolver.resolve(
        ArtifactKind.TOOL_POLICY,
        str(manifest.tool_permissions.policy_id),
        exact_ref_version(str(manifest.tool_permissions.policy_id)),
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
        skill_bundle_ref="prose-generation@prose-generation-v4",
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
        prompt_compiler_version="chapter-prompt-compiler:v6",
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
        "frozen Novel Forge stage" in result.system_instruction.content["text"]
    )
    assert "{{context_bundle}}" in result.prompt_template.content["text"]
    assert "prose-generation" in result.skill.ref
    assert result.context_policy.ref == snapshot.context_policy_ref
    assert result.tool_policy.ref == snapshot.tool_policy_ref
    assert result.output_schema.ref == snapshot.output_contract_ref
    assert [item.ref for item in result.required_knowledge] == [
        "knowledge:chapter-causal-cost:v2"
    ]
    assert result.materialization_hash.startswith("sha256:")


def test_current_draft_request_renders_single_body_contract_without_operator_policy() -> (
    None
):
    from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema

    registered, snapshot = _registered_version_and_snapshot()
    pack = materialize_registered_pack_version(snapshot, registered)
    *_, request = contracts(
        backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    prompt, evidence = _materialize_chapter_codex_prompt(
        request=request, stage="draft",
        inputs={"plan": {}, "style": {}, "chapter_memo": {}, "realization_contract": {}},
        materialization={
            "materialization_hash": HASH,
            "pack_artifacts": {
                "system_instruction": pack.system_instruction.to_dict(),
                "prompt_template": pack.prompt_template.to_dict(),
                "skill": pack.skill.to_dict(),
            },
            "context_selection": [{"asset_version_id": "context:v1", "content": {"context_segments": []}}],
            "knowledge_selection": [item.to_dict() for item in pack.required_knowledge],
            "tool_permissions": {"allowed": ["model.provider.invoke"], "denied": []},
            "output_schema": {"ref": "schema:chapter-provider-output:draft:v3", "content_hash": HASH,
                              "content": chapter_provider_output_schema("draft")},
        },
    )
    assert "<tool_policy>" not in prompt
    assert "second whole-chapter body" in prompt
    assert "operator handoff" not in prompt.lower()
    assert '"required":["scene_artifacts"]' in prompt
    assert evidence["prompt_template"]["version"] == "v9"


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


def test_retrieval_embedding_contract_is_bounded_and_exact() -> None:
    resolver = default_chapter_artifact_resolver(ROOT)

    input_schema = json.loads(
        resolver.resolve(
            ArtifactKind.SCHEMA,
            "schema:execution-input:retrieval-embed:v1",
            "v1",
        ).content_json
    )
    output_schema = json.loads(
        resolver.resolve(
            ArtifactKind.SCHEMA,
            "schema:execution-output:retrieval-embed:v1",
            "v1",
        ).content_json
    )

    assert input_schema["properties"]["texts"]["maxItems"] == 32
    assert output_schema["properties"]["vectors"]["items"]["maxItems"] == 8192
    assert output_schema["additionalProperties"] is False


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
        if item["ref"] != "knowledge:chapter-causal-cost:v2"
    ]
    registered["artifact_catalog"] = catalog
    registered["artifact_catalog_hash"] = canonical_hash(catalog)

    with pytest.raises(KernelError) as raised:
        materialize_registered_pack_version(snapshot, registered)

    assert raised.value.code == "CAPABILITY_PACK_REQUIRED_ASSET_MISSING"


def test_materialization_rejects_snapshot_version_mismatch() -> None:
    registered, snapshot = _registered_version_and_snapshot()
    registered["pack_version"] = "9.9.9"

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
                {
                    "asset_version_id": "context:v1",
                    "content": {
                        "context_segments": [],
                        "language_contract": {
                            "required_language": "zh-CN",
                            "reader_facing_prose": "REQUIRED",
                        },
                    },
                }
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
    assert "governed reader-facing language is zh-CN" in prompt
    assert evidence["required_reader_facing_language"] == "zh-CN"
    assert evidence["fully_rendered_prompt_hash"].startswith("sha256:")
    assert evidence["provider_view"]["representation_policy"] == (
        "authority-projection-task-provider-v1"
    )
    assert evidence["provider_view"]["provider_context_estimated_tokens"] > 0
    assert '"contract_version":"provider-task-view-v1"' in prompt
    assert '"contract_version":"provider-context-view-v2"' in prompt


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
                "asset_version_id": "world:v1",
                "asset_type": "world_bible",
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
                    "structured_facts": [{"kind": "objective", "value": "investigate"}],
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
            "selected_inputs": [{"asset_version_id": "world:v1"}],
        },
    }
    prompt, evidence = _materialize_chapter_codex_prompt(
        request=request,
        stage="draft",
        inputs={
            "chapter": 1,
            "plan": {
                "chapter": 1,
                "objective": "Investigate the vanished ledger.",
                "provider_evidence": {"receipt": "RUNTIME-EVIDENCE-MUST-NOT-RENDER"},
            },
        },
        materialization=_prompt_materialization(context),
    )

    assert prompt.count("SEMANTIC-CONTEXT-ONCE") == 1
    assert "RUNTIME-EVIDENCE-MUST-NOT-RENDER" not in prompt
    assert evidence["provider_prompt_projection_version"] == (
        "authority-projection-task-provider-v1"
    )
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
    context = {
        "schema_version": "novelos.reader_outcome_context_bundle.v2",
        "selected_inputs": [
            {
                "asset_version_id": "draft:v1",
                "asset_type": "draft_version",
                "projection": {
                    "chapter": 1,
                    "text": "READER-VISIBLE-CHAPTER",
                    "provider_evidence": {"receipt": "DRAFT-RECEIPT-NOISE"},
                },
            },
            {
                "asset_version_id": "state:v1",
                "asset_type": "story_state_snapshot",
                "projection": {
                    "accepted_through_chapter": 1,
                    "reader_facing_state": [
                        {
                            "state_kind": "character_state",
                            "identity": {"entity_id": "protagonist"},
                            "mutation": {"status": "cornered"},
                            "provider_receipt_refs": ["STATE-RECEIPT-NOISE"],
                        }
                    ],
                    "reducer_applications": ["REDUCER-AUDIT-NOISE"],
                },
            },
            {
                "asset_version_id": "outcome:v1",
                "asset_type": "chapter_outcome",
                "projection": {
                    "state_events": [
                        {
                            "state_kind": "relationship_state",
                            "identity": {"entity_id": "pair"},
                            "mutation": {"trust": "lower"},
                        }
                    ],
                    "cost_receipt_refs": ["COST-RECEIPT-NOISE"],
                },
            },
        ],
    }
    prompt, _ = _materialize_chapter_codex_prompt(
        request=request,
        stage="reader_outcome",
        inputs={
            "chapter": 1,
            "book_id": "book-1",
            "reader_contract_version": "reader-contract-v1",
            "evaluation_profile_version": "reader-profile-v1",
        },
        materialization=_prompt_materialization(context),
    )

    assert "READER-VISIBLE-CHAPTER" in prompt
    assert '"status":"cornered"' in prompt
    assert '"trust":"lower"' in prompt
    for excluded in (
        "DRAFT-RECEIPT-NOISE",
        "STATE-RECEIPT-NOISE",
        "REDUCER-AUDIT-NOISE",
        "COST-RECEIPT-NOISE",
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
        "context_selection": [{"asset_version_id": "context:v1", "content": context}],
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


@pytest.mark.parametrize("targeted", [False, True])
def test_revision_renderer_projects_one_output_method(targeted: bool) -> None:
    from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema

    registered, snapshot = _registered_version_and_snapshot()
    pack = materialize_registered_pack_version(snapshot, registered)
    *_, request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    from novel_forge.modules.chapter_authority.chapter_plan_views import (
        build_creative_baseline,
    )

    baseline = build_creative_baseline(
        {
            "chapter": 1,
            "title": "观察",
            "premise": "观察城市",
            "source_chapter_plan_asset_version_id": "plan:v1",
            "source_chapter_plan_content_hash": HASH,
        },
        {"production_input_manifest": {"style_policy_version_id": "style:v1"},
         "context_segments": [{"asset_type": "style_policy", "asset_version_id": "style:v1", "content": {}}]},
    )
    prompt, evidence = _materialize_chapter_codex_prompt(
        request=request,
        stage="revision",
        inputs={
            "draft": {
                "chapter": 1,
                "text": "旧句。保留句。",
                "creative_baseline": baseline,
            },
            "required_actions": [],
            **(
                {"quality_edit_contract": {"source_text_hash": HASH}}
                if targeted
                else {}
            ),
        },
        materialization={
            "pack_artifacts": {
                "system_instruction": pack.system_instruction.to_dict(),
                "prompt_template": pack.prompt_template.to_dict(),
                "skill": pack.skill.to_dict(),
            },
            "context_selection": [
                {"asset_version_id": "context:v1", "content": {"context_segments": []}}
            ],
            "knowledge_selection": [item.to_dict() for item in pack.required_knowledge],
            "tool_permissions": {"allowed": ["model.provider.invoke"], "denied": []},
            "output_schema": {
                "ref": "schema:chapter-provider-output:revision:"
                + ("v4" if targeted else "v3"),
                "content_hash": HASH,
                "content": chapter_provider_output_schema(
                    "revision", targeted_revision=targeted
                ),
            },
        },
    )
    method = prompt.split("<governed_skill>\n", 1)[1].split("\n</governed_skill>", 1)[0]
    if targeted:
        assert "complete Scene Slots" not in method
        assert "Return only necessary ordered edits" in method
        assert '"required":["resolved_issue_codes","edits"]' in prompt
        assert "The host joins Slot text" not in prompt
    else:
        assert "complete Scene Slots" in method
        assert "Return only necessary ordered edits" not in method
        assert '"required":["resolved_issue_codes","scene_artifacts"]' in prompt
    assert evidence["skill"]["version"] == "prose-generation-v4"
    assert (
        evidence["provider_prompt_projection_version"]
        == "authority-projection-work-requirements.v1"
    )
    legacy = default_chapter_artifact_resolver(ROOT).resolve(ArtifactKind.SKILL, "prose-generation", "prose-generation-v2")
    assert json.loads(legacy.content_json)["text"] == (ROOT / "skills/prose-generation/legacy-v2.md").read_text()
