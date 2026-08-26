# WP-QUALITY-PROOF-01 Canonical Quality Qualification Design

Status: APPROVED FOR IMPLEMENTATION

Date: 2026-08-26

Effective base SHA: `476090195e6718d9a2585f5b2ddd51dc88efd415`

Effective migration head: `20260825_0100_hierarchy_closure`

## 1. Decision summary

WP-QUALITY-PROOF-01 extends the existing Chapter Quality, Reader Calibration,
Book Followup, Narrative State, Longform Narrative, Content Authority and
Production Execution seams. It does not create another Quality Authority,
Judge runtime, Provider runtime, accepted-history store or long-term memory.

The qualification compares each accepted Canonical revision with the
first-draft candidate produced by the same Chapter Runtime. The two candidates
therefore share the same qualified Foundation, active plans, Narrative
Realization, accepted boundary, Context policy, Provider/model family and
chapter goal. The controlled difference is the downstream narrative-control
path:

```text
Baseline:  first draft candidate
Canonical: review -> revision -> independent re-review -> quality -> acceptance
```

This comparison is deliberately narrower than a reduced-context ablation. It
tests whether the currently wired editorial control loop improves the actual
candidate without creating an ungoverned generation path. A future campaign
may test Context or Realization ablations, but this WP will not claim that this
baseline isolates every Novel OS mechanism.

The real-provider campaign is one Book, one bounded Volume slice, two
consecutive four-Chapter ChapterGroups and eight accepted Chapters. The first
group makes post-Chapter Reader/Recap evidence available before the second
group is planned. The campaign must stop after Chapter 8.

## 2. Evidence vocabulary

The system keeps the following claims separate:

```text
Engineering Correctness
Narrative Correctness
Automated Judge Evidence
Editorial Quality
Human Preference
Reader Proxy Evidence
Real Reader Outcome
Longitudinal Quality
Commercial Outcome
```

Quality qualification has three non-collapsible layers:

- `L1_HARD_CORRECTNESS`: deterministic or Authority-backed Canon, identity,
  timeline, world rule, knowledge boundary, causality, Narrative Realization,
  required transition, obligation and accepted-history checks.
- `L2_EDITORIAL_QUALITY`: attributable automated editorial evidence and blind
  human comparison. Raw scores remain dimension-level observations.
- `L3_READER_LONGITUDINAL`: Reader Proxy trends plus accepted-history momentum,
  promise/payoff, repetition, Arc and bounded Volume evidence. Reader Proxy is
  advisory and is never narrative truth.

No aggregate score can erase an L1 severe failure. Chapter release gates and
campaign qualification are separate decisions: an internally releasable
Chapter with uncalibrated semantic evidence does not imply a qualified
campaign.

Final qualification statuses are:

- `PASS`
- `PASS_WITH_LIMITATIONS`
- `FAIL`
- `NOT_PROVEN`

Campaign lifecycle additionally includes `WAITING_HUMAN_EVIDENCE`. A campaign
in that lifecycle has final qualification status `NOT_PROVEN`; it is never
silently promoted. One valid human evaluator yields
`HUMAN_EVIDENCE_LIMITED`. Zero valid human evaluators remains
`WAITING_HUMAN_EVIDENCE / NOT_PROVEN`.

## 3. Canonical persistence and ownership

### 3.1 Quality campaign records

Migration `0101` adds bounded qualification records adjacent to existing
quality evidence, not a new business Authority:

- `authority_quality_qualification_campaign`: immutable manifest identity,
  exact release/migration/provider/pack/profile/budget lineage and lifecycle.
- `authority_quality_qualification_subject`: Chapter or Arc comparison subject,
  exact canonical/baseline AssetVersions and scope.
- `authority_quality_qualification_evidence`: typed L1/L2/L3 evidence binding,
  source AssetVersion/hash and evaluator/provider lineage.
- `authority_quality_qualification_decision`: fail-closed final result and
  limitations.

The application layer uses Command Kernel transactions and immutable Authority
assets for manifests, evidence reports and decisions. Campaign rows are
indexes/state for those immutable outputs, not a second artifact store.

### 3.2 Human blind comparison

The existing Reader Calibration persistence remains the owner of human
preference tasks, pairs and decisions. Migration `0101` extends it with:

- campaign, protocol and evaluation-profile versions;
- evaluator identity class and pseudonymous reviewer identity;
- `CHAPTER` / `ARC` scope, inclusive Chapter range and Arc bindings;
- deterministic balanced ordering metadata;
- `A`, `B`, `TIE`, `CANNOT_JUDGE` choices;
- per-dimension scores, confidence and optional rationale/evidence spans;
- adjudication status and a separate immutable adjudication record;
- blind evaluation-pack AssetVersion/hash and export timestamp.

`REJECT_BOTH` is retired for new protocol versions and remains readable only
for historical rows. The v2 Quality calibration contracts consume the human
records through an explicit adapter; they do not duplicate human truth.

### 3.3 Blind export boundary

Each evaluator receives a separate deterministic pack. It contains only:

- opaque campaign/evaluator/pair tokens;
- `Candidate A` and `Candidate B` text;
- Chapter or Arc scope label without internal AssetVersion IDs;
- the frozen evaluation protocol and dimension rubric;
- allowed preference choices, confidence and rationale fields.

It must not contain or infer:

- Canonical/baseline identity;
- internal AssetVersion, Operation or branch identity;
- Provider/model, Prompt/Skill/Pack identity;
- automated Judge output, Quality gate or system score;
- randomization seed or the private pair mapping.

Pack export runs a fail-closed leakage scan, stores a content hash and writes
the private pair mapping only to PostgreSQL Authority. Ordering is
deterministic from a campaign secret and reviewer identity, but balanced so
each reviewer sees four Canonical-left and four Canonical-right Chapter pairs.
The second reviewer receives the complementary ordering. Arc ordering is also
balanced when more than one Arc pair exists.

## 4. Human protocol

The target is two independent human evaluators. Each evaluator completes eight
Chapter comparisons in story order and, after reading the same complete
sequence, at least one Arc-level comparison for the primary Arc. A second Arc
comparison is required only if the frozen campaign contains a second evaluable
Arc.

Evaluators cannot see each other's decisions before submission. Required
dimensions are:

- overall preference;
- readability;
- character credibility;
- scene effectiveness;
- tension and momentum;
- emotional impact;
- prose quality;
- continuity;
- payoff satisfaction;
- desire to continue reading.

Each dimension is scored on the frozen ordinal scale while overall preference
uses `A`, `B`, `TIE` or `CANNOT_JUDGE`. The record includes confidence,
optional rationale and evidence spans. Disagreement is preserved. Adjudication
may explain disagreement but does not rewrite either raw decision and is not
called Ground Truth.

Two evaluators over this bounded sample remain `BOUNDED_HUMAN_EVIDENCE`. They
cannot statistically calibrate a Judge.

## 5. Calibration v2 convergence and Judge independence

The old `quality.golden_sample`, `quality.human_decision` and calibration-v1
operation surface is removed from current registration. Historical immutable
assets remain readable. New work uses only explicit v2 roles:

- Generator execution
- Reviewer execution
- Editorial Judge execution
- Human blind evaluation
- Optional adjudication
- Reader Proxy evidence

The v2 pairwise preference contract supports `TIE` and `CANNOT_JUDGE`, scope,
dimension scores, protocol version and evaluator class. Calibration diagnostics
add pairwise agreement, weighted ordinal agreement where defined, rank
correlation where sample size permits, false-positive/false-negative counts,
confidence bins, position bias and preference stability.

Every report records generator, reviewer and Judge provider/model/profile/prompt
hashes plus an independence relationship. Same-provider or same-model evidence
is labeled `DEPENDENT_SAME_PROVIDER` or `DEPENDENT_SAME_MODEL`. It may remain
useful automated evidence but cannot independently establish editorial quality.
Insufficient sample size yields `UNCALIBRATED` and `BOUNDED_EVIDENCE`.

## 6. Hard correctness

The L1 report consumes exact accepted evidence and checks:

- committed Book Acceptance and immutable accepted lineage;
- ChapterOutcome v3, StoryState, Canon and accepted cursor agreement;
- deterministic continuity/conflict reports for identity, timeline and world
  rules;
- knowledge-boundary and protected-context compliance;
- Narrative Realization event coverage and forbidden-change compliance;
- required state transitions and causal change evidence;
- Arc Actual/Progress/Outcome/Checkpoint validity;
- obligation creation, maintenance, due/payoff/violation lifecycle;
- absence of accepted-history mutation or future-state contamination.

Missing required evidence is `NOT_PROVEN`; a contradictory or severe invariant
failure is `FAIL`. L2/L3 results cannot offset either result.

## 7. Longitudinal evidence

The accepted Quality projection is upgraded to consume ChapterOutcome v3. Each
compact accepted observation binds the exact Acceptance, outcome, plan,
Realization, accepted draft, quality report, StoryState, Canon and provider
evidence. Full prose is discarded after bounded feature projection.

Momentum evidence distinguishes activity from causal progress:

- planned event coverage and actual causal progression;
- irreversible state change;
- goal progress and obstacle escalation;
- protagonist decision density;
- antagonist response/pressure;
- stagnation and ending propulsion.

Promise/payoff evidence reuses accepted Narrative Obligation state:

```text
CREATED -> MAINTAINED -> ESCALATED -> DUE
        -> PAID / PARTIALLY_PAID / OVERDUE / ABANDONED
```

It reports cadence, setup-payoff latency, overdue debt, false promise, repeated
delay and clustering without inventing a second ledger.

Repetition evidence combines accepted structured semantics with bounded text
features. It separately evaluates plot/conflict-solution pattern, scene
function, chapter structure, emotional beat, dialogue behavior, information
recap, protagonist reaction, antagonist response, hook pattern and prose/style
repetition. Lexical similarity is evidence for prose repetition only and cannot
stand in for semantic fatigue.

Arc evaluation consumes causal event coverage, protagonist/antagonist
interaction, Arc progress/checkpoints, obligation payoff and character change.
Bounded Volume evaluation consumes Arc interaction, long-promise progress,
payoff distribution, fatigue/trust trends, accumulated state evolution and
ending reachability. Neither is a mean of Chapter scores.

## 8. Reader Outcome and Recap

Reader Outcome retains the eleven existing dimensions and is explicitly
classified `READER_PROXY_ADVISORY`. Each accepted Chapter produces a versioned
Reader state transition. The Book Followup coordinator resolves actual prior
Reader reports, qualification status, disagreement, position bias, OOD/drift
and recent trend instead of hard-coded values.

The reachable chain is:

```text
Accepted Chapter
-> Reader Proxy Outcome
-> longitudinal Reader State
-> Recap / trend evidence
-> bounded future recommendation or Replan request
-> owning Planning/PlanChange approval gate
```

An unqualified Reader Judge may create an advisory future recommendation with
`activation_allowed=false`; it cannot mutate Canon, StoryState, accepted plans
or active future plans. Actual plan activation continues to require the owning
Authority and applicable human/calibration gates.

## 9. Campaign manifest and budgets

The scripted dry-run validates all contracts using scripted providers before
any real-provider call. After full regression and migration/recovery proof, the
real campaign freezes:

- exact release SHA and migration head;
- PostgreSQL database and object-store namespace;
- Provider/model routes and reasoning profiles by stage;
- Capability Pack versions, artifact hashes and Prompt/Skill hashes;
- Foundation, BookDesign, Planning and Narrative Realization lineage;
- Context, Quality and Reader profiles;
- two ChapterGroup ranges `[1,4]` and `[5,8]`;
- one primary Arc completion target and optional secondary Arc progress target;
- per-stage token limits, total input/output token ceiling, estimated cost
  ceiling, provider-call ceiling, retry ceiling and wall-clock deadline;
- a pre-freeze execution-headroom floor derived from settled Budget Authority
  reservations, with every `model.invoke` dispatch counted independently of
  capability naming;
- stop boundary `accepted_through_chapter == 8`.

Budget exhaustion, route drift, pack drift, dirty checkout, migration drift or
attempting Chapter 9 fails closed. Cost is reported as measured usage and
estimated cost unless the Provider supplies billed cost.
Terminal engineering qualification failures produce an overall `FAIL` record
while L1/L2/L3 remain `NOT_PROVEN`; they are not evidence that narrative quality
itself failed.

## 10. Recovery and idempotency

Campaign admission, pair creation, pack export, decision recording,
longitudinal projection and final decision are idempotent by stable frozen
identity. Tests inject failure after Provider receipt, after candidate
materialization, after acceptance, after pair mapping and after pack export.
Recovery reuses immutable receipts/outputs and never duplicates Provider calls,
human decisions or accepted Chapters.

## 11. Documentation cleanup

Current architecture/docs will describe the L1/L2/L3 evidence model and bounded
qualification semantics. Exact-SHA historical qualification records remain
unchanged except for index labels.

The following obsolete current-runtime surfaces are removed or explicitly
retired:

- calibration v1 operation registrations and dead rubric helper;
- hard-coded 300-Chapter campaign contract/runner/configs;
- dead 400-Chapter completion driver and tracked generated campaign output;
- dead Quality Eval / Long-chain Proof UI routes that call absent endpoints or
  imply fixture scores prove quality.

Git history preserves these artifacts; they are not retained as current proof.

## 12. Acceptance and report boundary

Engineering completion requires focused/unit/schema tests, PostgreSQL
integration, fresh migration, upgrade migration, recovery/idempotency,
composition-root checks and the current full regression. Only then is the exact
Runtime SHA frozen for real-provider execution.

The campaign report must include all required lineage, provider usage/failure,
L1/L2/L3 evidence and limitations. It must state:

> This qualification provides bounded quality evidence for one exact-SHA,
> eight-Chapter campaign. It does not prove autonomous million-word premium
> fiction, real-reader outcomes, commercial success or production readiness.

If the blind packs are exported but human decisions are incomplete, the
engineering WP may be delivered with campaign lifecycle
`WAITING_HUMAN_EVIDENCE`, final qualification `NOT_PROVEN`, and no simulated
human replacement.
