from __future__ import annotations

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
                needs={"unit": {"result": "success"}, "migration": {"result": "failed"}},
            )

    def test_release_manifest_requires_every_sha_bound_artifact_class(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for evidence_class, filename_template in REQUIRED_ARTIFACT_FILES.items():
                path = root / filename_template.format(sha=SHA)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix == ".json":
                    path.write_text(
                        json.dumps({"tested_sha": SHA, "evidence_class": evidence_class}),
                        encoding="utf-8",
                    )
                else:
                    path.write_text(f"tested_sha={SHA}\n", encoding="utf-8")
            manifest = build_release_qualification(commit_sha=SHA, artifact_root=root)
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(set(manifest["artifacts"]), set(REQUIRED_ARTIFACT_FILES))

            (root / REQUIRED_ARTIFACT_FILES["environment_metadata"].format(sha=SHA)).unlink()
            with self.assertRaisesRegex(ValueError, "environment_metadata"):
                build_release_qualification(commit_sha=SHA, artifact_root=root)

    def test_p0_report_requires_dependency_migration_gate_and_cleanup_identity(
        self,
    ) -> None:
        required_gates = (
            "source-preflight",
            "pytest-backend",
            "migration-head",
            "query-plan-release",
            "compose-runtime",
            "evidence-finalization",
        )
        manifest = {
            "schema_version": "novel-forge.backend-qualification-manifest.v1",
            "required_gates": list(required_gates),
            "expected_migration_head": "manifest-head",
            "manifest_digests": {
                "architecture/manifests/migration-manifest.yaml": DIGEST
            },
            "evidence_ceilings": {
                "CURRENT_UI": "DEFERRED / NOT_RUN_BY_SCOPE",
                "REAL_PROVIDER": "NOT_RUN_BY_SCOPE",
                "HISTORICAL_ORPHAN_MUTATION": "NOT_RUN_BY_SCOPE",
                "EIGHT_CHAPTER": "NOT_RUN_BY_SCOPE",
                "HUMAN_REVIEW": "NOT_RUN_BY_SCOPE",
                "LONGFORM": "NOT_PROVEN",
                "MULTIBOOK": "NOT_PROVEN",
                "PRODUCTION": "NOT_PROVEN",
            },
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
                    }
                    if gate_id == "source-preflight"
                    else pytest_evidence
                    if gate_id == "pytest-backend"
                    else {
                        "expected_head": "manifest-head",
                        "observed_head": "manifest-head",
                    }
                    if gate_id == "migration-head"
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
            },
            manifest=manifest,
            dependency_snapshot=dependency,
            gates=gates,
            cleanup={"status": "PASS", "remaining_resource_count": 0},
            run_identity={"run_id": "p0-run", "compose_project": "nf-p0-run"},
        )

        self.assertEqual(report["decision"], "PASS")
        self.assertEqual(report["migration"]["expected_head"], "manifest-head")
        self.assertEqual(report["migration"]["observed_head"], "manifest-head")
        self.assertFalse(report["dependency_snapshot"]["git_sha_alone_reproducible"])
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
                },
                manifest=manifest,
                dependency_snapshot=tampered_dependency,
                gates=gates,
                cleanup={"status": "PASS", "remaining_resource_count": 0},
                run_identity={"run_id": "p0-run"},
            )

        invalid_compose_gates = [dict(item) for item in gates]
        compose_gate = dict(invalid_compose_gates[4])
        compose_gate["evidence"] = {
            **compose_gate["evidence"],
            "post_restart_operation_id": "operation-pre",
        }
        invalid_compose_gates[4] = compose_gate
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
                },
                manifest=manifest,
                dependency_snapshot=dependency,
                gates=invalid_compose_gates,
                cleanup={"status": "PASS", "remaining_resource_count": 0},
                run_identity={"run_id": "p0-run"},
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
