# Bounded Quality Qualification

Status: `CURRENT` operational contract. This guide describes the exact 4+4
campaign implemented by `quality_qualification_v1.json`. It does not claim that
any current SHA has passed real-provider or human qualification. Only an
immutable exact-SHA report under `docs/qualification/` may make that claim.

## Claim boundary

This procedure asks one bounded question: does the Canonical Runtime's normal
Narrative Control path produce better accepted Chapters than the comparable
first draft from the same governed Chapter attempt?

The campaign is exactly:

```text
one dedicated Project / Book
one bounded Volume slice
one primary Arc evaluation
ChapterGroup 1: Chapters 1-4
ChapterGroup 2: Chapters 5-8
eight accepted Chapters total
two independent human reviewer targets
eight Chapter pairs plus one Arc pair per reviewer
```

Chapter 9 and background continuation are forbidden. Do not reinterpret this
as a 30/100/300-Chapter, million-word, real-reader, commercial, production, or
statistical-calibration proof.

## Evidence that must remain separate

| Layer | Meaning | Cannot be replaced by |
|---|---|---|
| L1 Hard Narrative Correctness | Canon, identity, time, world-rule, knowledge, causality, Realization, transition, obligation and accepted-history legality | prose, Judge or preference scores |
| L2 Editorial/Literary Quality | clarity, scene function, agency, dialogue, emotion, escalation, pacing, hook, information release, payoff, originality and economy | L1 correctness or Reader Proxy alone |
| L3 Reader/Longitudinal Outcome | momentum, promise/payoff, repetition/fatigue, Arc movement and Reader Outcome v3 trends | one Chapter score or real-reader claims |

The final status is one of `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL` or
`NOT_PROVEN`. A severe L1 failure takes precedence over all scores. Missing,
contaminated or incomplete evidence is not averaged as zero; it fails closed.

## Baseline protocol

For each Chapter, Candidate Baseline is the immutable first draft and Candidate
Canonical is the accepted revision from the same Chapter attempt. They share:

- the exact Story Foundation and accepted boundary;
- Chapter goal, ChapterPlan, Narrative Realization and Context;
- Provider/model route and comparable token policy.

The controlled difference is the Canonical review, revision, re-review,
Quality and acceptance path. This is a useful ablation of Narrative Control,
not an intentionally weak prompt-only strawman. The private mapping is retained
by Reader Calibration Authority and is never included in reviewer exports.

## Preflight and sequencing

Do not spend Provider budget until all engineering gates are green at the
candidate SHA:

1. unit, schema/contract, architecture and full Authority regression;
2. PostgreSQL integration, fresh migration and upgrade migration;
3. composition root, Chapter Runtime, Planning, Formation, Realization, Context,
   Canon/Narrative State, Reader/Recap/Replan and recovery qualification;
4. scripted 4+4 campaign and injected recovery replay;
5. clean named branch and clean worktree.

Record before preparation:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
PYTHONPATH=src python - <<'PY'
from novel_forge.storage.migrations import LATEST_MIGRATION_ID
print(LATEST_MIGRATION_ID)
PY
```

The real campaign must use a dedicated Project and one BookRun. The Provider
artifact queries every model call in that Project, so exploratory or unrelated
calls contaminate lineage and consume the same call/token/cost budget.
Every external effect whose `effect_type` is `model.invoke` is counted,
regardless of whether its capability is named `planning.*`, `chapter.*`,
`quality_*` or `model.*`.

## Canonical Authority preparation

Prepare the Book through current Authority applications or their public API;
never import `tests/`, call fixture seed helpers, insert Authority rows directly,
or relabel scripted evidence. The required chain is:

```text
Project Authority
→ Book Authority root
→ six qualified and active Story Design Foundation layers
→ durable Story Formation READY
→ BookDesign v5 semantic evaluation, approval and activation
→ exact-SHA Planning/Chapter/Reader/Narrative-Evaluation Pack activation
→ durable Book Opening
→ BookPlan + VolumePlan + ArcPlan activation
→ resolved Book production input snapshot
→ unstarted target=8 BookRun with recap cadence 4/8
```

The six Formation inputs are Creative Foundation, Theme Contract, Ending
Intent, Reader Promise, World Bible and Character Cast. Each must retain its
generation/import operation, candidate hash, independent qualification
AssetVersion/hash, Story Design activation operation and exact parent bindings.
Curated or operator-authored Foundation input is allowed only when honestly
classified and governed; it is frozen input, not provider quality evidence.
Because BookDesign v5 is reference-only, its independent semantic evaluator
resolves the six exact Foundation AssetVersions and qualification bindings from
the candidate itself. It validates those Authority versions before dispatch and
projects the Foundation source content, but not prior evaluation verdicts, into
the evaluator context. The exact Authority wrapper is validated first; its
governed `candidate_payload` is then exposed only in this closure as
`semantic_payload`. The generic Provider projection continues to strip
`candidate_payload`, so no other stage gains an implicit candidate-source
channel. Generator prompts, mutable projections and unbound context remain
excluded.

BookPlan generation has two bounded structural regeneration opportunities. The
second is recovery capacity for independent first-error failures in the dense
typed contract; it does not waive validation. Each repair receives the exact
failed candidate and validation report, and every regenerated candidate must
still pass the full structural and independent semantic gates.

Relevant public surfaces are:

- Book/BookDesign Authority under `/authority/books`;
- Story Formation under
  `/product/production/book-authority/books/{book_id}/formation-runs`;
- Book Opening under
  `/product/production/book-authority/books/{book_id}/opening-runs`;
- production input resolution and BookRun start under
  `/product/production/book-authority`;
- Capability Pack registration, compilation, approval, deployment and
  activation under `/api/capability-packs`.

Formation and Opening are RuntimeJob-backed. Run the canonical Book worker or
claim through the same worker executor until Formation is `READY` and Opening
is `COMPLETE`. A recovered Opening preserves the frozen business request and
never creates a new candidate, Planning or qualification truth merely to
continue execution. That rule does not mean re-opening a terminal inner
Operation. If a semantic-evaluation Operation is terminal and authoritative
Effect evidence proves replacement is safe, the Book Opening Recovery
Application may admit a new semantic-evaluation execution generation with
explicit `replacement_of` lineage. The predecessor remains immutable and the
new Operation uses generation-aware idempotency and concurrency identity.
Replacement is terminal-only and bounded at generation 3. If the current
semantic Operation is nonterminal, a recovered Opening must re-enter that same
generation/Operation through the normal governed worker. In particular, a
durable Provider receipt followed by a crash before output materialization or
Operation terminalization must replay the proven result without another
Provider invocation.

Book Opening execution loss and recovery authorization are separate. An
expired/lost Opening claim is first converged through the Book Opening Recovery
Application: its exact RuntimeJob, Attempt, Lease and execution generation become
terminal evidence and the Opening becomes `FAILED`. This loss step neither
creates a RecoveryIntent nor calls a Provider. A subsequent operator-authorized
`recover` requires a fresh immutable assessment, revalidates all Authority,
checkpoint, generation, policy and ExternalEffect evidence in its transaction,
and only then admits the next Opening execution generation.

An expired active Lease cannot be converted into an abort; abort must fail
closed and the formal loss path must terminalize it. Automatic loss assessment
identity is bound to the fresh authoritative snapshot, so release or evidence
drift after assessment requires a new immutable assessment.

An `UNKNOWN_AMBIGUOUS` ExternalEffect blocks replacement and requires the
existing Effect reconciliation path; operator approval cannot waive this
boundary. Recovery, loss convergence and checkpoint reconciliation never call a
Provider. Any admitted replacement executes later through the normal governed
worker path. Legacy `BookOpening.resume()` must not be used: it is blocked or
internally routed through the same assessment and recovery contract. HTTP,
maintenance, worker and any operational CLI surface must share that Application
path and must not contain direct repair SQL.

Checkpoint-based resume may skip a whole semantic work item only when the
cursor names the exact still-`ACTIVATED` Narrative Search and selection
decision, with exact search, `future-N` branch and `EVALUATION_PENDING`
Planning-generation lineage. Legacy binding uses the distinct
`LEGACY_EXECUTION_RECONCILIATION` fact; a missing RuntimeJob becomes an
attempt-less `CANCELLED` RuntimeJob / `ABORTED` OpeningExecution marker, not an
inferred checkpoint or RecoveryIntent.

## Non-secret runtime environment

Create a JSON object containing only non-secret values. The state capturer
rejects keys containing secret, token, password, API-key or credential markers.
Provider login material and MinIO access/secret keys remain process environment
only.

The real profile requires explicit `codex-cli` / `gpt-5.6-sol` / `high` routes
for Planning, draft, review, revision, rereview, Canon extraction, Quality,
Reader Outcome and Narrative Evaluation; no silent fallback is permitted. It
also requires the four exact Pack IDs, a validation runtime host/auth-profile
reference, an absolute Codex executable, an empty isolated Codex workspace, an
absolute persistent execution root, MinIO backend/endpoint/buckets, and an
immutable pricing snapshot.

Example non-secret shape (replace paths and Pack IDs with the selected exact
deployment configuration):

```json
{
  "NOVEL_FORGE_ENVIRONMENT": "validation",
  "NOVEL_FORGE_RELEASE_CHANNEL": "VALIDATION",
  "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
  "NOVEL_FORGE_PLANNING_PROVIDER": "codex-cli",
  "NOVEL_FORGE_PLANNING_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_PLANNING_REASONING_EFFORT": "high",
  "NOVEL_FORGE_DRAFT_PROVIDER": "codex-cli",
  "NOVEL_FORGE_DRAFT_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_REVIEW_PROVIDER": "codex-cli",
  "NOVEL_FORGE_REVIEW_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_REVISION_PROVIDER": "codex-cli",
  "NOVEL_FORGE_REVISION_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_REREVIEW_PROVIDER": "codex-cli",
  "NOVEL_FORGE_REREVIEW_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_CANON_EXTRACTION_PROVIDER": "codex-cli",
  "NOVEL_FORGE_CANON_EXTRACTION_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_QUALITY_PROVIDER": "codex-cli",
  "NOVEL_FORGE_QUALITY_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_READER_OUTCOME_PROVIDER": "codex-cli",
  "NOVEL_FORGE_READER_OUTCOME_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "codex-cli",
  "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": "gpt-5.6-sol",
  "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": "high",
  "NOVEL_FORGE_REASONING_EFFORT": "high",
  "NOVEL_FORGE_RUNTIME_HOST_ID": "host:bounded-quality:<sha12>",
  "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:chatgpt-codex-cli",
  "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": "story_planning_pack",
  "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": "chapter_generation_pack",
  "NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID": "reader_outcome_pack",
  "NOVEL_FORGE_NARRATIVE_EVALUATION_CAPABILITY_PACK_ID": "narrative_semantic_evaluation_pack",
  "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
  "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "/absolute/runtime/object-locators",
  "NOVEL_FORGE_MINIO_ENDPOINT": "127.0.0.1:9000",
  "NOVEL_FORGE_MINIO_RAW_BUCKET": "bounded-quality-raw",
  "NOVEL_FORGE_MINIO_ARTIFACT_BUCKET": "bounded-quality-artifacts",
  "NOVEL_FORGE_MINIO_EXPORT_BUCKET": "bounded-quality-exports",
  "NOVEL_FORGE_CODEX_EXECUTABLE": "/absolute/path/to/codex",
  "NOVEL_FORGE_CODEX_WORKSPACE": "/absolute/empty/codex-workspace",
  "NOVEL_FORGE_CODEX_EXECUTION_ROOT": "/absolute/persistent/codex-executions",
  "NOVEL_FORGE_CODEX_PRICING_REF": "operator-frozen:<model>:<date>:estimate-not-provider-billing",
  "NOVEL_FORGE_CODEX_PRICING_CURRENCY": "USD",
  "NOVEL_FORGE_CODEX_INPUT_PER_MILLION": "<amount>",
  "NOVEL_FORGE_CODEX_CACHED_INPUT_PER_MILLION": "<amount>",
  "NOVEL_FORGE_CODEX_OUTPUT_PER_MILLION": "<amount>"
}
```

The pricing values are an operator-frozen cost estimate unless the Provider
returns billing-grade cost. Usage must still be measured from real Provider
receipts; missing measured usage fails the real campaign.

## Capture and freeze exact state

Set secrets in the process environment, not the JSON file:

```bash
export NOVEL_FORGE_MINIO_ACCESS_KEY='<runtime value>'
export NOVEL_FORGE_MINIO_SECRET_KEY='<runtime value>'
export NOVEL_FORGE_QUALITY_CAMPAIGN_SECRET='<at least 16 random characters>'
```

Capture the already prepared unstarted BookRun. Reviewer IDs are operational
pseudonyms; the final report records evaluator identity class, not unnecessary
personal data.

```bash
PYTHONPATH=src python scripts/run_bounded_quality_qualification.py \
  capture-real-state \
  --database-url "$NOVEL_FORGE_DATABASE_URL" \
  --book-run-id '<book-run-id>' \
  --campaign-id 'quality:<sha12>:v1' \
  --reviewer 'reviewer-1:PROFESSIONAL_EDITOR' \
  --reviewer 'reviewer-2:EXPERIENCED_READER' \
  --runtime-env /absolute/path/runtime-env.json \
  --output /absolute/path/runtime-state.json
```

The command is read-only with respect to narrative/runtime Authority. It checks
an unstarted target-eight resolved-input BookRun, Formation-ready six-layer
Foundation, exact Planning snapshot, selected active validation Packs and clean
release SHA, then writes a descriptor. The descriptor is not narrative truth.

Freeze the campaign manifest:

```bash
PYTHONPATH=src python scripts/run_bounded_quality_qualification.py \
  freeze --mode real \
  --database-url "$NOVEL_FORGE_DATABASE_URL" \
  --state /absolute/path/runtime-state.json
```

Any SHA, migration, Pack, Foundation, Planning, route or profile drift requires
a new campaign identity. Never edit a frozen descriptor to point at new state.
Freeze also reads settled Budget Authority reservations and refuses admission
unless preparation leaves at least 80 Provider calls, 4,800,000 measured tokens
and USD 60.00 for execution. Unresolved reservations, an existing budget breach
or a model effect without a reservation also blocks freeze.

## Execute or recover the bounded campaign

```bash
PYTHONPATH=src python scripts/run_bounded_quality_qualification.py \
  run-real \
  --database-url "$NOVEL_FORGE_DATABASE_URL" \
  --state /absolute/path/runtime-state.json \
  --output /absolute/path/campaign-result.json
```

The runner executes Group 1-4, drains Reader/Recap evidence, then executes
Group 5-8. It checks budget after every Chapter and follow-up tick. Frozen
ceilings are eight Chapters, 120 Provider dispatches, 16 retries, 5,400,000
input tokens, 1,200,000 output tokens, 6,600,000 total tokens, USD 4 per call,
USD 8 per model Operation, USD 20 per Chapter, USD 80 per campaign Project and
four hours per invocation. The Operation envelope is deliberately two times the
per-call ceiling because the frozen Chapter operation contract permits two
Attempts; a first failed call with measured usage must not make its one legal
retry structurally unreachable. Both attempts still settle independently and
remain subject to the Chapter and campaign ceilings. These empirically bounded
ceilings include canonical preparation, search and repair calls. A ceiling is a
hard stop, not a target.

Before the first Chapter provider call, each ChapterGroup Narrative Search must
show the complete frozen request in its generation command and Context Bundle.
For this profile the Provider output schema bounds `chapter_range` to exactly
two values drawn from the frozen endpoints (`1`/`4` or `5`/`8`), fixes matrix
row Chapter identities to the complete range and restricts realization events
to it. Planning Authority then requires the exact ordered pair `[1,4]` or
`[5,8]` plus exact matrix and event coverage. This split avoids unsupported
array-valued JSON Schema constants without weakening admission. A candidate
that changes or reverses the range, repeats an endpoint, omits a Chapter, or
emits a disclosure outside the same event's `reader_may_learn` boundary is
rejected; repairs remain bounded and the failed candidate evidence is retained.

Operational Chapter planning applies the same dialect boundary to the Frozen
Narrative Realization slice. The Provider schema freezes its complete object
shape, array cardinalities and scalar vocabulary without using unsupported
object- or array-valued JSON Schema constants. Planning Authority then compares
the returned slice with the exact frozen object, including list order and
multiplicity. A schema-valid echo is therefore still only a candidate; any
semantic drift fails before ChapterPlan activation.

Canon extraction similarly receives an explicit Actual-evidence contract. Every
frozen Arc contribution has one observation; `OBSERVED` requires at least one
accepted-revision character-span reference in `resolution_evidence`. Every
frozen Narrative Realization event has one observation; `OBSERVED` requires
accepted-prose spans plus observed identity, action, decision, consequence and
state deltas. Planning context or Future Intent is never location evidence and
cannot become Actual merely by matching the output schema.

After an interruption, use the same state and frozen campaign:

```bash
PYTHONPATH=src python scripts/run_bounded_quality_qualification.py \
  resume \
  --database-url "$NOVEL_FORGE_DATABASE_URL" \
  --state /absolute/path/runtime-state.json \
  --output /absolute/path/resumed-result.json
```

Resume reconciles durable Attempts, receipts, Chapter acceptance and Group
state. Do not delete failures, release unresolved budgets manually, or create a
second BookRun to hide a failed attempt.

This command resumes the already admitted bounded campaign. It is not the
legacy Book Opening `resume()` mutation and cannot bypass Book Opening execution
loss, RecoveryAssessment, ExternalEffect reconciliation or generation checks.

A measured retryable Provider failure may consume the next Attempt only inside
the frozen USD 8 Operation envelope. If the operation reaches `FAILED_FINAL`,
`DEAD_LETTER`, or has used all frozen Attempts while still
`FAILED_RETRYABLE`, the campaign records
`CAMPAIGN_RUNTIME_RECOVERY_EXHAUSTED`; it cannot remain indefinitely `RUNNING`
or be rescued by editing its manifest.

A terminal budget, wall-clock, route, Pack or Provider-evidence violation is
persisted as an `ENGINEERING_QUALIFICATION_FAILURE` and moves the campaign to
`FAILED / FAIL`. It leaves Hard Correctness, Editorial Quality and
Reader/Longitudinal Quality at `NOT_PROVEN`; an engineering failure is not
rewritten as a narrative failure. Transient recoverable interruptions remain
resumable and do not use this terminal path.

At eight acceptances the campaign must remain
`WAITING_HUMAN_EVIDENCE / NOT_PROVEN`. This is the expected zero-human result,
not an engineering failure.

## Blind reviewer packs

Export only public packs:

```bash
PYTHONPATH=src python scripts/run_bounded_quality_qualification.py \
  export-blind-packs \
  --database-url "$NOVEL_FORGE_DATABASE_URL" \
  --state /absolute/path/runtime-state.json \
  --output-dir /absolute/path/blind-packs
```

Each reviewer reads Chapter pairs 1 through 8 in story order, then the Arc pair.
A/B ordering is deterministic, balanced and complementary across reviewers.
Public packs contain neither Canonical/Baseline mapping nor Provider/model,
Prompt/branch, Judge/system score or the other reviewer's decisions.

For each pair the reviewer records:

- `A`, `B`, `TIE` or `CANNOT_JUDGE`;
- ten 1-5 dimension scores for overall preference, readability, character
  credibility, scene effectiveness, tension/momentum, emotional impact, prose,
  continuity, payoff satisfaction and desire to continue;
- confidence from 0 to 1;
- optional rationale and evidence spans.

`CANNOT_JUDGE` requires null dimension values rather than invented scores.
Import append-only records with:

```bash
PYTHONPATH=src python scripts/run_bounded_quality_qualification.py \
  record-human \
  --database-url "$NOVEL_FORGE_DATABASE_URL" \
  --state /absolute/path/runtime-state.json \
  --input /absolute/path/human-records.json
```

The import supports `DECISION`, `ADJUDICATION` and `FINALIZE` records. Raw
reviewer disagreement is preserved; adjudication adds a new attributable
decision and never overwrites either reviewer. Human opinion is subjective
evidence, not `GroundTruth`.

Two valid independent reviewers produce only bounded preference evidence. One
valid reviewer is `HUMAN_EVIDENCE_LIMITED`. If reviews remain incomplete, do
not close collection and do not simulate them with an LLM.

## Judge-human calibration and final decision

After the intended human collection is complete, materialize the agreement
report and evaluate:

```bash
PYTHONPATH=src python scripts/run_bounded_quality_qualification.py \
  evaluate \
  --database-url "$NOVEL_FORGE_DATABASE_URL" \
  --state /absolute/path/runtime-state.json \
  --human-collection-closed
```

Calibration v2 reports pairwise agreement, rank/weighted agreement when
estimable, false positives/negatives, confidence, position bias and preference
stability. The current same-model generator/reviewer/Judge route is
`DEPENDENT_SAME_MODEL`. Eight Chapter pairs and one Arc pair per reviewer are
insufficient for statistical Judge calibration, so the calibration claim must
remain `UNCALIBRATED / BOUNDED_EVIDENCE` even if all preferences agree.

Without completed human evidence, omit `--human-collection-closed`; the only
valid outcome is `WAITING_HUMAN_EVIDENCE / NOT_PROVEN`.

## Exact-SHA report

Preserve a new immutable report under `docs/qualification/` only after the run.
It must include release/migration/manifest identity; Provider/model, Pack,
Prompt/Skill and Foundation/Planning/Realization lineage; measured usage, cost,
failures and retries; separate L1/L2/L3 evidence; Human Blind Comparison;
Judge-human diagnostics; Reader Outcome; momentum, payoff and repetition;
Chapter, Arc and bounded Volume conclusions; limitations and final status.

The report must say explicitly that it proves bounded evidence only and does
not prove autonomous million-word premium fiction, real-reader response,
commercial success or production qualification. Historical reports remain
immutable exact-SHA records and never become current evidence merely because a
new branch references them.
