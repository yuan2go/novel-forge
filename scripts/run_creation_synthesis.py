"""Run a bounded creative brief through native Formation, Book Opening and Chapter production."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_content_authority_application,
    build_production_execution_composition,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.creation_inputs import prepare_creation_inputs
from novel_forge.modules.book_authority.opening import (
    OpenBookProductionRequest,
    _OPENING_INPUT_ROLES,
)
from novel_forge.modules.book_design_authority.formation import (
    StartStoryFormationCommand,
)
from novel_forge.modules.book_design_authority.formation_domain import (
    StoryFormationInput,
)
from novel_forge.modules.content_authority.application import ContentOperationRequest
from novel_forge.modules.creative.domain import validate_creative_brief
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.tools.backend_qualification_resources import (
    require_disposable_database_name,
)
from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
)
from novel_forge.workers.book_authority import (
    execute_book_opening_claim,
    execute_story_formation_claim,
)
from scripts.creation_pilot import (
    authorize_execution,
    freeze_routes,
    prepare_pilot_book,
    pilot_stop_cursor,
    reading_checkpoints,
)
from scripts.run_world_production_smoke import (
    drive,
    export,
    export_artifacts,
    start_command,
    validate_configuration,
)
from novel_forge.modules.production_execution.security import redact_secret_text
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from scripts.creation_freeze import load_frozen_inputs
from scripts.creation_comparison import (
    COMPARISON_RUNTIME_SETTINGS, validate_comparison_budget,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--formation-policy", type=Path, required=True)
    parser.add_argument("--knowledge-policy", type=Path, help="Exact approved Book knowledge access policy, frozen before Formation")
    parser.add_argument("--comparison-budget", "--production-budget", dest="comparison_budget", type=Path, help="Immutable A/B or single-Book stage plan; native authorization is separate")
    parser.add_argument("--freeze-dir", type=Path)
    parser.add_argument("--freeze-manifest-hash", help="Pinned final-byte SHA-256 of freeze.json")
    parser.add_argument("--plan-change-proposal-id", default="", help="Owned ACTIVE future change required to continue past the configured intervention")
    parser.add_argument("--resume-after-checkpoint", type=int, default=0)
    parser.add_argument("--checkpoint-review-decision-id", default="")
    parser.add_argument("--register-input-only", action="store_true", help="Register the exact author brief through Content without Provider, Formation or Book activation")
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--book-id",
        required=True,
        help="Stable Book identity; --initialize creates it through Authority after authorization, while input-only registration binds the intended identity",
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--resume-formation-run-id", default="")
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="Register isolated Project/Book through existing Commands; idempotent on resume",
    )
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--authorized-total-usd", default="")
    parser.add_argument("--authorization-ref", default="")
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Requires existing explicit authorized Provider budgets",
    )
    parser.add_argument("--max-seconds", type=int, default=1800)
    args = parser.parse_args(argv)
    if not 1 <= args.max_seconds <= 7200:
        parser.error("max-seconds must be 1..7200")
    paths = {"brief": args.brief, "creation": args.policy, "formation": args.formation_policy}
    if args.knowledge_policy:
        paths["knowledge"] = args.knowledge_policy
    if args.comparison_budget:
        paths["budget"] = args.comparison_budget
    documents, input_snapshot = load_frozen_inputs(
        paths, freeze_dir=args.freeze_dir, expected_manifest_hash=args.freeze_manifest_hash,
        required=args.comparison_budget is not None,
    )
    brief, policy, formation_policy = (documents[key] for key in ("brief", "creation", "formation"))
    comparison_budget = validate_comparison_budget(documents["budget"]) if args.comparison_budget else None
    from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
    profile = policy["profiles"]["production_profile"]["content"]
    if args.knowledge_policy:
        profile["knowledge_access_policy"] = documents["knowledge"]
    knowledge_access = resolve_book_knowledge_access_policy(
        production_profile=profile, project_id=args.project_id, book_id=args.book_id,
    )
    validate_creative_brief(brief)
    if brief.get("author_design"):
        from novel_forge.modules.story_design_authority.author_input import validate_author_design
        validate_author_design(brief["author_design"], project_id=args.project_id, book_id=args.book_id)
    StoryFormationInput(
        creative_brief_asset_version_id="configuration-check",
        creative_brief_content_hash="sha256:" + "0" * 64,
        generation_policy=formation_policy,
    )
    if (
        policy.get("contract_version") != "creation-input-policy.v1"
        or policy["profiles"]["production_profile"]["content"]["target_chapter_count"]
        != formation_policy["target_chapters"]
    ):
        parser.error(
            "creation and Formation policies must have the same bounded target"
        )
    try:
        pilot_cursor = pilot_stop_cursor(policy, book_target=formation_policy["target_chapters"])
        checkpoints = reading_checkpoints(policy, book_target=formation_policy["target_chapters"])
    except ValueError as exc:
        parser.error(str(exc))
    repo = Path(__file__).resolve().parents[1]
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "source_sha": source_sha,
        "project_id": args.project_id,
        "book_id": args.book_id,
        "run_key": args.run_key,
        "stage": "CONFIGURATION",
        "implementation_identity": build_implementation_tree_identity(repo)[
            "implementation_tree_sha"
        ],
        "real_provider": "NOT_RUN",
        "human_editorial": "NOT_RUN",
        "longitudinal": "NOT_PROVEN",
        "input_snapshot": input_snapshot,
        "creation_policy": policy,
        "knowledge_access_policy": knowledge_access,
        "formation_policy": formation_policy,
        "book_target_chapter_count": formation_policy["target_chapters"],
        "pilot_stop_after_chapter": pilot_cursor,
        "reading_checkpoints": list(checkpoints),
        "production_scope": "AUTHOR_GUIDED_SINGLE_BOOK" if brief.get("author_design") else "CREATIVE_BRIEF_PRODUCTION",
        "full_book_completion": "NOT_PROVEN",
        "brief_input_hash": "sha256:"
        + hashlib.sha256(
            json.dumps(brief, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    }
    if comparison_budget is not None:
        report["comparison_budget"] = comparison_budget
    started_at = time.monotonic()

    def record(event):
        with (args.evidence_dir / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    execution = composition = None
    book_run_id = ""
    database_url = ""
    budget_binding = None
    try:
        if args.register_input_only:
            if args.execute or args.expected_sha != source_sha or subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).strip():
                raise ValueError("Input registration requires a clean exact SHA and cannot also execute production")
            if not args.workspace_id:
                raise ValueError("Input registration requires the existing project workspace")
            values = dict(os.environ)
            settings = IndustrialSettings.from_env(values, root=args.root)
            principal = build_trusted_principal_resolver(env=values).resolve_api_principal()
            content = build_content_authority_application(settings, env=values)
            authored = content.execute(ContentOperationRequest(
                definition_name="creative.brief.create", project_id=args.project_id,
                workspace_id=args.workspace_id, actor_id=principal.principal_id,
                trace_id=f"trace:{args.run_key}", correlation_id=args.run_key,
                idempotency_key=f"{args.run_key}:brief", payload={"brief": brief},
            ), principal=principal)
            report.update(status="AUTHOR_INPUT_REGISTERED_NOT_APPROVED", author_input={
                "asset_version_id": authored.asset_version_id, "content_hash": authored.content_hash,
                "operation_id": authored.operation_id, "provider_calls": 0,
            })
            return 0
        if not args.execute:
            report["status"] = "CONFIGURATION_VALIDATED_NO_PROVIDER_CALL"
            return 0
        if (
            args.expected_sha != source_sha
            or subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=repo, text=True
            ).strip()
        ):
            raise ValueError("execution requires a clean exact expected SHA")
        values = dict(os.environ)
        authorization = authorize_execution(
            values, args.authorized_total_usd, args.authorization_ref
        )
        report.update(authorization)
        validate_configuration(values)
        database_url = values.get("NOVEL_FORGE_DATABASE_URL", "")
        import psycopg

        with psycopg.connect(
            database_url, options="-c default_transaction_read_only=on"
        ) as connection:
            require_disposable_database_name(
                connection.execute("SELECT current_database()").fetchone()[0]
            )
        if comparison_budget is not None:
            from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
            native_budget = get_creative_budget(database_url, args.project_id)
            if native_budget["comparison_budget"] != comparison_budget:
                raise ValueError("Native experiment budget differs from the frozen opportunity plan")
            budget_binding = native_budget["budget_binding"]
            report.update(native_budget)
        settings = IndustrialSettings.from_env(values, root=args.root)
        resolver = build_trusted_principal_resolver(env=values)
        principal = resolver.resolve_api_principal()
        principal.require("book.authority.execute", args.project_id)
        worker = resolver.resolve_worker_principal("creation-synthesis-worker")
        formation_worker = resolver.resolve_book_formation_worker_principal(
            worker.principal_id
        )
        content = build_content_authority_application(settings, env=values)
        execution = build_production_execution_composition(settings, env=values)
        if any(
            route.model_profile.model_provider == "scripted_provider_v2"
            for route in execution.gateway.routes.values()
        ):
            raise ValueError("real creation execution cannot use scripted routes")
        chapter = build_chapter_authority_application(
            settings, execution=execution, env=values
        )
        composition = build_book_production_composition(
            settings,
            principal=principal,
            execution=execution,
            chapter_application=chapter,
            env=values,
        )
        frozen = {
            "contract_version": "creation-pilot.v1",
            "run_key": args.run_key,
            "brief_input_hash": report["brief_input_hash"],
            "creation_policy": policy,
            "formation_policy": formation_policy,
            "implementation_identity": report["implementation_identity"],
            "models": freeze_routes(execution.gateway.routes),
            "cost_accounting": authorization,
            "runtime_settings": {
                key: value
                for key, value in values.items()
                if key
                in {
                    "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL",
                    "NOVEL_FORGE_OPERATION_PROVIDER_CAP",
                    "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP",
                    "NOVEL_FORGE_DAILY_PROVIDER_CAP",
                    "NOVEL_FORGE_CHAPTER_PROVIDER_CAP",
                    "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID",
                    "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID",
                    "NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET",
                    "NOVEL_FORGE_BOOK_QUALITY_CONTEXT_TOKEN_BUDGET",
                    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_CALL_LIMIT",
                    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_COST_LIMIT",
                    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_TOKEN_LIMIT",
                    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_PER_CALL_TOKEN_LIMIT",
                    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_PER_CALL_COST_LIMIT",
                    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_WINDOW_SECONDS",
                    "NOVEL_FORGE_CODEX_ACCOUNTING_MODE",
                    "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF",
                    "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF",
                    "NOVEL_FORGE_CODEX_CLI_VERSION",
                    "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256",
                    "NOVEL_FORGE_CODEX_CONFIGURATION_REF",
                    "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT",
                    "NOVEL_FORGE_OPERATION_PROVIDER_CALL_LIMIT",
                    "NOVEL_FORGE_PROVIDER_PROJECT_CALL_LIMIT",
                    "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CALL_LIMIT",
                    "NOVEL_FORGE_PROVIDER_DAILY_CALL_LIMIT",
                    "NOVEL_FORGE_GLOBAL_DAILY_PROVIDER_CALL_LIMIT",
                    "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT",
                    "NOVEL_FORGE_OPERATION_PROVIDER_TOKEN_LIMIT",
                    "NOVEL_FORGE_PROVIDER_PROJECT_TOKEN_LIMIT",
                    "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_TOKEN_LIMIT",
                    "NOVEL_FORGE_PROVIDER_DAILY_TOKEN_LIMIT",
                    "NOVEL_FORGE_GLOBAL_DAILY_PROVIDER_TOKEN_LIMIT",
                }
            },
        }
        if comparison_budget is not None:
            frozen.update(
                comparison_budget=comparison_budget,
                input_snapshot=input_snapshot,
                runtime_identity={
                    "project_id": args.project_id, "book_id": args.book_id,
                    "workspace_id": args.workspace_id, "run_key": args.run_key,
                    "runtime_root": str(args.root.expanduser().resolve()),
                    "provider_execution_root": str(Path(values["NOVEL_FORGE_CODEX_EXECUTION_ROOT"]).expanduser().resolve()),
                },
                runtime_settings={key: value for key, value in values.items() if key in COMPARISON_RUNTIME_SETTINGS},
            )
        report["frozen_configuration"] = frozen
        report["stage"] = "PREPARATION"
        book = prepare_pilot_book(
            composition=composition,
            principal=principal,
            project_id=args.project_id,
            workspace_id=args.workspace_id,
            book_id=args.book_id,
            run_key=args.run_key,
            title=formation_policy["title"],
            frozen=frozen,
            initialize=args.initialize,
            budget_binding=budget_binding,
        )
        record(
            {"kind": "PREPARATION", "book_id": args.book_id, "version": book["version"]}
        )
        if policy.get("chapter_group_execution"):
            from novel_forge.modules.chapter_group_authority.policy import (
                ChapterGroupExecutionPolicy, PostgresChapterGroupExecutionPolicyAuthority,
            )
            group_policy = PostgresChapterGroupExecutionPolicyAuthority(
                database_url, application_build_id=composition.authority.application_build_id,
                commit_sha=composition.authority.commit_sha,
            ).configure(
                project_id=args.project_id, workspace_id=book["workspace_id"], principal=principal,
                policy=ChapterGroupExecutionPolicy(**policy["chapter_group_execution"]),
                idempotency_key=f"{args.run_key}:chapter-group-policy",
                trace_id=f"trace:{args.run_key}", correlation_id=args.run_key,
            )
            record({"kind": "CHAPTER_GROUP_POLICY", "result": group_policy})
        deadline = time.monotonic() + args.max_seconds
        formation = composition.formation
        report["stage"] = "FORMATION"
        existing_formation = formation.find_by_key(
            project_id=args.project_id,
            book_id=args.book_id,
            idempotency_key=f"{args.run_key}:formation",
        )
        if args.resume_formation_run_id and (
            not existing_formation
            or existing_formation["formation_run_id"] != args.resume_formation_run_id
        ):
            raise ValueError(
                "Explicit Formation id must match this exact pilot run key"
            )
        if existing_formation:
            run = existing_formation
            formation_run_id = run["formation_run_id"]
            if run["project_id"] != args.project_id or run["book_id"] != args.book_id:
                raise ValueError("resume Formation belongs to another Book")
            frozen = StoryFormationInput.from_mapping(run["frozen_input"])
            if frozen.generation_policy != formation_policy:
                raise ValueError("resume requires the original frozen Formation policy")
            if frozen.digest != run["frozen_input_digest"]:
                raise ValueError("Formation frozen input digest mismatch")
            original = AuthorityAssetQuery(database_url).require(
                project_id=args.project_id,
                asset_version_id=frozen.creative_brief_asset_version_id,
            )
            if original.content_hash != frozen.creative_brief_content_hash or any(
                original.content.get(key) != value for key, value in brief.items()
            ):
                raise ValueError("resume requires the original frozen creative brief")
        else:
            authored = content.execute(
                ContentOperationRequest(
                    definition_name="creative.brief.create",
                    project_id=args.project_id,
                    workspace_id=book["workspace_id"],
                    actor_id=principal.principal_id,
                    trace_id=f"trace:{args.run_key}",
                    correlation_id=args.run_key,
                    idempotency_key=f"{args.run_key}:brief",
                    payload={"brief": brief},
                ),
                principal=principal,
            )
            admitted = formation.admit(
                StartStoryFormationCommand(
                    project_id=args.project_id,
                    workspace_id=book["workspace_id"],
                    book_id=args.book_id,
                    actor_id=principal.principal_id,
                    expected_book_version=book["version"],
                    stable_idempotency_key=f"{args.run_key}:formation",
                    trace_id=f"trace:{args.run_key}",
                    correlation_id=args.run_key,
                    frozen_input=StoryFormationInput(
                        creative_brief_asset_version_id=authored.asset_version_id,
                        creative_brief_content_hash=authored.content_hash,
                        generation_policy=formation_policy,
                    ),
                ),
                principal=principal,
            )
            formation_run_id = admitted.formation_run_id
        report["formation_run_id"] = formation_run_id
        record({"kind": "FORMATION", "run": formation.require(formation_run_id)})
        for _ in range(10):
            state = formation.require(formation_run_id)
            if state["lifecycle"] == "READY":
                break
            if (
                state["lifecycle"] in {"FAILED", "ABORTED"}
                or time.monotonic() >= deadline
            ):
                raise RuntimeError(f"Formation stopped: {state}")
            if state["lifecycle"] == "WAITING_APPROVAL":
                report["status"] = "WAITING_APPROVAL"
                report["approval_checkpoint"] = {
                    "formation_run_id": formation_run_id,
                    "stage": state["current_stage"],
                    "version": state["version"],
                    "frozen_input_digest": state["frozen_input_digest"],
                }
                return 3
            formation.schedule_candidates(
                limit=1, project_id=args.project_id, formation_run_id=formation_run_id
            )
            claim = formation.runtime_jobs.claim(
                runtime_group="story_formation",
                worker_id=worker.principal_id,
                lease_seconds=60,
                job_kinds=("STORY_FORMATION_ADVANCE",),
                subject_kind="STORY_FORMATION_RUN",
                subject_id=formation_run_id,
                project_id=args.project_id,
            )
            if claim is None:
                raise RuntimeError(
                    "Formation awaits its existing lease/retry; resume the same run"
                )
            execute_story_formation_claim(
                formation.runtime_jobs,
                formation,
                formation_worker,
                claim,
                lease_seconds=60,
            )
            record({"kind": "FORMATION", "run": formation.require(formation_run_id)})
        prepared = prepare_creation_inputs(
            composition=composition,
            content=content,
            formation_run_id=formation_run_id,
            policy=policy,
        )
        versions = prepared["versions"]
        report["stage"] = "OPENING"
        opening_state = composition.opening.find_by_key(
            project_id=args.project_id,
            book_id=args.book_id,
            idempotency_key=f"{args.run_key}:opening",
        )
        if opening_state is None:
            opening = composition.open_book(
                OpenBookProductionRequest(
                    project_id=args.project_id,
                    workspace_id=book["workspace_id"],
                    book_id=args.book_id,
                    actor_id=principal.principal_id,
                    expected_book_version=prepared["book_version"],
                    production_profile=versions["production_profile"],
                    planning_input_versions={
                        role: versions[role] for role in _OPENING_INPUT_ROLES
                    },
                    arc_logical_keys=("arc:central",),
                    idempotency_key=f"{args.run_key}:opening",
                    trace_id=f"trace:{args.run_key}",
                    correlation_id=args.run_key,
                    initial_story_state_version=versions["story_state"],
                    initial_canon_snapshot_version=versions["canon_snapshot"],
                )
            )
            opening_state = composition.opening.require(opening.opening_run_id)
        opening_run_id = opening_state["opening_run_id"]
        report["opening_run_id"] = opening_run_id
        record(
            {
                "kind": "OPENING_PROGRESS",
                "progress": composition.opening.require_progress(opening_run_id),
            }
        )
        if opening_state["lifecycle"] == "COMPLETE":
            opened = opening_state["result"]
        else:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Bounded creation time exhausted before Opening; resume the frozen run"
                )
            claim = composition.opening.claim_next_execution(
                worker_id=worker.principal_id,
                lease_seconds=60,
                project_id=args.project_id,
                expected_opening_run_id=opening_run_id,
            )
            if claim is None:
                raise RuntimeError(
                    "Opening awaits existing lease/retry; inspect its native progress and resume"
                )
            opened = execute_book_opening_claim(
                RuntimeJobAuthority(database_url),
                composition.opening,
                worker,
                claim,
                lease_seconds=60,
            )
        record({"kind": "OPENING", "opening_run_id": opening_run_id, "result": opened})
        snapshot = composition.input_resolver.require(opened["input_snapshot_id"])
        admitted = composition.authority.start(
            start_command(
                snapshot,
                actor=principal.principal_id,
                run_key=f"{args.run_key}:production",
                chapters=formation_policy["target_chapters"],
            ),
            principal=principal,
        )
        book_run_id = admitted.book_run_id
        report["book_run_id"] = book_run_id
        report["stage"] = "CHAPTER_PRODUCTION"
        intervention = policy.get("future_plan_change") or {}
        stop_after = int(intervention.get("after_chapter") or 0)
        if args.plan_change_proposal_id:
            from scripts.creation_pilot import verify_future_plan_change
            report["future_plan_change"] = verify_future_plan_change(
                composition=composition, book_run_id=book_run_id,
                proposal_id=args.plan_change_proposal_id, intervention=intervention,
            )
            stop_after = 0
        report["status"] = drive(
            composition=composition,
            chapter=chapter,
            book_run_id=book_run_id,
            worker=worker,
            events=record,
            maximum_ticks=80,
            deadline=deadline,
            stop_after_chapter=stop_after,
            pilot_stop_after_chapter=pilot_cursor,
            checkpoints=checkpoints,
            resume_after_checkpoint=args.resume_after_checkpoint,
            checkpoint_review_decision_id=args.checkpoint_review_decision_id,
        )
        report["real_provider"] = "EXECUTED_SEE_RECEIPTS"
        return 0 if report["status"] in {"ACCEPTED_TARGET_REACHED", "PILOT_ACCEPTED_CURSOR_REACHED"} else 2
    except Exception as exc:
        report.update(
            status="BLOCKED",
            error={"type": type(exc).__name__, "message": redact_secret_text(str(exc))},
        )
        record({"kind": "FAILURE", "stage": report["stage"], "error": report["error"]})
        if execution is not None:
            report["real_provider"] = "INSPECT_RECEIPTS_PARTIAL_OR_FAILED"
        return 2
    finally:
        try:
            if composition is not None:
                export_artifacts(
                    project_id=args.project_id,
                    database_url=composition.authority.database_url,
                    destination=args.evidence_dir,
                    extra_kinds=(
                        "creative_brief",
                        "planning_generation_candidate",
                        "narrative_design_evaluation",
                        "book_design",
                        "style_policy",
                        "character_arc_portfolio",
                    ),
                )
        except Exception as exc:
            report["artifact_export_error"] = redact_secret_text(str(exc))
        try:
            if comparison_budget is not None and database_url:
                from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
                try:
                    native_budget = get_creative_budget(database_url, args.project_id)
                    if native_budget["comparison_budget"] != comparison_budget:
                        raise ValueError("Native experiment budget changed during execution")
                    report["budget_usage"] = native_budget["budget_usage"]
                    report["budget_binding_at_export"] = native_budget["budget_binding"]
                except Exception as exc:
                    report["budget_export_error"] = redact_secret_text(str(exc))
                    raise
            if composition is not None and book_run_id:
                export(
                    composition=composition,
                    book_run_id=book_run_id,
                    destination=args.evidence_dir,
                    include_artifacts=False,
                )
            if report.get("artifact_export_error"):
                raise RuntimeError("Partial artifact export; inspect retained status")
        except Exception as exc:
            report["export_error"] = redact_secret_text(str(exc))
            report["status"] = "EVIDENCE_EXPORT_BLOCKED"
            return 2
        finally:
            if execution is not None:
                execution.close()
            report["invocation_elapsed_seconds"] = round(
                time.monotonic() - started_at, 3
            )
            (args.evidence_dir / "creation-run.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str)
            )


if __name__ == "__main__":
    raise SystemExit(main())
