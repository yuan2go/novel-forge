from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority import BookProductionSupervisorTick
from novel_forge.modules.command_kernel.errors import KernelError


def _load_script():
    root = Path(__file__).resolve().parents[2]
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "run_short_longform_runtime_proof",
            scripts / "run_short_longform_runtime_proof.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts))


def test_real_proof_pack_identity_is_loaded_from_the_governed_manifest() -> None:
    proof = _load_script()
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "config/capability_packs/chapter_generation_pack.json"
        ).read_text(encoding="utf-8")
    )

    globals_ = proof._install_pack.__globals__
    assert globals_["PACK_ID"] == manifest["identity"]["pack_id"]
    assert globals_["PACK_VERSION"] == manifest["identity"]["version"]


def test_proof_object_store_buckets_are_stable_and_run_isolated(tmp_path: Path) -> None:
    proof = _load_script()

    first = proof._proof_bucket_names(tmp_path / "attempt-a")
    replay = proof._proof_bucket_names(tmp_path / "attempt-a")
    second = proof._proof_bucket_names(tmp_path / "attempt-b")

    assert first == replay
    assert first != second
    assert set(first) == {"raw", "artifact", "export"}
    assert all(name.startswith("novel-forge-proof-") for name in first.values())
    assert all(len(name) <= 63 for name in first.values())


def test_retry_installs_a_new_immutable_planning_pack_version() -> None:
    proof = _load_script()

    assert proof.PLANNING_PACK_INITIAL_VERSION == "1.5.0"
    assert proof.PLANNING_PACK_RECOVERY_VERSION == "1.6.0"
    assert proof.PLANNING_PACK_INITIAL_VERSION != proof.PLANNING_PACK_RECOVERY_VERSION


def test_provider_evidence_uses_the_persisted_process_receipt_lineage() -> None:
    proof = _load_script()
    content = {
        "real_model_call": True,
        "fixture_protocol_only": False,
        "usage": {"total_tokens": 10},
        "cost": {"amount": "0.01"},
        "production_execution": {
            "execution_handle": {
                "transport": "LOCAL_CLI_REMOTE_INFERENCE",
                "local_execution_receipt_id": "process-receipt:1",
            },
            "execution_result": {
                "outcome": "SUCCEEDED",
                "process_receipt_ref": "authority-asset-version:receipt-1",
            },
            "process_evidence": {
                "local_execution_receipt_id": "process-receipt:1",
                "terminal_event_observed": True,
                "model_authority": {"frozen_route_model": "gpt-5.6-sol"},
            },
        },
    }

    evidence = proof._provider_evidence(content)

    assert evidence["real_provider_call"] is True
    assert evidence["fixture_protocol_only"] is False
    assert evidence["model_authority"] == {"frozen_route_model": "gpt-5.6-sol"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("receipt", "process-receipt:other"),
        ("terminal", False),
        ("outcome", "FAILED_FINAL"),
    ],
)
def test_provider_evidence_fails_closed_without_matching_terminal_receipt(
    field: str,
    value: object,
) -> None:
    proof = _load_script()
    content = {
        "real_model_call": True,
        "fixture_protocol_only": False,
        "production_execution": {
            "execution_handle": {
                "transport": "LOCAL_CLI_REMOTE_INFERENCE",
                "local_execution_receipt_id": "process-receipt:1",
            },
            "execution_result": {
                "outcome": "SUCCEEDED",
                "process_receipt_ref": "authority-asset-version:receipt-1",
            },
            "process_evidence": {
                "local_execution_receipt_id": "process-receipt:1",
                "terminal_event_observed": True,
            },
        },
    }
    if field == "receipt":
        content["production_execution"]["process_evidence"][  # type: ignore[index]
            "local_execution_receipt_id"
        ] = value
    elif field == "terminal":
        content["production_execution"]["process_evidence"][  # type: ignore[index]
            "terminal_event_observed"
        ] = value
    else:
        content["production_execution"]["execution_result"][  # type: ignore[index]
            "outcome"
        ] = value

    assert proof._provider_evidence(content)["real_provider_call"] is False


def test_synchronous_planning_composition_drives_retryable_attempt_to_success() -> None:
    proof = _load_script()
    calls: list[int] = []
    expected = object()

    class Planning:
        def generate(self, _command, *, principal):
            calls.append(len(calls) + 1)
            assert principal == "operator"
            if len(calls) == 1:
                raise KernelError(
                    "MODEL_EFFECT_RETRYABLE_PLANNING",
                    "controlled timeout",
                )
            return expected

    result = proof._generate_planning_with_bounded_retry(
        Planning(),
        object(),
        principal="operator",
    )

    assert result is expected
    assert calls == [1, 2]


def test_synchronous_planning_composition_does_not_retry_terminal_failure() -> None:
    proof = _load_script()
    calls: list[int] = []

    class Planning:
        def generate(self, _command, *, principal):
            calls.append(1)
            raise KernelError("MODEL_EFFECT_FINAL_PLANNING", "terminal")

    with pytest.raises(KernelError) as raised:
        proof._generate_planning_with_bounded_retry(
            Planning(),
            object(),
            principal="operator",
        )

    assert raised.value.code == "MODEL_EFFECT_FINAL_PLANNING"
    assert calls == [1]


def test_proof_uses_a_bounded_explicit_quality_context_budget() -> None:
    proof = _load_script()

    assert proof.PROOF_QUALITY_CONTEXT_TOKEN_BUDGET == 28_000
    assert (
        proof.PROOF_QUALITY_CONTEXT_TOKEN_BUDGET
        <= proof.MAX_PROOF_QUALITY_CONTEXT_TOKEN_BUDGET
    )


def test_proof_script_only_references_defined_longform_checkpoint_members() -> None:
    proof = _load_script()
    script_path = Path(proof.__file__)
    tree = ast.parse(script_path.read_text(encoding="utf-8"))
    referenced = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "LongformCheckpointType"
    }

    assert referenced <= set(proof.LongformCheckpointType.__members__)


def test_proof_world_bible_exposes_governed_rules_and_power_boundaries() -> None:
    proof = _load_script()

    content = proof._proof_world_bible_content()
    facts = {str(item["key"]): item["value"] for item in content["structured_facts"]}

    assert content["safe_summary"]
    assert facts["world_rules"]
    assert facts["institutional_power_state"]


def test_proof_platform_profile_freezes_explicit_ai_content_policy() -> None:
    proof = _load_script()

    content = proof._proof_platform_profile_content()
    facts = {str(item["key"]): item["value"] for item in content["structured_facts"]}
    ai_policy = facts["platform_rules"]["ai_content"]

    assert content["business_model"] == "custom"
    assert content["chapter_length_range"] == {
        "min": 1200,
        "ideal": 2200,
        "max": 4000,
    }
    assert ai_policy["mode"] == "GOVERNED_ASSISTED_CONTENT_ALLOWED"
    assert ai_policy["release_scope"] == "INTERNAL_PROVIDER_VALIDATION"
    assert ai_policy["chapter_content_requirements"]
    assert ai_policy["authority_publish_gate_required"] is True
    assert ai_policy["external_publication_requires_separate_human_approval"] is True


def test_resume_returns_existing_active_chapter_before_supervisor_polling() -> None:
    proof = _load_script()
    calls = []
    request = {
        "chapter_request_id": "chapter-request:1",
        "chapter_number": 1,
        "chapter_root_operation_id": "chapter-root:1",
    }
    authority = SimpleNamespace(
        require=lambda _book_run_id: {
            "active_chapter_request_id": request["chapter_request_id"]
        },
        require_chapter_request=lambda _request_id: dict(request),
    )
    supervisor = SimpleNamespace(
        authority=authority,
        tick=lambda _book_run_id: calls.append("tick"),
    )

    resumed, ticks = proof._drive_to_chapter_dispatch(
        supervisor, book_run_id="book-run:1", chapter_number=1
    )

    assert resumed == request
    assert ticks == []
    assert calls == []


def test_drive_accepts_supervisor_generated_future_chapter_plan() -> None:
    proof = _load_script()
    request = {
        "chapter_request_id": "chapter-request:2",
        "chapter_number": 2,
        "chapter_root_operation_id": "chapter-root:2",
    }
    authority = SimpleNamespace(
        require=lambda _book_run_id: {"active_chapter_request_id": ""},
        require_chapter_request=lambda _request_id: dict(request),
    )
    results = iter(
        [
            BookProductionSupervisorTick(
                book_run_id="book-run:1",
                previous_state="READY",
                state="READY",
                action=proof.SupervisorAction.GENERATE_CHAPTER_PLAN,
                operation_id="planning-operation:2",
                evidence_ref="chapter-plan:2",
            ),
            BookProductionSupervisorTick(
                book_run_id="book-run:1",
                previous_state="READY",
                state="CHAPTER_RUNNING",
                action=proof.SupervisorAction.DISPATCH_CHAPTER,
                operation_id="chapter-root:2",
                evidence_ref=request["chapter_request_id"],
            ),
        ]
    )
    supervisor = SimpleNamespace(
        authority=authority,
        tick=lambda _book_run_id: next(results),
    )

    dispatched, ticks = proof._drive_to_chapter_dispatch(
        supervisor, book_run_id="book-run:1", chapter_number=2
    )

    assert dispatched == request
    assert [tick["action"] for tick in ticks] == [
        proof.SupervisorAction.GENERATE_CHAPTER_PLAN,
        proof.SupervisorAction.DISPATCH_CHAPTER,
    ]


def test_drive_advances_generated_group_and_governed_replan() -> None:
    proof = _load_script()
    request = {
        "chapter_request_id": "chapter-request:31",
        "chapter_number": 31,
        "chapter_root_operation_id": "chapter-root:31",
    }
    approvals: list[str] = []
    authority = SimpleNamespace(
        require=lambda _book_run_id: {"active_chapter_request_id": ""},
        require_chapter_request=lambda _request_id: dict(request),
    )
    actions = (
        proof.SupervisorAction.CLOSE_CHAPTER_GROUP,
        proof.SupervisorAction.GENERATE_CHAPTER_GROUP,
        proof.SupervisorAction.FREEZE_CHAPTER_GROUP_PLAN,
        proof.SupervisorAction.START_REPLAN,
        proof.SupervisorAction.WAIT_REPLAN_APPROVAL,
        proof.SupervisorAction.ACTIVATE_REPLAN,
        proof.SupervisorAction.START_CHAPTER_GROUP,
        proof.SupervisorAction.GENERATE_CHAPTER_PLAN,
        proof.SupervisorAction.FREEZE_CHAPTER_PLAN,
        proof.SupervisorAction.DISPATCH_CHAPTER,
    )
    ticks = iter(
        BookProductionSupervisorTick(
            book_run_id="book-run:1",
            previous_state="READY",
            state="READY",
            action=action,
            operation_id=f"operation:{index}",
            evidence_ref=(
                "replan:31"
                if action is proof.SupervisorAction.WAIT_REPLAN_APPROVAL
                else request["chapter_request_id"]
                if action is proof.SupervisorAction.DISPATCH_CHAPTER
                else f"evidence:{index}"
            ),
        )
        for index, action in enumerate(actions, start=1)
    )
    supervisor = SimpleNamespace(
        authority=authority,
        tick=lambda _book_run_id: next(ticks),
    )

    dispatched, observed = proof._drive_to_chapter_dispatch(
        supervisor,
        book_run_id="book-run:1",
        chapter_number=31,
        approve_replan=approvals.append,
    )

    assert dispatched == request
    assert approvals == ["replan:31"]
    assert [item["action"] for item in observed] == list(actions)


def test_drive_fails_closed_when_replan_approval_is_unavailable() -> None:
    proof = _load_script()
    authority = SimpleNamespace(
        require=lambda _book_run_id: {"active_chapter_request_id": ""}
    )
    supervisor = SimpleNamespace(
        authority=authority,
        tick=lambda _book_run_id: BookProductionSupervisorTick(
            book_run_id="book-run:1",
            previous_state="REPLAN_APPROVAL_PENDING",
            state="REPLAN_APPROVAL_PENDING",
            action=proof.SupervisorAction.WAIT_REPLAN_APPROVAL,
            evidence_ref="replan:1",
        ),
    )

    with pytest.raises(RuntimeError, match="governed Replan approval"):
        proof._drive_to_chapter_dispatch(
            supervisor, book_run_id="book-run:1", chapter_number=2
        )


def test_runtime_planning_inputs_use_unified_book_acceptance_checkpoint(
    monkeypatch,
) -> None:
    proof = _load_script()
    authority = SimpleNamespace(
        database_url="postgresql://unused",
        chapter_port=SimpleNamespace(
            require_acceptance_evidence=lambda **_kwargs: {"outputs": []}
        ),
        require_chapter_request=lambda _request_id: {
            "chapter_root_operation_id": "chapter-root:1",
            "book_run_id": "book-run:1",
        },
        require=lambda _book_run_id: {
            "last_chapter_outcome_version_id": "asset-version:chapter-outcome:1",
            "active_story_state_version_id": "asset-version:story-state:1",
            "active_canon_snapshot_version_id": "asset-version:canon:1",
        },
    )
    monkeypatch.setattr(
        proof,
        "_followup_output",
        lambda *_args, **_kwargs: {"asset_version_id": "asset-version:reader-state:1"},
    )

    inputs = proof._runtime_planning_inputs(
        authority,
        project_id="project:1",
        chapter_request_id="chapter-request:1",
        reader_report={},
    )

    assert inputs == {
        "previous_chapter_outcome": "asset-version:chapter-outcome:1",
        "story_state": "asset-version:story-state:1",
        "canon_snapshot": "asset-version:canon:1",
        "reader_state": "asset-version:reader-state:1",
    }


def test_rolling_narrative_versions_project_one_accepted_story_state() -> None:
    proof = _load_script()

    versions = proof._rolling_narrative_versions(
        {
            "active_story_state_version_id": "story-state:v2",
            "active_canon_snapshot_version_id": "canon:v2",
        }
    )

    assert versions == {
        "story_state": "story-state:v2",
        "canon_snapshot": "canon:v2",
        "character_state": "story-state:v2",
        "foreshadowing_state": "story-state:v2",
        "reward_ledger": "story-state:v2",
        "promise_ledger": "story-state:v2",
    }


def test_rolling_narrative_versions_fail_on_partial_acceptance_checkpoint() -> None:
    proof = _load_script()

    with pytest.raises(RuntimeError, match="complete Story State and Canon"):
        proof._rolling_narrative_versions(
            {
                "active_story_state_version_id": "story-state:v2",
                "active_canon_snapshot_version_id": "",
            }
        )


def test_release_checkout_accepts_current_clean_campaign_branch(monkeypatch) -> None:
    proof = _load_script()
    values = {
        ("rev-parse", "HEAD"): "a" * 40,
        ("branch", "--show-current"): "codex/longform-narrative-proof-campaign",
        ("status", "--porcelain", "--untracked-files=normal"): "",
    }
    monkeypatch.setattr(proof, "_git", lambda *args: values[args])

    checkout = proof._release_checkout(allow_dirty=False)

    assert checkout == {
        "commit_sha": "a" * 40,
        "branch": "codex/longform-narrative-proof-campaign",
        "dirty": "",
    }


def test_release_checkout_rejects_detached_or_dirty_state(monkeypatch) -> None:
    proof = _load_script()
    values = {
        ("rev-parse", "HEAD"): "a" * 40,
        ("branch", "--show-current"): "",
        ("status", "--porcelain", "--untracked-files=normal"): "",
    }
    monkeypatch.setattr(proof, "_git", lambda *args: values[args])
    with pytest.raises(RuntimeError, match="named Git branch"):
        proof._release_checkout(allow_dirty=False)

    values[("branch", "--show-current")] = "codex/campaign"
    values[("status", "--porcelain", "--untracked-files=normal")] = " M file"
    with pytest.raises(RuntimeError, match="clean Git worktree"):
        proof._release_checkout(allow_dirty=False)
