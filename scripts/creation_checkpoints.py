from __future__ import annotations

from typing import Any

from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority.application import ContentOperationRequest
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_control_repositories import BookControlRepository
from scripts.creation_reading import load_accepted_reading


REVIEW_CONTRACT = "author-reading-review.v1"


def reading_review_template(manifest: dict) -> dict:
    boundary = manifest["accepted_through_chapter"]
    start = 1 if boundary <= 6 else boundary - 2
    return {
        "contract_version": REVIEW_CONTRACT,
        **{key: manifest[key] for key in ("project_id", "book_id", "book_run_id", "accepted_through_chapter")},
        "reading_manifest_hash": manifest["manifest_hash"], "status": "NOT_REVIEWED",
        "paused_book_version": manifest.get("book_version"),
        "evidence_class": "AI_EDITORIAL_REVIEW", "independent_human_review": "NOT_REVIEWED",
        "decision_actor_class": "AI_OPERATOR_AUTOMATION", "reviewer_id": "", "summary": "",
        "chapter_assessments": [{
            "chapter_number": chapter["chapter_number"], "candidate_asset_version_id": chapter["candidate_asset_version_id"],
            "text_hash": chapter["text_hash"], "assessment": "", "locations": [],
        } for chapter in manifest["chapters"] if chapter["chapter_number"] >= start], "issues": [],
    }


def reading_checkpoints(policy: dict, *, book_target: int) -> tuple[int, ...]:
    values = policy.get("reading_checkpoints", [])
    stop = policy.get("pilot_stop_after_chapter") or book_target
    if (not isinstance(values, list) or any(type(value) is not int or not 0 < value <= stop for value in values)
        or values != sorted(set(values)) or values and values[-1] != stop):
        raise ValueError("reading_checkpoints must be increasing accepted cursors ending at the frozen sample target")
    return tuple(values)


def _documents(composition: Any, book: dict, *, kind: str) -> list:
    rows = AuthorityAssetQuery(composition.authority.database_url).list_versions(
        project_id=book["project_id"], asset_type=kind, limit=500,
    )
    if len(rows) == 500:
        raise ValueError("Checkpoint evidence reached the native asset page bound")
    return [row for row in rows if row.content.get("book_run_id") == book["book_run_id"]]


def validate_reading_review(review: dict, manifest: dict, *, previous_reviews: list[dict] = (), require_clear: bool = True) -> None:
    scope = {key: manifest[key] for key in ("project_id", "book_id", "book_run_id", "accepted_through_chapter")}
    if (review.get("contract_version") != REVIEW_CONTRACT
        or review.get("status") != "REVIEWED"
        or any(review.get(key) != value for key, value in scope.items())
        or review.get("reading_manifest_hash") != manifest["manifest_hash"]
        or type(review.get("paused_book_version")) is not int or review["paused_book_version"] < 1
        or review.get("evidence_class") not in {"AI_EDITORIAL_REVIEW", "OPERATOR_GUIDED"}
        or review.get("independent_human_review") != "NOT_REVIEWED"
        or review.get("decision_actor_class") not in {"AI_OPERATOR_AUTOMATION", "LOCAL_OPERATOR"}
        or not str(review.get("reviewer_id") or "").strip()
        or not str(review.get("summary") or "").strip()):
        raise ValueError("Checkpoint review must bind exact accepted text and explicit non-independent editorial evidence")
    chapters = {row["chapter_number"]: row for row in manifest["chapters"]}
    boundary = manifest["accepted_through_chapter"]
    start = 1 if boundary <= 6 else boundary - 2
    assessments = review.get("chapter_assessments")
    if not isinstance(assessments, list) or [item.get("chapter_number") for item in assessments] != list(range(start, boundary + 1)):
        raise ValueError("Checkpoint review omits a required accepted chapter; chapter six requires the entire first six")
    for assessment in assessments:
        target = chapters[assessment["chapter_number"]]
        if (assessment.get("candidate_asset_version_id") != target["candidate_asset_version_id"]
            or assessment.get("text_hash") != target["text_hash"]
            or not str(assessment.get("assessment") or "").strip()):
            raise ValueError("Chapter assessment differs from accepted manuscript identity")
        locations = assessment.get("locations")
        if not isinstance(locations, list) or not locations:
            raise ValueError("Chapter assessment needs actual accepted prose locations")
        for location in locations:
            left, right = location.get("start"), location.get("end")
            if (type(left) is not int or type(right) is not int or not 0 <= left < right <= len(target["text"])
                or target["text"][left:right] != location.get("text")):
                raise ValueError("Checkpoint location is absent from the accepted text")
    issues = review.get("issues")
    if not isinstance(issues, list) or len({item.get("issue_id") for item in issues}) != len(issues):
        raise ValueError("Checkpoint issues must have unique durable identities")
    current = {}
    for issue in issues:
        if (not issue.get("issue_id") or issue.get("status") not in {"OPEN", "RESOLVED"}
            or issue.get("chapter_number") not in chapters or not issue.get("diagnosis")
            or not isinstance(issue.get("severity"), str)
            or issue["severity"].lower() not in {"critical", "blocker", "blocking", "high", "major", "medium", "minor", "low"}
            or not str(issue.get("repair_target") or "").strip()
            or not issue.get("preservation_requirements") or not issue.get("acceptance_criteria")):
            raise ValueError("Checkpoint issue requires a chapter, severity, diagnosis, repair target, preservation and acceptance criteria")
        location = issue.get("location") or {}
        text = chapters[issue["chapter_number"]]["text"]
        left, right = location.get("start"), location.get("end")
        if (type(left) is not int or type(right) is not int or not 0 <= left < right <= len(text)
            or text[left:right] != location.get("text")):
            raise ValueError("Checkpoint issue must locate the exact accepted passage")
        if issue["status"] == "RESOLVED":
            evidence = issue.get("resolution_evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("Resolved checkpoint issue requires located resolution evidence")
            for check in evidence:
                target = chapters.get(check.get("chapter_number")) if isinstance(check, dict) else None
                location = check.get("location") or {} if isinstance(check, dict) else {}
                left, right = location.get("start"), location.get("end")
                if (target is None or check.get("candidate_asset_version_id") != target["candidate_asset_version_id"]
                    or check.get("text_hash") != target["text_hash"] or not check.get("reason") or not check.get("preservation_check")
                    or type(left) is not int or type(right) is not int or not 0 <= left < right <= len(target["text"])
                    or target["text"][left:right] != location.get("text")):
                    raise ValueError("Checkpoint resolution must recheck exact accepted text and preservation")
        if require_clear and issue["status"] != "RESOLVED":
            raise ValueError("Unresolved checkpoint issues block continuation")
        current[issue["issue_id"]] = issue
    for previous in previous_reviews:
        for old in previous.get("issues", []):
            if old["issue_id"] not in current:
                raise ValueError("A previously recorded checkpoint issue cannot disappear from the new review")
            if any(current[old["issue_id"]].get(key) != old.get(key) for key in (
                "chapter_number", "severity", "diagnosis", "repair_target", "location", "preservation_requirements", "acceptance_criteria",
            )):
                raise ValueError("A checkpoint issue cannot change its original repair or preservation contract")


def register_reading_review(*, composition: Any, content_application: Any, book_run_id: str,
                            review: dict, idempotency_key: str) -> dict:
    book = composition.authority.require(book_run_id)
    if (book["state"] != "PAUSED" or review.get("accepted_through_chapter") != book["accepted_through_chapter"]
        or type(review.get("paused_book_version")) is not int or review["paused_book_version"] != book["version"]):
        raise ValueError("Register checkpoint reading against the exact native paused cursor")
    manifest = load_accepted_reading(composition=composition, book_run_id=book_run_id, require_closed_groups=True)
    previous = [item.content for item in _documents(composition, book, kind="operator_checklist")
                if item.content.get("contract_version") == REVIEW_CONTRACT
                and item.content.get("accepted_through_chapter") == book["accepted_through_chapter"]]
    validate_reading_review(review, manifest, previous_reviews=previous, require_clear=False)
    result = content_application.execute(ContentOperationRequest(
        definition_name="chapter.operator_checklist.author", project_id=book["project_id"],
        workspace_id=book["workspace_id"], actor_id=composition.principal.principal_id,
        trace_id=f"trace:{idempotency_key}", correlation_id=book_run_id, idempotency_key=idempotency_key,
        payload={"content": {**review, "type": "operator_checklist", "chapter": book["accepted_through_chapter"] + 1,
                 "completed": True, "safe_summary": review["summary"],
                 "structured_facts": [{"key": "reading_manifest_hash", "value": manifest["manifest_hash"]}]}},
    ), principal=composition.principal)
    return {"review_asset_version_id": result.asset_version_id, "review_content_hash": result.content_hash,
            "operation_id": result.operation_id, "replayed": result.replayed,
            "independent_human_review": "NOT_REVIEWED"}


def _review(composition: Any, book: dict, identity: str, *, require_clear: bool = True):
    document = AuthorityAssetQuery(composition.authority.database_url).require(project_id=book["project_id"], asset_version_id=identity)
    if (document.asset_type != "operator_checklist" or document.lifecycle != "ACTIVE"
        or document.governance != "CLEAR" or document.eligibility != "ELIGIBLE"
        or canonical_hash(document.content) != document.content_hash
        or document.content.get("allowed_use") != "evidence_only"):
        raise ValueError("Checkpoint review must be an exact current governed Content evidence version")
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_operation_output_asset output
            JOIN authority_operation operation USING(operation_id)
            WHERE output.asset_version_id=%s AND operation.project_id=%s
              AND operation.definition_name='chapter.operator_checklist.author' AND operation.status='SUCCEEDED')""",
            [document.asset_version_id, book["project_id"]])
        if not uow.cursor.fetchone()[0]:
            raise ValueError("Checkpoint review has no successful native Content authoring operation")
    boundary = document.content.get("accepted_through_chapter")
    manifest = load_accepted_reading(composition=composition, book_run_id=book["book_run_id"],
                                     through_chapter=boundary, require_closed_groups=True)
    previous = [item.content for item in _documents(composition, book, kind="operator_checklist")
                if item.content.get("contract_version") == REVIEW_CONTRACT
                and item.content.get("accepted_through_chapter") == boundary]
    validate_reading_review(document.content, manifest, previous_reviews=previous, require_clear=require_clear)
    return document


def decide_reading_review(*, composition: Any, book_run_id: str, review_asset_version_id: str,
                          decision: str, reason: str, idempotency_key: str) -> dict:
    book = composition.authority.require(book_run_id)
    document = _review(composition, book, review_asset_version_id, require_clear=decision == "APPROVE")
    if (book["state"] != "PAUSED" or document.content["accepted_through_chapter"] != book["accepted_through_chapter"]
        or document.content.get("paused_book_version") != book["version"]):
        raise ValueError("Checkpoint decision requires its exact paused accepted cursor")
    return composition.controls.decide(
        principal=composition.principal, project_id=book["project_id"], book_run_id=book_run_id,
        chapter_number=book["accepted_through_chapter"] + 1, boundary="NEAR_TERM",
        subject_version_id=document.asset_version_id, decision=decision,
        reason=f"{document.content['decision_actor_class']}; {document.content['evidence_class']}; independent human NOT_REVIEWED. {reason}",
        idempotency_key=idempotency_key, trace_id=f"trace:{idempotency_key}", correlation_id=book_run_id,
    )


def require_reading_decision(*, composition: Any, book_run_id: str, boundary: int, decision_version_id: str = "") -> dict:
    book = composition.authority.require(book_run_id)
    query = AuthorityAssetQuery(composition.authority.database_url)
    rows = [query.require(project_id=book["project_id"], asset_version_id=decision_version_id)] if decision_version_id else _documents(composition, book, kind="editorial_decision_evidence")
    for document in rows:
        value = document.content
        if (value.get("contract_version") != "book-control-decision.v1" or value.get("book_run_id") != book_run_id
            or value.get("book_id") != book["book_id"] or value.get("chapter_number") != boundary + 1
            or value.get("accepted_through_chapter") != boundary or value.get("boundary") != "NEAR_TERM"
            or value.get("decision") != "APPROVE" or value.get("operator_type") != PrincipalType.LOCAL_OPERATOR.value):
            continue
        document = query.require(project_id=book["project_id"], asset_version_id=document.asset_version_id)
        with AuthorityUnitOfWork(composition.authority.database_url) as uow:
            current = BookControlRepository(uow.cursor).current_decision(project_id=book["project_id"], logical_ref=document.logical_ref)
        if current is None or current["asset_version_id"] != document.asset_version_id or current["content_hash"] != document.content_hash:
            continue
        review = _review(composition, book, value["subject_version_id"])
        return {"decision_version_id": document.asset_version_id, "review_asset_version_id": review.asset_version_id,
                "accepted_through_chapter": boundary, "reading_manifest_hash": review.content["reading_manifest_hash"],
                "paused_book_version": review.content.get("paused_book_version"),
                "evidence_class": review.content["evidence_class"], "independent_human_review": "NOT_REVIEWED"}
    raise KernelError("AUTHOR_READING_REVIEW_REQUIRED", "Continuation requires a current native editorial decision for the exact accepted reading checkpoint")
