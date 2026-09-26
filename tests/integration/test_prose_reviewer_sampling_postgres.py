from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

from novel_forge.api.authority_dependencies import build_production_execution_composition, build_longform_prose_review_model_port
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.book_followup_authority.application import BookFollowupAdmission, BookFollowupAuthorityApplication
from novel_forge.modules.book_followup_authority.prose_coordinator import BookProseReviewCoordinator
from novel_forge.modules.book_followup_authority.prose_sampling import ProseReviewSampleCommand, PROSE_SAMPLE_TYPE
from novel_forge.modules.book_followup_authority.prose_sample_feedback import (
    PROSE_REVIEWER_DIMENSIONS, prose_annotation_scope, prose_sample_outcomes,
)
from novel_forge.modules.capability_packs.longform_profiles import build_longform_prose_review_pack_profile, build_longform_prose_review_sample_pack_profile
from novel_forge.modules.capability_packs.validation_deployment import register_validation_runtime_definitions, install_longform_validation_pack
from novel_forge.modules.chapter_authority.execution_gateway import ProductionExecutionGatewayExternalEffectAdapter
from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject
from novel_forge.modules.chapter_quality_authority.reference_sampling import require_adjudicated_reference
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.content_authority.application import ContentAuthorityApplication, ContentOperationRequest
from novel_forge.modules.content_authority import CONTENT_CODECS
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier
from tests.integration.test_longform_prose_editorial_postgres import _accept_chapter, metadata, scripted_book
from tests.integration.capability_pack_postgres_support import ROOT


def _principal(project, actor):
    from tests.integration.capability_pack_postgres_support import PACK_PERMISSIONS

    return Principal(actor, PrincipalType.LOCAL_OPERATOR, frozenset({*PACK_PERMISSIONS,
        "book.authority.execute", "book.authority.query", "book.followup:longform.prose_review",
        "book.followup:longform.prose_review.sample", "provider.routing_policy.configure",
        "agent.authority.admin", "content.authority.execute", "content.operation:quality.human_evaluation.record",
        "content.operation:quality.adjudication.record"}), frozenset({project}), "integration-fixture")


def _authorize_budget(project, book, workspace, principal, expiry):
    from novel_forge.modules.command_kernel.creative_budget_runtime import _usage
    from tests.unit.test_creative_budget_contract import provider_campaign_policy

    policy = provider_campaign_policy()
    arm = policy["comparison_budget"]["arms"][0]
    arm.update(project_id=project, book_id=book)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        usage = _usage(uow.cursor, policy["comparison_budget"], project)
    for phase, allocation in policy["authorization"]["authorized_cumulative_caps"].items():
        historical = usage["phases"][phase]
        extra = 2 if phase == "REFERENCE" else 0
        allocation.update(calls=historical["calls_used_or_reserved"] + extra,
            tokens=max(historical["conservative_tokens"], historical["calls_used_or_reserved"] * 1000) + extra * 200000,
            priced_usd="10" if historical["calls_used_or_reserved"] or extra else "0")
        arm[phase.lower() + "_allocation"] = dict(allocation)
    allocations = policy["authorization"]["authorized_cumulative_caps"].values()
    totals = {**{key: sum(row[key] for row in allocations) for key in ("calls", "tokens")},
              "priced_usd": str(sum(int(row["priced_usd"]) for row in allocations))}
    arm["project_total"] = totals
    policy["comparison_budget"].update(experiment_id=project, expires_at=expiry, shared_total=totals, entitlements=[])
    policy["authorization"].update(project_id=project, book_id=book)
    configure_owned_policy(database_url=DATABASE_URL, owner="CREATIVE_EXPERIMENT_BUDGET", project_id=project,
        workspace_id=workspace, content=policy, idempotency_key=project + ":prose-budget", trace_id="fixture", correlation_id="fixture",
        application_build_id="prose-test", commit_sha="e" * 40, principal=principal)
    return policy


def test_native_prose_reviewer_sample_isolated_from_formal_findings_and_human_feedback(tmp_path, request):
    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=1)
        _accept_chapter(helper, fixture, 1)
        project = fixture["project_id"]
        workspace, book = "workspace:" + project, "book:" + project
        principal = _principal(project, "prose-sample-operator")
        versions = register_validation_runtime_definitions(DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40)
        formal = build_longform_prose_review_pack_profile(ROOT, operation_definition_hash=versions["prose_review"], pack_id="prose-" + project)
        sample_profile = build_longform_prose_review_sample_pack_profile(formal, operation_definition_hash=versions["prose_sample"])
        for profile in (formal, sample_profile):
            install_longform_validation_pack(DATABASE_URL, profile=profile, pack_version="1.0.0", agent_generation=1,
                expected_activation_version=0, project_id=project, workspace_id=workspace, book_id=book,
                application_build_id="prose-test", commit_sha="e" * 40, compiler=_principal(project, "compiler"),
                approver=_principal(project, "approver"), agent_admin=_principal(project, "agent-admin"),
                agent_domain="book_followup", agent_scope_type="BOOK")
        settings = IndustrialSettings(root=ROOT, environment="development", storage_authority="postgresql", database_url=DATABASE_URL)
        env = {"NOVEL_FORGE_ENVIRONMENT": "development", "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_COMMIT_SHA": "e" * 40, "NOVEL_FORGE_APPLICATION_BUILD_ID": "prose-test",
            "NOVEL_FORGE_LONGFORM_PROSE_REVIEW_CAPABILITY_PACK_ID": formal.pack_id,
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path)}
        execution = build_production_execution_composition(settings, env=env)
        execution.gateway.routes = {stage: replace(route, model_context_limit=200000) for stage, route in execution.gateway.routes.items()}
        model = build_longform_prose_review_model_port(settings, execution=execution, env=env)
        binder = model.capability_binder
        binder.pack_environment = binder.pack_runtime_profile = "validation"
        followup = BookFollowupAuthorityApplication(DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40, prose_model_port=model)
        coordinator = BookProseReviewCoordinator(followup)
        scope = dict(project_id=project, workspace_id=workspace, book_run_id=fixture["book"].book_run_id, principal=principal)
        run = coordinator.start(**scope, **metadata("formal-prose"), policy={"policy_version": "v1", "window_codepoints": 2048,
            "overlap_codepoints": 32, "context_token_budget": 16000, "maximum_windows": 1})
        formal_progress = coordinator.advance(**scope, run_id=run["run_id"], expected_version=0, **metadata("formal-advance"))
        original = formal_progress["operations"][0]["operation_id"]
        command = ProseReviewSampleCommand(project, principal.principal_id, original, "prose-grant", project + ":sample")
        prepared = followup.prepare_prose_sample(command, principal=principal)
        assert prepared["provider_calls"] == 0
        with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED"):
            followup.admit_prose_sample(command, principal=principal)
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        budget = _authorize_budget(project, book, workspace, principal, expiry)
        candidate = deepseek_candidates(available=True)[0]
        grant = {"authorization_id": command.authorization_id, "reason": "isolated scripted prose sampling boundary regression",
            "environment": "validation", "book_id": book, "task_type": "longform_prose_review", "logical_key": original,
            "generation_idempotency_key": command.idempotency_key, "input_versions_hash": prepared["input_versions_hash"],
            "command_hash": prepared["command_hash"], "producer_contract_hash": prepared["producer_contract_hash"],
            "candidate_id": candidate.candidate_id, "model_revision": candidate.model_revision, "expires_at": expiry,
            "maximum_calls": 1, "maximum_tokens": 200000, "maximum_amount": "1", "currency": "USD",
            "purpose": "REFERENCE_EVALUATION", "reference_evaluation": prepared["command_payload"]["reference_evaluation"],
            "production_eligible": False, "campaign": {"campaign_id": project, "manifest_hash": "sha256:" + "c" * 64,
                "sample_id": "reviewer-window", "group_id": original, "partition": "CALIBRATION", "maximum_calls": 2,
                "maximum_tokens": 400000, "maximum_amount": "2", "expires_at": expiry}}
        configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=project, workspace_id=workspace,
            content={"policy_version": "prose-sampling-v1", "reason": "fixture-only", "task_overrides": [], "bootstrap_authorizations": [grant]},
            idempotency_key=project + ":router", trace_id="fixture", correlation_id="fixture", application_build_id="prose-test", commit_sha="e" * 40, principal=principal)
        binder.provider_router = ProductionProviderRouter(DATABASE_URL, candidates=deepseek_candidates(available=True),
            execution_environment="validation", task_money_limit="1", task_token_limit=200000)
        model.max_cost_per_call = "1"
        admitted = followup.admit_prose_sample(command, principal=principal)
        assert followup.admit_prose_sample(command, principal=principal)["operation_id"] == admitted["operation_id"]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT dispatch.evidence,effect.request_payload FROM authority_external_effect effect JOIN authority_external_effect_dispatch dispatch USING(external_effect_id) WHERE effect.operation_id=%s AND dispatch.status='SUCCEEDED'", [original])
            original_evidence, original_request = uow.cursor.fetchone()
        calls = []

        def invoke(adapter, **kwargs):
            calls.append(kwargs)
            decision = kwargs["request_payload"]["_production_execution"]["capability_runtime"]["routing_decision"]
            assert decision["task"]["producer_contract_hash"] == prepared["producer_contract_hash"]
            assert decision["task"]["input_hash"] == original_request["_production_execution"]["capability_runtime"]["provider_admission"]["input_component_hashes"]["fully_rendered_prompt"]
            evidence = deepcopy(original_evidence)
            evidence.update(fixture_protocol_only=True, real_model_call=False, production_verified=False)
            binding, _ = adapter._binding_and_session(kwargs["stable_idempotency_key"], kwargs["capability"], kwargs["request_payload"])
            evidence["production_execution"]["execution_request"] = binding.request.to_dict()
            return ProviderResult("success", "fixture-prose-sample:" + kwargs["stable_idempotency_key"], evidence)

        native_admission = BookFollowupAdmission(admitted["operation_id"], project, False)
        with patch.object(ProductionExecutionGatewayExternalEffectAdapter, "execute", invoke):
            result = followup.run_or_recover(native_admission)
            followup.run_or_recover(native_admission)
        assert len(calls) == 1
        target = {"asset_version_id": result.output.asset_version_id, "content_hash": result.output.content_hash}
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            subject = require_reference_subject(uow.cursor, project_id=project, binding=target, allowed_types=frozenset({PROSE_SAMPLE_TYPE}))
            uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s", [admitted["operation_id"]])
            effect_id = uow.cursor.fetchone()[0]
            assert prose_sample_outcomes(uow.cursor, project_id=project, effect_ids=[effect_id]) == {}
            uow.cursor.execute("SELECT asset.asset_type,version.eligibility FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE output.operation_id=%s AND output.role='primary'", [admitted["operation_id"]])
            assert uow.cursor.fetchone() == (PROSE_SAMPLE_TYPE, "INELIGIBLE")
        _native_annotations(project, workspace, target, subject)
        assert coordinator.report(**scope, run_id=run["run_id"])["review_digest"] == formal_progress["review_digest"]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            assert prose_sample_outcomes(uow.cursor, project_id=project, effect_ids=[effect_id]) == {}
            from novel_forge.modules.command_kernel.creative_budget_runtime import _business_scope, _campaign_scope, _effect_identity, _usage

            usage = _usage(uow.cursor, budget["comparison_budget"], project)
            assert usage["phases"]["REFERENCE"]["calls_used_or_reserved"] == 1
            sampled_identity = _effect_identity(uow.cursor, effect_id, project)
            sampled_scope = _campaign_scope(uow.cursor, sampled_identity, plan=budget["comparison_budget"], project_id=project, generation=1)
            assert sampled_scope["phase"] == "REFERENCE" and sampled_scope["source_operation_id"] == original
            uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s", [original])
            identity = _effect_identity(uow.cursor, uow.cursor.fetchone()[0], project)
            historical = _business_scope(uow.cursor, identity, project_id=project)
            assert historical["chapter_number"] == 1 and historical["scope_sources"][-1]["value"]["manifest_digest"] == run["manifest_digest"]
            for mutated in ("command", "provider_pointer"):
                changed = deepcopy(identity)
                if mutated == "command":
                    changed["command_payload"]["payload"]["window_id"] = "stale-window"
                else:
                    changed["request_payload"]["_production_execution"]["input_artifacts"][0]["content_hash"] = "sha256:" + "0" * 64
                with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN"):
                    _business_scope(uow.cursor, changed, project_id=project)
        request.node.user_properties.append(("prose_reviewer_native", json.dumps({
            "evidence_class": "SCRIPTED_NATIVE_POSTGRESQL_INTEGRATION", "actual_real_model_calls": 0,
            "actual_human_evaluations": 0, "project_id": project, "source_operation_id": original,
            "sample_operation_id": admitted["operation_id"], "effect_id": effect_id,
            "sample": target, "subject": subject, "usage": usage, "scope": sampled_scope,
            "provider_calls": len(calls), "sample_eligibility": "INELIGIBLE",
            "formal_review_digest_unchanged": formal_progress["review_digest"],
            "independent_quality_projection": {},
        }, sort_keys=True, default=str)))
    finally:
        helper.doCleanups()


def _native_annotations(project, workspace, target, subject):
    app = ContentAuthorityApplication(DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40, integration_proven=CONTENT_CODECS, trusted_only=True)
    scope = prose_annotation_scope(producer_contract_hash=subject["producer_contract_hash"], window=subject["window"])
    span = subject["window"]["window"]["spans"][0]
    location = {"manifest_digest": subject["window"]["manifest_digest"], "window_id": subject["window"]["window"]["window_id"],
        "sample_path": "/findings", "observation": "Scripted annotation fixture, not an actual editorial judgment.",
        "asset_version_id": span["asset_version_id"], "text_hash": span["text_hash"], "start": span["start"],
        "end": span["start"] + 2, "quote": span["text"][:2], "fixture_protocol_only": True}
    labels = []

    def author(name, actor, payload, inputs):
        return app.execute(ContentOperationRequest(name, project, workspace, actor, "fixture", "fixture", identifier("prose-label"),
            {**payload, "reference_sample": target}, tuple(inputs)), principal=_principal(project, actor))

    for dimension in PROSE_REVIEWER_DIMENSIONS:
        shared = {**scope, "subject_asset_version_id": target["asset_version_id"], "dimension": dimension, "status": "PASSED"}
        humans = []
        for number in (1, 2):
            actor = "fixture-human-" + str(number)
            body = {**shared, "evaluation_id": identifier("human"), "evaluator_id": actor,
                "evaluator_group": "SCRIPTED_INTEGRATION_FIXTURE", "evaluator_identity_class": "PROFESSIONAL_EDITOR",
                "score": 88, "confidence": 0.8, "evidence": [location], "blind": True}
            if number == 1:
                with pytest.raises(KernelError, match="PROSE_REVIEWER_LABEL_SCOPE_INVALID"):
                    author("quality.human_evaluation.record", actor, {"evaluation": {**body, "evaluation_version": "stale-scope"}}, [target])
            human = author("quality.human_evaluation.record", actor, {"evaluation": body}, [target])
            humans.append({"asset_version_id": human.asset_version_id, "content_hash": human.content_hash})
        adjudication = author("quality.adjudication.record", "fixture-adjudicator", {"adjudication": {
            **shared, "adjudication_id": identifier("adjudication"), "adjudicator_id": "fixture-adjudicator",
            "adjudicator_identity_class": "PROFESSIONAL_EDITOR", "score_range": [85, 90],
            "source_human_evaluation_asset_version_ids": [item["asset_version_id"] for item in humans],
            "rationale": "Scripted boundary evidence only."}}, [target, *humans])
        labels.append({"asset_version_id": adjudication.asset_version_id, "content_hash": adjudication.content_hash})
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        reference = require_adjudicated_reference(uow.cursor, project_id=project,
            binding={"protocol_version": scope["protocol_version"], "adjudications": labels},
            target_id=target["asset_version_id"], target_hash=target["content_hash"], generators=[subject["generation_actor_id"]],
            evaluator_actor_id=subject["generation_actor_id"], chapter=scope["chapter_start"], chapter_end=scope["chapter_end"],
            scope_type=scope["scope_type"], expected_dimensions=PROSE_REVIEWER_DIMENSIONS, allowed_statuses={"PASSED"})
        assert len(reference["labels"]) == 4
        with pytest.raises(KernelError, match="QUALITY_REFERENCE_NOT_INDEPENDENT"):
            require_adjudicated_reference(uow.cursor, project_id=project,
                binding={"protocol_version": scope["protocol_version"], "adjudications": labels}, target_id=target["asset_version_id"],
                target_hash=target["content_hash"], generators=["fixture-human-1"], evaluator_actor_id=subject["generation_actor_id"],
                chapter=scope["chapter_start"], chapter_end=scope["chapter_end"], scope_type=scope["scope_type"],
                expected_dimensions=PROSE_REVIEWER_DIMENSIONS, allowed_statuses={"PASSED"})


def test_prose_coldstart_prepares_native_sampling_after_qualification_blocks_formal_send(tmp_path):
    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=1)
        _accept_chapter(helper, fixture, 1)
        project = fixture["project_id"]
        workspace, book = "workspace:" + project, "book:" + project
        principal = _principal(project, "coldstart-sample-operator")
        versions = register_validation_runtime_definitions(DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40)
        profile = build_longform_prose_review_pack_profile(ROOT, operation_definition_hash=versions["prose_review"], pack_id="coldstart-" + project)
        install_longform_validation_pack(DATABASE_URL, profile=profile, pack_version="1.0.0", agent_generation=1,
            expected_activation_version=0, project_id=project, workspace_id=workspace, book_id=book,
            application_build_id="prose-test", commit_sha="e" * 40, compiler=_principal(project, "compiler"),
            approver=_principal(project, "approver"), agent_admin=_principal(project, "agent-admin"),
            agent_domain="book_followup", agent_scope_type="BOOK")
        settings = IndustrialSettings(root=ROOT, environment="development", storage_authority="postgresql", database_url=DATABASE_URL)
        env = {"NOVEL_FORGE_ENVIRONMENT": "development", "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_COMMIT_SHA": "e" * 40, "NOVEL_FORGE_APPLICATION_BUILD_ID": "prose-test",
            "NOVEL_FORGE_LONGFORM_PROSE_REVIEW_CAPABILITY_PACK_ID": profile.pack_id,
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path)}
        execution = build_production_execution_composition(settings, env=env)
        model = build_longform_prose_review_model_port(settings, execution=execution, env=env)
        binder = model.capability_binder
        binder.pack_environment = binder.pack_runtime_profile = "validation"
        binder.provider_router = ProductionProviderRouter(DATABASE_URL, candidates=deepseek_candidates(available=True),
            execution_environment="validation", task_money_limit="1", task_token_limit=200000)
        followup = BookFollowupAuthorityApplication(DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40, prose_model_port=model)
        coordinator = BookProseReviewCoordinator(followup)
        scope = dict(project_id=project, workspace_id=workspace, book_run_id=fixture["book"].book_run_id, principal=principal)
        run = coordinator.start(**scope, **metadata("coldstart-prose"), policy={"policy_version": "v1", "window_codepoints": 2048,
            "overlap_codepoints": 32, "context_token_budget": 16000, "maximum_windows": 1})
        with patch.object(ProductionExecutionGatewayExternalEffectAdapter, "execute", side_effect=AssertionError("unqualified task must never dispatch")):
            with pytest.raises(KernelError, match="PROVIDER_ROUTING_BLOCKED"):
                coordinator.advance(**scope, run_id=run["run_id"], expected_version=0, **metadata("coldstart-advance"))
        progress = coordinator.report(**scope, run_id=run["run_id"])
        source = progress["operations"][0]["operation_id"]
        prepared = followup.prepare_prose_sample(ProseReviewSampleCommand(project, principal.principal_id, source, "pending-grant", "pending-sample"), principal=principal)
        assert prepared["provider_calls"] == 0 and prepared["producer_contract_hash"].startswith("sha256:")
        assert prepared["command_payload"]["prose_sampling"]["source_operation_id"] == source
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT COUNT(*) FROM authority_external_effect WHERE operation_id=%s", [source])
            assert uow.cursor.fetchone()[0] == 0
    finally:
        helper.doCleanups()
