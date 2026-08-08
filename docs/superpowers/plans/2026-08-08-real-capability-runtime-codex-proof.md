# Real Capability Runtime and Codex Production Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing PostgreSQL Chapter Authority materialize an immutable Capability Pack into a real Codex CLI request and prove one complete canonical Chapter run with durable capability, provider, usage, cost, trace, quality, and recovery evidence.

**Architecture:** Extend the current Capability Pack resolver and Chapter execution binder so the Attempt snapshot and exact content identities are frozen before ExternalEffect planning. Feed the materialized content through the existing ProductionExecutionGateway and CodexCliExecutionBackend, validate the stage result before success, and derive proof flags only from PostgreSQL Authority evidence.

**Tech Stack:** Python 3.11+, PostgreSQL Authority, MinIO, pytest, Codex CLI JSONL, JSON Schema subset validation, existing Command Kernel and ProductionExecutionGateway.

## Global Constraints

- PostgreSQL Authority and the Chapter Production Kernel remain the only production authority.
- No ProviderAdapterV2 wrapper, parallel execution runtime, Capability Orchestrator, Model Strategy System, or silent fallback.
- Controlled environments fail closed on missing content, drift, invalid context or Knowledge, unauthorized tools, invalid output, budget failure, or snapshot inconsistency.
- Fixture/process-double tests prove mechanics only and never set real-provider proof flags.
- Codex usage is `MEASURED`; CLI cost is `ESTIMATED` from a frozen pricing snapshot and is never described as provider-billed cost.
- `.idea/modules.xml` must not be modified, staged, overwritten, stashed, or committed.
- No migration unless a failing database invariant proves the existing JSONB and Authority AssetVersion stores insufficient.

---

### Task 1: Stage Output Contracts and Exact Pack Content Resolution

**Files:**
- Create: `src/novel_forge/modules/chapter_authority/provider_output_contracts.py`
- Modify: `src/novel_forge/modules/capability_pack_authority/domain.py`
- Modify: `src/novel_forge/modules/capability_pack_authority/runtime.py`
- Modify: `src/novel_forge/storage/capability_pack_authority_repositories.py`
- Test: `tests/unit/test_chapter_provider_output_contracts.py`
- Test: `tests/unit/test_capability_pack_runtime_resolver.py`
- Test: `tests/integration/test_capability_pack_runtime_snapshot_postgres.py`

**Interfaces:**
- Produces: `chapter_provider_output_schema(stage: str) -> dict[str, Any]`.
- Produces: `validate_chapter_provider_output_schema(stage: str, value: Mapping[str, Any]) -> dict[str, Any]` with `CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID` failures.
- Produces: `CapabilityPackRuntimeResolver.materialize_attempt_artifacts(snapshot: CapabilityPackAttemptSnapshot) -> CapabilityPackArtifactMaterialization`.
- `CapabilityPackArtifactMaterialization` contains exact system instruction, template, Skill and required Knowledge contents plus ref/version/hash/source identity and one canonical `materialization_hash`.

- [ ] **Step 1: Write failing output-contract tests**

Cover all model stages, exact required keys, additional-property rejection, numeric/string/array constraints, and distinct schema errors before semantic normalization.

- [ ] **Step 2: Run the focused tests and observe failure**

Run: `python -m pytest -q tests/unit/test_chapter_provider_output_contracts.py`

Expected: collection/import failure because the contract module does not exist.

- [ ] **Step 3: Implement the small stage schema catalog and validator**

Use Draft 2020-12-compatible schemas accepted by `codex exec --output-schema`. Implement only the schema keywords used by these contracts: `type`, `required`, `properties`, `additionalProperties`, `items`, `minItems`, `minLength`, `minimum`, `maximum`, `enum`, `const`, `anyOf`, and nullable unions. Return a canonical copy without changing domain semantics.

- [ ] **Step 4: Write failing exact-artifact resolution tests**

Exercise exact ref/version/kind lookup from the registered PostgreSQL artifact catalog, system/template/Skill content recovery, required Knowledge recovery, missing content, wrong kind, version mismatch, and hash drift.

- [ ] **Step 5: Implement immutable artifact materialization**

Load the Pack version selected by the frozen snapshot with `require_version`, verify the catalog and snapshot identity, resolve exact entries, and return content only after recomputing every content hash. Preserve all content in the registered Authority catalog; never read live repository paths during runtime.

- [ ] **Step 6: Run Task 1 tests**

Run: `python -m pytest -q tests/unit/test_chapter_provider_output_contracts.py tests/unit/test_capability_pack_runtime_resolver.py tests/integration/test_capability_pack_runtime_snapshot_postgres.py`

Expected: PASS when PostgreSQL is available; PostgreSQL tests may be explicitly skipped only when the service is unavailable.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/novel_forge/modules/chapter_authority/provider_output_contracts.py src/novel_forge/modules/capability_pack_authority/domain.py src/novel_forge/modules/capability_pack_authority/runtime.py src/novel_forge/storage/capability_pack_authority_repositories.py tests/unit/test_chapter_provider_output_contracts.py tests/unit/test_capability_pack_runtime_resolver.py tests/integration/test_capability_pack_runtime_snapshot_postgres.py
git diff --cached --check
git commit -m "feat: resolve exact capability runtime content"
```

### Task 2: Freeze Capability Materialization Before ExternalEffect

**Files:**
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Modify: `src/novel_forge/modules/chapter_authority/model_effects.py`
- Modify: `src/novel_forge/modules/agent_runtime/chapter_binding.py`
- Test: `tests/unit/test_capability_pack_runtime_binding.py`
- Test: `tests/unit/test_production_execution_gateway.py`
- Test: `tests/architecture/test_capability_pack_authority_boundaries.py`
- Test: `tests/integration/test_agent_runtime_crash_recovery_postgres.py`

**Interfaces:**
- Produces: `PostgresChapterExecutionContractBinder.freeze_before_external_effect(request, stage, inputs) -> ChapterCapabilityPreflight`.
- `ChapterCapabilityPreflight.to_effect_binding()` supplies snapshot ID/hash, materialization manifest ref/hash, capability/Prompt/Skill/Context/Knowledge/Tool/output-schema bindings.
- `PostgresChapterExecutionContractBinder.bind` requires the ExternalEffect's frozen preflight identity and never resolves the active deployment again.

- [ ] **Step 1: Add failing ordering and replay tests**

Assert the Attempt Pack Snapshot and materialization manifest exist before `plan_external_effect`, the ExternalEffect request contains their hashes, activation changes do not affect replay, and a mismatched snapshot or manifest fails before dispatch.

- [ ] **Step 2: Run the focused tests and observe failure**

Run: `python -m pytest -q tests/unit/test_capability_pack_runtime_binding.py tests/architecture/test_capability_pack_authority_boundaries.py`

Expected: FAIL because the current call order plans ExternalEffect first.

- [ ] **Step 3: Implement pre-effect freeze in the existing binder**

Resolve/freeze the current Attempt snapshot, materialize exact Pack content, select eligible input artifacts under the frozen context policy, require at least one eligible `knowledge_pack`, resolve the stage tool permission, bind the stage output schema and persist a `capability_materialization_manifest` Authority AssetVersion.

- [ ] **Step 4: Put the preflight binding into ExternalEffect**

Call preflight before `plan_external_effect`; include its canonical identity in `effect_request_payload`. On replay, compare the persisted effect binding with the current Attempt snapshot and reject drift. Keep budget reservation and ExecutionRequest creation after the effect ID exists.

- [ ] **Step 5: Make Agent Binding consume the same snapshot**

Require Agent Runtime Binding to reference the exact preflight snapshot and materialization hash. Replace empty Knowledge evidence with the frozen Knowledge selections; record Context and Skill selections without claiming model use until provider completion.

- [ ] **Step 6: Run Task 2 tests including crash recovery**

Run: `python -m pytest -q tests/unit/test_capability_pack_runtime_binding.py tests/unit/test_production_execution_gateway.py tests/architecture/test_capability_pack_authority_boundaries.py tests/integration/test_agent_runtime_crash_recovery_postgres.py`

Expected: PASS with PostgreSQL; recovery evidence shows identical snapshot/materialization hashes.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/novel_forge/modules/chapter_authority/execution_gateway.py src/novel_forge/modules/chapter_authority/model_effects.py src/novel_forge/modules/agent_runtime/chapter_binding.py tests/unit/test_capability_pack_runtime_binding.py tests/unit/test_production_execution_gateway.py tests/architecture/test_capability_pack_authority_boundaries.py tests/integration/test_agent_runtime_crash_recovery_postgres.py
git diff --cached --check
git commit -m "feat: freeze capabilities before external effects"
```

### Task 3: Materialize the Real Codex Request and Validate Before Success

**Files:**
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Modify: `src/novel_forge/modules/production_execution/backends.py`
- Modify: `src/novel_forge/modules/production_execution/process_supervisor.py`
- Test: `tests/unit/test_production_execution_gateway.py`
- Test: `tests/unit/test_execution_backend_conformance.py`
- Test: `tests/unit/test_chapter_capability_materialization.py`

**Interfaces:**
- `PostgresChapterExecutionPayloadResolver.resolve` returns a prompt containing exact system, template, Skill, Context and Knowledge content plus frozen tool/output constraints.
- `ResolvedExecutionPayload` carries the exact output schema and capability usage manifest.
- `CodexCliExecutionBackend` writes the schema into the persistent execution directory, constructs the trusted command, parses JSONL usage/tool events, validates schema and stage semantics, and only then creates a successful `ExecutionResult`.

- [ ] **Step 1: Write failing materialized-prompt tests**

Assert exact registered text occurs in stdin, context and Knowledge contents occur once, hashes and selection identities match, raw-source content is rejected, template variables are resolved, and output schema is the same schema written for Codex.

- [ ] **Step 2: Write failing Codex backend tests**

Use process doubles for successful JSONL, timeout, non-zero exit, bad final JSON, schema-invalid output, semantic-invalid output, unauthorized tool event, measured usage, estimated cost and persistent recovery. Mark all such tests fixture/mechanics only.

- [ ] **Step 3: Implement prompt materialization**

Read the frozen materialization manifest and exact Authority input artifacts, render the registered template, append the registered Skill and Knowledge under explicit source-isolated sections, add the stage request and schema, and calculate one request materialization hash.

- [ ] **Step 4: Implement Codex command and output lifecycle**

Use the configured absolute Codex executable with `exec --sandbox read-only --skip-git-repo-check --json --output-schema <path> --output-last-message <path> --color never --ignore-user-config --ignore-rules --ephemeral --cd <fixed-empty-workspace> -`. Create the output-schema file through the persistent execution directory and enforce the existing command allowlist.

- [ ] **Step 5: Implement measured usage, estimated cost and tool-event parsing**

Read terminal `turn.completed.usage`, retain input/cached/output/reasoning categories, calculate cost from an immutable per-million-token pricing snapshot, label it `ESTIMATED`, and reject any Codex tool event not allowed by the frozen policy. Record `model.provider.invoke` as the governed invocation.

- [ ] **Step 6: Validate before producing success evidence**

Map failures to `PROCESS_TIMEOUT`, `PROCESS_EXIT_FAILURE`, `INVALID_JSON`, `OUTPUT_SCHEMA_FAILURE`, `OUTPUT_SEMANTIC_FAILURE`, or `UNAUTHORIZED_TOOL_INVOCATION`. Do not store a successful result/validation receipt until both schema and `normalize_model_output` pass.

- [ ] **Step 7: Run Task 3 tests**

Run: `python -m pytest -q tests/unit/test_chapter_capability_materialization.py tests/unit/test_production_execution_gateway.py tests/unit/test_execution_backend_conformance.py`

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/novel_forge/modules/chapter_authority/execution_gateway.py src/novel_forge/modules/production_execution/backends.py src/novel_forge/modules/production_execution/process_supervisor.py tests/unit/test_chapter_capability_materialization.py tests/unit/test_production_execution_gateway.py tests/unit/test_execution_backend_conformance.py
git diff --cached --check
git commit -m "feat: execute materialized capabilities with Codex"
```

### Task 4: Wire Codex into Controlled Chapter Composition and Durable Ledgers

**Files:**
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/modules/chapter_authority/model_effects.py`
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Test: `tests/unit/test_chapter_authority_dependencies.py`
- Test: `tests/unit/test_provider_hard_stop_proof.py`
- Test: `tests/architecture/test_production_execution_plane_boundaries.py`

**Interfaces:**
- Explicit provider ID `codex-cli` creates a `LOCAL_CLI_REMOTE_INFERENCE` ModelProfile and registers the existing Codex backend directly.
- Controlled composition requires absolute executable, fixed execution root/workspace, model, pricing reference/rates, budget caps, Pack, MinIO and release identity.
- `model_call_log` and `cost_ledger` include measured/estimated status and capability usage evidence.

- [ ] **Step 1: Add failing composition tests**

Assert controlled `codex-cli` composition creates no ProviderAdapterV2, registers the Codex backend, refuses missing executable/pricing/Pack/object-store inputs, and never falls back to scripted provider.

- [ ] **Step 2: Implement explicit Codex route composition**

Branch only the existing Chapter provider construction for `codex-cli`; retain current remote ProviderAdapterV2 and scripted paths unchanged. Configure one fixed runtime workspace and persistent process root outside Authority object storage.

- [ ] **Step 3: Extend model and cost evidence**

Persist capability manifest refs/hash, Prompt/Skill/Context/Knowledge selections, allowed/denied/invoked tools, measured usage categories, pricing snapshot, calculation basis and estimated flag in model-call and cost-ledger Authority assets.

- [ ] **Step 4: Run Task 4 tests**

Run: `python -m pytest -q tests/unit/test_chapter_authority_dependencies.py tests/unit/test_provider_hard_stop_proof.py tests/architecture/test_production_execution_plane_boundaries.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/novel_forge/api/authority_dependencies.py src/novel_forge/modules/chapter_authority/model_effects.py src/novel_forge/modules/chapter_authority/execution_gateway.py tests/unit/test_chapter_authority_dependencies.py tests/unit/test_provider_hard_stop_proof.py tests/architecture/test_production_execution_plane_boundaries.py
git diff --cached --check
git commit -m "feat: compose governed Codex chapter execution"
```

### Task 5: Real PostgreSQL Codex Chapter and Recovery Proof

**Files:**
- Create: `scripts/run_real_capability_codex_proof.py`
- Create: `tests/integration/test_real_capability_codex_proof_postgres.py`
- Modify: `compose.yml` only if existing PostgreSQL/MinIO configuration cannot support provider-validation.
- Create: `docs/reports/real-capability-runtime-codex-proof.json`
- Create: `docs/reports/real-capability-runtime-codex-proof.md`

**Interfaces:**
- Proof CLI accepts database/object-store/Codex paths and pricing values from environment; it never accepts proof booleans.
- Proof output contains exact Git SHA, project/workspace/book/root operation IDs, Attempt/Effect/Execution/Agent bindings, capability hashes, provider receipts, trace counts, model calls, token/cost totals, canon/quality/release results, recovery evidence, and derived proof flags.

- [ ] **Step 1: Write the gated integration assertion**

The test invokes the proof only when `NOVEL_FORGE_RUN_REAL_CODEX_PROOF=1`, otherwise reports an explicit skip. When enabled it requires all derived flags and checks evidence is non-fixture and bound to current HEAD.

- [ ] **Step 2: Implement Authority-only proof setup**

Use Project Authority, Capability Pack Authority, Agent Runtime Authority and MKAOS Authority commands to create the project/book, register/compile/approve/deploy/activate the current Pack, activate Agent definitions, create a source-isolated Knowledge Pack, and admit a `SingleChapterRequest`. Do not import test harnesses or insert provider results directly.

- [ ] **Step 3: Run the full Chapter scheduler**

Execute the normal scheduler until the root Saga reaches a terminal state, covering plan, context, draft, review, revision, re-review, canon extraction/proposal/commit, quality groups/aggregate, publish, export and final release gate.

- [ ] **Step 4: Exercise one safe recovery path**

Inject one process failure or semantic-invalid first Attempt before a real Codex retry. Confirm the successor Attempt retains the same Pack/materialization hashes, the stale fence cannot commit, and there is exactly one canonical output per stage.

- [ ] **Step 5: Derive and persist proof report**

Set each proof flag from direct PostgreSQL queries and persistent process receipts. Preserve false with an exact blocking reason on any failure. Include measured token totals and explicitly estimated cost.

- [ ] **Step 6: Run the real proof**

Run with PostgreSQL/MinIO and the authenticated application Codex binary:

```bash
NOVEL_FORGE_RUN_REAL_CODEX_PROOF=1 python -m pytest -q tests/integration/test_real_capability_codex_proof_postgres.py -s
```

Expected: one real Chapter run; if environmental/provider failure prevents completion, the generated report retains false flags and exact evidence.

- [ ] **Step 7: Commit Task 5**

```bash
git add scripts/run_real_capability_codex_proof.py tests/integration/test_real_capability_codex_proof_postgres.py compose.yml docs/reports/real-capability-runtime-codex-proof.json docs/reports/real-capability-runtime-codex-proof.md
git diff --cached --check
git commit -m "test: prove canonical Codex chapter production"
```

### Task 6: Regression, Code Review, and Exact-HEAD Qualification

**Files:**
- Modify only files required by failures found during this task.

**Interfaces:**
- Produces final exact-HEAD evidence and an evidence-level-aware completion report.

- [ ] **Step 1: Run focused capability/provider/authority suites**

```bash
python -m pytest -q tests/architecture/test_capability_pack_authority_boundaries.py tests/architecture/test_production_execution_plane_boundaries.py tests/unit/test_capability_pack_runtime_binding.py tests/unit/test_capability_pack_runtime_resolver.py tests/unit/test_chapter_authority_dependencies.py tests/unit/test_production_execution_gateway.py tests/unit/test_execution_backend_conformance.py tests/unit/test_provider_hard_stop_proof.py
```

- [ ] **Step 2: Run PostgreSQL authority integration suites**

```bash
python -m pytest -q tests/integration/test_capability_pack_runtime_snapshot_postgres.py tests/integration/test_agent_runtime_crash_recovery_postgres.py tests/integration/test_real_capability_codex_proof_postgres.py
```

- [ ] **Step 3: Run repository checks**

```bash
python -m compileall -q src scripts
python -m ruff check src tests scripts
python -m pytest -q
```

- [ ] **Step 4: Review all changes against the design and AGENTS.md**

Check no bypass, silent fallback, fixture promotion, unbound Capability content, false cost claim, duplicate canonical commit, unrelated refactor, or `.idea/modules.xml` change exists.

- [ ] **Step 5: Bind final evidence to the exact tested HEAD**

Record `git rev-parse HEAD`, worktree state, migration state, database project/root operation IDs, proof report hash, Codex version and provider receipt identities. If code changes after the real run, rerun the qualification proof before claiming success.

- [ ] **Step 6: Commit qualification-only corrections if required**

```bash
git diff --check
git status --short
```

Do not create an empty commit. The final report distinguishes code/test/fixture/real-provider evidence and retains all non-claims.
