# Canon Approval Authority

Date: 2026-07-18.

The Canon chain is now:

`Revision -> Semantic Extraction -> CanonChangeProposal -> risk gate -> Canon Reduction -> nine Snapshots`.

`CanonChangeProposal` assigns a stable `change_id` and records state kind, entity,
previous state, proposed payload, Revision evidence span/digest, confidence, impact,
conflicts, and approval requirement. Invalid confidence or missing high-impact
evidence is rejected.

Character death, entity merge, world-rule change, major power jump, main-goal
change, abandoned foreshadow/promise, and other high-impact types require a decision
per `change_id`. Supported decisions are APPROVE, REJECT, EDIT_AND_APPROVE, DEFER,
and REQUEST_REEXTRACTION.

When approval is required, the root Operation and Saga enter `WAITING_GATE` before
Canon Reduction is admitted. Decisions are PostgreSQL Authority records and
ELIGIBLE `canon_approval_decision` AssetVersions. Every decision is executed by its
own `canon.change.approve` Operation and fenced Attempt; it is not materialized against
the chapter root or written as an untracked approval side effect. Once every change is approved,
rejected, or edited-and-approved, the root resumes and the Reduction Operation
freezes Proposal and Decision versions as inputs. Generic recover cannot bypass an
unresolved Canon gate.

Snapshots contain only approved/edited changes; rejected changes are excluded.
Their lineage includes Revision, Context, Extraction, Proposal, decisions, previous
Snapshots, and creating Operation.

API:

- `GET /product/canon-authority/approvals`
- `GET /product/canon-authority/approvals/{id}`
- `POST /product/canon-authority/approvals/{id}/decisions`
- `POST /product/canon-authority/operations/{id}/resume`

Approval request creation and its StateEvent/Audit/Outbox are committed in one unit of
work. Request expiry is frozen, and Proposal validation rejects invalid spans/digests,
cross-project previous-state references, duplicate/contradictory extraction, and
unknown high-impact entities.

Evidence: commits `320d792`, `97a4ba5`, `159b1e2`; migrations `0025`, `0026`, and
`0027`; unit decision/evidence/API
tests and PostgreSQL WAITING_GATE -> decision -> resume -> Snapshot proof.
`real_provider_proven=false`.
