from novel_forge.modules.context_builder.retrieval_benchmark import (
    BENCHMARK_CHAPTER_COUNTS,
    generate_longform_corpus,
    run_longform_retrieval_benchmark,
)


def test_generated_corpus_is_exact_bounded_and_spans_every_memory_layer() -> None:
    corpus = generate_longform_corpus(chapter_count=50, total_characters=150_000)

    assert len(corpus) == 50
    assert sum(len(item["content_text"]) for item in corpus) == 150_000
    assert {item["memory_layer"] for item in corpus} == {
        f"L{index}" for index in range(10)
    }


def test_bounded_expansion_improves_hard_recall_without_context_or_leakage_regression() -> (
    None
):
    report = run_longform_retrieval_benchmark(chapter_counts=(50,))

    assert report["status"] == "PASS"
    assert report["corpus"]["chapter_profiles"] == [50]
    assert report["candidate"]["required_fact_recall"] == 1.0
    assert (
        report["candidate"]["hard_case_recall"] > report["baseline"]["hard_case_recall"]
    )
    assert (
        report["candidate"]["normal_case_recall"]
        >= report["baseline"]["normal_case_recall"]
    )
    assert report["candidate"]["future_fact_leakage"] == 0
    assert report["candidate"]["stale_fact_leakage"] == 0
    assert report["candidate"]["hidden_knowledge_leakage"] == 0
    assert report["candidate"]["final_context_tokens_max"] <= 6000
    assert report["candidate"]["max_round_count"] <= 3
    assert report["candidate"]["replay_identity_drift"] == 0
    assert report["proof_scope"]["does_not_establish"]
    assert BENCHMARK_CHAPTER_COUNTS[-1] == 1000
