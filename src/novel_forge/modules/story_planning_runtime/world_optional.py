from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    read_failed_operation_success,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation_in_uow,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    execute_transaction_command,
)
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
    decision_template,
    verify_template_provenance,
)
from novel_forge.modules.worldbuilding.production_planning import _seal
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.world_preparation_repositories import (
    WorldPreparationRepository,
)
from .domain import canonical_hash

NAME = "story_planning.world_preparation.defer"
HANDLER = "novel_forge." + NAME


def optional_policy(cursor, *, project_id, book_id, operation_id=None):
    admission = selected_book_template(cursor, project_id=project_id, book_id=book_id)
    value = (
        decision_template(
            {
                "task": {
                    "work_id": book_id,
                    "policy_snapshot": admission["policy_snapshot"],
                }
            }
        )
        if admission
        else None
    )
    if (
        not value
        or value["version"] != "creative-execution-template.v3"
        or value["world_future_preparation"] == "REQUIRED"
    ):
        return None
    if operation_id:
        cursor.execute(
            "SELECT v.policy_snapshot,o.status FROM authority_attempt_capability_pack_snapshot s JOIN authority_capability_pack_validation_admission v ON v.compilation_id=s.snapshot_payload->>'compilation_id' AND v.project_id=%s AND v.book_id=%s JOIN authority_operation o ON o.operation_id=v.operation_id WHERE s.operation_id=%s ORDER BY s.created_at DESC LIMIT 1",
            [project_id, book_id, operation_id],
        )
        frozen = cursor.fetchone()
        if (
            not frozen
            or frozen[1] != "SUCCEEDED"
            or frozen[0] != admission["policy_snapshot"]
        ):
            return None
    return admission


def require_optional_source(source):
    if source.get("actor_experiment") or source.get("preparation_sources"):
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_DEPENDENCY_REQUIRED",
            "Independent actor experiments and accepted preparation commitments cannot be skipped",
        )


def deferred_action(*, source, source_ref, command, admission, rejected=None):
    require_optional_source(source)
    plan = (
        rejected["world_plan"]
        if rejected
        else {
            "contract_version": "world-production-plan.v1",
            "authority": "PLANNING_PROPOSAL",
            "baseline_id": source["reality"]["revision_id"],
            "accepted_through_chapter": source["reality"]["chapter_number"],
            "chapter_number": int(source["request"]["accepted_through_chapter"]) + 1,
            "intent_version_id": source["intent_version_id"],
            "policy": source["policy"],
            "selected_candidate_id": "",
            "selected_path_id": "",
            "causal_debts": [],
            "candidate_futures": [],
            "preparation_schedule": [],
            "alternative_paths": [],
            "rejected_paths": [],
            "continuation_decisions": [],
            "fact_mutation_allowed": False,
        }
    )
    if rejected and (
        plan["disposition"] != "BLOCKED"
        or any(c.get("eligible") for c in plan["candidate_futures"])
        or plan["selected_candidate_id"]
        or plan["preparation_schedule"]
    ):
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
            "Only rejected unselected speculative futures may be deferred",
        )
    reason = "Optional world future simulation deferred by the trusted execution template; no simulated event becomes a fact."
    return {
        "contract_version": "world-production-action.v2",
        "authority": "PLANNING_PROPOSAL",
        "project_id": command.project_id,
        "book_id": command.book_id,
        "book_run_id": source["request"]["book_run_id"],
        "actor_id": command.actor_id,
        "source": source_ref,
        "generation": None,
        "evaluation": None,
        "world_plan": _seal(
            {
                **{key: value for key, value in plan.items() if key != "plan_digest"},
                "disposition": "DEFER",
                "reason": reason,
            }
        ),
        "preserve_accepted_history": True,
        "fact_mutation_allowed": False,
        "optional_preparation": {
            "contract_version": "world-optional-preparation.v1",
            "status": "NOT_RUN",
            "reason": "REJECTED_OPTIONAL_SEARCH_DEFERRED"
            if rejected
            else "DISABLED_BY_TEMPLATE",
            "policy_admission": admission,
            "prior_simulation_status": "REJECTED" if rejected else "NOT_RUN",
        },
    }


def validate_optional_action(cursor, *, action, source):
    marker = action["optional_preparation"]
    admission = marker["policy_admission"]
    template = verify_template_provenance(
        cursor,
        {
            "task": {
                "project_id": action["project_id"],
                "work_id": action["book_id"],
                "policy_snapshot": admission["policy_snapshot"],
            }
        },
    )
    if (
        not template
        or template["version"] != "creative-execution-template.v3"
        or template["mode"] != "CREATIVE_VALIDATION"
        or template["world_future_preparation"] == "REQUIRED"
        or marker["contract_version"] != "world-optional-preparation.v1"
        or marker["status"] != "NOT_RUN"
        or action.get("generation") is not None
        or action.get("evaluation") is not None
        or action["world_plan"]["disposition"] != "DEFER"
        or action["world_plan"]["selected_candidate_id"]
        or action["world_plan"]["preparation_schedule"]
        or any(c.get("eligible") for c in action["world_plan"]["candidate_futures"])
        or action["world_plan"].get("fact_mutation_allowed") is not False
        or action.get("actor_proposals")
        or action.get("fact_mutation_allowed") is not False
    ):
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_POLICY_INVALID",
            "Deferral cannot certify a future, waive strict policy or mutate facts",
        )
    require_optional_source(source)
    retained = marker.get("retained_rejected_action")
    if retained:
        cursor.execute(
            "SELECT v.content_hash,v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s AND a.asset_type='narrative_governance_action'",
            [retained["asset_version_id"], action["project_id"]],
        )
        row = cursor.fetchone()
        if (
            not row
            or row[0] != retained["content_hash"]
            or row[0] != canonical_hash(row[1])
        ):
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
                "Retained rejection requires its exact original action",
            )
        old = row[1]["contract"]
        if (
            old["source"] != action["source"]
            or old["world_plan"]["disposition"] != "BLOCKED"
        ):
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
                "Deferral must preserve its rejected world source",
            )
        for key in (
            "candidate_futures",
            "rejected_paths",
            "baseline_id",
            "accepted_through_chapter",
        ):
            if old["world_plan"][key] != action["world_plan"][key]:
                raise KernelError(
                    "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
                    "Deferral cannot rewrite negative or accepted evidence",
                )
    elif (
        template["world_future_preparation"] != "DISABLED"
        or action["world_plan"]["candidate_futures"]
    ):
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
            "Optional simulation requires its retained result; disabled simulation contributes no futures",
        )


def continuation_action(database_url, command):
    if not command.runtime_continuation_id:
        return None
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT r.decision_evidence,o.status FROM authority_story_planning_runtime_continuation r JOIN authority_operation o ON o.operation_id=r.registered_by_operation_id WHERE r.continuation_id=%s AND r.project_id=%s AND r.book_id=%s",
            [command.runtime_continuation_id, command.project_id, command.book_id],
        )
        row = uow.cursor.fetchone()
    reference = (row[0] or {}).get("world_optional_action") if row else None
    if not reference:
        return None
    document = AuthorityAssetQuery(database_url).require(
        project_id=command.project_id, asset_version_id=reference["asset_version_id"]
    )
    if row[1] != "SUCCEEDED" or document.content_hash != reference["content_hash"]:
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_REGISTRATION_INVALID",
            "Only the completed native deferral command authorizes its successor",
        )
    with AuthorityUnitOfWork(database_url) as uow:
        source = AuthorityAssetQuery(database_url).require(
            project_id=command.project_id,
            asset_version_id=document.content["contract"]["source"]["asset_version_id"],
        )
        validate_optional_action(
            uow.cursor,
            action=document.content["contract"],
            source=source.content["contract"],
        )
        WorldPreparationRepository(uow.cursor).assert_source_current(
            project_id=command.project_id,
            book_id=command.book_id,
            frozen=source.content["contract"],
        )
    return document


def follow_optional_failure(application, *, command, operation_id, principal):
    from .application import _command_payload
    from .runtime_continuation import (
        runtime_continuation_definition,
        resolve_target,
        follow,
    )

    principal.require("story_planning.authority.execute", command.project_id)
    if principal.principal_id != command.actor_id:
        raise PermissionError(
            "World continuation actor must be the actual execution Principal"
        )
    with AuthorityUnitOfWork(application.database_url) as uow:
        admission = optional_policy(
            uow.cursor, project_id=command.project_id, book_id=command.book_id
        )
        if admission is None:
            return None
        uow.cursor.execute(
            "SELECT o.status,o.version,o.command_payload->'payload',a.error FROM authority_operation o JOIN LATERAL (SELECT result AS error FROM authority_attempt WHERE operation_id=o.operation_id ORDER BY attempt_number DESC LIMIT 1) a ON TRUE WHERE o.operation_id=%s AND o.project_id=%s",
            [operation_id, command.project_id],
        )
        state = uow.cursor.fetchone()
        if (
            not state
            or state[0] not in {"FAILED_RETRYABLE", "FAILED_FINAL"}
            or (state[3] or {}).get("error_code") != "WORLD_PREPARATION_BLOCKED"
        ):
            return None
        if state[2] != _command_payload(command):
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_OWNER_DRIFT",
                "Continuation requires the exact immutable source command",
            )
        uow.cursor.execute(
            "SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset b JOIN authority_asset a USING(asset_id) JOIN authority_asset_version v USING(asset_version_id) WHERE b.operation_id=%s AND a.asset_type='narrative_governance_action'",
            [operation_id],
        )
        rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
                "Continuation requires one retained blocked action",
            )
        old_id, old_hash, old_content = rows[0]
        uow.cursor.execute(
            "SELECT e.external_effect_id,e.status,e.request_payload->>'stage',e.request_payload FROM authority_external_effect e WHERE e.operation_id=%s ORDER BY e.created_at",
            [operation_id],
        )
        effects = uow.cursor.fetchall()
        uow.cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s AND status<>'SETTLED') OR EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND l.status='HELD')",
            [operation_id, operation_id],
        )
        if (
            uow.cursor.fetchone()[0]
            or len(effects) != 2
            or any(e[1] != "SUCCEEDED" for e in effects)
            or [e[2] for e in effects]
            != ["world_candidates.generate", "world_candidates.evaluate"]
        ):
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_RECONCILIATION_REQUIRED",
                "Only settled world stages without a lease or ChapterPlan dispatch permit deferral",
            )
        uow.cursor.execute(
            "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
            [operation_id],
        )
        old_snapshot = uow.cursor.fetchone()[0]
        depth = 1
        if command.runtime_continuation_id:
            uow.cursor.execute(
                "SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s AND successor_operation_id=%s",
                [command.runtime_continuation_id, operation_id],
            )
            previous = uow.cursor.fetchone()
            if previous is None or previous[0] >= 2:
                raise KernelError(
                    "WORLD_OPTIONAL_DEFERRAL_BOUND_EXCEEDED",
                    "Preserve the existing runtime continuation bound",
                )
            depth = previous[0] + 1
        for effect in effects:
            prior_policy = verify_template_provenance(
                uow.cursor,
                effect[3]["_production_execution"]["capability_runtime"][
                    "routing_decision"
                ],
            )
            if (
                not prior_policy
                or prior_policy["mode"] != "CREATIVE_VALIDATION"
                or prior_policy["require_literary_qualification"]
            ):
                raise KernelError(
                    "WORLD_OPTIONAL_DEFERRAL_POLICY_INVALID",
                    "Strict frozen execution cannot adopt optional validation implicitly",
                )
    query = AuthorityAssetQuery(application.database_url)
    old = query.require(project_id=command.project_id, asset_version_id=old_id)
    source_doc = query.require(
        project_id=command.project_id,
        asset_version_id=old_content["contract"]["source"]["asset_version_id"],
    )
    if (
        old.content_hash != old_hash
        or source_doc.content_hash != old_content["contract"]["source"]["content_hash"]
    ):
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
            "World result hashes must remain exact",
        )
    source = source_doc.content["contract"]
    if (
        source["request"] != dict(command.world_preparation_request)
        or old_content["contract"]["book_id"] != command.book_id
        or old_content["contract"]["project_id"] != command.project_id
        or old_content["contract"]["actor_id"] != command.actor_id
    ):
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_OWNER_DRIFT",
            "Preserve the exact Book, actor and frontier request",
        )
    require_optional_source(source)
    stage_documents = []
    for effect, role in zip(effects, ("generation", "evaluation"), strict=True):
        receipt = read_failed_operation_success(
            application.database_url,
            EffectCommandContext(
                operation_id=operation_id,
                project_id=command.project_id,
                actor_id=command.actor_id,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            ),
            effect_id=effect[0],
        )
        reference = old_content["contract"][role]
        stage_doc = query.require(
            project_id=command.project_id,
            asset_version_id=reference["asset_version_id"],
        )
        stage = stage_doc.content["contract"]
        if (
            not receipt
            or receipt["budget_reservation_status"] != "SETTLED"
            or stage_doc.content_hash != reference["content_hash"]
            or stage["source"] != old_content["contract"]["source"]
            or receipt["provider_evidence"].get("result") != stage["output"]
            or stage["evidence"].get("external_receipt_ref") != effect[0]
        ):
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_RECONCILIATION_REQUIRED",
                "Retain verified receipt and settled usage for every original stage",
            )
        stage_documents.append(stage)
    from .world_result_recovery import validate_world_generation_result
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    if stage_documents[1]["generation"] != old_content["contract"]["generation"]:
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
            "Evaluation must bind its exact generation",
        )
    validate_world_generation_result(stage_documents[0]["output"], source, command)
    from novel_forge.modules.worldbuilding.production_schema import (
        decode_world_generation,
    )

    plan = compile_world_plan(
        reality=source["reality"],
        generated=decode_world_generation(
            {
                key: value
                for key, value in stage_documents[0]["output"].items()
                if key not in {"knowledge_translations", "actor_adjudications"}
            }
        ),
        evaluation=stage_documents[1]["output"],
        policy=WorldProductionPolicy(**source["policy"]),
        chapter_number=int(source["request"]["accepted_through_chapter"]) + 1,
        intent_version_id=source["intent_version_id"],
    )
    from novel_forge.modules.worldbuilding.continuation import (
        apply_preparation_decisions,
    )

    if source["contract_version"] == "world-preparation-source.v2":
        plan = apply_preparation_decisions(fresh_plan=plan, decisions=[])
    if (
        plan != old_content["contract"]["world_plan"]
        or plan["disposition"] != "BLOCKED"
    ):
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_RESULT_INVALID",
            "Verified settled results must reproduce their exact rejection",
        )
    continuation_id = "planning-world-deferral:" + operation_id
    successor = replace(
        command,
        runtime_continuation_id=continuation_id,
        idempotency_key=command.idempotency_key + ":world-deferral",
    )
    target = resolve_target(application, successor)
    prior_decision = effects[0][3]["_production_execution"]["capability_runtime"][
        "routing_decision"
    ]
    prior_identity = prior_decision["selected"]["candidate"]
    prior_membership = (
        prior_decision["task"]["budget_snapshot"]["candidates"][
            prior_identity["candidate_id"]
        ].get("membership_identity")
        or {}
    )
    entitlement = target["account"].get("entitlement") or {}
    if (
        prior_identity["provider"] != "codex-cli"
        or target["model_provider"] != "codex-cli"
        or prior_identity["model"] != target["model_id"]
        or prior_identity["reasoning"] != target["reasoning_effort"]
        or target["cost_accounting_basis"] != "ACCOUNT_ENTITLEMENT"
        or prior_identity["pricing"]["accounting_basis"] != "ACCOUNT_ENTITLEMENT"
        or prior_membership.get("account_ref")
        != entitlement.get("account_identity_ref")
        or not prior_membership.get("account_ref")
        or prior_identity["authorization_ref"] != entitlement.get("authorization_ref")
    ):
        raise KernelError(
            "WORLD_OPTIONAL_DEFERRAL_ACCOUNT_DRIFT",
            "Continuation retains its actual authorized member account, model and reasoning",
        )
    route = {
        "reasoning_evidence_source": "FROZEN_AUTHORIZED_SOURCE_ROUTE",
        "authorized_reasoning_effort": target["reasoning_effort"],
        "account_runtime_hash": canonical_hash(target["account"]),
        "member_identity": prior_membership,
        "same_member_identity_preserved": True,
    }
    action = deferred_action(
        source=source_doc.content["contract"],
        source_ref=old_content["contract"]["source"],
        command=command,
        admission=admission,
        rejected=old_content["contract"],
    )
    action["optional_preparation"]["retained_rejected_action"] = {
        "asset_version_id": old_id,
        "content_hash": old_hash,
    }
    definition = runtime_continuation_definition(
        application_build_id=application.application_build_id,
        commit_sha=application.commit_sha,
    )
    definition.update(
        name=NAME,
        handler_key=HANDLER,
        policy={
            "execution_classification": "transaction_command",
            "provider_dispatch_allowed": False,
        },
        idempotency_scope="book:world-optional-deferral",
        concurrency_key_template="book:{book_id}:world-optional-deferral",
    )
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()
    frozen = _command_payload(successor)
    evidence = {
        "policy_admission": admission,
        "world_search_status": "REJECTED",
        "provider_invoked": False,
        **route,
    }
    content = {
        "contract_version": "planning-runtime-continuation.v1",
        "source_command": state[2],
        "successor_command": frozen,
        "target_runtime": target,
        "source_operation_id": operation_id,
        "continuation_id": continuation_id,
        "project_id": command.project_id,
        "book_id": command.book_id,
        "source_release_sha": old_snapshot["release_sha"],
        "target_release_sha": application.commit_sha,
        "decision_evidence": evidence,
        "chain_depth": depth,
    }

    def materialize(uow, registration_id, checkpoint):
        uow.cursor.execute(
            "SELECT status,version FROM authority_operation WHERE operation_id=%s FOR UPDATE",
            [operation_id],
        )
        current = uow.cursor.fetchone()
        if current != state[:2]:
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_OWNER_DRIFT",
                "World source changed before atomic continuation",
            )
        uow.cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND status<>'SUCCEEDED') OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s AND status<>'SETTLED') OR EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND l.status='HELD')",
            [operation_id, operation_id, operation_id],
        )
        if uow.cursor.fetchone()[0]:
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_RECONCILIATION_REQUIRED",
                "All original effects and usage must remain settled without an active lease",
            )
        WorldPreparationRepository(uow.cursor).assert_source_current(
            project_id=command.project_id,
            book_id=command.book_id,
            frozen=source_doc.content["contract"],
        )
        if (
            optional_policy(
                uow.cursor, project_id=command.project_id, book_id=command.book_id
            )
            != admission
        ):
            raise KernelError(
                "WORLD_OPTIONAL_DEFERRAL_POLICY_INVALID",
                "Template selection changed before continuation",
            )
        validate_optional_action(
            uow.cursor, action=action, source=source_doc.content["contract"]
        )
        if current[0] == "FAILED_RETRYABLE":
            transition_operation_in_uow(
                uow,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    actor_id=principal.principal_id,
                    expected_status=current[0],
                    expected_version=current[1],
                    target_status="FAILED_FINAL",
                    reason="Known rejected world search has no progressing retry; preserve it for optional deferral",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=registration_id,
                ),
            )
        action_doc = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=registration_id,
                project_id=command.project_id,
                asset_id=continuation_id + ":world-action",
                asset_type="narrative_governance_action",
                schema_version="production-execution-contract.v1",
                logical_ref=f"world_preparation/{operation_id}/deferred_action",
                category="runs",
                output_key="world_optional.action",
                role="execution_contract",
                content={"contract": action},
                qualification_policy="world-optional-deferral-not-qualified-v1",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
        )
        recorded_evidence = {
            **evidence,
            "world_optional_action": {
                "asset_version_id": action_doc.asset_version_id,
                "content_hash": action_doc.content_hash,
            },
        }
        recorded_content = {**content, "decision_evidence": recorded_evidence}
        document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=registration_id,
                project_id=command.project_id,
                asset_id=continuation_id,
                asset_type="planning_runtime_continuation",
                schema_version="planning-runtime-continuation.v1",
                logical_ref=f"planning/runtime_continuations/{operation_id}.json",
                category="runs",
                output_key="story_planning.runtime_continuation",
                role="primary",
                content=recorded_content,
                qualification_policy="world-optional-deferral-not-qualified-v1",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
        )
        uow.cursor.execute(
            "INSERT INTO authority_story_planning_runtime_continuation(continuation_id,project_id,workspace_id,book_id,source_operation_id,source_evidence_asset_version_id,registered_by_operation_id,source_command,successor_command,target_runtime,decision_evidence,source_release_sha,target_release_sha,chain_depth) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                continuation_id,
                command.project_id,
                command.workspace_id,
                command.book_id,
                operation_id,
                old_id,
                registration_id,
                Jsonb(state[2]),
                Jsonb(frozen),
                Jsonb(target),
                Jsonb(recorded_evidence),
                old_snapshot["release_sha"],
                application.commit_sha,
                depth,
            ],
        )
        uow.repositories.operation_graph.record_event(
            dict(
                event_id=str(uuid4()),
                audit_id=str(uuid4()),
                outbox_id=str(uuid4()),
                aggregate_type="planning_runtime_continuation",
                aggregate_id=continuation_id,
                operation_id=registration_id,
                project_id=command.project_id,
                event_type="story_planning.runtime_continuation.registered",
                correlation_id=command.correlation_id,
                causation_id=operation_id,
                payload={
                    "operation_id": registration_id,
                    "trace_id": command.trace_id,
                    "asset_version_id": document.asset_version_id,
                    "provider_invoked": False,
                },
            )
        )
        return {
            "continuation_id": continuation_id,
            "asset_version_id": document.asset_version_id,
            "provider_invoked": False,
        }

    execute_transaction_command(
        application.database_url,
        dict(
            definition_name=NAME,
            definition_version="1.0.0",
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            actor_id=principal.principal_id,
            idempotency_scope="book:world-optional-deferral",
            idempotency_key=continuation_id,
            trace_id=command.trace_id,
            span_id=str(uuid4()),
            correlation_id=command.correlation_id,
            causation_id=operation_id,
            causation_operation_id=operation_id,
            input=content,
            input_assets=[
                {"asset_version_id": old_id, "content_hash": old_hash},
                {
                    "asset_version_id": source_doc.asset_version_id,
                    "content_hash": source_doc.content_hash,
                },
            ],
        ),
        context=AdmissionContext(
            principal.principal_id,
            frozenset({"story_planning.authority.execute"}),
            frozenset({HANDLER}),
            application.application_build_id,
            application.commit_sha,
        ),
        handler=materialize,
    )
    return follow(application, operation_id, command, principal=principal)
