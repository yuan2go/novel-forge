# Reader Feedback Simulation And Backflow Report

Date: 2026-07-04

## Scope

This change upgrades Feedback from a post-publish sentiment loop into a two-layer reader feedback system:

1. Pre-publish reader simulation via deterministic Reader Agent personas.
2. Real feedback backflow from platform metrics and comments into durable Novel OS assets.

## Reader Simulation

New asset: `reader_simulation_report`.

The simulation runs six fixed Reader Agent personas:

- `shuangwen_reader`: payoff density, pace drag, immediate reward.
- `mystery_reader`: fair clues, puzzle pull, reversal credibility.
- `qidian_veteran`: mainline growth, paid value, world stability.
- `fanqie_reader`: direct emotion, reversals, low reading barrier.
- `relationship_reader`: relationship tension, character charm, emotional pull.
- `editor_reader`: commercial value, opening retention, platform fit.

Each persona outputs:

- predicted chapter score;
- dropout risk;
- follow-read motivation;
- pleasure or expectation gap;
- next-chapter expectation;
- revision suggestions;
- explainable signal counts.

Source isolation rule: `reader_simulation_report` rejects `source_document` and `source_chunk` inputs. It only accepts `draft_chapter.text` or explicit project-owned text, and records `source_chunk_raw_text_allowed=false`.

## Real Feedback Backflow

New asset: `reader_feedback_backflow_report`.

The real feedback backflow accepts:

- completion rate;
- follow-read rate;
- comments;
- favorites;
- bookshelf adds;
- rewards;
- chapter drop points;
- negative keywords;
- character mentions.

It writes:

- `operational_metric_snapshot` for normalized real metrics;
- `platform_feedback_backflow` through Platform Strategy OS;
- `review_rule_pack` for feedback-driven review gates;
- `topic_seed` for topic-library calibration;
- two `writing_template` assets for character repair and rhythm repair;
- MKAOS `apply_weight_update` records when project usage events exist;
- `reader_feedback_backflow_report` as the traceable summary.

## API

New endpoints:

- `POST /product/feedback/reader-simulation`
- `POST /product/feedback/real-backflow`

## UI

`/feedback-console` now includes:

- simulated reader pre-read panel;
- real feedback metrics JSON panel;
- summary metrics for simulation risk, MKAOS update count, operational metrics, and backflow targets.

## Tests

Added/updated:

- schema registration and validation for `reader_simulation_report` and `reader_feedback_backflow_report`;
- service proof that reader simulation scores six personas and rejects source chunks;
- service proof that real feedback backflow writes platform, review, topic, template, and MKAOS weight updates;
- Product API route registration for the two new endpoints;
- frontend architecture checks for the two new API calls.

Verification run:

- `python3 -m unittest tests.unit.test_schemas tests.unit.test_publish_feedback_loop tests.unit.test_product_api_routes`: OK, 24 tests.
- `python3 -m unittest tests.unit.test_mkaos tests.unit.test_feedback_backflow tests.unit.test_feedback_metrics_settings tests.unit.test_publish_feedback_loop tests.unit.test_product_api_routes tests.unit.test_schemas`: OK, 31 tests.
- `python3 -m compileall -q src/novel_forge/modules/feedback src/novel_forge/api src/novel_forge/schemas src/novel_forge/agents tests/unit/test_publish_feedback_loop.py`: OK.
- `npm --prefix web/admin test`: OK, 8 pass, 1 Playwright skip.
- `npm --prefix web/admin run build`: OK.

Not completed:

- `python3 -m unittest discover -s tests -p 'test_*.py'` and `python3 -m unittest tests.integration.test_pipeline` were interrupted after several minutes without failure output. The stack at interrupt was inside the existing sample pipeline's RAG/project-scope reference scan, not inside the new feedback simulation/backflow path.

## Remaining Work

- Connect reader simulation risk directly into Publish Gate blocking policy.
- Surface persona-level detail in Editor-in-Chief Console health cards.
- Feed real feedback backflow into Platform Strategy weight evolution instead of only writing project-scoped backflow assets.
- Investigate sample pipeline runtime cost around RAG/project-scope reference scanning before using full-discovery tests as a per-change gate.
