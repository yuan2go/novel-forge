#!/usr/bin/env python3
"""Operate the exact 4+4 bounded Quality Qualification campaign.

The script coordinates existing PostgreSQL Authorities.  It never creates a
second Canon, plan, Chapter, Reader, or human-preference persistence plane.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_quality_authority import (
    PostgresQualityQualificationAuthority,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.provider_control import normalize_provider_id
from novel_forge.modules.reader_calibration import (
    BlindScope,
    EvaluatorIdentityClass,
    HumanBlindDecision,
    PreferenceChoice,
)
from novel_forge.modules.runtime_proof import (
    BoundedQualityCampaignPreparer,
    BoundedQualityCampaignRunner,
    HumanReviewerTarget,
    PostgresBoundedQualityCampaignRuntime,
    QualityCampaignTerminalError,
    bounded_quality_chapter_fixture_response,
    bounded_quality_planning_fixture_response,
    load_quality_book_contract,
    load_quality_campaign_profile,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import (
    LATEST_MIGRATION_ID,
    get_migration_status,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "config/proof_campaigns/quality_qualification_v1.json"
DEFAULT_BOOK_CONTRACT = (
    ROOT / "config/proof_campaigns/quality_qualification_book_v1.json"
)
STATE_SCHEMA = "novel-forge.bounded-quality-runtime-state.v1"
RESULT_SCHEMA = "novel-forge.bounded-quality-campaign-result.v1"
_REQUIRED_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "project_id",
        "workspace_id",
        "book_id",
        "book_run_id",
        "primary_arc_plan_version_id",
        "volume_scope_id",
        "exact_release_sha",
        "migration_head",
        "capability_pack_manifest",
        "foundation_lineage",
        "planning_lineage",
        "realization_lineage",
        "reviewers",
        "runtime_env",
    }
)
_BASE_PERMISSIONS = frozenset(
    {
        "story_planning.authority.execute",
        "story_planning.authority.approve",
        "story_planning.authority.activate",
        "story_design.authority.execute",
        "narrative_design.evaluate",
        "book.authority.execute",
        "book.authority.approve_replan",
        "book_design.authority.execute",
        "book_design.authority.query",
        "book.followup:*",
        "chapter.authority.execute",
        "external_effect.execute",
        "quality.qualification.manage",
        "quality.qualification.query",
    }
)
_RUNTIME_ROLE_STAGES = {
    "generator": ("draft", "revision"),
    "reviewer": (
        "review",
        "rereview",
        "canon_extraction",
        "narrative_semantic_evaluation",
    ),
    "judge": (
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
    ),
    "reader_proxy": ("reader_outcome",),
}
_PACK_RUNTIME_BINDINGS = {
    "planning": ("NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID", "story_planning_pack"),
    "chapter": ("NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID", "chapter_generation_pack"),
    "reader_proxy": (
        "NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID",
        "reader_outcome_pack",
    ),
    "narrative_evaluation": (
        "NOVEL_FORGE_NARRATIVE_EVALUATION_CAPABILITY_PACK_ID",
        "narrative_semantic_evaluation_pack",
    ),
}
_STAGE_ROUTE_ENVIRONMENT_KEYS = {
    "draft": ("NOVEL_FORGE_DRAFT_PROVIDER", "NOVEL_FORGE_DRAFT_MODEL"),
    "review": ("NOVEL_FORGE_REVIEW_PROVIDER", "NOVEL_FORGE_REVIEW_MODEL"),
    "revision": ("NOVEL_FORGE_REVISION_PROVIDER", "NOVEL_FORGE_REVISION_MODEL"),
    "rereview": ("NOVEL_FORGE_REREVIEW_PROVIDER", "NOVEL_FORGE_REREVIEW_MODEL"),
    "canon_extraction": (
        "NOVEL_FORGE_CANON_EXTRACTION_PROVIDER",
        "NOVEL_FORGE_CANON_EXTRACTION_MODEL",
    ),
    "quality_structural": ("NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
    "quality_commercial": ("NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
    "quality_source_originality": (
        "NOVEL_FORGE_QUALITY_PROVIDER",
        "NOVEL_FORGE_QUALITY_MODEL",
    ),
    "quality_longform": ("NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
    "quality_platform": ("NOVEL_FORGE_QUALITY_PROVIDER", "NOVEL_FORGE_QUALITY_MODEL"),
    "reader_outcome": (
        "NOVEL_FORGE_READER_OUTCOME_PROVIDER",
        "NOVEL_FORGE_READER_OUTCOME_MODEL",
    ),
    "narrative_semantic_evaluation": (
        "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER",
        "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL",
    ),
}


def _json_file(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: str | Path, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as stream:
        stream.write(encoded)
        temporary = Path(stream.name)
    temporary.replace(target)
    return target


def _repository_state(*, allow_dirty: bool) -> dict[str, Any]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty_rows = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if dirty_rows and not allow_dirty:
        raise RuntimeError("exact-SHA Quality operation requires a clean worktree")
    return {"commit_sha": sha, "branch": branch, "dirty": bool(dirty_rows)}


def _state(path: str | Path) -> dict[str, Any]:
    return _validate_state_document(_json_file(path))


def _validate_state_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    raw = {str(key): value for key, value in raw.items()}
    missing = sorted(_REQUIRED_STATE_FIELDS - frozenset(raw))
    if missing:
        raise ValueError("runtime state lacks: " + ", ".join(missing))
    if raw["schema_version"] != STATE_SCHEMA:
        raise ValueError("unsupported bounded Quality runtime state")
    release_sha = str(raw["exact_release_sha"]).lower()
    if (
        len(release_sha) != 40
        or any(character not in "0123456789abcdef" for character in release_sha)
        or raw["migration_head"] != LATEST_MIGRATION_ID
        or not isinstance(raw["runtime_env"], dict)
    ):
        raise ValueError("runtime state release or migration identity is invalid")
    forbidden_runtime_keys = sorted(
        str(key)
        for key in raw["runtime_env"]
        if any(
            marker in str(key).upper()
            for marker in ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "CREDENTIAL")
        )
    )
    if forbidden_runtime_keys:
        raise ValueError(
            "runtime state must not persist credentials: "
            + ", ".join(forbidden_runtime_keys)
        )
    reviewers = raw["reviewers"]
    if (
        not isinstance(reviewers, list)
        or len(reviewers) != 2
        or any(not isinstance(item, Mapping) for item in reviewers)
        or len({str(item.get("reviewer_id") or "") for item in reviewers}) != 2
        or any(not str(item.get("reviewer_id") or "") for item in reviewers)
        or any(not str(item.get("identity_class") or "") for item in reviewers)
    ):
        raise ValueError("runtime state requires two independent reviewer targets")
    return raw


def _principal(project_id: str, *, worker: bool = False) -> Principal:
    return Principal(
        principal_id=(
            f"bounded-quality-worker:{project_id}"
            if worker
            else f"bounded-quality-operator:{project_id}"
        ),
        principal_type=(
            PrincipalType.WORKER if worker else PrincipalType.LOCAL_OPERATOR
        ),
        permissions=frozenset(
            permission
            for permission in _BASE_PERMISSIONS
            if not worker or permission != "book.authority.approve_replan"
        ),
        project_scope=frozenset({project_id}),
        authentication_source="bounded-quality-qualification-cli",
    )


def _quality(
    database_url: str,
    state: Mapping[str, Any],
) -> PostgresQualityQualificationAuthority:
    return PostgresQualityQualificationAuthority(
        database_url,
        application_build_id="bounded-quality-qualification-cli",
        commit_sha=str(state["exact_release_sha"]),
    )


def _verify_release_and_migration(
    database_url: str,
    state: Mapping[str, Any],
    *,
    allow_dirty: bool,
) -> dict[str, Any]:
    repository = _repository_state(allow_dirty=allow_dirty)
    if repository["commit_sha"] != state["exact_release_sha"]:
        raise RuntimeError("runtime state belongs to another exact repository SHA")
    migration = get_migration_status(database_url)
    if not migration["ok"] or migration["current"] != state["migration_head"]:
        raise RuntimeError("database migration head differs from the frozen campaign")
    return {"repository": repository, "migration": migration}


def _reviewer_targets(values: list[str]) -> list[dict[str, str]]:
    if len(values) != 2:
        raise ValueError("capture-real-state requires exactly two reviewers")
    reviewers: list[dict[str, str]] = []
    for value in values:
        reviewer_id, separator, identity_class = value.rpartition(":")
        if not separator or not reviewer_id.strip() or not identity_class.strip():
            raise ValueError("reviewer must use REVIEWER_ID:EVALUATOR_IDENTITY_CLASS")
        try:
            parsed_class = EvaluatorIdentityClass(identity_class.strip())
        except ValueError as exc:
            raise ValueError(
                f"unsupported evaluator identity class: {identity_class}"
            ) from exc
        reviewers.append(
            {
                "reviewer_id": reviewer_id.strip(),
                "identity_class": parsed_class.value,
            }
        )
    if len({item["reviewer_id"] for item in reviewers}) != 2:
        raise ValueError("capture-real-state requires two independent reviewers")
    return reviewers


def _selected_pack_binding(
    database_url: str,
    *,
    pack_id: str,
    environment: str,
    project_id: str,
    workspace_id: str,
    book_id: str,
    release_sha: str,
) -> dict[str, str]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT activation.active_deployment_id, version.manifest_hash,
                   deployment.pack_id, deployment.deployment_status,
                   deployment.environment, compilation.runtime_profile,
                   compilation.release_channel, compilation.release_sha,
                   deployment.project_id, deployment.workspace_id,
                   deployment.book_id
            FROM authority_capability_pack_activation AS activation
            JOIN authority_capability_pack_deployment AS deployment
              ON deployment.deployment_id=activation.active_deployment_id
            JOIN authority_capability_pack_version AS version
              ON version.pack_id=deployment.pack_id
             AND version.pack_version=deployment.pack_version
            JOIN authority_capability_pack_compilation AS compilation
              ON compilation.compilation_id=deployment.compilation_id
            WHERE activation.pack_id=%s
              AND activation.environment=%s
              AND (
                   activation.target_scope_type='SYSTEM'
                   OR (
                       activation.target_scope_type='PROJECT'
                       AND activation.project_id=%s
                   )
                   OR (
                       activation.target_scope_type='WORKSPACE'
                       AND activation.project_id=%s
                       AND activation.workspace_id=%s
                   )
                   OR (
                       activation.target_scope_type='BOOK'
                       AND activation.project_id=%s
                       AND activation.workspace_id=%s
                       AND activation.book_id=%s
                   )
              )
            ORDER BY CASE activation.target_scope_type
                       WHEN 'BOOK' THEN 4
                       WHEN 'WORKSPACE' THEN 3
                       WHEN 'PROJECT' THEN 2
                       ELSE 1
                     END DESC
            LIMIT 1
            """,
            [
                pack_id,
                environment,
                project_id,
                project_id,
                workspace_id,
                project_id,
                workspace_id,
                book_id,
            ],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise RuntimeError(f"no selected Capability Pack activation for {pack_id}")
    if (
        str(row[2]) != pack_id
        or str(row[3]) != "ACTIVE"
        or str(row[4]) != environment
        or str(row[5]) != environment
        or str(row[6]) != "VALIDATION"
        or str(row[7]) != release_sha
        or (row[8] is not None and str(row[8]) != project_id)
        or (row[9] is not None and str(row[9]) != workspace_id)
        or (row[10] is not None and str(row[10]) != book_id)
    ):
        raise RuntimeError(f"selected Capability Pack lineage drifted for {pack_id}")
    return {
        "pack_id": pack_id,
        "deployment_id": str(row[0]),
        "hash": str(row[1]),
    }


def _capture_real_state(args: argparse.Namespace) -> dict[str, Any]:
    repository = _repository_state(allow_dirty=False)
    migration = get_migration_status(args.database_url)
    if not migration["ok"] or migration["current"] != LATEST_MIGRATION_ID:
        raise RuntimeError("capture-real-state requires the current migration head")
    profile = load_quality_campaign_profile(args.profile, repository_root=ROOT)
    raw_runtime_env = _json_file(args.runtime_env)
    if any(isinstance(value, (dict, list)) for value in raw_runtime_env.values()):
        raise ValueError("runtime environment values must be scalar")
    runtime_env = {str(key): str(value) for key, value in raw_runtime_env.items()}
    provisional = {
        "exact_release_sha": repository["commit_sha"],
        "runtime_env": runtime_env,
    }
    effective_env = _runtime_env(provisional, mode="real", profile=profile)
    _verify_runtime_routes(profile, effective_env, mode="real")

    with AuthorityUnitOfWork(args.database_url) as uow:
        uow.cursor.execute(
            """
            SELECT project_id,workspace_id,book_id,input_snapshot_id,
                   target_chapter_count,accepted_through_chapter,
                   light_recap_cadence,formal_recap_cadence,input_mode
            FROM authority_book_production
            WHERE book_run_id=%s
            """,
            [args.book_run_id],
        )
        book_run = uow.cursor.fetchone()
        if book_run is None:
            raise RuntimeError("bounded Book run is missing")
        project_id, workspace_id, book_id = (str(item) for item in book_run[:3])
        if (
            int(book_run[4]) != 8
            or int(book_run[5]) != 0
            or int(book_run[6]) != 4
            or int(book_run[7]) != 8
            or str(book_run[8]) != "RESOLVED_AUTHORITY_INPUT"
        ):
            raise RuntimeError(
                "bounded Book run must be an unstarted 4+4 resolved-input run"
            )
        uow.cursor.execute(
            """
            SELECT release_sha,book_design_version,book_plan_version,
                   current_volume_plan_version,arc_portfolio_plan_versions
            FROM authority_book_production_input_snapshot
            WHERE snapshot_id=%s AND project_id=%s AND workspace_id=%s
              AND book_id=%s
            """,
            [str(book_run[3]), project_id, workspace_id, book_id],
        )
        snapshot = uow.cursor.fetchone()
        if snapshot is None or str(snapshot[0]) != repository["commit_sha"]:
            raise RuntimeError(
                "Book input snapshot is missing or belongs to another SHA"
            )
        arc_versions = tuple(str(item) for item in snapshot[4])
        if not arc_versions:
            raise RuntimeError("bounded campaign requires an active Arc plan")
        primary_arc = str(args.primary_arc_plan_version_id or arc_versions[0])
        if primary_arc not in arc_versions:
            raise RuntimeError("primary Arc is outside the frozen Planning snapshot")
        uow.cursor.execute(
            """
            SELECT binding.formation_run_id,binding.set_generation,
                   COUNT(*),MIN(run.foundation_set_digest),
                   MIN(run.book_design_asset_version_id),
                   MIN(run.book_design_content_hash),MIN(run.lifecycle)
            FROM authority_book_foundation_binding AS binding
            JOIN authority_story_formation_run AS run
              ON run.formation_run_id=binding.formation_run_id
            WHERE binding.project_id=%s AND binding.book_id=%s
              AND binding.freshness='CURRENT' AND binding.retired_at IS NULL
            GROUP BY binding.formation_run_id,binding.set_generation
            """,
            [project_id, book_id],
        )
        foundation_rows = uow.cursor.fetchall()
        if len(foundation_rows) != 1:
            raise RuntimeError("Book does not have one current Foundation set")
        foundation = foundation_rows[0]
        if (
            int(foundation[2]) != 6
            or str(foundation[6]) != "READY"
            or str(foundation[4]) != str(snapshot[1])
        ):
            raise RuntimeError("Foundation set is incomplete or not Formation-ready")
        uow.cursor.execute(
            """
            SELECT version FROM authority_book
            WHERE project_id=%s AND book_id=%s
            """,
            [project_id, book_id],
        )
        book_row = uow.cursor.fetchone()
        if book_row is None:
            raise RuntimeError("Book Authority root is missing")

    pack_manifest: dict[str, dict[str, str]] = {}
    for role, (environment_key, default_pack_id) in _PACK_RUNTIME_BINDINGS.items():
        pack_id = str(effective_env.get(environment_key) or default_pack_id)
        pack_manifest[role] = _selected_pack_binding(
            args.database_url,
            pack_id=pack_id,
            environment="validation",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            release_sha=repository["commit_sha"],
        )

    state: dict[str, Any] = {
        "schema_version": STATE_SCHEMA,
        "campaign_id": args.campaign_id,
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_id": book_id,
        "book_run_id": args.book_run_id,
        "primary_arc_plan_version_id": primary_arc,
        "volume_scope_id": profile.to_dict()["book"]["bounded_volume_scope"],
        "exact_release_sha": repository["commit_sha"],
        "migration_head": LATEST_MIGRATION_ID,
        "capability_pack_manifest": pack_manifest,
        "foundation_lineage": {
            "foundation_set_digest": str(foundation[3]),
            "story_formation_run_id": str(foundation[0]),
            "foundation_set_generation": int(foundation[1]),
            "book_design_asset_version_id": str(foundation[4]),
            "book_design_content_hash": str(foundation[5]),
            "book_version": int(book_row[0]),
            "source_classification": "FROZEN_AUTHORITY_INPUT_NOT_QUALITY_EVIDENCE",
        },
        "planning_lineage": {
            "input_snapshot_id": str(book_run[3]),
            "book_plan_asset_version_id": str(snapshot[2]),
            "volume_plan_asset_version_id": str(snapshot[3]),
            "arc_plan_asset_version_ids": list(arc_versions),
        },
        "realization_lineage": {
            "contract": "narrative-realization-v1",
            "expected_chapter_group_ranges": [[1, 4], [5, 8]],
            "binding_policy": "QUALIFICATION_FROZEN_BEFORE_EXECUTION",
        },
        "reviewers": _reviewer_targets(args.reviewer),
        "runtime_env": runtime_env,
    }
    captured = _validate_state_document(state)
    _verify_runtime_pack_ids(captured, effective_env, mode="real")
    _verify_freeze_lineage(
        args.database_url,
        captured,
        mode="real",
        values=effective_env,
    )
    state_path = _write_json(args.output, captured)
    return {
        "status": "CAPTURED",
        "state_path": str(state_path),
        "state": captured,
        "repository": repository,
        "migration": migration,
    }


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    allow_dirty = bool(args.allow_dirty and args.mode == "scripted")
    repository = _repository_state(allow_dirty=allow_dirty)
    migration = get_migration_status(args.database_url)
    if not migration["ok"] or migration["current"] != LATEST_MIGRATION_ID:
        raise RuntimeError(
            "bounded Quality preparation requires the current migration head"
        )
    profile = load_quality_campaign_profile(args.profile, repository_root=ROOT)
    book_contract = load_quality_book_contract(
        args.book_contract,
        campaign_profile=profile,
    )
    raw_runtime_env = _json_file(args.runtime_env)
    if any(isinstance(value, (dict, list)) for value in raw_runtime_env.values()):
        raise ValueError("runtime environment values must be scalar")
    runtime_env = {str(key): str(value) for key, value in raw_runtime_env.items()}
    settings_values = {
        **{str(key): str(value) for key, value in os.environ.items()},
        **runtime_env,
        "NOVEL_FORGE_ROOT": str(ROOT),
        "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql",
        "NOVEL_FORGE_DATABASE_URL": args.database_url,
        "NOVEL_FORGE_ENVIRONMENT": (
            "test" if args.mode == "scripted" else "validation"
        ),
    }
    settings = IndustrialSettings.from_env(settings_values, root=ROOT)
    prepared = BoundedQualityCampaignPreparer(
        database_url=args.database_url,
        repository_root=ROOT,
        settings=settings,
        runtime_env=runtime_env,
        profile=profile,
        book_contract=book_contract,
        campaign_id=args.campaign_id,
        exact_release_sha=repository["commit_sha"],
        mode=args.mode,
    ).prepare()
    planning = dict(prepared.planning_lineage)
    arc_versions = list(planning["arc_plan_asset_version_ids"])
    if not arc_versions:
        raise RuntimeError("prepared bounded Book has no Arc plan")
    foundation = {
        **dict(prepared.foundation_lineage),
        "story_formation_run_id": prepared.foundation_lineage["formation_run_id"],
        "source_classification": "FROZEN_AUTHORITY_INPUT_NOT_QUALITY_EVIDENCE",
    }
    safe_runtime_env = {
        key: value
        for key, value in prepared.runtime_env.items()
        if key != "NOVEL_FORGE_DATABASE_URL"
    }
    state = _validate_state_document(
        {
            "schema_version": STATE_SCHEMA,
            "campaign_id": args.campaign_id,
            "project_id": prepared.project_id,
            "workspace_id": prepared.workspace_id,
            "book_id": prepared.book_id,
            "book_run_id": prepared.book_run_id,
            "primary_arc_plan_version_id": arc_versions[0],
            "volume_scope_id": profile.to_dict()["book"]["bounded_volume_scope"],
            "exact_release_sha": prepared.exact_release_sha,
            "migration_head": LATEST_MIGRATION_ID,
            "capability_pack_manifest": prepared.capability_pack_manifest,
            "foundation_lineage": foundation,
            "planning_lineage": planning,
            "realization_lineage": {
                "contract": "narrative-realization-v1",
                "expected_chapter_group_ranges": [[1, 4], [5, 8]],
                "binding_policy": "QUALIFICATION_FROZEN_BEFORE_EXECUTION",
            },
            "initial_state_lineage": prepared.initial_state_lineage,
            "reviewers": _reviewer_targets(args.reviewer),
            "runtime_env": safe_runtime_env,
        }
    )
    effective_env = _runtime_env(state, mode=args.mode, profile=profile)
    _verify_runtime_routes(profile, effective_env, mode=args.mode)
    _verify_runtime_pack_ids(state, effective_env, mode=args.mode)
    _verify_freeze_lineage(
        args.database_url,
        state,
        mode=args.mode,
        values=effective_env,
    )
    state_path = _write_json(args.output, state)
    return {
        "status": "PREPARED",
        "mode": args.mode,
        "state_path": str(state_path),
        "state": state,
        "repository": repository,
        "migration": migration,
    }


def _verify_freeze_lineage(
    database_url: str,
    state: Mapping[str, Any],
    *,
    mode: str,
    values: Mapping[str, str],
) -> None:
    planning = dict(state["planning_lineage"])
    snapshot_id = str(planning.get("input_snapshot_id") or "")
    if not snapshot_id:
        raise ValueError("planning lineage requires input_snapshot_id")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT project_id,workspace_id,book_id,release_sha,
                   book_design_version,book_plan_version,
                   current_volume_plan_version,arc_portfolio_plan_versions
            FROM authority_book_production_input_snapshot
            WHERE snapshot_id=%s
            """,
            [snapshot_id],
        )
        snapshot = uow.cursor.fetchone()
        if snapshot is None:
            raise RuntimeError("frozen Planning input snapshot is missing")
        expected = tuple(
            str(state[field])
            for field in (
                "project_id",
                "workspace_id",
                "book_id",
                "exact_release_sha",
            )
        )
        if tuple(str(item) for item in snapshot[:4]) != expected:
            raise RuntimeError("Planning input snapshot scope or release drifted")
        if (
            str(snapshot[4])
            != str(state["foundation_lineage"].get("book_design_asset_version_id"))
            or str(snapshot[5]) != str(planning.get("book_plan_asset_version_id"))
            or str(snapshot[6]) != str(planning.get("volume_plan_asset_version_id"))
            or tuple(str(item) for item in snapshot[7])
            != tuple(
                str(item) for item in planning.get("arc_plan_asset_version_ids") or ()
            )
        ):
            raise RuntimeError(
                "frozen Foundation/Planning lineage differs from Authority"
            )
        for role, raw in dict(state["capability_pack_manifest"]).items():
            binding = dict(raw)
            deployment_id = str(binding.get("deployment_id") or "")
            expected_hash = str(binding.get("hash") or "")
            if mode == "scripted" and deployment_id.startswith("scripted-unpacked:"):
                continue
            uow.cursor.execute(
                """
                SELECT deployment.pack_id, version.manifest_hash,
                       deployment.deployment_status, deployment.environment,
                       compilation.runtime_profile,
                       compilation.release_channel, compilation.release_sha,
                       deployment.workflow_definition_ref,
                       deployment.target_scope_type, deployment.project_id,
                       deployment.workspace_id, deployment.book_id
                FROM authority_capability_pack_deployment AS deployment
                JOIN authority_capability_pack_version AS version
                  ON version.pack_id=deployment.pack_id
                 AND version.pack_version=deployment.pack_version
                JOIN authority_capability_pack_compilation AS compilation
                  ON compilation.compilation_id=deployment.compilation_id
                WHERE deployment.deployment_id=%s
                """,
                [deployment_id],
            )
            pack = uow.cursor.fetchone()
            expected_pack_id = str(binding.get("pack_id") or "")
            if mode == "real" and not expected_pack_id:
                raise ValueError(f"real Capability Pack {role} lacks pack_id")
            if (
                pack is None
                or (expected_pack_id and str(pack[0]) != expected_pack_id)
                or str(pack[1]) != expected_hash
                or str(pack[2]) != "ACTIVE"
            ):
                raise RuntimeError(f"Capability Pack lineage drifted for {role}")
            if mode == "real":
                environment = str(values.get("NOVEL_FORGE_ENVIRONMENT") or "")
                release_channel = str(
                    values.get("NOVEL_FORGE_RELEASE_CHANNEL") or "VALIDATION"
                ).upper()
                if (
                    str(pack[3]) != environment
                    or str(pack[4]) != environment
                    or str(pack[5]) != release_channel
                    or str(pack[6]) != str(state["exact_release_sha"])
                    or (
                        pack[9] is not None and str(pack[9]) != str(state["project_id"])
                    )
                    or (
                        pack[10] is not None
                        and str(pack[10]) != str(state["workspace_id"])
                    )
                    or (pack[11] is not None and str(pack[11]) != str(state["book_id"]))
                ):
                    raise RuntimeError(
                        f"Capability Pack release or scope drifted for {role}"
                    )
                uow.cursor.execute(
                    """
                    SELECT activation.active_deployment_id
                    FROM authority_capability_pack_activation AS activation
                    WHERE activation.pack_id=%s
                      AND activation.environment=%s
                      AND activation.workflow_definition_ref=%s
                      AND (
                           activation.target_scope_type='SYSTEM'
                           OR (
                               activation.target_scope_type='PROJECT'
                               AND activation.project_id=%s
                           )
                           OR (
                               activation.target_scope_type='WORKSPACE'
                               AND activation.project_id=%s
                               AND activation.workspace_id=%s
                           )
                           OR (
                               activation.target_scope_type='BOOK'
                               AND activation.project_id=%s
                               AND activation.workspace_id=%s
                               AND activation.book_id=%s
                           )
                      )
                    ORDER BY CASE activation.target_scope_type
                               WHEN 'BOOK' THEN 4
                               WHEN 'WORKSPACE' THEN 3
                               WHEN 'PROJECT' THEN 2
                               ELSE 1
                             END DESC
                    LIMIT 1
                    """,
                    [
                        expected_pack_id,
                        environment,
                        str(pack[7]),
                        state["project_id"],
                        state["project_id"],
                        state["workspace_id"],
                        state["project_id"],
                        state["workspace_id"],
                        state["book_id"],
                    ],
                )
                selected = uow.cursor.fetchone()
                if selected is None or str(selected[0]) != deployment_id:
                    raise RuntimeError(
                        f"frozen Capability Pack is not the selected activation for {role}"
                    )
                uow.cursor.execute(
                    """
                    SELECT 1
                    FROM authority_capability_pack_rollout
                    WHERE baseline_deployment_id=%s
                      AND status IN ('OFF','CANARY','PERCENTAGE','FULL','PAUSED')
                    LIMIT 1
                    """,
                    [deployment_id],
                )
                if uow.cursor.fetchone() is not None:
                    raise RuntimeError(
                        f"Quality Qualification forbids Pack rollout drift for {role}"
                    )


def _effective_stage_binding(
    values: Mapping[str, str], stage: str
) -> tuple[str, str, str]:
    provider_key, model_key = _STAGE_ROUTE_ENVIRONMENT_KEYS[stage]
    provider_fallback = ""
    model_fallback = ""
    if stage == "rereview":
        provider_fallback = str(values.get("NOVEL_FORGE_REVIEW_PROVIDER") or "")
        model_fallback = str(values.get("NOVEL_FORGE_REVIEW_MODEL") or "")
    elif stage == "canon_extraction":
        provider_fallback = str(values.get("NOVEL_FORGE_REVISION_PROVIDER") or "")
        model_fallback = str(values.get("NOVEL_FORGE_REVISION_MODEL") or "")
    elif stage.startswith("quality_") or stage in {
        "reader_outcome",
        "narrative_semantic_evaluation",
    }:
        provider_fallback = str(values.get("NOVEL_FORGE_REVIEW_PROVIDER") or "")
        model_fallback = str(values.get("NOVEL_FORGE_REVIEW_MODEL") or "")
    provider = normalize_provider_id(
        str(
            values.get(provider_key)
            or provider_fallback
            or values.get("NOVEL_FORGE_MODEL_PROVIDER")
            or ""
        )
    )
    model = str(values.get(model_key) or model_fallback or "").strip()
    reasoning = (
        str(
            values.get(f"NOVEL_FORGE_{stage.upper()}_REASONING_EFFORT")
            or values.get("NOVEL_FORGE_REASONING_EFFORT")
            or "high"
        )
        .strip()
        .lower()
    )
    return provider, model, reasoning


def _verify_frozen_campaign_binding(
    campaign: Mapping[str, Any], state: Mapping[str, Any]
) -> None:
    scalar_fields = (
        "project_id",
        "workspace_id",
        "book_id",
        "exact_release_sha",
        "migration_head",
    )
    for field in scalar_fields:
        if str(campaign[field]) != str(state[field]):
            raise RuntimeError(f"frozen campaign {field} differs from runtime state")
    for field in (
        "capability_pack_manifest",
        "foundation_lineage",
        "planning_lineage",
        "realization_lineage",
    ):
        if dict(campaign[field]) != dict(state[field]):
            raise RuntimeError(f"frozen campaign {field} differs from runtime state")


def _verify_runtime_routes(
    profile: Any,
    values: Mapping[str, str],
    *,
    mode: str,
    frozen_route_manifest: Mapping[str, Any] | None = None,
) -> None:
    expected = profile.provider_routes[mode]
    if frozen_route_manifest is not None:
        frozen = dict(frozen_route_manifest)
        if (
            frozen.get("mode") != mode
            or frozen.get("campaign_profile_digest") != profile.digest
        ):
            raise RuntimeError("frozen campaign profile or Provider mode drifted")
        for role, binding in expected.items():
            if dict(frozen.get(role) or {}) != dict(binding):
                raise RuntimeError(f"frozen Provider route drifted for {role}")

    planning = expected["planning"]
    actual_planning = (
        normalize_provider_id(str(values.get("NOVEL_FORGE_PLANNING_PROVIDER") or "")),
        str(values.get("NOVEL_FORGE_PLANNING_MODEL") or "").strip(),
        str(values.get("NOVEL_FORGE_PLANNING_REASONING_EFFORT") or "").strip().lower(),
    )
    expected_planning = (
        normalize_provider_id(str(planning["provider"])),
        str(planning["model"]),
        str(planning["reasoning_effort"]).lower(),
    )
    if actual_planning != expected_planning:
        raise RuntimeError("actual Planning Provider route differs from frozen profile")

    for role, stages in _RUNTIME_ROLE_STAGES.items():
        binding = expected[role]
        expected_stage = (
            normalize_provider_id(str(binding["provider"])),
            str(binding["model"]),
            str(binding["reasoning_effort"]).lower(),
        )
        for stage in stages:
            if _effective_stage_binding(values, stage) != expected_stage:
                raise RuntimeError(
                    f"actual {stage} Provider route differs from frozen {role} profile"
                )


def _verify_runtime_pack_ids(
    state: Mapping[str, Any], values: Mapping[str, str], *, mode: str
) -> None:
    manifest = dict(state["capability_pack_manifest"])
    for role, (environment_key, default_pack_id) in _PACK_RUNTIME_BINDINGS.items():
        binding = dict(manifest.get(role) or {})
        deployment_id = str(binding.get("deployment_id") or "")
        if mode == "scripted" and deployment_id.startswith("scripted-unpacked:"):
            continue
        expected_pack_id = str(binding.get("pack_id") or "")
        if not expected_pack_id:
            raise ValueError(f"Capability Pack {role} lacks pack_id")
        actual_pack_id = str(values.get(environment_key) or default_pack_id)
        if actual_pack_id != expected_pack_id:
            raise RuntimeError(f"runtime Capability Pack id drifted for {role}")


def _freeze(args: argparse.Namespace) -> dict[str, Any]:
    state = _state(args.state)
    proof = _verify_release_and_migration(
        args.database_url,
        state,
        allow_dirty=args.allow_dirty,
    )
    profile = load_quality_campaign_profile(
        args.profile,
        repository_root=ROOT,
    )
    values = _runtime_env(state, mode=args.mode, profile=profile)
    _verify_runtime_routes(profile, values, mode=args.mode)
    _verify_runtime_pack_ids(state, values, mode=args.mode)
    _verify_freeze_lineage(
        args.database_url,
        state,
        mode=args.mode,
        values=values,
    )
    budget_headroom = _verify_freeze_budget_headroom(
        args.database_url,
        str(state["project_id"]),
        profile,
    )
    manifest = profile.freeze_manifest(
        campaign_id=str(state["campaign_id"]),
        exact_release_sha=str(state["exact_release_sha"]),
        migration_head=str(state["migration_head"]),
        mode=args.mode,
        project_id=str(state["project_id"]),
        workspace_id=str(state["workspace_id"]),
        book_id=str(state["book_id"]),
        capability_pack_manifest=dict(state["capability_pack_manifest"]),
        foundation_lineage=dict(state["foundation_lineage"]),
        planning_lineage=dict(state["planning_lineage"]),
        realization_lineage=dict(state["realization_lineage"]),
    )
    operator = _principal(str(state["project_id"]))
    quality = _quality(args.database_url, state)
    admitted = quality.admit_campaign(
        manifest,
        stable_idempotency_key=f"{state['campaign_id']}:admit",
        trace_id=f"trace:{state['campaign_id']}:admit",
        correlation_id=str(state["campaign_id"]),
        principal=operator,
    )
    if admitted["lifecycle"] == "DRAFT":
        admitted = quality.freeze_campaign(
            str(state["campaign_id"]),
            expected_version=int(admitted["version"]),
            principal=operator,
        )
    if admitted["lifecycle"] != "FROZEN":
        raise RuntimeError("freeze command resolved a non-FROZEN campaign")
    return {
        "status": "FROZEN",
        "campaign": admitted,
        "manifest": manifest.to_dict(),
        "freeze_budget_headroom": budget_headroom,
        **proof,
    }


def _campaign_budget_usage(database_url: str, project_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_external_effect_dispatch AS dispatch
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id=dispatch.external_effect_id
            WHERE effect.project_id=%s AND effect.effect_type='model.invoke'
            """,
            [project_id],
        )
        provider_call_count = int(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT COALESCE(SUM(actual_tokens) FILTER (
                       WHERE status='SETTLED'),0),
                   COALESCE(SUM(settled_amount) FILTER (
                       WHERE status='SETTLED'),0),
                   COUNT(*) FILTER (
                       WHERE status NOT IN ('SETTLED','RELEASED')),
                   COUNT(*) FILTER (WHERE budget_breach)
            FROM authority_budget_reservation
            WHERE project_id=%s
            """,
            [project_id],
        )
        tokens, cost, unresolved, breaches = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_external_effect AS effect
            LEFT JOIN authority_budget_reservation AS reservation
              ON reservation.external_effect_id=effect.external_effect_id
             AND reservation.project_id=effect.project_id
            WHERE effect.project_id=%s
              AND effect.effect_type='model.invoke'
              AND reservation.reservation_id IS NULL
            """,
            [project_id],
        )
        unbound_effect_count = int(uow.cursor.fetchone()[0])
    return {
        "provider_call_count": provider_call_count,
        "settled_tokens": int(tokens),
        "settled_cost_amount": format(Decimal(str(cost)), "f"),
        "unresolved_reservation_count": int(unresolved),
        "budget_breach_count": int(breaches),
        "unbound_effect_count": unbound_effect_count,
    }


def _require_freeze_budget_headroom(
    profile: Any,
    usage: Mapping[str, Any],
) -> dict[str, Any]:
    budget = dict(profile.to_dict()["budget_policy"])
    policy = dict(budget["freeze_headroom_policy"])
    try:
        settled_cost = Decimal(str(usage["settled_cost_amount"]))
        cost_limit = Decimal(str(budget["cost_limit_usd"]))
        minimum_remaining_cost = Decimal(str(policy["minimum_remaining_cost_usd"]))
    except (InvalidOperation, KeyError) as exc:
        raise RuntimeError("freeze budget evidence is invalid") from exc
    remaining = {
        "remaining_provider_calls": int(budget["provider_call_limit"])
        - int(usage["provider_call_count"]),
        "remaining_tokens": int(budget["token_limit"]) - int(usage["settled_tokens"]),
        "remaining_cost_usd": format(cost_limit - settled_cost, "f"),
    }
    failures: list[str] = []
    if int(usage["unresolved_reservation_count"]):
        failures.append("unresolved_reservations")
    if int(usage["budget_breach_count"]):
        failures.append("existing_budget_breach")
    if int(usage["unbound_effect_count"]):
        failures.append("model_effect_without_budget_reservation")
    if remaining["remaining_provider_calls"] < int(
        policy["minimum_remaining_provider_calls"]
    ):
        failures.append("remaining_provider_calls")
    if remaining["remaining_tokens"] < int(policy["minimum_remaining_tokens"]):
        failures.append("remaining_tokens")
    if Decimal(remaining["remaining_cost_usd"]) < minimum_remaining_cost:
        failures.append("remaining_cost_usd")
    if failures:
        raise RuntimeError(
            "bounded Quality freeze lacks execution headroom: " + ", ".join(failures)
        )
    return {
        **dict(usage),
        **remaining,
        "policy": policy,
        "status": "PASS",
    }


def _verify_freeze_budget_headroom(
    database_url: str,
    project_id: str,
    profile: Any,
) -> dict[str, Any]:
    return _require_freeze_budget_headroom(
        profile,
        _campaign_budget_usage(database_url, project_id),
    )


def _runtime_env(
    state: Mapping[str, Any],
    *,
    mode: str,
    profile: Any,
) -> dict[str, str]:
    values = {str(key): str(value) for key, value in os.environ.items()}
    values.update(
        {str(key): str(value) for key, value in dict(state["runtime_env"]).items()}
    )
    values["NOVEL_FORGE_COMMIT_SHA"] = str(state["exact_release_sha"])
    values.setdefault(
        "NOVEL_FORGE_APPLICATION_BUILD_ID",
        "bounded-quality-qualification-cli",
    )
    budget = profile.to_dict()["budget_policy"]
    values.update(
        {
            "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": str(
                budget["cost_limit_per_call_usd"]
            ),
            "NOVEL_FORGE_OPERATION_PROVIDER_CAP": str(
                budget["cost_limit_per_operation_usd"]
            ),
            "NOVEL_FORGE_CHAPTER_PROVIDER_CAP": str(
                budget["cost_limit_per_chapter_usd"]
            ),
            "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP": str(budget["cost_limit_usd"]),
            "NOVEL_FORGE_PROVIDER_DAILY_CAP": str(budget["cost_limit_usd"]),
        }
    )
    if mode == "scripted":
        if values.get("NOVEL_FORGE_MODEL_PROVIDER") != "scripted_provider_v2":
            raise RuntimeError("dry-run requires the explicit scripted Provider route")
        values.setdefault("NOVEL_FORGE_ENVIRONMENT", "test")
        values.setdefault(
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE",
            "true",
        )
    elif values.get("NOVEL_FORGE_MODEL_PROVIDER") == "scripted_provider_v2":
        raise RuntimeError("run-real refuses a scripted Provider route")
    elif values.get("NOVEL_FORGE_ENVIRONMENT") != "validation":
        raise RuntimeError("run-real requires the controlled validation environment")
    return values


def _campaign_mode(campaign: Mapping[str, Any]) -> str:
    mode = str(dict(campaign["provider_route_manifest"]).get("mode") or "")
    if mode not in {"scripted", "real"}:
        raise RuntimeError("campaign Provider mode is not frozen")
    return mode


def _campaign_secret(mode: str) -> str:
    value = str(os.environ.get("NOVEL_FORGE_QUALITY_CAMPAIGN_SECRET") or "")
    if mode == "scripted" and not value:
        return "bounded-quality-scripted-secret-v1"
    if len(value) < 16:
        raise RuntimeError(
            "NOVEL_FORGE_QUALITY_CAMPAIGN_SECRET must be set for real blind export"
        )
    return value


def _run_campaign(
    args: argparse.Namespace,
    *,
    requested_mode: str | None,
) -> dict[str, Any]:
    state = _state(args.state)
    quality = _quality(args.database_url, state)
    operator = _principal(str(state["project_id"]))
    campaign = quality.require_campaign(
        str(state["campaign_id"]),
        principal=operator,
    )
    _verify_frozen_campaign_binding(campaign, state)
    mode = _campaign_mode(campaign)
    if requested_mode is not None and mode != requested_mode:
        raise RuntimeError(f"command requires a frozen {requested_mode} campaign")
    proof = _verify_release_and_migration(
        args.database_url,
        state,
        allow_dirty=bool(args.allow_dirty and mode == "scripted"),
    )
    profile = load_quality_campaign_profile(args.profile, repository_root=ROOT)
    env = _runtime_env(state, mode=mode, profile=profile)
    _verify_runtime_routes(
        profile,
        env,
        mode=mode,
        frozen_route_manifest=dict(campaign["provider_route_manifest"]),
    )
    _verify_runtime_pack_ids(state, env, mode=mode)
    _verify_freeze_lineage(
        args.database_url,
        state,
        mode=mode,
        values=env,
    )
    settings = IndustrialSettings.from_env(
        {
            **env,
            "NOVEL_FORGE_ROOT": str(ROOT),
            "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql",
            "NOVEL_FORGE_DATABASE_URL": args.database_url,
        },
        root=ROOT,
    )
    execution = build_production_execution_composition(
        settings,
        env=env,
        planning_fixture_factory=(
            bounded_quality_planning_fixture_response if mode == "scripted" else None
        ),
        chapter_fixture_factory=(
            bounded_quality_chapter_fixture_response if mode == "scripted" else None
        ),
    )
    try:
        chapter = build_chapter_authority_application(
            settings,
            execution=execution,
            env=env,
        )
        composition = build_book_production_composition(
            settings,
            principal=operator,
            execution=execution,
            env=env,
            chapter_application=chapter,
        )
        if campaign["lifecycle"] == "FROZEN":
            campaign = quality.start_campaign(
                str(state["campaign_id"]),
                expected_version=int(campaign["version"]),
                principal=operator,
            )
        if campaign["lifecycle"] not in {
            "RUNNING",
            "WAITING_HUMAN_EVIDENCE",
        }:
            raise RuntimeError("campaign is not runnable or resumable")
        book = composition.authority.require(str(state["book_run_id"]))
        if (
            book["project_id"] != state["project_id"]
            or book["book_id"] != state["book_id"]
            or int(book["target_chapter_count"]) != 8
            or int(book["accepted_through_chapter"]) > 8
        ):
            raise RuntimeError("Book run differs from the frozen bounded scope")
        reviewers = tuple(
            HumanReviewerTarget(
                str(item["reviewer_id"]),
                EvaluatorIdentityClass(str(item["identity_class"])),
            )
            for item in state["reviewers"]
        )
        runtime = PostgresBoundedQualityCampaignRuntime(
            database_url=args.database_url,
            profile=profile,
            campaign_id=str(state["campaign_id"]),
            book_run_id=str(state["book_run_id"]),
            project_id=str(state["project_id"]),
            workspace_id=str(state["workspace_id"]),
            book_id=str(state["book_id"]),
            primary_arc_plan_version_id=str(state["primary_arc_plan_version_id"]),
            volume_scope_id=str(state["volume_scope_id"]),
            composition=composition,
            chapter_application=chapter,
            operator=operator,
            chapter_worker=_principal(str(state["project_id"]), worker=True),
            quality_authority=quality,
            reviewers=reviewers,
            campaign_secret=_campaign_secret(mode),
            mode=mode,
        )
        try:
            result = BoundedQualityCampaignRunner(profile, mode=mode).run(runtime)
        except QualityCampaignTerminalError as exc:
            runtime.record_terminal_failure(exc)
            raise
        except KernelError as exc:
            terminal = runtime.terminal_failure_for_runtime_error(
                error_code=exc.code,
            )
            if terminal is not None:
                runtime.record_terminal_failure(terminal)
                raise terminal from exc
            raise
        current = quality.require_campaign(
            str(state["campaign_id"]),
            principal=operator,
        )
        payload = {
            "schema_version": RESULT_SCHEMA,
            "mode": mode,
            "result": asdict(result),
            "deterministic_identity": result.deterministic_identity,
            "semantic_identity": result.semantic_identity,
            "campaign": current,
            "bounded_evidence_only": True,
            "human_simulation_used": False,
            **proof,
        }
        if args.output:
            payload["output_path"] = str(_write_json(args.output, payload))
        return payload
    finally:
        execution.close()


def _pack_rows(database_url: str, campaign_id: str) -> list[dict[str, Any]]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT pack_id,task_id,reviewer_id,evaluator_identity_class,
                   protocol_version,evaluation_profile_version,pair_count,status
            FROM human_preference_evaluation_pack
            WHERE campaign_id=%s
            ORDER BY reviewer_id
            """,
            [campaign_id],
        )
        fields = (
            "pack_id",
            "task_id",
            "reviewer_id",
            "evaluator_identity_class",
            "protocol_version",
            "evaluation_profile_version",
            "pair_count",
            "status",
        )
        return [dict(zip(fields, row, strict=True)) for row in uow.cursor.fetchall()]


def _export(args: argparse.Namespace) -> dict[str, Any]:
    state = _state(args.state)
    operator = _principal(str(state["project_id"]))
    quality = _quality(args.database_url, state)
    output = Path(args.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = _pack_rows(args.database_url, str(state["campaign_id"]))
    if len(rows) != 2:
        raise RuntimeError("blind export requires exactly two persisted packs")
    exported: list[dict[str, Any]] = []
    for row in rows:
        public = quality.reader_calibration.reviewer_pack(
            pack_id=str(row["pack_id"]),
            reviewer_id=str(row["reviewer_id"]),
            principal=operator,
        )
        path = _write_json(output / f"{row['reviewer_id']}.json", public)
        exported.append({**row, "path": str(path)})
    return {
        "status": "EXPORTED",
        "campaign_id": state["campaign_id"],
        "packs": exported,
        "private_mapping_exported": False,
    }


def _record_human(args: argparse.Namespace) -> dict[str, Any]:
    state = _state(args.state)
    operator = _principal(str(state["project_id"]))
    calibration = _quality(args.database_url, state).reader_calibration
    document = _json_file(args.input)
    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("human import requires a non-empty records array")
    results: list[dict[str, Any]] = []
    for raw_value in records:
        raw = dict(raw_value)
        kind = str(raw.get("kind") or "DECISION").upper()
        if kind == "DECISION":
            decision = HumanBlindDecision(
                decision_id=str(raw["decision_id"]),
                pair_token=str(raw["pair_token"]),
                reviewer_id=str(raw["reviewer_id"]),
                evaluator_identity_class=EvaluatorIdentityClass(
                    str(raw["evaluator_identity_class"])
                ),
                protocol_version=str(raw["protocol_version"]),
                evaluation_version=str(raw["evaluation_version"]),
                scope_type=BlindScope(str(raw["scope_type"])),
                chapter_start=int(raw["chapter_start"]),
                chapter_end=int(raw["chapter_end"]),
                choice=PreferenceChoice(str(raw["choice"])),
                dimension_scores=dict(raw["dimension_scores"]),
                confidence=float(raw["confidence"]),
                rationale=str(raw.get("rationale") or ""),
                evidence_spans=tuple(
                    dict(item) for item in raw.get("evidence_spans") or ()
                ),
            )
            results.append(
                calibration.record_blind_decision(decision, principal=operator)
            )
        elif kind == "ADJUDICATION":
            choice = raw.get("resolved_choice")
            results.append(
                calibration.adjudicate_blind_subject(
                    task_id=str(raw["task_id"]),
                    subject_id=str(raw["subject_id"]),
                    adjudicator_id=str(raw["adjudicator_id"]),
                    resolved_choice=(
                        PreferenceChoice(str(choice)) if choice is not None else None
                    ),
                    rationale=str(raw["rationale"]),
                    dimension_scores=dict(raw.get("dimension_scores") or {}),
                    principal=operator,
                )
            )
        elif kind == "FINALIZE":
            results.append(
                calibration.build_agreement_report(
                    str(raw["task_id"]),
                    principal=operator,
                )
            )
        else:
            raise ValueError(f"unsupported human record kind: {kind}")
    return {
        "status": "RECORDED",
        "campaign_id": state["campaign_id"],
        "records": results,
        "human_subjectivity_is_ground_truth": False,
    }


def _evaluate(args: argparse.Namespace) -> dict[str, Any]:
    state = _state(args.state)
    operator = _principal(str(state["project_id"]))
    quality = _quality(args.database_url, state)
    decision = quality.evaluate_campaign(
        str(state["campaign_id"]),
        human_collection_closed=args.human_collection_closed,
        principal=operator,
    )
    if (
        not decision["human_evaluator_ids"]
        and decision["qualification_status"] != "NOT_PROVEN"
    ):
        raise RuntimeError("zero-human evaluation violated fail-closed semantics")
    return decision


def _add_common(parser: argparse.ArgumentParser, *, output: bool = False) -> None:
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    if output:
        parser.add_argument("--output")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare",
        help="prepare one canonical unstarted 4+4 Book and write frozen state",
    )
    prepare.add_argument("--database-url", required=True)
    prepare.add_argument("--campaign-id", required=True)
    prepare.add_argument("--mode", choices=("scripted", "real"), required=True)
    prepare.add_argument("--runtime-env", required=True)
    prepare.add_argument(
        "--reviewer",
        action="append",
        required=True,
        metavar="ID:IDENTITY_CLASS",
        help="repeat exactly twice for the independent human reviewer targets",
    )
    prepare.add_argument("--profile", default=str(DEFAULT_PROFILE))
    prepare.add_argument("--book-contract", default=str(DEFAULT_BOOK_CONTRACT))
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--allow-dirty", action="store_true")

    capture = subparsers.add_parser(
        "capture-real-state",
        help="capture one prepared canonical 4+4 Book as a non-authoritative state descriptor",
    )
    capture.add_argument("--database-url", required=True)
    capture.add_argument("--book-run-id", required=True)
    capture.add_argument("--campaign-id", required=True)
    capture.add_argument(
        "--reviewer",
        action="append",
        required=True,
        metavar="ID:IDENTITY_CLASS",
        help="repeat exactly twice for the independent human reviewer targets",
    )
    capture.add_argument("--runtime-env", required=True)
    capture.add_argument("--primary-arc-plan-version-id", default="")
    capture.add_argument("--profile", default=str(DEFAULT_PROFILE))
    capture.add_argument("--output", required=True)

    freeze = subparsers.add_parser("freeze", help="admit and freeze exact lineage")
    _add_common(freeze)
    freeze.add_argument("--mode", choices=("scripted", "real"), required=True)
    freeze.add_argument("--allow-dirty", action="store_true")

    dry_run = subparsers.add_parser("dry-run", help="run bounded scripted protocol")
    _add_common(dry_run, output=True)
    dry_run.add_argument("--allow-dirty", action="store_true")

    run_real = subparsers.add_parser("run-real", help="run bounded real Provider")
    _add_common(run_real, output=True)
    run_real.set_defaults(allow_dirty=False)

    resume = subparsers.add_parser("resume", help="resume the frozen campaign mode")
    _add_common(resume, output=True)
    resume.add_argument("--allow-dirty", action="store_true")

    export = subparsers.add_parser(
        "export-blind-packs",
        help="write only reviewer-safe public packs",
    )
    _add_common(export)
    export.add_argument("--output-dir", required=True)

    record = subparsers.add_parser(
        "record-human",
        help="append blinded decisions, adjudication, or task finalization",
    )
    _add_common(record)
    record.add_argument("--input", required=True)

    evaluate = subparsers.add_parser("evaluate", help="record fail-closed decision")
    _add_common(evaluate)
    evaluate.add_argument("--human-collection-closed", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "prepare":
            result = _prepare(args)
        elif args.command == "capture-real-state":
            result = _capture_real_state(args)
        elif args.command == "freeze":
            result = _freeze(args)
        elif args.command == "dry-run":
            result = _run_campaign(args, requested_mode="scripted")
        elif args.command == "run-real":
            result = _run_campaign(args, requested_mode="real")
        elif args.command == "resume":
            result = _run_campaign(args, requested_mode=None)
        elif args.command == "export-blind-packs":
            result = _export(args)
        elif args.command == "record-human":
            result = _record_human(args)
        elif args.command == "evaluate":
            result = _evaluate(args)
        else:  # pragma: no cover - argparse owns the command set
            raise AssertionError(args.command)
    except (KernelError, RuntimeError, ValueError, OSError) as exc:
        failure_code = getattr(exc, "failure_code", "")
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    **({"failure_code": failure_code} if failure_code else {}),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
