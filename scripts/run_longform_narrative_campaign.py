#!/usr/bin/env python3
"""Run or resume the exact-HEAD 300-Chapter Narrative Proof Campaign."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping
from uuid import uuid4

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority import (
    ResolveBookProductionInputCommand,
    StartBookProductionCommand,
)
from novel_forge.modules.book_design_authority import BookDesignAuthorityQuery
from novel_forge.modules.capability_packs.longform_profiles import (
    build_reader_outcome_pack_profile,
    build_story_planning_pack_profile,
)
from novel_forge.modules.runtime_proof import (
    contract_identity,
    load_campaign_contract,
)
from novel_forge.storage.migrations import run_migrations
from novel_forge.storage.object_store import MinioObjectStore

from run_real_capability_codex_proof import (
    PACK_PERMISSIONS,
    _install_pack,
    _jsonable,
    _principal,
    _query_rows,
    _runtime_env,
)
from run_short_longform_runtime_proof import (
    PLANNING_PACK_ID,
    PLANNING_PACK_INITIAL_VERSION,
    PROOF_QUALITY_CONTEXT_TOKEN_BUDGET,
    READER_PACK_ID,
    _accept_chapter,
    _bootstrap_assets,
    _bootstrap_chapter_profiles,
    _chapter_outputs,
    _codex_version,
    _complete_reader_sidecar,
    _drive_to_chapter_dispatch,
    _install_profile,
    _proof_bucket_names,
    _register_longform_definitions,
    _release_checkout,
    _run_chapter_scheduler,
    _run_planning,
    _seed_project_and_active_design,
)


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TARGETS = frozenset({1, 30, 100, 300})
SCHEMA_VERSION = "novel-forge.longform-proof-campaign-checkpoint.v1"


def _validate_target(value: int) -> int:
    if value not in ALLOWED_TARGETS:
        raise ValueError("target chapter must be one of 1, 30, 100, or 300")
    return value


def _classify_failure(error: BaseException) -> str:
    message = f"{type(error).__name__}: {error}".casefold()
    if any(word in message for word in ("credential", "provider", "codex login")):
        return "PROVIDER_FAILURE"
    if any(word in message for word in ("postgres", "minio", "connection refused")):
        return "ENVIRONMENT_BLOCKER"
    if "context" in message:
        return "CONTEXT_DEFECT"
    if any(word in message for word in ("canon", "continuity", "knowledge")):
        return "CONTENT_CORRECTNESS_FAILURE"
    if any(word in message for word in ("quality", "corrective", "readability")):
        return "CONTENT_QUALITY_FAILURE"
    if any(word in message for word in ("harness", "checkpoint output", "export")):
        return "PROOF_HARNESS_DEFECT"
    return "RUNTIME_DEFECT"


def _validate_resume_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    contract_identity: str,
    commit_sha: str,
    target_chapter: int,
) -> None:
    if checkpoint.get("contract_identity") != contract_identity:
        raise RuntimeError("resume checkpoint belongs to another Proof Contract")
    release = checkpoint.get("release")
    if not isinstance(release, Mapping) or release.get("commit_sha") != commit_sha:
        raise RuntimeError("resume checkpoint belongs to another exact HEAD")
    accepted = int(checkpoint.get("accepted_through_chapter") or 0)
    if target_chapter < accepted:
        raise RuntimeError("target chapter is behind the durable cursor")


def _validate_frozen_provider_policy(
    provider: Mapping[str, Any],
    *,
    model: str,
    reasoning_effort: str,
    quality_context_token_budget: int,
) -> None:
    if provider.get("provider") != "codex-cli":
        raise RuntimeError("Proof Contract provider is not codex-cli")
    if provider.get("silent_fallback") is not False:
        raise RuntimeError("Proof Contract permits silent Provider fallback")
    if str(provider.get("model") or "") != model:
        raise RuntimeError("CLI model differs from the frozen Proof Contract")
    if str(provider.get("reasoning_effort") or "") != reasoning_effort:
        raise RuntimeError(
            "CLI reasoning effort differs from the frozen Proof Contract"
        )
    if int(provider.get("quality_context_token_budget") or 0) != int(
        quality_context_token_budget
    ):
        raise RuntimeError(
            "CLI Quality context budget differs from the frozen Proof Contract"
        )


def _apply_frozen_provider_policy(
    env: Mapping[str, str], provider: Mapping[str, Any]
) -> dict[str, str]:
    model = str(provider["model"])
    effort = str(provider["reasoning_effort"])
    return {
        **dict(env),
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
        "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli",
        "NOVEL_FORGE_PLANNING_MODEL": model,
        "NOVEL_FORGE_PLANNING_REASONING_EFFORT": effort,
        "NOVEL_FORGE_DRAFT_MODEL": model,
        "NOVEL_FORGE_REVIEW_MODEL": model,
        "NOVEL_FORGE_REVISION_MODEL": model,
        "NOVEL_FORGE_REREVIEW_MODEL": model,
        "NOVEL_FORGE_CANON_EXTRACTION_MODEL": model,
        "NOVEL_FORGE_QUALITY_MODEL": model,
        "NOVEL_FORGE_READER_OUTCOME_MODEL": model,
        "NOVEL_FORGE_REASONING_EFFORT": effort,
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _record_process_failure(
    output_root: Path,
    error: BaseException,
    *,
    category: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> Path:
    path = output_root / "evidence" / "process-failures.json"
    existing: dict[str, Any] = {"failures": []}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, Mapping):
            existing = dict(loaded)
    failures = list(existing.get("failures") or [])
    failures.append(
        {
            "created_at": datetime.now().astimezone().isoformat(),
            "category": category or _classify_failure(error),
            "error_type": type(error).__name__,
            "error": str(error),
            "context": dict(context or {}),
        }
    )
    _write_json(
        path,
        {
            "schema_version": "novel-forge.proof-campaign-failure-history.v1",
            "failures": failures,
        },
    )
    return path


def _runtime_settings(
    args: argparse.Namespace,
    *,
    runtime_root: Path,
    commit_sha: str,
    buckets: Mapping[str, str],
    provider: Mapping[str, Any],
) -> tuple[IndustrialSettings, dict[str, str], str]:
    executable = str(Path(args.codex_executable).expanduser().resolve())
    login = subprocess.run(
        (executable, "login", "status"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    runtime_root.mkdir(parents=True, exist_ok=False)
    env = _apply_frozen_provider_policy(
        _runtime_env(
            commit_sha=commit_sha,
            codex_executable=executable,
            runtime_root=runtime_root,
            worker_id="chapter-worker:longform-narrative-proof",
            model=args.model,
            reasoning_effort=args.reasoning_effort,
        ),
        provider,
    )
    env.update(
        {
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "longform-narrative-proof",
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": PLANNING_PACK_ID,
            "NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID": READER_PACK_ID,
            "NOVEL_FORGE_STORY_PLANNING_WORKER_ID": (
                "planning-worker:longform-narrative-proof"
            ),
            "NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID": (
                "reader-worker:longform-narrative-proof"
            ),
            "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP": str(args.provider_cost_cap),
            "NOVEL_FORGE_PROVIDER_DAILY_CAP": str(args.provider_cost_cap),
            "NOVEL_FORGE_DAILY_PROVIDER_CAP": str(args.provider_cost_cap),
        }
    )
    settings = IndustrialSettings(
        root=ROOT,
        environment="production",
        storage_authority="postgresql",
        database_url=args.database_url,
        minio_endpoint=args.minio_endpoint,
        minio_access_key=args.minio_access_key,
        minio_secret_key=args.minio_secret_key,
        minio_secure=args.minio_secure,
        minio_raw_bucket=str(buckets["raw"]),
        minio_artifact_bucket=str(buckets["artifact"]),
        minio_export_bucket=str(buckets["export"]),
    )
    return settings, env, (login.stdout or login.stderr).strip()


def _operator(project_id: str):
    return _principal(
        f"operator:{project_id}",
        project_id,
        "project.authority.execute",
        "book_design.authority.execute",
        "book.authority.execute",
        "book.authority.approve_replan",
        "book.followup:*",
        "chapter.authority.execute",
        "story_design.authority.execute",
        "story_planning.authority.execute",
        "story_planning.authority.approve",
        "story_planning.authority.activate",
    )


def _initialise_campaign(
    args: argparse.Namespace,
    *,
    settings: IndustrialSettings,
    env: dict[str, str],
    contract_payload: dict[str, Any],
    commit_sha: str,
) -> tuple[dict[str, Any], Any, Any, Any]:
    suffix = uuid4().hex[:12]
    project_id = f"longform-proof:{commit_sha[:8]}:{suffix}"
    workspace_id = f"workspace:{project_id}"
    book_id = f"book:{project_id}"
    build_id = env["NOVEL_FORGE_APPLICATION_BUILD_ID"]
    operator = _operator(project_id)
    compiler = _principal(
        f"compiler:{project_id}", project_id, *sorted(PACK_PERMISSIONS)
    )
    approver = _principal(
        f"approver:{project_id}", project_id, *sorted(PACK_PERMISSIONS)
    )
    agent_admin = _principal(
        f"agent-admin:{project_id}", project_id, "agent.authority.admin"
    )
    book = _seed_project_and_active_design(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        principal=operator,
        campaign_contract=contract_payload,
    )
    bootstrap = _bootstrap_assets(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        principal=operator,
        campaign_contract=contract_payload,
    )
    chapter_profiles = _bootstrap_chapter_profiles(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        principal=operator,
    )
    planning_hash, reader_hash = _register_longform_definitions(
        args.database_url, build_id=build_id, commit_sha=commit_sha
    )
    planning_profile = build_story_planning_pack_profile(
        ROOT, operation_definition_hash=planning_hash, pack_id=PLANNING_PACK_ID
    )
    reader_profile = build_reader_outcome_pack_profile(
        ROOT, operation_definition_hash=reader_hash, pack_id=READER_PACK_ID
    )
    planning_pack = _install_profile(
        args.database_url,
        profile=planning_profile,
        version=PLANNING_PACK_INITIAL_VERSION,
        generation=1,
        expected_activation_version=0,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
        agent_domain="story_planning",
        agent_scope_type="BOOK",
    )
    reader_pack = _install_profile(
        args.database_url,
        profile=reader_profile,
        version="1.0.0",
        generation=1,
        expected_activation_version=0,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
        agent_domain="reader_outcome",
        agent_scope_type="CHAPTER",
    )
    execution = build_production_execution_composition(settings, env=env)
    chapter = build_chapter_authority_application(
        settings, execution=execution, env=env
    )
    chapter_pack = _install_pack(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
    )
    _planning, activated, projections, retry = _run_planning(
        database_url=args.database_url,
        settings=settings,
        env=env,
        execution=execution,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        book_design_version=str(book["active_book_design_version_id"]),
        bootstrap=bootstrap,
        principal=operator,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
        planning_profile=planning_profile,
        build_id=build_id,
        commit_sha=commit_sha,
        initial_chapter_group_end=6,
    )
    state = {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_id": book_id,
        "bootstrap": bootstrap,
        "chapter_profiles": chapter_profiles,
        "activated_plans": activated,
        "chapter_plan_projections": projections,
        "planning_retry": retry,
        "packs": {
            "planning": planning_pack,
            "reader": reader_pack,
            "chapter": chapter_pack,
        },
    }
    return state, execution, chapter, operator


def _resume_campaign(
    args: argparse.Namespace,
    *,
    settings: IndustrialSettings,
    env: dict[str, str],
    checkpoint: Mapping[str, Any],
) -> tuple[dict[str, Any], Any, Any, Any]:
    authority = dict(checkpoint["authority"])
    project_id = str(authority["project_id"])
    execution = build_production_execution_composition(settings, env=env)
    chapter = build_chapter_authority_application(
        settings, execution=execution, env=env
    )
    return dict(authority), execution, chapter, _operator(project_id)


def _start_or_require_book(
    args: argparse.Namespace,
    *,
    state: dict[str, Any],
    composition: Any,
    operator: Any,
) -> str:
    existing = _query_rows(
        args.database_url,
        """
        SELECT book_run_id FROM authority_book_production
        WHERE project_id=%s AND book_id=%s
        """,
        (state["project_id"], state["book_id"]),
    )
    if len(existing) > 1:
        raise RuntimeError("Campaign found multiple Book production runs")
    if existing:
        return str(existing[0]["book_run_id"])
    book = BookDesignAuthorityQuery(args.database_url).require_book(
        project_id=state["project_id"], book_id=state["book_id"]
    )
    snapshot = composition.input_resolver.resolve(
        ResolveBookProductionInputCommand(
            project_id=state["project_id"],
            workspace_id=state["workspace_id"],
            book_id=state["book_id"],
            production_profile=state["bootstrap"]["production_profile"],
            expected_book_version=int(book["version"]),
            actor_id=operator.principal_id,
            idempotency_key=f"{state['project_id']}:book-input:initial",
            trace_id=f"trace:{state['project_id']}:book-input:initial",
            correlation_id=f"correlation:{state['project_id']}",
        ),
        principal=operator,
    )
    admission = composition.authority.start(
        StartBookProductionCommand(
            project_id=state["project_id"],
            workspace_id=state["workspace_id"],
            book_id=state["book_id"],
            actor_id=operator.principal_id,
            trace_id=f"trace:{state['project_id']}:book-production",
            correlation_id=f"correlation:{state['project_id']}",
            stable_idempotency_key=f"{state['project_id']}:book-production",
            book_design_version=snapshot.book_design_version,
            book_plan_version=snapshot.book_plan_version,
            production_profile_version=snapshot.production_profile_version,
            longform_context_versions={
                "volume_plan_version": snapshot.current_volume_plan_version,
                "arc_plan_version": snapshot.active_arc_plan_versions[0],
                "character_state_version": snapshot.character_state_version,
                "foreshadowing_state_version": snapshot.foreshadowing_state_version,
                "quality_trend_version": snapshot.quality_trend_version,
                "reward_ledger_version": snapshot.reward_ledger_version,
                "promise_ledger_version": snapshot.promise_ledger_version,
                "reader_segment_version": snapshot.reader_segment_version,
                "reader_contract_version": snapshot.reader_contract_version,
                "platform_profile_version": snapshot.platform_profile_version,
            },
            target_chapter_count=300,
            light_recap_cadence=10,
            formal_recap_cadence=30,
            input_snapshot_id=snapshot.snapshot_id,
            input_mode="RESOLVED_AUTHORITY_INPUT",
        ),
        principal=operator,
    )
    return str(admission.book_run_id)


def _export_chapter(
    *,
    authority: Any,
    project_id: str,
    request: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    evidence = authority.chapter_port.require_acceptance_evidence(
        project_id=project_id,
        root_operation_id=str(request["chapter_root_operation_id"]),
    )
    outputs = _chapter_outputs(evidence)
    draft = outputs.get("draft_version")
    if draft is None:
        raise RuntimeError("accepted Chapter export has no draft_version")
    content = draft.get("content")
    if not isinstance(content, Mapping):
        raise RuntimeError("accepted Chapter export content is invalid")
    text = str(content.get("text") or "").strip()
    if not text:
        raise RuntimeError("accepted Chapter export prose is empty")
    chapter_number = int(request["chapter_number"])
    path = output_root / "novel" / "chapters" / f"chapter-{chapter_number:04d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return {
        "chapter": chapter_number,
        "path": str(path),
        "characters": len(text),
        "draft_asset_version_id": draft["asset_version_id"],
        "draft_content_hash": draft["content_hash"],
    }


def _collect_measurements(
    database_url: str, *, project_id: str, book_run_id: str
) -> dict[str, Any]:
    queries = {
        "operations": "SELECT COUNT(*) AS count FROM authority_operation WHERE project_id=%s",
        "attempts": """
            SELECT COUNT(*) AS count FROM authority_attempt AS attempt
            JOIN authority_operation AS operation
              ON operation.operation_id=attempt.operation_id
            WHERE operation.project_id=%s
        """,
        "provider_receipts": """
            SELECT COUNT(*) AS count FROM authority_external_receipt AS receipt
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.dispatch_id=receipt.dispatch_id
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id=dispatch.external_effect_id
            JOIN authority_operation AS operation
              ON operation.operation_id=effect.operation_id
            WHERE operation.project_id=%s
        """,
        "model_call_logs": """
            SELECT COUNT(*) AS count FROM authority_asset AS asset
            WHERE asset.project_id=%s AND asset.asset_type='model_call_log'
        """,
        "cost_ledgers": """
            SELECT COUNT(*) AS count FROM authority_asset AS asset
            WHERE asset.project_id=%s AND asset.asset_type='cost_ledger'
        """,
        "context_manifests": """
            SELECT COUNT(*) AS count
            FROM authority_asset AS asset
            JOIN authority_asset_version AS version
              ON version.asset_id=asset.asset_id
            WHERE asset.project_id=%s
              AND asset.asset_type='context_bundle'
              AND version.content->'context_manifest'->>'contract_version'
                    ='narrative-context-manifest-v1'
        """,
    }
    result = {
        name: int(_query_rows(database_url, sql, (project_id,))[0]["count"])
        for name, sql in queries.items()
    }
    chapter_rows = _query_rows(
        database_url,
        """
        SELECT request.chapter_number, COUNT(acceptance.acceptance_id) AS accepted
        FROM authority_book_chapter_request AS request
        LEFT JOIN authority_book_chapter_acceptance AS acceptance
          ON acceptance.chapter_request_id=request.chapter_request_id
         AND acceptance.status='COMMITTED'
        WHERE request.book_run_id=%s
        GROUP BY request.chapter_number ORDER BY request.chapter_number
        """,
        (book_run_id,),
    )
    result["chapter_rows"] = chapter_rows
    result["duplicate_logical_chapters"] = sum(
        1 for row in chapter_rows if int(row["accepted"]) != 1
    )
    return result


def _write_combined_novel(output_root: Path, *, through: int, title: str) -> Path:
    parts = [f"# {title}\n"]
    for chapter in range(1, through + 1):
        path = output_root / "novel" / "chapters" / f"chapter-{chapter:04d}.md"
        if not path.is_file():
            raise RuntimeError(f"combined novel export missing Chapter {chapter}")
        parts.append(path.read_text(encoding="utf-8").strip())
    target = output_root / "novel" / f"complete-through-{through:04d}.md"
    target.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return target


def _run(args: argparse.Namespace) -> dict[str, Any]:
    target = _validate_target(args.target_chapter)
    checkout = _release_checkout(allow_dirty=args.allow_dirty)
    commit_sha = checkout["commit_sha"]
    contract = load_campaign_contract(args.contract)
    identity = contract_identity(contract)
    contract_payload = contract.to_dict()
    contract_payload["contract_identity"] = identity
    _validate_frozen_provider_policy(
        contract_payload["provider"],
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        quality_context_token_budget=args.quality_context_token_budget,
    )
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_root / "campaign-checkpoint.json"
    previous: dict[str, Any] | None = None
    if checkpoint_path.is_file():
        previous = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        _validate_resume_checkpoint(
            previous,
            contract_identity=identity,
            commit_sha=commit_sha,
            target_chapter=target,
        )
    process_root = output_root / "runtime" / f"process-{os.getpid()}-{uuid4().hex[:8]}"
    buckets = (
        dict(previous["runtime"]["minio_buckets"])
        if previous is not None
        else _proof_bucket_names(output_root)
    )
    settings, env, login_status = _runtime_settings(
        args,
        runtime_root=process_root,
        commit_sha=commit_sha,
        buckets=buckets,
        provider=contract_payload["provider"],
    )
    migration = run_migrations(args.database_url)
    MinioObjectStore(settings).ensure_buckets()
    if previous is None:
        state, execution, chapter, operator = _initialise_campaign(
            args,
            settings=settings,
            env=env,
            contract_payload=contract_payload,
            commit_sha=commit_sha,
        )
    else:
        state, execution, chapter, operator = _resume_campaign(
            args, settings=settings, env=env, checkpoint=previous
        )
    composition_env = {
        **env,
        "NOVEL_FORGE_BOOK_QUALITY_CONTEXT_TOKEN_BUDGET": str(
            args.quality_context_token_budget
        ),
    }
    composition = build_book_production_composition(
        settings,
        principal=operator,
        execution=execution,
        env=composition_env,
        chapter_application=chapter,
    )
    book_run_id = _start_or_require_book(
        args, state=state, composition=composition, operator=operator
    )
    worker = _principal(
        env["NOVEL_FORGE_AUTHORITY_WORKER_ID"],
        state["project_id"],
        "chapter.authority.execute",
        worker=True,
    )
    chapter_exports = list((previous or {}).get("chapter_exports") or [])
    failures = list((previous or {}).get("failures") or [])
    supervisor_ticks: list[dict[str, Any]] = []
    try:
        accepted = int(
            composition.authority.require(book_run_id)["accepted_through_chapter"]
        )
        for chapter_number in range(accepted + 1, target + 1):
            request, ticks = _drive_to_chapter_dispatch(
                composition.supervisor,
                book_run_id=book_run_id,
                chapter_number=chapter_number,
                approve_replan=lambda replan_id: composition.replan.approve(
                    replan_id,
                    authority_type="PLAN_CHANGE_AUTHORITY",
                    authority_version="longform-proof-operator-approval-v1",
                    evidence={
                        "campaign_contract_identity": identity,
                        "future_only": True,
                        "human_behavior_claimed": False,
                        "quality_calibration_claimed": False,
                    },
                ),
            )
            supervisor_ticks.extend(ticks)
            _run_chapter_scheduler(
                chapter,
                database_url=args.database_url,
                project_id=state["project_id"],
                root_operation_id=str(request["chapter_root_operation_id"]),
                operator=operator,
                worker=worker,
                commit_sha=commit_sha,
            )
            supervisor_ticks.append(
                _accept_chapter(
                    composition.supervisor,
                    book_run_id=book_run_id,
                    chapter_number=chapter_number,
                )
            )
            _reader, reader_ticks = _complete_reader_sidecar(
                composition.supervisor,
                database_url=args.database_url,
                project_id=state["project_id"],
                book_run_id=book_run_id,
                chapter_request_id=str(request["chapter_request_id"]),
            )
            supervisor_ticks.extend(reader_ticks)
            chapter_exports.append(
                _export_chapter(
                    authority=composition.authority,
                    project_id=state["project_id"],
                    request=request,
                    output_root=output_root,
                )
            )
            partial = {
                "schema_version": SCHEMA_VERSION,
                "created_at": datetime.now().astimezone().isoformat(),
                "contract_identity": identity,
                "release": {
                    "branch": checkout["branch"],
                    "commit_sha": commit_sha,
                    "worktree_clean": not bool(checkout["dirty"]),
                },
                "runtime": {
                    "provider": "codex-cli",
                    "model": args.model,
                    "reasoning_effort": args.reasoning_effort,
                    "codex_login_status": login_status,
                    "codex_version": _codex_version(args.codex_executable),
                    "minio_buckets": buckets,
                    "process_root": str(process_root),
                    "migration": migration,
                },
                "authority": {**state, "book_run_id": book_run_id},
                "accepted_through_chapter": chapter_number,
                "requested_target_chapter": target,
                "chapter_exports": chapter_exports,
                "failures": failures,
                "last_supervisor_ticks": supervisor_ticks[-50:],
                "status": "RUNNING" if chapter_number < target else "CHECKPOINT_REACHED",
            }
            _write_json(checkpoint_path, partial)
        book = composition.authority.require(book_run_id)
        through = int(book["accepted_through_chapter"])
        combined = _write_combined_novel(
            output_root,
            through=through,
            title=str(contract_payload["book"]["title"]),
        )
        measurements = _collect_measurements(
            args.database_url,
            project_id=state["project_id"],
            book_run_id=book_run_id,
        )
        result = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        result.update(
            {
                "status": "CHECKPOINT_REACHED",
                "book_state": book["state"],
                "combined_novel": str(combined),
                "measurements": measurements,
                "proof_verdict": (
                    "NOT_EVALUATED"
                    if target == 1
                    else "PENDING_DEDICATED_VALIDATION"
                ),
            }
        )
        _write_json(checkpoint_path, result)
        _write_json(
            output_root / "evidence" / f"checkpoint-{through:04d}.json", result
        )
        return result
    except BaseException as exc:
        failure = {
            "created_at": datetime.now().astimezone().isoformat(),
            "category": _classify_failure(exc),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "accepted_through_chapter": int(
                composition.authority.require(book_run_id)[
                    "accepted_through_chapter"
                ]
            ),
        }
        failures.append(failure)
        failed = {
            **(previous or {}),
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now().astimezone().isoformat(),
            "contract_identity": identity,
            "release": {
                "branch": checkout["branch"],
                "commit_sha": commit_sha,
                "worktree_clean": not bool(checkout["dirty"]),
            },
            "runtime": {
                "provider": "codex-cli",
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
                "codex_login_status": login_status,
                "minio_buckets": buckets,
                "process_root": str(process_root),
                "migration": migration,
            },
            "authority": {**state, "book_run_id": book_run_id},
            "accepted_through_chapter": failure["accepted_through_chapter"],
            "requested_target_chapter": target,
            "chapter_exports": chapter_exports,
            "failures": failures,
            "status": "FAILED",
        }
        _write_json(checkpoint_path, failed)
        raise
    finally:
        execution.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--contract",
        default=str(
            ROOT / "config" / "proof_campaigns" / "longform_narrative_v1.json"
        ),
    )
    parser.add_argument("--target-chapter", type=int, required=True)
    parser.add_argument(
        "--codex-executable",
        default="/Applications/ChatGPT.app/Contents/Resources/codex",
    )
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument(
        "--quality-context-token-budget",
        type=int,
        default=PROOF_QUALITY_CONTEXT_TOKEN_BUDGET,
    )
    parser.add_argument("--provider-cost-cap", type=float, default=10_000.0)
    parser.add_argument("--minio-endpoint", default="127.0.0.1:59039")
    parser.add_argument("--minio-access-key", default="novel_forge")
    parser.add_argument("--minio-secret-key", default="novel_forge_secret")
    parser.add_argument("--minio-secure", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    try:
        result = _run(args)
    except BaseException as exc:
        output_root = Path(args.output_root).expanduser().resolve()
        failure_path = _record_process_failure(
            output_root,
            exc,
            context={
                "phase": "PROCESS",
                "target_chapter": args.target_chapter,
            },
        )
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "category": _classify_failure(exc),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "failure_history": str(failure_path),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "accepted_through_chapter": result["accepted_through_chapter"],
                "checkpoint": str(
                    Path(args.output_root).expanduser().resolve()
                    / "campaign-checkpoint.json"
                ),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
