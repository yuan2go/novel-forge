# ReviewIssue Blocking Proof

Date: 2026-07-03

## Proof 1: MKAOS Issue To ReviewIssue

Test:

```bash
python3 -m unittest tests/unit/test_review_issue.py
```

Covered by `test_mkaos_review_issue_blocks_publish_gate_and_release_package`.

Path:

- `review.service.review`
- `mkaos.validate_artifact`
- `review_issue.persist_review_issues_for_report`

Result:

- high MKAOS anti-encyclopedia issue becomes `review_issue`;
- `issue_type=mkaos_conflict`;
- issue is active and blocking.

## Proof 2: Canon Conflict To ReviewIssue

Covered by `test_canon_issue_candidate_persists_as_review_issue_with_revision_task_candidate`.

Path:

- `mkaos.check_canon_conflict`
- `mkaos.canon_conflict_to_issue_candidate`
- `review_issue.persist_issue_candidates`

Result:

- Canon conflict becomes `review_issue`;
- `issue_type=canon_conflict`;
- `revision_task_candidate` is present.

## Proof 3: Publish / Release Blocking

Covered by `test_mkaos_review_issue_blocks_publish_gate_and_release_package`.

Path:

- `audit.create_publish_gate_report`
- `review_issue.blocking_review_issues`
- `audit.create_release_package`

Result:

- publish gate decision becomes `blocked`;
- release package creation raises `release_package blocked by ...`.

## Proof 4: Canonical / Final Draft Blocking

Covered by `test_blocking_review_issue_prevents_final_draft_promotion`.

Path:

- `editor.execute_revision_plan`
- `review_issue.assert_no_blocking_review_issues`

Result:

- final draft promotion raises `canonical_chapter blocked by ...`.
