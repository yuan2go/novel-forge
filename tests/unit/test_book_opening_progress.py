from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json

from novel_forge.modules.book_authority.opening_progress import (
    BOOK_OPENING_WORKFLOW_PROGRESS_SCHEMA_VERSION,
    BookOpeningWorkflowProgressSnapshot,
    PostgresBookOpeningWorkflowProgressQuery,
    project_book_opening_workflow_progress,
)
import pytest
from novel_forge.modules.book_authority import (
    PostgresBookOpeningWorkflowProgressQuery as ExportedProgressQuery,
)


NOW = datetime(2026, 8, 29, 13, 0, tzinfo=timezone.utc)


def test_postgres_progress_query_requires_an_explicit_database() -> None:
    assert ExportedProgressQuery is PostgresBookOpeningWorkflowProgressQuery
    with pytest.raises(ValueError, match="PostgreSQL"):
        PostgresBookOpeningWorkflowProgressQuery("")


def _node(ordinal: int, kind: str) -> dict[str, object]:
    node_keys = {
        "BOOK_PLAN": "book-plan",
        "VOLUME_PORTFOLIO": "volume-portfolio",
        "CURRENT_VOLUME": "current-volume",
        "INITIAL_ARC_SCOPE": "initial-arc-scope",
        "INPUT_SNAPSHOT": "input-snapshot",
    }
    return {
        "workflow_node_id": f"node:{ordinal}",
        "opening_run_id": "opening:1",
        "node_key": node_keys[kind],
        "node_kind": kind,
        "ordinal": ordinal,
        "input_hash": "sha256:" + str(ordinal) * 64,
        "graph_revision": 1,
        "created_at": NOW,
    }


def _canonical_nodes() -> tuple[dict[str, object], ...]:
    return (
        _node(1, "BOOK_PLAN"),
        _node(2, "VOLUME_PORTFOLIO"),
        _node(3, "CURRENT_VOLUME"),
        _node(4, "INITIAL_ARC_SCOPE"),
        _node(5, "INPUT_SNAPSHOT"),
    )


def _canonical_edges(
    nodes: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    ordered = sorted(nodes, key=lambda node: int(node["ordinal"]))
    return tuple(
        {
            "opening_run_id": "opening:1",
            "predecessor_workflow_node_id": str(ordered[index]["workflow_node_id"]),
            "successor_workflow_node_id": str(ordered[index + 1]["workflow_node_id"]),
            "edge_kind": "REQUIRES",
            "created_at": NOW,
        }
        for index in range(len(ordered) - 1)
    )


def _workflow_graph_hash(
    nodes: tuple[dict[str, object], ...],
    edges: tuple[dict[str, object], ...],
) -> str:
    ordered = sorted(
        nodes,
        key=lambda node: (int(node["ordinal"]), str(node["workflow_node_id"])),
    )
    edge_contracts = {
        (
            str(edge["predecessor_workflow_node_id"]),
            str(edge["successor_workflow_node_id"]),
        ): {
            "child_node_id": str(edge["successor_workflow_node_id"]),
            "parent_node_id": str(edge["predecessor_workflow_node_id"]),
            "relation": str(edge["edge_kind"]),
        }
        for edge in edges
    }
    contract = {
        "contract_version": "book-opening-workflow-v1",
        "graph_revision": 1,
        "nodes": [
            {
                "input_hash": str(node["input_hash"]),
                "kind": str(node["node_kind"]),
                "node_key": str(node["node_key"]),
                "ordinal": int(node["ordinal"]),
                "workflow_node_id": str(node["workflow_node_id"]),
            }
            for node in ordered
        ],
        "edges": [
            edge_contracts[
                (
                    str(ordered[index]["workflow_node_id"]),
                    str(ordered[index + 1]["workflow_node_id"]),
                )
            ]
            for index in range(len(ordered) - 1)
            if (
                str(ordered[index]["workflow_node_id"]),
                str(ordered[index + 1]["workflow_node_id"]),
            )
            in edge_contracts
        ],
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
    )


def _valid_receipt(ordinal: int, *, asset_type: str) -> dict[str, object]:
    artifact_kinds = {
        1: "BOOK_PLAN",
        2: "VOLUME_PORTFOLIO",
        3: "CURRENT_VOLUME_PLAN",
        4: "INITIAL_ARC_SCOPE",
        5: "BOOK_PRODUCTION_INPUT_SNAPSHOT",
    }
    result: dict[str, object] = (
        {
            "snapshot_id": "snapshot:5",
            "snapshot_hash": "sha256:" + "5" * 64,
        }
        if ordinal == 5
        else {"unit_fixture_ordinal": ordinal}
    )
    result_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
    )
    asset_ids = () if ordinal == 5 else (f"asset-version:{ordinal}",)
    authoritative_assets = (
        ()
        if ordinal == 5
        else (
            {
                "asset_version_id": f"asset-version:{ordinal}",
                "asset_id": f"asset:{ordinal}",
                "asset_type": asset_type,
                "project_id": "project:1",
                "content_hash": "sha256:" + "a" * 64,
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
            },
        )
    )
    return {
        "node_receipt_id": f"receipt:{ordinal}",
        "workflow_node_id": f"node:{ordinal}",
        "opening_execution_id": "execution:1",
        "execution_generation": 1,
        "result": result,
        "result_hash": result_hash,
        "authoritative_evidence_hash": "sha256:" + "e" * 64,
        "reviewable_artifact_kind": artifact_kinds[ordinal],
        "requested_asset_version_ids": asset_ids,
        "authoritative_assets": authoritative_assets,
        "authoritative_snapshot": (
            {
                "snapshot_id": "snapshot:5",
                "snapshot_hash": "sha256:" + "5" * 64,
                "project_id": "project:1",
                "workspace_id": "workspace:1",
                "book_id": "book:1",
            }
            if ordinal == 5
            else {}
        ),
        "checkpoint_id": f"checkpoint:{ordinal}",
        "checkpoint_sequence": ordinal,
        "checkpoint_hash": "sha256:" + "c" * 64,
        "authoritative_checkpoint_id": f"checkpoint:{ordinal}",
        "authoritative_checkpoint_sequence": ordinal,
        "authoritative_checkpoint_hash": "sha256:" + "c" * 64,
        "checkpoint_workflow_node_id": f"node:{ordinal}",
        "checkpoint_opening_execution_id": "execution:1",
        "checkpoint_execution_generation": 1,
        "checkpoint_evidence_hash": "sha256:" + "e" * 64,
        "created_at": NOW,
    }


def _snapshot(
    *,
    nodes: tuple[dict[str, object], ...],
    receipts: tuple[dict[str, object], ...],
    lifecycle: str = "ADMITTED",
    current_workflow_node_id: str = "node:3",
    execution: dict[str, object] | None = None,
    edges: tuple[dict[str, object], ...] | None = None,
    workflow_graph_hash: str | None = None,
    workflow_graph_revision: int = 1,
) -> BookOpeningWorkflowProgressSnapshot:
    resolved_edges = _canonical_edges(nodes) if edges is None else edges
    resolved_graph_hash = workflow_graph_hash or _workflow_graph_hash(
        nodes, resolved_edges
    )
    return BookOpeningWorkflowProgressSnapshot(
        opening={
            "opening_run_id": "opening:1",
            "project_id": "project:1",
            "workspace_id": "workspace:1",
            "book_id": "book:1",
            "lifecycle": lifecycle,
            "version": 4,
            "execution_contract_version": "book-opening-execution-v2",
            "workflow_contract_version": "book-opening-workflow-v1",
            "workflow_graph_revision": workflow_graph_revision,
            "workflow_graph_hash": resolved_graph_hash,
            "current_workflow_node_id": current_workflow_node_id,
            "current_execution_id": "execution:1",
            "current_execution_generation": 1,
            "current_checkpoint_id": "checkpoint:2",
            "current_checkpoint_sequence": 2,
            "current_checkpoint_hash": "sha256:" + "c" * 64,
            "recovery_state": "READY",
            "budget_scope_id": "budget:1",
            "budget_scope_revision": 1,
            "budget_contract_state": "BOUND",
            "failure": {},
            "recovery_instruction": {},
        },
        nodes=nodes,
        receipts=receipts,
        execution=execution,
        budget={
            "budget_scope_id": "budget:1",
            "budget_scope_revision": 1,
            "policy_snapshot": {
                "provider_call_limit": 40,
                "token_limit": 1_800_000,
                "cost_limit_usd": "20",
            },
            "started_at": NOW - timedelta(minutes=10),
            "deadline_at": NOW + timedelta(minutes=50),
            "reservation_count": 4,
            "committed_call_count": 4,
            "settled_call_count": 4,
            "held_unknown_call_count": 0,
            "reserved_call_count": 0,
            "accounted_tokens": 154_947,
            "actual_tokens": 154_947,
            "accounted_cost_usd": Decimal("0.7402675"),
            "settled_cost_usd": Decimal("0.7402675"),
            "budget_breach_count": 0,
        },
        legacy_checkpoint=None,
        observed_at=NOW,
        edges=resolved_edges,
    )


def _valid_running_execution() -> dict[str, object]:
    return {
        "opening_execution_id": "execution:1",
        "execution_generation": 1,
        "workflow_node_id": "node:1",
        "execution_lifecycle": "RUNNING",
        "runtime_job_id": "runtime-job:1",
        "runtime_job_status": "RUNNING",
        "job_current_attempt_id": "attempt:1",
        "job_claimed_by": "worker:1",
        "job_current_fencing_token": 7,
        "attempt_id": "attempt:1",
        "attempt_runtime_job_id": "runtime-job:1",
        "attempt_status": "RUNNING",
        "attempt_lease_id": "lease:1",
        "attempt_worker_id": "worker:1",
        "attempt_fencing_token": 7,
        "lease_id": "lease:1",
        "lease_runtime_job_id": "runtime-job:1",
        "lease_attempt_id": "attempt:1",
        "lease_status": "HELD",
        "lease_worker_id": "worker:1",
        "lease_fencing_token": 7,
        "worker_id": "worker:1",
        "fencing_token": 7,
        "lease_expires_at": NOW + timedelta(minutes=5),
        "execution_current_attempt_id": "attempt:1",
        "execution_current_lease_id": "lease:1",
        "execution_current_worker_id": "worker:1",
        "execution_current_fencing_token": 7,
    }


def _valid_scheduled_execution(*, workflow_node_id: str) -> dict[str, object]:
    return {
        "opening_execution_id": "execution:1",
        "execution_generation": 1,
        "workflow_node_id": workflow_node_id,
        "execution_lifecycle": "SCHEDULED",
        "runtime_job_id": "runtime-job:1",
        "runtime_job_status": "READY",
    }


def test_progress_advances_only_over_contiguous_authoritative_receipts() -> None:
    nodes = (
        _node(1, "BOOK_PLAN"),
        _node(2, "VOLUME_PORTFOLIO"),
        _node(3, "CURRENT_VOLUME"),
        _node(4, "INITIAL_ARC_SCOPE"),
        _node(5, "INPUT_SNAPSHOT"),
    )
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=nodes,
            receipts=(
                _valid_receipt(1, asset_type="book_plan"),
                _valid_receipt(2, asset_type="volume_plan"),
            ),
            execution=_valid_scheduled_execution(workflow_node_id="node:3"),
        )
    ).to_dict()

    assert progress["schema_version"] == BOOK_OPENING_WORKFLOW_PROGRESS_SCHEMA_VERSION
    assert progress["schema_version"] == (
        "novel-forge.book-opening-workflow-progress.v1"
    )
    assert progress["compatibility_mode"] == "NODED_WORKFLOW"
    assert progress["current_layer"] == {
        "workflow_node_id": "node:3",
        "node_kind": "CURRENT_VOLUME",
        "node_key": "current-volume",
        "ordinal": 3,
        "lifecycle": "QUEUED",
    }
    assert progress["furthest_completed_layer"] == {
        "workflow_node_id": "node:2",
        "node_kind": "VOLUME_PORTFOLIO",
        "node_key": "volume-portfolio",
        "ordinal": 2,
        "lifecycle": "COMPLETE",
    }
    assert [node["lifecycle"] for node in progress["nodes"]] == [
        "COMPLETE",
        "COMPLETE",
        "QUEUED",
        "PENDING",
        "PENDING",
    ]
    assert progress["nodes"][0]["reviewable_artifact"]["status"] == "AVAILABLE"
    assert progress["nodes"][1]["persistent_checkpoint"]["checkpoint_sequence"] == 2
    assert progress["nodes"][2]["reviewable_artifact"]["status"] == "NOT_FORMED"
    assert progress["nodes"][2]["persistent_checkpoint"]["status"] == "NOT_FORMED"
    assert progress["reviewable_artifact"] == {
        "status": "AVAILABLE",
        "source_workflow_node_id": "node:2",
        "node_receipt_id": "receipt:2",
        "artifact_kind": "VOLUME_PORTFOLIO",
        "asset_versions": [
            {
                "asset_version_id": "asset-version:2",
                "asset_id": "asset:2",
                "asset_type": "volume_plan",
                "content_hash": "sha256:" + "a" * 64,
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
            }
        ],
        "artifact_reference": {
            "reference_type": "AUTHORITY_ASSET_VERSION_SET",
            "asset_version_ids": ["asset-version:2"],
        },
    }
    assert progress["persistent_checkpoint"] == {
        "status": "AVAILABLE",
        "source_workflow_node_id": "node:2",
        "checkpoint_id": "checkpoint:2",
        "checkpoint_sequence": 2,
        "checkpoint_hash": "sha256:" + "c" * 64,
        "authoritative_evidence_hash": "sha256:" + "e" * 64,
    }
    assert progress["blocking_reason"]["is_blocked"] is False
    assert progress["runtime_fence"]["status"] == "NOT_REQUIRED"
    assert progress["budget_usage"]["provider_calls"] == {
        "used": 4,
        "settled": 4,
        "held_unknown": 0,
        "reserved": 0,
        "limit": 40,
    }
    assert progress["budget_usage"]["tokens"]["used"] == 154_947
    assert progress["budget_usage"]["cost_usd"]["used"] == "0.7402675"
    assert "target_chapter_count" not in progress
    assert "chapter_end" not in progress


def test_execution_v2_is_reported_as_legacy_monolithic_without_invented_assets() -> (
    None
):
    snapshot = _snapshot(
        nodes=(),
        receipts=(),
        lifecycle="ADMITTED",
        current_workflow_node_id="",
        execution={
            "execution_lifecycle": "SCHEDULED",
            "runtime_job_id": "runtime-job:legacy",
            "runtime_job_status": "READY",
        },
    )
    snapshot = BookOpeningWorkflowProgressSnapshot(
        opening={
            **snapshot.opening,
            "execution_contract_version": "book-opening-execution-v2",
            "workflow_contract_version": "legacy-monolithic-v2",
            "workflow_graph_revision": 0,
            "workflow_graph_hash": "",
            "current_checkpoint_id": "checkpoint:legacy",
            "current_checkpoint_sequence": 4,
            "current_checkpoint_hash": "sha256:" + "c" * 64,
        },
        nodes=(),
        receipts=(),
        execution=snapshot.execution,
        budget=snapshot.budget,
        legacy_checkpoint={
            "checkpoint_id": "checkpoint:legacy",
            "checkpoint_sequence": 4,
            "checkpoint_hash": "sha256:" + "c" * 64,
            "authoritative_evidence_hash": "sha256:" + "e" * 64,
            "semantic_work_key": "volume_plan.generate:volume:1",
        },
        observed_at=NOW,
    )

    progress = project_book_opening_workflow_progress(snapshot).to_dict()

    assert progress["compatibility_mode"] == "LEGACY_MONOLITHIC"
    assert progress["progress_status"] == "QUEUED"
    assert progress["current_layer"] == {
        "workflow_node_id": "",
        "node_kind": "LEGACY_MONOLITHIC",
        "node_key": "legacy:book-opening-execution-v2",
        "ordinal": 1,
        "lifecycle": "QUEUED",
    }
    assert progress["furthest_completed_layer"] is None
    assert progress["nodes"] == [progress["current_layer"]]
    assert progress["reviewable_artifact"] == {
        "status": "UNAVAILABLE_LEGACY",
        "source_workflow_node_id": "",
        "node_receipt_id": "",
        "artifact_kind": "",
        "asset_versions": [],
        "artifact_reference": {},
    }
    assert progress["persistent_checkpoint"] == {
        "status": "AVAILABLE_LEGACY",
        "source_workflow_node_id": "",
        "checkpoint_id": "checkpoint:legacy",
        "checkpoint_sequence": 4,
        "checkpoint_hash": "sha256:" + "c" * 64,
        "authoritative_evidence_hash": "sha256:" + "e" * 64,
        "semantic_work_key": "volume_plan.generate:volume:1",
    }


def test_noded_contract_without_nodes_is_inconsistent_not_complete() -> None:
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=(),
            receipts=(),
            lifecycle="ADMITTED",
            current_workflow_node_id="node:missing",
            execution=None,
        )
    ).to_dict()

    assert progress["compatibility_mode"] == "NODED_WORKFLOW"
    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["current_layer"] is None
    assert progress["furthest_completed_layer"] is None
    assert progress["blocking_reason"] == {
        "is_blocked": True,
        "blocking_class": "AUTHORITY_EVIDENCE_INCONSISTENT",
        "code": "BOOK_OPENING_WORKFLOW_GRAPH_INVALID",
        "reason": "WORKFLOW_NODES_MISSING",
        "retryable": False,
        "wake_condition": "RECONCILE_AUTHORITY_EVIDENCE",
    }


@pytest.mark.parametrize("node_count", [1, 2, 3, 4, 6])
def test_noded_contract_requires_exact_five_node_cardinality(node_count: int) -> None:
    nodes = _canonical_nodes()
    if node_count <= 4:
        nodes = nodes[:node_count]
    else:
        nodes = (*nodes, _node(6, "BOOK_PLAN"))

    progress = project_book_opening_workflow_progress(
        _snapshot(nodes=nodes, receipts=(), current_workflow_node_id="node:1")
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["blocking_reason"]["code"] == (
        "BOOK_OPENING_WORKFLOW_GRAPH_INVALID"
    )
    assert progress["blocking_reason"]["reason"] == (
        "WORKFLOW_NODE_CARDINALITY_MISMATCH"
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"ordinal": 9}, "WORKFLOW_NODE_DEFINITION_MISMATCH"),
        ({"node_kind": "INPUT_SNAPSHOT"}, "WORKFLOW_NODE_DEFINITION_MISMATCH"),
    ],
)
def test_noded_contract_rejects_wrong_node_definition(
    mutation: dict[str, object], reason: str
) -> None:
    nodes = list(_canonical_nodes())
    nodes[1] = {**nodes[1], **mutation}

    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=tuple(nodes),
            receipts=(),
            current_workflow_node_id="node:1",
        )
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["blocking_reason"]["reason"] == reason


def test_noded_contract_requires_current_node_membership() -> None:
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(),
            current_workflow_node_id="node:outside",
        )
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["blocking_reason"]["reason"] == (
        "WORKFLOW_CURRENT_NODE_NOT_IN_GRAPH"
    )


def test_noded_contract_requires_exact_four_edge_chain() -> None:
    nodes = _canonical_nodes()
    edges = list(_canonical_edges(nodes))
    edges[2] = {
        **edges[2],
        "successor_workflow_node_id": "node:5",
    }

    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=nodes,
            receipts=(),
            current_workflow_node_id="node:1",
            edges=tuple(edges),
        )
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["blocking_reason"]["reason"] == "WORKFLOW_EDGE_SET_MISMATCH"


def test_noded_contract_recomputes_graph_hash() -> None:
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(),
            current_workflow_node_id="node:1",
            workflow_graph_hash="sha256:" + "f" * 64,
        )
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["blocking_reason"]["reason"] == "WORKFLOW_GRAPH_HASH_MISMATCH"


def test_noded_contract_requires_graph_revision_one() -> None:
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(),
            current_workflow_node_id="node:1",
            workflow_graph_revision=2,
        )
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["blocking_reason"]["reason"] == ("WORKFLOW_GRAPH_REVISION_MISMATCH")


def test_receipt_cannot_advance_when_referenced_asset_is_not_authoritative() -> None:
    invalid = {
        **_valid_receipt(1, asset_type="book_plan"),
        "authoritative_assets": (),
    }
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(invalid,),
            current_workflow_node_id="node:1",
        )
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["current_layer"]["node_kind"] == "BOOK_PLAN"
    assert progress["current_layer"]["lifecycle"] == "INCONSISTENT"
    assert progress["furthest_completed_layer"] is None
    assert progress["reviewable_artifact"] == {
        "status": "INVALID",
        "source_workflow_node_id": "node:1",
        "node_receipt_id": "receipt:1",
        "artifact_kind": "BOOK_PLAN",
        "asset_versions": [],
        "artifact_reference": {
            "reference_type": "AUTHORITY_ASSET_VERSION_SET",
            "asset_version_ids": [],
        },
        "evidence_problem": "REVIEWABLE_ASSET_AUTHORITY_MISMATCH",
    }
    assert progress["persistent_checkpoint"]["status"] == "AVAILABLE"
    assert progress["blocking_reason"] == {
        "is_blocked": True,
        "blocking_class": "AUTHORITY_EVIDENCE_INCONSISTENT",
        "code": "BOOK_OPENING_NODE_RECEIPT_INVALID",
        "reason": "REVIEWABLE_ASSET_AUTHORITY_MISMATCH",
        "retryable": False,
        "wake_condition": "RECONCILE_AUTHORITY_EVIDENCE",
    }


def test_receipt_cannot_advance_over_checkpoint_tuple_drift() -> None:
    invalid = {
        **_valid_receipt(1, asset_type="book_plan"),
        "authoritative_checkpoint_hash": "sha256:" + "f" * 64,
    }
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(invalid,),
            current_workflow_node_id="node:1",
        )
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["furthest_completed_layer"] is None
    assert progress["persistent_checkpoint"] == {
        "status": "INVALID",
        "source_workflow_node_id": "node:1",
        "checkpoint_id": "checkpoint:1",
        "checkpoint_sequence": 1,
        "checkpoint_hash": "sha256:" + "c" * 64,
        "authoritative_evidence_hash": "sha256:" + "e" * 64,
        "evidence_problem": "CHECKPOINT_AUTHORITY_MISMATCH",
    }


def test_later_receipt_without_predecessor_is_non_contiguous_evidence() -> None:
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(_valid_receipt(2, asset_type="volume_plan"),),
            current_workflow_node_id="node:1",
        )
    ).to_dict()

    assert progress["progress_status"] == "INCONSISTENT"
    assert progress["furthest_completed_layer"] is None
    assert progress["nodes"][0]["lifecycle"] == "READY"
    assert progress["nodes"][1]["lifecycle"] == "INCONSISTENT"
    assert progress["nodes"][1]["evidence_problem"] == ("NON_CONTIGUOUS_NODE_RECEIPT")
    assert progress["blocking_reason"]["reason"] == ("NON_CONTIGUOUS_NODE_RECEIPT")


def test_running_requires_one_exact_runtime_fence_generation() -> None:
    execution = _valid_running_execution()
    execution["execution_current_fencing_token"] = 8
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(),
            lifecycle="RUNNING",
            current_workflow_node_id="node:1",
            execution=execution,
        )
    ).to_dict()

    assert progress["current_layer"]["lifecycle"] == "RUNNING"
    assert progress["runtime_fence"]["status"] == "INVALID"
    assert progress["runtime_fence"]["required_fencing_token"] == 8
    assert progress["runtime_fence"]["observed_fencing_token"] == 7
    assert progress["blocking_reason"] == {
        "is_blocked": True,
        "blocking_class": "EXECUTION_LOST",
        "code": "BOOK_OPENING_EXECUTION_FENCE_INVALID",
        "reason": "RUNNING Book Opening has no valid current RuntimeJob Lease fence",
        "retryable": False,
        "wake_condition": "CONVERGE_EXECUTION_LOSS",
    }


def test_claimed_node_is_a_valid_starting_window_before_opening_runs() -> None:
    execution = _valid_running_execution()
    execution.update(
        {
            "execution_lifecycle": "BOUND",
            "runtime_job_status": "CLAIMED",
            "attempt_status": "CLAIMED",
        }
    )
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(),
            lifecycle="ADMITTED",
            current_workflow_node_id="node:1",
            execution=execution,
        )
    ).to_dict()

    assert progress["runtime_fence"]["status"] == "VALID"
    assert progress["runtime_fence"]["execution_phase"] == "CLAIMED"
    assert progress["blocking_reason"]["is_blocked"] is False


def test_running_runtime_fence_fails_closed_when_job_binding_is_missing() -> None:
    execution = _valid_running_execution()
    execution["job_current_attempt_id"] = ""

    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(),
            lifecycle="RUNNING",
            current_workflow_node_id="node:1",
            execution=execution,
        )
    ).to_dict()

    assert progress["runtime_fence"]["status"] == "INVALID"
    assert progress["blocking_reason"]["code"] == (
        "BOOK_OPENING_EXECUTION_FENCE_INVALID"
    )


def test_running_opening_without_current_execution_is_execution_lost() -> None:
    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(),
            lifecycle="RUNNING",
            current_workflow_node_id="node:1",
            execution=None,
        )
    ).to_dict()

    assert progress["runtime_fence"]["status"] == "INVALID"
    assert progress["progress_status"] == "BLOCKED"
    assert progress["blocking_reason"]["code"] == (
        "BOOK_OPENING_EXECUTION_FENCE_INVALID"
    )


def test_terminal_execution_chain_is_reported_as_the_blocking_reason() -> None:
    execution = _valid_running_execution()
    execution.update(
        {
            "execution_lifecycle": "LOST",
            "runtime_job_status": "FAILED",
            "attempt_status": "ABANDONED",
            "lease_status": "EXPIRED",
        }
    )

    progress = project_book_opening_workflow_progress(
        _snapshot(
            nodes=_canonical_nodes(),
            receipts=(),
            lifecycle="ADMITTED",
            current_workflow_node_id="node:1",
            execution=execution,
        )
    ).to_dict()

    assert progress["current_layer"]["lifecycle"] == "BLOCKED"
    assert progress["blocking_reason"] == {
        "is_blocked": True,
        "blocking_class": "EXECUTION_LOST",
        "code": "BOOK_OPENING_EXECUTION_TERMINAL_WITHOUT_CHECKPOINT",
        "reason": "LOST",
        "retryable": False,
        "wake_condition": "CONVERGE_EXECUTION_LOSS",
    }


def test_budget_usage_is_a_fail_closed_execution_gate() -> None:
    snapshot = _snapshot(
        nodes=_canonical_nodes(),
        receipts=(),
        current_workflow_node_id="node:1",
        execution=_valid_scheduled_execution(workflow_node_id="node:1"),
    )
    progress = project_book_opening_workflow_progress(
        BookOpeningWorkflowProgressSnapshot(
            opening=snapshot.opening,
            nodes=snapshot.nodes,
            receipts=snapshot.receipts,
            execution=snapshot.execution,
            budget={
                **snapshot.budget,
                "accounted_tokens": 1_800_000,
                "actual_tokens": 1_799_000,
            },
            legacy_checkpoint=snapshot.legacy_checkpoint,
            observed_at=snapshot.observed_at,
            edges=snapshot.edges,
        )
    ).to_dict()

    assert progress["current_layer"]["node_kind"] == "BOOK_PLAN"
    assert progress["current_layer"]["lifecycle"] == "QUEUED"
    assert progress["progress_status"] == "BLOCKED"
    assert progress["budget_usage"]["status"] == "EXHAUSTED"
    assert progress["budget_usage"]["exhaustion_reasons"] == ["TOKEN_LIMIT_REACHED"]
    assert progress["blocking_reason"] == {
        "is_blocked": True,
        "blocking_class": "BUDGET",
        "code": "BOOK_OPENING_BUDGET_EXHAUSTED",
        "reason": "TOKEN_LIMIT_REACHED",
        "retryable": False,
        "wake_condition": "STOP_AND_REVIEW_BUDGET",
    }


def test_account_entitlement_progress_never_reports_zero_monetary_cost() -> None:
    snapshot = _snapshot(
        nodes=_canonical_nodes(),
        receipts=(),
        current_workflow_node_id="node:1",
        execution=_valid_scheduled_execution(workflow_node_id="node:1"),
    )
    progress = project_book_opening_workflow_progress(
        BookOpeningWorkflowProgressSnapshot(
            opening=snapshot.opening,
            nodes=snapshot.nodes,
            receipts=snapshot.receipts,
            execution=snapshot.execution,
            budget={
                **snapshot.budget,
                "policy_snapshot": {
                    "execution_mode": "PROVIDER_ALLOWED",
                    "accounting_basis": "ACCOUNT_ENTITLEMENT",
                    "authorization_ref": (
                        "task-authorization:classical-corpus-20260908"
                    ),
                    "cost_observability": "UNKNOWN",
                    "provider_call_limit": 420,
                    "token_limit": 42_000_000,
                },
                "accounted_cost_usd": Decimal("0"),
                "settled_cost_usd": Decimal("0"),
            },
            legacy_checkpoint=snapshot.legacy_checkpoint,
            observed_at=snapshot.observed_at,
            edges=snapshot.edges,
        )
    ).to_dict()

    assert progress["budget_usage"]["cost_usd"] == {
        "used": None,
        "settled": None,
        "limit": None,
        "status": "UNKNOWN",
        "accounting_basis": "ACCOUNT_ENTITLEMENT",
    }
    assert "COST_LIMIT_REACHED" not in progress["budget_usage"]["exhaustion_reasons"]


def test_bound_budget_without_authority_row_requires_reconciliation() -> None:
    snapshot = _snapshot(
        nodes=_canonical_nodes(),
        receipts=(),
        current_workflow_node_id="node:1",
        execution=_valid_scheduled_execution(workflow_node_id="node:1"),
    )
    progress = project_book_opening_workflow_progress(
        BookOpeningWorkflowProgressSnapshot(
            opening=snapshot.opening,
            nodes=snapshot.nodes,
            receipts=snapshot.receipts,
            execution=snapshot.execution,
            budget={},
            legacy_checkpoint=snapshot.legacy_checkpoint,
            observed_at=snapshot.observed_at,
            edges=snapshot.edges,
        )
    ).to_dict()

    assert progress["budget_usage"]["status"] == "RECONCILIATION_REQUIRED"
    assert progress["budget_usage"]["authority_binding_status"] == "INVALID"
    assert progress["blocking_reason"]["code"] == (
        "BOOK_OPENING_BUDGET_RECONCILIATION_REQUIRED"
    )


def test_mixed_opening_cost_keeps_unknown_total_and_enforces_priced_lane() -> None:
    from novel_forge.modules.book_authority.opening_progress import _budget_usage

    snapshot = _snapshot(nodes=_canonical_nodes(), receipts=())
    budget = {**snapshot.budget, "accounted_cost_usd": Decimal("2"),
              "policy_snapshot": {**snapshot.budget["policy_snapshot"],
                  "cost_limit_usd": "2", "account_entitlement_lane": {"currency": "UNKNOWN"}}}
    usage = _budget_usage(opening=snapshot.opening, budget=budget, observed_at=NOW)
    assert usage["cost_usd"]["used"] is None
    assert usage["cost_usd"]["status"] == "UNKNOWN"
    assert usage["cost_usd"]["priced_lane_used"] == "2"
    assert "COST_LIMIT_REACHED" in usage["exhaustion_reasons"]
