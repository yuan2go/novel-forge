from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import (
    NarrativeRealityRevision,
    project_reality,
    reality_source_digest,
)


class NarrativeRealityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def project_acceptance(self, acceptance_id: str) -> str:
        self.cursor.execute("SELECT authority_project_reality(%s)", [acceptance_id])
        revision_id = str(self.cursor.fetchone()[0])
        self.cursor.execute("SELECT authority_index_reality_events(%s)", [revision_id])
        return revision_id

    def validate_chapter_knowledge(
        self, *, project_id: str, book_id: str, plan: dict[str, Any]
    ) -> tuple[dict[str, str], ...]:
        from novel_forge.modules.hierarchical_planning.epistemic_validation import (
            validate_planned_character_knowledge,
        )

        book_run_id = str(((plan.get("constraint_envelope") or {}).get("world_preparation") or {}).get("action", {}).get("book_run_id") or "")
        if not book_run_id:
            book_run_id = self.selected_edition_run(project_id=project_id, book_id=book_id)

        self.cursor.execute(
            """
            SELECT version.asset_version_id, version.content_hash, version.content
            FROM authority_book_production book
            JOIN authority_asset_version version
              ON version.asset_version_id=book.active_story_state_version_id
            WHERE book.project_id=%s AND book.book_id=%s
              AND (%s='' OR book.book_run_id=%s)
              AND book.state NOT IN ('COMPLETED', 'ABORTED')
            ORDER BY book.book_run_id FOR UPDATE OF book
            """,
            [project_id, book_id, book_run_id, book_run_id],
        )
        sources = self.cursor.fetchall()
        if not sources:
            validate_planned_character_knowledge(plan, {})
        for _, _, content in sources:
            validate_planned_character_knowledge(plan, dict(content))
        return tuple(
            {"asset_version_id": str(version_id), "content_hash": str(digest)}
            for version_id, digest, _ in sources
        )

    def frozen_world_rules(
        self, *, book_run_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        self.cursor.execute(
            """
            SELECT version.asset_version_id, version.content_hash, version.content
            FROM authority_book_production book
            JOIN authority_book_production_input_snapshot snapshot ON snapshot.snapshot_id=book.input_snapshot_id
            CROSS JOIN LATERAL jsonb_array_elements(snapshot.foundation_set->'bindings') binding
            JOIN authority_asset_version version ON version.asset_version_id=binding->>'asset_version_id'
              AND version.content_hash=binding->>'content_hash'
            WHERE book.book_run_id=%s AND binding->>'role'='WORLD_BIBLE'
            """,
            [book_run_id],
        )
        rules: list[dict[str, Any]] = []
        refs: list[dict[str, str]] = []
        for version_id, content_hash, content in self.cursor.fetchall():
            payload = content.get("candidate_payload", content)
            if "world_foundation" not in payload:
                continue
            from novel_forge.modules.worldbuilding.foundation import WorldFoundation

            WorldFoundation.from_mapping(payload["world_foundation"])
            refs.append(
                {"asset_version_id": str(version_id), "content_hash": str(content_hash)}
            )
            rules.extend(
                {
                    "asset_version_id": str(version_id),
                    "content_hash": str(content_hash),
                    "rule": rule,
                }
                for rule in payload["world_foundation"]["rules"]
            )
        return rules, refs

    def initial_state(
        self, *, version_id: str, frozen_versions: set[str]
    ) -> dict[str, Any] | None:
        if not version_id:
            return None
        if version_id not in frozen_versions:
            raise KernelError(
                "WORLD_INITIAL_SOURCE_UNBOUND",
                "initial state must be an exact frozen acceptance input",
            )
        self.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
            [version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "WORLD_INITIAL_SOURCE_MISSING", "frozen initial state disappeared"
            )
        return dict(row[0])

    def rebuild_sources(
        self, *, project_id: str, book_id: str, through_chapter: int | None, book_run_id: str = ""
    ) -> tuple[list[Any], dict[str, Any] | None, str]:
        book_run_id = book_run_id or self.selected_edition_run(project_id=project_id, book_id=book_id)
        self.cursor.execute(
            """
            SELECT source.accepted_chapter, source.chapter_outcome_asset_version_id,
                   source.story_state_asset_version_id, source.chapter_outcome,
                   state.content, operation.input_asset_snapshot
            FROM authority_narrative_state_rebuild_source source
            JOIN authority_asset_version state ON state.asset_version_id=source.story_state_asset_version_id
            JOIN authority_book_chapter_acceptance acceptance ON acceptance.acceptance_id=source.acceptance_id
            JOIN authority_operation operation ON operation.operation_id=acceptance.acceptance_operation_id
            WHERE source.project_id=%s AND source.book_id=%s
              AND (%s='' OR acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number))
              AND (%s::integer IS NULL OR source.accepted_chapter<=%s)
            ORDER BY source.accepted_chapter, source.chapter_outcome_asset_version_id
            """,
            [project_id, book_id, book_run_id, book_run_id, through_chapter, through_chapter],
        )
        rows = self.cursor.fetchall()
        if not rows:
            return [], None, ""
        first = dict(rows[0][4])
        version_id = str(first.get("previous_story_state_asset_version_id") or "")
        initial = self.initial_state(
            version_id=version_id,
            frozen_versions={str(item["asset_version_id"]) for item in rows[0][5]},
        )
        return rows, initial, version_id

    def selected_edition_run(self, *, project_id: str, book_id: str) -> str:
        self.cursor.execute("""SELECT COALESCE(e.content->>'validation_book_run_id',e.content->>'source_book_run_id')
            FROM authority_book_edition_head h JOIN authority_book b USING(book_id)
            JOIN authority_book_edition_event e ON e.revision_id=h.selected_revision_id AND e.event_kind='VALIDATED'
            WHERE b.project_id=%s AND b.book_id=%s ORDER BY e.created_at DESC,e.event_id DESC LIMIT 1""", [project_id, book_id])
        row = self.cursor.fetchone()
        return str(row[0]) if row else ""

    def require(
        self,
        *,
        book_run_id: str,
        chapter_number: int | None = None,
        event_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT r.project_id, r.book_id, r.book_run_id, r.chapter_number,
                   r.acceptance_id, r.outcome_version_id, r.state_version_id,
                   r.canon_version_id, r.projection_set_id, r.source_digest,
                   COALESCE(r.parent_revision_id, ''), r.revision_id,
                   s.content, c.content, o.content_hash, s.content_hash,
                   c.content_hash, p.projection_hash
            FROM authority_book_acceptance_lineage(%s) a
            JOIN authority_narrative_reality_revision r ON r.acceptance_id=a.acceptance_id
            JOIN authority_asset_version s ON s.asset_version_id=r.state_version_id
            JOIN authority_asset_version c ON c.asset_version_id=r.canon_version_id
            JOIN authority_asset_version o ON o.asset_version_id=r.outcome_version_id
            JOIN authority_book_narrative_projection_set p ON p.projection_set_id=r.projection_set_id
            WHERE (%s::integer IS NULL OR r.chapter_number=%s)
              AND a.status='COMMITTED' AND p.status='COMPLETE'
              AND a.chapter_outcome_asset_version_id=r.outcome_version_id
              AND a.story_state_asset_version_id=r.state_version_id
              AND a.canon_snapshot_asset_version_id=r.canon_version_id
              AND a.longform_projection_set_id=r.projection_set_id
            ORDER BY r.chapter_number DESC LIMIT 1
            """,
            [book_run_id, chapter_number, chapter_number],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "NARRATIVE_REALITY_NOT_COMMITTED",
                "no complete accepted Reality exists at the requested frontier",
            )
        revision = NarrativeRealityRevision(*row[:11])
        digest = reality_source_digest(
            {
                "outcome": row[14],
                "state": row[15],
                "canon": row[16],
                "projection": row[17],
            }
        )
        if revision.revision_id != row[11] or revision.source_digest != digest:
            raise KernelError(
                "NARRATIVE_REALITY_INTEGRITY_FAILED",
                "Reality source or immutable identity changed",
            )
        projected = project_reality(revision, dict(row[12]), dict(row[13]))
        projected["events"] = self.event_sources(
            book_run_id=book_run_id,
            through_chapter=revision.chapter_number,
            event_ids=event_ids,
            include_frontier=True,
        )
        self.cursor.execute(
            "SELECT timeline_id, max(end_ordinal) FROM authority_reality_event_index WHERE book_run_id=authority_book_source_run(%s,accepted_chapter) AND accepted_chapter<=%s AND world_tick AND timeline_id IS NOT NULL GROUP BY timeline_id",
            [book_run_id, revision.chapter_number],
        )
        projected["world_clock"] = {
            str(timeline): int(ordinal) for timeline, ordinal in self.cursor.fetchall()
        }
        self.cursor.execute(
            "SELECT state_kind, entity_key, timeline_id, max(end_ordinal) FROM authority_reality_event_index WHERE book_run_id=authority_book_source_run(%s,accepted_chapter) AND accepted_chapter<=%s AND world_tick AND timeline_id IS NOT NULL GROUP BY state_kind, entity_key, timeline_id",
            [book_run_id, revision.chapter_number],
        )
        projected["entity_clocks"] = {
            f"{kind}|{entity_key}|{timeline}": int(ordinal)
            for kind, entity_key, timeline, ordinal in self.cursor.fetchall()
        }
        return projected

    def recent_world_events(
        self, *, book_run_id: str, through_chapter: int, limit: int
    ) -> list[dict[str, Any]]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 128
            or type(through_chapter) is not int
            or through_chapter < 1
        ):
            raise KernelError(
                "NARRATIVE_EVENT_SCOPE_UNBOUNDED",
                "historical world discovery requires an exact frontier and bounded page",
            )
        self.cursor.execute(
            """
            SELECT v.content->'state_events'->i.event_ordinal
            FROM authority_book_acceptance_lineage(%s) accepted
            JOIN authority_narrative_reality_revision r ON r.acceptance_id=accepted.acceptance_id
            JOIN authority_reality_event_index i ON i.revision_id=r.revision_id
            JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
            WHERE i.accepted_chapter<=%s AND i.world_tick
            ORDER BY i.accepted_chapter DESC, i.event_ordinal DESC LIMIT %s
            """,
            [book_run_id, through_chapter, limit],
        )
        return [dict(row[0]) for row in self.cursor.fetchall()]

    def event_sources(
        self,
        *,
        book_run_id: str,
        through_chapter: int,
        event_ids: tuple[str, ...],
        include_frontier: bool = False,
    ) -> list[dict[str, Any]]:
        if len(event_ids) > 2048:
            raise KernelError(
                "NARRATIVE_EVENT_SCOPE_UNBOUNDED",
                "event lookup requires a bounded explicit cause set",
            )
        self.cursor.execute(
            """
            SELECT v.content->'state_events'->i.event_ordinal
            FROM authority_book_acceptance_lineage(%s) accepted
            JOIN authority_narrative_reality_revision r ON r.acceptance_id=accepted.acceptance_id
            JOIN authority_reality_event_index i ON i.revision_id=r.revision_id
            JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
            WHERE i.accepted_chapter<=%s
              AND (i.event_id=ANY(%s) OR (%s AND i.accepted_chapter=%s))
            ORDER BY i.accepted_chapter, i.event_ordinal
            """,
            [
                book_run_id,
                through_chapter,
                list(event_ids),
                include_frontier,
                through_chapter,
            ],
        )
        return [dict(row[0]) for row in self.cursor.fetchall()]

    def task_background_sources(self, *, reality: dict[str, Any], entity_keys: tuple[tuple[str, str], ...], required_event_ids: tuple[str, ...]) -> list[dict[str, Any]]:
        from novel_forge.modules.context_builder.task_context import confirmed_reader_facts, world_event_causes

        if len(entity_keys) > 2048 or len(required_event_ids) > 2048:
            raise KernelError("TASK_CONTEXT_DEPENDENCY_UNBOUNDED", "necessary source discovery exceeds its explicit host bound")
        self.cursor.execute(
            """
            WITH requested AS (SELECT * FROM unnest(%s::text[],%s::text[]) AS scope(state_kind,entity_key)),
            sources AS (
                SELECT v.content->'state_events'->i.event_ordinal AS event,
                       i.state_kind,i.entity_key,i.accepted_chapter,
                       CASE WHEN jsonb_typeof(v.content->'state_events'->i.event_ordinal->'version'->'entity')='number'
                                 AND (v.content->'state_events'->i.event_ordinal->'version'->>'entity') ~ '^[1-9][0-9]*$'
                            THEN (v.content->'state_events'->i.event_ordinal->'version'->>'entity')::numeric END AS entity_version
                FROM authority_book_acceptance_lineage(%s) accepted
                JOIN authority_narrative_reality_revision r ON r.acceptance_id=accepted.acceptance_id
                JOIN authority_reality_event_index i ON i.revision_id=r.revision_id
                JOIN requested scope ON (scope.state_kind,scope.entity_key)=(i.state_kind,i.entity_key)
                JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
                WHERE i.accepted_chapter<=%s AND i.fact_origin_kind='GOVERNED_BACKGROUND'
                  AND NOT (i.event_id=ANY(%s))
            ), chapters AS (
                SELECT state_kind,entity_key,accepted_chapter,
                       count(*)=count(entity_version) AND count(*)=count(DISTINCT entity_version) AS ordered,
                       min(entity_version) AS first_version,max(entity_version) AS latest_version
                FROM sources GROUP BY state_kind,entity_key,accepted_chapter
            ), boundaries AS (
                SELECT state_kind,entity_key,min(accepted_chapter) AS first_chapter,max(accepted_chapter) AS latest_chapter
                FROM sources GROUP BY state_kind,entity_key
            ) SELECT source.event FROM sources source
              JOIN chapters USING(state_kind,entity_key,accepted_chapter)
              JOIN boundaries USING(state_kind,entity_key)
              WHERE (source.accepted_chapter=first_chapter AND (NOT ordered OR source.entity_version=first_version))
                 OR (source.accepted_chapter=latest_chapter AND (NOT ordered OR source.entity_version=latest_version))
            """,
            [[kind for kind, _ in entity_keys], [key for _, key in entity_keys], reality["book_run_id"], reality["chapter_number"], sorted(confirmed_reader_facts(reality))],
        )
        found = {event["event_id"]: dict(event) for (event,) in self.cursor.fetchall()}
        pending = set(required_event_ids) | set(found)
        visited: set[str] = set()
        for _ in range(32):
            batch = tuple(sorted(pending - visited))
            if not batch:
                return [found[key] for key in sorted(found)]
            if len(visited | set(batch)) > 2048:
                raise KernelError("TASK_CONTEXT_DEPENDENCY_UNBOUNDED", "necessary causal closure exceeds its explicit host bound")
            rows = self.event_sources(book_run_id=reality["book_run_id"], through_chapter=reality["chapter_number"], event_ids=batch)
            if set(batch) - {row["event_id"] for row in rows}:
                raise KernelError("TASK_CONTEXT_DEPENDENCY_UNAVAILABLE", "required accepted event is unavailable at the frozen Book boundary")
            visited.update(batch)
            pending = set()
            for event in rows:
                found[event["event_id"]] = event
                for ref in world_event_causes(event):
                    if ref.startswith("local:"):
                        self.cursor.execute("SELECT parent.event_id FROM authority_reality_event_index child JOIN authority_reality_event_index parent ON parent.revision_id=child.revision_id WHERE child.book_run_id=authority_book_source_run(%s,child.accepted_chapter) AND child.event_id=%s AND child.accepted_chapter<=%s AND parent.batch_local_id=%s", [reality["book_run_id"], event["event_id"], reality["chapter_number"], ref[6:]])
                        matches = self.cursor.fetchall()
                        if len(matches) != 1:
                            raise KernelError("TASK_CONTEXT_DEPENDENCY_UNAVAILABLE", "local cause requires one exact accepted batch event")
                        pending.add(str(matches[0][0]))
                    elif ref not in reality.get("foundation_cause_refs", ()):
                        pending.add(ref)
        if pending - visited:
            raise KernelError("TASK_CONTEXT_DEPENDENCY_UNBOUNDED", "necessary causal closure exceeds its explicit host depth")
        return [found[key] for key in sorted(found)]

    def why_sources(self, *, reality: dict[str, Any], event_id: str) -> dict[str, Any]:
        events: dict[str, Any] = {}
        pending = [event_id]
        visited: set[str] = set()
        while pending and len(visited) < 64:
            batch = tuple(sorted(set(pending) - visited)[: 64 - len(visited)])
            if not batch:
                break
            visited.update(batch)
            found = self.event_sources(
                book_run_id=reality["book_run_id"],
                through_chapter=reality["chapter_number"],
                event_ids=batch,
            )
            pending = []
            for event in found:
                events[event["event_id"]] = event
                causes = event.get("causality", {}).get("cause_refs", [])
                local_names = [ref[6:] for ref in causes if ref.startswith("local:")]
                pending.extend(ref for ref in causes if not ref.startswith("local:"))
                if local_names:
                    self.cursor.execute("SELECT parent.event_id FROM authority_reality_event_index child JOIN authority_reality_event_index parent ON parent.revision_id=child.revision_id WHERE child.book_run_id=authority_book_source_run(%s,child.accepted_chapter) AND child.event_id=%s AND child.accepted_chapter<=%s AND parent.batch_local_id=ANY(%s)", [reality["book_run_id"], event["event_id"], reality["chapter_number"], local_names])
                    pending.extend(str(row[0]) for row in self.cursor.fetchall())
        return {**reality, "events": list(events.values())}

    def reader_evidence(self, *, reality: dict[str, Any]) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT v.asset_version_id, v.content_hash, v.content
            FROM authority_book_chapter_acceptance accepted
            JOIN authority_book_followup_operation link ON link.chapter_request_id=accepted.chapter_request_id AND link.followup_type='READER_OUTCOME'
            JOIN authority_operation op ON op.operation_id=link.operation_id AND op.status='SUCCEEDED'
            JOIN authority_operation_output_asset output ON output.operation_id=op.operation_id AND output.output_key='reader_outcome.state_transition'
            JOIN authority_asset_version v ON v.asset_version_id=output.asset_version_id
            WHERE accepted.acceptance_id=%s AND accepted.book_run_id=%s AND accepted.status='COMMITTED'
        """,
            [reality["acceptance_id"], reality["book_run_id"]],
        )
        rows = self.cursor.fetchall()
        if len(rows) > 1:
            raise KernelError(
                "NARRATIVE_READER_EVIDENCE_AMBIGUOUS",
                "Reader view requires one completed followup for its accepted subject",
            )
        return {
            "status": "AVAILABLE" if rows else "WAITING_EVIDENCE",
            "role": "ADVISORY_READER_EVIDENCE",
            "reality_mutation_allowed": False,
            "sources": [
                {
                    "asset_version_id": str(row[0]),
                    "content_hash": str(row[1]),
                    "content": dict(row[2]),
                }
                for row in rows
            ],
        }

    def verify_replay(self, *, book_run_id: str) -> dict[str, Any]:
        self.cursor.execute(
            "SELECT chapter_number FROM authority_book_acceptance_lineage(%s) WHERE TRUE AND status='COMMITTED' ORDER BY chapter_number",
            [book_run_id],
        )
        chapters = [int(row[0]) for row in self.cursor.fetchall()]
        parent = ""
        for ordinal, chapter in enumerate(chapters, 1):
            reality = self.require(book_run_id=book_run_id, chapter_number=chapter)
            if ordinal != chapter or reality["parent_revision_id"] != parent:
                raise KernelError(
                    "NARRATIVE_REALITY_REPLAY_FORK",
                    "accepted frontier must reconstruct one contiguous Reality chain",
                )
            parent = str(reality["revision_id"])
        return {
            "book_run_id": book_run_id,
            "accepted_count": len(chapters),
            "revision_id": parent,
            "authority_mutated": False,
        }
