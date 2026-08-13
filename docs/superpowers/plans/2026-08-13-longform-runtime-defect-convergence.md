# Long-form Runtime Defect Convergence Implementation Plan

> Execute task-by-task with red regressions before each semantic repair. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge the real-provider long-form failures on the current local branch and prove Chapter 1 cold start plus Chapter 2 stateful continuation on one exact qualified SHA.

**Architecture:** Keep PostgreSQL Authority, the Command Kernel ExternalEffect protocol, Narrative State v2 reducers, the existing Chapter 18-node Saga, and the frozen proof campaign as the only execution and evidence surfaces. Make retry identity operation-stable and bounded, normalize legacy obligation lifecycle only with explicit source semantics plus prior canonical state, and bind the frozen `zh-CN` requirement into Book/Planning/Chapter provider context and a deterministic proof-only language gate.

**Tech Stack:** Python 3.12, pytest, psycopg/PostgreSQL, MinIO, Docker Compose, Codex CLI real-provider runtime, Admin TypeScript/Next.js.

## Global Constraints

- Preserve fail-closed Authority and immutable failure evidence.
- Do not edit Ground Truth, lower quality thresholds, hand-edit Authority rows, or bypass Canon/Narrative/Book acceptance.
- Reuse current ExternalEffect, Context, Quality, Narrative State, Book/Chapter and runtime-proof surfaces.
- Only exact-SHA results count; fixture and local results do not establish real-provider proof.
- Required proof language is exactly `zh-CN`.
- Do not claim 30/100/300 chapter, long-form, multi-book, or production proof.

---

### Task 1: Freeze the current evidence baseline

**Files:**
- Inspect: `.local/proof-campaigns/longform-narrative-v1-1e28823-persistent/campaign-checkpoint.json`
- Inspect: `.local/proof-campaigns/longform-narrative-v1-f619529-persistent/evidence/process-failures.json`
- Inspect: `src/novel_forge/storage/migrations/versions/v20260813_0087_book_initial_narrative_state_binding.py`

**Interfaces:**
- Consumes: current Git state, migration registry and append-only campaign artifacts.
- Produces: start SHA, branch, worktree status, migration head and exact latest failure classification.

- [ ] **Step 1: Capture branch, SHA and worktree state**

```bash
git status --short --branch
git rev-parse HEAD
git log -8 --oneline --decorate
```

- [ ] **Step 2: Capture migration and Campaign evidence**

```bash
jq '{release,runtime:.runtime.migration,status,accepted_through_chapter,requested_target_chapter,failures}' .local/proof-campaigns/longform-narrative-v1-1e28823-persistent/campaign-checkpoint.json
jq . .local/proof-campaigns/longform-narrative-v1-f619529-persistent/evidence/process-failures.json
```

### Task 2: Make Planning retry one bounded operation-stable effect

**Files:**
- Modify: `src/novel_forge/modules/story_planning_runtime/application.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/execution.py`
- Modify: `src/novel_forge/modules/command_kernel/external_effect_runtime.py`
- Test: `tests/unit/test_story_planning_runtime.py`
- Test: `tests/integration/test_core_functional_loops_postgres.py`

**Interfaces:**
- Consumes: `story_planning.generate` operation retry policy, `plan_external_effect()`, verified receipts and attempt-fenced candidate commit.
- Produces: one operation-stable effect, one dispatch per operation attempt, a shared bounded retry budget and receipt-backed recovery without another Provider call.

- [ ] **Step 1: Add failing retry-policy and identity assertions**

```python
assert PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS == definition["retry_policy"]["max_attempts"]
assert external_effect_count == 1
assert candidate_count == 1
```

- [ ] **Step 2: Confirm the tests are red**

```bash
.venv/bin/python -m pytest tests/unit/test_story_planning_runtime.py -k provider_effect -q
.venv/bin/python -m pytest tests/integration/test_core_functional_loops_postgres.py -k planning_retry -q
```

- [ ] **Step 3: Share the bounded count and remove Attempt identity from effect identity**

```python
STORY_PLANNING_MAX_ATTEMPTS = 3
stable_key = f"{operation_id}:{definition.capability}:planning-pep-v2"
budget_key = f"budget:{stable_key}:attempt:{attempt_id}"
```

The effect request hash contains stable business inputs; Attempt/Fence/materialization identity remains in the PEP `ExecutionRequest`.

- [ ] **Step 4: Consume an already verified successful receipt**

```python
completion = read_succeeded_external_effect(database_url, context, effect_id=effect_id)
provider_evidence = (
    completion["provider_evidence"]
    if completion is not None
    else dispatch_external_effect(
        self.database_url,
        self.context,
        effect_id=self.effect_id,
        worker_id=self.worker_id,
        lease_seconds=self.lease_seconds,
        adapter=self.adapter,
    )["provider_evidence"]
)
```

The read requires `effect.status='SUCCEEDED'`, a verified receipt, the latest succeeded dispatch, matching Project/Operation scope and non-empty Provider evidence.

- [ ] **Step 5: Verify timeout→success, exhaustion, stale fencing and post-success recovery**

```bash
.venv/bin/python -m pytest tests/integration/test_external_effect_runtime_postgres.py tests/integration/test_core_functional_loops_postgres.py -k 'timeout or retry or stale or planning' -q
```

### Task 3: Preserve canonical obligation lifecycle under legacy ACTIVE

**Files:**
- Modify: `src/novel_forge/modules/narrative_state/contracts.py`
- Modify: `src/novel_forge/modules/narrative_state/reducers.py`
- Test: `tests/unit/test_narrative_state_semantics_v2.py`
- Test: `tests/integration/test_narrative_state_v2_postgres.py`

**Interfaces:**
- Consumes: legacy Promise/Thread/Foreshadow/Mystery changes, transition markers, prior canonical state and supersession identity.
- Produces: context-aware lifecycle with no implicit advancement, regression or terminal reopening.

- [ ] **Step 1: Add the failing lifecycle matrix**

```python
@pytest.mark.parametrize("field", ["reader_promise", "plot_thread", "foreshadow_state", "mystery_state"])
def test_new_legacy_active_obligation_opens(field):
    state = rebuild_story_state([_legacy_active_outcome(field, chapter=1)])
    assert _only_obligation(state)["state"]["status"] == "OPEN"

def test_existing_developing_legacy_active_does_not_regress():
    state = rebuild_story_state([
        _obligation_outcome(chapter=1, status="OPEN"),
        _obligation_outcome(chapter=2, status="DEVELOPED"),
        _legacy_active_outcome("plot_thread", chapter=3),
    ])
    assert _only_obligation(state)["state"]["status"] == "DEVELOPING"

def test_explicit_development_signal_advances_open_to_developing():
    state = rebuild_story_state([
        _obligation_outcome(chapter=1, status="OPEN"),
        _obligation_outcome(chapter=2, status="DEVELOPED"),
    ])
    assert _only_obligation(state)["state"]["status"] == "DEVELOPING"
```

Add exact companion cases named
`test_terminal_legacy_active_obligation_does_not_reopen` and
`test_linked_obligation_identity_and_supersession_remain_independent`; the former
must preserve the accepted terminal state, and the latter must assert
four distinct obligation entity keys, each prefixed by `obligation_id=`, plus the exact current
`supersedes_event_id`.

- [ ] **Step 2: Confirm unconditional mapping is red**

```bash
.venv/bin/python -m pytest tests/unit/test_narrative_state_semantics_v2.py -k 'active or obligation or supersession' -q
```

- [ ] **Step 3: Apply prior-state-aware legacy normalization**

```python
if legacy_source_status == "ACTIVE" and old:
    payload["status"] = old["status"]
if explicit_progress_signal:
    payload["status"] = "DEVELOPING"
```

Only explicit development source vocabulary advances lifecycle. Terminal and supersession checks remain fail-closed.

- [ ] **Step 4: Run unit and PostgreSQL Narrative regressions**

```bash
.venv/bin/python -m pytest tests/unit/test_narrative_state_semantics_v2.py tests/integration/test_narrative_state_v2_postgres.py -q
```

### Task 4: Bind and gate the frozen zh-CN contract

**Files:**
- Modify: `scripts/run_short_longform_runtime_proof.py`
- Modify: `scripts/run_longform_narrative_campaign.py`
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Modify: existing evaluator under `src/novel_forge/modules/runtime_proof/`
- Test: `tests/unit/test_longform_narrative_campaign_runner.py`
- Test: `tests/unit/test_chapter_provider_output_contracts.py`
- Test: `tests/unit/test_longform_narrative_campaign.py`

**Interfaces:**
- Consumes: frozen `book.language`, BookDesign/production profile, Chapter Context, final revision text and Proof evaluation.
- Produces: provider-visible `zh-CN` instruction and deterministic proof-only language eligibility distinct from Book Authority acceptance.

- [ ] **Step 1: Add failing binding and gate assertions**

```python
assert production_profile["language_contract"]["required_language"] == "zh-CN"
assert context_bundle_language == "zh-CN"
assert "Simplified Chinese" in rendered_prompt
assert evaluate_proof_language("English prose", required="zh-CN")["status"] == "FAILED"
assert evaluate_proof_language("雨落在档案馆的窗上。", required="zh-CN")["status"] == "PASSED"
```

- [ ] **Step 2: Bind language through existing governed inputs**

```python
language_contract = {
    "required_language": "zh-CN",
    "reader_facing_prose": "REQUIRED",
    "proof_gate": "PRIMARILY_REQUIRED_LANGUAGE",
}
```

Persist it through the strict Book production profile, Planning inputs and selected Context; add stage semantics for draft, revision and reader-facing quality stages. The existing strict BookDesign schema remains unchanged.

- [ ] **Step 3: Add deterministic Proof language evaluation**

```python
evaluation = evaluate_proof_language(text, required_language=required_language)
if evaluation["status"] != "PASSED":
    raise ProofValidationError("PROOF_LANGUAGE_CONTRACT_FAILED", evaluation)
```

Record Authority acceptance and Proof language status separately. English accepted prose remains evidence but never counts as Proof-valid.

- [ ] **Step 4: Run language regressions**

```bash
.venv/bin/python -m pytest tests/unit/test_longform_narrative_campaign.py tests/unit/test_longform_narrative_campaign_runner.py tests/unit/test_chapter_provider_output_contracts.py -q
```

### Task 5: Run the finite Provider-to-canonical semantic audit

**Files:**
- Inspect/modify only for a red-capable defect: `src/novel_forge/modules/story_planning_runtime/`
- Inspect/modify only for a red-capable defect: `src/novel_forge/modules/chapter_authority/provider_output_contracts.py`
- Inspect/modify only for a red-capable defect: `src/novel_forge/modules/narrative_state/contracts.py`
- Inspect/modify only for a red-capable defect: `src/novel_forge/modules/narrative_state/reducers.py`
- Test: focused files from Tasks 2–4.

**Interfaces:**
- Consumes: captured Provider JSON for Canon transitions, supersession, obligation identity/status and character-knowledge preconditions.
- Produces: an evidence matrix for vocabulary, identity, transition and schema-valid/domain-invalid combinations.

- [ ] **Step 1: Replay captured combinations**

```bash
.venv/bin/python -m pytest tests/unit/test_chapter_provider_output_contracts.py tests/unit/test_narrative_state_semantics_v2.py -q
```

- [ ] **Step 2: Search ambiguity surfaces**

```bash
rg -n 'ACTIVE|DEVELOPING|NEW|UPDATE|RESOLVED|supersedes_event_id|identity_fields' src/novel_forge/modules/story_planning_runtime src/novel_forge/modules/chapter_authority src/novel_forge/modules/narrative_state
```

- [ ] **Step 3: Fix only a reproduced domain-invalid combination**

Every change adds a regression using the real field combination and preserves schema, Authority and reducer gates.

### Task 6: Prove the combined production composition locally

**Files:**
- Test: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`
- Test: `tests/integration/test_chapter_authority_scheduler_postgres.py`
- Test: `tests/integration/test_core_functional_loops_postgres.py`
- Test: `tests/unit/test_short_longform_runtime_proof.py`

**Interfaces:**
- Consumes: Planning, Chapter Saga, Canon, Narrative State, Book acceptance and next-chapter input resolution.
- Produces: Chapter 1→2 composition evidence with one accepted row per logical chapter and no duplicate effects/state commits.

- [ ] **Step 1: Add or extend one cross-module Chapter 1→2 regression**

```python
assert accepted_chapters == [1, 2]
assert duplicate_logical_chapters == 0
assert next_plan_context["accepted_through_chapter"] == 1
assert canon_acceptance_count == 2
assert story_state_acceptance_count == 2
```

- [ ] **Step 2: Run focused composition tests**

```bash
.venv/bin/python -m pytest tests/integration/test_core_functional_loops_postgres.py tests/integration/test_chapter_authority_scheduler_postgres.py tests/integration/test_book_to_chapter_authority_vertical_postgres.py -q
```

### Task 7: Qualify one final exact SHA

**Files:**
- Record under: `.local/proof-campaigns/qualification-<sha>/logs/`

**Interfaces:**
- Consumes: clean candidate commit and current migration head.
- Produces: exact-SHA PASS/FAIL/SKIP matrix for every repository gate.

- [ ] **Step 1: Commit and record SHA**

```bash
git diff --check
git status --short
git commit -m "fix(longform): converge runtime proof semantics"
git rev-parse HEAD
```

- [ ] **Step 2: Run project qualification targets**

```bash
make test
make validate
make authority-test
make authority-postgres-test
make check-skills
make authority-query-plan-release
make authority-smoke
```

Also run the actual Admin test/build targets listed by the repository and record environment, migration head, command, exit status and log path.

### Task 8: Re-prove real Provider Chapter 1 and Chapter 2

**Files:**
- Produce: `.local/proof-campaigns/longform-narrative-v1-<sha>-persistent/`

**Interfaces:**
- Consumes: clean qualified exact SHA, fresh PostgreSQL database and project-scoped proof buckets.
- Produces: immutable Chapter 1 cold-start and Chapter 2 stateful-continuation evidence under one Book/Authority lineage.

- [ ] **Step 1: Run a fresh Chapter 1 Campaign**

```bash
.venv/bin/python scripts/run_longform_narrative_campaign.py --database-url "$DATABASE_URL" --output-root "$PROOF_ROOT" --target-chapter 1
```

- [ ] **Step 2: Verify Authority, Provider and zh-CN Proof evidence**

```bash
jq '{release,status,accepted_through_chapter,proof_verdict,chapter_exports,measurements}' "$PROOF_ROOT/campaign-checkpoint.json"
```

- [ ] **Step 3: Resume the same lineage through Chapter 2**

Add bounded validation targets 2 and 5 without changing frozen Book target or Ground Truth. Resume the same output root/database through Chapter 2; continue through Chapter 5 only after Chapter 2 passes.

- [ ] **Step 4: Preserve and classify every new failure**

Append evidence, reproduce deterministically, apply a minimal fix, create a new exact SHA, rerun qualification, and restart proof on that SHA.

### Task 9: Final integrity report

**Files:**
- Inspect: Git status, final qualification logs and final Campaign evidence.

**Interfaces:**
- Consumes: final exact-SHA engineering and real-runtime evidence.
- Produces: Baseline, defect chain, semantic audit, qualification, real-provider gates, blockers and strict verdict.

- [ ] **Step 1: Confirm clean state**

```bash
git status --short --branch
git diff --check
```

- [ ] **Step 2: Report strict labels**

```text
CHAPTER_1_COLD_START = PASSED | FAILED | BLOCKED
CHAPTER_2_STATEFUL_CONTINUATION = PASSED | FAILED | BLOCKED
CHAPTER_1_TO_5_SEQUENTIAL_STABILITY = PASSED | NOT_REACHED | FAILED | BLOCKED
PRODUCTION_COMPOSITION_QUALIFIED = true | false
```

Never emit the forbidden 30/100/300, long-form, multi-book, or production proof claims.
