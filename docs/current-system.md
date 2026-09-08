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

## Generated Foundation formation

The existing Formation API accepts either six exact qualified layer references or one
`creative-brief-v2` asset and a frozen `formation-generation.v1` policy. The latter
uses Story Formation RuntimeJobs to generate Creative Foundation, Theme, Ending,
Reader Promise, World and Character candidates through the governed Planning
Provider path. Independent semantic diagnosis and bounded repair precede Story
Design approval/activation; Book Design then validates the exact six-layer lineage.
`AUTO` is explicit policy authorization, while `REVIEW_PLAN` waits for the existing
approval commands. Generated assets remain proposals until their owning Authority
activates them. Foundation activation is never chapter acceptance or narrative history.
The bounded creative-search baseline selects the first independently qualified branch
and retains the alternatives; it does not claim a literary ranking. Only the selected
branch is approved/activated; alternatives retain qualification evidence without becoming
active Foundations. World depth follows
the current story need and includes deferred dimensions; generated voice anchors are
part of character/creative inputs. Scripted Formation execution proves wiring only.

The creation-input coordinator invokes existing Content commands for explicit runtime
policies and empty genesis, then the existing Book Opening command. It does not
create chapter-zero acceptance. Book Design activation projects the bound cast into
its existing planning trajectory artifact. `chapter.style_policy.compile` derives a
source-bound policy from the exact Creative Foundation and cast, including original
voice examples. Its frozen policy enables `scene-realization-composition.v2`: one
whole-chapter generation call receives distinct scene craft tasks and actor-scoped
voice inputs; targeted revision consumes evidenced diagnoses. Slot concatenation is
serialization only, not evidence of narrative integration or voice quality. Frozen
styles without the new policy retain the v1 contract.

## Scoped worker approval and local Codex execution

Formation claim and execution resolve the same configured Book worker Principal while
retaining the initiating operator and decision actor. The worker role has only the
execution permissions it needs. `AUTO` approval is a separate authorization bound to
the project, Book, Formation, action, policy and exact candidate; it is not a worker-wide
approval grant. Manual Foundation stages persist `WAITING_APPROVAL` and resume the same
frozen task after an explicit decision without consuming a technical retry or generating
a replacement candidate.

The production Provider registry includes the local Codex CLI as an ExternalEffect
backend. Its frozen route records the executable, model, reasoning setting, configuration
identity, structured output contract and isolated process/receipt directory. The process
uses an environment allowlist and has no cross-Book resume state. `ACCOUNT_ENTITLEMENT`
uses the existing budget lifecycle with finite call and token ceilings; observed terminal
usage settles after execution while unavailable monetary cost remains `UNKNOWN`. These
controls do not turn post-call usage into an exact pre-call remote token hard limit and do
not permit silent rerouting to another model, account or billing method.

## Governed corpus works and Book knowledge isolation

Source Import represents a collection as versioned `SourceWork` and ordered `SourceUnit`
identities over existing AssetVersion, Source and object-store boundaries. Governed
classical-corpus profiles parse catalogue-ordered HTML and explicitly shaped JSON,
preserve source locators and original-to-normalized hashes, and keep raw text outside
generation Context. Repository availability and parser reconciliation do not establish
authoritative-edition completeness or publication rights.

Every Book freezes one Knowledge access policy. `PROJECT_DEFAULT` retains legacy project
selection, `ALLOW_ONLY` admits only the exact listed KnowledgeCard AssetVersions, and an
explicit empty `DENY_ALL` never falls back to project-wide cards. The same policy identity
is carried through Planning, Context selection, Draft, Review and Revision, preventing
comparison groups from sharing cards through cache, summary or an upstream plan.

## Production mechanism choices

The comparison reads executable workflows, enabled prompt sections and postprocessors
at [InkOS 0910483](https://github.com/Narcooo/inkos/tree/091048383f411eb99948a8764f42b6fd13006f9b)
and [bishu-novel 5f074b5](https://github.com/alikon-art/DeterminFlow-Plugins/tree/5f074b5a887a7e74a61d00206abb99c107b786c2/plugins/bishu-novel).
[DeterminFlow 49a5c92](https://github.com/alikon-art/DeterminFlow/tree/49a5c9273cc152446a32474c9ac577316074f8e8)
is used only to resolve extension provisioning, workflow loading and enabled/scoped
prompt assembly in `web_server.py` and [scoped prompt builder](https://github.com/alikon-art/DeterminFlow/blob/49a5c9273cc152446a32474c9ac577316074f8e8/src/prompts/sub_agent_prompts.py).
These are design inputs, not runtime dependencies or Authority. No external source,
prompt, resource or fiction expression is incorporated.

| External executable mechanism | Problem it addresses | Decision and native production consumer |
|---|---|---|
| Bishu [build workflow](https://github.com/alikon-art/DeterminFlow-Plugins/blob/5f074b5a887a7e74a61d00206abb99c107b786c2/plugins/bishu-novel/resources/workflows/build/definition.json), world prompt sections and world rendering | An idea needs rules, resources, power and information constraints | ADAPT: Formation RuntimeJobs call `foundation_generation.py`; progressive World candidates declare needed/deferred dimensions and compiled rules. Story Design qualifies/activates them; Book Opening and World Preparation consume exact bindings. Fixed six-stage world expansion is REJECTED. |
| Bishu character skeleton/deep/voice nodes and enabled character prompts | Decorative cast and arbitrary voice labels | ADAPT: generated cast includes narrative function, desire, belief, fear, contradiction, relationships, behavior and voice anchors. Book Design projects its bound cast into the existing trajectory artifact; `chapter.style_policy.compile` passes source-bound voices to scene craft tasks. |
| Bishu story-plan and style-profiler | Conflict cannot sustain escalation or an ending; style is only adjectives | ADAPT: Creative Foundation, Theme, Ending and Reader Promise receive independent semantic diagnosis/repair before activation. Operational narrator/POV/genre constraints and original examples become the frozen style policy. Reference materials remain abstract approved inputs; raw reference prose cannot enter Draft. |
| Bishu MVP world → director → settler; `we_post.py` | Separate possible world consequences from narrative selection | KEEP native `src/novel_forge/modules/story_planning_runtime/world_preparation.py`, World Dynamics, Director evaluation and working projection. Provider produces bounded candidates, deterministic rules reject invalid paths, Planning activates only selected future work. Temporary external world cache is not adopted as Canon. |
| Bishu outline volume/near-term workflows | Distant planning is too detailed; actual events diverge from outline | KEEP typed Book/Arc/Volume/ChapterGroup/Chapter/Scene planning, accepted checkpoints and `book_replan`. Supervisor regenerates affected future dependencies; completion cases inspect ending, promise, theme and trajectories separately from execution's chapter bound. |
| InkOS writer Chapter Memo and author controls | Plans list events without explaining how or why to write them | KEEP the governed Memo node: motivated choice, cost, reader expectation, emotion, information and ending change feed Draft. Author changes remain versioned Intent/Planning commands, with no tool write access to Canon. |
| InkOS [memory retrieval](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/utils/memory-retrieval.ts); Bishu world trimmer and `trimmer_post.py` | Too much allowed but irrelevant material, or missing necessary facts | KEEP native protected/task-relevant Context ordering, bounded PostgreSQL lexical/structured discovery and optional governed semantic reranking. Accepted sources, entity/relationship/obligation links and incremental projections supply continuity. REJECT per-query whole-index replacement, silent retrieval failure and blanket character deletion. |
| Bishu MVP skeleton/dialogue/action/interior/description/transition/integration prompts | Different scenes need different craft, while stitched fragments lose continuity | ADAPT as `scene-craft-tasks.v1` in `scene-realization-composition.v2`: distinct objectives and scoped inputs within one whole-chapter call; integration addresses junctions, causal carryover and repetition. Simple scenes omit irrelevant tasks. Separate fixed writer Agents/calls are REJECTED. |
| Bishu polish workflow and professional-polisher dimensions | Generic polishing changes facts or rewrites everything | ADAPT into diagnosis-driven editing targets for dialogue, pacing, spatial clarity, explanation, voice and junctions. Existing bounded Revision consumes locations, preservation constraints and verification criteria; no fixed three-pass rewrite or genre-independent punctuation bans. |
| InkOS [chapter review cycle](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/pipeline/chapter-review-cycle.ts) review/revise/snapshot loop | A revision regresses; earlier candidates and blockers disappear | ADAPT bounded retention with immutable prose and review lineage. Selection separates workspace wrapper from actual prose, carries unresolved diagnoses, and requires checked improvement/preservation. REJECT absent-score-to-zero fallback and score-only acceptance. |
| Bishu Observer/Arbiter and `local_archive.py`; InkOS post-write settlement | Intended events or character assertions are mistaken for facts | KEEP final-prose extraction, independent support review, deterministic reconciliation and atomic Book acceptance. Background events use approved rule/decision provenance. REJECT model-authorized direct file/state merges; disclosure, belief and objective history remain separate. |
| Hooks/debt tracking and post-write feedback in both systems | Promises stagnate and the next chapter ignores actual outcomes | KEEP accepted Obligation/trajectory events, Reader proxy's explicit evidence ceiling, accepted Arc/ending checkpoints and scheduled longform recap → future PlanChange. Operator semantic helpers alone are not evidence of autonomous feedback. |
| InkOS production Skill bindings; Bishu workflow-scoped prompts | A declared skill is not actually loaded, or every node receives everything | KEEP versioned Capability Packs, governed Provider admission, role-specific projections and existing read queries. Formation assets, frozen creation sources, Memo, candidates, diagnostics and acceptance are exported by the native creation runner; missing bindings fail instead of silently disappearing. |

The runnable sample is an engineering control-flow experiment. Transport scripts do
not establish autonomous creative judgment, natural voices, calibrated semantic support,
real reader preference or long-term quality. Whole-book acceptance, human editorial
review and production qualification retain their separate evidence requirements.

## Creative execution and prose evidence

The selection node projects the immutable review of its selected prose. If a proposed
revision does not establish improvement or preservation, downstream gates retain the
original review and its unresolved issues; they do not reuse the rejected prose's
rereview. Canon also reviews observed Arc/Realization claims against the final text.
An arbitrary supersession identifier cannot authorize a contradiction: it must resolve
the exact accepted event of the same entity in the frozen Book boundary.

Candidate comparisons identify the immutable prose source separately from the workspace
version that carries it. Repeated retention preserves the same source, review, score and
blocking diagnoses; missing comparison evidence fails explicitly. Unresolved diagnoses
remain in a carried ledger across re-reviews, retaining their prior-candidate locations.
Revision and re-review consume that ledger as well as newly located issues. Omission
from a later issue list neither resolves a blocker nor turns its old quote into evidence
about the new prose. Candidate ranking does not grant acceptance; Quality and Book
acceptance retain their independent gates.

Book acceptance rechecks and locks selected asset versions inside its existing UoW.
Migration 0119 adds an insert guard binding current model-backed acceptance to the
same final prose hash, grounded Canon and Quality. Already accepted rows are unchanged;
unaccepted legacy model output needs new grounded evidence. Governed background facts
retain their approved decision/rule provenance separately from prose evidence.

The existing Chapter run query supports `include_workspace=true`. It exposes immutable
inputs/Memo, candidates, diagnoses, revision comparison, extraction/support/approval,
gates, attempts, acceptance and the exact accepted versions available to the next
chapter. This is a read projection; it grants no mutation permission.
The workspace's `creation_sources` resolves the command's frozen Book input snapshot,
including exact Foundation and policy versions, rather than the Book's latest pointer.

The existing Chapter Memo node invokes the governed Provider path from a frozen
ExecutionIntent. Its creative guidance describes motivated choices and costs, POV and
voice, scene conflict and information release, emotional movement and the ending change.
Draft receives this guidance and the Memo fingerprint as suggestions, not Canon.
Provider execution receipts remain on the immutable Memo for audit. Its governed
writing projection excludes those receipts; they are not narrative material and do
not consume the chapter's writing Context budget.

Current Provider reviews return located diagnoses, constraints, repair goals, preservation
requirements and acceptance criteria. Revision consumes these diagnoses. Re-review records
explicit checks; omission of an issue or a higher score does not establish resolution.
Candidate selection preserves the earlier candidate when no checked improvement exists or
required content regresses. Aesthetic suggestions cannot alone become objective blockers.

Current Provider Canon extraction consumes final prose without inheriting Writer assertion
or old revision state fields. Claims bind literal Unicode code-point spans, quotes and the
candidate text hash. Canon proposal uses a separate Provider support review; unsupported,
uncertain or incomplete extraction blocks reduction. Matching text is necessary evidence,
not a deterministic proof of semantic entailment. Successful no-change extraction requires
an explicit coverage explanation and support review. Governed background events retain
rule and decision provenance instead of fabricated prose evidence. Edited claims require
re-extraction. These checks establish contracts; scripted runs do not prove literary quality.

For a prose-grounded obligation payoff, the Provider supplies the literal references
`$FINAL_CANDIDATE` and `$CURRENT_CLAIM`. Grounding binds the actual frozen candidate
and claim; it rejects invented or cross-book Authority IDs. Acceptance derives a typed
Canon source locator from the Canon AssetVersion, state kind and ordinal, retaining the
grounded claim for replay. This locator identifies the source claim, not a separate
accepted event. Causal Debt keeps its stricter prerequisite and exact accepted-event
validation. Already accepted historical payloads are not rewritten.

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
| Source and MKAOS Authorities | source/Corpus lineage, frozen rights and purpose admission, abstractions, knowledge decisions and packs | draft prose or accepted story facts |
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
| World transition / Candidate Future | causal proposal | deterministic rules constrain candidate evolution; only Book-accepted observed or governed background effects advance reality |
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

Native Book supervision requests world preparation before Chapter planning. The
Planning operation freezes the approved Foundation set, current Intent, Book input
snapshot, accepted frontier, world rules, approved Character definitions, active Planning
window, ControlPolicy and bounded production policy.
Before the first acceptance, the baseline is a content-bound Foundation projection;
there is no synthetic chapter-zero acceptance. Subsequent rounds bind the exact
Narrative Reality revision.

`world_candidates.generate` and `world_candidates.evaluate` use the existing Planning
Capability Pack, Context admission, Provider Effect, receipt and budget boundaries.
The first stage supplies proposed transitions and preparation alternatives; the second
supplies Director dimensions and reasons. Deterministic rules reject unsupported
identities, causes, epistemic bases, quantities and times before selection. Candidate,
path, step, chapter-window, world-time and Context limits are frozen policy. A reasoned
`NO_OP` or `DEFER` is a valid result. Exhausted legal alternatives produce `BLOCKED`.
Model explanations remain hypotheses; formal checks cover the modeled predicates only.
The explicit `planning.causal.propose` API remains a manual proposal input.

Only the selected preparation path creates commitments. Its steps bind dependencies,
future Chapter windows and expected effects. Private preparation uses the Narrative
State reducers but has no accepted authority. A target may cite its own declared preparation
events: the complete path graph is validated before target eligibility, with exact historical
references and path-local scope. Provider array order does not determine dependency order.
Native planning resolves accepted preparation commitments before generating a fresh
portfolio. Due steps retain their original action/path identity; accepted event mappings
prevent duplicate execution, and fresh `NO_OP`/`DEFER` cannot discard them. Continuation
records execution, waiting, deferral, blocking and cancellation decisions against the new
frontier. An exact accepted effect from another event can support an unexecuted step,
with a separate reuse receipt rather than a fabricated execution record.
Planning completion cannot discharge a
commitment: repayment requires an exact accepted predicate event. Approved replacement
Intent can retire unfulfilled preparation while preserving its original decision and
accepted history. An expired unfulfilled window produces an accepted cancellation;
renewal creates a new commitment linked to that retirement event. Target retirement is
separate from predicate repayment: an already fulfilled preparation retains its payoff
receipt when the target expires or is cancelled, and its terminal target is no longer scheduled.
Selected on-camera events are assigned to one Scene and carried in a frozen public execution
contract. Observer must find the exact effects and local dependency identity in the final
prose before Book acceptance records the original action/step mapping. Its observed causal
transition must match the scheduled actor, time, effects and modeled prerequisites; the
observed action description is preserved. Missing or different observation cannot be
filled from the plan. Observer-only validation constraints remain outside Writer and
Quality text views, including the metadata of already accepted visible events. Missing execution
leaves the step pending; a successful chapter alone cannot complete it.

Selected background events enter Canon reconciliation with a governed source origin
that binds the source, generation, evaluation, selected transition and acceptance
policy. They carry no fabricated prose span. Book acceptance checks that the complete
background payload still equals that decision, then commits background and observed
facts in the same acceptance transaction and Reality lineage. Major changes retain
Canon and ControlPolicy approval gates. Rejecting the chapter leaves no background
fact. An accepted event cannot be withdrawn by a later Director choice.

World and Director Context can inspect their governed source projection. Writer and
Chapter Context exclude private world bindings and undisclosed background facts,
including previous-outcome and retrieval summaries. A planned disclosure references
an existing accepted event; only its accepted presentation changes the selected
character or reader audience. It does not create the objective event again. Disclosure
resolves exact historical occurrences through the accepted event index, even after the
entity's current state advances. Historical occurrence and current assertion are distinct:
a superseded state cannot be presented as a current assertion. Versioned audience policy
selects scalar fields and an explicit mode; mixed audiences use separate records.
Character-only disclosure does not expose hidden content to Reader-facing production.
Misdirection and withholding cannot grant new objective Character Knowledge, even when
Observer proposes a KNOWN record alongside that presentation.
Partial presentation cannot expand into the full fact through Context or retrieval.
Scene epistemic projections retain explicit Scene and Character scopes. Hidden
preparation commitments remain outside the Reader view.

Explicit batch-local event names and dependencies order same-chapter acceptance.
Each event validates against the frozen baseline plus its verified ancestors through
the same reducers. Cycles, unknown references, future causes, unordered writes and
cross-character knowledge fail before the atomic commit. Compiled rules are also checked
against the combined final projection, including effects outside each event's ancestor set.
Local names resolve to exact
accepted event identities in Why traces. Independent simultaneous events remain legal;
travel uses the affected entity's clock. Retry reuses frozen Context and confirmed
Provider outputs, and ChapterGroup recovery consumes a committed Book acceptance
whose response was lost. New generation contracts are versioned separately from
historical frozen commands, which retain their original stage set. An unfinished
directed repair resumes its exact child command from the retained failure report;
the parent generation receipt does not substitute for Planning acceptance.

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

## Corpus Foundation

Source Authority owns Corpus metadata through `source.corpus.commit`, the Source worker,
`SourceAuthorityRepository` and the existing Command Kernel/UoW. MKAOS remains the owner
of downstream abstractions and knowledge decisions. Corpus does not create another
import executor or knowledge policy engine: bounded metadata batches use the existing
`authority_source_import_job` with `mode=FOUNDATION`; Attempts, leases, fences, failures
and terminal replay remain Command Kernel records.

The immutable lineage is Source → DatasetManifest/acquisition snapshot → source-local
book identity → Edition → purpose membership. A source's external identity and purpose
are fixed. Source metadata changes create snapshots; rights declarations and snapshots
form explicit parent chains with monotonically ordered revisions. Edition identity is
bound to the source snapshot, work key and edition key, independently of its checksum.
Identical checksums do not deduplicate works or assert cross-source equivalence.

Rights declarations separate the dataset license from underlying-work authorization and
its evidence, copyright boundary, allowed/denied purposes and unresolved restrictions.
Declarations explicitly cover all works in the snapshot; heterogeneous or unverified
work rights must remain unresolved rather than inherit the repository's software license.
Production-reference admission denies UNKNOWN, CONFLICTING and RESTRICTED rights, any
unresolved restriction, purpose mismatch, retirement and changed rights requiring review.
BENCHMARK sources cannot acquire production-reference membership. PostgreSQL checks,
composite foreign keys, immutable-row guards and admission guards enforce these boundaries.

An ALLOW grants only the declared catalog/reference purpose; it never grants raw prose
entry to a model. Corpus output assets are ineligible for generation Context even if a
caller relabels their logical kind. Source abstraction, MKAOS and Context admission remain
mandatory. Rights changes neither rewrite historical decisions nor upgrade old Editions;
new use requires an explicit declaration/snapshot and a new admission. Retirement is an
append-only record, preserving every historical identity and decision.

Each import freezes one snapshot and at most 100 metadata entries within 256 KiB. Identical
snapshot/batch keys resolve the same Operation; changed payloads conflict. Source-scoped
locking and natural-key constraints serialize competing revisions and duplicate entries.
Edition records, admissions, allowed memberships, result asset, import outcome and outbox
evidence commit together under the current fence. Recovered committed outputs are reused
before rechecking mutable upstream state; failed transactions leave no partial catalog.
New rights do not change the meaning of an already committed result. Queries use bounded
keyset pages; current rights/snapshot lookup uses a revision index.

The manifest's format, external version, checksum and versioned adapter profile are the
extension contract. Acquisition receipts are explicit operator declarations unless bound
to an existing Source repository snapshot; registering metadata performs no download or
content verification. Subsequent adapters must retain that exact acquisition and Edition
identity when supplying bytes to the existing Source pipeline. Parsing/normalization,
chapter segmentation, deduplication/equivalence, embeddings, Deconstruction and corpus-scale
knowledge extraction are not implemented by this foundation. No Corpus metadata is a
Provider, content-quality or production qualification claim.

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

### Bounded Chinese creation pilot

The native creation runner prepares isolated Project/Book records through existing
Commands, freezes the pilot policy in Book runtime policy, and locates Formation and
Opening by their original idempotency keys on resume. Confirmed outputs remain owned
by the existing runtime. A project lifetime Provider cap spans Formation, Opening,
chapters, revisions and retries; an explicit total authorization is required for paid
execution. Configuration checks do not call a model.

The Chinese pilot policy requires 2000–3500 Han ideographs per chapter under
`HAN_CHARACTERS_V1`, independently of model scores. It is separate from the small
English engineering smoke. The workspace and exports resolve committed Acceptance
through its immutable ChapterOutcome, then verify exact Candidate/Quality/Review/Canon/
Context/Memo bindings and hashes. Historical Quality targets remain in the workspace.
Partial exports retain completed files and explicit errors. These contracts establish
engineering behavior; real creative effects require actual authorized text and receipts.
