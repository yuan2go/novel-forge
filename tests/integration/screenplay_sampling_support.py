from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.book_followup_authority.application import BookFollowupAdmission
from novel_forge.modules.book_followup_authority.screenplay import SCREENPLAY_STAGES
from novel_forge.modules.book_followup_authority.screenplay_sampling import (
    ScreenplaySampleCommand, screenplay_sample_definition, sample_definition_name, sample_purpose,
)
from novel_forge.modules.book_followup_authority.screenplay_sample_feedback import (
    require_screenplay_reference_subject, screenplay_annotation_scope, screenplay_reference_contract, screenplay_sample_outcomes,
)
from novel_forge.modules.capability_packs.screenplay_sample_profiles import build_screenplay_sampling_profile
from novel_forge.modules.capability_packs.validation_deployment import install_longform_validation_pack
from novel_forge.modules.chapter_authority.execution_gateway import ProductionExecutionGatewayExternalEffectAdapter
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.storage.authority_repositories import definition_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.unit.test_creative_budget_contract import provider_campaign_policy


def run_screenplay_samples(database_url, *, book, principal, app, followup, ports, profiles, source_id,
                           operations, application_build_id, commit_sha):
    project, workspace = book["project_id"], book["workspace_id"]
    principal = replace(principal, permissions=principal.permissions | {
        "provider.routing_policy.configure", "content.authority.execute", "content.operation:quality.human_evaluation.record",
        "content.operation:quality.adjudication.record", *("book.followup:" + sample_definition_name(stage) for stage in SCREENPLAY_STAGES)})
    for stage in SCREENPLAY_STAGES:
        definition = screenplay_sample_definition(application_build_id=application_build_id, commit_sha=commit_sha, stage=stage)
        with AuthorityUnitOfWork(database_url) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()
        profile = build_screenplay_sampling_profile(profiles[stage], stage=stage, operation_definition_hash=definition_hash(definition))
        install_longform_validation_pack(database_url, profile=profile, pack_version="1.0.0", agent_generation=1,
            expected_activation_version=0, project_id=project, workspace_id=workspace, book_id=book["book_id"],
            application_build_id=application_build_id, commit_sha=commit_sha,
            compiler=replace(principal, principal_id="screenplay-sample-fixture-compiler"),
            approver=replace(principal, principal_id="screenplay-sample-fixture-approver"),
            agent_admin=replace(principal, principal_id="screenplay-sample-fixture-admin"), agent_domain="book_followup", agent_scope_type="BOOK")
    receipts = []
    with AuthorityUnitOfWork(database_url) as uow:
        for operation in operations:
            uow.cursor.execute("SELECT dispatch.evidence FROM authority_external_effect effect JOIN authority_external_effect_dispatch dispatch USING(external_effect_id) WHERE effect.operation_id=%s AND dispatch.status='SUCCEEDED'", [operation["operation_id"]])
            receipts.append(uow.cursor.fetchone()[0])
    for model in ports.values():
        model.capability_binder.provider_router = ProductionProviderRouter(database_url, candidates=deepseek_candidates(available=True),
            execution_environment="validation", task_money_limit="1", task_token_limit=200000)
        model.max_cost_per_call = "1"
    cold = app.admit(stage="screenplay_generate", project_id=project, workspace_id=workspace, source_asset_version_id=source_id,
        principal=principal, idempotency_key="screenplay:coldstart:" + source_id)
    if not cold["replayed"]:
        with patch.object(ProductionExecutionGatewayExternalEffectAdapter, "execute", side_effect=AssertionError("No unqualified dispatch")):
            with pytest.raises(KernelError, match="PROVIDER_ROUTING_BLOCKED"):
                app.run(project_id=project, operation_id=cold["operation_id"], principal=principal)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [cold["operation_id"]])
        assert uow.cursor.fetchone() == ("PROVIDER_ROUTING_BLOCKED",)
    source_operation = cold["operation_id"]
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT COUNT(*) FROM authority_external_effect WHERE operation_id=%s", [source_operation])
        assert uow.cursor.fetchone()[0] == 0
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    budget = _budget(database_url, book, principal, expiry, application_build_id, commit_sha)
    expiry = budget["comparison_budget"]["expires_at"]
    upstream, grants, samples, calls = None, [], [], []
    expected_calls = 0
    for index, stage in enumerate(("screenplay_generate", "screenplay_review", "screenplay_revision", "screenplay_review")):
        command = ScreenplaySampleCommand(project, principal.principal_id, source_operation, "sample-grant-" + str(index),
            "screenplay-sample:" + source_id + ":" + str(index), stage, upstream)
        prepared = followup.prepare_screenplay_sample(command, principal=principal)
        assert prepared["provider_calls"] == 0
        candidate = deepseek_candidates(available=True)[0]
        grant = {"authorization_id": command.authorization_id, "reason": "scripted native screenplay sample closure",
            "environment": "validation", "book_id": book["book_id"], "task_type": stage, "logical_key": source_operation,
            "generation_idempotency_key": command.idempotency_key, "input_versions_hash": prepared["input_versions_hash"],
            "command_hash": prepared["command_hash"], "producer_contract_hash": prepared["producer_contract_hash"],
            "candidate_id": candidate.candidate_id, "model_revision": candidate.model_revision, "expires_at": expiry,
            "maximum_calls": 1, "maximum_tokens": 200000, "maximum_amount": "1", "currency": "USD",
            "purpose": sample_purpose(stage), "production_eligible": False,
            "campaign": {"campaign_id": budget["comparison_budget"]["experiment_id"], "manifest_hash": budget["comparison_budget"]["manifest_hash"],
                "sample_id": "screenplay-" + source_id + ":" + str(index), "group_id": source_operation + ":" + stage + ":" + str(index),
                "partition": "CALIBRATION", "maximum_calls": 4, "maximum_tokens": 800000, "maximum_amount": "4", "expires_at": expiry}}
        if stage == "screenplay_review":
            grant["reference_evaluation"] = prepared["command_payload"]["reference_evaluation"]
        grants.append(grant)
        configure_owned_policy(database_url=database_url, owner="PROVIDER_ROUTING", project_id=project, workspace_id=workspace,
            content={"policy_version": "scripted-screenplay-sampling-v1" + (":" + str(index) if index else ""), "reason": "fixture only", "task_overrides": [], "bootstrap_authorizations": grants},
            idempotency_key=command.idempotency_key + ":policy", trace_id="fixture", correlation_id="fixture",
            application_build_id=application_build_id, commit_sha=commit_sha, principal=principal)
        admitted = followup.admit_screenplay_sample(command, principal=principal)
        assert followup.admit_screenplay_sample(command, principal=principal)["operation_id"] == admitted["operation_id"]
        def invoke(adapter, **kwargs):
            calls.append(kwargs["request_payload"]["stage"])
            decision = kwargs["request_payload"]["_production_execution"]["capability_runtime"]["routing_decision"]
            assert decision["task"]["producer_contract_hash"] == prepared["producer_contract_hash"]
            evidence = deepcopy(receipts[index])
            evidence.update(fixture_protocol_only=True, real_model_call=False, production_verified=False)
            binding, _ = adapter._binding_and_session(kwargs["stable_idempotency_key"], kwargs["capability"], kwargs["request_payload"])
            evidence["production_execution"]["execution_request"] = binding.request.to_dict()
            return ProviderResult("success", "scripted-screenplay:" + kwargs["stable_idempotency_key"], evidence)
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [admitted["operation_id"]])
            previously_succeeded = uow.cursor.fetchone()[0] == "SUCCEEDED"
        expected_calls += not previously_succeeded
        admission = BookFollowupAdmission(admitted["operation_id"], project, False)
        with patch.object(ProductionExecutionGatewayExternalEffectAdapter, "execute", invoke):
            result = followup.run_or_recover(admission)
            followup.run_or_recover(admission)
        assert len(calls) == expected_calls
        upstream = {"asset_version_id": result.output.asset_version_id, "content_hash": result.output.content_hash}
        with AuthorityUnitOfWork(database_url) as uow:
            subject = require_screenplay_reference_subject(uow.cursor, project_id=project, binding=upstream)
            uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s", [admitted["operation_id"]])
            effect_id = uow.cursor.fetchone()[0]
            assert screenplay_sample_outcomes(uow.cursor, project_id=project, effect_ids=[effect_id]) == {}
            uow.cursor.execute("SELECT eligibility FROM authority_asset_version WHERE asset_version_id=%s", [upstream["asset_version_id"]])
            assert uow.cursor.fetchone()[0] == "INELIGIBLE"
            from novel_forge.modules.command_kernel.creative_budget_runtime import _campaign_scope, _effect_identity
            scope = _campaign_scope(uow.cursor, _effect_identity(uow.cursor, effect_id, project), plan=budget["comparison_budget"], project_id=project, generation=1)
            assert scope["phase"] == ("REFERENCE" if stage == "screenplay_review" else "CALIBRATION")
        if index in (0, 1) and not previously_succeeded:
            _annotations(database_url, project, workspace, principal, upstream, subject, application_build_id, commit_sha)
            with AuthorityUnitOfWork(database_url) as uow:
                assert screenplay_sample_outcomes(uow.cursor, project_id=project, effect_ids=[effect_id]) == {}
        samples.append({"stage": stage, "operation_id": admitted["operation_id"], "effect_id": effect_id,
            "target": upstream, "producer_contract_hash": prepared["producer_contract_hash"], "scope": scope})
    with pytest.raises(KernelError, match="ASSET_SCOPE_INVALID"):
        app.admit(stage="screenplay_review", project_id=project, workspace_id=workspace, source_asset_version_id=source_id,
            candidate_asset_version_id=samples[0]["target"]["asset_version_id"], principal=principal, idempotency_key="sample-cannot-be-formal:" + source_id)
    return {"evidence_class": "SCRIPTED_NATIVE_POSTGRESQL_INTEGRATION", "actual_real_model_calls": 0,
        "actual_human_evaluations": 0, "coldstart_source_operation_id": source_operation, "samples": samples,
        "scripted_call_count": len(calls), "qualification": "NOT_PROVEN"}


def _budget(database_url, book, principal, expiry, build, sha):
    from novel_forge.modules.command_kernel.creative_budget_runtime import _usage
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT command_payload->'policy' FROM authority_operation WHERE project_id=%s AND definition_name='creative.experiment_budget.configure' AND idempotency_key=%s AND status='SUCCEEDED'",
            [book["project_id"], "screenplay-budget:" + book["book_run_id"]])
        previous = uow.cursor.fetchone()
        if previous:
            return previous[0]
    policy = provider_campaign_policy()
    project = book["project_id"]
    arm = policy["comparison_budget"]["arms"][0]
    arm.update(project_id=project, book_id=book["book_id"])
    with AuthorityUnitOfWork(database_url) as uow:
        usage = _usage(uow.cursor, policy["comparison_budget"], project)
        uow.cursor.execute("SELECT v.content FROM authority_runtime_policy_selection s JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version) WHERE s.owner='CREATIVE_EXPERIMENT_BUDGET' AND s.project_id=%s", [project])
        selected = uow.cursor.fetchone()
        prior_caps = (selected[0].get("authorization", {}).get("authorized_cumulative_caps", {}) if selected else {})
    for phase, allocation in policy["authorization"]["authorized_cumulative_caps"].items():
        historical = usage["phases"][phase]
        extra = 2 if phase in {"REFERENCE", "CALIBRATION"} else 0
        prior = prior_caps.get(phase, {})
        allocation.update(calls=max(prior.get("calls", 0), historical["calls_used_or_reserved"]) + extra,
            tokens=max(prior.get("tokens", 0), historical["conservative_tokens"], historical["calls_used_or_reserved"] * 1000) + extra * 200000,
            priced_usd=str(max(Decimal(prior.get("priced_usd", "0")), Decimal(10 if historical["calls_used_or_reserved"] or extra else 0))))
        arm[phase.lower() + "_allocation"] = dict(allocation)
    allocations = policy["authorization"]["authorized_cumulative_caps"].values()
    totals = {**{key: sum(row[key] for row in allocations) for key in ("calls", "tokens")},
        "priced_usd": str(sum(Decimal(row["priced_usd"]) for row in allocations))}
    arm["project_total"] = totals
    policy["comparison_budget"].update(experiment_id=project, expires_at=expiry, shared_total=totals, entitlements=[])
    policy["authorization"].update(project_id=project, book_id=book["book_id"])
    configure_owned_policy(database_url=database_url, owner="CREATIVE_EXPERIMENT_BUDGET", project_id=project,
        workspace_id=book["workspace_id"], content=policy, idempotency_key="screenplay-budget:" + book["book_run_id"], trace_id="fixture", correlation_id="fixture",
        application_build_id=build, commit_sha=sha, principal=principal)
    return policy


def _annotations(database_url, project, workspace, principal, target, subject, build, sha):
    from novel_forge.modules.content_authority.application import ContentAuthorityApplication, ContentOperationRequest
    from novel_forge.modules.content_authority import CONTENT_CODECS
    from tests.integration.authority_postgres_support import identifier
    app = ContentAuthorityApplication(database_url, application_build_id=build, commit_sha=sha, integration_proven=CONTENT_CODECS, trusted_only=True)
    scope = screenplay_annotation_scope(subject)
    unit = subject["source"]["source_units"][0]
    content = subject["content"]
    output = content["input_candidate"] if content["stage"] == "screenplay_review" else content["sampled_output"]
    scene = output["scenes"][0]
    location = {"source_digest": subject["source"]["source_digest"], "unit_id": unit["unit_id"], "scene_id": scene["scene_id"],
        "beat_id": scene["beats"][0]["beat_id"], "start": 0, "end": 2, "quote": unit["text"][:2], "sample_path": "/findings",
        "observation": "Scripted schema/permission boundary check; not actual human literary judgment.", "fixture_protocol_only": True}
    def author(name, actor, payload, inputs):
        return app.execute(ContentOperationRequest(name, project, workspace, actor, "fixture", "fixture", identifier("screenplay-label"),
            {**payload, "reference_sample": target}, tuple(inputs)), principal=replace(principal, principal_id=actor))
    for dimension in screenplay_reference_contract(content["stage"], subject["producer_contract_hash"])["dimensions"]:
        shared = {**scope, "subject_asset_version_id": target["asset_version_id"], "dimension": dimension, "status": "PASSED"}
        humans = []
        for number in (1, 2):
            actor = "screenplay-fixture-human-" + str(number)
            body = {**shared, "evaluation_id": identifier("human"), "evaluator_id": actor,
                "evaluator_group": "SCRIPTED_INTEGRATION_FIXTURE", "evaluator_identity_class": "PROFESSIONAL_EDITOR",
                "score": 88, "confidence": 0.8, "evidence": [location], "blind": True}
            if number == 1:
                with pytest.raises(KernelError, match="SCREENPLAY_REFERENCE_SCOPE_INVALID"):
                    author("quality.human_evaluation.record", actor, {"evaluation": {**body, "evaluation_version": "stale"}}, [target])
            result = author("quality.human_evaluation.record", actor, {"evaluation": body}, [target])
            humans.append({"asset_version_id": result.asset_version_id, "content_hash": result.content_hash})
        author("quality.adjudication.record", "screenplay-fixture-adjudicator", {"adjudication": {
            **shared, "adjudication_id": identifier("adjudication"), "adjudicator_id": "screenplay-fixture-adjudicator",
            "adjudicator_identity_class": "PROFESSIONAL_EDITOR", "score_range": [85, 90],
            "source_human_evaluation_asset_version_ids": [item["asset_version_id"] for item in humans], "rationale": "Scripted boundary only."}}, [target, *humans])
