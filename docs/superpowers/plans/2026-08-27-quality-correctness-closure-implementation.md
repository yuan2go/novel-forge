# WP-QUALITY-PROOF-01 Correctness Closure Implementation Plan

Design: `docs/superpowers/specs/2026-08-27-quality-correctness-closure-design.md`

Base: `3511efbd4d83b6716fc6b930b5f86ff16c775eb7`

## Task 1: Freeze Character and Reader Promise lineage

- Add failing Production Preparation and Book Supervisor tests.
- Expose the exact Foundation Set from the existing Book input snapshot query.
- Freeze `CHARACTER_CAST` and `READER_PROMISE` as explicit overrides and
  capability-required Chapter inputs.
- Assert manifest and context version refs retain exact AssetVersions/hashes.

## Task 2: Build protected semantic projections

- Add a focused Character/Reader Foundation projection module.
- Reject incomplete executable identity vocabularies fail-closed.
- Add `character_cast`, authoritative `character_card` and `reader_promise` to
  allowed/protected Context policy.
- Require selected Character/Promise candidates in Chapter Context assembly.
- Assert Draft and Review provider views contain exact semantics and no Authority
  envelope leakage.

## Task 3: Add deterministic identity continuity

- Add red tests from the two real failed revisions.
- Implement conservative exact-alias/adjacent-pronoun validation.
- Feed protected identity facts and revision text into the existing Canon gate.
- Assert L1 blocking survives high automated review scores.

## Task 4: Repair bounded campaign inputs

- Add canonical name, aliases and pronouns to the frozen bounded campaign
  CharacterCast contract.
- Add contract tests that reject a campaign cast without executable identities.
- Run the scripted campaign dry-run only; do not call a real Provider.

## Task 5: Govern residual operation closure

- Add/reuse PostgreSQL recovery tests for expired lease -> `LEASE_LOST` ->
  audited recovery -> cancellation -> `CANCELLED` with no ExternalEffect.
- Execute that sequence against the exact residual operation idempotently.
- Persist a closure report with before/after Authority evidence.

## Task 6: Exact-HEAD qualification

- Run focused unit/integration tests after each slice.
- Run formatting, static checks and architecture/Skill drift gates.
- Run full Authority regression.
- Run PostgreSQL integration.
- Run fresh and upgrade migration proof to head `0101`.
- Run recovery qualification and verify no non-terminal residual operation.
- Commit the final exact HEAD and report any remaining unproven boundary.
