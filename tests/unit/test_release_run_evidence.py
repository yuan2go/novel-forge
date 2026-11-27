from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_forge.tools.release_run_evidence import (
    REQUIRED_ARTIFACT_FILES,
    build_p0_backend_qualification_report,
    build_ci_test_result,
    build_docker_image_evidence,
    build_release_qualification,
    validate_p0_backend_qualification_report,
    write_atomic_evidence,
    main as release_evidence_main,
)
from novel_forge.tools.backend_qualification_contract import (
    P0_PROOF_SCOPE,
    REQUIRED_GATE_ORDER,
)
from novel_forge.tools.pr_governance import validate_current_p0


SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


class ReleaseRunEvidenceTests(unittest.TestCase):
    def test_image_evidence_prefers_oci_manifest_digest(self) -> None:
        evidence = build_docker_image_evidence(
            commit_sha=SHA,
            image_ref=f"novel-forge:{SHA}",
            build_metadata={
                "containerimage.digest": DIGEST,
                "containerimage.config.digest": "sha256:" + "c" * 64,
            },
            image_id="sha256:" + "d" * 64,
        )
        self.assertEqual(evidence["docker_image_digest"], DIGEST)
        self.assertEqual(evidence["digest_kind"], "oci_manifest_digest")
        self.assertEqual(evidence["tested_sha"], SHA)

    def test_image_evidence_rejects_non_content_address(self) -> None:
        with self.assertRaisesRegex(ValueError, "content-addressed"):
            build_docker_image_evidence(
                commit_sha=SHA,
                image_ref="novel-forge:candidate",
                build_metadata={},
                image_id="latest",
            )

    def test_ci_result_requires_every_required_job_to_succeed(self) -> None:
        result = build_ci_test_result(
            commit_sha=SHA,
            needs={"unit": {"result": "success"}, "migration": {"result": "success"}},
        )
        self.assertTrue(result["all_required_jobs_passed"])
        with self.assertRaisesRegex(ValueError, "migration=failed"):
            build_ci_test_result(
                commit_sha=SHA,
                needs={
                    "unit": {"result": "success"},
                    "migration": {"result": "failed"},
                },
            )

    def test_release_manifest_requires_every_sha_bound_artifact_class(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for evidence_class, filename_template in REQUIRED_ARTIFACT_FILES.items():
                path = root / filename_template.format(sha=SHA)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix == ".json":
                    path.write_text(
                        json.dumps(
                            {"tested_sha": SHA, "evidence_class": evidence_class}
                        ),
                        encoding="utf-8",
                    )
                else:
                    path.write_text(f"tested_sha={SHA}\n", encoding="utf-8")
            manifest = build_release_qualification(commit_sha=SHA, artifact_root=root)
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(set(manifest["artifacts"]), set(REQUIRED_ARTIFACT_FILES))

            (
                root / REQUIRED_ARTIFACT_FILES["environment_metadata"].format(sha=SHA)
            ).unlink()
            with self.assertRaisesRegex(ValueError, "environment_metadata"):
                build_release_qualification(commit_sha=SHA, artifact_root=root)

    def test_p0_report_requires_dependency_migration_gate_and_cleanup_identity(
        self,
    ) -> None:
        required_gates = REQUIRED_GATE_ORDER
        manifest = {
            "schema_version": "novel-forge.backend-qualification-manifest.v2",
            "required_gates": list(required_gates),
            "expected_migration_head": "manifest-head",
            "manifest_digests": {
                "architecture/manifests/migration-manifest.yaml": DIGEST
            },
            "proof_scope": dict(P0_PROOF_SCOPE),
        }
        pytest_evidence = {
            "schema_version": "novel-forge.backend-pytest-evidence.v1",
            "status": "PASS",
            "junit": {
                "tests": 3,
                "passed": 3,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
                "duration_seconds": 0.2,
                "artifact": "backend.xml",
                "digest": DIGEST,
            },
            "collection": {
                "complete_collection": True,
                "collected_count": 2,
                "source_file_count": 1,
                "pytest_exit_status": 0,
                "report_digest": DIGEST,
            },
            "case_accounting": {
                "authority": "JUNIT_XML",
                "junit_case_count": 3,
                "collected_node_count": 2,
                "additional_junit_case_count": 1,
            },
        }
        postgres_evidence = {
            **pytest_evidence,
            "schema_version": "novel-forge.postgresql-pytest-evidence.v1",
            "semantic_slices": {
                "migration_matrix": [
                    "tests/integration/test_authority_migrations_postgres.py"
                ]
            },
        }
        documentation_evidence = {
            "schema_version": "novel-forge.documentation-reality-check.v1",
            "evidence_class": "reality_inventory",
            "status": "PASS",
            "tested_sha": SHA,
            "inventory_sha256": DIGEST,
            "canonical_document_count": 5,
            "capability_count": 13,
            "source_comment_count": 1,
            "module_docstring_count": 1,
            "source_docstring_count": 1,
            "errors": [],
            "artifact": "documentation-reality.json",
            "digest": DIGEST,
        }
        run_id = "p0-" + "1" * 32
        compose_project = "nf-p0-" + "1" * 32
        runtime_project = compose_project + "-runtime"
        database_name = "nf_p0_" + "1" * 32 + "_test"
        run_identity = {
            "run_id": run_id,
            "compose_project": compose_project,
            "compose_runtime_project": runtime_project,
            "database_name": database_name,
        }
        cleanup_evidence = {
            "status": "PASS",
            "owned_resource_count": 4,
            "remaining_resource_count": 0,
            "phases": [
                {
                    "phase": "postgresql",
                    "status": "PASS",
                    "resource_count": 2,
                    "remaining_resource_count": 0,
                    "run_id": run_id,
                    "compose_project": compose_project,
                    "receipt": (f"compose-resource-ownership-{compose_project}.json"),
                },
                {
                    "phase": "compose-runtime",
                    "status": "PASS",
                    "resource_count": 2,
                    "remaining_resource_count": 0,
                    "run_id": run_id,
                    "compose_project": runtime_project,
                    "receipt": (f"compose-resource-ownership-{runtime_project}.json"),
                },
            ],
        }
        gates = [
            {
                "gate_id": gate_id,
                "status": "PASS",
                "duration_seconds": 0.1,
                "evidence": (
                    {
                        "commit_sha": SHA,
                        "source_tree": "c" * 40,
                        "dirty": False,
                        "implementation_tree_sha": DIGEST,
                    }
                    if gate_id == "source-preflight"
                    else documentation_evidence
                    if gate_id == "documentation-reality"
                    else pytest_evidence
                    if gate_id == "pytest-backend"
                    else {"returncode": 0}
                    if gate_id == "static-and-manifests"
                    else {
                        "database_identity": {
                            "database_name": database_name,
                            "host_class": "LOOPBACK",
                            "port": 55432,
                            "server_identity_digest": DIGEST,
                        },
                        "dynamic_port": True,
                        "ownership_resource_count": 2,
                    }
                    if gate_id == "postgresql-start"
                    else postgres_evidence
                    if gate_id
                    in {
                        "migration-compatibility",
                        "pytest-postgresql-integration",
                    }
                    else {
                        "expected_head": "manifest-head",
                        "observed_head": "manifest-head",
                        "applied_count": 1,
                        "missing": [],
                        "extra": [],
                    }
                    if gate_id in {"migration-fresh", "migration-head"}
                    else {"artifact": "query-plan.json", "digest": DIGEST}
                    if gate_id == "query-plan-release"
                    else {
                        "artifact": "compose-runtime.json",
                        "digest": DIGEST,
                        "pre_restart_operation_id": "operation-pre",
                        "recovered_operation_id": "operation-recovered",
                        "post_restart_operation_id": "operation-post",
                        "authoritative_side_effect": True,
                    }
                    if gate_id == "compose-runtime"
                    else cleanup_evidence
                    if gate_id == "resource-cleanup"
                    else {"artifact": "p0.json", "atomic_write": True}
                ),
            }
            for gate_id in required_gates
        ]
        dependency = {
            "schema_version": "novel-forge.resolved-dependency-snapshot.v1",
            "python_implementation": "CPython",
            "python_version": "3.12.2",
            "package_count": 2,
            "packages": ["alpha==1", "beta==2"],
            "provenance_files": [],
            "digest": "sha256:da996a55bccd5c2080004a0d3c9636153d5a8980cb1aebbeb9d2e0e466a5f78d",
            "git_sha_alone_reproducible": False,
            "reproducibility_class": "RESOLVED_SNAPSHOT",
        }

        report = build_p0_backend_qualification_report(
            tested_sha=SHA,
            source_tree="c" * 40,
            source_identity={
                "commit_sha": SHA,
                "source_tree": "c" * 40,
                "dirty": False,
                "branch": "feature",
                "workflow_sha": "",
                "implementation_tree_sha": DIGEST,
            },
            manifest=manifest,
            dependency_snapshot=dependency,
            gates=gates,
            cleanup=cleanup_evidence,
            run_identity=run_identity,
        )

        self.assertEqual(report["decision"], "PASS")
        self.assertEqual(report["implementation_tree_sha"], DIGEST)
        self.assertEqual(report["migration"]["expected_head"], "manifest-head")
        self.assertEqual(report["migration"]["observed_head"], "manifest-head")
        self.assertFalse(report["dependency_snapshot"]["git_sha_alone_reproducible"])
        plan = {"head_sha": SHA, "implementation_tree_sha": DIGEST}
        validate_current_p0(report, plan=plan)
        for location in ("top", "nested"):
            with self.subTest(pr_identity_drift=location):
                drifted = copy.deepcopy(report)
                if location == "top":
                    drifted["implementation_tree_sha"] = "sha256:" + "9" * 64
                else:
                    drifted["source_identity"]["implementation_tree_sha"] = (
                        "sha256:" + "9" * 64
                    )
                with self.assertRaisesRegex(ValueError, "source identity"):
                    validate_current_p0(
                        drifted,
                        plan={
                            **plan,
                            "implementation_tree_sha": drifted[
                                "implementation_tree_sha"
                            ],
                        },
                    )
        tampered_dependency = dict(dependency)
        tampered_dependency["packages"] = ["alpha==1", "beta==3"]
        with self.assertRaisesRegex(ValueError, "digest differs"):
            build_p0_backend_qualification_report(
                tested_sha=SHA,
                source_tree="c" * 40,
                source_identity={
                    "commit_sha": SHA,
                    "source_tree": "c" * 40,
                    "dirty": False,
                    "branch": "feature",
                    "workflow_sha": "",
                    "implementation_tree_sha": DIGEST,
                },
                manifest=manifest,
                dependency_snapshot=tampered_dependency,
                gates=gates,
                cleanup=cleanup_evidence,
                run_identity=run_identity,
            )

        invalid_compose_gates = [dict(item) for item in gates]
        compose_index = required_gates.index("compose-runtime")
        compose_gate = dict(invalid_compose_gates[compose_index])
        compose_gate["evidence"] = {
            **compose_gate["evidence"],
            "post_restart_operation_id": "operation-pre",
        }
        invalid_compose_gates[compose_index] = compose_gate
        with self.assertRaisesRegex(ValueError, "distinct operation"):
            build_p0_backend_qualification_report(
                tested_sha=SHA,
                source_tree="c" * 40,
                source_identity={
                    "commit_sha": SHA,
                    "source_tree": "c" * 40,
                    "dirty": False,
                    "branch": "feature",
                    "workflow_sha": "",
                    "implementation_tree_sha": DIGEST,
                },
                manifest=manifest,
                dependency_snapshot=dependency,
                gates=invalid_compose_gates,
                cleanup=cleanup_evidence,
                run_identity=run_identity,
            )

        cleanup_mutations = (
            (
                "boolean-remaining-count",
                lambda payload: payload.update(remaining_resource_count=False),
            ),
            (
                "duplicate-phase",
                lambda payload: payload["phases"].__setitem__(
                    1, copy.deepcopy(payload["phases"][0])
                ),
            ),
            (
                "missing-receipt",
                lambda payload: payload["phases"][1].pop("receipt"),
            ),
            (
                "boolean-resource-count",
                lambda payload: payload["phases"][0].update(resource_count=False),
            ),
        )
        for label, mutate in cleanup_mutations:
            with self.subTest(cleanup=label):
                malformed = copy.deepcopy(report)
                mutate(malformed["cleanup"])
                malformed_cleanup_gate = next(
                    gate
                    for gate in malformed["gates"]
                    if gate["gate_id"] == "resource-cleanup"
                )
                malformed_cleanup_gate["evidence"] = copy.deepcopy(malformed["cleanup"])
                with self.assertRaisesRegex(ValueError, "cleanup"):
                    validate_p0_backend_qualification_report(
                        malformed,
                        expected_sha=SHA,
                    )

        gate_mutations = (
            (
                "static-and-manifests",
                lambda evidence: evidence.update(returncode=False),
                "static and manifest",
            ),
            (
                "postgresql-start",
                lambda evidence: evidence["database_identity"].update(
                    database_name="shared_database"
                ),
                "run-owned and isolated",
            ),
            (
                "migration-fresh",
                lambda evidence: evidence.update(
                    observed_head="wrong-head",
                    missing=["manifest-head"],
                    extra=["wrong-head"],
                ),
                "fresh migration",
            ),
        )
        for gate_id, mutate, expected in gate_mutations:
            with self.subTest(gate=gate_id):
                malformed = copy.deepcopy(report)
                gate = next(
                    item for item in malformed["gates"] if item["gate_id"] == gate_id
                )
                mutate(gate["evidence"])
                with self.assertRaisesRegex(ValueError, expected):
                    validate_p0_backend_qualification_report(
                        malformed,
                        expected_sha=SHA,
                    )

        rebound = copy.deepcopy(report)
        rebound["implementation_tree_sha"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ValueError, "source identity"):
            validate_p0_backend_qualification_report(rebound, expected_sha=SHA)

        shared_database = copy.deepcopy(report)
        shared_database["run_identity"]["database_name"] = "shared_database"
        postgresql_start = next(
            gate
            for gate in shared_database["gates"]
            if gate["gate_id"] == "postgresql-start"
        )
        postgresql_start["evidence"]["database_identity"]["database_name"] = (
            "shared_database"
        )
        with self.assertRaisesRegex(ValueError, "run-owned and isolated"):
            validate_p0_backend_qualification_report(
                shared_database,
                expected_sha=SHA,
            )

        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence" / "p0.json"
            write_atomic_evidence(output, report)
            validated = validate_p0_backend_qualification_report(
                json.loads(output.read_text(encoding="utf-8")),
                expected_sha=SHA,
            )
            cli_result = release_evidence_main(
                [
                    "p0-validate",
                    "--commit-sha",
                    SHA,
                    "--report",
                    str(output),
                ]
            )
            temporary_files = list(output.parent.glob(".p0.json.*.tmp"))

        self.assertEqual(validated["status"], "PASS")
        self.assertEqual(cli_result, 0)
        self.assertEqual(temporary_files, [])


if __name__ == "__main__":
    unittest.main()
