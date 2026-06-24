# Testing Strategy

## Current Runner

V5 uses Python stdlib `unittest` because the current environment does not include pytest and dependency installation is intentionally avoided during rebuild.

## Commands

```bash
make test
make lint
make validate
make demo
```

## Coverage Areas

- Schema common fields and review report shape.
- Local storage read/write.
- Mock model adapter methods.
- CLI help and validation.
- Ingest, clean, decompose, generation, review.
- End-to-end pipeline.

## Future ADR

Introduce pytest after dependency policy is approved.
