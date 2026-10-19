from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def selected_working_policy(uow, book, fallback, *, target_chapter=None):
    from .manuscript import _optional_document
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    from .working_prose import working_prose_policy

    selected = _optional_document(uow, book["project_id"], "book-working-policy/" + book["book_run_id"])
    if selected is None:
        return fallback
    profile = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=book["production_profile_version"])
    seen, frontier, revision = set(), book["current_chapter"], book["version"]
    while selected is not None:
        content = selected.content
        if (selected.asset_version_id in seen or selected.asset_type != "book_working_prose_policy"
                or content.get("version") != "book-working-prose-policy-selection.v1"
                or selected.lifecycle not in ({"ACTIVE"} if not seen else {"SUPERSEDED"})
                or selected.governance != "CLEAR" or selected.eligibility != "ELIGIBLE"
                or canonical_hash(content) != selected.content_hash
                or any(content.get(key) != book[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id"))
                or content.get("source_profile_version") != book["production_profile_version"]
                or content.get("source_profile_hash") != profile.content_hash
                or canonical_hash(profile.content) != profile.content_hash or profile.asset_type != "production_profile"
                or profile.governance != "CLEAR" or profile.eligibility != "ELIGIBLE"
                or type(content.get("effective_after_chapter")) is not int
                or not 0 <= content["effective_after_chapter"] <= frontier
                or type(content.get("source_book_version")) is not int or not 0 <= content["source_book_version"] < revision):
            raise KernelError("WORKING_PROSE_POLICY_SELECTION_DRIFT", "Future working policy must retain its exact Book, ordered selection lineage and frozen profile")
        policy = working_prose_policy(content)
        if policy is None:
            raise KernelError("WORKING_PROSE_POLICY_SELECTION_DRIFT", "A selected working policy cannot be empty")
        if target_chapter is None or target_chapter > content["effective_after_chapter"]:
            return policy
        seen.add(selected.asset_version_id)
        frontier, revision = content["effective_after_chapter"], content["source_book_version"]
        previous = content.get("previous_policy")
        if previous is None:
            return fallback
        if not isinstance(previous, dict) or set(previous) != {"asset_version_id", "content_hash"}:
            raise KernelError("WORKING_PROSE_POLICY_SELECTION_DRIFT", "Prior selection requires its exact immutable binding")
        selected = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=previous["asset_version_id"])
        if selected.content_hash != previous["content_hash"]:
            raise KernelError("WORKING_PROSE_POLICY_SELECTION_DRIFT", "Prior selection hash changed")
    return fallback


def select_working_policy(authority, book_run_id, *, policy, expected_version, idempotency_key, reason, principal):
    from novel_forge.modules.authority_security import PrincipalType
    from .manuscript import AUTHOR_WORKFLOW, _optional_document, _require_workflow_checkpoint, effective_workflow
    from .working_prose import working_prose_policy

    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise KernelError("WORKING_PROSE_AUTHOR_SELECTION_REQUIRED", "Only the authenticated local author/operator may choose future working inputs")
    policy = working_prose_policy({"working_prose_policy": policy})
    if policy is None or type(expected_version) is not int or not reason.strip() or not idempotency_key:
        raise KernelError("WORKING_PROSE_POLICY_SELECTION_INVALID", "Require an exact policy, checkpoint, reason and idempotency key")
    payload = {"expected_version": expected_version, "working_prose_policy": policy, "reason": reason}
    with AuthorityUnitOfWork(authority.database_url) as uow:
        uow.cursor.execute("""SELECT operation_id,command_payload,actor_id FROM authority_operation
            WHERE project_id=%s AND idempotency_scope='book:authority-mutation' AND idempotency_key=%s""", [book["project_id"], idempotency_key])
        previous = uow.cursor.fetchone()
        if previous:
            if previous[2] != principal.principal_id or previous[1].get("payload") != {
                    "action": "working_prose_policy_select", "book_run_id": book_run_id, **payload}:
                raise KernelError("WORKING_PROSE_POLICY_IDEMPOTENCY_CONFLICT", "A selection key retains its exact author, policy and checkpoint")
            result = uow.repositories.operations.transaction_result(previous[0], book["project_id"])
            if result["status"] != "SUCCEEDED":
                raise KernelError("WORKING_PROSE_POLICY_RECONCILIATION_REQUIRED", "Reconcile the original policy mutation")
            return {"operation_id": previous[0], "status": "SUCCEEDED", **result["result"], "replayed": True}

    def commit(uow, operation_id, checkpoint):
        current = _require_workflow_checkpoint(uow, book, expected_version, working_selection=True)
        if effective_workflow(uow.cursor, current) != AUTHOR_WORKFLOW:
            raise KernelError("WORKING_PROSE_AUTHOR_SELECTION_REQUIRED", "Future working selection requires this author-first Book")
        source = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=current["production_profile_version"])
        from novel_forge.modules.story_planning_runtime.domain import canonical_hash
        if (source.asset_type != "production_profile" or canonical_hash(source.content) != source.content_hash
                or source.governance != "CLEAR" or source.eligibility != "ELIGIBLE"):
            raise KernelError("WORKING_PROSE_POLICY_SELECTION_DRIFT", "Retain the exact governed production profile")
        previous = _optional_document(uow, book["project_id"], "book-working-policy/" + book_run_id)
        if previous:
            selected_working_policy(uow, current, None)
        content = {"version": "book-working-prose-policy-selection.v1",
            **{key: current[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id")},
            "source_profile_version": current["production_profile_version"], "source_profile_hash": source.content_hash,
            "source_book_version": expected_version,
            "effective_after_chapter": current["current_chapter"], "working_prose_policy": policy,
            "previous_policy": {"asset_version_id": previous.asset_version_id, "content_hash": previous.content_hash} if previous else None,
            "reason": reason, "existing_requests_rewritten": False}
        asset = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=book["project_id"], asset_id="book-working-policy:" + book_run_id,
            asset_type="book_working_prose_policy", schema_version=content["version"], logical_ref="book-working-policy/" + book_run_id,
            category="policy", output_key="book.working_prose_policy", role="primary", content=content,
            expected_current_asset_version_id=previous.asset_version_id if previous else None,
            qualification_policy="authenticated-book-policy.v1", trace_id=operation_id, correlation_id=book["root_operation_id"]))
        uow.cursor.execute("UPDATE authority_book_production SET version=version+1,updated_at=NOW() WHERE book_run_id=%s", [book_run_id])
        checkpoint("after_working_prose_policy_selection")
        return {"book_run_id": book_run_id, "policy_asset_version_id": asset.asset_version_id,
            "working_prose_policy": policy, "effective_after_chapter": current["current_chapter"], "state": current["state"]}

    return authority._execute_mutation(book=book, action="working_prose_policy_select", event_type="book.working_prose_policy.selected",
        idempotency_key=idempotency_key, actor_id=principal.principal_id, trace_id=idempotency_key,
        correlation_id=book["root_operation_id"], causation_id=book["root_operation_id"], payload=payload, handler=commit)
