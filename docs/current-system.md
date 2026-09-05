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
| Planning-owned Narrative Realization Authority | approved and frozen causal/event-chain execution-readiness contracts | attempts, leases, effects, accepted actual or a second planning owner |
| Book Authority | book run, accepted cursor, chapter acceptance and whole-book completion assessment | Chapter attempts, Provider receipts or unproven whole-book editorial approval |
| ChapterGroup coordinator | policy-bounded child coordination and group closure | child saga internals, structural narrative ownership or Book acceptance |
| Chapter Authority | chapter saga, draft/revision candidates and release artifacts | accepted Canon or Book cursor |
| Quality Qualification Authority | frozen quality subjects, evidence and decisions | draft text or Book acceptance |
| Canon Approval Authority | Canon approval and re-extraction decisions | raw extraction candidates |
| Narrative State projection | deterministic as-of view over Book-accepted evidence | source outcomes or Canon decisions |
| Reader/recap/calibration Authorities | observation, proxy, preference and proposal evidence; Reader Calibration owns versioned proxy policy | Canon, executed history, active plans or human editorial proof |
| Source and MKAOS Authorities | source lineage, abstractions, knowledge decisions and packs | draft prose or accepted story facts |
| Agent Runtime Authority | definitions, bindings, sessions, checkpoints and transcript provenance | domain assets or narrative truth |
| Command Kernel / Provider effect Authority | Operation, Attempt, Lease, Fence, ExternalEffect and receipt lifecycle | domain activation |

An Authority decides and writes business state. A repository only persists inside the
owner's `AuthorityUnitOfWork`. A coordinator orders work and retains references. A
candidate requires a decision. Evidence informs a decision. A projection derives a read
model. An accepted fact has crossed the owning acceptance boundary. These roles are not
interchangeable even when represented in the same database.

## Narrative object model

The following dispositions describe current contracts and explicit missing semantics.
`ADD` with `DESIGN_REVIEW_REQUIRED` identifies an absent contract; it does not claim an
implemented owner or acceptance route. Existing names remain where a rename would add
only a second representation.

| Concept | Disposition and current implementation | Owner / boundary |
|---|---|---|
| Story Intent | `KEEP` creative Foundation input and layer-specific intent evaluation | Story Design semantic decisions |
| Foundation | `KEEP` `QualifiedFoundationSet` with exact version, content, qualification and activation bindings | Book Design owns the composite binding; Story Design owns bound semantic facts |
| Theme | `KEEP` semantic candidate and qualified Foundation role | Story Design; thematic claim is distinct from accepted thematic progression |
| Reader Promise | `KEEP` versioned semantic candidate and Foundation binding | Story Design; neither proxy preference nor popularity evidence |
| Ending | `KEEP` ending-intent candidate and binding; whole-book ending approval is `DESIGN_REVIEW_REQUIRED` | Story Design intent; no inferred whole-book acceptance |
| World | `KEEP` semantic world-bible candidate and qualified binding | Story Design; no duplicate World Authority |
| Character | `KEEP` cast candidate and binding | Story Design intent; accepted character state is projected separately |
| Relationship | `SPLIT` intent/constraint versus accepted-state projection; independent typed trajectory aggregate remains `DESIGN_REVIEW_REQUIRED` | Story Design intent, Book-accepted state |
| Book Architecture | `KEEP` BookDesign semantic input plus activated `BOOK` planning contract | Book Design owns candidate decisions; Planning owns typed plan activation |
| Volume / Segment | `KEEP` structural/planning intervals and progression constraints | Planning; neither is a universal Arc parent |
| Narrative Arc | `KEEP` independently identified cross-Volume trajectory plan | Planning intent; accepted trajectory projection changes at Book acceptance |
| Character / Relationship / Thematic Trajectory | `SPLIT` intent, scheduled progression and accepted projection; independent typed portfolio lifecycle remains `DESIGN_REVIEW_REQUIRED` | Existing Planning and accepted-fact boundaries remain owners |
| Obligation | `KEEP` setup/debt, dependency, due window and payoff evidence | Planning schedules actions; Book acceptance projects actual resolution |
| ChapterGroup | `DEMOTE` execution window with frozen `ChapterWindowPolicy` | Coordinator retains references; policy bounds execution, never narrative truth |
| Chapter Plan | `SPLIT` Mission and Scene contracts compiled from the same immutable source version | One Planning activation source; no parallel active pointers |
| Chapter Mission | `ADD` typed `chapter-mission.v1` with source version/hash and exact trajectory/state/reader/exit commitments | Planning contract compiler; structural proof only |
| Scene Architecture | `ADD` typed `scene-architecture.v1`, own digest and exact Mission digest dependency | Planning; scene contributions must cover Mission changes/arcs exactly |
| Scene / Beat | `KEEP` ordered scene and beat intent inside Chapter Plan | Structural containment and planned causal/information progression |
| Narrative Realization | `KEEP` Planning-owned causal execution-readiness contract and accepted-boundary bindings | Generated/frozen realization is not accepted actual; Kernel owns execution state |
| Draft / Revision | `KEEP` immutable candidates and revision lineage | Chapter Authority; review/quality gates precede Book acceptance |
| Accepted Actual | `KEEP` immutable Book-accepted outcome/projection boundary | Book chapter-acceptance transaction; future replans cannot rewrite it |
| Canon | `KEEP` governed approval and accepted-fact projection | Canon decisions and Book acceptance remain distinct |
| Narrative State | `KEEP` deterministic as-of projection | Rebuildable from Book-accepted evidence |
| Reader Evidence | `KEEP` observations and advisory proxy/preference views | Reader Calibration policy is versioned and explicitly uncalibrated; calibrated behavior requires unavailable typed dataset lineage |
| Whole-book Completion | `ADD` durable terminal accepted-boundary assessment; acceptance is `DESIGN_REVIEW_REQUIRED` | Book Authority persists `BLOCKED` cases; no editorial acceptance is fabricated |

These relations remain separate:

| Relation | Current meaning |
|---|---|
| Structural containment | Chapter owns ordered Scene/Beat location; Volume/Segment describe structural spans |
| Trajectory | Arc/state/relationship/obligation change crosses structural spans |
| Planning dependency | Exact approved upstream versions constrain downstream planning; Scene binds its Mission digest |
| Execution dependency | Realization, Context, Provider admission and attempt contracts freeze the inputs used by execution |
| Accepted-fact projection | Book-accepted ChapterOutcome and projection-set identities determine Canon/Narrative State/trajectory views |

`compile_chapter_contracts` rejects no-op or missing state changes, missing trajectory
versions, duplicate scene identities, and omitted or undeclared scene contributions.
Mission and Scene digests appear in normalized chapter-plan evidence and Provider views.
The mission embedded in ChapterExecutionIntent is an execution projection: it binds
these Planning digests to accepted-boundary and Memo instructions and owns no active
planning state.
The proof ceiling is `NARRATIVE_CONTRACT_ONLY`; structural coverage cannot establish
literary quality, human approval or an independently persisted Scene Authority.

## Narrative validation descent

Layer-specific evaluation profiles and typed validators carry the current descent. The
existing eleven `NarrativeDesignLayer` profiles map onto the abstraction levels below;
a chapter count is an experiment sample size, never a product validation level. A
missing target contract stays blocked rather than being replaced with more prose.

| Level | Input → output / Authority | Gate, evidence and prerequisite for descent | Revision / replan semantics |
|---|---|---|---|
| Intent | Creative input → qualified intent candidate / Story Design | Intent profile and immutable evaluation lineage; qualified input before Foundation assembly | New candidate/decision; no mutation of accepted history |
| Foundation | Exact Theme/Promise/Ending/World/Cast bindings → qualified set / Story Design facts and Book Design binding | Six exact role/version dependencies, activation/content hashes, qualification receipts and Planning current-binding gate | Replace exact semantic versions and requalify dependents |
| Book Architecture | Qualified Foundation + design → active Book plan / Book Design and Planning | Semantic architecture evaluation, typed schema/lineage and activation gate | Future Plan Change validates dependencies and preserves executed/accepted spans |
| Trajectory Portfolio | Book/Volume/Arc, character development and obligation design → scheduled trajectory commitments / Planning | Arc graph, character development, disclosure/obligation and scheduling profiles; independent typed relationship/thematic portfolio acceptance is `DESIGN_REVIEW_REQUIRED` | Replan only unexecuted future commitments; retain accepted trajectory facts |
| Chapter Mission | Active plans and accepted boundary → typed Mission / Planning | Exact source version, non-noop state changes, Arc versions, reader/exit requirements and chapter-plan evaluation | New Chapter Plan version; downstream Scene digest must bind the new Mission |
| Scene Architecture | Mission → ordered Scene/Beat contract / Planning | Scene evaluation plus exact Mission transition/Arc coverage and distinct digest; failure blocks canonical plan admission | Replace the source plan; recompile both contracts without a second active source |
| Prose | Qualified plan + governed Context/Realization → Draft/Revision candidates / Chapter Authority | Provider admission, durable effects, review issues, revision and quality gates; upstream contracts required before generation | Immutable new candidate, issue-resolution lineage and bounded retries |
| Acceptance | Qualified candidate/ChapterOutcome → Accepted Actual / Book and Canon decision boundaries | Chapter quality/release evidence, exact outcome and atomic accepted projection transaction | Corrections need explicit owner decisions; future replan cannot rewrite acceptance |
| Longitudinal Narrative | Accepted projection sequence → drift/Arc/obligation and completion evidence / Quality, Reader and Book owners | Accepted trajectory/payoff/repetition/reader-trend evidence; whole-book ending/editorial approval is `DESIGN_REVIEW_REQUIRED`, human evidence is `WAITING_EVIDENCE` | Evidence may request future revisions; it cannot directly activate plans or grant whole-book acceptance |

Generator and evaluator operation identities are distinct. Scripted evaluation is
contract evidence only. A model judge can issue evaluation evidence but cannot become
the human evaluator or the semantic activation owner.

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

## Context governance and Provider admission

Context assembly has one governed seam. A ContextBundle compiles ContextProfile,
ProductionStageProfile and caller limits; Provider preflight then intersects that frozen
receipt with the Capability Pack and route policy. The resulting five inputs use logical
kind allowlist intersection, physical-type admission, deny-wins, required-source union
and strictest-limit semantics. Planning applies the same compiler to the bounded
`provider-context-view-v2` projection rather than treating the larger stored input as
prompt material. Eligibility and deterministic four-identity representation deduplication
precede ranking and consumption of total, section, bucket and Context-class budgets.
The Chapter request admission boundary freezes one Book identity and one accepted-state
boundary onto every candidate; Context assembly validates those identities but does not
invent Authority scope.
Optional projections may use an explicitly allowed structured-element truncation;
required or protected material fails closed when it cannot fit. ContextBundle v8 and
NarrativeContextManifest v4 retain every policy identity, selection, rejection,
deduplication, truncation, provenance and estimate. Historical v7 and typed legacy
manifests use their frozen validators and are not recompiled.

Context token estimates are selection evidence, not a Provider hard bound. Before a real
Provider ExternalEffect exists, Production Execution renders the exact request, binds its
hash to the route/provider/model and applies a versioned accounting contract covering the
complete input, framing, output reserve and safety margin. Context selection limits and
complete-request admission limits are distinct: normal execution admits against the
route/model window, while Book Opening also applies its immutable per-call token ceiling.
The admitted exact or conservative total becomes the Provider budget reservation. The
remote adapter sends that same admitted envelope. Agent, Planning and Chapter paths all
perform this preflight before effect creation. An unknown meter, route mismatch, changed
serialization or limit overflow creates no Provider ExternalEffect. Admission manifests
retain hashes and component identities rather than duplicating prompt or raw Source
bodies; Source Intelligence reconstructs transient Source bytes and must reproduce the
admitted hash.

The Context projection migration makes the read-only Context/MKAOS usage views recognize
bundle v7/v8 and manifest v3/v4. It adds no writable Context state or alternate Narrative
Authority. Policy and completion migrations are separate forward-only contracts; the
machine projection owns the exact migration identity.

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
  -> Chapter Mission + Scene Architecture from one Chapter Plan
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
cursor completion is not a whole-book acceptance decision. The Book-owned completion
assessment reads the exact terminal accepted projection, persists its content hash and
blockers, and returns `BLOCKED` while typed ending/editorial approval is unavailable. The synchronous
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

ChapterGroup size is a configurable execution policy. Positive windows may be terminal
or risk-bounded; the default maximum is a policy setting, and no minimum of three is a
narrative invariant. Reader proxy thresholds belong to a versioned, content-hashed
Reader Calibration policy frozen into admitted follow-up work. Unknown or altered policy
snapshots fail replay validation. The v1 thresholds remain uncalibrated advisory rules.

`run_calibration` rejects `BEHAVIOR_CALIBRATED` before metrics, database access or command
admission because caller observations have no typed authoritative exposure/outcome-event
binding. Aggregate behavior counts remain fixture diagnostics and cannot establish that
lineage. `resolve_profile` returns no admissible profile while the dataset contract is
absent, including previously stored unbound `VALID` rows. Fixture calibration continues
to persist `INSUFFICIENT_DATA`, `SHADOW` and `behavior_calibrated=false`.

Independent typed trajectory portfolio lifecycle, whole-book ending/editorial approval,
and authoritative Reader calibration dataset lineage remain explicit
`DESIGN_REVIEW_REQUIRED` boundaries. They do not
justify duplicate active state, reinterpret accepted history, or raise proof ceilings.

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

The retained live Provider reports target different implementation identities and remain
historical evidence. Current credentialed execution and real accepted-chapter production
are `NOT_PROVEN` until an admitted external route supplies new exact-identity evidence.
Human editorial remains `WAITING_EVIDENCE`; AI self-review and fixture preferences cannot
close that boundary. Continuous samples must be selected for trajectory/obligation and
quality-drift coverage, with engineering, narrative correctness, human, reader,
longitudinal and production evidence retained separately.
