# WP-QUALITY-PROOF-01 Correctness Closure Design

Status: APPROVED BY USER REQUEST

Date: 2026-08-27

Effective implementation base: `3511efbd4d83b6716fc6b930b5f86ff16c775eb7`

Effective migration head: `20260826_0101_quality_qualification`

## 1. Decision

Close the two real Chapter identity failures before another Provider campaign by
extending existing Authority, Production Preparation, Context, Chapter and
Command Kernel seams. No parallel Character Authority, Context store, Judge or
recovery plane is introduced.

The Canonical Book path must freeze the exact active `CHARACTER_CAST` and
`READER_PROMISE` Foundation bindings from the Book input snapshot into every
Chapter Production Input Manifest. Their Chapter Context projections are
`PROTECTED`, non-lossy and visible to Draft, Review, Revision, Rereview and
Canon extraction through the one existing ContextBundle.

## 2. Public seams

The implementation and tests use these existing public seams:

1. `ProductionPreparationService.prepare()` for frozen Chapter inputs and
   semantic projections.
2. `build_context_bundle()` and `build_provider_context_view()` for protected
   selection and the actual model-facing Draft/Review boundary.
3. `build_canon_patch()` / `validate_deterministic_continuity()` for the L1
   deterministic acceptance gate.
4. Command Kernel maintenance, recovery and cancellation commands for the
   abandoned exact-operation closure.
5. Canonical PostgreSQL migration and recovery test targets for exact-HEAD
   qualification.

## 3. Character identity contract

Canonical Chapter production accepts either the frozen Canonical
`character_cast` or explicitly selected authoritative `character_card` assets,
but never an unbound narrative summary. Every executable identity record must
contain:

- stable `character_id` (or authoritative `entity_id`);
- explicit `canonical_name`/`name`;
- a bounded list of exact `aliases` (the canonical name is implicitly one);
- an explicit non-empty `pronouns` list;
- the source AssetVersion and content hash supplied by the enclosing Context
  segment.

Stable characterization fields such as desire, need, fear, wound, values,
agency, voice, secret, moral boundary and Arc direction are projected without
semantic rewriting. Historical CharacterCast assets that lack the executable
identity vocabulary remain immutable and readable, but a Canonical Book Chapter
using them is blocked with repair evidence before any Provider call.

The bounded campaign contract is upgraded in place to include Chinese canonical
names, aliases and pronouns for all three frozen cast members. This is a campaign
input correction, not evidence that the historical bad drafts were valid.

## 4. Reader Promise contract

The exact active `READER_PROMISE` Foundation AssetVersion is selected from the
same Book input snapshot as CharacterCast. Production Preparation projects the
reader-facing promise text and its bounded semantic fields into a protected
`reader_promise_contract` fact. Draft and Review provider views must contain the
same AssetVersion, content hash and exact promise semantics. A manifest-only
ReaderPromise or an empty marker is a failure.

Reader Promise remains future intent/editorial contract. It does not become
Canon, Actual state or Reader Outcome merely by entering Context.

## 5. Deterministic identity continuity

The L1 gate adds a conservative surface-realization check backed only by the
explicit protected identity vocabulary. It does not infer gender from names,
slugs, roles or model judgment.

The checker tokenizes sentence/paragraph boundaries and carries an exact named
subject for one adjacent unit. It emits
`CHARACTER_IDENTITY_PRONOUN_CONTRADICTION` only when:

1. exactly one configured canonical name/alias establishes the subject;
2. the immediately following unit begins with an explicit third-person pronoun;
3. that pronoun is outside the subject's declared pronoun set.

The evidence includes the source identity, alias, expected/observed pronoun,
bounded text excerpt and source Character AssetVersion. Ambiguous multi-character
units are not guessed; semantic review remains responsible for broader OOC and
coreference questions. Any emitted contradiction is blocking and cannot be
averaged away by review or editorial scores.

## 6. Real-failure regressions

Two immutable 2026-08-27 artifacts seed regression fixtures:

- `签名之前`: CharacterCast semantics establish Lin Yao as `她`; the revision
  opens `林遥...。他把底图...` and must be blocked.
- `不存在的路`: CharacterCast semantics establish Director Xu as `她`; the
  revision contains `徐主任的通话随即接入。他没有问...` and must be blocked.

Tests retain only the minimum source excerpts and identity fields required to
reproduce the defect; they do not promote either unaccepted draft to Canon.
Separate preparation tests prove the historical unbound CharacterCast shape is
rejected before Provider execution.

## 7. Recovery closure

The residual operation
`161bbe98-2c07-4851-910a-5889b89f6c6c` is an abandoned
`story_design.semantic_evaluate` attempt with an expired lease and no
ExternalEffect. Closure must use the current Authority commands in this order:

1. mark the exact expired lease `EXPIRED` and the exact attempt `LEASE_LOST`
   through fenced attempt recovery (the all-database maintenance scan is not
   used for this targeted closure);
2. record an idempotent recovery command for audit visibility;
3. request cancellation at the exact operation version;
4. resolve as `no_external_effect` to terminal `CANCELLED`.

Direct SQL status mutation is forbidden. The result must retain recovery,
cancellation, StateEvent, audit and outbox evidence and leave no live lease,
running attempt or non-terminal operation.

## 8. Qualification boundary

Focused tests precede implementation. After focused green, run current-HEAD
unit/Authority regression, PostgreSQL integration, fresh migration, upgrade
migration and recovery qualification. The exact release SHA is frozen only
after those gates pass. No real Provider campaign is part of this closure run.

Passing this closure proves the protected-context and deterministic identity
controls are wired and regression-tested. It does not retroactively qualify the
two rejected drafts, calibrate an automated Judge, or prove long-form quality.
