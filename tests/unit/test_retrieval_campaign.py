from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.retrieval_campaign import (
    RetrievalCampaignPolicy,
    build_retrieval_coverage_contract,
    decide_retrieval_campaign_transition,
    evaluate_retrieval_coverage,
    merge_retrieval_round_documents,
    validate_retrieval_expansion_plan,
)


def _intent() -> dict[str, object]:
    return {
        "chapter": 401,
        "project_id": "project:alpha",
        "intent_fingerprint": "sha256:" + "1" * 64,
        "accepted_boundary": {"accepted_through_chapter": 400},
        "required_arc_contributions": [{"arc_plan_version_id": "arc:trust:v7"}],
        "active_obligations": [{"state": {"obligation_id": "obligation:return-key"}}],
        "required_long_distance_fact_ids": ["fact:oath-origin"],
        "explicit_historical_references": [
            {
                "reference_id": "history:bridge-oath",
                "query_hint": "bridge oath witness",
            }
        ],
        "retrieval_graph": {
            "entity_ids": ["entity:red-key"],
            "character_ids": ["character:mei", "character:ren"],
            "relationship_ids": ["relationship:mei-ren"],
        },
        "scene_plans": [
            {
                "scene_id": "scene:401:1",
                "participants": ["character:mei", "character:ren"],
            }
        ],
        "chapter_mission": {
            "required_outcomes": {
                "required_payoffs": ["obligation:return-key"],
                "required_events": ["history:bridge-oath"],
            },
            "knowledge_and_disclosure_boundaries": {
                "knowledge_boundaries": [
                    {
                        "fact_id": "fact:oath-origin",
                        "visibility": "ACCESSIBLE",
                        "retrieval_required": True,
                    }
                ],
                "disclosures": [],
            },
        },
    }


def _memo() -> dict[str, object]:
    return {
        "chapter": 401,
        "qualification": "QUALIFIED",
        "memo_fingerprint": "sha256:" + "2" * 64,
        "accepted_boundary": {"accepted_through_chapter": 400},
        "retrieval_queries": ["red key return", "Mei Ren trust"],
        "arc_actions": [{"arc_plan_version_id": "arc:trust:v7"}],
        "obligation_actions": [{"obligation_id": "obligation:return-key"}],
    }


def _document(
    identity: str,
    *,
    chapter: int,
    fact_ids: tuple[str, ...] = (),
    historical_reference_ids: tuple[str, ...] = (),
    entity_ids: tuple[str, ...] = (),
    relationship_ids: tuple[str, ...] = (),
    arc_ids: tuple[str, ...] = (),
    obligation_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "retrieval_document_id": identity,
        "source_asset_version_id": f"asset-version:{identity}",
        "source_content_hash": "sha256:" + "3" * 64,
        "projection_hash": "sha256:" + "4" * 64,
        "accepted_from_chapter": chapter,
        "accepted_to_chapter": None,
        "memory_layer": "L3",
        "content_text": identity,
        "fact_ids": list(fact_ids),
        "historical_reference_ids": list(historical_reference_ids),
        "entity_ids": list(entity_ids),
        "character_ids": [
            value for value in entity_ids if value.startswith("character:")
        ],
        "relationship_ids": list(relationship_ids),
        "arc_plan_version_ids": list(arc_ids),
        "obligation_ids": list(obligation_ids),
        "candidate_channels": ["FTS"],
    }


def test_coverage_contract_is_derived_from_frozen_intent_and_memo() -> None:
    contract = build_retrieval_coverage_contract(intent=_intent(), memo=_memo())

    assert contract["accepted_boundary"] == {"accepted_through_chapter": 400}
    assert contract["intent_fingerprint"] == "sha256:" + "1" * 64
    assert contract["memo_fingerprint"] == "sha256:" + "2" * 64
    assert contract["required"]["fact_ids"] == ["fact:oath-origin"]
    assert contract["required"]["relationship_ids"] == ["relationship:mei-ren"]
    assert contract["required"]["arc_plan_version_ids"] == ["arc:trust:v7"]
    assert contract["required"]["obligation_ids"] == ["obligation:return-key"]
    assert contract["required"]["historical_reference_ids"] == ["history:bridge-oath"]
    assert contract["protected_evidence"]["arc_plan_version_ids"] == ["arc:trust:v7"]
    assert contract["selectors"]["character_ids"] == [
        "character:mei",
        "character:ren",
    ]
    assert contract["coverage_contract_fingerprint"].startswith("sha256:")


def test_first_chapter_does_not_invent_historical_requirements() -> None:
    intent = _intent()
    memo = _memo()
    intent["chapter"] = 1
    intent["accepted_boundary"] = {"accepted_through_chapter": 0}
    memo["chapter"] = 1
    memo["accepted_boundary"] = {"accepted_through_chapter": 0}
    intent["required_long_distance_fact_ids"] = []
    intent["explicit_historical_references"] = []
    intent["chapter_mission"] = {
        "knowledge_and_disclosure_boundaries": {
            "knowledge_boundaries": [],
            "disclosures": [],
        }
    }

    contract = build_retrieval_coverage_contract(intent=intent, memo=memo)

    assert contract["required"] == {
        "fact_ids": [],
        "historical_reference_ids": [],
        "relationship_ids": [],
        "arc_plan_version_ids": [],
        "obligation_ids": [],
    }
    assert contract["selectors"]["relationship_ids"] == ["relationship:mei-ren"]
    assert contract["selectors"]["arc_plan_version_ids"] == ["arc:trust:v7"]
    assert contract["selectors"]["obligation_ids"] == ["obligation:return-key"]
    assert (
        evaluate_retrieval_coverage(contract=contract, documents=[])["sufficient"]
        is True
    )


def test_deterministic_coverage_requires_every_hard_evidence_identity() -> None:
    contract = build_retrieval_coverage_contract(intent=_intent(), memo=_memo())
    round_zero = [
        _document(
            "recent",
            chapter=399,
            entity_ids=("character:mei", "character:ren", "entity:red-key"),
            relationship_ids=("relationship:mei-ren",),
            arc_ids=("arc:trust:v7",),
            obligation_ids=("obligation:return-key",),
        )
    ]

    missing = evaluate_retrieval_coverage(contract=contract, documents=round_zero)
    assert missing["sufficient"] is False
    assert missing["missing"] == {
        "fact_ids": ["fact:oath-origin"],
        "historical_reference_ids": ["history:bridge-oath"],
    }

    complete = evaluate_retrieval_coverage(
        contract=contract,
        documents=[
            *round_zero,
            _document(
                "oath",
                chapter=30,
                fact_ids=("fact:oath-origin",),
                historical_reference_ids=("history:bridge-oath",),
            ),
        ],
    )
    assert complete["sufficient"] is True
    assert complete["missing"] == {}
    assert complete["coverage_fingerprint"].startswith("sha256:")


def test_current_arc_plan_requirement_is_covered_by_protected_mission_input() -> None:
    intent = _intent()
    memo = _memo()
    intent["required_long_distance_fact_ids"] = []
    intent["explicit_historical_references"] = []
    intent["retrieval_graph"] = {
        "entity_ids": [],
        "character_ids": [],
        "relationship_ids": [],
    }
    intent["scene_plans"] = []
    intent["active_obligations"] = []
    intent["chapter_mission"] = {
        "knowledge_and_disclosure_boundaries": {
            "knowledge_boundaries": [],
            "disclosures": [],
        }
    }
    memo["obligation_actions"] = []

    coverage = evaluate_retrieval_coverage(
        contract=build_retrieval_coverage_contract(intent=intent, memo=memo),
        documents=[],
    )

    assert coverage["sufficient"] is True
    assert coverage["observed"]["arc_plan_version_ids"] == ["arc:trust:v7"]
    assert coverage["evidence_document_ids"] == []


def test_expansion_plan_is_bounded_to_missing_contract_and_accepted_time() -> None:
    policy = RetrievalCampaignPolicy()
    contract = build_retrieval_coverage_contract(intent=_intent(), memo=_memo())
    coverage = evaluate_retrieval_coverage(contract=contract, documents=[])
    plan = validate_retrieval_expansion_plan(
        raw={
            "contract_version": "retrieval-expansion-plan-v1",
            "queries": [
                {
                    "query_id": "query:oath",
                    "text": "bridge oath witness",
                    "reason": "recover the missing oath provenance",
                    "targets": [
                        "fact:fact:oath-origin",
                        "history:history:bridge-oath",
                    ],
                    "selectors": {
                        "character_ids": ["character:mei"],
                        "relationship_ids": ["relationship:mei-ren"],
                    },
                    "temporal_range": {"from_chapter": 1, "to_chapter": 100},
                }
            ],
        },
        contract=contract,
        coverage=coverage,
        policy=policy,
        round_number=1,
        prior_query_fingerprints=(),
    )

    assert plan["round_number"] == 1
    assert plan["queries"][0]["temporal_range"]["to_chapter"] == 100
    assert plan["expansion_plan_fingerprint"].startswith("sha256:")

    invalid = dict(plan["queries"][0])
    invalid["selectors"] = {"asset_version_ids": ["asset-version:arbitrary"]}
    with pytest.raises(KernelError, match="selector"):
        validate_retrieval_expansion_plan(
            raw={
                "contract_version": "retrieval-expansion-plan-v1",
                "queries": [invalid],
            },
            contract=contract,
            coverage=coverage,
            policy=policy,
            round_number=1,
            prior_query_fingerprints=(),
        )

    future = dict(plan["queries"][0])
    future["temporal_range"] = {"from_chapter": 1, "to_chapter": 401}
    with pytest.raises(KernelError, match="accepted boundary"):
        validate_retrieval_expansion_plan(
            raw={
                "contract_version": "retrieval-expansion-plan-v1",
                "queries": [future],
            },
            contract=contract,
            coverage=coverage,
            policy=policy,
            round_number=1,
            prior_query_fingerprints=(),
        )


def test_duplicate_query_and_campaign_hard_bounds_stop_fail_closed() -> None:
    policy = RetrievalCampaignPolicy()
    contract = build_retrieval_coverage_contract(intent=_intent(), memo=_memo())
    coverage = evaluate_retrieval_coverage(contract=contract, documents=[])
    raw = {
        "contract_version": "retrieval-expansion-plan-v1",
        "queries": [
            {
                "query_id": "query:oath",
                "text": "bridge oath witness",
                "reason": "missing evidence",
                "targets": ["fact:fact:oath-origin"],
                "selectors": {},
                "temporal_range": {"from_chapter": 0, "to_chapter": 400},
            }
        ],
    }
    first = validate_retrieval_expansion_plan(
        raw=raw,
        contract=contract,
        coverage=coverage,
        policy=policy,
        round_number=1,
        prior_query_fingerprints=(),
    )
    later = validate_retrieval_expansion_plan(raw=raw, contract=contract, coverage=coverage,
        policy=policy, round_number=4, prior_query_fingerprints=(), existing_query_count=100)
    assert later["round_number"] == 4
    with pytest.raises(KernelError, match="novel query"):
        validate_retrieval_expansion_plan(
            raw=raw,
            contract=contract,
            coverage=coverage,
            policy=policy,
            round_number=2,
            prior_query_fingerprints=(first["queries"][0]["query_fingerprint"],),
        )

    assert decide_retrieval_campaign_transition(
        coverage=coverage,
        policy=policy,
        completed_rounds=3,
        total_queries=3,
        provider_calls=2,
        model_tokens=100,
        cost_amount="0.01",
        last_round_new_evidence=1,
        expansion_available=True,
    ) == {"continue": True, "termination_reason": "CONTINUE"}

    assert decide_retrieval_campaign_transition(
        coverage=coverage,
        policy=policy,
        completed_rounds=2,
        total_queries=1,
        provider_calls=0,
        model_tokens=0,
        cost_amount="0",
        last_round_new_evidence=0,
        expansion_available=True,
    ) == {"continue": False, "termination_reason": "NO_NEW_EVIDENCE"}


def test_round_union_is_order_independent_and_rejects_mutable_identity() -> None:
    older = _document("shared", chapter=30, fact_ids=("fact:oath-origin",))
    replay = dict(older)
    novel = _document("novel", chapter=300)

    first = merge_retrieval_round_documents(((older,), (replay, novel)))
    second = merge_retrieval_round_documents(((novel, replay), (older,)))

    assert first == second
    assert [item["retrieval_document_id"] for item in first] == ["novel", "shared"]

    mutated = dict(older)
    mutated["projection_hash"] = "sha256:" + "9" * 64
    with pytest.raises(KernelError, match="immutable"):
        merge_retrieval_round_documents(((older,), (mutated,)))


def test_generation_consumption_and_unknown_cost_do_not_stop_retrieval_progress():
    policy = RetrievalCampaignPolicy()
    result = decide_retrieval_campaign_transition(coverage={"sufficient": False}, policy=policy,
        completed_rounds=100, total_queries=1000, provider_calls=100, model_tokens=900000,
        cost_amount="UNKNOWN", last_round_new_evidence=1, expansion_available=True)
    assert result == {"continue": True, "termination_reason": "CONTINUE"}
    assert "model_token_limit" not in policy.execution_policy()
    old = RetrievalCampaignPolicy(policy_version="minimum-sufficient-retrieval-campaign-v1")
    assert old.to_dict()["model_token_limit"] == 4096
    assert "model_token_limit" not in old.execution_policy()


def test_unknown_usage_and_mixed_currency_remain_diagnostic():
    from novel_forge.modules.chapter_authority.handlers import _provider_usage, _campaign_usage
    unknown = _provider_usage({"usage": {"measurement": "UNKNOWN"}, "cost": {"currency": "UNKNOWN"}})
    assert unknown["input_tokens"] is None and unknown["cost_amount"] is None and unknown["latency_ms"] is None
    rounds = tuple({"usage": _provider_usage(e), "provider_evidence": e, "documents": []} for e in [
        {"usage": {"input_tokens": 5, "output_tokens": 2}, "cost": {"amount": "10", "currency": "USD"}},
        {"usage": {"input_tokens": 7, "output_tokens": 3}, "cost": {"amount": "20", "currency": "CNY"}},
        {"usage": {"measurement": "UNKNOWN"}, "cost": {"currency": "USD"}}])
    total = _campaign_usage(rounds)
    assert total["model_tokens"] is None and total["cost_amount"] is None and total["currency"] == "MIXED"
    assert total["cost_by_currency"]["USD"] == {"known_amount": "10", "unknown_measurements": 1}
    assert total["cost_by_currency"]["CNY"]["known_amount"] == "20"


def test_query_novelty_cannot_be_faked_by_changing_id_or_reason():
    policy = RetrievalCampaignPolicy()
    contract = build_retrieval_coverage_contract(intent=_intent(), memo=_memo())
    coverage = evaluate_retrieval_coverage(contract=contract, documents=[])
    query = {"query_id": "first", "text": "bridge oath", "reason": "missing", "targets": ["fact:fact:oath-origin"],
        "selectors": {}, "temporal_range": {"from_chapter": 0, "to_chapter": 400}}
    first = validate_retrieval_expansion_plan(raw={"contract_version": "retrieval-expansion-plan-v1", "queries": [query]},
        contract=contract, coverage=coverage, policy=policy, round_number=1, prior_query_fingerprints=())
    with pytest.raises(KernelError, match="novel query"):
        validate_retrieval_expansion_plan(raw={"contract_version": "retrieval-expansion-plan-v1", "queries": [{**query,
            "query_id": "second", "reason": "different prose reason"}]}, contract=contract, coverage=coverage,
            policy=policy, round_number=4, prior_query_fingerprints=(), prior_queries=first["queries"])
    assert decide_retrieval_campaign_transition(coverage=coverage, coverage_before=coverage, policy=policy,
        completed_rounds=2, total_queries=2, provider_calls=1, model_tokens=50, cost_amount="0.01",
        last_round_new_evidence=10, expansion_available=True)["termination_reason"] == "NO_NEW_EVIDENCE"
