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
| Book Design Authority | exact qualified Foundation binding set, BookDesign candidates and active design pointer | ownership of bound semantic facts or accepted chapter actual |
| Story Design Authority | Intent, Theme, Promise, Ending, World and Character semantic candidates, decisions and active versions | typed plan activation |
| Hierarchical Planning / Plan Change | typed plan contracts, active bindings and future-only replacements | semantic design or executed history |
| Narrative Realization Authority | approved and frozen event-chain realization contracts | plan scale or accepted actual |
| Book Authority | book run, accepted cursor and chapter-acceptance transaction | Chapter attempts or Provider receipts |
| Whole-book Completion Authority | immutable completion cases, exact accepted-source bindings and versioned blocked/rejected decisions | accepted Chapter history, Canon or human evaluator authorization |
| ChapterGroup Authority | bounded child coordination and group closure | child saga internals or Book acceptance |
| ChapterGroup execution policy Authority | immutable execution-policy versions, project selection and frozen Book bindings | narrative quality or child execution state |
| Chapter Authority | chapter saga, draft/revision candidates and release artifacts | accepted Canon or Book cursor |
| Quality Qualification Authority | frozen quality subjects, evidence and decisions | draft text or Book acceptance |
| Canon Approval Authority | Canon approval and re-extraction decisions | raw extraction candidates |
| Narrative State projection | deterministic as-of view over Book-accepted evidence | source outcomes or Canon decisions |
| Reader/recap/calibration Authorities | observation, proxy, preference and proposal evidence | Canon, executed history or active plans |
| ReaderProxy policy Authority | versioned advisory thresholds frozen per admission | human judgment, reader causality or accepted facts |
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
containment, causal dependency, temporal trajectory, planning dependency, execution dependency and
accepted-fact projection.

| Object | Current nature | Key relationship |
|---|---|---|
| Story Intent | semantic candidate/active version | Creative Foundation constrains downstream design, not accepted actual |
| Theme / Reader Promise / Ending Intent | semantic contracts | exact upstream intent bindings; reachability is not proof of delivery |
| World / Character | semantic Foundation inputs | owned by Story Design, distinct from accepted world/character/relationship state |
| Story Foundation | qualified input container | binds semantic evidence to Book Design |
| Book Design | candidate | informs Volume and Arc planning after activation |
| Book Architecture | strategic BOOK plan | owns structure, development and disclosure commitments after typed activation |
| Volume | plan/container | structurally contains Segment and ChapterGroup windows |
| Narrative Segment | plan | expresses ordered progression and handoff, not universal Arc parentage |
| Narrative Arc | trajectory plan | has independent identity and may cross Volumes |
| Arc trajectory | projection | moves only from accepted ChapterOutcome evidence |
| ChapterGroup | execution coordination window | schedules a policy-bounded sequence, not a universal narrative level |
| Chapter Plan | one immutable operational plan | separately validated Mission and Scene Architecture views |
| Chapter Mission | typed plan view | intent, Arc/trajectory/obligation commitments, state transitions and Frozen realization |
| Scene Architecture / Beat | typed scene view / execution component | exact Mission coverage and Scene-scoped ordered Beat identities |
| Narrative Realization | domain/execution contract | approved and Frozen event chain, not a repository Proposal or accepted actual |
| Draft / revision | candidate | cannot become Canon or accepted actual by generation alone |
| Accepted Actual | accepted fact | created only by Book chapter acceptance |
| Canon | approved projection | extraction is merely a proposal |
| Narrative State | projection | deterministic as-of view over accepted evidence |
| Narrative Reality revision | immutable accepted-source binding | exact Outcome, state, Canon, acceptance and parent revision; no independent fact writer |
| World transition / Candidate Future | causal proposal | deterministic rules constrain candidate evolution; only observed and accepted effects advance reality |
| Causal requirement / debt | predicate / preparation commitment | eligibility requires accepted support; actual payoff evidence discharges accepted debt |
| Scene realization slot | prose candidate component | dynamically selected capability and actor knowledge scope; deterministic ordered integration |
| Planned / accepted Obligation | planning commitment / accepted projection | planned actions never rewrite accepted setup/payoff history |
| Reader Evidence | observation | may motivate a proposal but cannot directly rewrite truth or plans |
| Whole-book Completion | case and decision evidence | distinct from terminal cursor; missing native whole-book human policy blocks acceptance |

The machine object inventory records `KEEP`, `MERGE`, `SPLIT`, `RENAME`, `DEMOTE`,
`RETIRE` or `ADD` dispositions. Mission and Scene are a logical split with one persisted
plan; the Scene/Beat aggregate is split into typed views and execution identities.
Realization is classified as an execution contract; ChapterGroup is an execution-policy
window. Foundation ownership is retained: the binding-set owner does not become the
owner of the semantic assets it references.

Current Chapter activation requires the current Mission/Scene contract and exact Frozen
realization even for imported candidates. Older binding definitions support frozen
receipt replay, not new production admission. Mission, scene, obligation, Arc schedule,
state-transition and realization changes participate in semantic diff and future-only
invalidation. Accepted and executed history remains outside replan mutation scope.

## Narrative validation hierarchy

The narrative qualification report follows abstraction and dependencies, not chapter-count
stages. Each layer retains its own observed proof and upstream blocking status. A missing
upper contract blocks downstream qualification even when candidate prose exists. The
report reads native immutable evidence; it does not activate plans or accept prose.

| Layer | Input → output | Owner and gate evidence | Revision boundary |
|---|---|---|---|
| Intent | story candidates → qualified creative/theme/ending/promise versions | Story Design; current semantic qualification profiles | new semantic version and decision |
| Foundation | qualified intent, world and cast → exact ready Foundation set | Story Design owns semantics; Book Design validates binding readiness and lineage | rebind and requalify the set |
| Book Architecture | ready Foundation and active BookDesign → active BOOK plan | Planning; exact Foundation binding plus architecture/development/obligation receipts | typed future-only replacement |
| Trajectory Portfolio | BOOK, Arc and character development → portfolio proof | full relationship/thematic activation and closure contract absent: `DESIGN_REVIEW_REQUIRED` | no inferred owner or activation |
| Chapter Mission | schedule, Arc working set, Frozen realization → current Chapter plan | Planning; Mission semantic receipt and typed contract validation | future-only Mission replacement |
| Scene Architecture | same Mission → covered scenes and ordered Beats | Planning; independent Scene receipt and exact Mission coverage | replace the owning future Chapter plan |
| Prose | active plan, Context and ExecutionIntent → draft/revision candidates | Chapter; Review, Revision and Quality evidence | new candidate version, never overwrite accepted prose |
| Acceptance | qualified outcome → committed Accepted Actual | Book; successful acceptance Operation and bound Canon/state projections | accepted history is not replan input to mutate |
| Longitudinal Narrative | accepted temporal history and independent observations → bounded trend evidence | Quality evidence projection; independent longitudinal proof required | evidence or future-change proposal only |

Entering the next qualification layer requires the previous layer's current, source-bound
proof. Chapter counts are sample metadata only. Engineering, Narrative Correctness, Human
Editorial, Reader Evidence, Longitudinal Stability and Production Evidence remain six
separate dimensions. Scripted evidence can support contracts, not narrative quality;
AI evaluation is not human evidence, and a combined reader/longitudinal record cannot be
duplicated into two independent proofs.

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

The Context projection migration advances the two read-only Context/MKAOS usage views to
recognize bundle v7/v8 and manifest v3/v4. It adds no writable Context state or alternate
Narrative Authority; the machine projection owns the exact migration identity.

## Executable novel-production chain

The current production-reachable chain is a set of Authority transitions, not one
all-owning command:

```text
Project scope
  -> optional Source/MKAOS inputs
  -> qualified Foundation + BookDesign candidate/decision
  -> Story Design candidate/decision
  -> five-layer Book Opening workflow
  -> active typed plans + Reality-bound causal preparation
  -> approved Narrative Realization
  -> Book production + ChapterGroup coordination
  -> Chapter Mission + Scene Architecture
  -> frozen retrieval union + ContextBundle
  -> durable Chapter saga
  -> selected Scene realization slots through governed Provider ExternalEffects
  -> exact slot integration and candidate revision
  -> conditional object-store ExternalEffects
  -> review, bounded revision, quality and release gates
  -> Book chapter acceptance
  -> Accepted Actual + Canon + Narrative State + long-form projections
  -> immutable Narrative Reality revision and accepted-event index
  -> asynchronous reader/recap evidence
  -> optional future-only plan-change proposal and reactivation
  -> next ChapterGroup/Chapter cycle
```

The logical design chain is therefore distributed across owners. There is no single
production command that starts from an idea and owns a finished book. Terminal Book
cursor completion does not imply whole-book acceptance. The independent Completion
Authority assesses complete accepted/projection history and Arc/obligation closure into
immutable cases; its decisions bind source digest and case/decision versions. Native
Chapter/Arc preference evidence does not authorize whole-book acceptance, so absent
typed whole-book editorial policy produces a recorded blocker, not an accepted book.
The synchronous
`ChapterAuthorityApplication.run` seam is fixture-guarded; the production path is durable
admission plus scheduler ticks. These absences are explicit machine boundaries, not
implicit capabilities.

## Narrative Reality and causal production

`NarrativeRealityRevision` references the exact Book acceptance, ChapterOutcome,
Narrative State, Canon and long-form projection set. Its immutable identity includes
its parent revision and source digest. PostgreSQL requires one revision for each
contiguous accepted frontier. Book acceptance inserts the revision and its derived
event index in the same transaction as cursor advancement. Neither an unaccepted
Draft nor a successful but unaccepted ChapterOutcome can advance this chain. Rebuild
starts from the original frozen Book input and replays accepted outcomes.

World Foundation extends the existing Story Design World asset with core ontology,
genre and Book-owned sections. Sections declare compilation scope and depth; they
need not describe every category before production begins. World rules distinguish
deterministic hard, quantitative and temporal predicates from soft causal suggestions.
Candidate transitions declare on-camera, off-camera or undercurrent effects, exact
story time, actor, changes and accepted causes. Known Character actions require their
own accepted knowledge or belief predicates. The world
clock advances from accepted world transitions, independently of narrative flashforwards.

`planning.causal.propose` binds the current Reality and qualified Creative Foundation.
It rejects invalid world transitions and evaluates causal requirements before ranking
eligible futures across the declared Director dimensions. Missing predicates become
causal preparation debts. The result is an existing Narrative Governance Action consumed
by subsequent planning. It cannot change World, Character, Reader, Obligation or Canon
facts. Canon observation preserves typed world transitions; Book acceptance rechecks
causes, world invariants and the exact origin of causal debt. Only accepted payoff
source evidence can fulfill that debt.

Creative Foundation authoring can compile explicitly labeled natural-language Intent
clauses into goal, required/forbidden constraints, tone, pacing, relationship, Arc,
theme, ending and allowed-deviation fields. Labels may be Chinese or contract field
names. Unlabeled or ambiguous instructions require an explicit interpretation; this
compiler does not infer unstated requirements. The source survives in the revisioned
Intent, while each downstream target receives only its applicable constraint fields.
The existing Story Design validation, approval and activation lifecycle still applies.

Scene capability selection produces ordered Skeleton, Dialogue, Action, Interior,
Description, Transition and Integration slots as needed. Dialogue and Interior slots
carry actor-local knowledge. The Draft and Revision contracts require complete slot
coverage and exact deterministic prose integration. A revision retains the frozen
contract, identifies changed slots and reruns the existing Review, Quality and Actual
reconciliation chain. Voice contracts distinguish Book, Narrator, POV, Character,
Dialogue and Genre layers; current drift checks prove explicit textual constraints,
not literary voice quality. These are capabilities within governed generation, not a
fixed population of autonomous specialist Agents.

Book ControlPolicy has AUTO, REVIEW_MAJOR_DECISION, REVIEW_PLAN, REVIEW_CHAPTER,
REVIEW_REALITY_COMMIT and MANUAL_DIRECTOR modes. Immutable per-frontier policy bindings
and versioned operator decisions govern the same production path. Decisions bind an
exact candidate and policy, are audited through the Command Kernel, and never act as
quality waivers. Workers cannot approve themselves. The supervisor reports the pending
boundary and resumes the existing operation after approval. Rejected Scene contracts
use the planning runtime's bounded candidate repair ledger; unrelated upstream plans
and accepted history are preserved.

Book read APIs expose revision-bound Reality, world/character/relationship views,
epistemic and reader knowledge, obligations, role Context and bounded accepted-event
Why traces. World Reasoner, Director, Character Reasoner, Scene Planner, Dialogue/Action
Writer, Continuity/Quality Judge and Observer projections share Context policy
intersection, actor/entity scope, deduplication and budget enforcement. A projection
and a candidate score are not evidence of real reader response or external-model quality.

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
the Narrative Reality revision, audit and outbox evidence. Reader and recap work follows asynchronously and remains
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

ChapterGroup now requires only positive ordered bounds at the domain boundary. Maximum
and preferred execution lengths belong to immutable, project-selected policy frozen per
Book run. ReaderProxy score bands and issue thresholds likewise belong to their own
versioned policy, frozen at admission and replayed unchanged after project policy edits.
Both configuration paths use governed commands, PostgreSQL integrity, trace, audit and
outbox evidence. Their numeric defaults are not universal narrative invariants.

A single-chapter execution window still requires every chapter-function row constraint.
Its reader-experience homogeneity comparison reports `NOT_APPLICABLE` with one
observation; this does not establish diversity or narrative quality. Comparisons across
multiple rows retain their blocking homogeneity checks.

Independent relationship/thematic trajectory portfolio activation remains unimplemented;
current character/Arc contracts and accepted relationship projections do not establish
that capability. It requires explicit design review rather than promotion of generic
plan fields into a second Authority.

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
