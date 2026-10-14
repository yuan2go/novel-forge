from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import canonical_hash

VERSION = "planning-runtime-continuation.v4"


def binding_identity(binding):
    return canonical_hash(
        {
            key: value
            for key, value in binding.items()
            if key != "successor_operation_id"
        }
    )


def effective_binding(database_url, binding):
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT v.content FROM authority_operation_output_asset output
            JOIN authority_operation op USING(operation_id)
            JOIN authority_asset_version v USING(asset_version_id)
            JOIN authority_asset a ON a.asset_id=v.asset_id
            WHERE op.project_id=%s AND op.definition_name='story_planning.runtime_continuation.register'
              AND op.definition_version='4.0.0' AND op.status='SUCCEEDED'
              AND a.asset_type='planning_runtime_continuation' AND v.content->>'contract_version'=%s
              AND v.content->>'continuation_id'=%s
            ORDER BY v.created_at DESC,v.asset_version_id DESC LIMIT 1""",
            [
                binding["project_id"],
                VERSION,
                binding["successor_command"]["runtime_continuation_id"],
            ],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return binding
    evidence = row[0]
    if (
        evidence["source_binding_hash"] != binding_identity(binding)
        or evidence["source_command"] != binding["source_command"]
        or evidence["successor_command"] != binding["successor_command"]
    ):
        raise KernelError(
            "PLANNING_DEPLOYMENT_REVALIDATION_SOURCE_DRIFT",
            "Deployment evidence must preserve the original continuation",
        )
    return {
        **binding,
        "target_release_sha": evidence["target_release_sha"],
        "target_runtime": evidence["target_runtime"],
    }


def deployment_target(uow, *, project_id, original, target):
    from .runtime_continuation import _require_version_only_pack_successor

    extras = {
        "planning_capacity",
        "generation_isolation",
        "world_host_revalidation",
        "world_source_correction",
        "planning_reference_contract",
        "provider_schema_correction",
    }
    if {
        key: value
        for key, value in original.items()
        if key not in extras | {"pack_snapshot"}
    } != {key: value for key, value in target.items() if key != "pack_snapshot"}:
        raise KernelError(
            "PLANNING_DEPLOYMENT_REVALIDATION_ROUTE_DRIFT",
            "Deployment revalidation cannot change model, reasoning or authenticated account",
        )
    old, new = original["pack_snapshot"], target["pack_snapshot"]
    physical = {
        "deployment_id",
        "activation_version",
        "pack_version",
        "manifest_hash",
        "compilation_id",
        "compilation_hash",
        "catalog_snapshot_hash",
        "binding_set_id",
        "binding_set_hash",
        "release_sha",
        "assignment_ref",
        "rollout_id",
    }
    if {key: value for key, value in old.items() if key not in physical} != {
        key: value for key, value in new.items() if key not in physical
    }:
        raise KernelError(
            "PLANNING_DEPLOYMENT_REVALIDATION_CONTRACT_DRIFT",
            "Deployment revalidation cannot change resolved story, policy or submission contracts",
        )
    proof = _require_version_only_pack_successor(
        uow, project_id=project_id, original=old, target=new
    )
    return {
        **deepcopy(target),
        **{key: deepcopy(value) for key, value in original.items() if key in extras},
    }, proof


def register(
    application,
    continuation_id,
    *,
    project_id,
    principal,
    authorization_ref,
    reason,
    execution_probe=None,
):
    from .application import _command_from_payload
    from .runtime_continuation import (
        DEFINITION_NAME,
        HANDLER_KEY,
        OUTPUT_KEY,
        require_binding,
        require_source,
        resolve_target,
        runtime_continuation_definition,
    )
    from novel_forge.storage.story_formation_repositories import (
        StoryFormationRepository,
    )

    principal.require("story_planning.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError(
            "Pending deployment revalidation requires the original trusted operator"
        )
    if not authorization_ref or not reason:
        raise ValueError(
            "Deployment revalidation requires original authorization and a concrete reason"
        )
    application._probe(execution_probe)
    binding = require_binding(
        application.database_url, continuation_id, effective=False
    )
    command = _command_from_payload(binding["successor_command"])
    if (
        binding["project_id"] != project_id
        or command.execution_contract_version != "1.21.0"
    ):
        raise KernelError(
            "PLANNING_DEPLOYMENT_REVALIDATION_SCOPE_INVALID",
            "Require the exact current Planning scope",
        )
    key = continuation_id + ":deployment:" + application.commit_sha

    def read_replay(uow):
        uow.cursor.execute(
            """SELECT op.operation_id,output.asset_version_id,v.content FROM authority_operation op
            JOIN authority_operation_output_asset output USING(operation_id)
            JOIN authority_asset_version v USING(asset_version_id)
            WHERE op.project_id=%s AND op.idempotency_scope='book:planning-runtime-continuation'
              AND op.idempotency_key=%s AND op.definition_name=%s AND op.definition_version='4.0.0'
              AND op.status='SUCCEEDED' AND output.output_key=%s""",
            [project_id, key, DEFINITION_NAME, OUTPUT_KEY],
        )
        retained = uow.cursor.fetchone()
        if not retained:
            return None
        if (
            retained[2]["source_binding_hash"] != binding_identity(binding)
            or retained[2]["authorization_ref"] != authorization_ref
            or retained[2]["reason"] != reason
            or retained[2]["registered_by"] != principal.principal_id
        ):
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_REQUEST_DRIFT",
                "Replay retains its actual operator decision",
            )
        return {
            "operation_id": retained[0],
            "continuation_id": continuation_id,
            "asset_version_id": retained[1],
            "target_release_sha": retained[2]["target_release_sha"],
            "replayed": True,
        }

    with AuthorityUnitOfWork(application.database_url) as uow:
        replay = read_replay(uow)
    if replay:
        return replay
    target = resolve_target(application, command)

    def require_pending(uow, *, allow_replay=False):
        uow.cursor.execute(
            "SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s ORDER BY formation_run_id FOR UPDATE",
            [project_id, command.book_id],
        )
        rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_AUTHORIZATION_REQUIRED",
                "Require one original Creation owner",
            )
        if allow_replay:
            replay = read_replay(uow)
            if replay:
                return {"replayed_result": replay}
        run = StoryFormationRepository(uow.cursor).require(rows[0][0])
        auth = run["frozen_input"]["generation_policy"]["auto_authorization"]
        if (
            auth.get("contract_version") != "formation-auto-authorization.v1"
            or auth.get("policy_version") != "formation-auto-policy.v1"
            or (
                auth.get("project_id"),
                auth.get("workspace_id"),
                auth.get("book_id"),
                auth.get("formation_run_id"),
            )
            != (
                project_id,
                command.workspace_id,
                command.book_id,
                run["formation_run_id"],
            )
            or not {
                "story_planning.candidate.approve",
                "story_planning.candidate.activate",
            }.issubset(auth.get("allowed_actions", []))
            or auth.get("authorized_by_principal_id") != principal.principal_id
            or auth.get("authorization_ref") != authorization_ref
            or binding["workspace_id"] != run["workspace_id"]
            or command.actor_id != binding["source_command"]["actor_id"]
            or StoryFormationRepository(uow.cursor).cancellation(
                run["formation_run_id"]
            )
        ):
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_AUTHORIZATION_REQUIRED",
                "Original authorization and uncancelled Creation must agree",
            )
        uow.cursor.execute(
            "SELECT successor_operation_id FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s FOR UPDATE",
            [continuation_id],
        )
        if uow.cursor.fetchone() != (None,):
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_ALREADY_STARTED",
                "Started successors retain their frozen deployment",
            )
        source = require_source(
            uow,
            source_operation_id=binding["source_operation_id"],
            project_id=project_id,
        )
        uow.cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_operation WHERE project_id=%s AND definition_name='story_planning.generate' AND command_payload#>>'{payload,runtime_continuation_id}'=%s)",
            [project_id, continuation_id],
        )
        if uow.cursor.fetchone()[0]:
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_ALREADY_STARTED",
                "An admitted successor cannot change deployment",
            )
        if source.get("mode") != "ISOLATED_PURE_GENERATION" or not binding[
            "target_runtime"
        ].get("generation_isolation"):
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_SOURCE_INVALID",
                "Only an already isolated pure-generation continuation qualifies",
            )
        uow.cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id) WHERE attempt.operation_id=%s AND lease.status='HELD')",
            [binding["source_operation_id"]],
        )
        if uow.cursor.fetchone()[0]:
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_SOURCE_LIVE",
                "Source execution must be stopped",
            )
        if source["command"] != binding["source_command"]:
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_SOURCE_DRIFT",
                "Original task is immutable",
            )
        return source

    with AuthorityUnitOfWork(application.database_url) as uow:
        source = require_pending(uow, allow_replay=True)
        if source.get("replayed_result"):
            return source["replayed_result"]
        new_target, proof = deployment_target(
            uow,
            project_id=project_id,
            original=binding["target_runtime"],
            target=target,
        )
        definition = runtime_continuation_definition(
            application_build_id=application.application_build_id,
            commit_sha=application.commit_sha,
            definition_version="4.0.0",
        )
        uow.repositories.definitions.register(definition)
        uow.commit()
    if binding["target_release_sha"] == application.commit_sha:
        raise KernelError(
            "PLANNING_DEPLOYMENT_REVALIDATION_RELEASE_UNCHANGED",
            "Require an actual release change",
        )
    content = {
        "contract_version": VERSION,
        "continuation_id": continuation_id,
        "source_binding_hash": binding_identity(binding),
        "source_command": binding["source_command"],
        "successor_command": binding["successor_command"],
        "source_release_sha": binding["target_release_sha"],
        "target_release_sha": application.commit_sha,
        "target_runtime": new_target,
        "source_operation_version": source["version"],
        "pack_version_successor": proof,
        "authorization_ref": authorization_ref,
        "registered_by": principal.principal_id,
        "reason": reason,
        "control_evidence_only": True,
    }

    def materialize(uow, operation_id, checkpoint):
        application._probe(execution_probe)
        current = require_pending(uow)
        from novel_forge.modules.capability_pack_authority.runtime import (
            CapabilityPackResolutionRequest,
        )

        resolver = application.execution_binder.resolver
        snapshot = resolver.pack_resolver.resolve_workflow_node(
            CapabilityPackResolutionRequest(
                project_id=project_id,
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
        if current != source or snapshot.to_dict() != target["pack_snapshot"]:
            raise KernelError(
                "PLANNING_DEPLOYMENT_REVALIDATION_SOURCE_DRIFT",
                "Source or active target changed before registration",
            )
        document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=project_id,
                asset_id=key,
                asset_type="planning_runtime_continuation",
                schema_version=VERSION,
                logical_ref=f"planning/runtime_continuations/{binding['source_operation_id']}/deployment/{application.commit_sha}.json",
                category="runs",
                output_key=OUTPUT_KEY,
                role="primary",
                content=content,
                qualification_policy="planning-runtime-continuation-operator-v1",
                trace_id=key,
                correlation_id=continuation_id,
                causation_id=binding["source_operation_id"],
            )
        )
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "planning_runtime_continuation",
                "aggregate_id": continuation_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": "story_planning.runtime_continuation.registered",
                "correlation_id": continuation_id,
                "causation_id": binding["source_operation_id"],
                "payload": {
                    "operation_id": operation_id,
                    "trace_id": key,
                    "continuation_id": continuation_id,
                    "asset_version_id": document.asset_version_id,
                    "target_release_sha": application.commit_sha,
                    "deployment_revalidation": True,
                },
            }
        )
        return {
            "continuation_id": continuation_id,
            "asset_version_id": document.asset_version_id,
            "target_release_sha": application.commit_sha,
        }

    return execute_transaction_command(
        application.database_url,
        {
            "definition_name": DEFINITION_NAME,
            "definition_version": "4.0.0",
            "project_id": project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "actor_id": principal.principal_id,
            "idempotency_scope": "book:planning-runtime-continuation",
            "idempotency_key": key,
            "trace_id": key,
            "span_id": str(uuid4()),
            "correlation_id": continuation_id,
            "causation_id": binding["source_operation_id"],
            "causation_operation_id": binding["source_operation_id"],
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
