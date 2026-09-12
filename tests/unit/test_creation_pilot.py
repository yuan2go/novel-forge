from __future__ import annotations

from decimal import Decimal

import pytest

from scripts.creation_pilot import authorize_execution, authorize_total
from novel_forge.modules.chapter_quality_authority.domain import (
    build_quality_group_evidence,
)


@pytest.mark.parametrize(
    "amount,reference", [("", ""), ("10", ""), ("NaN", "approval"), ("-1", "approval")]
)
def test_credentials_and_daily_caps_do_not_authorize_a_paid_experiment(
    amount, reference
):
    with pytest.raises(ValueError):
        authorize_total(
            {"NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP": "10"}, amount, reference
        )


def test_total_authorization_never_raises_an_existing_project_cap():
    values = {"NOVEL_FORGE_PROJECT_TOTAL_PROVIDER_CAP": "3"}
    assert Decimal(authorize_total(values, "10", "operator-explicit-budget")) == 3
    assert values["NOVEL_FORGE_PROJECT_TOTAL_PROVIDER_CAP"] == "3"


def test_account_entitlement_uses_exact_reference_and_no_fake_usd_budget():
    values = {
        "NOVEL_FORGE_CODEX_ACCOUNTING_MODE": "ACCOUNT_ENTITLEMENT",
        "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF": "approval:classical-corpus",
    }
    assert authorize_execution(values, "", "approval:classical-corpus") == {
        "accounting_basis": "ACCOUNT_ENTITLEMENT",
        "authorization_ref": "approval:classical-corpus",
        "authorized_total_usd": None,
        "monetary_cost_status": "UNKNOWN",
    }
    assert "NOVEL_FORGE_PROJECT_TOTAL_PROVIDER_CAP" not in values


@pytest.mark.parametrize(
    "amount,reference",
    [("1", "approval:classical-corpus"), ("", ""), ("", "another-approval")],
)
def test_account_entitlement_rejects_usd_or_wrong_authorization(amount, reference):
    with pytest.raises(ValueError):
        authorize_execution(
            {
                "NOVEL_FORGE_CODEX_ACCOUNTING_MODE": "ACCOUNT_ENTITLEMENT",
                "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF": "approval:classical-corpus",
            },
            amount,
            reference,
        )


def test_six_chapter_inputs_freeze_sources_and_do_not_invent_card_approval(tmp_path):
    import hashlib
    import json
    from scripts.prepare_knowledge_closure import prepare
    report = prepare(tmp_path / "unbound")
    assert report["real_provider_execution"] == "NOT_RUN"
    assert report["arm_a_binding"] == "KNOWLEDGE_APPROVAL_AND_EXACT_VERSION_BINDING_REQUIRED"
    assert not (tmp_path / "unbound/allow-only.json").exists()
    for name, digest in report["files"].items():
        assert digest == "sha256:" + hashlib.sha256((tmp_path / "unbound" / name).read_bytes()).hexdigest()
    prepare(tmp_path / "bound", ["exact-approved-version"])
    policy = json.loads((tmp_path / "bound/allow-only.json").read_text())
    assert policy["allowed_knowledge_card_asset_version_ids"] == ["exact-approved-version"]
    creation = json.loads((tmp_path / "bound/creation.json").read_text())
    assert creation["profiles"]["production_profile"]["content"]["target_chapter_count"] == 6
    assert creation["chapter_group_execution"]["maximum_chapters"] == 3
    assert creation["future_plan_change"]["after_chapter"] == 3
    from novel_forge.modules.command_kernel.errors import KernelError
    with pytest.raises(KernelError):
        prepare(tmp_path / "empty", [])


def test_blind_export_does_not_turn_missing_prose_into_review_material(tmp_path):
    from scripts.prepare_knowledge_closure import blind_export
    with pytest.raises(ValueError, match="six exact accepted chapters"):
        blind_export(tmp_path / "a", tmp_path / "b", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "text,status,count",
    [
        ("甲乙𠀀，！？123abc", "PASSED", 3),
        ("甲abc。", "FAILED", 1),
        ("甲乙丙丁戊", "FAILED", 5),
    ],
)
def test_han_length_policy_counts_unicode_and_cannot_be_overridden_by_model_pass(
    text, status, count
):
    context = {
        "platform_profile_version": "platform",
        "context_segments": [
            {
                "asset_version_id": "platform",
                "structured_facts": [
                    {
                        "key": "platform_rules",
                        "value": {
                            "chapter_length": {
                                "unit": "HAN_CHARACTERS_V1",
                                "minimum": 2,
                                "maximum": 4,
                            }
                        },
                    }
                ],
            },
            {
                "asset_version_id": "judge",
                "structured_facts": [
                    {"key": key, "value": value}
                    for key, value in {
                        "dimension": "chapter_length",
                        "target_asset_version_id": "draft",
                        "gate_status": "PASSED",
                        "provider_verified": True,
                        "calibration_status": "PROVIDER_UNCALIBRATED",
                    }.items()
                ],
            },
        ],
    }
    report = build_quality_group_evidence(
        group="platform",
        project_id="p",
        revision={"text": text},
        revision_asset_version_id="draft",
        context_bundle=context,
        canon={},
        fixture=False,
    )
    dimension = next(
        item for item in report["dimensions"] if item["dimension"] == "chapter_length"
    )
    assert dimension["gate_status"] == status
    assert dimension["calibration_status"] == "DETERMINISTIC"
    assert dimension["evidence_locations"][0]["observed"] == count
