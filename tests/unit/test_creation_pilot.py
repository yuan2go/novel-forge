from __future__ import annotations
from pathlib import Path

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

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


def mixed_configuration():
    from scripts.run_world_production_smoke import ACCOUNT_ENTITLEMENT_IDENTITY, CAPS
    return {
        **{key: "verified-runtime-identity" for key in ACCOUNT_ENTITLEMENT_IDENTITY},
        **{key: "2" for key in CAPS},
        "NOVEL_FORGE_CODEX_ACCOUNTING_MODE": "ACCOUNT_ENTITLEMENT",
        "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT": "1600",
        "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT": "80000000",
        "NOVEL_FORGE_PROJECT_TOTAL_PROVIDER_CAP": "20",
        "NOVEL_FORGE_ENVIRONMENT": "validation",
        "NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID": "operator",
        "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": "isolated-project",
    }


def mixed_accounting():
    return {"accounting_basis": "MIXED", "authorization_ref": "native-campaign",
            "authorized_total_usd": "20", "monetary_cost_status": "PRICED_ESTIMATED_ENTITLEMENT_UNKNOWN"}


def test_creation_freeze_covers_every_configured_production_money_cap():
    from scripts.creation_comparison import COMPARISON_RUNTIME_SETTINGS
    from scripts.run_world_production_smoke import MONETARY_CAPS
    assert set(MONETARY_CAPS) <= COMPARISON_RUNTIME_SETTINGS


def test_native_mixed_configuration_does_not_flatten_codex_into_priced_or_free_execution():
    from scripts.run_world_production_smoke import validate_configuration
    values = mixed_configuration()
    with pytest.raises(ValueError, match="cannot use monetary Provider caps"):
        validate_configuration(values)
    validate_configuration(values, campaign_accounting=mixed_accounting())
    assert authorize_execution(values, "", values["NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF"])["monetary_cost_status"] == "UNKNOWN"
    assert values["NOVEL_FORGE_PROJECT_TOTAL_PROVIDER_CAP"] == "20"


@pytest.mark.parametrize("cap", ["0", "-1", "NaN", "21", ""])
def test_mixed_caps_cannot_exceed_or_drop_the_native_allowance(cap):
    from scripts.run_world_production_smoke import validate_configuration
    values = mixed_configuration()
    values["NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL"] = cap
    with pytest.raises(ValueError, match="within native campaign allowance"):
        validate_configuration(values, campaign_accounting=mixed_accounting())


@pytest.mark.parametrize("key", ["NOVEL_FORGE_PROVIDER_DAILY_CAP", "NOVEL_FORGE_GLOBAL_PROVIDER_CAP",
    "NOVEL_FORGE_GLOBAL_MONTHLY_PROVIDER_CAP", "NOVEL_FORGE_WORK_PROVIDER_CAP", "NOVEL_FORGE_MODEL_PROJECT_CAP"])
@pytest.mark.parametrize("cap", ["NaN", "21"])
def test_all_configured_runtime_money_caps_bind_the_native_allowance(key, cap):
    from scripts.run_world_production_smoke import validate_configuration
    values = mixed_configuration()
    values[key] = cap
    with pytest.raises(ValueError, match="within native campaign allowance"):
        validate_configuration(values, campaign_accounting=mixed_accounting())
    with pytest.raises(ValueError, match="cannot use monetary Provider caps"):
        validate_configuration(values)


@pytest.mark.parametrize("change", [{"accounting_basis": "PRICED"}, {"monetary_cost_status": "KNOWN"},
    {"authorization_ref": ""}, {"authorized_total_usd": "NaN"}, {"authorized_total_usd": "-1"},
    {"authorized_total_usd": "0"}])
def test_mixed_configuration_requires_a_finite_native_priced_grant(change):
    from scripts.run_world_production_smoke import validate_configuration
    with pytest.raises(ValueError):
        validate_configuration(mixed_configuration(), campaign_accounting={**mixed_accounting(), **change})


@pytest.mark.parametrize("calls,tokens", [(0, 0), (1, 0), (0, 100)])
def test_creation_initialization_requires_both_positive_native_dimensions_before_commands(tmp_path, calls, tokens):
    from novel_forge.storage.versioned_policy_repository import policy_hash
    from scripts.creation_pilot import prepare_pilot_book
    from tests.unit.test_creation_comparison import comparison_identities
    identity = comparison_identities(tmp_path)[0]
    frozen, binding = identity["frozen_configuration"], identity["budget_binding"]
    binding["authorization"]["authorized_cumulative_caps"]["CREATION"] = {"calls": calls, "tokens": tokens}
    binding["policy_hash"] = policy_hash({
        "policy_version": binding["policy_version"], "comparison_budget": frozen["comparison_budget"],
        "authorization": binding["authorization"],
    })
    with pytest.raises(ValueError, match="requires positive CREATION calls and tokens"):
        prepare_pilot_book(
            composition=None, principal=None, project_id=identity["project_id"],
            workspace_id=frozen["runtime_identity"]["workspace_id"], book_id=identity["book_id"],
            run_key=identity["run_key"], title="No command may run", frozen=frozen,
            initialize=True, budget_binding=binding,
        )


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
    source = Path(__file__).resolve().parents[2] / "tests/fixtures/creation/knowledge-closure"
    report = prepare(tmp_path / "unbound", input_dir=source, synthetic_source_imports=True)
    assert report["real_provider_execution"] == "NOT_RUN"
    assert report["arm_a_binding"] == "KNOWLEDGE_APPROVAL_AND_EXACT_VERSION_BINDING_REQUIRED"
    assert not (tmp_path / "unbound/allow-only.json").exists()
    for name, digest in report["files"].items():
        assert digest == "sha256:" + hashlib.sha256((tmp_path / "unbound" / name).read_bytes()).hexdigest()
    bound = prepare(tmp_path / "bound", ["exact-approved-version"], target_book_id="planned-treatment-book", input_dir=source, synthetic_source_imports=True)
    policy = json.loads((tmp_path / "bound/allow-only.json").read_text())
    assert policy["allowed_knowledge_card_asset_version_ids"] == ["exact-approved-version"]
    creation = json.loads((tmp_path / "bound/creation.json").read_text())
    assert creation["profiles"]["production_profile"]["content"]["target_chapter_count"] == 6
    assert creation["chapter_group_execution"]["maximum_chapters"] == 3
    assert creation["future_plan_change"]["after_chapter"] == 3
    assert bound["analysis_target"]["target_book_id"] == "planned-treatment-book"
    assert bound["analysis_target"]["intended_use"] == "ABSTRACT_GENERATION"
    for name in ("professional", "fiction"):
        imported = json.loads((tmp_path / "bound" / f"{name}-import.json").read_text())
        assert imported["purpose"] == "PRODUCTION_REFERENCE"
        assert imported["rights"]["allowed_purposes"] == ["PRODUCTION_REFERENCE"]
        assert "ABSTRACT_GENERATION" in imported["rights"]["allowed_uses"]
    from novel_forge.modules.command_kernel.errors import KernelError
    with pytest.raises(KernelError):
        prepare(tmp_path / "empty", [], input_dir=source, synthetic_source_imports=True)


def test_blind_export_does_not_turn_missing_prose_into_review_material(tmp_path):
    from scripts.prepare_knowledge_closure import blind_export
    with pytest.raises(ValueError, match="six exact accepted chapters"):
        blind_export(tmp_path / "a", tmp_path / "b", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("long_goal", [False, True], ids=["bounded-target", "long-novel-pilot"])
@pytest.mark.parametrize("boundary", [6, 30, 40, 50])
def test_creation_cursor_closes_accepted_group_without_dispatching_next_chapter(monkeypatch, long_goal, boundary):
    from scripts import run_world_production_smoke as runner
    monkeypatch.setattr(runner, "RuntimeJobAuthority", lambda _database: None)
    book = {"project_id": "p", "book_id": "b", "book_run_id": "run", "state": "CANON_COMMITTED",
            "target_chapter_count": 180 if long_goal else boundary, "accepted_through_chapter": boundary}
    group = {"group_run_id": "second-group", "state": "CLOSURE_PENDING", "chapter_end": boundary}
    closed, paused, events = [], [], []
    def close(identity, **_kw):
        closed.append(identity)
        group["state"] = "COMPLETED"
        return group
    def pause(identity, **_kw):
        paused.append(identity)
        book["state"] = "PAUSED"
        return book
    composition = SimpleNamespace(
        principal="operator", authority=SimpleNamespace(database_url="not-connected", require=lambda _id: dict(book), pause=pause),
        query=SimpleNamespace(active_chapter_group_run_id=lambda **_kw: "" if closed else "second-group"),
        chapter_groups=SimpleNamespace(require=lambda _id: dict(group), close=close),
    )
    chapter = Mock()
    options = {"pilot_stop_after_chapter": boundary} if long_goal else {}
    for _ in range(2):
        result = runner.drive(composition=composition, chapter=chapter, book_run_id="run", worker="worker",
                              events=events.append, maximum_ticks=2, deadline=0, **options)
        assert result == ("PILOT_ACCEPTED_CURSOR_REACHED" if long_goal else "ACCEPTED_TARGET_REACHED")
    assert closed == ["second-group"]
    assert paused == (["run"] if long_goal else [])
    assert book["target_chapter_count"] == (180 if long_goal else boundary)
    assert book["accepted_through_chapter"] == boundary
    chapter.scheduler.assert_not_called()


@pytest.mark.parametrize("cursor", [-1, True, 6.0, "6", 180, 181])
def test_pilot_cursor_cannot_replace_or_exceed_full_novel_goal(cursor):
    from scripts.creation_pilot import pilot_stop_cursor
    with pytest.raises(ValueError):
        pilot_stop_cursor({"pilot_stop_after_chapter": cursor}, book_target=180)


def test_pilot_cursor_and_future_change_are_separate_frozen_boundaries():
    from scripts.creation_pilot import pilot_stop_cursor
    policy = {"pilot_stop_after_chapter": 6, "future_plan_change": {"after_chapter": 3}}
    assert pilot_stop_cursor(policy, book_target=180) == 6
    assert pilot_stop_cursor({}, book_target=180) == 0
    with pytest.raises(ValueError, match="precede"):
        pilot_stop_cursor({"pilot_stop_after_chapter": 3, "future_plan_change": {"after_chapter": 3}}, book_target=180)


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


def test_custom_pilot_input_freeze_preserves_rights_and_does_not_invent_sources(tmp_path):
    import hashlib
    import json
    from scripts.prepare_knowledge_closure import main
    source = tmp_path / 'custom'
    source.mkdir()
    manifest = {'purpose': 'PRODUCTION_REFERENCE', 'rights': {'evidence_refs': ['rights:operator-declared']}}
    (source / 'real-import.json').write_text(json.dumps(manifest))
    (source / 'creation.json').write_text(json.dumps({'pilot_stop_after_chapter': 6}))
    destination = tmp_path / 'frozen'
    assert main(['prepare', '--input-dir', str(source), '--input-names', 'real-import.json', 'creation.json', '--output', str(destination), '--target-book-id', 'treatment-book']) == 0
    assert (destination / 'real-import.json').read_bytes() == (source / 'real-import.json').read_bytes()
    assert not (destination / 'professional-import.json').exists()
    assert not (destination / 'fiction-import.json').exists()
    frozen = json.loads((destination / 'freeze.json').read_text())
    assert frozen['input_directory'] == str(source.resolve())
    assert frozen['analysis_target']['target_book_id'] == 'treatment-book'
    assert frozen['files']['real-import.json'] == 'sha256:' + hashlib.sha256((source / 'real-import.json').read_bytes()).hexdigest()


@pytest.mark.parametrize('pilot,boundary,accepted', [(True, 6, 6), (False, 3, 3), (False, 3, 4)])
def test_frozen_cursor_blocks_group_crossing_without_dispatch(monkeypatch, pilot, boundary, accepted):
    from scripts import run_world_production_smoke as runner
    monkeypatch.setattr(runner, 'RuntimeJobAuthority', lambda _database: None)
    book = {'project_id': 'p', 'book_id': 'b', 'book_run_id': 'run', 'state': 'CANON_COMMITTED',
            'target_chapter_count': 180, 'accepted_through_chapter': accepted}
    group = {'group_run_id': 'crossing', 'state': 'CHAPTER_RUNNING', 'chapter_start': boundary - 1,
             'chapter_end': boundary + 1}
    def reconcile(*_args, **_kwargs):
        group['state'] = 'READY'
        return group
    def pause(*_args, **_kwargs):
        book['state'] = 'PAUSED'
        return book
    composition = SimpleNamespace(
        principal='operator', authority=SimpleNamespace(database_url='none', require=lambda _id: dict(book), pause=pause),
        query=SimpleNamespace(active_chapter_group_run_id=lambda **_kw: 'crossing',
            active_plan_covering_chapter=lambda **_kw: {'asset_version_id': 'crossing-plan', 'content': {'chapter_range': [boundary-1, boundary+1]}}),
        chapter_groups=SimpleNamespace(require=lambda _id: dict(group), reconcile_and_accept=reconcile),
    )
    chapter = Mock()
    expected = 'PILOT_CURSOR_PARTIAL_GROUP_BLOCKED' if pilot else 'FUTURE_PLAN_CHANGE_SCOPE_BLOCKED' if accepted == boundary else 'FUTURE_PLAN_CHANGE_CURSOR_PASSED'
    result = runner.drive(composition=composition, chapter=chapter, book_run_id='run', worker='worker', events=lambda _event: None,
                          maximum_ticks=1, deadline=0, **{'pilot_stop_after_chapter' if pilot else 'stop_after_chapter': boundary})
    assert result == expected
    assert book['state'] == 'PAUSED'
    assert book['accepted_through_chapter'] == accepted and book['target_chapter_count'] == 180
    chapter.scheduler.assert_not_called()
    if pilot:
        assert group['state'] == 'READY'
