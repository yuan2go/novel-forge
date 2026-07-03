# Phase 5 ReviewIssue Report

Date: 2026-07-03

## Completed

- Added `review_issue` schema and local asset mapping.
- Added `review_issues` SQL migration.
- Added ReviewIssue service for create/list/status/update/blocking queries.
- Review service now persists Review/MKAOS issues as durable ReviewIssue assets.
- MKAOS Canon issue candidates can be persisted through the same service.
- Publish gate includes active blocking ReviewIssues.
- Release package fails closed on active blocking ReviewIssues.
- Editor final draft promotion fails closed on active blocking ReviewIssues.
- Added minimal ReviewIssue API routes.
- Added regression tests for MKAOS issue persistence, Canon issue persistence, release blocking, and final draft blocking.

## Tests

| Command | Result |
| -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/review_issue src/novel_forge/modules/review src/novel_forge/modules/audit src/novel_forge/modules/editor src/novel_forge/schemas src/novel_forge/api/routers/reviews.py` | OK |
| `python3 -m unittest tests/unit/test_review_issue.py` | 3 tests OK |
| `python3 -m unittest tests/unit/test_schemas.py` | 17 tests OK |
| `python3 -m unittest tests/unit/test_product_api_routes.py` | 1 test OK |
| `python3 -m unittest tests/unit/test_mkaos.py` | 5 tests OK |
| `python3 -m unittest tests/unit/test_module_services.py` | 10 tests OK |
| `python3 -m unittest tests/unit/test_context_builder_mkaos_flow.py` | 2 tests OK |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | 4 tests OK |
| `python3 -m unittest tests/unit/test_postgres_migrations.py` | 2 tests OK |
| `python3 -m unittest tests/unit/test_publishing_center.py` | 1 test OK |
| `python3 -m unittest tests/unit/test_longform_stability.py` | 8 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 1 test OK, 405.552s |

## Tradeoffs

- ReviewIssue persistence uses local JSON assets first; SQL migration is present for Postgres deployments.
- Existing inline `ReviewReport.issues` remains for compatibility.
- ReviewIssue -> RevisionTask is currently a candidate payload, not automatic task creation outside existing publish gate/rework paths.

## Risks

- Existing tests now produce more review assets; UI filters should distinguish ReviewReport from ReviewIssue.
- Full Agent Center and LoopRun consumption is deferred to Phase 6/8.
