from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.book_design_authority.domain import (
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    WORK_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignPayload,
)
from novel_forge.modules.book_design_authority.foundation import (
    FoundationBinding,
    FoundationRole,
    QualifiedFoundationSet,
    foundation_upstream_digest,
)
from novel_forge.modules.book_design_authority.foundation_validation import (
    validate_foundation_layer,
)
from novel_forge.modules.book_design_authority.formation_domain import (
    FormationLayerInput,
    StoryFormationInput,
    StoryFormationStage,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority import GENERATOR_DESIGN_SCOPE


_STAGE_ROLE = {
    StoryFormationStage.CREATIVE_FOUNDATION: FoundationRole.CREATIVE_FOUNDATION,
    StoryFormationStage.THEME_CONTRACT: FoundationRole.THEME_CONTRACT,
    StoryFormationStage.ENDING_INTENT: FoundationRole.ENDING_INTENT,
    StoryFormationStage.READER_PROMISE: FoundationRole.READER_PROMISE,
    StoryFormationStage.WORLD_BIBLE: FoundationRole.WORLD_BIBLE,
    StoryFormationStage.CHARACTER_CAST: FoundationRole.CHARACTER_CAST,
}


class StoryFormationRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def create(
        self,
        *,
        formation_run_id: str,
        project_id: str,
        workspace_id: str,
        book_id: str,
        root_operation_id: str,
        stable_idempotency_key: str,
        expected_book_version: int,
        formation_policy_version: str,
        frozen_input: StoryFormationInput,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT formation_run_id, frozen_input_digest
            FROM authority_story_formation_run
            WHERE project_id=%s AND book_id=%s AND stable_idempotency_key=%s
            """,
            [project_id, book_id, stable_idempotency_key],
        )
        existing = self.cursor.fetchone()
        if existing is not None:
            if str(existing[0]) != formation_run_id or str(existing[1]) != frozen_input.digest:
                raise KernelError(
                    "STORY_FORMATION_IDEMPOTENCY_CONFLICT",
                    "Formation idempotency key was reused with different frozen inputs",
                )
            return self.require(formation_run_id)
        self.cursor.execute(
            """
            SELECT version
            FROM authority_book
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
            FOR SHARE
            """,
            [project_id, workspace_id, book_id],
        )
        book = self.cursor.fetchone()
        if book is None or int(book[0]) != expected_book_version:
            raise KernelError(
                "STORY_FORMATION_BOOK_VERSION_CONFLICT",
                "Formation must freeze the current Book version",
            )
        author_selected = (frozen_input.generation_policy or {}).get("author_creative_foundation")
        if author_selected:
            self.authored_creative_layer(project_id=project_id, book_id=book_id, **author_selected)
        self.cursor.execute(
            """
            INSERT INTO authority_story_formation_run(
                formation_run_id, project_id, workspace_id, book_id,
                root_operation_id, stable_idempotency_key, expected_book_version,
                lifecycle, current_stage, formation_policy_version,
                frozen_stage_inputs, frozen_input_digest,
                book_design_asset_version_id, book_design_content_hash
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,'ADMITTED','CREATIVE_SEARCH',%s,%s,%s,%s,%s
            )
            """,
            [
                formation_run_id,
                project_id,
                workspace_id,
                book_id,
                root_operation_id,
                stable_idempotency_key,
                expected_book_version,
                formation_policy_version,
                Jsonb(frozen_input.to_dict()),
                frozen_input.digest,
                frozen_input.book_design_asset_version_id or None,
                frozen_input.book_design_content_hash or None,
            ],
        )
        for role, layer in frozen_input.by_role.items():
            stage = StoryFormationStage(role.value)
            self.cursor.execute(
                """
                INSERT INTO authority_story_formation_stage(
                    formation_stage_id, formation_run_id, stage,
                    attempt_ordinal, status, generation_operation_id,
                    candidate_asset_version_id, candidate_content_hash,
                    qualification_evidence_asset_version_id, qualification_hash,
                    activation_operation_id, binding, checkpoint
                ) VALUES (%s,%s,%s,1,'PENDING',%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    str(uuid4()),
                    formation_run_id,
                    stage.value,
                    layer.generation_operation_id,
                    layer.asset_version_id,
                    layer.content_hash,
                    layer.qualification_evidence_asset_version_id,
                    layer.qualification_hash,
                    layer.activation_operation_id,
                    Jsonb({}),
                    Jsonb(
                        {
                            "candidate_asset_version_ids": list(
                                layer.candidate_asset_version_ids
                            ),
                            "selection_reason": list(layer.selection_reason),
                        }
                    ),
                ],
            )
        return self.require(formation_run_id)

    def advance_one(
        self,
        formation_run_id: str,
        operation_id: str,
        *,
        expected_stage: str,
        expected_version: int,
        generated_layer: FormationLayerInput | None = None,
        generated_book_design: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT project_id, book_id, lifecycle, current_stage,
                   frozen_stage_inputs, frozen_input_digest,
                   book_design_asset_version_id, book_design_content_hash,
                   version
            FROM authority_story_formation_run
            WHERE formation_run_id=%s
            FOR UPDATE
            """,
            [formation_run_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("STORY_FORMATION_NOT_FOUND", "Formation run is missing")
        if str(row[2]) in {"READY", "ABORTED"}:
            return self.require(formation_run_id)
        if str(row[2]) not in {"ADMITTED", "RUNNING"}:
            raise KernelError(
                "STORY_FORMATION_NOT_RUNNABLE",
                "Formation is not in a restartable lifecycle",
            )
        if str(row[3]) != expected_stage or int(row[8]) != expected_version:
            raise KernelError(
                "STORY_FORMATION_JOB_STALE",
                "Formation RuntimeJob does not match its frozen stage/version",
            )
        frozen = StoryFormationInput.from_mapping(dict(row[4]))
        if frozen.digest != str(row[5]):
            raise KernelError(
                "STORY_FORMATION_FROZEN_INPUT_DRIFT",
                "persisted Formation input no longer matches its digest",
            )
        stage = StoryFormationStage(str(row[3]))
        if generated_layer is not None:
            expected_role = FoundationRole.CREATIVE_FOUNDATION if stage is StoryFormationStage.CREATIVE_SEARCH else _STAGE_ROLE.get(stage)
            if not frozen.creative_brief_asset_version_id or generated_layer.role is not expected_role:
                raise KernelError("STORY_FORMATION_GENERATED_LAYER_SCOPE", "Generated layer does not belong to this frozen stage")
            self._record_generated_layer(formation_run_id, generated_layer)
        if stage is StoryFormationStage.CREATIVE_SEARCH:
            selected = self.stage_input(formation_run_id, FoundationRole.CREATIVE_FOUNDATION) if frozen.creative_brief_asset_version_id else frozen.by_role[FoundationRole.CREATIVE_FOUNDATION]
            self._record_creative_search(formation_run_id, selected)
            next_stage = StoryFormationStage.CREATIVE_FOUNDATION
        elif stage in _STAGE_ROLE:
            role = _STAGE_ROLE[stage]
            self._bind_layer(
                formation_run_id=formation_run_id,
                project_id=str(row[0]),
                book_id=str(row[1]),
                layer=self.stage_input(formation_run_id, role) if frozen.creative_brief_asset_version_id else frozen.by_role[role],
            )
            next_stage = StoryFormationStage(
                {
                    FoundationRole.CREATIVE_FOUNDATION: "THEME_CONTRACT",
                    FoundationRole.THEME_CONTRACT: "ENDING_INTENT",
                    FoundationRole.ENDING_INTENT: "READER_PROMISE",
                    FoundationRole.READER_PROMISE: "WORLD_BIBLE",
                    FoundationRole.WORLD_BIBLE: "CHARACTER_CAST",
                    FoundationRole.CHARACTER_CAST: "BOOK_DESIGN",
                }[role]
            )
        elif stage is StoryFormationStage.BOOK_DESIGN:
            if generated_book_design is not None:
                if not frozen.creative_brief_asset_version_id or set(generated_book_design) != {"asset_version_id", "content_hash"}:
                    raise KernelError("STORY_FORMATION_DESIGN_INPUT_INVALID", "Generated design must bind the exact brief Formation")
                row = list(row)
                row[6], row[7] = generated_book_design["asset_version_id"], generated_book_design["content_hash"]
            if not str(row[6] or "") or not str(row[7] or ""):
                self.cursor.execute(
                    """
                    UPDATE authority_story_formation_run
                    SET lifecycle='WAITING_APPROVAL', version=version+1,
                        updated_at=NOW()
                    WHERE formation_run_id=%s AND version=%s
                    """,
                    [formation_run_id, int(row[8])],
                )
                if self.cursor.rowcount != 1:
                    raise KernelError(
                        "STORY_FORMATION_VERSION_CONFLICT",
                        "Formation changed before its BookDesign approval wait",
                    )
                return self.require(formation_run_id)
            foundation = self._require_book_design(
                project_id=str(row[0]),
                book_id=str(row[1]),
                asset_version_id=str(row[6]),
                content_hash=str(row[7]),
            )
            self.cursor.execute(
                """
                UPDATE authority_story_formation_run
                SET lifecycle='READY', current_stage='COMPLETE',
                    foundation_set_digest=%s, book_design_asset_version_id=%s, book_design_content_hash=%s, version=version+1, updated_at=NOW()
                WHERE formation_run_id=%s AND version=%s
                """,
                [foundation.set_digest, row[6], row[7], formation_run_id, int(row[8])],
            )
            return self.require(formation_run_id)
        else:
            return self.require(formation_run_id)
        self.cursor.execute(
            """
            UPDATE authority_story_formation_run
            SET lifecycle='RUNNING', current_stage=%s,
                version=version+1, updated_at=NOW()
            WHERE formation_run_id=%s AND version=%s
            """,
            [next_stage.value, formation_run_id, int(row[8])],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "STORY_FORMATION_VERSION_CONFLICT",
                "Formation stage changed concurrently",
            )
        return self.require(formation_run_id)

    def bind_book_design(
        self,
        formation_run_id: str,
        *,
        expected_version: int,
        asset_version_id: str,
        content_hash: str,
        operation_id: str,
    ) -> dict[str, Any]:
        """INVARIANT: Close Formation with an independently approved Foundation-bound BookDesign.

        Foundation layers must already be current. The BookDesign remains
        owned and activated by Book Design Authority; this method only freezes
        that exact Authority version into coordinator lineage.
        """
        self.cursor.execute(
            """
            SELECT project_id, book_id, lifecycle, current_stage, version
            FROM authority_story_formation_run
            WHERE formation_run_id=%s
            FOR UPDATE
            """,
            [formation_run_id],
        )
        row = self.cursor.fetchone()
        if (
            row is None
            or str(row[2]) != "WAITING_APPROVAL"
            or str(row[3]) != StoryFormationStage.BOOK_DESIGN.value
            or int(row[4]) != expected_version
        ):
            raise KernelError(
                "STORY_FORMATION_BOOK_DESIGN_APPROVAL_CONFLICT",
                "Formation is not waiting for BookDesign at the expected version",
            )
        foundation = self._require_book_design(
            project_id=str(row[0]),
            book_id=str(row[1]),
            asset_version_id=asset_version_id,
            content_hash=content_hash,
        )
        self.cursor.execute(
            """
            SELECT last_operation_id
            FROM authority_book
            WHERE project_id=%s AND book_id=%s
              AND current_book_design_asset_version_id=%s
            """,
            [str(row[0]), str(row[1]), asset_version_id],
        )
        design_activation = self.cursor.fetchone()
        if design_activation is None or not str(design_activation[0] or ""):
            raise KernelError(
                "STORY_FORMATION_BOOK_DESIGN_ACTIVATION_MISSING",
                "BookDesign has no authoritative activation operation lineage",
            )
        design_activation_operation_id = str(design_activation[0])
        self.cursor.execute(
            """
            UPDATE authority_story_formation_run
            SET lifecycle='READY', current_stage='COMPLETE',
                book_design_asset_version_id=%s,
                book_design_content_hash=%s,
                foundation_set_digest=%s,
                version=version+1, updated_at=NOW()
            WHERE formation_run_id=%s AND version=%s
              AND lifecycle='WAITING_APPROVAL'
              AND current_stage='BOOK_DESIGN'
            """,
            [
                asset_version_id,
                content_hash,
                foundation.set_digest,
                formation_run_id,
                expected_version,
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "STORY_FORMATION_BOOK_DESIGN_APPROVAL_CONFLICT",
                "BookDesign approval raced with another Formation transition",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_story_formation_stage(
                formation_stage_id, formation_run_id, stage, attempt_ordinal,
                status, candidate_asset_version_id, candidate_content_hash,
                activation_operation_id, binding, checkpoint
            ) VALUES (%s,%s,'BOOK_DESIGN',1,'ACTIVE',%s,%s,%s,%s,%s)
            ON CONFLICT (formation_run_id, stage, attempt_ordinal) DO UPDATE
            SET status='ACTIVE',
                candidate_asset_version_id=EXCLUDED.candidate_asset_version_id,
                candidate_content_hash=EXCLUDED.candidate_content_hash,
                activation_operation_id=EXCLUDED.activation_operation_id,
                binding=EXCLUDED.binding,
                checkpoint=EXCLUDED.checkpoint,
                updated_at=NOW()
            WHERE authority_story_formation_stage.status IN (
                'PENDING','WAITING_APPROVAL'
            )
            """,
            [
                str(uuid4()),
                formation_run_id,
                asset_version_id,
                content_hash,
                design_activation_operation_id,
                Jsonb(
                    {
                        "authority": "BOOK_DESIGN_AUTHORITY",
                        "asset_version_id": asset_version_id,
                        "content_hash": content_hash,
                        "foundation_set_digest": foundation.set_digest,
                    }
                ),
                Jsonb(
                    {
                        "book_design_activation_operation_id": (
                            design_activation_operation_id
                        ),
                        "formation_binding_operation_id": operation_id,
                    }
                ),
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "STORY_FORMATION_BOOK_DESIGN_STAGE_CONFLICT",
                "BookDesign Formation evidence was already committed differently",
            )
        return self.require(formation_run_id)

    def wait_for_approval(
        self,
        formation_run_id: str,
        *,
        operation_id: str,
        expected_stage: str,
        expected_version: int,
        authority: str,
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        candidate_asset_version_ids: tuple[str, ...],
        runtime_attempt_id: str,
    ) -> dict[str, Any]:
        try:
            stage = StoryFormationStage(expected_stage)
        except ValueError as exc:
            raise KernelError(
                "STORY_FORMATION_APPROVAL_TARGET_INVALID",
                "approval wait has an unknown Formation stage",
            ) from exc
        if (
            authority not in {"STORY_PLANNING_AUTHORITY", "BOOK_DESIGN_AUTHORITY"}
            or not candidate_asset_version_id.strip()
            or len(candidate_content_hash) != 71
            or not candidate_content_hash.startswith("sha256:")
            or not candidate_asset_version_ids
            or candidate_asset_version_id not in candidate_asset_version_ids
            or len(set(candidate_asset_version_ids)) != len(candidate_asset_version_ids)
            or not runtime_attempt_id.strip()
        ):
            raise KernelError(
                "STORY_FORMATION_APPROVAL_TARGET_INVALID",
                "approval wait is not bound to an exact candidate and runtime attempt",
            )
        self.cursor.execute(
            """
            SELECT project_id,lifecycle,current_stage,version,recovery_instruction
            FROM authority_story_formation_run
            WHERE formation_run_id=%s
            FOR UPDATE
            """,
            [formation_run_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("STORY_FORMATION_NOT_FOUND", "Formation run is missing")
        approval = {
            "action": "APPROVE_EXACT_CANDIDATE_AND_RESUME",
            "formation_run_id": formation_run_id,
            "stage": stage.value,
            "authority": authority,
            "candidate_asset_version_id": candidate_asset_version_id,
            "candidate_content_hash": candidate_content_hash,
            "candidate_asset_version_ids": list(candidate_asset_version_ids),
            "wait_operation_id": operation_id,
            "runtime_attempt_id": runtime_attempt_id,
        }
        if str(row[1]) == "WAITING_APPROVAL":
            existing = dict(row[4] or {})
            comparable = {
                key: value
                for key, value in approval.items()
                if key not in {"wait_operation_id", "runtime_attempt_id"}
            }
            current = {
                key: existing.get(key)
                for key in comparable
            }
            if current != comparable:
                raise KernelError(
                    "STORY_FORMATION_APPROVAL_TARGET_DRIFT",
                    "Formation is already waiting on a different exact candidate",
                )
            return self.require(formation_run_id)
        if (
            str(row[1]) not in {"ADMITTED", "RUNNING"}
            or str(row[2]) != stage.value
            or int(row[3]) != expected_version
        ):
            raise KernelError(
                "STORY_FORMATION_APPROVAL_WAIT_CONFLICT",
                "Formation changed before its approval wait was committed",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_story_formation_stage(
                formation_stage_id,formation_run_id,stage,attempt_ordinal,status,
                candidate_asset_version_id,candidate_content_hash,binding,checkpoint
            ) VALUES (%s,%s,%s,1,'WAITING_APPROVAL',%s,%s,%s,%s)
            ON CONFLICT (formation_run_id,stage,attempt_ordinal) DO UPDATE
            SET status='WAITING_APPROVAL',
                candidate_asset_version_id=EXCLUDED.candidate_asset_version_id,
                candidate_content_hash=EXCLUDED.candidate_content_hash,
                checkpoint=authority_story_formation_stage.checkpoint || EXCLUDED.checkpoint,
                updated_at=NOW()
            WHERE authority_story_formation_stage.status IN ('PENDING','RUNNING')
              AND (
                authority_story_formation_stage.candidate_asset_version_id IS NULL
                OR authority_story_formation_stage.candidate_asset_version_id=
                   EXCLUDED.candidate_asset_version_id
              )
            """,
            [
                str(uuid4()),
                formation_run_id,
                stage.value,
                candidate_asset_version_id,
                candidate_content_hash,
                Jsonb({"authority": authority}),
                Jsonb({"approval_wait": approval}),
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "STORY_FORMATION_APPROVAL_TARGET_DRIFT",
                "Formation stage already contains a different approval target",
            )
        self.cursor.execute(
            """
            UPDATE authority_story_formation_run
            SET lifecycle='WAITING_APPROVAL',failure='{}'::jsonb,
                recovery_instruction=%s,version=version+1,updated_at=NOW()
            WHERE formation_run_id=%s AND version=%s
              AND lifecycle IN ('ADMITTED','RUNNING') AND current_stage=%s
            """,
            [Jsonb(approval), formation_run_id, expected_version, stage.value],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "STORY_FORMATION_APPROVAL_WAIT_CONFLICT",
                "Formation changed before its approval wait was committed",
            )
        return self.require(formation_run_id)

    def fail(
        self, formation_run_id: str, *, error: dict[str, Any], operation_id: str
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_story_formation_run
            SET lifecycle='FAILED', failure=%s,
                recovery_instruction=%s, version=version+1, updated_at=NOW()
            WHERE formation_run_id=%s AND lifecycle IN ('ADMITTED','RUNNING')
            """,
            [
                Jsonb(error),
                Jsonb(
                    {
                        "action": "RESUME_WITH_SAME_FROZEN_INPUTS",
                        "formation_run_id": formation_run_id,
                        "failed_operation_id": operation_id,
                    }
                ),
                formation_run_id,
            ],
        )

    def record_author_decision(
        self, formation_run_id: str, *, expected_version: int,
        candidate_asset_version_id: str, candidate_content_hash: str,
        decision: str, reason: str, actor_id: str, operation_id: str,
    ) -> dict[str, Any]:
        self.cursor.execute(
            "SELECT version,lifecycle,current_stage,recovery_instruction FROM "
            "authority_story_formation_run WHERE formation_run_id=%s FOR UPDATE",
            [formation_run_id],
        )
        row = self.cursor.fetchone()
        if row is None or int(row[0]) != expected_version or row[1] != "WAITING_APPROVAL":
            raise KernelError("STORY_FORMATION_REVIEW_CONFLICT", "Formation review version changed")
        approval = dict(row[3] or {})
        if candidate_asset_version_id not in approval.get("candidate_asset_version_ids", []):
            raise KernelError("STORY_FORMATION_REVIEW_SCOPE", "Candidate is outside the frozen comparison")
        if decision not in {"SELECT", "APPROVE", "REJECT", "REQUEST_CHANGES"} or not reason.strip():
            raise ValueError("Author decision and content-based reason are required")
        self.cursor.execute(
            "SELECT version.content_hash FROM authority_asset_version version "
            "JOIN authority_asset asset ON asset.asset_id=version.asset_id "
            "JOIN authority_story_formation_run run ON run.project_id=asset.project_id "
            "WHERE run.formation_run_id=%s AND version.asset_version_id=%s",
            [formation_run_id, candidate_asset_version_id],
        )
        asset = self.cursor.fetchone()
        if asset is None or str(asset[0]) != candidate_content_hash:
            raise KernelError("STORY_FORMATION_REVIEW_HASH_DRIFT", "Review target content changed")
        entry = dict(candidate_asset_version_id=candidate_asset_version_id,
                     candidate_content_hash=candidate_content_hash, decision=decision,
                     reason=reason, actor_id=actor_id, operation_id=operation_id)
        if decision in {"SELECT", "APPROVE"}:
            approval.update(candidate_asset_version_id=candidate_asset_version_id,
                            candidate_content_hash=candidate_content_hash,
                            author_selection=entry)
        elif candidate_asset_version_id == approval.get("candidate_asset_version_id"):
            approval["author_selection"] = entry
        self.cursor.execute(
            "UPDATE authority_story_formation_stage SET candidate_asset_version_id=%s, "
            "candidate_content_hash=%s, checkpoint=checkpoint || %s || "
            "jsonb_build_object('author_decisions', COALESCE(checkpoint->'author_decisions','[]'::jsonb) || %s), "
            "updated_at=NOW() WHERE formation_run_id=%s AND stage=%s AND attempt_ordinal=1 "
            "AND status='WAITING_APPROVAL'",
            [approval["candidate_asset_version_id"], approval["candidate_content_hash"],
             Jsonb({"approval_wait": approval}), Jsonb([entry]), formation_run_id, str(row[2])],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("STORY_FORMATION_REVIEW_CONFLICT", "Formation stage changed")
        self.cursor.execute(
            "UPDATE authority_story_formation_run SET recovery_instruction=%s, version=version+1, "
            "updated_at=NOW() WHERE formation_run_id=%s AND version=%s",
            [Jsonb(approval), formation_run_id, expected_version],
        )
        return self.require(formation_run_id)

    def author_selection(self, formation_run_id: str, stage: str) -> dict[str, Any]:
        self.cursor.execute(
            "SELECT checkpoint->'approval_wait'->'author_selection' FROM "
            "authority_story_formation_stage WHERE formation_run_id=%s AND stage=%s AND attempt_ordinal=1",
            [formation_run_id, stage],
        )
        row = self.cursor.fetchone()
        return dict(row[0] or {}) if row else {}

    def resume(self, formation_run_id: str, expected_version: int) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT project_id,book_id,lifecycle,current_stage,version,
                   recovery_instruction
            FROM authority_story_formation_run
            WHERE formation_run_id=%s
            FOR UPDATE
            """,
            [formation_run_id],
        )
        waiting = self.cursor.fetchone()
        if (
            waiting is not None
            and str(waiting[2]) == "WAITING_APPROVAL"
            and int(waiting[4]) == expected_version
        ):
            approval = dict(waiting[5] or {})
            candidate_id = str(approval.get("candidate_asset_version_id") or "")
            candidate_hash = str(approval.get("candidate_content_hash") or "")
            authority = str(approval.get("authority") or "")
            if dict(approval.get("author_selection") or {}).get("decision") in {"REJECT", "REQUEST_CHANGES"}:
                raise KernelError("STORY_FORMATION_AUTHOR_CHANGES_PENDING", "Select and approve an acceptable candidate before resuming")
            if authority == "STORY_PLANNING_AUTHORITY":
                self.cursor.execute(
                    """
                    SELECT version.content_hash,state.approval,
                           state.updated_by_operation_id
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    JOIN authority_story_design_version_state AS state
                      ON state.project_id=asset.project_id
                     AND state.asset_version_id=version.asset_version_id
                    WHERE asset.project_id=%s AND version.asset_version_id=%s
                    """,
                    [str(waiting[0]), candidate_id],
                )
                decision = self.cursor.fetchone()
                satisfied = bool(
                    decision is not None
                    and str(decision[0]) == candidate_hash
                    and str(decision[1]) == "APPROVED"
                    and str(decision[2] or "")
                )
            elif authority == "BOOK_DESIGN_AUTHORITY":
                self.cursor.execute(
                    """
                    SELECT version.content_hash,book.last_operation_id
                    FROM authority_book AS book
                    JOIN authority_asset_version AS version
                      ON version.asset_version_id=book.current_book_design_asset_version_id
                    WHERE book.project_id=%s AND book.book_id=%s
                      AND book.current_book_design_asset_version_id=%s
                    """,
                    [str(waiting[0]), str(waiting[1]), candidate_id],
                )
                decision = self.cursor.fetchone()
                satisfied = bool(
                    decision is not None
                    and str(decision[0]) == candidate_hash
                    and str(decision[1] or "")
                )
            else:
                satisfied = False
            if not satisfied:
                raise KernelError(
                    "STORY_FORMATION_APPROVAL_PENDING",
                    "the exact frozen Formation candidate is not approved yet",
                )
        self.cursor.execute(
            """
            UPDATE authority_story_formation_run
            SET lifecycle='RUNNING', failure='{}'::jsonb,
                recovery_instruction='{}'::jsonb,
                version=version+1, updated_at=NOW()
            WHERE formation_run_id=%s
              AND lifecycle IN ('FAILED','WAITING_APPROVAL') AND version=%s
            """,
            [formation_run_id, expected_version],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "STORY_FORMATION_RESUME_CONFLICT",
                "Formation is not failed or approved at the expected version",
            )
        return self.require(formation_run_id)

    def abort(self, formation_run_id: str, expected_version: int) -> dict[str, Any]:
        self.cursor.execute(
            """
            UPDATE authority_story_formation_run
            SET lifecycle='ABORTED', version=version+1, updated_at=NOW()
            WHERE formation_run_id=%s
              AND lifecycle IN ('ADMITTED','RUNNING','FAILED','WAITING_APPROVAL')
              AND version=%s
            """,
            [formation_run_id, expected_version],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "STORY_FORMATION_ABORT_CONFLICT",
                "Formation cannot abort at the expected version",
            )
        return self.require(formation_run_id)

    def require(self, formation_run_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT formation_run_id, project_id, workspace_id, book_id,
                   root_operation_id, lifecycle, current_stage,
                   formation_policy_version, frozen_input_digest,
                   COALESCE(foundation_set_digest, ''), version,
                   failure, recovery_instruction, book_design_asset_version_id,
                   book_design_content_hash, expected_book_version, frozen_stage_inputs
            FROM authority_story_formation_run
            WHERE formation_run_id=%s
            """,
            [formation_run_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("STORY_FORMATION_NOT_FOUND", "Formation run is missing")
        names = (
            "formation_run_id",
            "project_id",
            "workspace_id",
            "book_id",
            "root_operation_id",
            "lifecycle",
            "current_stage",
            "formation_policy_version",
            "frozen_input_digest",
            "foundation_set_digest",
            "version",
            "failure",
            "recovery_instruction",
            "book_design_asset_version_id",
            "book_design_content_hash",
            "expected_book_version",
            "frozen_input",
        )
        return dict(zip(names, row, strict=True))

    def stage_input(self, formation_run_id: str, role: FoundationRole) -> FormationLayerInput:
        self.cursor.execute(
            "SELECT checkpoint->'generated_layer' FROM authority_story_formation_stage WHERE formation_run_id=%s AND stage=%s AND attempt_ordinal=1",
            [formation_run_id, role.value],
        )
        row = self.cursor.fetchone()
        if row is None or not row[0]:
            raise KernelError("STORY_FORMATION_STAGE_INPUT_MISSING", "Generated stage has no committed input")
        return FormationLayerInput.from_mapping(dict(row[0]))

    def _record_generated_layer(self, formation_run_id: str, layer: FormationLayerInput) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_story_formation_stage(
                formation_stage_id, formation_run_id, stage, attempt_ordinal, status,
                generation_operation_id, candidate_asset_version_id, candidate_content_hash,
                qualification_evidence_asset_version_id, qualification_hash,
                activation_operation_id, binding, checkpoint
            ) VALUES (%s,%s,%s,1,'PENDING',%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (formation_run_id, stage, attempt_ordinal) DO UPDATE
            SET status='PENDING',
                generation_operation_id=EXCLUDED.generation_operation_id,
                candidate_asset_version_id=EXCLUDED.candidate_asset_version_id,
                candidate_content_hash=EXCLUDED.candidate_content_hash,
                qualification_evidence_asset_version_id=
                    EXCLUDED.qualification_evidence_asset_version_id,
                qualification_hash=EXCLUDED.qualification_hash,
                activation_operation_id=EXCLUDED.activation_operation_id,
                checkpoint=authority_story_formation_stage.checkpoint ||
                    EXCLUDED.checkpoint,
                updated_at=NOW()
            WHERE authority_story_formation_stage.status='WAITING_APPROVAL'
              AND authority_story_formation_stage.candidate_asset_version_id=
                  EXCLUDED.candidate_asset_version_id
            """,
            [str(uuid4()), formation_run_id, layer.role.value, layer.generation_operation_id,
             layer.asset_version_id, layer.content_hash, layer.qualification_evidence_asset_version_id,
             layer.qualification_hash, layer.activation_operation_id, Jsonb({}),
             Jsonb({"generated_layer": layer.to_dict()})],
        )
        if self.stage_input(formation_run_id, layer.role) != layer:
            raise KernelError("STORY_FORMATION_STAGE_INPUT_DRIFT", "A retry cannot replace the committed generated layer")

    def generated_layer(self, *, project_id: str, book_id: str, candidate_id: str, candidates: tuple[str, ...], reasons: tuple[str, ...]) -> FormationLayerInput:
        self.cursor.execute(
            """
            SELECT generation.generator_operation_name, version.content_hash, version.schema_version,
                   generation.operation_id, qualification.evaluation_asset_version_id,
                   evidence.content_hash, active.activated_by_operation_id
            FROM authority_story_planning_generation AS generation
            JOIN authority_asset_version AS version ON version.asset_version_id=generation.candidate_asset_version_id
            JOIN authority_narrative_design_qualification AS qualification
              ON qualification.generation_operation_id=generation.operation_id
             AND qualification.asset_version_id=version.asset_version_id
            JOIN authority_asset_version AS evidence ON evidence.asset_version_id=qualification.evaluation_asset_version_id
            JOIN authority_story_design_active_version AS active
              ON active.project_id=generation.project_id AND active.asset_version_id=version.asset_version_id
            WHERE generation.project_id=%s AND generation.book_id=%s
              AND generation.candidate_asset_version_id=%s AND qualification.qualification_status='PASS'
            ORDER BY qualification.design_layer LIMIT 16
            """,
            [project_id, book_id, candidate_id],
        )
        rows = self.cursor.fetchall()
        unique = set(tuple(str(value) for value in row) for row in rows)
        supervised = len(unique) != 1
        if supervised:
            from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt
            approved = approved_design_receipt(self.cursor, project_id=project_id, book_id=book_id, asset_version_id=candidate_id)
            if approved is None or approved["lifecycle"] != "ACTIVE":
                raise KernelError("FOUNDATION_GENERATION_EVIDENCE_REQUIRED", "Foundation needs independent qualification or exact supervised author approval")
            self.cursor.execute("""SELECT generation.generator_operation_name, version.content_hash, version.schema_version,
                generation.operation_id, active.activated_by_operation_id
                FROM authority_story_planning_generation generation JOIN authority_asset_version version
                  ON version.asset_version_id=generation.candidate_asset_version_id
                JOIN authority_story_design_active_version active ON active.project_id=generation.project_id
                  AND active.asset_version_id=version.asset_version_id
                WHERE generation.project_id=%s AND generation.book_id=%s AND generation.candidate_asset_version_id=%s""",
                [project_id, book_id, candidate_id])
            native = self.cursor.fetchone()
            if native is None:
                raise KernelError("FOUNDATION_GENERATION_EVIDENCE_REQUIRED", "Supervised Foundation lost its native generation")
            row = (*native[:4], approved["decision_asset_version_id"], approved["decision_content_hash"], native[4])
        else:
            row = unique.pop()
        layer = FormationLayerInput(
            role=FoundationRole(GENERATOR_DESIGN_SCOPE[row[0]].value), asset_version_id=candidate_id,
            content_hash=row[1], schema_version=row[2], generation_operation_id=row[3],
            qualification_evidence_asset_version_id=row[4], qualification_hash=row[5],
            activation_operation_id=row[6], candidate_asset_version_ids=candidates, selection_reason=reasons,
            selection_basis="AUTHOR_COMPARISON" if supervised else "INDEPENDENT_COMPARISON",
        )
        self._require_qualification(project_id, layer)
        return layer

    def authored_creative_layer(self, *, project_id: str, book_id: str, asset_version_id: str, content_hash: str) -> FormationLayerInput:
        from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt
        approved = approved_design_receipt(self.cursor, project_id=project_id, book_id=book_id, asset_version_id=asset_version_id)
        self.cursor.execute("""SELECT state.source_kind,state.execution_evidence,version.schema_version,active.activated_by_operation_id,
            version.content->>'routing_eligibility',state.generator_operation_name
            FROM authority_story_design_version_state state JOIN authority_asset_version version USING(asset_version_id)
            JOIN authority_story_design_active_version active ON active.project_id=state.project_id AND active.asset_version_id=state.asset_version_id
            WHERE state.project_id=%s AND state.asset_version_id=%s""", [project_id, asset_version_id])
        row = self.cursor.fetchone()
        if (approved is None or approved["lifecycle"] != "ACTIVE" or approved["content_hash"] != content_hash
                or row is None or row[0] != "OPERATOR_AUTHORED" or row[4] == "BENCHMARK_ONLY"
                or row[5] != "creative.candidates.generate"):
            raise KernelError("FORMATION_AUTHOR_INPUT_REQUIRED", "Formation needs exact native original author input; diagnostic candidates cannot be promoted")
        return FormationLayerInput(role=FoundationRole.CREATIVE_FOUNDATION, asset_version_id=asset_version_id,
            content_hash=content_hash, schema_version=row[2], generation_operation_id=row[1]["authoring_operation_id"],
            qualification_evidence_asset_version_id=approved["decision_asset_version_id"], qualification_hash=approved["decision_content_hash"],
            activation_operation_id=row[3], candidate_asset_version_ids=(asset_version_id,),
            selection_reason=(approved["author_review"]["reason"],), selection_basis="AUTHOR_DIRECTION")

    def _record_creative_search(
        self, formation_run_id: str, selected: FormationLayerInput
    ) -> None:
        requested = tuple(selected.candidate_asset_version_ids)
        self.cursor.execute(
            """
            SELECT state.asset_version_id, state.design_scope,
                   state.qualification, state.freshness,
                   version.lifecycle, version.eligibility, version.governance,
                   active.asset_version_id
            FROM authority_story_design_version_state AS state
            JOIN authority_asset_version AS version
              ON version.asset_version_id=state.asset_version_id
            LEFT JOIN authority_story_design_active_version AS active
              ON active.project_id=state.project_id
             AND active.asset_version_id=state.asset_version_id
            WHERE state.asset_version_id=ANY(%s)
            """,
            [list(requested)],
        )
        rows = {str(row[0]): row for row in self.cursor.fetchall()}
        if selected.selection_basis != "INDEPENDENT_COMPARISON":
            from novel_forge.modules.story_design_authority.author_supervision import candidate_supervision, approved_design_receipt
            self.cursor.execute("SELECT project_id,book_id FROM authority_story_formation_run WHERE formation_run_id=%s", [formation_run_id])
            project_id, book_id = self.cursor.fetchone()
            if set(rows) != set(requested):
                raise KernelError("CREATIVE_SEARCH_CANDIDATE_EVIDENCE_INVALID", "Author comparison cannot refer to missing candidates")
            for identity, row in rows.items():
                supervised = candidate_supervision(self.cursor, project_id=project_id, asset_version_id=identity)
                if (supervised is None or supervised["book_id"] != book_id or row[2] not in {"STRUCTURALLY_VALID", "SEMANTICALLY_VALID"}
                        or row[3] != "CURRENT" or row[6] != "CLEAR"):
                    raise KernelError("CREATIVE_SEARCH_CANDIDATE_EVIDENCE_INVALID", "Author comparison requires exact technically valid same-Book inputs")
            approved = approved_design_receipt(self.cursor, project_id=project_id, book_id=book_id, asset_version_id=selected.asset_version_id)
            if approved is None or approved["lifecycle"] != "ACTIVE":
                raise KernelError("CREATIVE_SEARCH_SELECTION_DRIFT", "Selected author input must have native approval and activation")
            if selected.selection_basis == "AUTHOR_DIRECTION":
                checked = self.authored_creative_layer(project_id=project_id, book_id=book_id,
                    asset_version_id=selected.asset_version_id, content_hash=selected.content_hash)
                if checked != selected or len(requested) != 1:
                    raise KernelError("CREATIVE_SEARCH_SELECTION_DRIFT", "Author direction is one exact approved original input")
        else:
            if set(rows) != set(requested) or any(
                tuple(str(item) for item in row[1:4])
                != (FoundationRole.CREATIVE_FOUNDATION.value, "QUALIFIED", "CURRENT")
                or str(row[4]) not in {"CANDIDATE", "ACTIVE"}
                or tuple(str(item) for item in row[5:7]) != ("ELIGIBLE", "CLEAR")
                for row in rows.values()
            ):
                raise KernelError(
                    "CREATIVE_SEARCH_CANDIDATE_EVIDENCE_INVALID",
                    "Creative Search candidates require qualified immutable Story Design evidence",
                )
        if str(rows[selected.asset_version_id][7] or "") != selected.asset_version_id:
            raise KernelError(
                "CREATIVE_SEARCH_SELECTION_DRIFT",
                "selected Creative Foundation is not the exact active Authority version",
            )
        # INVARIANT: comparison lineage is neither Planning scope nor Story authority.
        self.cursor.execute(
            """
            INSERT INTO authority_story_formation_stage(
                formation_stage_id, formation_run_id, stage, attempt_ordinal,
                status, generation_operation_id, candidate_asset_version_id,
                candidate_content_hash, qualification_evidence_asset_version_id,
                qualification_hash, activation_operation_id, binding, checkpoint
            ) VALUES (%s,%s,'CREATIVE_SEARCH',1,'ACTIVE',%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (formation_run_id, stage, attempt_ordinal) DO UPDATE
            SET status='ACTIVE',
                generation_operation_id=EXCLUDED.generation_operation_id,
                candidate_asset_version_id=EXCLUDED.candidate_asset_version_id,
                candidate_content_hash=EXCLUDED.candidate_content_hash,
                qualification_evidence_asset_version_id=
                    EXCLUDED.qualification_evidence_asset_version_id,
                qualification_hash=EXCLUDED.qualification_hash,
                activation_operation_id=EXCLUDED.activation_operation_id,
                binding=EXCLUDED.binding,
                checkpoint=authority_story_formation_stage.checkpoint ||
                    EXCLUDED.checkpoint,
                updated_at=NOW()
            WHERE authority_story_formation_stage.status='WAITING_APPROVAL'
              AND authority_story_formation_stage.candidate_asset_version_id=
                  EXCLUDED.candidate_asset_version_id
            """,
            [
                str(uuid4()),
                formation_run_id,
                selected.generation_operation_id,
                selected.asset_version_id,
                selected.content_hash,
                selected.qualification_evidence_asset_version_id,
                selected.qualification_hash,
                selected.activation_operation_id,
                Jsonb(
                    {
                        "candidate_asset_version_ids": list(
                            selected.candidate_asset_version_ids
                        ),
                        "selected_asset_version_id": selected.asset_version_id,
                        "selection_reason": list(selected.selection_reason),
                    }
                ),
                Jsonb({"comparison": "FROZEN", **({"selection_basis": selected.selection_basis, "literary_qualification": "NOT_PROVEN"} if selected.selection_basis != "INDEPENDENT_COMPARISON" else {})}),
            ],
        )

    def _bind_layer(
        self,
        *,
        formation_run_id: str,
        project_id: str,
        book_id: str,
        layer: FormationLayerInput,
    ) -> None:
        self.cursor.execute(
            """
            SELECT asset.asset_type, version.content, version.content_hash,
                   version.schema_version, version.lifecycle,
                   version.eligibility, version.governance,
                   state.generator_operation_name, state.design_scope,
                   state.lifecycle, state.qualification, state.approval,
                   state.freshness, active.activated_by_operation_id,
                   state.execution_evidence
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            JOIN authority_story_design_version_state AS state
              ON state.project_id=asset.project_id
             AND state.asset_version_id=version.asset_version_id
            JOIN authority_story_design_active_version AS active
              ON active.project_id=state.project_id
             AND active.asset_version_id=state.asset_version_id
            WHERE asset.project_id=%s AND version.asset_version_id=%s
            FOR SHARE
            """,
            [project_id, layer.asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "FOUNDATION_ACTIVE_DESIGN_REQUIRED",
                f"{layer.role.value} is not an active Story Design version",
            )
        generator = str(row[7])
        expected_scope = GENERATOR_DESIGN_SCOPE.get(generator)
        if (
            str(row[2]) != layer.content_hash
            or str(row[3]) != layer.schema_version
            or tuple(str(item) for item in row[4:7])
            != ("ACTIVE", "ELIGIBLE", "CLEAR")
            or expected_scope is None
            or expected_scope.value != layer.role.value
            or str(row[8]) != layer.role.value
            or tuple(str(item) for item in row[9:13])
            != ("ACTIVE", "SEMANTICALLY_VALID" if dict(row[14]).get("author_supervision", {}).get("mode") == "AUTHOR_SUPERVISED" else "QUALIFIED", "APPROVED", "CURRENT")
            or str(row[13]) != layer.activation_operation_id
            or str(dict(row[14]).get("operation_id") or "")
            != layer.generation_operation_id
        ):
            raise KernelError(
                "FOUNDATION_ACTIVE_DESIGN_DRIFT",
                f"{layer.role.value} active/qualification/generation lineage drifted",
            )
        self._require_qualification(project_id, layer)
        parents = self._current_parent_bindings(
            project_id=project_id, book_id=book_id, role=layer.role
        )
        self._require_generation_parent_inputs(layer, parents)
        parent_contents = self._parent_contents(project_id, parents)
        content = dict(row[1])
        layer_payload = content.get("candidate_payload")
        if not isinstance(layer_payload, dict) or not layer_payload:
            raise KernelError(
                "FOUNDATION_AUTHORITY_ENVELOPE_INVALID",
                f"{layer.role.value} is not a schema-backed Story Design candidate",
            )
        validation = validate_foundation_layer(
            role=layer.role,
            content=layer_payload,
            parent_bindings=parents,
            parent_contents=parent_contents,
        )
        upstream_digest = foundation_upstream_digest(parents) if parents else ""
        self._mark_impacted_descendants(
            project_id=project_id,
            book_id=book_id,
            changed_role=layer.role,
            replacement_asset_version_id=layer.asset_version_id,
        )
        self.cursor.execute(
            """
            UPDATE authority_book_foundation_binding
            SET freshness='STALE', retired_at=NOW()
            WHERE project_id=%s AND book_id=%s AND foundation_role=%s
              AND freshness='CURRENT' AND retired_at IS NULL
            """,
            [project_id, book_id, layer.role.value],
        )
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(set_generation) FILTER (
                       WHERE formation_run_id=%s
                   ), 0),
                   COALESCE(MAX(set_generation), 0)
            FROM authority_book_foundation_binding
            WHERE project_id=%s AND book_id=%s
            """,
            [formation_run_id, project_id, book_id],
        )
        run_generation, book_generation = (
            int(item) for item in self.cursor.fetchone()
        )
        generation = run_generation or book_generation + 1
        self.cursor.execute(
            """
            INSERT INTO authority_book_foundation_binding(
                foundation_binding_id, formation_run_id, project_id, book_id,
                set_generation, foundation_role, authority_name,
                asset_version_id, content_hash, schema_version,
                qualification_evidence_asset_version_id, qualification_hash,
                activation_operation_id, upstream_digest, freshness
            ) VALUES (%s,%s,%s,%s,%s,%s,'STORY_DESIGN_AUTHORITY',%s,%s,%s,%s,%s,%s,
                      NULLIF(%s,''),'CURRENT')
            """,
            [
                str(uuid4()),
                formation_run_id,
                project_id,
                book_id,
                generation,
                layer.role.value,
                layer.asset_version_id,
                layer.content_hash,
                layer.schema_version,
                layer.qualification_evidence_asset_version_id,
                layer.qualification_hash,
                layer.activation_operation_id,
                upstream_digest,
            ],
        )
        self.cursor.execute(
            """
            UPDATE authority_story_formation_stage
            SET status='ACTIVE', upstream_digest=NULLIF(%s,''),
                binding=%s, checkpoint=checkpoint || %s, updated_at=NOW()
            WHERE formation_run_id=%s AND stage=%s AND attempt_ordinal=1
              AND status='PENDING'
            """,
            [
                upstream_digest,
                Jsonb(
                    FoundationBinding(
                        role=layer.role,
                        authority="STORY_DESIGN_AUTHORITY",
                        asset_version_id=layer.asset_version_id,
                        content_hash=layer.content_hash,
                        schema_version=layer.schema_version,
                        qualification_evidence_asset_version_id=(
                            layer.qualification_evidence_asset_version_id
                        ),
                        qualification_hash=layer.qualification_hash,
                        activation_id=layer.activation_operation_id,
                        upstream_digest=upstream_digest,
                    ).to_dict()
                ),
                Jsonb(validation),
                formation_run_id,
                layer.role.value,
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "STORY_FORMATION_STAGE_CONFLICT",
                f"{layer.role.value} Formation stage already changed",
            )

    def _mark_impacted_descendants(
        self,
        *,
        project_id: str,
        book_id: str,
        changed_role: FoundationRole,
        replacement_asset_version_id: str,
    ) -> None:
        """INVARIANT: Invalidate only future bindings that depend on a replaced parent.

        Immutable AssetVersions and accepted history remain untouched.  A
        repeated Formation using the same version is harmless; a changed
        parent makes every current descendant unusable until rebound through
        the governed sequence.
        """
        self.cursor.execute(
            """
            SELECT asset_version_id
            FROM authority_book_foundation_binding
            WHERE project_id=%s AND book_id=%s AND foundation_role=%s
              AND freshness='CURRENT' AND retired_at IS NULL
            """,
            [project_id, book_id, changed_role.value],
        )
        existing = self.cursor.fetchone()
        if existing is None or str(existing[0]) == replacement_asset_version_id:
            return
        descendants = [
            role.value
            for role in FoundationRole
            if changed_role in role.required_parents
        ]
        if not descendants:
            return
        self.cursor.execute(
            """
            UPDATE authority_book_foundation_binding
            SET freshness='IMPACTED', retired_at=NOW()
            WHERE project_id=%s AND book_id=%s
              AND foundation_role=ANY(%s)
              AND freshness='CURRENT' AND retired_at IS NULL
            """,
            [project_id, book_id, descendants],
        )

    def _require_qualification(
        self, project_id: str, layer: FormationLayerInput
    ) -> None:
        self.cursor.execute(
            """
            SELECT version.content_hash, version.lifecycle, version.eligibility,
                   version.governance, version.content,
                   output.operation_id, operation.status
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            LEFT JOIN authority_operation_output_asset AS output
              ON output.asset_version_id=version.asset_version_id
            LEFT JOIN authority_operation AS operation
              ON operation.operation_id=output.operation_id
            WHERE asset.project_id=%s AND version.asset_version_id=%s
            """,
            [project_id, layer.qualification_evidence_asset_version_id],
        )
        row = self.cursor.fetchone()
        evidence = dict(row[4]) if row is not None else {}
        qualification = evidence.get("qualification")
        if evidence.get("evidence", {}).get("author_supervision", {}).get("mode") == "AUTHOR_SUPERVISED":
            from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt
            scope = evidence["evidence"]["author_supervision"]
            approved = approved_design_receipt(self.cursor, project_id=project_id, book_id=scope["book_id"], asset_version_id=layer.asset_version_id)
            if (approved is None or approved["decision_asset_version_id"] != layer.qualification_evidence_asset_version_id
                    or approved["decision_content_hash"] != layer.qualification_hash or approved["content_hash"] != layer.content_hash):
                raise KernelError("FOUNDATION_AUTHOR_REVIEW_DRIFT", "Author approval no longer identifies the exact Foundation")
            return
        if (
            row is None
            or tuple(str(item) for item in row[:4])
            != (layer.qualification_hash, "ACTIVE", "ELIGIBLE", "CLEAR")
            or evidence.get("schema_version") != "narrative-design-evaluation.v1"
            or evidence.get("candidate_asset_version_id") != layer.asset_version_id
            or evidence.get("candidate_content_hash") != layer.content_hash
            or evidence.get("generation_operation_id")
            != layer.generation_operation_id
            or str(evidence.get("evaluation_operation_id") or "") != str(row[5] or "")
            or str(row[6] or "") != "SUCCEEDED"
            or str(row[5] or "") == layer.generation_operation_id
            or not isinstance(qualification, dict)
            or qualification.get("status") != "PASS"
        ):
            raise KernelError(
                "FOUNDATION_QUALIFICATION_DRIFT",
                f"{layer.role.value} independent qualification evidence drifted",
            )

    def _current_parent_bindings(
        self, *, project_id: str, book_id: str, role: FoundationRole
    ) -> tuple[FoundationBinding, ...]:
        if not role.required_parents:
            return ()
        self.cursor.execute(
            """
            SELECT foundation_role, authority_name, asset_version_id, content_hash,
                   schema_version, qualification_evidence_asset_version_id,
                   qualification_hash, activation_operation_id,
                   COALESCE(upstream_digest, '')
            FROM authority_book_foundation_binding
            WHERE project_id=%s AND book_id=%s
              AND foundation_role=ANY(%s)
              AND freshness='CURRENT' AND retired_at IS NULL
            """,
            [project_id, book_id, [item.value for item in role.required_parents]],
        )
        by_role = {
            FoundationRole(str(row[0])): FoundationBinding(
                role=FoundationRole(str(row[0])),
                authority=str(row[1]),
                asset_version_id=str(row[2]),
                content_hash=str(row[3]),
                schema_version=str(row[4]),
                qualification_evidence_asset_version_id=str(row[5]),
                qualification_hash=str(row[6]),
                activation_id=str(row[7]),
                upstream_digest=str(row[8]),
            )
            for row in self.cursor.fetchall()
        }
        if set(by_role) != set(role.required_parents):
            raise KernelError(
                "FOUNDATION_PARENT_SET_INCOMPLETE",
                f"{role.value} cannot activate before its exact parents",
            )
        return tuple(by_role[item] for item in role.required_parents)

    def _require_generation_parent_inputs(
        self,
        layer: FormationLayerInput,
        parents: tuple[FoundationBinding, ...],
    ) -> None:
        if not parents:
            return
        self.cursor.execute(
            """
            SELECT input_asset_snapshot
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [layer.generation_operation_id],
        )
        row = self.cursor.fetchone()
        snapshot = row[0] if row is not None else None
        if not isinstance(snapshot, list):
            raise KernelError(
                "FOUNDATION_GENERATION_LINEAGE_MISSING",
                f"{layer.role.value} generation has no frozen parent inputs",
            )
        frozen = {
            (str(item.get("asset_version_id") or ""), str(item.get("content_hash") or ""))
            for item in snapshot
            if isinstance(item, dict)
        }
        expected = {(item.asset_version_id, item.content_hash) for item in parents}
        if not expected.issubset(frozen):
            raise KernelError(
                "FOUNDATION_GENERATION_LINEAGE_DRIFT",
                f"{layer.role.value} was not generated against its current exact parents",
            )

    def _parent_contents(
        self, project_id: str, parents: tuple[FoundationBinding, ...]
    ) -> dict[FoundationRole, dict[str, Any]]:
        result: dict[FoundationRole, dict[str, Any]] = {}
        for parent in parents:
            self.cursor.execute(
                """
                SELECT version.content, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND version.asset_version_id=%s
                """,
                [project_id, parent.asset_version_id],
            )
            row = self.cursor.fetchone()
            if row is None or str(row[1]) != parent.content_hash:
                raise KernelError(
                    "FOUNDATION_PARENT_CONTENT_DRIFT",
                    f"{parent.role.value} content no longer matches its binding",
                )
            content = dict(row[0])
            payload = content.get("candidate_payload")
            if not isinstance(payload, dict) or not payload:
                raise KernelError(
                    "FOUNDATION_AUTHORITY_ENVELOPE_INVALID",
                    f"{parent.role.value} is not a schema-backed Story Design candidate",
                )
            result[parent.role] = {
                **payload,
                "asset_version_id": parent.asset_version_id,
                "content_hash": parent.content_hash,
            }
        return result

    def _require_book_design(
        self,
        *,
        project_id: str,
        book_id: str,
        asset_version_id: str,
        content_hash: str,
    ) -> QualifiedFoundationSet:
        from novel_forge.storage.foundation_repositories import (
            require_current_foundation_set,
        )

        foundation = require_current_foundation_set(
            self.cursor, project_id=project_id, book_id=book_id
        )
        self.cursor.execute(
            """
            SELECT version.content, version.content_hash, version.schema_version,
                   version.lifecycle, version.eligibility, version.governance,
                   book.current_book_design_asset_version_id
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            JOIN authority_book AS book
              ON book.project_id=asset.project_id AND book.book_id=%s
            WHERE asset.project_id=%s AND asset.asset_type='book_design'
              AND version.asset_version_id=%s
            """,
            [book_id, project_id, asset_version_id],
        )
        row = self.cursor.fetchone()
        if (
            row is None
            or str(row[1]) != content_hash
            or str(row[2]) not in {FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION, WORK_BOOK_DESIGN_SCHEMA_VERSION}
            or tuple(str(item) for item in row[3:6])
            != (
                "ACTIVE",
                "ELIGIBLE",
                "CLEAR",
            )
            or str(row[6]) != asset_version_id
        ):
            raise KernelError(
                "STORY_FORMATION_BOOK_DESIGN_REQUIRED",
                "Formation requires the exact active qualified Foundation-bound BookDesign",
            )
        design = BookDesignPayload.from_mapping(dict(row[0]))
        if design.foundation_set != foundation:
            raise KernelError(
                "BOOK_DESIGN_FOUNDATION_SET_STALE",
                "BookDesign does not bind the current qualified Foundation Set",
            )
        return foundation


__all__ = ["StoryFormationRepository"]
