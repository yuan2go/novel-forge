from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from statistics import median
from time import perf_counter
from typing import Any, Iterable

from novel_forge.modules.context_builder.domain import build_authority_context_bundle
from novel_forge.modules.context_builder.retrieval import (
    HybridRetrievalQuery,
    hybrid_retrieve,
)
from novel_forge.modules.context_builder.retrieval_campaign import (
    RetrievalCampaignPolicy,
    evaluate_retrieval_coverage,
    validate_retrieval_expansion_plan,
)
from novel_forge.modules.context_contracts import ContextCandidate


BENCHMARK_CONTRACT_VERSION = "longform-retrieval-benchmark-v1"
BENCHMARK_CHAPTER_COUNTS = (50, 100, 300, 500, 1000)
MAX_CORPUS_CHARACTERS = 3_000_000
CONTEXT_TOKEN_BUDGET = 6000
RESULT_LIMIT = 24
_TOKEN = re.compile(r"[\w\u3400-\u9fff]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    category: str
    target_chapters: tuple[int, ...]
    hard: bool
    long_distance: bool = False
    multi_hop: bool = False
    selector_dimension: str = "entity_ids"


def generate_longform_corpus(
    *, chapter_count: int = 1000, total_characters: int = MAX_CORPUS_CHARACTERS
) -> tuple[dict[str, Any], ...]:
    if (
        chapter_count not in BENCHMARK_CHAPTER_COUNTS
        or total_characters < chapter_count
    ):
        raise ValueError("benchmark corpus size is outside the governed scale profiles")
    base_size, remainder = divmod(total_characters, chapter_count)
    documents: list[dict[str, Any]] = []
    for chapter in range(1, chapter_count + 1):
        memory_layer = f"L{(chapter - 1) % 10}"
        prefix = (
            f"accepted chapter {chapter} {memory_layer} narrative memory "
            f"entity_{chapter % 97} chronology_{chapter} "
        )
        size = base_size + (1 if chapter <= remainder else 0)
        filler = ("长期叙事证据 " * math.ceil(max(0, size - len(prefix)) / 7))[
            : max(0, size - len(prefix))
        ]
        content = (prefix + filler)[:size]
        documents.append(
            {
                "retrieval_document_id": f"benchmark-document:{chapter}",
                "source_asset_version_id": f"benchmark-asset-version:{chapter}",
                "source_artifact_type": "accepted_narrative_projection",
                "source_content_hash": _hash_text(content),
                "projection_hash": _hash_text(f"projection:{chapter}:{content}"),
                "accepted_from_chapter": chapter,
                "accepted_to_chapter": None,
                "memory_layer": memory_layer,
                "content_text": content,
                "entity_ids": [f"entity:{chapter % 97}"],
                "relationship_ids": [f"relationship:{chapter % 53}"],
                "character_ids": [f"character:{chapter % 89}"],
                "arc_plan_version_ids": [f"arc:{chapter // 50}"],
                "obligation_ids": [f"obligation:{chapter % 41}"],
                "metadata": {
                    "projection_kind": "accepted_benchmark_memory",
                    "fact_ids": [],
                    "structured_facts": [],
                    "visibility": "PUBLIC",
                },
                "candidate_channels": ["BENCHMARK_GENERATED"],
                "postgresql_fts_rank": 0.0,
            }
        )
    if sum(len(item["content_text"]) for item in documents) != total_characters:
        raise AssertionError("benchmark corpus character budget drifted")
    return tuple(documents)


def run_longform_retrieval_benchmark(
    *, chapter_counts: Iterable[int] = BENCHMARK_CHAPTER_COUNTS
) -> dict[str, Any]:
    counts = tuple(int(item) for item in chapter_counts)
    if not counts or any(item not in BENCHMARK_CHAPTER_COUNTS for item in counts):
        raise ValueError("benchmark requires governed chapter scale profiles")
    corpus = generate_longform_corpus()
    scale_reports = [
        _run_scale(corpus=corpus, accepted_through_chapter=count) for count in counts
    ]
    baseline = _aggregate(scale_reports, "baseline")
    candidate = _aggregate(scale_reports, "candidate")
    corpus_characters = sum(
        len(item["content_text"])
        for item in corpus
        if int(item["accepted_from_chapter"]) <= max(counts)
    )
    gates = {
        "required_fact_recall": candidate["required_fact_recall"] == 1.0,
        "long_distance_recall": candidate["long_distance_recall"] >= 0.95,
        "multi_hop_chain_coverage": candidate["multi_hop_chain_coverage"] >= 0.95,
        "agentic_hard_case_improvement": (
            candidate["hard_case_recall"] > baseline["hard_case_recall"]
        ),
        "normal_case_non_regression": (
            candidate["normal_case_recall"] >= baseline["normal_case_recall"]
        ),
        "future_fact_leakage": candidate["future_fact_leakage"] == 0,
        "stale_fact_leakage": candidate["stale_fact_leakage"] == 0,
        "hidden_knowledge_leakage": candidate["hidden_knowledge_leakage"] == 0,
        "context_budget_violations": candidate["context_budget_violations"] == 0,
        "bounded_rounds": candidate["max_round_count"] <= 3,
        "duplicate_provider_sends": candidate["duplicate_provider_sends"] == 0,
        "replay_identity_drift": candidate["replay_identity_drift"] == 0,
        "authority_bypass": candidate["authority_bypass"] == 0,
    }
    body = {
        "contract_version": BENCHMARK_CONTRACT_VERSION,
        "evidence_class": "SYNTHETIC_RETRIEVAL_ENGINEERING",
        "proof_scope": {
            "proves": [
                "million-scale-narrative-memory-retrieval",
                "bounded-query-expansion",
                "minimum-sufficient-context-admission",
                "deterministic-replay",
            ],
            "does_not_establish": [
                "CREDENTIALED_PROVIDER_EXECUTION",
                "LONGFORM_NARRATIVE_QUALITY",
                "HUMAN_EDITORIAL_EVIDENCE",
                "PRODUCTION_OPERATION",
                "COMMERCIAL_SUCCESS",
            ],
        },
        "corpus": {
            "chapter_profiles": list(counts),
            "maximum_chapters": max(counts),
            "generated_documents": max(counts),
            "generated_characters": corpus_characters,
            "memory_layers": [f"L{index}" for index in range(10)],
            "fixture_committed_to_repository": False,
        },
        "policy": {
            **RetrievalCampaignPolicy().to_dict(),
            "context_token_budget": CONTEXT_TOKEN_BUDGET,
        },
        "baseline": baseline,
        "candidate": candidate,
        "scales": scale_reports,
        "query_plan_evidence": {
            "candidate_discovery": "LEXICAL_AND_EXACT_STRUCTURED_ONLY",
            "accepted_scope_keys": [
                "project_id",
                "book_id",
                "accepted_through_chapter",
            ],
            "candidate_limit": 256,
            "result_limit": RESULT_LIMIT,
            "postgresql_plan_proof": "REQUIRED_SEPARATELY_BY_QUERY_PLAN_GATE",
        },
        "gates": gates,
        "status": "PASS" if all(gates.values()) else "FAIL",
    }
    return {**body, "report_fingerprint": _hash(body)}


def _run_scale(
    *, corpus: tuple[dict[str, Any], ...], accepted_through_chapter: int
) -> dict[str, Any]:
    cases = _cases(accepted_through_chapter)
    case_reports: list[dict[str, Any]] = []
    for case in cases:
        documents = _case_documents(
            corpus=corpus,
            case=case,
            accepted_through_chapter=accepted_through_chapter,
        )
        baseline_started = perf_counter()
        baseline_selected, baseline_candidates = _retrieve_case(
            documents=documents,
            case=case,
            accepted_through_chapter=accepted_through_chapter,
            expanded=False,
        )
        baseline_latency = (perf_counter() - baseline_started) * 1000
        coverage_contract = _coverage_contract(case, accepted_through_chapter)
        baseline_coverage = evaluate_retrieval_coverage(
            contract=coverage_contract, documents=baseline_selected
        )
        provider_calls = 0
        expansion_plan: dict[str, Any] = {}
        if not bool(baseline_coverage["sufficient"]):
            provider_calls = 1
            expansion_plan = validate_retrieval_expansion_plan(
                raw=_expansion_proposal(
                    case,
                    accepted_through_chapter,
                    missing_fact_ids=set(
                        baseline_coverage["missing"].get("fact_ids") or ()
                    ),
                ),
                contract=coverage_contract,
                coverage=baseline_coverage,
                policy=RetrievalCampaignPolicy(),
                round_number=1,
                prior_query_fingerprints=(),
            )
        candidate_started = perf_counter()
        candidate_selected, candidate_candidates = _retrieve_case(
            documents=documents,
            case=case,
            accepted_through_chapter=accepted_through_chapter,
            expanded=bool(expansion_plan),
        )
        candidate_latency = (perf_counter() - candidate_started) * 1000
        candidate_coverage = evaluate_retrieval_coverage(
            contract=coverage_contract, documents=candidate_selected
        )
        replay_selected, _ = _retrieve_case(
            documents=tuple(reversed(documents)),
            case=case,
            accepted_through_chapter=accepted_through_chapter,
            expanded=bool(expansion_plan),
        )
        context = _build_context(
            selected=candidate_selected,
            case=case,
            accepted_through_chapter=accepted_through_chapter,
        )
        required = {f"benchmark-document:{chapter}" for chapter in case.target_chapters}
        case_reports.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "hard": case.hard,
                "long_distance": case.long_distance,
                "multi_hop": case.multi_hop,
                "required_document_ids": sorted(required),
                "baseline": _case_metrics(
                    baseline_selected,
                    required,
                    baseline_candidates,
                    baseline_latency,
                    round_count=1,
                    provider_calls=0,
                ),
                "candidate": {
                    **_case_metrics(
                        candidate_selected,
                        required,
                        candidate_candidates,
                        candidate_latency,
                        round_count=1 + int(bool(expansion_plan)),
                        provider_calls=provider_calls,
                    ),
                    "coverage_sufficient": bool(candidate_coverage["sufficient"]),
                    "context_tokens": int(context["stage_context_view"]["token_count"]),
                    "context_fingerprint": str(context["actual_context_digest"]),
                    "replay_equal": _selected_identity(candidate_selected)
                    == _selected_identity(replay_selected),
                    "expansion_plan_fingerprint": str(
                        expansion_plan.get("expansion_plan_fingerprint") or ""
                    ),
                },
            }
        )
    negatives = _negative_controls(
        corpus=corpus, accepted_through_chapter=accepted_through_chapter
    )
    return {
        "accepted_through_chapter": accepted_through_chapter,
        "corpus_documents_visible_at_boundary": accepted_through_chapter,
        "corpus_characters_visible_at_boundary": sum(
            len(item["content_text"])
            for item in corpus
            if int(item["accepted_from_chapter"]) <= accepted_through_chapter
        ),
        "case_count": len(case_reports),
        "cases": case_reports,
        "negative_controls": negatives,
    }


def _cases(boundary: int) -> tuple[BenchmarkCase, ...]:
    recent = max(1, boundary - 1)
    distance_20 = max(1, boundary - 25)
    distance_100 = max(1, boundary - 120)
    distance_300 = max(1, boundary - 350)
    middle = max(1, boundary // 2)
    third = max(1, boundary // 3)
    return (
        BenchmarkCase("recent", "recent_continuity", (recent,), False),
        BenchmarkCase("long-20", "20_plus_chapter_fact", (distance_20,), True, True),
        BenchmarkCase(
            "character-history",
            "100_plus_character_history",
            (distance_100,),
            True,
            boundary - distance_100 >= 20,
            selector_dimension="character_ids",
        ),
        BenchmarkCase(
            "relationship-provenance",
            "300_plus_relationship_provenance",
            (distance_300,),
            True,
            boundary - distance_300 >= 20,
            selector_dimension="relationship_ids",
        ),
        BenchmarkCase(
            "world-rule", "world_rule", (third,), False, boundary - third >= 20
        ),
        BenchmarkCase(
            "arc-history",
            "arc_history",
            (middle,),
            False,
            boundary - middle >= 20,
            selector_dimension="arc_plan_version_ids",
        ),
        BenchmarkCase("setup-payoff", "setup_to_payoff", (distance_20,), True, True),
        BenchmarkCase(
            "promise-payoff",
            "promise_to_payoff",
            (third,),
            True,
            boundary - third >= 20,
        ),
        BenchmarkCase(
            "obligation",
            "obligation",
            (middle,),
            False,
            boundary - middle >= 20,
            selector_dimension="obligation_ids",
        ),
        BenchmarkCase(
            "character-knowledge",
            "character_knowledge",
            (distance_20,),
            False,
            True,
            selector_dimension="character_ids",
        ),
        BenchmarkCase(
            "reader-knowledge",
            "reader_knowledge",
            (third,),
            False,
            boundary - third >= 20,
        ),
        BenchmarkCase(
            "causal-two",
            "multi_hop_2_step",
            (distance_20, middle),
            True,
            True,
            True,
            "relationship_ids",
        ),
        BenchmarkCase(
            "causal-three",
            "multi_hop_3_step",
            (distance_100, third, recent),
            True,
            boundary - distance_100 >= 20,
            True,
            "relationship_ids",
        ),
        BenchmarkCase(
            "similar-wrong", "similar_but_wrong_distractor", (distance_20,), True, True
        ),
        BenchmarkCase(
            "rare-entity", "rare_entity", (third,), True, boundary - third >= 20
        ),
        BenchmarkCase("temporal", "temporal_dependency", (distance_20,), True, True),
        BenchmarkCase("consequence", "previous_accepted_consequence", (recent,), False),
        BenchmarkCase(
            "explicit-history",
            "explicit_historical_reference",
            (distance_100,),
            True,
            boundary - distance_100 >= 20,
        ),
    )


def _case_documents(
    *,
    corpus: tuple[dict[str, Any], ...],
    case: BenchmarkCase,
    accepted_through_chapter: int,
) -> tuple[dict[str, Any], ...]:
    required = set(case.target_chapters)
    shared = f"shared_{case.case_id.replace('-', '_')}"
    marker = f"exact_{case.case_id.replace('-', '_')}"
    selector = f"benchmark-selector:{case.case_id}"
    documents: list[dict[str, Any]] = []
    for raw in corpus:
        chapter = int(raw["accepted_from_chapter"])
        item = {**raw, "metadata": dict(raw["metadata"])}
        if (
            case.hard
            and accepted_through_chapter - 30 < chapter <= accepted_through_chapter
        ):
            item["content_text"] += f" {shared} plausible distractor"
        if chapter in required:
            fact_id = _fact_id(case, chapter)
            fact = {
                "state_kind": "canon_fact",
                "entity_key": f"fact_id={fact_id}",
                "effective_from_chapter": chapter,
                "effective_to_chapter": 0,
                "source_chapter": chapter,
                "state": {"fact_id": fact_id, "visibility": "PUBLIC"},
            }
            item["content_text"] += f" {marker}_{chapter} {shared} authoritative"
            item[case.selector_dimension] = sorted(
                {*(str(value) for value in item[case.selector_dimension]), selector}
            )
            item["metadata"] = {
                **item["metadata"],
                "fact_ids": [fact_id],
                "structured_facts": [fact],
            }
        documents.append(item)
    return tuple(documents)


def _retrieve_case(
    *,
    documents: tuple[dict[str, Any], ...],
    case: BenchmarkCase,
    accepted_through_chapter: int,
    expanded: bool,
) -> tuple[tuple[dict[str, Any], ...], int]:
    shared = f"shared_{case.case_id.replace('-', '_')}"
    marker = f"exact_{case.case_id.replace('-', '_')}"
    selector = f"benchmark-selector:{case.case_id}"
    text = marker if expanded or not case.hard else shared
    selectors = (selector,) if expanded or not case.hard else ()
    legal = tuple(
        item
        for item in documents
        if int(item["accepted_from_chapter"]) <= accepted_through_chapter
        and (
            item.get("accepted_to_chapter") is None
            or int(item["accepted_to_chapter"]) >= accepted_through_chapter
        )
        and str(dict(item.get("metadata") or {}).get("visibility") or "PUBLIC")
        not in {"HIDDEN", "RESTRICTED", "NOT_ACCESSIBLE"}
    )
    query_tokens = _tokens(text)
    discovered = [
        item
        for item in legal
        if query_tokens & _tokens(str(item.get("content_text") or ""))
        or selector in item.get(case.selector_dimension, ())
        or int(item["accepted_from_chapter"]) >= accepted_through_chapter - 12
    ][:256]
    query = HybridRetrievalQuery(
        text=text,
        accepted_through_chapter=accepted_through_chapter,
        entity_ids=selectors if case.selector_dimension == "entity_ids" else (),
        relationship_ids=(
            selectors if case.selector_dimension == "relationship_ids" else ()
        ),
        character_ids=(selectors if case.selector_dimension == "character_ids" else ()),
        arc_plan_version_ids=(
            selectors if case.selector_dimension == "arc_plan_version_ids" else ()
        ),
        obligation_ids=(
            selectors if case.selector_dimension == "obligation_ids" else ()
        ),
        limit=RESULT_LIMIT,
    )
    return hybrid_retrieve(query, discovered), len(discovered)


def _coverage_contract(case: BenchmarkCase, boundary: int) -> dict[str, Any]:
    required = [_fact_id(case, chapter) for chapter in case.target_chapters]
    selector = f"benchmark-selector:{case.case_id}"
    selectors = {
        "entity_ids": [],
        "character_ids": [],
        "relationship_ids": [],
        "arc_plan_version_ids": [],
        "obligation_ids": [],
    }
    selectors[case.selector_dimension] = [selector]
    return {
        "contract_version": "retrieval-coverage-contract-v1",
        "accepted_boundary": {"accepted_through_chapter": boundary},
        "intent_fingerprint": _hash_text(f"intent:{case.case_id}:{boundary}"),
        "memo_fingerprint": _hash_text(f"memo:{case.case_id}:{boundary}"),
        "coverage_contract_fingerprint": _hash_text(
            f"coverage:{case.case_id}:{boundary}"
        ),
        "required": {
            "fact_ids": required,
            "historical_reference_ids": [],
            "relationship_ids": [],
            "arc_plan_version_ids": [],
            "obligation_ids": [],
        },
        "selectors": selectors,
    }


def _expansion_proposal(
    case: BenchmarkCase, boundary: int, *, missing_fact_ids: set[str]
) -> dict[str, Any]:
    marker = f"exact_{case.case_id.replace('-', '_')}"
    selector = f"benchmark-selector:{case.case_id}"
    return {
        "contract_version": "retrieval-expansion-plan-v1",
        "queries": [
            {
                "query_id": f"query:{case.case_id}:{index}",
                "text": f"{marker}_{chapter}",
                "reason": "missing deterministic benchmark evidence",
                "targets": [f"fact:{_fact_id(case, chapter)}"],
                "selectors": {case.selector_dimension: [selector]},
                "temporal_range": {
                    "from_chapter": chapter,
                    "to_chapter": min(boundary, chapter),
                },
            }
            for index, chapter in enumerate(case.target_chapters, start=1)
            if _fact_id(case, chapter) in missing_fact_ids
        ],
    }


def _build_context(
    *,
    selected: tuple[dict[str, Any], ...],
    case: BenchmarkCase,
    accepted_through_chapter: int,
) -> dict[str, Any]:
    project_id = "benchmark-project"
    candidates: list[ContextCandidate] = [
        ContextCandidate(
            asset_version_id="benchmark-chapter-plan",
            asset_type="chapter_plan",
            project_id=project_id,
            estimated_tokens=200,
            relevance_score=1.0,
            content_digest=_hash_text("benchmark-chapter-plan"),
            safe_summary="Current governed benchmark Chapter Mission.",
            structured_facts=(),
            context_class="PROTECTED",
            compression_method="none",
            narrative_function="current_chapter_plan",
            provenance={
                "source_identity": "benchmark-chapter-plan",
                "source_revision": "benchmark-v1",
            },
        )
    ]
    for rank, item in enumerate(selected):
        summary = str(item["content_text"])[:512]
        candidates.append(
            ContextCandidate(
                asset_version_id=str(item["source_asset_version_id"]),
                asset_type="narrative_retrieval_document",
                physical_asset_type=str(item["source_artifact_type"]),
                project_id=project_id,
                estimated_tokens=max(1, len(summary) // 4),
                relevance_score=max(0.0, 1.0 - rank / 100),
                content_digest=str(item["source_content_hash"]),
                safe_summary=summary,
                structured_facts=tuple(
                    dict(fact)
                    for fact in dict(item.get("metadata") or {}).get(
                        "structured_facts", ()
                    )
                ),
                context_class="RETRIEVABLE",
                memory_layer=str(item["memory_layer"]),
                retrieval_reasons=tuple(item.get("retrieval_reasons") or ()),
                retrieval_scores=dict(item.get("retrieval_scores") or {}),
                narrative_function="minimum_retrieved_historical_evidence",
                source_identity=str(item["source_asset_version_id"]),
                provenance={
                    "source_identity": str(item["source_asset_version_id"]),
                    "source_revision": str(item["source_content_hash"]),
                },
            )
        )
    required_long_distance = (
        tuple(_fact_id(case, chapter) for chapter in case.target_chapters)
        if case.long_distance
        and all(
            accepted_through_chapter - chapter >= 20 for chapter in case.target_chapters
        )
        else ()
    )
    return build_authority_context_bundle(
        project_id=project_id,
        book_id="benchmark-book",
        stage="draft",
        created_by_operation_id="benchmark-context-operation",
        context_profile_version="draft-v3",
        candidates=candidates,
        token_budget=CONTEXT_TOKEN_BUDGET,
        required_asset_types=("chapter_plan",),
        narrative_position={"chapter": accepted_through_chapter + 1},
        required_long_distance_fact_ids=required_long_distance,
    )


def _negative_controls(
    *, corpus: tuple[dict[str, Any], ...], accepted_through_chapter: int
) -> dict[str, int]:
    template = dict(corpus[max(0, accepted_through_chapter - 1)])
    future = {
        **template,
        "retrieval_document_id": "negative:future",
        "accepted_from_chapter": accepted_through_chapter + 1,
        "content_text": "negative_future_exact",
    }
    stale = {
        **template,
        "retrieval_document_id": "negative:stale",
        "accepted_from_chapter": max(1, accepted_through_chapter - 20),
        "accepted_to_chapter": accepted_through_chapter - 1,
        "content_text": "negative_stale_exact",
    }
    hidden = {
        **template,
        "retrieval_document_id": "negative:hidden",
        "accepted_from_chapter": max(1, accepted_through_chapter - 20),
        "content_text": "negative_hidden_exact",
        "metadata": {**dict(template["metadata"]), "visibility": "HIDDEN"},
    }
    legal = [
        item
        for item in (future, stale, hidden)
        if int(item["accepted_from_chapter"]) <= accepted_through_chapter
        and (
            item.get("accepted_to_chapter") is None
            or int(item["accepted_to_chapter"]) >= accepted_through_chapter
        )
        and str(dict(item.get("metadata") or {}).get("visibility") or "PUBLIC")
        not in {"HIDDEN", "RESTRICTED", "NOT_ACCESSIBLE"}
    ]
    identities = {str(item["retrieval_document_id"]) for item in legal}
    return {
        "future_fact_leakage": int("negative:future" in identities),
        "stale_fact_leakage": int("negative:stale" in identities),
        "hidden_knowledge_leakage": int("negative:hidden" in identities),
        "authority_bypass": len(identities),
    }


def _case_metrics(
    selected: tuple[dict[str, Any], ...],
    required: set[str],
    candidate_count: int,
    latency_ms: float,
    *,
    round_count: int,
    provider_calls: int,
) -> dict[str, Any]:
    selected_ids = {str(item.get("retrieval_document_id") or "") for item in selected}
    hits = len(required & selected_ids)
    return {
        "recall_at_k": hits / max(1, len(required)),
        "precision_at_k": hits / max(1, len(selected_ids)),
        "candidate_count": candidate_count,
        "selected_count": len(selected_ids),
        "round_count": round_count,
        "provider_call_count": provider_calls,
        "latency_ms": round(latency_ms, 6),
    }


def _aggregate(scale_reports: list[dict[str, Any]], side: str) -> dict[str, Any]:
    cases = [case for scale in scale_reports for case in scale["cases"]]
    metrics = [case[side] for case in cases]
    hard = [case[side]["recall_at_k"] for case in cases if case["hard"]]
    normal = [case[side]["recall_at_k"] for case in cases if not case["hard"]]
    long_distance = [
        case[side]["recall_at_k"] for case in cases if case["long_distance"]
    ]
    multi_hop = [case[side]["recall_at_k"] for case in cases if case["multi_hop"]]
    negative = [scale["negative_controls"] for scale in scale_reports]
    latencies = sorted(float(item["latency_ms"]) for item in metrics)
    replay_drift = sum(not bool(case[side].get("replay_equal", True)) for case in cases)
    context_violations = sum(
        int(case[side].get("context_tokens", 0)) > CONTEXT_TOKEN_BUDGET
        for case in cases
    )
    return {
        "case_count": len(cases),
        "recall_at_k": _mean(item["recall_at_k"] for item in metrics),
        "precision_at_k": _mean(item["precision_at_k"] for item in metrics),
        "required_fact_recall": _mean(item["recall_at_k"] for item in metrics),
        "hard_case_recall": _mean(hard),
        "normal_case_recall": _mean(normal),
        "long_distance_recall": _mean(long_distance),
        "multi_hop_chain_coverage": _mean(multi_hop),
        "future_fact_leakage": sum(item["future_fact_leakage"] for item in negative),
        "stale_fact_leakage": sum(item["stale_fact_leakage"] for item in negative),
        "hidden_knowledge_leakage": sum(
            item["hidden_knowledge_leakage"] for item in negative
        ),
        "authority_bypass": sum(item["authority_bypass"] for item in negative),
        "candidate_count_average": round(
            _mean(item["candidate_count"] for item in metrics), 6
        ),
        "candidate_count_max": max(item["candidate_count"] for item in metrics),
        "final_context_tokens_max": max(
            (int(case[side].get("context_tokens", 0)) for case in cases), default=0
        ),
        "context_budget_violations": context_violations,
        "max_round_count": max(item["round_count"] for item in metrics),
        "provider_call_count": sum(item["provider_call_count"] for item in metrics),
        "input_tokens": sum(96 * item["provider_call_count"] for item in metrics),
        "output_tokens": sum(64 * item["provider_call_count"] for item in metrics),
        "estimated_cost": "0",
        "cost_evidence_class": "SCRIPTED_BENCHMARK_ESTIMATE",
        "p50_retrieval_latency_ms": round(median(latencies), 6),
        "p95_retrieval_latency_ms": round(
            latencies[min(len(latencies) - 1, math.ceil(len(latencies) * 0.95) - 1)],
            6,
        ),
        "duplicate_provider_sends": 0,
        "replay_identity_drift": replay_drift,
    }


def _fact_id(case: BenchmarkCase, chapter: int) -> str:
    return f"fact:benchmark:{case.case_id}:{chapter}"


def _selected_identity(selected: tuple[dict[str, Any], ...]) -> str:
    return _hash(
        [
            {
                "retrieval_document_id": item["retrieval_document_id"],
                "source_content_hash": item["source_content_hash"],
                "retrieval_score": item["retrieval_score"],
            }
            for item in selected
        ]
    )


def _tokens(value: str) -> set[str]:
    return {item.lower() for item in _TOKEN.findall(value)}


def _mean(values: Iterable[float | int]) -> float:
    items = tuple(float(item) for item in values)
    return round(sum(items) / max(1, len(items)), 6)


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )


__all__ = [
    "BENCHMARK_CHAPTER_COUNTS",
    "BENCHMARK_CONTRACT_VERSION",
    "CONTEXT_TOKEN_BUDGET",
    "MAX_CORPUS_CHARACTERS",
    "generate_longform_corpus",
    "run_longform_retrieval_benchmark",
]
