from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.production_retrieval import (
    build_campaign_final_query_plan,
    build_expanded_retrieval_query_plan,
    build_retrieval_result,
    discover_accepted_retrieval_candidates,
    freeze_retrieval_candidate_union,
    load_frozen_retrieval_candidate_union,
)
from novel_forge.modules.context_builder.retrieval_campaign import (
    RetrievalCampaignPolicy,
    decide_retrieval_campaign_transition,
    evaluate_retrieval_coverage,
    merge_retrieval_round_documents,
    validate_retrieval_expansion_plan,
)
from novel_forge.modules.context_builder.retrieval_campaign_store import (
    complete_retrieval_campaign,
    freeze_retrieval_round,
    load_retrieval_rounds,
    start_retrieval_campaign,
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
    provider_id = "deterministic_chapter_fixture_v1"
    external_effect_backed = False

    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
        reservation_amount: str | None = None,
        reservation_tokens: int | None = None,
        pre_send_assertion: Any | None = None,
    ) -> ModelProviderResult:
        if stage in {"memo", "canon_support"}:
            from .execution_gateway import default_chapter_fixture_response
            output = default_chapter_fixture_response(stage, payload)
        elif stage == "draft":
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
            raise KernelError(
                "MODEL_EFFECT_STAGE_UNSUPPORTED", f"unsupported fixture stage: {stage}"
            )
        output = self.structured_fixture_output(stage, payload, output)
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


    @staticmethod
    def structured_fixture_output(
        stage: str, payload: dict[str, Any], output: dict[str, Any]
    ) -> dict[str, Any]:
        if stage in {"review", "rereview"}:
            from .execution_gateway import _fixture_knowledge_checks
            return {**output, "knowledge_checks": _fixture_knowledge_checks(payload)}
        if stage not in {"draft", "revision"}:
            return output
        text = str(output["text"])
        if stage == "draft":
            artifacts = [
                {"slot_id": slot["slot_id"], "text": text if index == 0 else "The visible consequences continue.", "used_fact_ids": []}
                for index, slot in enumerate((payload.get("realization_contract") or {}).get("slots", []))
            ]
        else:
            draft = payload["draft"]
            artifacts = json.loads(json.dumps(draft.get("scene_artifacts", [])))
            if artifacts:
                if not text.startswith(draft["text"]):
                    raise ValueError("fixture revision only supports append-only prose")
                artifacts[-1]["text"] += text[len(draft["text"]):]
        from .realization_composition import serialize_realization
        separators = (payload.get("draft") or {}).get("scene_separators") if stage == "revision" else None
        return {**output, "scene_artifacts": artifacts, "text": serialize_realization(artifacts, separators) if artifacts else text}


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
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        intent = request.require_input("chapter_execution_intent")
        generated = self.provider.invoke(request, stage="memo", payload={"execution_intent": intent.content})
        from .creative_memo import qualify_creative_memo
        content = qualify_creative_memo(
            intent=intent.content, intent_asset_version_id=intent.asset_version_id,
            result=generated.output, execution_evidence=_provider_evidence(generated),
        )
        return _model_output(ChapterNode.MEMO, content, request=request, generated=generated)


def deterministic_retrieval_coverage_fast_path(
    *, project_id: str, book_id: str, intent_asset_version_id: str,
    memo_asset_version_id: str, query_plan: dict[str, Any],
    documents: list[dict[str, Any]], semantic_status: dict[str, Any],
    context_token_budget: int,
) -> bool:
    del context_token_budget
    if query_plan.get("semantic_policy") != "FALLBACK_ALLOWED":
        return False
    preview = build_retrieval_result(
        project_id=project_id,
        book_id=book_id,
        intent_asset_version_id=intent_asset_version_id,
        memo_asset_version_id=memo_asset_version_id,
        query_plan=query_plan,
        documents=documents,
        discovery_rejections=(),
        semantic_status=semantic_status,
    )
    selected = preview["selected_documents"]
    coverage = evaluate_retrieval_coverage(
        contract=dict(query_plan.get("coverage_contract") or {}),
        documents=selected,
    )
    return bool(coverage.get("sufficient")) and (
        bool(selected)
        or int(dict(query_plan.get("accepted_boundary") or {}).get("accepted_through_chapter") or 0) == 0
    )


def bind_quality_prose_evidence(
    locations: list[dict[str, Any]], *, text: str, target_asset_version_id: str,
) -> list[dict[str, Any]]:
    from novel_forge.modules.review.diagnostics import validate_location

    return [
        {
            **validate_location({"quote": evidence.get("quote")}, text),
            "claim": evidence.get("claim"),
            "target_asset_version_id": target_asset_version_id,
        }
        for evidence in locations
    ]


@dataclass(frozen=True, slots=True)
class _RetrievalHandler:
    provider: ChapterModelPort
    semantic_provider_bound: bool = False
    expansion_provider_bound: bool = False

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
            deterministic_coverage = deterministic_retrieval_coverage_fast_path(
                project_id=request.project_id,
                book_id=str(plan.content.get("book_id") or f"book:{request.project_id}"),
                intent_asset_version_id=intent.asset_version_id,
                memo_asset_version_id=memo.asset_version_id,
                query_plan=query_plan,
                documents=documents,
                semantic_status=semantic_status,
                context_token_budget=int(request.command.get("context_token_budget") or 6000),
            )
            if deterministic_coverage:
                semantic_status["deterministic_coverage_fast_path"] = True
            if (
                semantic_enabled
                and not deterministic_coverage
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
            self._run_campaign(
                request=request,
                plan=plan,
                intent=intent,
                memo=memo,
                query_plan=query_plan,
                frozen_union=frozen_union,
                discovery_rejections=tuple(
                    dict(item) for item in snapshot.get("rejected_documents") or ()
                ),
            ),
        )

    def _run_campaign(
        self,
        *,
        request: ChapterHandlerRequest,
        plan: ChapterInputAsset,
        intent: ChapterInputAsset,
        memo: ChapterInputAsset,
        query_plan: dict[str, Any],
        frozen_union: Any,
        discovery_rejections: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        book_id = str(plan.content.get("book_id") or f"book:{request.project_id}")
        policy = RetrievalCampaignPolicy(
            **dict(query_plan.get("campaign_policy") or {})
        )
        coverage_contract = dict(query_plan.get("coverage_contract") or {})
        campaign = start_retrieval_campaign(
            request.database_url,
            project_id=request.project_id,
            book_id=book_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            worker_id=request.worker_id,
            chapter=int(plan.content.get("chapter") or 0),
            intent_asset_version_id=intent.asset_version_id,
            memo_asset_version_id=memo.asset_version_id,
            intent_fingerprint=str(intent.content.get("intent_fingerprint") or ""),
            memo_fingerprint=str(memo.content.get("memo_fingerprint") or ""),
            accepted_boundary=dict(intent.content.get("accepted_boundary") or {}),
            policy=policy,
            coverage_contract=coverage_contract,
        )
        rounds = load_retrieval_rounds(
            request.database_url, campaign_id=str(campaign["campaign_id"])
        )
        if not rounds:
            round_zero_result = build_retrieval_result(
                project_id=request.project_id,
                book_id=book_id,
                intent_asset_version_id=intent.asset_version_id,
                memo_asset_version_id=memo.asset_version_id,
                query_plan=query_plan,
                documents=frozen_union.documents,
                discovery_rejections=discovery_rejections,
                semantic_status=frozen_union.semantic_status,
                query_embedding=frozen_union.query_embedding,
                query_embedding_evidence=frozen_union.query_embedding_evidence,
                candidate_snapshot_id=frozen_union.candidate_snapshot_id,
                candidate_snapshot_hash=frozen_union.snapshot_hash,
            )
            coverage_before = evaluate_retrieval_coverage(
                contract=coverage_contract, documents=()
            )
            coverage_after = evaluate_retrieval_coverage(
                contract=coverage_contract,
                documents=round_zero_result["selected_documents"],
            )
            freeze_retrieval_round(
                request.database_url,
                campaign_id=str(campaign["campaign_id"]),
                project_id=request.project_id,
                book_id=book_id,
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
                worker_id=request.worker_id,
                round_number=0,
                query_plan=query_plan,
                documents=frozen_union.documents,
                rejected_documents=discovery_rejections,
                semantic_status=frozen_union.semantic_status,
                coverage_before=coverage_before,
                coverage_after=coverage_after,
                new_evidence_count=len(frozen_union.documents),
                provider_evidence=frozen_union.query_embedding_evidence,
                external_effect_id=_external_effect_id(
                    frozen_union.query_embedding_evidence
                ),
                **_provider_usage(frozen_union.query_embedding_evidence),
            )
            rounds = load_retrieval_rounds(
                request.database_url, campaign_id=str(campaign["campaign_id"])
            )

        termination_reason = str(campaign.get("termination_reason") or "")
        while not termination_reason:
            coverage = dict(rounds[-1]["coverage_after"])
            usage = _campaign_usage(rounds)
            decision = decide_retrieval_campaign_transition(
                coverage=coverage,
                policy=policy,
                completed_rounds=len(rounds),
                total_queries=sum(
                    len(item["query_plan"].get("queries") or ()) for item in rounds
                ),
                provider_calls=usage["provider_calls"],
                model_tokens=usage["model_tokens"],
                cost_amount=usage["cost_amount"],
                last_round_new_evidence=int(rounds[-1]["new_evidence_count"]),
                expansion_available=self.expansion_provider_bound,
            )
            if not bool(decision["continue"]):
                termination_reason = str(decision["termination_reason"])
                break

            round_number = len(rounds)
            existing_query_count = sum(
                len(item["query_plan"].get("queries") or ()) for item in rounds
            )
            prior_fingerprints = [
                str(query.get("query_fingerprint") or "")
                for item in rounds
                for query in item["expansion_plan"].get("queries") or ()
            ]
            expansion_request = replace(
                request,
                command={
                    **request.command,
                    "_effect_instance": f"retrieval-expansion-round-{round_number}",
                    "context_token_budget": min(
                        resolve_stage_context_token_budget(
                            request.command,
                            "retrieval_query_expansion",
                        ),
                        policy.model_token_limit - usage["model_tokens"],
                    ),
                },
            )
            remaining_cost = max(
                Decimal("0"),
                Decimal(policy.cost_limit) - Decimal(usage["cost_amount"]),
            )
            provider_cost_ceiling = Decimal(
                str(getattr(self.provider, "max_cost_per_call", "0") or "0")
            )
            provider_result = self.provider.invoke(
                expansion_request,
                stage="retrieval_query_expansion",
                payload={
                    "campaign_id": str(campaign["campaign_id"]),
                    "round_number": round_number,
                    "accepted_boundary": dict(
                        coverage_contract.get("accepted_boundary") or {}
                    ),
                    "intent_fingerprint": str(
                        coverage_contract.get("intent_fingerprint") or ""
                    ),
                    "memo_fingerprint": str(
                        coverage_contract.get("memo_fingerprint") or ""
                    ),
                    "mission": dict(intent.content.get("chapter_mission") or {}),
                    "memo": dict(memo.content),
                    "coverage": coverage,
                    "coverage_contract": coverage_contract,
                    "allowed_retrieval_dimensions": sorted(
                        dict(coverage_contract.get("selectors") or {})
                    ),
                    "allowed_retrieval_selectors": dict(
                        coverage_contract.get("selectors") or {}
                    ),
                    "prior_rounds": [
                        {
                            "round_number": int(item["round_number"]),
                            "query_plan_fingerprint": str(
                                item["query_plan_fingerprint"]
                            ),
                            "coverage_after": dict(item["coverage_after"]),
                            "new_evidence_count": int(item["new_evidence_count"]),
                        }
                        for item in rounds
                    ],
                    "policy": policy.to_dict(),
                },
                reservation_amount=format(
                    min(remaining_cost, provider_cost_ceiling), "f"
                ),
                reservation_tokens=(policy.model_token_limit - usage["model_tokens"]),
            )
            expansion_plan = validate_retrieval_expansion_plan(
                raw=provider_result.output,
                contract=coverage_contract,
                coverage=coverage,
                policy=policy,
                round_number=round_number,
                prior_query_fingerprints=prior_fingerprints,
                existing_query_count=existing_query_count,
            )
            expanded_query_plan = build_expanded_retrieval_query_plan(
                base_query_plan=query_plan,
                expansion_plan=expansion_plan,
            )
            discovery = discover_accepted_retrieval_candidates(
                request.database_url,
                project_id=request.project_id,
                book_id=book_id,
                query_plan=expanded_query_plan,
            )
            existing_ids = {
                str(document.get("retrieval_document_id") or "")
                for item in rounds
                for document in item["documents"]
            }
            merged_documents = merge_retrieval_round_documents(
                [
                    *(item["documents"] for item in rounds),
                    discovery.documents,
                ]
            )
            round_plans = [
                *(item["query_plan"] for item in rounds),
                discovery.query_plan,
            ]
            final_plan = build_campaign_final_query_plan(
                base_query_plan=query_plan, round_query_plans=round_plans
            )
            intermediate = build_retrieval_result(
                project_id=request.project_id,
                book_id=book_id,
                intent_asset_version_id=intent.asset_version_id,
                memo_asset_version_id=memo.asset_version_id,
                query_plan=final_plan,
                documents=merged_documents,
                discovery_rejections=(
                    *discovery_rejections,
                    *(
                        rejection
                        for item in rounds[1:]
                        for rejection in item["rejected_documents"]
                    ),
                    *discovery.rejected_documents,
                ),
                semantic_status=_campaign_semantic_status(
                    rounds, discovery.semantic_status
                ),
                candidate_snapshot_id=str(campaign["campaign_id"]),
            )
            coverage_after = evaluate_retrieval_coverage(
                contract=coverage_contract,
                documents=intermediate["selected_documents"],
            )
            evidence = provider_result.to_evidence()
            freeze_retrieval_round(
                request.database_url,
                campaign_id=str(campaign["campaign_id"]),
                project_id=request.project_id,
                book_id=book_id,
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
                worker_id=request.worker_id,
                round_number=round_number,
                query_plan=discovery.query_plan,
                documents=discovery.documents,
                rejected_documents=discovery.rejected_documents,
                semantic_status=discovery.semantic_status,
                coverage_before=coverage,
                coverage_after=coverage_after,
                new_evidence_count=sum(
                    str(item.get("retrieval_document_id") or "") not in existing_ids
                    for item in discovery.documents
                ),
                expansion_plan=expansion_plan,
                expansion_reason="DETERMINISTIC_COVERAGE_GAP",
                provider_evidence=evidence,
                external_effect_id=_external_effect_id(evidence),
                input_tokens=provider_result.input_tokens,
                output_tokens=provider_result.output_tokens,
                cost_amount=provider_result.cost_amount,
                currency=provider_result.currency,
                latency_ms=_provider_latency_ms(evidence),
            )
            rounds = load_retrieval_rounds(
                request.database_url, campaign_id=str(campaign["campaign_id"])
            )

        merged_documents = merge_retrieval_round_documents(
            item["documents"] for item in rounds
        )
        final_plan = build_campaign_final_query_plan(
            base_query_plan=query_plan,
            round_query_plans=(item["query_plan"] for item in rounds),
        )
        final_semantic_status = _campaign_semantic_status(rounds)
        final_evidence_identity = _content_hash(
            {
                "campaign_id": str(campaign["campaign_id"]),
                "round_snapshot_hashes": [item["snapshot_hash"] for item in rounds],
                "coverage": dict(rounds[-1]["coverage_after"]),
                "termination_reason": termination_reason,
            }
        )
        result = build_retrieval_result(
            project_id=request.project_id,
            book_id=book_id,
            intent_asset_version_id=intent.asset_version_id,
            memo_asset_version_id=memo.asset_version_id,
            query_plan=final_plan,
            documents=merged_documents,
            discovery_rejections=tuple(
                rejection for item in rounds for rejection in item["rejected_documents"]
            ),
            semantic_status=final_semantic_status,
            query_embedding=(frozen_union.query_embedding if len(rounds) == 1 else ()),
            query_embedding_evidence=(
                frozen_union.query_embedding_evidence if len(rounds) == 1 else {}
            ),
            candidate_snapshot_id=str(campaign["campaign_id"]),
            candidate_snapshot_hash=final_evidence_identity,
        )
        result.pop("result_fingerprint", None)
        result["retrieval_campaign"] = {
            "contract_version": "retrieval-campaign-result-v1",
            "campaign_id": str(campaign["campaign_id"]),
            "policy_version": policy.policy_version,
            "accepted_boundary": dict(coverage_contract.get("accepted_boundary") or {}),
            "round_count": len(rounds),
            "round_snapshot_hashes": [item["snapshot_hash"] for item in rounds],
            "coverage": dict(rounds[-1]["coverage_after"]),
            "termination_reason": termination_reason,
            "final_evidence_identity": final_evidence_identity,
            "usage": _campaign_usage(rounds),
            "authority": "DETERMINISTIC_CONTEXT_POLICY",
        }
        result["result_fingerprint"] = _content_hash(result)
        terminal_status = (
            "FALLBACK"
            if termination_reason == "DETERMINISTIC_FALLBACK"
            else "COMPLETED"
        )
        completed = complete_retrieval_campaign(
            request.database_url,
            campaign_id=str(campaign["campaign_id"]),
            project_id=request.project_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            worker_id=request.worker_id,
            status=terminal_status,
            termination_reason=termination_reason,
            final_result_fingerprint=str(result["result_fingerprint"]),
            final_evidence_identity=final_evidence_identity,
        )
        if str(completed["final_result_fingerprint"]) != str(
            result["result_fingerprint"]
        ):
            raise KernelError(
                "RETRIEVAL_CAMPAIGN_REPLAY_DRIFT",
                "replayed retrieval campaign produced a different result identity",
            )
        return result


def merge_task_retrieval_projections(metadata: dict[str, Any], documents: list[dict[str, Any]]) -> dict[str, Any]:
    from novel_forge.modules.context_builder.writer_projection import WRITER_PROJECTION_VERSION, project_writer_history, provider_visible_data

    clean_history = any((item.get("compression_provenance") or {}).get("writer_projection_version") in {WRITER_PROJECTION_VERSION, "accepted-writer-history.v2"} for item in documents)
    source_type = str((documents[0].get("source_artifact_type") if documents else "") or metadata.get("physical_asset_type") or "")
    summary = str(metadata.get("safe_summary") or "")
    if clean_history and summary:
        summary = project_writer_history(summary, source_artifact_type=source_type)
    facts = list(metadata.get("structured_facts") or ())
    summaries = [summary]
    refs = set(metadata.get("task_dependency_matched_refs") or ())
    reasons = set(metadata.get("retrieval_reasons") or ())
    for document in sorted(documents, key=lambda item: str(item.get("retrieval_document_id") or "")):
        if str(document.get("source_content_hash") or "") != str(metadata.get("content_hash") or ""):
            raise KernelError("CONTEXT_RETRIEVAL_SOURCE_DRIFT", "same-source task projections must bind the exact frozen content hash")
        facts.extend(fact for fact in (document.get("metadata") or {}).get("structured_facts", ()) if isinstance(fact, dict))
        summary = str(document.get("safe_summary") or "")
        summaries.append(project_writer_history(summary, source_artifact_type=source_type) if clean_history and summary else summary)
        refs.update(document.get("task_dependency_matched_refs") or ())
        reasons.update(document.get("retrieval_reasons") or ())
    if clean_history:
        facts = provider_visible_data(facts)
        metadata = {**metadata, "physical_asset_type": source_type, "provenance": {**dict(metadata.get("provenance") or {}), "writer_projection_version": "accepted-writer-history.v2" if any((item.get("compression_provenance") or {}).get("writer_projection_version") == "accepted-writer-history.v2" for item in documents) else WRITER_PROJECTION_VERSION}}
    return {**metadata, "structured_facts": list({json.dumps(fact, ensure_ascii=False, sort_keys=True): fact for fact in facts}.values()), "safe_summary": "\n\n".join(dict.fromkeys(text for text in summaries if text)), "task_dependency_matched_refs": sorted(refs), "retrieval_reasons": sorted(reasons)}


@dataclass(frozen=True, slots=True)
class _ContextHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = next(
            (item for item in request.inputs if item.asset_type == "chapter_plan"), None
        )
        if plan is None:
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
        frozen_knowledge_access = manifest.get("knowledge_access_policy")
        if frozen_knowledge_access is not None and not isinstance(
            frozen_knowledge_access, dict
        ):
            raise KernelError(
                "CONTEXT_KNOWLEDGE_ACCESS_POLICY_INVALID",
                "Production Input Manifest Knowledge access policy is malformed",
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
        frozen_boundaries = {
            json.dumps(
                dict(item.get("accepted_boundary") or {}),
                sort_keys=True,
                separators=(",", ":"),
            )
            for item in request.command.get("context_candidates", [])
            if dict(item.get("accepted_boundary") or {})
        }
        if len(frozen_boundaries) != 1:
            raise KernelError(
                "CONTEXT_ACCEPTED_BOUNDARY_UNRESOLVED",
                "Context requires one frozen accepted boundary for every candidate",
            )
        governed_boundary = json.loads(next(iter(frozen_boundaries)))
        retrieval_boundary = dict(retrieval.content.get("accepted_boundary") or {})
        equivalent_boundary = {
            "accepted_through_chapter": retrieval_boundary.get(
                "accepted_through_chapter"
            ),
            "story_state_snapshot_version": retrieval_boundary.get(
                "story_state_asset_version_id", ""
            ),
            "canon_snapshot_version": retrieval_boundary.get(
                "canon_snapshot_asset_version_id", ""
            ),
        }
        if governed_boundary != equivalent_boundary:
            raise KernelError(
                "CONTEXT_ACCEPTED_BOUNDARY_MISMATCH",
                "Retrieval and governed Context use different accepted boundaries",
            )
        campaign_result = retrieval.content.get("retrieval_campaign")
        if not isinstance(campaign_result, dict):
            raise KernelError(
                "CONTEXT_RETRIEVAL_CAMPAIGN_MISSING",
                "Context requires deterministic Retrieval Campaign evidence",
            )
        coverage = campaign_result.get("coverage")
        if not isinstance(coverage, dict) or coverage.get("sufficient") is not True:
            missing = (
                dict(coverage.get("missing") or {})
                if isinstance(coverage, dict)
                else {"campaign_evidence": ["coverage"]}
            )
            raise KernelError(
                "CONTEXT_RETRIEVAL_INSUFFICIENT",
                "Context cannot admit evidence until deterministic coverage is "
                f"sufficient; missing={json.dumps(missing, sort_keys=True)}",
            )
        task_scoped_context = str(((request.command.get("preparation_report") or {}).get("stage_context_profile_versions") or {}).get("draft")) == "draft-context-profile-v4"
        task_dependency_refs = sorted(set((retrieval.content.get("query_plan") or {}).get("task_dependency_discovery", {}).get("required_refs") or ()))
        selected_documents: dict[str, list[dict[str, Any]]] = {}
        for document in retrieval.content.get("selected_documents") or ():
            if isinstance(document, dict):
                selected_documents.setdefault(
                    str(document.get("source_asset_version_id") or ""), []
                ).append(dict(document))
        for source_id, documents in selected_documents.items():
            if source_id in candidate_metadata:
                if task_scoped_context:
                    candidate_metadata[source_id] = merge_task_retrieval_projections(candidate_metadata[source_id], documents)
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
                "book_id": str(request.command.get("book_id") or ""),
                "accepted_boundary": dict(governed_boundary),
                "estimated_tokens": max(
                    1, int(best.get("output_characters") or 0) // 4
                ),
                "safe_summary": str(best.get("safe_summary") or ""),
                "structured_facts": [
                    dict(item)
                    for item in dict(best.get("metadata") or {}).get(
                        "structured_facts", ()
                    )
                    if isinstance(item, dict)
                ],
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
        if task_scoped_context:
            for source_id, documents in selected_documents.items():
                candidate_metadata[source_id] = merge_task_retrieval_projections(candidate_metadata[source_id], documents)
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
            if str(metadata.get("asset_type") or "") in {"narrative_retrieval_document", "story_state_snapshot", "canon_snapshot"}:
                from .provider_views import build_task_narrative_projection, project_retrieved_state_context
                projection = build_task_narrative_projection(plan.content, task_scoped=task_scoped_context)
                if task_scoped_context:
                    projection["required_event_refs"] = sorted(set(projection.get("required_event_refs") or ()) | set(task_dependency_refs) | set(metadata.get("task_dependency_matched_refs") or ()))
                facts = list(item.content.get("structured_facts") or ())
                if task_scoped_context:
                    facts = list({json.dumps(fact, ensure_ascii=False, sort_keys=True): fact for fact in [*facts, *(metadata.get("structured_facts") or ())]}.values())
                metadata = project_retrieved_state_context({**metadata, "structured_facts": facts or metadata.get("structured_facts") or []}, projection=projection, chapter=int(plan.content["chapter"]))
                source_content = metadata
            else:
                source_content = item.content
            governed_candidates.append(
                {
                    **metadata,
                    "asset_type": str(metadata.get("asset_type") or item.asset_type),
                    "physical_asset_type": item.asset_type,
                    "content_digest": item.content_hash,
                    "safe_summary": str(
                        source_content.get("safe_summary")
                        or metadata.get("safe_summary")
                        or ""
                    ),
                    "structured_facts": list(
                        source_content.get("structured_facts")
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
            "character_cast",
            "reader_promise",
            "quality_rubric",
            "platform_profile",
        }
        # WHY: These inputs are not prose-generation context, but once Preparation
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
        def context_model_call(stage: str, task: dict[str, Any]) -> dict[str, Any]:
            frozen = replace(request, command={
                **request.command, "_context_compression_task": task,
                "_effect_instance": _content_hash({"stage": stage, "task": task}),
            })
            result = self.provider.invoke(frozen, stage=stage, payload={
                "chapter_plan": plan.content, "context_compression_task": task,
            })
            return {**result.output, "_execution_evidence": dict(result.execution_evidence or {})}

        routes = getattr(getattr(self.provider, "adapter", None), "routes", {})
        compression_routes = [routes.get(stage) for stage in ("context_compress", "context_fidelity")]
        compression_allocation = min((int(getattr(route, "model_context_limit", 0)) // 4 for route in compression_routes), default=0)
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
            context_profile_version=str(((request.command.get("preparation_report") or {}).get("stage_context_profile_versions") or {}).get("draft") or "draft-context-profile-v2"),
            context_model_call=context_model_call,
            compression_input_tokens=compression_allocation,
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
            knowledge_access_policy=(
                dict(frozen_knowledge_access)
                if isinstance(frozen_knowledge_access, dict)
                else None
            ),
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
        from .author_draft import adopted_author_draft
        authored = adopted_author_draft(request)
        if authored is not None:
            return authored
        plan = request.require_input("chapter_plan")
        intent = request.require_input("chapter_execution_intent")
        memo = request.require_input("chapter_memo")
        context = request.require_input("context_bundle")
        from .realization_composition import compile_realization_contract
        from .craft_execution import require_craft_delivery
        require_craft_delivery(plan=plan.content, intent=intent.content, memo=memo.content, context=context.content)
        realization_contract = compile_realization_contract(plan.content, build_draft_style_view(context.content))
        if not realization_contract["slots"]:
            raise KernelError("REALIZATION_PLAN_UNBOUND", "model Draft requires frozen Scene slots")
        generated = self.provider.invoke(
            request,
            stage="draft",
            payload={
                "plan": build_draft_plan_view(plan.content),
                "style": build_draft_style_view(context.content),
                "realization_contract": realization_contract,
                "execution_intent": intent.content,
                "chapter_memo": memo.content,
            },
        )
        content = normalize_draft_result(
                plan=plan.content,
                context_asset_version_id=context.asset_version_id,
                context_content_hash=context.content_hash,
                context_content=context.content,
                result=generated.output,
                provider_evidence=_provider_evidence(generated),
            )
        content["creative_execution"] = {
            "memo_asset_version_id": memo.asset_version_id,
            "memo_content_hash": memo.content_hash,
            "memo_fingerprint": memo.content.get("memo_fingerprint"),
            "intent_asset_version_id": intent.asset_version_id,
            "guidance": dict(memo.content.get("creative_guidance") or {}),
            "scene_directives": list(memo.content.get("scene_directives") or []),
            "authority": "CREATIVE_SUGGESTION_ONLY",
        }
        author_guidance = build_draft_plan_view(plan.content).get("author_design_guidance")
        if author_guidance:
            content["author_design_guidance"] = author_guidance
        return _model_output(ChapterNode.DRAFT, content, request=request, generated=generated)


@dataclass(frozen=True, slots=True)
class _ReviewHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        from .review_window import prepare_native_review, require_review_frontier
        draft, context, targets, window, payload = prepare_native_review(request, stage="review")
        reviewed = self.provider.invoke(
            request,
            stage="review",
            payload=payload,
        )
        require_review_frontier(request)
        return _model_output(
            ChapterNode.REVIEW,
            normalize_review_result(
                draft=draft.content,
                draft_asset_version_id=draft.asset_version_id,
                result=reviewed.output,
                provider_evidence=_provider_evidence(reviewed),
                project_id=request.project_id,
                context_bundle_version_id=context.asset_version_id,
                knowledge_targets=targets,
                cross_chapter_window=window,
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
            from novel_forge.modules.revision.domain import quality_edit_contract
            edit_contract = quality_edit_contract(revision=revision.content, revision_asset_version_id=revision.asset_version_id,
                                                  revision_tasks=tuple(item.content for item in quality_tasks))
            revised = self.provider.invoke(
                request,
                stage="revision",
                payload={
                    **({"quality_edit_contract": edit_contract} if edit_contract is not None else {}),
                    "draft": revision.content,
                    "review": dict(revision.content.get("selected_review") or {}),
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
        incumbent = next((item for item in request.inputs if item.asset_type == "best_draft_candidate"), None)
        if incumbent is not None:
            from dataclasses import replace
            from .candidate_selection import retained_candidate_evidence
            retained = retained_candidate_evidence(incumbent.asset_version_id, incumbent.content)
            draft = replace(draft, asset_version_id=retained.asset_version_id, content=incumbent.content)
            review = replace(review, asset_version_id=retained.review_asset_version_id, content=dict(incumbent.content["selected_review"]))
        from .review_window import prepare_native_review, require_review_frontier
        revision, context, targets, _, payload = prepare_native_review(request, stage="rereview")
        reviewed = self.provider.invoke(
            request,
            stage="rereview",
            payload=payload,
        )
        require_review_frontier(request)
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
                knowledge_targets=targets,
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
        from .candidate_selection import bind_selected_review, retained_candidate_evidence
        from novel_forge.modules.review.diagnostics import require_review_score
        if existing_best is None:
            previous_asset = request.require_input("draft_chapter")
            previous_review = request.require_input("review_report")
            previous_source_id = previous_asset.asset_version_id
            previous_score = require_review_score(previous_review.content)
            previous_blockers = _blocking_issue_codes(previous_review.content)
            previous_review_id = previous_review.asset_version_id
            bind_selected_review(candidate=previous_asset.content, candidate_id=previous_source_id,
                                 review=previous_review.content, review_id=previous_review_id)
        else:
            previous_asset = existing_best
            incumbent = retained_candidate_evidence(existing_best.asset_version_id, existing_best.content)
            previous_source_id = incumbent.asset_version_id
            previous_score, previous_blockers = incumbent.score, incumbent.blocker_codes
            previous_review_id = incumbent.review_asset_version_id
        bind_selected_review(candidate=revision.content, candidate_id=revision.asset_version_id,
                             review=rereview.content, review_id=rereview.asset_version_id)
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
                asset_version_id=previous_source_id,
                workspace_asset_version_id=previous_asset.asset_version_id,
                content=previous_asset.content,
                score=previous_score,
                blocker_codes=tuple(previous_blockers),
                review_asset_version_id=previous_review_id,
            ),
            challenger=CandidateEvidence(
                asset_version_id=revision.asset_version_id,
                content=revision.content,
                score=require_review_score(rereview.content),
                blocker_codes=tuple(sorted(set(_blocking_issue_codes(rereview.content)) | {
                    check["observation"] for check in rereview.content.get("quality_resolution_checks", [])
                    if check["status"] != "SATISFIED" or check["preservation"] != "PRESERVED"})),
                review_asset_version_id=rereview.asset_version_id,
                diagnostic_contract_version=str(rereview.content.get("diagnostic_contract_version") or ""),
                resolution_checks=tuple(rereview.content.get("resolution_checks") or []),
                cross_chapter_review=bool(rereview.content.get("cross_chapter_window")),
                preservation_checks=tuple(rereview.content.get("preservation_checks") or []),
                quality_resolution_checks=tuple(rereview.content.get("quality_resolution_checks") or []),
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
                previous_source_id: previous_asset.content,
                revision.asset_version_id: revision.content,
            },
        )
        if comparison["selected_asset_version_id"] == revision.asset_version_id:
            selected_review_content, selected_review_id = rereview.content, rereview.asset_version_id
        elif existing_best is None:
            selected_review_content, selected_review_id = previous_review.content, previous_review.asset_version_id
        else:
            selected_review_content = dict(existing_best.content["selected_review"])
            selected_review_id = str(selected_review_content["selection_review_source_asset_version_id"])
        selected_source_id = str(best.get("selected_source_asset_version_id") or "")
        selected_review = bind_selected_review(candidate=best, candidate_id=selected_source_id,
                                              review=selected_review_content, review_id=selected_review_id)
        best["selected_review"] = selected_review
        return ChapterHandlerOutput(
            asset_type=ChapterNode.BEST_CANDIDATE.asset_type,
            output_key=ChapterNode.BEST_CANDIDATE.output_key,
            role="primary",
            content=best,
            auxiliary_outputs=(
                ChapterAuxiliaryOutput(
                    asset_type="re_review_report", output_key="chapter.best_candidate.selected_review",
                    role="selection_evidence", content=selected_review,
                    reference_asset_version_ids=(selected_review_id, selected_source_id),
                ),
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
                "validator": str(
                    content["deterministic_validation"].get("contract_version")
                    or "deterministic-continuity-v3"
                ),
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
        from novel_forge.modules.canon_graph.grounding import extract_grounded_candidates
        extractor = extract_grounded_candidates if generated is not None else build_canon_extraction
        content = extractor(
            revision=revision.content,
            revision_asset_version_id=revision.asset_version_id,
            project_id=request.project_id,
            context_bundle_version_id=context.asset_version_id,
            provider_extraction=provider_extraction,
        )
        from novel_forge.modules.canon_graph.background import attach_background_proposals
        content = attach_background_proposals(
            extraction=content,
            binding=dict((context.content.get("chapter_execution_expectations") or {}).get("world_preparation") or {}),
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
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        extraction = request.require_input("canon_extraction")
        proposal = build_canon_change_proposal(
            project_id=request.project_id,
            extraction=extraction.content,
            extraction_asset_version_id=extraction.asset_version_id,
        )
        generated = None
        if extraction.content.get("grounding"):
            from novel_forge.modules.canon_graph.grounding import grounded_claims, validate_support_review
            revision = request.require_input("best_draft_candidate")
            generated = self.provider.invoke(request, stage="canon_support", payload={
                "revision": revision.content, "grounding": extraction.content["grounding"],
                "claims": grounded_claims(extraction.content),
            })
            if request.command.get("chapter_sampling"):
                from novel_forge.modules.chapter_quality_authority.canon_support_reference import validate_sample_result
                validate_sample_result(extraction.content, revision.content, revision.asset_version_id, generated.output)
                return replace(_model_output(ChapterNode.CANON_PROPOSAL, dict(generated.output),
                    request=request, generated=generated), asset_type="canon_support_review")
            proposal["grounding"] = validate_support_review(
                extraction=extraction.content, revision=revision.content,
                revision_asset_version_id=revision.asset_version_id, result=generated.output,
            )
        generation = int(request.command.get("canon_reextraction_generation") or 1)
        proposal["generation"] = generation
        proposal["supersedes_asset_version_id"] = str(
            request.command.get("supersedes_proposal_asset_version_id") or ""
        )
        if generated is not None:
            return _model_output(ChapterNode.CANON_PROPOSAL, proposal, request=request, generated=generated)
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
        reference_calibration = None
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
            from novel_forge.modules.chapter_quality_authority.reference_sampling import admitted_reference_calibration
            reference_calibration = admitted_reference_calibration(request, generated,
                stage=f"quality_{self.group}", target_asset_version_id=revision.asset_version_id)
            provider_entries = []
            schema_ref = str((generated.capability_evidence or {}).get("output_schema_ref") or "")
            current_quality_contract = schema_ref.startswith(f"schema:chapter-provider-output:quality_{self.group}:v3")
            for item in generated.output.get("dimensions", []):
                located = list(item.get("evidence_locations") or [])
                if current_quality_contract:
                    located = bind_quality_prose_evidence(
                        located, text=str(revision.content.get("text") or ""),
                        target_asset_version_id=revision.asset_version_id,
                    )
                    if item.get("gate_status") in {"PASSED", "FAILED"} and not located:
                        raise KernelError(
                            "QUALITY_EVIDENCE_LOCATION_MISSING",
                            "a decisive model Quality status requires located candidate prose",
                        )
                provider_entries.append(
                    {
                        **dict(item),
                        "evidence_locations": located,
                        "target_asset_version_id": revision.asset_version_id,
                        "calibration_status": "REFERENCE_CALIBRATED" if reference_calibration else "PROVIDER_UNCALIBRATED",
                        "provider_verified": True, "human_verified": False,
                        # WHY: Scripted Provider output is useful only for exercising
                        # the internal protocol.  Quality Authority will turn a
                        # passing result into an explicit fixture waiver only
                        # when a separately persisted scoped approval exists.
                        "fixture_protocol_only": not generated.real_model_call,
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
            fixture=fixture, reference_calibration=reference_calibration,
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
        from novel_forge.modules.revision.domain import freeze_quality_edit_scope
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
                        **({"contract_version": "governed-revision-task-v2", "bounded_edit_scope": freeze_quality_edit_scope(revision=revision.content,
                            revision_asset_version_id=revision.asset_version_id, quality=content, action=action)}
                           if (review.content.get("cross_chapter_window") or {}).get("contract_version") == "cross-chapter-review-window.v2" or review.content.get("craft_targets") else {}),
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
                and record.get("context_bundle_asset_version_id") == context.asset_version_id
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
                "context_bundle_asset_version_id": str(content.get("context_bundle_asset_version_id") or ""),
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


def _content_hash(value: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )


def _external_effect_id(evidence: dict[str, Any]) -> str:
    pending: list[Any] = [evidence]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            identity = str(current.get("external_effect_id") or "")
            if identity:
                return identity
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return ""


def _provider_latency_ms(evidence: dict[str, Any]) -> int:
    pending: list[Any] = [evidence]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key in ("latency_ms", "duration_ms", "elapsed_ms"):
                if current.get(key) is not None:
                    return max(0, int(current[key]))
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return 0


def _provider_usage(evidence: dict[str, Any]) -> dict[str, Any]:
    usage = dict(evidence.get("usage") or {})
    cost = dict(evidence.get("cost") or {})
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cost_amount": str(cost.get("amount") or "0"),
        "currency": str(cost.get("currency") or "USD"),
        "latency_ms": _provider_latency_ms(evidence),
    }


def _campaign_usage(rounds: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    currencies = {str(item["usage"].get("currency") or "USD") for item in rounds}
    if len(currencies) > 1:
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_CURRENCY_MISMATCH",
            "retrieval campaign usage cannot combine different currencies",
        )
    input_tokens = sum(int(item["usage"].get("input_tokens") or 0) for item in rounds)
    output_tokens = sum(int(item["usage"].get("output_tokens") or 0) for item in rounds)
    amount = sum(
        (Decimal(str(item["usage"].get("cost_amount") or "0")) for item in rounds),
        Decimal("0"),
    )
    return {
        "provider_calls": sum(
            bool(item.get("external_effect_id") or item.get("provider_evidence"))
            for item in rounds
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model_tokens": input_tokens + output_tokens,
        "cost_amount": format(amount, "f"),
        "currency": next(iter(currencies), "USD"),
        "latency_ms": sum(int(item["usage"].get("latency_ms") or 0) for item in rounds),
        "candidate_count": sum(len(item["documents"]) for item in rounds),
    }


def _campaign_semantic_status(
    rounds: tuple[dict[str, Any], ...],
    additional: dict[str, Any] | None = None,
) -> dict[str, Any]:
    statuses = [dict(item["semantic_status"]) for item in rounds]
    if additional is not None:
        statuses.append(dict(additional))
    base = dict(statuses[0]) if statuses else {}
    base.update(
        {
            "campaign_round_count": len(statuses),
            "agentic_expansion_used": len(statuses) > 1,
            "candidate_document_count": sum(
                int(item.get("candidate_document_count") or 0) for item in statuses
            ),
            "semantic_candidate_expansion": False,
        }
    )
    return base


def build_chapter_handler_registry(
    provider: ChapterModelPort,
) -> ChapterHandlerRegistry:
    routes = getattr(getattr(provider, "adapter", None), "routes", {})
    semantic_provider_bound = isinstance(routes, dict) and "retrieval" in routes
    expansion_provider_bound = (
        bool(getattr(provider, "external_effect_backed", False))
        and isinstance(routes, dict)
        and "retrieval_query_expansion" in routes
    )
    registry = ChapterHandlerRegistry(
        model_effects_required=bool(getattr(provider, "external_effect_backed", False)),
        semantic_retrieval_available=semantic_provider_bound,
        agentic_retrieval_available=expansion_provider_bound,
    )
    registry.register(ChapterNode.PLAN, _PlanHandler())
    registry.register(ChapterNode.EXECUTION_INTENT, _ExecutionIntentHandler())
    registry.register(ChapterNode.MEMO, _MemoHandler(provider))
    registry.register(
        ChapterNode.RETRIEVAL,
        _RetrievalHandler(
            provider,
            semantic_provider_bound,
            expansion_provider_bound,
        ),
    )
    registry.register(ChapterNode.CONTEXT, _ContextHandler(provider))
    registry.register(ChapterNode.DRAFT, _DraftHandler(provider))
    registry.register(ChapterNode.REVIEW, _ReviewHandler(provider))
    registry.register(ChapterNode.REVISION, _RevisionHandler(provider))
    registry.register(ChapterNode.REREVIEW, _ReReviewHandler(provider))
    registry.register(ChapterNode.BEST_CANDIDATE, _BestCandidateHandler())
    registry.register(ChapterNode.CANON_EXTRACTION, _CanonExtractionHandler(provider))
    registry.register(ChapterNode.CANON_PROPOSAL, _CanonProposalHandler(provider))
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
    from novel_forge.modules.review.diagnostics import blocking_diagnosis_codes
    return blocking_diagnosis_codes(review)


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
        "provider_output_schema_ref": str((result.capability_evidence or {}).get("output_schema_ref") or ""),
        **{key: value for key, value in result.output.items() if not isinstance(value, list)},
        **{field: [{**dict(item), **identity} for item in values]
        for field, values in result.output.items()
        if isinstance(values, list)},
    }
