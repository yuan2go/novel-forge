# V5 Strategic Risk Plan

## Current Assessment

This document records the current position on high-level V5 risks after the post-P2 optimization pass.

## Real LLM Adapter Risk

Claude Code can be used now as an operator workflow, but not as a stable in-process LLM adapter.

Supported now:

- `ClaudeCodeAdapter.create_handoff_packet()` creates a bounded manual task packet.
- The packet can reference project files, expected schema-backed output, and validation commands.
- Claude Code can read the packet through the current development session and write validated assets using repository rules.

Not supported now:

- Calling the current Claude Code session from business code as if it were an API.
- Running hidden shell/network automation to ask Claude Code for content.
- Treating manual Claude Code output as automatically validated.

Decision:

- Keep `generate`, `analyze`, `review`, `revise`, and `batch` fail-closed for provider skeletons.
- Use handoff packets for current Claude Code integration.
- Add true provider implementations only after ADR, dependency policy, secret policy, and mocked tests.

## Retrieval Risk

Previous risk:

- Vector retrieval was a local hash-vector proof of plumbing.

Current mitigation:

- `vector-search` now uses a hybrid local ranker: deterministic hash vectors + BM25-style lexical scoring.
- Tokenization now includes ASCII tokens plus Chinese unigram/bigram features.
- Index metadata records `hybrid-hash-vector-bm25`, document frequency, token counts, and tokenizer type.

Remaining risk:

- This is still not a true semantic embedding model or vector database.
- Real embeddings require ADR, cost policy, dependency policy, and no-network tests.

## Ebook Parsing Risk

Previous risk:

- EPUB/MOBI/AZW3 support was fixture-level extraction.

Current mitigation:

- EPUB extraction now prefers `META-INF/container.xml` and OPF spine order.
- EPUB metadata records extraction method, spine items, title/language/creator when available, and warnings.
- MOBI/AZW3 extraction records explicit warnings that proprietary parsing is limited without external dependencies.

Remaining risk:

- Full MOBI/AZW3 parsing still requires a dedicated library or external tool decision.
- DRM-protected or malformed ebooks remain out of scope.

## Feedback Trend Risk

Previous risk:

- Feedback trend analysis was mostly rating average plus keyword rules.

Current mitigation:

- `FeedbackInsight` now includes `trend_metrics`: rating slope, rating volatility, low-rating ratio, row count, chapter count, and confidence.
- Retention risk now includes a numeric risk score.
- Plot adjustment plans react to declining slope and volatility, not only keyword hits.

Remaining risk:

- This is not statistically robust for small samples.
- Model-assisted interpretation and larger cohort analytics remain future work.

## Long Project Memory Risk

Previous risk:

- Workspace state tracked chapter continuity, but did not exercise multi-book memory enough.

Current mitigation:

- `init-workspace` supports optional series title and book number.
- Workspace status reports series and book identifiers.
- Tests cover two books in the same series with separate project IDs and chapter memory.

Remaining risk:

- Cross-book canon reconciliation is still basic.
- Real multi-book projects need larger fixtures and conflict-resolution workflows.
