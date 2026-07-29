# Authority Parity Manifest

> Source: `config/authority/authority-parity-manifest.json`

The manifest is the machine-readable compatibility contract between the twelve
actual `CHAPTER_PRODUCTION_STEPS` in the Legacy Chapter Production Bus and the
PostgreSQL Chapter Authority graph. It is a many-to-many capability map, not a
name comparison.

Each record declares the business capability, Authority command, Operation
definitions, registered handlers, input/output contracts and AssetVersions,
ExternalEffects, idempotency/retry/cancel/timeout/lease/fence policies, failure
classification, recovery, Projection, evidence, production status, evidence
grade, and known gap.

Supported evidence grades are:

```text
NOT_MAPPED
PARTIALLY_MAPPED
MAPPED_NOT_TESTED
TESTED_WITH_FAKE
TESTED_WITH_REAL_PROVIDER
PRODUCTION_PROVEN
DEPRECATED
```

The loader and validator in
`src/novel_forge/tools/authority_parity_manifest.py` verify:

- exact coverage of source-code Legacy steps;
- no duplicate step records;
- registered OperationDefinitions and handlers;
- non-empty formal output contracts;
- no selected production boundary direct-write bypass;
- truthful separation of fixture/integration/real-provider/production evidence.

Run:

```bash
make authority-parity-check
```

The command prints JSON and returns non-zero on a gap. `production_enabled`
means an Authority mapping is enabled; it does not upgrade
`TESTED_WITH_FAKE` to real Provider or production proof.
