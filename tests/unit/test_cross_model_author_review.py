from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.author_supervision import supervised_decision, verify_frozen_supervision
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.review.cross_model_binding import generator_identity
from novel_forge.modules.production_execution.cross_model_review import reviewer_rejection
from tests.unit.test_author_supervised_routing import prepared
from tests.unit.test_cost_aware_routing import NOW


def contract(provider="codex-cli"):
    return {"generator": {"provider": provider, "model": "generator-model", "model_revision": "gen-r1"},
        "required_reviewer_provider": "deepseek" if provider == "codex-cli" else "codex-cli",
        "target_asset_version_id": "exact-draft", "target_content_hash": "sha256:" + "c" * 64}


@pytest.mark.parametrize("kind", ["AUTHOR_ORIGINAL", "MODEL_EDITED_BY_AUTHOR", "EDITION_MIXED"])
def test_authored_source_contract_requires_exact_authorized_reviewer_and_immutable_provenance(kind):
    from dataclasses import asdict
    task, model = prepared("review")
    reviewer = {key: asdict(model)[key] for key in ("candidate_id", "provider", "model", "model_revision")}
    source = {"kind": kind, "decision": {"asset_version_id": "author-decision", "content_hash": "decision-hash"}}
    requirement = {"schema_version": "cross-model-review.v2", "target_asset_version_id": "new-draft",
        "target_content_hash": "new-hash", "source": source, "source_hash": snapshot_hash(source),
        "reviewer_policy": "EXPLICIT_AUTHORIZED_REVIEWER", "authorized_reviewer": reviewer, "purpose": "AUTHOR_ADVISORY"}
    scope = replace(task, declared_requirements={"cross_model_review": requirement})
    result = supervised_decision(CostAwareRouter().explain(scope, [model], {}, now=NOW), now=NOW).to_dict()
    assert result["status"] == "AUTHOR_SUPERVISED_SELECTED"
    verify_frozen_supervision(result)
    assert "generator" not in requirement
    assert reviewer_rejection(requirement, {**reviewer, "model_revision": "unapproved"}) == "CROSS_MODEL_REVIEW_AUTHORIZED_REVIEWER_REQUIRED"
    assert reviewer_rejection({**requirement, "authorized_reviewer": {}}, reviewer) == "CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED"
    assert reviewer_rejection({**requirement, "source": {**source, "kind": "invented"}}, reviewer) == "CROSS_MODEL_REVIEW_IDENTITY_INVALID"
    assert reviewer_rejection({**requirement, "schema_version": "cross-model-review.v99"}, reviewer) == "CROSS_MODEL_REVIEW_IDENTITY_INVALID"


@pytest.mark.parametrize("provider", ["codex-cli", "deepseek"])
def test_opposite_provider_is_required_even_with_author_permission(provider):
    scope, model = prepared("review")
    scope = replace(scope, declared_requirements={"cross_model_review": contract(provider)})
    reviewer = replace(model, provider=contract(provider)["required_reviewer_provider"], model="reviewer-model")
    result = supervised_decision(CostAwareRouter().explain(scope, [reviewer], {}, now=NOW), now=NOW).to_dict()
    assert result["status"] == "AUTHOR_SUPERVISED_SELECTED"
    assert result["independent_qualification_eligible"] is False
    verify_frozen_supervision(result)
    same = replace(reviewer, provider=provider)
    blocked = supervised_decision(CostAwareRouter().explain(scope, [same], {}, now=NOW), now=NOW).to_dict()
    assert blocked["status"] == "BLOCKED"
    assert "CROSS_MODEL_REVIEW_DIFFERENT_PROVIDER_REQUIRED" in blocked["candidates"][0]["rejected_reasons"]
    result["selected"]["candidate"]["provider"] = provider
    with pytest.raises(KernelError, match="DIFFERENT_PROVIDER"):
        verify_frozen_supervision(result)


def test_different_account_or_alias_does_not_establish_independence():
    value = contract()
    assert reviewer_rejection(value, {"provider": "codex-cli", "model": "another-model"})
    assert reviewer_rejection(value, {"provider": "deepseek", "model": "generator-model"})
    value["required_reviewer_provider"] = "codex-cli"
    assert reviewer_rejection(value, {"provider": "codex-cli", "model": "reviewer"}) == "CROSS_MODEL_REVIEW_IDENTITY_INVALID"


def test_unknown_and_schema_failures_still_block_cross_model_review():
    scope, model = prepared("review")
    model = replace(model, provider="deepseek", model="reviewer")
    for failure in ("UNKNOWN_EXTERNAL_OUTCOME", "SCHEMA_REJECTION"):
        task = replace(scope, declared_requirements={"cross_model_review": contract()},
            history=({"candidate_id": model.candidate_id, "failure_class": failure},))
        assert supervised_decision(CostAwareRouter().explain(task, [model], {}, now=NOW), now=NOW).to_dict()["status"] == "BLOCKED"


def test_generator_receipt_is_required_and_benchmark_source_is_rejected():
    class Cursor:
        rows = []
        def execute(self, sql, values):
            assert values == ["project", "draft", "sha256:" + "c" * 64, "book"]
        def fetchall(self):
            return self.rows
    cursor = Cursor()
    args = dict(project_id="project", book_id="book", asset_version_id="draft", content_hash="sha256:" + "c" * 64)
    with pytest.raises(KernelError, match="SOURCE_REQUIRED"):
        generator_identity(cursor, **args)
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash
    evidence = {"real_model_call": True, "model_id": "model", "provider_id": "deepseek"}
    cursor.rows = [("effect", "model", {"bootstrap_authorization": {"id": "sample"}, "decision_id": "routing",
        "selected": {"candidate": {"model": "model", "provider": "deepseek", "model_revision": "revision"}}},
        evidence, snapshot_hash(evidence), {"evidence": evidence}, "VERIFIED")]
    with pytest.raises(KernelError, match="SOURCE_INVALID"):
        generator_identity(cursor, **args)


def test_author_must_dispose_exact_model_findings_without_claiming_qualification():
    from novel_forge.modules.authority_security import Principal, PrincipalType
    from novel_forge.modules.story_design_authority.author_supervision import validate_author_review
    class Cursor:
        def execute(self, sql, args):
            assert args == ["project", "draft", "hash"]
        def fetchall(self):
            return [("review:1", "review-hash", {"evaluations": [{"layer": "CAUSALITY", "criteria": [
                {"criterion": "knowledge", "verdict": "FAIL"}, {"criterion": "motivation", "verdict": "PASS"}]}]})]
    principal = Principal("author", PrincipalType.LOCAL_OPERATOR, frozenset({"story_design.authority.execute"}), frozenset({"project"}), "unit-test")
    review = {"asset_version_id": "draft", "content_hash": "hash", "decision": "ACCEPT", "reason": "Exact text reviewed", "findings": []}
    args = dict(principal=principal, supervision={"project_id": "project", "author_id": "author"}, asset_version_id="draft", content_hash="hash", cursor=Cursor())
    with pytest.raises(KernelError, match="UNRESOLVED_FINDING"):
        validate_author_review(review, **args)
    review["findings"] = [{"finding_id": "review:1:CAUSALITY:knowledge", "disposition": "DISMISSED_WITH_EVIDENCE", "reason": "Paragraph 4 contains the witnessed disclosure."}]
    assert validate_author_review(review, **args) == [{"asset_version_id": "review:1", "content_hash": "review-hash", "purpose": "AUTHOR_ADVISORY"}]
    with pytest.raises(PermissionError):
        validate_author_review(review, **{**args, "principal": replace(principal, principal_type=PrincipalType.SERVICE)})


def test_old_evaluation_payload_remains_strict_and_advisory_is_explicit():
    from novel_forge.modules.story_design_authority.evaluation_runtime import NarrativeSemanticEvaluationCommand, evaluation_command_payload
    command = NarrativeSemanticEvaluationCommand(project_id="project", workspace_id="workspace", book_id="book", actor_id="reviewer",
        candidate_asset_version_id="draft", generation_operation_id="generation", generator_operation_name="creative.candidates.generate",
        candidate_content_hash="sha256:"+"a"*64, evaluator_execution_class="MODEL_PROVIDER", idempotency_key="review", trace_id="trace", correlation_id="correlation")
    assert "evaluation_purpose" not in evaluation_command_payload(command, generation_actor_id="generator", opening_execution_binding={})
    advisory = replace(command, author_supervised_review=True)
    assert evaluation_command_payload(advisory, generation_actor_id="generator", opening_execution_binding={})["evaluation_purpose"] == "AUTHOR_ADVISORY"
    with pytest.raises(ValueError):
        replace(advisory, evaluator_execution_class="SCRIPTED_FIXTURE", evaluation={"status": "PASS"})
    with pytest.raises(ValueError):
        replace(advisory, routing_bootstrap_authorization_id="diagnostic")


def test_trial_reviewer_cannot_be_used_for_strict_qualification():
    scope, model = prepared("narrative_semantic_evaluation")
    model = replace(model, provider="deepseek", model="reviewer")
    for purpose in (None, "STRICT_QUALIFICATION", "AUTHOR_ADVISORY"):
        cross = {**contract(), **({"purpose": purpose} if purpose else {})}
        task = replace(scope, declared_requirements={"cross_model_review": cross})
        strict = CostAwareRouter().explain(task, [model], {}, now=NOW)
        result = supervised_decision(strict, now=NOW).to_dict()
        if purpose != "AUTHOR_ADVISORY":
            assert result == strict.to_dict()
            assert result["status"] == "BLOCKED"
        else:
            assert result["status"] == "AUTHOR_SUPERVISED_SELECTED"
            result["task"]["declared_requirements"]["cross_model_review"]["purpose"] = "STRICT_QUALIFICATION"
            with pytest.raises(KernelError, match="AUTHOR_ADVISORY_PURPOSE_REQUIRED"):
                verify_frozen_supervision(result)


@pytest.mark.parametrize("frozen", [None, "AUTHOR_ADVISORY"])
def test_review_purpose_is_read_from_native_frozen_command(frozen):
    from unittest.mock import patch
    from novel_forge.modules.review.cross_model_binding import freeze_review_requirement
    class Cursor:
        def execute(self, sql, args):
            assert args == ["project", "operation"]
        def fetchall(self):
            return [("exact-draft", "hash", "chapter_plan", {},
                     {"payload": {"evaluation_purpose": frozen}})]
    with patch("novel_forge.modules.review.cross_model_binding.generator_identity", return_value={**contract(),"purpose":"AUTHOR_ADVISORY"}):
        result = freeze_review_requirement(Cursor(), project_id="project", book_id="book", operation_id="operation",
            task_type="narrative_semantic_evaluation", request_input={"evaluation_target":{"candidate_asset_version_id":"exact-draft"},
                "evaluation_purpose":"AUTHOR_ADVISORY"})
    assert result["purpose"] == (frozen or "STRICT_QUALIFICATION")


def test_mixed_design_reuses_exact_existing_qualification_without_relabeling():
    from novel_forge.modules.story_design_authority.author_supervision import reusable_qualified_design_receipt
    from novel_forge.modules.story_design_authority.qualification import required_qualification_profiles
    class Cursor:
        rows = [(p.layer.value,p.profile_id,p.profile_version,p.profile_hash,"q-hash","e-hash","evaluation","target-hash")
                for p in required_qualification_profiles("book_plan.generate")]
        def execute(self, sql, args):
            assert "evaluator_execution_class='MODEL_PROVIDER'" in sql
        def fetchall(self): return self.rows
    cursor=Cursor()
    args=dict(project_id="project",book_id="book",asset_version_id="qualified-plan",generator="book_plan.generate")
    receipt=reusable_qualified_design_receipt(cursor,**args)
    assert receipt["mode"] == "STRICT_QUALIFIED"
    assert receipt["asset_version_id"] == "qualified-plan"
    cursor.rows=cursor.rows[:-1]
    with pytest.raises(KernelError,match="QUALIFICATION_INCOMPLETE"):
        reusable_qualified_design_receipt(cursor,**args)
