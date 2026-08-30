# P0 Backend Engineering Qualification and CI Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one exact-SHA, backend-only, fail-closed P0 qualification path that proves the current PostgreSQL Authority implementation and scripted Compose runtime, emits machine-readable evidence, and is used unchanged by local execution and CI.

**Architecture:** A thin qualification orchestrator will coordinate existing migration, Authority application, PostgreSQL integration, query-plan, worker-health, Compose, and release-evidence seams. A versioned qualification manifest will classify every pytest collection and semantic proof slice; JUnit XML plus a pytest collection report will be the only authority for test counts, durations, outcomes, and skips. Run-scoped PostgreSQL and Compose resources will use Docker-assigned ports, UUID identities, labels, recorded resource IDs, and ownership-checked teardown.

**Tech Stack:** Python 3.12, pytest 8 built-in JUnit XML, psycopg 3, PostgreSQL 16 with pgvector, Docker Compose v2, Make, GitHub Actions, JSON-compatible YAML manifests, Ruff.

## Global Constraints

- The unique implementation baseline is `origin/main@6b8ed04928bc40a7b347c93db4adaf1db72435d7` in `/Users/yuan/projects/novel-forge-worktrees/p0-backend-qualification-ci-implementation-01` on `codex/p0-backend-qualification-ci-implementation-01`.
- The expected migration head is read from `architecture/manifests/migration-manifest.yaml` and cross-checked with the existing migration registry; `20260829_0104_book_opening_workflow_nodes` is only the baseline fact.
- PostgreSQL, Compose project, database, ports, artifact root, and resource ownership are qualification-run scoped; cleanup must verify ownership before mutation.
- The full `tests/integration` pytest collection is PostgreSQL-required. Qualification never selects PostgreSQL tests with curated filename globs.
- Pytest counts, durations, failures, errors, and skips come only from JUnit XML; complete collection identity comes from a machine-readable pytest hook report.
- The resolved Python dependency snapshot digest is part of qualification identity. The report must state that Git SHA alone does not reproduce an unlocked dependency environment.
- Existing migration utilities, Authority applications, worker health projection, query-plan tool, Compose probe, worker E2E, and release evidence are extended and reused; no second runtime, health, migration, or domain Authority is introduced.
- The backend qualification target must not invoke npm, and authoritative backend CI must not depend on `web`. Current Admin UI is `DEFERRED / NOT_RUN_BY_SCOPE` and its source is not expanded.
- CI removes `authority-parity-check`; local and CI invoke the same `make p0-backend-qualification` entry.
- Every new runner, evidence, cleanup, redaction, safety, and gate behavior is introduced red-first. A real backend defect requires a regression at the nearest public seam before a bounded fix.
- Complete qualification is rerun from zero only after all implementation commits exist, against the clean final implementation SHA; evidence is stored outside the tracked tree.
- Remote green and branch governance are separate operational Exit Gates. Required-check protection is not enabled or claimed until the exact final SHA is remotely green.
- `REAL_PROVIDER`, `HISTORICAL_ORPHAN_MUTATION`, `EIGHT_CHAPTER`, `HUMAN_REVIEW`, `LONGFORM`, `MULTIBOOK`, and `PRODUCTION` remain `NOT_RUN_BY_SCOPE` or `NOT_PROVEN` in every report.
- Do not redesign Novel OS, add product behavior, create UI/API compatibility work, or change current Admin pages.

---

## File Structure

### New files

- `architecture/manifests/backend-qualification-manifest.yaml` — versioned classification of canonical backend pytest collections, semantic proof slices, required gates, and evidence ceilings.
- `src/novel_forge/tools/backend_qualification_contract.py` — manifest loader, migration-head cross-check, dependency snapshot digest, JUnit parser, collection completeness validator, redaction, and report invariants.
- `src/novel_forge/tools/pytest_collection_evidence.py` — pytest plugin that writes collected node IDs and source paths as atomic JSON without parsing terminal output.
- `src/novel_forge/tools/backend_qualification_resources.py` — run identity, disposable DSN policy, Docker-assigned port resolution, Compose resource discovery, ownership receipt, and fail-closed cleanup.
- `src/novel_forge/tools/backend_qualification.py` — public CLI/orchestrator, bounded subprocess lifecycle, ordered gates, cleanup finalizer, and final evidence assembly through `release_run_evidence`.
- `scripts/run_p0_backend_qualification.py` — import-only executable shim for the public orchestrator.
- `compose.qualification.yml` — qualification-only labels and Docker-assigned host ports layered over existing Compose definitions.
- `tests/unit/test_backend_qualification_contract.py` — migration, dependency, JUnit, collection, redaction, and ceiling contract tests.
- `tests/unit/test_pytest_collection_evidence.py` — public pytest-plugin output/atomicity tests.
- `tests/unit/test_backend_qualification_resources.py` — DSN rejection, UUID identity, ownership mismatch, cleanup, and dynamic-port parsing tests.
- `tests/unit/test_backend_qualification.py` — public CLI, gate ordering, timeout, failure, cleanup, exact-SHA, and report tests using a recording process boundary.
- `tests/architecture/test_backend_qualification_boundaries.py` — no npm/web dependency, no stale command, manifest coverage, and no real-provider/historical mutation assertions.

### Modified files

- `architecture/manifests/test-manifest.yaml` — add explicit qualification class and complete-collection policy to all four current collection roots.
- `src/novel_forge/tools/architecture_manifest.py` — validate classification coverage and the backend qualification manifest without stdout-derived authority counts.
- `scripts/check_required_test_manifest.py` — keep the existing public manifest entry while delegating to the strengthened checker.
- `scripts/run_authority_postgres_tests.py` — replace filename globs and in-process skip tracking with the complete integration root, JUnit XML, collection JSON, and fail-closed validation.
- `tests/integration/conftest.py` — reuse the production-grade disposable database validator while preserving existing migration/truncation behavior.
- `compose.postgres-test.yml` — parameterize run-scoped database identity, use Docker-assigned host port, and label the owned service/network.
- `scripts/verify_authority_compose.py` — add run identity/ownership guard, atomic output, dynamic ports, post-restart subsequent operation, authoritative side-effect assertions, and cleanup evidence.
- `src/novel_forge/tools/worker_fleet_evidence.py` — require distinct pre-restart and post-restart work plus authoritative side-effect evidence.
- `scripts/verify_authority_worker_e2e.py` — reuse the shared run-resource contract and emit the strengthened worker evidence fields.
- `tests/unit/test_worker_fleet_evidence.py` — reject restart/readiness-only evidence and require post-restart work success.
- `src/novel_forge/tools/release_run_evidence.py` — add atomic P0 report finalization and exact-SHA/dependency/migration/ceiling validation while preserving existing release evidence builders.
- `tests/unit/test_release_run_evidence.py` — cover the new P0 aggregate and reject intermediate-SHA, missing digest, non-manifest head, unsafe cleanup, and raised proof ceilings.
- `Makefile` — add backend-only public qualification targets, remove fixed-port defaults, and keep npm outside the canonical backend path.
- `.github/workflows/core-os-ci.yml` — invoke the common backend target, upload JUnit/JSON artifacts, remove stale commands and duplicate stdout-based gates, and remove `web` from authoritative dependencies.
- `tests/unit/test_core_os_characterization.py` — characterize the new stable required-check name and common-entry contract.
- `README.md` — replace `.[dev]`, document the backend entry, dependency evidence limit, and deferred UI.
- `docs/operations/local-development.md` — document dynamic resources, safe cleanup, artifact layout, and backend/UI separation.
- `docs/development/testing.md` — make the backend qualification path canonical and classify UI as deferred.

## Canonical Interfaces

The tasks below must use these names consistently:

```python
@dataclass(frozen=True)
class QualificationManifest:
    schema_version: str
    migration_manifest: Path
    pytest_collections: tuple[PytestCollectionContract, ...]
    required_gates: tuple[str, ...]
    semantic_slices: Mapping[str, tuple[str, ...]]
    evidence_ceilings: Mapping[str, str]

def load_qualification_manifest(repo_root: Path) -> QualificationManifest: ...
def expected_migration_head(repo_root: Path) -> str: ...
def resolved_dependency_snapshot(python: str) -> dict[str, object]: ...
def parse_junit_xml(path: Path) -> dict[str, object]: ...
def validate_collection_report(*, contract: PytestCollectionContract, report_path: Path, repo_root: Path) -> dict[str, object]: ...
def sanitize_evidence(value: object) -> object: ...

@dataclass(frozen=True)
class QualificationRunIdentity:
    run_id: str
    compose_project: str
    database_name: str
    artifact_root: Path

class OwnedComposeProject:
    def assert_unclaimed(self) -> None: ...
    def capture(self) -> dict[str, tuple[str, ...]]: ...
    def assert_owned(self) -> dict[str, tuple[str, ...]]: ...
    def cleanup(self) -> dict[str, object]: ...

def run_qualification(argv: Sequence[str] | None = None, *, process_runner: ProcessRunner | None = None) -> int: ...
def build_p0_backend_qualification_report(*, tested_sha: str, source_tree: str, manifest: Mapping[str, object], dependency_snapshot: Mapping[str, object], gates: Sequence[Mapping[str, object]], cleanup: Mapping[str, object]) -> dict[str, object]: ...
```

### Task 1: Canonical Qualification Manifest and Test Classification

**Files:**
- Create: `architecture/manifests/backend-qualification-manifest.yaml`
- Create: `src/novel_forge/tools/backend_qualification_contract.py`
- Modify: `architecture/manifests/test-manifest.yaml`
- Modify: `src/novel_forge/tools/architecture_manifest.py`
- Test: `tests/unit/test_backend_qualification_contract.py`
- Test: `tests/architecture/test_backend_qualification_boundaries.py`

**Interfaces:**
- Consumes: existing JSON-compatible YAML loader pattern in `novel_forge.tools.architecture_manifest`.
- Produces: `load_qualification_manifest(repo_root: Path) -> QualificationManifest`; explicit full-root PostgreSQL classification; semantic slice node/file prefixes used by final evidence.

- [ ] **Step 1: Add failing manifest classification tests**

```python
def test_integration_collection_is_complete_and_postgresql_required() -> None:
    manifest = load_qualification_manifest(ROOT)
    integration = next(item for item in manifest.pytest_collections if item.name == "integration")
    assert integration.paths == ("tests/integration",)
    assert integration.classification == "POSTGRESQL_REQUIRED"
    assert integration.complete_collection is True
    assert integration.allow_skips is False

def test_every_pytest_collection_has_exactly_one_qualification_class() -> None:
    result = check_tests(ROOT)
    assert result["kind"] == "tests"
    assert {item["classification"] for item in result["collections"]} == {
        "BACKEND_NON_POSTGRESQL",
        "POSTGRESQL_REQUIRED",
    }
```

- [ ] **Step 2: Run the focused tests and confirm red**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification_contract.py tests/architecture/test_backend_qualification_boundaries.py -q`

Expected: FAIL because the manifest loader and qualification classification fields do not exist.

- [ ] **Step 3: Add the versioned manifest and loader**

The manifest must name these complete roots, not filename subsets:

```json
{
  "schema_version": "novel-forge.backend-qualification-manifest.v1",
  "migration_manifest": "architecture/manifests/migration-manifest.yaml",
  "pytest_collections": [
    {"name": "architecture", "paths": ["tests/architecture"], "classification": "BACKEND_NON_POSTGRESQL", "complete_collection": true, "allow_skips": false},
    {"name": "unit", "paths": ["tests/unit"], "classification": "BACKEND_NON_POSTGRESQL", "complete_collection": true, "allow_skips": false},
    {"name": "acceptance", "paths": ["tests/acceptance"], "classification": "BACKEND_NON_POSTGRESQL", "complete_collection": true, "allow_skips": false},
    {"name": "integration", "paths": ["tests/integration"], "classification": "POSTGRESQL_REQUIRED", "complete_collection": true, "allow_skips": false}
  ]
}
```

Add exact semantic slices for fresh/upgrade migration, Book Opening workflow/recovery, provider hard-stop/callback, and the backend vertical slice. These are proof-claim requirements layered on top of the complete integration execution, never the selection mechanism.

- [ ] **Step 4: Strengthen `check_tests`**

Validate that every collection in `test-manifest.yaml` maps exactly once to the qualification manifest, every tracked `test_*.py` source lies under exactly one declared collection root, the complete `tests/integration` root is PostgreSQL-required, and no PostgreSQL-required collection permits skips. Task 2 adds node-level machine collection evidence without changing this classification contract.

- [ ] **Step 5: Run the focused and manifest gates**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification_contract.py tests/architecture/test_backend_qualification_boundaries.py -q && PYTHONPATH=src python scripts/check_required_test_manifest.py`

Expected: PASS; the checker reports one complete `POSTGRESQL_REQUIRED` integration collection and three complete backend non-PostgreSQL collections.

- [ ] **Step 6: Commit**

```bash
git add architecture/manifests/backend-qualification-manifest.yaml architecture/manifests/test-manifest.yaml src/novel_forge/tools/architecture_manifest.py tests/unit/test_backend_qualification_contract.py tests/architecture/test_backend_qualification_boundaries.py
git commit -m "test: define complete backend qualification collections"
```

### Task 2: Machine-Readable Pytest Evidence and Qualification Identity

**Files:**
- Create: `src/novel_forge/tools/pytest_collection_evidence.py`
- Modify: `src/novel_forge/tools/backend_qualification_contract.py`
- Test: `tests/unit/test_pytest_collection_evidence.py`
- Test: `tests/unit/test_backend_qualification_contract.py`

**Interfaces:**
- Consumes: `QualificationManifest` and pytest hook APIs.
- Produces: `--novel-forge-collection-report PATH`; `parse_junit_xml`; `validate_collection_report`; `expected_migration_head`; `resolved_dependency_snapshot`.

- [ ] **Step 1: Write red tests for JUnit authority, migration head, dependencies, and redaction**

```python
def test_junit_is_the_only_test_count_authority(tmp_path: Path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text('<testsuites tests="3" failures="0" errors="0" skipped="1" time="1.25"><testsuite tests="3" failures="0" errors="0" skipped="1" time="1.25"/></testsuites>')
    assert parse_junit_xml(junit) == {
        "tests": 3, "passed": 2, "failures": 0, "errors": 0,
        "skipped": 1, "duration_seconds": 1.25,
    }

def test_expected_head_comes_from_manifest_and_matches_runtime_registry() -> None:
    assert expected_migration_head(ROOT) == json.loads((ROOT / "architecture/manifests/migration-manifest.yaml").read_text())["head"]

def test_dependency_snapshot_is_sorted_hashed_and_disclaims_sha_only_reproduction() -> None:
    snapshot = resolved_dependency_snapshot(sys.executable)
    assert snapshot["digest"].startswith("sha256:")
    assert snapshot["git_sha_alone_reproducible"] is False
    assert snapshot["reproducibility_class"] in {"RESOLVED_SNAPSHOT", "CONSTRAINTS_BOUND_RESOLVED_SNAPSHOT"}
```

- [ ] **Step 2: Confirm red**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification_contract.py tests/unit/test_pytest_collection_evidence.py -q`

Expected: FAIL at the missing parser/plugin and identity functions.

- [ ] **Step 3: Implement the pytest hook report**

At `pytest_collection_finish`, write a sibling temporary JSON file and `os.replace` it into the requested path. Record schema version, rootdir, sorted node IDs, sorted source files, collected count, and collection errors. Never parse pytest stdout.

- [ ] **Step 4: Implement strict JUnit parsing**

Use `xml.etree.ElementTree`; reject missing files, malformed XML, negative counters, inconsistent totals, and nonzero skip when the collection contract forbids skips. Derive `passed = tests - failures - errors - skipped` and reject a negative result.

- [ ] **Step 5: Implement manifest-derived migration and dependency identity**

Read `head` from the canonical migration manifest, call existing `validate_migration_chain`, and require equality with `LATEST_MIGRATION_ID`. Resolve dependencies with `[python, "-m", "pip", "freeze", "--all"]`, normalize/sort nonempty lines, hash the UTF-8 snapshot, record constraints/lock presence, and explicitly set `git_sha_alone_reproducible` to false when none exists.

- [ ] **Step 6: Implement recursive evidence sanitization**

Reject keys matching `password`, `secret`, `token`, `credential`, `api_key`, `database_url`, or `dsn`; redact PostgreSQL URLs and credential-bearing URI authority sections inside string values before evidence persistence.

- [ ] **Step 7: Run focused tests and a real pytest evidence probe**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification_contract.py tests/unit/test_pytest_collection_evidence.py -q --junitxml=/tmp/nf-p0-contract.xml -p novel_forge.tools.pytest_collection_evidence --novel-forge-collection-report=/tmp/nf-p0-contract-collection.json`

Expected: PASS; both files parse as structured XML/JSON and contain no stdout-derived counters.

- [ ] **Step 8: Commit**

```bash
git add src/novel_forge/tools/backend_qualification_contract.py src/novel_forge/tools/pytest_collection_evidence.py tests/unit/test_backend_qualification_contract.py tests/unit/test_pytest_collection_evidence.py
git commit -m "feat: add machine-readable qualification evidence"
```

### Task 3: Run-Scoped PostgreSQL and Ownership-Checked Resources

**Files:**
- Create: `src/novel_forge/tools/backend_qualification_resources.py`
- Create: `compose.qualification.yml`
- Modify: `compose.postgres-test.yml`
- Modify: `tests/integration/conftest.py`
- Test: `tests/unit/test_backend_qualification_resources.py`

**Interfaces:**
- Consumes: Docker Compose project labels, `psycopg.conninfo.conninfo_to_dict`, and existing integration migration fixtures.
- Produces: `QualificationRunIdentity.create`; `validate_disposable_database_url`; `OwnedComposeProject`; Docker-assigned port resolution.

- [ ] **Step 1: Add red safety tests**

```python
def test_run_identity_is_uuid_scoped_and_test_database_is_disposable(tmp_path: Path) -> None:
    identity = QualificationRunIdentity.create(commit_sha="a" * 40, artifact_parent=tmp_path)
    assert identity.compose_project.startswith("nf-p0-")
    assert identity.database_name.startswith("nf_p0_")
    assert identity.database_name.endswith("_test")

def test_cleanup_refuses_unowned_resource_ids(fake_docker: FakeDocker, tmp_path: Path) -> None:
    project = owned_project(fake_docker, tmp_path)
    project.capture()
    fake_docker.add_foreign_container(project.project_name)
    with pytest.raises(ResourceOwnershipError, match="resource set changed"):
        project.cleanup()
    assert fake_docker.down_calls == []
```

- [ ] **Step 2: Confirm red**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification_resources.py -q`

Expected: FAIL because run identity and owned Compose lifecycle are absent.

- [ ] **Step 3: Implement immutable run identity and DSN policy**

Generate a lowercase UUID token once. Derive project/database/artifact names from that token, validate full lowercase SHA, reject non-loopback hosts for local qualification, reject protected/historical database names, require the exact run-owned database name, and expose only a SHA-256 server identity digest in evidence.

- [ ] **Step 4: Implement Docker-assigned ports**

Use Compose long port syntax with `published: "0"` in qualification files. Resolve the actual port only after service creation by obtaining the Compose container ID and parsing the full JSON returned by `docker inspect`; never reserve/release a guessed port and never scan human progress output.

- [ ] **Step 5: Implement ownership receipt and checked cleanup**

Before `up`, require zero resources for the UUID project label. After creation, capture exact container, volume, and network IDs plus both `com.docker.compose.project` and `novel-forge.qualification.run-id` labels into an atomic receipt. Before `down --volumes --remove-orphans`, enumerate again and require every resource to carry the run label and project label; refresh IDs after controlled restart and reject unknown IDs. Record cleanup `PASS` or `FAIL` separately.

- [ ] **Step 6: Reuse the validator in integration preflight**

Keep existing `require_disposable_test_database`, migration, and truncation behavior. Replace duplicate name/host checks in `tests/integration/conftest.py` with the shared validator and preserve its read-only server probe before any write.

- [ ] **Step 7: Validate configuration and tests**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification_resources.py tests/unit/test_database_runtime.py -q && NOVEL_FORGE_QUALIFICATION_RUN_ID=test-contract docker compose -p nf-p0-config -f compose.yml -f compose.qualification.yml config --quiet && NOVEL_FORGE_QUALIFICATION_RUN_ID=test-contract NOVEL_FORGE_POSTGRES_TEST_DATABASE=nf_p0_config_test docker compose -p nf-p0-pg-config -f compose.postgres-test.yml config --quiet`

Expected: PASS; rendered published ports are dynamic and every cleanup-relevant resource has ownership metadata.

- [ ] **Step 8: Commit**

```bash
git add src/novel_forge/tools/backend_qualification_resources.py compose.qualification.yml compose.postgres-test.yml tests/integration/conftest.py tests/unit/test_backend_qualification_resources.py
git commit -m "feat: isolate qualification resources by run identity"
```

### Task 4: Complete PostgreSQL Collection Runner

**Files:**
- Modify: `scripts/run_authority_postgres_tests.py`
- Modify: `src/novel_forge/tools/backend_qualification_contract.py`
- Test: `tests/unit/test_backend_qualification.py`
- Test: `tests/architecture/test_backend_qualification_boundaries.py`

**Interfaces:**
- Consumes: integration collection contract, pytest evidence plugin, JUnit parser, validated run-owned DSN.
- Produces: `run_authority_postgres_tests.py --junit-xml PATH --collection-report PATH`; it consumes the orchestrator-provided `NOVEL_FORGE_DATABASE_URL` environment variable and exits 0 only for complete, zero-skip integration execution.

- [ ] **Step 1: Add red runner-contract tests**

```python
def test_postgres_runner_executes_complete_integration_root() -> None:
    command = build_postgres_pytest_command(CONTRACT, junit_xml=Path("result.xml"), collection_report=Path("collection.json"))
    assert "tests/integration" in command
    assert not any("*_postgres.py" in part for part in command)
    assert "--junitxml=result.xml" in command

def test_postgres_runner_rejects_unreported_or_skipped_items() -> None:
    with pytest.raises(QualificationContractError):
        validate_postgres_test_evidence(contract=CONTRACT, junit={"tests": 10, "skipped": 1}, collection={"source_files": []})
```

- [ ] **Step 2: Confirm red**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification.py tests/architecture/test_backend_qualification_boundaries.py -q`

Expected: FAIL because the old runner still builds curated filename globs and has no JUnit contract.

- [ ] **Step 3: Replace selection with the full root**

Build a subprocess command for `python -m pytest tests/integration --junitxml=... -p novel_forge.tools.pytest_collection_evidence --novel-forge-collection-report=...`. Require explicit output paths and require `NOVEL_FORGE_DATABASE_URL` in the supplied child environment; never place its value in argv, fall back to `.env`, or assume port `55432`.

- [ ] **Step 4: Validate structured outputs after pytest exits**

Parse JUnit and collection JSON even on failure, compare every discovered `tests/integration/test_*.py` file with collected source files, reject collection errors, zero tests, skips, failures, errors, or missing semantic-slice modules, and return stable exit codes: `0=PASS`, `1=TEST_OR_CONTRACT_FAIL`, `2=PREFLIGHT_FAIL`.

- [ ] **Step 5: Run the runner's non-database contract tests**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification.py tests/architecture/test_backend_qualification_boundaries.py -q`

Expected: PASS and no curated PostgreSQL filename pattern remains in the runner.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_authority_postgres_tests.py src/novel_forge/tools/backend_qualification_contract.py tests/unit/test_backend_qualification.py tests/architecture/test_backend_qualification_boundaries.py
git commit -m "feat: qualify the complete PostgreSQL integration collection"
```

### Task 5: P0 Orchestrator and Release Evidence Aggregation

**Files:**
- Create: `src/novel_forge/tools/backend_qualification.py`
- Create: `scripts/run_p0_backend_qualification.py`
- Modify: `src/novel_forge/tools/release_run_evidence.py`
- Test: `tests/unit/test_backend_qualification.py`
- Test: `tests/unit/test_release_run_evidence.py`

**Interfaces:**
- Consumes: Tasks 1–4 interfaces and existing migration/query-plan scripts.
- Produces: `run_qualification`; `build_p0_backend_qualification_report`; exact-SHA report `novel-forge.p0-backend-qualification-report.v1`.

- [ ] **Step 1: Add failing public-CLI tests**

```python
def test_cli_lists_stable_backend_gates_without_mutation(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_qualification(["--list-gates"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["gates"] == list(MANIFEST.required_gates)

def test_failed_gate_still_runs_owned_cleanup_and_writes_fail_report(tmp_path: Path) -> None:
    processes = RecordingProcessRunner(fail_gate="pytest-integration")
    output = tmp_path / "report.json"
    assert run_qualification(["--profile", "local", "--output", str(output)], process_runner=processes) == 1
    report = json.loads(output.read_text())
    assert report["decision"] == "FAIL"
    assert report["cleanup"]["status"] == "PASS"
    assert report["gates"][-1]["status"] == "NOT_RUN"
```

- [ ] **Step 2: Confirm red**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification.py tests/unit/test_release_run_evidence.py -q`

Expected: FAIL because the orchestrator and aggregate contract are absent.

- [ ] **Step 3: Implement source and provider preflight**

Require full clean HEAD/tree, record branch/ref without requiring a branch in CI, reject SHA mismatch against `GITHUB_SHA`, reject real-provider selection, reject provider credentials in the child environment, and never read `.env`. Compute manifest hashes and resolved dependency digest before gate execution.

- [ ] **Step 4: Implement bounded ordered gates**

Use argument-vector subprocesses with process groups. Gate order is source preflight, static/manifests, non-PostgreSQL pytest, PostgreSQL start, fresh migration, full PostgreSQL integration, observed-head validation, query-plan release, Compose runtime proof, evidence finalization. Apply per-gate and total timeouts, terminate only recorded child process groups, and mark dependent remaining gates `NOT_RUN` after a hard failure.

- [ ] **Step 5: Implement exact migration observation**

On the fresh run-owned database call the existing `novel_forge.cli.authority authority-migrate`, then the existing `get_migration_status`. Require both current and expected values to equal `expected_migration_head(repo_root)`. Validate that JUnit includes passing cases from every migration semantic slice declared in the qualification manifest.

- [ ] **Step 6: Extend existing release evidence aggregation**

Build the P0 report through `release_run_evidence`, validate exact SHA/tree, dependency digest, manifest-derived expected/observed head, ordered gates, JUnit hashes/summaries, Compose proof hash, cleanup, and fixed evidence ceilings. Sanitize, write a sibling temporary file, fsync, and rename atomically. Reject a PASS decision if any required gate, artifact, cleanup, or ceiling is absent or inconsistent.

- [ ] **Step 7: Prove failure and success paths**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification.py tests/unit/test_release_run_evidence.py -q`

Expected: PASS for list, simulated success, timeout, failure, redaction, cleanup, and exact-SHA cases.

- [ ] **Step 8: Commit**

```bash
git add src/novel_forge/tools/backend_qualification.py scripts/run_p0_backend_qualification.py src/novel_forge/tools/release_run_evidence.py tests/unit/test_backend_qualification.py tests/unit/test_release_run_evidence.py
git commit -m "feat: orchestrate exact-SHA backend qualification"
```

### Task 6: Compose Enqueue/Restart/Subsequent-Work Proof

**Files:**
- Modify: `scripts/verify_authority_compose.py`
- Modify: `src/novel_forge/tools/worker_fleet_evidence.py`
- Modify: `scripts/verify_authority_worker_e2e.py`
- Modify: `tests/unit/test_worker_fleet_evidence.py`
- Test: `tests/unit/test_backend_qualification.py`

**Interfaces:**
- Consumes: existing `authority_compose_probe`, Authority applications, worker health projection, `OwnedComposeProject`.
- Produces: Compose evidence with `pre_restart_operation`, `recovered_operation`, `post_restart_operation`, authoritative side-effect counters, worker generation/restart evidence, and ownership-checked cleanup.

- [ ] **Step 1: Add red evidence tests**

```python
def test_worker_evidence_requires_distinct_post_restart_work() -> None:
    evidence = valid_worker_evidence("content")
    evidence["post_restart_work_id"] = evidence["pre_restart_work_id"]
    with pytest.raises(ValueError, match="distinct post-restart work"):
        validate_worker_evidence(evidence)

def test_compose_proof_requires_authoritative_side_effect_after_restart() -> None:
    evidence = valid_compose_evidence()
    evidence["post_restart_operation"]["output_asset_count"] = 0
    with pytest.raises(QualificationContractError, match="post-restart authoritative side effect"):
        validate_compose_evidence(evidence)
```

- [ ] **Step 2: Confirm red**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_worker_fleet_evidence.py tests/unit/test_backend_qualification.py -q`

Expected: FAIL because readiness after restart is currently accepted without subsequent work.

- [ ] **Step 3: Extend the existing smoke, not the runtime**

After the controlled content-worker restart and readiness, call the existing probe `submit --suffix post-restart-<run-id>` and `verify`. Require a distinct operation ID, a succeeded Authority operation, at least one attempt/lease, output asset, audit record, and published outbox row. Preserve the existing recovered operation and stale-fence proof.

- [ ] **Step 4: Bind restart to the existing health projection**

Read the target worker's health projection before and after restart and require a changed startup/heartbeat generation or observed stop/start sequence using the existing projection fields. Do not introduce another health table or readiness endpoint.

- [ ] **Step 5: Use run-owned Compose lifecycle and atomic output**

Layer `compose.qualification.yml`, set only mock/scripted provider configuration, capture ownership after `up` and controlled restart, and invoke checked cleanup. On failure retain bounded logs under the run artifact root after recursive sanitization.

- [ ] **Step 6: Strengthen worker-fleet evidence**

Require `pre_restart_work_id`, `recovered_work_id`, `post_restart_work_id`, and `authoritative_side_effect` for all seven scenarios. Extend each existing scenario with the smallest second public operation for its own worker after restart; keep the current recovery/fencing/drain assertions.

- [ ] **Step 7: Run focused tests**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_worker_fleet_evidence.py tests/unit/test_backend_qualification.py -q`

Expected: PASS; health-only and same-work replay evidence fail closed.

- [ ] **Step 8: Commit**

```bash
git add scripts/verify_authority_compose.py src/novel_forge/tools/worker_fleet_evidence.py scripts/verify_authority_worker_e2e.py tests/unit/test_worker_fleet_evidence.py tests/unit/test_backend_qualification.py
git commit -m "test: prove worker success after controlled restart"
```

### Task 7: Canonical Make and CI Closure

**Files:**
- Modify: `Makefile`
- Modify: `.github/workflows/core-os-ci.yml`
- Modify: `tests/unit/test_core_os_characterization.py`
- Modify: `tests/architecture/test_backend_qualification_boundaries.py`

**Interfaces:**
- Consumes: public qualification CLI from Task 5.
- Produces: `make p0-backend-qualification`; stable remote check name `P0 Backend Qualification`; artifact upload independent of Admin UI.

- [ ] **Step 1: Add red CI/Make characterization**

```python
def test_authoritative_backend_job_uses_common_entry_and_not_web() -> None:
    workflow = (ROOT / ".github/workflows/core-os-ci.yml").read_text()
    assert "name: P0 Backend Qualification" in workflow
    assert "make p0-backend-qualification" in workflow
    assert "authority-parity-check" not in workflow
    backend = workflow.split("backend-qualification:", 1)[1]
    assert "needs: web" not in backend

def test_backend_make_recipe_contains_no_npm() -> None:
    makefile = (ROOT / "Makefile").read_text()
    recipe = makefile.split("p0-backend-qualification:", 1)[1].split("\n\n", 1)[0]
    assert "npm" not in recipe
```

- [ ] **Step 2: Confirm red**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_core_os_characterization.py tests/architecture/test_backend_qualification_boundaries.py -q`

Expected: FAIL on stale parity invocation, web dependency, and missing common target.

- [ ] **Step 3: Add backend-only Make targets**

`p0-backend-qualification` must call only `$(PYTHON) scripts/run_p0_backend_qualification.py --profile $(P0_PROFILE) --output $(P0_EVIDENCE_DIR)/p0-backend-qualification-$$(git rev-parse HEAD).json`. `p0-backend-static` must contain only Python/Ruff/manifest/Compose-config checks. Remove fixed `55432` fallback from backend qualification paths.

- [ ] **Step 4: Replace duplicated authoritative CI with the common entry**

Use one job ID `backend-qualification`, display name `P0 Backend Qualification`, exact checkout SHA binding, Python 3.12, `python -m pip install -e ".[test,industrial]"`, and the Make target. Always upload the exact-SHA report, JUnit XML, collection JSON, query-plan JSON, Compose JSON, sanitized logs, and cleanup receipt. Do not declare `needs: web`; do not invoke npm.

- [ ] **Step 5: Preserve UI honestly**

Remove `web` from required backend dependencies. Either omit the UI job or keep it as a separately named non-authoritative manual workflow; in both cases the backend evidence itself records `CURRENT_UI=DEFERRED / NOT_RUN_BY_SCOPE` and no UI PASS.

- [ ] **Step 6: Validate workflow source and targets**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_core_os_characterization.py tests/architecture/test_backend_qualification_boundaries.py -q && make p0-backend-list-gates && make authority-compose-config-check`

Expected: PASS; gate list is JSON, Compose config parses, and no stale Make target appears in CI.

- [ ] **Step 7: Commit**

```bash
git add Makefile .github/workflows/core-os-ci.yml tests/unit/test_core_os_characterization.py tests/architecture/test_backend_qualification_boundaries.py
git commit -m "ci: make backend qualification authoritative"
```

### Task 8: Backend/UI Documentation and Operational Exit Gates

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/local-development.md`
- Modify: `docs/development/testing.md`
- Test: `tests/architecture/test_backend_qualification_boundaries.py`

**Interfaces:**
- Consumes: final Make/CI names and evidence schema.
- Produces: accurate operator instructions and explicit proof ceiling/governance status.

- [ ] **Step 1: Add red documentation assertions**

```python
def test_docs_use_real_extras_dynamic_resources_and_defer_ui() -> None:
    docs = "\n".join(path.read_text() for path in DOC_PATHS)
    assert ".[dev]" not in docs
    assert ".[test,industrial]" in docs
    assert "DEFERRED / NOT_RUN_BY_SCOPE" in docs
    assert "Git SHA alone" in docs
    assert "branch governance" in docs
```

- [ ] **Step 2: Confirm red**

Run: `PYTHONPATH=src python -m pytest tests/architecture/test_backend_qualification_boundaries.py -q`

Expected: FAIL on obsolete extras, fixed-port instructions, and missing operational gates.

- [ ] **Step 3: Correct setup and qualification instructions**

Document `python -m pip install -e '.[test,industrial]'`, `make p0-backend-qualification`, Docker-assigned ports, UUID resource identities, output artifact layout, ownership-failure recovery, and the prohibition on `.env` DSNs.

- [ ] **Step 4: State evidence and UI boundaries**

State that current Admin pages are an unsupported deferred snapshot, not an Authority client and not backend/product evidence. State that a resolved dependency digest identifies the executed environment while Git SHA alone cannot reproduce unlocked ranges.

- [ ] **Step 5: State repository operational Exit Gates**

Document this order exactly: implementation final SHA → clean zero-state qualification → push exact SHA → remote `P0 Backend Qualification` green → enable that required check and branch governance → verify enforcement. Until the last two steps, repository governance is `OPEN / NOT_CLOSED`.

- [ ] **Step 6: Run documentation and architecture gates**

Run: `PYTHONPATH=src python -m pytest tests/architecture/test_backend_qualification_boundaries.py tests/architecture -q && git diff --check`

Expected: PASS with no UI implementation changes.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/operations/local-development.md docs/development/testing.md tests/architecture/test_backend_qualification_boundaries.py
git commit -m "docs: define backend qualification operations"
```

### Task 9: Focused Regression Sweep and Final Implementation Commit

**Files:**
- Modify only files implicated by demonstrated regressions.
- Test: all new unit/architecture tests plus existing owners of changed utilities.

**Interfaces:**
- Consumes: all prior task interfaces.
- Produces: clean final implementation SHA before any authoritative evidence run.

- [ ] **Step 1: Run all new and directly owning tests**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_backend_qualification_contract.py tests/unit/test_pytest_collection_evidence.py tests/unit/test_backend_qualification_resources.py tests/unit/test_backend_qualification.py tests/unit/test_release_run_evidence.py tests/unit/test_worker_fleet_evidence.py tests/unit/test_core_os_characterization.py tests/architecture/test_backend_qualification_boundaries.py -q`

Expected: PASS with zero skips.

- [ ] **Step 2: Run static and architecture owners**

Run: `make lint lint-authority lint-ratchet architecture-manifests-check architecture-fitness-check head-integrity-check authority-only-config-check && git diff --check`

Expected: PASS.

- [ ] **Step 3: Handle any real backend defect red-first**

For each failure attributable to production behavior, add one regression to the nearest existing public-seam test file, run that node ID to confirm the expected failure, make the complete bounded correction, then rerun the node ID and its owning collection. Environment failures remain `BLOCKED`; no skip, mock Authority, direct table repair, or weakened assertion is permitted.

- [ ] **Step 4: Commit bounded corrections**

```bash
git add -A src tests
git commit -m "fix: close backend qualification regression"
```

If Step 3 finds no production defect, omit this commit rather than creating an empty commit.

- [ ] **Step 5: Record the final implementation identity**

Run: `git status --short && git rev-parse HEAD && git rev-parse HEAD^{tree}`

Expected: empty status followed by one full final SHA and one full tree SHA.

### Task 10: Exact-Final-SHA Zero-State Qualification and Remote Exit Gates

**Files:**
- Evidence output only under an untracked external directory such as `/tmp/novel-forge-p0-<final-sha>/`.
- No tracked source changes after the final implementation SHA is selected.

**Interfaces:**
- Consumes: clean final SHA and `make p0-backend-qualification`.
- Produces: machine-readable exact-SHA evidence and an honest repository governance decision.

- [ ] **Step 1: Prove clean exact final source identity**

Run: `test -z "$(git status --porcelain)" && FINAL_SHA=$(git rev-parse HEAD) && test ${#FINAL_SHA} -eq 40 && printf '%s\n' "$FINAL_SHA"`

Expected: one 40-character SHA; no design-SHA or intermediate-SHA evidence is accepted.

- [ ] **Step 2: Execute qualification from zero**

Run: `FINAL_SHA=$(git rev-parse HEAD) P0_PROFILE=local P0_EVIDENCE_DIR="/tmp/novel-forge-p0-$(git rev-parse HEAD)" make p0-backend-qualification`

Expected: exit 0; fresh PostgreSQL/Compose resources are created and ownership-checked cleanup passes.

- [ ] **Step 3: Validate the report independently**

Run: `PYTHONPATH=src python -m novel_forge.tools.release_run_evidence p0-validate --commit-sha "$(git rev-parse HEAD)" --report "/tmp/novel-forge-p0-$(git rev-parse HEAD)/p0-backend-qualification-$(git rev-parse HEAD).json"`

Expected: PASS with matching final SHA/tree, manifest-derived migration head, dependency digest, complete JUnit counts, zero skips, Compose post-restart side effect, cleanup PASS, UI deferred, and all evidence ceilings intact.

- [ ] **Step 4: Recheck source immutability**

Run: `test -z "$(git status --porcelain)" && REPORT="/tmp/novel-forge-p0-$(git rev-parse HEAD)/p0-backend-qualification-$(git rev-parse HEAD).json" && test "$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["tested_sha"])' "$REPORT")" = "$(git rev-parse HEAD)"`

Expected: PASS; qualification created no tracked changes.

- [ ] **Step 5: Push the exact implementation branch and obtain remote green**

Run: `git push --set-upstream origin codex/p0-backend-qualification-ci-implementation-01`

Expected: remote branch points at the same final SHA. The remote `P0 Backend Qualification` check must complete successfully for that exact SHA. If GitHub Actions remains disabled, report `BLOCKED_BY_REPOSITORY_CONFIGURATION / NOT_RUN`; do not claim remote green.

- [ ] **Step 6: Apply repository governance only after remote green**

Enable the authoritative `P0 Backend Qualification` required check and branch governance for `main`, then verify the effective rule through a read-only repository query. This is an operational Exit Gate and is not performed before exact-final-SHA remote green.

- [ ] **Step 7: Publish the evidence ceiling verbatim**

Report engineering qualification separately from operational governance. Preserve: `REAL_PROVIDER=NOT_RUN_BY_SCOPE`, `HISTORICAL_ORPHAN_MUTATION=NOT_RUN_BY_SCOPE`, `EIGHT_CHAPTER=NOT_RUN_BY_SCOPE`, `HUMAN_REVIEW=NOT_RUN_BY_SCOPE`, `LONGFORM=NOT_PROVEN`, `MULTIBOOK=NOT_PROVEN`, `PRODUCTION=NOT_PROVEN`, `CURRENT_UI=DEFERRED / NOT_RUN_BY_SCOPE`.

## Plan Self-Check

### Approved design consistency

- The orchestrator is an engineering runner over existing seams, not a second Novel OS workflow engine.
- Existing migration runner/registry, Authority applications, query-plan tool, Compose probe, worker-health projection, worker E2E, and release evidence remain authoritative.
- The Admin UI is untouched by product implementation and removed from backend authority.
- Scripted/mock provider is the only provider profile admitted.
- Fresh and supported historical migrations, full backend tests, runtime readiness, recovery, and exact-SHA evidence remain the engineering qualification scope.

### Latest constraint coverage

1. Task 2 derives expected migration head from the canonical manifest and cross-checks the runtime registry.
2. Task 3 uses UUID identities, Docker-assigned ports, labels, receipts, exact resource IDs, and checked cleanup.
3. Tasks 1 and 4 execute the full integration root and fail on unclassified/missing collection files.
4. Tasks 2 and 4 use JUnit XML for counts/durations/skips and JSON hook output for collection identity.
5. Tasks 2 and 5 include the resolved dependency digest and explicit SHA-only reproducibility disclaimer; constraints are added only after demonstrated drift.
6. Tasks 3, 5, and 6 reuse existing runtime/health/migration/Authority/Compose/E2E seams and prove enqueue → worker → side effect → restart → subsequent work.
7. Task 7 gives backend CI no `web` dependency and gives the Make recipe no npm; Task 8 records UI deferral.
8. Task 7 removes `authority-parity-check` and makes local/CI use one entry.
9. Tasks 1–7 are red/green/commit TDD batches; Task 9 defines regression-first bounded production fixes.
10. Task 10 runs the complete zero-state qualification only after the clean final implementation SHA.
11. Task 10 orders remote green before required-check/branch governance and leaves governance open if remote execution is unavailable.
12. Tasks 5, 8, and 10 enforce and publish the unchanged proof ceiling.

### Internal contradiction check

- Fixed `55432` statements in the approved design are treated as superseded implementation details; no canonical runner contract contains that port.
- `0104` remains a checked baseline observation, while all runner expectations use the manifest-derived value.
- Semantic slice file lists support claim attribution only; they never select or limit the complete PostgreSQL collection.
- Worker matrix detail may remain parallel CI evidence, but the sole authoritative required check and local invocation share `make p0-backend-qualification`.
- Source completion, local qualification, remote green, and repository governance are four separate states and cannot be collapsed into one claim.
- Dependency snapshot identity improves provenance without claiming a lock that does not exist and without expanding into package-manager migration.

### Placeholder and type check

- All planned public names appear in the Canonical Interfaces section and use the same spelling in later tasks.
- Every implementation task names exact files, focused red/green commands, expected outcomes, and a bounded commit.
- Conditional regression paths explicitly prohibit empty commits and evidence inflation.
