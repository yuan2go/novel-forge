from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from novel_forge.modules.capability_packs.artifacts import (
    ArtifactKind,
    artifact_content_hash,
    default_chapter_artifact_resolver,
)
from novel_forge.modules.book_followup_authority.contracts import (
    BOOK_FOLLOWUP_DEFINITION_VERSION,
)
from novel_forge.modules.production_execution.capability_registry import (
    PLANNING_TIMEOUT_POLICY_VERSION,
    default_capability_registry,
)
from novel_forge.modules.story_planning_runtime.domain import (
    STORY_PLANNING_OPERATION_DEFINITION_REF,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    STORY_PLANNING_WORKFLOW_DEFINITION_REF,
)
from novel_forge.modules.story_design_authority import (
    required_qualification_profiles,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NARRATIVE_EVALUATION_DEFINITION,
    NARRATIVE_EVALUATION_HANDLER,
    NARRATIVE_EVALUATION_VERSION,
)

_BASE_PACK = "config/capability_packs/historical/chapter_generation_pack_2_26_0.json"
STORY_PLANNING_PROMPT_VERSION = "v12"
NARRATIVE_EVALUATION_PROMPT_VERSION = "v3"


@dataclass(frozen=True, slots=True)
class LongformCapabilityPackProfile:
    pack_id: str
    workflow_ref: str
    manifest: dict[str, Any]
    artifact_catalog: dict[str, Any]
    agent_skill_ref: str


def build_world_sampling_pack_profile(source: LongformCapabilityPackProfile, *, application_build_id: str,
                                     commit_sha: str, reference_samples: bool = False) -> LongformCapabilityPackProfile:
    from novel_forge.modules.story_planning_runtime.world_sampling import (
        WORLD_REFERENCE_SAMPLE_VERSION,
        WORLD_SAMPLE_SCOPE,
        WORLD_SAMPLE_VERSION,
        world_sample_definitions,
    )
    from novel_forge.storage.authority_repositories import definition_hash

    manifest = deepcopy(source.manifest)
    template = next(item for item in manifest["workflow_template"]["nodes"] if item["node_id"] == "chapter_plan.generate")
    nodes = []
    version = WORLD_REFERENCE_SAMPLE_VERSION if reference_samples else WORLD_SAMPLE_VERSION
    workflow_ref = "world_provider_sampling@" + version
    for definition in world_sample_definitions(application_build_id=application_build_id, commit_sha=commit_sha,
                                              reference_samples=reference_samples):
        stage = "world_candidates." + definition["name"].rsplit(".", 1)[1]
        node = deepcopy(template)
        node.update(node_id=stage, stage=stage, operation_name=definition["name"],
            operation_definition_ref=definition["name"] + "@" + version,
            operation_definition_hash=definition_hash(definition), handler_key=definition["handler_key"],
            output_asset_types=["world_provider_sample"], depends_on=[],
            retry_policy={**definition["retry_policy"], "retryable_errors": []})
        nodes.append(node)
    pack_id = source.pack_id + (".world_reference_sampling" if reference_samples else ".world_sampling")
    manifest["identity"].update(pack_id=pack_id, name="World Provider Sampling Pack",
                               description="Isolated World stage samples using frozen native Planning inputs.")
    manifest["workflow_template"].update(workflow_id="world_provider_sampling", workflow_version=version,
        idempotency_scope=WORLD_SAMPLE_SCOPE, nodes=nodes, completion={"required_terminal_nodes": [node["node_id"] for node in nodes],
            "required_evidence": ["trace", "audit"], "required_output_asset_types": ["world_provider_sample"]})
    tool = next(item for item in manifest["tool_permissions"]["tools"] if item["tool_ref"] == "model.provider.invoke")
    tool["allowed_operations"] = [node["node_id"] for node in nodes]
    manifest["tool_permissions"]["tools"] = [tool]
    manifest["evaluation"]["required_gates"] = [{"gate_id": "world_sample_source_isolation",
        "judge_capability_id": "quality.originality.judge", "blocking": True, "threshold": 1,
        "required_evidence": ["world_provider_sample"]}]
    manifest["evaluation"]["metrics"] = []
    return LongformCapabilityPackProfile(pack_id=pack_id, workflow_ref=workflow_ref, manifest=manifest,
        artifact_catalog=deepcopy(source.artifact_catalog), agent_skill_ref=source.agent_skill_ref)


def build_story_planning_pack_profile(
    repository_root: str | Path,
    *,
    operation_definition_hash: str,
    pack_id: str = "story_planning_pack",
    execution_contract_version: str | None = None,
    planning_task_token_budget: int | None = None,
    narrative_intent_boundary: bool = True,
    event_first_planning: bool = False,
) -> LongformCapabilityPackProfile:
    version = execution_contract_version or STORY_PLANNING_OPERATION_DEFINITION_REF.rpartition("@")[2]
    if version not in {"1.11.0", "1.12.0", "1.13.0", "1.14.0", "1.15.0", "1.16.0", "1.17.0", "1.18.0", "1.19.0", "1.21.0"}:
        raise ValueError("Unsupported Planning execution contract")
    intent_boundary = narrative_intent_boundary and version == "1.21.0"
    if event_first_planning and not intent_boundary:
        raise ValueError("Event-first methods require the current narrative intent contract")
    operation_ref = f"story_planning.generate@{version}"
    root, manifest, artifacts = _base(repository_root, pack_id)
    if version != "1.21.0":
        artifacts = [item for item in artifacts if not (
            item["kind"] == ArtifactKind.SKILL.value and item["ref"] == "quality-review"
            and item["version"] == "quality-review-v4")]
        for item in artifacts:
            if item["kind"] == ArtifactKind.SKILL.value and item["ref"] == "quality-review" and item["version"] == "quality-review-v3":
                item["source_identity"] = "skills/quality-review/SKILL.md"
    if planning_task_token_budget is not None:
        if type(planning_task_token_budget) is not int or not 0 < planning_task_token_budget <= min(512000, manifest["context_sources"]["max_tokens"]):
            raise ValueError("Planning Context target must fit the system ceiling")
        manifest["context_sources"]["planning_task_token_budget"] = planning_task_token_budget
    from novel_forge.modules.story_planning_runtime.foundation_generation import (
        FOUNDATION_CAPABILITIES,
    )

    capabilities = (
        *FOUNDATION_CAPABILITIES,
        ("book_plan.generate", "planning.book.generate"),
        ("volume_plan.generate", "planning.volume.generate"),
        ("arc_plan.generate", "planning.arc.generate"),
        ("chapter_group_plan.generate", "planning.chapter_group.generate"),
        ("chapter_plan.generate", "planning.story_chapter.generate"),
    )
    _require_hash(operation_definition_hash)
    template = next(
        item
        for item in manifest["workflow_template"]["nodes"]
        if item.get("node_id") == "draft"
    )
    nodes: list[dict[str, Any]] = []
    for stage, capability in capabilities:
        node = deepcopy(template)
        node.update(
            node_id=stage,
            operation_name="story_planning.generate",
            operation_definition_ref=operation_ref,
            operation_definition_hash=operation_definition_hash,
            handler_key="novel_forge.story_planning.generate",
            stage=stage,
            capability_id=capability,
            input_asset_types=["planning_generation_input_snapshot"],
            output_asset_types=["planning_generation_candidate"],
            depends_on=[],
            commit_authority="STORY_DESIGN_AUTHORITY",
            retry_policy={
                "max_attempts": 3,
                "retryable_errors": [],
                "dead_letter_on_exhausted": True,
            },
            timeout_policy_ref=(
                f"timeout:{capability.replace('.', '-')}:{PLANNING_TIMEOUT_POLICY_VERSION}"
            ),
        )
        nodes.append(node)
    manifest["identity"].update(
        version="2.15.0" if event_first_planning else "2.14.0" if intent_boundary else "2.13.0" if version == "1.21.0" else "2.11.0" if version == "1.19.0" else "2.10.0" if version == "1.18.0" else "2.9.0" if version == "1.17.0" else "2.8.0",
        name="Story Planning Generator Pack",
        domain="story_planning",
        description="Governed Foundation formation and hierarchical Planning candidate generation.",
    )
    manifest["compatibility"]["required_capabilities"] = [
        *(item[1] for item in capabilities),
        "quality.originality.judge",
    ]
    manifest["workflow_template"].update(
        workflow_id="story_planning_generators",
        workflow_version=STORY_PLANNING_WORKFLOW_DEFINITION_REF.rpartition("@")[2],
        nodes=nodes,
        completion={
            "required_terminal_nodes": [item[0] for item in capabilities],
            "required_evidence": ["trace", "audit"],
            "required_output_asset_types": ["planning_generation_candidate"],
        },
    )
    manifest["context_sources"]["allowed_asset_types"] = sorted(
        {
            *manifest["context_sources"]["allowed_asset_types"],
            "planning_generation_input_snapshot",
        }
    )
    manifest["tool_permissions"]["tools"] = [
        {
            **manifest["tool_permissions"]["tools"][0],
            "allowed_operations": [item[0] for item in capabilities],
        }
    ]
    manifest["evaluation"]["required_gates"] = [
        {
            "gate_id": "planning_source_isolation",
            "judge_capability_id": "quality.originality.judge",
            "blocking": True,
            "threshold": 1,
            "required_evidence": ["planning_generation_candidate"],
        }
    ]
    manifest["evaluation"]["metrics"] = []
    artifacts = _bind_domain_artifacts(
        root,
        manifest,
        artifacts,
        skill_ref="long-outline",
        skill_version="long-outline-v5" if event_first_planning else "long-outline-v4" if intent_boundary else "long-outline-v3" if version in {"1.18.0", "1.19.0", "1.21.0"} else "long-outline-v2",
        skill_path="skills/long-outline/SKILL.md" if event_first_planning else "skills/long-outline/legacy-event-planning-20261011.md" if intent_boundary else "skills/long-outline/legacy-narrative-intent-20261010.md" if version in {"1.18.0", "1.19.0", "1.21.0"} else "config/capability_packs/artifacts/long_outline_work_v2.md",
        system_ref="prompt-system:story-planning-pack",
        system_path=(
            "config/capability_packs/artifacts/story_planning_system_instruction_v12.md" if intent_boundary else "config/capability_packs/artifacts/story_planning_system_instruction_v11.md" if version == "1.21.0" else "config/capability_packs/artifacts/story_planning_system_instruction_v9.md" if version == "1.19.0" else "config/capability_packs/artifacts/story_planning_system_instruction.md"
        ),
        template_ref="prompt-template:story-planning-pack",
        template_path=("config/capability_packs/artifacts/story_planning_template_v3.md" if intent_boundary else "config/capability_packs/artifacts/story_planning_template_v2.md" if version == "1.21.0" else "config/capability_packs/artifacts/story_planning_template.md"),
        template_version="v3" if intent_boundary else "v2" if version == "1.21.0" else "v1",
        input_schema_ref="schema:story-planning-pack-input:v2" if intent_boundary else "schema:story-planning-pack-input:v1",
        output_schema_ref="schema:story-planning-pack-output:v2" if intent_boundary else "schema:story-planning-pack-output:v1",
        system_version=STORY_PLANNING_PROMPT_VERSION if intent_boundary else "v11" if version == "1.21.0" else "v9" if version == "1.19.0" else "v8",
    )
    artifacts = _bind_planning_qualification_skills(root, manifest, artifacts, aligned_methods=version in {"1.18.0", "1.19.0", "1.21.0"}, historical_methods=version != "1.21.0", narrative_intent_boundary=intent_boundary)
    _update_policy_artifacts(manifest, artifacts)
    for _stage, capability in capabilities:
        _append_capability_schemas(artifacts, capability)
        _append_artifact(
            artifacts,
            ArtifactKind.TIMEOUT_POLICY,
            f"timeout:{capability.replace('.', '-')}:{PLANNING_TIMEOUT_POLICY_VERSION}",
            PLANNING_TIMEOUT_POLICY_VERSION,
            {
                "policy_id": (
                    f"timeout:{capability.replace('.', '-')}:{PLANNING_TIMEOUT_POLICY_VERSION}"
                ),
                "operation_timeout_seconds": STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
                "timeout_action": "FAIL_ATTEMPT",
                "authority_binding": operation_ref,
            },
            "generated:story-planning-pack-profile",
        )
    return LongformCapabilityPackProfile(
        pack_id,
        STORY_PLANNING_WORKFLOW_DEFINITION_REF,
        manifest,
        _catalog(artifacts),
        "long-outline",
    )


def build_reader_outcome_pack_profile(
    repository_root: str | Path,
    *,
    operation_definition_hash: str,
    pack_id: str = "reader_outcome_pack",
    coordinated_contract: bool = False,
) -> LongformCapabilityPackProfile:
    from novel_forge.modules.book_followup_authority.contracts import READER_OUTCOME_DEFINITION_VERSION

    version = READER_OUTCOME_DEFINITION_VERSION if coordinated_contract else BOOK_FOLLOWUP_DEFINITION_VERSION
    root, manifest, artifacts = _base(repository_root, pack_id)
    _require_hash(operation_definition_hash)
    manifest["identity"]["version"] = "1.6.0" if coordinated_contract else "1.2.0"
    template = next(
        item
        for item in manifest["workflow_template"]["nodes"]
        if item.get("node_id") == "draft"
    )
    node = deepcopy(template)
    node.update(
        node_id="reader_outcome",
        operation_name="reader_outcome.evaluate",
        operation_definition_ref=(
            f"reader_outcome.evaluate@{version}"
        ),
        operation_definition_hash=operation_definition_hash,
        handler_key=("novel_forge.book_followup_authority.reader_outcome.evaluate"),
        stage="reader_outcome",
        capability_id="quality.reader_outcome.judge",
        input_asset_types=["best_draft_candidate" if coordinated_contract else "draft_version", "canon_snapshot"],
        output_asset_types=["reader_outcome_report"],
        depends_on=[],
        commit_authority="BOOK_FOLLOWUP_AUTHORITY",
        timeout_policy_ref="timeout:quality-reader_outcome-judge:v1",
    )
    manifest["identity"].update(
        name="Reader Outcome Pack",
        domain="book_followup",
        description="Governed Reader Outcome execution constrained to SHADOW evidence.",
    )
    manifest["compatibility"]["required_capabilities"] = [
        "quality.reader_outcome.judge",
        "quality.originality.judge",
    ]
    manifest["workflow_template"].update(
        workflow_id="book_followup_reader_outcome",
        workflow_version=version,
        nodes=[node],
        completion={
            "required_terminal_nodes": ["reader_outcome"],
            "required_evidence": ["trace", "audit"],
            "required_output_asset_types": ["reader_outcome_report"],
        },
    )
    manifest["context_sources"]["allowed_asset_types"] = [
        "draft_version",
        "canon_snapshot",
        "context_bundle",
    ]
    if coordinated_contract:
        manifest["context_sources"]["allowed_asset_types"].append("best_draft_candidate")
    manifest["tool_permissions"]["tools"] = [
        {
            **manifest["tool_permissions"]["tools"][0],
            "allowed_operations": ["reader_outcome"],
        }
    ]
    manifest["evaluation"]["required_gates"] = [
        {
            "gate_id": "reader_outcome_source_isolation",
            "judge_capability_id": "quality.originality.judge",
            "blocking": True,
            "threshold": 1,
            "required_evidence": ["reader_outcome_report"],
        }
    ]
    manifest["evaluation"]["metrics"] = []
    artifacts = _bind_domain_artifacts(
        root,
        manifest,
        artifacts,
        skill_ref="reader-feedback",
        skill_version="reader-feedback-v2",
        skill_path="skills/reader-feedback/SKILL.md",
        system_ref="prompt-system:reader-outcome-pack",
        system_path=(
            "config/capability_packs/artifacts/reader_outcome_system_instruction.md"
        ),
        template_ref="prompt-template:reader-outcome-pack",
        template_path=("config/capability_packs/artifacts/reader_outcome_template.md"),
        input_schema_ref="schema:reader-outcome-pack-input:v1",
        output_schema_ref="schema:reader-outcome-pack-output:v1",
        template_version="v2",
    )
    _update_policy_artifacts(manifest, artifacts)
    _append_capability_schemas(artifacts, "quality.reader_outcome.judge")
    _append_artifact(
        artifacts,
        ArtifactKind.TIMEOUT_POLICY,
        "timeout:quality-reader_outcome-judge:v1",
        "v1",
        {
            "policy_id": "timeout:quality-reader_outcome-judge:v1",
            "operation_timeout_seconds": 180,
            "timeout_action": "FAIL_ATTEMPT",
            "authority_binding": (
                f"reader_outcome.evaluate@{version}"
            ),
        },
        "generated:reader-outcome-pack-profile",
    )
    return LongformCapabilityPackProfile(
        pack_id,
        f"book_followup_reader_outcome@{version}",
        manifest,
        _catalog(artifacts),
        "reader-feedback",
    )


def build_longform_prose_review_pack_profile(
    repository_root: str | Path,
    *,
    operation_definition_hash: str,
    pack_id: str = "longform_prose_review_pack",
    literal_citations: bool = True,
) -> LongformCapabilityPackProfile:
    root, manifest, artifacts = _base(repository_root, pack_id)
    _require_hash(operation_definition_hash)
    manifest["identity"]["version"] = "1.5.0" if literal_citations else "1.4.0"
    template = next(
        item
        for item in manifest["workflow_template"]["nodes"]
        if item.get("node_id") == "draft"
    )
    node = deepcopy(template)
    node.update(
        node_id="longform_prose_review",
        operation_name="longform.prose_review",
        operation_definition_ref=(
            f"longform.prose_review@{BOOK_FOLLOWUP_DEFINITION_VERSION}"
        ),
        operation_definition_hash=operation_definition_hash,
        handler_key=("novel_forge.book_followup_authority.longform.prose_review"),
        stage="longform_prose_review",
        capability_id="review.chapter.evaluate",
        input_asset_types=["longform_prose_review_window"],
        output_asset_types=["longform_prose_review_report"],
        depends_on=[],
        commit_authority="BOOK_FOLLOWUP_AUTHORITY",
        timeout_policy_ref="timeout:review-chapter-evaluate:v1",
    )
    manifest["identity"].update(
        name="Longform Prose Review Pack",
        domain="book_followup",
        description="Governed Longform Prose Review execution constrained to SHADOW evidence.",
    )
    manifest["compatibility"]["required_capabilities"] = [
        "review.chapter.evaluate",
        "quality.originality.judge",
    ]
    manifest["workflow_template"].update(
        workflow_id="book_followup_longform_prose_review",
        workflow_version=BOOK_FOLLOWUP_DEFINITION_VERSION,
        nodes=[node],
        completion={
            "required_terminal_nodes": ["longform_prose_review"],
            "required_evidence": ["trace", "audit"],
            "required_output_asset_types": ["longform_prose_review_report"],
        },
    )
    manifest["context_sources"]["allowed_asset_types"] = [
        "longform_prose_review_window",
        "context_bundle",
    ]
    manifest["tool_permissions"]["tools"] = [
        {
            **manifest["tool_permissions"]["tools"][0],
            "allowed_operations": ["longform_prose_review"],
        }
    ]
    manifest["evaluation"]["required_gates"] = [
        {
            "gate_id": "longform_prose_review_source_isolation",
            "judge_capability_id": "quality.originality.judge",
            "blocking": True,
            "threshold": 1,
            "required_evidence": ["longform_prose_review_report"],
        }
    ]
    manifest["evaluation"]["metrics"] = []
    artifacts = _bind_domain_artifacts(
        root,
        manifest,
        artifacts,
        skill_ref="quality-review",
        skill_version="quality-review-v5",
        skill_path="skills/quality-review/SKILL.md",
        system_ref="prompt-system:longform-prose-review-pack",
        system_path=(
            "config/capability_packs/artifacts/longform_prose_review_system_instruction_v2.md" if literal_citations else "config/capability_packs/artifacts/longform_prose_review_system_instruction.md"
        ),
        template_ref="prompt-template:longform-prose-review-pack",
        template_path=("config/capability_packs/artifacts/longform_prose_review_template_v3.md" if literal_citations else "config/capability_packs/artifacts/longform_prose_review_template.md"),
        input_schema_ref="schema:longform-prose-review-pack-input:v1",
        output_schema_ref="schema:longform-prose-review-pack-output:v1",
        system_version="v2" if literal_citations else "v1",
        template_version="v3" if literal_citations else "v2",
    )
    _update_policy_artifacts(manifest, artifacts)
    _append_capability_schemas(artifacts, "review.chapter.evaluate")
    _append_artifact(
        artifacts,
        ArtifactKind.TIMEOUT_POLICY,
        "timeout:review-chapter-evaluate:v1",
        "v1",
        {
            "policy_id": "timeout:review-chapter-evaluate:v1",
            "operation_timeout_seconds": 180,
            "timeout_action": "FAIL_ATTEMPT",
            "authority_binding": (
                f"longform.prose_review@{BOOK_FOLLOWUP_DEFINITION_VERSION}"
            ),
        },
        "generated:longform-prose-review-pack-profile",
    )
    return LongformCapabilityPackProfile(
        pack_id,
        f"book_followup_longform_prose_review@{BOOK_FOLLOWUP_DEFINITION_VERSION}",
        manifest,
        _catalog(artifacts),
        "quality-review",
    )


def build_longform_prose_review_sample_pack_profile(
    source: LongformCapabilityPackProfile, *, operation_definition_hash: str,
) -> LongformCapabilityPackProfile:
    from novel_forge.modules.book_followup_authority.prose_sampling import (
        PROSE_SAMPLE_DEFINITION, PROSE_SAMPLE_VERSION, PROSE_SAMPLE_WORKFLOW, PROSE_SAMPLE_TYPE,
    )

    _require_hash(operation_definition_hash)
    manifest = deepcopy(source.manifest)
    node = manifest["workflow_template"]["nodes"][0]
    if node["operation_name"] != "longform.prose_review" or len(manifest["workflow_template"]["nodes"]) != 1:
        raise ValueError("prose sampling must retain the formal prose review producer")
    node.update(operation_name=PROSE_SAMPLE_DEFINITION,
        operation_definition_ref=PROSE_SAMPLE_DEFINITION + "@" + PROSE_SAMPLE_VERSION,
        operation_definition_hash=operation_definition_hash,
        handler_key="novel_forge.book_followup_authority." + PROSE_SAMPLE_DEFINITION,
        output_asset_types=[PROSE_SAMPLE_TYPE])
    pack_id = source.pack_id + ".samples"
    manifest["identity"].update(pack_id=pack_id, version=source.manifest["identity"]["version"],
        name="Longform Prose Reviewer Sample Pack", description="Independent reviewer benchmark samples remain ineligible for production findings.")
    manifest["workflow_template"].update(workflow_id=PROSE_SAMPLE_WORKFLOW.split("@")[0], workflow_version=PROSE_SAMPLE_VERSION)
    manifest["workflow_template"]["completion"]["required_output_asset_types"] = [PROSE_SAMPLE_TYPE]
    for gate in manifest["evaluation"]["required_gates"]:
        gate["required_evidence"] = [PROSE_SAMPLE_TYPE if kind == "longform_prose_review_report" else kind for kind in gate["required_evidence"]]
    return LongformCapabilityPackProfile(pack_id, PROSE_SAMPLE_WORKFLOW, manifest, deepcopy(source.artifact_catalog), source.agent_skill_ref)


def build_narrative_evaluation_pack_profile(
    repository_root: str | Path,
    *,
    operation_definition_hash: str,
    pack_id: str = "narrative_semantic_evaluation_pack",
) -> LongformCapabilityPackProfile:

    root, manifest, artifacts = _base(repository_root, pack_id)
    _require_hash(operation_definition_hash)
    template = next(
        item
        for item in manifest["workflow_template"]["nodes"]
        if item.get("node_id") == "draft"
    )
    node = deepcopy(template)
    node.update(
        node_id="narrative_semantic_evaluation",
        operation_name=NARRATIVE_EVALUATION_DEFINITION,
        operation_definition_ref=(
            f"{NARRATIVE_EVALUATION_DEFINITION}@{NARRATIVE_EVALUATION_VERSION}"
        ),
        operation_definition_hash=operation_definition_hash,
        handler_key=NARRATIVE_EVALUATION_HANDLER,
        stage="narrative_semantic_evaluation",
        capability_id="quality.intrinsic.judge",
        input_asset_types=[
            "book_design",
            "planning_generation_candidate",
            "context_bundle",
        ],
        output_asset_types=["narrative_design_evaluation"],
        depends_on=[],
        commit_authority="STORY_DESIGN_AUTHORITY",
        retry_policy={
            "max_attempts": 3,
            "retryable_errors": [],
            "dead_letter_on_exhausted": True,
        },
        timeout_policy_ref="timeout:quality-intrinsic-judge:v1",
    )
    manifest["identity"].update(
        version="2.27.0",
        name="Narrative Semantic Evaluation Pack",
        domain="story_design",
        description=(
            "Independent governed semantic evaluation for immutable design candidates."
        ),
    )
    manifest["compatibility"]["required_capabilities"] = [
        "quality.intrinsic.judge",
        "quality.originality.judge",
    ]
    manifest["workflow_template"].update(
        workflow_id="story_design_semantic_evaluation",
        workflow_version=NARRATIVE_EVALUATION_VERSION,
        nodes=[node],
        completion={
            "required_terminal_nodes": ["narrative_semantic_evaluation"],
            "required_evidence": ["trace", "audit", "model_call_log"],
            "required_output_asset_types": ["narrative_design_evaluation"],
        },
    )
    manifest["context_sources"]["allowed_asset_types"] = [
        "book_design",
        "planning_generation_candidate",
        "context_bundle",
    ]
    manifest["tool_permissions"]["tools"] = [
        {
            **manifest["tool_permissions"]["tools"][0],
            "allowed_operations": ["narrative_semantic_evaluation"],
        }
    ]
    manifest["evaluation"]["required_gates"] = [
        {
            "gate_id": "narrative_evaluation_source_isolation",
            "judge_capability_id": "quality.originality.judge",
            "blocking": True,
            "threshold": 1,
            "required_evidence": ["narrative_design_evaluation"],
        }
    ]
    manifest["evaluation"]["metrics"] = []
    artifacts = _bind_domain_artifacts(
        root,
        manifest,
        artifacts,
        skill_ref="quality-review",
        skill_version="quality-review-v5",
        skill_path="skills/quality-review/SKILL.md",
        system_ref="prompt-system:narrative-semantic-evaluation-pack",
        system_path=(
            "config/capability_packs/artifacts/"
            "narrative_evaluation_system_instruction.md"
        ),
        template_ref="prompt-template:narrative-semantic-evaluation-pack",
        template_path=(
            "config/capability_packs/artifacts/narrative_evaluation_template.md"
        ),
        input_schema_ref="schema:narrative-semantic-evaluation-pack-input:v1",
        output_schema_ref="schema:narrative-semantic-evaluation-pack-output:v1",
        system_version=NARRATIVE_EVALUATION_PROMPT_VERSION,
    )
    _update_policy_artifacts(manifest, artifacts)
    _append_capability_schemas(artifacts, "quality.intrinsic.judge")
    return LongformCapabilityPackProfile(
        pack_id,
        f"story_design_semantic_evaluation@{NARRATIVE_EVALUATION_VERSION}",
        manifest,
        _catalog(artifacts),
        "quality-review",
    )


def _base(
    repository_root: str | Path, pack_id: str
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    root = Path(repository_root).resolve()
    manifest = json.loads((root / _BASE_PACK).read_text(encoding="utf-8"))
    manifest["identity"]["pack_id"] = pack_id
    artifacts = [
        item.to_dict() for item in default_chapter_artifact_resolver(root, include_current_contracts=False).artifacts()
    ]
    return root, manifest, artifacts


def _bind_domain_artifacts(
    root: Path,
    manifest: dict[str, Any],
    artifacts: list[dict[str, Any]],
    *,
    skill_ref: str,
    skill_version: str,
    skill_path: str,
    system_ref: str,
    system_path: str,
    template_ref: str,
    template_path: str,
    input_schema_ref: str,
    output_schema_ref: str,
    system_version: str = "v1",
    template_version: str = "v1",
) -> list[dict[str, Any]]:
    skill_content = {"text": _text(root, skill_path)}
    system_content = {"text": _text(root, system_path)}
    template_content = {"text": _text(root, template_path)}
    _append_artifact(
        artifacts,
        ArtifactKind.SKILL,
        skill_ref,
        skill_version,
        skill_content,
        skill_path,
    )
    _append_artifact(
        artifacts,
        ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
        system_ref,
        system_version,
        system_content,
        system_path,
    )
    _append_artifact(
        artifacts,
        ArtifactKind.PROMPT_TEMPLATE,
        template_ref,
        template_version,
        template_content,
        template_path,
    )
    for schema_ref, role in (
        (input_schema_ref, "input"),
        (output_schema_ref, "output"),
    ):
        _append_artifact(
            artifacts,
            ArtifactKind.SCHEMA,
            schema_ref,
            schema_ref.rpartition(":")[2],
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": f"novel-forge://schemas/{schema_ref.removeprefix('schema:')}",
                "title": f"Governed long-form Pack {role} envelope",
                "type": "object",
                "additionalProperties": True,
            },
            "generated:longform-pack-domain-schema",
        )
    manifest["skill_binding"]["skills"] = [
        {
            "skill_ref": skill_ref,
            "version": skill_version,
            "content_hash": artifact_content_hash(skill_content),
            "required": True,
            "input_contract_ref": input_schema_ref,
            "output_contract_ref": output_schema_ref,
            "preconditions": ["frozen_authority_inputs"],
            "postconditions": ["schema_backed_candidate"],
            "depends_on": [],
            "max_invocations_per_run": 1,
            "drift_policy": "FAIL_CLOSED",
        }
    ]
    manifest["prompt_binding"].update(
        system_instruction_ref=system_ref,
        system_instruction_version=system_version,
        system_instruction_hash=artifact_content_hash(system_content),
        template_ref=template_ref,
        template_version=template_version,
        template_hash=artifact_content_hash(template_content),
        input_schema_ref=input_schema_ref,
        output_schema_ref=output_schema_ref,
    )
    return artifacts


def _bind_planning_qualification_skills(
    root: Path,
    manifest: dict[str, Any],
    artifacts: list[dict[str, Any]],
    *, aligned_methods: bool = False, historical_methods: bool = False,
    narrative_intent_boundary: bool = False,
) -> list[dict[str, Any]]:
    skill_paths = {
        "topic-development": "skills/topic-development/SKILL.md",
        "worldbuilding": "skills/worldbuilding/SKILL.md",
        "hot-novel-business-deconstruction": "skills/hot-novel-business-deconstruction/SKILL.md",
        "long-outline": "skills/long-outline/SKILL.md",
        "character-design": "skills/character-design/SKILL.md",
        "canon-continuity-graph": "skills/canon-continuity-graph/SKILL.md",
        "narrative-beat-design": "skills/narrative-beat-design/SKILL.md",
        "chapter-outline": "skills/chapter-outline/SKILL.md",
    }
    bindings = {
        str(item["skill_ref"]): item for item in manifest["skill_binding"]["skills"]
    }
    required = {
        profile.skill_ref
        for stage in (
            "creative.candidates.generate", "theme.candidates.generate",
            "ending.intent.generate", "reader.promise.generate",
            "world.design.generate", "character.cast.generate",
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
            "chapter_group_plan.generate",
            "chapter_plan.generate",
        )
        for profile in required_qualification_profiles(stage)
    }
    for skill_ref in sorted(required):
        if skill_ref in bindings:
            continue
        path = skill_paths[skill_ref]
        version = f"{skill_ref}-qualification-v2"
        if skill_ref == "character-design" and not historical_methods:
            if aligned_methods:
                version = f"{skill_ref}-qualification-v3"
            else:
                path = "config/capability_packs/artifacts/character_design_work_v2.md"
        if skill_ref == "narrative-beat-design":
            if aligned_methods:
                version = f"{skill_ref}-qualification-v3"
            else:
                path = "config/capability_packs/artifacts/narrative_beat_design_work_v2.md"
        snapshot_path = {
            "skills/hot-novel-business-deconstruction/SKILL.md": "skills/hot-novel-business-deconstruction/legacy-v1.0.0.md",
            "skills/character-design/SKILL.md": "config/capability_packs/artifacts/character_design_work_v3.md",
        }.get(path, path) if historical_methods else path
        if skill_ref in {"topic-development", "worldbuilding", "character-design", "narrative-beat-design", "chapter-outline"}:
            if narrative_intent_boundary:
                version = f"{skill_ref}-qualification-v4"
            elif snapshot_path == f"skills/{skill_ref}/SKILL.md":
                snapshot_path = f"skills/{skill_ref}/legacy-narrative-intent-20261010.md"
        content = {"text": _text(root, snapshot_path)}
        _append_artifact(
            artifacts,
            ArtifactKind.SKILL,
            skill_ref,
            version,
            content,
            path,
        )
        bindings[skill_ref] = {
            "skill_ref": skill_ref,
            "version": version,
            "content_hash": artifact_content_hash(content),
            "required": True,
            "input_contract_ref": "schema:story-planning-pack-input:v2" if narrative_intent_boundary else "schema:story-planning-pack-input:v1",
            "output_contract_ref": "schema:story-planning-pack-output:v2" if narrative_intent_boundary else "schema:story-planning-pack-output:v1",
            "preconditions": ["frozen_authority_inputs"],
            "postconditions": ["typed_narrative_semantic_evaluation"],
            "depends_on": [],
            "max_invocations_per_run": 1,
            "drift_policy": "FAIL_CLOSED",
        }
    manifest["skill_binding"]["skills"] = [bindings[key] for key in sorted(bindings)]
    return artifacts


def _update_policy_artifacts(
    manifest: dict[str, Any], artifacts: list[dict[str, Any]]
) -> None:
    for artifact in artifacts:
        if artifact["ref"] == manifest["context_sources"]["policy_id"]:
            if "planning_task_token_budget" in manifest["context_sources"]:
                artifact["content"]["planning_task_token_budget"] = manifest["context_sources"]["planning_task_token_budget"]
            artifact["content"]["allowed_asset_types"] = list(
                manifest["context_sources"]["allowed_asset_types"]
            )
            artifact["content_hash"] = artifact_content_hash(artifact["content"])
        elif artifact["ref"] == manifest["tool_permissions"]["policy_id"]:
            artifact["content"]["explicit_tool_refs"] = ["model.provider.invoke"]
            artifact["content_hash"] = artifact_content_hash(artifact["content"])


def _append_capability_schemas(
    artifacts: list[dict[str, Any]], capability_id: str
) -> None:
    contract = default_capability_registry().resolve(capability_id)
    for schema_ref in (contract.input_schema_ref, contract.output_schema_ref):
        _append_artifact(
            artifacts,
            ArtifactKind.SCHEMA,
            schema_ref,
            "v1",
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": True,
            },
            "generated:longform-pack-capability-schema",
        )


def _append_artifact(
    artifacts: list[dict[str, Any]],
    kind: ArtifactKind,
    ref: str,
    version: str,
    content: Any,
    source_identity: str,
) -> None:
    candidate = {
        "kind": kind.value,
        "ref": ref,
        "version": version,
        "content": content,
        "content_hash": artifact_content_hash(content),
        "source_identity": source_identity,
    }
    for index, existing in enumerate(artifacts):
        if (existing["kind"], existing["ref"], existing["version"]) == (
            candidate["kind"],
            ref,
            version,
        ):
            artifacts[index] = candidate
            return
    artifacts.append(candidate)


def _catalog(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "novelos.capability_pack.artifact_catalog.v1",
        "artifacts": artifacts,
    }


def _text(root: Path, relative_path: str) -> str:
    return (root / relative_path).read_text(encoding="utf-8").replace("\r\n", "\n")


def _require_hash(value: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError("operation_definition_hash must be a SHA-256 authority hash")


__all__ = [
    "LongformCapabilityPackProfile",
    "STORY_PLANNING_PROMPT_VERSION",
    "NARRATIVE_EVALUATION_PROMPT_VERSION",
    "build_narrative_evaluation_pack_profile",
    "build_reader_outcome_pack_profile",
    "build_longform_prose_review_pack_profile",
    "build_story_planning_pack_profile",
]
