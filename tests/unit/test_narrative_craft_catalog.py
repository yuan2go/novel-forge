from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft import (
    CRAFT_FAMILIES, core_catalog, core_catalog_hash, craft_candidate,
    require_core_mechanism, validate_craft_mechanism,
)
from novel_forge.modules.mkaos_authority.domain import validate_knowledge_candidate


def test_catalog_is_diverse_conditioned_original_and_has_no_quality_claims():
    catalog = core_catalog()
    assert 30 <= len(catalog) <= 50
    assert {item["family"] for item in catalog} == CRAFT_FAMILIES
    assert len({item["abstract_mechanism"] for item in catalog}) == len(catalog)
    assert len({item["repair_strategies"][0] for item in catalog}) == len(catalog)
    for mechanism in catalog:
        assert mechanism["provenance"]["origin"] == "REPOSITORY_ORIGINAL"
        assert mechanism["provenance"]["confidence"] == "HYPOTHESIS"
        assert mechanism["effect_evidence"] == []
        assert validate_knowledge_candidate(craft_candidate(mechanism))["craft_mechanism"] == mechanism


def test_catalog_copy_is_not_mutable_shared_state_and_hash_binds_exact_catalog():
    catalog = core_catalog()
    digest = core_catalog_hash()
    catalog[0]["abstract_mechanism"] = "modified"
    assert core_catalog_hash() == digest
    assert require_core_mechanism(catalog[0]["mechanism_id"], digest)["abstract_mechanism"] != "modified"
    with pytest.raises(KernelError, match="reviewed exact catalog"):
        require_core_mechanism(catalog[0]["mechanism_id"], "sha256:" + "0" * 64)


@pytest.mark.parametrize("change", [
    {"version": True}, {"unexpected": "raw"}, {"review_checks": []},
    {"family": "UNIVERSAL_RULE"}, {"version": 0},
    {"provenance": {"origin": "HUMAN_READER_PROVEN"}},
    {"effect_evidence": [{"kind": "EFFECTIVENESS_SCORE", "asset_version_id": "x", "claim": "0.98"}]},
])
def test_invalid_universal_or_unversioned_claims_fail_closed(change):
    candidate = deepcopy(core_catalog()[0])
    candidate.update(change)
    with pytest.raises(KernelError):
        validate_craft_mechanism(candidate)


def test_source_abstraction_requires_observation_and_cannot_smuggle_source():
    candidate = core_catalog()[0]
    candidate["version"] = 1
    candidate["provenance"]["origin"] = "SOURCE_ABSTRACTION"
    with pytest.raises(KernelError):
        validate_craft_mechanism(candidate)
    candidate["provenance"]["source_observation_asset_version_ids"] = ["observation:v1"]
    assert validate_craft_mechanism(candidate)
    candidate["source_text"] = "forbidden"
    with pytest.raises(KernelError):
        validate_craft_mechanism(candidate)


def test_original_revision_template_is_portable_but_source_revision_needs_predecessor():
    template = core_catalog()[0]
    template["version"] = 2
    assert validate_craft_mechanism(template)["provenance"]["supersedes_card_asset_version_id"] == ""
    template["provenance"].update({"origin": "SOURCE_ABSTRACTION", "source_observation_asset_version_ids": ["observation:v1"]})
    with pytest.raises(KernelError, match="preceding governed Card"):
        validate_craft_mechanism(template)
