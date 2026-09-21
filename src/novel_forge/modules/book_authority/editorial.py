from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .editorial_domain import (
    editorial_readiness,
    require_editorial_principal,
    validate_editorial_policy,
)
from .evidence_commands import execute_book_evidence_command


def load_editorial_events(
    uow: AuthorityUnitOfWork, book_run_id: str
) -> list[dict[str, Any]]:
    from .completion import _rows

    uow.cursor.execute(
        "SELECT * FROM authority_book_editorial_event WHERE book_run_id=%s ORDER BY event_version",
        [book_run_id],
    )
    return _rows(uow.cursor)


def require_review_closure(progress: dict[str, Any], policy: dict[str, Any]) -> None:
    if (
        not progress["source_current"]
        or not progress["coverage_complete"]
        or not progress["review_complete"]
        or progress["paused"]
    ):
        raise KernelError(
            "BOOK_EDITORIAL_COVERAGE_REQUIRED",
            "current whole manuscript coverage is required for signature",
        )
    for finding in progress["findings"]:
        if finding["status"] == "OBSERVATION":
            continue
        disposition = finding.get("disposition")
        if not disposition or disposition.get("status") != "DISPOSITION_RECORDED":
            raise KernelError(
                "BOOK_EDITORIAL_ISSUE_UNRESOLVED",
                "every conflicting or open finding requires version-bound disposition",
            )
        if disposition["decision"] == "DISMISSED_WITH_EVIDENCE":
            continue
        if finding["status"] == "CONFLICT_REQUIRES_REVIEW":
            raise KernelError(
                "BOOK_EDITORIAL_ISSUE_UNRESOLVED",
                "conflicting judgments require an explicit evidence-bound human decision",
            )
        severities = {
            member["severity"]
            for member in finding["members"]
            if member["judgment"] == "ISSUE"
        }
        if severities & {"BLOCKING", "MAJOR"}:
            raise KernelError(
                "BOOK_EDITORIAL_KEY_ISSUE_UNRESOLVED",
                "future proposals or preserved history do not resolve key manuscript defects",
            )
        if (
            disposition["decision"] != "MINOR_EXCEPTION"
            or not policy["allow_minor_exceptions"]
        ):
            raise KernelError(
                "BOOK_EDITORIAL_EXCEPTION_REQUIRED",
                "minor retained issues require a policy-permitted explicit exception",
            )


class BookEditorialWorkflow:
    def __init__(self, completion: Any) -> None:
        self.completion = completion
        self.database_url = completion.database_url
        self.commit_sha = completion.commit_sha
        self.application_build_id = completion.application_build_id

    def record(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        expected_version: int,
        kind: str,
        content: dict[str, Any],
        principal: Principal,
        **metadata: Any,
    ) -> dict[str, Any]:
        require_editorial_principal(principal, project_id)
        if kind not in {"POLICY", "SIGNATURE", "REVOCATION"}:
            raise KernelError(
                "BOOK_EDITORIAL_KIND_INVALID", "unsupported editorial action"
            )
        scope = dict(
            project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id
        )

        def handler(
            uow: AuthorityUnitOfWork, operation_id: str, checkpoint: Any
        ) -> dict[str, Any]:
            events = load_editorial_events(uow, book_run_id)
            if len(events) != expected_version:
                raise KernelError(
                    "BOOK_EDITORIAL_VERSION_CONFLICT",
                    "reload editorial history before changing it",
                )
            payload = dict(content)
            if kind == "POLICY":
                if (
                    set(content) != {"policy", "approval_rationale"}
                    or not str(content["approval_rationale"]).strip()
                ):
                    raise KernelError(
                        "BOOK_EDITORIAL_POLICY_APPROVAL_REQUIRED",
                        "explicit policy approval rationale is required",
                    )
                validate_editorial_policy(content["policy"])
                previous = [
                    event["content"]["policy"]
                    for event in events
                    if event["kind"] == "POLICY"
                    and event["content"]["policy"]["policy_version"]
                    == content["policy"]["policy_version"]
                ]
                if previous and previous[-1] != content["policy"]:
                    raise KernelError(
                        "BOOK_EDITORIAL_POLICY_VERSION_CONFLICT",
                        "changed policy needs a new version",
                    )
            elif kind == "SIGNATURE":
                required = {
                    "case_id",
                    "source_digest",
                    "review_run_id",
                    "review_digest",
                    "policy_event_id",
                    "statement",
                    "exception_rationale",
                }
                if set(content) != required or not str(content["statement"]).strip():
                    raise KernelError(
                        "BOOK_EDITORIAL_SIGNATURE_INVALID",
                        "signature must explicitly bind case, prose review, policy and statement",
                    )
                policies = [event for event in events if event["kind"] == "POLICY"]
                if (
                    not policies
                    or policies[-1]["event_id"] != content["policy_event_id"]
                ):
                    raise KernelError(
                        "BOOK_EDITORIAL_POLICY_STALE",
                        "signature requires the current approved policy",
                    )
                policy = policies[-1]["content"]["policy"]
                if (
                    not policy["enabled"]
                    or principal.principal_id not in policy["authorized_reviewers"]
                ):
                    raise PermissionError(
                        "the active editorial policy must name this authenticated reviewer"
                    )
                from .completion import _load_source
                from .completion_domain import assess_completion

                source = _load_source(uow, **scope)
                case = self.completion._case(uow, content["case_id"], book_run_id)
                assessment = assess_completion(
                    source["book"], source["accepted"]
                ).to_dict()
                if (
                    case["source_digest"] != content["source_digest"]
                    or assessment["source_digest"] != content["source_digest"]
                    or assessment["blockers"]
                    or case["exact_release_sha"] != self.commit_sha
                ):
                    raise KernelError(
                        "BOOK_EDITORIAL_SOURCE_STALE",
                        "signature requires the current complete exact implementation and manuscript case",
                    )
                from novel_forge.modules.book_followup_authority.prose_coordinator import (
                    load_review_run,
                    review_progress,
                )

                run = load_review_run(uow, run_id=content["review_run_id"], **scope)
                progress = review_progress(uow, run)
                if (
                    run["exact_release_sha"] != self.commit_sha
                    or progress["review_digest"] != content["review_digest"]
                ):
                    raise KernelError(
                        "BOOK_EDITORIAL_REVIEW_STALE",
                        "signature requires exact current review evidence",
                    )
                require_review_closure(progress, policy)
                if (
                    any(
                        item["status"] != "OBSERVATION" for item in progress["findings"]
                    )
                    and not str(content["exception_rationale"]).strip()
                ):
                    raise KernelError(
                        "BOOK_EDITORIAL_EXCEPTION_REQUIRED",
                        "retained minor findings require a signed exception rationale",
                    )
                payload.update(
                    manifest_digest=progress["manifest_digest"],
                    release_sha=self.commit_sha,
                    public_release_authorized=False,
                )
            else:
                if (
                    set(content) != {"signature_id", "reason"}
                    or not str(content["reason"]).strip()
                ):
                    raise KernelError(
                        "BOOK_EDITORIAL_REVOCATION_INVALID",
                        "revocation requires signature and reason",
                    )
                signature = next(
                    (
                        event
                        for event in events
                        if event["event_id"] == content["signature_id"]
                        and event["kind"] == "SIGNATURE"
                    ),
                    None,
                )
                if not signature or signature["actor_id"] != principal.principal_id:
                    raise PermissionError(
                        "only the original signer may revoke this signature"
                    )
            event_id = str(uuid4())
            uow.cursor.execute(
                "INSERT INTO authority_book_editorial_event(event_id,project_id,workspace_id,book_run_id,event_version,kind,content,actor_id,authentication_source,created_by_operation_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    event_id,
                    project_id,
                    workspace_id,
                    book_run_id,
                    expected_version + 1,
                    kind,
                    Jsonb(payload),
                    principal.principal_id,
                    principal.authentication_source,
                    operation_id,
                ],
            )
            return {
                "event_id": event_id,
                "event_version": expected_version + 1,
                "kind": kind,
                "content": payload,
                "actor_id": principal.principal_id,
            }

        return execute_book_evidence_command(
            database_url=self.database_url,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
            name="book.editorial." + kind.lower(),
            payload={
                **scope,
                "expected_version": expected_version,
                "kind": kind,
                "content": content,
            },
            principal=principal,
            handler=handler,
            **metadata,
        )

    def history(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_run_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("book.authority.query", project_id)
        from .completion import _load_source

        with AuthorityUnitOfWork(self.database_url) as uow:
            _load_source(
                uow,
                project_id=project_id,
                workspace_id=workspace_id,
                book_run_id=book_run_id,
            )
            events = load_editorial_events(uow, book_run_id)
            return {
                "book_run_id": book_run_id,
                "expected_version": len(events),
                "events": [
                    {
                        key: row[key]
                        for key in (
                            "event_id",
                            "event_version",
                            "kind",
                            "content",
                            "actor_id",
                            "authentication_source",
                        )
                    }
                    for row in events
                ],
                "public_release_authorized": False,
            }


def completion_editorial_evidence(
    uow: AuthorityUnitOfWork,
    *,
    case: dict[str, Any],
    payload: dict[str, Any],
    release_sha: str,
) -> tuple[list[str], dict[str, Any]]:
    events = load_editorial_events(uow, payload["book_run_id"])
    signatures = [
        event
        for event in events
        if event["kind"] == "SIGNATURE"
        and event["content"].get("case_id") == case["case_id"]
    ]
    if not signatures:
        blockers = ["WAITING_AUTHORIZED_EDITORIAL_SIGNATURES"]
        if not any(event["kind"] == "POLICY" for event in events):
            blockers.append("WHOLE_BOOK_EDITORIAL_POLICY_REQUIRED")
        return blockers, {}
    from novel_forge.modules.book_followup_authority.prose_coordinator import (
        load_review_run,
        review_progress,
    )

    signature = signatures[-1]
    run = load_review_run(
        uow,
        run_id=signature["content"]["review_run_id"],
        **{key: case[key] for key in ("project_id", "workspace_id", "book_run_id")},
    )
    progress = review_progress(uow, run)
    status = editorial_readiness(
        events=[
            event
            for event in events
            if event["kind"] != "SIGNATURE"
            or event["content"].get("case_id") == case["case_id"]
        ],
        source_digest=case["source_digest"],
        manifest_digest=progress["manifest_digest"],
        review_digest=progress["review_digest"],
        release_sha=release_sha,
    )
    blockers = list(status["blockers"])
    if (
        not progress["source_current"]
        or not progress["coverage_complete"]
        or not progress["review_complete"]
    ):
        blockers.append("BOOK_EDITORIAL_REVIEW_STALE")
    return blockers, status
