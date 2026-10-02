from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path

import pytest

from novel_forge.modules.command_kernel.creative_budget_runtime import configure_creative_budget, get_creative_budget, _usage
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_book_coordination_claim, schedule_book_coordination_jobs
from tests.unit.test_creative_budget_contract import provider_campaign_policy


def run_reselection_budget_probe(*, composition, snapshot, admitted, transport, monkeypatch, stop, calibration=None, original_cap=False):
    database_url = composition.authority.database_url
    original_prepare = PostgresPlanningExecutionPreparer.prepare
    original_resolve = PostgresProductionExecutionPayloadResolver.resolve
    state = {}

    def prepare(preparer, **kwargs):
        command = kwargs["command"]
        if command.project_id == snapshot.project_id and command.generator_operation_name == "chapter_plan.generate" and stop == "calibration" and command.repair_number == 2:
            raise KernelError("SCRIPTED_CALIBRATION_BOUNDARY_REACHED", "finite scripted calibration stops before its third Provider generation")
        if command.project_id == snapshot.project_id and command.generator_operation_name == "chapter_plan.generate" and not state and stop != "calibration":
            policy = provider_campaign_policy()
            arm = policy["comparison_budget"]["arms"][0]
            arm.update(project_id=snapshot.project_id, book_id=snapshot.book_id)
            with AuthorityUnitOfWork(database_url) as uow:
                prior = _usage(uow.cursor, policy["comparison_budget"], snapshot.project_id)
            calls = 3 if command.world_preparation_request else 1
            if not original_cap:
                assert calibration and calibration["calls_per_generation"] == calls
                calibrated = calibration["reservations"]
            for phase, cap in policy["authorization"]["authorized_cumulative_caps"].items():
                used = prior["phases"][phase]
                count = calls if phase in {"PRODUCTION", "REPAIR"} else 0
                cap.update(calls=used["calls_used_or_reserved"] + count,
                    tokens=max(used["conservative_tokens"], used["calls_used_or_reserved"] * 1000) + count * 32_000,
                    priced_usd=format(Decimal(used["priced_usd"]) + count, "f"))
                if phase == "REPAIR" and stop == "tokens":
                    cap.update(calls=cap["calls"] + 1, tokens=used["conservative_tokens"] + 32_000 + (calls - 1) * 1000)
                if not original_cap and phase in {"PRODUCTION", "REPAIR"}:
                    generation = 0 if phase == "PRODUCTION" else 1
                    amounts = [row["estimated_tokens"] for row in calibrated if row["repair_number"] == generation]
                    assert len(amounts) == calls
                    cap["tokens"] = used["conservative_tokens"] + sum(amounts) + (max(amounts) if phase == "REPAIR" and stop == "calls" else 0)
                arm[phase.lower() + "_allocation"] = deepcopy(cap)
            caps = policy["authorization"]["authorized_cumulative_caps"].values()
            totals = {key: sum(cap[key] for cap in caps) for key in ("calls", "tokens")}
            totals["priced_usd"] = format(sum(Decimal(cap["priced_usd"]) for cap in caps), "f")
            arm["project_total"] = totals
            policy["comparison_budget"].update(experiment_id="craft-budget:" + snapshot.project_id,
                shared_total=totals, entitlements=[], expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
            policy["authorization"].update(project_id=snapshot.project_id, book_id=snapshot.book_id)
            if not original_cap:
                from novel_forge.modules.mkaos_authority.craft import craft_hash
                policy["authorization"].update(authorization_ref="scripted-complete-request-calibration:" + calibration["project_id"], evidence_hash=craft_hash(calibrated))
            configure_creative_budget(database_url=database_url, policy=policy, project_id=snapshot.project_id,
                workspace_id=snapshot.workspace_id, principal=composition.principal,
                application_build_id=composition.authority.application_build_id, commit_sha=composition.authority.commit_sha,
                idempotency_key=snapshot.project_id + ":craft-budget:configure", trace_id="craft-budget:scripted", correlation_id=admitted.book_run_id)
            state.update(policy=policy, prior=prior, calls_per_generation=calls)
        return original_prepare(preparer, **kwargs)

    def resolve(resolver, request, admission):
        result = original_resolve(resolver, request, admission)
        if request.project_id != snapshot.project_id or request.stage not in {"chapter_plan.generate", "world_candidates.generate", "world_candidates.evaluate"}:
            return result
        payload = deepcopy(result.request_payload)
        assert payload["fixture_protocol_only"] and not payload["real_model_call"]
        if original_cap:
            payload["usage"] = {"input_tokens": 800, "output_tokens": 200, "total_tokens": 1000,
                                "measurement": "SIMULATED_SCRIPTED_RECEIPT_NOT_MODEL_USAGE"}
        else:
            with AuthorityUnitOfWork(database_url) as uow:
                uow.cursor.execute("""SELECT g.repair_number,e.request_payload->'provider_token_contract'
                    FROM authority_story_planning_generation g JOIN authority_external_effect e USING(operation_id)
                    WHERE g.project_id=%s AND g.operation_id=%s AND e.external_effect_id=%s""",
                    [snapshot.project_id, request.operation_id, request.external_effect_id])
                generation, token_contract = uow.cursor.fetchone()
            total = int(token_contract["estimated_total_tokens"])
            output = int(token_contract["max_output_tokens"])
            if calibration is not None:
                expected = next(row for row in calibration["reservations"] if row["repair_number"] == generation and row["stage"] == request.stage)
                assert total == expected["estimated_tokens"], "complete frozen request changed after synthetic calibration"
            payload["usage"] = {"input_tokens": total - output, "output_tokens": output, "total_tokens": total,
                                "measurement": "SIMULATED_COMPLETE_REQUEST_RESERVATION_NOT_MODEL_USAGE"}
        payload["cost"] = {"amount": "0", "currency": "USD", "measurement": "SIMULATED_NOT_BILLED"}
        return replace(result, request_payload=payload)

    monkeypatch.setattr(PostgresPlanningExecutionPreparer, "prepare", prepare)
    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, "resolve", resolve)
    jobs = RuntimeJobAuthority(database_url)
    if stop == "calibration":
        with pytest.raises(KernelError, match="SCRIPTED_CALIBRATION_BOUNDARY_REACHED"):
            for _ in range(20):
                schedule_book_coordination_jobs(composition.query, jobs, limit=1, book_run_id=admitted.book_run_id)
                claim = jobs.claim(runtime_group="book", worker_id="craft-budget-calibration-fixture", lease_seconds=30,
                    job_kinds=("BOOK_COORDINATION_TICK",), subject_kind="BOOK_RUN", subject_id=admitted.book_run_id)
                assert claim is not None
                execute_book_coordination_claim(jobs, composition, claim)
            pytest.fail("Finite native calibration did not reach its third-generation boundary")
        assert len(transport.chapter_inputs) == 2
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("""SELECT g.repair_number,e.external_effect_id,e.request_payload->>'stage',
                b.estimated_tokens,b.actual_tokens,b.status,e.request_payload->'provider_token_contract'->>'contract_hash'
                FROM authority_story_planning_generation g JOIN authority_external_effect e USING(operation_id)
                JOIN authority_budget_reservation b USING(external_effect_id)
                WHERE g.project_id=%s AND g.generator_operation_name='chapter_plan.generate'
                ORDER BY g.repair_number,e.created_at""", [snapshot.project_id])
            rows = [dict(zip(("repair_number", "effect_id", "stage", "estimated_tokens", "actual_tokens", "status", "reservation_contract_hash"), row)) for row in uow.cursor.fetchall()]
        assert len(rows) == 6 and all(row["status"] == "SETTLED" and row["actual_tokens"] == row["estimated_tokens"] for row in rows)
        return {"budget_exhaustion": "calibration", "project_id": snapshot.project_id, "calls_per_generation": 3,
            "reservations": rows, "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
            "budget_evidence_class": "SCRIPTED_NATIVE_COMPLETE_REQUEST_CALIBRATION_ONLY", "actual_real_model_calls": 0, "actual_billed_cost": 0}
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        for _ in range(20):
            schedule_book_coordination_jobs(composition.query, jobs, limit=1, book_run_id=admitted.book_run_id)
            claim = jobs.claim(runtime_group="book", worker_id="craft-budget-fixture", lease_seconds=30,
                job_kinds=("BOOK_COORDINATION_TICK",), subject_kind="BOOK_RUN", subject_id=admitted.book_run_id)
            assert claim is not None
            execute_book_coordination_claim(jobs, composition, claim)
        pytest.fail("Finite native repair budget did not stop dispatch")
    if original_cap:
        assert not transport.chapter_inputs
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("""SELECT e.external_effect_id,e.status,e.request_payload->'provider_token_contract'
                FROM authority_external_effect e JOIN authority_story_planning_generation g USING(operation_id)
                WHERE g.project_id=%s AND g.generator_operation_name='chapter_plan.generate'
                  AND e.request_payload->>'stage'='chapter_plan.generate'""", [snapshot.project_id])
            effects = uow.cursor.fetchall()
            assert len(effects) == 1 and effects[0][1] == "READY"
            effect_id, _, contract = effects[0]
            cap = state["policy"]["authorization"]["authorized_cumulative_caps"]["PRODUCTION"]
            assert cap["tokens"] == 96_000 and contract["estimated_total_tokens"] + 2000 > cap["tokens"]
            repair = state["policy"]["authorization"]["authorized_cumulative_caps"]["REPAIR"]
            assert repair["tokens"] == (34_000 if stop == "tokens" else 96_000)
            uow.cursor.execute("SELECT COUNT(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [effect_id])
            assert uow.cursor.fetchone()[0] == 0
            uow.cursor.execute("SELECT COUNT(*) FROM authority_budget_reservation WHERE external_effect_id=%s", [effect_id])
            assert uow.cursor.fetchone()[0] == 0
        return {"budget_exhaustion": stop, "original_insufficient_cap": True, "policy": state["policy"], "frozen_request_contract": contract,
            "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
            "budget_evidence_class": "SCRIPTED_NATIVE_INSUFFICIENT_REQUEST_AUTHORIZATION_ONLY", "actual_real_model_calls": 0, "actual_billed_cost": 0}
    assert len(transport.chapter_inputs) == 2
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT operation_id,repair_of_operation_id,repair_number,repair_result_asset_version_id
            FROM authority_story_planning_generation WHERE project_id=%s AND generator_operation_name='chapter_plan.generate'
            ORDER BY repair_number""", [snapshot.project_id])
        generations = uow.cursor.fetchall()
        assert len(generations) == 3 and [row[2] for row in generations] == [0, 1, 2]
        parent, child, blocked = generations
        assert child[1] == parent[0] and blocked[1] == child[0]
        source = uow.repositories.asset_documents.require(project_id=snapshot.project_id, asset_version_id=child[3])
        assert source.content["raw_result"]["knowledge_translations"][0]["decision"] == "REJECT"
        assert source.content["diagnostic"]["failure_class"] == "BUSINESS_REJECT"
        selection = transport.chapter_inputs[1]["narrative_intelligence"]
        assert selection["need"]["craft_context"]["reselection"]["history"][0]["source_asset_version_id"] == child[3]
        assert selection["selected"][0]["knowledge_card_asset_version_id"] != transport.chapter_inputs[0]["narrative_intelligence"]["selected"][0]["knowledge_card_asset_version_id"]
        uow.cursor.execute("""SELECT b.reservation_id,b.operation_id,b.estimated_tokens,b.actual_tokens,b.status,b.evidence,
            e.external_effect_id,e.request_payload->>'stage' FROM authority_budget_reservation b
            JOIN authority_external_effect e USING(external_effect_id) WHERE b.operation_id=ANY(%s) ORDER BY b.created_at""",
            [[parent[0], child[0]]])
        reservations = [dict(zip(("reservation_id", "operation_id", "estimated_tokens", "actual_tokens", "status", "evidence", "effect_id", "stage"), row)) for row in uow.cursor.fetchall()]
        assert len(reservations) == state["calls_per_generation"] * 2
        proofs = [row["evidence"]["creative_experiment"] for row in reservations]
        assert len({proof["contract_hash"] for proof in proofs}) == len({proof["policy_hash"] for proof in proofs}) == 1
        assert all(proof["authorization"] == state["policy"]["authorization"] for proof in proofs)
        assert all(proof["business_scope"]["chapter_number"] == 1 for proof in proofs)
        assert {proof["phase"] for proof in proofs} == {"PRODUCTION", "REPAIR"}
        assert all(row["status"] == "SETTLED" and row["actual_tokens"] == row["estimated_tokens"] and row["evidence"]["fixture"] and not row["evidence"]["real_model_call"] for row in reservations)
        uow.cursor.execute("SELECT COUNT(*) FROM authority_external_effect_dispatch d JOIN authority_external_effect e USING(external_effect_id) WHERE e.operation_id=%s", [blocked[0]])
        assert uow.cursor.fetchone()[0] == 0
        uow.cursor.execute("SELECT COUNT(*) FROM authority_budget_reservation WHERE operation_id=%s", [blocked[0]])
        assert uow.cursor.fetchone()[0] == 0
        uow.cursor.execute("SELECT request_payload->'provider_token_contract'->>'estimated_total_tokens' FROM authority_external_effect WHERE operation_id=%s", [blocked[0]])
        pending = uow.cursor.fetchall()
        assert len(pending) == 1
        next_reservation = int(pending[0][0])
    usage = get_creative_budget(database_url, snapshot.project_id)["budget_usage"]
    repair = usage["phases"]["REPAIR"]
    assert repair["calls_used_or_reserved"] == state["prior"]["phases"]["REPAIR"]["calls_used_or_reserved"] + state["calls_per_generation"]
    calibrated_repair = [row["estimated_tokens"] for row in calibration["reservations"] if row["repair_number"] == 1]
    assert repair["conservative_tokens"] == state["prior"]["phases"]["REPAIR"]["conservative_tokens"] + sum(calibrated_repair)
    cap = state["policy"]["authorization"]["authorized_cumulative_caps"]["REPAIR"]
    assert (repair["calls_used_or_reserved"] + 1 > cap["calls"]) == (stop == "calls")
    assert (repair["conservative_tokens"] + next_reservation > cap["tokens"]) == (stop == "tokens")
    proof = {"proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY", "budget_evidence_class": "SCRIPTED_NATIVE_BUDGET_PROTOCOL_ONLY", "project_id": snapshot.project_id,
        "book_run_id": admitted.book_run_id, "budget_exhaustion": stop, "generations": generations,
        "reservations": reservations, "policy": state["policy"], "usage": usage,
        "actual_real_model_calls": 0, "actual_billed_cost": 0, "token_cost_basis": "SIMULATED_COMPLETE_REQUEST_RESERVATION_NOT_MODEL_USAGE",
        "calibration": calibration, "next_frozen_reservation_tokens": next_reservation}
    if os.environ.get("NARRATIVE_CRAFT_NATIVE_EVIDENCE_PATH"):
        Path(os.environ["NARRATIVE_CRAFT_NATIVE_EVIDENCE_PATH"]).write_text(json.dumps(proof, ensure_ascii=False, indent=2, default=str))
    return proof
