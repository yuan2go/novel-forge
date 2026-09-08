from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import (
    CorpusAction,
    CorpusPurpose,
    EvaluateCorpusAdmission,
    FreezeCorpusSnapshot,
    ImportCorpusBatch,
    RegisterCorpusSource,
    RetireCorpusSource,
    RightsDeclaration,
    corpus_admission,
    corpus_identity,
)
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository


def apply_corpus_action(
    repository: SourceAuthorityRepository,
    action: CorpusAction,
    *,
    project_id: str,
    workspace_id: str,
    operation_id: str,
) -> dict[str, Any]:
    repository.corpus_authorization_lock(project_id, write=True)
    scope = {"project_id": project_id, "created_by_operation_id": operation_id}
    if isinstance(action, RegisterCorpusSource):
        source_id = corpus_identity(
            "source", project_id, action.source_kind, action.external_identity
        )
        source = repository.corpus_insert(
            "source",
            {
                **scope,
                "source_id": source_id,
                "workspace_id": workspace_id,
                "source_kind": action.source_kind,
                "external_identity": action.external_identity,
                "purpose": action.purpose.value,
            },
        )
        return {"source_id": source_id, "source": source}
    if isinstance(action, ImportCorpusBatch):
        snapshot = repository.corpus_record("snapshot", project_id, action.snapshot_id)
        source_id = snapshot["source_id"]
    elif isinstance(action, EvaluateCorpusAdmission):
        edition = repository.corpus_record("edition", project_id, action.edition_id)
        source_id = edition["source_id"]
    else:
        source_id = action.source_id
    source = repository.corpus_source_lock(project_id, source_id)
    if source["workspace_id"] != workspace_id:
        raise KernelError(
            "CORPUS_WORKSPACE_INVALID", "source belongs to a different workspace"
        )
    if isinstance(action, EvaluateCorpusAdmission):
        return _decision(repository, scope, source, edition, action.purpose)
    if isinstance(action, RetireCorpusSource):
        repository.corpus_insert(
            "retirement", {**scope, "source_id": source_id, "reason": action.reason}
        )
        return {"source_id": source_id, "retired": True}
    if source["retired"]:
        raise KernelError(
            "CORPUS_SOURCE_NOT_ELIGIBLE",
            "retirement preserves history and forbids new imports/revisions",
        )
    if isinstance(action, RightsDeclaration):
        identity = corpus_identity("rights", project_id, action.model_dump(mode="json"))
        if not repository.corpus_existing("rights", project_id, identity):
            _require_parent(
                repository, "rights", project_id, source_id, action.previous_rights_id
            )
        repository.corpus_insert(
            "rights",
            {
                **scope,
                "rights_id": identity,
                "source_id": source_id,
                "previous_rights_id": action.previous_rights_id,
                "declaration": action.model_dump(mode="json"),
            },
        )
        return {"rights_id": identity, "source_id": source_id}
    if isinstance(action, FreezeCorpusSnapshot):
        identity = corpus_identity(
            "snapshot", project_id, action.model_dump(mode="json")
        )
        if not repository.corpus_existing("snapshot", project_id, identity):
            _require_parent(
                repository,
                "snapshot",
                project_id,
                source_id,
                action.previous_snapshot_id,
            )
            if (
                repository.corpus_latest("rights", project_id, source_id)
                != action.rights_id
            ):
                raise KernelError(
                    "CORPUS_RIGHTS_NOT_ELIGIBLE",
                    "freeze requires the current declaration from this source",
                )
        repository.corpus_insert(
            "snapshot",
            {
                **scope,
                "snapshot_id": identity,
                "source_id": source_id,
                "rights_id": action.rights_id,
                "previous_snapshot_id": action.previous_snapshot_id,
                "manifest": action.manifest.model_dump(mode="json"),
                "acquisition": action.acquisition.model_dump(mode="json"),
                "repository_snapshot_asset_version_id": action.acquisition.repository_snapshot_asset_version_id,
            },
        )
        return {
            "snapshot_id": identity,
            "rights_id": action.rights_id,
            "source_id": source_id,
        }
    if not isinstance(action, ImportCorpusBatch):
        raise ValueError("unsupported corpus action")
    results = []
    for entry in sorted(
        action.entries,
        key=lambda item: (item.external_work_id, item.external_edition_id),
    ):
        book_id = corpus_identity("book", source_id, entry.external_work_id)
        repository.corpus_insert(
            "book_identity",
            {
                **scope,
                "source_id": source_id,
                "book_source_id": book_id,
                "external_work_id": entry.external_work_id,
            },
        )
        edition_id = corpus_identity(
            "edition", action.snapshot_id, book_id, entry.external_edition_id
        )
        edition = repository.corpus_insert(
            "edition",
            {
                **scope,
                "source_id": source_id,
                "snapshot_id": action.snapshot_id,
                "book_source_id": book_id,
                "edition_id": edition_id,
                **entry.model_dump(mode="json", exclude={"external_work_id"}),
            },
        )
        result = _decision(
            repository, scope, source, edition, CorpusPurpose(source["purpose"])
        )
        if result["admission"]["decision"] == "ALLOW":
            membership_id = corpus_identity("membership", edition_id, source["purpose"])
            if not repository.corpus_existing("membership", project_id, membership_id):
                repository.corpus_insert(
                    "membership",
                    {
                        **scope,
                        "membership_id": membership_id,
                        "edition_id": edition_id,
                        "purpose": source["purpose"],
                        "decision_id": result["decision_id"],
                        "decision": "ALLOW",
                    },
                )
            result["membership_id"] = membership_id
        results.append({**result, "book_source_id": book_id})
    return {
        "snapshot_id": action.snapshot_id,
        "entries": results,
        "source_id": source_id,
    }


def _require_parent(
    repository: SourceAuthorityRepository,
    kind: str,
    project: str,
    source: str,
    previous: str | None,
) -> None:
    if repository.corpus_latest(kind, project, source) != previous:
        raise KernelError(
            "CORPUS_REVISION_INVALID",
            f"{kind} parent is not the current source revision",
        )


def _decision(
    repository: SourceAuthorityRepository,
    scope: dict[str, str],
    source: dict[str, Any],
    edition: dict[str, Any],
    purpose: CorpusPurpose,
) -> dict[str, Any]:
    snapshot = repository.corpus_record(
        "snapshot", scope["project_id"], edition["snapshot_id"]
    )
    frozen = repository.corpus_record(
        "rights", scope["project_id"], snapshot["rights_id"]
    )
    rights = RightsDeclaration.model_validate(frozen["declaration"])
    latest = repository.corpus_latest(
        "rights", scope["project_id"], source["source_id"]
    )
    decision = corpus_admission(
        rights=rights,
        source_purpose=CorpusPurpose(source["purpose"]),
        requested_purpose=purpose,
        retired=source["retired"],
        rights_current=latest == frozen["rights_id"],
        external_work_id=repository.corpus_record("book_identity", scope["project_id"], edition["book_source_id"])["external_work_id"],
    )
    decision_id = corpus_identity(
        "admission", scope["created_by_operation_id"], edition["edition_id"], purpose
    )
    evidence = {
        **decision,
        "snapshot_id": snapshot["snapshot_id"],
        "rights_id": frozen["rights_id"],
        "current_rights_id": latest,
        "evidence_refs": list(rights.evidence_refs),
        "dataset_license": rights.dataset_license,
        "underlying_rights": rights.underlying_rights.value,
        "source_purpose": source["purpose"],
        "source_retired": source["retired"],
    }
    repository.corpus_insert(
        "admission",
        {
            **scope,
            "decision_id": decision_id,
            "edition_id": edition["edition_id"],
            "rights_id": frozen["rights_id"],
            "purpose": purpose.value,
            "decision": decision["decision"],
            "evidence": evidence,
        },
    )
    return {
        "source_id": source["source_id"],
        "edition_id": edition["edition_id"],
        "decision_id": decision_id,
        "admission": evidence,
    }
