# GitHub Knowledge Source Intake

Novel Forge can use GitHub repositories as research entrances for multidisciplinary knowledge parsing, but they are not treated as ready-made fiction material.

## Source Tiers

| Tier | Examples | Pipeline Use | Boundary |
|---|---|---|---|
| A: lower-risk public or clearly licensed sources | Project Gutenberg, original project notes, confirmed public-domain corpora | corpus analysis, knowledge cards, material cards | verify country-specific copyright and license before raw storage |
| B: research reference sources | CBETA, CBDB, CHGIS, web-novel research datasets, paper datasets | mechanism extraction, relation models, map rules, review checks | do not redistribute raw data; keep commercial/non-commercial limits visible |
| C: index or high-risk observation sources | Chinese Text Project, forum corpora, tieba/douban/comment data, crawler tools | metadata, manual notes, aggregate feedback, risk rules | no bulk crawling, no raw user content storage, no direct generation |

## Default Acquisition Order

1. Official data package.
2. Official API.
3. Official machine-readable catalog or robot endpoint.
4. GitHub repository after license review.
5. Manual notes and metadata.
6. Ordinary webpage crawling only when explicitly permitted.

## Registered GitHub Categories

The backend registry in `novel_forge.modules.source_intake` currently tracks:

- Ancient Chinese and allusion resources for classical language, mythology, historical entities, and naming rules.
- Web-novel research corpora for genre structure, NER, and reader/metadata analysis.
- Paper metadata and research datasets for extraction, classification, and review methodology.
- Dialogue, forum, and crawler-tool repositories for aggregate pattern and risk analysis only.

## Handoff Workflow

Use `POST /product/handoffs/github-knowledge` with registered repository ids or names.

The API writes a metadata-only `SourceDocument` under `data/raw/`, then creates a `ClaudeCodeHandoff` for `multidisciplinary-knowledge`.

The handoff requires Claude Code/Codex to:

- verify repository license before reading or downloading raw files;
- record source ids, source URLs, and license review status in the `KnowledgeCard` metadata;
- keep `raw_text_used=false` unless an explicit compatible license permits raw access;
- extract abstract principles, constraints, conflict generators, review checks, or story functions;
- avoid storing raw forum posts, user identifiers, protected web-novel prose, and crawler outputs as reusable assets.

## Non-Goals

- This is not a general GitHub crawler.
- This does not auto-clone repositories.
- This does not bypass robots rules, platform terms, non-commercial licenses, or data redistribution limits.
- This does not allow raw third-party text to enter the commercial drafting path without review.
