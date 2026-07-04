# MKAOS Knowledge Asset Evolution Report

## Goal

This pass moves MKAOS closer to a knowledge asset operating system: knowledge should improve through graph context, production effect, review outcomes, reader feedback, and controlled mutation rather than remaining static cards.

## Implemented

| Capability | Implementation | Evidence |
| --- | --- | --- |
| Multidisciplinary knowledge graph | Graph snapshots include knowledge cards, disciplines, flows, rules, templates, source evidence nodes, usage bindings, pack usage, and effect-observed edges. Conflict detection now reasons over `contradicts`, `forbids`, and `requires`. | `src/novel_forge/modules/mkaos/service.py`, `build_knowledge_graph`, `detect_knowledge_conflicts` |
| Knowledge effect scoring | Usage events and quality scores aggregate into learning snapshots with recommended weight deltas and confidence. | `learn_from_knowledge_effects`, `_knowledge_learning_metrics` |
| Review rule evolution | `run_knowledge_evolution_cycle` creates review-rule candidates from negative learning signals and reader feedback tags. | `run_knowledge_evolution_cycle`, `_evolve_review_rules_from_learning` |
| Hot-template backflow | Strong positive learning signals and supplied hot-deconstruction patterns become template candidates by default, active templates only when explicitly applied. | `_backflow_templates_from_learning` |
| Reader feedback weight influence | Reader feedback attribution feeds learning signals and top-tag aggregation. Weight/status changes require explicit apply flags. | `attribute_reader_feedback_to_knowledge`, `run_knowledge_evolution_cycle` |
| Low-effect elimination | Repeated negative signals generate `needs_review`, `quarantined`, or `do_not_select` recommendations; optional apply writes status mutation audit. | `_low_effect_knowledge_elimination`, `change_knowledge_status` |
| Standard MKAOS API envelope | MKAOS POST/PATCH responses expose `success`, `request_id`, `trace_id`, `envelope_id`, `data`, `error`, and `warnings` while retaining old top-level fields. | `src/novel_forge/api/routers/mkaos.py` |
| Provider opt-in boundary | Conflict model judge and extraction provider modes are local-first. Opt-in is required before mock/provider results are accepted. | `_model_judge_conflict_result`, `extract_knowledge_candidates` |
| UI operations view | MKAOS console adds a lightweight graph canvas and Knowledge Evolution panel. | `web/admin/app/features/mkaos/MkaosConsolePage.tsx` |

## Follow-up Hardening

| Previous Risk | Hardening |
| --- | --- |
| Deep semantic conflicts needed a model judge or stronger graph reasoning. | Conflict detection now runs transitive graph inference: selected knowledge that supports/requires an intermediate node that forbids/contradicts another selected node becomes a structured conflict. Deterministic semantic-pair rules cover platform rhythm, anti-encyclopedia pressure, and mystery clue-chain conflicts. Model judge remains opt-in. |
| Extraction provider had no real quality validation path. | `validate_extraction_provider_quality` scores model-assisted candidates for schema completeness, flow/discipline classification, confidence, copyright risk, and source-expression overlap. `extract_knowledge_candidates` records this report when provider mode is used. |
| Automatic rule/template activation and knowledge isolation required explicit apply flags only. | `run_knowledge_evolution_cycle` now supports `evolution_mode=guarded_auto` and production guarded policy. It can auto-apply safe rule/template promotions and quarantine high-confidence low-effect knowledge while recording `auto_applied` evidence. |
| Large-scale graph UI was summary/table only. | MKAOS UI now includes a dependency-free Graph Explorer with graph sampling counts, SVG preview, node type distribution, and relation distribution. |

## Operating Policy

Default mode is advisory:

- no automatic rule activation;
- no automatic template activation;
- no automatic knowledge quarantine;
- no real provider calls;
- no source text in graph, pack, context, or evolution reports.

Explicit apply flags:

- `apply_updates`: apply learning weight deltas;
- `apply_rule_updates`: create enabled rule cards;
- `apply_template_updates`: create active templates;
- `apply_elimination`: apply status changes for low-effect knowledge.

Guarded automation:

- `evolution_mode=guarded_auto`: automatically activates safe rule/template promotions and low-effect quarantine when deterministic thresholds are met.
- `evolution_mode=production_guarded`: production-friendly guarded automation, still requiring OS Envelope and runtime policy.
- Real external providers remain opt-in; default tests do not call external services.

## Remaining Gap

MKAOS now acts as a local-first knowledge asset OS kernel. The remaining work is production maturity:

1. richer graph inference across Canon/Character/Arc/Foreshadowing/WorldRule;
2. real model-judge and extraction providers behind Runtime Policy;
3. statistically meaningful feedback volume by platform/genre;
4. human approval UI for rule/template promotion and quarantine;
5. large-graph UI with filtering, path explanation, and diff;
6. long-running acceptance proving selection quality improves across chapters.
