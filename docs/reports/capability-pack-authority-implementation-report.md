# Capability Pack Authority Implementation Report

Date: 2026-08-06
Baseline: `4e941af430481baf64322c24e97cb1a828e996f1`
Migration Head: `20260805_0071_capability_pack_authority`

## Outcome

Novel Forge now has one PostgreSQL-backed Capability Pack configuration authority. The existing P1A compiler remains a deterministic pure compiler; the new layer registers immutable inputs, performs trusted compilation, records approval decisions, materializes an all-node Binding Set, manages deployment and rollout pointers, and resolves the exact Pack snapshot before controlled Agent admission.

This work does not create a Capability Pack execution runtime. Command Kernel still owns Operation, Saga, Attempt, Lease, Fence, retry, cancellation, compensation, and ExternalEffect. Workflow Authority owns graph and node state. Agent Runtime owns Agent execution and Candidate production. Domain Authorities retain validation and commit.

## Current architecture and implementation audit

Before this change, the repository had a schema-backed Capability Pack protocol, validator, deterministic compiler, repository artifact resolver, and a Chapter binding check. The remaining production gap was authority: CompiledCapabilityPack could be supplied inline to `agent.chapter_binding.register`, no PostgreSQL Pack Version/Compilation/Approval/Deployment registry existed, and no scope-aware resolver froze a deployment identity into Agent Runtime evidence.

The implemented path is now:

```text
Manifest + Artifact Catalog AssetVersions
  -> structural/semantic validation
  -> pure compilation outside write transaction
  -> locked input-identity recheck
  -> trusted CompiledCapabilityPack AssetVersion
  -> append-only Approval Decision
  -> immutable complete Binding Set
  -> scoped Deployment candidate
  -> CAS Activation pointer
  -> stable Rollout Assignment
  -> CapabilityPackExecutionSnapshot
  -> scoped Agent Runtime Binding snapshot
  -> existing Operation/Attempt/Lease/Fence/ExternalEffect runtime
```

The authority tables are configuration and evidence facts only:

- `authority_capability_pack` and `authority_capability_pack_version` hold stable identity and immutable registered versions.
- `authority_capability_pack_validation` and `authority_capability_pack_compilation` hold append-only validation and trusted compilation facts.
- `authority_capability_pack_approval` holds append-only approve/reject/revoke decisions bound to an exact compilation hash.
- `authority_capability_pack_binding_set` holds one content-addressed, all-node binding snapshot per compilation.
- `authority_capability_pack_deployment` and `authority_capability_pack_activation` separate deployment history from the CAS-protected active pointer.
- `authority_capability_pack_rollout` and `authority_capability_pack_assignment` hold staged rollout policy and stable subject assignments.
- `authority_capability_pack_deprecation` holds append-only deprecation and retirement facts.

No Pack Run, Pack Attempt, Pack Lease, Pack Fence, Pack Worker, Pack Workflow, Pack Provider, or Pack ExternalEffect table exists.

## Object, state, and authority model

The principal lifecycle is:

```text
REGISTERED -> VALIDATED -> TRUSTED_COMPILATION -> APPROVED
    -> CANDIDATE_DEPLOYMENT -> ACTIVE -> DISABLED/DEPRECATED/RETIRED
                                  |
                                  +-> CANARY/PERCENTAGE/FULL rollout
                                  +-> CAS rollback to a previous Deployment
```

Approval is not a mutable flag. The current decision is the latest append-only decision for the exact compilation. Compiler and approver separation is enforced when requested. Revocation appends a `REVOKED` decision and marks related non-terminal deployments `ROLLBACK_REQUIRED`; historical runtime bindings remain immutable, while new admission fails closed.

Binding Set cross-validation distinguishes two different contracts that must not be conflated:

- Agent Capability hash: the reusable Agent role capability contract.
- Execution Capability hash: the existing Production Execution Plane capability contract reached through the one-to-one execution mapping.

The Binding Set additionally freezes exact OperationDefinition, AgentDefinition, prompt, skill, tool, context, evaluation, route, approval, budget, input/output contract, and Domain Authority identities. Activation only changes the scope-aware CAS pointer. Controlled Chapter and Agent execution derive an immutable runtime binding directly from the selected Binding Set; they never overwrite the global legacy Chapter-node activation projection.

## Runtime resolution

`CapabilityPackRuntimeResolver` resolves new admission in deterministic precedence order:

1. Book
2. Workspace
3. Project
4. System

It fails closed on ambiguity, missing activation, wrong environment/runtime profile/release channel/release SHA, expired or revoked approval, retired version, OperationDefinition drift, AgentDefinition drift, Agent Capability drift, or execution-mapping drift.

Canary and percentage assignments use a stable SHA-256 bucket over rollout and subject identity and are stored append-only. Paused rollout admission selects the baseline without rewriting the assignment; resume restores the original rollout mode; completed rollout admission selects the candidate. Retries and recovery reuse the frozen assignment; they do not re-randomize.

Controlled Chapter execution and the direct Agent Run API now resolve this snapshot from PostgreSQL. Agent Runtime Binding stores the exact deployment, activation version, Binding Set identity/hash, selected scope, and assignment reference. The Binding Set hash is the content-addressed link to all configuration contracts.

## API and CLI

The Authority API exposes command/query routes under `/api/capability-packs`, including register, validate, compile, approve, deploy, activate, disable, rollout control, rollback, deprecate, retire, revoke, version/deployment detail, drift, deployment usage, and Pack/Version/Compilation/Binding Set multi-dimensional usage queries.

The CLI exposes the same application/query layer through:

```text
novel-forge authority-capability-pack <action> ...
```

The CLI does not write Pack tables directly. A registration payload file is bootstrap input to the same Command Kernel application path; trusted Compilation is still produced server-side from registered immutable inputs.

## Verification matrix

| Area | Evidence in this change | Classification |
|---|---|---|
| Domain/scope/hash invariants | focused unit tests | local code proof |
| 0071 schema, indexes, constraints, immutable triggers | unit inspection plus migration from empty PostgreSQL database | real PostgreSQL schema proof |
| Register to trusted Compilation | real PostgreSQL lifecycle test | fixture configuration proof |
| Duties separation and exact approval hash | rejection plus approval in real PostgreSQL test | authority transaction proof |
| All-node Binding Set and scope-aware activation | real PostgreSQL lifecycle test | fixture Agent Definition proof |
| Stable rollout assignment | stable stored assignment plus PostgreSQL pause/resume/complete and explicit rollback | deterministic assignment proof |
| Transaction recovery | all nine required checkpoints from `after_manifest_asset` through `before_outbox` roll back atomically, followed by successful retry | transaction recovery proof |
| CAS promotion and rollback | activation versions 1 -> 2 -> 3 | concurrency-control proof |
| Project isolation | cross-project command and detail query reject globally supplied IDs | authorization proof |
| Rollout lifecycle | stable assignment, pause-to-baseline, resume-to-original-mode, completed-to-candidate unit proof | deterministic rollout proof |
| Revocation blocks new admission | real PostgreSQL resolver rejection | fail-closed proof |
| Retired version | new Deployment creation rejected | lifecycle proof |
| Drift | exact Manifest/Compilation/Catalog/Binding Set, Operation, Agent, Capability, Prompt, Skill, Tool, Context, Evaluation, release/profile/channel checks | fail-closed query proof |
| Usage projection | run/success/failure/retry/cancel/reconcile/commit/provider/token/cost/latency, actual gate AssetVersion decisions, reader outcome lineage, all requested identity dimensions, and fixture/real split | query projection proof |
| REST/CLI surfaces and architecture boundary | unit and architecture tests | local interface proof |

## Local qualification evidence

- Focused Capability Pack, Agent Runtime, and architecture tests: `44 passed`.
- Fresh PostgreSQL Capability Pack lifecycle: `1 passed` on PostgreSQL 16.14.
- Fresh combined Capability Pack, Unified Agent Runtime, and Chapter Scheduler suite: `11 passed`.
- Existing required PostgreSQL Authority suite: `164 passed`, with no skips.
- Repository unit and acceptance suites: `1368 + 2 passed` through `make authority-test`.
- `make validate`, `make head-integrity-check`, targeted Capability Pack Ruff, Compose configuration, migration/module/test manifests, and architecture fitness all passed.

## Explicit non-claims

- `REAL_PROVIDER_PROVEN=false`: no real provider was called by the Pack lifecycle test.
  A call counts as real-provider evidence only when its frozen Provider Capability Profile is validation-eligible and a successful controlled effect has exact request and receipt lineage; `V2_CONTROLLED` alone is insufficient.
- `LONGFORM_PROVEN=false`: no 12/30/50 chapter long-form run was executed.
- `MULTI_BOOK_PROVEN=false`: the test uses one Book-scoped fixture.
- `PRODUCTION_VERIFIED=false`: local PostgreSQL and fixture Agent Definitions are not a production release qualification.
- `AUTO_ROLLBACK_PROVEN=false`: rollback is an explicit authorized command; automatic threshold-triggered rollback is not implemented.
- `UI_COMPLETE=false`: API and CLI management surfaces exist; a complete visual Pack Center is not included.

## Remaining work before production qualification

- Register and qualify production Agent Definitions whose capabilities are `QUALIFIED_REAL_RUNTIME` and whose prompt/skill/tool/context contracts exactly match the approved Pack.
- Run a real-provider Chapter path and prove provider hard-stop, trace, receipt, cost, quality, Domain Commit, and publish-gate lineage at one exact release SHA.
- Run multi-book canary and concurrency pressure tests, including conflicting activation requests from independent database sessions.
- Run the 12/30/50 chapter long-form acceptance suites and classify quality/reader/publish evidence without inferring causal or production proof.
- Add operator UI depth and alert-driven, approval-gated rollback proposals if product requirements demand them.
