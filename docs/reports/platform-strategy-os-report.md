# Platform Strategy OS Implementation Report

Date: 2026-07-03

## Summary

Implemented Platform Strategy OS as a schema-backed strategy layer for platform-specific production logic. The system now distinguishes 起点、番茄、飞卢、晋江、知乎盐选、微信读书/出版向 by outline architecture, chapter rhythm, prose policy, opening gates, chapter gates, retention risk, publish adapter rules, and feedback backflow mappings.

## Implemented

1. Added platform strategy asset types:
   - `platform_rhythm_rule`
   - `platform_opening_gate`
   - `platform_chapter_gate`
   - `platform_retention_risk`
   - `platform_publish_adapter`
   - `platform_feedback_backflow`
   - `platform_strategy_pack`
2. Added default platform strategy library for six platform families.
3. Added `platform_strategy` service with pack building, gate evaluation, retention risk, publish adapter, and feedback backflow.
4. Added Product API router under `/product/platform-strategy/*`.
5. Integrated `platform_strategy_pack` into `build_planning_context`.
6. Routed Outline and ChapterPlan fallback constraints through platform-specific pacing, required beats, risk controls, and word budget.
7. Added unit tests proving same-topic platform divergence and planning context injection.
8. Made persisted `platform_strategy_pack` ids deterministic so pipeline replays do not create random platform assets.

## Key Files

- `src/novel_forge/modules/platform_strategy/service.py`
- `src/novel_forge/api/routers/platform_strategy.py`
- `src/novel_forge/modules/planning_context.py`
- `src/novel_forge/modules/outline/service.py`
- `src/novel_forge/modules/chapter_plan/service.py`
- `src/novel_forge/schemas/assets.py`
- `src/novel_forge/schemas/base.py`
- `tests/unit/test_platform_strategy_os.py`

## Verification

Passed:

- `python3 -m compileall -q src/novel_forge/modules/platform_strategy src/novel_forge/api/routers/platform_strategy.py src/novel_forge/modules/planning_context.py src/novel_forge/modules/outline src/novel_forge/modules/chapter_plan src/novel_forge/schemas`
- `python3 -m unittest tests/unit/test_platform_strategy_os.py`
- `python3 -m unittest tests/unit/test_product_api_routes.py`
- `python3 -m unittest tests/unit/test_context_and_production_chain.py`
- `python3 -m unittest tests/unit/test_schemas.py`
- `python3 -m unittest tests.integration.test_pipeline`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `npm --prefix web/admin test`
- `npm --prefix web/admin run build`

Final results:

- Platform Strategy OS unit tests: 4 tests OK.
- Pipeline idempotency: 1 test OK in 444.668s.
- Full Python discover: 311 tests OK in 1035.242s, skipped=1.
- Admin test/build: OK.

Fix note: the first full discover run exposed that randomly generated strategy pack ids increased `data/platforms` count on pipeline replay. The implementation now uses stable hashed ids for persisted platform strategy packs.

## Remaining Work

1. Add UI console for platform strategy editing and side-by-side strategy comparison.
2. Connect real platform metrics imports into `platform_retention_risk`.
3. Extend publish adapters from local contract preparation to real platform-specific dry-run packages.
4. Add platform strategy visibility inside Agent Center run detail.
