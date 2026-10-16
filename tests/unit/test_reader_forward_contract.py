from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from novel_forge.modules.book_followup_authority.reader_recovery import (
    output_capacity_contract_failure,
    read_reader_recovery_source,
)
from novel_forge.modules.chapter_authority.provider_views import (
    project_reader_outcome_context_input,
    _build_reader_outcome_context_view,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_followup_authority.completed_reader import (
    completed_reader_result,
)
from novel_forge.modules.capability_packs.longform_profiles import (
    build_reader_outcome_pack_profile,
)
from novel_forge.modules.book_followup_authority.definitions import (
    book_followup_operation_definitions,
    reader_outcome_definition,
)

ROOT = Path(__file__).resolve().parents[2]


def capacity():
    return {
        "status": "BLOCKED",
        "task": {"input_tokens": 100, "output_tokens": 600},
        "selected": None,
        "candidates": [
            {
                "rejected_reasons": ["CONTEXT_CAPACITY_EXCEEDED"],
                "candidate": {"output_limit": 500, "context_limit": 1000},
            }
        ],
    }


def test_reader_capacity_requires_a_pure_output_limit_failure():
    assert output_capacity_contract_failure(capacity())
    for mutate in (
        lambda d: d.update(selected={"model": "chosen"}),
        lambda d: d["task"].update(input_tokens=900),
        lambda d: d["task"].update(output_tokens=400),
        lambda d: d["task"].update(output_tokens="600"),
        lambda d: d["candidates"][0].update(
            rejected_reasons=["CONTEXT_CAPACITY_EXCEEDED", "AUTHORIZATION_REQUIRED"]
        ),
    ):
        decision = capacity()
        mutate(decision)
        assert not output_capacity_contract_failure(decision)


@pytest.mark.parametrize("blocked", [True, False])
def test_reader_recovery_never_consumes_an_external_intent_or_unsettled_owner(blocked):
    cursor = MagicMock()
    cursor.fetchone.return_value = (
        {
            "definition_name": "reader_outcome.evaluate",
            "definition_version": "1.1.0",
            "status": "FAILED_FINAL",
        },
        "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID",
        blocked,
    )
    assert bool(read_reader_recovery_source(cursor, "source", "project")) is not blocked
    assert "authority_lease_acquisition" in cursor.execute.call_args[0][0]
    assert "status<>'SETTLED'" in cursor.execute.call_args[0][0]


def test_current_reader_projection_requires_selected_best_candidate():
    content = {"text": "Accepted selected prose"}
    assert project_reader_outcome_context_input("best_draft_candidate", content) == {}
    assert (
        project_reader_outcome_context_input(
            "best_draft_candidate", content, coordinated_contract=True
        )["text"]
        == content["text"]
    )
    bundle = {
        "schema_version": "novelos.reader_outcome_context_bundle.v3",
        "selected_inputs": [
            {
                "asset_type": "best_draft_candidate",
                "asset_version_id": "best",
                "projection": {"text": "Accepted selected prose"},
            }
        ],
    }
    assert (
        _build_reader_outcome_context_view(bundle)["segments"][0]["asset_version_id"]
        == "best"
    )
    legacy = deepcopy(bundle)
    legacy["schema_version"] = "novelos.reader_outcome_context_bundle.v2"
    with pytest.raises(KernelError):
        _build_reader_outcome_context_view(legacy)
    bundle["selected_inputs"][0]["asset_type"] = "draft_version"
    with pytest.raises(KernelError):
        _build_reader_outcome_context_view(bundle)


def test_reader_factory_preserves_legacy_default_and_adds_explicit_pack():
    old = next(
        d
        for d in book_followup_operation_definitions(
            application_build_id="test", commit_sha="a" * 40
        )
        if d["name"] == "reader_outcome.evaluate"
    )
    new = reader_outcome_definition(application_build_id="test", commit_sha="a" * 40)
    assert old["definition_version"] == "1.1.0" and new["definition_version"] == "1.4.0"
    assert new["definition_status"] == "implemented_validation_pending"
    legacy = build_reader_outcome_pack_profile(
        ROOT, operation_definition_hash="sha256:" + "a" * 64
    )
    current = build_reader_outcome_pack_profile(
        ROOT, operation_definition_hash="sha256:" + "b" * 64, coordinated_contract=True
    )
    assert legacy.workflow_ref == "book_followup_reader_outcome@1.1.0"
    assert legacy.manifest["identity"]["version"] == "1.2.0"
    assert current.workflow_ref == "book_followup_reader_outcome@1.4.0"
    assert current.manifest["identity"]["version"] == "1.8.0"
    assert (
        current.manifest["workflow_template"]["nodes"][0]["input_asset_types"][0]
        == "best_draft_candidate"
    )


def test_completed_reader_uses_formal_owner_receipt_and_rejects_unsettled_accounting():
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchone.return_value = (
        "owner",
        "actor",
        "trace",
        "correlation",
        "SUCCEEDED",
    )
    with (
        patch(
            "novel_forge.modules.book_followup_authority.completed_reader.AuthorityUnitOfWork",
            return_value=uow,
        ),
        patch(
            "novel_forge.modules.book_followup_authority.completed_reader.read_completed_operation_success",
            return_value={"budget_reservation_status": "HELD_UNKNOWN"},
        ) as read,
    ):
        with pytest.raises(KernelError, match="settled"):
            completed_reader_result("db", effect_id="effect", project_id="project")
        assert read.call_args.kwargs["effect_id"] == "effect"
        assert read.call_args.args[1].operation_id == "owner"


def test_current_recap_uses_native_immutable_observations_only_and_keeps_old_default():
    from novel_forge.modules.book_followup_authority.definitions import (
        longform_recap_definition,
    )
    from novel_forge.modules.book_followup_authority.domain import (
        build_longform_recap_outputs,
        LongformCheckpointType,
    )

    old = next(
        d
        for d in book_followup_operation_definitions(
            application_build_id="test", commit_sha="a" * 40
        )
        if d["name"] == "longform.recap"
    )
    new = longform_recap_definition(application_build_id="test", commit_sha="a" * 40)
    assert old["definition_version"] == "1.1.0" and new["definition_version"] == "1.2.0"
    observation = {
        "contract_version": "accepted-realization-deviations.v2",
        "project_id": "p",
        "book_id": "b",
        "chapter_number": 2,
        "accepted_history_mutation_allowed": False,
        "deviations": [{"deviation_id": "proof"}],
    }
    arguments = dict(
        project_id="p",
        book_id="b",
        chapter_range=(1, 2),
        checkpoint_type=LongformCheckpointType.ARC_CHECKPOINT,
        observations={"accepted_realization_deviations": observation},
    )
    legacy = build_longform_recap_outputs(**arguments)
    current = build_longform_recap_outputs(**arguments, coordinated_contract=True)
    assert not any(
        item["type"] == "ACCEPTED_REALIZATION_DEVIATION"
        for item in legacy["deviation_report"]["deviations"]
    )
    assert any(
        item["type"] == "ACCEPTED_REALIZATION_DEVIATION"
        for item in current["deviation_report"]["deviations"]
    )
    assert current["recap"]["plan_mutation_allowed"] is False
    observation["book_id"] = "foreign"
    with pytest.raises(ValueError):
        build_longform_recap_outputs(**arguments, coordinated_contract=True)


@pytest.mark.parametrize("invalid", [None, "wrong-hash", "wrong-frontier"])
def test_recap_native_scope_hash_and_future_boundary_fail_closed(invalid):
    from novel_forge.modules.book_followup_authority.accepted_realization import (
        read_accepted_realization_deviations,
    )
    from novel_forge.modules.hierarchical_planning.realization_domain import (
        realization_hash,
    )

    cursor = MagicMock()
    cursor.fetchone.return_value = (
        None
        if invalid is None
        else (
            "acceptance",
            2,
            "owner",
            "run",
            "root",
            {"book_production_input_snapshot_id": "snapshot"},
        )
    )
    evidence = {"chapter_number": 2}
    cursor.fetchall.return_value = [
        (
            "deviation",
            "MISSING_REQUIRED_EVENT",
            "realization",
            "bad" if invalid == "wrong-hash" else realization_hash(evidence),
            2 if invalid == "wrong-frontier" else 3,
            evidence,
        )
    ]
    with patch(
        "novel_forge.modules.book_followup_authority.accepted_realization.require_known_cli_lineage"
    ):
        with pytest.raises(KernelError):
            read_accepted_realization_deviations(
                cursor,
                project_id="p",
                workspace_id="w",
                book_id="b",
                chapter_request_id="request",
                actor_id="actor",
            )
    assert not any(
        "UPDATE " in call.args[0] or "INSERT " in call.args[0]
        for call in cursor.execute.call_args_list
    )
