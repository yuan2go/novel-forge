# Canon Re-extraction Authority

Migration 0029 adds approval transitions and append-only re-extraction generations.

`DEFER` freezes deadline, required information, assigned operator, and expiry policy.
Only a versioned, idempotent reopen command or expiry coordinator returns it to
`PENDING`; the root remains `WAITING_GATE` meanwhile.

`REQUEST_REEXTRACTION` invalidates, but never deletes, the old requests and records a
generation that supersedes the old Proposal. The Chapter scheduler admits new Canon
Extraction and Proposal Operations, creates new per-change approvals, and resumes the
same root Saga only after the new generation resolves. Old decisions are excluded
from reduction.

`EDIT_AND_APPROVE` materializes `CanonChangeResolution`; its payload is revalidated
for schema, project/entity identity, change type, confidence/evidence, previous-state
scope, duplicates, and world/timeline/power/relationship conflicts before reduction.

Evidence: `canon_graph/approval_domain.py`, `approval_authority.py`, the trusted
Canon reopen API, Migration 0029, unit tests, and PostgreSQL gate-recovery tests.
