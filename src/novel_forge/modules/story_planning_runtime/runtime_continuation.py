
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .domain import StoryPlanningGenerationCommand, canonical_hash

DEFINITION_NAME = "story_planning.runtime_continuation.register"
HANDLER_KEY = "novel_forge.story_planning.runtime_continuation.register"
OUTPUT_KEY = "story_planning.runtime_continuation"


def runtime_continuation_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": DEFINITION_NAME,
        "definition_version": "1.0.0",
        "family": "story_planning_runtime",
        "command_schema_version": "planning-runtime-continuation.command.v1",
        "result_schema_version": "planning-runtime-continuation.result.v1",
        "enabled": True,
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {
            "asset_type": "planning_runtime_continuation",
            "output_key": OUTPUT_KEY,
        },
        "handler_key": HANDLER_KEY,
        "handler_contract_version": "planning-runtime-continuation.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["story_planning.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "trusted_operator_required": True,
            "zero_dispatch_required": True,
        },
        "idempotency_scope": "book:planning-runtime-continuation",
        "concurrency_key_template": "book:{book_id}:planning-runtime-continuation",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable_atomic"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable continuation registration",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["story_planning_runtime"],
        "migration_owner": "story-planning-runtime",
        "completion_contract": {
            "version": "planning-runtime-continuation-completion.v1",
            "required_asset_selectors": [
                {
                    "selector": "planning_runtime_continuation",
                    "output_key": OUTPUT_KEY,
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [
                "story_planning.runtime_continuation.registered"
            ],
        },
    }


def require_source(
    uow: AuthorityUnitOfWork, *, source_operation_id: str, project_id: str
) -> dict[str, Any]:
    uow.cursor.execute(
        "SELECT op.status, op.version, op.workspace_id, op.command_payload->'payload', g.book_id, g.candidate_asset_version_id FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.operation_id=%s AND op.project_id=%s FOR UPDATE OF op",
        [source_operation_id, project_id],
    )
    row = uow.cursor.fetchone()
    if row is None or row[0] not in {"CANCELLED","FAILED_FINAL"} or row[5]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SOURCE_INVALID",
            "source must be this project's cancelled generation with no Candidate",
        )
    frozen = dict(row[3])
    if (
        frozen.get("project_id"),
        frozen.get("workspace_id"),
        frozen.get("book_id"),
    ) != (project_id, str(row[2]), str(row[4])):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SCOPE_INVALID",
            "source command differs from its native Book scope",
        )
    uow.cursor.execute(
        "SELECT status, error, result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1",
        [source_operation_id],
    )
    attempt = uow.cursor.fetchone()
    if (
        attempt is None
        or attempt[0] not in {"FAILED_RETRYABLE", "FAILED_FINAL"}
        or (
            dict(attempt[1] or {}).get("error_code")
            or dict(attempt[2] or {}).get("error_code")
        )
        not in {"EXECUTION_CONTRACT_FROZEN_CONFLICT", "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "PROVIDER_ROUTING_BLOCKED", "NATIVE_PLANNING_REPAIR_SOURCE_INVALID"}
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED",
            "only a retained execution-contract or undispatched result-repair Context failure permits runtime continuation",
        )
    preflight_code = dict(attempt[1] or {}).get("error_code") or dict(attempt[2] or {}).get("error_code")
    if (row[0] == "FAILED_FINAL") != (preflight_code == "NATIVE_PLANNING_REPAIR_SOURCE_INVALID"):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_SOURCE_INVALID","Terminal history only permits the proven undispatched input-order recovery")
    if preflight_code in {"PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED","PROVIDER_ROUTING_BLOCKED","NATIVE_PLANNING_REPAIR_SOURCE_INVALID"}:
        from .preflight_continuation import require_capacity_source
        return require_capacity_source(uow, source_operation_id=source_operation_id, project_id=project_id,
            frozen=frozen, version=int(row[1]),routing_failure=preflight_code == "PROVIDER_ROUTING_BLOCKED",
            input_order_failure=preflight_code == "NATIVE_PLANNING_REPAIR_SOURCE_INVALID")
    uow.cursor.execute(
        "SELECT external_effect_id, status, provider, model_id, request_payload FROM authority_external_effect WHERE operation_id=%s AND project_id=%s ORDER BY external_effect_id FOR UPDATE",
        [source_operation_id, project_id],
    )
    effects = uow.cursor.fetchall()
    uow.cursor.execute(
        "SELECT count(*) FROM authority_external_effect_dispatch dispatch JOIN authority_external_effect effect USING(external_effect_id) WHERE effect.operation_id=%s AND effect.project_id=%s",
        [source_operation_id, project_id],
    )
    dispatched = int(uow.cursor.fetchone()[0])
    uow.cursor.execute(
        "SELECT status FROM authority_budget_reservation WHERE operation_id=%s AND project_id=%s FOR UPDATE",
        [source_operation_id, project_id],
    )
    reservations = uow.cursor.fetchall()
    if (
        not effects
        or any(effect[1] != "CANCELLED" for effect in effects)
        or dispatched
        or not reservations
        or any(reservation[0] != "RELEASED" for reservation in reservations)
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "continuation requires cancelled zero-dispatch Effects and released reservations",
        )
    if len(effects) != 1:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_EFFECT_SCOPE_INVALID",
            "this bounded continuation supports one frozen Planning Provider intent",
        )
    uow.cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [source_operation_id],
    )
    snapshot_row = uow.cursor.fetchone()
    if snapshot_row is None:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING",
            "the failed runtime must have retained its exact Pack snapshot",
        )
    snapshot = dict(snapshot_row[0])
    request = dict(effects[0][4])
    capability = dict(
        dict(request.get("_production_execution") or {}).get("capability_runtime") or {}
    )
    evidence_id = str(capability.get("provider_admission_asset_version_id") or "")
    uow.cursor.execute(
        "SELECT version.content_hash, asset.asset_type, version.content FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE output.operation_id=%s AND output.asset_version_id=%s",
        [source_operation_id, evidence_id],
    )
    evidence = uow.cursor.fetchone()
    if (
        evidence is None
        or evidence[1] != "provider_request_admission_manifest"
        or str(evidence[0]) != capability.get("provider_admission_content_hash")
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_EVIDENCE_MISSING",
            "source must retain its exact native Provider admission evidence",
        )
    identity = dict(dict(evidence[2]).get("contract", evidence[2])).get(
        "provider_request_identity", {}
    )
    if (
        not isinstance(identity, Mapping)
        or not identity.get("provider")
        or identity.get("model") != str(effects[0][3])
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_EVIDENCE_INVALID",
            "native admission must identify the actual Provider model behind its gateway",
        )
    depth = 0
    if frozen.get("runtime_continuation_id"):
        uow.cursor.execute(
            "SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s AND successor_operation_id=%s",
            [frozen["runtime_continuation_id"], source_operation_id],
        )
        prior = uow.cursor.fetchone()
        if prior is None:
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_LINEAGE_INVALID",
                "source continuation lineage is incomplete",
            )
        depth = int(prior[0])
    if depth >= 2:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_BOUND_EXCEEDED",
            "runtime continuation cannot exceed two successors",
        )
    return {
        "source_operation_id": source_operation_id,
        "command": frozen,
        "version": int(row[1]),
        "evidence_asset_version_id": evidence_id,
        "evidence_hash": str(evidence[0]),
        "snapshot": snapshot,
        "provider": str(identity["provider"]),
        "model_id": str(effects[0][3]),
        "depth": depth + 1,
    }


def resolve_target(
    application: Any, command: StoryPlanningGenerationCommand
) -> dict[str, Any]:
    from .binder import PostgresPlanningExecutionBundleResolver

    resolver = getattr(application.execution_binder, "resolver", None)
    if (
        not isinstance(resolver, PostgresPlanningExecutionBundleResolver)
        or resolver.release_sha != application.commit_sha
        or resolver.execution_preparer.planning_route.release_sha
        != application.commit_sha
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_RUNTIME_INVALID",
            "continuation requires the native resolver at the actual current release",
        )
    snapshot = resolver.pack_resolver.resolve_workflow_node(
        CapabilityPackResolutionRequest(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            workflow_definition_ref=resolver.workflow_definition_ref,
            workflow_node_id=command.generator_operation_name,
            environment=resolver.environment,
            runtime_profile=resolver.runtime_profile,
            release_channel=resolver.release_channel,
            release_sha=application.commit_sha,
            operation_definition_ref=f"story_planning.generate@{command.execution_contract_version}",
            pack_id=resolver.pack_id,
        )
    )
    model = resolver.execution_preparer.planning_route.model_profile
    account = {}
    if model.model_provider == "codex-cli":
        from novel_forge.modules.production_execution.codex_configuration import (
            codex_account_binding_evidence,
        )

        session = resolver.execution_preparer.execution_transport.session_for_project(
            command.project_id
        )
        backend = session.gateway.backends.resolve(model.backend_id)
        try:
            account = codex_account_binding_evidence(backend)
        except ValueError as error:
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_REQUIRED",
                "Codex continuation requires the existing native account-entitlement backend",
            ) from error
    return {
        "pack_snapshot": snapshot.to_dict(),
        "model_provider": model.model_provider,
        "model_id": model.model_id,
        "reasoning_effort": model.reasoning_effort,
        "runtime_class": model.runtime_class.value,
        "model_backend_id": model.backend_id,
        "auth_profile_ref": resolver.execution_preparer.planning_route.auth_profile_ref,
        "cost_accounting_basis": resolver.execution_preparer.cost_accounting_basis,
        "account": account,
    }


def require_route_evidence(
    uow: AuthorityUnitOfWork,
    *,
    source: dict[str, Any],
    target: dict[str, Any],
    authorized_reasoning_effort: str,
) -> dict[str, Any]:
    if (
        authorized_reasoning_effort not in {"low", "medium", "high", "xhigh"}
        or target["reasoning_effort"] != authorized_reasoning_effort
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_REASONING_UNAUTHORIZED",
            "the current explicit author decision must match the actual Planning reasoning effort",
        )
    decision = {
        "reasoning_evidence_source": "CURRENT_USER_DECISION",
        "authorized_reasoning_effort": authorized_reasoning_effort,
    }
    if source.get("preflight_failure"):
        if (source["source_auth_profile_ref"] != target["auth_profile_ref"]
                or source["source_backend_id"] != target["model_backend_id"]
                or source["source_reasoning_effort"] != target["reasoning_effort"]
                or target["cost_accounting_basis"] != "ACCOUNT_ENTITLEMENT" or not target["account"]):
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT", "Capacity successors must retain the original authenticated membership binding and reasoning")
        if source["preflight_failure"].get("contract_version") in {"planning-repair-route-preflight.v1","planning-input-order-preflight.v1"}:
            from novel_forge.modules.production_execution.execution_template import selected_book_template, decision_template
            admission = selected_book_template(uow.cursor,project_id=source["command"]["project_id"],book_id=source["command"]["book_id"])
            template = decision_template({"task":{"work_id":source["command"]["book_id"],
                "policy_snapshot":admission["policy_snapshot"]}}) if admission else None
            repair = source["preflight_failure"]["blocked_decision"]["native_repair_evidence"]
            if (not template or template['version'] not in {'creative-execution-template.v2','creative-execution-template.v3','creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6'}
                    or not template.get('repair_routing')
                    or repair['repair_number'] > template['repair_routing']['max_same_route_repairs']
                    or repair['parent_candidate_id'] not in template['allowed_candidates']):
                raise KernelError("PLANNING_RUNTIME_CONTINUATION_POLICY_REQUIRED","Routing successor requires the explicit trusted v2 native repair policy")
            decision["target_repair_template"] = admission
        return {**decision,"account_evidence_source":"ORIGINAL_SETTLED_NATIVE_RESULT_ROUTE",
            "source_auth_profile_ref":source["source_auth_profile_ref"],"source_result_operation_id":source["route_evidence_operation_id"],
            "account_runtime_hash":canonical_hash(target["account"])}
    if (
        source["provider"] == "scripted_provider_v2"
        and target["runtime_class"] == "SCRIPTED_FIXTURE"
    ):
        return {**decision, "account_evidence_source": "SCRIPTED_FIXTURE_ONLY"}
    command = source["command"]
    if command.get("runtime_continuation_id"):
        uow.cursor.execute(
            "SELECT target_runtime FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s AND successor_operation_id=%s",
            [command["runtime_continuation_id"], source["source_operation_id"]],
        )
        previous = uow.cursor.fetchone()
        if previous is None:
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_LINEAGE_INVALID",
                "source has no prior frozen runtime approval",
            )
        prior = dict(previous[0])
        compared = (
            "model_provider",
            "model_id",
            "reasoning_effort",
            "runtime_class",
            "model_backend_id",
            "cost_accounting_basis",
        )

        def stable_account(runtime):
            account = dict(runtime.get("account") or {})
            account["entitlement"] = {
                key: value
                for key, value in dict(account.get("entitlement") or {}).items()
                if key != "authorization_ref"
            }
            return account

        if any(prior.get(key) != target.get(key) for key in compared) or stable_account(
            prior
        ) != stable_account(target):
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT",
                "a subsequent continuation must retain the prior registered account, backend and reasoning",
            )
        return {
            **decision,
            "account_evidence_source": "PRIOR_REGISTERED_RUNTIME",
            "source_runtime_hash": canonical_hash(prior),
            "authorization_reference_change": "NATIVE_BUDGET_SUCCESSOR_ALLOWED",
        }
    uow.cursor.execute(
        "SELECT runtime_policy FROM authority_book WHERE project_id=%s AND workspace_id=%s AND book_id=%s",
        [command["project_id"], command["workspace_id"], command["book_id"]],
    )
    row = uow.cursor.fetchone()
    frozen = dict(row[0] or {}).get("creation_pilot") if row else None
    if (
        not isinstance(frozen, Mapping)
        or not isinstance(frozen.get("models"), Mapping)
        or not frozen["models"]
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_REQUIRED",
            "this bounded continuation requires the original native Book model and account policy",
        )
    routes = list(frozen["models"].values())
    if any(
        not isinstance(route, Mapping)
        or not isinstance(route.get("model_profile"), Mapping)
        for route in routes
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_INVALID",
            "Book model policy must contain typed frozen route objects",
        )
    expected = {
        (
            str(route["model_profile"].get("backend_id") or ""),
            str(route["model_profile"].get("runtime_class") or ""),
            str(route.get("auth_profile_ref") or ""),
        )
        for route in routes
    }
    if len(expected) != 1:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_INVALID",
            "Book routes must share one frozen backend and account",
        )
    backend_id, runtime_class, auth_profile = next(iter(expected))
    if (
        (backend_id, runtime_class)
        != (target["model_backend_id"], target["runtime_class"])
        or target["model_provider"] != "codex-cli"
        or (frozen.get("cost_accounting") or {}).get("accounting_basis")
        != target["cost_accounting_basis"]
        or target["cost_accounting_basis"] != "ACCOUNT_ENTITLEMENT"
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT",
            "continuation cannot change the Book backend, runtime or accounting basis",
        )
    settings = frozen.get("runtime_settings") or {}
    fields = {
        "account_identity_ref": "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF",
        "cli_version": "NOVEL_FORGE_CODEX_CLI_VERSION",
        "executable_sha256": "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256",
        "configuration_ref": "NOVEL_FORGE_CODEX_CONFIGURATION_REF",
    }
    account = dict(target["account"])
    entitlement = dict(account.get("entitlement") or {})
    if any(
        not isinstance(settings.get(key), str)
        or not settings[key]
        or entitlement.get(field) != settings[key]
        for field, key in fields.items()
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT",
            "native Book account, CLI and configuration identity must remain exact",
        )
    uow.cursor.execute(
        "SELECT evidence->>'cost_authorization_ref' FROM authority_budget_reservation WHERE operation_id=%s AND project_id=%s ORDER BY created_at",
        [source.get("route_evidence_operation_id", source["source_operation_id"]), command["project_id"]],
    )
    references = {str(row[0] or "") for row in uow.cursor.fetchall()}
    if len(references) != 1 or not next(iter(references)):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_REQUIRED",
            "the released source budget must retain its original authorization reference",
        )
    from novel_forge.modules.production_execution.codex_configuration import (
        codex_local_binding_hash,
    )

    prior_entitlement = {**entitlement, "authorization_ref": next(iter(references))}
    expected_suffix = codex_local_binding_hash(
        codex_home=account["codex_home"],
        executable=account["executable"],
        entitlement=prior_entitlement,
        retry_policy=str(account.get("retry_policy") or ""),
    )
    if not auth_profile.endswith(":codex:" + expected_suffix):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT",
            "current executable and account directory do not reconstruct the original Book authentication binding",
        )
    return {
        **decision,
        "account_evidence_source": "BOOK_RUNTIME_POLICY_CREATION_PILOT",
        "book_route_policy_hash": canonical_hash(
            {
                "models": frozen["models"],
                "runtime_settings": settings,
                "cost_accounting": frozen.get("cost_accounting"),
            }
        ),
        "source_auth_profile_ref": auth_profile,
        "preserved_account_fields": list(fields),
        "authorization_reference_change": "NATIVE_BUDGET_SUCCESSOR_ALLOWED",
    }


def register(
    application: Any,
    source_operation_id: str,
    *,
    project_id: str,
    principal: Principal,
    expected_source_version: int,
    decision_evidence: Mapping[str, Any],
    trace_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    from .application import (
        _command_from_payload,
        _command_payload,
    )

    principal.require("story_planning.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError(
            "runtime continuation registration requires the existing trusted local operator"
        )
    if (
        not isinstance(decision_evidence, Mapping)
        or not isinstance(decision_evidence.get("authorization_ref"), str)
        or not decision_evidence["authorization_ref"].strip()
        or not isinstance(decision_evidence.get("reason"), str)
        or not decision_evidence["reason"].strip()
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DECISION_REQUIRED",
            "operator registration must cite the actual authorization and failure reason",
        )
    with AuthorityUnitOfWork(application.database_url) as uow:
        source = require_source(
            uow, source_operation_id=source_operation_id, project_id=project_id
        )
    if source["version"] != expected_source_version:
        raise KernelError(
            "OPERATION_VERSION_CONFLICT",
            "cancelled source version differs from the requested registration",
        )
    original = _command_from_payload(source["command"])
    continuation_id = f"planning-runtime-continuation:{source_operation_id}"
    successor = replace(
        original,
        execution_contract_version=original.execution_contract_version,
        runtime_continuation_id=continuation_id,
        idempotency_key=f"{original.idempotency_key}:runtime-continuation:{source['depth']}",
    )
    application._register_definitions(successor.execution_contract_version)
    target = resolve_target(application, successor)
    if source["snapshot"]["release_sha"] == application.commit_sha:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_RELEASE_UNCHANGED",
            "same-release failures use native Attempt recovery",
        )
    if (source["provider"], source["model_id"]) != (
        target["model_provider"],
        target["model_id"],
    ) or source["snapshot"]["route_policy_hash"] != target["pack_snapshot"][
        "route_policy_hash"
    ]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_MODEL_ROUTE_DRIFT",
            "runtime continuation cannot switch the frozen Provider model or routing policy",
        )
    capacity_decision = None
    if source.get("preflight_failure"):
        from .preflight_continuation import require_capacity_target
        capacity_decision = require_capacity_target(source, target)
    with AuthorityUnitOfWork(application.database_url) as uow:
        route_evidence = require_route_evidence(
            uow,
            source=source,
            target=target,
            authorized_reasoning_effort=str(
                decision_evidence.get("authorized_reasoning_effort") or ""
            ),
        )
    definition = runtime_continuation_definition(
        application_build_id=application.application_build_id,
        commit_sha=application.commit_sha,
    )
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()
    frozen_successor = _command_payload(successor)
    decision = {
        **dict(decision_evidence),
        **route_evidence,
        "registered_by": principal.principal_id,
        "registered_by_agent": True,
        "independent_human_review": "NOT_REVIEWED",
    }
    content = {
        "contract_version": "planning-runtime-continuation.v1",
        "continuation_id": continuation_id,
        "source_operation_id": source_operation_id,
        "source_evidence_asset_version_id": source["evidence_asset_version_id"],
        "project_id": project_id,
        "workspace_id": original.workspace_id,
        "book_id": original.book_id,
        "source_command": source["command"],
        "successor_command": frozen_successor,
        "target_runtime": target,
        "decision_evidence": decision,
        "source_release_sha": source["snapshot"]["release_sha"],
        "target_release_sha": application.commit_sha,
        "chain_depth": source["depth"],
        **({"source_preflight_failure": source["preflight_failure"], "capacity_decision": capacity_decision}
           if source.get("preflight_failure") else {}),
        "control_evidence_only": True,
    }

    def materialize(uow, registration_operation_id, checkpoint):
        current = require_source(
            uow, source_operation_id=source_operation_id, project_id=project_id
        )
        if (
            current != source
            or require_route_evidence(
                uow,
                source=current,
                target=target,
                authorized_reasoning_effort=route_evidence[
                    "authorized_reasoning_effort"
                ],
            )
            != route_evidence
        ):
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_SOURCE_DRIFT",
                "source changed before continuation registration",
            )
        document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=registration_operation_id,
                project_id=project_id,
                asset_id=continuation_id,
                asset_type="planning_runtime_continuation",
                schema_version="planning-runtime-continuation.v1",
                logical_ref=f"planning/runtime_continuations/{source_operation_id}.json",
                category="runs",
                output_key=OUTPUT_KEY,
                role="primary",
                content=content,
                qualification_policy="planning-runtime-continuation-operator-v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
                causation_id=source_operation_id,
            )
        )
        uow.cursor.execute(
            "INSERT INTO authority_story_planning_runtime_continuation(continuation_id,project_id,workspace_id,book_id,source_operation_id,source_evidence_asset_version_id,registered_by_operation_id,source_command,successor_command,target_runtime,decision_evidence,source_release_sha,target_release_sha,chain_depth) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                continuation_id,
                project_id,
                original.workspace_id,
                original.book_id,
                source_operation_id,
                source["evidence_asset_version_id"],
                registration_operation_id,
                Jsonb(source["command"]),
                Jsonb(frozen_successor),
                Jsonb(target),
                Jsonb(decision),
                source["snapshot"]["release_sha"],
                application.commit_sha,
                source["depth"],
            ],
        )
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "planning_runtime_continuation",
                "aggregate_id": continuation_id,
                "operation_id": registration_operation_id,
                "project_id": project_id,
                "event_type": "story_planning.runtime_continuation.registered",
                "correlation_id": correlation_id,
                "causation_id": source_operation_id,
                "payload": {
                    "operation_id": registration_operation_id,
                    "trace_id": trace_id,
                    "continuation_id": continuation_id,
                    "asset_version_id": document.asset_version_id,
                    "source_operation_id": source_operation_id,
                    "target_release_sha": application.commit_sha,
                },
            }
        )
        return {
            "continuation_id": continuation_id,
            "asset_version_id": document.asset_version_id,
            "content_hash": document.content_hash,
            "source_operation_id": source_operation_id,
            "target_release_sha": application.commit_sha,
        }

    return execute_transaction_command(
        application.database_url,
        {
            "definition_name": DEFINITION_NAME,
            "definition_version": "1.0.0",
            "project_id": project_id,
            "workspace_id": original.workspace_id,
            "book_id": original.book_id,
            "actor_id": principal.principal_id,
            "idempotency_scope": "book:planning-runtime-continuation",
            "idempotency_key": continuation_id,
            "trace_id": trace_id,
            "span_id": str(uuid4()),
            "correlation_id": correlation_id,
            "causation_id": source_operation_id,
            "causation_operation_id": source_operation_id,
            "input": content,
            "input_assets": [
                {
                    "asset_version_id": source["evidence_asset_version_id"],
                    "content_hash": source["evidence_hash"],
                }
            ],
        },
        context=AdmissionContext(
            actor_id=principal.principal_id,
            permissions=frozenset({"story_planning.authority.execute"}),
            available_handlers=frozenset({HANDLER_KEY}),
            application_build_id=application.application_build_id,
            commit_sha=application.commit_sha,
        ),
        handler=materialize,
    )


def require_binding(database_url: str, continuation_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT project_id, workspace_id, book_id, source_operation_id, source_command, successor_command, target_runtime, target_release_sha, successor_operation_id FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s",
            [continuation_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_NOT_REGISTERED",
            "a worker may only follow an operator-registered continuation",
        )
    return dict(
        zip(
            (
                "project_id",
                "workspace_id",
                "book_id",
                "source_operation_id",
                "source_command",
                "successor_command",
                "target_runtime",
                "target_release_sha",
                "successor_operation_id",
            ),
            row,
            strict=True,
        )
    )


def require_successor(
    application: Any, command: StoryPlanningGenerationCommand, *, validate_runtime: bool = True
) -> dict[str, Any]:
    from .application import _command_payload

    binding = require_binding(application.database_url, command.runtime_continuation_id)
    if (
        binding["successor_command"] != _command_payload(command)
        or validate_runtime and binding["target_release_sha"] != application.commit_sha
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT",
            "successor must use the registered frozen task and actual approved release",
        )
    if validate_runtime and not binding["successor_operation_id"] and resolve_target(application, command) != binding["target_runtime"]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_RUNTIME_DRIFT",
            "the exact registered Pack and model route changed",
        )
    return binding


def require_snapshot(
    database_url: str, command: StoryPlanningGenerationCommand, snapshot: Any
) -> None:
    binding = require_binding(database_url, command.runtime_continuation_id)
    if (
        snapshot.execution_snapshot.to_dict()
        != binding["target_runtime"]["pack_snapshot"]
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_DRIFT",
            "the Attempt must freeze the exact operator-registered runtime",
        )


def follow(
    application: Any,
    source_operation_id: str,
    command: StoryPlanningGenerationCommand,
    *,
    principal: Principal,
):
    from .application import _command_from_payload, _command_payload

    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute(
            "SELECT source_command, successor_command FROM authority_story_planning_runtime_continuation WHERE source_operation_id=%s AND project_id=%s",
            [source_operation_id, command.project_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return None
    if row[0] != _command_payload(command):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT",
            "original-stage replay must retain the exact registered source task",
        )
    return application.generate(
        _command_from_payload(dict(row[1])), principal=principal
    )


def attach_successor(
    uow: AuthorityUnitOfWork, command: StoryPlanningGenerationCommand, operation_id: str
) -> None:
    uow.cursor.execute(
        "UPDATE authority_story_planning_runtime_continuation SET successor_operation_id=%s WHERE continuation_id=%s AND (successor_operation_id IS NULL OR successor_operation_id=%s)",
        [operation_id, command.runtime_continuation_id, operation_id],
    )
    if uow.cursor.rowcount != 1:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SUCCESSOR_CONFLICT",
            "only one successor Operation may bind the registered continuation",
        )
