# MKAOS Feedback Weight Proof

Date: 2026-07-03

## Proof Path

The proof is implemented in `tests/unit/test_mkaos_selector_canon.py::test_selector_respects_feedback_quality_and_weight`.

Steps:

1. Create two project-scoped Knowledge Cards with equal priority, quality, and weight.
2. Bind both cards to the `prose` flow.
3. Record positive review feedback for one card through `record_review_feedback`.
4. Apply a positive weight update through `apply_weight_update`.
5. Build a `prose` Knowledge Pack.
6. Assert the feedback-weighted card is selected first.
7. Assert `selector_decision.feedback_delta > 0` and `selector_decision.weight > 1`.

## Evidence

Code paths:

- `src/novel_forge/modules/mkaos/service.py::record_review_feedback`
- `src/novel_forge/modules/mkaos/service.py::apply_weight_update`
- `src/novel_forge/modules/mkaos/service.py::_quality_feedback_delta`
- `src/novel_forge/modules/mkaos/service.py::_selector_decision`
- `src/novel_forge/modules/mkaos/service.py::_select_pack_items`

Test command:

```bash
python3 -m unittest tests/unit/test_mkaos_selector_canon.py
```

Result: 3 tests OK.

## Conclusion

Feedback and quality records are no longer write-only. They can change subsequent Knowledge Pack ordering, while the resulting pack records selector scores for audit.
