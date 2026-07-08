# Module Map

Updated: 2026-07-08
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`, starting commit `3f68522`

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

## V7 Content Intelligence Modules

| Module | Path | Responsibility | Status | Tests / Evidence |
|---|---|---|---|---|
| Genre OS | `modules/genre_os/service.py` | Genre profiles, subgenre mechanics, platform fit, template binding, strategy packs, risk gates | Implemented foundation | `tests/unit/test_genre_os.py`, `api/routers/genre_os.py`, Web route `genre-console` |
| Style OS | `modules/style_os/service.py` | Authorized style sample ingestion, abstract fingerprinting, style profile/policy/rule, drift gate | Implemented foundation | `tests/unit/test_style_os.py`, `api/routers/style_os.py`, Web route `style-console` |
| Canon Graph 2.0 plugins | `modules/canon_graph/service.py` | Genre-specific canon reports, ledger, typed graph reducer snapshot/diff, and ReviewIssue conversion for critical conflicts | Implemented foundation plus reducer | `tests/unit/test_canon_graph_plugins.py`, `/product/canon-graph/plugin`, Web route `canon-graph-v2` |
| Quality Eval 2.0 / Eval Center | `modules/quality_eval/service.py`, `modules/evaluation_center/service.py` | Rubric packs, Opening 3/Golden 10/Volume 30/Longform 100 reports, provider-backed judge evidence, provider run reports, gates, human annotations, golden sets, provider calibration reports | Implemented provider-evidence and calibration foundation | `tests/unit/test_quality_eval_v2.py`, `api/routers/quality_eval_v2.py`, `api/routers/evaluation.py`, Web route `quality-eval-v2` |
| Long-chain Proof Center | `modules/long_chain_proof/service.py`, `modules/v7_provider_proof/service.py` | Deterministic/mock/state-only runs, opt-in provider 50 proof, and aggregate V7 provider proof manifest for opening/single/50 evidence | Implemented foundation | `tests/unit/test_long_chain_proof.py`, `tests/unit/test_v7_provider_proof.py`, `/product/provider-proof/v7`, integration 50-chapter fixture, Web route `long-chain-proof` |
| Publishing/Feedback Adapter 2.0 | `modules/publishing_feedback_adapters/service.py` | Manual upload package, Fanqie/Qidian project-scoped rule snapshots, platform adapter gate, receipt parser confidence/status normalization, generic HTTP platform publish adapter, receipts/status, metrics, comments, clustering, human-gated mutation proposal, patch artifacts, planned AgentTasks, re-review plan, publish-gate rerun plan | Implemented foundation plus hardened platform-specific manual and feedback-apply slices | `tests/unit/test_publishing_feedback_adapters.py`, Web route `publishing-feedback-v2` |
| V7 Agent operations | `modules/agent_scheduler/service.py` | Scheduler operation specs/runners for new V7 build/run/import/cluster/proposal/provider/platform/provider-proof operations | Implemented foundation | Agent scheduler/registry tests |
| V7 workflow processors | `modules/workflow_nodes/service.py` | Processor registry entries for V7 service operations, provider quality judge, provider proof, and platform API publish | Implemented foundation | Workflow runtime smoke tests plus focused module tests |
| V7 shared UI / OS Cockpit | `modules/novel_os_cockpit/service.py`, `web/admin/app/features/content-intelligence/ContentIntelligencePages.tsx`, `web/admin/app/features/os/OperatingSystemConsolePage.tsx` | API-backed consoles, provider judge controls, platform gate controls, Artifact Inspector, V1 artifact coverage, production gate board, workflow governance readiness, feedback approval queue, multi-book cost/quality dashboard, and parallel schedule view | Implemented foundation plus production control console | `tests/unit/test_novel_os_cockpit.py`, `npm --prefix web/admin run lint`, `npm --prefix web/admin test` |
| Portfolio OS | `modules/portfolio_os/service.py` | PortfolioProject, BookPotentialScore, CrossBookSimilarityReport, BookLifecycleGateReport, ResourceAllocationPlan, approval-gated scheduler plan, planned AgentTasks, per-book isolation contract, contamination guard, cost-quality rollup, non-dispatching allocation plan | Implemented foundation | `tests/unit/test_portfolio_os.py`, API routes `/product/portfolio/*` |

## Creative Pipeline Modules

| Module | Path | Responsibility | Status | Tests / Evidence |
|---|---|---|---|---|
| Source intake / ingestion | `modules/source_intake/`, `modules/ingestion/` | Import raw/source assets, file handling, source metadata, source policy/license/risk/snapshot/sync-job lifecycle, R0-R4 context eligibility | Implemented foundation | `test_source_intake.py`, ingestion/MKAOS tests, `/product/sources/*` routes |
| Cleaning | `modules/cleaning/service.py` | Normalize raw text into cleaned assets | Implemented | `test_module_services.py` |
| Decomposition | `modules/decomposition/service.py` | Abstract deconstruction assets | Implemented | pipeline/module tests |
| Analysis | `modules/analysis/service.py` | Web/published/classic analysis report creation | Partially implemented | `test_analysis_services.py` |
| Knowledge | `modules/knowledge/service.py` | Knowledge card extraction/use | Implemented | module tests |
| Materials | `modules/materials/service.py` | Reusable material cards | Implemented | module tests |
| Topics | `modules/topics/service.py` | Topic seed and development | Implemented | CLI/module tests |
| Worldbuilding | `modules/worldbuilding/service.py` | World bible generation | Implemented | module tests |
| Characters | `modules/characters/service.py` | Character cards | Implemented | module tests |
| Outline | `modules/outline/service.py`, `modules/long_planning/service.py` | Long outline and planning | Implemented | module tests |
| Chapter plan | `modules/chapter_plan/service.py` | Chapter-level plan with embedded blueprint contract | Implemented | `test_chapter_blueprint_contract.py` plus module tests |
| Drafting | `modules/drafting/service.py` | Draft chapter candidate using chapter blueprint evidence | Implemented for local/runtime slices | provider/runtime and blueprint handoff tests |
| Review / revision / editor | `modules/review/`, `modules/revision/`, `modules/editor/`, `modules/review_issue/`, `modules/content_quality_loop/` | Review report, readable gate, issue strategy contract, revision task, revision plan, editor patch, re-review evidence | Implemented, still deepening | `test_review_issue.py`, `test_content_quality_loop.py`, `test_module_services.py`, `test_loop_kernel.py`, and editor tests |
| Feedback | `modules/feedback/`, `modules/feedback_backflow/` | Reader feedback import/analysis/backflow | Partially implemented | feedback tests |

## Novel OS Runtime Modules

| Module | Path | Responsibility | Status | Notes |
|---|---|---|---|---|
| OS Envelope | `modules/os_envelope/service.py` | Runtime context/evidence boundary | Partially implemented | Needs universal path coverage |
| Context Builder | `modules/context_builder/service.py` | Context plan, bundle, stage profile contract, source isolation | Partially implemented | Stage-specific profile enforcement exists; continue KG/context invalidation depth and final workflow assertions |
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
| Reader Promise | `modules/reader_promise/service.py` | Project-owned promise/payoff lifecycle, per-draft ledger, broken-promise ReviewIssue/RevisionTask hook | Implemented foundation | Payoff detection is deterministic and needs calibration plus UI repair depth |
| Chapter Economy | `modules/chapter_economy/service.py` | Pleasure point extraction, scene-value scoring, watery/repeated-payoff risk, ReviewIssue/RevisionTask hook | Implemented foundation | Heuristic detection needs provider/human calibration and guided repair UI |
| Character Pressure | `modules/character_pressure/service.py` | Protagonist agency/charm scoring, antagonist/proxy pressure scoring, weak-agency/weak-pressure ReviewIssue/RevisionTask hook | Implemented foundation | Heuristic detection needs provider/human calibration and guided repair UI |
| Mobile Reading | `modules/mobile_reading/service.py` | Paragraph density, long paragraph, dense beat, and scanability report with ReviewIssue/RevisionTask hook | Implemented foundation | Heuristic detection needs provider/human calibration and guided repair UI |
| Longform recap/stability | `modules/longform_recap/`, `modules/longform_stability/` | Long-chain state, v1 reducer into CanonGraph state-machine ledger/snapshot/diff, explicit light/formal recap cadence, stability gates | Partially implemented | Operator-configurable cadence UI and full novel-scale autonomous proof not complete |

## Quality, Publishing, And Operations

| Module | Path | Responsibility | Status | Notes |
|---|---|---|---|---|
| Evaluation center | `modules/evaluation_center/service.py` | Eval cases/results, gate integration | Partially implemented | Needs broader production fixtures |
| Publishing / local export | `modules/publishing/`, `modules/chapter_production_bus/service.py` | Publish gate, release gate, release package, adapters, and v1 local export markdown/manifest/provenance/checklist handoff | Partially implemented | V1 local export is inspectable and operator-gated; platform auto-publish and final multi-chapter handoff proof remain deferred |
| Audit / audit log | `modules/audit/`, `modules/audit_log/` | Review/originality/audit assets and logs | Partially implemented | Publishing logic should keep moving out of audit |
| Platform strategy | `modules/platform_strategy/service.py` | Platform strategy pack and fit | Partially implemented | Real platform integration partial |
| Permission center | `modules/permission_center/service.py` | Tool/provider permission surface plus schema-backed ApprovalRequest create/list/resolve/expire/snapshot lifecycle | Partially implemented | High-risk source/context/publish/story mutation callers still need staged migration to ApprovalRequest refs |
| Metrics / analytics | `modules/metrics/`, `modules/clickhouse_analytics/` | Dashboards/analytics slices | Partially implemented | ClickHouse optional profile |
| Provider fallback | `modules/provider_fallback/service.py` | Environment policy and fallback governance | Partially implemented | Production/local fallback policy remains important |

## Skills

| Area | Path | Status | Rule |
|---|---|---|---|
| Project Skill source | `skills/` | Implemented | Source of truth |
| Claude runtime Skill copy | `.claude/skills/` | Implemented/generated plus external Skills | Do not edit as source |
| Sync script | `scripts/sync_claude_skills.py` | Implemented | Use `make sync-skills-dry-run`, `make sync-skills`, `make check-skills` |
| Skill docs | `docs/09-skills/` | Partially current | Use with current code evidence |
