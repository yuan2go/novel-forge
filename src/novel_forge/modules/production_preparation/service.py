from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Protocol

from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import (
    ChapterAuthorityCommand,
    ProductionPreparationReport,
    ProductionPreparationRequest,
    ProductionPreparationResult,
    ResolvedProductionAsset,
)
from .policies import (
    ALWAYS_REQUIRED_ASSET_TYPES,
    CONTEXT_VERSION_REF_KEYS,
    CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
    OPTIONAL_CONTEXT_ASSET_TYPES,
)


class AssetResolver(Protocol):
    def resolve_latest(
        self, *, project_id: str, asset_type: str
    ) -> ResolvedProductionAsset | None: ...

    def resolve_override(
        self, *, project_id: str, asset_version_id: str
    ) -> ResolvedProductionAsset: ...


class ProductionPreparationService:
    def __init__(self, resolver: AssetResolver) -> None:
        self.resolver = resolver

    def prepare(self, request: ProductionPreparationRequest) -> ProductionPreparationResult:
        self._validate(request)
        required = list(ALWAYS_REQUIRED_ASSET_TYPES)
        if request.chapter > 1:
            required.extend(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES)
        ordered_types = tuple(dict.fromkeys([*required, *OPTIONAL_CONTEXT_ASSET_TYPES]))
        selected: dict[str, ResolvedProductionAsset] = {}
        blocked: list[dict[str, str]] = []
        for asset_type in ordered_types:
            override = request.explicit_asset_version_overrides.get(asset_type)
            try:
                asset = (
                    self.resolver.resolve_override(
                        project_id=request.project_id,
                        asset_version_id=override,
                    )
                    if override
                    else self.resolver.resolve_latest(
                        project_id=request.project_id,
                        asset_type=asset_type,
                    )
                )
            except ValueError:
                raise
            except KernelError as exc:
                code = exc.code
                blocked.append({"asset_type": asset_type, "code": code})
                asset = None
            if asset is not None:
                if asset.project_id != request.project_id:
                    raise ValueError("cross-project production asset resolution")
                if asset.asset_type != asset_type:
                    raise ValueError(
                        f"override asset type mismatch: expected {asset_type}, got {asset.asset_type}"
                    )
                fit_issue = self._asset_fit_issue(
                    asset_type=asset_type,
                    asset=asset,
                    requested_chapter=request.chapter,
                )
                if fit_issue:
                    blocked.append({"asset_type": asset_type, "code": fit_issue})
                else:
                    selected[asset_type] = asset
        missing = tuple(kind for kind in required if kind not in selected)
        repair_actions = tuple(self._repair_action(kind) for kind in missing)
        digest = self._digest(selected)
        decision = "READY" if not missing and not blocked else "BLOCKED"
        report = ProductionPreparationReport(
            project_id=request.project_id,
            chapter=request.chapter,
            decision=decision,
            selected_asset_version_ids=tuple(
                item.asset_version_id for item in selected.values()
            ),
            selection_reasons={
                item.asset_version_id: item.selected_reason for item in selected.values()
            },
            missing_required_asset_types=missing,
            blocked_assets=tuple(blocked),
            approval_requirements=tuple(
                kind for kind in ("operator_checklist", "operator_approval") if kind in missing
            ),
            context_digest=digest,
            estimated_token_budget=request.context_token_budget,
            estimated_provider_budget={
                "currency": "USD",
                "status": "ESTIMATE_UNCALIBRATED",
                "maximum_tokens": request.context_token_budget,
            },
            repair_actions=repair_actions,
            idempotency_key=request.idempotency_key,
        )
        if decision != "READY":
            return ProductionPreparationResult(report=report, command=None)
        chapter_plan = selected["chapter_plan"].content
        title = request.title_override.strip() or str(chapter_plan.get("title") or "").strip()
        premise = request.premise_override.strip() or str(
            chapter_plan.get("premise") or chapter_plan.get("objective") or ""
        ).strip()
        if not title or not premise:
            blocked_report = ProductionPreparationReport(
                **{
                    **asdict(report),
                    "decision": "BLOCKED",
                    "repair_actions": (*report.repair_actions, "complete chapter plan title and premise"),
                }
            )
            return ProductionPreparationResult(report=blocked_report, command=None)
        candidates = tuple(
            {
                "asset_version_id": item.asset_version_id,
                "content_hash": item.content_hash,
                "asset_type": item.asset_type,
                "project_id": item.project_id,
                "selection_reason": item.selected_reason,
                "safe_summary": str(item.content.get("safe_summary") or ""),
                "structured_facts": list(item.content.get("structured_facts") or []),
                "narrative_function": str(
                    item.content.get("narrative_function") or item.asset_type
                ),
                "estimated_tokens": int(
                    item.content.get("estimated_tokens")
                    or max(1, len(str(item.content.get("safe_summary") or "")) // 4)
                ),
                **(
                    {"allowed_use": str(item.content["allowed_use"])}
                    if item.content.get("allowed_use")
                    else {}
                ),
            }
            for item in selected.values()
            if item.asset_type != "chapter_plan"
        )
        version_refs = {
            CONTEXT_VERSION_REF_KEYS.get(kind, f"{kind}_version"): item.asset_version_id
            for kind, item in selected.items()
        }
        command = ChapterAuthorityCommand(
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            chapter=request.chapter,
            title=title,
            premise=premise,
            context_candidates=candidates,
            context_version_refs=version_refs,
            context_token_budget=request.context_token_budget,
            preparation_report=asdict(report),
            idempotency_key=request.idempotency_key,
        )
        return ProductionPreparationResult(report=report, command=command)

    @staticmethod
    def _validate(request: ProductionPreparationRequest) -> None:
        if (
            not request.project_id
            or not request.workspace_id
            or request.chapter <= 0
            or not request.idempotency_key
            or request.context_token_budget <= 0
        ):
            raise ValueError("production preparation request is incomplete")

    @staticmethod
    def _digest(selected: dict[str, ResolvedProductionAsset]) -> str:
        payload = [
            (kind, asset.asset_version_id, asset.content_hash)
            for kind, asset in sorted(selected.items())
        ]
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _repair_action(asset_type: str) -> str:
        if asset_type == "canon_snapshot":
            return "produce and qualify the previous chapter Canon snapshot"
        if asset_type in {"operator_checklist", "operator_approval"}:
            return f"create an eligible {asset_type} Authority asset"
        return f"create or re-qualify the required {asset_type} Authority asset"

    @staticmethod
    def _asset_fit_issue(
        *,
        asset_type: str,
        asset: ResolvedProductionAsset,
        requested_chapter: int,
    ) -> str:
        content = asset.content
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
        facts = {
            str(item.get("key")): item.get("value")
            for item in content.get("structured_facts", [])
            if isinstance(item, dict)
        }
        if asset_type == "operator_checklist" and not (
            content.get("completed") is True or facts.get("completed") is True
        ):
            return "OPERATOR_CHECKLIST_INCOMPLETE"
        if asset_type == "operator_approval":
            if not (content.get("approved") is True or facts.get("approved") is True):
                return "OPERATOR_APPROVAL_MISSING"
            expires_at = str(content.get("expires_at") or "").strip()
            if expires_at:
                try:
                    parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    if parsed <= datetime.now(timezone.utc):
                        return "OPERATOR_APPROVAL_EXPIRED"
                except ValueError:
                    return "OPERATOR_APPROVAL_EXPIRY_INVALID"
        return ""
