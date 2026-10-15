# Frozen PR conflict reconciliation

Historical audit snapshot; NOT_RUNTIME_AUTHORITY. Evidence ceiling: CODE_EXISTS / WIRED
source inspection only. Tests, hooks, builds, database migrations, recovery execution,
Provider calls and production qualification: NOT_RUN_BY_USER_REQUEST.

## Frozen sources and prior integration

- Main baseline: `c1408f0e2478b42bedf8ee925703aaa01fa9713e`.
- PR #133: `b333b08a02accac3a01e42fd252beb15784c682b` (46 ancestry-only missing commits).
- PR #135: `c9c7fc1d9a6d8a2dde715890105990d02a37d657` (71 ancestry-only missing commits).
- PR #173: `f06f4daccada314b25f7559733ad331d5c056da0` (5 missing source commits).
- The three exact heads contribute 122 distinct historical commits outside baseline main;
  this is not a count of newly implemented features or newly authored commits.

The live GitHub record for merged PR #138 explicitly names the same exact #133/#135
heads. Its head is `d4382d36afdcd614a4693f0686d82c690d4d14c5`, and its merge
`3c4d6dc5fa5370288bad6e1302b4b3fd5e80b5df` is an ancestor of baseline main.
The implementation commits `9fc34231e77a636272bb582e0e745de5571d1d35` and
`2e4db4ecdb8e3d9f7f10f1e55cb246143777dc42` remain reachable and contain the
coordinated native runtime changes and forward migrations 0169–0180.

Current registered successors retain World agency/host/projection (0169–0171), failed
step successor v2 (0172), retained graph (0173), Quality namespace (0174), Canon output
repair (0175), Quality correction control (0176), realization uncertainty (0177), Planning
reference contract (0178), Arc scope (0179) and Foundation direction (0180).
Earlier conflicting source migrations and superseded modules/tests are not restored as
active implementations. Native planning repair now belongs to Story Planning Runtime,
not Production Execution. The current owner implementation and SQL guards take precedence
over older exports. Reconciliation of #133/#135 therefore retains the current main tree
and adds their exact parents to history, rather than reapplying obsolete SQL contracts.

## #173 conflict decisions

- Preserve main's manuscript runtime environment, accepted/current/retained source
  resolver, original history transport, and richer retained-working fixtures.
- Retain incoming exact World accounting, prior Chapter method-audit references and
  nested canonical-string transport. Existing history accounting remains in the
  protected-envelope accounting path; v1 and v2 retain separate contract markers.
- Preserve current World input-delivery recovery, capacity inheritance and all nine
  existing common-guard dispatch predicates. Append only the two new distinct
  World exact-accounting and Chapter prior-audit predicates.
- Keep every pre-existing migration body byte-identical (236 files, excluding package
  registries). Preserve all frozen source migration identities; never register the
  foreign branch chain as an alternative main chain.
- Append active main `20261015_0219_world_exact_context_convergence` after
  `20261015_0218_retained_working_convergence`, then
  `20261015_0220_chapter_prior_audit_convergence`. Both require backup and are forward-only.
  Registry, manifest, code-reality projection and canonical operating text agree.
- Foreign/discontinuous applied histories still fail closed. No applied history,
  original failure, body text, accepted cursor, receipt, lease or execution ledger is rewritten.

Static metadata and SQL text assembly found 221 unique registered migration identities,
unchanged main guard dispatches plus exactly two additions, and no conflict markers or
Python parse errors in changed source. These are source inspections, not PostgreSQL
execution, tests, deployment or new runtime qualification.

## Historical source and execution preservation

The Git archive exports retain every added/modified source path at each old exact head,
including original migrations, test source, execution JSON and the PR #135 prose files.
They are frozen historical evidence, not current production inputs, new test results or
claims of formal acceptance. Existing main prose and execution artifacts remain unchanged.

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `pr133-frozen-source.zip` | 173 | `bd8cd36283d2d89ab47379aa15d8748448fabe2e6ccf383e018ca1d7e010249d` |
| `pr135-frozen-source.zip` | 212 | `5bc720f0353852baa61d89655289308c852870174b36b88213e472d5c5602238` |

Credential-pattern inspection of exported contents found no matching private-key,
GitHub token or long OpenAI-style secret patterns; this is not a comprehensive security audit.
Original dirty worktrees and active databases/workers are outside this integration and
remain untouched. Applying migrations and complete applicable runtime verification require
a later separately authorized operation.
