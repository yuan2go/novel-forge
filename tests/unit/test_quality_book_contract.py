from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_forge.modules.runtime_proof import (
    BoundedQualityBookContract,
    load_quality_book_contract,
    load_quality_campaign_profile,
)


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "config/proof_campaigns/quality_qualification_v1.json"
BOOK = ROOT / "config/proof_campaigns/quality_qualification_book_v1.json"


def _profile():  # type: ignore[no-untyped-def]
    return load_quality_campaign_profile(PROFILE, repository_root=ROOT)


def test_quality_book_contract_freezes_six_layers_and_bounded_inputs() -> None:
    contract = load_quality_book_contract(BOOK, campaign_profile=_profile())
    payload = contract.to_dict()

    assert payload["book"]["target_chapters"] == 8
    assert len(payload["foundation"]["layers"]) == 6
    assert payload["foundation"]["creative_alternate"]["role"] == (
        "CREATIVE_FOUNDATION"
    )
    assert len(payload["bootstrap_inputs"]) == 17
    assert len(payload["chapter_profiles"]) == 4
    assert contract.digest.startswith("sha256:")


def test_quality_book_contract_rejects_human_claim_or_missing_review_criterion() -> (
    None
):
    payload = json.loads(BOOK.read_text(encoding="utf-8"))
    human_claim = deepcopy(payload)
    human_claim["bootstrap_inputs"]["book.reader_contract.author"]["human_verified"] = (
        True
    )
    with pytest.raises(ValueError, match="source/evidence boundary"):
        BoundedQualityBookContract.from_mapping(
            human_claim,
            campaign_profile=_profile(),
        )

    incomplete = deepcopy(payload)
    incomplete["foundation"]["layers"][0]["review_assertions"].pop(
        "CORE_CONFLICT_CLARITY"
    )
    with pytest.raises(ValueError, match="one substantive assertion"):
        BoundedQualityBookContract.from_mapping(
            incomplete,
            campaign_profile=_profile(),
        )
