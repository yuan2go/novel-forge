# Capability map

## Agent, capability, Skill, and Capability Pack

| Term | Meaning |
|---|---|
| Agent | A governed reasoning executor with a versioned definition, scope, permissions, budgets, tools, context, and candidate output. Its lifecycle is projected from Command Kernel Operation/Attempt facts. It is not a Domain Authority. |
| Capability | A versioned unit of work with typed input/output and a risk/qualification contract. Agent capabilities map one-to-one to an execution capability in PEP. |
| Skill | A reusable, versioned procedure bound by content hash, input/output contracts, invocation limits, dependencies, and drift policy. It does not own runtime state. |
| Capability Pack | A validated, compiled, content-addressed manifest that freezes roles, workflows, capabilities, Skills, prompts, tools, policies, gates, and compatibility for a release channel. |

Agent output remains a proposal until the relevant Domain Authority accepts it. The runtime has one execution plane: Agent execution uses the same Operation, Attempt, Lease/Fence, ExternalEffect, and provider gateway as other governed work.

## Runtime capability map

| Capability family | Runtime status | Evidence boundary |
|---|---|---|
| Project/workspace/task and asset authority | `runtime-wired` | Atomic command and query tests; PostgreSQL suites exist. |
| Book design and typed planning | `runtime-wired` | Candidate/decision/activation and Book-flow tests. |
| Chapter production saga | `runtime-wired`, `fixture-proven` | 18-node bounded acceptance paths; selected PostgreSQL integration. |
| Book supervision and follow-up | `runtime-wired`, `fixture-proven` | Deterministic tick, Reader/recap/replan tests. |
| Narrative State Contract v2: Canon, ChapterOutcome, StoryState, temporal query | `runtime-wired`, `PostgreSQL-fixture-validated` | Entity-aware current state, accepted-only as-of reads, Book acceptance and deterministic rebuild tests. |
| Context building | `runtime-wired`, `fixture-proven` | Source isolation and budget/profile validation. |
| Source Import and Source Authority | `runtime-wired`, `fixture-proven` | Governed repository/document/chunk flows; integration suites exist. |
| MKAOS knowledge candidate/approval/pack | `runtime-wired`, `fixture-proven` | Evidence and source-leakage gates; integration suites exist. |
| Agent candidate runtime | first slice `runtime-wired` | Admission, scheduler, checkpoint/gate/budget/recovery tests; limited operation coverage. |
| Capability Pack authority | `runtime-wired`, `fixture-proven` | Validation, compilation, deployment/activation contracts. |
| Provider qualification | `implemented`, selectively `runtime-wired` | D0 probe exists; default Compose remains fixture-only. |
| Admin console | `implemented`, `fixture-proven` | Type and route/component tests; incomplete product depth. |

## Explicitly not proven

- complete autonomous Agent Center operation;
- broad Agent operation coverage and business rollback across all domains;
- real-provider model usage hard-stop across a sustained Book run;
- long-form quality and continuity over a full novel;
- external publishing or multi-book scale;
- production deployment, SLOs, or operational history.
