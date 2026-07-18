from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Protocol

from novel_forge.modules.command_kernel.errors import KernelError

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
from .policies import (
    COLLECTION_ASSET_TYPES,
    CONTEXT_VERSION_REF_KEYS,
    CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
    STAGE_PROFILES,
    requirements_for,
)


class AssetResolver(Protocol):
    def resolve_latest(self, *, project_id: str, asset_type: str) -> ResolvedProductionAsset | None: ...
    def resolve_all(self, *, project_id: str, asset_type: str, limit: int = 200) -> tuple[ResolvedProductionAsset, ...]: ...
    def resolve_override(self, *, project_id: str, asset_version_id: str) -> ResolvedProductionAsset: ...


class ProductionPreparationService:
    def __init__(self, resolver: AssetResolver) -> None:
        self.resolver = resolver

    def prepare(self, request: ProductionPreparationRequest) -> ProductionPreparationResult:
        self._validate(request)
        profile = STAGE_PROFILES[request.stage]
        requirements = requirements_for(request.stage, request.chapter)
        selected_by_type: dict[str, list[ResolvedProductionAsset]] = {}
        selections: list[ProductionInputSelection] = []
        rejections: list[ProductionInputRejection] = []
        blocked: list[dict[str, str]] = []

        for requirement in requirements:
            candidates = self._candidates(request, requirement.asset_type)
            accepted: list[ResolvedProductionAsset] = []
            for candidate in candidates:
                issue = self._asset_fit_issue(
                    asset_type=requirement.asset_type,
                    asset=candidate,
                    requested_chapter=request.chapter,
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
                    if requirement.required:
                        blocked.append({"asset_type": requirement.asset_type, "code": issue})
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
                if not self._matches_requested_profile(request, requirement.asset_type, candidate):
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

        missing: list[str] = []
        declarations = selected_by_type.get("empty_state_declaration", [])
        for requirement in requirements:
            if not requirement.required or selected_by_type.get(requirement.asset_type):
                continue
            declaration = self._empty_state_declaration(declarations, requirement.asset_type, request.chapter)
            if declaration is not None:
                selected_by_type.setdefault(requirement.asset_type, []).append(declaration)
                selections.append(
                    ProductionInputSelection(
                        declaration.asset_version_id,
                        declaration.asset_type,
                        "state",
                        f"explicit empty baseline for {requirement.asset_type}",
                    )
                )
            else:
                missing.append(requirement.asset_type)

        selected = [item for values in selected_by_type.values() for item in values]
        risks = self._risks(request, selected)
        approvals = selected_by_type.get("approval_decision", [])
        unmet_risks = tuple(risk for risk in risks if not self._risk_approved(risk, approvals, request))
        repair_actions = [self._repair_action(kind) for kind in missing]
        repair_actions.extend(f"obtain {risk.approval_type} for {risk.code}" for risk in unmet_risks)
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
            selected_asset_version_ids=tuple(item.asset_version_id for item in selected),
            selection_reasons={item.asset_version_id: item.selected_reason for item in selected},
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
        )
        if decision is not ProductionPreparationDecision.READY:
            return ProductionPreparationResult(report=report, command=None)

        chapter_plan = selected_by_type["chapter_plan"][0].content
        title = request.title_override.strip() or str(chapter_plan.get("title") or "").strip()
        premise = request.premise_override.strip() or str(
            chapter_plan.get("premise") or chapter_plan.get("objective") or ""
        ).strip()
        if not title or not premise:
            report = ProductionPreparationReport(
                **{
                    **asdict(report),
                    "decision": ProductionPreparationDecision.BLOCKED.value,
                    "repair_actions": (*report.repair_actions, "complete chapter plan title and premise"),
                }
            )
            return ProductionPreparationResult(report=report, command=None)

        # Governance and approval assets are frozen with the command as evidence-only
        # Context segments.  This keeps Manifest == frozen inputs == Context lineage
        # without exposing their content to the model-facing rendered view.
        candidates = tuple(
            self._context_candidate(item, evidence_only_types=profile.evidence_only_types)
            for item in selected
        )
        version_refs: dict[str, object] = {}
        for kind, values in selected_by_type.items():
            key = CONTEXT_VERSION_REF_KEYS.get(kind, f"{kind}_versions")
            version_refs[key] = (
                values[0].asset_version_id
                if len(values) == 1 and kind not in COLLECTION_ASSET_TYPES
                else [item.asset_version_id for item in values]
            )
        return ProductionPreparationResult(
            report=report,
            command=ChapterAuthorityCommand(
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                chapter=request.chapter,
                chapter_plan_asset_version_id=selected_by_type["chapter_plan"][0].asset_version_id,
                chapter_plan_content_hash=selected_by_type["chapter_plan"][0].content_hash,
                title=title,
                premise=premise,
                context_candidates=candidates,
                context_version_refs=version_refs,
                context_token_budget=request.context_token_budget,
                preparation_report=asdict(report),
                idempotency_key=request.idempotency_key,
            ),
        )

    def _candidates(self, request: ProductionPreparationRequest, asset_type: str) -> tuple[ResolvedProductionAsset, ...]:
        override = request.explicit_asset_version_overrides.get(asset_type)
        if override:
            ids = [override] if isinstance(override, str) else list(override)
            assets = tuple(
                self.resolver.resolve_override(project_id=request.project_id, asset_version_id=item)
                for item in ids
            )
        elif hasattr(self.resolver, "resolve_all"):
            assets = tuple(self.resolver.resolve_all(project_id=request.project_id, asset_type=asset_type))
        else:
            latest = self.resolver.resolve_latest(project_id=request.project_id, asset_type=asset_type)
            assets = () if latest is None else (latest,)
        for asset in assets:
            if asset.project_id != request.project_id:
                raise KernelError("PREPARATION_CROSS_PROJECT_INPUT", "production candidate belongs to another project")
            if asset.asset_type != asset_type:
                raise KernelError("PREPARATION_OVERRIDE_TYPE_MISMATCH", "production override has the wrong asset type")
        return assets

    @staticmethod
    def _matches_requested_profile(request: ProductionPreparationRequest, asset_type: str, asset: ResolvedProductionAsset) -> bool:
        requested = (
            request.requested_quality_profile if asset_type in {"quality_profile", "quality_rubric"}
            else request.requested_platform_profile if asset_type == "platform_profile"
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
    ) -> dict[str, object]:
        evidence_only = item.asset_type in {
            "operator_checklist", "approval_decision", *evidence_only_types,
        }
        return {
            "asset_version_id": item.asset_version_id,
            "content_hash": item.content_hash,
            "asset_type": item.asset_type,
            "project_id": item.project_id,
            "selection_reason": item.selected_reason,
            "safe_summary": str(item.content.get("safe_summary") or ""),
            "structured_facts": list(item.content.get("structured_facts") or []),
            "narrative_function": str(item.content.get("narrative_function") or item.asset_type),
            "estimated_tokens": int(item.content.get("estimated_tokens") or max(1, len(str(item.content.get("safe_summary") or "")) // 4)),
            "allowed_use": (
                "evidence_only"
                if evidence_only
                else str(item.content.get("allowed_use") or "generation")
            ),
            # Source governance use mode and model rendering use are separate.
            # Evidence-only project assets are eligible to be frozen/segmented,
            # while the Context View renderer still excludes their expression.
            "source_use_mode": str(item.content.get("source_use_mode") or "generation"),
            "entity_id": str(item.content.get("entity_id") or ""),
            "scope": dict(item.content.get("scope") or {}),
        }

    @staticmethod
    def _empty_state_declaration(declarations: list[ResolvedProductionAsset], state_kind: str, chapter: int) -> ResolvedProductionAsset | None:
        for declaration in declarations:
            content = declaration.content
            if content.get("state_kind") == state_kind and int(content.get("chapter", 0)) == chapter - 1 and content.get("declared_empty") is True:
                return declaration
        return None

    @staticmethod
    def _risks(request: ProductionPreparationRequest, selected: list[ResolvedProductionAsset]) -> tuple[ProductionPreparationRisk, ...]:
        risks: list[ProductionPreparationRisk] = []
        high_source = tuple(item.asset_version_id for item in selected if int(item.content.get("source_risk", 0)) >= 70)
        if high_source:
            risks.append(ProductionPreparationRisk("HIGH_SOURCE_RISK", "high", "source_risk", high_source))
        estimated_cost = float(request.operator_decision.get("estimated_provider_cost", 0) or 0)
        if estimated_cost > 5:
            risks.append(ProductionPreparationRisk("HIGH_PROVIDER_BUDGET", "high", "provider_budget"))
        return tuple(risks)

    @staticmethod
    def _risk_approved(risk: ProductionPreparationRisk, approvals: list[ResolvedProductionAsset], request: ProductionPreparationRequest) -> bool:
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
            if content.get("decision") != "APPROVED" or int(content.get("chapter", 0)) != request.chapter:
                continue
            if risk.code not in set(content.get("risk_codes") or []):
                continue
            if not set(risk.target_asset_version_ids).issubset(set(content.get("target_asset_version_ids") or [])):
                continue
            return True
        return False

    @staticmethod
    def _manifest(*, request: ProductionPreparationRequest, selected: list[ResolvedProductionAsset], selections: list[ProductionInputSelection], rejections: list[ProductionInputRejection], risks: tuple[ProductionPreparationRisk, ...], unmet_risks: tuple[ProductionPreparationRisk, ...]) -> ProductionInputManifest:
        selected_payload = tuple(
            {
                "asset_version_id": item.asset_version_id,
                "asset_type": item.asset_type,
                "content_hash": item.content_hash,
                "entity_id": str(item.content.get("entity_id") or ""),
                "role": next((entry.role for entry in selections if entry.asset_version_id == item.asset_version_id), "context"),
            }
            for item in selected
        )
        source_rows = [
            {
                "asset_version_id": item.asset_version_id,
                "governance_status": str(item.content.get("governance_status") or "CLEAR"),
                "source_policy_version": str(item.content.get("source_policy_version") or ""),
                "allowed_use": str(item.content.get("allowed_use") or "generation"),
                "raw_source": item.content.get("raw_source") is True,
                "source_risk": int(item.content.get("source_risk") or 0),
            }
            for item in selected
            if any(key in item.content for key in ("source_policy_version", "source_risk", "raw_source", "allowed_use"))
        ]
        raw_count = sum(1 for item in source_rows if item["raw_source"])
        source_governance = {
            "status": "CLEAR" if all(item["governance_status"] == "CLEAR" and not item["raw_source"] for item in source_rows) else "BLOCKED",
            "raw_source_ratio": (raw_count / len(source_rows)) if source_rows else 0.0,
            "copyright_mode": STAGE_PROFILES[request.stage].copyright_mode,
            "assets": source_rows,
        }
        digest_payload = {
            "project_id": request.project_id,
            "chapter": request.chapter,
            "stage": request.stage,
            "selected": selected_payload,
            "rejected": [asdict(item) for item in rejections],
            "token_budget": request.context_token_budget,
            "quality_profile": request.requested_quality_profile,
            "platform_profile": request.requested_platform_profile,
            "source_governance": source_governance,
            "qualification_evidence": {item.asset_version_id: item.qualification for item in selected},
            "approval_requirements": [asdict(item) for item in unmet_risks],
            "risk_summary": [asdict(item) for item in risks],
        }
        digest = "sha256:" + hashlib.sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        by_type = {item.asset_type: item for item in selected}
        entity_scopes: dict[str, list[str]] = {}
        for item in selected:
            entity_id = str(item.content.get("entity_id") or "")
            if entity_id:
                entity_scopes.setdefault(item.asset_type, []).append(entity_id)
        def version(*types: str) -> str:
            return next((by_type[item].asset_version_id for item in types if item in by_type), "")
        return ProductionInputManifest(
            project_id=request.project_id,
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
            timeline_snapshot_version_id=version("timeline_snapshot"),
            context_profile_version_id=version("context_profile"),
            selected_asset_versions=selected_payload,
            rejected_asset_versions=tuple(asdict(item) for item in rejections),
            entity_scopes=entity_scopes,
            selection_reasons={item.asset_version_id: item.selection_reason for item in selections},
            rejection_reasons={item.asset_version_id: item.code for item in rejections},
            source_governance=source_governance,
            qualification_evidence={item.asset_version_id: item.qualification for item in selected},
            token_budget=request.context_token_budget,
            provider_budget={"currency": "USD", "status": "ESTIMATE_UNCALIBRATED", "maximum_tokens": request.context_token_budget},
            approval_requirements=tuple(asdict(item) for item in unmet_risks),
            risk_summary=tuple(asdict(item) for item in risks),
            manifest_digest=digest,
            created_by_operation_id="pending:chapter-plan-operation",
        )

    @staticmethod
    def _asset_fit_issue(*, asset_type: str, asset: ResolvedProductionAsset, requested_chapter: int, stage: str, forbidden_types: tuple[str, ...]) -> str:
        content = asset.content
        if asset_type in forbidden_types or content.get("quarantined") is True:
            return "STAGE_ASSET_FORBIDDEN"
        if content.get("raw_source") is True or content.get("source_expression_included") is True:
            return "RAW_SOURCE_FORBIDDEN"
        allowed_use = str(content.get("allowed_use") or "generation")
        if stage == "draft" and allowed_use in {"review_only", "eval_only", "structure_only"}:
            return "STAGE_USE_FORBIDDEN"
        if asset_type == "chapter_plan":
            try:
                if int(content.get("chapter")) != requested_chapter:
                    return "CHAPTER_PLAN_TARGET_MISMATCH"
            except (TypeError, ValueError):
                return "CHAPTER_PLAN_TARGET_MISSING"
        if asset_type in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES:
            try:
                if int(content.get("chapter")) != requested_chapter - 1:
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
            str(item.get("entity_id") or item.get("character_id") or item.get("id") or item)
            for item in (*plan.get("cast", []), *plan.get("character_ids", []))
            if item
        }
        entity_id = str(asset.content.get("entity_id") or asset.content.get("character_id") or "")
        if asset.asset_type in {"character_card", "character_state_snapshot"} and entity_id and wanted_entities and entity_id not in wanted_entities:
            return "ENTITY_SCOPE_MISMATCH"
        wanted_pairs = {
            tuple(sorted(str(value) for value in item))
            for item in plan.get("relationship_pairs", [])
            if isinstance(item, (list, tuple)) and len(item) == 2
        }
        pair = asset.content.get("relationship_pair") or scope.get("relationship_pair")
        if asset.asset_type == "relationship_state_snapshot" and wanted_pairs and isinstance(pair, (list, tuple)) and len(pair) == 2 and tuple(sorted(str(value) for value in pair)) not in wanted_pairs:
            return "RELATIONSHIP_SCOPE_MISMATCH"
        return ""

    @staticmethod
    def _repair_action(asset_type: str) -> str:
        if asset_type == "canon_snapshot":
            return "produce a qualified previous-chapter Canon snapshot or explicit EmptyStateDeclaration"
        if asset_type in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES:
            return f"produce a qualified previous-chapter {asset_type} or explicit EmptyStateDeclaration"
        return f"create or re-qualify the required {asset_type} Authority asset"

    @staticmethod
    def _validate(request: ProductionPreparationRequest) -> None:
        if request.stage not in STAGE_PROFILES:
            raise ValueError("unknown production preparation stage")
        if any(not item for item in (request.project_id, request.workspace_id, request.idempotency_key)) or request.chapter <= 0 or request.context_token_budget <= 0:
            raise ValueError("production preparation request is incomplete")
