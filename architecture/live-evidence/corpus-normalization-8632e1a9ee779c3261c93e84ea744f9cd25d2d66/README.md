# Corpus normalization focused evidence

Tested revision: `8632e1a9ee779c3261c93e84ea744f9cd25d2d66`.
Implementation commit: `47cf86bf8e02e83a7a572f30dfaba7ab5d7b1013`.
Their implementation identity is `sha256:499708477473f917ff60558dfb4004c2b42cc27958829c8be1f863c3c54ea01c`.
The later evidence commit does not change implementation files.

`report.json` contains commands, dependency identity, failures, proof scope and limits.
JUnit records 74 unit nodes, 35 PostgreSQL nodes and one current-main upgrade node, with
zero failures/errors/skips. Historical upgrade alternatives were deliberately not selected.
This is focused qualification; full P0, UI and real-model campaigns were not run.

| Behavior | Native entry and consumer | Evidence |
|---|---|---|
| Import, segmentation, preserved byte/record lineage | Corpus CLI/API → SourceImport worker → SourceWork/Transform/Chunk | native-operations.json, native-storage-checks.json |
| Review and exact boundary repair | Source Corpus command → immutable review → existing work operation | bound-postgres.xml |
| Parent/review/fence changes | preparation plus atomic publication validation | bound-postgres.xml |
| Versioned reprocessing and old history | same Edition/acquisition → new SourceWork/Bridge; old knowledge consumption rejected | legacy-upgrade-summary.json, bound-history-preservation.json |
| Exact/near candidates and pair decisions | indexed processing query → explicit Source decision; no rights transfer | native-format-summary.json, bound-query-plans.json |
| Benchmark/research isolation and authorized abstract knowledge | existing Source/MKAOS admission, Pack and Context boundaries | bound-postgres.xml |

The real sample is [Project Gutenberg 23950](https://www.gutenberg.org/ebooks/23950),
separately acquired TXT and HTML representations from the same catalogue. They are not
independent publisher editions. Raw source, object store and all development failures remain
outside Git at `/tmp/nf-corpus-wp3-20260909`. The sample runs made no model calls.
TXT parsed into 120 chapters. Publisher framing was explicitly reviewed and retained as
excluded source units; normalized structure became usable but completeness remained UNKNOWN.
Requiring the [fixed Wikisource catalogue](https://zh.wikisource.org/w/index.php?oldid=5401635&title=%E4%B8%89%E5%9C%8B%E6%BC%94%E7%BE%A9)
correctly produced REVIEW_REQUIRED. Ignoring number style, spacing and punctuation gives
106 matching titles and 14 unresolved differences. Preface coverage also differs.
These are source/agent observations, not independent human labels or semantic accuracy.

`bound-matching.json` uses four explicitly synthetic variants of chapters 21–30, with the
unchanged threshold; zero candidate-label mismatches in those four fixtures is not a
population accuracy claim. Discovery stays bounded and may miss candidates. Accepted
pair relations do not create an automatic transitive canonical group.

For a local run, configure PostgreSQL, trusted principal/project scope, object storage and
local allowed roots as described in `docs/runtime-operations.md`. With existing Project
Authority identifiers, use the native entry:

```bash
novel-forge corpus import --project-id "$PROJECT" --workspace-id "$WORKSPACE" \
  --manifest config/corpus/chinese-longform-local.json --source "$LOCAL_BOOK" --run-key first-parse
novel-forge corpus run --project-id "$PROJECT" --job-id "$JOB"
novel-forge corpus lineage --project-id "$PROJECT" --job-id "$JOB"
novel-forge corpus inspect --project-id "$PROJECT" --edition-id "$EDITION"
novel-forge corpus reprocess --project-id "$PROJECT" --edition-id "$EDITION" \
  --manifest parser.json --run-key reviewed-parser
novel-forge corpus resume --project-id "$PROJECT" --job-id "$REPROCESS_JOB"
```

JOB is returned by import, Edition by lineage, and the complete frozen parser profile by
inspect. Review/equivalence payloads and pause/cancel commands are documented in the same
operations guide. No SQL or manual acquisition/Bridge creation is required.

The owned PostgreSQL container and its anonymous volume were removed after export.
Verified source/evidence files remain outside Git; unrelated user resources were untouched.
