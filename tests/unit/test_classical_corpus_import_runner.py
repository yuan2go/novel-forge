import json

import pytest

from novel_forge.modules.project_authority.domain import build_project_snapshot
from scripts.run_classical_corpus_import import (
    ANALYSIS_OVERRIDE_POLICY_VERSION,
    ANALYSIS_OVERRIDE_REVIEW_CLASS,
    ANALYSIS_OVERRIDE_SCHEMA_VERSION,
    _load_analysis_overrides,
    _project_payload,
)


def test_classical_corpus_runner_uses_an_authoritative_project_stage() -> None:
    snapshot = build_project_snapshot(
        project_id="project:classical-corpus",
        workspace_id="workspace:classical-corpus",
        payload=_project_payload(),
    )

    assert snapshot["stage"] == "DESIGN"
    assert snapshot["config"] == {
        "validation_scope": "CLASSICAL_CORPUS_SOURCE_ONLY",
        "publication_policy": "FORBIDDEN",
    }


def _override_manifest(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": ANALYSIS_OVERRIDE_SCHEMA_VERSION,
        "policy_version": ANALYSIS_OVERRIDE_POLICY_VERSION,
        "review_class": ANALYSIS_OVERRIDE_REVIEW_CLASS,
        "project_id": "project:corpus",
        "workspace_id": "workspace:corpus",
        "overrides": [
            {
                "work_key": "chinese-novel.yushimingyan",
                "logical_document_scope_hash": "sha256:" + "a" * 64,
                "content_type": "CLASSIC_LITERATURE",
                "reason": "The frozen repository work identity is a classical story collection.",
                "decision_ref": "experimental-policy:content-type:yushimingyan:v1",
                "boundary_resolution": "CONFIRM_SOURCE_WORK_AGGREGATE",
                "expected_document_count": 40,
            }
        ],
    }
    value.update(updates)
    return value


def test_analysis_override_manifest_is_exactly_scoped_and_auditable(tmp_path) -> None:
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(_override_manifest()), encoding="utf-8")

    overrides, evidence = _load_analysis_overrides(
        path,
        project_id="project:corpus",
        workspace_id="workspace:corpus",
        selected_work_keys=("chinese-novel.yushimingyan",),
        known_work_keys=frozenset({"chinese-novel.yushimingyan"}),
    )

    assert overrides["chinese-novel.yushimingyan"].content_type.value == (
        "CLASSIC_LITERATURE"
    )
    assert evidence["review_class"] == ANALYSIS_OVERRIDE_REVIEW_CLASS
    assert evidence["override_count"] == 1
    assert evidence["overrides"][0]["contract_hash"].startswith("sha256:")
    assert evidence["overrides"][0]["expected_document_count"] == 40


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"project_id": "project:other"}, "identity mismatch"),
        (
            {
                "overrides": [
                    {
                        "work_key": "chinese-novel.other",
                        "logical_document_scope_hash": "sha256:" + "a" * 64,
                        "content_type": "CLASSIC_LITERATURE",
                        "reason": "This override must not escape the frozen work set.",
                        "decision_ref": "experimental-policy:content-type:other:v1",
                        "boundary_resolution": "CONFIRM_SOURCE_WORK_AGGREGATE",
                        "expected_document_count": 40,
                    }
                ]
            },
            "unknown work key",
        ),
    ],
)
def test_analysis_override_manifest_rejects_scope_drift(
    tmp_path, updates: dict[str, object], error: str
) -> None:
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(_override_manifest(**updates)), encoding="utf-8")

    with pytest.raises(RuntimeError, match=error):
        _load_analysis_overrides(
            path,
            project_id="project:corpus",
            workspace_id="workspace:corpus",
            selected_work_keys=("chinese-novel.yushimingyan",),
            known_work_keys=frozenset({"chinese-novel.yushimingyan"}),
        )
