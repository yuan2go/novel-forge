# Module Map

## Purpose

This map separates current executable modules from target platform layers. Do not confuse module presence with full platform capability.

A module is a service/capability area. A workflow node is an executable production step. An artifact is a schema-backed output. A run records execution.

## Current Modules

| Module | Package / Area | Data Directory | Current Status |
|---|---|---|---|
| Ingestion | `modules/ingestion` | `data/raw` | executable through CLI/API workflow |
| Cleaning | `modules/cleaning` | `data/cleaned` | executable through CLI/API workflow |
| Decomposition | `modules/decomposition` | `data/decompositions` | executable; primarily web-fiction-style abstraction |
| Analysis | analysis schemas/services/skills/UI | `data/analysis` | first schema/service/UI/handoff slice implemented; semantic scoring and richer gates remain |
| Knowledge | `modules/knowledge` | `data/knowledge` | executable/mock-backed extraction |
| Materials | `modules/materials` | `data/materials` | executable/mock-backed curation |
| Platforms | profiles/schemas | `data/platforms` | profile assets exist in project config flow |
| Genres | profiles/schemas | `data/genres` | profile assets exist in project config flow |
| Topics | `modules/topics` | `data/topics` | executable through CLI |
| Worldbuilding | `modules/worldbuilding` | `data/worlds` | executable through CLI |
| Characters | `modules/characters` | `data/characters` | executable through CLI |
| Continuity | continuity schemas/services | `data/continuity` | shallow schemas; workbench still P0 |
| Styles | style assets/reports | `data/styles` | partial |
| Quality Standards | standards/rules | `data/quality_standards` | partial |
| Templates | template assets/skills | `data/templates` | partial |
| Context Builder | `modules/context_builder` | `data/contexts` | context build plan and bundle are schema/API/UI backed |
| Outline | `modules/outline` + `modules/production_chain` | `data/outlines` | executable; outline versions recorded |
| Chapter Plan | `modules/chapter_plan` + `modules/production_chain` | `data/chapter_plans` | executable; chapter-plan versions recorded |
| Drafting | `modules/drafting` + `modules/production_chain` | `data/drafts` | executable; draft versions and generation runs recorded; editor patch workflow still P0 |
| Review | `modules/review` | `data/reviews` | executable; deeper audit reports still P0/P1 |
| Revision | `modules/revision` | `data/reviews` | executable; revision task/patch chain still P0 |
| Publishing | publishing schemas/services | `data/publishing` | publish gate/release package first version |
| Feedback | `modules/feedback` | `data/feedback` | CLI/back-end base; web productization still P0 |
| Training | `modules/training` | `data/training` | executable/schema-backed exercise generation |
| Image Prompts | schemas | `data/image_prompts` | schema ready |
| Workspace | `modules/workspace` | `data/workspaces` | executable project/workspace state |
| Runs | workflow/status services | `data/runs` | WorkflowRun, TaskStatus, handoff, dead letter base |
| Skills | `skills/` | docs-backed capability layer | repository source of truth; runtime copies generated |

## Platform Layer Mapping

| Platform Layer | Current Modules / Areas | Missing or Incomplete P0/P1 Work |
|---|---|---|
| Workflow | `workflows/pipeline.py`, status services, Celery tasks | formal `WorkflowDefinition`, `WorkflowNode`, `NodeRun`, invalidation, chapter queue |
| Knowledge | decomposition, analysis, knowledge, materials, templates | deepen Analysis Center semantic scoring and conversion gates |
| Context | search, vector search, Qdrant, `modules/context_builder` | manual source curation, compression controls, invalidation warnings |
| Production | topics, worlds, characters, outlines, chapter plans, drafts, `modules/production_chain` | chapter queue, parameter trace dashboard, invalidation warnings |
| Evaluation | review, originality, style, publish gate | continuity audit, platform fit, semantic originality evidence, prompt regression |
| Editor | draft workbench, diff/save | paragraph suggestions, `editor_patch`, apply/rollback workflow |
| Long-form Stability | continuity assets | timeline, foreshadowing workbench, relationship/faction/map/prop systems, change impact |
| Agent | handoff, permission/tool concepts | contracts, runs, checkpoints, budgets, gates, metrics, state machine, Agent Center UI |
| Feedback | feedback import/insight | web import, sentiment, payoff/toxic clusters, role heat, retention/drop-off, feedback loop |
| Publishing | publish gate, release package | publishing calendar, queue, platform status, publishing plan/log, post-release data |
| Model Evaluation | provider metadata/health | model profiles, benchmark tasks/runs, A/B, cost-quality, routing |

## Service Boundary

Current workflow step logic lives in `src/novel_forge/modules/<module>/service.py`.

`src/novel_forge/workflows/pipeline.py` remains the orchestration and compatibility layer. It initializes storage, preserves public workflow function names used by CLI/tests, runs the sample pipeline, and performs project validation.

Future platform migration should avoid putting all new logic into `pipeline.py`. Add domain services and keep `pipeline.py` thin.

## Rule

New P0 work must state whether it is:

- current module extension;
- new workflow node;
- new artifact schema;
- new UI workbench;
- new quality gate;
- new Agent contract;
- new analytics/reporting surface.
