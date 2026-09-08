from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
from pathlib import Path

import pytest

from novel_forge.modules.source_import import analysis_profiles
from novel_forge.modules.source_import.analysis_profiles import (
    analysis_strategy_from_dict,
    plan_analysis_tasks,
    resolve_analysis_strategy,
    resolve_corpus_analysis_strategy,
)
from novel_forge.modules.source_import.domain import SourceImportPolicy
from novel_forge.modules.source_import.methodologies import SourceMethodologyRegistry
from novel_forge.modules.source_import.profiling import (
    ClassificationSample,
    LogicalDocumentScope,
    SourceAnalysisOverride,
    SourceContentType,
    SOURCE_WORK_AGGREGATE_BOUNDARY,
    SourceIntelligencePolicy,
    build_classification_evidence,
    resolve_profile,
)


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills"


def _scope() -> LogicalDocumentScope:
    return LogicalDocumentScope(
        scope_kind="FILE_DOCUMENT",
        source_document_id="source-document:project:abc",
        source_transform_id="source-transform:project:def",
        source_chunk_asset_version_ids=("source-chunk:project:def:0:v1",),
        boundary_policy_version="file-logical-document.v1",
        label="governed document 1",
    )


def _classification(
    content_type: str, confidence: float, second: float = 0.1
) -> dict[str, object]:
    alternative_type = (
        "PROFESSIONAL_KNOWLEDGE" if content_type == "UNKNOWN" else "UNKNOWN"
    )
    return {
        "content_type": content_type,
        "confidence": confidence,
        "alternatives": [
            {"content_type": content_type, "confidence": confidence},
            {"content_type": alternative_type, "confidence": second},
        ],
        "evidence_codes": ["STRUCTURE", "SEMANTIC_SAMPLE"],
        "boundary_assessment": {
            "scope_kind": "FILE_DOCUMENT",
            "suspected_document_count": 1,
            "review_required": False,
        },
    }


def test_source_identity_policy_contains_no_analysis_semantics() -> None:
    policy = SourceImportPolicy()
    serialized = asdict(policy)
    assert "analysis_profile" not in serialized
    assert not any(
        marker in policy.policy_hash
        for marker in ("classifier", "methodology", "skill")
    )
    assert SourceIntelligencePolicy().policy_hash != policy.policy_hash


def test_routing_policy_changes_analysis_but_not_profiling_identity() -> None:
    baseline = SourceIntelligencePolicy()
    changed = replace(baseline, routing_policy_version="source-analysis-routing.v99")

    assert changed.policy_hash != baseline.policy_hash
    assert changed.profiling_policy_hash == baseline.profiling_policy_hash
    assert changed.classifier_contract_hash == baseline.classifier_contract_hash


def test_logical_document_scope_is_not_implicitly_a_book() -> None:
    scope = _scope()
    assert scope.scope_kind == "FILE_DOCUMENT"
    assert "BOOK" not in scope.to_dict().values()
    assert scope.scope_hash.startswith("sha256:")


def test_classification_evidence_is_bounded_and_contains_no_source_text() -> None:
    scope = _scope()
    content = (
        "# Distributed Systems\n"
        "A quorum constrains which failures a service can tolerate.\n"
        "## Review checks\n"
        "Verify the consistency model before assuming availability.\n"
    )
    evidence = build_classification_evidence(
        scope=scope,
        path_hints=("library/notes.md",),
        source_segments=(
            {
                "source_chunk_asset_version_id": scope.source_chunk_asset_version_ids[
                    0
                ],
                "content": content,
                "content_hash": "sha256:"
                + hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "byte_size": len(content.encode("utf-8")),
            },
        ),
        policy=SourceIntelligencePolicy(max_sample_bytes_per_chunk=128),
    )
    payload = evidence.to_dict()
    assert payload["signals"]["heading_count"] == 2
    assert payload["path_hints"] == ["library", "notes", "md"]
    assert len(payload["samples"]) == 1
    assert payload["samples"][0]["byte_end"] <= 128
    assert "Distributed Systems" not in str(payload)


def test_classification_signal_boundary_may_end_before_a_chinese_character() -> None:
    scope = LogicalDocumentScope(
        scope_kind="FILE_DOCUMENT",
        source_document_id="source-document:project:utf8",
        source_transform_id="source-transform:project:utf8",
        source_chunk_asset_version_ids=(
            "source-chunk:project:utf8:0:v1",
            "source-chunk:project:utf8:1:v1",
        ),
        boundary_policy_version="file-logical-document.v1",
        label="governed UTF-8 boundary fixture",
    )
    contents = ("a", "中文正文")
    segments = tuple(
        {
            "source_chunk_asset_version_id": chunk_id,
            "content": content,
            "content_hash": "sha256:"
            + hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "byte_size": len(content.encode("utf-8")),
        }
        for chunk_id, content in zip(
            scope.source_chunk_asset_version_ids, contents, strict=True
        )
    )

    evidence = build_classification_evidence(
        scope=scope,
        path_hints=("中文/作品.json",),
        source_segments=segments,
        policy=SourceIntelligencePolicy(max_signal_bytes=2),
    )

    assert evidence.signals["total_bytes"] == 13
    assert len(evidence.samples) == 2


def test_low_confidence_unknown_and_boundary_review_fail_closed() -> None:
    policy = SourceIntelligencePolicy(min_confidence=0.75, min_margin=0.2)
    low = resolve_profile(
        classifier_output=_classification("PROFESSIONAL_KNOWLEDGE", 0.6, 0.3),
        policy=policy,
    )
    unknown = resolve_profile(
        classifier_output=_classification("UNKNOWN", 0.98, 0.01),
        policy=policy,
    )
    boundary = _classification("PUBLISHED_FICTION", 0.95, 0.01)
    boundary["boundary_assessment"]["review_required"] = True  # type: ignore[index]
    composite = resolve_profile(classifier_output=boundary, policy=policy)
    assert (low.status, unknown.status, composite.status) == (
        "NEEDS_REVIEW",
        "NEEDS_REVIEW",
        "NEEDS_REVIEW",
    )
    assert all(item.manual_review_required for item in (low, unknown, composite))


def test_governance_override_is_explicit_and_does_not_hide_prediction() -> None:
    resolution = resolve_profile(
        classifier_output=_classification("MIXED", 0.91, 0.05),
        policy=SourceIntelligencePolicy(),
        override=SourceAnalysisOverride(
            logical_document_scope_hash="sha256:" + "a" * 64,
            content_type=SourceContentType.WRITING_THEORY,
            reason="operator separated the imported appendix from the main argument",
            decision_ref="review-issue:source-profile:42",
        ),
    )
    assert resolution.status == "ROUTABLE"
    assert resolution.predicted_content_type == SourceContentType.MIXED
    assert resolution.resolved_content_type == SourceContentType.WRITING_THEORY
    assert resolution.resolution_mode == "GOVERNANCE_OVERRIDE"
    assert resolution.override_decision_ref == "review-issue:source-profile:42"


def test_governance_override_requires_an_exact_logical_document_target() -> None:
    with pytest.raises(ValueError, match="scope hash"):
        SourceAnalysisOverride(
            logical_document_scope_hash="repository-wide",
            content_type=SourceContentType.WRITING_THEORY,
            reason="operator reviewed this document against the governed taxonomy",
            decision_ref="review-issue:source-profile:invalid-target",
        )


def test_content_override_cannot_bypass_unresolved_document_boundary() -> None:
    output = _classification("MIXED", 0.91, 0.05)
    output["boundary_assessment"]["review_required"] = True  # type: ignore[index]
    output["boundary_assessment"]["suspected_document_count"] = 2  # type: ignore[index]
    resolution = resolve_profile(
        classifier_output=output,
        policy=SourceIntelligencePolicy(),
        override=SourceAnalysisOverride(
            logical_document_scope_hash="sha256:" + "b" * 64,
            content_type=SourceContentType.WRITING_THEORY,
            reason="operator identified the dominant content type for later analysis",
            decision_ref="review-issue:source-boundary:43",
        ),
    )
    assert resolution.status == "NEEDS_REVIEW"
    assert resolution.resolved_content_type == SourceContentType.UNKNOWN
    assert resolution.resolution_mode == "GOVERNANCE_OVERRIDE"
    assert resolution.manual_review_required


def test_exact_source_work_aggregate_boundary_decision_can_route() -> None:
    output = _classification("CLASSIC_LITERATURE", 0.99, 0.01)
    output["boundary_assessment"]["review_required"] = True  # type: ignore[index]
    output["boundary_assessment"]["suspected_document_count"] = 40  # type: ignore[index]
    override = SourceAnalysisOverride(
        logical_document_scope_hash="sha256:" + "c" * 64,
        content_type=SourceContentType.CLASSIC_LITERATURE,
        reason="the governed SourceWork manifest confirms forty chapter units",
        decision_ref="experimental-policy:source-work-boundary:40",
        boundary_resolution=SOURCE_WORK_AGGREGATE_BOUNDARY,
        expected_document_count=40,
    )

    resolution = resolve_profile(
        classifier_output=output,
        policy=SourceIntelligencePolicy(),
        override=override,
    )
    mismatched = resolve_profile(
        classifier_output=output,
        policy=SourceIntelligencePolicy(),
        override=replace(override, expected_document_count=39),
    )

    assert resolution.status == "ROUTABLE"
    assert resolution.resolved_content_type == SourceContentType.CLASSIC_LITERATURE
    assert resolution.reasons == (
        "SOURCE_WORK_AGGREGATE_BOUNDARY_CONFIRMED_BY_GOVERNANCE",
    )
    assert mismatched.status == "NEEDS_REVIEW"
    assert "LOGICAL_DOCUMENT_BOUNDARY_REVIEW_REQUIRED" in mismatched.reasons


def test_heterogeneous_content_routes_to_exact_different_skill_methodologies() -> None:
    registry = SourceMethodologyRegistry(SKILL_ROOT)
    fiction = resolve_analysis_strategy(
        SourceContentType.PUBLISHED_FICTION,
        registry=registry,
        routing_policy_version="source-analysis-routing.v2",
    )
    professional = resolve_analysis_strategy(
        SourceContentType.PROFESSIONAL_KNOWLEDGE,
        registry=registry,
        routing_policy_version="source-analysis-routing.v2",
    )
    assert {item.skill_id for item in fiction.analyzers} == {
        "published-fiction-craft-analysis"
    }
    assert {item.skill_id for item in professional.analyzers} == {
        "multidisciplinary-knowledge"
    }
    fiction_methodology = registry.require("published-fiction-craft-analysis")
    professional_methodology = registry.require("multidisciplinary-knowledge")
    assert fiction_methodology.content_digest != professional_methodology.content_digest
    assert "scene objective" in fiction_methodology.content.lower()
    assert "可信度规则" in professional_methodology.content
    assert all(
        item.methodology_content_hash == fiction_methodology.content_digest
        for item in fiction.analyzers
    )


@pytest.mark.parametrize(
    ("content_type", "expected_skills"),
    (
        (
            "WEB_NOVEL",
            {"hot-novel-deconstruction", "hot-novel-business-deconstruction"},
        ),
        ("PUBLISHED_FICTION", {"published-fiction-craft-analysis"}),
        ("CLASSIC_LITERATURE", {"classic-literary-depth-analysis"}),
        ("WRITING_THEORY", {"multidisciplinary-knowledge"}),
        ("PROFESSIONAL_KNOWLEDGE", {"multidisciplinary-knowledge"}),
        ("HISTORY_SOCIAL_SCIENCE", {"multidisciplinary-knowledge"}),
        (
            "BIOGRAPHY_MEMOIR",
            {"published-fiction-craft-analysis", "multidisciplinary-knowledge"},
        ),
        ("PHILOSOPHY_ESSAY", {"multidisciplinary-knowledge"}),
        ("PLATFORM_RULES", {"platform-strategy-os"}),
    ),
)
def test_every_routable_source_type_resolves_governed_skills(
    content_type: str, expected_skills: set[str]
) -> None:
    strategy = resolve_analysis_strategy(
        SourceContentType(content_type),
        registry=SourceMethodologyRegistry(SKILL_ROOT),
        routing_policy_version="source-analysis-routing.v2",
    )
    assert {item.skill_id for item in strategy.analyzers} == expected_skills


@pytest.mark.parametrize("content_type", ("UNKNOWN", "MIXED"))
def test_unroutable_source_types_have_no_fallback_strategy(content_type: str) -> None:
    with pytest.raises(ValueError, match="not routable"):
        resolve_analysis_strategy(
            SourceContentType(content_type),
            registry=SourceMethodologyRegistry(SKILL_ROOT),
            routing_policy_version="source-analysis-routing.v2",
        )


def test_missing_mkaos_capability_blocks_strategy_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_type = SourceContentType.PLATFORM_RULES
    monkeypatch.setitem(
        analysis_profiles._PROFILES,
        content_type,
        replace(
            analysis_profiles._PROFILES[content_type],
            mkaos_capability="source.missing",
        ),
    )
    with pytest.raises(ValueError, match="not governed"):
        resolve_analysis_strategy(
            content_type,
            registry=SourceMethodologyRegistry(SKILL_ROOT),
            routing_policy_version="source-analysis-routing.v2",
        )


def test_methodology_digest_changes_analyzer_and_task_identity() -> None:
    registry = SourceMethodologyRegistry(SKILL_ROOT)
    strategy = resolve_analysis_strategy(
        SourceContentType.PLATFORM_RULES,
        registry=registry,
        routing_policy_version="source-analysis-routing.v2",
    )
    changed = replace(
        strategy.analyzers[0], methodology_content_hash="sha256:" + "f" * 64
    )
    assert changed.fingerprint != strategy.analyzers[0].fingerprint
    chunks = (
        {
            "asset_version_id": _scope().source_chunk_asset_version_ids[0],
            "chunk_index": 0,
        },
    )
    first = plan_analysis_tasks(
        strategy=strategy,
        logical_document_scope=_scope(),
        analysis_plan_asset_version_id="source-analysis-plan:one:v1",
        chunks=chunks,
    )
    changed_strategy = replace(strategy, analyzers=(changed, *strategy.analyzers[1:]))
    second = plan_analysis_tasks(
        strategy=changed_strategy,
        logical_document_scope=_scope(),
        analysis_plan_asset_version_id="source-analysis-plan:two:v1",
        chunks=chunks,
    )
    assert first[0].stable_key != second[0].stable_key


def test_classical_long_novel_uses_one_compound_stratified_task() -> None:
    chunks = tuple(
        {
            "asset_version_id": f"source-chunk:classical:{index}:v1",
            "chunk_index": index,
            "byte_size": 100,
            "content_hash": "sha256:" + f"{index:064x}",
            "source_byte_start": index * 100,
            "source_byte_end": (index + 1) * 100,
        }
        for index in range(12)
    )
    scope = LogicalDocumentScope(
        scope_kind="FILE_DOCUMENT",
        source_document_id="source-document:classical:novel",
        source_transform_id="source-transform:classical:novel",
        source_chunk_asset_version_ids=tuple(
            str(item["asset_version_id"]) for item in chunks
        ),
        boundary_policy_version="file-logical-document.v1",
        label="governed classical novel",
    )
    units = tuple(
        {
            "ordinal": index + 1,
            "kind": "CHAPTER",
            "title": f"Chapter {index + 1}",
            "normalized_byte_start": index * 100,
            "normalized_byte_end": (index + 1) * 100,
            "status": "AVAILABLE",
        }
        for index in range(12)
    )
    strategy = resolve_corpus_analysis_strategy(
        SourceContentType.CLASSIC_LITERATURE,
        collection_kind="LONG_NOVEL",
        registry=SourceMethodologyRegistry(SKILL_ROOT),
        routing_policy_version="source-analysis-routing.v2",
        sample_byte_limit=107_504,
    )

    tasks = plan_analysis_tasks(
        strategy=strategy,
        logical_document_scope=scope,
        analysis_plan_asset_version_id="source-analysis-plan:classical:v1",
        chunks=chunks,
        source_units=units,
        collection_kind="LONG_NOVEL",
    )

    assert len(tasks) == 1
    assert len(tasks[0].compound_analyzers) == 7
    assert {item.dimension for item in tasks[0].compound_analyzers} >= {
        "structure",
        "character_choice_cost",
        "foreshadowing_payoff",
    }
    assert [
        sample["role"] for sample in tasks[0].sampling_manifest["samples"]
    ] == [
        "OPENING_CONTINUOUS_WINDOW",
        "MIDDLE_CONTINUOUS_WINDOW",
        "ENDING_CONTINUOUS_WINDOW",
        "COMPLETE_CONFLICT_UNIT",
    ]
    assert tasks[0].sampling_manifest["whole_work_analyzed"] is False
    assert tasks[0].sampling_manifest["coverage_claim"] == (
        "BOUNDED_STRATIFIED_SAMPLE"
    )


def test_short_story_sampling_keeps_complete_units_within_provider_budget() -> None:
    sizes = (62_579, 50_653, 56_384)
    starts = (0, sizes[0], sizes[0] + sizes[1])
    chunks = tuple(
        {
            "asset_version_id": f"source-chunk:stories:{index}:v1",
            "chunk_index": index,
            "byte_size": size,
            "content_hash": "sha256:" + f"{index:064x}",
            "source_byte_start": starts[index],
            "source_byte_end": starts[index] + size,
        }
        for index, size in enumerate(sizes)
    )
    scope = LogicalDocumentScope(
        scope_kind="FILE_DOCUMENT",
        source_document_id="source-document:classical:stories",
        source_transform_id="source-transform:classical:stories",
        source_chunk_asset_version_ids=tuple(
            str(item["asset_version_id"]) for item in chunks
        ),
        boundary_policy_version="file-logical-document.v1",
        label="governed classical story collection",
    )
    units = tuple(
        {
            "ordinal": index + 1,
            "kind": "STORY",
            "title": f"Story {index + 1}",
            "normalized_byte_start": starts[index],
            "normalized_byte_end": starts[index] + size,
            "status": "AVAILABLE",
        }
        for index, size in enumerate(sizes)
    )
    strategy = resolve_corpus_analysis_strategy(
        SourceContentType.CLASSIC_LITERATURE,
        collection_kind="SHORT_STORY_COLLECTION",
        registry=SourceMethodologyRegistry(SKILL_ROOT),
        routing_policy_version="source-analysis-routing.v2",
        sample_byte_limit=107_504,
    )

    task = plan_analysis_tasks(
        strategy=strategy,
        logical_document_scope=scope,
        analysis_plan_asset_version_id="source-analysis-plan:stories:v1",
        chunks=chunks,
        source_units=units,
        collection_kind="SHORT_STORY_COLLECTION",
    )[0]

    assert task.sampling_manifest["sampled_source_unit_ordinals"] == [2, 3]
    assert task.sampling_manifest["sampled_byte_count"] == 107_037
    assert task.sampling_manifest["sample_byte_limit"] == 107_504
    assert all(item["complete_unit"] for item in task.sampling_manifest["samples"])


def test_analysis_strategy_fingerprint_freezes_every_invalidation_dimension() -> None:
    strategy = resolve_analysis_strategy(
        SourceContentType.PLATFORM_RULES,
        registry=SourceMethodologyRegistry(SKILL_ROOT),
        routing_policy_version="source-analysis-routing.v2",
    )
    analyzer = strategy.analyzers[0]

    variants = (
        replace(strategy, content_type=SourceContentType.PROFESSIONAL_KNOWLEDGE),
        replace(strategy, profile_id="platform_rules_changed"),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, methodology_content_hash="sha256:" + "f" * 64),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, skill_version="99.0.0"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, analyzer_id="source.platform-policy.changed"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, analyzer_version="99.0.0"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, prompt_id="source.platform-policy.changed"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, prompt_version="99.0.0"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, schema_version="source.changed.v99"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, capability_id="source.platform.changed"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, capability_version="99.0.0"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, provider_policy_version="99.0.0"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, aggregation_policy_version="99.0.0"),
                *strategy.analyzers[1:],
            ),
        ),
        replace(
            strategy,
            analyzers=(
                replace(analyzer, recommended_scales=("DOCUMENT_SECTION",)),
                *strategy.analyzers[1:],
            ),
        ),
        replace(strategy, profile_version="99.0"),
        replace(strategy, routing_policy_version="source-analysis-routing.v99"),
        replace(strategy, window_chunks=strategy.window_chunks + 1),
        replace(strategy, max_analyzer_calls=strategy.max_analyzer_calls + 1),
        replace(strategy, mkaos_capability="mkaos.rule.changed"),
        replace(strategy, abstraction_policy_version="platform-rule-abstraction.99"),
    )

    assert all(item.fingerprint != strategy.fingerprint for item in variants)
    restored = analysis_strategy_from_dict(
        strategy.to_dict(), expected_fingerprint=strategy.fingerprint
    )
    assert restored == strategy
    with pytest.raises(ValueError, match="fingerprint drifted"):
        analysis_strategy_from_dict(
            variants[0].to_dict(), expected_fingerprint=strategy.fingerprint
        )


def test_missing_or_mismatched_skill_materialization_fails_closed(
    tmp_path: Path,
) -> None:
    registry = SourceMethodologyRegistry(tmp_path)
    with pytest.raises(ValueError, match="not available"):
        registry.require("published-fiction-craft-analysis")

    skill = tmp_path / "published-fiction-craft-analysis"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: wrong-skill\n---\n\n# Wrong\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="identity"):
        registry.require("published-fiction-craft-analysis")


def test_classification_sample_rejects_unbounded_or_invalid_identity() -> None:
    with pytest.raises(ValueError, match="sample"):
        ClassificationSample(
            source_chunk_asset_version_id="",
            byte_start=0,
            byte_end=1,
            sample_hash="sha256:" + "a" * 64,
            position="BEGINNING",
        )
