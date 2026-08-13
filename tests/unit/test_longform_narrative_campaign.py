from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_forge.modules.runtime_proof import (
    LongformCampaignContract,
    contract_identity,
    evaluate_proof_language,
    load_campaign_contract,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config" / "proof_campaigns" / "longform_narrative_v1.json"
CANONICAL_CONTRACT_PATH = (
    ROOT / "config" / "proof_campaigns" / "longform_narrative_v2.json"
)


def _minimal_contract() -> dict[str, object]:
    return {
        "schema_version": "novel-forge.longform-proof-contract.v1",
        "campaign_id": "longform-narrative-v1",
        "campaign_version": 1,
        "baseline_git_sha": "3d89e805175ccb4a40c208ce434ed3fe946b38d0",
        "migration_head": "20260812_0086_corrective_generation_terminal_lineage",
        "book": {
            "title": "The Ledger Under Rain",
            "language": "zh-CN",
            "target_chapters": 300,
            "volumes": [
                {
                    "volume": volume,
                    "title": f"Volume {volume}",
                    "goal": f"Goal {volume}",
                    "pressure": f"Pressure {volume}",
                    "reward": f"Reward {volume}",
                    "cost": f"Cost {volume}",
                    "ending_escalation": f"Escalation {volume}",
                }
                for volume in range(1, 11)
            ],
            "chapter_pattern": [
                {
                    "offset": offset,
                    "function": f"beat-{offset}",
                    "pressure_delta": f"pressure-{offset}",
                    "information_gain": f"information-{offset}",
                    "hook": f"hook-{offset}",
                }
                for offset in range(1, 31)
            ],
        },
        "ground_truth": {
            "world_rules": [
                {
                    "fact_id": "rule:revision-traces",
                    "statement": "Revisions leave traces.",
                }
            ],
            "characters": [{"character_id": "lin-qiao", "name": "Lin Qiao"}],
            "knowledge_matrix": [
                {
                    "fact_id": "fact:living-witness",
                    "holder": "lin-qiao",
                    "known_from_chapter": 1,
                }
            ],
            "obligations": [
                {
                    "obligation_id": "obligation:living-witness",
                    "setup_chapter": 1,
                    "payoff_chapter": 90,
                    "setup": "A living witness is listed as dead.",
                    "payoff": "The witness testifies under her own name.",
                }
            ],
            "state_checkpoints": [
                {"chapter": 30, "expected": ["checkpoint-30"]},
                {"chapter": 100, "expected": ["checkpoint-100"]},
                {"chapter": 300, "expected": ["checkpoint-300"]},
            ],
            "context_probes": [
                {
                    "probe_id": "probe:living-witness:30",
                    "chapter": 30,
                    "must_include": ["fact:living-witness"],
                    "must_exclude": [],
                }
            ],
        },
        "proof_thresholds": {
            "checkpoint_chapters": [30, 100, 300],
            "minimum_chapter_characters": 1200,
            "maximum_duplicate_logical_chapters": 0,
            "maximum_future_context_items": 0,
            "minimum_context_precision": 0.9,
            "minimum_context_recall": 0.9,
        },
        "provider": {
            "provider": "codex-cli",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "silent_fallback": False,
        },
        "runtime_bindings": {
            "capability_pack_id": "chapter_generation_pack",
            "capability_pack_version": "1.1.0",
            "capability_pack_manifest_hash": "sha256:" + "a" * 64,
            "skill_bindings": [
                {
                    "skill_ref": "prose-generation",
                    "version": "prose-generation-v1",
                    "content_hash": "sha256:" + "b" * 64,
                }
            ],
            "mkaos_policy_version": "mkaos-proof-policy-v1",
        },
        "freeze_policy": {
            "ground_truth_mutable_after_chapter_1": False,
            "thresholds_mutable_after_chapter_1": False,
            "material_change_requires_new_campaign_version": True,
        },
    }


def test_contract_expands_one_frozen_book_to_three_hundred_chapters() -> None:
    contract = LongformCampaignContract.from_mapping(_minimal_contract())

    assert contract.target_chapters == 300
    assert [row["chapter"] for row in contract.chapter_matrix] == list(range(1, 301))
    assert contract.chapter_matrix[29]["volume"] == 1
    assert contract.chapter_matrix[30]["volume"] == 2
    assert contract.checkpoint_chapters == (30, 100, 300)
    assert contract_identity(contract).startswith("sha256:")


def test_contract_rejects_mutable_ground_truth_or_thresholds() -> None:
    payload = _minimal_contract()
    payload["freeze_policy"]["ground_truth_mutable_after_chapter_1"] = True

    with pytest.raises(
        ValueError, match="Ground Truth and thresholds must be immutable"
    ):
        LongformCampaignContract.from_mapping(payload)


def test_contract_requires_the_frozen_simplified_chinese_language() -> None:
    payload = _minimal_contract()
    payload["book"]["language"] = "en-US"

    with pytest.raises(ValueError, match="book.language must equal zh-CN"):
        LongformCampaignContract.from_mapping(payload)


def test_proof_language_gate_accepts_primarily_chinese_prose() -> None:
    result = evaluate_proof_language(
        "林乔把旧账册压在桌上，逐页核对未曾改变的编号。Ledger 17仍在原处，她抬头看向证人。",
        required_language="zh-CN",
    )

    assert result["status"] == "PASSED"
    assert result["required_language"] == "zh-CN"
    assert result["han_character_ratio"] >= 0.6


def test_proof_language_gate_rejects_english_prose() -> None:
    result = evaluate_proof_language(
        "Lin Qiao put the ledger on the table and asked the witness to sign it.",
        required_language="zh-CN",
    )

    assert result["status"] == "FAILED"
    assert result["reason"] == "PROSE_NOT_PRIMARILY_ZH_CN"


def test_contract_rejects_non_contiguous_pattern_and_invalid_obligation_window() -> (
    None
):
    payload = _minimal_contract()
    payload["book"]["chapter_pattern"][9]["offset"] = 11

    with pytest.raises(ValueError, match="chapter_pattern offsets"):
        LongformCampaignContract.from_mapping(payload)

    payload = _minimal_contract()
    payload["ground_truth"]["obligations"][0]["payoff_chapter"] = 1
    with pytest.raises(ValueError, match="obligation payoff"):
        LongformCampaignContract.from_mapping(payload)


def test_contract_rejects_future_fact_in_must_include_context() -> None:
    payload = _minimal_contract()
    payload["ground_truth"]["knowledge_matrix"].append(
        {
            "fact_id": "fact:future-confession",
            "holder": "lin-qiao",
            "known_from_chapter": 80,
        }
    )
    payload["ground_truth"]["context_probes"][0]["must_include"].append(
        "fact:future-confession"
    )

    with pytest.raises(ValueError, match="future knowledge"):
        LongformCampaignContract.from_mapping(payload)


def test_repository_contract_has_stable_declared_identity() -> None:
    contract = load_campaign_contract(CONTRACT_PATH)
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert contract.campaign_id == "longform-narrative-v1"
    assert len(contract.chapter_matrix) == 300
    assert contract_identity(contract) == raw["contract_identity"]

    drifted = deepcopy(raw)
    drifted["proof_thresholds"]["minimum_context_recall"] = 0.5
    drifted.pop("contract_identity")
    assert (
        contract_identity(LongformCampaignContract.from_mapping(drifted))
        != raw["contract_identity"]
    )


def test_canonical_architecture_campaign_versions_the_frozen_contract() -> None:
    contract = load_campaign_contract(CANONICAL_CONTRACT_PATH)
    raw = json.loads(CANONICAL_CONTRACT_PATH.read_text(encoding="utf-8"))

    assert contract.campaign_id == "longform-narrative-v2"
    assert contract.campaign_version == 2
    assert contract.migration_head == "20260814_0088_canonical_narrative_architecture"
    assert raw["runtime_bindings"]["capability_pack_version"] == "1.3.0"
    assert contract_identity(contract) == raw["contract_identity"]
