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
    CRAFT_OUTPUT_CONTRACT, LEGACY_CRAFT_OUTPUT_CONTRACT, validate_discovery_schema,
)
from novel_forge.modules.source_import.execution import PostgresContentIntelligenceExecutionPort
from novel_forge.modules.source_import.execution_contracts import MKAOS_STAGE, validate_content_intelligence_output
from novel_forge.modules.source_import.methodologies import SourceMethodologyRegistry
from novel_forge.modules.source_import.profiling import SourceContentType


@pytest.mark.parametrize("field", ["mkaos_capability", "mkaos_skill_id", "mkaos_skill_version", "mkaos_methodology_content_hash"])
def test_schema_recovery_admission_rejects_method_drift_before_creating_child(field):
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_import.application import SourceImportApplication

    registry = SourceMethodologyRegistry(Path("skills"))
    method = registry.require("anti-copy-abstraction")
    app = SimpleNamespace(methodology_registry=registry)
    payload = {"mkaos_capability": "mkaos.knowledge.extract", "abstraction_policy_version": CRAFT_DISCOVERY_POLICY,
        "mkaos_skill_id": method.skill_id, "mkaos_skill_version": method.skill_version,
        "mkaos_methodology_content_hash": method.content_digest}
    payload[field] = "drift"
    with pytest.raises(KernelError, match="Retain the original abstraction method"):
        SourceImportApplication._admit_mkaos_from_scope(app, project_id="project", parent_operation_id="old",
            trace_id="trace", correlation_id="job", job={}, observation={"observation_asset_version_id": "observation:1"},
            payload=payload, schema_recovery={"original_operation_id": "old"})


def discovered():
    craft = core_catalog()[0]
    craft["mechanism_id"] = "fixture-source-discovery"
    craft["version"] = 1
    craft["schema_version"] = "narrative-craft-mechanism.v1"
    craft.pop("affinity_evidence", None)
    craft["provenance"].update({"origin": "SOURCE_ABSTRACTION", "source_observation_asset_version_ids": ["observation:1"], "abstraction_policy_version": CRAFT_DISCOVERY_POLICY, "confidence": "HYPOTHESIS"})
    return craft_candidate(craft)


def test_completed_composition_projection_preserves_guidance_and_provider_original():
    from novel_forge.modules.source_import.abstraction_recovery import project_invalid_composition
    from novel_forge.modules.command_kernel.errors import KernelError

    original = discovered()
    original["craft_mechanism"]["composition"]["requires"] = ["An explanation rather than a mechanism ID", "valid-other-method"]
    frozen = deepcopy(original)
    projected, receipt = project_invalid_composition(original)
    assert original == frozen
    assert projected["craft_mechanism"]["composition"]["requires"] == ["valid-other-method"]
    restored = deepcopy(projected)
    restored["craft_mechanism"]["composition"] = original["craft_mechanism"]["composition"]
    assert restored == original
    assert receipt["new_model_calls"] == 0
    assert receipt["removed_relationship_claims"] == [{"field": "requires", "index": 0, "value": "An explanation rather than a mechanism ID"}]
    projected["craft_mechanism"]["composition"] = {key: [] for key in projected["craft_mechanism"]["composition"]}
    with pytest.raises(KernelError, match="Require invalid relationship references"):
        project_invalid_composition(projected)


@pytest.mark.parametrize("drift", [None, "effect", "projection"])
def test_completed_composition_execution_uses_exact_receipt_without_new_model_call(monkeypatch, drift):
    from novel_forge.modules.source_import.abstraction_recovery import project_invalid_composition
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_authority.corpus import corpus_hash

    port = object.__new__(PostgresContentIntelligenceExecutionPort)
    port.database_url = "fixture"
    port.methodology_registry = SourceMethodologyRegistry(Path("skills"))
    from novel_forge.modules.source_import.corpus_ingestion import curated_analysis
    monkeypatch.setattr(curated_analysis, "curated_provider_gate", lambda *args: {})
    original = discovered()
    original["craft_mechanism"]["composition"]["requires"] = ["Unsupported prose as a reference"]
    projected, projection = project_invalid_composition(original)
    repair = {"contract_version": "source-abstraction-composition-recovery.v1", "original_external_effect_id": "original-effect",
        "original_cache_key": "original-cache", "composition_projection": projection}
    if drift == "projection":
        repair["composition_projection"] = {**projection, "projected_result_hash": "changed"}
    seen = []
    monkeypatch.setattr(port, "_replay_succeeded_effect", lambda **kwargs: {"result": original, "provider_execution_reused": True,
        "reused_external_effect_id": "changed" if drift == "effect" else "original-effect"})
    monkeypatch.setattr(port, "_execute", lambda **kwargs: pytest.fail("Completed-result recovery cannot invoke a Provider"))
    monkeypatch.setattr(port, "_execution_log", lambda **kwargs: seen.append(kwargs) or SimpleNamespace(asset_version_id="reused-log"))
    contract = {"version": CRAFT_OUTPUT_CONTRACT, "observation_asset_version_id": "observation:1",
        "output_schema_hash": corpus_hash(craft_discovery_schema(grounded=False, observation_id="observation:1"))}
    args = dict(worker=SimpleNamespace(project_id="project"), capability="mkaos.knowledge.extract",
        abstraction_policy_version=CRAFT_DISCOVERY_POLICY, observation_asset_version_id="observation:1",
        observation={"findings": [{"finding_code": "F", "statement": "source assessment"}]}, evidence_spans=(),
        output_contract=contract, completed_result_repair=repair)
    if drift:
        with pytest.raises(KernelError):
            port.execute_mkaos_extraction(**args)
        assert not seen
    else:
        result = port.execute_mkaos_extraction(**args)
        assert result["candidate"] == projected
        assert result["provider_execution_reused"] is True
        assert seen[0]["domain_binding"]["source_output_projection"] == projection
        assert original["craft_mechanism"]["composition"]["requires"] == ["Unsupported prose as a reference"]


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
    from novel_forge.modules.source_authority.corpus import corpus_hash
    port = object.__new__(PostgresContentIntelligenceExecutionPort)
    port.methodology_registry = SourceMethodologyRegistry(Path("skills"))
    seen = []

    def execute(*, worker, spec):
        seen.append(spec)
        return {"result": discovered(), "provider_execution_reused": False}

    monkeypatch.setattr(port, "_execute", execute)
    monkeypatch.setattr(port, "_execution_log", lambda **kwargs: SimpleNamespace(asset_version_id="execution:fixture"))
    contract = {"version": CRAFT_OUTPUT_CONTRACT, "observation_asset_version_id": "observation:1",
        "output_schema_hash": corpus_hash(craft_discovery_schema(grounded=False, observation_id="observation:1"))}
    output = port.execute_mkaos_extraction(worker=SimpleNamespace(project_id="p"), capability="mkaos.knowledge.extract", abstraction_policy_version=CRAFT_DISCOVERY_POLICY, observation_asset_version_id="observation:1", observation={"findings": [{"finding_code": "FOCUS", "statement": "unprojected-observation-text"}]}, evidence_spans=(), output_contract=contract)
    spec = seen[0]
    assert spec.output_schema == craft_discovery_schema(grounded=False, observation_id="observation:1")
    assert spec.context_contract["source_expression_available"] is False
    assert spec.artifact_version_ids == ("observation:1",)
    assert "unprojected-observation-text" not in str(spec.input_payload)
    assert output["candidate"]["craft_mechanism"]["provenance"]["confidence"] == "HYPOTHESIS"
    assert spec.input_payload["craft_output_contract"]["version"] == CRAFT_OUTPUT_CONTRACT
    assert spec.context_contract["craft_output_contract"] == spec.input_payload["craft_output_contract"]


def test_supported_wire_schema_preserves_exact_source_array_and_legacy_validation():
    from novel_forge.modules.production_execution.codex_configuration import codex_output_schema

    current = craft_discovery_schema(grounded=False, observation_id="observation:1")
    legacy = craft_discovery_schema(grounded=False, observation_id="observation:1", contract_version=LEGACY_CRAFT_OUTPUT_CONTRACT)
    assert current != legacy
    for schema in (current, legacy):
        assert validate_discovery_schema(schema)
        validate_content_intelligence_output(MKAOS_STAGE, schema, discovered())
        for ids in ([], ["other"], ["observation:1", "observation:1"]):
            bad = discovered()
            bad["craft_mechanism"]["provenance"]["source_observation_asset_version_ids"] = ids
            with pytest.raises(ValueError):
                validate_content_intelligence_output(MKAOS_STAGE, schema, bad)
    field = codex_output_schema(current)["properties"]["craft_mechanism"]["properties"]["provenance"]["properties"]["source_observation_asset_version_ids"]
    assert "const" not in field
    assert field["items"]["const"] == "observation:1"
    assert field["minItems"] == field["maxItems"] == 1


def test_legacy_mkaos_execution_keeps_old_schema_and_cache_inputs(monkeypatch):
    from novel_forge.modules.source_authority.corpus import corpus_hash

    port = object.__new__(PostgresContentIntelligenceExecutionPort)
    port.methodology_registry = SourceMethodologyRegistry(Path("skills"))
    seen = []
    monkeypatch.setattr(port, "_execute", lambda **kwargs: seen.append(kwargs["spec"]) or {"result": discovered(), "provider_execution_reused": False})
    monkeypatch.setattr(port, "_execution_log", lambda **kwargs: SimpleNamespace(asset_version_id="execution:fixture"))
    schema = craft_discovery_schema(grounded=False, observation_id="observation:1", contract_version=LEGACY_CRAFT_OUTPUT_CONTRACT)
    contract = {"version": LEGACY_CRAFT_OUTPUT_CONTRACT, "observation_asset_version_id": "observation:1", "output_schema_hash": corpus_hash(schema)}
    args = dict(worker=SimpleNamespace(project_id="p"), capability="mkaos.knowledge.extract", abstraction_policy_version=CRAFT_DISCOVERY_POLICY,
        observation_asset_version_id="observation:1", observation={"findings": [{"finding_code": "FOCUS", "statement": "abstract"}]}, evidence_spans=())
    port.execute_mkaos_extraction(**args, output_contract=contract)
    assert seen[0].output_schema == schema
    assert "craft_output_contract" not in seen[0].input_payload
    assert "craft_output_contract" not in seen[0].context_contract
    with pytest.raises(Exception, match="SOURCE_CRAFT_OUTPUT_CONTRACT_DRIFT"):
        port.execute_mkaos_extraction(**args, output_contract={**contract, "output_schema_hash": "wrong"})
