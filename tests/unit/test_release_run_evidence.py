from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_forge.tools.release_run_evidence import (
    REQUIRED_ARTIFACT_FILES,
    build_ci_test_result,
    build_docker_image_evidence,
    build_release_qualification,
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


if __name__ == "__main__":
    unittest.main()
