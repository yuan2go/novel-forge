from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .service import Principal, PrincipalType


FORMATION_AUTO_ACTIONS = frozenset(
    {
        "story_planning.candidate.approve",
        "story_planning.candidate.activate",
        "book_design.candidate.decide",
        "book_design.candidate.activate",
    }
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_formation_auto_authorization(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Formation AUTO authorization must be an object")
    authorization = dict(value)
    expected = {
        "contract_version",
        "policy_version",
        "authorization_ref",
        "authorized_by_principal_id",
        "project_id",
        "workspace_id",
        "book_id",
        "formation_run_id",
        "allowed_actions",
    }
    if set(authorization) != expected:
        raise ValueError("Formation AUTO authorization fields must match exactly")
    required = expected - {"allowed_actions"}
    if (
        authorization["contract_version"] != "formation-auto-authorization.v1"
        or authorization["policy_version"] != "formation-auto-policy.v1"
        or any(not str(authorization[field]).strip() for field in required)
        or not isinstance(authorization["allowed_actions"], list)
        or frozenset(str(item) for item in authorization["allowed_actions"])
        != FORMATION_AUTO_ACTIONS
        or len(authorization["allowed_actions"]) != len(FORMATION_AUTO_ACTIONS)
    ):
        raise ValueError("Formation AUTO authorization is incomplete or over-broad")
    authorization["allowed_actions"] = sorted(FORMATION_AUTO_ACTIONS)
    return authorization


def build_scoped_auto_decision_evidence(
    *,
    authorization: Mapping[str, Any],
    formation_input_digest: str,
    action: str,
    candidate_asset_version_id: str,
    candidate_content_hash: str,
    executed_by_principal_id: str,
) -> dict[str, Any]:
    canonical = canonical_formation_auto_authorization(authorization)
    if action not in FORMATION_AUTO_ACTIONS or action not in canonical[
        "allowed_actions"
    ]:
        raise PermissionError("Formation AUTO action is not authorized")
    if (
        not candidate_asset_version_id.strip()
        or len(candidate_content_hash) != 71
        or not candidate_content_hash.startswith("sha256:")
        or not executed_by_principal_id.strip()
        or len(formation_input_digest) != 71
        or not formation_input_digest.startswith("sha256:")
    ):
        raise ValueError("Formation AUTO decision requires an exact candidate")
    return {
        "contract_version": "formation-auto-decision.v1",
        "authorization": canonical,
        "authorization_hash": _canonical_hash(canonical),
        "formation_input_digest": formation_input_digest,
        "action": action,
        "candidate_asset_version_id": candidate_asset_version_id,
        "candidate_content_hash": candidate_content_hash,
        "executed_by_principal_id": executed_by_principal_id,
    }


def build_manual_formation_continuation_evidence(
    *,
    formation_run_id: str,
    formation_input_digest: str,
    project_id: str,
    workspace_id: str,
    book_id: str,
    action: str,
    candidate_asset_version_id: str,
    candidate_content_hash: str,
    approved_by_principal_id: str,
    approval_operation_id: str,
    executed_by_principal_id: str,
) -> dict[str, Any]:
    if action != "story_planning.candidate.activate":
        raise PermissionError("manual Formation continuation cannot decide a candidate")
    required = (
        formation_run_id,
        formation_input_digest,
        project_id,
        workspace_id,
        book_id,
        candidate_asset_version_id,
        candidate_content_hash,
        approved_by_principal_id,
        approval_operation_id,
        executed_by_principal_id,
    )
    if (
        any(not str(item).strip() for item in required)
        or len(formation_input_digest) != 71
        or not formation_input_digest.startswith("sha256:")
        or len(candidate_content_hash) != 71
        or not candidate_content_hash.startswith("sha256:")
    ):
        raise ValueError("manual Formation continuation evidence is incomplete")
    return {
        "contract_version": "formation-manual-continuation.v1",
        "formation_run_id": formation_run_id,
        "formation_input_digest": formation_input_digest,
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_id": book_id,
        "action": action,
        "candidate_asset_version_id": candidate_asset_version_id,
        "candidate_content_hash": candidate_content_hash,
        "approved_by_principal_id": approved_by_principal_id,
        "approval_operation_id": approval_operation_id,
        "executed_by_principal_id": executed_by_principal_id,
    }


def require_worker_scoped_auto_decision(
    *,
    principal: Principal,
    evidence: Mapping[str, Any] | None,
    project_id: str,
    workspace_id: str,
    book_id: str,
    action: str,
    candidate_asset_version_id: str,
    candidate_content_hash: str,
) -> None:
    if getattr(principal, "principal_type", None) is not PrincipalType.WORKER:
        return
    decision = dict(evidence or {})
    if decision.get("contract_version") == "formation-manual-continuation.v1":
        expected_manual_fields = {
            "contract_version",
            "formation_run_id",
            "formation_input_digest",
            "project_id",
            "workspace_id",
            "book_id",
            "action",
            "candidate_asset_version_id",
            "candidate_content_hash",
            "approved_by_principal_id",
            "approval_operation_id",
            "executed_by_principal_id",
        }
        if (
            set(decision) == expected_manual_fields
            and action == "story_planning.candidate.activate"
            and (
                decision.get("project_id"),
                decision.get("workspace_id"),
                decision.get("book_id"),
                decision.get("action"),
                decision.get("candidate_asset_version_id"),
                decision.get("candidate_content_hash"),
                decision.get("executed_by_principal_id"),
            )
            == (
                project_id,
                workspace_id,
                book_id,
                action,
                candidate_asset_version_id,
                candidate_content_hash,
                principal.principal_id,
            )
            and str(decision.get("formation_run_id") or "").startswith(
                "story-formation:"
            )
            and len(str(decision.get("formation_input_digest") or "")) == 71
            and str(decision.get("formation_input_digest") or "").startswith(
                "sha256:"
            )
            and str(decision.get("approved_by_principal_id") or "").strip()
            and str(decision.get("approval_operation_id") or "").strip()
        ):
            return
        raise PermissionError(
            "worker Formation continuation is not bound to the exact approval"
        )
    expected_fields = {
        "contract_version",
        "authorization",
        "authorization_hash",
        "formation_input_digest",
        "action",
        "candidate_asset_version_id",
        "candidate_content_hash",
        "executed_by_principal_id",
    }
    authorization = canonical_formation_auto_authorization(
        decision.get("authorization")
    )
    if (
        set(decision) != expected_fields
        or decision.get("contract_version") != "formation-auto-decision.v1"
        or decision.get("authorization_hash") != _canonical_hash(authorization)
        or len(str(decision.get("formation_input_digest") or "")) != 71
        or not str(decision.get("formation_input_digest") or "").startswith(
            "sha256:"
        )
        or (
            authorization["project_id"],
            authorization["workspace_id"],
            authorization["book_id"],
        )
        != (project_id, workspace_id, book_id)
        or action not in authorization["allowed_actions"]
        or (
            decision.get("action"),
            decision.get("candidate_asset_version_id"),
            decision.get("candidate_content_hash"),
            decision.get("executed_by_principal_id"),
        )
        != (
            action,
            candidate_asset_version_id,
            candidate_content_hash,
            principal.principal_id,
        )
    ):
        raise PermissionError(
            "worker Formation decision is not bound to the exact candidate and scope"
        )


__all__ = [
    "FORMATION_AUTO_ACTIONS",
    "build_manual_formation_continuation_evidence",
    "build_scoped_auto_decision_evidence",
    "canonical_formation_auto_authorization",
    "require_worker_scoped_auto_decision",
]
