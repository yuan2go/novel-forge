"""Storage-free chapter handlers for PostgreSQL authority execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

from novel_forge.modules.chapter_authority.contracts import (
    ChapterAuxiliaryOutput,
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterHandlerRequest,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.domain_handlers import (
    build_canon_extraction,
    build_canon_patch,
    build_context_bundle,
    build_export_package,
    build_final_release_gate,
    build_publish_gate,
    build_quality_report,
    normalize_draft_result,
    normalize_review_result,
    normalize_rereview_result,
    normalize_revision_result,
)
from novel_forge.modules.chapter_authority.chapter_plan_views import (
    build_draft_context_view,
    build_draft_plan_view,
    build_draft_style_view,
    normalize_authoritative_chapter_plan,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ChapterModelPort,
    ModelProviderResult,
)
from novel_forge.modules.chapter_quality_authority import (
    QUALITY_GROUPS,
    build_quality_group_evidence,
    build_quality_context_view,
)
from novel_forge.modules.canon_graph.approval_domain import (
    build_canon_change_proposal,
    resolve_canon_extraction,
)


class DeterministicFixtureChapterProvider:
    """Deterministic acceptance provider; never presented as a real model call."""

    provider_id = "deterministic_chapter_fixture_v1"
    external_effect_backed = False

    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
    ) -> ModelProviderResult:
        if stage == "draft":
            plan = payload["plan"]
            output = {
                "text": (
                    f"{plan['premise']} The choice is made in public. "
                    "The promise is kept, but its cost remains too abstract."
                )
            }
        elif stage == "review":
            output = {
                "decision": "NEEDS_REVISION",
                "score": 72,
                "issues": [
                    {
                        "code": "COST_NOT_CONCRETE",
                        "severity": "blocking",
                        "message": "The promised cost must become visible in the scene.",
                    }
                ],
            }
        elif stage == "revision":
            draft = payload["draft"]
            review = payload["review"]
            output = {
                "text": (
                    f"{draft['text']} The protagonist surrenders the only safe route home "
                    "before the witnesses leave, making the cost irreversible."
                ),
                "resolved_issue_codes": [str(item["code"]) for item in review["issues"]],
                "canon_assertions": [
                    {
                        "subject": "protagonist",
                        "predicate": "gave_up",
                        "object": "safe_route_home",
                        "effective_chapter": draft["chapter"],
                    }
                ],
            }
        elif stage == "rereview":
            revision = payload["revision"]
            review = payload["review"]
            output = {
                "decision": "PASSED",
                "score": 88,
                "issues": [],
                "resolved_issue_codes": [
                    str(item["code"]) for item in review.get("issues", [])
                ],
                "target_content_hash": str(revision.get("content_hash", "")),
            }
        else:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError("MODEL_EFFECT_STAGE_UNSUPPORTED", f"unsupported fixture stage: {stage}")
        return ModelProviderResult(
            output=output,
            provider_id=self.provider_id,
            model_id="deterministic-fixture-model-v1",
            prompt_version=f"chapter-{stage}-fixture-v1",
            skill_version="deterministic-fixture-v1",
            input_tokens=0,
            output_tokens=0,
            cost_amount="0",
            currency="USD",
            real_model_call=False,
        )


@dataclass(frozen=True, slots=True)
class _PlanHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        chapter = int(request.command["chapter"])
        source_plan = request.require_input("chapter_plan")
        if (
            request.command.get("chapter_plan_asset_version_id")
            != source_plan.asset_version_id
            or request.command.get("chapter_plan_content_hash") != source_plan.content_hash
        ):
            raise KernelError(
                "CHAPTER_PLAN_FROZEN_IDENTITY_MISMATCH",
                "ChapterPlan command identity does not match the frozen AssetVersion",
            )
        plan, qualification = normalize_authoritative_chapter_plan(
            project_id=request.project_id,
            expected_chapter=chapter,
            content=source_plan.content,
            asset_version_id=source_plan.asset_version_id,
            content_hash=source_plan.content_hash,
        )
        manifest = dict(
            request.command.get("preparation_report", {}).get(
                "production_input_manifest", {}
            )
        )
        if not manifest:
            selected = [
                {
                    "asset_version_id": str(item["asset_version_id"]),
                    "asset_type": str(item.get("asset_type") or "unknown"),
                    "content_hash": str(item["content_hash"]),
                    "role": "context",
                    "entity_id": str(item.get("entity_id") or ""),
                }
                for item in request.command.get("context_candidates", [])
            ]
            payload = {
                "project_id": request.project_id,
                "chapter": chapter,
                "stage": "draft",
                "selected_asset_versions": selected,
                "fixture": True,
            }
            manifest = {
                **payload,
                "workspace_id": request.workspace_id,
                "quality_profile_version_id": next(
                    (
                        item["asset_version_id"] for item in selected
                        if item["asset_type"] in {"quality_profile", "quality_rubric"}
                    ),
                    "",
                ),
                "platform_profile_version_id": next(
                    (
                        item["asset_version_id"] for item in selected
                        if item["asset_type"] == "platform_profile"
                    ),
                    "",
                ),
                "manifest_digest": "sha256:"
                + hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "contract_version": "production-input-manifest-v2",
                "approval_requirements": [],
                "risk_summary": [],
            }
        manifest["created_by_operation_id"] = request.operation_id
        manifest["manifest_digest"] = "sha256:" + hashlib.sha256(
            json.dumps(
                {key: value for key, value in manifest.items() if key != "manifest_digest"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        auxiliary = (
            ChapterAuxiliaryOutput(
                asset_type="production_input_manifest",
                output_key="chapter.production_input_manifest",
                role="production_input_manifest",
                content=manifest,
                reference_asset_version_ids=tuple(
                    str(item["asset_version_id"])
                    for item in manifest.get("selected_asset_versions", [])
                ),
            ),
            ChapterAuxiliaryOutput(
                asset_type="chapter_plan_qualification_report",
                output_key="chapter.plan.qualification",
                role="completion_evidence",
                content={
                    **json.loads(json.dumps(asdict(qualification), sort_keys=True)),
                    "project_id": request.project_id,
                    "chapter": chapter,
                    "source_chapter_plan_asset_version_id": source_plan.asset_version_id,
                },
                reference_asset_version_ids=(source_plan.asset_version_id,),
            ),
        )
        return ChapterHandlerOutput(
            asset_type=ChapterNode.PLAN.asset_type,
            output_key=ChapterNode.PLAN.output_key,
            role="primary",
            content=plan,
            auxiliary_outputs=auxiliary,
        )


@dataclass(frozen=True, slots=True)
class _ContextHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = next((item for item in request.inputs if item.asset_type == "chapter_plan"), None)
        if plan is None:
            from novel_forge.modules.command_kernel.errors import KernelError
            raise KernelError("CHAPTER_HANDLER_INPUT_INVALID", "generated chapter plan is missing")
        manifest_asset = next(
            (item for item in request.inputs if item.asset_type == "production_input_manifest"),
            None,
        )
        manifest = (
            dict(manifest_asset.content)
            if manifest_asset is not None
            else dict(
                request.command.get("preparation_report", {}).get(
                    "production_input_manifest", {}
                )
            )
        )
        candidate_metadata = {
            str(item.get("asset_version_id")): dict(item)
            for item in request.command.get("context_candidates", [])
        }
        governed_candidates = []
        frozen_candidates = [
            item
            for item in request.inputs
            if item is not plan and item.asset_type != "production_input_manifest"
        ]
        if set(candidate_metadata) != {item.asset_version_id for item in frozen_candidates}:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "CONTEXT_FROZEN_INPUT_MISMATCH",
                "governed context candidates must equal frozen AssetVersion inputs",
            )
        for item in frozen_candidates:
            metadata = candidate_metadata[item.asset_version_id]
            physical_asset_type = str(
                metadata.get("physical_asset_type") or metadata.get("asset_type") or ""
            )
            if physical_asset_type != item.asset_type:
                raise KernelError(
                    "CONTEXT_FROZEN_INPUT_TYPE_MISMATCH",
                    "Context candidate physical type differs from frozen AssetVersion",
                )
            governed_candidates.append(
                {
                    **metadata,
                    "asset_type": str(metadata.get("asset_type") or item.asset_type),
                    "physical_asset_type": item.asset_type,
                    "content_digest": item.content_hash,
                    "safe_summary": str(item.content.get("safe_summary") or metadata.get("safe_summary") or ""),
                    "structured_facts": list(item.content.get("structured_facts") or metadata.get("structured_facts") or []),
                }
            )
        bundle = build_context_bundle(
                plan=plan.content,
                plan_asset_version_id=plan.asset_version_id,
                plan_content_hash=plan.content_hash,
                project_id=request.project_id,
                created_by_operation_id=request.operation_id,
                governed_candidates=governed_candidates,
                version_refs=dict(request.command.get("context_version_refs", {})),
            token_budget=int(request.command.get("context_token_budget", 6000)),
        )
        bundle["production_input_manifest"] = manifest
        bundle["production_input_manifest_asset_version_id"] = (
            manifest_asset.asset_version_id if manifest_asset is not None else ""
        )
        manifest_ids = {
            str(item.get("asset_version_id"))
            for item in manifest.get("selected_asset_versions", [])
        }
        frozen_ids = {item.asset_version_id for item in frozen_candidates}
        segment_ids = {
            str(item.get("asset_version_id"))
            for item in bundle.get("context_segments", [])
            if str(item.get("asset_version_id")) != plan.asset_version_id
        }
        consistent = bool(manifest) and manifest_ids == frozen_ids == segment_ids
        if not consistent:
            from novel_forge.modules.command_kernel.errors import KernelError
            raise KernelError(
                "CONTEXT_MANIFEST_CONSISTENCY_FAILED",
                "Manifest, frozen inputs, and Context segments differ: "
                f"manifest_only={sorted(manifest_ids - frozen_ids)}; "
                f"frozen_only={sorted(frozen_ids - manifest_ids)}; "
                f"segment_only={sorted(segment_ids - frozen_ids)}; "
                f"frozen_without_segment={sorted(frozen_ids - segment_ids)}",
            )
        report = {
            "type": "ContextManifestConsistencyReport",
            "project_id": request.project_id,
            "manifest_asset_version_id": (
                manifest_asset.asset_version_id if manifest_asset is not None else ""
            ),
            "manifest_digest": str(manifest.get("manifest_digest") or ""),
            "selected_asset_version_ids": sorted(manifest_ids),
            "frozen_input_asset_version_ids": sorted(frozen_ids),
            "context_segment_asset_version_ids": sorted(segment_ids),
            "consistent": True,
            "contract_version": "context-manifest-consistency-v1",
        }
        return ChapterHandlerOutput(
            asset_type=ChapterNode.CONTEXT.asset_type,
            output_key=ChapterNode.CONTEXT.output_key,
            role="primary",
            content=bundle,
            auxiliary_outputs=(
                ChapterAuxiliaryOutput(
                    asset_type="context_manifest_consistency_report",
                    output_key="chapter.context.manifest_consistency",
                    role="completion_evidence",
                    content=report,
                    reference_asset_version_ids=tuple(sorted(manifest_ids)),
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class _DraftHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = request.require_input("chapter_plan")
        context = request.require_input("context_bundle")
        generated = self.provider.invoke(
            request,
            stage="draft",
            payload={
                "plan": build_draft_plan_view(plan.content),
                "context": build_draft_context_view(context.content),
                "style": build_draft_style_view(context.content),
            },
        )
        return _output(
            ChapterNode.DRAFT,
            normalize_draft_result(
                plan=plan.content,
                context_asset_version_id=context.asset_version_id,
                result=generated.output,
                provider_evidence=_provider_evidence(generated),
            ),
        )


@dataclass(frozen=True, slots=True)
class _ReviewHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        context = request.require_input("context_bundle")
        reviewed = self.provider.invoke(
            request,
            stage="review",
            payload={"draft": draft.content, "context": context.content},
        )
        return _output(
            ChapterNode.REVIEW,
            normalize_review_result(
                draft=draft.content,
                draft_asset_version_id=draft.asset_version_id,
                result=reviewed.output,
                provider_evidence=_provider_evidence(reviewed),
                project_id=request.project_id,
                context_bundle_version_id=context.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _RevisionHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        review = request.require_input("review_report")
        context = request.require_input("context_bundle")
        revised = self.provider.invoke(
            request,
            stage="revision",
            payload={"draft": draft.content, "review": review.content, "context": context.content},
        )
        return _output(
            ChapterNode.REVISION,
            normalize_revision_result(
                draft=draft.content,
                review=review.content,
                draft_asset_version_id=draft.asset_version_id,
                review_asset_version_id=review.asset_version_id,
                result=revised.output,
                provider_evidence=_provider_evidence(revised),
                project_id=request.project_id,
                context_bundle_version_id=context.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _ReReviewHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        review = request.require_input("review_report")
        revision = request.require_input("draft_version")
        context = request.require_input("context_bundle")
        reviewed = self.provider.invoke(
            request,
            stage=(
                "review"
                if getattr(self.provider, "external_effect_backed", False)
                else "rereview"
            ),
            payload={
                "draft": revision.content,
                "original_draft": draft.content,
                "review": review.content,
                "revision": revision.content,
                "context": context.content,
            },
        )
        return _output(
            ChapterNode.REREVIEW,
            normalize_rereview_result(
                draft_asset_version_id=draft.asset_version_id,
                review=review.content,
                review_asset_version_id=review.asset_version_id,
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                context_bundle_version_id=context.asset_version_id,
                result=reviewed.output,
                provider_evidence=_provider_evidence(reviewed),
                project_id=request.project_id,
            ),
        )
@dataclass(frozen=True, slots=True)
class _CanonHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        extraction = request.require_input("canon_extraction")
        proposal = request.require_input("canon_change_proposal")
        decisions = [
            {**item.content, "asset_version_id": item.asset_version_id}
            for item in request.inputs
            if item.asset_type == "canon_approval_decision"
        ]
        resolved_extraction = resolve_canon_extraction(
            extraction=extraction.content,
            proposal={**proposal.content, "asset_version_id": proposal.asset_version_id},
            decisions=decisions,
        )
        context = request.require_input("context_bundle")
        content = build_canon_patch(
            revision=revision.content,
            revision_asset_version_id=revision.asset_version_id,
            project_id=request.project_id,
            context_bundle_version_id=context.asset_version_id,
            extraction=resolved_extraction,
            context_bundle=context.content,
        )
        snapshot_outputs = tuple(
            ChapterAuxiliaryOutput(
                asset_type=str(snapshot["asset_type"]),
                output_key=f"chapter.canon.snapshot.{snapshot['state_kind']}",
                role="state_snapshot",
                content=dict(snapshot),
                reference_asset_version_ids=tuple(
                    sorted(
                        {
                            revision.asset_version_id,
                            extraction.asset_version_id,
                            proposal.asset_version_id,
                            *(item.asset_version_id for item in request.inputs if item.asset_type == "canon_approval_decision"),
                            context.asset_version_id,
                            *snapshot.get("previous_asset_version_ids", []),
                        }
                    )
                ),
                evidence={
                    "authority_family": "chapter",
                    "state_kind": snapshot["state_kind"],
                    "append_only": True,
                },
            )
            for snapshot in content["snapshot_candidates"]
        )
        primary = _output(
            ChapterNode.CANON,
            content,
        )
        return ChapterHandlerOutput(
            asset_type=primary.asset_type,
            output_key=primary.output_key,
            role=primary.role,
            content=primary.content,
            qualification_policy=primary.qualification_policy,
            auxiliary_outputs=snapshot_outputs,
        )


@dataclass(frozen=True, slots=True)
class _CanonExtractionHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        context = request.require_input("context_bundle")
        provider_extraction = None
        if bool(getattr(self.provider, "external_effect_backed", False)) or bool(
            getattr(self.provider, "supports_semantic_extraction", False)
        ):
            generated = self.provider.invoke(
                request,
                stage="canon_extraction",
                payload={"revision": revision.content, "context": context.content},
            )
            provider_extraction = _canon_provider_extraction(generated)
        return _output(
            ChapterNode.CANON_EXTRACTION,
            build_canon_extraction(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                project_id=request.project_id,
                context_bundle_version_id=context.asset_version_id,
                provider_extraction=provider_extraction,
            ),
        )


@dataclass(frozen=True, slots=True)
class _CanonProposalHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        extraction = request.require_input("canon_extraction")
        proposal = build_canon_change_proposal(
            project_id=request.project_id,
            extraction=extraction.content,
            extraction_asset_version_id=extraction.asset_version_id,
        )
        generation = int(request.command.get("canon_reextraction_generation") or 1)
        proposal["generation"] = generation
        proposal["supersedes_asset_version_id"] = str(
            request.command.get("supersedes_proposal_asset_version_id") or ""
        )
        return _output(
            ChapterNode.CANON_PROPOSAL,
            proposal,
        )


@dataclass(frozen=True, slots=True)
class _QualityGroupHandler:
    group: str
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        plan = request.require_input("chapter_plan")
        canon = request.require_input("canon_patch")
        context = request.require_input("context_bundle")
        fixture = not any(
            bool(item.content.get("provider_evidence", {}).get("real_model_call"))
            for item in request.inputs
        )
        context_content = dict(context.content)
        quality_context = build_quality_context_view(
            group=self.group,
            revision=revision.content,
            revision_asset_version_id=revision.asset_version_id,
            chapter_plan=plan.content,
            chapter_plan_asset_version_id=plan.asset_version_id,
            context_bundle=context.content,
            context_bundle_asset_version_id=context.asset_version_id,
            canon=canon.content,
            canon_asset_version_id=canon.asset_version_id,
            token_budget=int(request.command.get("context_token_budget") or 6000),
        )
        if bool(getattr(self.provider, "external_effect_backed", False)):
            generated = self.provider.invoke(
                request,
                stage=f"quality_{self.group}",
                payload={
                    "revision": revision.content,
                    "quality_context": quality_context,
                    "dimensions": list(QUALITY_GROUPS[self.group]),
                },
            )
            provider_entries = []
            for item in generated.output.get("dimensions", []):
                provider_entries.append({
                    **dict(item),
                    "target_asset_version_id": revision.asset_version_id,
                    "calibration_status": "PROVIDER_UNCALIBRATED",
                    "provider_verified": True,
                })
            context_content["context_segments"] = [
                *list(context.content.get("context_segments", [])),
                {
                    "asset_version_id": f"external-effect:{request.operation_id}",
                    "narrative_function": "quality_evidence",
                    "source_expression_included": False,
                    "structured_facts": [{"key": "dimension_evidence", "value": provider_entries}],
                },
            ]
            fixture = False
        content = build_quality_group_evidence(
            group=self.group,
            project_id=request.project_id,
            revision=revision.content,
            revision_asset_version_id=revision.asset_version_id,
            context_bundle=context_content,
            canon=canon.content,
            fixture=fixture,
        )
        content["quality_context_type"] = quality_context["type"]
        content["quality_context_digest"] = quality_context["context_digest"]
        node = {
            "structural": ChapterNode.QUALITY_STRUCTURAL,
            "commercial": ChapterNode.QUALITY_COMMERCIAL,
            "source_originality": ChapterNode.QUALITY_SOURCE_ORIGINALITY,
            "longform": ChapterNode.QUALITY_LONGFORM,
            "platform": ChapterNode.QUALITY_PLATFORM,
        }[self.group]
        return _output(node, content)


@dataclass(frozen=True, slots=True)
class _QualityHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        review = request.require_input("re_review_report")
        canon = request.require_input("canon_patch")
        context = request.require_input("context_bundle")
        groups = [
            item for item in request.inputs
            if item.asset_type == "chapter_quality_group_report"
        ]
        if {str(item.content.get("group")) for item in groups} != {
            "structural", "commercial", "source_originality", "longform", "platform"
        }:
            from novel_forge.modules.command_kernel.errors import KernelError
            raise KernelError("QUALITY_FANIN_INCOMPLETE", "all five quality groups are required")
        group_reports = [
            dimension
            for group in groups
            for dimension in group.content.get("dimensions", [])
        ]
        content = build_quality_report(
            revision=revision.content,
            revision_asset_version_id=revision.asset_version_id,
            canon=canon.content,
            canon_asset_version_id=canon.asset_version_id,
            review=review.content,
            review_asset_version_id=review.asset_version_id,
            project_id=request.project_id,
            context_bundle_version_id=context.asset_version_id,
            context_bundle=context.content,
            evidence_reports=group_reports,
        )
        primary = _output(
            ChapterNode.QUALITY,
            content,
        )
        evidence_outputs = tuple(
            ChapterAuxiliaryOutput(
                asset_type="chapter_quality_evidence",
                output_key=f"chapter.quality.evidence.{report['dimension']}",
                role="quality_evidence",
                content=dict(report),
                reference_asset_version_ids=(
                    revision.asset_version_id,
                    review.asset_version_id,
                    canon.asset_version_id,
                    context.asset_version_id,
                ),
                evidence={
                    "dimension": report["dimension"],
                    "calibration_status": report["calibration_status"],
                    "production_verified": False,
                },
            )
            for report in content["evidence_reports"]
        )
        return ChapterHandlerOutput(
            asset_type=primary.asset_type,
            output_key=primary.output_key,
            role=primary.role,
            content=primary.content,
            qualification_policy=primary.qualification_policy,
            auxiliary_outputs=evidence_outputs,
        )


@dataclass(frozen=True, slots=True)
class _PublishGateHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        review = request.require_input("re_review_report")
        canon = request.require_input("canon_patch")
        quality = request.require_input("quality_score_report")
        context = request.require_input("context_bundle")
        return _output(
            ChapterNode.PUBLISH_GATE,
            build_publish_gate(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                quality=quality.content,
                quality_asset_version_id=quality.asset_version_id,
                review=review.content,
                review_asset_version_id=review.asset_version_id,
                canon=canon.content,
                canon_asset_version_id=canon.asset_version_id,
                context_bundle=context.content,
                context_bundle_version_id=context.asset_version_id,
                project_id=request.project_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _ExportHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        publish_gate = request.require_input("publish_gate_report")
        return _output(
            ChapterNode.EXPORT,
            build_export_package(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                quality=publish_gate.content,
                quality_asset_version_id=publish_gate.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _FinalReleaseGateHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        export = request.require_input("release_package")
        publish_gate = request.require_input("publish_gate_report")
        quality = request.require_input("quality_score_report")
        review = request.require_input("re_review_report")
        canon = request.require_input("canon_patch")
        context = request.require_input("context_bundle")
        return _output(
            ChapterNode.FINAL_RELEASE_GATE,
            build_final_release_gate(
                project_id=request.project_id,
                export_package=export.content,
                export_asset_version_id=export.asset_version_id,
                export_blobs=export.blobs,
                publish_gate=publish_gate.content,
                publish_gate_asset_version_id=publish_gate.asset_version_id,
                quality=quality.content,
                quality_asset_version_id=quality.asset_version_id,
                review=review.content,
                review_asset_version_id=review.asset_version_id,
                canon=canon.content,
                canon_asset_version_id=canon.asset_version_id,
                context_bundle_version_id=context.asset_version_id,
            ),
        )


def build_chapter_handler_registry(
    provider: ChapterModelPort,
) -> ChapterHandlerRegistry:
    registry = ChapterHandlerRegistry(
        model_effects_required=bool(getattr(provider, "external_effect_backed", False))
    )
    registry.register(ChapterNode.PLAN, _PlanHandler())
    registry.register(ChapterNode.CONTEXT, _ContextHandler())
    registry.register(ChapterNode.DRAFT, _DraftHandler(provider))
    registry.register(ChapterNode.REVIEW, _ReviewHandler(provider))
    registry.register(ChapterNode.REVISION, _RevisionHandler(provider))
    registry.register(ChapterNode.REREVIEW, _ReReviewHandler(provider))
    registry.register(ChapterNode.CANON_EXTRACTION, _CanonExtractionHandler(provider))
    registry.register(ChapterNode.CANON_PROPOSAL, _CanonProposalHandler())
    registry.register(ChapterNode.CANON, _CanonHandler())
    registry.register(ChapterNode.QUALITY_STRUCTURAL, _QualityGroupHandler("structural", provider))
    registry.register(ChapterNode.QUALITY_COMMERCIAL, _QualityGroupHandler("commercial", provider))
    registry.register(ChapterNode.QUALITY_SOURCE_ORIGINALITY, _QualityGroupHandler("source_originality", provider))
    registry.register(ChapterNode.QUALITY_LONGFORM, _QualityGroupHandler("longform", provider))
    registry.register(ChapterNode.QUALITY_PLATFORM, _QualityGroupHandler("platform", provider))
    registry.register(ChapterNode.QUALITY, _QualityHandler())
    registry.register(ChapterNode.PUBLISH_GATE, _PublishGateHandler())
    registry.register(ChapterNode.EXPORT, _ExportHandler())
    registry.register(ChapterNode.FINAL_RELEASE_GATE, _FinalReleaseGateHandler())
    return registry


def _output(node: ChapterNode, content: dict[str, Any]) -> ChapterHandlerOutput:
    return ChapterHandlerOutput(
        asset_type=node.asset_type,
        output_key=node.output_key,
        role="primary",
        content=content,
    )


def _provider_evidence(result: ModelProviderResult) -> dict[str, Any]:
    evidence = result.to_evidence()
    evidence.pop("result", None)
    return evidence


def _canon_provider_extraction(result: ModelProviderResult) -> dict[str, Any]:
    identity = {
        "provider_id": result.provider_id,
        "model_id": result.model_id,
        "prompt_version": result.prompt_version,
    }
    return {
        field: [{**dict(item), **identity} for item in values]
        for field, values in result.output.items()
        if isinstance(values, list)
    }
