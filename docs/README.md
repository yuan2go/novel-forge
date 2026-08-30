# Canonical documentation

Novel Forge documentation is a projection of executable repository facts. Source code,
schema, migrations, runtime composition and tests outrank every sentence in this
directory.

The canonical prose set is intentionally limited to:

- `README.md` — thin repository entry point.
- `docs/README.md` — this allowlist and evidence policy.
- `docs/current-system.md` — current architecture, ownership and evidence ceiling.
- `docs/runtime-operations.md` — executable setup, migration, runtime and recovery
  procedures.
- `docs/development.md` — repository, documentation, comment and validation rules.

`architecture/reality-evidence.json` is the separately governed machine-readable
capability-to-code inventory. It is evidence for the prose set, not another prose
document.

`python -m novel_forge.tools.documentation_reality --repo-root .` validates this
allowlist, referenced files and symbols, evidence status, and comment policy. Any other
file under `docs/` fails the repository gate.

## Evidence rules

Capability status uses only `CODE_EXISTS`, `WIRED`, `EXECUTABLE`, `QUALIFIED`, and
`PRODUCTION_PROVEN`. Lower states never imply higher states. A class, fixture, test, or
scripted Provider route is not production evidence.

Design candidates are not current documentation. If an exceptional repository-local
proposal is explicitly authorized, it must be isolated from this directory and carry
all three labels: `PROPOSAL`, `NOT_IMPLEMENTED`, and `NOT_RUNTIME_AUTHORITY`. It must be
removed when accepted, rejected, or abandoned.
