from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.narrative_reality_repositories import (
    NarrativeRealityRepository,
)
from novel_forge.storage.foundation_repositories import require_current_foundation_set
from novel_forge.modules.book_design_authority.foundation import FoundationRole


class CausalPlanningRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def validate_candidate_references(
        self, *, reality: dict[str, Any], candidates: tuple[Any, ...]
    ) -> None:
        arc_refs = {ref for candidate in candidates for ref in candidate.arc_refs}
        self.cursor.execute(
            """
            SELECT binding.asset_version_id FROM story_plan_binding binding
            JOIN active_story_plan_version active ON active.binding_id=binding.binding_id
            WHERE binding.project_id=%s AND binding.book_id=%s
              AND binding.contract_type='ARC' AND binding.freshness='CURRENT'
              AND binding.asset_version_id=ANY(%s)
            """,
            [reality["project_id"], reality["book_id"], sorted(arc_refs)],
        )
        if arc_refs != {str(row[0]) for row in self.cursor.fetchall()}:
            raise KernelError(
                "CAUSAL_PLAN_ARC_SCOPE_INVALID",
                "candidate Arc references require exact current Arc Plan versions in this Book",
            )
        obligations = {
            str(entry["state"].get("obligation_id") or "")
            for entry in reality["current_state"].get("narrative_obligation", [])
        }
        if not {
            ref for candidate in candidates for ref in candidate.obligation_refs
        }.issubset(obligations):
            raise KernelError(
                "CAUSAL_PLAN_OBLIGATION_SCOPE_INVALID",
                "candidate obligation references require accepted obligations in the frozen Reality",
            )

    def frozen_replay_inputs(
        self, *, project_id: str, idempotency_key: str
    ) -> tuple[str, str, list[dict[str, Any]]] | None:
        self.cursor.execute(
            "SELECT book.book_id, op.workspace_id, op.input_asset_snapshot FROM authority_operation op JOIN authority_book_production book ON book.book_run_id=op.command_payload->>'book_run_id' AND book.project_id=op.project_id WHERE op.project_id=%s AND op.idempotency_scope='book:causal-planning' AND op.idempotency_key=%s",
            [project_id, idempotency_key],
        )
        row = self.cursor.fetchone()
        return (str(row[0]), str(row[1]), list(row[2])) if row else None

    def require_inputs(
        self,
        *,
        project_id: str,
        book_run_id: str,
        intent_version_id: str,
        reality_revision_id: str,
        current: bool = True,
        cause_refs: tuple[str, ...] = (),
    ) -> tuple[dict[str, Any], list[dict[str, str]], str]:
        self.cursor.execute(
            "SELECT project_id, workspace_id, accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE",
            [book_run_id],
        )
        book = self.cursor.fetchone()
        if book is None or book[0] != project_id:
            raise KernelError(
                "CAUSAL_PLAN_BOOK_SCOPE_INVALID",
                "Causal planning requires its owned Book run",
            )
        chapter = int(book[2])
        if not current:
            self.cursor.execute(
                "SELECT chapter_number FROM authority_narrative_reality_revision WHERE book_run_id=%s AND revision_id=%s",
                [book_run_id, reality_revision_id],
            )
            row = self.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "CAUSAL_PLAN_REALITY_UNKNOWN",
                    "frozen planning input requires an accepted Reality",
                )
            chapter = int(row[0])
        reality = NarrativeRealityRepository(self.cursor).require(
            book_run_id=book_run_id, chapter_number=chapter, event_ids=cause_refs
        )
        if reality["revision_id"] != reality_revision_id:
            raise KernelError(
                "CAUSAL_PLAN_REALITY_STALE",
                "planning cannot use an obsolete accepted Reality",
            )
        self.cursor.execute(
            """
            SELECT v.content_hash, v.content FROM authority_asset_version v
            JOIN authority_story_design_version_state s ON s.asset_version_id=v.asset_version_id
            LEFT JOIN authority_story_design_active_version a ON a.project_id=s.project_id AND a.asset_version_id=s.asset_version_id
            WHERE v.asset_version_id=%s AND s.project_id=%s
              AND (NOT %s OR (a.asset_version_id IS NOT NULL AND s.lifecycle='ACTIVE' AND s.qualification='QUALIFIED' AND s.approval='APPROVED' AND s.freshness='CURRENT'))
              AND s.generator_operation_name='creative.candidates.generate'
            """,
            [intent_version_id, project_id, current],
        )
        intent = self.cursor.fetchone()
        if intent is None:
            raise KernelError(
                "CAUSAL_PLAN_INTENT_NOT_ACTIVE",
                "Causal planning requires an active qualified Story Intent",
            )
        intent_content = dict(intent[1])
        intent_payload = intent_content.get("candidate_payload") or intent_content
        if "narrative_intent" in intent_payload:
            from novel_forge.modules.story_design_authority.intent import (
                NarrativeIntent,
            )

            reality["intent_constraints"] = NarrativeIntent.from_mapping(
                intent_payload["narrative_intent"]
            ).route(target="CHAPTER")
        else:
            reality["intent_constraints"] = {
                "source_asset_version_id": intent_version_id,
                "objective": intent_payload.get("objective", ""),
                "structured_intent_status": "NOT_COMPILED",
            }
        if current:
            foundation = require_current_foundation_set(
                self.cursor,
                project_id=project_id,
                book_id=reality["book_id"],
                require_ready=True,
                lock=True,
            )
            if (
                foundation.by_role[FoundationRole.CREATIVE_FOUNDATION].asset_version_id
                != intent_version_id
            ):
                raise KernelError(
                    "CAUSAL_PLAN_FOUNDATION_MISMATCH",
                    "Director Intent must be the Book's current qualified Creative Foundation",
                )
        versions = [
            reality["outcome_version_id"],
            reality["state_version_id"],
            reality["canon_version_id"],
            intent_version_id,
        ]
        self.cursor.execute(
            "SELECT asset_version_id, content_hash FROM authority_asset_version WHERE asset_version_id=ANY(%s) ORDER BY asset_version_id",
            [versions],
        )
        refs = [
            {"asset_version_id": str(row[0]), "content_hash": str(row[1])}
            for row in self.cursor.fetchall()
        ]
        rules, rule_refs = NarrativeRealityRepository(self.cursor).frozen_world_rules(
            book_run_id=book_run_id
        )
        reality["world_rule_constraints"] = rules
        refs.extend(rule_refs)
        return reality, refs, str(book[1])

    def operation_payload(self, operation_id: str) -> dict[str, Any]:
        self.cursor.execute(
            "SELECT command_payload FROM authority_operation WHERE operation_id=%s",
            [operation_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CAUSAL_OPERATION_MISSING",
                "admitted causal planning command disappeared",
            )
        return dict(row[0])

    def validate_obligation_origins(
        self,
        *,
        book_run_id: str,
        previous_reality: dict[str, Any],
        chapter_outcome: dict[str, Any],
    ) -> None:
        from dataclasses import asdict
        from novel_forge.modules.narrative_state.causal_obligations import (
            causal_obligation_requirement,
        )

        previous = {
            entry["state"]["obligation_id"]: entry["state"]
            for entry in previous_reality.get("current_state", {}).get(
                "narrative_obligation", []
            )
        }
        for event in chapter_outcome.get("state_events", []):
            if event.get("state_kind") != "narrative_obligation":
                continue
            payload = event["mutation"]["payload"]
            if payload.get("obligation_type") != "CAUSAL_DEBT":
                continue
            predicate = asdict(causal_obligation_requirement(payload))
            if (payload.get("fact_origin") or {}).get("kind") == "GOVERNED_PREPARATION":
                from novel_forge.storage.world_preparation_repositories import WorldPreparationRepository
                WorldPreparationRepository(self.cursor).validate_preparation_origin(project_id=chapter_outcome["project_id"], book_run_id=book_run_id, previous_reality=previous_reality, outcome=chapter_outcome, payload=payload, predicate=predicate, existing=payload["obligation_id"] in previous)
                continue
            self.cursor.execute(
                """
                SELECT version.content FROM authority_asset_version version
                JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
                JOIN authority_operation operation ON operation.operation_id=output.operation_id
                WHERE version.asset_version_id=%s AND operation.definition_name='planning.causal.propose'
                  AND operation.status='SUCCEEDED' AND operation.project_id=%s
                  AND output.output_key='planning.causal.action'
                """,
                [
                    payload["causal_plan_asset_version_id"],
                    chapter_outcome["project_id"],
                ],
            )
            row = self.cursor.fetchone()
            if row is None or row[0].get("book_run_id") != book_run_id:
                raise KernelError(
                    "CAUSAL_OBLIGATION_ORIGIN_UNRESOLVED",
                    "causal debt origin must be a committed planning proposal in this Book run",
                )
            action = dict(row[0])
            plan = action["causal_plan"]
            debt = next(
                (
                    item
                    for item in plan["causal_debts"]
                    if item["debt_id"] == payload["obligation_id"]
                ),
                None,
            )
            if (
                debt is None
                or {key: debt["preparation"].get(key) for key in predicate} != predicate
            ):
                raise KernelError(
                    "CAUSAL_OBLIGATION_PREDICATE_DRIFT",
                    "observed debt differs from its frozen causal requirement",
                )
            if payload["obligation_id"] not in previous and (
                action["reality_revision_id"] != previous_reality.get("revision_id")
                or action["chapter_number"] != chapter_outcome["chapter_number"]
            ):
                raise KernelError(
                    "CAUSAL_OBLIGATION_ORIGIN_STALE",
                    "new debt must originate in this chapter's current Reality-bound causal preparation",
                )

    def current_action(
        self,
        *,
        project_id: str,
        book_run_id: str,
        reality_revision_id: str,
        chapter_number: int,
        lock: bool = False,
    ) -> str | None:
        logical_ref = causal_action_ref(
            book_run_id, reality_revision_id, chapter_number
        )
        self.cursor.execute(
            "SELECT current_asset_version_id FROM authority_asset_locator WHERE project_id=%s AND logical_ref=%s"
            + (" FOR UPDATE" if lock else ""),
            [project_id, logical_ref],
        )
        row = self.cursor.fetchone()
        return str(row[0]) if row else None


def causal_action_ref(
    book_run_id: str, reality_revision_id: str, chapter_number: int
) -> str:
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash

    digest = canonical_hash(
        [book_run_id, reality_revision_id, chapter_number]
    ).removeprefix("sha256:")
    return f"story_planning/causal/{digest}.json"
