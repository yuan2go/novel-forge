# Autonomous Novel OS Capability Map

Updated: 2026-08-01  
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`  
Audited HEAD: `aa991b53039cdf2e4e7911d4483052b9a6a752a1`

Status in this document is evidence-based:

- **Implemented**: substantial code path exists;
- **Fixture-proven**: deterministic/mock integration proves protocol behavior;
- **Partial**: important path exists but the business loop is incomplete;
- **Design/Foundation**: schema, migration, contract or first slice exists;
- **Unproven**: no current real-world proof;
- **Blocked**: current HEAD or deployment condition prevents a valid completion claim.

A UI page, API route, schema, fixture or design document alone is not a completed capability.

## 1. Current Capability Summary

| Capability group | Current state | Strongest evidence | Main gap |
|---|---|---|---|
| PostgreSQL Command Kernel | Implemented / fixture-proven | DB constraints, Operation/Saga/Attempt tests | production load and recovery drill |
| Chapter Authority | Implemented / fixture-proven | 18-node PostgreSQL Saga | real Provider and editorial quality |
| Canon and Story State | Implemented foundation | proposal/approval/update and 9 snapshots | long-horizon semantic accuracy |
| Quality and Review | Implemented foundation | 5 groups, 41 dimensions, aggregate gate | Judge calibration and real model evidence |
| Book Authority | Implemented foundation / fixture-proven | persistent coordination and child delegation | autonomous whole-book progression |
| Provider v2 | Implemented protocol | registry, route, query/cancel/callback contracts | real composition, billed cost and production proof |
| Long-form | Partial | Reader Outcome/Recap/Plan proposal contracts | real 100/300 chapter and million-word proof |
| Source and MKAOS Authority | Blocked pending integrity verification | current imports/migration registrations | confirm all target modules/migrations/tests committed |
| Agent collaboration | Design/Foundation / fixture-proven | frozen scope, work order, candidate graph | complete autonomous Agent Center |
| Web operator product | Partial | broad Next.js console | authentication, browser E2E and guided repair |
| Publishing/platform | Partial | local/manual/generic adapter foundations | official platform and real receipt proof |
| Portfolio/multi-book | Design/Foundation | isolation, scoring and allocation plans | real parallel dispatch and operational proof |
| Production deployment | Blocked/partial | Docker and CI configuration | Authority-only topology and readiness |
| Security/multi-user | Partial | trusted server Principal | HTTP authentication and project RBAC |

## 2. Runtime And Authority Capabilities

| Capability | Status | Code evidence | Explicit limit |
|---|---|---|---|
| Operation Definition registry | Implemented | `modules/command_kernel/`, `storage/authority_repositories.py` | definition deployment governance still requires release process |
| Command admission | Implemented | schema, permission, approval, handler and frozen input checks | full multi-user identity not implemented |
| Idempotency | Implemented | unique key plus Request Digest conflict | production operational policy still needs load proof |
| Operation lifecycle | Implemented | version/status CAS | distributed pressure not proven |
| Saga/dependency graph | Implemented | graph coordination and DB acyclic guard | large dynamic graph scale not proven |
| Attempt/retry | Implemented | active Attempt uniqueness and retry policies | real provider failure distribution unproven |
| Lease/fencing | Implemented | DB lease function, monotonic fencing and stale rejection | multi-worker production load unproven |
| Cancellation | Implemented foundation | cancellation command and effect cancellation | real upstream cancellation unproven |
| Compensation | Implemented foundation | compensation contracts and repositories | end-to-end irreversible action drill incomplete |
| External Effect | Implemented foundation | effect/dispatch/receipt/query/callback/reconcile | real provider/platform proof absent |
| Inbox/Outbox | Implemented foundation | durable tables and recovery operations | production dispatcher topology incomplete |
| Audit/State Event | Implemented | admission and lifecycle evidence | retention/analytics operations partial |
| AssetVersion | Implemented | immutable versions, qualification and output binding | latest business Authority migration integrity pending |
| Blob/Object effect | Fixture-proven | verified local object delivery protocol | remote production object store proof absent |

## 3. Chapter Production Capabilities

| Stage | Status | Current behavior | Limit |
|---|---|---|---|
| Production Preparation | Implemented foundation | resolves frozen ChapterPlan/context/profile assets | deployment/operator workflow proof incomplete |
| Plan materialization | Implemented | validates authoritative ChapterPlan identity and qualification | autonomous ChapterPlan generation is separate and incomplete |
| Context | Implemented | manifest/frozen input/segment equality and source-isolated views | retrieval selection quality needs calibration |
| Draft | Fixture-proven | governed model stage and normalized output | real Chinese prose unproven |
| Review | Fixture-proven | structured review and issues | semantic review accuracy unproven |
| Revision | Fixture-proven | revised DraftVersion and resolved issue codes | real repair quality unproven |
| Re-review | Fixture-proven | independent pass/fail evidence | real evaluator calibration unproven |
| Canon Extraction | Fixture-proven | semantic extraction stage or deterministic fallback | real extraction precision/recall unproven |
| Canon Proposal/Approval | Implemented foundation | versioned proposal and decision-gated changes | operator merge/repair UX partial |
| Canon Update | Fixture-proven | patch plus append-only state snapshots | long-horizon conflicts unproven |
| Structural Quality | Fixture-proven | structural dimensions | calibration incomplete |
| Commercial Quality | Fixture-proven | promise/reward/charm/pressure/hook dimensions | platform/reader calibration incomplete |
| Source/Originality Quality | Fixture-proven | originality, leakage and style evidence | external plagiarism corpus proof incomplete |
| Long-form Quality | Fixture-proven | continuity, promise, arc and repetition dimensions | real long-chain evidence absent |
| Platform Quality | Fixture-proven | format, length and policy dimensions | real platform rule integration partial |
| Quality Aggregate | Implemented | fail-closed five-group fan-in | input evidence can still be fixture/uncalibrated |
| Publish Gate | Fixture-proven | internal release decision | not a real platform permission |
| Export | Fixture-proven | package/blob/effect/receipt protocol | real object and publishing adapter unproven |
| Final Release Gate | Fixture-proven | post-export evidence gate | no real publication proof |

## 4. Book And Long-form Capabilities

| Capability | Status | Current evidence | Remaining gap |
|---|---|---|---|
| Book root admission | Fixture-proven | persistent Book Operation and Saga | real book execution environment |
| Book input freezing | Implemented | BookDesign, BookPlan, production and long-form versions | upstream semantic generator acceptance still partial |
| Sequential chapter cursor | Implemented | reservation and acceptance progression | parallel/group policies need broader proof |
| Chapter child delegation | Fixture-proven | Chapter Authority command port and persisted delegation | real Provider child runs unproven |
| Chapter acceptance | Fixture-proven | Final Gate evidence to ChapterOutcome/StoryState | production editorial acceptance unproven |
| Pause/resume/cancel | Fixture-proven foundation | Book gate and child/root cancellation | real long-running worker/provider race proof incomplete |
| Reader Outcome | Shadow foundation | governed report and state candidate | uncalibrated and non-blocking |
| Longform Recap | Deterministic foundation | recap, deviation and proposal outputs | semantic model/human proof incomplete |
| Plan Change | Design/Foundation | diff, impact, decision and activation contracts | complete automatic replan propagation unproven |
| Hierarchical planning | Design/Foundation | Book/Volume/Arc/ChapterGroup migrations/contracts | continuous planner execution incomplete |
| Ending/closure | Design/partial | ending and reachability concepts in execution/design layers | no full-book closure proof |
| Whole-book supervisor | Missing/partial | coordination pieces exist separately | no single autonomous progression owner |
| Million-word stability | Unproven | no current real-provider long novel evidence | staged 10/30/100/300/million-word proof required |

## 5. Knowledge And Content Intelligence

| Capability | Status | Current evidence | Remaining gap |
|---|---|---|---|
| Source registry/intake | Broad Legacy foundation | source metadata, rights/risk and snapshots | Authority migration and full caller convergence |
| Source eligibility | Implemented foundation | R0-R4, quarantine, allowed-use and approval concepts | current Source Authority integrity pending |
| MKAOS ingestion | Broad foundation | document/chunk/candidate/card/pack flows | Authority migration and real corpus operations |
| MKAOS quality | Partial | leakage, near-duplicate, risk and usability gates | real calibration and full production enforcement |
| MKAOS lineage | Partial | source-to-output lineage and feedback attribution | PostgreSQL Authority convergence and scale |
| Context Builder | Partial/meaningful | stage profiles, source isolation and token budgets | universal production path use and selection evaluation |
| Retrieval | Partial | local, Qdrant and pgvector slices | real embedding/rerank quality and operations |
| Genre OS | Implemented foundation | strategy profiles and policy assets | real output calibration and Authority binding |
| Style OS | Implemented foundation | abstract fingerprint/policy/drift | provider-assisted calibration and larger corpus workflows |
| Analysis/decomposition | Partial | web/published/classic analysis slices | model quality, lineage and asset conversion closure |
| Material system | Implemented foundation | reusable structured assets | Authority lifecycle and usage learning depth |

## 6. Creative And Quality Product Capabilities

| Capability | Status | Explicit limit |
|---|---|---|
| Topic generation | Local/domain implementation | not yet fully Authority-led real-provider production |
| Worldbuilding | Local/domain implementation | contradiction and lifecycle Authority partial |
| Character design | Local/domain implementation | long-horizon state and editable lifecycle partial |
| Outline/Book planning | Partial | semantic generator and hierarchical acceptance still converging |
| ChapterPlan | Implemented contract, partial production | real automatic generation and qualification not yet whole-book closed |
| Readable prose | Partial | governed Chapter stage exists, real quality not proven |
| ReviewIssue | Implemented foundation | universal caller and repair UX still converging |
| Revision strategy | Partial | candidate/plan/patch contracts exist, real provider repair proof absent |
| Reader Promise | Foundation | deterministic payoff detection needs calibration |
| Chapter Economy | Foundation | heuristic water/repetition detection needs calibration |
| Character Pressure | Foundation | heuristic agency/pressure scores need calibration |
| Mobile Reading | Foundation | heuristic layout checks need platform/reader calibration |
| Evaluation Center | Partial | golden-set and annotation foundations, no production premium Judge proof |

## 7. Agent, UI, Publishing And Portfolio

| Capability | Status | Explicit limit |
|---|---|---|
| Agent Registry | Foundation | target-role and operation coverage incomplete |
| Agent Scheduler | Partial | broad Legacy scheduler plus newer Authority workers; topology not unified |
| Agent Collaboration V1 | Fixture-proven foundation | no real Codex/Provider collaborative book-design proof |
| Permission Center | Foundation | approval records exist; not full user/org RBAC |
| OS Cockpit | Partial | broad evidence views; some actions remain review/planning only |
| Web Admin | Partial | Node/static tests historically reported; browser smoke and auth incomplete |
| Local export | Development slice | no production distribution proof |
| Platform strategy | Partial | rules and gates, limited official integration |
| Publishing adapters | Manual/generic foundation | no verified official platform API lifecycle |
| Feedback import/backflow | Partial | proposal/patch/AgentTask plans exist; live stream and causal proof absent |
| Portfolio OS | Foundation | allocation plans are non-dispatching and approval-gated |
| Multi-book isolation | Fixture/design evidence | real concurrency and contamination proof absent |

## 8. Current Completion Assessment

Practical maturity, not module count:

| Dimension | Assessment |
|---|---|
| Architecture/control-plane design | 65-70% |
| Fixture/protocol implementation | 60-65% |
| Real business loop | 35-40% |
| Production readiness | 25-30% |
| Final Autonomous Novel OS target | roughly half of the critical proof remains |

The next maturity step is not adding more isolated modules. It is closing one buildable and deployable Authority path, then proving real Provider, whole-book and multi-book behavior in staged acceptance gates.

## 9. Completion Rule

A capability may be marked production-complete only when all applicable evidence exists:

```text
current HEAD builds
+ Authority command path
+ frozen versions
+ idempotency/concurrency
+ durable worker/recovery
+ real external behavior where applicable
+ output qualification
+ audit/trace/cost
+ positive and negative tests
+ operator workflow
+ production deployment proof
```
