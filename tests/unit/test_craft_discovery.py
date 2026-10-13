from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_forge.modules.mkaos_authority.craft import core_catalog, craft_candidate
from novel_forge.modules.source_import.analysis_profiles import (
    analysis_strategy_from_dict, resolve_analysis_strategy, resolve_corpus_analysis_strategy,
)
from novel_forge.modules.source_import.craft_discovery import (
    CRAFT_DISCOVERY_POLICY, CRAFT_DISCOVERY_ROUTING, WRITING_METHODS_ROUTING, WRITING_METHODS_EVIDENCE_ROUTING, craft_discovery_schema,
)
from novel_forge.modules.source_import.execution import PostgresContentIntelligenceExecutionPort
from novel_forge.modules.source_import.execution_contracts import MKAOS_STAGE, validate_content_intelligence_output
from novel_forge.modules.source_import.methodologies import SourceMethodologyRegistry
from novel_forge.modules.source_import.profiling import SourceContentType


def discovered():
    craft = core_catalog()[0]
    craft["mechanism_id"] = "fixture-source-discovery"
    craft["version"] = 1
    craft["schema_version"] = "narrative-craft-mechanism.v1"
    craft.pop("affinity_evidence", None)
    craft["provenance"].update({"origin": "SOURCE_ABSTRACTION", "source_observation_asset_version_ids": ["observation:1"], "abstraction_policy_version": CRAFT_DISCOVERY_POLICY, "confidence": "HYPOTHESIS"})
    return craft_candidate(craft)


def test_new_routing_freezes_discovery_without_changing_legacy_strategy():
    registry = SourceMethodologyRegistry(Path("skills"))
    legacy = resolve_analysis_strategy(SourceContentType.WEB_NOVEL, registry=registry, routing_policy_version="source-analysis-routing.v2")
    strategy = resolve_analysis_strategy(SourceContentType.WEB_NOVEL, registry=registry, routing_policy_version=CRAFT_DISCOVERY_ROUTING)
    assert strategy.abstraction_policy_version == CRAFT_DISCOVERY_POLICY
    assert legacy.abstraction_policy_version == "anti-copy-abstraction.2.0"
    assert strategy.fingerprint != legacy.fingerprint
    assert analysis_strategy_from_dict(legacy.to_dict(), expected_fingerprint=legacy.fingerprint) == legacy
    assert analysis_strategy_from_dict(strategy.to_dict(), expected_fingerprint=strategy.fingerprint) == strategy
    corpus = resolve_corpus_analysis_strategy(SourceContentType.CLASSIC_LITERATURE, collection_kind="LONG_NOVEL", registry=registry, routing_policy_version=CRAFT_DISCOVERY_ROUTING, sample_byte_limit=16000)
    assert corpus.abstraction_policy_version == CRAFT_DISCOVERY_POLICY
    with pytest.raises(ValueError, match="governed fiction"):
        resolve_analysis_strategy(SourceContentType.PLATFORM_RULES, registry=registry, routing_policy_version=CRAFT_DISCOVERY_ROUTING)


def test_writing_methods_are_explicit_and_preserve_original_methodology_replay():
    registry = SourceMethodologyRegistry(Path("skills"))
    original = resolve_analysis_strategy(SourceContentType.WRITING_THEORY, registry=registry, routing_policy_version=CRAFT_DISCOVERY_ROUTING)
    selected = resolve_analysis_strategy(SourceContentType.WRITING_THEORY, registry=registry, routing_policy_version=WRITING_METHODS_ROUTING)
    evidence = resolve_analysis_strategy(SourceContentType.WRITING_THEORY, registry=registry, routing_policy_version=WRITING_METHODS_EVIDENCE_ROUTING)
    assert {item.skill_version for item in original.analyzers} == {"1.1.0"}
    assert {item.skill_version for item in selected.analyzers} == {"1.2.0"}
    assert {item.skill_version for item in evidence.analyzers} == {"1.2.1"}
    assert {item.prompt_version for item in evidence.analyzers} == {"2.1"}
    assert selected.mkaos_capability == "mkaos.knowledge.extract"
    assert selected.abstraction_policy_version == CRAFT_DISCOVERY_POLICY
    assert registry.require("multidisciplinary-knowledge").skill_version == "1.1.0"
    for strategy in (original, selected, evidence):
        assert analysis_strategy_from_dict(strategy.to_dict(), expected_fingerprint=strategy.fingerprint) == strategy
        for analyzer in strategy.analyzers:
            assert registry.require(analyzer.skill_id, expected_digest=analyzer.methodology_content_hash).skill_version == analyzer.skill_version
    with pytest.raises(ValueError, match="writing-theory"):
        resolve_analysis_strategy(SourceContentType.WEB_NOVEL, registry=registry, routing_policy_version=WRITING_METHODS_ROUTING)
    with pytest.raises(ValueError, match="document profile"):
        resolve_corpus_analysis_strategy(SourceContentType.WRITING_THEORY, collection_kind="APHORISM_COLLECTION", registry=registry, routing_policy_version=WRITING_METHODS_ROUTING, sample_byte_limit=16000)


@pytest.mark.parametrize("tamper", ["origin", "confidence", "observation", "evidence", "version"])
def test_discovery_cannot_claim_editorial_reader_or_other_source_evidence(tamper):
    schema = craft_discovery_schema(grounded=False, observation_id="observation:1")
    candidate = discovered()
    validate_content_intelligence_output(MKAOS_STAGE, schema, candidate)
    changed = deepcopy(candidate)
    craft = changed["craft_mechanism"]
    if tamper == "origin":
        craft["provenance"]["origin"] = "REPOSITORY_ORIGINAL"
    elif tamper == "confidence":
        craft["provenance"]["confidence"] = "EDITORIAL_REVIEWED"
    elif tamper == "observation":
        craft["provenance"]["source_observation_asset_version_ids"] = ["unrelated:observation"]
    elif tamper == "evidence":
        craft["effect_evidence"] = [{"kind": "HUMAN_READER", "asset_version_id": "invented", "claim": "works"}]
    else:
        craft["version"] = 2
    with pytest.raises(ValueError):
        validate_content_intelligence_output(MKAOS_STAGE, schema, changed)


def test_real_extraction_entry_uses_strict_contract_and_immutable_observation_reference(monkeypatch):
    port = object.__new__(PostgresContentIntelligenceExecutionPort)
    port.methodology_registry = SourceMethodologyRegistry(Path("skills"))
    seen = []

    def execute(*, worker, spec):
        seen.append(spec)
        return {"result": discovered(), "provider_execution_reused": False}

    monkeypatch.setattr(port, "_execute", execute)
    monkeypatch.setattr(port, "_execution_log", lambda **kwargs: SimpleNamespace(asset_version_id="execution:fixture"))
    output = port.execute_mkaos_extraction(worker=SimpleNamespace(project_id="p"), capability="mkaos.knowledge.extract", abstraction_policy_version=CRAFT_DISCOVERY_POLICY, observation_asset_version_id="observation:1", observation={"findings": [{"finding_code": "FOCUS", "statement": "unprojected-observation-text"}]}, evidence_spans=())
    spec = seen[0]
    assert spec.output_schema == craft_discovery_schema(grounded=False, observation_id="observation:1")
    assert spec.context_contract["source_expression_available"] is False
    assert spec.artifact_version_ids == ("observation:1",)
    assert "unprojected-observation-text" not in str(spec.input_payload)
    assert output["candidate"]["craft_mechanism"]["provenance"]["confidence"] == "HYPOTHESIS"
