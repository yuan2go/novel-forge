import json
import os
from pathlib import Path
import subprocess
import sys
import time

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.workers.book_authority import (
    execute_book_coordination_claim,
    schedule_book_coordination_jobs,
)


def run_process_recovery(*, composition, runtime_config, book_run_id, project_id):
    root = Path(runtime_config["root"])
    config = {
        **runtime_config,
        "book_run_id": book_run_id,
        "project_id": project_id,
        "database_url": composition.authority.database_url,
    }
    principal = composition.principal
    config["principal"] = {
        "principal_id": principal.principal_id,
        "principal_type": principal.principal_type.value,
        "permissions": sorted(principal.permissions),
        "project_scope": sorted(principal.project_scope),
        "authentication_source": principal.authentication_source,
    }
    config_path = root / "world-process-input.json"
    config_path.write_text(json.dumps(config))
    phases = []
    creative = str(config.get("crash_target") or "").startswith("creative_process_")
    for phase in (("crash", "resume") if creative else ("crash", "contender", "resume")):
        result = subprocess.run(
            [sys.executable, "-m", __name__, str(config_path), phase],
            capture_output=True,
            text=True,
            timeout=240,
        )
        phases.append(
            {
                "phase": phase,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        expected = 86 if phase == "crash" else 1 if phase == "contender" else 0
        if result.returncode != expected:
            calls_path = root / "world-process-calls.jsonl"
            phases[-1]["confirmed_transport_calls"] = (
                calls_path.read_text() if calls_path.exists() else ""
            )
        assert result.returncode == expected, phases[-1]
        if phase == "contender":
            assert "CONTENT_RECOVERY_LEASE_ACTIVE" in result.stderr
            time.sleep(31)
        if phase == "crash":
            assert (
                composition.authority.require(book_run_id)["accepted_through_chapter"]
                == 0
            )
            time.sleep(31 if creative else 1.2)
    calls = [
        json.loads(line)
        for line in (root / "world-process-calls.jsonl").read_text().splitlines()
    ]
    assert len({call["pid"] for call in calls}) == 2
    if creative:
        for stage in ("memo", "canon_support", "draft", "revision", "canon_extraction"):
            stage_calls = [call for call in calls if call["stage"] == stage]
            assert len(stage_calls) == 3, (stage, len(stage_calls))
    generated = [call for call in calls if call["stage"] == "world_candidates.generate"]
    assert len(generated) == 3
    assert [
        call["input"]["world_preparation"]["accepted_through_chapter"]
        for call in generated
    ] == [0, 1, 2]
    reality = composition.query.narrative_reality(book_run_id=book_run_id)
    assert reality["chapter_number"] == 3
    assert any(
        entry["state"].get("goal_reached") is True
        for entry in reality["current_state"]["world_state"]
    )
    debts = [
        entry["state"]
        for entry in reality["current_state"]["narrative_obligation"]
        if entry["state"].get("obligation_type") == "CAUSAL_DEBT"
    ]
    assert len(debts) == 1 and debts[0]["status"] == "FULFILLED"
    from novel_forge.modules.narrative_state import NarrativeStateRebuildService

    rebuilt = NarrativeStateRebuildService(composition.authority.database_url).rebuild(
        project_id=project_id, book_id=reality["book_id"]
    )
    assert rebuilt.projection["current_state"] == reality["current_state"]
    return {
        "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
        "scenario": config.get("crash_target", "process_recovery"),
        "book_run_id": book_run_id,
        "calls": calls,
        "processes": phases,
        "reality_revision_id": reality["revision_id"],
    }


def main():
    from tests.integration.world_causal_production_support import (
        AutonomousWorldTransport,
    )

    config = json.loads(Path(sys.argv[1]).read_text())
    phase = sys.argv[2]
    root = Path(config["root"])
    transport = AutonomousWorldTransport("multi_preparation")

    def record(stage, inputs, callback):
        output = callback(stage, inputs)
        with (root / "world-process-calls.jsonl").open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "stage": stage,
                        "input": inputs,
                        "output": output,
                    }
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        return output

    def chapter_fault(point):
        target = config.get("crash_target")
        stage = "canon_support" if target == "creative_process_support" else "memo"
        boundary = "after_domain_asset_materialized" if target == "creative_process_artifact" else "after_provider_success"
        if phase == "crash" and str(target).startswith("creative_process_") and point == boundary and transport.calls[-1]["stage"] == stage:
            os._exit(86)

    def fault(point):
        if (
            phase == "crash"
            and not str(config.get("crash_target") or "").startswith("creative_process_")
            and point == "after_provider_receipt_before_budget_settlement"
            and transport.calls[-1]["stage"] == "world_candidates.generate"
        ):
            os._exit(86)

    settings = IndustrialSettings(
        root=str(root),
        environment="development",
        storage_authority="postgresql",
        database_url=config["database_url"],
    )
    execution = build_production_execution_composition(
        settings,
        env=config["env"],
        chapter_fixture_factory=lambda stage, inputs: record(stage, inputs, transport),
        planning_fixture_factory=lambda stage, inputs: record(
            stage, inputs, transport.planning
        ),
    )
    raw = config["principal"]
    principal = Principal(
        principal_id=raw["principal_id"],
        principal_type=PrincipalType(raw["principal_type"]),
        permissions=frozenset(raw["permissions"]),
        project_scope=frozenset(raw["project_scope"]),
        authentication_source=raw["authentication_source"],
    )
    chapter = build_chapter_authority_application(
        settings, execution=execution, env=config["env"], runtime_fault_injector=chapter_fault,
    )
    composition = build_book_production_composition(
        settings,
        principal=principal,
        execution=execution,
        env=config["env"],
        chapter_application=chapter,
        planning_post_provider_fault_injector=fault,
    )
    jobs = RuntimeJobAuthority(config["database_url"])
    for _ in range(60):
        if (
            composition.authority.require(config["book_run_id"])[
                "accepted_through_chapter"
            ]
            == 3
        ):
            execution.close()
            print(json.dumps({"pid": os.getpid(), "accepted_through_chapter": 3}))
            return
        schedule_book_coordination_jobs(
            composition.query, jobs, limit=1, book_run_id=config["book_run_id"]
        )
        claim = jobs.claim(
            runtime_group="book",
            worker_id=f"process-{os.getpid()}",
            lease_seconds=1,
            job_kinds=("BOOK_COORDINATION_TICK",),
            subject_kind="BOOK_RUN",
            subject_id=config["book_run_id"],
        )
        assert claim is not None
        execute_book_coordination_claim(
            jobs, composition, claim, lease_seconds=1
        )
        scheduler = chapter.scheduler(principal=Principal(principal_id="world-recovery-chapter-worker", principal_type=PrincipalType.WORKER, permissions=principal.permissions - {"book.authority.approve_replan"}, project_scope=principal.project_scope, authentication_source="owned-process-recovery-fixture"))
        for _ in range(80):
            roots = [item for item in scheduler.pending_roots(limit=100) if item[0] == config["project_id"]]
            if not roots:
                break
            for project_id, root_id in roots:
                scheduler.tick(project_id=project_id, root_operation_id=root_id)
    raise AssertionError(
        "bounded process recovery failed to complete the accepted preparation"
    )


if __name__ == "__main__":
    main()
