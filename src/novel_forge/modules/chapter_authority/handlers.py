"""Storage-free chapter handlers for PostgreSQL authority execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.production_retrieval import (
    build_retrieval_result,
    freeze_retrieval_candidate_union,
    load_frozen_retrieval_candidate_union,
)

from novel_forge.modules.chapter_authority.contracts import (
    ChapterAuxiliaryOutput,
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterHandlerRequest,
    ChapterInputAsset,
    ChapterNode,
    resolve_stage_context_token_budget,
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
    ChapterPlanQualificationProfile,
    build_draft_plan_view,
    build_draft_style_view,
    normalize_authoritative_chapter_plan,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ChapterModelPort,
    ModelProviderResult,
)
from novel_forge.modules.chapter_authority.execution_artifacts import (
    build_chapter_execution_intent,
    qualify_chapter_memo,
)
from novel_forge.modules.chapter_authority.candidate_selection import (
    CandidateEvidence,
    build_best_candidate,
    compare_candidates,
)
from novel_forge.modules.chapter_quality_authority import (
    QUALITY_GROUPS,
    build_multiscale_quality_report,
    build_quality_group_evidence,
    build_quality_context_view,
)
from novel_forge.modules.canon_graph.approval_domain import (
    build_canon_change_proposal,
    resolve_canon_extraction,
)
from novel_forge.modules.content_intelligence import (
    build_hook_analysis,
    build_pacing_observation,
)
from novel_forge.modules.narrative_state import measure_narrative_runtime
from novel_forge.modules.production_execution import CommitManifest
from novel_forge.modules.revision.domain import apply_quality_revision_result
from novel_forge.modules.production_preparation.policies import (
    CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
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
                "resolved_issue_codes": [
                    str(item["code"]) for item in review["issues"]
                ],
                "canon_assertions": [
                    {
                        "subject": "protagonist",
                        "predicate": "gave_up",
                        "object": "safe_route_home",
                        "effective_from_chapter": draft["chapter"],
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

            raise KernelError(
                "MODEL_EFFECT_STAGE_UNSUPPORTED", f"unsupported fixture stage: {stage}"
            )
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
            or request.command.get("chapter_plan_content_hash")
            != source_plan.content_hash
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
            qualification_profile=(
                ChapterPlanQualificationProfile(
                    **request.command.get("preparation_report", {}).get(
                        "chapter_plan_qualification_profile", {}
                    )
                )
                if request.command.get("preparation_report", {}).get(
                    "chapter_plan_qualification_profile"
                )
                else None
            ),
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
                "manifest_source": "FROZEN_COMMAND_CANDIDATES",
                "fixture_protocol_only": False,
            }
            manifest = {
                **payload,
                "workspace_id": request.workspace_id,
                "quality_profile_version_id": next(
                    (
                        item["asset_version_id"]
                        for item in selected
                        if item["asset_type"] in {"quality_profile", "quality_rubric"}
                    ),
                    "",
                ),
                "platform_profile_version_id": next(
                    (
                        item["asset_version_id"]
                        for item in selected
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
        manifest["manifest_digest"] = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_digest"
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
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
class _ExecutionIntentHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = request.require_input("chapter_plan")
        accepted_inputs = [
            {
                **item.content,
                "asset_type": item.asset_type,
                "asset_version_id": item.asset_version_id,
            }
            for item in request.inputs
            if item.asset_type in {"story_state_snapshot", "canon_snapshot"}
        ]
        return _output(
            ChapterNode.EXECUTION_INTENT,
            build_chapter_execution_intent(
                project_id=request.project_id,
                operation_id=request.operation_id,
                chapter_plan_asset_version_id=plan.asset_version_id,
                chapter_plan_content_hash=plan.content_hash,
                chapter_plan=plan.content,
                accepted_inputs=accepted_inputs,
            ),
        )


@dataclass(frozen=True, slots=True)
class _MemoHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        intent = request.require_input("chapter_execution_intent")
        mission = dict(intent.content.get("chapter_mission") or {})
        result = {
            "execution_strategy": "materialize the locked objective through irreversible choice",
            "tension_strategy": "carry accepted tension into escalating scene consequences",
            "composition_strategy": (
                "realize each locked causal event once while combining its Arc, state, "
                "information, relationship, and reader functions"
            ),
            "scene_directives": [
                {
                    "scene_id": str(item["scene_id"]),
                    "directive": str(
                        item.get("goal") or "advance the chapter objective"
                    ),
                }
                for item in intent.content.get("scene_plans") or ()
            ],
            "retrieval_queries": [
                "previous accepted ending",
                "active narrative obligations",
                "relevant accepted arc history",
            ],
            "obligation_actions": [
                {
                    "obligation_id": str(
                        (item.get("state") or {}).get("obligation_id")
                        or item.get("entity_key")
                        or ""
                    ),
                    "action": "DEVELOP",
                }
                for item in intent.content.get("active_obligations") or ()
                if isinstance(item, dict)
                and str(
                    (item.get("state") or {}).get("obligation_id")
                    or item.get("entity_key")
                    or ""
                )
            ],
            "arc_actions": [
                {
                    "arc_plan_version_id": str(
                        item.get("arc_plan_version_id") or item.get("arc_id") or ""
                    ),
                    "action": str(
                        item.get("action")
                        or item.get("contribution")
                        or item.get("kind")
                        or "ADVANCE"
                    ),
                }
                for item in mission.get("arc_contributions") or ()
                if isinstance(item, dict)
            ],
            "stop_conditions": [
                "do not contradict the locked ChapterPlan or Chapter Mission",
                "do not split one composed event into disconnected exposition-only scenes",
            ],
        }
        return _output(
            ChapterNode.MEMO,
            qualify_chapter_memo(
                intent=intent.content,
                intent_asset_version_id=intent.asset_version_id,
                result=result,
                execution_evidence={
                    "runtime": "deterministic-domain-service",
                    "operation_id": request.operation_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True)
class _RetrievalHandler:
    provider: ChapterModelPort
    semantic_provider_bound: bool = False

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = request.require_input("chapter_plan")
        intent = request.require_input("chapter_execution_intent")
        memo = request.require_input("chapter_memo")
        snapshot = dict(request.command.get("retrieval_snapshot") or {})
        query_plan = dict(snapshot.get("query_plan") or {})
        documents = [dict(item) for item in snapshot.get("documents") or ()]
        if str(query_plan.get("intent_fingerprint") or "") != str(
            intent.content.get("intent_fingerprint") or ""
        ) or str(query_plan.get("memo_fingerprint") or "") != str(
            memo.content.get("memo_fingerprint") or ""
        ):
            raise KernelError(
                "RETRIEVAL_FROZEN_QUERY_IDENTITY_MISMATCH",
                "retrieval query plan does not match frozen Intent and Memo",
            )
        expected_sources = {
            (
                str(item.get("source_asset_version_id") or ""),
                str(item.get("source_content_hash") or ""),
            )
            for item in documents
        }
        control_ids = {
            plan.asset_version_id,
            intent.asset_version_id,
            memo.asset_version_id,
        }
        frozen_sources = {
            (item.asset_version_id, item.content_hash)
            for item in request.inputs
            if item.asset_version_id not in control_ids
        }
        if expected_sources != frozen_sources:
            raise KernelError(
                "RETRIEVAL_FROZEN_CANDIDATE_MISMATCH",
                "retrieval document sources differ from frozen Operation inputs",
            )
        semantic_status = dict(snapshot.get("semantic_status") or {})
        frozen_union = load_frozen_retrieval_candidate_union(
            request.database_url,
            project_id=request.project_id,
            operation_id=request.operation_id,
            query_plan_fingerprint=str(query_plan.get("query_plan_fingerprint") or ""),
        )
        if frozen_union is None:
            query_embedding: tuple[float, ...] = ()
            query_embedding_model = ""
            query_embedding_dimensions = 0
            query_embedding_evidence: dict[str, Any] = {}
            semantic_enabled = query_plan.get("semantic_policy") != "DISABLED"
            if (
                semantic_enabled
                and int(semantic_status.get("ready_document_count") or 0) > 0
                and self.semantic_provider_bound
            ):
                provider_result = self.provider.invoke(
                    request,
                    stage="retrieval",
                    payload={
                        "texts": [str(query_plan.get("postgresql_fts_query") or "")],
                        "purpose": "accepted_history_query_embedding",
                        "query_plan_fingerprint": str(
                            query_plan.get("query_plan_fingerprint") or ""
                        ),
                        "candidate_projection_cutoff": str(
                            query_plan.get("candidate_projection_cutoff") or ""
                        ),
                    },
                )
                vectors = provider_result.output.get("vectors")
                if not isinstance(vectors, list) or len(vectors) != 1:
                    raise KernelError(
                        "RETRIEVAL_QUERY_EMBEDDING_INVALID",
                        "query embedding Provider returned the wrong batch cardinality",
                    )
                query_embedding = tuple(float(item) for item in vectors[0])
                query_embedding_dimensions = int(
                    provider_result.output.get("embedding_dimensions") or 0
                )
                query_embedding_model = str(
                    provider_result.output.get("embedding_model") or ""
                )
                if (
                    not query_embedding_model
                    or query_embedding_dimensions <= 0
                    or len(query_embedding) != query_embedding_dimensions
                ):
                    raise KernelError(
                        "RETRIEVAL_QUERY_EMBEDDING_INVALID",
                        "query embedding Provider returned incompatible identity",
                    )
                query_embedding_evidence = provider_result.to_evidence()
            elif query_plan.get("semantic_policy") == "REQUIRED":
                raise KernelError(
                    "RETRIEVAL_QUERY_EMBEDDING_REQUIRED",
                    "semantic-required retrieval lacks a compatible governed projection/provider",
                )
            semantic_status["provider_wired"] = self.semantic_provider_bound
            frozen_union = freeze_retrieval_candidate_union(
                request.database_url,
                project_id=request.project_id,
                book_id=str(
                    plan.content.get("book_id") or f"book:{request.project_id}"
                ),
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
                worker_id=request.worker_id,
                query_plan=query_plan,
                base_documents=documents,
                semantic_status=semantic_status,
                query_embedding=query_embedding,
                query_embedding_model=query_embedding_model,
                query_embedding_dimensions=query_embedding_dimensions,
                query_embedding_evidence=query_embedding_evidence,
            )
        return _output(
            ChapterNode.RETRIEVAL,
            build_retrieval_result(
                project_id=request.project_id,
                book_id=str(
                    plan.content.get("book_id") or f"book:{request.project_id}"
                ),
                intent_asset_version_id=intent.asset_version_id,
                memo_asset_version_id=memo.asset_version_id,
                query_plan=query_plan,
                documents=frozen_union.documents,
                discovery_rejections=tuple(
                    dict(item) for item in snapshot.get("rejected_documents") or ()
                ),
                semantic_status=frozen_union.semantic_status,
                query_embedding=frozen_union.query_embedding,
                query_embedding_evidence=frozen_union.query_embedding_evidence,
                candidate_snapshot_id=frozen_union.candidate_snapshot_id,
                candidate_snapshot_hash=frozen_union.snapshot_hash,
            ),
        )


@dataclass(frozen=True, slots=True)
class _ContextHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = next(
            (item for item in request.inputs if item.asset_type == "chapter_plan"), None
        )
        if plan is None:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "CHAPTER_HANDLER_INPUT_INVALID", "generated chapter plan is missing"
            )
        manifest_asset = next(
            (
                item
                for item in request.inputs
                if item.asset_type == "production_input_manifest"
            ),
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
            if str(item.get("asset_type") or "") != "chapter_plan"
        }
        governed_candidates = []
        frozen_arc_plans: dict[str, dict[str, Any]] = {}
        intent = request.require_input("chapter_execution_intent")
        memo = request.require_input("chapter_memo")
        retrieval = request.require_input("retrieval_result")
        if (
            retrieval.content.get("intent_asset_version_id") != intent.asset_version_id
            or retrieval.content.get("memo_asset_version_id") != memo.asset_version_id
            or dict(retrieval.content.get("accepted_boundary") or {})
            != dict(intent.content.get("accepted_boundary") or {})
        ):
            raise KernelError(
                "CONTEXT_RETRIEVAL_IDENTITY_MISMATCH",
                "Context requires RetrievalResult for its exact Intent, Memo, and boundary",
            )
        selected_documents: dict[str, list[dict[str, Any]]] = {}
        for document in retrieval.content.get("selected_documents") or ():
            if isinstance(document, dict):
                selected_documents.setdefault(
                    str(document.get("source_asset_version_id") or ""), []
                ).append(dict(document))
        for source_id, documents in selected_documents.items():
            if source_id in candidate_metadata:
                continue
            best = max(
                documents,
                key=lambda item: float(item.get("retrieval_score") or 0.0),
            )
            compression_method = str(best.get("compression_method") or "none")
            compression_provenance = dict(best.get("compression_provenance") or {})
            candidate_metadata[source_id] = {
                "asset_version_id": source_id,
                "asset_type": "narrative_retrieval_document",
                "physical_asset_type": str(best.get("source_artifact_type") or ""),
                "content_hash": str(best.get("source_content_hash") or ""),
                "project_id": request.project_id,
                "estimated_tokens": max(
                    1, int(best.get("output_characters") or 0) // 4
                ),
                "safe_summary": str(best.get("safe_summary") or ""),
                "structured_facts": [],
                "narrative_function": str(
                    dict(best.get("metadata") or {}).get("projection_kind")
                    or "accepted_historical_evidence"
                ),
                "source_use_mode": "generation",
                "allowed_use": "generation",
                "context_class": (
                    "COMPRESSIBLE"
                    if compression_method not in {"", "none", "full", "full_asset"}
                    else "RETRIEVABLE"
                ),
                "memory_layer": str(best.get("memory_layer") or ""),
                "relevance_score": max(
                    float(item.get("retrieval_score") or 0.0) for item in documents
                ),
                "retrieval_reasons": sorted(
                    {
                        str(reason)
                        for item in documents
                        for reason in item.get("retrieval_reasons") or ()
                    }
                ),
                "retrieval_scores": dict(best.get("retrieval_scores") or {}),
                "provenance": {
                    "retrieval_result_asset_version_id": retrieval.asset_version_id,
                    "retrieval_document_ids": sorted(
                        str(item.get("retrieval_document_id") or "")
                        for item in documents
                    ),
                    "accepted_boundary": dict(
                        retrieval.content.get("accepted_boundary") or {}
                    ),
                    "source_projection_hashes": sorted(
                        str(item.get("projection_hash") or "") for item in documents
                    ),
                },
                "compression_method": compression_method,
                "compression_trace": (
                    [compression_provenance]
                    if compression_method not in {"", "none", "full", "full_asset"}
                    else []
                ),
            }
        frozen_candidates = [
            item
            for item in request.inputs
            if item is not plan
            and item.asset_type
            not in {
                "production_input_manifest",
                "chapter_execution_intent",
                "chapter_memo",
                "retrieval_result",
            }
        ]
        if set(candidate_metadata) != {
            item.asset_version_id for item in frozen_candidates
        }:
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
                    "safe_summary": str(
                        item.content.get("safe_summary")
                        or metadata.get("safe_summary")
                        or ""
                    ),
                    "structured_facts": list(
                        item.content.get("structured_facts")
                        or metadata.get("structured_facts")
                        or []
                    ),
                }
            )
            if str(metadata.get("asset_type") or "") == "arc_plan":
                frozen_arc_plans[item.asset_version_id] = dict(item.content)
        available_candidate_types = {
            str(item["asset_type"]) for item in governed_candidates
        }
        required_candidate_types = {
            "quality_rubric",
            "platform_profile",
        }
        # These inputs are not prose-generation context, but once Preparation
        # freezes them the downstream Quality/Publish nodes must consume the
        # exact evidence.  Protect them from draft-oriented token eviction;
        # Context rendering still keeps every one evidence-only.
        quality_evidence_types = {
            "operator_checklist",
            "operator_approval",
            "approval_decision",
            "structural_quality_report",
            "commercial_quality_report",
            "source_originality_quality_report",
            "longform_quality_report",
            "platform_quality_report",
        }
        required_candidate_types.update(
            quality_evidence_types & available_candidate_types
        )
        if int(plan.content["chapter"]) > 1:
            required_candidate_types.update(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES)
        bundle = build_context_bundle(
            plan=plan.content,
            plan_asset_version_id=plan.asset_version_id,
            plan_content_hash=plan.content_hash,
            project_id=request.project_id,
            created_by_operation_id=request.operation_id,
            governed_candidates=governed_candidates,
            version_refs=dict(request.command.get("context_version_refs", {})),
            required_asset_types=(
                "chapter_plan",
                "chapter_execution_intent",
                "chapter_memo",
                "retrieval_result",
                *sorted(required_candidate_types & available_candidate_types),
            ),
            token_budget=int(request.command.get("context_token_budget", 6000)),
            book_id=str(
                request.command.get("book_id")
                or plan.content.get("book_id")
                or f"book:{request.project_id}"
            ),
            target_capability_id="prose.chapter.draft",
            capability_pack_snapshot_ref=str(
                request.command.get("capability_pack_snapshot_ref") or ""
            ),
            execution_intent=intent.content,
            execution_intent_asset_version_id=intent.asset_version_id,
            chapter_memo=memo.content,
            chapter_memo_asset_version_id=memo.asset_version_id,
            retrieval_result=retrieval.content,
            retrieval_result_asset_version_id=retrieval.asset_version_id,
            frozen_arc_plans=frozen_arc_plans,
        )
        bundle["production_input_manifest"] = manifest
        bundle["production_input_manifest_asset_version_id"] = (
            manifest_asset.asset_version_id if manifest_asset is not None else ""
        )
        bundle["chapter_execution"] = {
            "intent_asset_version_id": intent.asset_version_id,
            "intent_fingerprint": str(intent.content.get("intent_fingerprint") or ""),
            "memo_asset_version_id": memo.asset_version_id,
            "memo_fingerprint": str(memo.content.get("memo_fingerprint") or ""),
            "retrieval_result_asset_version_id": retrieval.asset_version_id,
            "retrieval_result_fingerprint": str(
                retrieval.content.get("result_fingerprint") or ""
            ),
            "source_chapter_plan_asset_version_id": plan.asset_version_id,
            "accepted_boundary": dict(intent.content.get("accepted_boundary") or {}),
        }
        source_plan_asset_version_id = str(
            plan.content.get("source_chapter_plan_asset_version_id") or ""
        )
        manifest_ids = {
            str(item.get("asset_version_id"))
            for item in manifest.get("selected_asset_versions", [])
            if str(item.get("asset_version_id") or "") != source_plan_asset_version_id
        }
        execution_ids = {
            intent.asset_version_id,
            memo.asset_version_id,
            retrieval.asset_version_id,
        }
        context_manifest_ids = {
            str(item) for item in bundle.get("selected_asset_version_ids", [])
        }
        frozen_ids = {item.asset_version_id for item in frozen_candidates}
        segment_ids = {
            str(item.get("asset_version_id"))
            for item in bundle.get("context_segments", [])
            if str(item.get("asset_version_id")) != plan.asset_version_id
        }
        context_selected_ids = {
            str(item)
            for item in bundle.get("selected_asset_version_ids", [])
            if str(item) != plan.asset_version_id
        }
        context_rejected_ids = {
            str(item.get("asset_version_id") or "")
            for item in bundle.get("rejected_asset_versions", [])
            if str(item.get("asset_version_id") or "") != plan.asset_version_id
        }
        context_external_selected_ids = context_selected_ids - execution_ids
        dynamic_candidate_ids = set(selected_documents) - {
            str(item.get("asset_version_id") or "")
            for item in request.command.get("context_candidates", [])
        }
        static_candidate_ids = frozen_ids - dynamic_candidate_ids
        consistent = (
            bool(manifest)
            and manifest_ids == static_candidate_ids
            and context_selected_ids == segment_ids
            and execution_ids.issubset(context_manifest_ids)
            and not context_external_selected_ids.intersection(context_rejected_ids)
            and context_external_selected_ids.union(context_rejected_ids) == frozen_ids
        )
        if not consistent:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "CONTEXT_MANIFEST_CONSISTENCY_FAILED",
                "Manifest, frozen inputs, and Context selection partition differ: "
                f"manifest_only={sorted(manifest_ids - static_candidate_ids)}; "
                f"static_only={sorted(static_candidate_ids - manifest_ids)}; "
                f"selected_only={sorted(context_selected_ids - frozen_ids)}; "
                f"segment_only={sorted(segment_ids - context_selected_ids)}; "
                f"unaccounted={sorted(frozen_ids - context_selected_ids - context_rejected_ids)}",
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
            "execution_artifact_version_ids": sorted(execution_ids),
            "context_rejected_asset_version_ids": sorted(context_rejected_ids),
            "consistent": True,
            "contract_version": "context-manifest-consistency-v2",
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
        intent = request.require_input("chapter_execution_intent")
        memo = request.require_input("chapter_memo")
        context = request.require_input("context_bundle")
        generated = self.provider.invoke(
            request,
            stage="draft",
            payload={
                "plan": build_draft_plan_view(plan.content),
                "style": build_draft_style_view(context.content),
                "execution_intent": intent.content,
                "chapter_memo": memo.content,
            },
        )
        return _model_output(
            ChapterNode.DRAFT,
            normalize_draft_result(
                plan=plan.content,
                context_asset_version_id=context.asset_version_id,
                context_content_hash=context.content_hash,
                context_content=context.content,
                result=generated.output,
                provider_evidence=_provider_evidence(generated),
            ),
            request=request,
            generated=generated,
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
            payload={"draft": draft.content},
        )
        return _model_output(
            ChapterNode.REVIEW,
            normalize_review_result(
                draft=draft.content,
                draft_asset_version_id=draft.asset_version_id,
                result=reviewed.output,
                provider_evidence=_provider_evidence(reviewed),
                project_id=request.project_id,
                context_bundle_version_id=context.asset_version_id,
            ),
            request=request,
            generated=reviewed,
        )


@dataclass(frozen=True, slots=True)
class _RevisionHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        quality_tasks = tuple(
            item for item in request.inputs if item.asset_type == "revision_task"
        )
        if quality_tasks:
            revision = request.require_input("best_draft_candidate")
            quality = request.require_input("quality_score_report")
            context = request.require_input("context_bundle")
            revised = self.provider.invoke(
                request,
                stage="revision",
                payload={
                    "draft": revision.content,
                    "quality": quality.content,
                    "required_actions": [item.content for item in quality_tasks],
                },
            )
            return _model_output(
                ChapterNode.REVISION,
                apply_quality_revision_result(
                    project_id=request.project_id,
                    revision=revision.content,
                    revision_asset_version_id=revision.asset_version_id,
                    quality=quality.content,
                    quality_asset_version_id=quality.asset_version_id,
                    revision_tasks=tuple(item.content for item in quality_tasks),
                    revision_task_asset_version_ids=tuple(
                        item.asset_version_id for item in quality_tasks
                    ),
                    context_bundle_version_id=context.asset_version_id,
                    result=revised.output,
                    provider_evidence=_provider_evidence(revised),
                ),
                request=request,
                generated=revised,
            )
        draft = request.require_input("draft_chapter")
        review = request.require_input("review_report")
        context = request.require_input("context_bundle")
        revised = self.provider.invoke(
            request,
            stage="revision",
            payload={
                "draft": draft.content,
                "review": review.content,
            },
        )
        return _model_output(
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
            request=request,
            generated=revised,
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
            stage="rereview",
            payload={
                "draft": revision.content,
                "original_draft": draft.content,
                "review": review.content,
                "revision": revision.content,
            },
        )
        return _model_output(
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
            request=request,
            generated=reviewed,
        )


@dataclass(frozen=True, slots=True)
class _BestCandidateHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        rereview = request.require_input("re_review_report")
        existing_best = next(
            (
                item
                for item in request.inputs
                if item.asset_type == "best_draft_candidate"
            ),
            None,
        )
        if existing_best is None:
            previous_asset = request.require_input("draft_chapter")
            previous_review = request.require_input("review_report")
            previous_score = float(previous_review.content.get("score") or 0)
            previous_blockers = _blocking_issue_codes(previous_review.content)
            previous_review_id = previous_review.asset_version_id
        else:
            previous_asset = existing_best
            selection = dict(existing_best.content.get("candidate_comparison") or {})
            selected_id = str(
                existing_best.content.get("selected_source_asset_version_id") or ""
            )
            selected_evidence = next(
                (
                    dict(selection.get(key) or {})
                    for key in ("previous", "challenger")
                    if str((selection.get(key) or {}).get("asset_version_id") or "")
                    == selected_id
                ),
                {},
            )
            previous_score = float(selected_evidence.get("score") or 0)
            previous_blockers = tuple(selected_evidence.get("blocker_codes") or ())
            previous_review_id = str(
                selected_evidence.get("review_asset_version_id") or ""
            )
        prior_quality = next(
            (
                item
                for item in request.inputs
                if item.asset_type == "quality_score_report"
            ),
            None,
        )
        if prior_quality is not None:
            previous_blockers = tuple(
                sorted(
                    {
                        *previous_blockers,
                        *(
                            str(
                                item.get("observation")
                                or item.get("issue", {}).get("code")
                                or ""
                            )
                            for item in prior_quality.content.get("required_actions")
                            or ()
                        ),
                    }
                    - {""}
                )
            )
        generation = int(request.command.get("correction_generation") or 0)
        threshold = float(
            (request.command.get("preparation_report") or {}).get(
                "minimum_net_improvement", 3.0
            )
        )
        comparison = compare_candidates(
            project_id=request.project_id,
            chapter_root_operation_id=str(
                request.command.get("chapter_root_operation_id")
                or request.correlation_id
            ),
            previous=CandidateEvidence(
                asset_version_id=previous_asset.asset_version_id,
                content=previous_asset.content,
                score=previous_score,
                blocker_codes=tuple(previous_blockers),
                review_asset_version_id=previous_review_id,
            ),
            challenger=CandidateEvidence(
                asset_version_id=revision.asset_version_id,
                content=revision.content,
                score=float(rereview.content.get("score") or 0),
                blocker_codes=_blocking_issue_codes(rereview.content),
                review_asset_version_id=rereview.asset_version_id,
            ),
            minimum_net_improvement=threshold,
            correction_generation=generation,
            maximum_correction_generations=int(
                (request.command.get("preparation_report") or {}).get(
                    "maximum_correction_generations", 1
                )
            ),
        )
        best, snapshot = build_best_candidate(
            comparison=comparison,
            candidates={
                previous_asset.asset_version_id: previous_asset.content,
                revision.asset_version_id: revision.content,
            },
        )
        return ChapterHandlerOutput(
            asset_type=ChapterNode.BEST_CANDIDATE.asset_type,
            output_key=ChapterNode.BEST_CANDIDATE.output_key,
            role="primary",
            content=best,
            auxiliary_outputs=(
                ChapterAuxiliaryOutput(
                    asset_type="candidate_comparison",
                    output_key="chapter.best_candidate.comparison",
                    role="selection_evidence",
                    content=comparison,
                    reference_asset_version_ids=(
                        previous_asset.asset_version_id,
                        revision.asset_version_id,
                        rereview.asset_version_id,
                    ),
                ),
                ChapterAuxiliaryOutput(
                    asset_type="best_candidate_snapshot",
                    output_key="chapter.best_candidate.snapshot",
                    role="selection_evidence",
                    content=snapshot,
                    reference_asset_version_ids=(
                        previous_asset.asset_version_id,
                        revision.asset_version_id,
                    ),
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class _CanonHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("best_draft_candidate")
        extraction = request.require_input("canon_extraction")
        proposal = request.require_input("canon_change_proposal")
        decisions = [
            {**item.content, "asset_version_id": item.asset_version_id}
            for item in request.inputs
            if item.asset_type == "canon_approval_decision"
        ]
        resolved_extraction = resolve_canon_extraction(
            extraction=extraction.content,
            proposal={
                **proposal.content,
                "asset_version_id": proposal.asset_version_id,
            },
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
        continuity_report = {
            **dict(content["deterministic_validation"]),
            "project_id": request.project_id,
            "chapter": int(content["chapter"]),
            "canon_patch_source_operation_id": request.operation_id,
            "source_revision_asset_version_id": revision.asset_version_id,
            "context_bundle_asset_version_id": context.asset_version_id,
            "review_issue_candidates": [
                {
                    "issue_type": "deterministic_continuity",
                    "severity": item["severity"],
                    "blocking": item["severity"] == "blocking",
                    "code": item["conflict_code"],
                    "message": item["recommended_resolution"],
                    "evidence": item["evidence"],
                }
                for item in content["deterministic_validation"]["violations"]
            ],
        }
        validation_output = ChapterAuxiliaryOutput(
            asset_type="deterministic_continuity_report",
            output_key="chapter.canon.deterministic_continuity",
            role="completion_evidence",
            content=continuity_report,
            reference_asset_version_ids=tuple(
                sorted(
                    {
                        revision.asset_version_id,
                        extraction.asset_version_id,
                        proposal.asset_version_id,
                        context.asset_version_id,
                        *content["historical_input_version_ids"],
                    }
                )
            ),
            evidence={
                "authority_family": "chapter",
                "validator": "deterministic-continuity-v2",
                "semantic_judge_used": False,
            },
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
            auxiliary_outputs=(validation_output,),
        )


@dataclass(frozen=True, slots=True)
class _CanonExtractionHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("best_draft_candidate")
        context = request.require_input("context_bundle")
        provider_extraction = None
        generated: ModelProviderResult | None = None
        if bool(getattr(self.provider, "external_effect_backed", False)) or bool(
            getattr(self.provider, "supports_semantic_extraction", False)
        ):
            generated = self.provider.invoke(
                request,
                stage="canon_extraction",
                payload={
                    "revision": revision.content,
                    "execution_expectations": dict(
                        context.content.get("chapter_execution_expectations") or {}
                    ),
                },
            )
            provider_extraction = _canon_provider_extraction(generated)
        content = build_canon_extraction(
            revision=revision.content,
            revision_asset_version_id=revision.asset_version_id,
            project_id=request.project_id,
            context_bundle_version_id=context.asset_version_id,
            provider_extraction=provider_extraction,
        )
        if generated is None:
            return _output(ChapterNode.CANON_EXTRACTION, content)
        return _model_output(
            ChapterNode.CANON_EXTRACTION,
            content,
            request=request,
            generated=generated,
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
        revision = request.require_input("best_draft_candidate")
        plan = request.require_input("chapter_plan")
        canon = request.require_input("canon_patch")
        context = request.require_input("context_bundle")
        fixture = not any(
            bool(item.content.get("provider_evidence", {}).get("real_model_call"))
            for item in request.inputs
        )
        context_content = dict(context.content)
        generated: ModelProviderResult | None = None
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
            token_budget=resolve_stage_context_token_budget(
                request.command, f"quality_{self.group}"
            ),
        )
        if bool(
            getattr(self.provider, "external_effect_backed", False)
            or getattr(self.provider, "supports_quality_evaluation", False)
        ):
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
                provider_entries.append(
                    {
                        **dict(item),
                        "target_asset_version_id": revision.asset_version_id,
                        "calibration_status": "PROVIDER_UNCALIBRATED",
                        "provider_verified": True,
                    }
                )
            context_content["context_segments"] = [
                *list(context.content.get("context_segments", [])),
                {
                    "asset_version_id": f"external-effect:{request.operation_id}",
                    "narrative_function": "quality_evidence",
                    "source_expression_included": False,
                    "structured_facts": [
                        {"key": "dimension_evidence", "value": provider_entries}
                    ],
                },
            ]
            fixture = not generated.real_model_call
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
        content["quality_context_coverage"] = dict(quality_context["coverage_report"])
        node = {
            "structural": ChapterNode.QUALITY_STRUCTURAL,
            "commercial": ChapterNode.QUALITY_COMMERCIAL,
            "source_originality": ChapterNode.QUALITY_SOURCE_ORIGINALITY,
            "longform": ChapterNode.QUALITY_LONGFORM,
            "platform": ChapterNode.QUALITY_PLATFORM,
        }[self.group]
        primary = _output(node, content)
        coverage = ChapterAuxiliaryOutput(
            asset_type="quality_context_coverage_report",
            output_key=f"chapter.quality.context_coverage.{self.group}",
            role="quality_context_evidence",
            content={
                **dict(quality_context["coverage_report"]),
                "project_id": request.project_id,
                "group": self.group,
                "target_revision_asset_version_id": revision.asset_version_id,
                "context_bundle_asset_version_id": context.asset_version_id,
                "context_digest": quality_context["context_digest"],
            },
            reference_asset_version_ids=(
                revision.asset_version_id,
                plan.asset_version_id,
                canon.asset_version_id,
                context.asset_version_id,
            ),
            evidence={
                "group": self.group,
                "critical_facts_preserved": quality_context["coverage_report"][
                    "critical_facts_preserved"
                ],
            },
        )
        auxiliaries: tuple[ChapterAuxiliaryOutput, ...] = (coverage,)
        if self.group == "commercial":
            provider_dimensions = (
                list(generated.output.get("dimensions", []))
                if generated is not None
                else []
            )
            provider_evidence = (
                {
                    **_provider_evidence(generated),
                    "trace_id": request.trace_id,
                    "operation_id": request.operation_id,
                }
                if generated is not None
                else {
                    "trace_id": request.trace_id,
                    "operation_id": request.operation_id,
                    "real_model_call": False,
                }
            )
            hook_analysis = build_hook_analysis(
                project_id=request.project_id,
                chapter=int(revision.content["chapter"]),
                chapter_plan=plan.content,
                provider_dimensions=provider_dimensions,
                target_asset_version_id=revision.asset_version_id,
                chapter_plan_asset_version_id=plan.asset_version_id,
                provider_evidence=provider_evidence,
            )
            pacing_observation = build_pacing_observation(
                project_id=request.project_id,
                chapter=int(revision.content["chapter"]),
                revision=revision.content,
                chapter_plan=plan.content,
                canon=canon.content,
                provider_dimensions=provider_dimensions,
                target_asset_version_id=revision.asset_version_id,
                provider_evidence=provider_evidence,
            )
            intelligence_refs = (
                revision.asset_version_id,
                plan.asset_version_id,
                canon.asset_version_id,
                context.asset_version_id,
            )
            auxiliaries = (
                *auxiliaries,
                ChapterAuxiliaryOutput(
                    asset_type="hook_analysis",
                    output_key="chapter.quality.commercial.hook_analysis",
                    role="longform_observation",
                    content=hook_analysis,
                    reference_asset_version_ids=intelligence_refs,
                    evidence={
                        "capability": "hook.analyze",
                        "commercial_quality_reused": True,
                    },
                ),
                ChapterAuxiliaryOutput(
                    asset_type="pacing_observation",
                    output_key="chapter.quality.commercial.pacing_observation",
                    role="longform_observation",
                    content=pacing_observation,
                    reference_asset_version_ids=intelligence_refs,
                    evidence={
                        "capability": "pacing.analyze",
                        "semantic_and_deterministic_separated": True,
                    },
                ),
            )
        if generated is not None:
            commit = _execution_commit_auxiliary(node, request, generated)
            if commit is not None:
                auxiliaries = (*auxiliaries, commit)
        return ChapterHandlerOutput(
            asset_type=primary.asset_type,
            output_key=primary.output_key,
            role=primary.role,
            content=primary.content,
            qualification_policy=primary.qualification_policy,
            auxiliary_outputs=auxiliaries,
        )


@dataclass(frozen=True, slots=True)
class _QualityHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = request.require_input("chapter_plan")
        revision = request.require_input("best_draft_candidate")
        review = request.require_input("re_review_report")
        canon = request.require_input("canon_patch")
        context = request.require_input("context_bundle")
        groups = [
            item
            for item in request.inputs
            if item.asset_type == "chapter_quality_group_report"
        ]
        if {str(item.content.get("group")) for item in groups} != {
            "structural",
            "commercial",
            "source_originality",
            "longform",
            "platform",
        }:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "QUALITY_FANIN_INCOMPLETE", "all five quality groups are required"
            )
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
        action_outputs = (
            tuple(
                ChapterAuxiliaryOutput(
                    asset_type="revision_task",
                    output_key=f"chapter.quality.required_action.{ordinal}",
                    role="required_action",
                    content={
                        **dict(action),
                        "type": "GovernedRevisionTask",
                        "contract_version": "governed-revision-task-v1",
                        "project_id": request.project_id,
                        "chapter": int(content["chapter"]),
                        "target_revision_asset_version_id": revision.asset_version_id,
                        "source_quality_operation_id": request.operation_id,
                        "status": "OPEN",
                        "mutates_accepted_canon": False,
                    },
                    reference_asset_version_ids=tuple(
                        sorted(
                            {
                                revision.asset_version_id,
                                review.asset_version_id,
                                canon.asset_version_id,
                                context.asset_version_id,
                                *action.get("evidence_asset_version_ids", []),
                            }
                        )
                    ),
                    evidence={
                        "required_authority": action["required_authority"],
                        "reevaluation_gate": action["reevaluation_gate"],
                    },
                )
                for ordinal, action in enumerate(
                    content.get("required_actions", []), start=1
                )
            )
            if not any(item.asset_type == "revision_task" for item in request.inputs)
            else ()
        )
        manifest = dict(context.content.get("context_manifest") or {})
        authority_boundary = dict(manifest.get("authority_state_boundary") or {})
        provider_usage = _provider_usage_records(request.inputs)
        knowledge_selection = [
            dict(item) for item in manifest.get("knowledge_usage") or []
        ]
        provider_effect_ids = sorted(
            {
                str(record.get("external_effect_id") or "")
                for record in provider_usage or []
                if str(record.get("external_effect_id") or "")
            }
        )
        if provider_usage is None:
            mkaos_usage = None
        elif not knowledge_selection:
            mkaos_usage = []
        elif not provider_effect_ids:
            mkaos_usage = [{"availability": "NOT_AVAILABLE"}]
        else:
            mkaos_usage = [
                {
                    **item,
                    "availability": "MEASURED",
                    "context_manifest_asset_version_id": context.asset_version_id,
                    "provider_external_effect_ids": provider_effect_ids,
                    "result_asset_version_id": revision.asset_version_id,
                }
                for item in knowledge_selection
            ]
        planning_violations = [
            {
                "dimension": str(item.get("observation") or ""),
                "evidence_asset_version_ids": list(
                    item.get("evidence_asset_version_ids") or []
                ),
                "issue": dict(item.get("issue") or {}),
            }
            for item in content.get("required_actions", [])
            if str(item.get("observation") or "")
            in {
                "canon_consistency",
                "character_motivation_drift",
                "relationship_continuity",
                "timeline_consistency",
                "foreshadow_status",
                "promise_payoff_debt",
                "world_rule_conflict",
                "power_state_conflict",
                "arc_progress",
            }
        ]
        constraint_envelope = plan.content.get("constraint_envelope")
        planning_evidence = (
            {
                "constraint_envelope": dict(constraint_envelope),
                "constraint_violations": planning_violations,
                "evidence_source": "chapter_quality_aggregate",
            }
            if isinstance(constraint_envelope, dict) and constraint_envelope
            else None
        )
        measurement = measure_narrative_runtime(
            story_state={
                "accepted_through_chapter": authority_boundary.get(
                    "accepted_through_chapter",
                    max(0, int(content["chapter"]) - 1),
                ),
                "state_hash": authority_boundary.get(
                    "story_state_snapshot_version",
                    context.content.get("story_state_snapshot_version", ""),
                ),
            },
            context_bundle=context.content,
            planning_candidate=planning_evidence,
            quality_decision=content,
            mkaos_usage_records=mkaos_usage,
            provider_usage_records=provider_usage,
        )
        measurement_output = ChapterAuxiliaryOutput(
            asset_type="narrative_runtime_measurement",
            output_key="chapter.quality.narrative_runtime_measurement",
            role="proof_observation",
            content={
                **measurement,
                "project_id": request.project_id,
                "chapter": int(content["chapter"]),
                "source_quality_operation_id": request.operation_id,
                "context_bundle_asset_version_id": context.asset_version_id,
            },
            reference_asset_version_ids=tuple(
                sorted(
                    {
                        revision.asset_version_id,
                        review.asset_version_id,
                        canon.asset_version_id,
                        context.asset_version_id,
                        plan.asset_version_id,
                        *(
                            item.asset_version_id
                            for item in request.inputs
                            if item.asset_type in {"model_call_log", "cost_ledger"}
                        ),
                        *(item.asset_version_id for item in groups),
                    }
                )
            ),
            evidence={
                "proof_status": measurement["proof_status"],
                "context_digest": context.content.get("actual_context_digest", ""),
                "production_verified": False,
            },
        )
        accepted_through_chapter = int(
            authority_boundary.get(
                "accepted_through_chapter",
                max(0, int(content["chapter"]) - 1),
            )
        )
        multiscale_quality = build_multiscale_quality_report(
            project_id=request.project_id,
            book_id=str(
                request.command.get("book_id")
                or plan.content.get("book_id")
                or context.content.get("book_id")
                or ""
            ),
            context_bundle=context.content,
            accepted_through_chapter=accepted_through_chapter,
            source_asset_version_ids=(
                context.asset_version_id,
                plan.asset_version_id,
                *(item.asset_version_id for item in groups),
            ),
        )
        multiscale_output = ChapterAuxiliaryOutput(
            asset_type="multiscale_narrative_quality_report",
            output_key="chapter.quality.multiscale_narrative_quality",
            role="longitudinal_quality_projection",
            content={
                **multiscale_quality,
                "source_quality_operation_id": request.operation_id,
            },
            reference_asset_version_ids=tuple(
                sorted(
                    {
                        context.asset_version_id,
                        plan.asset_version_id,
                        *(item.asset_version_id for item in groups),
                    }
                )
            ),
            evidence={
                "accepted_history_only": True,
                "observation_status": multiscale_quality["observation_status"],
                "production_verified": False,
            },
        )
        return ChapterHandlerOutput(
            asset_type=primary.asset_type,
            output_key=primary.output_key,
            role=primary.role,
            content=primary.content,
            qualification_policy=primary.qualification_policy,
            auxiliary_outputs=(
                *evidence_outputs,
                *action_outputs,
                measurement_output,
                multiscale_output,
            ),
        )


def _provider_usage_records(
    inputs: tuple[ChapterInputAsset, ...],
) -> list[dict[str, Any]] | None:
    costs = {
        (
            str(item.content.get("operation_id") or ""),
            str(item.content.get("attempt_id") or ""),
            str(item.content.get("stage") or ""),
        ): item.content
        for item in inputs
        if item.asset_type == "cost_ledger"
    }
    model_calls = [item for item in inputs if item.asset_type == "model_call_log"]
    if not model_calls:
        return None
    records: list[dict[str, Any]] = []
    for item in model_calls:
        content = dict(item.content)
        evidence = dict(content.get("provider_evidence") or {})
        usage = dict(evidence.get("usage") or {})
        cost = dict(evidence.get("cost") or {})
        key = (
            str(content.get("operation_id") or ""),
            str(content.get("attempt_id") or ""),
            str(content.get("stage") or ""),
        )
        ledger = dict(costs.get(key) or {})
        total_tokens = (
            ledger.get("total_tokens")
            if "total_tokens" in ledger
            else usage.get("total_tokens")
        )
        amount = ledger.get("amount") if "amount" in ledger else cost.get("amount")
        records.append(
            {
                "model_call_log_asset_version_id": item.asset_version_id,
                "operation_id": key[0],
                "attempt_id": key[1],
                "stage": key[2],
                "external_effect_id": str(
                    content.get("external_effect_id")
                    or ledger.get("external_effect_id")
                    or ""
                ),
                "provider_id": str(
                    evidence.get("provider_id") or ledger.get("provider_id") or ""
                ),
                "model_id": str(
                    evidence.get("model_id") or ledger.get("model_id") or ""
                ),
                "trace_id": str(
                    content.get("trace_id") or ledger.get("trace_id") or ""
                ),
                "total_tokens": (
                    int(total_tokens) if total_tokens is not None else None
                ),
                "cost": str(amount) if amount is not None else None,
                "currency": str(ledger.get("currency") or cost.get("currency") or ""),
                "usage_receipt_ref": str(
                    (evidence.get("production_execution") or {})
                    .get("execution_result", {})
                    .get("usage_receipt_ref")
                    or ""
                ),
                "cost_receipt_ref": str(
                    (evidence.get("production_execution") or {})
                    .get("execution_result", {})
                    .get("cost_receipt_ref")
                    or ""
                ),
                "accepted_candidate": bool(content.get("accepted_candidate", True)),
                "retry_count": 0 if content.get("accepted_candidate", True) else 1,
            }
        )
    return records


@dataclass(frozen=True, slots=True)
class _PublishGateHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("best_draft_candidate")
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
        revision = request.require_input("best_draft_candidate")
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
    routes = getattr(getattr(provider, "adapter", None), "routes", {})
    semantic_provider_bound = isinstance(routes, dict) and "retrieval" in routes
    registry = ChapterHandlerRegistry(
        model_effects_required=bool(getattr(provider, "external_effect_backed", False)),
        semantic_retrieval_available=semantic_provider_bound,
    )
    registry.register(ChapterNode.PLAN, _PlanHandler())
    registry.register(ChapterNode.EXECUTION_INTENT, _ExecutionIntentHandler())
    registry.register(ChapterNode.MEMO, _MemoHandler())
    registry.register(
        ChapterNode.RETRIEVAL,
        _RetrievalHandler(provider, semantic_provider_bound),
    )
    registry.register(ChapterNode.CONTEXT, _ContextHandler())
    registry.register(ChapterNode.DRAFT, _DraftHandler(provider))
    registry.register(ChapterNode.REVIEW, _ReviewHandler(provider))
    registry.register(ChapterNode.REVISION, _RevisionHandler(provider))
    registry.register(ChapterNode.REREVIEW, _ReReviewHandler(provider))
    registry.register(ChapterNode.BEST_CANDIDATE, _BestCandidateHandler())
    registry.register(ChapterNode.CANON_EXTRACTION, _CanonExtractionHandler(provider))
    registry.register(ChapterNode.CANON_PROPOSAL, _CanonProposalHandler())
    registry.register(ChapterNode.CANON, _CanonHandler())
    registry.register(
        ChapterNode.QUALITY_STRUCTURAL, _QualityGroupHandler("structural", provider)
    )
    registry.register(
        ChapterNode.QUALITY_COMMERCIAL, _QualityGroupHandler("commercial", provider)
    )
    registry.register(
        ChapterNode.QUALITY_SOURCE_ORIGINALITY,
        _QualityGroupHandler("source_originality", provider),
    )
    registry.register(
        ChapterNode.QUALITY_LONGFORM, _QualityGroupHandler("longform", provider)
    )
    registry.register(
        ChapterNode.QUALITY_PLATFORM, _QualityGroupHandler("platform", provider)
    )
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


def _blocking_issue_codes(review: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(item.get("code") or "")
                for item in review.get("issues") or ()
                if isinstance(item, dict)
                and str(item.get("severity") or "").lower()
                in {"blocking", "blocker", "critical", "high"}
                and str(item.get("code") or "")
            }
        )
    )


def _model_output(
    node: ChapterNode,
    content: dict[str, Any],
    *,
    request: ChapterHandlerRequest,
    generated: ModelProviderResult,
) -> ChapterHandlerOutput:
    primary = _output(node, content)
    commit = _execution_commit_auxiliary(node, request, generated)
    if commit is None:
        return primary
    return ChapterHandlerOutput(
        asset_type=primary.asset_type,
        output_key=primary.output_key,
        role=primary.role,
        content=primary.content,
        qualification_policy=primary.qualification_policy,
        auxiliary_outputs=(commit,),
    )


def _execution_commit_auxiliary(
    node: ChapterNode,
    request: ChapterHandlerRequest,
    generated: ModelProviderResult,
) -> ChapterAuxiliaryOutput | None:
    execution = generated.execution_evidence
    if not execution:
        return None
    validation_ref = str(execution.get("validation_manifest_ref") or "")
    if not validation_ref:
        raise KernelError(
            "EXECUTION_COMMIT_MANIFEST_INVALID",
            "gateway output has no durable ValidationManifest evidence reference",
        )
    committed_ref = f"authority-output:{request.operation_id}:{node.output_key}:v1"
    manifest = CommitManifest(
        manifest_id=f"commit-manifest:{request.operation_id}:{node.value}",
        operation_id=request.operation_id,
        attempt_id=request.attempt_id,
        fencing_token=request.fencing_token,
        validation_manifest_ref=validation_ref,
        committed_asset_version_refs=(committed_ref,),
        authority_commit_ref=(
            f"authority-operation:{request.operation_id}:output:{node.output_key}"
        ),
        projection_materialization_refs=(),
        rejected_output_refs=(),
        rollback_ref=f"append-only:supersede:{committed_ref}",
        decision="COMMITTED",
    )
    route = execution.get("route_snapshot")
    return ChapterAuxiliaryOutput(
        asset_type="execution_commit_manifest",
        output_key=f"{node.output_key}.execution_commit_manifest",
        role="execution_commit_evidence",
        content=manifest.to_dict(),
        qualification_policy="production-execution-commit-v1",
        evidence={
            "route_snapshot_id": (
                str(route.get("route_snapshot_id") or "")
                if isinstance(route, dict)
                else ""
            ),
            "external_effect_bound": True,
        },
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
