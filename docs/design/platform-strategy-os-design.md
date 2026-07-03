# Platform Strategy OS Design

Date: 2026-07-03

## Objective

Platform Strategy OS models platform differences as production logic, not prose-style switches. The same topic can now produce different outline, chapter, prose, gate, publishing, and feedback strategies for different target platforms.

## Covered Platforms

| Platform | Core Strategy |
| -- | -- |
| 起点 | Long growth, world depth, paid retention, mainline stability |
| 番茄 | Fast pace, strong emotion, reversal density, low reading barrier |
| 飞卢 | Pleasure density, strong premise, identity gap, fast feedback |
| 晋江 | Relationship tension, emotional arc, character charm, bond progression |
| 知乎盐选 | Sharp hook, realism, short/mid structure, reversal density |
| 微信读书/出版向 | Literary quality, structural integrity, theme expression, language stability |

## Asset Types

- `platform_profile`
- `platform_rhythm_rule`
- `platform_opening_gate`
- `platform_chapter_gate`
- `platform_retention_risk`
- `platform_publish_adapter`
- `platform_feedback_backflow`
- `platform_strategy_pack`

`platform_strategy_pack` is the runtime bundle consumed by planning context. It combines the platform profile, rhythm rule, gates, publish adapter, feedback backflow, and derived outline/chapter/prose strategies.

## Service Boundary

Module:

- `src/novel_forge/modules/platform_strategy/service.py`

Public functions:

- `ensure_default_platform_strategy_assets`
- `list_platform_strategy_assets`
- `build_platform_strategy_pack`
- `evaluate_platform_opening_gate`
- `evaluate_platform_chapter_gate`
- `assess_platform_retention_risk`
- `prepare_platform_publish_adapter`
- `create_platform_feedback_backflow`

## API

- `GET /product/platform-strategy/assets`
- `POST /product/platform-strategy/defaults`
- `POST /product/platform-strategy/pack`
- `POST /product/platform-strategy/opening-gate`
- `POST /product/platform-strategy/chapter-gate`
- `POST /product/platform-strategy/retention-risk`
- `POST /product/platform-strategy/publish-adapter`
- `POST /product/platform-strategy/feedback-backflow`

## Generation Integration

`build_planning_context` now builds and injects `platform_strategy` for project-bound Outline and ChapterPlan flows. The generated planning context includes:

- strategy pack id/path;
- platform id/name;
- outline strategy;
- chapter strategy;
- prose strategy;
- validation policy.

Outline and ChapterPlan fallback logic now uses platform-specific pacing, required beats, opening requirements, risk controls, and word budgets.

## Current Limits

1. The first slice uses deterministic built-in platform strategies, not external platform analytics.
2. Gates are heuristic and intended as production proof, not final editorial scoring.
3. UI-specific platform strategy console is not yet implemented.
4. External publish adapter still prepares local release contracts; real platform API integrations remain future work.
