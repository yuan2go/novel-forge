from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.causal_domain import (
    CandidateFuture,
    build_causal_plan,
)
from novel_forge.modules.narrative_state.reality import narrative_hash

from .dynamics import (
    WorldTransition,
    candidate_transition,
    require_contract_fields,
    require_text_fields,
    evaluate_requirement,
    state_index,
    validate_world_state_rules,
)


@dataclass(frozen=True, slots=True)
class WorldProductionPolicy:
    version: str = "world-production-policy.v1"
    max_candidates: int = 4
    max_paths_per_candidate: int = 3
    max_preparation_steps: int = 4
    planning_window_chapters: int = 4
    max_provider_stages: int = 2
    context_token_budget: int = 8192
    max_world_time_advance: int = 1000

    def __post_init__(self) -> None:
        bounds = (
            (self.max_candidates, 16),
            (self.max_paths_per_candidate, 8),
            (self.max_preparation_steps, 16),
            (self.planning_window_chapters, 32),
            (
                self.context_token_budget,
                512000
                if self.version == "world-production-policy.v4"
                else 24000
                if self.version == "world-production-policy.v3"
                else 16000,
            ),
            (self.max_world_time_advance, 1_000_000),
        )
        if (
            self.version
            not in {
                "world-production-policy.v1",
                "world-production-policy.v2",
                "world-production-policy.v3",
                "world-production-policy.v4",
            }
            or (
                self.version == "world-production-policy.v1"
                and self.max_provider_stages != 2
            )
            or (
                self.version
                in {"world-production-policy.v2", "world-production-policy.v3"}
                and (
                    type(self.max_provider_stages) is not int
                    or not 3 <= self.max_provider_stages <= 5
                )
            )
            or (
                self.version == "world-production-policy.v4"
                and (
                    type(self.max_provider_stages) is not int
                    or not 2 <= self.max_provider_stages <= 5
                )
            )
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= maximum
                for value, maximum in bounds
            )
        ):
            raise KernelError(
                "WORLD_PRODUCTION_POLICY_INVALID",
                "world preparation requires a frozen bounded policy",
            )


def validate_generated_candidates(
    generated: Mapping[str, Any], policy: WorldProductionPolicy
) -> list[Mapping[str, Any]]:
    require_contract_fields(generated, required={"disposition", "reason", "candidates"})
    require_text_fields(generated, ("disposition", "reason"))
    candidates = generated["candidates"]
    if not isinstance(candidates, list) or len(candidates) > policy.max_candidates:
        raise KernelError(
            "WORLD_GENERATION_BOUND_EXCEEDED",
            "candidate generation exceeded its frozen portfolio bound",
        )
    if generated["disposition"] not in {"CANDIDATES", "NO_OP", "DEFER"} or bool(
        candidates
    ) != (generated["disposition"] == "CANDIDATES"):
        raise KernelError(
            "WORLD_GENERATION_DISPOSITION_INVALID",
            "only a candidate portfolio may contain proposed events",
        )
    identities: set[str] = set()
    for index, candidate in enumerate(candidates):
        require_contract_fields(
            candidate,
            required={
                "transition",
                "affected_entities",
                "world_consequences",
                "arc_refs",
                "obligation_refs",
                "risks",
                "rationale",
                "soft_assumptions",
                "narrative_preferences",
                "preparation_paths",
            },
            optional={"information_scope"},
        )
        information = candidate.get("information_scope")
        if information is not None and "disclosures" not in information:
            require_contract_fields(
                information, required={"reader_exposure", "reveal_event_ids"}
            )
            if (
                information["reader_exposure"] not in {"CONCEAL", "REVEAL"}
                or not isinstance(information["reveal_event_ids"], list)
                or any(
                    not isinstance(ref, str) or not ref
                    for ref in information["reveal_event_ids"]
                )
                or bool(information["reveal_event_ids"])
                != (information["reader_exposure"] == "REVEAL")
            ):
                raise KernelError(
                    "WORLD_INFORMATION_SCOPE_INVALID",
                    "information scope must explicitly select or conceal accepted events",
                )
        if information is not None and "disclosures" in information:
            require_contract_fields(information, required={"disclosures"})
            rows = information["disclosures"]
            if not isinstance(rows, list) or len(rows) > 8:
                raise KernelError(
                    "WORLD_INFORMATION_SCOPE_INVALID",
                    "disclosure portfolio exceeds its frozen bound",
                )
            if any(
                not isinstance(row, Mapping) or not row.get("disclosure_id")
                for row in rows
            ) or len({row["disclosure_id"] for row in rows}) != len(rows):
                raise KernelError(
                    "WORLD_INFORMATION_SCOPE_INVALID",
                    "each audience presentation requires a distinct stable disclosure identity",
                )
        for field in ("affected_entities", "world_consequences"):
            evidence = candidate[field]
            if (
                not isinstance(evidence, list)
                or not evidence
                or any(
                    not isinstance(item, str) or not item.strip() for item in evidence
                )
            ):
                raise KernelError(
                    "WORLD_GENERATION_CANDIDATE_EVIDENCE_INVALID",
                    f"$.candidates[{index}].{field}: expected nonempty consequence evidence array, actual {type(evidence).__name__}",
                )
        transition = WorldTransition.from_mapping(candidate["transition"])
        if transition.transition_id in identities:
            raise KernelError(
                "WORLD_GENERATION_IDENTITY_COLLISION",
                "generated futures need unique batch-local identities",
            )
        identities.add(transition.transition_id)
        paths = candidate["preparation_paths"]
        if not isinstance(paths, list) or len(paths) > policy.max_paths_per_candidate:
            raise KernelError(
                "WORLD_GENERATION_BOUND_EXCEEDED",
                "preparation alternatives exceed the frozen search bound",
            )
        path_ids: set[str] = set()
        for path in paths:
            require_contract_fields(path, required={"path_id", "steps", "rationale"})
            require_text_fields(path, ("path_id", "rationale"))
            if path["path_id"] in path_ids:
                raise KernelError(
                    "WORLD_GENERATION_IDENTITY_COLLISION",
                    "preparation paths need unique names",
                )
            path_ids.add(path["path_id"])
            steps = path["steps"]
            if (
                not isinstance(steps, list)
                or not 1 <= len(steps) <= policy.max_preparation_steps
            ):
                raise KernelError(
                    "WORLD_GENERATION_BOUND_EXCEEDED",
                    "preparation path exceeds its frozen depth",
                )
            for step in steps:
                require_contract_fields(step, required={"transition", "chapter_offset"})
                offset = step["chapter_offset"]
                if (
                    isinstance(offset, bool)
                    or not isinstance(offset, int)
                    or not 0 <= offset < policy.planning_window_chapters
                ):
                    raise KernelError(
                        "WORLD_PREPARATION_WINDOW_INVALID",
                        "preparation must remain inside the unaccepted planning window",
                    )
                WorldTransition.from_mapping(step["transition"])
    return candidates


def _simulate_preparation(
    *,
    reality: Mapping[str, Any],
    target: WorldTransition,
    path: Mapping[str, Any],
    chapter_number: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from novel_forge.modules.narrative_state.causal_batch import compile_causal_batch
    from .working_state import preview_preparation_transition

    steps = path["steps"]
    local_names = [step["transition"]["transition_id"] for step in steps]
    if len(local_names) != len(set(local_names)) or target.transition_id in local_names:
        raise KernelError(
            "WORLD_PREPARATION_IDENTITY_COLLISION",
            "preparation steps and target need distinct batch-local names",
        )
    known = {
        entry.get("source_event_id", "") for entry in state_index(reality).values()
    }
    known.update(event.get("event_id", "") for event in reality.get("events", []))
    known.update(reality.get("foundation_cause_refs", []))
    known.discard("")
    nodes = []
    by_name = {step["transition"]["transition_id"]: step for step in steps}
    for raw in [*(step["transition"] for step in steps), target.to_dict()]:
        refs = list(raw["cause_refs"])
        if raw["transition_id"] == target.transition_id:
            refs = list(
                dict.fromkeys([*refs, *(f"local:{name}" for name in local_names)])
            )
        nodes.append(
            {
                "event_id": f"planning:{path['path_id']}:{raw['transition_id']}",
                "state_kind": raw["state_kind"],
                "identity": {"entity_key": raw["entity_key"]},
                "story_time": raw["story_time"],
                "mutation": {
                    "payload": {
                        "causal_batch": {
                            "contract_version": "causal-batch-event.v1",
                            "local_id": raw["transition_id"],
                            "depends_on": refs,
                        }
                    }
                },
            }
        )
    graph = compile_causal_batch(nodes, accepted_ids=frozenset(known))
    schedule = []
    for node in graph.ordered:
        name = node["mutation"]["payload"]["causal_batch"]["local_id"]
        if name == target.transition_id:
            continue
        step = by_name[name]
        if any(
            by_name[parent]["chapter_offset"] > step["chapter_offset"]
            for parent in graph.ancestors[name]
        ):
            raise KernelError(
                "WORLD_PREPARATION_ORDER_INVALID",
                "a preparation cause cannot be scheduled after its effect",
            )
        working = deepcopy(reality)
        working.setdefault("events", []).extend(
            {"event_id": identity} for identity in known
        )
        for prior in schedule:
            if prior["transition"]["transition_id"] not in graph.ancestors[name]:
                continue
            working["current_state"], simulated = preview_preparation_transition(
                reality=working,
                transition=WorldTransition.from_mapping(prior["transition"]),
                chapter_number=prior["chapter_number"],
                path_id=path["path_id"],
            )
            working["events"].append(simulated)
        transition = WorldTransition.from_mapping(step["transition"])
        if not candidate_transition(transition, working)["eligible"]:
            raise KernelError(
                "WORLD_PREPARATION_UNSUPPORTED",
                "a preparation step has unfulfilled modeled preconditions",
            )
        preview_preparation_transition(
            reality=working,
            transition=transition,
            chapter_number=chapter_number + step["chapter_offset"],
            path_id=path["path_id"],
        )
        schedule.append(
            {
                "transition": json.loads(json.dumps(transition.to_dict())),
                "chapter_number": chapter_number + step["chapter_offset"],
                "depends_on": list(transition.cause_refs),
                "expected_effect": dict(transition.changes),
                "status": "PLANNED_NOT_ACCEPTED",
                "path_id": path["path_id"],
            }
        )
    working = deepcopy(reality)
    working.setdefault("events", []).extend(
        {"event_id": identity} for identity in known
    )
    for step in schedule:
        working["current_state"], simulated = preview_preparation_transition(
            reality=working,
            transition=WorldTransition.from_mapping(step["transition"]),
            chapter_number=step["chapter_number"],
            path_id=path["path_id"],
        )
        working["events"].append(simulated)
    validate_world_state_rules(
        reality=reality,
        state=state_index(working),
        affected_kinds={step["transition"]["state_kind"] for step in schedule},
    )
    if not candidate_transition(target, working)["eligible"]:
        raise KernelError(
            "WORLD_PREPARATION_INSUFFICIENT",
            "preparation does not establish the modeled target preconditions",
        )
    return schedule, working


def compile_world_plan(
    *,
    reality: Mapping[str, Any],
    generated: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    policy: WorldProductionPolicy,
    chapter_number: int,
    intent_version_id: str,
) -> dict[str, Any]:
    agency = reality.get("epistemic_contract") == "world-agency.v2"
    if agency:
        generated = _bind_candidate_identities(generated, reality)
    candidates = validate_generated_candidates(generated, policy)
    require_contract_fields(
        evaluation,
        required={"evaluations", "action_classifications"}
        if agency
        else {"evaluations"},
    )
    if agency:
        from .production_schema import agency_transition_paths

        paths = agency_transition_paths(generated)
        checks = evaluation["action_classifications"]
        if (
            not isinstance(checks, list)
            or len(checks) != len(paths)
            or {row.get("field_path") for row in checks} != set(paths)
        ):
            raise KernelError(
                "WORLD_AGENCY_REVIEW_BINDING_INVALID",
                "Director must check every exact generated action classification",
            )
        rejected = []
        for check in checks:
            require_contract_fields(
                check, required={"field_path", "supported", "rationale"}
            )
            if (
                type(check["supported"]) is not bool
                or not isinstance(check["rationale"], str)
                or not check["rationale"].strip()
            ):
                raise KernelError(
                    "WORLD_AGENCY_REVIEW_INVALID",
                    "action classification requires a located supported/unsupported judgment with reasons",
                )
            if not check["supported"]:
                rejected.append(check)
        if rejected:
            raise KernelError(
                "WORLD_AGENCY_CLASSIFICATION_REJECTED",
                json.dumps({"diagnostics": rejected}, ensure_ascii=False),
            )
    rows = evaluation["evaluations"]
    if not isinstance(rows, list):
        raise KernelError(
            "WORLD_DIRECTOR_REFERENCE_INVALID",
            "Director must evaluate the exact generated portfolio",
        )
    judged: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        require_contract_fields(
            row,
            required={"transition_id", "dimensions", "rationale", "preferred_path_id"},
        )
        require_text_fields(row, ("transition_id", "rationale"))
        if row["transition_id"] in judged:
            raise KernelError(
                "WORLD_DIRECTOR_REFERENCE_INVALID",
                "Director cannot duplicate a candidate evaluation",
            )
        judged[row["transition_id"]] = row
    if set(judged) != {
        candidate["transition"]["transition_id"] for candidate in candidates
    }:
        raise KernelError(
            "WORLD_DIRECTOR_REFERENCE_INVALID",
            "Director cannot invent or omit generated candidates",
        )
    base = {
        "contract_version": "world-production-plan.v1",
        "authority": "PLANNING_PROPOSAL",
        "baseline_id": reality["revision_id"],
        "accepted_through_chapter": reality["chapter_number"],
        "chapter_number": chapter_number,
        "intent_version_id": intent_version_id,
        "policy": asdict(policy),
        "reason": generated["reason"],
        "fact_mutation_allowed": False,
        "selected_candidate_id": "",
        "selected_path_id": "",
        "causal_debts": [],
        "candidate_futures": [],
        "preparation_schedule": [],
        "alternative_paths": [],
        "rejected_paths": [],
    }
    if not candidates:
        return _seal({**base, "disposition": generated["disposition"]})
    viable: list[dict[str, Any]] = []
    for source in candidates:
        name = source["transition"]["transition_id"]
        judgment = judged[name]
        transitions = [
            source["transition"],
            *(
                step["transition"]
                for path in source["preparation_paths"]
                for step in path["steps"]
            ),
        ]
        if any(
            raw["story_time"]["end_ordinal"]
            > int(
                reality.get("world_clock", {}).get(raw["story_time"]["timeline_id"], 0)
            )
            + policy.max_world_time_advance
            for raw in transitions
        ):
            base["candidate_futures"].append(
                {
                    "transition_id": name,
                    "eligible": False,
                    "rejection": {
                        "code": "WORLD_PRODUCTION_TIME_BOUND",
                        "message": "candidate or preparation exceeds the frozen world time horizon",
                    },
                    "dimensions": dict(judgment["dimensions"]),
                }
            )
            continue
        future = CandidateFuture.from_mapping(
            {
                key: value
                for key, value in {
                    **source,
                    "dimensions": judgment["dimensions"],
                    "rationale": judgment["rationale"],
                }.items()
                if key
                not in {
                    "preparation_paths",
                    "soft_assumptions",
                    "narrative_preferences",
                    "information_scope",
                }
            }
        )
        plan = build_causal_plan(
            reality=reality,
            candidates=(future,),
            chapter_number=chapter_number,
            intent_revision_id=intent_version_id,
        )
        evaluated = plan["candidate_futures"][0]
        base["candidate_futures"].append(
            {
                **evaluated,
                "hypotheses": source["soft_assumptions"],
                "narrative_preferences": source["narrative_preferences"],
                "preparation_paths": source["preparation_paths"],
                "information_scope": source.get(
                    "information_scope",
                    {"reader_exposure": "CONCEAL", "reveal_event_ids": []},
                ),
            }
        )
        preferred = judgment["preferred_path_id"]
        if preferred and preferred not in {
            path["path_id"] for path in source["preparation_paths"]
        }:
            raise KernelError(
                "WORLD_DIRECTOR_REFERENCE_INVALID",
                "Director preferred path must exist in the generated portfolio",
            )
        paths = []
        if not evaluated["eligible"]:
            for path in source["preparation_paths"]:
                try:
                    schedule, simulated = _simulate_preparation(
                        reality=reality,
                        target=future.transition,
                        path=path,
                        chapter_number=chapter_number,
                    )
                    paths.append(
                        {**path, "schedule": schedule, "simulation": simulated}
                    )
                except KernelError as exc:
                    base["rejected_paths"].append(
                        {
                            **path,
                            "target_transition_id": name,
                            "rejection": {"code": exc.code, "message": str(exc)},
                        }
                    )
            if not paths:
                continue
        paths.sort(key=lambda path: (path["path_id"] != preferred, path["path_id"]))
        if paths and evaluated.get("rejection"):
            proven = build_causal_plan(
                reality=paths[0]["simulation"],
                candidates=(future,),
                chapter_number=chapter_number,
                intent_revision_id=intent_version_id,
            )
            evaluated = {**proven["candidate_futures"][0], "eligible": False}
            baseline_index = state_index(reality)
            receipts = {
                r.requirement_id: evaluate_requirement(r, baseline_index)
                for r in (
                    *future.transition.requirements,
                    *future.transition.epistemic_basis,
                )
            }
            evaluated["requirements"] = list(receipts.values())
            plan["causal_debts"] = [
                {
                    **debt,
                    "preparation": receipts[debt["requirement_id"]],
                    "status": "DISCHARGED_BY_ACCEPTED_REALITY"
                    if receipts[debt["requirement_id"]]["satisfied"]
                    else "PREPARATION_REQUIRED",
                    "discharge_evidence": receipts[debt["requirement_id"]][
                        "source_event_id"
                    ]
                    if receipts[debt["requirement_id"]]["satisfied"]
                    else "",
                }
                for debt in proven["causal_debts"]
            ]
            base["candidate_futures"][-1] = {
                **base["candidate_futures"][-1],
                **evaluated,
            }
            base["candidate_futures"][-1].pop("rejection", None)
        viable.append(
            {"candidate": evaluated, "debts": plan["causal_debts"], "paths": paths}
        )
    if not viable:
        return _seal(
            {
                **base,
                "disposition": "BLOCKED",
                "reason": "No candidate has a legal modeled preparation path; revise the future goal or provide new accepted support.",
            }
        )
    viable.sort(
        key=lambda item: (
            -item["candidate"]["rank_value"],
            item["candidate"]["candidate_id"],
        )
    )
    selected = viable[0]
    paths = selected["paths"]
    selected_source = next(
        item
        for item in base["candidate_futures"]
        if item.get("candidate_id") == selected["candidate"]["candidate_id"]
    )
    current_batch = bool(
        agency
        and paths
        and all(
            step["chapter_number"] == chapter_number for step in paths[0]["schedule"]
        )
    )
    disclosure_projection = []
    from novel_forge.modules.narrative_state.information import (
        project_disclosure,
        project_candidate_disclosure,
    )

    for row in selected_source["information_scope"].get("disclosures", []):
        if agency and row.get("event_id", "").startswith("local:"):
            schedule = paths[0]["schedule"] if paths else []
            if any(step["chapter_number"] != chapter_number for step in schedule):
                raise KernelError(
                    "WORLD_DISCLOSURE_SOURCE_SCOPE_INVALID",
                    "a later chapter's preparation cannot support this chapter's disclosure",
                )
            disclosure_projection.append(
                project_candidate_disclosure(
                    reality,
                    row,
                    transitions=[
                        *(step["transition"] for step in schedule),
                        selected_source["transition"],
                    ],
                    chapter_number=chapter_number,
                    path_id=paths[0]["path_id"] if paths else "direct",
                )
            )
        else:
            disclosure_projection.append(project_disclosure(reality, row))
    for event_id in selected_source["information_scope"].get("reveal_event_ids", []):
        from novel_forge.modules.narrative_state.information import (
            accepted_event_projection,
        )

        entry = accepted_event_projection(reality, event_id)
        disclosure_projection.append(
            {
                "fact_id": event_id,
                "audience": "READER",
                "mode": "CONFIRM",
                "source": entry,
            }
        )
    return _seal(
        {
            **base,
            "disposition": "ELIGIBLE"
            if selected["candidate"]["eligible"]
            else "PREPARATION_REQUIRED",
            "selected_candidate_id": selected["candidate"]["candidate_id"],
            "disclosure_projection": disclosure_projection,
            "causal_debts": _renew_cancelled_preparation(selected["debts"], reality),
            "selected_path_id": paths[0]["path_id"] if paths else "",
            "preparation_schedule": paths[0]["schedule"] if paths else [],
            **({"target_in_current_batch": True} if current_batch else {}),
            "alternative_paths": [
                {
                    key: value
                    for key, value in path.items()
                    if key not in {"schedule", "simulation"}
                }
                for path in paths[1:]
            ],
        }
    )


def _bind_candidate_identities(generated, reality):
    from novel_forge.modules.narrative_state.contracts import (
        NarrativeStateKind,
        _identity_for,
    )

    result = deepcopy(generated)
    singles = {
        "character_state": "character_id",
        "world_state": "world_state_id",
        "location_state": "location_id",
        "faction_state": "faction_id",
        "power_state": "character_id",
    }
    for candidate in result["candidates"]:
        transitions = [
            candidate["transition"],
            *(
                step["transition"]
                for path in candidate["preparation_paths"]
                for step in path["steps"]
            ),
        ]
        aliases = {}
        for raw in transitions:
            transition = WorldTransition.from_mapping(raw)
            changes = dict(transition.changes)
            key = transition.entity_key
            if "=" in key:
                identity = dict(part.split("=", 1) for part in key.split("|"))
                if any(
                    field in changes and str(changes[field]) != value
                    for field, value in identity.items()
                ):
                    raise KernelError(
                        "WORLD_BACKGROUND_IDENTITY_MISMATCH",
                        "World content cannot replace its typed entity identity",
                    )
                changes.update(identity)
            elif transition.state_kind.value in singles:
                field = singles[transition.state_kind.value]
                if key not in reality.get("approved_entity_ids", []):
                    raise KernelError(
                        "WORLD_GENERATION_IDENTITY_UNKNOWN",
                        "an opaque entity key must resolve to approved Foundation identity",
                    )
                if field in changes and changes[field] != key:
                    raise KernelError(
                        "WORLD_BACKGROUND_IDENTITY_MISMATCH",
                        "World content cannot replace its approved entity identity",
                    )
                changes[field] = key
            identity = _identity_for(
                NarrativeStateKind(transition.state_kind),
                changes,
                ordinal=0,
                source="",
                allow_legacy_fallback=False,
            )
            alias = (raw["state_kind"], key)
            if alias in aliases and aliases[alias] != identity.entity_key:
                raise KernelError(
                    "WORLD_GENERATION_IDENTITY_COLLISION",
                    "one local entity alias cannot name different typed records",
                )
            aliases[alias] = identity.entity_key
            raw.update(
                json.loads(json.dumps(transition.to_dict())),
                changes=changes,
                entity_key=identity.entity_key,
            )
        for raw in transitions:
            for predicate in [*raw["requirements"], *raw["epistemic_basis"]]:
                predicate["entity_key"] = aliases.get(
                    (predicate["state_kind"], predicate["entity_key"]),
                    predicate["entity_key"],
                )
            observation = raw["changes"].get("observation_source")
            if observation:
                observation["entity_key"] = aliases.get(
                    (observation["state_kind"], observation["entity_key"]),
                    observation["entity_key"],
                )
    return result


def _renew_cancelled_preparation(
    debts: list[dict[str, Any]], reality: Mapping[str, Any]
) -> list[dict[str, Any]]:
    prior = {
        entry["state"]["obligation_id"]: entry
        for entry in reality["current_state"].get("narrative_obligation", [])
    }
    result = deepcopy(debts)
    for debt in result:
        for _ in range(len(prior) + 1):
            old = prior.get(debt["debt_id"])
            if old is None or old["state"].get("status") != "CANCELLED":
                break
            if not old.get("source_event_id"):
                raise KernelError(
                    "WORLD_PREPARATION_RETIREMENT_UNPROVEN",
                    "renewal requires an exact accepted retirement event",
                )
            debt["debt_id"] = "causal-debt:" + narrative_hash(
                {
                    "prior_debt_id": debt["debt_id"],
                    "retirement_event_id": old["source_event_id"],
                }
            )
    return result


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "plan_digest": narrative_hash(value)}
