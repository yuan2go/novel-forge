# Bounded Corpus quality evidence

Tested implementation: `d8252aa555e5212a778b23acddb20fac32a0afff`.
The evidence commit changes no identity-covered implementation files.
`report.json` separates deterministic ingestion/review/curation, scripted Source analysis,
and unavailable real model/human/full-edition proofs. This is focused engineering evidence,
not canonical P0, literary quality or a whole-corpus completeness claim.

The 87-node focused collection and 2 migration windows have no skips. `validation.log`
contains the complete applicable `make validate`; `head-integrity.log` is separate.
The migration window is fresh plus the execution-time main head 0126 with existing facts.
Database plans use 5,000 representative fixture rows, rolled back, with default planner
settings. `cleanup.json` records task-owned container/volume removal; source objects and
isolated database backups remain outside Git for audit.

`executed-*.py` are the actual local experiment command records. They use native production
CLI/composition and intentionally point at the isolated run directory, not production.
They are evidence scripts, not another product ingestion/approval route. Do not run them
against a production database. Their environment JSON files contain the caller's own
isolated database configuration and are not in Git. The checked-in manifests retain exact
acquisition/configuration identities, but never novel bytes or credentials.

For supported product commands, use [Corpus operations](../../../docs/runtime-operations.md#canonical-works-and-curated-analysis).
The minimum import/inspect/reprocess commands are in the immediately preceding section.
Use `novel-forge corpus status|pause|resume|cancel|run --project-id "$PROJECT" --job-id "$JOB"`
on the original job. Source/curated decisions require a current exact previous revision.
A frozen curated subset can be dispatched through `corpus analyze` only with explicit
model call/token authorization and current Source use admission; its MKAOS candidates
still require the existing approval path.

To repeat the engineering collection, install `.[api,postgres,provider-openai,test,object,ingestion,industrial]`,
set `NOVEL_FORGE_DATABASE_URL` to a caller-owned disposable PostgreSQL database and set
`CORPUS_TESTED_SHA=$(git rev-parse HEAD)`. The exact argument lists are in `report.json`.
Run `make validate`, those pytest collections, and
`python -m pytest tests/integration/test_corpus_migrations_postgres.py -k '0126 or 0001'`.
No paid inference is needed. Keep evidence in an external directory through
`CORPUS_EVIDENCE_DIR`; raw source bytes remain in the configured object store/cache.

The Sanguo directory assessment is based on newly acquired Wikisource oldid 5401635 bytes,
not the earlier web extraction. Fourteen differences were reviewed: two scoped glyph
variants accepted, twelve wording/transcription/insufficient-evidence findings retained.
Labels are Agent observations, never independent human annotations. No statistical
semantic accuracy is claimed. Three Gutenberg novels were both development and regression
samples; two independent-site first-chapter excerpts were acquired after implementation
freeze. These excerpts do not establish two complete independent editions.

The Honglou TXT title-only duplicate was excluded through a scoped decision and reprocessing;
its raw bytes remain retained. The EPUB's cross-spine continuations remain blocked and
unselected. The final curated revision selects two valid research members and retains all
four excluded members, with their individual reasons and rights. Corpus permissions are
never inherited from a canonical representative.
