from __future__ import annotations

from copy import deepcopy

import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.editorial_domain import (
    editorial_readiness,
    require_editorial_principal,
    validate_editorial_policy,
)
from novel_forge.modules.book_followup_authority.prose_review import (
    PROSE_DIMENSIONS,
    aggregate_reports,
    freeze_manifest,
    validate_window_report,
)
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.mark.parametrize("native_recovery", [False, True])
def test_review_without_external_recovery_does_not_require_resolution_authority(native_recovery):
    from types import SimpleNamespace
    from novel_forge.modules.book_followup_authority.prose_recovery import recover_prose_review
    principal = Principal(principal_id="reviewer", principal_type=PrincipalType.SERVICE,
        authentication_source="server_configuration", project_scope=frozenset({"p"}), permissions=frozenset({"book.authority.execute", "book.followup:longform.prose_review"}))
    coordinator = SimpleNamespace(followup=SimpleNamespace(prose_model_port=SimpleNamespace(
        capability_binder=object() if native_recovery else None)))
    scope = dict(run_id="review", project_id="p", workspace_id="w", book_run_id="book", principal=principal)
    if native_recovery:
        with pytest.raises(PermissionError, match="external_effect.resolve"):
            recover_prose_review(coordinator, **scope)
    else:
        assert recover_prose_review(coordinator, **scope) == []


def manifest():
    return freeze_manifest(
        project_id="p",
        workspace_id="w",
        book_run_id="b",
        sources=[
            {
                "acceptance_id": "a",
                "chapter_number": 1,
                "asset_version_id": "draft",
                "asset_hash": "hash",
                "text": "剑锋停在门外。她没有追击，因为桥下还有孩子。",
            }
        ],
        policy={
            "policy_version": "v1",
            "window_codepoints": 16,
            "overlap_codepoints": 4,
            "context_token_budget": 2048,
            "maximum_windows": 3,
        },
    )


def report(frozen, window, judgment="ISSUE", lineage="goal"):
    span = window["spans"][0]
    return {
        "schema_version": "longform-prose-review.v1",
        "manifest_digest": frozen["manifest_digest"],
        "window_id": window["window_id"],
        "reviewed_dimensions": list(PROSE_DIMENSIONS),
        "findings": [
            {
                "lineage_id": lineage,
                "dimension": "motivation_cost",
                "judgment": judgment,
                "severity": "MAJOR" if judgment == "ISSUE" else "NONE",
                "confidence": 0.6,
                "claim": "动机需要相邻证据",
                "rationale": "局部窗口不能推断全部动机",
                "evidence": [
                    {
                        "asset_version_id": "draft",
                        "text_hash": span["text_hash"],
                        "start": span["start"],
                        "end": span["start"] + 2,
                        "quote": span["text"][:2],
                    }
                ],
            }
        ],
    }


def literal_report_case():
    frozen = manifest()
    frozen["policy"].update(diagnosis_contract="prose-root-cause.v1", citation_locator_contract="literal-prose-citation.v1")
    window = frozen["windows"][0]
    raw = report(frozen, window)
    raw["schema_version"] = "longform-prose-review.v3"
    raw["findings"][0]["repair"] = {"root_cause": "SCENE_ORGANIZATION", "problem_owner": "PLAN", "repair_scope": "FUTURE_REPLAN",
        "revision_goal": "Clarify the future scene's purpose", "preserve": ["The existing reason for stopping"], "resolution_criteria": ["The next event follows that decision"]}
    citation = raw["findings"][0]["evidence"][0]
    citation.pop("start")
    citation.pop("end")
    return frozen, window, raw


def test_literal_review_locates_unicode_quote_without_model_arithmetic_and_preserves_judgment():
    frozen, window, raw = literal_report_case()
    original = deepcopy(raw)
    result = validate_window_report(raw, manifest=frozen, window=window)
    assert raw == original
    assert result["findings"][0]["evidence"][0]["start"] == 0
    assert result["findings"][0]["evidence"][0]["end"] == 2
    assert result["findings"][0]["repair"] == original["findings"][0]["repair"]
    assert result["findings"][0]["severity"] == original["findings"][0]["severity"]
    assert validate_window_report(result, manifest=frozen, window=window) == result


@pytest.mark.parametrize("drift", ["quote", "source", "hash", "ambiguous", "stored_location"])
def test_literal_review_rejects_unbound_or_nonunique_quote_without_fuzzy_repair(drift):
    frozen, window, raw = literal_report_case()
    citation = raw["findings"][0]["evidence"][0]
    if drift == "quote":
        citation["quote"] = "An unprovided action"
    elif drift == "source":
        citation["asset_version_id"] = "foreign"
    elif drift == "hash":
        citation["text_hash"] = "changed"
    elif drift == "ambiguous":
        window["spans"][0]["text"] = citation["quote"] * 2
    else:
        citation.update(start=1,end=3)
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION"):
        validate_window_report(raw, manifest=frozen, window=window)


def test_frozen_numeric_review_still_rejects_wrong_offsets_even_when_quote_is_unique():
    frozen = manifest()
    window = frozen["windows"][0]
    raw = report(frozen, window)
    raw["findings"][0]["evidence"][0].update(start=1,end=3)
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION_INVALID"):
        validate_window_report(raw,manifest=frozen,window=window)


def test_literal_flags_bind_formal_and_sample_output_to_quote_only_provider_schema():
    from novel_forge.modules.book_followup_authority.prose_review import prose_review_invoke_payload
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder

    frozen, window, raw = literal_report_case()
    content = {**frozen, "window": window}
    invocation = prose_review_invoke_payload(content)
    from novel_forge.modules.book_followup_authority.prose_sampling import prose_sample_invoke_payload
    assert prose_sample_invoke_payload(content) == invocation
    schema, identity = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="longform_prose_review", request_payload={"input": invocation})
    assert identity == "schema:chapter-provider-output:longform_prose_review:v3"
    citation = schema["properties"]["findings"]["items"]["anyOf"][0]["properties"]["evidence"]["items"]
    assert set(citation["properties"]) == {"asset_version_id", "text_hash", "quote"}
    assert schema["properties"]["schema_version"]["enum"] == [raw["schema_version"]]
    legacy = {**content, "policy": {"diagnosis_contract": "prose-root-cause.v1"}}
    assert prose_sample_invoke_payload(legacy) == {"manifest_digest": frozen["manifest_digest"], "window_id": window["window_id"]}
    old_schema, old_identity = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="longform_prose_review", request_payload={"input": prose_review_invoke_payload(legacy)})
    assert old_identity == "schema:chapter-provider-output:longform_prose_review:v2"
    assert "start" in old_schema["properties"]["findings"]["items"]["anyOf"][0]["properties"]["evidence"]["items"]["properties"]


@pytest.mark.parametrize("version", ["v2", "v3", "unsupported"])
def test_prose_template_adapter_admission_accepts_current_and_frozen_legacy_versions(version):
    from types import SimpleNamespace
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder

    class ReachedArtifactBinding(Exception):
        pass

    def artifacts(_metadata):
        raise ReachedArtifactBinding()

    binder = SimpleNamespace(routes={"longform_prose_review": None}, capability_pack_id="pack", provider_router=None,
        _operation_graph=lambda *args: {"definition_name": "longform.prose_review"},
        _resolve_pack_snapshot=lambda **kwargs: object(),
        pack_resolver=SimpleNamespace(materialize_attempt_artifacts=lambda _snapshot: SimpleNamespace(
            prompt_template=SimpleNamespace(ref="prompt-template:longform-prose-review-pack", version=version))),
        _artifacts=artifacts)
    metadata = {key: key for key in ("operation_id", "attempt_id", "project_id", "workspace_id", "book_id", "worker_id")}
    metadata["fencing_token"] = 1
    expected = KernelError if version == "unsupported" else ReachedArtifactBinding
    with pytest.raises(expected):
        PostgresChapterExecutionContractBinder.freeze_before_external_effect(binder,
            capability="model.longform_prose_review", request_payload={"stage": "longform_prose_review", "_production_execution": metadata},
            snapshot_fencing_token=1, snapshot_worker_id="worker")


def test_literal_review_same_quote_in_overlapping_spans_has_one_absolute_location():
    frozen, window, raw = literal_report_case()
    window["spans"].append(deepcopy(window["spans"][0]))
    resolved = validate_window_report(raw, manifest=frozen, window=window)
    assert resolved["findings"][0]["evidence"][0]["start"] == 0


@pytest.mark.parametrize("fault", [None, "already_valid", "missing_quote", "changed_prose"])
def test_legacy_citation_revalidation_preserves_judgments_and_requires_only_numeric_failure(fault):
    from novel_forge.modules.book_followup_authority.prose_review import revalidate_legacy_citation_report

    target, window, raw = literal_report_case()
    source = deepcopy(target)
    source["policy"].pop("citation_locator_contract")
    old = deepcopy(raw)
    old["schema_version"] = "longform-prose-review.v2"
    old["findings"][0]["evidence"][0].update(start=1, end=3)
    source_window = deepcopy(window)
    if fault == "already_valid":
        old["findings"][0]["evidence"][0].update(start=0, end=2)
    elif fault == "missing_quote":
        old["findings"][0]["evidence"][0]["quote"] = "未提供的句子"
    elif fault == "changed_prose":
        source_window["spans"][0]["text"] += "changed"
    before = deepcopy(old)
    if fault:
        with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION"):
            revalidate_legacy_citation_report(old, source_manifest=source, source_window=source_window,
                target_manifest=target, target_window=window)
    else:
        resolved, proof = revalidate_legacy_citation_report(old, source_manifest=source, source_window=source_window,
            target_manifest=target, target_window=window)
        assert resolved["findings"][0]["repair"] == old["findings"][0]["repair"]
        assert resolved["findings"][0]["rationale"] == old["findings"][0]["rationale"]
        assert proof["locations"][0]["original_location"] == {"start": 1, "end": 3}
        assert proof["locations"][0]["start"] == 0
        assert proof["manuscript_mutation_allowed"] is False
    assert old == before


def test_exact_chinese_coverage_and_exclusions():
    frozen = manifest()
    first = report(frozen, frozen["windows"][0], "INSUFFICIENT_EVIDENCE")
    partial = aggregate_reports(frozen, [first])
    assert not partial["coverage_complete"] and partial["uncovered_ranges"]
    reports = [
        report(frozen, window, "INTENTIONAL", str(index))
        for index, window in enumerate(frozen["windows"])
    ]
    whole = aggregate_reports(frozen, reports + reports)
    assert whole["coverage_complete"]
    assert len(whole["completed_window_ids"]) == len(reports)
    assert whole["quality_absence_proven"] is False


@pytest.mark.parametrize("operation", [
    {"operation_id": "pending", "status": "RECONCILIATION_REQUIRED"},
    {"operation_id": "pending", "status": "SUCCEEDED", "external_effects": [{"status": "UNKNOWN"}]},
    {"operation_id": "pending", "status": "SUCCEEDED", "budget_receipts": [{"status": "HELD_UNKNOWN"}]},
])
def test_automatic_review_reconciles_old_work_before_following_acceptance(operation):
    from types import SimpleNamespace
    from novel_forge.modules.book_followup_authority.prose_coordinator import (
        BookProseReviewCoordinator,
    )

    coordinator = BookProseReviewCoordinator(
        SimpleNamespace(
            database_url="unused", application_build_id="test", commit_sha="e" * 40
        )
    )
    coordinator.report = lambda **_: {
        "manifest": {
            "policy": {"execution_mode": "AUTOMATIC", "follow_acceptance": True}
        },
        "paused": False,
        "implementation_current": True,
        "source_current": False,
        "operations": [operation],
    }
    principal = Principal(
        "worker",
        PrincipalType.WORKER,
        frozenset({"*"}),
        frozenset({"*"}),
        "server_configuration",
    )
    assert coordinator.automatic_tick(
        principal=principal,
        run_id="run",
        project_id="project",
        workspace_id="workspace",
        book_run_id="book",
    ) == {"status": "BLOCKED", "operation_id": "pending"}


def test_automatic_relation_retrieval_requires_paired_evidence_and_reports_exclusions():
    frozen = freeze_manifest(
        project_id="p",
        workspace_id="w",
        book_run_id="b",
        sources=[
            {
                "acceptance_id": str(number),
                "chapter_number": number,
                "asset_version_id": str(number),
                "asset_hash": str(number),
                "text": text,
            }
            for number, text in (
                (1, "青铜旧印留在桥下。她答应回来救人。"),
                (2, "城门的守军已经撤离。"),
                (8, "青铜旧印仍在桥下。孩子还记得那个承诺。"),
            )
        ],
        policy={
            **manifest()["policy"],
            "window_codepoints": 64,
            "maximum_windows": 10,
            "relation_window_limit": 1,
            "execution_mode": "AUTOMATIC",
            "follow_acceptance": True,
        },
    )
    window = frozen["windows"][-1]
    assert window["relation_hypothesis"]["status"] == "UNVERIFIED"
    assert [span["chapter_number"] for span in window["spans"]] == [1, 8]
    assert sum(len(span["text"]) for span in window["spans"]) <= 64
    evidence = []
    for span in window["spans"]:
        evidence.append(
            {
                "asset_version_id": span["asset_version_id"],
                "text_hash": span["text_hash"],
                "start": span["start"],
                "end": span["start"] + 4,
                "quote": span["text"][:4],
            }
        )
    reviewed = report(frozen, window)
    reviewed["findings"][0]["evidence"] = evidence[:1]
    with pytest.raises(KernelError, match="both retrieved passages"):
        validate_window_report(reviewed, manifest=frozen, window=window)
    reviewed["findings"][0]["evidence"] = evidence
    result = aggregate_reports(frozen, [reviewed])
    assert result["relation_verification"]["paired_evidence_hypothesis_ids"] == [
        window["relation_hypothesis"]["hypothesis_id"]
    ]
    assert result["relation_verification"]["global_relationships_verified"] is False
    assert result["relation_verification"]["retrieval"]["uncovered_relation_classes"]
    assert not result["coverage_complete"]


def test_citations_do_not_accept_bytes_or_changed_text():
    frozen = manifest()
    window = frozen["windows"][0]
    valid = report(frozen, window)
    validate_window_report(valid, manifest=frozen, window=window)
    invalid = deepcopy(valid)
    invalid["findings"][0]["evidence"][0]["quote"] = "伪造"
    with pytest.raises(KernelError, match="exact provided"):
        validate_window_report(invalid, manifest=frozen, window=window)
    invalid = deepcopy(valid)
    invalid["findings"][0]["evidence"][0]["end"] = 99
    with pytest.raises(KernelError):
        validate_window_report(invalid, manifest=frozen, window=window)


def test_same_lineage_disjoint_evidence_is_conflict_not_category_merge():
    frozen = manifest()
    reports = [report(frozen, window) for window in frozen["windows"]]
    assert (
        aggregate_reports(frozen, reports)["findings"][0]["status"]
        == "CONFLICT_REQUIRES_REVIEW"
    )


def test_policy_named_humans_and_exact_signature_drift_revocation():
    policy = {
        "policy_version": "v1",
        "enabled": True,
        "authorized_reviewers": ["human"],
        "minimum_signatures": 1,
        "allow_minor_exceptions": False,
    }
    validate_editorial_policy(policy)
    events = [
        {
            "event_id": "policy",
            "kind": "POLICY",
            "actor_id": "human",
            "content": {"policy": policy},
        },
        {
            "event_id": "signature",
            "kind": "SIGNATURE",
            "actor_id": "human",
            "content": {
                "policy_event_id": "policy",
                "source_digest": "s",
                "manifest_digest": "m",
                "review_digest": "r",
                "release_sha": "a",
            },
        },
    ]
    scope = dict(
        source_digest="s", manifest_digest="m", review_digest="r", release_sha="a"
    )
    assert editorial_readiness(events=events, **scope)["status"] == "SIGNED"
    assert (
        editorial_readiness(events=events, **{**scope, "review_digest": "changed"})[
            "status"
        ]
        == "WAITING_EVIDENCE"
    )
    events.append(
        {
            "event_id": "revoked",
            "kind": "REVOCATION",
            "content": {"signature_id": "signature"},
        }
    )
    assert editorial_readiness(events=events, **scope)["status"] == "WAITING_EVIDENCE"
    with pytest.raises(PermissionError):
        require_editorial_principal(
            Principal(
                "worker",
                PrincipalType.WORKER,
                frozenset({"*"}),
                frozenset({"*"}),
                "server_configuration",
            ),
            "p",
        )


def test_cross_chapter_window_preserves_boundary_text_and_budget():
    frozen = freeze_manifest(
        project_id="p",
        workspace_id="w",
        book_run_id="b",
        sources=[
            {
                "acceptance_id": str(i),
                "chapter_number": i,
                "asset_version_id": str(i),
                "asset_hash": "hash",
                "text": "门外剑声停了。孩子仍在桥下。",
            }
            for i in (1, 2)
        ],
        policy={
            "policy_version": "v1",
            "window_codepoints": 16,
            "overlap_codepoints": 4,
            "context_token_budget": 2048,
            "maximum_windows": 3,
        },
    )
    crossing = [window for window in frozen["windows"] if len(window["spans"]) == 2]
    assert (
        crossing
        and crossing[0]["spans"][0]["chapter_number"] == 1
        and crossing[0]["spans"][1]["chapter_number"] == 2
    )
    assert all(
        sum(len(span["text"]) for span in window["spans"]) <= 16
        for window in frozen["windows"]
    )


def test_retrieved_cross_window_evidence_is_bounded_and_exact():
    from novel_forge.modules.book_followup_authority.prose_coordinator import (
        BookProseReviewCoordinator,
    )

    frozen = manifest()
    sources = [
        {
            "asset_version_id": "draft",
            "text": "剑锋停在门外。她没有追击，因为桥下还有孩子。",
        }
    ]
    previous = frozen["manifest_digest"]
    BookProseReviewCoordinator._append_evidence_window(
        frozen,
        sources,
        [
            {"asset_version_id": "draft", "start": 0, "end": 5},
            {"asset_version_id": "draft", "start": 14, "end": 20},
        ],
    )
    assert frozen["manifest_digest"] != previous
    assert frozen["windows"][-1]["spans"][1]["text"] == sources[0]["text"][14:20]
    with pytest.raises(KernelError):
        BookProseReviewCoordinator._append_evidence_window(
            frozen,
            sources,
            [
                {"asset_version_id": "draft", "start": 0, "end": 17},
                {"asset_version_id": "draft", "start": 18, "end": 20},
            ],
        )


def test_exact_frozen_prose_survives_final_pack_prompt_materialization():
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from novel_forge.modules.chapter_authority.execution_gateway import (
        _materialize_production_codex_prompt,
    )
    from novel_forge.modules.book_followup_authority.prose_review import (
        prose_review_output_schema,
    )

    frozen = manifest()
    projection = {
        "schema_version": "longform-prose-window.v1",
        "manifest_digest": frozen["manifest_digest"],
        "window": frozen["windows"][0],
        "policy": frozen["policy"],
        "source_isolation": "ACCEPTED_PROSE_ONLY",
    }
    artifacts_root = (
        Path(__file__).resolve().parents[2] / "config/capability_packs/artifacts"
    )
    artifacts = {
        key: {
            "ref": key,
            "version": "v1",
            "content_hash": "sha256:" + "b" * 64,
            "content": {"text": value},
        }
        for key, value in {
            "system_instruction": (
                artifacts_root / "longform_prose_review_system_instruction.md"
            ).read_text(),
            "prompt_template": (
                artifacts_root / "longform_prose_review_template.md"
            ).read_text(),
            "skill": "审读证据仅限实际提供的正文。",
        }.items()
    }
    prompt, evidence = _materialize_production_codex_prompt(
        request=SimpleNamespace(
            target_scope=SimpleNamespace(
                to_dict=lambda: {"asset_version_id": "window:1"}
            )
        ),
        stage="longform_prose_review",
        inputs={
            "manifest_digest": frozen["manifest_digest"],
            "window_id": frozen["windows"][0]["window_id"],
        },
        materialization={
            "pack_artifacts": artifacts,
            "context_selection": [
                {
                    "asset_version_id": "context:1",
                    "content": {
                        "schema_version": "novelos.longform_prose_review_context_bundle.v2",
                        "selected_inputs": [
                            {
                                "asset_type": "longform_prose_review_window",
                                "projection": projection,
                            }
                        ],
                    },
                }
            ],
            "knowledge_selection": [
                {
                    "ref": "quality-review:v1",
                    "version": "v1",
                    "content": {"principles": ["不能把有意重复判为事实错误"]},
                }
            ],
            "tool_permissions": {"allowed": ["model.provider.invoke"]},
            "output_schema": {
                "ref": "schema:longform-prose-review",
                "content": prose_review_output_schema(),
            },
        },
    )
    assert (
        json.dumps(
            projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        in prompt
    )
    assert "关系停滞" in prompt and "INSUFFICIENT_EVIDENCE" in prompt
    assert (
        evidence["provider_view"]["context_contract_version"]
        == "provider-context-view-v2"
    )


def test_completion_checks_each_exact_signature_group(monkeypatch):
    from novel_forge.modules.book_authority import editorial
    from novel_forge.modules.book_followup_authority import prose_coordinator
    policy = {"policy_version": "v1", "enabled": True, "authorized_reviewers": ["one", "two"],
              "minimum_signatures": 2, "allow_minor_exceptions": False}
    events = [{"event_id": "policy", "kind": "POLICY", "content": {"policy": policy}}]
    def sign(identity, actor, run, digest):
        return {"event_id": identity, "kind": "SIGNATURE", "actor_id": actor, "content": {
            "case_id": "case", "policy_event_id": "policy", "source_digest": "source",
            "review_run_id": run, "manifest_digest": "manifest", "review_digest": digest, "release_sha": "release"}}
    events.extend([sign("a", "one", "valid", "review"), sign("b", "two", "valid", "review"),
                   sign("c", "one", "stale", "old")])
    monkeypatch.setattr(editorial, "load_editorial_events", lambda *args: events)
    monkeypatch.setattr(prose_coordinator, "load_review_run", lambda uow, **scope: {
        **scope, "exact_release_sha": "release"})
    monkeypatch.setattr(prose_coordinator, "review_progress", lambda uow, run: {
        "manifest_digest": "manifest", "review_digest": "review" if run["run_id"] == "valid" else "changed",
        "source_current": True, "coverage_complete": True, "review_complete": True, "paused": False, "findings": []})
    case = {"case_id": "case", "source_digest": "source", "project_id": "p", "workspace_id": "w", "book_run_id": "book"}
    blockers, status = editorial.completion_editorial_evidence(None, case=case, payload=case, release_sha="release")
    assert blockers == []
    assert status["signature_ids"] == ["a", "b"]
    events.append({"event_id": "revoke-c", "kind": "REVOCATION", "content": {"signature_id": "c"}})
    assert editorial.completion_editorial_evidence(None, case=case, payload=case, release_sha="release")[0] == []
    events[2]["content"]["review_run_id"] = "other"
    assert editorial.completion_editorial_evidence(None, case=case, payload=case, release_sha="release")[0]


def test_expired_signature_cannot_supply_quorum():
    from datetime import datetime, timezone
    policy = {"policy_version": "v1", "enabled": True, "authorized_reviewers": ["one"],
              "minimum_signatures": 1, "allow_minor_exceptions": False}
    events = [{"event_id": "policy", "kind": "POLICY", "content": {"policy": policy}},
              {"event_id": "expired", "kind": "SIGNATURE", "actor_id": "one", "content": {
                  "policy_event_id": "policy", "source_digest": "s", "manifest_digest": "m", "review_digest": "r",
                  "release_sha": "a", "expires_at": "2026-09-20T00:00:00+00:00"}}]
    result = editorial_readiness(events=events, source_digest="s", manifest_digest="m", review_digest="r",
                                 release_sha="a", now=datetime(2026, 9, 21, tzinfo=timezone.utc))
    assert result["status"] == "WAITING_EVIDENCE"


@pytest.mark.parametrize("decision,severity,conflict,allowed", [
    ("MINOR_EXCEPTION", "MINOR", False, True), ("MINOR_EXCEPTION", "MAJOR", False, False),
    ("MINOR_EXCEPTION", "BLOCKING", False, False), ("MINOR_EXCEPTION", "MINOR", True, False),
    ("KEEP_HISTORY", "BLOCKING", False, True), ("CURRENT_CANDIDATE_REVISION", "BLOCKING", False, True),
    ("FUTURE_PLAN_PROPOSAL", "BLOCKING", False, True)])
def test_disposition_does_not_convert_proposals_or_major_issues_to_resolution(decision, severity, conflict, allowed):
    from novel_forge.modules.book_authority.editorial_domain import validate_finding_disposition
    policy = {"event_id": "policy", "content": {"policy": {"policy_version": "v1", "enabled": True,
        "authorized_reviewers": ["reviewer"], "minimum_signatures": 1, "allow_minor_exceptions": True}}}
    finding = {"status": "CONFLICT_REQUIRES_REVIEW" if conflict else "OPEN",
               "members": [{"judgment": "ISSUE", "severity": severity}]}
    command = dict(finding=finding, decision=decision, policy_event=policy, actor_id="reviewer")
    if not allowed:
        with pytest.raises(KernelError):
            validate_finding_disposition(**command)
    else:
        result = validate_finding_disposition(**command)
        assert result["resolution"] == ("PERMITTED_EXCEPTION" if decision == "MINOR_EXCEPTION" else "UNRESOLVED")


def test_dismissal_needs_named_reviewer_and_complete_located_counterevidence():
    from novel_forge.modules.book_authority.editorial_domain import validate_finding_disposition
    frozen = manifest()
    issue = report(frozen, frozen["windows"][0])["findings"][0]
    policy = {"event_id": "policy", "content": {"policy": {"policy_version": "v1", "enabled": True,
        "authorized_reviewers": ["reviewer"], "minimum_signatures": 1, "allow_minor_exceptions": False}}}
    command = dict(finding={"status": "OPEN", "members": [issue]}, decision="DISMISSED_WITH_EVIDENCE",
                   policy_event=policy, actor_id="reviewer")
    with pytest.raises(KernelError, match="recheck"):
        validate_finding_disposition(**command)
    counter = report(frozen, frozen["windows"][0], "INTENTIONAL")
    assert validate_finding_disposition(**command, counter_reports=[counter])["resolution"] == "DISMISSED_BY_AUTHORIZED_REVIEWER"
    with pytest.raises(PermissionError):
        validate_finding_disposition(**{**command, "actor_id": "other"}, counter_reports=[counter])
    counter["findings"][0]["evidence"][0]["text_hash"] = "stale"
    with pytest.raises(KernelError):
        validate_finding_disposition(**command, counter_reports=[counter])
    counter["findings"][0]["judgment"] = "INSUFFICIENT_EVIDENCE"
    with pytest.raises(KernelError):
        validate_finding_disposition(**command, counter_reports=[counter])


def test_manual_range_selection_reviews_only_requested_spans_without_hiding_source_manifest():
    from novel_forge.modules.book_followup_authority.prose_coordinator import BookProseReviewCoordinator

    frozen = manifest()
    original_sources = deepcopy(frozen['sources'])
    frozen['policy']['window_selection'] = 'EXPLICIT_RANGES_ONLY'
    text = '剑锋停在门外。她没有追击，因为桥下还有孩子。'
    ranges = [{'asset_version_id': 'draft', 'start': 0, 'end': 5},
              {'asset_version_id': 'draft', 'start': 14, 'end': 20}]
    BookProseReviewCoordinator._append_evidence_window(frozen, [{'asset_version_id': 'draft', 'text': text}], ranges)
    assert len(frozen['windows']) == 1
    assert frozen['sources'] == original_sources
    assert [(span['start'], span['end'], span['text']) for span in frozen['windows'][0]['spans']] == [(0, 5, text[:5]), (14, 20, text[14:20])]
    assert aggregate_reports(frozen, [])['coverage_complete'] is False


def test_automatic_review_cannot_use_manual_selected_range_policy():
    frozen = manifest()
    with pytest.raises(KernelError, match='LONGFORM_PROSE_POLICY_INVALID'):
        freeze_manifest(project_id='p', workspace_id='w', book_run_id='run',
            sources=[{'chapter_number': 1, 'acceptance_id': '', 'asset_version_id': 'draft', 'asset_hash': 'hash', 'text': '正文'}],
            policy={**frozen['policy'], 'execution_mode': 'AUTOMATIC', 'window_selection': 'EXPLICIT_RANGES_ONLY'})


def test_explicit_working_review_output_allocation_is_frozen_and_historical_policy_is_unchanged():
    frozen = manifest()
    source = dict(chapter_number=1, acceptance_id='', asset_version_id='working:1', asset_hash='hash',
                  text='他停下凿子，先把落石移开。', source_isolation='AUTHOR_SELECTED_UNREVIEWED_PROSE')
    policy = {**frozen['policy'], 'provider_output_tokens': 384000}
    current = freeze_manifest(project_id='p', workspace_id='w', book_run_id='b', sources=[source], policy=policy, work_intent=False)
    assert current['schema_version'] == 'longform-prose-manifest.v3'
    assert current['policy']['provider_output_tokens'] == 384000
    policy['provider_output_tokens'] = 8192
    assert current['policy']['provider_output_tokens'] == 384000
    assert 'provider_output_tokens' not in frozen['policy']
    for invalid in (0, -1, True, '384000', None):
        with pytest.raises(KernelError, match='LONGFORM_PROSE_POLICY_INVALID'):
            freeze_manifest(project_id='p', workspace_id='w', book_run_id='b', sources=[source],
                            policy={**policy, 'provider_output_tokens': invalid}, work_intent=False)
    with pytest.raises(KernelError, match='LONGFORM_PROSE_POLICY_INVALID'):
        freeze_manifest(project_id='p', workspace_id='w', book_run_id='b', sources=[{**source, 'source_isolation': 'ACCEPTED_PROSE_ONLY'}],
                        policy=policy, work_intent=False)
