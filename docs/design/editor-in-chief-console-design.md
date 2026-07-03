# Editor-in-Chief Console Design

Date: 2026-07-04

## Objective

Editor-in-Chief Console is the top-level editorial control surface for Novel OS. It answers whether a book can continue production, must pause for repair, or can proceed toward publishing without forcing the operator to inspect Canon, Character, Arc, Foreshadowing, ReviewIssue, Longform Recap, LoopRun, Agent Center, and Publish Gate pages one by one.

## Product Questions

| Editor Question | System Answer |
| -- | -- |
| Is the book healthy? | Overall quality score, risk level, continue/pause/publish decision |
| Has the mainline drifted? | Arc progress score, Canon Graph alerts, plot/canon ReviewIssue evidence |
| Did characters drift? | Character drift issues, state ledgers, active burdens, remaining debt |
| Are foreshadowing threads broken? | Open, dropped, expired clues and foreshadowing graph alerts |
| Are the last 10 chapters fatigued? | Pattern similarity, motif budget, reader fatigue reports |
| What should the next 10 chapters do? | Next-10 strategy, platform beats, do-not rules |
| What must be fixed first? | Blocking ReviewIssue plus active RevisionTask queue |
| Can it publish? | Publish Gate, release package status, platform fit |

## Architecture

The console is a read-only aggregation layer:

- Backend service: `src/novel_forge/modules/editor_chief/service.py`
- Product API: `GET /product/editor-chief/snapshot`
- Admin page: `/editor-chief`
- UI component: `web/admin/app/features/os/EditorChiefConsolePage.tsx`

The service reads existing governance artifacts and public services:

- Longform Stability dashboard
- Canon Graph reasoning
- ReviewIssue list
- Publishing assets
- platform strategy / retention / adapter assets
- longform evidence assets such as chapter pattern, motif budget, reader fatigue, character state, foreshadowing graph, and arc plan

It does not write assets or trigger generation. This keeps the total-control view from changing production state simply by opening it.

## Decision Model

The snapshot computes:

- `overall_health.quality_score`
- `overall_health.risk_level`
- `executive_decision.decision`
- `executive_decision.can_continue`
- `executive_decision.must_pause`
- `executive_decision.can_publish`

Blocking ReviewIssue, blocked Publish Gate, Canon Graph blocked status, and major longform evidence failures push the decision toward `pause_for_revision`. A ready publish gate without active blockers can become `ready_to_publish`. Medium risk becomes `continue_with_caution`.

## UI Contract

The first viewport shows:

- project selector;
- direct links to related consoles;
- decision summary;
- quality/risk metrics.

The body maps to the eight editor questions, using the existing admin design system: `FeatureShell`, `Metric`, `PanelHeader`, `DataTable`, badges, and links. It does not introduce a separate SaaS-style dashboard or login surface.

## Current Limits

1. The score is rule-based and deterministic; it is not a trained quality model.
2. Platform fit currently reads local strategy and publish evidence, not external platform telemetry.
3. Next-10 strategy is advisory and should later be converted into LoopRun/AgentTask operations.
4. The console is read-only; future P1 work can add controlled actions such as dispatching RevisionTask from selected blocking issues.
