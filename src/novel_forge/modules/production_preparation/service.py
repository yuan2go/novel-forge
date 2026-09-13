from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Protocol

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import (
    compact_canon_facts,
    compact_current_state_facts,
)
from novel_forge.modules.chapter_authority.chapter_plan_views import (
    normalize_authoritative_chapter_plan,
    qualification_profile_for_plan,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_task_narrative_projection,
    project_narrative_state_facts,
)
from novel_forge.modules.mkaos_authority.domain import (
    assert_abstract_content_safe,
    resolve_book_knowledge_access_policy,
    validate_book_knowledge_access_policy,
)

from .contracts import (
    ChapterAuthorityCommand,
    ProductionInputManifest,
    ProductionInputRejection,
    ProductionInputSelection,
    ProductionPreparationDecision,
    ProductionPreparationReport,
    ProductionPreparationRequest,
    ProductionPreparationResult,
    ProductionPreparationRisk,
    ResolvedProductionAsset,
)
from .foundation_context import (
    project_character_foundation_context,
    project_reader_promise_context,
)
from .policies import (
    COLLECTION_ASSET_TYPES,
    CONTEXT_VERSION_REF_KEYS,
    CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
    STAGE_PROFILES,
    requirements_for,
)

_STATE_ASSET_TYPES = {"story_state_snapshot", "canon_snapshot"}


class AssetResolver(Protocol):
    def resolve_latest(
        self, *, project_id: str, asset_type: str
    ) -> ResolvedProductionAsset | None: ...
    def resolve_all(
        self, *, project_id: str, asset_type: str, limit: int = 200
    ) -> tuple[ResolvedProductionAsset, ...]: ...
    def resolve_override(
        self, *, project_id: str, asset_version_id: str
    ) -> ResolvedProductionAsset: ...
    def resolve_active_arc_plan_override(
        self, *, project_id: str, book_id: str, asset_version_id: str
    ) -> ResolvedProductionAsset: ...


class ProductionPreparationService:
    def __init__(self, resolver: AssetResolver) -> None:
        self.resolver = resolver

    def prepare(
        self, request: ProductionPreparationRequest
    ) -> ProductionPreparationResult:
        self._validate(request)
        knowledge_access = self._knowledge_access_policy(request)
        profile = STAGE_PROFILES[request.stage]
        requirements = requirements_for(
            request.stage,
            request.chapter,
            capability_required_asset_types=(request.capability_required_asset_types),
        )
        selected_by_type: dict[str, list[ResolvedProductionAsset]] = {}
        selections: list[ProductionInputSelection] = []
        rejections: list[ProductionInputRejection] = []
        blocked: list[dict[str, str]] = []

        for requirement in requirements:
            candidates = self._candidates(
                request,
                requirement.asset_type,
                knowledge_access=knowledge_access,
            )
            accepted: list[ResolvedProductionAsset] = []
            fit_issues: list[str] = []
            for candidate in candidates:
                knowledge_issue = self._knowledge_access_issue(
                    candidate, knowledge_access=knowledge_access
                )
                if knowledge_issue:
                    rejections.append(
                        ProductionInputRejection(
                            asset_version_id=candidate.asset_version_id,
                            asset_type=candidate.asset_type,
                            code=knowledge_issue,
                            reason=(
                                "candidate is outside the frozen Book Knowledge access policy"
                            ),
                        )
                    )
                    continue
                issue = self._asset_fit_issue(
                    asset_type=requirement.asset_type,
                    asset=candidate,
                    requested_chapter=request.chapter,
                    requested_book_id=request.book_id,
                    stage=request.stage,
                    forbidden_types=profile.forbidden_asset_types,
                )
                if issue:
                    rejections.append(
                        ProductionInputRejection(
                            asset_version_id=candidate.asset_version_id,
                            asset_type=candidate.asset_type,
                            code=issue,
                            reason="candidate violates stage, state, or governance policy",
                        )
                    )
                    fit_issues.append(issue)
                    continue
                scope_issue = self._selection_scope_issue(
                    request=request,
                    asset=candidate,
                    selected_by_type=selected_by_type,
                )
                if scope_issue:
                    rejections.append(
                        ProductionInputRejection(
                            candidate.asset_version_id,
                            candidate.asset_type,
                            scope_issue,
                            "candidate is outside the chapter, stage, entity, or relationship scope",
                        )
                    )
                    continue
                if not self._matches_requested_profile(
                    request, requirement.asset_type, candidate
                ):
                    rejections.append(
                        ProductionInputRejection(
                            candidate.asset_version_id,
                            candidate.asset_type,
                            "PROFILE_ID_MISMATCH",
                            "candidate does not match the requested versioned profile",
                        )
                    )
                    continue
                accepted.append(candidate)
                if requirement.cardinality == "one":
                    break
            if accepted:
                selected_by_type[requirement.asset_type] = accepted
                selections.extend(
                    ProductionInputSelection(
                        asset_version_id=item.asset_version_id,
                        asset_type=item.asset_type,
                        role=requirement.role.value,
                        selection_reason=item.selected_reason,
                        entity_id=str(item.content.get("entity_id") or ""),
                    )
                    for item in accepted
                )
            elif requirement.required and fit_issues:
                blocked.append(
                    {
                        "asset_type": requirement.asset_type,
                        "code": fit_issues[0],
                    }
                )

        knowledge_projection: dict[str, dict[str, Any]] = {}
        plans = selected_by_type.get("chapter_plan") or []
        if plans and (
            "knowledge_translations" in plans[0].content
            or plans[0].content.get("knowledge_translation_policy_version") == "knowledge-grounded-selection-v2"
        ):
            knowledge_projection = self._bind_translated_knowledge(
                request=request, plan=plans[0], selected_by_type=selected_by_type,
                selections=selections, rejections=rejections, blocked=blocked,
                knowledge_access=knowledge_access,
            )

        missing: list[str] = []
        for requirement in requirements:
            if not requirement.required or selected_by_type.get(requirement.asset_type):
                continue
            missing.append(requirement.asset_type)
        selected = [item for values in selected_by_type.values() for item in values]
        risks = self._risks(request, selected)
        approvals = selected_by_type.get("approval_decision", [])
        unmet_risks = tuple(
            risk for risk in risks if not self._risk_approved(risk, approvals, request)
        )
        repair_actions = [self._repair_action(kind) for kind in missing]
        repair_actions.extend(
            "replan the Chapter knowledge translation or restore the approved exact Card: " + item.get("asset_version_id", "")
            for item in blocked if item["asset_type"] == "knowledge_card"
        )
        repair_actions.extend(
            f"obtain {risk.approval_type} for {risk.code}" for risk in unmet_risks
        )
        manifest = self._manifest(
            request=request,
            selected=selected,
            selections=selections,
            rejections=rejections,
            risks=risks,
            unmet_risks=unmet_risks,
        )
        decision = (
            ProductionPreparationDecision.BLOCKED
            if missing or blocked
            else ProductionPreparationDecision.REQUIRES_APPROVAL
            if unmet_risks
            else ProductionPreparationDecision.READY
        )
        report = ProductionPreparationReport(
            project_id=request.project_id,
            chapter=request.chapter,
            decision=decision.value,
            selected_asset_version_ids=tuple(
                item.asset_version_id for item in selected
            ),
            selection_reasons={
                item.asset_version_id: item.selected_reason for item in selected
            },
            missing_required_asset_types=tuple(missing),
            blocked_assets=tuple(blocked),
            approval_requirements=tuple(risk.approval_type for risk in unmet_risks),
            context_digest=manifest.manifest_digest,
            estimated_token_budget=request.context_token_budget,
            estimated_provider_budget=manifest.provider_budget,
            repair_actions=tuple(repair_actions),
            idempotency_key=request.idempotency_key,
            production_input_manifest=asdict(manifest),
            risks=tuple(asdict(item) for item in risks),
            chapter_plan_qualification_profile={},
        )
        if decision is not ProductionPreparationDecision.READY:
            return ProductionPreparationResult(report=report, command=None)

        chapter_plan_asset = selected_by_type["chapter_plan"][0]
        chapter_plan = chapter_plan_asset.content
        plan_profile = qualification_profile_for_plan(chapter_plan)
        try:
            chapter_plan, _ = normalize_authoritative_chapter_plan(
                project_id=request.project_id,
                expected_chapter=request.chapter,
                content=chapter_plan,
                asset_version_id=chapter_plan_asset.asset_version_id,
                content_hash=chapter_plan_asset.content_hash,
                qualification_profile=plan_profile,
            )
        except KernelError as exc:
            if exc.code != "CHAPTER_PLAN_SEMANTIC_FIELDS_MISSING":
                raise
            report = ProductionPreparationReport(
                **{
                    **asdict(report),
                    "decision": ProductionPreparationDecision.BLOCKED.value,
                    "repair_actions": (*report.repair_actions, exc.message),
                    "chapter_plan_qualification_profile": asdict(plan_profile),
                }
            )
            return ProductionPreparationResult(report=report, command=None)
        report = ProductionPreparationReport(
            **{
                **asdict(report),
                "chapter_plan_qualification_profile": asdict(plan_profile),
            }
        )
        title = (
            request.title_override.strip()
            or str(chapter_plan.get("title") or "").strip()
        )
        premise = (
            request.premise_override.strip()
            or str(
                chapter_plan.get("premise") or chapter_plan.get("objective") or ""
            ).strip()
        )
        if not title or not premise:
            report = ProductionPreparationReport(
                **{
                    **asdict(report),
                    "decision": ProductionPreparationDecision.BLOCKED.value,
                    "repair_actions": (
                        *report.repair_actions,
                        "complete chapter plan title and premise",
                    ),
                }
            )
            return ProductionPreparationResult(report=report, command=None)

        version_refs: dict[str, object] = {}
        for kind, values in selected_by_type.items():
            key = CONTEXT_VERSION_REF_KEYS.get(kind, f"{kind}_versions")
            version_refs[key] = (
                values[0].asset_version_id
                if len(values) == 1 and kind not in COLLECTION_ASSET_TYPES
                else [item.asset_version_id for item in values]
            )
        accepted_boundary = {
            "accepted_through_chapter": max(0, request.chapter - 1),
            "story_state_snapshot_version": version_refs.get(
                "story_state_snapshot_version",
                version_refs.get("story_state_snapshot_versions", ""),
            ),
            "canon_snapshot_version": version_refs.get("canon_snapshot_version", ""),
        }
        candidates = tuple(
            self._context_candidate(
                item,
                evidence_only_types=profile.evidence_only_types,
                task_narrative_projection=build_task_narrative_projection(chapter_plan),
                chapter=request.chapter,
                book_id=request.book_id,
                accepted_boundary=accepted_boundary,
                knowledge_projection=knowledge_projection.get(item.asset_version_id),
            )
            for item in selected
        )
        return ProductionPreparationResult(
            report=report,
            command=ChapterAuthorityCommand(
                project_id=request.project_id,
                book_id=request.book_id,
                workspace_id=request.workspace_id,
                chapter=request.chapter,
                chapter_plan_asset_version_id=selected_by_type["chapter_plan"][
                    0
                ].asset_version_id,
                chapter_plan_content_hash=selected_by_type["chapter_plan"][
                    0
                ].content_hash,
                title=title,
                premise=premise,
                context_candidates=candidates,
                context_version_refs=version_refs,
                context_token_budget=request.context_token_budget,
                preparation_report=asdict(report),
                idempotency_key=request.idempotency_key,
            ),
        )

    def _bind_translated_knowledge(
        self, *, request, plan, selected_by_type, selections, rejections, blocked,
        knowledge_access,
    ) -> dict[str, dict[str, Any]]:
        from novel_forge.modules.mkaos_authority.applicability import assess_applicability, prose_applicability_view
        from novel_forge.modules.story_planning_runtime.execution import _required_selection_terms

        adopted: dict[str, dict[str, Any]] = {}
        for translation in plan.content.get("knowledge_translations") or ():
            if translation.get("decision") in {"ADOPT", "ADAPT"}:
                adopted[translation["knowledge_card_asset_version_id"]] = dict(translation)
        existing = {
            item.asset_version_id: item
            for item in selected_by_type.get("knowledge_card") or ()
        }
        for kind in ("knowledge_card", "knowledge_pack"):
            for item in selected_by_type.pop(kind, []):
                if item.asset_version_id not in adopted:
                    rejections.append(ProductionInputRejection(
                        item.asset_version_id, kind, "KNOWLEDGE_NOT_ADOPTED_BY_CHAPTER_PLAN",
                        "Only knowledge explicitly translated into the active Chapter plan may enter this generation Context.",
                    ))
        selections[:] = [item for item in selections if item.asset_type not in {"knowledge_card", "knowledge_pack"}]
        sources = {
            kind: {"content": values[0].content, "asset_version_id": values[0].asset_version_id, "content_hash": values[0].content_hash}
            for kind, values in selected_by_type.items() if values
        }
        if "story_state_snapshot" in sources:
            sources["story_state"] = sources["story_state_snapshot"]
        result: dict[str, dict[str, Any]] = {}
        for identity, translation in adopted.items():
            try:
                item = existing.get(identity) or self.resolver.resolve_override(
                    project_id=request.project_id, asset_version_id=identity,
                )
                issue = self._knowledge_access_issue(item, knowledge_access=knowledge_access)
                issue = issue or self._asset_fit_issue(
                    asset_type="knowledge_card", asset=item,
                    requested_chapter=request.chapter, requested_book_id=request.book_id,
                    stage=request.stage, forbidden_types=STAGE_PROFILES[request.stage].forbidden_asset_types,
                )
                if item.project_id != request.project_id or item.asset_type != "knowledge_card" or item.content_hash != translation["content_hash"]:
                    issue = "KNOWLEDGE_TRANSLATION_VERSION_DRIFT"
                if not issue and hasattr(self.resolver, "require_current_knowledge"):
                    self.resolver.require_current_knowledge(
                        project_id=request.project_id, book_id=request.book_id,
                        asset_version_id=identity, content_hash=translation["content_hash"],
                        knowledge_access_policy=knowledge_access,
                    )
                assessment = assess_applicability(
                    item.content["abstract_content"], sources=sources,
                    hard_constraints=_required_selection_terms([plan.content], {"hard_constraints", "forbidden_events", "prohibited_outcomes"}),
                )
                if not issue and assessment["status"] == "REJECTED":
                    issue = "KNOWLEDGE_TRANSLATION_APPLICABILITY_CHANGED"
                if (
                    not issue
                    and translation.get("decision") == "ADOPT"
                    and translation.get("usage_role") in {"MECHANISM", "CONSTRAINT"}
                    and assessment["status"] != "APPLICABLE"
                ):
                    issue = "KNOWLEDGE_TRANSLATION_ADOPTION_REQUIRES_REPLAN"
                if issue:
                    blocked.append({
                        "asset_type": "knowledge_card", "asset_version_id": identity,
                        "code": issue, "translation": translation,
                        "chapter_plan_asset_version_id": plan.asset_version_id,
                        "chapter_plan_content_hash": plan.content_hash,
                        "current_applicability_assessment": assessment,
                    })
                    continue
            except KernelError as error:
                blocked.append({"asset_type": "knowledge_card", "asset_version_id": identity, "code": error.code})
                continue
            selected_by_type.setdefault("knowledge_card", []).append(item)
            selections.append(ProductionInputSelection(
                identity, "knowledge_card", "context", "EXACT_ACTIVE_CHAPTER_TRANSLATION",
            ))
            result[identity] = {
                "applicability_assessment": prose_applicability_view(assessment),
                "translation": translation,
                "chapter_plan_asset_version_id": plan.asset_version_id,
                "chapter_plan_content_hash": plan.content_hash,
            }
        return result

    def _candidates(
        self,
        request: ProductionPreparationRequest,
        asset_type: str,
        *,
        knowledge_access: dict[str, Any],
    ) -> tuple[ResolvedProductionAsset, ...]:
        override = request.explicit_asset_version_overrides.get(asset_type)
        if (
            asset_type in {"knowledge_card", "knowledge_pack"}
            and knowledge_access["mode"] == "DENY_ALL"
        ):
            assets: tuple[ResolvedProductionAsset, ...] = ()
        elif (
            asset_type == "knowledge_card"
            and knowledge_access["mode"] == "ALLOW_ONLY"
            and not override
        ):
            assets = tuple(
                self.resolver.resolve_override(
                    project_id=request.project_id,
                    asset_version_id=asset_version_id,
                )
                for asset_version_id in knowledge_access[
                    "allowed_knowledge_card_asset_version_ids"
                ]
            )
        elif (
            asset_type == "knowledge_pack"
            and knowledge_access["mode"] == "ALLOW_ONLY"
            and not override
        ):
            assets = ()
        elif override:
            ids = [override] if isinstance(override, str) else list(override)
            assets = tuple(
                (
                    self.resolver.resolve_active_arc_plan_override(
                        project_id=request.project_id,
                        book_id=request.book_id,
                        asset_version_id=item,
                    )
                    if asset_type == "arc_plan"
                    and hasattr(self.resolver, "resolve_active_arc_plan_override")
                    else self.resolver.resolve_override(
                        project_id=request.project_id, asset_version_id=item
                    )
                )
                for item in ids
            )
        elif (
            request.chapter > 1
            and asset_type in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
            and hasattr(self.resolver, "resolve_accepted_for_boundary")
        ):
            assets = tuple(
                self.resolver.resolve_accepted_for_boundary(
                    project_id=request.project_id,
                    book_id=request.book_id,
                    asset_type=asset_type,
                    accepted_chapter=request.chapter - 1,
                )
            )
        elif hasattr(self.resolver, "resolve_all"):
            assets = tuple(
                self.resolver.resolve_all(
                    project_id=request.project_id, asset_type=asset_type
                )
            )
        else:
            latest = self.resolver.resolve_latest(
                project_id=request.project_id, asset_type=asset_type
            )
            assets = () if latest is None else (latest,)
        for asset in assets:
            if asset.project_id != request.project_id:
                raise KernelError(
                    "PREPARATION_CROSS_PROJECT_INPUT",
                    "production candidate belongs to another project",
                )
            if asset.asset_type != asset_type:
                raise KernelError(
                    "PREPARATION_OVERRIDE_TYPE_MISMATCH",
                    "production override has the wrong asset type",
                )
        return assets

    @staticmethod
    def _knowledge_access_policy(
        request: ProductionPreparationRequest,
    ) -> dict[str, Any]:
        scoped_book_id = request.book_id or f"book:{request.project_id}"
        if request.knowledge_access_policy:
            return validate_book_knowledge_access_policy(
                request.knowledge_access_policy,
                project_id=request.project_id,
                book_id=scoped_book_id,
            )
        return resolve_book_knowledge_access_policy(
            production_profile={},
            project_id=request.project_id,
            book_id=scoped_book_id,
        )

    @staticmethod
    def _knowledge_access_issue(
        asset: ResolvedProductionAsset,
        *,
        knowledge_access: dict[str, Any],
    ) -> str:
        if asset.asset_type not in {"knowledge_card", "knowledge_pack"}:
            return ""
        mode = str(knowledge_access["mode"])
        allowed = set(
            knowledge_access["allowed_knowledge_card_asset_version_ids"]
        )
        if mode == "DENY_ALL":
            return "BOOK_KNOWLEDGE_ACCESS_DENIED"
        if mode == "PROJECT_DEFAULT":
            return ""
        if asset.asset_type == "knowledge_card":
            return (
                ""
                if asset.asset_version_id in allowed
                else "BOOK_KNOWLEDGE_CARD_OUTSIDE_ALLOWLIST"
            )
        items = asset.content.get("items")
        if not isinstance(items, list) or not items:
            return "BOOK_KNOWLEDGE_PACK_LINEAGE_INVALID"
        card_ids = {
            str(item.get("knowledge_card_asset_version_id") or "")
            for item in items
            if isinstance(item, dict)
        }
        if len(card_ids) != len(items) or not card_ids or not card_ids.issubset(allowed):
            return "BOOK_KNOWLEDGE_PACK_OUTSIDE_ALLOWLIST"
        return ""

    @staticmethod
    def _matches_requested_profile(
        request: ProductionPreparationRequest,
        asset_type: str,
        asset: ResolvedProductionAsset,
    ) -> bool:
        requested = (
            request.requested_quality_profile
            if asset_type in {"quality_profile", "quality_rubric"}
            else request.requested_platform_profile
            if asset_type == "platform_profile"
            else "default"
        )
        if requested == "default":
            return True
        identity = str(
            asset.content.get("profile_id")
            or asset.content.get("name")
            or asset.content.get("logical_ref")
            or ""
        )
        return requested in {identity, asset.asset_version_id}

    @staticmethod
    def _context_candidate(
        item: ResolvedProductionAsset,
        *,
        evidence_only_types: tuple[str, ...],
        task_narrative_projection: dict[str, object],
        chapter: int,
        book_id: str,
        accepted_boundary: dict[str, object],
        knowledge_projection: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        declared_scope = dict(item.content.get("scope") or {})
        declared_book_id = str(item.content.get("book_id") or declared_scope.get("book_id") or "")
        if declared_book_id and declared_book_id != book_id:
            raise KernelError(
                "PREPARATION_CROSS_BOOK_INPUT",
                "production Context candidate belongs to another Book",
            )
        evidence_only = item.asset_type in {
            "operator_checklist",
            "approval_decision",
            *evidence_only_types,
        }
        safe_summary = str(item.content.get("safe_summary") or "")
        structured_facts = list(item.content.get("structured_facts") or [])
        if item.asset_type == "story_state_snapshot":
            structured_facts = project_narrative_state_facts(
                compact_current_state_facts(item.content),
                projection=task_narrative_projection,
                chapter=chapter,
            )
            quality_observations = item.content.get(
                "_accepted_quality_observations"
            )
            if quality_observations:
                structured_facts.append(
                    {
                        "key": "accepted_quality_observations",
                        "value": list(quality_observations),
                        "provider_visibility": "INTERNAL_QUALITY_ONLY",
                    }
                )
            safe_summary = (
                "Compact authoritative current Narrative State through Chapter "
                f"{item.content.get('accepted_through_chapter')}."
            )
        elif item.asset_type == "canon_snapshot":
            if item.content.get("contract_version") != "canon-snapshot-v2":
                raise KernelError(
                    "CANON_SNAPSHOT_CONTRACT_UNSUPPORTED",
                    "execution context accepts only Canon snapshot v2",
                )
            structured_facts = project_narrative_state_facts(
                compact_canon_facts(item.content),
                projection=task_narrative_projection,
                chapter=chapter,
            )
            safe_summary = (
                "Compact authoritative Canon truth through Chapter "
                f"{item.content.get('accepted_through_chapter')}."
            )
        elif item.asset_type == "knowledge_card":
            abstract_content = item.content.get("abstract_content")
            if not isinstance(abstract_content, dict):
                raise KernelError(
                    "PREPARATION_KNOWLEDGE_CARD_INVALID",
                    "KnowledgeCard lacks governed abstract content",
                )
            assert_abstract_content_safe(abstract_content)
            projected = {
                key: abstract_content.get(key)
                for key in (
                    "concept_name",
                    "mechanism",
                    "applicability",
                    "failure_conditions",
                    "constraints",
                    "conflict_generators",
                    "review_checks",
                    "semantic_family",
                    "selection_tags",
                    "repetition_key",
                    "applicability_contract",
                    "preconditions",
                    "exceptions",
                    "misuse_risks",
                    "epistemic_status",
                    "source_finding_codes",
                )
                if abstract_content.get(key) not in (None, "", [])
            }
            if knowledge_projection:
                projected.update(knowledge_projection)
            safe_summary = json.dumps(
                projected,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            structured_facts = [
                {
                    "kind": "narrative_intelligence",
                    "knowledge_card_asset_version_id": item.asset_version_id,
                    "semantic_family": str(
                        abstract_content.get("semantic_family") or ""
                    ),
                    "repetition_key": str(
                        abstract_content.get("repetition_key") or ""
                    ),
                }
            ]
        projection: dict[str, object] = {}
        if item.asset_type in {"character_cast", "character_card"}:
            projection = project_character_foundation_context(
                asset_type=item.asset_type,
                content=item.content,
                source_asset_version_id=item.asset_version_id,
            )
        elif item.asset_type == "reader_promise":
            projection = project_reader_promise_context(
                content=item.content,
                source_asset_version_id=item.asset_version_id,
            )
        if projection:
            safe_summary = str(projection["safe_summary"])
            structured_facts = list(projection["structured_facts"])
        knowledge_card_ids: list[str] = []
        if item.asset_type == "knowledge_card":
            knowledge_card_ids = [item.asset_version_id]
        elif item.asset_type == "knowledge_pack":
            knowledge_card_ids = [
                str(entry.get("knowledge_card_asset_version_id") or "")
                for entry in item.content.get("items") or ()
                if isinstance(entry, dict)
            ]
        return {
            "asset_version_id": item.asset_version_id,
            "content_hash": item.content_hash,
            "content_digest": item.content_hash,
            "asset_type": item.asset_type,
            "physical_asset_type": str(
                item.content.get("physical_asset_type") or item.asset_type
            ),
            "project_id": item.project_id,
            "book_id": book_id,
            "accepted_boundary": dict(accepted_boundary),
            "selection_reason": item.selected_reason,
            "safe_summary": safe_summary,
            "structured_facts": structured_facts,
            "narrative_function": str(
                projection.get("narrative_function")
                or item.content.get("narrative_function")
                or item.asset_type
            ),
            "estimated_tokens": int(
                max(
                    1,
                    len(
                        safe_summary
                        + repr(
                            [
                                fact
                                for fact in structured_facts
                                if fact.get("provider_visibility")
                                != "INTERNAL_QUALITY_ONLY"
                            ]
                        )
                    )
                    // 4,
                )
                if item.asset_type in _STATE_ASSET_TYPES or knowledge_projection
                else item.content.get("estimated_tokens")
                or projection.get("estimated_tokens")
                or max(1, len(safe_summary + repr(structured_facts)) // 4)
            ),
            "allowed_use": (
                "evidence_only"
                if evidence_only
                else str(item.content.get("allowed_use") or "generation")
            ),
            # INVARIANT: source governance and model rendering are separate;
            # evidence-only assets freeze into lineage but not rendered expression.
            "source_use_mode": str(item.content.get("source_use_mode") or "generation"),
            "entity_id": str(item.content.get("entity_id") or ""),
            "scope": dict(item.content.get("scope") or {}),
            "context_class": "PROTECTED" if knowledge_projection else str(projection.get("context_class") or "RETRIEVABLE"),
            "compression_method": str(
                "authority_projection" if knowledge_projection else projection.get("compression_method") or "safe_summary"
            ),
            "semantic_projection": bool(
                projection.get("semantic_projection", True)
            ),
            **(
                {
                    "provenance": {
                        "authority": "MKAOS",
                        "knowledge_card_asset_version_ids": knowledge_card_ids,
                        **({"knowledge_card_usages": [{
                            "knowledge_card_asset_version_id": entry["knowledge_card_asset_version_id"],
                            "usage_role": entry["usage_role"],
                        } for entry in item.content.get("items") or ()]}
                           if item.asset_type == "knowledge_pack" else {}),
                    }
                }
                if item.asset_type in {"knowledge_card", "knowledge_pack"}
                else {}
            ),
        }

    @staticmethod
    def _risks(
        request: ProductionPreparationRequest, selected: list[ResolvedProductionAsset]
    ) -> tuple[ProductionPreparationRisk, ...]:
        risks: list[ProductionPreparationRisk] = []
        high_source = tuple(
            item.asset_version_id
            for item in selected
            if int(item.content.get("source_risk", 0)) >= 70
        )
        if high_source:
            risks.append(
                ProductionPreparationRisk(
                    "HIGH_SOURCE_RISK", "high", "source_risk", high_source
                )
            )
        estimated_cost = float(
            request.operator_decision.get("estimated_provider_cost", 0) or 0
        )
        if estimated_cost > 5:
            risks.append(
                ProductionPreparationRisk(
                    "HIGH_PROVIDER_BUDGET", "high", "provider_budget"
                )
            )
        return tuple(risks)

    @staticmethod
    def _risk_approved(
        risk: ProductionPreparationRisk,
        approvals: list[ResolvedProductionAsset],
        request: ProductionPreparationRequest,
    ) -> bool:
        now = datetime.now(timezone.utc)
        for approval in approvals:
            content = approval.content
            expires = str(content.get("expires_at") or "")
            if expires:
                parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed <= now:
                    continue
            if (
                content.get("decision") != "APPROVED"
                or int(content.get("chapter", 0)) != request.chapter
            ):
                continue
            if risk.code not in set(content.get("risk_codes") or []):
                continue
            if not set(risk.target_asset_version_ids).issubset(
                set(content.get("target_asset_version_ids") or [])
            ):
                continue
            return True
        return False

    @staticmethod
    def _manifest(
        *,
        request: ProductionPreparationRequest,
        selected: list[ResolvedProductionAsset],
        selections: list[ProductionInputSelection],
        rejections: list[ProductionInputRejection],
        risks: tuple[ProductionPreparationRisk, ...],
        unmet_risks: tuple[ProductionPreparationRisk, ...],
    ) -> ProductionInputManifest:
        selected_payload = tuple(
            {
                "asset_version_id": item.asset_version_id,
                "asset_type": item.asset_type,
                "physical_asset_type": str(
                    item.content.get("physical_asset_type") or item.asset_type
                ),
                "content_hash": item.content_hash,
                "entity_id": str(item.content.get("entity_id") or ""),
                "role": next(
                    (
                        entry.role
                        for entry in selections
                        if entry.asset_version_id == item.asset_version_id
                    ),
                    "context",
                ),
            }
            for item in selected
        )
        source_rows = [
            {
                "asset_version_id": item.asset_version_id,
                "governance_status": str(
                    item.content.get("governance_status") or "CLEAR"
                ),
                "source_policy_version": str(
                    item.content.get("source_policy_version") or ""
                ),
                "allowed_use": str(item.content.get("allowed_use") or "generation"),
                "raw_source": item.content.get("raw_source") is True,
                "source_risk": int(item.content.get("source_risk") or 0),
            }
            for item in selected
            if any(
                key in item.content
                for key in (
                    "source_policy_version",
                    "source_risk",
                    "raw_source",
                    "allowed_use",
                )
            )
        ]
        raw_count = sum(1 for item in source_rows if item["raw_source"])
        source_governance = {
            "status": "CLEAR"
            if all(
                item["governance_status"] == "CLEAR" and not item["raw_source"]
                for item in source_rows
            )
            else "BLOCKED",
            "raw_source_ratio": (raw_count / len(source_rows)) if source_rows else 0.0,
            "copyright_mode": STAGE_PROFILES[request.stage].copyright_mode,
            "assets": source_rows,
        }
        knowledge_access = ProductionPreparationService._knowledge_access_policy(
            request
        )
        digest_payload = {
            "project_id": request.project_id,
            "book_id": request.book_id,
            "chapter": request.chapter,
            "stage": request.stage,
            "selected": selected_payload,
            "rejected": [asdict(item) for item in rejections],
            "token_budget": request.context_token_budget,
            "quality_profile": request.requested_quality_profile,
            "platform_profile": request.requested_platform_profile,
            "source_governance": source_governance,
            "qualification_evidence": {
                item.asset_version_id: item.qualification for item in selected
            },
            "approval_requirements": [asdict(item) for item in unmet_risks],
            "risk_summary": [asdict(item) for item in risks],
            "knowledge_access_policy": knowledge_access,
        }
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    digest_payload, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        )
        by_type = {item.asset_type: item for item in selected}
        entity_scopes: dict[str, list[str]] = {}
        for item in selected:
            entity_id = str(item.content.get("entity_id") or "")
            if entity_id:
                entity_scopes.setdefault(item.asset_type, []).append(entity_id)

        def version(*types: str) -> str:
            return next(
                (by_type[item].asset_version_id for item in types if item in by_type),
                "",
            )

        return ProductionInputManifest(
            project_id=request.project_id,
            book_id=request.book_id,
            workspace_id=request.workspace_id,
            chapter=request.chapter,
            stage=request.stage,
            quality_profile_version_id=version("quality_profile", "quality_rubric"),
            platform_profile_version_id=version("platform_profile"),
            style_policy_version_id=version("style_policy"),
            chapter_plan_version_id=version("chapter_plan"),
            outline_version_id=version("outline", "outline_version"),
            volume_arc_version_id=version("volume_arc"),
            world_bible_version_id=version("world_bible"),
            canon_snapshot_version_id=version("canon_snapshot"),
            context_profile_version_id=version("context_profile"),
            selected_asset_versions=selected_payload,
            rejected_asset_versions=tuple(asdict(item) for item in rejections),
            entity_scopes=entity_scopes,
            selection_reasons={
                item.asset_version_id: item.selection_reason for item in selections
            },
            rejection_reasons={item.asset_version_id: item.code for item in rejections},
            source_governance=source_governance,
            qualification_evidence={
                item.asset_version_id: item.qualification for item in selected
            },
            token_budget=request.context_token_budget,
            provider_budget={
                "currency": "USD",
                "status": "ESTIMATE_UNCALIBRATED",
                "maximum_tokens": request.context_token_budget,
            },
            approval_requirements=tuple(asdict(item) for item in unmet_risks),
            risk_summary=tuple(asdict(item) for item in risks),
            knowledge_access_policy=knowledge_access,
            manifest_digest=digest,
            created_by_operation_id="pending:chapter-plan-operation",
        )

    @staticmethod
    def _asset_fit_issue(
        *,
        asset_type: str,
        asset: ResolvedProductionAsset,
        requested_chapter: int,
        requested_book_id: str,
        stage: str,
        forbidden_types: tuple[str, ...],
    ) -> str:
        content = asset.content
        if asset_type == "operator_checklist" and content.get("contract_version") == "author-reading-review.v1":
            return "OPERATOR_CHECKLIST_PURPOSE_MISMATCH"
        if asset_type in forbidden_types or content.get("quarantined") is True:
            return "STAGE_ASSET_FORBIDDEN"
        if (
            content.get("raw_source") is True
            or content.get("source_expression_included") is True
        ):
            return "RAW_SOURCE_FORBIDDEN"
        allowed_use = str(content.get("allowed_use") or "generation")
        if stage == "draft" and allowed_use in {
            "review_only",
            "eval_only",
            "structure_only",
        }:
            return "STAGE_USE_FORBIDDEN"
        if asset_type == "chapter_plan":
            try:
                if int(content.get("chapter")) != requested_chapter:
                    return "CHAPTER_PLAN_TARGET_MISMATCH"
            except (TypeError, ValueError):
                return "CHAPTER_PLAN_TARGET_MISSING"
        if asset_type in {"character_cast", "character_card"}:
            try:
                project_character_foundation_context(
                    asset_type=asset_type,
                    content=content,
                    source_asset_version_id=asset.asset_version_id,
                )
            except KernelError as exc:
                return exc.code
        if asset_type == "reader_promise":
            try:
                project_reader_promise_context(
                    content=content,
                    source_asset_version_id=asset.asset_version_id,
                )
            except KernelError as exc:
                return exc.code
        if asset_type in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES:
            expected_contract = (
                "story-state-snapshot-v2"
                if asset_type == "story_state_snapshot"
                else "canon-snapshot-v2"
            )
            if content.get("contract_version") != expected_contract:
                return "NARRATIVE_STATE_CONTRACT_UNSUPPORTED"
            if content.get("_authority_acceptance_bound") is not True:
                return "NARRATIVE_STATE_NOT_ACCEPTANCE_BOUND"
            if not requested_book_id or content.get("book_id") != requested_book_id:
                return "NARRATIVE_STATE_BOOK_SCOPE_MISMATCH"
            try:
                if (
                    int(content.get("accepted_through_chapter"))
                    != requested_chapter - 1
                ):
                    return "HISTORICAL_SNAPSHOT_CHAPTER_MISMATCH"
            except (TypeError, ValueError):
                return "HISTORICAL_SNAPSHOT_CHAPTER_MISSING"
        return ""

    @staticmethod
    def _selection_scope_issue(
        *,
        request: ProductionPreparationRequest,
        asset: ResolvedProductionAsset,
        selected_by_type: dict[str, list[ResolvedProductionAsset]],
    ) -> str:
        scope = dict(asset.content.get("scope") or {})
        stages = {str(item) for item in scope.get("stages", [])}
        if stages and request.stage not in stages:
            return "STAGE_SCOPE_MISMATCH"
        chapter_range = scope.get("chapter_range") or {}
        if isinstance(chapter_range, (list, tuple)) and len(chapter_range) == 2:
            start, end = chapter_range
        elif isinstance(chapter_range, dict):
            start = chapter_range.get("start", scope.get("chapter_start"))
            end = chapter_range.get("end", scope.get("chapter_end"))
        else:
            start, end = scope.get("chapter_start"), scope.get("chapter_end")
        if start is not None and request.chapter < int(start):
            return "CHAPTER_SCOPE_MISMATCH"
        if end is not None and request.chapter > int(end):
            return "CHAPTER_SCOPE_MISMATCH"

        plan_assets = selected_by_type.get("chapter_plan") or []
        if not plan_assets:
            return ""
        plan = plan_assets[0].content
        wanted_entities = {
            str(
                item.get("entity_id")
                or item.get("character_id")
                or item.get("id")
                or item
            )
            for item in (*plan.get("cast", []), *plan.get("character_ids", []))
            if item
        }
        entity_id = str(
            asset.content.get("entity_id") or asset.content.get("character_id") or ""
        )
        if (
            asset.asset_type == "character_card"
            and entity_id
            and wanted_entities
            and entity_id not in wanted_entities
        ):
            return "ENTITY_SCOPE_MISMATCH"
        return ""

    @staticmethod
    def _repair_action(asset_type: str) -> str:
        if asset_type in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES:
            state_name = {
                "canon_snapshot": "Canon snapshot",
                "story_state_snapshot": "StoryState snapshot",
            }[asset_type]
            return (
                "complete and commit the previous chapter through Book Authority "
                f"to produce an accepted {state_name} v2"
            )
        return f"create or re-qualify the required {asset_type} Authority asset"

    @staticmethod
    def _validate(request: ProductionPreparationRequest) -> None:
        if request.stage not in STAGE_PROFILES:
            raise ValueError("unknown production preparation stage")
        if (
            any(
                not item
                for item in (
                    request.project_id,
                    request.workspace_id,
                    request.idempotency_key,
                )
            )
            or request.chapter <= 0
            or request.context_token_budget <= 0
            or (request.chapter > 1 and not request.book_id)
        ):
            raise ValueError("production preparation request is incomplete")
