# MKAOS Professional Book Import Capability Analysis

Date: 2026-07-04
Branch: `feat/v6-post-mkaos-industrialization`

## 1. Executive Conclusion

MKAOS is now a usable Knowledge Asset OS kernel rather than a simple knowledge-base extension. It has source evidence isolation, source chunks, evidence spans, knowledge candidates, KnowledgeCard approval, selector/pack/debugger, quality scoring, knowledge graph, conflict review, feedback learning, mutation/version/lineage audit, ReviewIssue integration, and a web/admin operations console.

For the specific question, “Can the system import one professional book and automatically split it?” the answer is:

**Conditionally yes for safe ingestion and deterministic chunking; partially yes for automatic extraction; not yet fully complete for high-quality, book-scale automatic knowledge graph construction.**

Current MKAOS can:

1. Import a professional book as `source_kind=professional_book`.
2. Store raw source only in the evidence layer.
3. Clean and deduplicate repeated short lines.
4. Split cleaned text into source chunks.
5. Create evidence spans for chunks.
6. Generate `knowledge_card_candidate` assets from chunks.
7. Approve candidates into formal KnowledgeCards.
8. Block source raw text from Knowledge Pack, Context Bundle, prose prompt, graph explorer, and generation RAG paths.
9. Validate opt-in model-assisted extraction outputs against source-expression overlap and quality checks.

Current MKAOS does **not** yet fully provide:

1. Native PDF / EPUB / DOCX parsing with page/section preservation.
2. TOC-aware chapter/section semantic chunking for long professional books.
3. Full-book batch extraction orchestration over all chunks.
4. Automatic RuleCard / TemplateCard extraction from the whole book without operator approval.
5. True external model extraction provider E2E quality proof by default.
6. Statistical validation that extracted knowledge improves downstream novel production after many chapters.

## 2. Evidence From Current Code

| Capability | Current status | Evidence |
| --- | --- | --- |
| Professional book source policy | Implemented first slice | `src/novel_forge/modules/mkaos/service.py::_source_kind_policy`, `professional_book` |
| Source import | Implemented | `import_source_document` stores `source_document` under `raw` with `use_in_generation_rag=False` |
| Pipeline import | Implemented first slice | `import_source_with_pipeline` returns import report, dry-run support, copyright boundary, recommended extraction |
| Cleaning | Implemented deterministic | `clean_source_text` removes repeated short lines and page-only markers |
| Chunking | Implemented deterministic | `split_clean_text(target_chars=600)` paragraph-batches cleaned text |
| Chunk rebuild | Implemented | `rebuild_source_chunks` writes `source_chunk` assets with `evidence_layer_only=True` |
| Evidence span | Implemented | `create_evidence_span` stores page/section/paragraph/sentence/char metadata and hash, no raw text in span |
| Candidate extraction | Implemented first slice | `extract_knowledge_candidates` creates `knowledge_card_candidate`, defaults local deterministic |
| Provider extraction opt-in | Implemented first slice | `provider_mode=model_assisted` requires `provider_opt_in` or env opt-in |
| Provider quality validation | Implemented first slice | `validate_extraction_provider_quality` checks abstraction, flow/discipline coverage, source-expression overlap |
| Candidate approval | Implemented | `approve_knowledge_candidate` converts candidate to `knowledge_card` |
| Source leakage guard | Implemented regression coverage | `tests/unit/test_mkaos_source_leakage_regression.py` |
| Import pipeline test | Implemented | `tests/unit/test_mkaos_import_pipeline.py` |
| Extraction tests | Implemented | `tests/unit/test_mkaos_extraction_agent.py`, `tests/unit/test_mkaos_provider_semantic_governance.py` |

## 3. Current Professional Book Flow

Current supported flow:

```text
operator supplies text
  -> import_source_with_pipeline(source_kind=professional_book)
  -> import_source_document
  -> clean_source_text
  -> split_clean_text
  -> source_document + source_chunk assets
  -> create_evidence_span
  -> extract_knowledge_candidates
  -> validate_extraction_provider_quality
  -> approve_knowledge_candidate
  -> KnowledgeCard
  -> UsageBinding / Selector v2 / KnowledgePack
  -> ContextBundle / AgentRun
  -> ReviewIssue / RevisionTask / Feedback Learning / Lineage Audit
```

Safety boundary:

```text
source_document.content.text
source_chunk.content.raw_text
source_chunk.content.clean_text
```

remain evidence-layer data. They are explicitly marked:

```text
use_in_generation_rag = False
evidence_layer_only = True
allow_downstream_generation = False
```

Knowledge Pack and generation contexts should only use:

```text
source_document_id
source_chunk_id
evidence_span_id
content_hash
abstracted principle
rule/template/constraint
```

## 4. Can It “Automatically Split” A Professional Book?

### 4.1 What “Automatically Split” Means Today

The system can automatically split book text into `source_chunk` assets after import. The current split algorithm is deterministic paragraph batching, with target size around 600 characters.

This is sufficient for:

1. Small to medium pasted professional text.
2. Operator-supplied plain text.
3. Evidence-layer indexing.
4. Safe candidate extraction on bounded chunks.
5. Regression testing source leakage.

### 4.2 What It Does Not Yet Mean

It does not yet mean:

1. “Upload PDF and preserve page numbers automatically.”
2. “Recognize table of contents, chapters, headings, footnotes, figures, citations.”
3. “Split by semantic concept boundaries across a whole book.”
4. “Automatically extract a mature multi-disciplinary knowledge graph from all chapters.”
5. “Automatically activate all knowledge, rules, and templates without review.”

Those are P2/P3 extensions, not current stable P1 behavior.

## 5. Completeness Assessment

| Area | Score | Judgment |
| --- | ---: | --- |
| Source evidence isolation | 90/100 | Strong local-first boundary; raw text remains evidence-layer only. |
| Professional book import policy | 75/100 | `professional_book` exists with safe default policy, but file parsing is not native yet. |
| Automatic chunking | 70/100 | Works for text; not TOC/page/section-aware enough for real books. |
| Evidence span lineage | 80/100 | Supports metadata fields and hash; automatic page/paragraph extraction depends on upstream parser. |
| Automatic knowledge extraction | 65/100 | Deterministic candidate generation works; model-assisted provider is opt-in and locally validated. |
| Knowledge graph construction | 75/100 | Relations, graph snapshot, explorer, conflict review exist; full semantic graph construction from a book is not automatic yet. |
| Feedback learning | 75/100 | Usage/review/reader feedback can influence recommendations and weights; needs real volume. |
| Governance/audit | 85/100 | Mutation/version/lineage/audit and approval first slice exist. |
| UI operations | 75/100 | MKAOS console is operational; large-scale graph/extraction workbench remains P2. |
| End-to-end professional book ingestion | 68/100 | Safe ingestion works; full book-to-knowledge-graph automation remains incomplete. |

Overall:

```text
MKAOS Knowledge Asset OS kernel: 82/100
Professional book import and chunking: 70/100
Professional book -> mature knowledge graph automation: 58/100
```

## 6. What Is Required To Claim Full Professional Book Automation

To claim “导入一本专业书籍自动拆分并沉淀为知识资产操作系统资产,” the system still needs:

1. **Document parser adapters**
   - PDF / EPUB / DOCX / Markdown.
   - Page, heading, footnote, table, figure, citation extraction.
   - Operator-visible parser report.

2. **TOC-aware chunking**
   - Preserve book chapter and section hierarchy.
   - Chunk by heading and semantic unit, not only paragraph length.
   - Store `page_start/page_end`, `section_title`, `paragraph_start/end`, `char_start/end`.

3. **Batch extraction run**
   - `professional_book_extraction_run`.
   - Iterate all chunks under budget.
   - Produce candidates grouped by discipline, concept, flow, risk, and evidence span.
   - Deduplicate concepts across chapters.

4. **Candidate review queue**
   - Approve / reject / merge / split candidate.
   - Human approval and guarded auto policy.
   - Batch approve only when quality and copyright risk pass.

5. **Rule/template extraction**
   - KnowledgeCard candidates.
   - RuleCard candidates.
   - TemplateCard candidates.
   - Cross-discipline fusion candidates.

6. **Graph auto-linking**
   - Detect supports / contradicts / refines / requires / forbids.
   - Create graph relations with confidence.
   - Run semantic conflict review.

7. **Regression suite generation**
   - Convert important rules and source leakage risks into KnowledgeRegressionCase.
   - Run on every selector/extraction change.

8. **Effect validation**
   - Track which book-derived knowledge was used.
   - Measure review pass, reader feedback, publish gate, source leakage, and anti-encyclopedia issues.
   - Feed results into Knowledge Quality Score and Feedback Learning.

## 7. Implemented Next Slice

The next slice has been implemented as a local-first professional book import run.

Implemented:

1. `professional_book_import_run` run asset.
2. Parser boundary for text / Markdown and optional PDF / EPUB / DOCX adapters.
3. Section-aware Markdown / book-heading parser.
4. Section-aware chunking with chapter/section/paragraph metadata.
5. Evidence span creation for structured chunks.
6. Full-book batch extraction first slice across selected chunks.
7. KnowledgeCard candidate generation.
8. RuleCard candidate generation.
9. TemplateCard candidate generation.
10. Governance approval queue for knowledge/rule/template candidates.
11. Candidate relation auto-linking for `supports`, `validated_by_rule`, and `used_by_template`.
12. Graph Explorer refresh after import.
13. Product and compatibility API endpoint:

```text
POST /product/mkaos/professional-book/import-run
POST /api/mkaos/professional-book/import-run
```

Key implementation files:

- `src/novel_forge/modules/mkaos/service.py`
- `src/novel_forge/api/routers/mkaos.py`
- `src/novel_forge/modules/mkaos/__init__.py`
- `tests/unit/test_mkaos_professional_book_import.py`
- `tests/acceptance/test_mkaos_professional_book_import.py`

Current first-slice flow:

```text
text / markdown / optional file parser
  -> structured sections
  -> section-aware source chunks
  -> evidence spans
  -> professional_book_extraction_run
  -> knowledge_card_candidate
  -> rule_card_candidate
  -> template_card_candidate
  -> knowledge_governance_approval queue
  -> candidate knowledge relations
  -> graph explorer report
```

Acceptance criteria:

1. Import a synthetic professional-book fixture with chapters/sections: implemented.
2. Preserve section metadata in chunks and evidence spans: implemented.
3. Generate KnowledgeCard candidates: implemented.
4. Generate RuleCard/TemplateCard candidates: implemented.
5. No raw source text enters import run report: implemented.
6. Candidate approval creates active KnowledgeCards: implemented.
7. Candidate relations are auto-linked: implemented.

Remaining after this slice:

1. PDF / EPUB / DOCX parsing is adapter-based and dependency-optional; real parser quality still needs online/manual fixture validation.
2. Section-aware chunking is heading-aware, not a full scholarly TOC/footnote/table parser.
3. Rule/template candidates are deterministic first slice, not model-grade extraction.
4. Candidate graph links are conservative relation candidates and require review before production activation.
5. UI can call the endpoint through API work later; the backend and tests are complete first.

## 8. Verification Run

The following focused tests passed before this implementation:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_import_pipeline tests.unit.test_mkaos_extraction_agent tests.unit.test_mkaos_evidence_span tests.unit.test_mkaos_source_leakage_regression tests.unit.test_mkaos_provider_semantic_governance
```

Result:

```text
Ran 11 tests in 1.840s
OK
```

Additional implementation verification:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_professional_book_import tests.acceptance.test_mkaos_professional_book_import
PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_import_pipeline tests.unit.test_mkaos_extraction_agent tests.unit.test_mkaos_evidence_span tests.unit.test_mkaos_source_leakage_regression tests.unit.test_mkaos_knowledge_graph_v1 tests.unit.test_mkaos_graph_explorer tests.unit.test_mkaos_professional_book_import tests.acceptance.test_mkaos_professional_book_import
```

Result:

```text
Ran 13 tests
OK
```

## 9. Final Answer

MKAOS is substantially complete as a P1 Knowledge Asset OS kernel. It can safely import professional-book text/Markdown and automatically split it into section-aware source chunks, with evidence isolation, batch candidate extraction, rule/template candidate generation, approval queue creation, and candidate relation auto-linking.

It still should not be described as a fully automatic “professional book -> complete mature multi-disciplinary knowledge graph” pipeline. Production-grade book ingestion still needs robust real file parser validation, richer TOC/footnote/table parsing, model-assisted extraction quality proof, UI batch review ergonomics, and long-run effect validation.
