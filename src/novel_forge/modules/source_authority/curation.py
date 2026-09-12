from __future__ import annotations

from copy import deepcopy
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from .corpus import CorpusUse, corpus_hash, corpus_identity


def _parent(
    current: dict[str, Any] | None, expected: str | None, workspace: str
) -> None:
    if expected != (current["revision_id"] if current else None):
        raise KernelError(
            "CORPUS_CATALOG_STALE", "inspect current revision before changing members"
        )
    if current and current["workspace_id"] != workspace:
        raise KernelError(
            "CORPUS_WORKSPACE_INVALID", "catalog belongs to another workspace"
        )


def apply_catalog_action(
    repository: Any,
    action: Any,
    *,
    project_id: str,
    workspace_id: str,
    operation_id: str,
) -> dict[str, Any]:
    repository.corpus_authorization_lock(project_id, write=True)
    if action.action == "declare_relation":
        left, right = sorted((action.left_id, action.right_id))
        rows = repository.catalog_processings(project_id, [left, right])
        if (
            left == right
            or len(rows) != 2
            or any(r["workspace_id"] != workspace_id for r in rows.values())
        ):
            raise KernelError(
                "CORPUS_RELATION_SCOPE",
                "two exact scoped processing revisions required",
            )
        previous = repository.corpus_equivalence_current(project_id, left, right)
        if action.previous_id != (previous["decision_id"] if previous else None):
            raise KernelError("CORPUS_EQUIVALENCE_STALE", "relation changed")
        from novel_forge.modules.source_import.corpus_ingestion.similarity import (
            compare,
        )

        decision = (
            "REJECT"
            if action.relation == "DIFFERENT_WORK"
            else "ACCEPT"
            if action.relation
            in {
                "SAME_WORK",
                "SAME_EDITION_COPY",
                "REVISION",
                "ABRIDGED",
                "EXPANDED",
                "EXCERPT",
            }
            else "REVOKE"
        )
        validate_relation_write(repository, project_id, workspace_id, rows, decision)
        identity = corpus_identity("relation", operation_id)
        repository.corpus_quality_insert(
            "equivalence",
            {
                "decision_id": identity,
                "project_id": project_id,
                "left_id": left,
                "right_id": right,
                "previous_id": action.previous_id,
                "canonical_work_id": previous["canonical_work_id"]
                if previous
                else corpus_identity("pair", left, right),
                "decision": decision,
                "relation": action.relation,
                "evidence": {
                    **compare(rows[left], rows[right]),
                    "operator_evidence": list(action.evidence_refs),
                    "relation_subject_id": action.left_id,
                    "relation_reference_id": action.right_id,
                },
                "reason": action.reason,
                "created_by_operation_id": operation_id,
            },
        )
        return {
            "decision_id": identity,
            "relation": action.relation,
            "rights_transfer": False,
        }
    if action.action == "resolve_canonical_works":
        return _resolve_works(
            repository, action, project_id, workspace_id, operation_id
        )
    return _revise_curated(repository, action, project_id, workspace_id, operation_id)


def validate_relation_write(repository, project, workspace, rows, decision):
    if len(rows) != 2 or any(r["workspace_id"] != workspace for r in rows.values()):
        raise KernelError(
            "CORPUS_RELATION_SCOPE", "two scoped processing revisions required"
        )
    if decision != "REJECT":
        return
    editions = [r["edition_id"] for r in rows.values()]
    groups = {}
    for group, edition in repository.catalog_conflicts(project, editions, [])[
        "existing_groups"
    ]:
        groups.setdefault(group, set()).add(edition)
    if len(set(editions)) < 2 or any(len(members) > 1 for members in groups.values()):
        raise KernelError(
            "CORPUS_SPLIT_REQUIRED",
            "split conflicting canonical members before declaring different works",
        )


def _resolve_works(
    repository: Any, action: Any, project: str, workspace: str, operation: str
) -> dict[str, Any]:
    work_ids = [
        corpus_identity("canonical-work", project, c.work_key) for c in action.changes
    ]
    if len(set(work_ids)) != len(work_ids):
        raise KernelError(
            "CORPUS_DUPLICATE_GROUP_CHANGE", "one revision per work in a command"
        )
    inputs = [m.processing_id for c in action.changes for m in c.members]
    rows = repository.catalog_processings(project, inputs)
    if set(rows) != set(inputs) or any(
        r["workspace_id"] != workspace for r in rows.values()
    ):
        raise KernelError("CORPUS_MEMBER_SCOPE", "exact scoped processing required")
    assigned = set()
    revisions = []
    for change, work_id in zip(action.changes, work_ids, strict=True):
        current = repository.catalog_current("work", project, work_id)
        _parent(current, change.previous_id, workspace)
        editions = [rows[m.processing_id]["edition_id"] for m in change.members]
        if len(set(editions)) != len(editions):
            raise KernelError(
                "CORPUS_DUPLICATE_EDITION_MEMBER", "one processing per Edition"
            )
        if change.state == "ACTIVE":
            if assigned.intersection(editions):
                raise KernelError(
                    "CORPUS_AMBIGUOUS_WORK_MEMBERSHIP",
                    "Edition cannot be active in two canonical works",
                )
            assigned.update(editions)
            conflicts = repository.catalog_conflicts(project, editions, work_ids)
            if conflicts["negative_relations"] or conflicts["existing_groups"]:
                raise KernelError("CORPUS_CANONICAL_CONFLICT", str(conflicts))
        revision = corpus_identity("canonical-revision", operation, work_id)
        members = [
            {
                "processing_id": m.processing_id,
                "edition_id": rows[m.processing_id]["edition_id"],
                "evidence": m.model_dump(mode="json"),
            }
            for m in change.members
        ]
        repository.catalog_insert(
            "work",
            {
                "revision_id": revision,
                "work_id": work_id,
                "project_id": project,
                "workspace_id": workspace,
                "previous_id": change.previous_id,
                "manifest": {
                    **change.model_dump(mode="json"),
                    "decision_reason": action.reason,
                },
                "created_by_operation_id": operation,
            },
            members,
        )
        revisions.append(
            {"work_id": work_id, "revision_id": revision, "members": len(members)}
        )
    return {
        "revisions": revisions,
        "automatic_transitive_merge": False,
        "rights_transfer": False,
    }


def curated_availability(
    repository: Any, project: str, members: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = repository.catalog_processings(
        project, [m["processing_id"] for m in members]
    )
    permissions = repository.corpus_edition_uses(
        project, tuple(m["edition_id"] for m in members), CorpusUse.SOURCE_ANALYSIS
    )
    documents = tuple(r["source_document_id"] for r in rows.values())
    denials = repository.corpus_document_denials(
        project, documents, CorpusUse.SOURCE_ANALYSIS
    )
    canonical_ids = [
        m["evidence"].get("canonical_revision_id")
        for m in members
        if m["evidence"].get("canonical_revision_id")
    ]
    active_canonical = repository.catalog_active_work_revisions(project, canonical_ids)
    relation_versions = repository.catalog_relation_versions(
        project, [m["edition_id"] for m in members]
    )
    outcomes = []
    for member in members:
        p = rows.get(member["processing_id"])
        permission = permissions.get(member["edition_id"])
        reasons = []
        frozen_relations = member["evidence"].get("relation_versions")
        current_relations = relation_versions.get(member["edition_id"], [])
        if frozen_relations is not None and frozen_relations != current_relations:
            reasons.append("RELATION_EVIDENCE_CHANGED")
        elif frozen_relations is None and current_relations:
            reasons.append("RELATION_BASELINE_NOT_FROZEN")
        if not p or not p["current"]:
            reasons.append("PROCESSING_SUPERSEDED_OR_MISSING")
        if not permission or permission["decision"] != "ALLOW":
            reasons.extend(
                permission["reasons"] if permission else ["RIGHTS_SCOPE_MISSING"]
            )
        if p and p["source_document_id"] in denials:
            reasons.append(denials[p["source_document_id"]])
        if p and member["evidence"].get("review_id") != p["review_id"]:
            reasons.append("REVIEW_REVISION_CHANGED")
        if (
            member["evidence"].get("canonical_revision_id")
            and member["evidence"]["canonical_revision_id"] not in active_canonical
        ):
            reasons.append("CANONICAL_MEMBERSHIP_REVISED")
        if not member["evidence"].get("canonical_revision_id"):
            reasons.append("CANONICAL_WORK_UNRESOLVED")
        outcomes.append(
            {
                "processing_id": member["processing_id"],
                "edition_id": member["edition_id"],
                "selected": member["evidence"]["selected"],
                "available": not reasons,
                "reasons": reasons,
            }
        )
    return outcomes


def _revise_curated(
    repository: Any, action: Any, project: str, workspace: str, operation: str
) -> dict[str, Any]:
    identity = corpus_identity("curated-corpus", project, action.corpus_key)
    current = repository.catalog_current("curated", project, identity)
    _parent(current, action.previous_id, workspace)
    filters = action.filters.model_dump(mode="json")
    if current and current["manifest"]["purpose"] != action.purpose:
        raise KernelError(
            "CORPUS_PURPOSE_IMMUTABLE", "create another purpose-specific corpus"
        )
    if action.state == "FROZEN" and (
        not current or filters != current["manifest"]["filters"]
    ):
        raise KernelError(
            "CORPUS_CANDIDATE_REVIEW_REQUIRED",
            "inspect a candidate revision with identical filters before freezing",
        )
    pool = (
        repository.catalog_candidates(
            project, action.purpose.value, filters, action.candidate_limit
        )
        if not current or action.state == "CANDIDATE"
        else {
            "members": deepcopy(current["members"]),
            "truncated": current["manifest"].get("candidate_pool_truncated", False),
        }
    )
    members = pool["members"]
    processing = repository.catalog_processings(
        project, [m["processing_id"] for m in members]
    )
    relation_versions = repository.catalog_relation_versions(
        project, [m["edition_id"] for m in members]
    )
    for member in members:
        p = processing[member["processing_id"]]
        if p["workspace_id"] != workspace:
            raise KernelError(
                "CORPUS_WORKSPACE_INVALID", "candidate belongs to another workspace"
            )
        if action.state != "FROZEN":
            member["evidence"]["relation_versions"] = relation_versions.get(
                member["edition_id"], []
            )
            member["evidence"]["review_id"] = p["review_id"]
            member["evidence"]["assessment_hash"] = corpus_hash(p["assessment"])
    choices = {c.processing_id: c for c in action.choices}
    if len(choices) != len(action.choices) or set(choices) - set(processing):
        raise KernelError(
            "CORPUS_SELECTION_SCOPE",
            "choices must reference distinct inspected candidate processing revisions",
        )
    for member in members:
        if member["processing_id"] in choices:
            member["evidence"].update(
                choices[member["processing_id"]].model_dump(mode="json")
            )
    availability = curated_availability(repository, project, members)
    selected = [m for m in members if m["evidence"]["selected"]]
    if action.state == "FROZEN":
        if not selected or any(
            not r["available"] for r in availability if r["selected"]
        ):
            raise KernelError("CORPUS_SELECTED_MEMBERS_BLOCKED", str(availability))
        hashes = [processing[m["processing_id"]]["normalized_hash"] for m in selected]
        if len(set(hashes)) != len(hashes):
            raise KernelError(
                "CORPUS_DUPLICATE_SELECTION",
                "exclude exact copies explicitly; their lineage remains retained",
            )
    revision = corpus_identity("curated-revision", operation, identity)
    manifest = {
        **action.model_dump(mode="json"),
        "candidate_pool_truncated": pool["truncated"],
        "availability": availability,
        "selected_count": len(selected),
        "selection_scope": "EXPLICIT_FROZEN_SUBSET"
        if action.state == "FROZEN"
        else "CANDIDATES_NOT_ACTIVATED",
    }
    repository.catalog_insert(
        "curated",
        {
            "revision_id": revision,
            "corpus_id": identity,
            "project_id": project,
            "workspace_id": workspace,
            "previous_id": action.previous_id,
            "manifest": manifest,
            "created_by_operation_id": operation,
        },
        members,
    )
    return {
        "corpus_id": identity,
        "revision_id": revision,
        "state": action.state,
        "selected_count": len(selected),
        "availability": availability,
        "candidate_pool_truncated": pool["truncated"],
    }


def require_curated_operation_current(
    repository: Any, project: str, operation: str
) -> dict[str, Any]:
    repository.corpus_authorization_lock(project)
    binding = repository.catalog_execution_binding(project, operation)
    if not binding:
        return {}
    frozen = repository.catalog_current(
        "curated", project, binding["curated_revision_id"], revision=True
    )
    current = (
        repository.catalog_current("curated", project, frozen["corpus_id"])
        if frozen
        else None
    )
    if (
        not current
        or current["revision_id"] != binding["curated_revision_id"]
        or current["manifest"]["state"] != "FROZEN"
    ):
        raise KernelError(
            "CURATED_SELECTION_CHANGED",
            "frozen history remains readable; new execution requires current explicit selection",
        )
    selected = [
        m
        for m in binding["members"]
        if m["processing_id"] == binding["member_processing_id"]
    ]
    availability = curated_availability(repository, project, selected)
    if len(selected) != 1 or any(not r["available"] for r in availability):
        raise KernelError("CURATED_PROVIDER_INPUT_STALE", str(availability))
    from .consumption import require_curated_consumption
    intent = binding.get("requested_manifest", {})
    require_curated_consumption(repository, project, frozen, selected,
                                intended_use=intent.get("intended_use", "SOURCE_ANALYSIS"), target_book_id=intent.get("target_book_id", ""))
    return binding["budget"]


def require_curated_evidence_current(
    repository: Any, project: str, asset_version: str
) -> None:
    operation = repository.catalog_evidence_operation(project, asset_version)
    if operation:
        require_curated_operation_current(repository, project, operation)
