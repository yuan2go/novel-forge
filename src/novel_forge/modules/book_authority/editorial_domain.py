from __future__ import annotations

from typing import Any, Mapping, Sequence

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError


def require_editorial_principal(principal: Principal, project_id: str) -> None:
    principal.require("book.authority.execute", project_id)
    if (
        principal.principal_type is not PrincipalType.LOCAL_OPERATOR
        or principal.authentication_source != "server_configuration"
    ):
        raise PermissionError(
            "editorial policy and signature require an authenticated human operator"
        )


def validate_editorial_policy(policy: Mapping[str, Any]) -> None:
    if set(policy) != {
        "policy_version",
        "enabled",
        "authorized_reviewers",
        "minimum_signatures",
        "allow_minor_exceptions",
    }:
        raise KernelError(
            "BOOK_EDITORIAL_POLICY_INVALID",
            "policy fields must be explicit and versioned",
        )
    reviewers = policy["authorized_reviewers"]
    if (
        not isinstance(reviewers, list)
        or not reviewers
        or len(set(reviewers)) != len(reviewers)
        or any(not isinstance(value, str) or not value.strip() for value in reviewers)
    ):
        raise KernelError(
            "BOOK_EDITORIAL_POLICY_INVALID", "named distinct reviewers are required"
        )
    if (
        not isinstance(policy["policy_version"], str)
        or not policy["policy_version"].strip()
        or type(policy["enabled"]) is not bool
        or type(policy["allow_minor_exceptions"]) is not bool
        or type(policy["minimum_signatures"]) is not int
        or not 1 <= policy["minimum_signatures"] <= len(reviewers)
    ):
        raise KernelError(
            "BOOK_EDITORIAL_POLICY_INVALID",
            "invalid version, activation or signature threshold",
        )


def editorial_readiness(
    *,
    events: Sequence[Mapping[str, Any]],
    source_digest: str,
    manifest_digest: str,
    review_digest: str,
    release_sha: str,
) -> dict[str, Any]:
    policies = [event for event in events if event["kind"] == "POLICY"]
    if not policies:
        return {
            "status": "WAITING_POLICY_APPROVAL",
            "blockers": ["WHOLE_BOOK_EDITORIAL_POLICY_REQUIRED"],
            "signature_ids": [],
            "policy_event_id": "",
        }
    policy_event = policies[-1]
    policy = policy_event["content"]["policy"]
    validate_editorial_policy(policy)
    revoked = {
        event["content"]["signature_id"]
        for event in events
        if event["kind"] == "REVOCATION"
    }
    signatures = [
        event
        for event in events
        if event["kind"] == "SIGNATURE"
        and event["event_id"] not in revoked
        and event["content"].get("policy_event_id") == policy_event["event_id"]
        and event["actor_id"] in policy["authorized_reviewers"]
        and all(
            event["content"].get(key) == value
            for key, value in {
                "source_digest": source_digest,
                "manifest_digest": manifest_digest,
                "review_digest": review_digest,
                "release_sha": release_sha,
            }.items()
        )
    ]
    by_actor = {event["actor_id"]: event for event in signatures}
    blockers = []
    if not policy["enabled"]:
        blockers.append("WHOLE_BOOK_EDITORIAL_POLICY_INACTIVE")
    if len(by_actor) < policy["minimum_signatures"]:
        blockers.append("WAITING_AUTHORIZED_EDITORIAL_SIGNATURES")
    return {
        "status": "WAITING_EVIDENCE" if blockers else "SIGNED",
        "blockers": blockers,
        "signature_ids": sorted(event["event_id"] for event in by_actor.values()),
        "policy_event_id": policy_event["event_id"],
    }
