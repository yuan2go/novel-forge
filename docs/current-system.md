# Current system

## What Novel Forge is today

Novel Forge is a local-first, PostgreSQL-authoritative AI novel production runtime. It
combines versioned story-design and planning Authorities with durable book/chapter
coordination, governed Provider and object-store effects, candidate review gates, and an
atomic transition from a qualified chapter candidate to accepted narrative facts.

It is not a one-shot prompt generator, a complete autonomous Agent product, or proof of
long-form production quality. The current machine projection is
`architecture/reality-evidence.json`; executable code, schema, migrations, composition
and current tests remain its source, never the reverse.

Capability states are ordered `CODE_EXISTS`, `WIRED`, `EXECUTABLE`, `QUALIFIED`, and
`PRODUCTION_PROVEN`. A lower state never implies a higher one. The projection binds its
implementation-tree identity, and Documentation Reality fails when code or instruction
identity changes without a corresponding projection update.

## Production topology

```text
CLI / FastAPI / worker manifest / Compose process
  -> application or coordinator
  -> owning Authority command
  -> Command Kernel Operation
  -> Attempt + Lease + Fence
  -> durable ExternalEffect intent when external I/O is needed
  -> Provider or object-store adapter outside the business transaction
  -> receipt reconciliation
  -> owning Authority transaction
  -> PostgreSQL evidence + outbox + accepted projections
```

The checked entry surfaces are the CLI and FastAPI composition, production-entry and
worker manifests, and Compose services. `ProductionExecutionComposition` supplies the
shared execution gateway, object storage and budget wiring. RuntimeJob and the Book,
ChapterGroup and follow-up coordinators schedule cross-owner work; coordination does not
grant authority to mutate another owner's state.

## Authority model

The machine projection records exact owner symbols and mutation evidence. The operative
ownership boundaries are:

| Owner | Owns | Does not own |
|---|---|---|
| Project Authority | project/workspace lifecycle and bindings | book content or Provider effects |
| Book Design Authority | foundation-qualified BookDesign candidates and active design pointer | Story Design activation or accepted chapter actual |
| Story Design Authority | semantic candidates, decisions and active semantic versions | typed plan activation |
| Hierarchical Planning / Plan Change | typed plan contracts, active bindings and future-only replacements | semantic design or executed history |
| Narrative Realization Authority | approved and frozen event-chain realization contracts | plan scale or accepted actual |
| Book Authority | book run, accepted cursor and chapter-acceptance transaction | Chapter attempts or Provider receipts |
| ChapterGroup Authority | bounded child coordination and group closure | child saga internals or Book acceptance |
| Chapter Authority | chapter saga, draft/revision candidates and release artifacts | accepted Canon or Book cursor |
| Quality Qualification Authority | frozen quality subjects, evidence and decisions | draft text or Book acceptance |
| Canon Approval Authority | Canon approval and re-extraction decisions | raw extraction candidates |
| Narrative State projection | deterministic as-of view over Book-accepted evidence | source outcomes or Canon decisions |
| Reader/recap/calibration Authorities | observation, proxy, preference and proposal evidence | Canon, executed history or active plans |
| Source and MKAOS Authorities | source lineage, abstractions, knowledge decisions and packs | draft prose or accepted story facts |
| Agent Runtime Authority | definitions, bindings, sessions, checkpoints and transcript provenance | domain assets or narrative truth |
| Command Kernel / Provider effect Authority | Operation, Attempt, Lease, Fence, ExternalEffect and receipt lifecycle | domain activation |

An Authority decides and writes business state. A repository only persists inside the
owner's `AuthorityUnitOfWork`. A coordinator orders work and retains references. A
candidate requires a decision. Evidence informs a decision. A projection derives a read
model. An accepted fact has crossed the owning acceptance boundary. These roles are not
interchangeable even when represented in the same database.

## Narrative object model

The runtime does not implement one universal narrative tree. It distinguishes structural
containment, causal dependency, temporal trajectory, planning dependency and
accepted-fact projection.

| Object | Current nature | Key relationship |
|---|---|---|
| Story Foundation | qualified input container | binds semantic evidence to Book Design |
| Book Design | candidate | informs Volume and Arc planning after activation |
| Volume | plan/container | structurally contains Segment and ChapterGroup windows |
| Narrative Segment | plan | expresses ordered progression and handoff, not universal Arc parentage |
| Narrative Arc | trajectory plan | has independent identity and may cross Volumes |
| Arc trajectory | projection | moves only from accepted ChapterOutcome evidence |
| ChapterGroup | coordination container | contains a bounded sequence of Chapter plans, not Chapter execution state |
| Chapter Plan | operational plan | contains scene/beat intent and depends on active higher plans |
| Scene / Beat | plan component | schedules state and information movement toward a candidate draft |
| Narrative Realization | proposal/contract | approved event-chain realization, separate from plan scale and actual |
| Draft / revision | candidate | cannot become Canon or accepted actual by generation alone |
| Accepted Actual | accepted fact | created only by Book chapter acceptance |
| Canon | approved projection | extraction is merely a proposal |
| Narrative State | projection | deterministic as-of view over accepted evidence |
| Obligation | trajectory | setup, due-window and payoff state across accepted chapters |
| Reader State | evidence | may motivate a proposal but cannot directly rewrite truth or plans |

## Bounded long-form retrieval

Retrieval binds one campaign to the exact project, book, accepted-through chapter,
ExecutionIntent, Memo and policy identity. Round zero uses the accepted selective
retrieval projection. If deterministic coverage still identifies required evidence,
Production Execution may return a typed query-expansion proposal through the existing
ExternalEffect path. Deterministic policy validates every query and selector, freezes at
most three append-only rounds, and alone decides sufficiency and termination. The model
cannot name admissible AssetVersions or expand the accepted boundary. Context Authority
admits only the frozen union after coverage is sufficient and continues to enforce the
configured token budget; the default final retrieval limit remains 24.

## Executable novel-production chain

The current production-reachable chain is a set of Authority transitions, not one
all-owning command:

```text
Project scope
  -> optional Source/MKAOS inputs
  -> qualified Foundation + BookDesign candidate/decision
  -> Story Design candidate/decision
  -> five-layer Book Opening workflow
  -> active typed plans
  -> approved Narrative Realization
  -> Book production + ChapterGroup coordination
  -> Chapter plan
  -> frozen retrieval union + ContextBundle
  -> durable Chapter saga
  -> conditional Provider/object-store ExternalEffects
  -> review, bounded revision, quality and release gates
  -> Book chapter acceptance
  -> Accepted Actual + Canon + Narrative State + long-form projections
  -> asynchronous reader/recap evidence
  -> optional future-only plan-change proposal and reactivation
  -> next ChapterGroup/Chapter cycle
```

The logical design chain is therefore distributed across owners. There is no single
production command that starts from an idea and owns a finished book, and terminal Book
cursor completion is not a separate whole-book acceptance decision. The synchronous
`ChapterAuthorityApplication.run` seam is fixture-guarded; the production path is durable
admission plus scheduler ticks. These absences are explicit machine boundaries, not
implicit capabilities.

## Persistence, effects and recovery

PostgreSQL owns production business and execution facts. `AuthorityUnitOfWork` rolls back
unless explicitly committed, and composed owner mutations use the declared transaction
or savepoint boundary. The migration registry and migration manifest jointly determine
the current head; canonical prose intentionally does not duplicate its identity.

Provider and MinIO-compatible object-store calls use durable ExternalEffect intent,
dispatch generation and receipt records. A request that may have started is reconciled
before retry and is never blindly resent. Idempotency keys bind the request digest;
Attempt leases and fencing reject stale workers. Safe database retries are restricted to
classified SQL states, while an unknown commit result requires evidence-based
reconciliation. Recovery appends attempt, receipt, checkpoint or replacement lineage and
does not rewrite terminal history.

Book acceptance is the decisive narrative mutation: one transaction advances the cursor
and binds ChapterOutcome, accepted Canon/Narrative State inputs, long-form projections,
audit and outbox evidence. Reader and recap work follows asynchronously and remains
advisory.

## Semantic constraint classes

Only `CURRENT_PROVEN_INVARIANT` statements may be treated as canonical architecture
invariants. Current implementation shape is `CURRENT_RUNTIME_FACT`; thresholds and
limits owned by profiles or frozen capability packs are `CONFIGURABLE_POLICY`; import
adapters for retired shapes are `HISTORICAL_COMPATIBILITY`; and undecided domain meaning
is `UNRESOLVED_DESIGN_CONSTRAINT` with `design_review_required=true`.

The current proven set includes atomic Book chapter acceptance, no blind resend after an
ambiguous external effect, candidate/accepted-actual separation, raw-source isolation,
and Arc identity independent of Volume containment. The typed planning levels, planning
horizons, five Book Opening layers and the minimum evaluator behavior are current runtime
facts, not claims of final design. Quality thresholds, retry counts and context budgets
are configurable policies. The pre-hierarchy import flag is compatibility-only.

Two constraints remain unresolved: the hard three-to-eight ChapterGroup range lacks
evidence of final business necessity, and reader-proxy thresholds lack a versioned policy
owner. Current code continues to enforce them; documentation must not rationalize them as
proven invariants.

## Qualification ceiling

`make p0-backend-qualification` is the single high-level backend engineering gate. It
binds a clean implementation revision, complete non-PostgreSQL and PostgreSQL test
collections, fresh and supported-upgrade migrations, query plans, scripted Compose
runtime/recovery and zero-residue cleanup. A capability can be `QUALIFIED` only while a
retained passing report matches the current implementation-tree identity and covers its
test references.

P0 uses scripted Provider behavior. It establishes local backend, PostgreSQL and recovery
engineering only. Credentialed Provider execution is separately qualified and becomes
stale when implementation or instruction identity changes. Neither route establishes
admin UI execution, human editorial evidence, longitudinal narrative stability or
production operation. No current capability is `PRODUCTION_PROVEN`.
