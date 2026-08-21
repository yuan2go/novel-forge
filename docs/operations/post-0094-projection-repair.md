# Post-0094 Accepted Projection Repair

This runbook applies to databases that contain committed accepted Chapters but
whose 0094 long-form projection pointers are absent, incomplete or stale.
Migration `20260821_0095_post_merge_correctness_repair` is forward-only and
does not rebuild history inside the migration transaction.

## Runtime chain

```text
0095 discovery / explicit repair registration
→ RuntimeJob
→ bounded repair Operation
→ Attempt → Lease / Fence
→ shared canonical accepted-evidence projector
→ per-Chapter immutable projection set + repair checkpoint
→ next bounded RuntimeJob, when needed
→ terminal validation
→ one fenced/CAS active-pointer activation
→ AUTHORITATIVE_REPAIR_COMPLETE
```

The source set is limited to committed Book acceptance, ChapterOutcome,
StoryState, CanonSnapshot and exact frozen planning AssetVersions. Drafts,
unaccepted candidates and current guessed state are not repair inputs. Legacy
accepted outcomes without modern Arc evidence produce explicit `UNKNOWN`
adaptation provenance; planned contribution is never converted to Actual.

The terminal validator requires a continuous `1..N` acceptance sequence, exact
source IDs and hashes, complete projection components, acceptance pointer
alignment and current Book head alignment. It then updates
`active_longform_projection_set_id` once under the current repair Attempt fence
and expected Book version. Checkpointed partial work is not an active repaired
head. Idempotent conflicts fail closed instead of accepting different content.

## Operational states

- `REGISTERED`, `RUNNING`, `CHECKPOINTED`, `FAILED_RETRYABLE`: repair is not
  complete; normal Book scheduling excludes the run and the worker may resume.
- `FAILED_TERMINAL`: the accepted sequence or source evidence is invalid and
  requires operator investigation. No accepted history is rewritten.
- `AUTHORITATIVE_REPAIR_COMPLETE`: the accepted projection head is valid and
  Chapter N+1 admission may proceed.

Inspect repair status through the Book progress projection and the
`authority_book_projection_repair` / `authority_book_projection_repair_checkpoint`
tables. Audit records retain RuntimeJob, Operation, Attempt, fencing token,
source digest, projection hash and terminal validation evidence.

## Semantic retrieval readiness

`RETRIEVAL_SEMANTIC_PROJECTION_READY` is deliberately separate from
authoritative repair. Accepted retrieval documents can be embedded later by
the `narrative.retrieval.embedding.project` worker Operation through PEP,
ExternalEffect and durable Receipt. A semantic-required Context profile fails
closed until the governed document/query embeddings are ready. A
`FALLBACK_ALLOWED` profile records an explicit PostgreSQL FTS/graph/temporal
fallback in the RetrievalResult. There is no silent downgrade.

## Recovery

Restart the normal Book/Chapter workers; do not edit projection pointers
manually. The repair scheduler resumes from the durable checkpoint and the
embedding scheduler reconciles successful receipts before considering another
provider dispatch. A stale or expired worker lease cannot commit either
projection state.
