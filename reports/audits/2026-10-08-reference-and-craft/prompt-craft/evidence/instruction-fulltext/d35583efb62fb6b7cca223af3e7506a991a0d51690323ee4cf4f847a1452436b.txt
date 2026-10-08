---
name: agent-loop-governance
description: Use when governing bounded Agent Runtime execution through AgentRun operations, sessions, budgets, checkpoints, gates, retries, dead letters, and owner-approved domain submission.
---

# Agent Runtime Loop Governance

## Purpose

- Turn one bounded Agent task into an auditable AgentRun and, when a model/tool dialogue
  is required, an Agent Session bound to a Command Kernel Operation.
- Review scheduler, checkpoint, gate, budget, retry, dead-letter and recovery behavior.
- Preserve the distinction between Agent execution evidence and domain Authority state.

## Input contract

- Project/workspace scope, Principal and requested Agent definition/version.
- Frozen operation definition, runtime binding, Capability Pack, ContextBundle and Tool
  policy identities.
- Token/cost/time limits, checkpoint/gate policy, retry ceiling and stop conditions.
- Current Operation, Attempt, Lease, Fence, ExternalEffect, session and transcript
  evidence when resuming or diagnosing.

Reject cross-project inputs, floating versions, missing execution mappings and any task
whose requested domain mutation has no owning Authority command.

## Allowed context

- Current project-scoped ContextBundle and accepted Canon/Narrative State evidence.
- Frozen Agent definition, Capability Pack, prompt/Skill hashes and runtime policy.
- Relevant ReviewIssue, gate, budget, trace, audit and recovery evidence.
- No raw source document or ungoverned chat memory as domain truth.

## Authority boundary

- Agent Runtime owns definitions, activations, runtime bindings, AgentRun projection,
  sessions, transcripts and dispatch evidence.
- Command Kernel owns Operation, Attempt, Lease, Fence and ExternalEffect lifecycle.
- The Agent may submit a candidate or typed command only. Story Design, Planning, Plan
  Change, Book, Chapter, Quality and Canon Authorities retain their decisions.
- A repository or coordinator cannot convert Agent output into accepted narrative truth.

## Procedure

1. Resolve the production entry, Agent definition, capability execution mapping and
   frozen instruction/context identities.
2. Admit one bounded AgentRun Operation and record its task, budgets, stop conditions and
   expected output contract.
3. Let the Agent scheduler claim the current Attempt under lease and fence; create or
   resume the bound Agent Session when the operation uses the harness.
4. Route model/tool I/O through Production Execution and durable ExternalEffect intent.
5. Append transcript, cost/usage, checkpoint and gate evidence; never overwrite a
   terminal Attempt or session event.
6. Submit resulting candidates or commands to their owning domain Authority and retain
   its acceptance/rejection evidence.
7. On retry, create a new Attempt under the declared ceiling. On ambiguous effect or
   commit outcome, stop and reconcile before dispatch. On exhaustion, dead-letter with a
   recovery instruction.

## Output contract

Return a schema-backed governance record containing:

- AgentRun/Operation and optional Agent Session identities;
- Agent definition, runtime binding, Capability Pack, prompt/Skill and ContextBundle
  identities;
- task scope, budgets, stop condition and current status;
- Attempt/Lease/Fence, ExternalEffect, checkpoint, transcript and gate references;
- domain submission and owner decision references, if any;
- retry, dead-letter or reconciliation instruction on failure;
- `trace_id`, correlation/causation identity, validation status and evidence paths.

## Quality criteria

- Every execution step is traceable to the same frozen project-scoped contract.
- Budget, permission, Provider and Tool limits fail closed.
- Agent completion is not reported as domain acceptance without owner evidence.
- Retry/recovery appends new versioned facts and ambiguous effects are never blindly
  resent.
- Fixture, scripted Provider, credentialed Provider and production proof remain distinct.

## Failure semantics

- Missing/stale binding, context, instruction identity, budget or permission: reject
  admission or hard-stop the active Attempt.
- Lost lease or stale fence: reject completion and let the scheduler reacquire according
  to policy.
- Ambiguous external outcome: enter reconciliation; do not redispatch.
- Blocking owner gate or human decision: checkpoint as waiting evidence, not success.
- Exhausted retry ceiling: dead-letter with a durable recovery instruction.

## Required evidence

- `AgentRuntimeAuthorityApplication` and `AgentAuthorityScheduler` result.
- Operation/Attempt/Lease/Fence and ExternalEffect/receipt records.
- Agent runtime binding, session/transcript and Capability Pack materialization records.
- ContextBundle, prompt/Skill identity, model usage/cost and Tool-call evidence.
- Owning domain Authority result and gate decision for every submitted mutation.

## Related Skills

- `context-builder-source-isolation`
- `provider-runtime-policy`
- `review-issue-gate`
- `novel-os-engineering-audit`
