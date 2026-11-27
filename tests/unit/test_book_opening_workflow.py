from __future__ import annotations

from novel_forge.modules.book_authority.opening_workflow import (
    BOOK_OPENING_TOPOLOGY_BUDGET_CONTRACT_VERSION,
    BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
    BookOpeningWorkflowResult,
    BookOpeningWorkflowNodeKind,
    assess_book_opening_topology_budget,
    build_book_opening_workflow,
)


DEFAULT_V2_POLICY = {
    "execution_mode": "PROVIDER_ALLOWED",
    "provider_call_limit": 48,
    "token_limit": 4_800_000,
    "cost_limit_usd": "96",
    "per_call_token_limit": 100_000,
    "per_call_cost_limit_usd": "2",
}


def _topology_budget(*, arc_count: int = 2):
    return assess_book_opening_topology_budget(
        policy_contract_version="book-opening-provider-budget.v2",
        policy_hash="sha256:" + "b" * 64,
        policy=DEFAULT_V2_POLICY,
        arc_count=arc_count,
    )


def test_default_v2_budget_admits_minimum_topology_without_eleventh_call_failure() -> (
    None
):
    assessment = _topology_budget(arc_count=1)

    assert assessment.contract_version == BOOK_OPENING_TOPOLOGY_BUDGET_CONTRACT_VERSION
    assert assessment.minimum_topology_provider_calls == 18
    assert assessment.max_volume_count == 5
    assert assessment.reserved_provider_calls == 6


def test_default_v2_budget_fits_v4_a2_and_one_complete_search_reserve() -> None:
    assessment = _topology_budget(arc_count=2)

    assert assessment.max_volume_count == 4
    assert assessment.provider_calls_for(volume_count=4) == 42
    assert assessment.provider_calls_for(volume_count=4) + 6 == 48


def test_account_entitlement_topology_is_bounded_by_calls_and_tokens() -> None:
    assessment = assess_book_opening_topology_budget(
        policy_contract_version="book-opening-provider-budget.v2",
        policy_hash="sha256:" + "e" * 64,
        policy={
            "execution_mode": "PROVIDER_ALLOWED",
            "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "authorization_ref": "task-authorization:classical-corpus-20260908",
            "cost_observability": "UNKNOWN",
            "provider_call_limit": 48,
            "token_limit": 4_800_000,
            "per_call_token_limit": 100_000,
        },
        arc_count=2,
    )

    assert assessment.max_volume_count == 4
    assert assessment.provider_calls_for(volume_count=4) + 6 == 48


def test_topology_admission_rejects_policy_that_cannot_fund_v1_a1() -> None:
    for insufficient in (
        {**DEFAULT_V2_POLICY, "provider_call_limit": 17},
        {**DEFAULT_V2_POLICY, "token_limit": 1_700_000},
        {**DEFAULT_V2_POLICY, "cost_limit_usd": "34"},
    ):
        try:
            assess_book_opening_topology_budget(
                policy_contract_version="book-opening-provider-budget.v2",
                policy_hash="sha256:" + "c" * 64,
                policy=insufficient,
                arc_count=1,
            )
        except ValueError as exc:
            assert "minimum Book Opening topology" in str(exc)
        else:
            raise AssertionError("an underfunded topology was admitted")


def test_topology_v2_rejects_a_forged_legacy_policy_version() -> None:
    try:
        assess_book_opening_topology_budget(
            policy_contract_version="book-opening-provider-budget.v1",
            policy_hash="sha256:" + "c" * 64,
            policy=DEFAULT_V2_POLICY,
            arc_count=1,
        )
    except ValueError as exc:
        assert "identity is invalid" in str(exc)
    else:
        raise AssertionError("a v1 policy was accepted as a topology-v2 contract")


def test_workflow_plan_is_a_fixed_five_layer_graph() -> None:
    topology_budget = _topology_budget()
    workflow = build_book_opening_workflow(
        opening_run_id="book-opening:workflow",
        frozen_request_digest="sha256:" + "a" * 64,
        arc_logical_keys=("arc:main", "arc:relationship"),
        topology_budget=topology_budget,
    )

    assert workflow.contract_version == BOOK_OPENING_WORKFLOW_CONTRACT_VERSION
    assert [node.kind for node in workflow.nodes] == [
        BookOpeningWorkflowNodeKind.BOOK_PLAN,
        BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO,
        BookOpeningWorkflowNodeKind.CURRENT_VOLUME,
        BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE,
        BookOpeningWorkflowNodeKind.INPUT_SNAPSHOT,
    ]
    assert [node.ordinal for node in workflow.nodes] == [1, 2, 3, 4, 5]
    assert len({node.workflow_node_id for node in workflow.nodes}) == 5
    assert len({node.stable_idempotency_key for node in workflow.nodes}) == 5
    assert (
        workflow.node(BookOpeningWorkflowNodeKind.BOOK_PLAN).input_contract[
            "opening_topology_budget"
        ]
        == topology_budget.to_dict()
    )
    assert [(edge.parent_node_id, edge.child_node_id) for edge in workflow.edges] == [
        (
            workflow.nodes[index].workflow_node_id,
            workflow.nodes[index + 1].workflow_node_id,
        )
        for index in range(4)
    ]


def test_workflow_identity_freezes_arc_scope_and_request_digest() -> None:
    topology_budget = _topology_budget()
    first = build_book_opening_workflow(
        opening_run_id="book-opening:workflow",
        frozen_request_digest="sha256:" + "a" * 64,
        arc_logical_keys=("arc:main", "arc:relationship"),
        topology_budget=topology_budget,
    )
    replay = build_book_opening_workflow(
        opening_run_id="book-opening:workflow",
        frozen_request_digest="sha256:" + "a" * 64,
        arc_logical_keys=("arc:main", "arc:relationship"),
        topology_budget=topology_budget,
    )
    drifted = build_book_opening_workflow(
        opening_run_id="book-opening:workflow",
        frozen_request_digest="sha256:" + "b" * 64,
        arc_logical_keys=("arc:main",),
        topology_budget=_topology_budget(arc_count=1),
    )

    assert first == replay
    assert first.graph_hash != drifted.graph_hash
    arc = first.node(BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE)
    assert arc.input_contract == {
        "arc_logical_keys": ["arc:main", "arc:relationship"],
        "depends_on_kind": "CURRENT_VOLUME",
        "frozen_request_digest": "sha256:" + "a" * 64,
    }
    assert arc.input_hash.startswith("sha256:")


def test_workflow_rejects_invalid_identity() -> None:
    for kwargs in (
        {
            "opening_run_id": "",
            "frozen_request_digest": "sha256:" + "a" * 64,
            "arc_logical_keys": ("arc:main",),
            "topology_budget": _topology_budget(arc_count=1),
        },
        {
            "opening_run_id": "book-opening:workflow",
            "frozen_request_digest": "not-a-digest",
            "arc_logical_keys": ("arc:main",),
            "topology_budget": _topology_budget(arc_count=1),
        },
        {
            "opening_run_id": "book-opening:workflow",
            "frozen_request_digest": "sha256:" + "a" * 64,
            "arc_logical_keys": (),
            "topology_budget": _topology_budget(arc_count=1),
        },
        {
            "opening_run_id": "book-opening:workflow",
            "frozen_request_digest": "sha256:" + "a" * 64,
            "arc_logical_keys": ("arc:main", "arc:main"),
            "topology_budget": _topology_budget(),
        },
    ):
        try:
            build_book_opening_workflow(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid workflow identity was accepted")


def test_workflow_result_is_typed_and_round_trips_exact_portfolios() -> None:
    payload = {
        "workflow_contract_version": BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
        "book_design_version": "book-design:v1",
        "book_plan_version": "book-plan:v1",
        "volume_portfolio_plan_versions": ["volume:v1", "volume:v2"],
        "current_volume_plan_version": "volume:v1",
        "arc_portfolio_plan_versions": ["arc:v1", "arc:v2"],
        "current_relevant_arc_plan_versions": ["arc:v1"],
        "input_snapshot_id": "snapshot:v1",
        "search_ids": [
            "search:book",
            "search:volume:1",
            "search:volume:2",
            "search:arc:1",
            "search:arc:2",
        ],
        "node_receipt_ids": [f"receipt:{ordinal}" for ordinal in range(1, 6)],
    }

    result = BookOpeningWorkflowResult.from_mapping(payload)

    assert result.to_dict() == payload


def test_workflow_result_rejects_schema_and_lineage_drift() -> None:
    valid = {
        "workflow_contract_version": BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
        "book_design_version": "book-design:v1",
        "book_plan_version": "book-plan:v1",
        "volume_portfolio_plan_versions": ["volume:v1", "volume:v2"],
        "current_volume_plan_version": "volume:v1",
        "arc_portfolio_plan_versions": ["arc:v1", "arc:v2"],
        "current_relevant_arc_plan_versions": ["arc:v1", "arc:v2"],
        "input_snapshot_id": "snapshot:v1",
        "search_ids": [
            "search:book",
            "search:volume:1",
            "search:volume:2",
            "search:arc:1",
            "search:arc:2",
        ],
        "node_receipt_ids": [f"receipt:{ordinal}" for ordinal in range(1, 6)],
    }
    invalid = []
    missing_field = dict(valid)
    missing_field.pop("book_plan_version")
    invalid.append(missing_field)
    wrong_current = dict(valid)
    wrong_current["current_volume_plan_version"] = "volume:outside"
    invalid.append(wrong_current)
    reordered_scope = dict(valid)
    reordered_scope["current_relevant_arc_plan_versions"] = ["arc:v2", "arc:v1"]
    invalid.append(reordered_scope)
    missing_receipt = dict(valid)
    missing_receipt["node_receipt_ids"] = ["receipt:1"]
    invalid.append(missing_receipt)

    for payload in invalid:
        try:
            BookOpeningWorkflowResult.from_mapping(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("drifted workflow result was accepted")
