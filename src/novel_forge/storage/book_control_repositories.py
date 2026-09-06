from __future__ import annotations

from typing import Any

from novel_forge.modules.book_authority.control_policy import (
    CONTROL_BOUNDARIES,
    CONTROL_POLICY_OWNER,
    ControlPolicy,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.storage.versioned_policy_repository import VersionedPolicyRepository


def control_decision_ref(
    book_run_id: str,
    chapter_number: int,
    boundary: str,
    subject_version_id: str,
    policy_hash: str,
) -> str:
    return (
        "book_control/decisions/"
        + narrative_hash(
            [book_run_id, chapter_number, boundary, subject_version_id, policy_hash]
        ).removeprefix("sha256:")
        + ".json"
    )


class BookControlRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def book_scope(self, book_run_id: str, *, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            "SELECT book_id, workspace_id, accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE",
            [book_run_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_CONTROL_SCOPE_INVALID",
                "Editorial control requires its owned Book run",
            )
        return {
            "book_id": str(row[0]),
            "workspace_id": str(row[1]),
            "accepted_through_chapter": int(row[2]),
        }

    def freeze(
        self, *, project_id: str, book_run_id: str, chapter_number: int, actor_id: str
    ) -> dict[str, Any]:
        self.book_scope(book_run_id, project_id=project_id)
        if chapter_number <= 0:
            raise KernelError(
                "BOOK_CONTROL_FRONTIER_INVALID",
                "Control binding requires a positive chapter frontier",
            )
        return VersionedPolicyRepository(
            self.cursor, owner=CONTROL_POLICY_OWNER, project_id=project_id
        ).freeze(
            subject_id=f"{book_run_id}:chapter:{chapter_number}",
            default=ControlPolicy().to_dict(),
            actor_id=actor_id,
        )

    def current_decision(
        self, *, project_id: str, logical_ref: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT v.asset_version_id, v.content_hash, v.content FROM authority_asset_version v
            JOIN authority_asset a ON a.asset_id=v.asset_id
            JOIN authority_asset_locator locator ON locator.current_asset_version_id=v.asset_version_id AND locator.project_id=a.project_id
            JOIN authority_operation_output_asset output ON output.asset_version_id=v.asset_version_id
            JOIN authority_operation operation ON operation.operation_id=output.operation_id
            WHERE a.project_id=%s AND locator.logical_ref=%s AND a.asset_type='editorial_decision_evidence'
              AND v.lifecycle='ACTIVE' AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR'
              AND operation.definition_name='book.control.decide' AND operation.status='SUCCEEDED'
            ORDER BY v.created_at DESC LIMIT 1
        """,
            [project_id, logical_ref],
        )
        row = self.cursor.fetchone()
        return (
            {
                "asset_version_id": str(row[0]),
                "content_hash": str(row[1]),
                "content": dict(row[2]),
            }
            if row
            else None
        )

    def subject(self, *, project_id: str, version_id: str) -> dict[str, str]:
        self.cursor.execute(
            "SELECT v.content_hash FROM authority_asset_version v JOIN authority_asset a ON a.asset_id=v.asset_id WHERE v.asset_version_id=%s AND a.project_id=%s",
            [version_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_CONTROL_SUBJECT_UNKNOWN",
                "Editorial decision must bind an exact owned artifact",
            )
        return {"asset_version_id": version_id, "content_hash": str(row[0])}

    def require_approval(
        self,
        *,
        project_id: str,
        book_run_id: str,
        chapter_number: int,
        actor_id: str,
        boundary: str,
        subject_version_id: str,
    ) -> tuple[dict[str, str], ...]:
        snapshot = self.freeze(
            project_id=project_id,
            book_run_id=book_run_id,
            chapter_number=chapter_number,
            actor_id=actor_id,
        )
        policy = ControlPolicy(**snapshot["policy"])
        if not policy.requires(boundary):
            return ()
        ref = control_decision_ref(
            book_run_id,
            chapter_number,
            boundary,
            subject_version_id,
            snapshot["policy_hash"],
        )
        decision = self.current_decision(project_id=project_id, logical_ref=ref)
        if decision is None or decision["content"]["decision"] != "APPROVE":
            raise KernelError(
                "BOOK_CONTROL_APPROVAL_REQUIRED",
                f"{boundary} requires an operator decision for {subject_version_id} under {policy.policy_version}",
            )
        return (
            {
                "asset_version_id": decision["asset_version_id"],
                "content_hash": decision["content_hash"],
            },
        )

    def require_planning_approval(
        self,
        *,
        project_id: str,
        book_id: str,
        contract_type: str,
        subject_version_id: str,
        actor_id: str,
    ) -> tuple[dict[str, str], ...]:
        self.cursor.execute(
            "SELECT book_run_id, accepted_through_chapter FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state NOT IN ('COMPLETED','ABORTED') ORDER BY book_run_id FOR UPDATE",
            [project_id, book_id],
        )
        books = self.cursor.fetchall()
        boundaries = (
            ("CHAPTER", "SCENE")
            if contract_type == "CHAPTER"
            else ("NEAR_TERM" if contract_type == "CHAPTER_GROUP" else contract_type,)
        )
        return tuple(
            ref
            for run_id, frontier in books
            for boundary in boundaries
            for ref in self.require_approval(
                project_id=project_id,
                book_run_id=str(run_id),
                chapter_number=int(frontier) + 1,
                actor_id=actor_id,
                boundary=boundary,
                subject_version_id=subject_version_id,
            )
        )

    def causal_subjects(
        self, *, project_id: str, book_run_id: str, chapter_number: int, subject_version_id: str = ""
    ) -> dict[str, str]:
        from novel_forge.storage.causal_planning_repositories import (
            CausalPlanningRepository,
        )
        from novel_forge.modules.canon_graph.background import world_action_boundaries
        self.cursor.execute("""
            SELECT v.asset_version_id, v.content_hash, v.content->'contract', source.content->'contract'
            FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            JOIN authority_asset_version source ON source.asset_version_id=v.content->'contract'->'source'->>'asset_version_id'
            JOIN authority_book_production book ON book.book_run_id=%s AND book.project_id=a.project_id
            WHERE a.project_id=%s AND a.asset_type='narrative_governance_action'
              AND v.content->'contract'->>'contract_version'='world-production-action.v1'
              AND v.content->'contract'->>'book_run_id'=book.book_run_id
              AND (v.content->'contract'->'world_plan'->>'chapter_number')::integer=%s
              AND source.content->'contract'->'request'->>'input_snapshot_id'=book.input_snapshot_id
              AND (source.content->'contract'->'request'->>'accepted_through_chapter')::integer=book.accepted_through_chapter
              AND (%s='' OR v.asset_version_id=%s)
            ORDER BY v.created_at DESC, v.asset_version_id DESC LIMIT 1
        """, [book_run_id, project_id, chapter_number, subject_version_id, subject_version_id])
        automatic = self.cursor.fetchone()
        if automatic:
            binding = dict(zip(("asset_version_id", "content_hash", "action", "frozen_source"), automatic, strict=True))
            return {boundary: str(automatic[0]) for boundary in world_action_boundaries(binding)}

        self.cursor.execute(
            "SELECT revision_id FROM authority_narrative_reality_revision WHERE book_run_id=%s AND project_id=%s AND chapter_number=%s",
            [book_run_id, project_id, chapter_number - 1],
        )
        row = self.cursor.fetchone()
        if row is None:
            return {}
        version = CausalPlanningRepository(self.cursor).current_action(
            project_id=project_id,
            book_run_id=book_run_id,
            reality_revision_id=str(row[0]),
            chapter_number=chapter_number,
        )
        if not version:
            return {}
        self.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
            [version],
        )
        plan = self.cursor.fetchone()[0]["causal_plan"]
        subjects = {"DIRECTOR": version}
        if any(
            candidate["candidate_id"] == plan["selected_candidate_id"]
            and candidate.get("risks")
            for candidate in plan["candidate_futures"]
        ):
            subjects["MAJOR_DECISION"] = version
        return subjects

    def readiness(self, *, project_id: str, book_run_id: str) -> dict[str, Any]:
        self.cursor.execute(
            "SELECT accepted_through_chapter, active_chapter_request_id, book_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s",
            [book_run_id, project_id],
        )
        book = self.cursor.fetchone()
        if book is None:
            raise KernelError(
                "BOOK_CONTROL_SCOPE_INVALID",
                "Book control query requires its project scope",
            )
        chapter = int(book[0]) + 1
        self.cursor.execute(
            """
            SELECT v.content, v.content_hash FROM authority_runtime_policy_version v
            WHERE v.owner=%s AND v.project_id=%s AND v.policy_version=COALESCE(
                (SELECT policy_version FROM authority_runtime_policy_binding WHERE owner=%s AND project_id=%s AND subject_id=%s),
                (SELECT policy_version FROM authority_runtime_policy_selection WHERE owner=%s AND project_id=%s))
        """,
            [
                CONTROL_POLICY_OWNER,
                project_id,
                CONTROL_POLICY_OWNER,
                project_id,
                f"{book_run_id}:chapter:{chapter}",
                CONTROL_POLICY_OWNER,
                project_id,
            ],
        )
        row = self.cursor.fetchone()
        from novel_forge.storage.versioned_policy_repository import policy_hash

        policy = ControlPolicy(**row[0]) if row else ControlPolicy()
        digest = str(row[1]) if row else policy_hash(policy.to_dict())
        subjects = self.causal_subjects(
            project_id=project_id, book_run_id=book_run_id, chapter_number=chapter
        )
        self.cursor.execute(
            "SELECT chapter_plan_version, chapter_root_operation_id, chapter_number FROM authority_book_chapter_request WHERE chapter_request_id=%s AND project_id=%s",
            [book[1], project_id],
        )
        request = self.cursor.fetchone()
        if request and int(request[2]) == chapter:
            subjects.update(CHAPTER=str(request[0]), SCENE=str(request[0]))
            self.cursor.execute(
                """
                SELECT a.asset_type, v.asset_version_id, v.content
                FROM authority_operation op
                JOIN authority_operation_output_asset output ON output.operation_id=op.operation_id
                JOIN authority_asset_version v ON v.asset_version_id=output.asset_version_id
                JOIN authority_asset a ON a.asset_id=v.asset_id
                WHERE op.project_id=%s AND op.status='SUCCEEDED' AND
                    ((op.root_operation_id=%s AND a.asset_type='release_package') OR
                     (op.causation_operation_id=%s AND a.asset_type='chapter_outcome'))
            """,
                [project_id, request[1], request[1]],
            )
            for kind, version, content in self.cursor.fetchall():
                boundary, subject = (
                    ("REALITY_COMMIT", str(version))
                    if kind == "chapter_outcome"
                    else ("FINAL_CANDIDATE", str(content["source_asset_version_id"]))
                )
                if boundary in subjects and subjects[boundary] != subject:
                    raise KernelError(
                        "BOOK_CONTROL_SUBJECT_AMBIGUOUS",
                        "Control query requires one exact selected candidate",
                    )
                subjects[boundary] = subject
        pending = [(boundary, subject) for boundary, subject in subjects.items()]
        if policy.mode == "REVIEW_PLAN":
            self.cursor.execute(
                """
                SELECT DISTINCT ON (s.logical_key) s.planning_scope, v.asset_version_id
                FROM authority_story_design_version_state s
                JOIN authority_asset_version v ON v.asset_version_id=s.asset_version_id
                WHERE s.project_id=%s AND v.content->>'book_id'=%s
                  AND s.planning_scope IN ('BOOK','VOLUME','ARC','CHAPTER_GROUP','CHAPTER')
                  AND s.qualification='QUALIFIED' AND s.freshness='CURRENT'
                  AND s.lifecycle NOT IN ('REJECTED','SUPERSEDED','ARCHIVED')
                  AND (s.lifecycle<>'ACTIVE' OR EXISTS (SELECT 1 FROM story_plan_binding b WHERE b.asset_version_id=v.asset_version_id AND b.execution_scope='PLANNED'))
                  AND NOT EXISTS (SELECT 1 FROM story_plan_binding b WHERE b.asset_version_id=v.asset_version_id AND b.execution_scope='EXECUTED')
                ORDER BY s.logical_key, v.created_at DESC, v.asset_version_id
            """,
                [project_id, str(book[2])],
            )
            for scope, version in self.cursor.fetchall():
                boundaries = (
                    ("CHAPTER", "SCENE")
                    if scope == "CHAPTER"
                    else ("NEAR_TERM" if scope == "CHAPTER_GROUP" else str(scope),)
                )
                pending.extend((boundary, str(version)) for boundary in boundaries)
        pending.extend(
            (boundary, "")
            for boundary in CONTROL_BOUNDARIES
            if boundary not in {item[0] for item in pending}
        )
        gates = []
        for boundary, subject in sorted(set(pending)):
            if not policy.requires(boundary):
                continue
            decision = (
                self.current_decision(
                    project_id=project_id,
                    logical_ref=control_decision_ref(
                        book_run_id, chapter, boundary, subject, digest
                    ),
                )
                if subject
                else None
            )
            gates.append(
                {
                    "boundary": boundary,
                    "subject_version_id": subject,
                    "decision_version_id": decision["asset_version_id"]
                    if decision
                    else "",
                    "status": decision["content"]["decision"]
                    if decision
                    else "WAITING_OPERATOR"
                    if subject
                    else "WAITING_SUBJECT",
                }
            )
        return {
            "contract_version": "book-control-readiness.v1",
            "project_id": project_id,
            "book_run_id": book_run_id,
            "chapter_number": chapter,
            "accepted_through_chapter": int(book[0]),
            "policy": policy.to_dict(),
            "policy_hash": digest,
            "gates": gates,
            "fact_mutation_allowed": False,
        }
