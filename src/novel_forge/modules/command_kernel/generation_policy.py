from __future__ import annotations

from collections.abc import Iterable


def pure_generation_capabilities(capabilities: Iterable[str]) -> bool:
    values = tuple(capabilities)
    return bool(values) and all(value.startswith("model.") for value in values)


def pure_generation_operation(cursor, operation_id: str, project_id: str) -> bool:
    cursor.execute(
        """SELECT definition_snapshot->'external_capabilities'
        FROM authority_operation WHERE operation_id=%s AND project_id=%s""",
        [operation_id, project_id],
    )
    row = cursor.fetchone()
    return bool(row and pure_generation_capabilities(row[0] or ()))


def _reference_coordinator_roots(
    cursor, operation_id: str, project_id: str
) -> tuple[str, ...] | None:
    from .errors import KernelError

    cursor.execute(
        "SELECT definition_snapshot,workspace_id,root_operation_id FROM authority_operation WHERE operation_id=%s AND project_id=%s",
        [operation_id, project_id],
    )
    row = cursor.fetchone()
    if not row:
        return None
    snapshot, workspace, root_id = row
    if root_id != operation_id:
        return None
    if (
        snapshot.get("external_capabilities") != []
        or snapshot.get("irreversible_effect_policy", {}).get("allowed") is not False
        or snapshot.get("execution_mode") != "saga"
    ):
        return None
    policy = snapshot.get("policy", {})
    chapter = (
        snapshot.get("name") == "chapter.slice.run"
        and snapshot.get("family") == "chapter_authority"
        and snapshot.get("handler_key") == "novel_forge.chapter_authority.root"
        and snapshot.get("handler_contract_version") == "2.1.1"
        and snapshot.get("definition_version") in {
            "3.4.1", "3.5.0", "3.6.0", "3.7.0", "3.8.0", "3.9.0", "3.10.0",
            "3.10.0-author-first.v1", "3.10.0-working-revision.v1",
        }
        and policy.get("execution_classification") == "saga"
        and policy.get("authority") == "postgresql"
        and policy.get("orchestration") == "dynamic_fenced_saga_v1"
        and snapshot.get("completion_contract", {}).get("version")
        == "chapter.slice.run.completion.v1"
    )
    if chapter:
        cursor.execute(
            """SELECT op.saga_id,s.saga_id,s.project_id FROM authority_operation op
            LEFT JOIN authority_saga s ON s.root_operation_id=op.operation_id
            WHERE op.operation_id=%s AND op.project_id=%s""",
            [operation_id, project_id],
        )
        owner = cursor.fetchone()
        if not owner or (owner[0] or owner[1]) and (
            owner[0] != owner[1] or owner[2] != project_id
        ):
            raise KernelError(
                "GENERATION_COORDINATOR_SCOPE_INVALID",
                "Chapter coordinator differs from its native Saga",
            )
        return ()
    book = (
        snapshot.get("name") == "book.production.coordinate"
        and snapshot.get("family") == "book_authority"
        and snapshot.get("handler_key") == "novel_forge.book_authority.coordinator"
        and snapshot.get("handler_contract_version") == "book-authority-coordinator-v1"
        and policy.get("execution_classification") == "saga"
        and policy.get("chapter_authority_state_ownership") == "reference_only"
        and policy.get("persistent_checkpoint_required") is True
        and snapshot.get("completion_contract", {}).get("version")
        == "book.production.coordinate.completion.v1"
    )
    group = (
        snapshot.get("name") == "chapter_group.production.run"
        and snapshot.get("family") == "chapter_group_authority"
        and snapshot.get("handler_key")
        == "novel_forge.chapter_group_authority.chapter_group.production.run"
        and snapshot.get("handler_contract_version") == "chapter-group-step-handler-v1"
        and policy.get("chapter_execution_owner") == "chapter_authority"
        and policy.get("book_cursor_owner") == "book_authority"
        and policy.get("group_checkpoint_only") is True
        and snapshot.get("completion_contract", {}).get("version")
        == "chapter-group-root-completion-v1"
    )
    if not (book or group):
        return None
    if book:
        cursor.execute(
            """SELECT b.book_run_id FROM authority_book_production b
            WHERE b.root_operation_id=%s AND b.project_id=%s AND b.workspace_id=%s""",
            [operation_id, project_id, workspace],
        )
        owner = cursor.fetchone()
        if not owner:
            raise KernelError(
                "GENERATION_COORDINATOR_SCOPE_INVALID",
                "Book coordinator lacks its owning state",
            )
        cursor.execute(
            """SELECT r.chapter_root_operation_id,d.delegation_id
            FROM authority_book_chapter_request r LEFT JOIN authority_child_delegation d
              ON d.owner_id=r.book_run_id AND d.project_id=r.project_id AND d.chapter_request_id=r.chapter_request_id
              AND d.child_root_operation_id=r.chapter_root_operation_id AND d.child_saga_id=r.chapter_saga_id
              AND d.chapter_number=r.chapter_number AND d.plan_version_id=r.chapter_plan_version
              AND d.owner_authority='BOOK' AND d.child_authority='CHAPTER'
            WHERE r.book_run_id=%s AND r.project_id=%s""",
            [owner[0], project_id],
        )
        links = cursor.fetchall()
        roots = []
        cursor.execute(
            """SELECT g.root_operation_id FROM authority_chapter_group_production g
            JOIN authority_book_production b USING(book_run_id,project_id,book_id)
            WHERE g.book_run_id=%s AND g.project_id=%s AND b.workspace_id=%s""",
            [owner[0], project_id, workspace],
        )
        group_roots = tuple(r[0] for r in cursor.fetchall())
        for group_root in group_roots:
            group_references = _reference_coordinator_roots(
                cursor, group_root, project_id
            )
            if group_references is None:
                raise KernelError(
                    "GENERATION_COORDINATOR_REFERENCE_INVALID",
                    "Referenced Group lacks its native coordinator contract",
                )
            roots.extend((group_root, *group_references))
        cursor.execute(
            """SELECT f.operation_id FROM authority_book_followup_operation f
            JOIN authority_book_chapter_request r USING(chapter_request_id,book_run_id,project_id)
            WHERE f.book_run_id=%s AND f.project_id=%s
            UNION SELECT pg.operation_id FROM authority_story_planning_generation pg
            JOIN authority_story_narrative_search s ON s.search_id=pg.narrative_search_id
              AND s.project_id=pg.project_id AND s.workspace_id=pg.workspace_id AND s.book_id=pg.book_id
            WHERE s.book_run_id=%s AND s.project_id=%s AND s.workspace_id=%s
            UNION SELECT pg.operation_id FROM authority_story_planning_generation pg
            JOIN authority_operation op ON op.operation_id=pg.operation_id AND op.project_id=pg.project_id
              AND op.workspace_id=pg.workspace_id
            JOIN authority_book_production b ON b.book_run_id=op.command_payload #>> '{payload,world_preparation_request,book_run_id}'
              AND b.project_id=pg.project_id AND b.workspace_id=pg.workspace_id AND b.book_id=pg.book_id
            WHERE b.book_run_id=%s AND b.project_id=%s AND pg.generator_operation_name='chapter_plan.generate'""",
            [
                owner[0],
                project_id,
                owner[0],
                project_id,
                workspace,
                owner[0],
                project_id,
            ],
        )
        roots.extend(r[0] for r in cursor.fetchall())
    else:
        cursor.execute(
            """SELECT g.group_run_id,g.recap_operation_id FROM authority_chapter_group_production g
            JOIN authority_book_production b ON b.book_run_id=g.book_run_id AND b.project_id=g.project_id AND b.book_id=g.book_id
            WHERE g.root_operation_id=%s AND g.project_id=%s AND b.workspace_id=%s""",
            [operation_id, project_id, workspace],
        )
        owner = cursor.fetchone()
        if not owner:
            raise KernelError(
                "GENERATION_COORDINATOR_SCOPE_INVALID",
                "Group coordinator lacks its owning Book",
            )
        cursor.execute(
            """SELECT c.child_root_operation_id,d.delegation_id
            FROM authority_chapter_group_chapter c JOIN authority_chapter_group_production g USING(group_run_id)
            LEFT JOIN authority_book_chapter_request r ON r.chapter_request_id=c.chapter_request_id
              AND r.book_run_id=g.book_run_id AND r.project_id=g.project_id AND r.chapter_number=c.chapter_number
              AND r.chapter_plan_version=c.chapter_plan_version_id AND r.chapter_root_operation_id=c.child_root_operation_id
            LEFT JOIN authority_child_delegation d ON d.delegation_id=c.child_delegation_id
              AND d.owner_id=g.book_run_id AND d.project_id=g.project_id AND d.chapter_request_id=r.chapter_request_id
              AND d.child_root_operation_id=c.child_root_operation_id AND d.child_saga_id=r.chapter_saga_id
              AND d.chapter_number=r.chapter_number AND d.plan_version_id=r.chapter_plan_version
              AND d.owner_authority='BOOK' AND d.child_authority='CHAPTER'
            WHERE c.group_run_id=%s AND c.project_id=%s""",
            [owner[0], project_id],
        )
        links = cursor.fetchall()
        roots = [owner[1]] if owner[1] else []
    for root, delegation in links:
        if root and not delegation:
            raise KernelError(
                "GENERATION_COORDINATOR_REFERENCE_INVALID",
                "Referenced Chapter lacks its exact native delegation",
            )
        if root:
            roots.append(root)
    if roots:
        cursor.execute(
            "SELECT operation_id FROM authority_operation WHERE operation_id=ANY(%s) AND project_id=%s AND workspace_id=%s",
            [roots, project_id, workspace],
        )
        if set(roots) != {r[0] for r in cursor.fetchall()}:
            raise KernelError(
                "GENERATION_COORDINATOR_REFERENCE_INVALID",
                "Referenced execution is outside the owning scope",
            )
    return tuple(roots)


def generation_graph(cursor, operation_id: str, project_id: str) -> bool:
    cursor.execute(
        """SELECT op.root_operation_id FROM authority_operation op
        JOIN authority_operation root ON root.operation_id=op.root_operation_id
          AND root.project_id=op.project_id AND root.workspace_id IS NOT DISTINCT FROM op.workspace_id
        WHERE op.operation_id=%s AND op.project_id=%s""",
        [operation_id, project_id],
    )
    row = cursor.fetchone()
    if not row:
        return False
    root_id = row[0]
    references = _reference_coordinator_roots(cursor, root_id, project_id)
    roots = [root_id, *(references or ())]
    cursor.execute(
        """SELECT child.definition_snapshot->'external_capabilities',
                  child.definition_snapshot #> '{irreversible_effect_policy,allowed}'
        FROM authority_operation child
        WHERE (child.root_operation_id=ANY(%s) OR child.operation_id=ANY(%s)) AND child.project_id=%s""",
        [roots, roots, project_id],
    )
    rows = tuple(cursor.fetchall())
    capabilities = tuple(value for row in rows for value in (row[0] or ()))
    return (
        (
            references is not None
            or any(value.startswith("model.") for value in capabilities)
        )
        and all(
            value.startswith("model.") or value == "object_store.put"
            for value in capabilities
        )
        and not any(row[1] is True for row in rows)
    )
