from dataclasses import asdict
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.worldbuilding.foundation import WorldFoundation
from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy
from novel_forge.storage.foundation_repositories import require_current_foundation_set
from novel_forge.storage.narrative_reality_repositories import (
    NarrativeRealityRepository,
)


class WorldPreparationRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def validate_binding(
        self,
        *,
        project_id: str,
        book_id: str,
        binding: Mapping[str, Any],
        require_current: bool = True,
    ) -> dict[str, Any]:
        def contract(reference: Mapping[str, Any]) -> dict[str, Any]:
            self.cursor.execute(
                "SELECT v.content_hash, v.content FROM authority_asset_version v JOIN authority_asset a ON a.asset_id=v.asset_id WHERE a.project_id=%s AND v.asset_version_id=%s",
                [project_id, reference["asset_version_id"]],
            )
            row = self.cursor.fetchone()
            if row is None or row[0] != reference.get("content_hash"):
                raise KernelError(
                    "WORLD_BINDING_SOURCE_INVALID",
                    "world binding must reference exact project-scoped immutable artifacts",
                )
            return dict(row[1]["contract"])

        action = contract(binding)
        if (
            action != binding["action"]
            or action["project_id"] != project_id
            or action["book_id"] != book_id
        ):
            raise KernelError(
                "WORLD_BINDING_ACTION_DRIFT",
                "active plan must retain its exact governed world action",
            )
        source = contract(action["source"])
        if binding.get("frozen_source") != source:
            raise KernelError(
                "WORLD_BINDING_SOURCE_DRIFT",
                "private working source differs from its immutable source artifact",
            )
        for stage in ("generation", "evaluation"):
            output = contract(action[stage])
            evidence = output["evidence"]
            if output["source"] != action["source"]:
                raise KernelError(
                    "WORLD_BINDING_RECEIPT_DRIFT",
                    "world output must reference this exact source",
                )
            self.cursor.execute(
                "SELECT operation_id, status FROM authority_external_effect WHERE external_effect_id=%s",
                [evidence["external_receipt_ref"]],
            )
            if self.cursor.fetchone() != (evidence["operation_id"], "SUCCEEDED"):
                raise KernelError(
                    "WORLD_BINDING_EFFECT_UNCONFIRMED",
                    "world output requires a confirmed governed Provider effect",
                )
        if require_current:
            self.assert_source_current(
                project_id=project_id, book_id=book_id, frozen=source
            )
        return source

    def require_decisions(
        self, *, project_id: str, binding: Mapping[str, Any]
    ) -> tuple[dict[str, str], ...]:
        from novel_forge.storage.book_control_repositories import BookControlRepository
        from novel_forge.modules.canon_graph.background import world_action_boundaries

        action = binding["action"]
        return tuple(
            ref
            for boundary in world_action_boundaries(binding)
            for ref in BookControlRepository(self.cursor).require_approval(
                project_id=project_id,
                book_run_id=action["book_run_id"],
                chapter_number=action["world_plan"]["chapter_number"],
                actor_id=action["actor_id"],
                boundary=boundary,
                subject_version_id=binding["asset_version_id"],
            )
        )

    def validate_acceptance(
        self,
        *,
        project_id: str,
        book_id: str,
        binding: Mapping[str, Any],
        outcome: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        from novel_forge.modules.canon_graph.background import (
            attach_background_proposals,
            require_background_payload,
        )
        from novel_forge.modules.canon_graph.domain import SEMANTIC_CHANGE_FIELDS

        actual = [
            event
            for event in outcome.get("state_events", [])
            if (
                event.get("mutation", {}).get("payload", {}).get("fact_origin") or {}
            ).get("kind")
            == "GOVERNED_BACKGROUND"
        ]
        if not binding:
            if actual or any(
                (
                    event.get("mutation", {}).get("payload", {}).get("fact_origin")
                    or {}
                ).get("kind")
                == "GOVERNED_PREPARATION"
                for event in outcome.get("state_events", [])
            ):
                raise KernelError(
                    "WORLD_ACCEPTANCE_SOURCE_MISSING",
                    "background Actual requires a frozen active Planning binding",
                )
            return None
        source = self.validate_binding(
            project_id=project_id, book_id=book_id, binding=binding
        )
        self.require_decisions(project_id=project_id, binding=binding)
        if binding["action"]["contract_version"] == "world-production-action.v2":
            from novel_forge.modules.canon_graph.background import (
                scheduled_world_events,
                preparation_lineage,
            )
            from novel_forge.modules.narrative_state.contracts import (
                narrative_event_payload,
            )
            from novel_forge.modules.worldbuilding.dynamics import WorldTransition
            import json

            scheduled = {
                raw["transition_id"]: raw
                for raw in scheduled_world_events(binding)
                if raw["camera"] == "ON_CAMERA"
            }
            for event in outcome.get("state_events", []):
                payload = event["mutation"]["payload"]
                lineage = payload.get("preparation_lineage")
                if (
                    not lineage
                    or (payload.get("fact_origin") or {}).get("kind")
                    == "GOVERNED_BACKGROUND"
                ):
                    continue
                raw = scheduled.get(lineage.get("transition_id"))
                if raw is None or lineage != preparation_lineage(
                    binding, raw["transition_id"]
                ):
                    raise KernelError(
                        "WORLD_PREPARATION_ACCEPTANCE_LINEAGE_INVALID",
                        "on-camera preparation must belong to this frozen selected scope",
                    )
                transition = WorldTransition.from_mapping(raw)
                if (
                    event["state_kind"] != transition.state_kind.value
                    or event["identity"]["entity_key"] != transition.entity_key
                    or any(
                        payload.get(key) != value
                        for key, value in narrative_event_payload(
                            transition.changes
                        ).items()
                    )
                    or payload.get("world_transition")
                    != {
                        "payload_json": json.dumps(
                            raw, sort_keys=True, separators=(",", ":")
                        )
                    }
                ):
                    raise KernelError(
                        "WORLD_PREPARATION_ACCEPTANCE_EFFECT_INVALID",
                        "accepted on-camera preparation must preserve the observed and scheduled effects",
                    )
        from novel_forge.modules.canon_graph.disclosure import (
            validate_disclosure_acceptance,
        )

        validate_disclosure_acceptance(outcome, binding)
        expected = attach_background_proposals(
            extraction={"chapter": binding["action"]["world_plan"]["chapter_number"]},
            binding=binding,
        )
        expected_by_id = {
            item["fact_origin"]["transition_id"]: item
            for field in SEMANTIC_CHANGE_FIELDS
            for item in expected.get(field, [])
            if item["fact_origin"]["kind"] == "GOVERNED_BACKGROUND"
        }
        observed_by_id = {
            event["mutation"]["payload"]["fact_origin"]["transition_id"]: event[
                "mutation"
            ]["payload"]
            for event in actual
        }
        if len(actual) != len(observed_by_id) or set(expected_by_id) != set(
            observed_by_id
        ):
            raise KernelError(
                "WORLD_ACCEPTANCE_SELECTION_DRIFT",
                "accepted background events must match the complete selected world batch",
            )
        for identity, expected_item in expected_by_id.items():
            payload = observed_by_id[identity]
            require_background_payload(expected=expected_item, actual=payload)
        expected_preparation = {
            item["obligation_id"]: item
            for item in expected.get("obligation_changes", [])
        }
        actual_preparation = [
            event["mutation"]["payload"]
            for event in outcome.get("state_events", [])
            if (event["mutation"]["payload"].get("fact_origin") or {}).get("kind")
            == "GOVERNED_PREPARATION"
        ]
        if len(actual_preparation) != len(expected_preparation) or {
            item["obligation_id"] for item in actual_preparation
        } != set(expected_preparation):
            raise KernelError(
                "WORLD_PREPARATION_ACCEPTANCE_DRIFT",
                "accepted preparation commitments must equal the selected and actually discharged obligations",
            )
        for item in actual_preparation:
            expected_item = expected_preparation[item["obligation_id"]]
            if any(
                item.get(key) != expected_item.get(key)
                for key in (
                    "status",
                    "fact_origin",
                    "causal_requirement",
                    "causal_plan_asset_version_id",
                    "payoff_evidence",
                    "target_window",
                    "preparation_schedule",
                    "retirement_evidence",
                    "intent_version_id",
                )
            ):
                raise KernelError(
                    "WORLD_PREPARATION_ACCEPTANCE_DRIFT",
                    "an observed preparation obligation cannot replace its source or repayment evidence",
                )
        return source["reality"]

    def validate_preparation_origin(
        self,
        *,
        project_id: str,
        book_run_id: str,
        previous_reality: Mapping[str, Any],
        outcome: Mapping[str, Any],
        payload: Mapping[str, Any],
        predicate: Mapping[str, Any],
        existing: bool,
    ) -> None:
        origin = payload["fact_origin"]
        if (
            origin.get("action_asset_version_id")
            != payload["causal_plan_asset_version_id"]
        ):
            raise KernelError(
                "CAUSAL_OBLIGATION_ORIGIN_UNRESOLVED",
                "preparation must preserve its original action identity",
            )
        self.cursor.execute(
            "SELECT v.content_hash, v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND v.asset_version_id=%s",
            [project_id, payload["causal_plan_asset_version_id"]],
        )
        row = self.cursor.fetchone()
        if row is None or row[0] != origin.get("action_content_hash"):
            raise KernelError(
                "CAUSAL_OBLIGATION_ORIGIN_UNRESOLVED",
                "preparation must resolve its immutable generated action",
            )
        action = row[1]["contract"]
        self.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
            [action["source"]["asset_version_id"]],
        )
        source_row = self.cursor.fetchone()
        if source_row is None or action["book_run_id"] != book_run_id:
            raise KernelError(
                "CAUSAL_OBLIGATION_ORIGIN_UNRESOLVED",
                "preparation belongs to another Book or missing source",
            )
        self.validate_binding(
            project_id=project_id,
            book_id=action["book_id"],
            binding={
                "asset_version_id": payload["causal_plan_asset_version_id"],
                "content_hash": row[0],
                "action": action,
                "frozen_source": source_row[0]["contract"],
            },
            require_current=False,
        )
        plan = action["world_plan"]
        debt = next(
            (
                item
                for item in plan["causal_debts"]
                if item["debt_id"] == payload["obligation_id"]
            ),
            None,
        )
        if debt is None or {
            key: debt["preparation"].get(key) for key in predicate
        } != dict(predicate):
            raise KernelError(
                "CAUSAL_OBLIGATION_PREDICATE_DRIFT",
                "preparation cannot replace the selected target predicate",
            )
        if not existing and (
            plan["baseline_id"] != previous_reality.get("revision_id")
            or plan["chapter_number"] != outcome["chapter_number"]
        ):
            raise KernelError(
                "CAUSAL_OBLIGATION_ORIGIN_STALE",
                "new preparation must originate in this acceptance window",
            )

    def require_source(
        self,
        *,
        project_id: str,
        book_id: str,
        request: Mapping[str, Any],
        contract_version: str = "world-preparation-source.v2",
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT book.project_id, book.book_id, book.input_snapshot_id,
                   book.accepted_through_chapter, book.active_story_state_version_id,
                   book.active_canon_snapshot_version_id, to_jsonb(snapshot),
                   profile.content
            FROM authority_book_production book
            JOIN authority_book_production_input_snapshot snapshot ON snapshot.snapshot_id=book.input_snapshot_id
            JOIN authority_asset_version profile ON profile.asset_version_id=book.production_profile_version
            WHERE book.book_run_id=%s FOR UPDATE OF book
            """,
            [request["book_run_id"]],
        )
        row = self.cursor.fetchone()
        expected = (
            project_id,
            book_id,
            request["input_snapshot_id"],
            int(request["accepted_through_chapter"]),
            request["story_state_version_id"],
            request["canon_version_id"],
        )
        observed = (
            tuple(row[:4]) + (str(row[4] or ""), str(row[5] or "")) if row else None
        )
        if observed != expected:
            raise KernelError(
                "WORLD_PREPARATION_BASELINE_STALE",
                "world preparation must use the exact current Book frontier",
            )
        snapshot = dict(row[6])
        foundation = require_current_foundation_set(
            self.cursor,
            project_id=project_id,
            book_id=book_id,
            require_ready=True,
            lock=True,
        )
        bindings = list(snapshot["foundation_set"]["bindings"])
        if {binding["asset_version_id"] for binding in bindings} != {
            binding.asset_version_id for binding in foundation.by_role.values()
        }:
            raise KernelError(
                "WORLD_PREPARATION_FOUNDATION_STALE",
                "changed Foundation requires an approved future input rebind",
            )
        refs = [
            {
                "asset_version_id": binding["asset_version_id"],
                "content_hash": binding["content_hash"],
            }
            for binding in bindings
        ]
        self.cursor.execute(
            "SELECT asset_version_id, content_hash, content FROM authority_asset_version WHERE asset_version_id=ANY(%s)",
            [[ref["asset_version_id"] for ref in refs]],
        )
        documents = {
            str(version): (str(digest), dict(content))
            for version, digest, content in self.cursor.fetchall()
        }
        if any(
            documents.get(ref["asset_version_id"], (None,))[0] != ref["content_hash"]
            for ref in refs
        ):
            raise KernelError(
                "WORLD_PREPARATION_SOURCE_CORRUPT",
                "Foundation content must match the approved exact binding",
            )
        by_role = {
            binding["role"]: documents[binding["asset_version_id"]][1]
            for binding in bindings
        }
        world = by_role["WORLD_BIBLE"]
        world = world.get("candidate_payload", world)
        if "world_foundation" not in world:
            raise KernelError(
                "WORLD_PREPARATION_FOUNDATION_REQUIRED",
                "autonomous world production requires approved compiled World Foundation",
            )
        compiled = WorldFoundation.from_mapping(world["world_foundation"])
        chapter = int(row[3])
        repository = NarrativeRealityRepository(self.cursor)
        if chapter:
            reality = repository.require(
                book_run_id=request["book_run_id"], chapter_number=chapter
            )
            reality["baseline_kind"] = "ACCEPTED_REALITY"
        else:
            initial_id = str(snapshot.get("initial_story_state_version") or "")
            initial = repository.initial_state(
                version_id=initial_id,
                frozen_versions={initial_id} if initial_id else set(),
            )
            if initial_id:
                self.cursor.execute(
                    "SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s",
                    [initial_id],
                )
                refs.append(
                    {
                        "asset_version_id": initial_id,
                        "content_hash": str(self.cursor.fetchone()[0]),
                    }
                )
            identity = "foundation:" + narrative_hash(
                {
                    "book_run_id": request["book_run_id"],
                    "input_snapshot_id": request["input_snapshot_id"],
                    "bindings": refs,
                }
            )
            reality = {
                "project_id": project_id,
                "book_id": book_id,
                "book_run_id": request["book_run_id"],
                "chapter_number": 0,
                "revision_id": identity,
                "baseline_kind": "APPROVED_FOUNDATION",
                "current_state": dict((initial or {}).get("current_state") or {}),
                "events": [],
                "world_clock": {},
            }
        cast = by_role["CHARACTER_CAST"]
        cast = cast.get("candidate_payload", cast)
        character_ids = [
            str(item["character_id"])
            for item in cast.get("characters", [])
            if item.get("character_id")
        ]
        reality["approved_entity_ids"] = list(
            dict.fromkeys((*compiled.entity_ids, *character_ids))
        )
        reality["approved_character_ids"] = character_ids
        reality["world_dynamics_contract"] = "world-dynamics.v2"
        world_binding = next(
            binding for binding in bindings if binding["role"] == "WORLD_BIBLE"
        )
        reality["foundation_cause_refs"] = [
            f"foundation:{binding['asset_version_id']}" for binding in bindings
        ]
        reality["world_rule_constraints"] = [
            {
                "asset_version_id": world_binding["asset_version_id"],
                "content_hash": world_binding["content_hash"],
                "rule": rule,
            }
            for rule in world["world_foundation"]["rules"]
        ]
        intent_binding = next(
            binding for binding in bindings if binding["role"] == "CREATIVE_FOUNDATION"
        )
        intent = by_role["CREATIVE_FOUNDATION"]
        intent = intent.get("candidate_payload", intent)
        self.cursor.execute(
            "SELECT b.owner, b.project_id, b.subject_id, v.content_hash, v.content FROM authority_runtime_policy_binding b JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version) WHERE b.owner='BOOK_CONTROL' AND b.project_id=%s AND b.subject_id=%s",
            [project_id, f"{request['book_run_id']}:chapter:{chapter + 1}"],
        )
        control = self.cursor.fetchone()
        if control is None:
            raise KernelError(
                "WORLD_CONTROL_POLICY_UNFROZEN",
                "world generation requires the Book-owned frozen editorial policy",
            )
        control_snapshot = dict(
            zip(
                ("owner", "project_id", "subject_id", "policy_hash", "policy"),
                control,
                strict=True,
            )
        )
        policy_raw = row[7].get("world_production_policy") or {}
        policy = WorldProductionPolicy(**policy_raw)
        planning_refs = request.get("planning_input_refs") or []
        if not isinstance(planning_refs, list) or not planning_refs:
            raise KernelError(
                "WORLD_PLANNING_WINDOW_REQUIRED",
                "native world preparation requires its frozen Planning inputs",
            )
        planning_inputs = []
        for ref in planning_refs:
            if (
                not isinstance(ref, dict)
                or set(ref) != {"role", "asset_version_id"}
                or ref["role"]
                not in {"book_plan", "volume_plan", "arc_plans", "chapter_group_plan"}
            ):
                raise KernelError(
                    "WORLD_PLANNING_WINDOW_INVALID",
                    "world Planning references require exact typed roles",
                )
            self.cursor.execute(
                "SELECT v.content_hash, v.content FROM authority_asset_version v JOIN story_plan_binding b ON b.asset_version_id=v.asset_version_id JOIN active_story_plan_version active USING(binding_id) WHERE b.project_id=%s AND b.book_id=%s AND b.asset_version_id=%s AND b.freshness='CURRENT'",
                [project_id, book_id, ref["asset_version_id"]],
            )
            plan = self.cursor.fetchone()
            if plan is None:
                raise KernelError(
                    "WORLD_PLANNING_WINDOW_STALE",
                    "world preparation requires the current active Planning boundary",
                )
            planning_inputs.append({**ref, "content_hash": plan[0], "content": plan[1]})
        from novel_forge.modules.chapter_authority.provider_views import (
            project_world_planning_window,
        )

        planning_window = project_world_planning_window(
            planning_inputs, chapter=chapter + 1, window=policy.planning_window_chapters
        )
        if contract_version == "world-preparation-source.v2" and chapter:
            history = repository.recent_world_events(
                book_run_id=request["book_run_id"],
                through_chapter=chapter,
                limit=min(128, policy.max_candidates * policy.max_preparation_steps),
            )
            combined = {
                event["event_id"]: event for event in [*reality["events"], *history]
            }
            reality["events"] = [combined[key] for key in sorted(combined)]
        continuations = (
            self.preparation_sources(reality=reality, limit=policy.max_candidates)
            if contract_version == "world-preparation-source.v2" and chapter
            else []
        )
        return {
            "contract_version": contract_version,
            **(
                {"preparation_sources": continuations}
                if contract_version == "world-preparation-source.v2"
                else {}
            ),
            "request": dict(request),
            "reality": reality,
            "foundation_refs": refs,
            "intent_version_id": intent_binding["asset_version_id"],
            "intent": intent,
            "world_foundation": world["world_foundation"],
            "character_definitions": list(cast.get("characters") or []),
            "planning_window": planning_window,
            "entity_ids": reality["approved_entity_ids"],
            "policy": asdict(policy),
            "control_snapshot": control_snapshot,
            "fact_mutation_allowed": False,
        }

    def preparation_sources(
        self, *, reality: dict[str, Any], limit: int
    ) -> list[dict[str, Any]]:
        origins = sorted(
            {
                entry["state"]["causal_plan_asset_version_id"]
                for entry in reality["current_state"].get("narrative_obligation", [])
                if (entry["state"].get("fact_origin") or {}).get("kind")
                == "GOVERNED_PREPARATION"
                and entry["state"].get("status") != "CANCELLED"
            }
        )
        if not origins:
            return []
        self.cursor.execute(
            """
            SELECT v.asset_version_id, v.content_hash, v.content->'contract'
            FROM authority_asset_version v
            CROSS JOIN LATERAL jsonb_array_elements(v.content->'contract'->'world_plan'->'candidate_futures') candidate
            WHERE v.asset_version_id=ANY(%s)
              AND v.content->'contract'->>'book_run_id'=%s
              AND candidate->>'candidate_id'=v.content->'contract'->'world_plan'->>'selected_candidate_id'
              AND NOT EXISTS (
                SELECT 1 FROM authority_reality_event_index i
                WHERE i.book_run_id=%s AND i.preparation_action_version_id=v.asset_version_id
                  AND i.preparation_transition_id=candidate->'transition'->>'transition_id'
                  AND i.accepted_chapter<=%s)
            ORDER BY v.asset_version_id LIMIT %s
            """,
            [
                origins,
                reality["book_run_id"],
                reality["book_run_id"],
                reality["chapter_number"],
                limit + 1,
            ],
        )
        rows = self.cursor.fetchall()
        if len(rows) > limit:
            raise KernelError(
                "WORLD_PREPARATION_PORTFOLIO_BLOCKED",
                "existing preparation exceeds the frozen portfolio; an explicit future decision is required",
            )
        result = []
        history_ids = set()
        for version, digest, action in rows:
            self.cursor.execute(
                "SELECT preparation_transition_id, event_id FROM authority_reality_event_index WHERE book_run_id=%s AND preparation_action_version_id=%s AND preparation_transition_id IS NOT NULL AND accepted_chapter<=%s ORDER BY preparation_transition_id LIMIT 129",
                [reality["book_run_id"], version, reality["chapter_number"]],
            )
            mappings = self.cursor.fetchall()
            if len(mappings) > 128:
                raise KernelError(
                    "WORLD_PREPARATION_MAPPING_UNBOUNDED",
                    "one preparation origin exceeded its accepted event bound",
                )
            history_ids.update(event_id for _, event_id in mappings)
            plan = action["world_plan"]
            for raw in [
                *(step["transition"] for step in plan["preparation_schedule"]),
                *(
                    candidate["transition"]
                    for candidate in plan["candidate_futures"]
                    if candidate.get("candidate_id") == plan["selected_candidate_id"]
                ),
            ]:
                history_ids.update(
                    ref
                    for ref in raw["cause_refs"]
                    if not ref.startswith(("local:", "foundation:"))
                )
            result.append(
                {
                    "origin": {
                        "asset_version_id": version,
                        "content_hash": digest,
                        "action": action,
                    },
                    "accepted_steps": dict(mappings),
                }
            )
        found = NarrativeRealityRepository(self.cursor).event_sources(
            book_run_id=reality["book_run_id"],
            through_chapter=reality["chapter_number"],
            event_ids=tuple(sorted(history_ids)),
        )
        events = {
            event["event_id"]: event for event in [*reality.get("events", []), *found]
        }
        reality["events"] = [events[key] for key in sorted(events)]
        return result

    def assert_source_current(
        self, *, project_id: str, book_id: str, frozen: Mapping[str, Any]
    ) -> None:
        current = self.require_source(
            project_id=project_id,
            book_id=book_id,
            request=frozen["request"],
            contract_version=frozen["contract_version"],
        )
        if narrative_hash(current) != narrative_hash(frozen):
            raise KernelError(
                "WORLD_PREPARATION_SOURCE_STALE",
                "changed Reality, Foundation, Intent or policy requires a new world planning operation",
            )
