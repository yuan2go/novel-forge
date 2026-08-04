# Legacy Migration Codec Registry

The closed registry in `legacy_migration/codecs.py` contains **59 typed source
mappings**. They are not 59 domain migration implementations.

Every registry record declares:

- `materialization_level`;
- `domain_adapter` and `domain_validator`;
- `projection_strategy` and `activation_strategy`;
- schema envelope, stable identity and scope/reference rules;
- quarantine and reconciliation policy.

| Declared level | Count | Meaning |
|---|---:|---|
| `DOMAIN_NATIVE` | 18 | A real adapter is available for validation, Authority application, projection, approval/activation and reconciliation. |
| `ARCHIVAL_NATIVE` | 41 | Only immutable PostgreSQL AssetVersion archival is promised. |

Conversion always begins as `ARCHIVAL_NATIVE` with lifecycle `IMPORTED`,
eligibility `PENDING_EVALUATION`, and activation `NEEDS_REVIEW`. Legacy fields
such as `migration_approved=true` or `status=APPROVED` are retained only as
untrusted evidence. A DOMAIN_NATIVE declaration is a target capability; the
individual item is upgraded only after domain validation, explicit migration
approval, typed activation and reconciliation succeed.

Unknown source types fail closed and are quarantined. Missing, cross-project or
ambiguous required references cannot be downgraded to `reference_count` only;
they must resolve through the persisted two-pass reference table.

The complete type list and adapter coverage are in
`domain-native-migration-matrix.md`; the JSON registry is reproducible through
`TypedMigrationCodecRegistry.to_manifest()`.
