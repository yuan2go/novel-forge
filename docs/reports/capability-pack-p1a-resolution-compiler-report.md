# Capability Pack P1A Resolution and Compiler Report

## 1. Identity and scope

- Date: 2026-08-05 (Asia/Shanghai)
- Branch: `feat/v7-content-intelligence-and-longform-proof`
- Reference baseline supplied by the task: `ef72563815a25ad51efc9be91b5138c2429ee1b5`
- Start HEAD used for implementation: `dcaf300057b997ac49099bcb4839f063774320ce`
- End implementation/tested HEAD: `3f2a6019f6086f73a2b8bd9fcd0a9bd995818711`
- Origin at completion time: `dfe4cb22ef671af66be9f47502dd254fe126aed3`
- Implementation commit: `3f2a6019f6086f73a2b8bd9fcd0a9bd995818711`
- Runtime profile used for compilation proof: `validation`
- Novel Forge version input: `6.0.0`
- Release channel: `VALIDATION`

The report commit necessarily follows the tested implementation commit. The
compiled identity below remains bound to the implementation commit and does not
claim that the report-only commit was compiled. No remote push was performed.

## 2. Changed files

Protocol, resolution, and compiler:

- `src/novel_forge/modules/capability_packs/__init__.py`
- `src/novel_forge/modules/capability_packs/artifacts.py`
- `src/novel_forge/modules/capability_packs/compiler.py`
- `src/novel_forge/modules/capability_packs/errors.py`
- `src/novel_forge/modules/capability_packs/loader.py`
- `src/novel_forge/modules/capability_packs/operation_catalog.py`
- `src/novel_forge/modules/capability_packs/protocol.py`
- `src/novel_forge/modules/capability_packs/schema.py`
- `src/novel_forge/modules/capability_packs/semantic.py`
- `src/novel_forge/modules/capability_packs/type_catalog.py`
- `src/novel_forge/modules/capability_packs/validator.py`
- `src/novel_forge/modules/capability_packs/versioning.py`

Governed fixture artifacts:

- `config/capability_packs/chapter_generation_pack.json`
- `config/capability_packs/artifacts/chapter_generation_contract_catalog.json`
- `config/capability_packs/artifacts/chapter_generation_system_instruction.md`
- `config/capability_packs/artifacts/chapter_generation_template.md`

Tests and report:

- `tests/unit/test_capability_pack_validator.py`
- `tests/unit/test_capability_pack_resolution_compiler.py`
- `docs/reports/capability-pack-p1a-resolution-compiler-report.md`

No migration, Authority runtime, Production Execution runtime, API, CLI, or Web
file was changed.

## 3. P0 hardening and regression

The P0 loader and static validator now additionally reject:

- duplicate JSON keys;
- non-UTF-8 JSON, non-object roots, non-finite numbers, and files over 1 MiB;
- Skill dependency cycles;
- duplicate Evaluation Gate IDs and duplicate Tool bindings;
- Tool operation references outside the Workflow node set;
- enabled database/file access with an empty allowlist (`DENY_ALL`, never allow-all);
- invalid status/lifecycle/release-channel combinations;
- floating reference aliases including `latest`, `current`, `active-latest`,
  `stable`, `main`, `master`, `HEAD`, `tip`, `trunk`, and `nightly`.

P0 regression result: 77/77 tests passed on the implementation commit.

## 4. Capability Type and Tool policy catalogs

`CapabilityTypePolicyCatalog` is immutable and opens only
`production_workflow`. Its policy snapshot defines generation classification,
external-effect eligibility, Authority Operation and Attempt Fence requirements,
raw-source prohibition, audit level, and the allowed lifecycle/channel triples.

Unknown capability types are reported structurally and evaluated with an
unsupported, conservative policy while the validator collects the remaining
errors. They are not added to the supported catalog.

`ToolDefinitionCatalog` governs the minimum risk, exact allowed action,
audit/approval requirements, and matching Authority external-capability patterns.
For this fixture, both `model.provider.invoke` and `storage.object.put` require
`EXECUTE`; changing the former to `READ` fails compilation.

## 5. OperationDefinition truth source

The compiler does not maintain a Chapter Operation dictionary. The in-memory
catalog is populated by the existing `chapter_operation_definitions()` and
computes each semantic identity with the existing `definition_hash()`. A
read-only `RepositoryOperationDefinitionLoader` adapts the existing
`OperationDefinitionRepository.get()` boundary by preloading exact
`definition_name + definition_version` rows into an immutable memory snapshot;
the compiler itself receives no database handle.

The resolved snapshot retains:

- enabled state, family, handler key and handler contract version;
- execution mode, idempotency scope, and concurrency key template;
- application build ID and source commit SHA;
- command/result schemas and permissions;
- approval, retry, timeout, cancellation, compensation, irreversible-effect,
  policy, external-capability, and completion contracts;
- the existing Authority semantic definition hash.

Duplicate name/version rows must match the complete snapshot, not only the
semantic hash. Conflicts in `enabled`, build ID, or commit SHA fail closed.
`enabled` must be an exact JSON/Python boolean; truthy strings and integers are
rejected. Every compiled Operation snapshot must have the requested release SHA.

The 18 resolved definitions are:

| Node | Authority OperationDefinition | Capability |
|---|---|---|
| plan | `chapter.plan.materialize@2.2.0` | `planning.chapter.generate` |
| context | `chapter.context.build@2.2.0` | `retrieval.index.query` |
| draft | `chapter.draft.generate@2.2.0` | `prose.chapter.draft` |
| review | `chapter.review.evaluate@2.2.0` | `review.chapter.evaluate` |
| revision | `chapter.revision.apply@2.2.0` | `revision.chapter.revise` |
| rereview | `chapter.revision.review@2.2.0` | `review.chapter.evaluate` |
| canon_extraction | `chapter.canon.extract@2.2.0` | `canon.extract` |
| canon_proposal | `chapter.canon.propose_changes@2.2.0` | `canon.extract` |
| canon | `chapter.canon.update@2.2.0` | `canon.extract` |
| quality_structural | `chapter.quality.structural.evaluate@2.2.0` | `quality.intrinsic.judge` |
| quality_commercial | `chapter.quality.commercial.evaluate@2.2.0` | `quality.intrinsic.judge` |
| quality_source_originality | `chapter.quality.source_originality.evaluate@2.2.0` | `quality.originality.judge` |
| quality_longform | `chapter.quality.longform.evaluate@2.2.0` | `quality.intrinsic.judge` |
| quality_platform | `chapter.quality.platform.evaluate@2.2.0` | `quality.platform.judge` |
| quality | `chapter.quality.evaluate@2.2.0` | `quality.intrinsic.judge` |
| publish_gate | `chapter.publishing.prepare_release@2.2.0` | `publishing.release.query` |
| export | `chapter.export.render@2.2.0` | `storage.object.put` |
| final_release_gate | `chapter.publishing.finalize_release@2.2.0` | `publishing.release.query` |

Scheduler dependencies, `ChapterNode` stage/handler identity, primary output,
Capability Registry identity, and the OperationDefinition snapshot are all
compared independently. Any drift returns a structured hard error.

## 6. Artifact resolution sources

The resolver is an exact-key, local-only, immutable catalog. It does not read
environment variables, access the network, expand `$ref`, or infer filenames.

Resolved source classes:

- Skill artifacts: actual root `skills/*/SKILL.md` files, UTF-8 decoded and
  canonical-hashed;
- Prompt system instruction/template: the two signed-in repository Markdown
  artifacts under `config/capability_packs/artifacts/`;
- Schema, protocol, context/source/tool/validation/commit/timeout/budget/
  approval/compensation policy, and rule artifacts: exact versioned entries in
  `chapter_generation_contract_catalog.json`;
- Capability definitions: the existing Production Execution
  `default_capability_registry()` and its contract hashes;
- Operation definitions: the existing Chapter Authority definition factory or
  a preloaded read-only PostgreSQL repository snapshot.

The resolver recomputes canonical content hashes. Duplicate exact identities
must also have identical provenance. Canonical artifact JSON forbids NaN and
infinities. The state contract separately represents the real Kernel
`OperationStatus`, `AttemptStatus`, and the current PostgreSQL Saga status set;
SHA-256 patterns explicitly require string values.

The current fixture resolved 51 Artifact bindings. Skill and Prompt hashes in
the Manifest are compared to real content. Other resolved contracts have their
content hash frozen into the Catalog Snapshot and Compilation Hash; where a
Manifest also declares the same policy constraint, cross-section validation
compares the resolved policy content rather than trusting the ref alone.

## 7. Version resolver

`CapabilityPackVersionResolver` takes the exact Pack identity, protocol,
Novel Forge version, release SHA, runtime profile, channel, explicit dependency
versions, and a read-only Pack Catalog. It rejects:

- protocol/build/runtime-profile/channel incompatibility;
- disabled or retired Packs;
- missing, floating, incompatible, or cyclic dependencies;
- Manifest upstream declarations that differ from injected exact dependencies;
- duplicate Pack identity with different Manifest content or dependency set;
- multiple versions of one `pack_id` in a single resolution closure;
- a root Catalog Manifest hash different from the Manifest supplied to the
  compiler.

No database Pack Registry was added.

## 8. Cross-section semantic validation

The semantic pass runs after structural validation and collects structured
errors for:

- missing/disabled/drifted OperationDefinitions;
- handler, stage, Capability, Scheduler dependency, primary-output, retry,
  approval, compensation, timeout, schema, external-effect, and completion
  conflicts;
- Workflow input assets without an ancestor producer or declared external input;
- Completion output/evidence without an Authority producer;
- blocking Evaluation gates disconnected from completion/downstream decisions;
- required Capability omissions and unknown Judge capabilities;
- Tool actions or node bindings incompatible with the OperationDefinition
  external-capability contract;
- Context, Tool, Source, Rule, approval, compensation, and timeout policy content
  that differs from the Manifest constraint;
- missing, wrong-kind, wrong-version, floating, or hash-drifted Artifacts.

Workflow and Skill cycle detection is deterministic and returns structured
reports; recursive asset analysis has its own visiting guard and cannot turn an
authoring cycle into `RecursionError`.

## 9. Chapter Pack drift discovered and corrected

Authority definitions remained unchanged. The fixture was corrected because it
contained a second, contradictory set of runtime semantics:

1. The five Skill hashes were not hashes of the actual root Skill files. They
   now bind the repository content.
2. Prompt hashes had no resolvable Prompt refs or exact versions. Explicit
   system/template refs, versions, files, and real hashes were added.
3. Workflow nodes lacked the current Authority `definition_hash`; all 18 now
   carry the expected semantic hash.
4. Manifest retry counts varied between 1, 2, and 3 and listed provider-specific
   retry errors. Authority definitions specify `max_attempts=2`; the fixture now
   treats this as an expected constraint and does not create a second retry
   controller.
5. Node approval refs implied independent admission rules, including a required
   Canon admission approval. Current OperationDefinitions specify
   `approval.required=false`; the fixture now binds the common admission policy.
   Business quality/release gates remain separate and are not weakened.
6. Several nodes declared runtime compensation. Current definitions specify
   `supported=false` with append-only evidence; the fixture now matches that
   truth source.
7. Context input named `chapter_production_input_manifest`; the Authority
   completion selector is `production_input_manifest`, so the asset flow was
   corrected.
8. Empty database/file allowlists are now paired with access disabled and are
   explicitly interpreted as `DENY_ALL`.
9. Tool bindings were checked bidirectionally against real model/object-store
   external capabilities and restricted to exact `EXECUTE` actions.

The meaning of Manifest runtime fields is now explicit:

- `operation_definition_hash`, retry/approval/compensation bindings, and output
  types are expected constraints checked against Authority truth;
- timeout, Context, Source, Tool, Validation, Commit, Budget, and governance refs
  are exact governed Artifact bindings;
- node order/dependencies are an expected Scheduler graph and deterministic
  compilation input;
- no Manifest field directly controls an Authority Operation at P1A.

## 10. Immutable compiled snapshot

The frozen/slots `CompiledCapabilityPack` uses schema
`novelos.capability_pack.compiled.v1`. It contains:

- Pack/protocol/runtime profile/build/channel/release identities;
- Capability Type policy and resolved Capability contract hashes;
- complete resolved OperationDefinition snapshots and hashes;
- resolved Artifact refs, versions, hashes, and repository-relative provenance;
- deterministic topological node plan;
- external input, completion, Tool, Context/Source, Evaluation, Audit, and exact
  dependency-resolution snapshots;
- Catalog Snapshot Hash and Compilation Hash.

`to_dict()` returns detached JSON. Frozen dataclasses and immutable tuples/JSON
strings prevent mutation of the compiled identity. Catalog inputs are sorted by
identity; duplicate identity conflicts fail closed. Time, UUID, run/attempt IDs,
local absolute paths, environment values, and provider results are absent.

Compilation proof bound to the implementation commit:

| Field | Value |
|---|---|
| Schema | `novelos.capability_pack.compiled.v1` |
| Pack | `chapter_generation_pack@1.0.0` |
| Release SHA | `3f2a6019f6086f73a2b8bd9fcd0a9bd995818711` |
| Manifest Hash | `sha256:69fd8bd943a434e9418cc8d18527f78821fe4574c78f88e59b3aa8b8974136fe` |
| Catalog Snapshot Hash | `sha256:1988feba4ef3af0e4c40469eb65353361df508fdcfed557261ef704ef09e4b88` |
| Compilation Hash | `sha256:23d9393d2123c0bfead97c6ff5ec08082b66580813c7dd31ed541f9dc686912d` |
| Workflow nodes | 18 |
| Resolved operations | 18 |
| Resolved capabilities | 11 |
| Resolved artifacts | 51 |

The release SHA is an explicit trusted build input and is cross-checked against
every OperationDefinition snapshot. The pure compiler does not invoke Git; the
caller remains responsible for constructing catalogs from the checkout named by
that SHA. Artifact and Catalog content hashes make that input auditable.

## 11. Test evidence

All results below are from implementation commit
`3f2a6019f6086f73a2b8bd9fcd0a9bd995818711`.

| Command | Result | Test/tool duration |
|---|---|---:|
| `PYTHONPATH=src python3 -m unittest tests.unit.test_capability_pack_validator` | PASS, 77/77 | 9.954 s |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_capability_pack_resolution_compiler` | PASS, 53/53 | 1.057 s |
| `PYTHONPATH=src python3 -m compileall -q src tests` | PASS | 0.310 s wall |
| `make architecture-manifests-check` | PASS; module/migration/worker/test/console manifests | 4.386 s wall |
| `make architecture-fitness-check` | PASS; 0 violations | 7.058 s wall |
| `make head-integrity-check` | PASS; 0 missing/untracked required paths | 3.092 s wall |
| `ruff check src/novel_forge/modules/capability_packs tests/unit/test_capability_pack_validator.py tests/unit/test_capability_pack_resolution_compiler.py` | PASS | 0.083 s wall |
| `git diff --check` | PASS | <0.001 s wall |

The dual read-only final review reported no remaining P0 or P1 findings after
the final fixes. No tests were deleted or weakened.

## 12. Not executed or blocked

- Full PostgreSQL integration suite: `NOT_EXECUTED` — P1A creates no database
  state or migration and is intentionally a pure compile boundary.
- Provider/long-form/multi-book tests: `NOT_EXECUTED` — prohibited and outside
  P1A; no provider credential was read.
- Remote CI: `NOT_EXECUTED` — the task explicitly requires no push.
- Runtime binding/Authority admission execution: `NOT_EXECUTED` — P1A explicitly
  stops before runtime integration.

There were no blocked preconditions for the required P1A commands.

## 13. Design deviations and boundaries

- The repository does not yet expose one authoritative store for every Schema,
  Policy, Protocol, and Prompt artifact. P1A therefore adds an explicit,
  versioned, read-only repository Catalog with real contract content. It does
  not create hash-only placeholder assets and does not claim database authority.
- PostgreSQL OperationDefinitions can be loaded through the existing repository,
  but loading is deliberately separated from compilation. The compiler receives
  the immutable preloaded snapshot so compilation cannot perform database I/O.
- The existing Capability Registry remains the only Capability Definition
  registry. Capability Type Policy and Tool Definition catalogs govern different
  concerns and do not copy Capability definitions.
- Authority retry, approval, compensation, external-effect, and completion
  policies remain runtime truth. Manifest values are drift constraints or exact
  Artifact refs, not independent controllers.

## 14. Not implemented and P1 recommendations

Not implemented in P1A:

- Runtime Binding or ProductionExecutionGateway submission;
- Pack Registry, Pack Run, Pack Attempt, Pack lease/fence, or a second state machine;
- database persistence or migrations;
- API, CLI, Web, provider execution, canary, or Pack migration;
- Chapter Authority/Scheduler/Saga/Attempt behavior changes.

Recommended later work, not implemented here:

1. Add a PostgreSQL-backed, signed Capability Pack release registry that stores
   immutable Manifest/Compilation identities without creating a Pack runtime.
2. Add Authority admission binding that accepts only an exact compiled snapshot
   and reuses existing Operation/Attempt/Fence state.
3. Promote local Schema/Policy/Protocol artifacts to governed AssetVersion-backed
   releases while retaining the same resolver protocol and hashes.
4. Add Pack dependency lockfiles/release attestations and build orchestration that
   verifies the checkout SHA before invoking this pure compiler.
5. Add runtime conformance tests only in P1B/P2, without changing the existing
   Chapter node order or creating Pack Run/Attempt state.

## 15. Evidence status

```text
p0_regression_passed=true
duplicate_json_keys_rejected=true
skill_dependency_cycle_validated=true
cross_section_semantics_validated=true
capability_type_catalog_defined=true
operation_catalog_reuses_authority_definitions=true
operation_definition_drift_rejected=true
artifact_versions_resolved=true
artifact_hashes_verified=true
version_resolver_defined=true
deterministic_compiler_output=true
compiled_snapshot_immutable=true
chapter_generation_pack_compiled=true
runtime_behavior_unchanged=true
runtime_integrated=false
database_migration_added=false
pack_run_state_added=false
pack_attempt_state_added=false
real_provider_executed=false
longform_proven=false
multi_book_proven=false
production_verified=false
```
