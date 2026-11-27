"""INVARIANT: Book prose D0 consumes one native, independently owned review window."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

from novel_forge.api.authority_dependencies import (
    build_book_followup_authority_application,
    build_production_execution_composition,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.creation_runtime import (
    creation_runtime_environment,
)
from novel_forge.modules.book_followup_authority.prose_coordinator import (
    BookProseReviewCoordinator,
)
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.provider_qualification import (
    D0LiveQualificationEvidence,
    D0ProbeConfig,
    D0QualificationAuthority,
    D0QualificationCommand,
)
from novel_forge.modules.provider_qualification.accounting import (
    accounting_scope_from_cost,
)
from novel_forge.modules.provider_qualification.domain import request_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.object_store import MinioObjectStore


CAPABILITY = "model.longform_prose_review"


class ConsumerRestartRequired(RuntimeError):
    pass


class WindowResponseLoss:
    def __init__(self, delegate, *, database_url, scope, window):
        self.delegate, self.database_url, self.scope, self.window = (
            delegate,
            database_url,
            scope,
            window,
        )
        self.triggered, self.operation_id = False, None

    def __getattr__(self, key):
        return getattr(self.delegate, key)

    def session_for_project(self, project_id):
        if self.triggered:
            raise ConsumerRestartRequired(
                "Rebuild the qualification consumer before saved-result recovery"
            )
        return self.delegate.session_for_project(project_id)

    def execute(self, *, stable_idempotency_key, capability, request_payload):
        target = (
            capability == CAPABILITY
            and request_payload.get("stage") == "longform_prose_review"
        )
        if target:
            metadata = request_payload.get("_production_execution") or {}
            operation_id = metadata.get("operation_id")
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """SELECT operation.project_id,operation.workspace_id,operation.actor_id,
                    operation.command_payload,operation.input_asset_snapshot
                    FROM authority_operation operation JOIN authority_book_prose_review_event event
                    ON event.content->>'operation_id'=operation.operation_id
                    WHERE event.run_id=%s AND event.kind='WINDOW_ADMITTED' AND operation.operation_id=%s
                      AND event.content->>'window_id'=%s AND operation.definition_name='longform.prose_review'""",
                    [self.scope["run_id"], operation_id, self.window["window_id"]],
                )
                rows = uow.cursor.fetchall()
            validate_window_request(rows, self.scope, self.window, metadata)
            if self.operation_id not in {None, operation_id}:
                raise ValueError("D0 cannot change its original review Operation")
            self.operation_id = operation_id
        result = self.delegate.execute(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
        )
        if target and not self.triggered and result.outcome == "success":
            self.triggered = True
            raise ExternalEffectAdapterError(
                "Book prose qualification lost the response after durable completion",
                request_sent=True,
                failure_kind="response_loss",
            )
        return result


def require_unknown_checkpoint(database_url, operation_id):
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT effect.external_effect_id,effect.status,dispatch.status,dispatch.evidence,
            (SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=effect.external_effect_id),
            (SELECT count(*) FROM authority_external_receipt receipt JOIN authority_external_effect_dispatch d USING(dispatch_id)
                WHERE d.external_effect_id=effect.external_effect_id),
            (SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=effect.external_effect_id AND outcome='success')
            FROM authority_external_effect effect JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
            WHERE effect.operation_id=%s AND effect.capability=%s""",
            [operation_id, CAPABILITY],
        )
        rows = uow.cursor.fetchall()
    if (
        len(rows) != 1
        or rows[0][1] not in {"UNKNOWN", "RECONCILIATION_REQUIRED"}
        or rows[0][2] != "UNKNOWN"
        or rows[0][3].get("failure_kind") != "response_loss"
        or rows[0][3].get("request_sent") is not True
        or rows[0][4:] != (1, 0, 0)
    ):
        raise ValueError(
            "Old qualification consumer must retain UNKNOWN with one dispatch and no accepted result"
        )
    return dict(
        external_effect_id=rows[0][0],
        effect_status=rows[0][1],
        dispatch_count=1,
        receipt_count=0,
        reconciliation_count=0,
    )


def validate_window_request(rows, scope, window, metadata):
    if len(rows) != 1:
        raise ValueError("D0 requires its exact native review admission")
    project, workspace, actor, command, inputs = rows[0]
    payload = command.get("payload", command)
    pointers = [
        item
        for item in metadata.get("input_artifacts", [])
        if item.get("artifact_type") == "longform_prose_review_window"
    ]
    binding = window["input_asset"]
    if (
        (project, workspace, actor)
        != (scope["project_id"], scope["workspace_id"], scope["actor_id"])
        or payload.get("book_id") != scope["book_id"]
        or metadata.get("book_id") != scope["book_id"]
        or metadata.get("project_id") != scope["project_id"]
        or metadata.get("workspace_id") != scope["workspace_id"]
        or any(
            payload.get(key) != scope[key] for key in ("book_run_id", "manifest_digest")
        )
        or payload.get("window_id") != window["window_id"]
        or len(inputs) != 1
        or len(pointers) != 1
        or any(
            inputs[0].get(key) != value or pointers[0].get(key) != value
            for key, value in binding.items()
        )
    ):
        raise ValueError(
            "D0 review Book, author, window or frozen source identity changed"
        )


def require_review_scope(report, *, commit_sha, allow_controlled_replay=False):
    policy = report["manifest"]["policy"]
    if (
        report["exact_release_sha"] != commit_sha
        or report["paused"]
        or not report["source_current"]
        or len(report["manifest"]["windows"]) != 1
        or policy.get("execution_mode") != "MANUAL"
        or policy.get("window_selection") != "EXPLICIT_RANGES_ONLY"
        or policy.get("source_current_policy") != "FROZEN_SELECTED_RANGE"
        or policy.get("follow_acceptance", False)
    ):
        raise ValueError(
            "D0 requires one current, unpaused, manually frozen native review window"
        )
    if report["operations"] and not allow_controlled_replay:
        raise ValueError(
            "D0 must not redispatch a reused or already admitted review window"
        )


def require_controlled_review(database_url, *, report, scope, principal):
    operations = report["operations"]
    if (
        len(operations) != 1
        or operations[0].get("source_run_id")
        or operations[0].get("source_operation_id", operations[0]["operation_id"])
        != operations[0]["operation_id"]
    ):
        raise ValueError("D0 cannot borrow another review or a replacement Root")
    operation_id = operations[0]["operation_id"]
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT operation.actor_id,operation.command_payload
            FROM authority_operation operation WHERE project_id=%s AND definition_name='book.prose_review.advance'
            AND idempotency_key=%s AND idempotency_scope='project:book.prose_review.advance'""",
            [scope["project_id"], "book-prose-d0:" + scope["run_id"]],
        )
        control = uow.cursor.fetchone()
        expected = {**scope, "expected_version": 0}
        if not control or control != (principal.principal_id, expected):
            raise ValueError(
                "D0 recovery requires its exact original author advancement"
            )
        uow.cursor.execute(
            """SELECT effect.status,dispatch.evidence FROM authority_external_effect effect
            JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
            WHERE effect.operation_id=%s AND effect.capability=%s""",
            [operation_id, CAPABILITY],
        )
        rows = uow.cursor.fetchall()
    if (
        len(rows) != 1
        or rows[0][0] not in {"SUCCEEDED", "UNKNOWN", "RECONCILIATION_REQUIRED"}
        or rows[0][1].get("failure_kind") != "response_loss"
        or rows[0][1].get("request_sent") is not True
    ):
        raise ValueError(
            "D0 requires the original durable response-loss observation before recovery"
        )
    return operation_id


def run_book_prose_qualification(args, *, root: Path, commit_sha: str):
    from scripts import run_real_provider_qualification as base

    env = creation_runtime_environment(args.source_project_id, os.environ)
    if env.get("NOVEL_FORGE_COMMIT_SHA") != commit_sha:
        raise ValueError(
            "Book prose qualification requires its existing exact runtime release"
        )
    settings = IndustrialSettings.from_env(root=root)
    if settings.database_url != args.database_url:
        raise ValueError("Qualification cannot substitute another Book database")
    principal = build_trusted_principal_resolver(env=env).resolve_api_principal()
    principal.require("book.authority.execute", args.source_project_id)
    principal.require("book.followup:longform.prose_review", args.source_project_id)
    principal.require("external_effect.resolve", args.source_project_id)
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute(
            "SELECT workspace_id,book_id FROM authority_book_production WHERE project_id=%s AND book_run_id=%s",
            [args.source_project_id, args.book_run_id],
        )
        row = uow.cursor.fetchone()
    if not row:
        raise ValueError("Qualification requires the existing native Book")
    scope = dict(
        project_id=args.source_project_id,
        workspace_id=row[0],
        book_run_id=args.book_run_id,
        run_id=args.prose_review_run_id,
    )
    execution = build_production_execution_composition(settings, env=env)
    try:
        coordinator = BookProseReviewCoordinator(
            BookFollowupAuthorityApplication(
                settings.database_url,
                application_build_id=env["NOVEL_FORGE_APPLICATION_BUILD_ID"],
                commit_sha=commit_sha,
            )
        )
        report = coordinator.report(**scope, principal=principal)
        require_review_scope(
            report, commit_sha=commit_sha, allow_controlled_replay=True
        )
        route = execution.gateway.routes["longform_prose_review"]
        if (
            route.model_profile.model_provider,
            route.model_profile.model_id,
            route.model_profile.reasoning_effort,
        ) != (args.provider, args.model, args.reasoning_effort):
            raise ValueError("D0 options differ from the existing Book Provider route")
        readiness_env = {
            **env,
            "NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_METHOD": route.token_accounting_method,
            "NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_EVIDENCE_REF": route.token_accounting_evidence_ref,
            "NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT": str(route.model_context_limit),
        }
        preflight = base._current_preflight(
            args, readiness_env=readiness_env, capability=CAPABILITY
        )
        if (
            preflight["status"] != "READY_FOR_LIVE_QUALIFICATION"
            or args.preflight_only
            or not args.execute
        ):
            return {
                **preflight,
                "scope": scope,
                "provider_request_sent": False,
                "qualification_execution": "NOT_RUN",
            }
        advance = dict(
            idempotency_key="book-prose-d0:" + args.prose_review_run_id,
            trace_id="trace:book-prose-d0:" + args.prose_review_run_id,
            correlation_id=args.prose_review_run_id,
            expected_version=0,
        )
        if report["operations"]:
            original_operation_id = require_controlled_review(
                settings.database_url,
                report=report,
                scope=scope,
                principal=principal,
            )
        else:
            if report["expected_version"] != 0:
                raise ValueError(
                    "D0 requires an unchanged fresh review control boundary"
                )
            fault = WindowResponseLoss(
                execution.gateway,
                database_url=settings.database_url,
                scope={
                    **scope,
                    "book_id": row[1],
                    "manifest_digest": report["manifest_digest"],
                    "actor_id": principal.principal_id,
                },
                window=report["manifest"]["windows"][0],
            )
            coordinator = BookProseReviewCoordinator(
                build_book_followup_authority_application(
                    settings, execution=replace(execution, gateway=fault), env=env
                )
            )
            try:
                coordinator.advance(**scope, **advance, principal=principal)
            except ConsumerRestartRequired:
                pass
            except KernelError as error:
                if error.code != "EFFECT_EXTERNAL_STATE_UNKNOWN" or not fault.triggered:
                    raise
            if not fault.triggered or not fault.operation_id:
                raise ValueError("No exact native response-loss boundary was observed")
            original_operation_id = fault.operation_id
            require_unknown_checkpoint(settings.database_url, original_operation_id)
    finally:
        execution.close()
    recovered = build_production_execution_composition(settings, env=env)
    try:
        followup = build_book_followup_authority_application(
            settings, execution=recovered, env=env
        )
        followup.run_or_recover(
            BookFollowupAdmission(original_operation_id, scope["project_id"], True)
        )
        base._effect_evidence(
            settings.database_url,
            operation_id=original_operation_id,
            capability=CAPABILITY,
        )
        coordinator = BookProseReviewCoordinator(followup)
        final = coordinator.advance(**scope, **advance, principal=principal)
        replay = coordinator.advance(**scope, **advance, principal=principal)
        if (
            len(final["operations"]) != 1
            or final["operations"][0]["operation_id"] != original_operation_id
            or final["operations"][0]["status"] != "SUCCEEDED"
            or final["operations"] != replay["operations"]
        ):
            raise ValueError(
                "D0 requires original Operation completion and deterministic replay, never an isolated successor"
            )
    finally:
        recovered.close()
    return qualify_native_effect(
        base,
        settings=settings,
        scope={**scope, "book_id": row[1]},
        principal=principal,
        operation_id=original_operation_id,
        commit_sha=commit_sha,
        preflight=preflight,
    )


def qualify_native_effect(
    base, *, settings, scope, principal, operation_id, commit_sha, preflight
):
    effect, provider, dispatches, receipts, reconciliations, _ = base._effect_evidence(
        settings.database_url, operation_id=operation_id, capability=CAPABILITY
    )
    production = provider["production_execution"]
    request, handle, result, route = (
        production[key]
        for key in (
            "execution_request",
            "execution_handle",
            "execution_result",
            "route_snapshot",
        )
    )
    if (
        request["project_id"],
        request["workspace_id"],
        request["book_id"],
        route["release_sha"],
    ) != (
        scope["project_id"],
        scope["workspace_id"],
        scope["book_id"],
        commit_sha,
    ):
        raise ValueError("D0 receipt scope or release changed")
    runtime = provider["capability_runtime"]
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute(
            "SELECT request_timeout_seconds FROM authority_external_effect WHERE external_effect_id=%s",
            [effect["external_effect_id"]],
        )
        timeout = int(uow.cursor.fetchone()[0])
    config = D0ProbeConfig.from_mapping(
        dict(
            schema_version="d0-provider-probe-config.v1",
            provider=provider["provider_id"],
            backend_id=handle["backend_id"],
            model_env="NOVEL_FORGE_QUALITY_MODEL",
            model_version_env="NOVEL_FORGE_D0_MODEL_VERSION",
            route_policy_version=f"{route['policy_id']}@{route['policy_version']}",
            timeout_seconds=timeout,
            auth_secret_ref="env://NOVEL_FORGE_PROVIDER_AUTH_PROFILE",
            capability=CAPABILITY,
            prompt_version=provider["prompt_version"],
            prompt_hash=runtime["prompt_template"]["content_hash"],
            instruction_version=runtime["system_instruction"]["version"],
            instruction_hash=runtime["system_instruction"]["content_hash"],
            skill_version=provider["skill_version"],
            skill_hash=runtime["skill"]["content_hash"],
            accounting_scope=accounting_scope_from_cost(provider["cost"]),
        )
    )
    identity = preflight["implementation_identity"]
    command = D0QualificationCommand(
        project_id=scope["project_id"],
        workspace_id=scope["workspace_id"],
        actor_id=principal.principal_id,
        idempotency_key="book-prose-d0:" + effect["external_effect_id"],
        trace_id="trace:book-prose-d0:" + effect["external_effect_id"],
        correlation_id=scope["run_id"],
        config=config,
        resolved_model=provider["model_id"],
        resolved_model_version="provider-not-reported",
        resolved_auth_profile_ref=route["auth_profile_ref"],
        implementation_identity=identity,
    )
    store = MinioObjectStore(settings)
    request_ref = store.put_json(
        object_key=f"d0/book-prose/{effect['external_effect_id']}/request.json",
        payload=effect,
    )
    response_ref = store.put_json(
        object_key=f"d0/book-prose/{effect['external_effect_id']}/response.json",
        payload={"provider_evidence": provider},
    )
    evidence = D0LiveQualificationEvidence.from_mapping(
        dict(
            schema_version="d0-live-qualification-evidence.v1",
            release_sha=commit_sha,
            implementation_identity=identity,
            source_operation_id=operation_id,
            external_effect_id=effect["external_effect_id"],
            request_object_ref=request_ref,
            response_object_ref=response_ref,
            auth_profile_ref=route["auth_profile_ref"],
            provider=provider["provider_id"],
            backend_id=handle["backend_id"],
            model=provider["model_id"],
            model_version=command.resolved_model_version,
            route_snapshot_id=route["route_snapshot_id"],
            route_snapshot_hash=request_hash(route),
            prompt_version=config.prompt_version,
            prompt_hash=config.prompt_hash,
            instruction_version=config.instruction_version,
            instruction_hash=config.instruction_hash,
            skill_version=config.skill_version,
            skill_hash=config.skill_hash,
            request_hash=effect["request_hash"],
            response_hash=request_hash(provider),
            provider_execution_id=request["execution_id"],
            provider_request_identity=handle.get("provider_request_id")
            or handle.get("external_request_id")
            or handle.get("local_execution_receipt_id"),
            usage=provider["usage"],
            cost=provider["cost"],
            latency={"duration_ms": base._duration_ms(result)},
            controlled_failure=dict(
                checkpoint="after_provider_response_before_effect_receipt",
                failure_kind="response_loss",
                request_sent=True,
            ),
            recovery=dict(
                external_state_was_ambiguous=True,
                recovered_without_resend=True,
                replayed=True,
            ),
            fixture_protocol_only=False,
            real_model_call=True,
        )
    )
    decision = D0QualificationAuthority(
        settings.database_url,
        evidence_store=store,
        application_build_id="book-prose-qualification:" + commit_sha,
        commit_sha=commit_sha,
        implementation_identity=identity,
    ).execute_live(command, evidence)
    return dict(
        schema_version="book-prose-runtime-qualification.v1",
        result="PASS",
        qualification=decision,
        scope=scope,
        source_operation_id=operation_id,
        external_effect_id=effect["external_effect_id"],
        dispatch_count=dispatches,
        receipt_count=receipts,
        reconciliation_count=reconciliations,
        accounting_scope=config.accounting_scope,
        usage=evidence.usage,
        cost=evidence.cost,
        release_sha=commit_sha,
        implementation_identity=identity,
        proof_scope=base.PROOF_SCOPE,
        literary_qualification="NOT_PROVEN",
        manuscript_mutation_allowed=False,
    )
