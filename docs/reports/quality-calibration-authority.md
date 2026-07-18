# Quality Calibration Authority

Golden sample, human decision, calibration run, promotion and revoke are generic
PostgreSQL Content Authority Operations with frozen inputs and append-only outputs.
Policy checks sample count, exact decision set, coverage, accuracy, in-range score,
per-status precision/recall, agreement and unresolved adjudication. Runs produce a
candidate report; only Promotion can reach `GOLDEN_SET_CALIBRATED`. Zero-sample,
partial, duplicate, mismatched, stale and revoked inputs fail closed.

All evidence is deterministic fixture protocol. `real_provider_proven=false` and
`production_verified=false`. Evidence: calibration domain/codecs and 29-operation
PostgreSQL runtime proof, commits `80be0cb`, `5584744`.
