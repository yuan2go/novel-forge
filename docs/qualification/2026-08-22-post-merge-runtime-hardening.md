# Post-Merge Runtime Hardening Qualification

> **Status:** EXACT-SHA EVIDENCE SNAPSHOT — not architecture authority
>
> **Baseline main:** `1fcb1789c1c46643a2bf63cac8ae22a94ea3e67f`
>
> **Qualified release:** `00b5572b8559d851df79aab028cee5eebfe5a0c3`
>
> **Date:** 2026-08-22, Asia/Shanghai

The machine-readable companion is
[`2026-08-22-small-real-provider-qualification.json`](2026-08-22-small-real-provider-qualification.json).
This record closes the bounded hardening run; it is not a claim of literary,
long-form, multi-book or production qualification.

## Docs/runtime reconciliation

The review started from executable entry/composition, Operation, Attempt,
Lease/Fence, ExternalEffect/Receipt, Domain Authority, PostgreSQL mutation,
recovery, consumer and tests. It corrected current-runtime documents that had
treated the 0095 success path as full recovery, called semantic reranking
semantic retrieval, or blurred scripted and real-provider proof.

The prior 2026-08-21 correctness spec/plan are retained only as
`SUPERSEDED / HISTORICAL_ONLY`. The canonical/current-runtime views were
updated in `docs/architecture/`, the production-flow view and the post-0094
repair runbook. No historically useful document or published migration was
deleted or rewritten; migration 0096 is forward-only.

## Closed runtime contracts

### Arc follow-up

Accepted Chapter, Canon, Story State and Arc Actual are immutable inputs to the
follow-up. The converged state handling is:

```text
READY -> RUNNING -> PROPOSED -> WAITING_APPROVAL -> COMPLETED
                  |             |
                  |             -> Book.REPLAN_APPROVAL_PENDING
                  -> FAILED_RETRYABLE / RECONCILIATION_REQUIRED
                  -> FAILED_FINAL / DEAD_LETTER / CANCELLED / MANUAL_INTERVENTION
```

- `FAILED_RETRYABLE` keeps the same follow-up and stable idempotency identity;
  the Book remains `CHECKPOINT_PENDING` only while an explicit retry or
  reconciliation action exists.
- exhaustion, `FAILED_FINAL` and `DEAD_LETTER` persist terminal evidence and
  move the Book to `PAUSED`; generic resume cannot advance Chapter N+1.
- `CANCELLED` persists cancellation evidence, moves the Book to `PAUSED`, and
  requires an explicit checkpoint re-request or abort.
- a missing ArcRevision after a nominal success becomes
  `MANUAL_INTERVENTION`, never silent completion.
- PlanChange approval uses `REPLAN_APPROVAL_PENDING`, not
  `CHECKPOINT_PENDING`.

This is why a non-retryable Arc Recap failure cannot leave a Book permanently
and unactionably `CHECKPOINT_PENDING`.

### Embedding unknown external state

The logical projection identity is source AssetVersion + source content hash +
projection version. `UNKNOWN_EXTERNAL_STATE` checkpoints the original Attempt
and reconciles its original effect/dispatch/receipt. A completed receipt
materializes that result; confirmed non-execution authorizes a governed retry;
an unresolved outcome stays reconciliation/manual. No new dispatch is created
merely because a worker crashed or a lease was taken over. READY projections
are content/model/dimension conflict checked, and stale fences cannot consume
or rewrite them.

### Agent execution identity and aggregate budget

Controlled admission persists the Agent Definition/version/hash, role,
Tool/Skill/Capability Pack identities and hashes, prompt/context policies,
provider/model/reasoning/route, release SHA, runtime/policy hashes, Accepted
Boundary and budget. Every model turn compares the current Attempt binding with
that frozen contract. Runtime B therefore cannot silently execute a Session
admitted under runtime A; exact frozen execution is used or execution fails
closed and requires re-admission/migration.

Session budget usage is derived from authoritative Operation lineage and
ledgers. Agent turns, descendant Typed Capability model effects and remote Tool
effects aggregate to the parent Session without copying child costs into a
second ledger. Tools remain `READ_ONLY_QUERY`, `TYPED_CAPABILITY`, or
submit-only `AUTHORITY_COMMAND`; Skills cannot elevate permissions.

### Retrieval Candidate v3

The query plan independently discovers PostgreSQL FTS, vector, graph and
temporal candidates, unions/deduplicates them by document, freezes source
AssetVersions, and reranks with the explicit
`accepted-hybrid-ranking-v3` policy. Vector eligibility includes project,
book, Accepted Boundary, document lifecycle, source hash, projection version,
embedding model and dimensions before top-k selection.

`REQUIRED`, `FALLBACK_ALLOWED` and `DISABLED` are explicit semantic policies.
The PostgreSQL integration fixture proves Chapter 200 can retrieve a Chapter 20
passage with high semantic similarity and no lexical/entity/relationship/Arc/
obligation/recent channel, while Chapter 201, stale and incompatible
model/version candidates are excluded. RetrievalResult replay and fingerprint
are deterministic.

## Small real-provider proof

The exact-SHA run used the authenticated Codex CLI remote-inference transport,
provider `codex-cli`, model `gpt-5.6-sol`, reasoning `medium`, PostgreSQL
Authority and MinIO. The Accepted Boundary is fixture chapter 0, so it is not
human, behavior-calibrated or long-form evidence.

### A. Agent Session

- Session `agent-session:small-provider:00b5572b:35ee03b947d2`
- Operation `ffa4ccd8-2bd3-4275-af07-98ad74b8e88a`
- Attempt `65e8bd8f-7878-42ff-8dc5-19082caab4c1`
- policy hash
  `sha256:e00a4bb78c0824258a52683ddff8d0a10e473ab4edb22bad6bd70422331a7d0b`
- two model effects and two verified receipts
- transcript:
  `REQUEST_STARTED -> MODEL_MESSAGE -> TOOL_REQUESTED -> TOOL_OBSERVED -> MODEL_MESSAGE -> REQUEST_COMMITTED`
- exactly one `narrative.query_accepted` call; no Authority mutation
- 39,636 tokens; estimated USD 0.07285600

### B. Embedding and receipt recovery

- Operation `8424a108-776c-4de1-a575-c983edbaa560`
- Attempt `cf24b8f2-0aa8-4185-8198-28dcc7f98870`
- effect `868431d1-0c55-4386-aa43-5d2e245062bc`
- receipt `process-receipt:a9ff623395062e1f044bf6cb`
- READY projection
  `retrieval-embedding:42b37977f4b22164107e113d52bf17b6b8a70aad7535280a13fac290f328229e`
- frozen model `gpt-5.6-sol`, 8 dimensions, L2-unit/non-placeholder contract
- provider-success crash injected; expired lease taken over; original receipt
  replayed; provider dispatch count remained exactly 1
- 20,030 tokens; estimated USD 0.0315735

### C. Chapter Memo → Retrieval → Draft

- root Operation `a9b68f3a-48c7-47a4-ad80-72c602c931bf`
- bounded stop at Draft; no acceptance or multi-chapter campaign
- query embedding effect `0ae70e10-5527-48df-8982-2c4ad03e7335`, receipt
  `process-receipt:34e4f274f44e39f5e51bb989`
- Draft effect `4d4682c5-f89c-41fa-82fb-32f0c3127f41`, receipt
  `process-receipt:fa89ba42e21e89acfc7aec6e`
- RetrievalResult fingerprint
  `sha256:4224fc66b4cfb7b865ec94d921aa4f2f4f867198d2ebaa56a7bd3a503d47cd46`
- Context fingerprint
  `sha256:94d6ba523334bbedd0ba601ece1235417bf7909f58765b5e79a5b7ae36cb01b0`
- Draft AssetVersion
  `authority-output:fc34abda-1018-4952-89da-0d9449a6ed2b:chapter.draft:v1`
  persists both exact fingerprints
- semantic policy `REQUIRED`, status READY, candidate source channels
  `TEMPORAL + VECTOR`; lexical/entity/relationship/Arc/obligation scores are
  zero; no future leak
- 44,822 tokens; estimated USD 0.1177085

PostgreSQL independently reports 5 effects, 5 dispatches, 5 verified receipts,
5 distinct-effect `model_call_log` AssetVersions and 5 distinct-effect
`cost_ledger` AssetVersions. Total real-provider usage is 104,488 tokens and
estimated USD 0.222138. Cost is an immutable pricing-snapshot estimate, not a
Provider-billed amount.

## Executed verification

Local changed-module/domain tests:

```text
pytest -q <21 changed unit test modules>
180 passed, 5 subtests passed

pytest -q tests/architecture
99 passed, 11 subtests passed
```

Targeted PostgreSQL suites:

```text
pytest -q \
  tests/integration/test_book_followup_authority_postgres.py \
  tests/integration/test_agent_harness_scheduler_postgres.py \
  tests/integration/test_provider_budget_runtime_postgres.py \
  tests/integration/test_retrieval_candidate_v3_postgres.py \
  tests/integration/test_retrieval_embedding_projection_postgres.py \
  tests/integration/test_unified_agent_runtime_postgres.py
27 passed, 6 subtests passed

pytest -q <chapter effect success + unknown-state + Agent receipt-recovery tests>
3 passed
```

The exact-SHA qualification command first passed `--setup-only`, then passed
the full bounded run and emitted all five positive proof flags. GitHub CI was
not run, so this evidence is `LOCAL_TESTED` and `POSTGRES_TESTED`, not
`CI_TESTED`.

A broader pre-existing Chapter/MKAOS audit selection pair still expects one
selection row where the current fixture produces zero. Those two tests also
fail at the starting main baseline and are not used as green evidence here;
they remain an explicit test-suite cleanup item rather than a hardening or
Provider claim.

## Status and next gate

| Scope | Highest earned evidence |
|---|---|
| Arc follow-up | `RECOVERY_PROVEN`, `LOCAL_TESTED`, `POSTGRES_TESTED` |
| Embedding recovery | `PROVIDER_PROVEN`, `RECOVERY_PROVEN` |
| Agent execution contract | `PROVIDER_PROVEN`; aggregate child accounting is `POSTGRES_TESTED` |
| Retrieval Candidate v3 | `PROVIDER_PROVEN`, `POSTGRES_TESTED` |
| One Chapter intelligence slice | `PROVIDER_PROVEN` at Draft only |
| Long-form | `LONGFORM_PROVEN = NO` |
| Production | `PRODUCTION_QUALIFIED = NO` |
| CI | `CI_TESTED = NO` |

The system is ready to propose a separate bounded 10-Chapter qualification
after merge/CI and explicit treatment of the baseline MKAOS audit assertions.
It is not ready to claim a 30-Chapter gate: 30 must wait for a successful
10-Chapter run with failure injection and liveness evidence.
