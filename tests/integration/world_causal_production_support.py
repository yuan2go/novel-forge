import json

from novel_forge.modules.chapter_authority.execution_gateway import (
    default_chapter_fixture_response,
)
from novel_forge.modules.story_planning_runtime.execution import (
    planning_fixture_response,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.workers.book_authority import (
    execute_book_coordination_claim,
    schedule_book_coordination_jobs,
)
from tests.integration.narrative_reality_vertical_support import admit_native_production


def capture_world_execution_evidence(*, composition, project_id, book_run_id):
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    query = AuthorityAssetQuery(composition.authority.database_url)
    documents = {}
    for kind in (
        "world_preparation_source",
        "world_preparation_generation",
        "world_preparation_evaluation",
        "narrative_governance_action",
        "context_bundle",
    ):
        for document in query.list(project_id=project_id, asset_type=kind, limit=100):
            if document.logical_ref.startswith("world_preparation/"):
                documents[document.asset_version_id] = document
    effect_ids, action_ids = set(), set()
    for document in tuple(documents.values()):
        if document.asset_type == "narrative_governance_action":
            action_ids.add(document.asset_version_id)
        if document.asset_type not in {
            "world_preparation_generation",
            "world_preparation_evaluation",
        }:
            continue
        evidence = document.content["contract"]["evidence"]
        assert evidence["fixture_protocol_only"] and not evidence["real_model_call"]
        effect_ids.add(evidence["external_receipt_ref"])
        for key in (
            "cost_receipt_ref",
            "usage_receipt_ref",
            "input_manifest_ref",
            "output_manifest_ref",
            "validation_manifest_ref",
        ):
            ref = evidence[key]
            selector = (
                {"asset_version_id": ref.split(":", 1)[1]}
                if ref.startswith("authority-asset-version:")
                else {"logical_ref": ref}
            )
            receipt = query.require(project_id=project_id, **selector)
            documents[receipt.asset_version_id] = receipt
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute(
            "SELECT to_jsonb(effect) FROM authority_external_effect effect WHERE external_effect_id=ANY(%s) ORDER BY external_effect_id",
            [sorted(effect_ids)],
        )
        effects = [row[0] for row in uow.cursor.fetchall()]
        assert len(effects) == len(effect_ids) and all(
            effect["status"] == "SUCCEEDED" for effect in effects
        )
        uow.cursor.execute(
            "SELECT to_jsonb(dispatch), to_jsonb(receipt) FROM authority_external_effect_dispatch dispatch LEFT JOIN authority_external_receipt receipt USING(dispatch_id) WHERE dispatch.external_effect_id=ANY(%s) ORDER BY dispatch.external_effect_id, dispatch.generation",
            [sorted(effect_ids)],
        )
        receipts = [
            {"dispatch": row[0], "receipt": row[1]} for row in uow.cursor.fetchall()
        ]
        uow.cursor.execute(
            "SELECT v.asset_version_id, v.content_hash, a.asset_type, v.content#>>'{constraint_envelope,world_preparation,asset_version_id}' FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND v.content#>>'{constraint_envelope,world_preparation,asset_version_id}'=ANY(%s) ORDER BY v.asset_version_id",
            [project_id, sorted(action_ids)],
        )
        consumers = [
            dict(
                zip(
                    (
                        "asset_version_id",
                        "content_hash",
                        "asset_type",
                        "world_action_version_id",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in uow.cursor.fetchall()
        ]
    book = composition.authority.require(book_run_id)
    realities = [
        composition.query.narrative_reality(
            book_run_id=book_run_id, chapter_number=chapter
        )
        for chapter in range(1, int(book["accepted_through_chapter"]) + 1)
    ]
    return {
        "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
        "artifacts": [
            {
                "asset_version_id": doc.asset_version_id,
                "asset_type": doc.asset_type,
                "logical_ref": doc.logical_ref,
                "content_hash": doc.content_hash,
                "content": doc.content,
            }
            for doc in sorted(
                documents.values(), key=lambda item: item.asset_version_id
            )
        ],
        "effects": effects,
        "receipts": receipts,
        "planning_consumers": consumers,
        "accepted_realities": realities,
    }


class AutonomousWorldTransport:
    def __init__(self, scenario="delayed_disclosure"):
        self.calls = []
        self.scenario = scenario
        self.faults = []

    def post_provider_checkpoint(self, point):
        if (
            self.scenario == "provider_recovery"
            and not self.faults
            and point == "after_provider_receipt_before_budget_settlement"
            and self.calls[-1]["stage"] == "world_candidates.generate"
        ):
            self.faults.append(point)
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "MODEL_EFFECT_RETRYABLE_WORLD_PROOF",
                "injected process loss after confirmed world Provider receipt",
            )

    def planning(self, stage, inputs):
        self.calls.append({"stage": stage, "input": json.loads(json.dumps(inputs))})
        if stage == "world_candidates.generate":
            task = inputs["world_preparation"]
            rule = next(
                rule
                for rule in task["world_foundation"]["rules"]
                if rule["enforcement"] != "SOFT_CAUSAL"
            )
            predicate = rule["predicate"]
            actor = task["approved_entity_ids"][0]
            tick = max(task["world_clock"].values(), default=0) + 1
            proposed = {
                "transition_id": "advance-faction-pressure",
                "actor_id": actor,
                "camera": "OFF_CAMERA",
                "story_time": {
                    "timeline_id": "main",
                    "start_ordinal": tick,
                    "end_ordinal": tick,
                    "precision": "EXACT",
                    "label": "",
                },
                "action": "act on the approved faction pressure",
                "state_kind": predicate["state_kind"],
                "entity_key": predicate["entity_key"],
                "changes": {predicate["field"]: predicate["value"]},
                "requirements": [],
                "epistemic_basis": [],
                "cause_refs": [task["foundation_cause_refs"][0]],
            }
            result = {
                "disposition": "CANDIDATES",
                "reason": "The approved faction pressure can advance off camera.",
                "candidates": [
                    {
                        "transition": {"payload_json": json.dumps(proposed)},
                        "affected_entities": [actor],
                        "world_consequences": [
                            "Faction pressure advances without public disclosure."
                        ],
                        "arc_refs": [],
                        "obligation_refs": [],
                        "risks": [],
                        "rationale": "Approved rule and initial faction provide causal support.",
                        "information_scope": {
                            "reader_exposure": "CONCEAL",
                            "reveal_event_ids": [],
                        },
                        "soft_assumptions": ["The faction chooses to act."],
                        "narrative_preferences": ["Delay disclosure."],
                        "preparation_paths": [],
                    }
                ],
            }
            if self.scenario in {
                "reader_partial",
                "character_disclosure",
                "reader_misdirect",
                "mixed_disclosure",
                "withhold_disclosure",
            }:
                proposed["changes"]["private_marker"] = (
                    "UNREVEALED_SUCCESSOR_AND_PRIVATE_CAUSE"
                )
                result["candidates"][0]["transition"] = {
                    "payload_json": json.dumps(proposed)
                }
            if self.scenario == "multi_preparation":
                from copy import deepcopy

                if task["accepted_through_chapter"]:
                    result = {
                        "disposition": "NO_OP"
                        if task["accepted_through_chapter"] == 1
                        else "DEFER",
                        "reason": "Continue existing accepted preparation before inventing another future.",
                        "candidates": [],
                    }
                else:
                    first = deepcopy(proposed)
                    first.update(
                        transition_id="gather-records",
                        changes={**proposed["changes"], "phase": 1},
                    )
                    second = deepcopy(first)
                    second.update(
                        transition_id="verify-records",
                        cause_refs=["local:gather-records"],
                        changes={**proposed["changes"], "phase": 2},
                    )
                    second["story_time"].update(
                        start_ordinal=tick + 1, end_ordinal=tick + 1
                    )
                    proposed.update(
                        transition_id="resolve-inquiry",
                        cause_refs=["local:verify-records"],
                        changes={**proposed["changes"], "goal_reached": True},
                        requirements=[
                            {
                                "requirement_id": "records-verified",
                                "state_kind": predicate["state_kind"],
                                "entity_key": predicate["entity_key"],
                                "field": "phase",
                                "operator": "EQUALS",
                                "value": 2,
                            }
                        ],
                    )
                    proposed["story_time"].update(
                        start_ordinal=tick + 2, end_ordinal=tick + 2
                    )
                    result["candidates"][0]["transition"] = {
                        "payload_json": json.dumps(proposed)
                    }
                    result["candidates"][0]["preparation_paths"] = [
                        {
                            "path_id": "records-path",
                            "rationale": "Records must be gathered before verification before resolution.",
                            "steps": [
                                {
                                    "chapter_offset": 0,
                                    "transition": {"payload_json": json.dumps(first)},
                                },
                                {
                                    "chapter_offset": 1,
                                    "transition": {"payload_json": json.dumps(second)},
                                },
                            ],
                        }
                    ]
            elif self.scenario == "causal_preparation":
                from copy import deepcopy

                step = deepcopy(proposed)
                step["transition_id"] = "prepare-inquiry"
                step["changes"]["prepared"] = True
                proposed["transition_id"] = "complete-prepared-inquiry"
                proposed["changes"]["goal_reached"] = True
                proposed["requirements"] = [
                    {
                        "requirement_id": "prepared-inquiry",
                        "state_kind": "world_state",
                        "entity_key": "world_state_id=council-inquiry",
                        "field": "prepared",
                        "operator": "EQUALS",
                        "value": True,
                    }
                ]
                supports = [
                    entry
                    for entry in task["context_projection"]["selection"]
                    if entry["entity_key"] == "world_state_id=council-inquiry"
                ]
                if supports:
                    proposed["cause_refs"] = [supports[0]["source_event_id"]]
                candidate = result["candidates"][0]
                candidate["transition"] = {"payload_json": json.dumps(proposed)}
                candidate["preparation_paths"] = [
                    {
                        "path_id": "prepare-inquiry-path",
                        "rationale": "Establish the missing preparation before the target.",
                        "steps": [
                            {
                                "chapter_offset": 0,
                                "transition": {"payload_json": json.dumps(step)},
                            }
                        ],
                    }
                ]
            elif (
                self.scenario == "historical_disclosure"
                and task["accepted_through_chapter"] == 1
            ):
                proposed["transition_id"] = "subsequent-faction-event"
                proposed["changes"]["phase"] = 2
                result["candidates"][0]["transition"] = {
                    "payload_json": json.dumps(proposed)
                }
            elif task["accepted_through_chapter"]:
                hidden = next(
                    entry
                    for entry in task["context_projection"]["selection"]
                    if (entry["state"].get("fact_origin") or {}).get("kind")
                    == "GOVERNED_BACKGROUND"
                )
                if self.scenario == "historical_disclosure":
                    prior_event = min(
                        (
                            item
                            for item in task["accepted_history"]
                            if item["state_kind"] == "world_state"
                        ),
                        key=lambda item: item["accepted_chapter"],
                    )
                    assert prior_event["accepted_chapter"] == 1
                    hidden = {"source_event_id": prior_event["event_id"]}
                proposed.update(
                    {
                        "transition_id": "reveal-accepted-notice",
                        "camera": "ON_CAMERA",
                        "state_kind": "disclosure_event",
                        "entity_key": "disclosure_id=accepted-notice",
                        "changes": {
                            "disclosure_id": "accepted-notice",
                            "fact_id": hidden["source_event_id"],
                            "audience": "READER",
                            "disclosure_mode": "CONFIRM",
                        },
                        "cause_refs": [hidden["source_event_id"]],
                    }
                )
                result["candidates"][0]["transition"] = {
                    "payload_json": json.dumps(proposed)
                }
                result["candidates"][0]["information_scope"] = {
                    "reader_exposure": "REVEAL",
                    "reveal_event_ids": [hidden["source_event_id"]],
                }
            if task.get("disclosure_contract") == "world-information-scope.v2":
                for candidate in result["candidates"]:
                    information = candidate["information_scope"]
                    audience = (
                        task["character_definitions"][0]["character_id"]
                        if self.scenario == "character_disclosure"
                        else "READER"
                    )
                    mode = {
                        "reader_partial": "PARTIAL",
                        "reader_misdirect": "MISDIRECT",
                        "withhold_disclosure": "WITHHOLD",
                    }.get(self.scenario, "CONFIRM")
                    rows = [
                        {
                            "disclosure_id": "accepted-notice",
                            "event_id": event_id,
                            "audience": audience,
                            "mode": mode,
                            "fields": [] if mode == "WITHHOLD" else ["status"],
                            "presentation_channel": "LETTER",
                            "claim_kind": "HISTORICAL_OCCURRENCE",
                        }
                        for event_id in information["reveal_event_ids"]
                    ]
                    if rows and self.scenario == "mixed_disclosure":
                        rows.append(
                            {
                                **rows[0],
                                "disclosure_id": "character-notice",
                                "audience": task["character_definitions"][0][
                                    "character_id"
                                ],
                            }
                        )
                    candidate["information_scope"] = {"disclosures": rows}
                    if rows:
                        raw = json.loads(candidate["transition"]["payload_json"])
                        raw["changes"].update(audience=audience, disclosure_mode=mode)
                        candidate["transition"]["payload_json"] = json.dumps(raw)
        elif stage == "world_candidates.evaluate":
            from novel_forge.modules.hierarchical_planning.causal_domain import (
                DIRECTOR_DIMENSIONS,
            )

            result = {
                "evaluations": [
                    {
                        "transition_id": item["transition"]["transition_id"],
                        "dimensions": dict.fromkeys(DIRECTOR_DIMENSIONS, 0.8),
                        "rationale": "The generated transition follows the supplied rule and preserves information asymmetry.",
                        "preferred_path_id": "",
                    }
                    for item in inputs["world_preparation"]["generated_portfolio"][
                        "candidates"
                    ]
                ]
            }
        else:
            result = planning_fixture_response(stage, inputs)
            if stage == "chapter_plan.generate":
                for disclosure in inputs.get("world_preparation", {}).get(
                    "disclosures", []
                ):
                    result["disclosures"].append(
                        {
                            "disclosure_id": disclosure.get(
                                "disclosure_id", "accepted-notice"
                            ),
                            "fact_id": disclosure["fact_id"],
                            "audience": disclosure["audience"],
                            "mode": disclosure["mode"],
                            "presentation_channel": disclosure.get(
                                "presentation_channel", "DOCUMENT"
                            ),
                            "earliest_chapter": result["chapter_number"],
                        }
                    )
                    result["knowledge_boundaries"].append(
                        {
                            "layer": "READER_KNOWLEDGE"
                            if disclosure["audience"] == "READER"
                            else "CHARACTER_KNOWLEDGE",
                            "subject_id": "reader"
                            if disclosure["audience"] == "READER"
                            else disclosure["audience"],
                            "fact_id": disclosure["fact_id"],
                            "status": {
                                "CONFIRM": "KNOWN",
                                "PARTIAL": "SUSPECTED",
                                "HINT": "HINTED",
                                "MISDIRECT": "MISDIRECTED",
                                "WITHHOLD": "WITHHELD",
                            }[disclosure["mode"]],
                            "available_from_chapter": result["chapter_number"],
                        }
                    )
        self.calls[-1]["output"] = result
        return result

    def __call__(self, stage, inputs):
        self.calls.append({"stage": stage, "input": json.loads(json.dumps(inputs))})
        result = default_chapter_fixture_response(stage, inputs)
        prose = {
            "character_disclosure": "Mara reads the sealed notice and understands it; its contents remain unquoted.",
            "reader_partial": "The notice hints at an earlier inquiry but withholds its concealed participants.",
            "reader_misdirect": "The notice presents a misleading impression of the earlier inquiry.",
            "withhold_disclosure": "The sealed notice remains unread and its contents remain hidden.",
        }.get(
            self.scenario,
            "The dated notice confirms that the council inquiry was already open.",
        )
        if stage == "draft" and any(
            item["disclosure_id"] == "accepted-notice"
            for item in inputs["plan"].get("disclosures", [])
        ):
            result["scene_artifacts"][-1]["text"] += " " + prose
            result["text"] = "\n\n".join(
                item["text"] for item in result["scene_artifacts"]
            )
        if (
            self.scenario.startswith("intra_chapter")
            and stage == "draft"
            and int(inputs["plan"]["chapter"]) == 1
        ):
            result["scene_artifacts"][-1]["text"] += (
                " Mara receives a signed message identifying the meeting room. Using the message, Mara redirects the messenger."
            )
            result["text"] = "\n\n".join(
                item["text"] for item in result["scene_artifacts"]
            )
        if (
            self.scenario.startswith("intra_chapter")
            and stage == "canon_extraction"
            and int(inputs["revision"]["chapter"]) == 1
        ):
            text = inputs["revision"]["text"]
            received = "Mara receives a signed message identifying the meeting room."
            acted = "Using the message, Mara redirects the messenger."

            def time(tick):
                return {
                    "timeline_id": "main",
                    "start_ordinal": tick,
                    "end_ordinal": tick,
                    "precision": "EXACT",
                    "label": "",
                }

            result["character_knowledge_changes"].append(
                {
                    "character_id": "mara",
                    "fact_id": "meeting-room",
                    "status": "KNOWN",
                    "summary": received,
                    "evidence_start": text.index(received),
                    "evidence_end": text.index(received) + len(received),
                    "confidence": 1.0,
                    "causal_batch": {
                        "contract_version": "causal-batch-event.v1",
                        "local_id": "receive-message",
                        "depends_on": [],
                    },
                    "story_time": time(1),
                }
            )
            transition = {
                "transition_id": "act-on-message",
                "actor_id": "mara",
                "camera": "ON_CAMERA",
                "story_time": time(2),
                "action": acted,
                "state_kind": "consequence_state",
                "entity_key": "consequence_id=redirect-message",
                "changes": {"status": "REDIRECTED"},
                "requirements": [],
                "epistemic_basis": [
                    {
                        "requirement_id": "mara-received-message",
                        "state_kind": "character_knowledge",
                        "entity_key": "character_id=mara|fact_id=meeting-room",
                        "field": "status",
                        "operator": "EQUALS",
                        "value": "KNOWN",
                    }
                ],
                "cause_refs": ["local:receive-message"],
            }
            result["consequence_changes"].append(
                {
                    "consequence_id": "redirect-message",
                    "status": "REDIRECTED",
                    "summary": acted,
                    "evidence_start": text.index(acted),
                    "evidence_end": text.index(acted) + len(acted),
                    "confidence": 1.0,
                    "world_transition": {"payload_json": json.dumps(transition)},
                    "causal_batch": {
                        "contract_version": "causal-batch-event.v1",
                        "local_id": "act-on-message",
                        "depends_on": ["local:receive-message"],
                    },
                    "story_time": time(2),
                }
            )
        if stage == "canon_extraction":
            for disclosure in inputs.get("execution_expectations", {}).get(
                "disclosures", []
            ):
                if disclosure["disclosure_id"] not in {
                    "accepted-notice",
                    "character-notice",
                }:
                    continue
                text = inputs["revision"]["text"]
                start = text.index(prose)
                result["disclosure_events"] = [
                    item
                    for item in result["disclosure_events"]
                    if item.get("disclosure_id") != disclosure["disclosure_id"]
                ]
                result["disclosure_events"].append(
                    {
                        "disclosure_id": disclosure["disclosure_id"],
                        "fact_id": disclosure["fact_id"],
                        "audience": disclosure["audience"],
                        "disclosure_mode": disclosure["mode"],
                        "presentation_channel": disclosure["presentation_channel"],
                        "summary": prose,
                        "evidence_start": start,
                        "evidence_end": start + len(prose),
                        "confidence": 1.0,
                    }
                )
        if stage == "canon_extraction" and self.scenario == "intra_chapter_missing":
            result["character_knowledge_changes"] = []
        if stage == "canon_extraction" and self.scenario == "intra_chapter_cycle":
            result["character_knowledge_changes"][-1]["causal_batch"]["depends_on"] = [
                "local:act-on-message"
            ]
        self.calls[-1]["output"] = result
        return result


def execute_autonomous_world_vertical(
    *,
    composition,
    chapter_application,
    snapshot,
    generic,
    transport,
    runtime_config=None,
):
    from novel_forge.modules.command_kernel.errors import KernelError

    if transport.scenario == "manual_director":
        from novel_forge.modules.book_authority.control_policy import ControlPolicy

        composition.controls.configure(
            project_id=snapshot.project_id,
            workspace_id=snapshot.workspace_id,
            policy=ControlPolicy(
                policy_version="native-director-review-v1", mode="MANUAL_DIRECTOR"
            ),
            principal=composition.principal,
            idempotency_key=f"{snapshot.project_id}:control-policy",
            trace_id=f"{snapshot.project_id}:control-policy",
            correlation_id=snapshot.project_id,
        )
    admitted = admit_native_production(
        composition=composition, snapshot=snapshot, generic=generic
    )
    if transport.scenario == "process_recovery":
        from tests.integration.world_process_recovery_support import (
            run_process_recovery,
        )

        return run_process_recovery(
            composition=composition,
            runtime_config=runtime_config,
            book_run_id=admitted.book_run_id,
            project_id=snapshot.project_id,
        )
    jobs = RuntimeJobAuthority(composition.authority.database_url)
    coordination = []
    first_reality = None
    decisions = []
    acceptance_faults = []
    lease_takeovers = []
    armed = False

    def acceptance_failure(point):
        nonlocal armed
        if point == "after_chapter_acceptance":
            if not acceptance_faults:
                acceptance_faults.append(point)
                raise RuntimeError("injected world acceptance rollback")
            armed = True
        if (
            point == "after_operation_completion_before_response"
            and armed
            and len(acceptance_faults) == 1
        ):
            acceptance_faults.append(point)
            raise RuntimeError("injected world acceptance response loss")

    if transport.scenario == "acceptance_recovery":
        composition.authority.failure_injector = acceptance_failure
    for _ in range(60):
        schedule_book_coordination_jobs(
            composition.query, jobs, limit=1, book_run_id=admitted.book_run_id
        )
        if transport.scenario == "concurrent_workers" and not lease_takeovers:
            from concurrent.futures import ThreadPoolExecutor
            import time
            import pytest

            def compete(worker):
                return jobs.claim(
                    runtime_group="book",
                    worker_id=worker,
                    lease_seconds=1,
                    job_kinds=("BOOK_COORDINATION_TICK",),
                    subject_kind="BOOK_RUN",
                    subject_id=admitted.book_run_id,
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                competed = list(
                    pool.map(compete, ("world-worker-one", "world-worker-two"))
                )
            held = [item for item in competed if item is not None]
            assert len(held) == 1
            abandoned = held[0]
            time.sleep(1.1)
            successor = compete("world-worker-successor")
            assert (
                successor is not None
                and successor.runtime_job_id == abandoned.runtime_job_id
            )
            assert successor.fencing_token > abandoned.fencing_token
            with pytest.raises(KernelError):
                jobs.complete(abandoned, {"forged": "late predecessor"})
            lease_takeovers.append(
                {
                    "abandoned_attempt_id": abandoned.attempt_id,
                    "successor_attempt_id": successor.attempt_id,
                }
            )
            result = execute_book_coordination_claim(
                jobs, composition, successor, lease_seconds=1
            )
            coordination.append(result)
            assert jobs.complete(successor, result)["replayed"] is True
            continue
        claim = jobs.claim(
            runtime_group="book",
            worker_id="world-causal-worker",
            lease_seconds=30,
            job_kinds=("BOOK_COORDINATION_TICK",),
            subject_kind="BOOK_RUN",
            subject_id=admitted.book_run_id,
        )
        assert claim is not None, {
            "coordination": coordination,
            "book": composition.authority.require(admitted.book_run_id),
        }
        try:
            result = execute_book_coordination_claim(jobs, composition, claim)
        except RuntimeError as exc:
            if transport.scenario != "acceptance_recovery" or not str(exc).startswith(
                "injected world acceptance"
            ):
                raise
            if len(acceptance_faults) == 1:
                assert (
                    composition.authority.require(admitted.book_run_id)[
                        "accepted_through_chapter"
                    ]
                    == 0
                )
            continue
        except KernelError as exc:
            if (
                exc.code != "MODEL_EFFECT_RETRYABLE_WORLD_PROOF"
                or transport.scenario != "provider_recovery"
            ):
                raise
            assert (
                composition.authority.require(admitted.book_run_id)[
                    "accepted_through_chapter"
                ]
                == 0
            )
            continue
        coordination.append(result)
        assert jobs.complete(claim, result)["replayed"] is True
        if result["action"] == "WAIT_CONTROL_DECISION":
            assert transport.scenario == "manual_director"
            readiness = composition.controls.readiness(
                project_id=snapshot.project_id, book_run_id=admitted.book_run_id
            )
            gate = next(
                item
                for item in readiness["gates"]
                if item["status"] == "WAITING_OPERATOR"
            )
            decisions.append(
                composition.controls.decide(
                    principal=composition.principal,
                    project_id=snapshot.project_id,
                    book_run_id=admitted.book_run_id,
                    chapter_number=readiness["chapter_number"],
                    boundary=gate["boundary"],
                    subject_version_id=gate["subject_version_id"],
                    decision="APPROVE",
                    reason="Fixture operator decision verifies governance only",
                    idempotency_key=f"{admitted.book_run_id}:approve:{gate['subject_version_id']}",
                    trace_id=admitted.book_run_id,
                    correlation_id=admitted.book_run_id,
                )
            )
            continue
        if result["state"] == "PLAN_APPROVAL_PENDING":
            from novel_forge.storage.authority_uow import AuthorityUnitOfWork

            with AuthorityUnitOfWork(composition.authority.database_url) as uow:
                uow.cursor.execute(
                    "SELECT status, report FROM authority_story_planning_validation_report WHERE project_id=%s AND status='FAIL'",
                    [snapshot.project_id],
                )
                reports = uow.cursor.fetchall()
            raise AssertionError(
                {
                    "generation": composition.planning.require_generation(
                        result["operation_id"]
                    ),
                    "validation_failures": reports,
                }
            )
        if result["action"] == "DISPATCH_CHAPTER":
            stages = [call["stage"] for call in transport.calls]
            generated_task = next(
                call["input"]["world_preparation"]
                for call in reversed(transport.calls)
                if call["stage"] == "world_candidates.generate"
            )
            assert generated_task.get("character_definitions"), (
                "World reasoning requires the approved character goals and definitions"
            )
            assert {
                item["role"] for item in generated_task.get("planning_window", [])
            } >= {"book_plan", "arc_plans", "chapter_group_plan"}, (
                "World generation and Director need the exact approved planning window"
            )
            assert "world_candidates.generate" in stages, (
                "native Supervisor must generate candidates before Chapter dispatch"
            )
            assert "world_candidates.evaluate" in stages, (
                "Director evidence must come from the governed Provider evaluation stage"
            )
            assert (
                stages.index("world_candidates.generate")
                < stages.index("world_candidates.evaluate")
                < stages.index("chapter_plan.generate")
            )
            scheduler = chapter_application.scheduler(
                principal=Principal(
                    principal_id="world-causal-worker",
                    principal_type=PrincipalType.WORKER,
                    permissions=composition.principal.permissions
                    - {"book.authority.approve_replan"},
                    project_scope=composition.principal.project_scope,
                    authentication_source="postgres-native-world-worker-fixture",
                )
            )
            for _ in range(80):
                try:
                    tick = scheduler.tick(
                        project_id=snapshot.project_id,
                        root_operation_id=result["operation_id"],
                    )
                except KernelError as exc:
                    expected = {
                        "intra_chapter_missing": "WORLD_BATCH_REFERENCE_UNKNOWN",
                        "intra_chapter_cycle": "WORLD_BATCH_CAUSAL_CYCLE",
                    }.get(transport.scenario)
                    if expected is None or exc.code != expected:
                        raise
                    assert (
                        composition.authority.require(admitted.book_run_id)[
                            "accepted_through_chapter"
                        ]
                        == 0
                    )
                    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

                    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
                        uow.cursor.execute(
                            "SELECT count(*) FROM authority_narrative_reality_revision WHERE book_run_id=%s",
                            [admitted.book_run_id],
                        )
                        assert uow.cursor.fetchone()[0] == 0
                        uow.cursor.execute(
                            "SELECT count(*) FROM authority_reality_event_index WHERE book_run_id=%s",
                            [admitted.book_run_id],
                        )
                        assert uow.cursor.fetchone()[0] == 0
                    return {
                        "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
                        "rejection": exc.code,
                        "book_run_id": admitted.book_run_id,
                        "calls": transport.calls,
                        "partial_reality_commits": 0,
                    }
                if tick.saga_status == "SUCCEEDED":
                    break
            else:
                raise AssertionError("native chapter exhausted its bounded schedule")
        book = composition.authority.require(admitted.book_run_id)
        if int(book["accepted_through_chapter"]) == 1 and first_reality is None:
            reality = composition.query.narrative_reality(
                book_run_id=admitted.book_run_id
            )
            background = [
                event
                for event in reality["events"]
                if event["mutation"]["payload"].get("fact_origin", {}).get("kind")
                == "GOVERNED_BACKGROUND"
            ]
            assert background, (
                "accepted background events need non-prose source evidence"
            )
            assert not any(
                entry["state"].get("fact_id") == background[0]["event_id"]
                for entry in reality["current_state"]["reader_knowledge"]
            )
            first_reality = reality
            if transport.scenario == "intra_chapter":
                assert any(
                    entry["state"].get("character_id") == "mara"
                    and entry["state"].get("fact_id") == "meeting-room"
                    for entry in reality["current_state"]["character_knowledge"]
                )
                assert any(
                    event["causality"]["cause_refs"] == ["local:receive-message"]
                    for event in reality["events"]
                    if event["state_kind"] == "consequence_state"
                )
                acted = next(
                    event
                    for event in reality["events"]
                    if event["mutation"]["payload"]
                    .get("causal_batch", {})
                    .get("local_id")
                    == "act-on-message"
                )
                received = next(
                    event
                    for event in reality["events"]
                    if event["mutation"]["payload"]
                    .get("causal_batch", {})
                    .get("local_id")
                    == "receive-message"
                )
                why = composition.query.reality_view(
                    book_run_id=admitted.book_run_id,
                    view="why",
                    event_id=acted["event_id"],
                )
                assert any(
                    edge["cause"] == received["event_id"]
                    and edge["effect"] == acted["event_id"]
                    for edge in why["edges"]
                )
                assert "local:receive-message" not in why["external_evidence_refs"]
            if transport.scenario in {"causal_preparation", "multi_preparation"}:
                debts = [
                    entry["state"]
                    for entry in reality["current_state"]["narrative_obligation"]
                    if entry["state"].get("obligation_type") == "CAUSAL_DEBT"
                ]
                assert (
                    len(debts) == 1
                    and debts[0]["status"] == "OPEN"
                    and not debts[0]["payoff_evidence"]
                )
                reader = composition.query.reality_view(
                    book_run_id=admitted.book_run_id, view="reader"
                )
                assert not any(
                    entry["state"].get("obligation_type") == "CAUSAL_DEBT"
                    for entry in reader["entries"]
                )
            assert (
                len(
                    [
                        call
                        for call in transport.calls
                        if call["stage"] == "world_candidates.generate"
                    ]
                )
                == 1
            )
            assert (
                len(
                    [
                        call
                        for call in transport.calls
                        if call["stage"] == "world_candidates.evaluate"
                    ]
                )
                == 1
            )
            if transport.scenario == "perturbed_foundation":
                assert (
                    background[0]["mutation"]["payload"]["world_state_id"]
                    == "harbor-pressure"
                )
                assert background[0]["mutation"]["payload"]["status"] == "RISING"
                return {
                    "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
                    "book_run_id": admitted.book_run_id,
                    "scenario": transport.scenario,
                    "calls": transport.calls,
                    "reality_revision_id": reality["revision_id"],
                    "background_event_ids": [event["event_id"] for event in background],
                }
        if (
            transport.scenario == "multi_preparation"
            and int(book["accepted_through_chapter"]) >= 2
        ):
            current = composition.query.narrative_reality(
                book_run_id=admitted.book_run_id
            )
            state = next(
                entry["state"]
                for entry in current["current_state"]["world_state"]
                if entry["entity_key"] == "world_state_id=council-inquiry"
            )
            assert state["phase"] == 2, (
                "native scheduling must execute the due second step even when new generation says NO_OP"
            )
            if int(book["accepted_through_chapter"]) == 2:
                assert not state.get("goal_reached")
                continue
            assert state["goal_reached"] is True
            assert first_reality is not None
            debts = [
                entry["state"]
                for entry in current["current_state"]["narrative_obligation"]
                if entry["state"].get("obligation_type") == "CAUSAL_DEBT"
            ]
            assert len(debts) == 1 and debts[0]["status"] == "FULFILLED"
            from novel_forge.modules.narrative_state import NarrativeStateRebuildService

            rebuilt = NarrativeStateRebuildService(
                composition.authority.database_url
            ).rebuild(project_id=snapshot.project_id, book_id=snapshot.book_id)
            assert rebuilt.projection["current_state"] == current["current_state"]
            return {
                "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
                "scenario": transport.scenario,
                "book_run_id": admitted.book_run_id,
                "calls": transport.calls,
                "reality_revision_id": current["revision_id"],
                "first_reality_id": first_reality["revision_id"],
            }
        if (
            transport.scenario == "historical_disclosure"
            and int(book["accepted_through_chapter"]) == 2
        ):
            current = composition.query.narrative_reality(
                book_run_id=admitted.book_run_id
            )
            first_event = next(
                event
                for event in first_reality["events"]
                if event["mutation"]["payload"].get("fact_origin", {}).get("kind")
                == "GOVERNED_BACKGROUND"
            )
            assert all(
                entry["source_event_id"] != first_event["event_id"]
                for entry in current["current_state"]["world_state"]
            )
            assert not any(
                entry["state"].get("fact_id") == first_event["event_id"]
                for kind in ("character_knowledge", "reader_knowledge")
                for entry in current["current_state"][kind]
            )
            continue
        if int(book["accepted_through_chapter"]) >= 2:
            reality = composition.query.narrative_reality(
                book_run_id=admitted.book_run_id
            )
            assert first_reality is not None
            background = [
                event
                for event in first_reality["events"]
                if (event["mutation"]["payload"].get("fact_origin") or {}).get("kind")
                == "GOVERNED_BACKGROUND"
            ]
            fact_id = background[0]["event_id"]
            if transport.scenario != "causal_preparation":
                expected_reader = {
                    "reader_partial": "SUSPECTED",
                    "reader_misdirect": "MISDIRECTED",
                    "character_disclosure": None,
                    "withhold_disclosure": None,
                }.get(transport.scenario, "KNOWN")
                actual_reader = [
                    entry["state"]
                    for entry in reality["current_state"]["reader_knowledge"]
                    if entry["state"].get("fact_id") == fact_id
                ]
                assert (
                    actual_reader[0]["status"] if actual_reader else None
                ) == expected_reader
                if transport.scenario in {
                    "reader_partial",
                    "reader_misdirect",
                    "mixed_disclosure",
                }:
                    assert actual_reader[0]["disclosure_policy"][
                        "presentation_projection"
                    ] == {"status": "OPEN"}
                assert not any(
                    (event["mutation"]["payload"].get("fact_origin") or {}).get("kind")
                    == "GOVERNED_BACKGROUND"
                    for event in reality["events"]
                )
            else:
                debts = [
                    entry["state"]
                    for entry in reality["current_state"]["narrative_obligation"]
                    if entry["state"].get("obligation_type") == "CAUSAL_DEBT"
                ]
                assert (
                    len(debts) == 1
                    and debts[0]["status"] == "FULFILLED"
                    and debts[0]["payoff_evidence"]["event_id"] == fact_id
                )
                assert any(
                    entry["state"].get("goal_reached") is True
                    for entry in reality["current_state"]["world_state"]
                )
            character_information = [
                entry["state"]
                for entry in reality["current_state"]["character_knowledge"]
                if entry["state"].get("fact_id") == fact_id
            ]
            if transport.scenario in {"character_disclosure", "mixed_disclosure"}:
                assert (
                    len(character_information) == 1
                    and character_information[0]["status"] == "KNOWN"
                )
            else:
                assert not character_information
            provider_requests = capture_final_provider_requests(
                composition=composition, project_id=snapshot.project_id
            )
            for request in provider_requests:
                if request["stage"] not in {
                    "world_candidates.generate",
                    "world_candidates.evaluate",
                }:
                    assert (
                        "UNREVEALED_SUCCESSOR_AND_PRIVATE_CAUSE"
                        not in request["input_text"]
                    ), {"stage": request["stage"], "leak_paths": _secret_paths(request)}
            assert (
                composition.query.narrative_reality(
                    book_run_id=admitted.book_run_id, chapter_number=1
                )
                == first_reality
            )
            from novel_forge.modules.narrative_state import NarrativeStateRebuildService

            rebuilt = NarrativeStateRebuildService(
                composition.authority.database_url
            ).rebuild(project_id=snapshot.project_id, book_id=snapshot.book_id)
            assert rebuilt.projection["current_state"] == reality["current_state"]
            if transport.scenario == "manual_director":
                assert len(decisions) == 2
            if transport.scenario == "acceptance_recovery":
                assert len(acceptance_faults) == 2
            if transport.scenario == "provider_recovery":
                assert len(transport.faults) == 1
            return {
                "faults": [*transport.faults, *acceptance_faults],
                "editorial_decisions": decisions,
                "lease_takeovers": lease_takeovers,
                "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
                "book_run_id": admitted.book_run_id,
                "scenario": transport.scenario,
                "calls": transport.calls,
                "final_provider_requests": provider_requests,
                "reality_revision_id": reality["revision_id"],
                "background_event_ids": [event["event_id"] for event in background],
            }
    raise AssertionError(
        "autonomous production failed to reach one accepted Reality within its bounded schedule"
    )


def _secret_paths(value, prefix=""):
    if isinstance(value, dict):
        return [
            p
            for key, item in value.items()
            for p in _secret_paths(item, prefix + "." + str(key))
        ]
    if isinstance(value, list):
        return [
            p
            for index, item in enumerate(value)
            for p in _secret_paths(item, prefix + f"[{index}]")
        ]
    return [prefix] if "UNREVEALED_SUCCESSOR_AND_PRIVATE_CAUSE" in str(value) else []


def capture_final_provider_requests(*, composition, project_id):
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    from novel_forge.modules.chapter_authority.execution_gateway import (
        PostgresProductionExecutionPayloadResolver,
    )
    from novel_forge.modules.production_execution.contracts import ExecutionRequest
    from types import SimpleNamespace
    from novel_forge.modules.production_execution.postgres import (
        PostgresExecutionContractSource,
    )

    query = AuthorityAssetQuery(composition.authority.database_url)
    contracts = PostgresExecutionContractSource(
        composition.authority.database_url, project_id=project_id
    )
    resolver = PostgresProductionExecutionPayloadResolver(
        composition.authority.database_url
    )
    result = []
    for document in query.list(
        project_id=project_id, asset_type="execution_recovery_session", limit=200
    ):
        request = ExecutionRequest.from_dict(document.content["record"]["request"])
        if request.stage not in {
            "world_candidates.generate",
            "world_candidates.evaluate",
            "chapter_plan.generate",
            "draft",
            "review",
            "revision",
            "canon_extraction",
        } and not request.stage.startswith("quality_"):
            continue
        route = contracts.route_snapshot(request.route_snapshot_id)
        admission = SimpleNamespace(route_snapshot=route)
        try:
            payload = resolver.resolve(request, admission)
        except Exception as exc:
            exc.add_note(f"Final payload replay stage={request.stage}, execution={request.execution_id}")
            raise
        result.append(
            {
                "execution_id": request.execution_id,
                "stage": request.stage,
                "external_effect_id": request.external_effect_id,
                "input_text": payload.input_text,
                "prompt_evidence": payload.capability_evidence,
            }
        )
    assert {
        "world_candidates.generate",
        "world_candidates.evaluate",
        "draft",
        "canon_extraction",
    }.issubset({row["stage"] for row in result})
    return result
