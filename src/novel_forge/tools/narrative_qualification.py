from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from typing import Any, Mapping, Sequence

from novel_forge.modules.chapter_quality_authority import (
    load_accepted_quality_observations,
)
from novel_forge.modules.chapter_quality_authority.longitudinal import (
    build_longitudinal_quality_evidence,
)
from novel_forge.modules.reader_calibration.domain import BLIND_EVALUATION_DIMENSIONS
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.chapter_contracts import (
    chapter_contract_evidence,
)
from novel_forge.schemas.narrative_qualification import (
    BlindEditorialPack,
    BlindEditorialSample,
    EvidenceDimension,
    NarrativeQualificationReport,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
    build_implementation_tree_identity,
)
from novel_forge.tools.release_run_evidence import (
    validate_p0_backend_qualification_report,
)


CAPABILITIES = (
    "continuity",
    "character_trajectory",
    "relationship_trajectory",
    "obligation_setup_payoff",
    "causal_progression",
    "escalation",
    "reader_promise",
    "arc_closure",
    "quality_drift",
)
DRIFT_DIMENSIONS = (
    "repetition_drift",
    "character_flattening",
    "plot_drift",
    "exposition_inflation",
    "stakes_inflation",
    "context_pollution",
    "promise_debt",
    "continuity_debt",
)


def _hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
    )


def collect_accepted_snapshot(
    database_url: str, *, book_run_id: str = ""
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url, coordinate_nested=True) as uow:
        uow.cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        uow.cursor.execute(
            """
            SELECT to_jsonb(book), to_jsonb(snapshot)
            FROM authority_book_production AS book
            LEFT JOIN authority_book_production_input_snapshot AS snapshot
              ON snapshot.snapshot_id=book.input_snapshot_id
            WHERE (%s='' OR book.book_run_id=%s)
            ORDER BY book.accepted_through_chapter DESC,book.book_run_id
            LIMIT 1
            """,
            [book_run_id, book_run_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            if book_run_id:
                raise ValueError("requested Book Authority run does not exist")
            return {
                "book": {},
                "design": {},
                "accepted": [],
                "observations": [],
                "assets": [],
                "effects": [],
                "human_decisions": [],
                "reader_events": [],
            }
        book, design = dict(row[0]), dict(row[1] or {})
        uow.cursor.execute(
            """
            SELECT to_jsonb(acceptance), request.chapter_root_operation_id,
                   root.definition_snapshot->>'commit_sha', root.status,
                   to_jsonb(projection)
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
             AND request.project_id=acceptance.project_id
             AND request.book_run_id=acceptance.book_run_id
            JOIN authority_operation AS root
              ON root.operation_id=request.chapter_root_operation_id
             AND root.project_id=acceptance.project_id
            LEFT JOIN authority_book_narrative_projection_set AS projection
              ON projection.projection_set_id=acceptance.longform_projection_set_id
             AND projection.acceptance_id=acceptance.acceptance_id
            WHERE acceptance.book_run_id=%s AND acceptance.status='COMMITTED'
            ORDER BY acceptance.chapter_number
            """,
            [book["book_run_id"]],
        )
        accepted = [
            dict(
                a,
                chapter_root_operation_id=root,
                source_commit_sha=sha,
                root_status=status,
                projection=dict(projection or {}),
            )
            for a, root, sha, status, projection in uow.cursor.fetchall()
        ]
        observations = load_accepted_quality_observations(
            database_url,
            project_id=book["project_id"],
            book_id=book["book_id"],
            accepted_through_chapter=book["accepted_through_chapter"],
        )
        roots = [item["chapter_root_operation_id"] for item in accepted]
        uow.cursor.execute(
            """
            SELECT version.asset_version_id, asset.asset_type, version.content_hash,
                   version.content, operation.root_operation_id, operation.operation_id,
                   operation.definition_name, operation.status
            FROM authority_operation_output_asset AS output
            JOIN authority_operation AS operation ON operation.operation_id=output.operation_id
            JOIN authority_asset AS asset ON asset.asset_id=output.asset_id
              AND asset.project_id=operation.project_id
            JOIN authority_asset_version AS version ON version.asset_version_id=output.asset_version_id
            WHERE operation.project_id=%s
              AND (operation.root_operation_id=ANY(%s) OR operation.operation_id=ANY(%s))
            ORDER BY version.asset_version_id
            """,
            [book["project_id"], roots, roots],
        )
        keys = (
            "asset_version_id",
            "asset_type",
            "content_hash",
            "content",
            "root_operation_id",
            "operation_id",
            "definition_name",
            "operation_status",
        )
        assets = [dict(zip(keys, row, strict=True)) for row in uow.cursor.fetchall()]
        source_plan_ids = {
            str(item.get("chapter_plan_asset_version_id") or "")
            for item in observations
        }
        source_plan_ids.update(
            str(item["content"].get("source_chapter_plan_asset_version_id") or "")
            for item in assets
            if item["asset_type"] == "chapter_plan"
        )
        source_plan_ids -= {item["asset_version_id"] for item in assets} | {""}
        uow.cursor.execute(
            """
            SELECT version.asset_version_id, asset.asset_type, version.content_hash, version.content
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s)
            ORDER BY version.asset_version_id
            """,
            [book["project_id"], sorted(source_plan_ids)],
        )
        assets.extend(
            {
                "asset_version_id": version,
                "asset_type": kind,
                "content_hash": digest,
                "content": content,
                "root_operation_id": "",
                "operation_id": "",
                "definition_name": "",
                "operation_status": "SOURCE_AUTHORITY_ASSET",
            }
            for version, kind, digest, content in uow.cursor.fetchall()
        )
        uow.cursor.execute(
            """
            SELECT to_jsonb(effect), operation.root_operation_id,
                   COALESCE((SELECT jsonb_agg(to_jsonb(dispatch) ORDER BY dispatch.generation)
                     FROM authority_external_effect_dispatch AS dispatch
                     WHERE dispatch.external_effect_id=effect.external_effect_id),'[]'::jsonb),
                   COALESCE((SELECT jsonb_agg(to_jsonb(receipt) ORDER BY receipt.external_receipt_id)
                     FROM authority_external_receipt AS receipt
                     JOIN authority_external_effect_dispatch AS dispatch ON dispatch.dispatch_id=receipt.dispatch_id
                     WHERE dispatch.external_effect_id=effect.external_effect_id),'[]'::jsonb)
            FROM authority_external_effect AS effect
            JOIN authority_operation AS operation ON operation.operation_id=effect.operation_id
            WHERE operation.project_id=%s AND operation.root_operation_id=ANY(%s)
              AND effect.capability LIKE 'model.%%'
            ORDER BY effect.external_effect_id
            """,
            [book["project_id"], roots],
        )
        effects = [
            dict(
                effect, root_operation_id=root, dispatches=dispatches, receipts=receipts
            )
            for effect, root, dispatches, receipts in uow.cursor.fetchall()
        ]
        draft_ids = [item["accepted_draft_asset_version_id"] for item in observations]
        uow.cursor.execute(
            """
            SELECT decision.decision_id, decision.reviewer_id, task.evidence_level,
                   decision.evaluator_identity_class, decision.pack_id,
                   pair.asset_a_version_id, pair.asset_b_version_id,
                   pair.blinded, decision.position_revealed_after_decision
            FROM human_preference_decision AS decision
            JOIN human_preference_pair AS pair ON pair.pair_id=decision.pair_id
            JOIN human_preference_task AS task ON task.task_id=pair.task_id
            WHERE decision.project_id=%s AND task.book_id=%s
              AND (pair.asset_a_version_id=ANY(%s) OR pair.asset_b_version_id=ANY(%s))
            ORDER BY decision.decision_id
            """,
            [book["project_id"], book["book_id"], draft_ids, draft_ids],
        )
        human_keys = (
            "decision_id",
            "reviewer_id",
            "evidence_level",
            "identity_class",
            "pack_id",
            "asset_a",
            "asset_b",
            "blinded",
            "position_revealed_after_decision",
        )
        humans = [
            dict(zip(human_keys, row, strict=True)) for row in uow.cursor.fetchall()
        ]
        uow.cursor.execute(
            """
            SELECT event.outcome_event_id, event.event_type, exposure.chapter_asset_version_id,
                   event.reader_session_id, session.consent_policy_version
            FROM reader_outcome_event AS event
            JOIN reader_exposure AS exposure ON exposure.exposure_id=event.exposure_id
            JOIN reader_session AS session ON session.reader_session_id=event.reader_session_id
            WHERE event.project_id=%s AND event.book_id=%s
              AND exposure.chapter_asset_version_id=ANY(%s)
            ORDER BY event.outcome_event_id
            """,
            [book["project_id"], book["book_id"], draft_ids],
        )
        reader_keys = (
            "outcome_event_id",
            "event_type",
            "chapter_asset_version_id",
            "reader_session_id",
            "consent_policy_version",
        )
        readers = [
            dict(zip(reader_keys, row, strict=True)) for row in uow.cursor.fetchall()
        ]
    return {
        "book": book,
        "design": design,
        "accepted": accepted,
        "observations": observations,
        "assets": assets,
        "effects": effects,
        "human_decisions": humans,
        "reader_events": readers,
    }


def _fixture_effect(effect: Mapping[str, Any]) -> bool:
    profile = effect.get("provider_capability_profile") or {}
    return (
        profile.get("real_provider_validation_eligible") is not True
        or effect.get("provider_control_level") == "FIXTURE_CONTROLLED"
        or any(
            token in str(effect.get("provider") or "").lower()
            for token in ("fixture", "scripted", "fake", "mock")
        )
        or any(
            (receipt.get("payload") or {})
            .get("evidence", {})
            .get("fixture_protocol_only")
            is True
            for receipt in effect.get("receipts") or ()
        )
    )


def _effect_summary(
    effect: Mapping[str, Any], assets: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    effect_id = effect["external_effect_id"]
    logs = [
        a
        for a in assets
        if a["asset_type"] == "model_call_log"
        and a["content"].get("external_effect_id") == effect_id
    ]
    costs = [
        a
        for a in assets
        if a["asset_type"] == "cost_ledger"
        and a["content"].get("external_effect_id") == effect_id
    ]
    receipts = list(effect.get("receipts") or ())
    runtime = (effect.get("request_payload") or {}).get("_production_execution") or {}
    admission = (runtime.get("capability_runtime") or {}).get(
        "provider_admission"
    ) or {}
    evidence = logs[0]["content"].get("provider_evidence", {}) if logs else {}
    usage = dict(evidence.get("usage") or {})
    binding = dict(runtime.get("capability_runtime") or {})
    manifests = [
        a
        for a in assets
        if a["asset_type"] == "provider_request_admission_manifest"
        and a["asset_version_id"] == binding.get("provider_admission_asset_version_id")
        and a["content_hash"] == binding.get("provider_admission_content_hash")
    ]
    frozen = (
        dict(manifests[0]["content"].get("contract", manifests[0]["content"]))
        if len(manifests) == 1
        else {}
    )
    provider_identity = frozen.get("provider_request_identity") or {}
    admitted = (
        bool(frozen)
        and frozen.get("provider_admission") == admission
        and admission.get("status") == "ADMITTED"
        and type(admission.get("total_reserved")) is int
        and type(admission.get("applicable_limit")) is int
        and 0 < admission["total_reserved"] <= admission["applicable_limit"]
        and admission.get("envelope_hash") == _hash(provider_identity)
        and admission.get("envelope_hash")
        == binding.get("provider_request_envelope_hash")
        and provider_identity.get("provider") == runtime.get("route_provider")
        and provider_identity.get("provider") == evidence.get("provider_id")
        and provider_identity.get("model") == evidence.get("model_id")
    )
    latency_ms = None
    dispatches = list(effect.get("dispatches") or ())
    if len(dispatches) == 1:
        try:
            started = datetime.fromisoformat(str(dispatches[0]["created_at"]))
            finished = datetime.fromisoformat(str(dispatches[0]["finished_at"]))
            latency_ms = (finished - started).total_seconds() * 1000
        except (ValueError, TypeError, KeyError):
            pass
    received = (
        (receipts[0].get("payload") or {}).get("evidence") or {}
        if len(receipts) == 1
        else {}
    )
    execution = dict(received.get("production_execution") or {})
    execution_request = dict(execution.get("execution_request") or {})
    handle = dict(execution.get("execution_handle") or {})
    request_identity_matches = (
        (
            execution_request.get("external_effect_id") == effect_id
            and handle.get("provider_request_id") == effect.get("provider_request_id")
            and dict(execution.get("process_evidence") or {}).get("request_hash")
            == admission.get("envelope_hash")
        )
        if effect.get("provider") == "production_execution_gateway"
        else received.get("request_hash") == admission.get("envelope_hash")
    )
    response_identity_matches = (
        bool(received.get("result"))
        and received.get("result") == evidence.get("result")
        and request_identity_matches
        and receipts[0].get("provider") == effect.get("provider")
    )
    complete = (
        not _fixture_effect(effect)
        and effect.get("status") == "SUCCEEDED"
        and bool(effect.get("provider_request_id"))
        and bool(effect.get("request_hash"))
        and len(effect.get("dispatches") or ()) == 1
        and len(receipts) == 1
        and bool(receipts[0].get("payload_hash"))
        and bool(receipts[0].get("receipt_id"))
        and bool(logs)
        and bool(costs)
        and evidence.get("real_model_call") is True
        and admitted
        and response_identity_matches
        and latency_ms is not None
        and latency_ms > 0
        and all(
            type(usage.get(key)) is int and usage[key] > 0
            for key in ("input_tokens", "output_tokens")
        )
    )
    return {
        "external_effect_id": effect_id,
        "root_operation_id": effect.get("root_operation_id"),
        "capability": effect.get("capability"),
        "provider": effect.get("provider"),
        "external_model_provider": runtime.get("route_provider", ""),
        "model_id": effect.get("model_id"),
        "request_hash": effect.get("request_hash"),
        "provider_request_id": effect.get("provider_request_id"),
        "receipt_ids": [r["external_receipt_id"] for r in receipts],
        "receipt_payload_hashes": [r.get("payload_hash") for r in receipts],
        "dispatch_count": len(effect.get("dispatches") or ()),
        "model_call_log_ids": [a["asset_version_id"] for a in logs],
        "cost_ledger_ids": [a["asset_version_id"] for a in costs],
        "usage": usage,
        "latency": {
            "measurement": "DURABLE_DISPATCH_WALL_CLOCK"
            if latency_ms is not None
            else "NOT_OBSERVED",
            "duration_ms": latency_ms,
        },
        "response_hash": _hash(received["result"]) if received.get("result") else "",
        "response_identity_matches": response_identity_matches,
        "provider_admission_asset_version_ids": [
            a["asset_version_id"] for a in manifests
        ],
        "provider_admission_verified": admitted,
        "provider_admission_hash": _hash(admission) if admission else "",
        "fixture_backed": _fixture_effect(effect),
        "complete_real_receipt": complete,
    }


def _engineering(
    path: Path | None, root: Path, implementation: Mapping[str, Any]
) -> EvidenceDimension:
    if path is None:
        return EvidenceDimension(
            "NOT_PROVEN",
            "NO_CURRENT_EXACT_SHA_P0_ATTACHED",
            (),
            ("Narrative collection does not run engineering qualification.",),
        )
    payload = json.loads(path.read_text())
    validate_p0_backend_qualification_report(
        payload, expected_sha=str(payload.get("tested_sha") or "")
    )
    if (
        payload["implementation_tree_sha"] != implementation["implementation_tree_sha"]
        or build_git_implementation_tree_identity(root, payload["tested_sha"])[
            "implementation_tree_sha"
        ]
        != implementation["implementation_tree_sha"]
    ):
        raise ValueError("Engineering evidence belongs to another implementation")
    return EvidenceDimension(
        "QUALIFIED",
        "LOCAL_BACKEND_ENGINEERING",
        (str(path), _hash(payload)),
        ("P0 does not establish narrative, human, Provider or production quality.",),
    )


def _planning_boundaries(
    observation: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
    root_operation_id: str,
) -> dict[str, Any]:
    plans = [
        item
        for item in assets
        if item["asset_type"] == "chapter_plan"
        and item["root_operation_id"] == root_operation_id
        and (
            item["asset_version_id"] == observation.get("chapter_plan_asset_version_id")
            or item["content"].get("source_chapter_plan_asset_version_id")
            == observation.get("chapter_plan_asset_version_id")
        )
    ]
    if len(plans) != 1:
        return {
            "gate": "NOT_PROVEN",
            "reason": "UNIQUE_ACCEPTED_EXECUTION_PLAN_REQUIRED",
        }
    plan = plans[0]
    recorded = dict(plan["content"].get("narrative_contracts") or {})
    mission = dict(recorded.get("chapter_mission") or {})
    sources = [
        item
        for item in assets
        if item["asset_version_id"] == mission.get("source_asset_version_id")
        and item["content_hash"] == mission.get("source_content_hash")
    ]
    if len(sources) != 1:
        return {"gate": "NOT_PROVEN", "reason": "PLANNING_SOURCE_IDENTITY_NOT_OBSERVED"}
    source = sources[0]
    try:
        expected = chapter_contract_evidence(
            source["content"],
            asset_version_id=source["asset_version_id"],
            content_hash=source["content_hash"],
        )
    except (KernelError, ValueError, TypeError, KeyError) as exc:
        return {"gate": "NOT_PROVEN", "reason": str(exc)}
    bindings = [
        dict(item["content"].get("chapter_mission") or {}).get(
            "planning_contract_binding", {}
        )
        for item in assets
        if item["asset_type"] == "chapter_execution_intent"
        and item["root_operation_id"] == root_operation_id
    ]
    bound = any(
        binding.get("chapter_mission_digest") == expected["chapter_mission_digest"]
        and binding.get("scene_architecture_digest")
        == expected["scene_architecture_digest"]
        and binding.get("source_asset_version_id") == source["asset_version_id"]
        and binding.get("source_content_hash") == source["content_hash"]
        for binding in bindings
    )
    return {
        "gate": "STRUCTURAL_COVERAGE_PASS"
        if recorded == expected and bound
        else "NOT_PROVEN",
        "chapter_mission_digest": expected["chapter_mission_digest"],
        "scene_architecture_digest": expected["scene_architecture_digest"],
        "source_asset_version_id": source["asset_version_id"],
        "source_content_hash": source["content_hash"],
        "execution_plan_asset_version_id": plan["asset_version_id"],
        "execution_binding_verified": bound,
    }


def _capability_coverage(
    requested: Sequence[str],
    observations: Sequence[Mapping[str, Any]],
    accepted: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    signals = {
        "continuity": lambda row: bool(
            row.get("canon_snapshot_asset_version_id")
            and row.get("story_state_asset_version_id")
        ),
        "character_trajectory": lambda row: bool(
            row.get("character_ids") and row.get("protagonist_decision_ids")
        ),
        "relationship_trajectory": lambda row: False,
        "obligation_setup_payoff": lambda row: bool(row.get("obligation_states")),
        "causal_progression": lambda row: bool(row.get("causal_progress_event_ids")),
        "escalation": lambda row: row.get("obstacle_escalation") is True,
        "reader_promise": lambda row: any(
            str(item.get("obligation_type") or item.get("kind") or "")
            == "READER_PROMISE"
            for item in row.get("obligation_states") or ()
        ),
        "arc_closure": lambda row: any(
            state.get("lifecycle_status") == "COMPLETED"
            and state.get("observation_status") == "OBSERVED"
            for item in accepted
            if item["acceptance_id"] == row["acceptance_id"]
            for state in item.get("projection", {}).get("arc_state", [])
        ),
        "quality_drift": lambda row: bool(
            row.get("quality_gate") and row.get("semantic_repetition_signatures")
        ),
    }
    result = {}
    for name in requested:
        refs = [row["acceptance_id"] for row in observations if signals[name](row)]
        result[name] = {
            "status": "SUPPORTING_OBSERVATIONS" if refs else "NOT_OBSERVED",
            "acceptance_ids": refs,
            "qualification": "NOT_PROVEN",
            "rationale": "Use accepted capability observations and the intervening sequence; presence is not a semantic quality decision."
            if refs
            else "The accepted observation contract does not supply evidence for this capability in this sample.",
        }
    return result


def build_narrative_report(
    snapshot: Mapping[str, Any],
    *,
    implementation: Mapping[str, Any],
    capabilities: Sequence[str],
    engineering: EvidenceDimension,
    matching_source_revisions: Sequence[str] = (),
) -> tuple[NarrativeQualificationReport, BlindEditorialPack, dict[str, Any]]:
    requested = tuple(dict.fromkeys(capabilities))
    if not requested or set(requested) - set(CAPABILITIES):
        raise ValueError("sampling requires known narrative capabilities")
    book = dict(snapshot["book"])
    observations = list(snapshot["observations"])
    accepted = list(snapshot["accepted"])
    assets = list(snapshot["assets"])
    by_id = {item["asset_version_id"]: item for item in assets}
    effects = [_effect_summary(item, assets) for item in snapshot["effects"]]
    fixture = bool(
        "FIXTURE" in str(book.get("input_mode") or "")
        or any(item["fixture_backed"] for item in effects)
    )
    observed_ids = {item["acceptance_id"] for item in observations}
    accepted_ids = {item["acceptance_id"] for item in accepted}
    complete = (
        bool(accepted)
        and observed_ids == accepted_ids
        and all(
            item.get("root_status") == "SUCCEEDED"
            and item.get("projection", {}).get("status") == "COMPLETE"
            for item in accepted
        )
    )
    chapters = [int(item["chapter_number"]) for item in accepted]
    continuous = bool(chapters) and chapters == list(
        range(chapters[0], chapters[-1] + 1)
    )
    refs = tuple(sorted(accepted_ids))
    verified_humans = [
        item
        for item in snapshot["human_decisions"]
        if item["evidence_level"] == "HUMAN_VERIFIED"
        and item["blinded"] is True
        and item["pack_id"]
        and item["identity_class"]
        in {
            "PROFESSIONAL_EDITOR",
            "AUTHOR_EDITOR",
            "EXPERIENCED_READER",
            "GENERAL_READER",
        }
    ]
    human_ids = (
        tuple(item["decision_id"] for item in verified_humans) if not fixture else ()
    )
    dimensions = {
        "engineering": engineering,
        "narrative_correctness": EvidenceDimension(
            "BOUNDED_CONTRACT_EVIDENCE" if complete and not fixture else "NOT_PROVEN",
            "ACCEPTED_AUTHORITY_CONTRACT_ONLY",
            refs,
            (
                "Accepted gates establish their bounded contract, not whole-book editorial quality.",
            ),
        ),
        "human_editorial": EvidenceDimension(
            "BOUNDED_HUMAN_EVIDENCE" if human_ids else "WAITING_EVIDENCE",
            "EXTERNAL_HUMAN_DECISIONS_ONLY",
            human_ids,
            (
                "AI Judge, fixture preferences and an exported pack are not human evaluation.",
            ),
        ),
        "reader_evidence": EvidenceDimension(
            "NOT_PROVEN",
            "OBSERVATIONS_WITHOUT_CAUSAL_OR_PRODUCTION_QUALIFICATION",
            tuple(item["outcome_event_id"] for item in snapshot["reader_events"]),
            (
                "Reader events require their own exposure, calibration and production evidence; AI Reader Proxy stays separate.",
            ),
        ),
        "longitudinal_stability": EvidenceDimension(
            "EVIDENCE_NOT_YET_SUFFICIENT",
            "BOUNDED_ACCEPTED_PROGRESS_OBSERVATIONS",
            refs,
            (
                "A capability-scoped continuous sample does not prove long-form stability; no chapter-count threshold upgrades this status.",
            ),
        ),
        "production_evidence": EvidenceDimension(
            "NOT_PROVEN",
            "NO_PRODUCTION_OPERATION_STUDY",
            (),
            (
                "Local acceptance and an external call do not prove sustained production operation.",
            ),
        ),
    }
    pack_token = "editorial:" + secrets.token_hex(16)
    public: list[BlindEditorialSample] = []
    private: list[dict[str, Any]] = []
    progress: list[dict[str, Any]] = []
    accepted_reports: list[dict[str, Any]] = []
    real_chapters: list[str] = []
    for row in accepted:
        observation = next(
            (
                item
                for item in observations
                if item["acceptance_id"] == row["acceptance_id"]
            ),
            {},
        )
        draft_id = str(observation.get("accepted_draft_asset_version_id") or "")
        text = str(by_id.get(draft_id, {}).get("content", {}).get("text") or "")
        scoped = [
            effect
            for effect in effects
            if effect["root_operation_id"] == row["chapter_root_operation_id"]
        ]
        stages = {
            str(effect["capability"]).removeprefix("model.")
            for effect in scoped
            if effect["complete_real_receipt"]
        }
        scoped_assets = [
            item
            for item in assets
            if item["root_operation_id"] == row["chapter_root_operation_id"]
            and item.get("operation_status") == "SUCCEEDED"
        ]
        scoped_asset_ids = {item["asset_version_id"] for item in scoped_assets}
        required_lineage = {
            str(observation.get(key) or "")
            for key in (
                "accepted_draft_asset_version_id",
                "quality_aggregate_asset_version_id",
            )
        }
        required_types = {
            "context_bundle",
            "review_report",
            "re_review_report",
            "final_release_gate_report",
        }
        planning_boundaries = _planning_boundaries(
            observation, assets, row["chapter_root_operation_id"]
        )
        is_real = (
            complete
            and planning_boundaries.get("gate") == "STRUCTURAL_COVERAGE_PASS"
            and not fixture
            and bool(text)
            and "" not in required_lineage
            and required_lineage <= scoped_asset_ids
            and required_types <= {item["asset_type"] for item in scoped_assets}
            and bool(
                snapshot["design"].get("design_admission_status")
                == "LONGFORM_DESIGN_QUALIFIED"
            )
            and row.get("source_commit_sha") in matching_source_revisions
            and {"draft", "review", "revision"} <= stages
            and any(stage.startswith("quality") for stage in stages)
            and bool(scoped)
            and all(effect["complete_real_receipt"] for effect in scoped)
        )
        if is_real:
            real_chapters.append(row["acceptance_id"])
        lineage = {
            key: row.get(key)
            for key in (
                "acceptance_id",
                "chapter_number",
                "chapter_request_id",
                "acceptance_operation_id",
                "chapter_root_operation_id",
                "chapter_outcome_asset_version_id",
                "story_state_asset_version_id",
                "canon_snapshot_asset_version_id",
                "longform_projection_set_id",
                "source_commit_sha",
            )
        }
        lineage.update(
            {
                key: observation.get(key, "")
                for key in (
                    "chapter_plan_asset_version_id",
                    "quality_aggregate_asset_version_id",
                    "narrative_realization_id",
                    "narrative_realization_asset_version_id",
                    "narrative_realization_contract_digest",
                )
            }
        )
        lineage["planning_boundaries"] = planning_boundaries
        lineage.update(
            accepted_draft_asset_version_id=draft_id,
            source_implementation_matches=row.get("source_commit_sha")
            in matching_source_revisions,
            provider_effects=scoped,
            real_provider_accepted_actual="PASS" if is_real else "NOT_PROVEN",
        )
        accepted_reports.append(lineage)
        if text:
            token = "sample:" + secrets.token_hex(16)
            public.append(BlindEditorialSample(token, len(public) + 1, text))
            private.append({"sample_token": token, **lineage, "text_hash": _hash(text)})
        obligation_states = observation.get("obligation_states") or []
        prefix = [
            item
            for item in observations
            if int(item["chapter_number"]) <= int(row["chapter_number"])
        ]
        prefix_quality = build_longitudinal_quality_evidence(prefix).to_dict()
        drift = {
            dimension: {"status": "NOT_PROVEN", "measurement": None}
            for dimension in DRIFT_DIMENSIONS
        }
        drift["repetition_drift"] = {
            "status": "BOUNDED_SIGNATURE_OBSERVATION",
            "measurement": prefix_quality["repetition"],
        }
        drift["promise_debt"] = {
            "status": "BOUNDED_ACCEPTED_OBSERVATION",
            "measurement": {
                "narrative_debt_score": observation.get("narrative_debt_score"),
                "promise_payoff": prefix_quality["promise_payoff"],
            },
        }
        progress.append(
            {
                "acceptance_id": row["acceptance_id"],
                "chapter_number": row["chapter_number"],
                "narrative_progress": {
                    "active_arc_ids": observation.get("active_arc_ids", []),
                    "goal_progress_units": observation.get("goal_progress_units"),
                    "causal_progress_event_ids": observation.get(
                        "causal_progress_event_ids", []
                    ),
                },
                "quality_gate": observation.get("quality_gate", "NOT_OBSERVED"),
                "semantic_repetition_signatures": observation.get(
                    "semantic_repetition_signatures", {}
                ),
                "character_ids": observation.get("character_ids", []),
                "open_obligation_ids": [
                    item.get("obligation_id")
                    for item in obligation_states
                    if item.get("status") != "FULFILLED"
                ],
                "narrative_debt_score": observation.get("narrative_debt_score"),
                "average_sentence_length": observation.get("average_sentence_length"),
                "drift_evidence": drift,
            }
        )
    blind = BlindEditorialPack(pack_token, BLIND_EVALUATION_DIMENSIONS, tuple(public))
    private_pack = {
        "schema_version": "novel-forge.narrative-editorial-private.v1",
        "pack_token": pack_token,
        "implementation": dict(implementation),
        "book_run_id": book.get("book_run_id", ""),
        "samples": private,
    }
    design = dict(snapshot["design"])
    report = NarrativeQualificationReport(
        implementation=implementation,
        source={
            "kind": "POSTGRESQL_REPEATABLE_READ_ACCEPTED_AUTHORITY",
            "book_run_id": book.get("book_run_id", ""),
            "project_id": book.get("project_id", ""),
            "book_id": book.get("book_id", ""),
            "fixture_backed": fixture,
            "accepted_snapshot_hash": _hash(accepted),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        sampling={
            "requested_capabilities": list(requested),
            "selection": "ALL_AVAILABLE_ACCEPTED_PROGRESS_WITH_EXACT_LINEAGE",
            "rationale": "Retain the complete available accepted sequence and its missing capability observations; chapter numbers are sample coordinates, never validation stages.",
            "chapter_numbers": chapters,
            "continuous": continuous,
            "sample_size": len(chapters),
            "capability_coverage": _capability_coverage(
                requested, observations, accepted
            ),
        },
        dimensions=dimensions,
        accepted_chapters=tuple(accepted_reports),
        design_evidence={
            "input_snapshot_id": design.get("snapshot_id", ""),
            "design_admission_status": design.get(
                "design_admission_status", "NOT_PROVEN"
            ),
            "foundation_set_digest": design.get("foundation_set_digest", ""),
            "qualification_hash": design.get("design_qualification_hash", ""),
            "qualification": design.get("design_qualification", {}),
            "foundation_set": design.get("foundation_set", {}),
            "book_plan_version": design.get("book_plan_version", ""),
            "volume_portfolio_plan_versions": design.get(
                "volume_portfolio_plan_versions", []
            ),
            "arc_portfolio_plan_versions": design.get(
                "arc_portfolio_plan_versions", []
            ),
            "upstream_gate_observed": design.get("design_admission_status")
            == "LONGFORM_DESIGN_QUALIFIED",
            "missing_evidence_is_not_design_approval": True,
        },
        progress_observations=tuple(progress),
        longitudinal_observations=build_longitudinal_quality_evidence(
            observations
        ).to_dict(),
        real_chapter_production={
            "status": "PASS" if real_chapters else "NOT_PROVEN",
            "acceptance_ids": real_chapters,
            "proof_ceiling": "EXACT_IMPLEMENTATION_REAL_ACCEPTED_CHAPTER_ONLY",
            "missing_evidence": []
            if real_chapters
            else [
                "No accepted chapter has complete current nonfixture Draft/Review/Revision/Quality Provider admission, receipt, usage and cost lineage."
            ],
        },
        blind_pack={
            "pack_token": pack_token,
            "public_content_hash": _hash(blind.to_dict()),
            "private_mapping_hash": _hash(private_pack),
            "public_path": "reviewer/pack.json",
            "private_path": "private/mapping.json",
            "sample_count": len(public),
            "human_editorial_status": dimensions["human_editorial"].status,
            "comparison_baseline": "NOT_FABRICATED_SINGLE_ARM_REVIEW",
        },
        limitations=(
            "Collection PASS means the report schema and source queries succeeded; six qualification dimensions remain separate.",
            "Fixture or scripted accepted facts support engineering diagnostics only.",
            "The canonical accepted-quality loader retains its bounded horizon and fails closed if a rollup is required.",
        ),
    )
    return report, blind, private_pack


def write_pack(
    output_dir: Path,
    report: NarrativeQualificationReport,
    blind: BlindEditorialPack,
    private: Mapping[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    for directory in ("reviewer", "private"):
        (output_dir / directory).mkdir(mode=0o700)
    for path, payload in (
        (output_dir / "report.json", report.to_dict()),
        (output_dir / "reviewer/pack.json", blind.to_dict()),
        (output_dir / "private/mapping.json", dict(private)),
    ):
        with path.open("x", encoding="utf-8") as stream:
            os.chmod(path, 0o600)
            stream.write(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read accepted PostgreSQL facts into independent narrative evidence and blind editorial packs."
    )
    parser.add_argument("--database-config", type=Path)
    parser.add_argument("--book-run-id", default="")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/novel-forge-narrative-qualification"),
    )
    parser.add_argument("--capability", action="append", choices=CAPABILITIES)
    parser.add_argument("--engineering-evidence", type=Path)
    args = parser.parse_args(argv)
    database_url = (
        str(json.loads(args.database_config.read_text())["url"])
        if args.database_config
        else os.environ.get("NOVEL_FORGE_DATABASE_URL", "")
    )
    if not database_url:
        parser.error("--database-config or NOVEL_FORGE_DATABASE_URL is required")
    identity = build_implementation_tree_identity(args.repo_root)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=args.repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    implementation = {
        "commit_sha": commit,
        "implementation_tree_sha": identity["implementation_tree_sha"],
    }
    snapshot = collect_accepted_snapshot(database_url, book_run_id=args.book_run_id)
    matched: list[str] = []
    for sha in sorted(
        {str(item.get("source_commit_sha") or "") for item in snapshot["accepted"]}
    ):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        try:
            if (
                build_git_implementation_tree_identity(args.repo_root, sha)[
                    "implementation_tree_sha"
                ]
                == identity["implementation_tree_sha"]
            ):
                matched.append(sha)
        except (ValueError, subprocess.CalledProcessError):
            continue
    report, blind, private = build_narrative_report(
        snapshot,
        implementation=implementation,
        capabilities=args.capability or CAPABILITIES,
        engineering=_engineering(
            args.engineering_evidence, args.repo_root, implementation
        ),
        matching_source_revisions=matched,
    )
    write_pack(args.output_dir, report, blind, private)
    print(
        json.dumps(
            {
                "collection_status": "PASS",
                "report": str(args.output_dir / "report.json"),
                "dimensions": {
                    name: asdict(value) for name, value in report.dimensions.items()
                },
                "real_chapter_production": report.real_chapter_production["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
