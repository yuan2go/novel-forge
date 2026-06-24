# Testing Strategy

## Current Runner

V5 uses Python stdlib `unittest` because the current environment does not include pytest and dependency installation is intentionally avoided during rebuild.

## Commands

```bash
make test
make lint
make validate
make demo
make sync-skills-dry-run
make check-skills
```

## Coverage Areas

- Schema common fields and review report shape.
- Local storage read/write.
- Mock model adapter methods.
- Provider adapter contract skeletons and fail-closed behavior.
- CLI help and validation.
- Skills frontmatter and required sections.
- Skills runtime sync dry-run, copy behavior, and drift detection.
- External Claude Code resource intake command boundaries and import-decision sections.
- Ingest, including directory batch fixtures for `.txt`, `.md`, `.epub`, `.mobi`, and `.azw3`.
- Clean, including OCR-style spacing noise, advertisement/watermark removal, repeated blank collapse, and chapter detection.
- Decompose, generation, review.
- Pipeline TaskStatus and failed WorkflowRun recording.
- Pipeline run logs, recovery notes, and repeated sample cleanup.
- Automatic sample workspace updates during pipeline execution.
- Local asset search by category, type, tag, and keyword.
- Stricter semantic validation for feedback insight and workspace state shapes.
- End-to-end pipeline.

## Future ADR

Introduce pytest after dependency policy is approved.
