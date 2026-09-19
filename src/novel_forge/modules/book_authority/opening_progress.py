from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_authority.opening_workflow import (
    BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
    BookOpeningWorkflowNodeKind,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


BOOK_OPENING_WORKFLOW_PROGRESS_SCHEMA_VERSION = (
    "novel-forge.book-opening-workflow-progress.v1"
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class BookOpeningWorkflowProgressSnapshot:
    opening: Mapping[str, Any]
    nodes: tuple[Mapping[str, Any], ...]
    receipts: tuple[Mapping[str, Any], ...]
    execution: Mapping[str, Any] | None
    budget: Mapping[str, Any]
    legacy_checkpoint: Mapping[str, Any] | None
    observed_at: datetime
    current_checkpoint: Mapping[str, Any] | None = None
    edges: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class BookOpeningWorkflowProgressProjection:
    schema_version: str
    opening_run_id: str
    project_id: str
    workspace_id: str
    book_id: str
    opening_lifecycle: str
    workflow_contract_version: str
    workflow_graph_revision: int
    workflow_graph_hash: str
    compatibility_mode: str
    progress_status: str
    current_layer: Mapping[str, Any] | None
    furthest_completed_layer: Mapping[str, Any] | None
    nodes: tuple[Mapping[str, Any], ...]
    reviewable_artifact: Mapping[str, Any]
    persistent_checkpoint: Mapping[str, Any]
    current_execution_checkpoint: Mapping[str, Any]
    blocking_reason: Mapping[str, Any]
    runtime_fence: Mapping[str, Any]
    budget_usage: Mapping[str, Any]
    observed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


_EXPECTED_WORKFLOW_NODES = (
    (1, BookOpeningWorkflowNodeKind.BOOK_PLAN.value, "book-plan"),
    (2, BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO.value, "volume-portfolio"),
    (3, BookOpeningWorkflowNodeKind.CURRENT_VOLUME.value, "current-volume"),
    (4, BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE.value, "initial-arc-scope"),
    (5, BookOpeningWorkflowNodeKind.INPUT_SNAPSHOT.value, "input-snapshot"),
)


def _workflow_graph_problem(
    *,
    opening: Mapping[str, Any],
    ordered_nodes: tuple[Mapping[str, Any], ...],
    edges: tuple[Mapping[str, Any], ...],
) -> str:

    contract_version = str(opening.get("workflow_contract_version") or "")
    if contract_version != BOOK_OPENING_WORKFLOW_CONTRACT_VERSION:
        return "WORKFLOW_CONTRACT_VERSION_MISMATCH"
    graph_revision = _safe_int(opening.get("workflow_graph_revision"))
    if graph_revision != 1:
        return "WORKFLOW_GRAPH_REVISION_MISMATCH"
    if not ordered_nodes:
        return "WORKFLOW_NODES_MISSING"
    if len(ordered_nodes) != len(_EXPECTED_WORKFLOW_NODES):
        return "WORKFLOW_NODE_CARDINALITY_MISMATCH"

    opening_run_id = str(opening.get("opening_run_id") or "")
    node_ids: list[str] = []
    for node, expected in zip(ordered_nodes, _EXPECTED_WORKFLOW_NODES, strict=True):
        ordinal, node_kind, node_key = expected
        node_id = str(node.get("workflow_node_id") or "")
        if (
            not node_id
            or _safe_int(node.get("ordinal")) != ordinal
            or str(node.get("node_kind") or "") != node_kind
            or str(node.get("node_key") or "") != node_key
        ):
            return "WORKFLOW_NODE_DEFINITION_MISMATCH"
        node_opening_run_id = str(node.get("opening_run_id") or "")
        if node_opening_run_id and node_opening_run_id != opening_run_id:
            return "WORKFLOW_NODE_OWNER_MISMATCH"
        if _safe_int(node.get("graph_revision")) != graph_revision:
            return "WORKFLOW_NODE_GRAPH_REVISION_MISMATCH"
        if not _is_sha256(node.get("input_hash")):
            return "WORKFLOW_NODE_INPUT_HASH_INVALID"
        node_ids.append(node_id)
    if len(set(node_ids)) != len(node_ids):
        return "WORKFLOW_NODE_IDENTITY_DUPLICATE"

    current_node_id = str(opening.get("current_workflow_node_id") or "")
    if current_node_id not in node_ids:
        return "WORKFLOW_CURRENT_NODE_NOT_IN_GRAPH"

    expected_edges = tuple(
        (node_ids[index], node_ids[index + 1], "REQUIRES")
        for index in range(len(node_ids) - 1)
    )
    observed_edges: list[tuple[str, str, str]] = []
    for edge in edges:
        edge_opening_run_id = str(edge.get("opening_run_id") or "")
        if edge_opening_run_id and edge_opening_run_id != opening_run_id:
            return "WORKFLOW_EDGE_OWNER_MISMATCH"
        observed_edges.append(
            (
                str(edge.get("predecessor_workflow_node_id") or ""),
                str(edge.get("successor_workflow_node_id") or ""),
                str(edge.get("edge_kind") or ""),
            )
        )
    if len(observed_edges) != len(expected_edges) or set(observed_edges) != set(
        expected_edges
    ):
        return "WORKFLOW_EDGE_SET_MISMATCH"

    expected_hash = _canonical_hash(
        {
            "contract_version": contract_version,
            "graph_revision": graph_revision,
            "nodes": [
                {
                    "input_hash": str(node.get("input_hash") or ""),
                    "kind": str(node.get("node_kind") or ""),
                    "node_key": str(node.get("node_key") or ""),
                    "ordinal": _safe_int(node.get("ordinal")),
                    "workflow_node_id": str(node.get("workflow_node_id") or ""),
                }
                for node in ordered_nodes
            ],
            "edges": [
                {
                    "child_node_id": child_id,
                    "parent_node_id": parent_id,
                    "relation": relation,
                }
                for parent_id, child_id, relation in expected_edges
            ],
        }
    )
    observed_hash = str(opening.get("workflow_graph_hash") or "")
    if observed_hash != expected_hash:
        return "WORKFLOW_GRAPH_HASH_MISMATCH"
    return ""


def project_book_opening_workflow_progress(
    snapshot: BookOpeningWorkflowProgressSnapshot,
) -> BookOpeningWorkflowProgressProjection:

    opening = dict(snapshot.opening)
    if str(opening.get("workflow_contract_version") or "") == ("legacy-monolithic-v2"):
        return _project_legacy_monolithic(snapshot)
    project_id = str(opening.get("project_id") or "")
    ordered_nodes = tuple(
        sorted(
            snapshot.nodes,
            key=lambda item: (
                _safe_int(item.get("ordinal")),
                str(item.get("workflow_node_id") or ""),
            ),
        )
    )
    graph_problem = _workflow_graph_problem(
        opening=opening,
        ordered_nodes=ordered_nodes,
        edges=snapshot.edges,
    )
    receipts_by_node: dict[str, list[Mapping[str, Any]]] = {}
    for receipt in snapshot.receipts:
        receipts_by_node.setdefault(str(receipt["workflow_node_id"]), []).append(
            receipt
        )

    node_reports: list[dict[str, Any]] = []
    completed_prefix = True
    furthest_node: dict[str, Any] | None = None
    furthest_receipt: Mapping[str, Any] | None = None
    current_node_id = str(opening.get("current_workflow_node_id") or "")
    for raw_node in ordered_nodes:
        node = dict(raw_node)
        node_id = str(node.get("workflow_node_id") or "")
        candidates = receipts_by_node.get(node_id, [])
        receipt = candidates[0] if len(candidates) == 1 else None
        receipt_valid, invalid_reason = _validate_receipt(
            node=node,
            receipt=receipt,
            receipt_count=len(candidates),
            project_id=project_id,
        )
        if receipt_valid and not completed_prefix:
            receipt_valid = False
            invalid_reason = "NON_CONTIGUOUS_NODE_RECEIPT"
        complete = completed_prefix and receipt_valid
        if complete:
            lifecycle = "COMPLETE"
        elif invalid_reason:
            lifecycle = "INCONSISTENT"
        elif node_id == current_node_id:
            lifecycle = _active_node_lifecycle(snapshot.execution)
        else:
            lifecycle = "PENDING"
        if complete:
            furthest_node = node
            furthest_receipt = receipt
        else:
            completed_prefix = False
        node_reports.append(
            {
                "workflow_node_id": node_id,
                "node_key": str(node.get("node_key") or ""),
                "node_kind": str(node.get("node_kind") or ""),
                "ordinal": _safe_int(node.get("ordinal")),
                "lifecycle": lifecycle,
                "input_hash": str(node.get("input_hash") or ""),
                "graph_revision": int(node.get("graph_revision") or 0),
                "node_receipt_id": (
                    str(receipt.get("node_receipt_id") or "") if receipt else ""
                ),
                "evidence_status": (
                    "VALID" if complete else "INVALID" if invalid_reason else "PENDING"
                ),
                "evidence_problem": invalid_reason,
                "reviewable_artifact": _reviewable_artifact(
                    receipt,
                    evidence_problem=invalid_reason,
                ),
                "persistent_checkpoint": _persistent_checkpoint(
                    receipt,
                    evidence_problem=invalid_reason,
                ),
            }
        )

    current_report = next(
        (item for item in node_reports if item["lifecycle"] != "COMPLETE"),
        None,
    )
    furthest_report = (
        next(
            item
            for item in node_reports
            if item["workflow_node_id"] == str(furthest_node["workflow_node_id"])
        )
        if furthest_node is not None
        else None
    )
    selected_receipt = None
    selected_problem = ""
    if current_report is not None:
        current_receipts = receipts_by_node.get(
            str(current_report["workflow_node_id"]), []
        )
        if len(current_receipts) == 1:
            selected_receipt = current_receipts[0]
            selected_problem = str(current_report.get("evidence_problem") or "")
    if selected_receipt is None:
        selected_receipt = furthest_receipt

    budget_usage = _budget_usage(
        opening=opening,
        budget=snapshot.budget,
        observed_at=snapshot.observed_at,
    )
    blocking = _blocking_reason(
        opening=opening,
        node_reports=tuple(node_reports),
        execution=snapshot.execution,
        observed_at=snapshot.observed_at,
    )
    if graph_problem:
        blocking = {
            "is_blocked": True,
            "blocking_class": "AUTHORITY_EVIDENCE_INCONSISTENT",
            "code": "BOOK_OPENING_WORKFLOW_GRAPH_INVALID",
            "reason": graph_problem,
            "retryable": False,
            "wake_condition": "RECONCILE_AUTHORITY_EVIDENCE",
        }
    runtime_fence = _opening_runtime_fence(
        opening=opening,
        execution=snapshot.execution,
        observed_at=snapshot.observed_at,
    )
    if runtime_fence["status"] == "INVALID" and not blocking["is_blocked"]:
        blocking = {
            "is_blocked": True,
            "blocking_class": "EXECUTION_LOST",
            "code": "BOOK_OPENING_EXECUTION_FENCE_INVALID",
            "reason": "RUNNING Book Opening has no valid current RuntimeJob Lease fence",
            "retryable": False,
            "wake_condition": "CONVERGE_EXECUTION_LOSS",
        }
    if not blocking["is_blocked"]:
        blocking = _budget_blocking_reason(budget_usage)

    if graph_problem or any(
        item["lifecycle"] == "INCONSISTENT" for item in node_reports
    ):
        progress_status = "INCONSISTENT"
    elif not current_report:
        progress_status = "COMPLETE"
    elif blocking["is_blocked"]:
        progress_status = "BLOCKED"
    else:
        progress_status = str(current_report["lifecycle"])

    return BookOpeningWorkflowProgressProjection(
        schema_version=BOOK_OPENING_WORKFLOW_PROGRESS_SCHEMA_VERSION,
        opening_run_id=str(opening.get("opening_run_id") or ""),
        project_id=project_id,
        workspace_id=str(opening.get("workspace_id") or ""),
        book_id=str(opening.get("book_id") or ""),
        opening_lifecycle=str(opening.get("lifecycle") or ""),
        workflow_contract_version=str(opening.get("workflow_contract_version") or ""),
        workflow_graph_revision=int(opening.get("workflow_graph_revision") or 0),
        workflow_graph_hash=str(opening.get("workflow_graph_hash") or ""),
        compatibility_mode="NODED_WORKFLOW",
        progress_status=progress_status,
        current_layer=_layer_summary(current_report),
        furthest_completed_layer=_layer_summary(furthest_report),
        nodes=tuple(node_reports),
        reviewable_artifact=_reviewable_artifact(
            selected_receipt,
            evidence_problem=selected_problem,
        ),
        persistent_checkpoint=_persistent_checkpoint(
            selected_receipt,
            evidence_problem=selected_problem,
        ),
        current_execution_checkpoint=_current_execution_checkpoint(
            opening=opening,
            checkpoint=snapshot.current_checkpoint,
        ),
        blocking_reason=blocking,
        runtime_fence=runtime_fence,
        budget_usage=budget_usage,
        observed_at=snapshot.observed_at,
    )


def _project_legacy_monolithic(
    snapshot: BookOpeningWorkflowProgressSnapshot,
) -> BookOpeningWorkflowProgressProjection:
    opening = dict(snapshot.opening)
    execution = snapshot.execution
    lifecycle = str(opening.get("lifecycle") or "")
    if lifecycle == "COMPLETE":
        node_lifecycle = "COMPLETE"
        progress_status = "COMPLETE"
    elif lifecycle in {"FAILED", "ABORTED"}:
        node_lifecycle = "BLOCKED"
        progress_status = "BLOCKED"
    else:
        node_lifecycle = _active_node_lifecycle(execution)
        progress_status = node_lifecycle
    node = {
        "workflow_node_id": "",
        "node_kind": "LEGACY_MONOLITHIC",
        "node_key": "legacy:book-opening-execution-v2",
        "ordinal": 1,
        "lifecycle": node_lifecycle,
    }
    checkpoint = dict(snapshot.legacy_checkpoint or {})
    checkpoint_matches = bool(checkpoint) and (
        str(checkpoint.get("checkpoint_id") or "")
        == str(opening.get("current_checkpoint_id") or "")
        and int(checkpoint.get("checkpoint_sequence") or 0)
        == int(opening.get("current_checkpoint_sequence") or 0)
        and str(checkpoint.get("checkpoint_hash") or "")
        == str(opening.get("current_checkpoint_hash") or "")
    )
    if checkpoint_matches:
        checkpoint_report = {
            "status": "AVAILABLE_LEGACY",
            "source_workflow_node_id": "",
            "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
            "checkpoint_sequence": int(checkpoint.get("checkpoint_sequence") or 0),
            "checkpoint_hash": str(checkpoint.get("checkpoint_hash") or ""),
            "authoritative_evidence_hash": str(
                checkpoint.get("authoritative_evidence_hash") or ""
            ),
            "semantic_work_key": str(checkpoint.get("semantic_work_key") or ""),
        }
    else:
        checkpoint_report = {
            "status": "NOT_FORMED",
            "source_workflow_node_id": "",
            "checkpoint_id": "",
            "checkpoint_sequence": 0,
            "checkpoint_hash": "",
            "authoritative_evidence_hash": "",
            "semantic_work_key": "",
        }
    budget_usage = _budget_usage(
        opening=opening,
        budget=snapshot.budget,
        observed_at=snapshot.observed_at,
    )
    blocking = _blocking_reason(
        opening=opening,
        node_reports=(),
        execution=execution,
        observed_at=snapshot.observed_at,
    )
    runtime_fence = _opening_runtime_fence(
        opening=opening,
        execution=execution,
        observed_at=snapshot.observed_at,
    )
    if runtime_fence["status"] == "INVALID" and not blocking["is_blocked"]:
        blocking = {
            "is_blocked": True,
            "blocking_class": "EXECUTION_LOST",
            "code": "BOOK_OPENING_EXECUTION_FENCE_INVALID",
            "reason": "RUNNING Book Opening has no valid current RuntimeJob Lease fence",
            "retryable": False,
            "wake_condition": "CONVERGE_EXECUTION_LOSS",
        }
        progress_status = "BLOCKED"
    if not blocking["is_blocked"]:
        blocking = _budget_blocking_reason(budget_usage)
        if blocking["is_blocked"]:
            progress_status = "BLOCKED"
    return BookOpeningWorkflowProgressProjection(
        schema_version=BOOK_OPENING_WORKFLOW_PROGRESS_SCHEMA_VERSION,
        opening_run_id=str(opening.get("opening_run_id") or ""),
        project_id=str(opening.get("project_id") or ""),
        workspace_id=str(opening.get("workspace_id") or ""),
        book_id=str(opening.get("book_id") or ""),
        opening_lifecycle=lifecycle,
        workflow_contract_version=str(opening.get("workflow_contract_version") or ""),
        workflow_graph_revision=int(opening.get("workflow_graph_revision") or 0),
        workflow_graph_hash=str(opening.get("workflow_graph_hash") or ""),
        compatibility_mode="LEGACY_MONOLITHIC",
        progress_status=progress_status,
        current_layer=node,
        furthest_completed_layer=node if node_lifecycle == "COMPLETE" else None,
        nodes=(node,),
        reviewable_artifact={
            "status": "UNAVAILABLE_LEGACY",
            "source_workflow_node_id": "",
            "node_receipt_id": "",
            "artifact_kind": "",
            "asset_versions": [],
            "artifact_reference": {},
        },
        persistent_checkpoint=checkpoint_report,
        current_execution_checkpoint=_current_execution_checkpoint(
            opening=opening,
            checkpoint=snapshot.current_checkpoint or snapshot.legacy_checkpoint,
        ),
        blocking_reason=blocking,
        runtime_fence=runtime_fence,
        budget_usage=budget_usage,
        observed_at=snapshot.observed_at,
    )


def _layer_summary(node: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if node is None:
        return None
    return {
        "workflow_node_id": str(node["workflow_node_id"]),
        "node_kind": str(node["node_kind"]),
        "node_key": str(node["node_key"]),
        "ordinal": int(node["ordinal"]),
        "lifecycle": str(node["lifecycle"]),
    }


def _validate_receipt(
    *,
    node: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    receipt_count: int,
    project_id: str,
) -> tuple[bool, str]:
    if receipt_count == 0:
        return False, ""
    if receipt_count != 1 or receipt is None:
        return False, "DUPLICATE_NODE_RECEIPT"
    node_id = str(node["workflow_node_id"])
    if (
        _canonical_hash(dict(receipt.get("result") or {}))
        != str(receipt.get("result_hash") or "")
        or str(receipt.get("checkpoint_workflow_node_id") or "") != node_id
        or str(receipt.get("checkpoint_id") or "") == ""
        or int(receipt.get("checkpoint_sequence") or 0) <= 0
        or not _is_sha256(receipt.get("checkpoint_hash"))
        or str(receipt.get("checkpoint_opening_execution_id") or "")
        != str(receipt.get("opening_execution_id") or "")
        or int(receipt.get("checkpoint_execution_generation") or 0)
        != int(receipt.get("execution_generation") or 0)
        or str(receipt.get("checkpoint_evidence_hash") or "")
        != str(receipt.get("authoritative_evidence_hash") or "")
        or str(receipt.get("authoritative_checkpoint_id") or "")
        != str(receipt.get("checkpoint_id") or "")
        or int(receipt.get("authoritative_checkpoint_sequence") or 0)
        != int(receipt.get("checkpoint_sequence") or 0)
        or str(receipt.get("authoritative_checkpoint_hash") or "")
        != str(receipt.get("checkpoint_hash") or "")
    ):
        return False, "CHECKPOINT_AUTHORITY_MISMATCH"

    requested = tuple(
        str(item) for item in receipt.get("requested_asset_version_ids") or ()
    )
    artifacts = tuple(dict(item) for item in receipt.get("authoritative_assets") or ())
    actual_ids = tuple(str(item.get("asset_version_id") or "") for item in artifacts)
    artifact_kind = str(receipt.get("reviewable_artifact_kind") or "")
    expected_kind, minimum_assets, maximum_assets = {
        "BOOK_PLAN": ("BOOK_PLAN", 1, 1),
        "VOLUME_PORTFOLIO": ("VOLUME_PORTFOLIO", 1, None),
        "CURRENT_VOLUME": ("CURRENT_VOLUME_PLAN", 1, 1),
        "INITIAL_ARC_SCOPE": ("INITIAL_ARC_SCOPE", 1, None),
        "INPUT_SNAPSHOT": ("BOOK_PRODUCTION_INPUT_SNAPSHOT", 0, 0),
    }.get(str(node.get("node_kind") or ""), ("", 1, 0))
    if (
        artifact_kind != expected_kind
        or len(requested) < minimum_assets
        or (maximum_assets is not None and len(requested) > maximum_assets)
        or requested != actual_ids
        or any(
            str(item.get("project_id") or "") != project_id
            or not _is_sha256(item.get("content_hash"))
            for item in artifacts
        )
    ):
        return False, "REVIEWABLE_ASSET_AUTHORITY_MISMATCH"
    if str(node.get("node_kind") or "") == "INPUT_SNAPSHOT":
        result = dict(receipt.get("result") or {})
        snapshot = dict(receipt.get("authoritative_snapshot") or {})
        if (
            str(result.get("snapshot_id") or "") == ""
            or str(result.get("snapshot_id") or "")
            != str(snapshot.get("snapshot_id") or "")
            or str(result.get("snapshot_hash") or "")
            != str(snapshot.get("snapshot_hash") or "")
            or str(snapshot.get("project_id") or "") != project_id
        ):
            return False, "REVIEWABLE_SNAPSHOT_AUTHORITY_MISMATCH"
    return True, ""


def _active_node_lifecycle(execution: Mapping[str, Any] | None) -> str:
    if not execution:
        return "READY"
    lifecycle = str(execution.get("execution_lifecycle") or "")
    if lifecycle == "SCHEDULED":
        return "QUEUED"
    if lifecycle in {"BOUND", "RUNNING"}:
        return "RUNNING"
    if lifecycle == "SUCCEEDED":
        return "CHECKPOINT_PENDING"
    if lifecycle in {"FAILED", "LOST", "ABORTED"}:
        return "BLOCKED"
    return "READY"


def _reviewable_artifact(
    receipt: Mapping[str, Any] | None, *, evidence_problem: str = ""
) -> dict[str, Any]:
    if receipt is None:
        return {
            "status": "NOT_FORMED",
            "source_workflow_node_id": "",
            "node_receipt_id": "",
            "artifact_kind": "",
            "asset_versions": [],
            "artifact_reference": {},
        }
    assets = [
        {
            "asset_version_id": str(item.get("asset_version_id") or ""),
            "asset_id": str(item.get("asset_id") or ""),
            "asset_type": str(item.get("asset_type") or ""),
            "content_hash": str(item.get("content_hash") or ""),
            "lifecycle": str(item.get("lifecycle") or ""),
            "eligibility": str(item.get("eligibility") or ""),
        }
        for item in receipt.get("authoritative_assets") or ()
    ]
    artifact_kind = str(receipt.get("reviewable_artifact_kind") or "")
    result = dict(receipt.get("result") or {})
    artifact_reference = (
        {
            "reference_type": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
            "snapshot_id": str(result.get("snapshot_id") or ""),
            "snapshot_hash": str(result.get("snapshot_hash") or ""),
        }
        if artifact_kind == "BOOK_PRODUCTION_INPUT_SNAPSHOT"
        else {
            "reference_type": "AUTHORITY_ASSET_VERSION_SET",
            "asset_version_ids": [
                str(item.get("asset_version_id") or "") for item in assets
            ],
        }
    )
    if evidence_problem in {
        "REVIEWABLE_ASSET_AUTHORITY_MISMATCH",
        "REVIEWABLE_SNAPSHOT_AUTHORITY_MISMATCH",
    }:
        return {
            "status": "INVALID",
            "source_workflow_node_id": str(receipt.get("workflow_node_id") or ""),
            "node_receipt_id": str(receipt.get("node_receipt_id") or ""),
            "artifact_kind": artifact_kind,
            "asset_versions": assets,
            "artifact_reference": artifact_reference,
            "evidence_problem": evidence_problem,
        }
    return {
        "status": "NOT_REQUIRED" if artifact_kind == "NOT_REQUIRED" else "AVAILABLE",
        "source_workflow_node_id": str(receipt.get("workflow_node_id") or ""),
        "node_receipt_id": str(receipt.get("node_receipt_id") or ""),
        "artifact_kind": artifact_kind,
        "asset_versions": assets,
        "artifact_reference": artifact_reference,
    }


def _current_execution_checkpoint(
    *,
    opening: Mapping[str, Any],
    checkpoint: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if checkpoint is None:
        return {
            "status": "NOT_FORMED",
            "workflow_node_id": "",
            "checkpoint_id": "",
            "checkpoint_sequence": 0,
            "checkpoint_hash": "",
            "semantic_work_key": "",
            "evidence_type": "",
            "evidence_id": "",
            "evidence_hash": "",
            "layer_completion": False,
        }
    exact_head = (
        str(checkpoint.get("checkpoint_id") or "")
        == str(opening.get("current_checkpoint_id") or "")
        and int(checkpoint.get("checkpoint_sequence") or 0)
        == int(opening.get("current_checkpoint_sequence") or 0)
        and str(checkpoint.get("checkpoint_hash") or "")
        == str(opening.get("current_checkpoint_hash") or "")
    )
    return {
        "status": "AVAILABLE" if exact_head else "INVALID",
        "workflow_node_id": str(checkpoint.get("workflow_node_id") or ""),
        "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
        "checkpoint_sequence": int(checkpoint.get("checkpoint_sequence") or 0),
        "checkpoint_hash": str(checkpoint.get("checkpoint_hash") or ""),
        "semantic_work_key": str(checkpoint.get("semantic_work_key") or ""),
        "evidence_type": str(checkpoint.get("evidence_type") or ""),
        "evidence_id": str(checkpoint.get("evidence_id") or ""),
        "evidence_hash": str(checkpoint.get("evidence_hash") or ""),
        "layer_completion": (
            str(checkpoint.get("evidence_type") or "") == "BOOK_OPENING_NODE_RECEIPT"
        ),
    }


def _persistent_checkpoint(
    receipt: Mapping[str, Any] | None, *, evidence_problem: str = ""
) -> dict[str, Any]:
    if receipt is None:
        return {
            "status": "NOT_FORMED",
            "source_workflow_node_id": "",
            "checkpoint_id": "",
            "checkpoint_sequence": 0,
            "checkpoint_hash": "",
            "authoritative_evidence_hash": "",
        }
    invalid = evidence_problem == "CHECKPOINT_AUTHORITY_MISMATCH"
    value = {
        "status": "INVALID" if invalid else "AVAILABLE",
        "source_workflow_node_id": str(receipt.get("workflow_node_id") or ""),
        "checkpoint_id": str(receipt.get("checkpoint_id") or ""),
        "checkpoint_sequence": int(receipt.get("checkpoint_sequence") or 0),
        "checkpoint_hash": str(receipt.get("checkpoint_hash") or ""),
        "authoritative_evidence_hash": str(
            receipt.get("authoritative_evidence_hash") or ""
        ),
    }
    if invalid:
        value["evidence_problem"] = evidence_problem
    return value


def _runtime_fence(
    execution: Mapping[str, Any] | None, observed_at: datetime
) -> dict[str, Any]:
    if not execution or str(execution.get("execution_lifecycle") or "") not in {
        "BOUND",
        "RUNNING",
    }:
        return {
            "status": "NOT_REQUIRED",
            "runtime_job_id": str((execution or {}).get("runtime_job_id") or ""),
            "runtime_job_status": str(
                (execution or {}).get("runtime_job_status") or ""
            ),
            "attempt_id": "",
            "attempt_status": "",
            "lease_id": "",
            "lease_status": "",
            "worker_id": "",
            "fencing_token": None,
            "required_fencing_token": None,
            "observed_fencing_token": None,
            "lease_expires_at": None,
        }
    lease_expires_at = execution.get("lease_expires_at")
    runtime_job_id = str(execution.get("runtime_job_id") or "")
    attempt_id = str(execution.get("attempt_id") or "")
    lease_id = str(execution.get("lease_id") or "")
    worker_id = str(execution.get("worker_id") or "")
    fencing_token = int(execution.get("fencing_token") or 0)
    required_attempt_id = str(execution.get("execution_current_attempt_id") or "")
    required_lease_id = str(execution.get("execution_current_lease_id") or "")
    required_worker_id = str(execution.get("execution_current_worker_id") or "")
    required_fencing_token = int(execution.get("execution_current_fencing_token") or 0)
    valid = (
        str(execution.get("runtime_job_status") or "")
        in {"CLAIMED", "RUNNING", "CHECKPOINTED"}
        and str(execution.get("attempt_status") or "")
        in {"CLAIMED", "RUNNING", "CHECKPOINTED"}
        and str(execution.get("lease_status") or "") == "HELD"
        and isinstance(lease_expires_at, datetime)
        and lease_expires_at > observed_at
        and fencing_token > 0
        and runtime_job_id != ""
        and attempt_id != ""
        and lease_id != ""
        and worker_id != ""
        and required_attempt_id == attempt_id
        and required_lease_id == lease_id
        and required_worker_id == worker_id
        and required_fencing_token == fencing_token
        and str(execution.get("job_current_attempt_id") or "") == attempt_id
        and str(execution.get("job_claimed_by") or "") == worker_id
        and int(execution.get("job_current_fencing_token") or 0) == fencing_token
        and str(execution.get("attempt_runtime_job_id") or "") == runtime_job_id
        and str(execution.get("attempt_lease_id") or "") == lease_id
        and str(execution.get("attempt_worker_id") or "") == worker_id
        and int(execution.get("attempt_fencing_token") or 0) == fencing_token
        and str(execution.get("lease_runtime_job_id") or "") == runtime_job_id
        and str(execution.get("lease_attempt_id") or "") == attempt_id
        and str(execution.get("lease_worker_id") or "") == worker_id
        and int(execution.get("lease_fencing_token") or 0) == fencing_token
    )
    return {
        "status": "VALID" if valid else "INVALID",
        "runtime_job_id": runtime_job_id,
        "runtime_job_status": str(execution.get("runtime_job_status") or ""),
        "attempt_id": attempt_id,
        "attempt_status": str(execution.get("attempt_status") or ""),
        "lease_id": lease_id,
        "lease_status": str(execution.get("lease_status") or ""),
        "worker_id": worker_id,
        "fencing_token": fencing_token or None,
        "required_fencing_token": required_fencing_token or None,
        "observed_fencing_token": fencing_token or None,
        "lease_expires_at": lease_expires_at,
    }


def _opening_runtime_fence(
    *,
    opening: Mapping[str, Any],
    execution: Mapping[str, Any] | None,
    observed_at: datetime,
) -> dict[str, Any]:
    fence = _runtime_fence(execution, observed_at)
    opening_lifecycle = str(opening.get("lifecycle") or "")
    execution_lifecycle = str((execution or {}).get("execution_lifecycle") or "")
    if opening_lifecycle == "ADMITTED":
        if execution_lifecycle == "SCHEDULED" and fence["status"] == "NOT_REQUIRED":
            return {**fence, "execution_phase": "QUEUED"}
        if execution_lifecycle == "BOUND" and fence["status"] == "VALID":
            return {**fence, "execution_phase": "CLAIMED"}
        return {**fence, "status": "INVALID", "execution_phase": "INVALID"}
    if opening_lifecycle == "RUNNING":
        if execution_lifecycle == "RUNNING" and fence["status"] == "VALID":
            return {**fence, "execution_phase": "RUNNING"}
        return {**fence, "status": "INVALID", "execution_phase": "INVALID"}
    if opening_lifecycle == "COMPLETE" and execution_lifecycle == "SUCCEEDED":
        return {**fence, "execution_phase": "COMPLETED"}
    if opening_lifecycle in {"FAILED", "ABORTED"}:
        return {**fence, "execution_phase": "TERMINAL"}
    return {**fence, "status": "INVALID", "execution_phase": "INVALID"}


def _blocking_reason(
    *,
    opening: Mapping[str, Any],
    node_reports: tuple[Mapping[str, Any], ...],
    execution: Mapping[str, Any] | None,
    observed_at: datetime,
) -> dict[str, Any]:
    inconsistent = next(
        (item for item in node_reports if item["lifecycle"] == "INCONSISTENT"),
        None,
    )
    if inconsistent is not None:
        return {
            "is_blocked": True,
            "blocking_class": "AUTHORITY_EVIDENCE_INCONSISTENT",
            "code": "BOOK_OPENING_NODE_RECEIPT_INVALID",
            "reason": str(inconsistent["evidence_problem"]),
            "retryable": False,
            "wake_condition": "RECONCILE_AUTHORITY_EVIDENCE",
        }
    lifecycle = str(opening.get("lifecycle") or "")
    if lifecycle in {"FAILED", "ABORTED"}:
        failure = dict(opening.get("failure") or {})
        return {
            "is_blocked": True,
            "blocking_class": "OPENING_TERMINAL",
            "code": str(failure.get("code") or f"BOOK_OPENING_{lifecycle}"),
            "reason": str(failure.get("message") or failure.get("reason") or lifecycle),
            "retryable": False,
            "wake_condition": str(
                dict(opening.get("recovery_instruction") or {}).get("action") or "NONE"
            ),
        }
    execution_lifecycle = str((execution or {}).get("execution_lifecycle") or "")
    if execution_lifecycle in {"FAILED", "LOST", "ABORTED"}:
        return {
            "is_blocked": True,
            "blocking_class": "EXECUTION_LOST",
            "code": "BOOK_OPENING_EXECUTION_TERMINAL_WITHOUT_CHECKPOINT",
            "reason": execution_lifecycle,
            "retryable": False,
            "wake_condition": "CONVERGE_EXECUTION_LOSS",
        }
    runtime_job_status = str((execution or {}).get("runtime_job_status") or "")
    if execution_lifecycle == "SCHEDULED" and runtime_job_status in {
        "SUCCEEDED",
        "FAILED",
        "DEAD_LETTER",
        "CANCELLED",
    }:
        return {
            "is_blocked": True,
            "blocking_class": "EXECUTION_LOST",
            "code": "BOOK_OPENING_RUNTIME_JOB_TERMINAL_WITHOUT_CHECKPOINT",
            "reason": runtime_job_status,
            "retryable": False,
            "wake_condition": "CONVERGE_EXECUTION_LOSS",
        }
    return {
        "is_blocked": False,
        "blocking_class": "NONE",
        "code": "",
        "reason": "",
        "retryable": False,
        "wake_condition": "",
    }


def _budget_usage(
    *, opening: Mapping[str, Any], budget: Mapping[str, Any], observed_at: datetime
) -> dict[str, Any]:
    policy = dict(budget.get("policy_snapshot") or {})
    deadline = budget.get("deadline_at")
    accounting_basis = str(policy.get("accounting_basis") or "PRICED").upper()
    cost_observable = accounting_basis != "ACCOUNT_ENTITLEMENT" and not policy.get("account_entitlement_lane")
    cost = (
        Decimal(str(budget.get("accounted_cost_usd") or "0"))
        if accounting_basis != "ACCOUNT_ENTITLEMENT"
        else None
    )
    settled_cost = (
        Decimal(str(budget.get("settled_cost_usd") or "0")) if accounting_basis != "ACCOUNT_ENTITLEMENT" else None
    )
    contract_state = str(opening.get("budget_contract_state") or "UNBOUND")
    expected_scope_id = str(opening.get("budget_scope_id") or "")
    expected_scope_revision = int(opening.get("budget_scope_revision") or 0)
    observed_scope_id = str(budget.get("budget_scope_id") or "")
    observed_scope_revision = int(budget.get("budget_scope_revision") or 0)
    authority_binding_valid = (
        contract_state == "BOUND"
        and expected_scope_id != ""
        and expected_scope_revision > 0
        and observed_scope_id == expected_scope_id
        and observed_scope_revision == expected_scope_revision
    )
    call_limit = int(policy.get("provider_call_limit") or 0)
    token_limit = int(policy.get("token_limit") or 0)
    cost_limit = (
        Decimal(str(policy.get("cost_limit_usd") or "0")) if accounting_basis != "ACCOUNT_ENTITLEMENT" else None
    )
    committed_calls = int(budget.get("committed_call_count") or 0)
    accounted_tokens = int(budget.get("accounted_tokens") or 0)
    deadline_exceeded = isinstance(deadline, datetime) and observed_at >= deadline
    exhaustion_reasons: list[str] = []
    if int(budget.get("budget_breach_count") or 0) > 0:
        exhaustion_reasons.append("BUDGET_BREACH_RECORDED")
    if call_limit > 0 and committed_calls >= call_limit:
        exhaustion_reasons.append("PROVIDER_CALL_LIMIT_REACHED")
    if token_limit > 0 and accounted_tokens >= token_limit:
        exhaustion_reasons.append("TOKEN_LIMIT_REACHED")
    if (
        cost_limit is not None
        and cost is not None
        and cost_limit > 0
        and cost >= cost_limit
    ):
        exhaustion_reasons.append("COST_LIMIT_REACHED")
    if deadline_exceeded:
        exhaustion_reasons.append("DEADLINE_REACHED")
    status = (
        "RECONCILIATION_REQUIRED"
        if not authority_binding_valid
        else "EXHAUSTED"
        if exhaustion_reasons
        else "OPEN"
    )
    return {
        "status": status,
        "contract_state": contract_state,
        "authority_binding_status": "VALID" if authority_binding_valid else "INVALID",
        "authority_binding_problem": (
            ""
            if authority_binding_valid
            else "BUDGET_SCOPE_AUTHORITY_MISSING_OR_MISMATCH"
            if contract_state == "BOUND"
            else f"BUDGET_CONTRACT_{contract_state}"
        ),
        "budget_scope_id": expected_scope_id,
        "budget_scope_revision": expected_scope_revision,
        "observed_budget_scope_id": observed_scope_id,
        "observed_budget_scope_revision": observed_scope_revision,
        "provider_calls": {
            "used": committed_calls,
            "settled": int(budget.get("settled_call_count") or 0),
            "held_unknown": int(budget.get("held_unknown_call_count") or 0),
            "reserved": int(budget.get("reserved_call_count") or 0),
            "limit": call_limit,
        },
        "tokens": {
            "used": accounted_tokens,
            "actual": int(budget.get("actual_tokens") or 0),
            "limit": token_limit,
        },
        "cost_usd": {
            "used": _decimal_text(cost) if cost_observable and cost is not None else None,
            "settled": (
                _decimal_text(settled_cost) if cost_observable and settled_cost is not None else None
            ),
            "limit": _decimal_text(cost_limit) if cost_observable and cost_limit is not None else None,
            "status": "KNOWN" if cost_observable else "UNKNOWN",
            "accounting_basis": accounting_basis,
            **({"priced_lane_used": _decimal_text(Decimal(str(budget.get("accounted_cost_usd") or "0"))),
                "priced_lane_limit": str(policy["cost_limit_usd"]),
                "account_entitlement_cost_status": "UNKNOWN"}
               if policy.get("account_entitlement_lane") else {}),
        },
        "reservation_count": int(budget.get("reservation_count") or 0),
        "budget_breach_count": int(budget.get("budget_breach_count") or 0),
        "started_at": budget.get("started_at"),
        "deadline_at": deadline,
        "deadline_exceeded": deadline_exceeded,
        "exhaustion_reasons": exhaustion_reasons,
    }


def _budget_blocking_reason(budget_usage: Mapping[str, Any]) -> dict[str, Any]:
    status = str(budget_usage.get("status") or "")
    if status == "RECONCILIATION_REQUIRED":
        return {
            "is_blocked": True,
            "blocking_class": "BUDGET",
            "code": "BOOK_OPENING_BUDGET_RECONCILIATION_REQUIRED",
            "reason": str(
                budget_usage.get("authority_binding_problem")
                or budget_usage.get("contract_state")
                or "UNBOUND"
            ),
            "retryable": False,
            "wake_condition": "RECONCILE_BUDGET_SCOPE",
        }
    if status == "EXHAUSTED":
        reasons = tuple(
            str(item) for item in budget_usage.get("exhaustion_reasons") or ()
        )
        return {
            "is_blocked": True,
            "blocking_class": "BUDGET",
            "code": "BOOK_OPENING_BUDGET_EXHAUSTED",
            "reason": ",".join(reasons),
            "retryable": False,
            "wake_condition": "STOP_AND_REVIEW_BUDGET",
        }
    return {
        "is_blocked": False,
        "blocking_class": "NONE",
        "code": "",
        "reason": "",
        "retryable": False,
        "wake_condition": "",
    }


class PostgresBookOpeningWorkflowProgressQuery:
    def __init__(self, database_url: str) -> None:
        if not str(database_url).strip():
            raise ValueError("Book Opening progress query requires PostgreSQL")
        self.database_url = database_url

    def progress(self, *, opening_run_id: str) -> BookOpeningWorkflowProgressProjection:
        if not str(opening_run_id).strip():
            raise ValueError("opening_run_id is required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            cursor = uow.cursor
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(
                """
                SELECT opening_run_id,project_id,workspace_id,book_id,
                       lifecycle,version,execution_contract_version,
                       workflow_contract_version,workflow_graph_revision,
                       workflow_graph_hash,current_workflow_node_id,
                       current_execution_id,current_execution_generation,
                       current_checkpoint_id,current_checkpoint_sequence,
                       current_checkpoint_hash,recovery_state,budget_scope_id,
                       budget_scope_revision,budget_contract_state,failure,
                       recovery_instruction,transaction_timestamp() AS observed_at
                FROM authority_book_opening_run
                WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )
            opening = _fetchone_mapping(cursor)
            if opening is None:
                raise KernelError(
                    "BOOK_OPENING_NOT_FOUND", "Book opening run is missing"
                )

            cursor.execute(
                """
                SELECT workflow_node_id,opening_run_id,node_key,node_kind,
                       ordinal,input_hash,graph_revision,
                       stable_idempotency_key,created_at
                FROM authority_book_opening_workflow_node
                WHERE opening_run_id=%s
                ORDER BY ordinal,workflow_node_id
                """,
                [opening_run_id],
            )
            nodes = tuple(_fetchall_mappings(cursor))

            cursor.execute(
                """
                SELECT opening_run_id,predecessor_workflow_node_id,
                       successor_workflow_node_id,edge_kind,created_at
                FROM authority_book_opening_workflow_edge
                WHERE opening_run_id=%s
                ORDER BY predecessor_workflow_node_id,
                         successor_workflow_node_id
                """,
                [opening_run_id],
            )
            edges = tuple(_fetchall_mappings(cursor))

            cursor.execute(
                """
                SELECT node_receipt_id,opening_run_id,workflow_node_id,
                       opening_execution_id,execution_generation,result,result_hash,
                       authoritative_evidence_hash,reviewable_artifact_kind,
                       reviewable_asset_version_ids AS requested_asset_version_ids,
                       checkpoint_id,checkpoint_sequence,checkpoint_hash,created_at
                FROM authority_book_opening_node_receipt
                WHERE opening_run_id=%s
                ORDER BY created_at,node_receipt_id
                """,
                [opening_run_id],
            )
            receipt_rows = tuple(_fetchall_mappings(cursor))
            receipts = self._resolve_receipt_evidence(
                cursor,
                opening_run_id=opening_run_id,
                project_id=str(opening["project_id"]),
                receipt_rows=receipt_rows,
            )
            execution = self._current_execution(cursor, opening=opening)
            budget = self._budget(cursor, opening=opening)
            legacy_checkpoint = self._legacy_checkpoint(cursor, opening=opening)
            current_checkpoint = self._current_checkpoint(cursor, opening=opening)

        return project_book_opening_workflow_progress(
            BookOpeningWorkflowProgressSnapshot(
                opening=opening,
                nodes=nodes,
                receipts=receipts,
                execution=execution,
                budget=budget,
                legacy_checkpoint=legacy_checkpoint,
                observed_at=opening["observed_at"],
                current_checkpoint=current_checkpoint,
                edges=edges,
            )
        )

    @staticmethod
    def _resolve_receipt_evidence(
        cursor: Any,
        *,
        opening_run_id: str,
        project_id: str,
        receipt_rows: tuple[Mapping[str, Any], ...],
    ) -> tuple[Mapping[str, Any], ...]:
        checkpoint_ids = tuple(
            sorted(
                {
                    str(row.get("checkpoint_id") or "")
                    for row in receipt_rows
                    if str(row.get("checkpoint_id") or "")
                }
            )
        )
        checkpoints: dict[str, Mapping[str, Any]] = {}
        if checkpoint_ids:
            cursor.execute(
                """
                SELECT checkpoint_id,checkpoint_sequence,checkpoint_hash,
                       workflow_node_id AS checkpoint_workflow_node_id,
                       opening_execution_id AS checkpoint_opening_execution_id,
                       execution_generation AS checkpoint_execution_generation,
                       evidence_hash AS checkpoint_evidence_hash
                FROM authority_book_opening_semantic_checkpoint
                WHERE opening_run_id=%s
                  AND checkpoint_id=ANY(%s::text[])
                """,
                [opening_run_id, list(checkpoint_ids)],
            )
            checkpoints = {
                str(row["checkpoint_id"]): row for row in _fetchall_mappings(cursor)
            }

        requested_asset_ids = tuple(
            dict.fromkeys(
                str(asset_version_id)
                for row in receipt_rows
                for asset_version_id in (row.get("requested_asset_version_ids") or ())
                if str(asset_version_id)
            )
        )
        assets: dict[str, Mapping[str, Any]] = {}
        if requested_asset_ids:
            cursor.execute(
                """
                SELECT version.asset_version_id,version.asset_id,
                       asset.asset_type,asset.project_id,version.content_hash,
                       version.lifecycle,version.eligibility
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=ANY(%s::text[])
                  AND asset.project_id=%s
                """,
                [list(requested_asset_ids), project_id],
            )
            assets = {
                str(row["asset_version_id"]): row for row in _fetchall_mappings(cursor)
            }

        requested_snapshot_ids = tuple(
            dict.fromkeys(
                str(dict(row.get("result") or {}).get("snapshot_id") or "")
                for row in receipt_rows
                if str(row.get("reviewable_artifact_kind") or "")
                == "BOOK_PRODUCTION_INPUT_SNAPSHOT"
                and str(dict(row.get("result") or {}).get("snapshot_id") or "")
            )
        )
        snapshots: dict[str, Mapping[str, Any]] = {}
        if requested_snapshot_ids:
            cursor.execute(
                """
                SELECT snapshot_id,snapshot_hash,project_id,workspace_id,book_id
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=ANY(%s::text[]) AND project_id=%s
                """,
                [list(requested_snapshot_ids), project_id],
            )
            snapshots = {
                str(row["snapshot_id"]): row for row in _fetchall_mappings(cursor)
            }

        resolved: list[Mapping[str, Any]] = []
        for source in receipt_rows:
            receipt = dict(source)
            checkpoint = checkpoints.get(str(receipt.get("checkpoint_id") or ""), {})
            receipt.update(
                {
                    "checkpoint_workflow_node_id": str(
                        checkpoint.get("checkpoint_workflow_node_id") or ""
                    ),
                    "checkpoint_opening_execution_id": str(
                        checkpoint.get("checkpoint_opening_execution_id") or ""
                    ),
                    "checkpoint_execution_generation": int(
                        checkpoint.get("checkpoint_execution_generation") or 0
                    ),
                    "checkpoint_evidence_hash": str(
                        checkpoint.get("checkpoint_evidence_hash") or ""
                    ),
                    "authoritative_checkpoint_id": str(
                        checkpoint.get("checkpoint_id") or ""
                    ),
                    "authoritative_checkpoint_sequence": int(
                        checkpoint.get("checkpoint_sequence") or 0
                    ),
                    "authoritative_checkpoint_hash": str(
                        checkpoint.get("checkpoint_hash") or ""
                    ),
                    "authoritative_assets": tuple(
                        assets[asset_version_id]
                        for asset_version_id in (
                            str(item)
                            for item in (
                                receipt.get("requested_asset_version_ids") or ()
                            )
                        )
                        if asset_version_id in assets
                    ),
                    "authoritative_snapshot": snapshots.get(
                        str(dict(receipt.get("result") or {}).get("snapshot_id") or ""),
                        {},
                    ),
                }
            )
            resolved.append(receipt)
        return tuple(resolved)

    @staticmethod
    def _current_execution(
        cursor: Any, *, opening: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        execution_id = str(opening.get("current_execution_id") or "")
        generation = int(opening.get("current_execution_generation") or 0)
        if not execution_id or generation <= 0:
            return None
        cursor.execute(
            """
            SELECT execution.opening_execution_id,
                   execution.generation AS execution_generation,
                   execution.workflow_node_id,
                   execution.workflow_transition_kind,
                   execution.lifecycle AS execution_lifecycle,
                   execution.runtime_job_id,
                   execution.current_attempt_id AS execution_current_attempt_id,
                   execution.current_lease_id AS execution_current_lease_id,
                   execution.current_worker_id AS execution_current_worker_id,
                   execution.current_fencing_token
                       AS execution_current_fencing_token,
                   job.status AS runtime_job_status,
                   job.current_attempt_id AS job_current_attempt_id,
                   job.claimed_by AS job_claimed_by,
                   job.current_fencing_token AS job_current_fencing_token,
                   attempt.attempt_id,
                   attempt.runtime_job_id AS attempt_runtime_job_id,
                   attempt.status AS attempt_status,
                   attempt.lease_id AS attempt_lease_id,
                   attempt.worker_id AS attempt_worker_id,
                   attempt.fencing_token AS attempt_fencing_token,
                   attempt.lease_expires_at AS attempt_lease_expires_at,
                   lease.lease_id,lease.runtime_job_id AS lease_runtime_job_id,
                   lease.attempt_id AS lease_attempt_id,
                   lease.status AS lease_status,
                   lease.worker_id AS lease_worker_id,
                   lease.fencing_token AS lease_fencing_token,
                   lease.worker_id,lease.fencing_token,lease.lease_expires_at
            FROM authority_book_opening_execution AS execution
            LEFT JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            LEFT JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=execution.current_attempt_id
            LEFT JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=execution.current_lease_id
            WHERE execution.opening_run_id=%s
              AND execution.opening_execution_id=%s
              AND execution.generation=%s
            """,
            [str(opening["opening_run_id"]), execution_id, generation],
        )
        return _fetchone_mapping(cursor)

    @staticmethod
    def _budget(cursor: Any, *, opening: Mapping[str, Any]) -> Mapping[str, Any]:
        budget_scope_id = str(opening.get("budget_scope_id") or "")
        revision = int(opening.get("budget_scope_revision") or 0)
        if not budget_scope_id or revision <= 0:
            return {}
        cursor.execute(
            """
            SELECT scope.budget_scope_id,
                   scope.revision AS budget_scope_revision,
                   scope.policy_snapshot,scope.started_at,scope.deadline_at,
                   COALESCE(usage.reservation_count,0) AS reservation_count,
                   COALESCE(usage.committed_call_count,0)
                       AS committed_call_count,
                   COALESCE(usage.settled_call_count,0) AS settled_call_count,
                   COALESCE(usage.held_unknown_call_count,0)
                       AS held_unknown_call_count,
                   COALESCE(usage.reserved_call_count,0) AS reserved_call_count,
                   COALESCE(usage.accounted_tokens,0) AS accounted_tokens,
                   COALESCE(usage.actual_tokens,0) AS actual_tokens,
                   COALESCE(usage.accounted_cost_usd,0) AS accounted_cost_usd,
                   COALESCE(usage.settled_cost_usd,0) AS settled_cost_usd,
                   COALESCE(usage.budget_breach_count,0) AS budget_breach_count
            FROM authority_provider_budget_scope AS scope
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS reservation_count,
                       COUNT(*) FILTER (
                           WHERE reservation.status IN (
                               'RESERVED','HELD_UNKNOWN','SETTLED'
                           )
                       ) AS committed_call_count,
                       COUNT(*) FILTER (WHERE reservation.status='SETTLED')
                           AS settled_call_count,
                       COUNT(*) FILTER (WHERE reservation.status='HELD_UNKNOWN')
                           AS held_unknown_call_count,
                       COUNT(*) FILTER (WHERE reservation.status='RESERVED')
                           AS reserved_call_count,
                       COALESCE(SUM(
                           CASE
                               WHEN reservation.status='SETTLED'
                                   THEN reservation.actual_tokens
                               WHEN reservation.status IN ('RESERVED','HELD_UNKNOWN')
                                   THEN GREATEST(
                                       reservation.actual_tokens,
                                       reservation.estimated_tokens
                                   )
                               ELSE 0
                           END
                       ),0) AS accounted_tokens,
                       COALESCE(SUM(reservation.actual_tokens),0) AS actual_tokens,
                       COALESCE(SUM(
                           CASE
                               WHEN reservation.status='SETTLED'
                                   THEN reservation.settled_amount
                               WHEN reservation.status IN ('RESERVED','HELD_UNKNOWN')
                                   THEN reservation.reserved_amount
                               ELSE 0
                           END
                       ),0) AS accounted_cost_usd,
                       COALESCE(SUM(reservation.settled_amount) FILTER (
                           WHERE reservation.status='SETTLED'
                       ),0) AS settled_cost_usd,
                       COUNT(*) FILTER (WHERE reservation.budget_breach)
                           AS budget_breach_count
                FROM authority_budget_reservation AS reservation
                WHERE reservation.budget_scope_id=scope.budget_scope_id
                  AND reservation.budget_scope_revision=scope.revision
            ) AS usage ON TRUE
            WHERE scope.budget_scope_id=%s AND scope.revision=%s
            """,
            [budget_scope_id, revision],
        )
        return _fetchone_mapping(cursor) or {}

    @staticmethod
    def _legacy_checkpoint(
        cursor: Any, *, opening: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        if str(opening.get("workflow_contract_version") or "") != (
            "legacy-monolithic-v2"
        ):
            return None
        checkpoint_id = str(opening.get("current_checkpoint_id") or "")
        if not checkpoint_id:
            return None
        cursor.execute(
            """
            SELECT checkpoint_id,checkpoint_sequence,checkpoint_hash,
                   evidence_hash AS authoritative_evidence_hash,
                   semantic_work_key
            FROM authority_book_opening_semantic_checkpoint
            WHERE opening_run_id=%s AND checkpoint_id=%s
            """,
            [str(opening["opening_run_id"]), checkpoint_id],
        )
        return _fetchone_mapping(cursor)

    @staticmethod
    def _current_checkpoint(
        cursor: Any, *, opening: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        checkpoint_id = str(opening.get("current_checkpoint_id") or "")
        if not checkpoint_id:
            return None
        cursor.execute(
            """
            SELECT checkpoint_id,checkpoint_sequence,checkpoint_hash,
                   workflow_node_id,semantic_work_key,evidence_type,evidence_id,
                   evidence_hash
            FROM authority_book_opening_semantic_checkpoint
            WHERE opening_run_id=%s AND checkpoint_id=%s
            """,
            [str(opening["opening_run_id"]), checkpoint_id],
        )
        return _fetchone_mapping(cursor)


def _fetchone_mapping(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(_column_names(cursor), row, strict=True))


def _fetchall_mappings(cursor: Any) -> tuple[dict[str, Any], ...]:
    columns = _column_names(cursor)
    return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())


def _column_names(cursor: Any) -> tuple[str, ...]:
    names: list[str] = []
    for column in cursor.description:
        name = getattr(column, "name", None)
        names.append(str(name if name is not None else column[0]))
    return tuple(names)


def _is_sha256(value: object) -> bool:
    return _SHA256.fullmatch(str(value or "")) is not None


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _decimal_text(value)
    return value


__all__ = [
    "BOOK_OPENING_WORKFLOW_PROGRESS_SCHEMA_VERSION",
    "BookOpeningWorkflowProgressProjection",
    "BookOpeningWorkflowProgressSnapshot",
    "PostgresBookOpeningWorkflowProgressQuery",
    "project_book_opening_workflow_progress",
]
