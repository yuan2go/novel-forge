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
