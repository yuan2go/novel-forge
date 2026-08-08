# Real Capability Runtime and Codex Production Proof Design

## Objective

Prove that the existing PostgreSQL Chapter Authority executes an exact Capability Pack through the existing Production Execution Gateway and a real, locally authenticated Codex CLI process. The proof must cover the complete canonical single-chapter workflow and must not introduce a second execution runtime or promote fixture evidence.

The target status is `REAL_PROVIDER_CAPABILITY_RUNTIME_PROVEN=true` only when one current-HEAD run provides durable evidence for capability materialization, real provider execution, structured and semantic validation, usage and estimated cost, traceability, canonical commits, quality decisions, and recovery.

## Scope

This change is one vertical slice:

```text
Chapter Attempt
-> Capability Requirement
-> Pack Resolution
-> immutable Attempt Capability Snapshot
-> Prompt / Skill / Context / Knowledge / Tool materialization
-> ExternalEffect
-> ExecutionRequest
-> CodexCliExecutionBackend
-> structured and semantic validation
-> usage / estimated cost / trace
-> Agent candidate
-> Review / Revision / Re-review
-> Canon / Quality / Reader Outcome / release gates
```

It reuses Capability Pack Authority, Agent Runtime Binding, Chapter Authority, ProductionExecutionGateway, CodexProcessSupervisor, AuthorityExecutionRecoveryStore, and the existing domain handlers. It does not add a Capability Orchestrator, ProviderAdapterV2 wrapper, model strategy system, parallel runtime, new creative Skill family, multi-book proof, or long-form proof.

## Capability Freezing

`PostgresChapterExecutionContractBinder` gains a pre-effect freeze operation. It resolves the active Pack exactly once for the current Attempt and stores the existing `authority_attempt_capability_pack_snapshot` before `plan_external_effect` is called. The returned immutable preflight contains the snapshot identity and the exact identities and hashes of the stage capability, system instruction, template, Skill, context policy, evaluation policy, tool policy, output schema, and required Knowledge.

The ExternalEffect request payload binds the preflight snapshot ID/hash and a canonical capability materialization hash. Replay and recovery load that original Attempt snapshot and reject any active-deployment change. The later ExecutionRequest binding consumes the same preflight and fails if its Attempt, Fence, Pack, node, artifact, or materialization identity differs.

Controlled environments fail closed for missing Pack or capability, missing registered artifact content, content hash drift, version mismatch, invalid or cross-project context, missing required Knowledge, unauthorized tools, and snapshot inconsistency.

## Content Materialization

Capability Pack Authority remains the source of exact Pack content. The runtime resolver reads the registered artifact catalog through the Pack version selected by the Attempt snapshot and verifies each artifact against its frozen ref, version, kind, and SHA-256 hash.

`PostgresChapterExecutionPayloadResolver` constructs the actual Codex input from:

- the registered system instruction text;
- the registered prompt template text;
- the registered stage Skill text;
- frozen Authority input artifacts selected by the Context policy;
- at least one eligible `knowledge_pack` for required-Knowledge stages;
- the stage task input and exact output contract;
- the tool policy, with default deny and only the stage's explicitly allowed operation.

The materialized request records declared and consumed Prompt, Skill, Context, Knowledge, Tool and output-schema identities. The model sees the content, not only its references. Raw reference documents remain forbidden.

The real proof creates an eligible, source-isolated Knowledge Pack through existing MKAOS Authority commands and supplies it as a Chapter input. No fixture or direct table insert is credited as Knowledge proof.

## Codex CLI Execution

The existing `CodexCliExecutionBackend` is registered directly by Chapter composition for the explicit `codex-cli` provider. It uses `CodexProcessSupervisor`, a persistent execution directory, `LocalProcessExecutionPolicy`, and an explicit absolute executable path.

The command uses only options verified by the installed CLI: non-interactive `exec`, JSONL stdout, output JSON Schema, final-message file, ephemeral execution, ignored user configuration and rules, read-only sandbox, fixed working directory, and stdin prompt. No ProviderAdapterV2 wrapper or direct model call is introduced.

The backend parses measured usage from the terminal `turn.completed` JSONL event. Since authenticated Codex CLI does not emit billed cost, it calculates an `ESTIMATED` amount from an explicit immutable pricing snapshot configured for the run. Evidence records model, measured token categories, pricing reference and rates, formula, currency, and `estimated=true`; it never claims provider-billed cost.

Tool evidence records the allowed, denied and invoked sets. For model stages, `model.provider.invoke` is invoked; all filesystem, database, command, HTTP and MCP tools remain denied to model-controlled execution. The Codex sandbox is read-only and the prompt contains all required governed content.

## Validation and Failure Semantics

A zero process exit is necessary but insufficient. Before the ExternalEffect can receive a successful receipt, the backend must complete:

```text
process success
-> final-message JSON parse
-> exact stage JSON Schema validation
-> Chapter stage semantic normalization
-> Authority eligibility validation
```

The stored normalized result is the validated domain result. Bad JSON, schema failure and semantic failure produce distinct failure codes and cannot produce a successful candidate or receipt. Timeout, process start/exit failure, invalid result, Attempt retry and worker recovery remain distinct in execution evidence.

An invalid completed process is a failed Attempt, not a reusable success. A retry creates a new Authority Attempt and ExternalEffect while retaining the operation's capability selection rules. Recovery of a previously dispatched valid execution reuses its persistent receipt and the original frozen snapshot. Codex upstream cancellation is not claimed; only local process-group termination is evidenced.

## Evidence and Proof

Each real model call writes:

- ExternalEffect request and receipt;
- ExecutionRequest, handle, process receipt and validation manifest;
- Capability Attempt Snapshot and capability materialization manifest;
- Agent Runtime Binding and accepted candidate;
- model call log with provider/model, measured usage and consumed capabilities;
- cost ledger with estimated cost and pricing snapshot;
- trace/correlation identity and canonical output lineage.

The proof runner uses the normal PostgreSQL Chapter Authority admission and scheduler in `provider-validation`, PostgreSQL and MinIO. It registers and activates the current Pack and Agent definitions through their Authority applications, creates qualified Chapter/Context/Knowledge inputs through existing authorities, runs all current Chapter nodes, and queries durable evidence afterward.

Proof flags are computed from evidence rather than requested as inputs. Any failed requirement leaves its flag false and preserves the failure report.

## Verification

Implementation follows test-first seams:

1. Pack content resolution and hash-drift fail-closed tests.
2. Pre-effect snapshot ordering and replay immutability tests.
3. Prompt/Skill/Context/Knowledge/Tool materialization tests.
4. Stage JSON Schema and semantic validation tests.
5. Codex command, JSONL usage, estimated-cost and failure taxonomy tests.
6. PostgreSQL integration tests for snapshot/effect/binding/recovery invariants using controlled process fixtures; these do not count as real-provider proof.
7. One real Codex provider-validation Chapter run, including one safe failure/recovery scenario.
8. Focused regression, full relevant PostgreSQL suites, static architecture checks, and final code review at the exact tested HEAD.

No migration is planned because existing JSONB snapshots, Authority AssetVersions, ExternalEffect receipts, model call logs and cost ledgers can hold the required evidence. A migration is allowed only if a failing database invariant proves those stores insufficient.

## Non-Claims

This slice does not prove provider-billed cost, remote Codex cancellation, complete autonomous Agent Center, production deployment, multi-book production, long-form stability, human preference calibration, or production verification.
