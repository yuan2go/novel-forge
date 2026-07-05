# Module Map

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

This map lists current implementation areas and evidence paths. Status means code was found in the current repository; it does not imply complete product maturity.

## Entrypoints

| Area | Path | Key Responsibilities | Status | Extension Notes |
|---|---|---|---|---|
| Package | `src/novel_forge/__init__.py` | Package identity/version | Implemented | Keep version aligned with `pyproject.toml` and API metadata |
| CLI | `src/novel_forge/cli.py` | Local commands, pipeline, validation, industrial operations, API/worker launch | Implemented | Add command tests in `tests/unit/test_cli.py` for new commands |
| API app | `src/novel_forge/api/app.py` | FastAPI app, health, assets, pipeline/task roots, product routers | Implemented | Route additions should go through product router registration |
| Product routers | `src/novel_forge/api/routers/` | Product API surface | Implemented, depth varies | Keep routers thin; move logic to services/modules |
| Product services | `src/novel_forge/api/services/` | API use cases, task helpers, fallback policy, asset index | Partially split | Continue moving use cases out of monolithic service methods |
| Web console | `web/admin/app/` | Next.js route pages and feature components | Implemented shell | New routes need API helpers, tests/smoke, and docs |
| Tests | `tests/` | Unit, integration, acceptance fixtures | Broad coverage | Add characterization tests before splitting large services |

## Creative Pipeline Modules

| Module | Path | Responsibility | Status | Tests / Evidence |
|---|---|---|---|---|
| Source intake / ingestion | `modules/source_intake/`, `modules/ingestion/` | Import raw/source assets, file handling, source metadata | Implemented | `test_source_intake.py`, ingestion/MKAOS tests |
| Cleaning | `modules/cleaning/service.py` | Normalize raw text into cleaned assets | Implemented | `test_module_services.py` |
| Decomposition | `modules/decomposition/service.py` | Abstract deconstruction assets | Implemented | pipeline/module tests |
| Analysis | `modules/analysis/service.py` | Web/published/classic analysis report creation | Partially implemented | `test_analysis_services.py` |
| Knowledge | `modules/knowledge/service.py` | Knowledge card extraction/use | Implemented | module tests |
| Materials | `modules/materials/service.py` | Reusable material cards | Implemented | module tests |
| Topics | `modules/topics/service.py` | Topic seed and development | Implemented | CLI/module tests |
| Worldbuilding | `modules/worldbuilding/service.py` | World bible generation | Implemented | module tests |
| Characters | `modules/characters/service.py` | Character cards | Implemented | module tests |
| Outline | `modules/outline/service.py`, `modules/long_planning/service.py` | Long outline and planning | Implemented | module tests |
| Chapter plan | `modules/chapter_plan/service.py` | Chapter-level plan | Implemented | module tests |
| Drafting | `modules/drafting/service.py` | Draft chapter candidate | Implemented for local/runtime slices | provider/runtime tests |
| Review / revision / editor | `modules/review/`, `modules/revision/`, `modules/editor/`, `modules/review_issue/` | Review report, issue, revision task, editor patch | Implemented, still deepening | review issue and editor tests |
| Feedback | `modules/feedback/`, `modules/feedback_backflow/` | Reader feedback import/analysis/backflow | Partially implemented | feedback tests |

## Novel OS Runtime Modules

| Module | Path | Responsibility | Status | Notes |
|---|---|---|---|---|
| OS Envelope | `modules/os_envelope/service.py` | Runtime context/evidence boundary | Partially implemented | Needs universal path coverage |
| Context Builder | `modules/context_builder/service.py` | Context plan, bundle, source isolation | Partially implemented | Continue KG/context invalidation depth |
| Workflow nodes | `modules/workflow_nodes/` | Node execution/query/control/publishing ops | Partially split | Use seam files for new side-effect boundaries |
| Agent registry | `modules/agent_registry/service.py` | Runtime profile/operation registry assets | First slice | Add operation coverage as Agents mature |
| Agent scheduler | `modules/agent_scheduler/` | Queue lifecycle, operation registry, runners, lease/retry/recovery/rollback/dead-letter | First production slices | Keep service facade thin; add tests before each split |
| Agent runs/messages | `modules/agent_runs/`, `modules/agent_messages/` | Agent run records and message bus slices | Partially implemented | Needs UI/product flow depth |
| Runtime policy | `modules/runtime_policy/service.py` | Provider policy and runtime envelope checks | Partially implemented | Continue hard-stop coverage |
| Runtime ledger | `modules/runtime_ledger/service.py` | Trace, gate, model call, cost evidence | Partially implemented | All model paths should write evidence |
| Model router/gateway | `modules/model_router/service.py`, `model_adapters/` | Provider route resolution and guarded calls | Partially implemented | Production provider allowlist/approval evidence is critical |
| Loop kernel | `modules/loop_kernel/service.py` | Governance loops and iteration | Partially implemented | Productized learning loops remain partial |
| Operation transactions/checkpoints | `modules/operation_transactions/`, `modules/operation_checkpoint/` | Transaction, checkpoint, rollback evidence | Partially implemented | Multi-asset rollback depth still growing |

## Knowledge, Canon, And Stability

| Module | Path | Responsibility | Status | Notes |
|---|---|---|---|---|
| MKAOS core | `modules/mkaos/` | Knowledge asset selection, risk, quality, pack policy | Broad partial implementation | Continue use-case split and gate hardening |
| MKAOS ingestion | `modules/mkaos_ingestion/` | Repository/book import, chunking, rights, file formats | Implemented slices | Acceptance tests exist |
| MKAOS quality | `modules/mkaos_quality/` | Source risk, quote leakage, near duplicate, flow binding, usability gates | Implemented slices | Needs production calibration |
| MKAOS model extraction | `modules/mkaos_model_extraction/` | Prompt registry, provider runner, sanitizer, confidence, candidate validation | Partially implemented | Provider paths must stay guarded |
| MKAOS converters | `modules/mkaos_converters/` | Knowledge -> creative assets/rules/hooks | Implemented slices | Lineage must remain visible |
| Canon graph | `modules/canon_graph/service.py` | Canon graph snapshots/conflict/impact | Partially implemented | Human-grade merge workflows remain partial |
| Novel KG | `modules/novel_kg/` | Typed ontology/KG workbench | Partially implemented | Graph backend depth remains partial |
| Continuity graph | `modules/continuity_graph/service.py` | Continuity reports and graph slices | Partially implemented | Long-form consistency remains high-risk |
| Longform recap/stability | `modules/longform_recap/`, `modules/longform_stability/` | Long-chain state, recap, stability gates | Partially implemented | Full novel-scale autonomous proof not complete |

## Quality, Publishing, And Operations

| Module | Path | Responsibility | Status | Notes |
|---|---|---|---|---|
| Evaluation center | `modules/evaluation_center/service.py` | Eval cases/results, gate integration | Partially implemented | Needs broader production fixtures |
| Publishing | `modules/publishing/` | Publish gate, release gate, release package, adapters | Partially implemented | Main implementation is being migrated here from audit |
| Audit / audit log | `modules/audit/`, `modules/audit_log/` | Review/originality/audit assets and logs | Partially implemented | Publishing logic should keep moving out of audit |
| Platform strategy | `modules/platform_strategy/service.py` | Platform strategy pack and fit | Partially implemented | Real platform integration partial |
| Permission center | `modules/permission_center/service.py` | Tool/provider permission surface | Partially implemented | Needs ongoing hard-stop verification |
| Metrics / analytics | `modules/metrics/`, `modules/clickhouse_analytics/` | Dashboards/analytics slices | Partially implemented | ClickHouse optional profile |
| Provider fallback | `modules/provider_fallback/service.py` | Environment policy and fallback governance | Partially implemented | Production/local fallback policy remains important |

## Skills

| Area | Path | Status | Rule |
|---|---|---|---|
| Project Skill source | `skills/` | Implemented | Source of truth |
| Claude runtime Skill copy | `.claude/skills/` | Implemented/generated plus external Skills | Do not edit as source |
| Sync script | `scripts/sync_claude_skills.py` | Implemented | Use `make sync-skills-dry-run`, `make sync-skills`, `make check-skills` |
| Skill docs | `docs/09-skills/` | Partially current | Use with current code evidence |
