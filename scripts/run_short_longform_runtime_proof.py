#!/usr/bin/env python3
"""Run the exact-HEAD real Codex short long-form vertical proof."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import uuid4

from novel_forge.api.authority_dependencies import (
    build_book_authority_application,
    build_chapter_authority_application,
    build_story_planning_generation_application,
)
from novel_forge.modules.book_authority import (
    BookProductionInputResolver,
    PostgresBookAuthority,
    PostgresBookProductionSupervisor,
    ResolveBookProductionInputCommand,
    StartBookProductionCommand,
)
from novel_forge.modules.book_followup_authority import LongformCheckpointType
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
)
from novel_forge.modules.book_production import SupervisorAction
from novel_forge.modules.book_replan import (
    BookReplanCoordinator,
    CoordinateBookReplanCommand,
)
from novel_forge.modules.canon_graph.approval_authority import (
    CanonApprovalContext,
    decide_canon_approval,
    list_canon_approvals,
)
from novel_forge.modules.chapter_group_authority import (
    PostgresChapterGroupAuthority,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_design_authority import (
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
    BookDesignAuthorityQuery,
)
from novel_forge.modules.book_followup_authority.definitions import (
    book_followup_operation_definitions,
)
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
)
from novel_forge.modules.capability_packs.longform_profiles import (
    LongformCapabilityPackProfile,
    build_reader_outcome_pack_profile,
    build_story_planning_pack_profile,
)
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions,
)
from novel_forge.modules.command_kernel.asset_commands import (
    AuthorityAssetWriteCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.plan_change_authority import PostgresPlanChangeAuthority
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationStatus,
    StoryPlanningGenerationCommand,
)
from novel_forge.modules.story_planning_runtime.application import (
    story_planning_generation_definition,
)
from novel_forge.storage.authority_repositories import definition_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import run_migrations
from novel_forge.storage.object_store import MinioObjectStore

from run_real_capability_codex_proof import (
    PACK_PERMISSIONS,
    _git,
    _install_pack,
    _jsonable,
    _pack_command,
    _principal,
    _query_rows,
    _register_agents,
    _runtime_env,
)


ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feat/v7-content-intelligence-and-longform-proof"
PLANNING_PACK_ID = "story_planning_pack"
READER_PACK_ID = "reader_outcome_pack"
BOOTSTRAP_DEFINITION = "short_longform.proof.bootstrap"
BOOTSTRAP_HANDLER = "novel_forge.proof.short_longform.bootstrap"


class OneShotMeasuredProviderFailure:
    """Fail once after measured Provider usage and before candidate acceptance."""

    def __init__(self) -> None:
        self.triggered = False

    def __call__(self, checkpoint: str) -> None:
        if (
            checkpoint == "after_measured_usage_before_candidate_acceptance"
            and not self.triggered
        ):
            self.triggered = True
            raise KernelError(
                "MODEL_EFFECT_RETRYABLE_PLANNING_REAL_PROOF",
                "controlled post-provider failure after measured Codex usage",
            )


def _proof_bucket_names(runtime_root: Path) -> dict[str, str]:
    """Return deterministic, per-run MinIO buckets for immutable proof artifacts."""

    identity = hashlib.sha256(str(runtime_root.resolve()).encode("utf-8")).hexdigest()[:16]
    prefix = f"novel-forge-proof-{identity}"
    return {
        "raw": f"{prefix}-raw",
        "artifact": f"{prefix}-artifact",
        "export": f"{prefix}-export",
    }


def _bootstrap_definition(build_id: str, commit_sha: str) -> dict[str, Any]:
    command = {
        "type": "object",
        "required": ["project_id", "book_id", "evidence_level"],
        "properties": {
            "project_id": {"type": "string", "minLength": 1},
            "book_id": {"type": "string", "minLength": 1},
            "evidence_level": {"const": "CONTROLLED_PROOF_BOOTSTRAP"},
        },
        "additionalProperties": False,
    }
    return {
        "name": BOOTSTRAP_DEFINITION,
        "definition_version": "1.0.0",
        "family": "runtime_proof",
        "command_schema_version": "short-longform-proof-bootstrap.command.v1",
        "result_schema_version": "short-longform-proof-bootstrap.result.v1",
        "enabled": True,
        "command_schema": command,
        "result_schema": {"type": "object"},
        "input_contract": command,
        "output_contract": {"type": "object"},
        "handler_key": BOOTSTRAP_HANDLER,
        "handler_contract_version": "short-longform-proof-bootstrap-v1",
        "application_build_id": build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "proof_bootstrap_only": True,
            "may_claim_runtime_output": False,
        },
        "idempotency_scope": "project:short-longform-proof-bootstrap",
        "concurrency_key_template": "project:{project_id}:short-longform-bootstrap",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable_atomic"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only controlled proof bootstrap",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["story_planning", "book_production"],
        "migration_owner": "runtime-proof",
        "completion_contract": {
            "version": "short-longform-proof-bootstrap-completion-v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["short_longform.proof.bootstrap.created"],
        },
    }


def _bootstrap_assets(
    database_url: str,
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    build_id: str,
    commit_sha: str,
    principal: Principal,
) -> dict[str, str]:
    rows: dict[str, tuple[str, dict[str, Any]]] = {
        "world_bible": (
            "world_bible",
            {"rules": ["public records preserve physical revision traces"]},
        ),
        "character_cast": (
            "character_cast",
            {"characters": ["Lin Qiao", "Mei An", "Director Wu"]},
        ),
        "theme_contract": (
            "theme_contract",
            {"question": "What does accountable truth cost?"},
        ),
        "ending_intent": (
            "ending_intent",
            {"ending": "Lin Qiao chooses accountable agency at a visible cost."},
        ),
        "reader_promise": (
            "reader_promise",
            {"promise": "Each discovery forces a harder public choice."},
        ),
        "platform_profile": (
            "platform_profile",
            {
                "profile_id": "platform:short-longform-proof",
                "chapter_length": {"minimum": 1200, "maximum": 4000},
                "safe_summary": "Provider-validation platform constraints.",
                "structured_facts": [
                    {
                        "key": "platform_rules",
                        "value": {
                            "chapter_length": {"minimum": 1200, "maximum": 4000},
                            "format": {"mobile_paragraphs": True},
                        },
                    }
                ],
            },
        ),
        "production_profile": (
            "production_profile",
            {
                "profile_id": "production:short-longform-proof",
                "target_chapter_count": 3,
            },
        ),
        "previous_volume_outcome": ("previous_volume_outcome", {"status": "NONE"}),
        "story_state": ("story_state", {"chapter_number": 0, "facts": []}),
        "canon_snapshot": ("canon_snapshot", {"chapter_number": 0, "facts": []}),
        "arc_portfolio": ("arc_portfolio", {"arcs": ["truth-versus-safety"]}),
        "ending_reachability": (
            "ending_reachability",
            {"status": "REACHABLE", "target_chapter": 3},
        ),
        "character_arc_portfolio": (
            "character_arc_portfolio",
            {"arcs": ["avoidance-to-accountability"]},
        ),
        "conflict_state": (
            "conflict_state",
            {"pressure": "institutional archive purge"},
        ),
        "promise_ledger": (
            "promise_ledger",
            {"open": ["the erased ledger must become public"]},
        ),
        "foreshadowing_ledger": (
            "foreshadowing_ledger",
            {"open": ["a living witness is listed as dead"]},
        ),
        "foreshadowing_state": (
            "foreshadowing_state",
            {"open": ["a living witness is listed as dead"]},
        ),
        "previous_chapter_group_outcome": (
            "previous_chapter_group_outcome",
            {"status": "NONE"},
        ),
        "quality_trend": ("quality_trend", {"direction": "STABLE"}),
        "reader_state": (
            "reader_state",
            {"mode": "SHADOW", "calibration_status": "UNCALIBRATED"},
        ),
        "previous_chapter_outcome": (
            "previous_chapter_outcome",
            {"chapter_number": 0, "status": "NONE"},
        ),
        "reader_segment": (
            "reader_segment_profile",
            {"segment_id": "internal-proof-reader"},
        ),
        "reader_contract": (
            "reader_contract",
            {"contract_id": "reader-contract:shadow:v1"},
        ),
        "character_state": (
            "character_state",
            {"chapter_number": 0, "commitment": "avoidance"},
        ),
        "reward_ledger": ("reward_ledger", {"open": [], "paid": []}),
        "chapter_row_1": (
            "chapter_function_matrix_row",
            {"chapter_number": 1, "function": "setup", "hook": "the erased name"},
        ),
        "chapter_row_2": (
            "chapter_function_matrix_row",
            {"chapter_number": 2, "function": "reversal", "hook": "the witness refuses"},
        ),
        "chapter_row_3": (
            "chapter_function_matrix_row",
            {"chapter_number": 3, "function": "payoff", "hook": "the public cost"},
        ),
    }
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.definitions.register(_bootstrap_definition(build_id, commit_sha))
        uow.commit()

    def handler(
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        checkpoint("after_domain_validation")
        versions: dict[str, str] = {}
        for label, (asset_type, raw_content) in rows.items():
            content = {
                "book_id": book_id,
                "evidence_level": "CONTROLLED_PROOF_BOOTSTRAP",
                "runtime_result": False,
                "safe_summary": f"Controlled bootstrap input for {label}.",
                **raw_content,
            }
            document = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    asset_id=f"proof-bootstrap:{project_id}:{label}",
                    asset_type=asset_type,
                    schema_version=f"proof-bootstrap-{asset_type}.v1",
                    logical_ref=f"proof/bootstrap/{label}.json",
                    category="proof_bootstrap",
                    output_key=f"short_longform.bootstrap.{label}",
                    role="bootstrap_input",
                    content=content,
                    qualification_policy="controlled-proof-bootstrap-v1",
                    trace_id=f"trace:{project_id}:bootstrap",
                    correlation_id=f"correlation:{project_id}",
                )
            )
            versions[label] = document.asset_version_id
        checkpoint("after_business_projection_update")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "short_longform_proof_bootstrap",
                "aggregate_id": project_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": "short_longform.proof.bootstrap.created",
                "correlation_id": f"correlation:{project_id}",
                "causation_id": operation_id,
                "payload": {
                    "operation_id": operation_id,
                    "book_id": book_id,
                    "evidence_level": "CONTROLLED_PROOF_BOOTSTRAP",
                    "asset_count": len(versions),
                },
            }
        )
        checkpoint("after_outbox_insert")
        return versions

    result = execute_transaction_command(
        database_url,
        {
            "definition_name": BOOTSTRAP_DEFINITION,
            "definition_version": "1.0.0",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "actor_id": principal.principal_id,
            "idempotency_scope": "project:short-longform-proof-bootstrap",
            "idempotency_key": f"{project_id}:bootstrap:v1",
            "trace_id": f"trace:{project_id}:bootstrap",
            "span_id": str(uuid4()),
            "correlation_id": f"correlation:{project_id}",
            "causation_id": "",
            "input": {
                "project_id": project_id,
                "book_id": book_id,
                "evidence_level": "CONTROLLED_PROOF_BOOTSTRAP",
            },
            "input_assets": [],
        },
        context=AdmissionContext(
            actor_id=principal.principal_id,
            permissions=frozenset({"book.authority.execute"}),
            available_handlers=frozenset({BOOTSTRAP_HANDLER}),
            application_build_id=build_id,
            commit_sha=commit_sha,
        ),
        handler=handler,
    )
    return {key: str(value) for key, value in result.items() if key in rows}


def _bootstrap_chapter_profiles(
    database_url: str,
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    build_id: str,
    commit_sha: str,
    principal: Principal,
) -> dict[str, str]:
    rows: dict[str, tuple[str, dict[str, Any]]] = {
        "quality_rubric": (
            "quality_rubric",
            {
                "profile_id": "quality:short-longform-proof:uncalibrated",
                "calibration_status": "UNCALIBRATED",
                "safe_summary": "Uncalibrated structural quality thresholds.",
                "structured_facts": [
                    {
                        "key": "thresholds",
                        "value": {
                            "readability": 70,
                            "maximum_average_paragraph": 270,
                            "maximum_duplicate_sentence_ratio": 0.25,
                            "minimum_prose_characters": 80,
                        },
                    }
                ],
            },
        ),
        "style_policy": (
            "style_policy",
            {
                "profile_id": "style:short-longform-proof",
                "safe_summary": "Original concise civic-fantasy prose policy.",
                "structured_facts": [
                    {
                        "key": "style_rules",
                        "value": {
                            "copyright_boundary": "project_owned_only",
                            "named_work_imitation": False,
                        },
                    }
                ],
            },
        ),
        "operator_checklist": (
            "operator_checklist",
            {
                "checklist_id": "operator-checklist:short-longform-proof",
                "safe_summary": "Controlled operator approved internal proof release only.",
                "structured_facts": [
                    {"key": "completed", "value": True},
                    {"key": "scope", "value": "INTERNAL_PROOF_RELEASE"},
                    {"key": "external_publish_permitted", "value": False},
                    {"key": "production_verified", "value": False},
                ],
            },
        ),
    }

    def handler(
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        checkpoint("after_domain_validation")
        versions: dict[str, str] = {}
        for label, (asset_type, raw_content) in rows.items():
            document = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    asset_id=f"proof-bootstrap:{project_id}:{label}",
                    asset_type=asset_type,
                    schema_version=f"proof-bootstrap-{asset_type}.v1",
                    logical_ref=f"proof/bootstrap/{label}.json",
                    category="proof_bootstrap",
                    output_key=f"short_longform.bootstrap.{label}",
                    role="bootstrap_input",
                    content={
                        "book_id": book_id,
                        "evidence_level": "CONTROLLED_PROOF_BOOTSTRAP",
                        "runtime_result": False,
                        **raw_content,
                    },
                    qualification_policy="controlled-proof-bootstrap-v1",
                    trace_id=f"trace:{project_id}:chapter-profiles",
                    correlation_id=f"correlation:{project_id}",
                )
            )
            versions[label] = document.asset_version_id
        checkpoint("after_business_projection_update")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "short_longform_proof_bootstrap",
                "aggregate_id": project_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": "short_longform.proof.bootstrap.created",
                "correlation_id": f"correlation:{project_id}",
                "causation_id": operation_id,
                "payload": {
                    "operation_id": operation_id,
                    "book_id": book_id,
                    "evidence_level": "CONTROLLED_PROOF_BOOTSTRAP",
                    "asset_count": len(versions),
                    "bootstrap_kind": "CHAPTER_PROFILES",
                },
            }
        )
        checkpoint("after_outbox_insert")
        return versions

    result = execute_transaction_command(
        database_url,
        {
            "definition_name": BOOTSTRAP_DEFINITION,
            "definition_version": "1.0.0",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "actor_id": principal.principal_id,
            "idempotency_scope": "project:short-longform-proof-bootstrap",
            "idempotency_key": f"{project_id}:bootstrap:chapter-profiles:v1",
            "trace_id": f"trace:{project_id}:chapter-profiles",
            "span_id": str(uuid4()),
            "correlation_id": f"correlation:{project_id}",
            "causation_id": "",
            "input": {
                "project_id": project_id,
                "book_id": book_id,
                "evidence_level": "CONTROLLED_PROOF_BOOTSTRAP",
            },
            "input_assets": [],
        },
        context=AdmissionContext(
            actor_id=principal.principal_id,
            permissions=frozenset({"book.authority.execute"}),
            available_handlers=frozenset({BOOTSTRAP_HANDLER}),
            application_build_id=build_id,
            commit_sha=commit_sha,
        ),
        handler=handler,
    )
    return {key: str(value) for key, value in result.items() if key in rows}


def _seed_project_and_active_design(
    database_url: str,
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    build_id: str,
    commit_sha: str,
    principal: Principal,
) -> dict[str, Any]:
    ProjectAuthorityApplication(
        database_url, application_build_id=build_id, commit_sha=commit_sha
    ).execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            idempotency_key=f"project:create:{project_id}",
            trace_id=f"trace:{project_id}",
            correlation_id=f"correlation:{project_id}",
            payload={"title": "The Ledger Under Rain", "stage": "PRODUCTION"},
        ),
        principal=principal,
    )
    app = BookDesignAuthorityApplication(
        database_url, application_build_id=build_id, commit_sha=commit_sha
    )
    base = {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_id": book_id,
        "actor_id": principal.principal_id,
        "service_identity": "short-longform-runtime-proof",
        "correlation_id": f"correlation:{project_id}",
    }
    app.execute(
        BookDesignAuthorityCommand(
            definition_name="book.create",
            idempotency_key=f"book:create:{book_id}",
            trace_id=f"trace:{project_id}:book:create",
            payload={
                "schema_version": "book-authority.v1",
                "title": "The Ledger Under Rain",
                "production_profile": {"environment": "provider-validation"},
                "runtime_policy": {"legacy_write": False, "silent_fallback": False},
                "release_identity": f"{build_id}@{commit_sha}",
            },
            **base,
        ),
        principal=principal,
    )
    query = BookDesignAuthorityQuery(database_url)
    book = query.require_book(project_id=project_id, book_id=book_id)
    proposed = app.execute(
        BookDesignAuthorityCommand(
            definition_name="book_design.propose",
            expected_book_version=int(book["version"]),
            expected_current_design_asset_version_id="",
            idempotency_key=f"book-design:propose:{book_id}",
            trace_id=f"trace:{project_id}:book-design:propose",
            payload={
                "schema_version": "book-design.v1",
                "title": "The Ledger Under Rain",
                "genre": "original civic fantasy mystery",
                "premise": "An archive clerk finds a living witness recorded as dead.",
                "theme": "truth becomes accountable only when someone pays its cost",
                "core_conflict": "public truth versus institutional safety",
                "reader_promise": "three escalating choices with auditable consequences",
                "ending": "the evidence becomes public and creates a new obligation",
                "protagonist": {
                    "name": "Lin Qiao",
                    "external_goal": "preserve the erased ledger",
                    "internal_need": "accept responsibility for public truth",
                    "flaw": "mistakes procedural safety for moral neutrality",
                    "arc": "avoidance to accountable agency",
                },
                "world_rules": [
                    "official records carry revision traces",
                    "public correction imposes a named civic debt",
                ],
                "target_chapters": 3,
            },
            **base,
        ),
        principal=principal,
    )
    book = query.require_book(project_id=project_id, book_id=book_id)
    app.execute(
        BookDesignAuthorityCommand(
            definition_name="book_design.decide",
            expected_book_version=int(book["version"]),
            expected_current_design_asset_version_id="",
            target_asset_version_id=str(proposed["asset_version_id"]),
            idempotency_key=f"book-design:decide:{book_id}",
            trace_id=f"trace:{project_id}:book-design:decide",
            payload={"decision": "APPROVE", "reason": "controlled operator review"},
            **base,
        ),
        principal=principal,
    )
    book = query.require_book(project_id=project_id, book_id=book_id)
    app.execute(
        BookDesignAuthorityCommand(
            definition_name="book_design.activate",
            expected_book_version=int(book["version"]),
            expected_current_design_asset_version_id="",
            target_asset_version_id=str(proposed["asset_version_id"]),
            idempotency_key=f"book-design:activate:{book_id}",
            trace_id=f"trace:{project_id}:book-design:activate",
            payload={"reason": "approved short long-form proof design"},
            **base,
        ),
        principal=principal,
    )
    return query.require_book(project_id=project_id, book_id=book_id)


def _register_longform_definitions(
    database_url: str, *, build_id: str, commit_sha: str
) -> tuple[str, str]:
    planning = story_planning_generation_definition(
        application_build_id=build_id, commit_sha=commit_sha
    )
    reader = next(
        item
        for item in book_followup_operation_definitions(
            application_build_id=build_id, commit_sha=commit_sha
        )
        if item["name"] == "reader_outcome.evaluate"
    )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.definitions.register(planning)
        uow.repositories.definitions.register(reader)
        for definition in chapter_operation_definitions(
            application_build_id=build_id,
            commit_sha=commit_sha,
            model_effects_required=True,
        ):
            uow.repositories.definitions.register(definition)
        uow.commit()
    return definition_hash(planning), definition_hash(reader)


def _install_profile(
    database_url: str,
    *,
    profile: LongformCapabilityPackProfile,
    version: str,
    generation: int,
    expected_activation_version: int,
    project_id: str,
    workspace_id: str,
    book_id: str,
    build_id: str,
    commit_sha: str,
    compiler: Principal,
    approver: Principal,
    agent_admin: Principal,
    agent_domain: str,
    agent_scope_type: str,
) -> dict[str, Any]:
    manifest = deepcopy(profile.manifest)
    manifest["identity"]["version"] = version
    for node in manifest["workflow_template"]["nodes"]:
        agent_ref = str(node.get("agent_definition_ref") or "")
        if agent_ref:
            node["agent_definition_ref"] = f"{agent_ref.rpartition('@')[0]}@{generation}"
    app = CapabilityPackAuthorityApplication(
        database_url, application_build_id=build_id, commit_sha=commit_sha
    )
    registration = _pack_command(
        app,
        compiler,
        action="capability_pack.manifest.register",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=profile.pack_id,
        payload={
            "manifest": manifest,
            "artifact_catalog": profile.artifact_catalog,
            "release_channel": "VALIDATION",
            "owner_scope_type": "PROJECT",
            "owner_project_id": project_id,
            "dependencies": [],
        },
    )
    compilation_id = f"compilation:{profile.pack_id}:{version}:{commit_sha[:12]}"
    compilation = _pack_command(
        app,
        compiler,
        action="capability_pack.compile",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=profile.pack_id,
        pack_version=version,
        compilation_id=compilation_id,
        payload={
            "target_runtime_profile": "provider-validation",
            "novel_forge_version": "6.0.0",
            "release_sha": commit_sha,
            "release_channel": "VALIDATION",
        },
    )
    compiled = dict(compilation["compiled"])
    _register_agents(
        database_url,
        compiled=compiled,
        project_id=project_id,
        workspace_id=workspace_id,
        build_id=build_id,
        commit_sha=commit_sha,
        principal=agent_admin,
        agent_skill_ref=profile.agent_skill_ref,
        agent_domain=agent_domain,
        agent_scope_type=agent_scope_type,
    )
    approval = _pack_command(
        app,
        approver,
        action="capability_pack.approval.decide",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=profile.pack_id,
        pack_version=version,
        compilation_id=compilation_id,
        payload={
            "compilation_hash": compilation["compilation_hash"],
            "decision": "APPROVED",
            "approval_policy_ref": "capability-pack-approval-scope:v1",
            "scope": {
                "schema_version": "CapabilityPackApprovalScope.v1",
                "allowed_environments": ["provider-validation"],
                "allowed_runtime_profiles": ["provider-validation"],
                "allowed_release_channels": ["VALIDATION"],
                "allowed_scope_types": ["BOOK"],
                "allowed_project_ids": [project_id],
                "allowed_workspace_ids": [workspace_id],
                "allowed_book_ids": [book_id],
                "allowed_workflow_definition_refs": [profile.workflow_ref],
                "allow_canary": False,
                "allow_percentage_rollout": False,
                "allow_full_rollout": True,
                "maximum_rollout_percentage": 100,
            },
            "limitations": [],
            "reason": "exact-HEAD short long-form real Codex proof",
            "evidence_refs": [f"runtime-proof:{commit_sha}"],
            "enforce_duties_separation": True,
        },
    )
    deployment_id = f"deployment:{profile.pack_id}:{version}:{commit_sha[:12]}"
    deployment = _pack_command(
        app,
        compiler,
        action="capability_pack.deployment.create",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=profile.pack_id,
        pack_version=version,
        compilation_id=compilation_id,
        deployment_id=deployment_id,
        payload={
            "target_scope_type": "BOOK",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "environment": "provider-validation",
            "rollout_policy_ref": "rollout:stable-sha256:v1",
        },
    )
    activation = _pack_command(
        app,
        compiler,
        action="capability_pack.deployment.activate",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=profile.pack_id,
        pack_version=version,
        deployment_id=deployment_id,
        expected_activation_version=expected_activation_version,
        payload={
            "environment": "provider-validation",
            "reason": "activate exact-HEAD short long-form proof Pack",
        },
    )
    return {
        "registration": registration,
        "compilation": compilation,
        "approval": approval,
        "deployment": deployment,
        "activation": activation,
        "deployment_id": deployment_id,
    }


def _planning_inputs(
    generator: str,
    *,
    bootstrap: Mapping[str, str],
    book_design_version: str,
    activated: Mapping[str, str],
    chapter_number: int = 1,
    previous_outcome: str = "",
    story_state: str = "",
    runtime_inputs: Mapping[str, str] | None = None,
) -> dict[str, str]:
    aliases = {
        "book_design": book_design_version,
        "book_plan": activated.get("book_plan.generate", ""),
        "volume_plan": activated.get("volume_plan.generate", ""),
        "arc_plans": activated.get("arc_plan.generate", ""),
        "chapter_group_plan": activated.get("chapter_group_plan.generate", ""),
        "chapter_function_matrix_row": bootstrap[f"chapter_row_{chapter_number}"],
        "previous_chapter_outcome": previous_outcome
        or bootstrap["previous_chapter_outcome"],
        "story_state": story_state or bootstrap["story_state"],
        **dict(runtime_inputs or {}),
    }
    result: dict[str, str] = {}
    for role in GENERATOR_INPUT_ROLES[generator]:
        value = aliases.get(role) or bootstrap.get(role) or ""
        if not value:
            raise RuntimeError(f"missing controlled Planning input role: {role}")
        result[role] = value
    return result


def _approve_activate(
    planning: Any,
    generated: Any,
    *,
    principal: Principal,
    key: str,
) -> dict[str, Any]:
    if generated.status is not PlanningGenerationStatus.APPROVAL_PENDING:
        raise RuntimeError(
            f"Planning candidate did not wait for approval: {generated.status}"
        )
    planning.approve_candidate(
        generated.candidate_asset_version_id,
        principal=principal,
        idempotency_key=f"{key}:approve",
        trace_id=f"trace:{key}:approve",
        correlation_id=f"correlation:{key}",
    )
    return planning.activate_candidate(
        generated.candidate_asset_version_id,
        principal=principal,
        idempotency_key=f"{key}:activate",
        trace_id=f"trace:{key}:activate",
        correlation_id=f"correlation:{key}",
    )


def _run_planning(
    *,
    database_url: str,
    settings: IndustrialSettings,
    env: dict[str, str],
    chapter: Any,
    project_id: str,
    workspace_id: str,
    book_id: str,
    book_design_version: str,
    bootstrap: Mapping[str, str],
    principal: Principal,
    compiler: Principal,
    approver: Principal,
    agent_admin: Principal,
    planning_profile: LongformCapabilityPackProfile,
    build_id: str,
    commit_sha: str,
) -> tuple[Any, dict[str, str], dict[int, dict[str, Any]], dict[str, Any]]:
    failure = OneShotMeasuredProviderFailure()
    planning = build_story_planning_generation_application(
        settings,
        env=env,
        chapter_application=chapter,
        post_provider_fault_injector=failure,
    )
    activated: dict[str, str] = {}
    projections: dict[int, dict[str, Any]] = {}
    retry_key = f"{project_id}:book-plan:real-retry"
    book_command = StoryPlanningGenerationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        generator_operation_name="book_plan.generate",
        logical_key="book:main",
        input_versions=_planning_inputs(
            "book_plan.generate",
            bootstrap=bootstrap,
            book_design_version=book_design_version,
            activated=activated,
        ),
        idempotency_key=retry_key,
        trace_id=f"trace:{retry_key}",
        correlation_id=f"correlation:{project_id}",
    )
    try:
        planning.generate(book_command, principal=principal)
    except KernelError as exc:
        if exc.code != "MODEL_EFFECT_RETRYABLE_PLANNING_REAL_PROOF":
            raise
    else:
        raise RuntimeError("real retry fault injection did not trigger")
    replacement_pack = _install_profile(
        database_url,
        profile=planning_profile,
        version="1.1.0",
        generation=2,
        expected_activation_version=1,
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
    generated = planning.generate(book_command, principal=principal)
    _approve_activate(planning, generated, principal=principal, key=retry_key)
    activated["book_plan.generate"] = generated.candidate_asset_version_id

    sequence = (
        ("volume_plan.generate", "volume:1", activated["book_plan.generate"]),
        ("arc_plan.generate", "arc:primary", ""),
        (
            "chapter_group_plan.generate",
            "chapter-group:1-3",
            "",
        ),
        ("chapter_plan.generate", "chapter:1", ""),
    )
    for generator, logical_key, explicit_parent in sequence:
        parent = explicit_parent
        if generator == "arc_plan.generate":
            parent = activated["volume_plan.generate"]
        elif generator == "chapter_group_plan.generate":
            parent = activated["volume_plan.generate"]
        elif generator == "chapter_plan.generate":
            parent = activated["chapter_group_plan.generate"]
        key = f"{project_id}:{generator}:{logical_key}"
        command = StoryPlanningGenerationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name=generator,
            logical_key=logical_key,
            input_versions=_planning_inputs(
                generator,
                bootstrap=bootstrap,
                book_design_version=book_design_version,
                activated=activated,
            ),
            parent_version_id=parent,
            idempotency_key=key,
            trace_id=f"trace:{key}",
            correlation_id=f"correlation:{project_id}",
        )
        item = planning.generate(command, principal=principal)
        activation = _approve_activate(
            planning, item, principal=principal, key=key
        )
        activated[generator] = item.candidate_asset_version_id
        if generator == "chapter_plan.generate":
            projections[1] = dict(activation["chapter_plan_projection"])
    evidence = {
        "fault_injection_triggered": failure.triggered,
        "retry_operation_id": generated.generation_operation_id,
        "replacement_pack": replacement_pack,
    }
    return planning, activated, projections, evidence


def _collect_planning_evidence(
    database_url: str, *, project_id: str
) -> dict[str, Any]:
    return {
        "operations": _query_rows(
            database_url,
            """
            SELECT operation_id, status, trace_id, created_at, updated_at
            FROM authority_operation
            WHERE project_id=%s AND definition_name='story_planning.generate'
            ORDER BY created_at
            """,
            (project_id,),
        ),
        "attempts": _query_rows(
            database_url,
            """
            SELECT attempt.operation_id, attempt.attempt_id,
                   attempt.attempt_number, attempt.status,
                   snapshot.snapshot_id, snapshot.snapshot_hash,
                   snapshot.pack_id, snapshot.pack_version,
                   snapshot.deployment_id
            FROM authority_attempt AS attempt
            JOIN authority_operation AS operation
              ON operation.operation_id=attempt.operation_id
            JOIN authority_attempt_capability_pack_snapshot AS snapshot
              ON snapshot.attempt_id=attempt.attempt_id
            WHERE operation.project_id=%s
              AND operation.definition_name='story_planning.generate'
            ORDER BY operation.created_at, attempt.attempt_number
            """,
            (project_id,),
        ),
        "effects": _query_rows(
            database_url,
            """
            SELECT effect.operation_id, effect.external_effect_id,
                   effect.status, effect.capability, effect.provider,
                   receipt.receipt_id, receipt.status AS receipt_status,
                   dispatch.evidence
            FROM authority_external_effect AS effect
            JOIN authority_operation AS operation
              ON operation.operation_id=effect.operation_id
            LEFT JOIN LATERAL (
                SELECT dispatch_id, status, evidence
                FROM authority_external_effect_dispatch
                WHERE external_effect_id=effect.external_effect_id
                ORDER BY generation DESC LIMIT 1
            ) AS dispatch ON TRUE
            LEFT JOIN LATERAL (
                SELECT receipt_id, status
                FROM authority_external_receipt
                WHERE dispatch_id=dispatch.dispatch_id
                ORDER BY received_at DESC LIMIT 1
            ) AS receipt ON TRUE
            WHERE operation.project_id=%s
              AND operation.definition_name='story_planning.generate'
            ORDER BY operation.created_at, effect.created_at
            """,
            (project_id,),
        ),
        "usage_cost": _query_rows(
            database_url,
            """
            SELECT asset.asset_type, version.content,
                   output.operation_id, output.output_key
            FROM authority_operation_output_asset AS output
            JOIN authority_operation AS operation
              ON operation.operation_id=output.operation_id
            JOIN authority_asset AS asset ON asset.asset_id=output.asset_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=output.asset_version_id
            WHERE operation.project_id=%s
              AND operation.definition_name='story_planning.generate'
              AND asset.asset_type IN ('model_call_log','cost_ledger')
            ORDER BY operation.created_at, asset.asset_type, version.created_at
            """,
            (project_id,),
        ),
    }


def _chapter_outputs(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    outputs = evidence.get("outputs")
    if not isinstance(outputs, list):
        raise RuntimeError("Chapter acceptance evidence has no outputs")
    return {str(item["asset_type"]): dict(item) for item in outputs}


def _run_chapter_scheduler(
    chapter: Any,
    *,
    database_url: str,
    project_id: str,
    root_operation_id: str,
    operator: Principal,
    worker: Principal,
    commit_sha: str,
) -> list[dict[str, Any]]:
    scheduler = chapter.scheduler(principal=worker)
    ticks: list[dict[str, Any]] = []
    terminal = ""
    for _ in range(100):
        tick = scheduler.tick(
            project_id=project_id,
            root_operation_id=root_operation_id,
        )
        row = _jsonable(asdict(tick))
        ticks.append(row)
        print(
            json.dumps(
                {
                    "phase": "chapter_scheduler",
                    "root_operation_id": root_operation_id,
                    **row,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if tick.saga_status == "WAITING_GATE":
            pending = [
                item
                for item in list_canon_approvals(
                    database_url, project_id=project_id
                )
                if item["root_operation_id"] == root_operation_id
                and item["status"]
                not in {
                    "APPROVED",
                    "REJECTED",
                    "EDITED_AND_APPROVED",
                    "INVALIDATED",
                    "EXPIRED",
                }
            ]
            for item in pending:
                decide_canon_approval(
                    database_url,
                    CanonApprovalContext(
                        project_id=project_id,
                        principal_id=operator.principal_id,
                        trace_id=f"trace:{project_id}:canon-approval",
                        correlation_id=f"correlation:{project_id}",
                    ),
                    approval_request_id=str(item["approval_request_id"]),
                    expected_version=int(item["version"]),
                    decision="APPROVE",
                    reason="operator reviewed real Codex extraction evidence",
                    evidence={
                        "evidence_level": "OPERATOR_REVIEWED_REAL_PROVIDER",
                        "release_sha": commit_sha,
                    },
                    edited_payload=None,
                    idempotency_key=(
                        f"{project_id}:approve:{item['approval_request_id']}"
                    ),
                )
        if tick.saga_status in {
            "SUCCEEDED",
            "FAILED_FINAL",
            "DEAD_LETTER",
            "CANCELLED",
            "COMPENSATION_FAILED",
        }:
            terminal = str(tick.saga_status)
            break
    if terminal != "SUCCEEDED":
        raise RuntimeError(
            f"Chapter {root_operation_id} did not succeed: {terminal or 'timeout'}"
        )
    return ticks


def _followup_output(
    database_url: str,
    *,
    project_id: str,
    chapter_request_id: str,
    followup_type: str,
    output_key: str,
) -> dict[str, Any]:
    rows = _query_rows(
        database_url,
        """
        SELECT link.operation_id, operation.status, binding.asset_version_id,
               binding.content_hash, version.content
        FROM authority_book_followup_operation AS link
        JOIN authority_operation AS operation ON operation.operation_id=link.operation_id
        JOIN authority_operation_output_asset AS binding
          ON binding.operation_id=link.operation_id AND binding.output_key=%s
        JOIN authority_asset_version AS version
          ON version.asset_version_id=binding.asset_version_id
        WHERE link.project_id=%s AND link.chapter_request_id=%s
          AND link.followup_type=%s
        """,
        (output_key, project_id, chapter_request_id, followup_type),
    )
    if len(rows) != 1 or rows[0]["status"] != "SUCCEEDED":
        raise RuntimeError(
            f"{followup_type} output {output_key} is not uniquely succeeded"
        )
    return rows[0]


def _complete_reader_sidecar(
    supervisor: PostgresBookProductionSupervisor,
    *,
    database_url: str,
    project_id: str,
    book_run_id: str,
    chapter_request_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ticks: list[dict[str, Any]] = []
    for _ in range(5):
        tick = supervisor.tick(book_run_id)
        ticks.append(_jsonable(asdict(tick)))
        rows = _query_rows(
            database_url,
            """
            SELECT operation.status
            FROM authority_book_followup_operation AS link
            JOIN authority_operation AS operation
              ON operation.operation_id=link.operation_id
            WHERE link.project_id=%s AND link.chapter_request_id=%s
              AND link.followup_type='READER_OUTCOME'
            """,
            (project_id, chapter_request_id),
        )
        if len(rows) == 1 and rows[0]["status"] == "SUCCEEDED":
            report = _followup_output(
                database_url,
                project_id=project_id,
                chapter_request_id=chapter_request_id,
                followup_type="READER_OUTCOME",
                output_key="reader_outcome.report",
            )
            return report, ticks
    raise RuntimeError("Reader Outcome sidecar did not succeed in five Supervisor ticks")


def _generate_chapter_plan(
    planning: Any,
    *,
    chapter_number: int,
    project_id: str,
    workspace_id: str,
    book_id: str,
    book_design_version: str,
    bootstrap: Mapping[str, str],
    activated: Mapping[str, str],
    runtime_inputs: Mapping[str, str],
    principal: Principal,
    key_suffix: str = "initial",
) -> tuple[str, dict[str, Any]]:
    key = f"{project_id}:chapter-plan:{chapter_number}:{key_suffix}"
    generated = planning.generate(
        StoryPlanningGenerationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name="chapter_plan.generate",
            logical_key=f"chapter:{chapter_number}",
            input_versions=_planning_inputs(
                "chapter_plan.generate",
                bootstrap=bootstrap,
                book_design_version=book_design_version,
                activated=activated,
                chapter_number=chapter_number,
                previous_outcome=str(
                    runtime_inputs.get("previous_chapter_outcome") or ""
                ),
                story_state=str(runtime_inputs.get("story_state") or ""),
                runtime_inputs=runtime_inputs,
            ),
            parent_version_id=activated["chapter_group_plan.generate"],
            idempotency_key=key,
            trace_id=f"trace:{key}",
            correlation_id=f"correlation:{project_id}",
        ),
        principal=principal,
    )
    activation = _approve_activate(
        planning, generated, principal=principal, key=key
    )
    projection = activation.get("chapter_plan_projection")
    if not isinstance(projection, Mapping):
        raise RuntimeError("activated Chapter plan has no typed projection")
    return generated.candidate_asset_version_id, dict(projection)


def _runtime_planning_inputs(
    authority: PostgresBookAuthority,
    *,
    project_id: str,
    chapter_request_id: str,
    reader_report: Mapping[str, Any],
) -> dict[str, str]:
    request = authority.require_chapter_request(chapter_request_id)
    evidence = authority.chapter_port.require_acceptance_evidence(
        project_id=project_id,
        root_operation_id=request["chapter_root_operation_id"],
    )
    outputs = _chapter_outputs(evidence)
    book = authority.require(request["book_run_id"])
    reader_state = _followup_output(
        authority.database_url,
        project_id=project_id,
        chapter_request_id=chapter_request_id,
        followup_type="READER_OUTCOME",
        output_key="reader_outcome.state_transition",
    )
    return {
        "previous_chapter_outcome": str(book["last_chapter_outcome_version_id"]),
        "story_state": str(book["active_story_state_version_id"]),
        "canon_snapshot": str(outputs["canon_snapshot"]["asset_version_id"]),
        "character_state": str(
            outputs["character_state_snapshot"]["asset_version_id"]
        ),
        "foreshadowing_state": str(
            outputs["foreshadow_snapshot"]["asset_version_id"]
        ),
        "reward_ledger": str(outputs["reward_ledger_snapshot"]["asset_version_id"]),
        "promise_ledger": str(
            outputs["promise_ledger_snapshot"]["asset_version_id"]
        ),
        "reader_state": str(reader_state["asset_version_id"]),
    }


def _controlled_recap(
    authority: PostgresBookAuthority,
    *,
    project_id: str,
    chapter_request_id: str,
    principal: Principal,
) -> dict[str, Any]:
    request = authority.require_chapter_request(chapter_request_id)
    book = authority.require(request["book_run_id"])
    evidence = authority.chapter_port.require_acceptance_evidence(
        project_id=project_id,
        root_operation_id=request["chapter_root_operation_id"],
    )
    outputs = _chapter_outputs(evidence)
    reader = _followup_output(
        authority.database_url,
        project_id=project_id,
        chapter_request_id=chapter_request_id,
        followup_type="READER_OUTCOME",
        output_key="reader_outcome.report",
    )
    frozen = dict(book["longform_context_versions"])
    authority_inputs = authority.resolve_asset_refs(
        project_id=project_id,
        asset_version_ids=(
            str(book["book_design_version"]),
            str(book["book_plan_version"]),
            str(frozen["volume_plan_version"]),
            str(frozen["arc_plan_version"]),
            str(frozen["quality_trend_version"]),
            str(book["last_chapter_outcome_version_id"]),
            str(book["active_story_state_version_id"]),
        ),
    )

    def asset_ref(name: str) -> dict[str, str]:
        item = outputs[name]
        return {
            "asset_version_id": str(item["asset_version_id"]),
            "content_hash": str(item["content_hash"]),
        }

    admission = authority.schedule_longform_recap(
        chapter_request_id,
        principal=principal,
        payload={
            "book_id": book["book_id"],
            "checkpoint_type": LongformCheckpointType.LIGHT.value,
            "chapter_range": [1, int(request["chapter_number"])],
            "book_design_version": book["book_design_version"],
            "book_plan_version": book["book_plan_version"],
            "volume_plan_version": frozen["volume_plan_version"],
            "arc_plan_version": frozen["arc_plan_version"],
            "canon_snapshot_version": outputs["canon_snapshot"]["asset_version_id"],
            "character_state_version": outputs["character_state_snapshot"][
                "asset_version_id"
            ],
            "foreshadowing_state_version": outputs["foreshadow_snapshot"][
                "asset_version_id"
            ],
            "reader_state_version": reader["asset_version_id"],
            "quality_trend_version": frozen["quality_trend_version"],
            "reward_ledger_version": outputs["reward_ledger_snapshot"][
                "asset_version_id"
            ],
            "promise_ledger_version": outputs["promise_ledger_snapshot"][
                "asset_version_id"
            ],
            "chapter_outcome_versions": [book["last_chapter_outcome_version_id"]],
            "story_state_version": book["active_story_state_version_id"],
            "observations": {
                "evidence_level": "CONTROLLED_PROOF",
                "controlled_proof_runtime_claim": "CONTROL_FLOW_ONLY",
                "reader_state": dict(reader["content"].get("reader_state") or {}),
                "reader_qualification": {
                    "qualification_status": "SHADOW",
                    "sample_size": 0,
                    "confidence": 0,
                    "disagreement": True,
                    "position_bias": True,
                    "ood": True,
                    "drift_detected": False,
                    "recent_reports": [],
                    "last_adjustment_chapter": None,
                },
                "canon": {
                    "conflicts": [
                        {
                            "type": "FUTURE_PROMISE_PAYOFF_DEVIATION",
                            "target": "chapter:3",
                            "executed_content_affected": False,
                        }
                    ],
                    "evidence_level": "CONTROLLED_PROOF",
                },
                "quality_trend": {"direction": "STABLE"},
            },
        },
        input_assets=(
            {
                "asset_version_id": str(reader["asset_version_id"]),
                "content_hash": str(reader["content_hash"]),
            },
            asset_ref("canon_snapshot"),
            asset_ref("character_state_snapshot"),
            asset_ref("foreshadow_snapshot"),
            asset_ref("reward_ledger_snapshot"),
            asset_ref("promise_ledger_snapshot"),
            *authority_inputs,
        ),
    )
    authority.followup.run_or_recover(
        BookFollowupAdmission(admission.operation_id, project_id, True)
    )
    return {
        "operation_id": admission.operation_id,
        "recap": _followup_output(
            authority.database_url,
            project_id=project_id,
            chapter_request_id=chapter_request_id,
            followup_type="LONGFORM_RECAP",
            output_key="longform.recap.report",
        ),
        "deviation": _followup_output(
            authority.database_url,
            project_id=project_id,
            chapter_request_id=chapter_request_id,
            followup_type="LONGFORM_RECAP",
            output_key="longform.recap.deviation_report",
        ),
        "replan_request": _followup_output(
            authority.database_url,
            project_id=project_id,
            chapter_request_id=chapter_request_id,
            followup_type="LONGFORM_RECAP",
            output_key="longform.recap.replan_request",
        ),
    }


def _drive_to_chapter_dispatch(
    supervisor: PostgresBookProductionSupervisor,
    *,
    book_run_id: str,
    chapter_number: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ticks: list[dict[str, Any]] = []
    book = supervisor.authority.require(book_run_id)
    active_request_id = str(book.get("active_chapter_request_id") or "")
    if active_request_id:
        request = supervisor.authority.require_chapter_request(active_request_id)
        if (
            int(request["chapter_number"]) != chapter_number
            or not str(request.get("chapter_root_operation_id") or "")
        ):
            raise RuntimeError("active Book Chapter request differs from resume target")
        return request, ticks
    for _ in range(12):
        tick = supervisor.tick(book_run_id)
        row = _jsonable(asdict(tick))
        ticks.append(row)
        print(
            json.dumps(
                {"phase": "book_supervisor", "chapter": chapter_number, **row},
                ensure_ascii=False,
            ),
            flush=True,
        )
        if tick.action is SupervisorAction.DISPATCH_CHAPTER:
            request = supervisor.authority.require_chapter_request(tick.evidence_ref)
            if int(request["chapter_number"]) != chapter_number:
                raise RuntimeError("Supervisor dispatched the wrong Chapter")
            return request, ticks
        if tick.action is SupervisorAction.GENERATE_CHAPTER_PLAN:
            # Future Chapter Plans are expected to be generated by the governed
            # Planning seam.  The next Supervisor tick freezes and dispatches
            # that durable Authority output.
            continue
        if tick.action in {
            SupervisorAction.GENERATE_CHAPTER_GROUP,
            SupervisorAction.START_REPLAN,
        }:
            raise RuntimeError(
                f"Supervisor unexpectedly generated missing Authority input: {tick.action}"
            )
    raise RuntimeError(f"Supervisor did not dispatch Chapter {chapter_number}")


def _accept_chapter(
    supervisor: PostgresBookProductionSupervisor,
    *,
    book_run_id: str,
    chapter_number: int,
) -> dict[str, Any]:
    tick = supervisor.tick(book_run_id)
    if tick.action is not SupervisorAction.ACCEPT_CHAPTER:
        raise RuntimeError(
            f"Supervisor did not accept Chapter {chapter_number}: {tick.action}"
        )
    book = supervisor.authority.require(book_run_id)
    if int(book["accepted_through_chapter"]) != chapter_number:
        raise RuntimeError("Book cursor did not advance sequentially")
    return _jsonable(asdict(tick))


def _run_book_phase(
    *,
    database_url: str,
    settings: IndustrialSettings,
    env: dict[str, str],
    chapter: Any,
    planning: Any,
    project_id: str,
    workspace_id: str,
    book_id: str,
    book_design_version: str,
    bootstrap: Mapping[str, str],
    activated: dict[str, str],
    projections: dict[int, dict[str, Any]],
    operator: Principal,
    commit_sha: str,
    build_id: str,
    stop_after_chapter: int = 0,
) -> dict[str, Any]:
    book_record = BookDesignAuthorityQuery(database_url).require_book(
        project_id=project_id, book_id=book_id
    )
    input_resolver = BookProductionInputResolver(
        database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    )
    authority = build_book_authority_application(
        settings, env=env, chapter_application=chapter
    )
    existing_books = _query_rows(
        database_url,
        """
        SELECT book_run_id, input_snapshot_id
        FROM authority_book_production
        WHERE project_id=%s AND book_id=%s
        """,
        (project_id, book_id),
    )
    if len(existing_books) > 1:
        raise RuntimeError("Book resume found multiple production runs")
    if existing_books:
        existing = existing_books[0]
        initial_snapshot = input_resolver.require(str(existing["input_snapshot_id"]))
        admission = SimpleNamespace(book_run_id=str(existing["book_run_id"]))
    else:
        initial_snapshot = input_resolver.resolve(
            ResolveBookProductionInputCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                production_profile=bootstrap["production_profile"],
                expected_book_version=int(book_record["version"]),
                actor_id=operator.principal_id,
                idempotency_key=f"{project_id}:book-input:initial",
                trace_id=f"trace:{project_id}:book-input:initial",
                correlation_id=f"correlation:{project_id}",
            ),
            principal=operator,
        )
        admission = authority.start(
            StartBookProductionCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=operator.principal_id,
                trace_id=f"trace:{project_id}:book-production",
                correlation_id=f"correlation:{project_id}",
                stable_idempotency_key=f"{project_id}:book-production",
                book_design_version=initial_snapshot.book_design_version,
                book_plan_version=initial_snapshot.book_plan_version,
                production_profile_version=(
                    initial_snapshot.production_profile_version
                ),
                longform_context_versions={
                    "volume_plan_version": (
                        initial_snapshot.current_volume_plan_version
                    ),
                    "arc_plan_version": initial_snapshot.active_arc_plan_versions[0],
                    "character_state_version": initial_snapshot.character_state_version,
                    "foreshadowing_state_version": (
                        initial_snapshot.foreshadowing_state_version
                    ),
                    "quality_trend_version": initial_snapshot.quality_trend_version,
                    "reward_ledger_version": initial_snapshot.reward_ledger_version,
                    "promise_ledger_version": initial_snapshot.promise_ledger_version,
                    "reader_segment_version": initial_snapshot.reader_segment_version,
                    "reader_contract_version": initial_snapshot.reader_contract_version,
                    "platform_profile_version": initial_snapshot.platform_profile_version,
                },
                target_chapter_count=3,
                light_recap_cadence=3,
                formal_recap_cadence=3,
                input_snapshot_id=initial_snapshot.snapshot_id,
                input_mode="RESOLVED_AUTHORITY_INPUT",
            ),
            principal=operator,
        )
    chapter_groups = PostgresChapterGroupAuthority(
        database_url,
        book_authority=authority,
        application_build_id=build_id,
        commit_sha=commit_sha,
    )
    supervisor = PostgresBookProductionSupervisor(
        authority,
        planning=planning,
        chapter_groups=chapter_groups,
        principal=operator,
    )
    worker = _principal(
        env["NOVEL_FORGE_AUTHORITY_WORKER_ID"],
        project_id,
        "chapter.authority.execute",
        worker=True,
    )
    supervisor_ticks: list[dict[str, Any]] = []
    chapter_ticks: dict[int, list[dict[str, Any]]] = {}
    chapter_requests: dict[int, dict[str, Any]] = {}
    reader_reports: dict[int, dict[str, Any]] = {}
    runtime_inputs: dict[str, str] = {}

    for chapter_number in (1, 2):
        checkpoint = authority.require(admission.book_run_id)
        if int(checkpoint["accepted_through_chapter"]) >= chapter_number:
            rows = _query_rows(
                database_url,
                """
                SELECT request.chapter_request_id
                FROM authority_book_chapter_request AS request
                JOIN authority_book_chapter_acceptance AS acceptance
                  ON acceptance.chapter_request_id=request.chapter_request_id
                 AND acceptance.project_id=request.project_id
                 AND acceptance.status='COMMITTED'
                WHERE request.book_run_id=%s AND request.project_id=%s
                  AND request.chapter_number=%s
                """,
                (admission.book_run_id, project_id, chapter_number),
            )
            if len(rows) != 1:
                raise RuntimeError(
                    f"accepted Chapter {chapter_number} has no unique request"
                )
            request = authority.require_chapter_request(
                str(rows[0]["chapter_request_id"])
            )
            chapter_requests[chapter_number] = request
            chapter_ticks[chapter_number] = []
            reader = _followup_output(
                database_url,
                project_id=project_id,
                chapter_request_id=str(request["chapter_request_id"]),
                followup_type="READER_OUTCOME",
                output_key="reader_outcome.report",
            )
            reader_reports[chapter_number] = reader
            runtime_inputs = _runtime_planning_inputs(
                authority,
                project_id=project_id,
                chapter_request_id=str(request["chapter_request_id"]),
                reader_report=reader,
            )
            continue
        request, dispatch_ticks = _drive_to_chapter_dispatch(
            supervisor,
            book_run_id=admission.book_run_id,
            chapter_number=chapter_number,
        )
        supervisor_ticks.extend(dispatch_ticks)
        chapter_requests[chapter_number] = request
        chapter_ticks[chapter_number] = _run_chapter_scheduler(
            chapter,
            database_url=database_url,
            project_id=project_id,
            root_operation_id=str(request["chapter_root_operation_id"]),
            operator=operator,
            worker=worker,
            commit_sha=commit_sha,
        )
        supervisor_ticks.append(
            _accept_chapter(
                supervisor,
                book_run_id=admission.book_run_id,
                chapter_number=chapter_number,
            )
        )
        reader, reader_ticks = _complete_reader_sidecar(
            supervisor,
            database_url=database_url,
            project_id=project_id,
            book_run_id=admission.book_run_id,
            chapter_request_id=str(request["chapter_request_id"]),
        )
        reader_reports[chapter_number] = reader
        supervisor_ticks.extend(reader_ticks)
        runtime_inputs = _runtime_planning_inputs(
            authority,
            project_id=project_id,
            chapter_request_id=str(request["chapter_request_id"]),
            reader_report=reader,
        )
        if stop_after_chapter == chapter_number:
            return {
                "stopped_after_chapter": chapter_number,
                "book_run": authority.require(admission.book_run_id),
                "initial_snapshot": initial_snapshot.to_dict(),
                "chapter_requests": chapter_requests,
                "reader_reports": reader_reports,
                "supervisor_ticks": supervisor_ticks,
                "chapter_ticks": chapter_ticks,
            }

    original_chapter_3, original_projection = _generate_chapter_plan(
        planning,
        chapter_number=3,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        book_design_version=book_design_version,
        bootstrap=bootstrap,
        activated=activated,
        runtime_inputs=runtime_inputs,
        principal=operator,
    )
    activated["chapter_plan.generate:3:original"] = original_chapter_3
    projections[3] = original_projection
    controlled_recap = _controlled_recap(
        authority,
        project_id=project_id,
        chapter_request_id=str(chapter_requests[2]["chapter_request_id"]),
        principal=operator,
    )
    plan_change = PostgresPlanChangeAuthority(
        database_url,
        story_design=planning.story_design,
        planning=planning.planning,
        application_build_id=build_id,
        commit_sha=commit_sha,
    )
    replan = BookReplanCoordinator(
        database_url,
        book_authority=authority,
        planning=planning,
        plan_change=plan_change,
        input_resolver=input_resolver,
        principal=operator,
    )
    command = CoordinateBookReplanCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        book_run_id=admission.book_run_id,
        source_recap_asset_version_id=str(controlled_recap["recap"]["asset_version_id"]),
        replan_request_asset_version_id=str(
            controlled_recap["replan_request"]["asset_version_id"]
        ),
        affected_scope="CHAPTER",
        target_asset_version_id=original_chapter_3,
        idempotency_key=f"{project_id}:replan:chapter:3",
        trace_id=f"trace:{project_id}:replan:chapter:3",
        correlation_id=str(controlled_recap["operation_id"]),
    )
    pending = replan.start(command)
    pending_replay = replan.start(command)
    approved = replan.approve(
        pending["replan_id"],
        authority_type="PLAN_CHANGE_AUTHORITY",
        authority_version="controlled-proof-operator-approval-v1",
        evidence={
            "evidence_level": "CONTROLLED_PROOF",
            "future_only": True,
            "human_behavior_claimed": False,
            "quality_calibration_claimed": False,
        },
    )
    resumed = replan.activate(pending["replan_id"])
    resumed_replay = replan.activate(pending["replan_id"])
    replacement_chapter_3 = str(
        replan.require(pending["replan_id"])["replacement_candidate_asset_version_id"]
    )
    activated["chapter_plan.generate:3:replacement"] = replacement_chapter_3
    projection = resumed.get("chapter_plan_projection")
    if isinstance(projection, Mapping):
        projections[3] = dict(projection)

    request, dispatch_ticks = _drive_to_chapter_dispatch(
        supervisor,
        book_run_id=admission.book_run_id,
        chapter_number=3,
    )
    supervisor_ticks.extend(dispatch_ticks)
    chapter_requests[3] = request
    chapter_ticks[3] = _run_chapter_scheduler(
        chapter,
        database_url=database_url,
        project_id=project_id,
        root_operation_id=str(request["chapter_root_operation_id"]),
        operator=operator,
        worker=worker,
        commit_sha=commit_sha,
    )
    supervisor_ticks.append(
        _accept_chapter(
            supervisor,
            book_run_id=admission.book_run_id,
            chapter_number=3,
        )
    )
    reader, reader_ticks = _complete_reader_sidecar(
        supervisor,
        database_url=database_url,
        project_id=project_id,
        book_run_id=admission.book_run_id,
        chapter_request_id=str(request["chapter_request_id"]),
    )
    reader_reports[3] = reader
    supervisor_ticks.extend(reader_ticks)

    final_recap: dict[str, Any] | None = None
    for _ in range(8):
        tick = supervisor.tick(admission.book_run_id)
        supervisor_ticks.append(_jsonable(asdict(tick)))
        try:
            final_recap = _followup_output(
                database_url,
                project_id=project_id,
                chapter_request_id=str(request["chapter_request_id"]),
                followup_type="LONGFORM_RECAP",
                output_key="longform.recap.report",
            )
        except RuntimeError:
            final_recap = None
        group_rows = _query_rows(
            database_url,
            """
            SELECT state FROM authority_chapter_group_production
            WHERE book_run_id=%s ORDER BY created_at DESC LIMIT 1
            """,
            (admission.book_run_id,),
        )
        if (
            final_recap is not None
            and len(group_rows) == 1
            and group_rows[0]["state"] == "COMPLETED"
        ):
            break
    if final_recap is None:
        raise RuntimeError("final deterministic Longform Recap did not succeed")
    final_book = authority.require(admission.book_run_id)
    if final_book["state"] != "COMPLETED":
        raise RuntimeError("three-Chapter Book did not complete")
    return {
        "book_run": final_book,
        "initial_snapshot": initial_snapshot.to_dict(),
        "new_snapshot_id": resumed["input_snapshot_id"],
        "chapter_requests": chapter_requests,
        "reader_reports": reader_reports,
        "controlled_recap": controlled_recap,
        "final_recap": final_recap,
        "replan": {
            "pending": pending,
            "pending_replay": pending_replay,
            "approved": approved,
            "resumed": resumed,
            "resumed_replay": resumed_replay,
            "original_chapter_3": original_chapter_3,
            "replacement_chapter_3": replacement_chapter_3,
        },
        "supervisor_ticks": supervisor_ticks,
        "chapter_ticks": chapter_ticks,
    }


def _resume_book_phase(args: argparse.Namespace) -> dict[str, Any]:
    source_path = Path(args.resume_planning_output).expanduser().resolve()
    source = json.loads(source_path.read_text(encoding="utf-8"))
    commit_sha = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    dirty = _git("status", "--porcelain", "--untracked-files=normal")
    if source["release"]["commit_sha"] != commit_sha:
        raise RuntimeError("resume Planning evidence belongs to another HEAD")
    if branch != BRANCH:
        raise RuntimeError(f"unexpected proof branch: {branch}")
    if dirty and not args.allow_dirty:
        raise RuntimeError("exact-HEAD proof requires a clean Git worktree")
    executable = str(Path(args.codex_executable).expanduser().resolve())
    login = subprocess.run(
        (executable, "login", "status"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    runtime_root.mkdir(parents=True, exist_ok=False)
    env = _runtime_env(
        commit_sha=commit_sha,
        codex_executable=executable,
        runtime_root=runtime_root,
        worker_id="chapter-worker:short-longform-real-proof",
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    env.update(
        {
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "short-longform-real-proof",
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": PLANNING_PACK_ID,
            "NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID": READER_PACK_ID,
            "NOVEL_FORGE_STORY_PLANNING_WORKER_ID": (
                "planning-worker:short-longform-real-proof"
            ),
            "NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID": (
                "reader-worker:short-longform-real-proof"
            ),
            "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP": "100.00",
            "NOVEL_FORGE_PROVIDER_DAILY_CAP": "100.00",
            "NOVEL_FORGE_DAILY_PROVIDER_CAP": "100.00",
        }
    )
    proof_buckets = _proof_bucket_names(runtime_root)
    settings = IndustrialSettings(
        root=ROOT,
        environment="production",
        storage_authority="postgresql",
        database_url=args.database_url,
        minio_endpoint=args.minio_endpoint,
        minio_access_key=args.minio_access_key,
        minio_secret_key=args.minio_secret_key,
        minio_secure=args.minio_secure,
        minio_raw_bucket=proof_buckets["raw"],
        minio_artifact_bucket=proof_buckets["artifact"],
        minio_export_bucket=proof_buckets["export"],
    )
    run_migrations(args.database_url)
    MinioObjectStore(settings).ensure_buckets()
    authority_source = dict(source["authority"])
    project_id = str(authority_source["project_id"])
    workspace_id = str(authority_source["workspace_id"])
    book_id = str(authority_source["book_id"])
    operator = _principal(
        f"operator:{project_id}",
        project_id,
        "project.authority.execute",
        "book_design.authority.execute",
        "book.authority.execute",
        "book.followup:*",
        "chapter.authority.execute",
        "story_design.authority.execute",
        "story_planning.authority.execute",
        "story_planning.authority.approve",
        "story_planning.authority.activate",
    )
    chapter = build_chapter_authority_application(settings, env=env)
    planning = build_story_planning_generation_application(
        settings, env=env, chapter_application=chapter
    )
    activated = dict(authority_source["activated_plans"])
    projections = {
        int(key): dict(value)
        for key, value in authority_source["chapter_plan_projections"].items()
    }
    book_record = BookDesignAuthorityQuery(args.database_url).require_book(
        project_id=project_id, book_id=book_id
    )
    chapter_profiles = _bootstrap_chapter_profiles(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=env["NOVEL_FORGE_APPLICATION_BUILD_ID"],
        commit_sha=commit_sha,
        principal=operator,
    )
    try:
        book_phase = _run_book_phase(
            database_url=args.database_url,
            settings=settings,
            env=env,
            chapter=chapter,
            planning=planning,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            book_design_version=str(book_record["active_book_design_version_id"]),
            bootstrap=dict(authority_source["bootstrap"]),
            activated=activated,
            projections=projections,
            operator=operator,
            commit_sha=commit_sha,
            build_id=env["NOVEL_FORGE_APPLICATION_BUILD_ID"],
            stop_after_chapter=args.stop_after_chapter,
        )
    finally:
        chapter.close()
    source["created_at"] = datetime.now().astimezone().isoformat()
    source["release"] = {
        "branch": branch,
        "commit_sha": commit_sha,
        "worktree_clean": not bool(dirty),
        "allow_dirty": bool(args.allow_dirty),
    }
    source["runtime"]["codex_login_status"] = (
        login.stdout or login.stderr
    ).strip()
    source["authority"]["activated_plans"] = activated
    source["authority"]["chapter_plan_projections"] = projections
    source["authority"]["chapter_profiles"] = chapter_profiles
    source["authority"]["book_phase"] = _jsonable(book_phase)
    source["planning_evidence"] = _jsonable(
        _collect_planning_evidence(args.database_url, project_id=project_id)
    )
    source["phase"] = "SHORT_LONGFORM_COMPLETE"
    return source


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.resume_planning_output:
        return _resume_book_phase(args)
    commit_sha = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    dirty = _git("status", "--porcelain", "--untracked-files=normal")
    if branch != BRANCH:
        raise RuntimeError(f"unexpected proof branch: {branch}")
    if dirty and not args.allow_dirty:
        raise RuntimeError("exact-HEAD proof requires a clean Git worktree")
    executable = str(Path(args.codex_executable).expanduser().resolve())
    login = subprocess.run(
        (executable, "login", "status"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    runtime_root.mkdir(parents=True, exist_ok=False)
    env = _runtime_env(
        commit_sha=commit_sha,
        codex_executable=executable,
        runtime_root=runtime_root,
        worker_id="chapter-worker:short-longform-real-proof",
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    env.update(
        {
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "short-longform-real-proof",
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": PLANNING_PACK_ID,
            "NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID": READER_PACK_ID,
            "NOVEL_FORGE_STORY_PLANNING_WORKER_ID": (
                "planning-worker:short-longform-real-proof"
            ),
            "NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID": (
                "reader-worker:short-longform-real-proof"
            ),
            "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP": "100.00",
            "NOVEL_FORGE_PROVIDER_DAILY_CAP": "100.00",
            "NOVEL_FORGE_DAILY_PROVIDER_CAP": "100.00",
        }
    )
    proof_buckets = _proof_bucket_names(runtime_root)
    settings = IndustrialSettings(
        root=ROOT,
        environment="production",
        storage_authority="postgresql",
        database_url=args.database_url,
        minio_endpoint=args.minio_endpoint,
        minio_access_key=args.minio_access_key,
        minio_secret_key=args.minio_secret_key,
        minio_secure=args.minio_secure,
        minio_raw_bucket=proof_buckets["raw"],
        minio_artifact_bucket=proof_buckets["artifact"],
        minio_export_bucket=proof_buckets["export"],
    )
    migration = run_migrations(args.database_url)
    MinioObjectStore(settings).ensure_buckets()
    suffix = uuid4().hex[:12]
    project_id = f"short-longform-proof:{commit_sha[:8]}:{suffix}"
    workspace_id = f"workspace:{project_id}"
    book_id = f"book:{project_id}"
    build_id = env["NOVEL_FORGE_APPLICATION_BUILD_ID"]
    operator = _principal(
        f"operator:{project_id}",
        project_id,
        "project.authority.execute",
        "book_design.authority.execute",
        "book.authority.execute",
        "book.followup:*",
        "chapter.authority.execute",
        "story_design.authority.execute",
        "story_planning.authority.execute",
        "story_planning.authority.approve",
        "story_planning.authority.activate",
    )
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
    )
    bootstrap = _bootstrap_assets(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        principal=operator,
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
        ROOT,
        operation_definition_hash=planning_hash,
        pack_id=PLANNING_PACK_ID,
    )
    reader_profile = build_reader_outcome_pack_profile(
        ROOT,
        operation_definition_hash=reader_hash,
        pack_id=READER_PACK_ID,
    )
    planning_pack = _install_profile(
        args.database_url,
        profile=planning_profile,
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
    chapter = build_chapter_authority_application(settings, env=env)
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
    planning, activated, projections, retry = _run_planning(
        database_url=args.database_url,
        settings=settings,
        env=env,
        chapter=chapter,
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
    )
    planning_evidence = _collect_planning_evidence(
        args.database_url, project_id=project_id
    )
    planning_result = {
        "schema_version": "novel-forge.short-longform-runtime-proof.v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "release": {
            "branch": branch,
            "commit_sha": commit_sha,
            "worktree_clean": not bool(dirty),
            "allow_dirty": bool(args.allow_dirty),
        },
        "runtime": {
            "environment": "provider-validation",
            "provider": "codex-cli",
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "codex_login_status": (login.stdout or login.stderr).strip(),
            "cost_semantics": "MEASURED usage, ESTIMATED cost, not provider billed",
        },
        "authority": {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "migration": _jsonable(migration),
            "bootstrap": bootstrap,
            "chapter_profiles": chapter_profiles,
            "planning_pack": _jsonable(planning_pack),
            "reader_pack": _jsonable(reader_pack),
            "chapter_pack": _jsonable(chapter_pack),
            "activated_plans": activated,
            "chapter_plan_projections": projections,
        },
        "retry": _jsonable(retry),
        "planning_evidence": _jsonable(planning_evidence),
        "phase": "PLANNING_COMPLETE",
        "proof_flags": {
            "planning_real_provider_proven": False,
            "reader_outcome_real_provider_proven": False,
            "real_provider_attempt_retry_proven": False,
            "book_authority_command_boundary_proven": False,
            "three_chapter_continuity_proven": False,
            "longform_recap_proven": False,
            "replan_loop_proven": False,
            "resume_after_replan_proven": False,
            "short_longform_runtime_proven": False,
        },
        "non_claims": {
            "quality_calibrated": False,
            "longform_proven": False,
            "production_verified": False,
            "multi_book_proven": False,
        },
    }
    if args.stop_after_planning:
        chapter.close()
        return planning_result
    try:
        book_phase = _run_book_phase(
            database_url=args.database_url,
            settings=settings,
            env=env,
            chapter=chapter,
            planning=planning,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            book_design_version=str(book["active_book_design_version_id"]),
            bootstrap=bootstrap,
            activated=activated,
            projections=projections,
            operator=operator,
            commit_sha=commit_sha,
            build_id=build_id,
            stop_after_chapter=args.stop_after_chapter,
        )
    finally:
        chapter.close()
    planning_result["authority"]["book_phase"] = _jsonable(book_phase)
    planning_result["authority"]["activated_plans"] = activated
    planning_result["authority"]["chapter_plan_projections"] = projections
    planning_result["phase"] = "SHORT_LONGFORM_COMPLETE"
    return planning_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--codex-executable",
        default="/Applications/ChatGPT.app/Contents/Resources/codex",
    )
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--minio-endpoint", default="127.0.0.1:59039")
    parser.add_argument("--minio-access-key", default="novel_forge")
    parser.add_argument("--minio-secret-key", default="novel_forge_secret")
    parser.add_argument("--minio-secure", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument(
        "--stop-after-planning",
        action="store_true",
        help="Persist a resumable exact-HEAD Planning Authority checkpoint.",
    )
    parser.add_argument(
        "--resume-planning-output",
        default="",
        help="Resume the Book phase from this exact-HEAD Planning proof JSON.",
    )
    parser.add_argument(
        "--stop-after-chapter",
        type=int,
        choices=(1, 2),
        default=0,
        help="Stop after durable Chapter acceptance and Reader sidecar completion.",
    )
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = _run(args)
    except BaseException as exc:
        failure = {
            "schema_version": "novel-forge.short-longform-runtime-proof.failure.v1",
            "created_at": datetime.now().astimezone().isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        output.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise
    output.write_text(
        json.dumps(_jsonable(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result["proof_flags"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
