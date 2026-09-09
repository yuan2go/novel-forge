from __future__ import annotations

from copy import deepcopy
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import CorpusUse, corpus_identity
from novel_forge.modules.source_import.corpus_ingestion.similarity import compare


def apply_quality_decision(
    repository: Any, action: Any, *, project_id: str, operation_id: str
) -> dict[str, Any]:
    repository.corpus_authorization_lock(project_id, write=True)
    if action.action == "review_processing":
        processing = repository.corpus_processing(project_id, action.processing_id)
        repository.require_corpus_edition_use(
            project_id,
            processing["edition_id"],
            CorpusUse.LOCAL_PROCESSING,
            require_bridge=False,
        )
        previous = processing["review"]["review_id"] if processing["review"] else None
        if action.previous_id != previous:
            raise KernelError(
                "CORPUS_REVIEW_STALE", "review changed; inspect the current revision"
            )
        assessment = deepcopy(processing["assessment"])
        issues = {i["issue_id"]: i for i in assessment["issues"]}
        resolutions = list(assessment.get("resolutions", []))
        for decision in action.decisions:
            finding = issues.get(decision.issue_id)
            if finding is None or finding.get("resolution"):
                raise KernelError(
                    "CORPUS_ISSUE_SCOPE_INVALID", "unresolved issue identity required"
                )
            allowed = {
                "CONFIRM_EXCERPT": {
                    "MISSING_OR_UNORDERED_CHAPTER",
                    "TOC_BODY_MISMATCH",
                    "TOC_ENTRY_MISMATCH",
                },
                "MARK_NON_BODY": {
                    "NON_BODY_UNIT",
                    "SHORT_OR_TOC_UNIT",
                    "DUPLICATE_TITLE",
                    "NUMBER_CONFLICT",
                },
                "CONFIRM_BOUNDARY": {"SHORT_OR_TOC_UNIT"},
                "CONFIRM_LEGITIMATE_REPETITION": {"DUPLICATE_BODY", "REPEATED_SHORT_BODY"},
                "CONFIRM_TOC_VARIANT": {"TOC_ENTRY_MISMATCH"},
                "ANNOTATE_TOC_DIFFERENCE": {"TOC_ENTRY_MISMATCH"},
                "REJECT_CORRUPT": set(issues[i]["code"] for i in issues),
            }
            if finding["code"] not in allowed[decision.resolution]:
                raise KernelError(
                    "CORPUS_REVIEW_CANNOT_WAIVE",
                    "this issue requires new source evidence or a new parser contract",
                )
            if decision.resolution in {"CONFIRM_LEGITIMATE_REPETITION", "CONFIRM_TOC_VARIANT", "ANNOTATE_TOC_DIFFERENCE"}:
                if not decision.evidence_refs or not decision.classification:
                    raise KernelError("CORPUS_SCOPED_EVIDENCE_REQUIRED", "classification and exact source evidence required")
                if decision.resolution == "CONFIRM_TOC_VARIANT" and (
                    not finding.get("expected_title") or not finding.get("observed_title")
                    or decision.classification not in {"DISPLAY", "TRANSCRIPTION_SUSPECTED", "VERSION_WORDING"}
                ):
                    raise KernelError("CORPUS_MISSING_CONTENT_CANNOT_BE_WAIVED", "only a located title variant can be accepted")
                if decision.resolution == "CONFIRM_LEGITIMATE_REPETITION" and decision.classification != "LEGITIMATE_REPETITION":
                    raise KernelError("CORPUS_DUPLICATE_EVIDENCE_REQUIRED", "explicit per-occurrence legitimate repetition evidence required")
                if decision.resolution == "ANNOTATE_TOC_DIFFERENCE":
                    finding.setdefault("annotations", []).append(decision.model_dump(mode="json"))
                    continue
            resolution = {
                **decision.model_dump(mode="json"),
                "evidence": finding["evidence"],
            }
            resolutions.append(resolution)
            finding["resolution"] = resolution
            finding["blocking"] = decision.resolution == "REJECT_CORRUPT"
            if decision.resolution == "CONFIRM_EXCERPT":
                assessment["coverage"] = "EXCERPT"
            if decision.resolution == "REJECT_CORRUPT":
                assessment["coverage"] = "CORRUPT"
        assessment["resolutions"] = resolutions
        assessment["requires_reprocessing"] = any(
            r["resolution"] == "MARK_NON_BODY" for r in resolutions
        )
        assessment["structure_usable"] = not assessment[
            "requires_reprocessing"
        ] and not any(i["blocking"] for i in assessment["issues"])
        identity = corpus_identity("review", operation_id)
        repository.corpus_quality_insert(
            "review",
            {
                "review_id": identity,
                "project_id": project_id,
                "processing_id": action.processing_id,
                "previous_id": previous,
                "decisions": [d.model_dump(mode="json") for d in action.decisions],
                "assessment": assessment,
                "reason": action.reason,
                "created_by_operation_id": operation_id,
            },
        )
        return {
            "review_id": identity,
            "processing_id": action.processing_id,
            "assessment": assessment,
        }
    left_id, right_id = sorted((action.left_id, action.right_id))
    if left_id == right_id:
        raise KernelError(
            "CORPUS_EQUIVALENCE_SELF",
            "two exact distinct processing identities required",
        )
    left, right = (
        repository.corpus_processing(project_id, left_id),
        repository.corpus_processing(project_id, right_id),
    )
    previous = repository.corpus_equivalence_current(project_id, left_id, right_id)
    if action.previous_id != (previous["decision_id"] if previous else None):
        raise KernelError("CORPUS_EQUIVALENCE_STALE", "pair decision changed")
    if action.decision == "REVOKE" and (
        not previous or previous["decision"] != "ACCEPT"
    ):
        raise KernelError(
            "CORPUS_EQUIVALENCE_NOT_ACCEPTED", "only an accepted pair can be revoked"
        )
    identity = corpus_identity("equivalence", operation_id)
    evidence = compare(left, right)
    repository.corpus_quality_insert(
        "equivalence",
        {
            "decision_id": identity,
            "project_id": project_id,
            "left_id": left_id,
            "right_id": right_id,
            "previous_id": action.previous_id,
            "canonical_work_id": previous["canonical_work_id"]
            if previous
            else corpus_identity(
                "canonical-work-pair",
                *sorted((left["edition_id"], right["edition_id"])),
            ),
            "decision": action.decision,
            "evidence": {**evidence, "operator_evidence": action.evidence_refs},
            "reason": action.reason,
            "created_by_operation_id": operation_id,
        },
    )
    return {
        "decision_id": identity,
        "decision": action.decision,
        "comparison": evidence,
        "rights_transfer": False,
        "transitive_merge": False,
    }
