from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from enum import StrEnum
from typing import Any, Mapping


BOOK_OPENING_WORKFLOW_CONTRACT_VERSION = "book-opening-workflow-v1"
BOOK_OPENING_WORKFLOW_RESULT_SCHEMA_VERSION = "book-opening-workflow-result.v3"
BOOK_OPENING_PROVIDER_BUDGET_POLICY_CONTRACT_VERSION = "book-opening-provider-budget.v2"
BOOK_OPENING_TOPOLOGY_BUDGET_CONTRACT_VERSION = "book-opening-topology-budget.v2"
BOOK_OPENING_PROVIDER_CALLS_PER_SEARCH = 6
BOOK_OPENING_RESERVED_SEARCH_COUNT = 1


@dataclass(frozen=True, slots=True)
class BookOpeningTopologyBudget:
    contract_version: str
    policy_contract_version: str
    policy_hash: str
    arc_count: int
    calls_per_search: int
    reserved_search_count: int
    provider_call_capacity: int
    reserved_provider_calls: int
    max_volume_count: int

    @property
    def minimum_topology_provider_calls(self) -> int:
        return self.provider_calls_for(volume_count=1)

    def provider_calls_for(self, *, volume_count: int) -> int:
        if (
            not isinstance(volume_count, int)
            or isinstance(volume_count, bool)
            or volume_count <= 0
        ):
            raise ValueError("volume_count must be a positive integer")
        return self.calls_per_search * (1 + volume_count + self.arc_count)

    def require_volume_count(self, volume_count: int) -> None:
        required = self.provider_calls_for(volume_count=volume_count)
        if volume_count > self.max_volume_count or (
            required + self.reserved_provider_calls > self.provider_call_capacity
        ):
            raise ValueError(
                "Book Plan Volume skeleton exceeds the frozen Opening topology budget"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "policy_contract_version": self.policy_contract_version,
            "policy_hash": self.policy_hash,
            "arc_count": self.arc_count,
            "calls_per_search": self.calls_per_search,
            "reserved_search_count": self.reserved_search_count,
            "provider_call_capacity": self.provider_call_capacity,
            "reserved_provider_calls": self.reserved_provider_calls,
            "max_volume_count": self.max_volume_count,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> BookOpeningTopologyBudget:
        expected = {
            "contract_version",
            "policy_contract_version",
            "policy_hash",
            "arc_count",
            "calls_per_search",
            "reserved_search_count",
            "provider_call_capacity",
            "reserved_provider_calls",
            "max_volume_count",
        }
        if set(value) != expected:
            raise ValueError("Opening topology budget fields must match exactly")
        integer_fields = (
            "arc_count",
            "calls_per_search",
            "reserved_search_count",
            "provider_call_capacity",
            "reserved_provider_calls",
            "max_volume_count",
        )
        if any(
            not isinstance(value[field], int)
            or isinstance(value[field], bool)
            or int(value[field]) <= 0
            for field in integer_fields
        ):
            raise ValueError("Opening topology budget integers must be positive")
        budget = cls(
            contract_version=str(value["contract_version"]),
            policy_contract_version=str(value["policy_contract_version"]),
            policy_hash=str(value["policy_hash"]),
            arc_count=int(value["arc_count"]),
            calls_per_search=int(value["calls_per_search"]),
            reserved_search_count=int(value["reserved_search_count"]),
            provider_call_capacity=int(value["provider_call_capacity"]),
            reserved_provider_calls=int(value["reserved_provider_calls"]),
            max_volume_count=int(value["max_volume_count"]),
        )
        if (
            budget.contract_version != BOOK_OPENING_TOPOLOGY_BUDGET_CONTRACT_VERSION
            or budget.policy_contract_version
            != BOOK_OPENING_PROVIDER_BUDGET_POLICY_CONTRACT_VERSION
            or not _is_sha256_digest(budget.policy_hash)
            or budget.calls_per_search != BOOK_OPENING_PROVIDER_CALLS_PER_SEARCH
            or budget.reserved_search_count != BOOK_OPENING_RESERVED_SEARCH_COUNT
            or budget.reserved_provider_calls
            != budget.calls_per_search * budget.reserved_search_count
        ):
            raise ValueError("Opening topology budget contract is invalid")
        budget.require_volume_count(budget.max_volume_count)
        if (
            budget.provider_calls_for(volume_count=budget.max_volume_count + 1)
            + budget.reserved_provider_calls
            <= budget.provider_call_capacity
        ):
            raise ValueError("Opening topology max Volume count is not canonical")
        return budget


def _is_sha256_digest(value: str) -> bool:
    if len(value) != 71 or not value.startswith("sha256:"):
        return False
    try:
        int(value[7:], 16)
    except ValueError:
        return False
    return True


def assess_book_opening_topology_budget(
    *,
    policy_contract_version: str,
    policy_hash: str,
    policy: Mapping[str, Any],
    arc_count: int,
) -> BookOpeningTopologyBudget:

    if (
        policy_contract_version != BOOK_OPENING_PROVIDER_BUDGET_POLICY_CONTRACT_VERSION
        or not _is_sha256_digest(policy_hash)
        or not isinstance(arc_count, int)
        or isinstance(arc_count, bool)
        or arc_count <= 0
    ):
        raise ValueError("Opening topology budget identity is invalid")
    if str(policy.get("execution_mode") or "") != "PROVIDER_ALLOWED":
        raise ValueError("Book Opening topology requires Provider execution authority")

    def positive_int(field: str) -> int:
        value = policy.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"Opening budget {field} must be a positive integer")
        return int(value)

    call_limit = positive_int("provider_call_limit")
    token_limit = positive_int("token_limit")
    per_call_token_limit = positive_int("per_call_token_limit")
    try:
        cost_limit = Decimal(str(policy.get("cost_limit_usd") or ""))
        per_call_cost_limit = Decimal(str(policy.get("per_call_cost_limit_usd") or ""))
    except InvalidOperation as exc:
        raise ValueError("Opening budget cost limits must be decimal values") from exc
    if cost_limit <= 0 or per_call_cost_limit <= 0:
        raise ValueError("Opening budget cost limits must be positive")
    cost_call_capacity = int(
        (cost_limit / per_call_cost_limit).to_integral_value(rounding=ROUND_FLOOR)
    )
    provider_call_capacity = min(
        call_limit,
        token_limit // per_call_token_limit,
        cost_call_capacity,
    )
    search_capacity = provider_call_capacity // BOOK_OPENING_PROVIDER_CALLS_PER_SEARCH
    max_volume_count = (
        search_capacity - 1 - arc_count - BOOK_OPENING_RESERVED_SEARCH_COUNT
    )
    if max_volume_count < 1:
        raise ValueError(
            "Provider budget cannot fund the minimum Book Opening topology and reserve"
        )
    return BookOpeningTopologyBudget.from_mapping(
        {
            "contract_version": BOOK_OPENING_TOPOLOGY_BUDGET_CONTRACT_VERSION,
            "policy_contract_version": policy_contract_version,
            "policy_hash": policy_hash,
            "arc_count": arc_count,
            "calls_per_search": BOOK_OPENING_PROVIDER_CALLS_PER_SEARCH,
            "reserved_search_count": BOOK_OPENING_RESERVED_SEARCH_COUNT,
            "provider_call_capacity": provider_call_capacity,
            "reserved_provider_calls": (
                BOOK_OPENING_PROVIDER_CALLS_PER_SEARCH
                * BOOK_OPENING_RESERVED_SEARCH_COUNT
            ),
            "max_volume_count": max_volume_count,
        }
    )


class BookOpeningWorkflowNodeKind(StrEnum):
    BOOK_PLAN = "BOOK_PLAN"
    VOLUME_PORTFOLIO = "VOLUME_PORTFOLIO"
    CURRENT_VOLUME = "CURRENT_VOLUME"
    INITIAL_ARC_SCOPE = "INITIAL_ARC_SCOPE"
    INPUT_SNAPSHOT = "INPUT_SNAPSHOT"


@dataclass(frozen=True, slots=True)
class BookOpeningWorkflowNode:
    workflow_node_id: str
    kind: BookOpeningWorkflowNodeKind
    node_key: str
    ordinal: int
    input_contract: Mapping[str, Any]
    input_hash: str
    stable_idempotency_key: str


@dataclass(frozen=True, slots=True)
class BookOpeningWorkflowEdge:
    parent_node_id: str
    child_node_id: str
    relation: str = "REQUIRES"


@dataclass(frozen=True, slots=True)
class BookOpeningWorkflow:
    opening_run_id: str
    contract_version: str
    graph_revision: int
    graph_hash: str
    nodes: tuple[BookOpeningWorkflowNode, ...]
    edges: tuple[BookOpeningWorkflowEdge, ...]

    def node(self, kind: BookOpeningWorkflowNodeKind) -> BookOpeningWorkflowNode:
        matches = tuple(node for node in self.nodes if node.kind == kind)
        if len(matches) != 1:
            raise ValueError(f"workflow node cardinality violation for {kind.value}")
        return matches[0]


@dataclass(frozen=True, slots=True)
class BookOpeningWorkflowResult:
    book_design_version: str
    book_plan_version: str
    volume_portfolio_plan_versions: tuple[str, ...]
    current_volume_plan_version: str
    arc_portfolio_plan_versions: tuple[str, ...]
    current_relevant_arc_plan_versions: tuple[str, ...]
    input_snapshot_id: str
    search_ids: tuple[str, ...]
    node_receipt_ids: tuple[str, ...]
    workflow_contract_version: str = BOOK_OPENING_WORKFLOW_CONTRACT_VERSION

    def __post_init__(self) -> None:
        scalar_identities = (
            self.book_design_version,
            self.book_plan_version,
            self.current_volume_plan_version,
            self.input_snapshot_id,
        )
        if any(not str(value).strip() for value in scalar_identities):
            raise ValueError("Book Opening workflow result identity is incomplete")
        if self.workflow_contract_version != BOOK_OPENING_WORKFLOW_CONTRACT_VERSION:
            raise ValueError("Book Opening workflow result contract is unsupported")
        identity_sets = {
            "Volume Portfolio": self.volume_portfolio_plan_versions,
            "Arc Portfolio": self.arc_portfolio_plan_versions,
            "current Arc scope": self.current_relevant_arc_plan_versions,
            "Narrative Search": self.search_ids,
            "node receipt": self.node_receipt_ids,
        }
        for label, values in identity_sets.items():
            if not values or any(not str(value).strip() for value in values):
                raise ValueError(f"Book Opening {label} identity is incomplete")
            if len(set(values)) != len(values):
                raise ValueError(f"Book Opening {label} identity must be unique")
        if self.current_volume_plan_version not in self.volume_portfolio_plan_versions:
            raise ValueError("current Volume must belong to the frozen portfolio")
        relevant_positions = tuple(
            self.arc_portfolio_plan_versions.index(value)
            for value in self.current_relevant_arc_plan_versions
            if value in self.arc_portfolio_plan_versions
        )
        if (
            len(relevant_positions) != len(self.current_relevant_arc_plan_versions)
            or tuple(sorted(relevant_positions)) != relevant_positions
        ):
            raise ValueError(
                "current Arc scope must be an ordered subset of the frozen portfolio"
            )
        if len(self.node_receipt_ids) != len(BookOpeningWorkflowNodeKind):
            raise ValueError("Book Opening result requires exactly five node receipts")
        if len(self.search_ids) != (
            1
            + len(self.volume_portfolio_plan_versions)
            + len(self.arc_portfolio_plan_versions)
        ):
            raise ValueError(
                "Book Opening Search identities must exactly cover Book, Volume, and Arc assets"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> BookOpeningWorkflowResult:
        expected = {
            "workflow_contract_version",
            "book_design_version",
            "book_plan_version",
            "volume_portfolio_plan_versions",
            "current_volume_plan_version",
            "arc_portfolio_plan_versions",
            "current_relevant_arc_plan_versions",
            "input_snapshot_id",
            "search_ids",
            "node_receipt_ids",
        }
        if set(value) != expected:
            raise ValueError("Book Opening workflow result fields must match exactly")

        def identities(field: str) -> tuple[str, ...]:
            raw = value[field]
            if not isinstance(raw, (list, tuple)):
                raise ValueError(f"Book Opening workflow result {field} must be a list")
            return tuple(str(item).strip() for item in raw)

        return cls(
            workflow_contract_version=str(value["workflow_contract_version"]),
            book_design_version=str(value["book_design_version"]),
            book_plan_version=str(value["book_plan_version"]),
            volume_portfolio_plan_versions=identities("volume_portfolio_plan_versions"),
            current_volume_plan_version=str(value["current_volume_plan_version"]),
            arc_portfolio_plan_versions=identities("arc_portfolio_plan_versions"),
            current_relevant_arc_plan_versions=identities(
                "current_relevant_arc_plan_versions"
            ),
            input_snapshot_id=str(value["input_snapshot_id"]),
            search_ids=identities("search_ids"),
            node_receipt_ids=identities("node_receipt_ids"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_contract_version": self.workflow_contract_version,
            "book_design_version": self.book_design_version,
            "book_plan_version": self.book_plan_version,
            "volume_portfolio_plan_versions": list(self.volume_portfolio_plan_versions),
            "current_volume_plan_version": self.current_volume_plan_version,
            "arc_portfolio_plan_versions": list(self.arc_portfolio_plan_versions),
            "current_relevant_arc_plan_versions": list(
                self.current_relevant_arc_plan_versions
            ),
            "input_snapshot_id": self.input_snapshot_id,
            "search_ids": list(self.search_ids),
            "node_receipt_ids": list(self.node_receipt_ids),
        }


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Mapping[str, Any]) -> str:
    return (
        "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    )


def _stable_identity(*parts: str) -> str:
    material = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _require_non_empty(value: str, *, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _require_sha256(value: str, *, name: str) -> str:
    normalized = _require_non_empty(value, name=name)
    prefix, separator, encoded = normalized.partition(":")
    if separator != ":" or prefix != "sha256" or len(encoded) != 64:
        raise ValueError(f"{name} must be a sha256 digest")
    try:
        int(encoded, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a sha256 digest") from exc
    return normalized


def build_book_opening_workflow(
    *,
    opening_run_id: str,
    frozen_request_digest: str,
    arc_logical_keys: tuple[str, ...],
    topology_budget: BookOpeningTopologyBudget,
) -> BookOpeningWorkflow:
    run_id = _require_non_empty(opening_run_id, name="opening_run_id")
    request_digest = _require_sha256(
        frozen_request_digest,
        name="frozen_request_digest",
    )
    normalized_arcs = tuple(
        _require_non_empty(key, name="arc_logical_key") for key in arc_logical_keys
    )
    if not normalized_arcs:
        raise ValueError("arc_logical_keys must not be empty")
    if len(set(normalized_arcs)) != len(normalized_arcs):
        raise ValueError("arc_logical_keys must be unique")
    if not isinstance(topology_budget, BookOpeningTopologyBudget):
        raise ValueError("topology_budget must be an immutable assessment")
    canonical_topology_budget = BookOpeningTopologyBudget.from_mapping(
        topology_budget.to_dict()
    )
    if canonical_topology_budget.arc_count != len(normalized_arcs):
        raise ValueError("topology budget Arc count differs from the frozen scope")

    definitions: tuple[
        tuple[BookOpeningWorkflowNodeKind, str, Mapping[str, Any]], ...
    ] = (
        (
            BookOpeningWorkflowNodeKind.BOOK_PLAN,
            "book-plan",
            {
                "frozen_request_digest": request_digest,
                "generator": "book_plan.generate",
                "opening_topology_budget": canonical_topology_budget.to_dict(),
            },
        ),
        (
            BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO,
            "volume-portfolio",
            {
                "depends_on_kind": BookOpeningWorkflowNodeKind.BOOK_PLAN.value,
                "frozen_request_digest": request_digest,
            },
        ),
        (
            BookOpeningWorkflowNodeKind.CURRENT_VOLUME,
            "current-volume",
            {
                "chapter_cursor": 1,
                "depends_on_kind": BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO.value,
                "frozen_request_digest": request_digest,
            },
        ),
        (
            BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE,
            "initial-arc-scope",
            {
                "arc_logical_keys": list(normalized_arcs),
                "depends_on_kind": BookOpeningWorkflowNodeKind.CURRENT_VOLUME.value,
                "frozen_request_digest": request_digest,
            },
        ),
        (
            BookOpeningWorkflowNodeKind.INPUT_SNAPSHOT,
            "input-snapshot",
            {
                "depends_on_kind": BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE.value,
                "frozen_request_digest": request_digest,
            },
        ),
    )

    nodes: list[BookOpeningWorkflowNode] = []
    for ordinal, (kind, node_key, input_contract) in enumerate(definitions, start=1):
        input_hash = _digest(input_contract)
        identity = _stable_identity(run_id, kind.value, node_key, input_hash)
        nodes.append(
            BookOpeningWorkflowNode(
                workflow_node_id=f"book-opening-node:{identity}",
                kind=kind,
                node_key=node_key,
                ordinal=ordinal,
                input_contract=input_contract,
                input_hash=input_hash,
                stable_idempotency_key=(
                    f"book-opening-node:{run_id}:{kind.value}:{node_key}:{input_hash}"
                ),
            )
        )

    edges = tuple(
        BookOpeningWorkflowEdge(
            parent_node_id=nodes[index].workflow_node_id,
            child_node_id=nodes[index + 1].workflow_node_id,
        )
        for index in range(len(nodes) - 1)
    )
    graph_contract = {
        "contract_version": BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
        "graph_revision": 1,
        "nodes": [
            {
                "input_hash": node.input_hash,
                "kind": node.kind.value,
                "node_key": node.node_key,
                "ordinal": node.ordinal,
                "workflow_node_id": node.workflow_node_id,
            }
            for node in nodes
        ],
        "edges": [
            {
                "child_node_id": edge.child_node_id,
                "parent_node_id": edge.parent_node_id,
                "relation": edge.relation,
            }
            for edge in edges
        ],
    }
    return BookOpeningWorkflow(
        opening_run_id=run_id,
        contract_version=BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
        graph_revision=1,
        graph_hash=_digest(graph_contract),
        nodes=tuple(nodes),
        edges=edges,
    )
