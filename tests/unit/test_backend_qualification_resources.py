from __future__ import annotations

from pathlib import Path
import json
import subprocess
from tempfile import TemporaryDirectory
from typing import Sequence
import unittest

from novel_forge.tools.backend_qualification_resources import (
    ComposeResource,
    ComposeResourceSnapshot,
    DockerCommandError,
    DockerComposeClient,
    OwnedComposeProject,
    QualificationRunIdentity,
    ResourceOwnershipError,
    published_loopback_port,
    require_disposable_database_name,
    validate_disposable_database_url,
)


SHA = "a" * 40


class FakeComposeClient:
    def __init__(self) -> None:
        self.resources: list[ComposeResource] = []
        self.down_calls: list[tuple[str, ...]] = []

    def discover(self, project_name: str) -> ComposeResourceSnapshot:
        return ComposeResourceSnapshot(tuple(self.resources))

    def down(
        self,
        *,
        project_name: str,
        compose_files: Sequence[Path],
        environment: dict[str, str],
    ) -> None:
        self.down_calls.append((project_name, *(str(path) for path in compose_files)))
        self.resources.clear()


class QualificationRunIdentityTests(unittest.TestCase):
    def test_identity_scopes_compose_database_and_artifacts_to_one_uuid(self) -> None:
        with TemporaryDirectory() as temporary:
            identity = QualificationRunIdentity.create(
                commit_sha=SHA,
                artifact_parent=Path(temporary),
            )

        self.assertRegex(identity.run_id, r"^p0-[0-9a-f]{32}$")
        token = identity.run_id.removeprefix("p0-")
        self.assertEqual(identity.compose_project, f"nf-p0-{token}")
        self.assertEqual(identity.database_name, f"nf_p0_{token}_test")
        self.assertEqual(
            identity.artifact_root.name,
            f"novel-forge-p0-{SHA[:12]}-{token}",
        )
        self.assertTrue(identity.artifact_root.is_absolute())

    def test_database_url_must_match_the_run_owned_loopback_database(self) -> None:
        database_name = "nf_p0_0123456789abcdef0123456789abcdef_test"
        safe_identity = validate_disposable_database_url(
            "postgresql://novel_forge:private@127.0.0.1:49152/" + database_name,
            expected_database=database_name,
        )

        self.assertEqual(safe_identity["database_name"], database_name)
        self.assertEqual(safe_identity["host_class"], "LOOPBACK")
        self.assertEqual(safe_identity["port"], 49152)
        self.assertRegex(
            safe_identity["server_identity_digest"], r"^sha256:[0-9a-f]{64}$"
        )
        self.assertNotIn("private", str(safe_identity))
        with self.assertRaisesRegex(ValueError, "run-owned database"):
            validate_disposable_database_url(
                "postgresql://novel_forge:private@127.0.0.1:49152/other_test",
                expected_database=database_name,
            )
        with self.assertRaisesRegex(ValueError, "loopback"):
            validate_disposable_database_url(
                "postgresql://novel_forge:private@database.internal:5432/"
                + database_name,
                expected_database=database_name,
            )

    def test_cleanup_refuses_a_resource_not_in_the_owned_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            identity = QualificationRunIdentity.create(
                commit_sha=SHA, artifact_parent=Path(temporary)
            )
            client = FakeComposeClient()
            owned = OwnedComposeProject(
                identity=identity,
                repo_root=Path(temporary),
                compose_files=(Path("compose.yml"),),
                environment={"NOVEL_FORGE_QUALIFICATION_RUN_ID": identity.run_id},
                client=client,
            )
            owned.assert_unclaimed()
            client.resources.append(
                ComposeResource(
                    kind="container",
                    resource_id="owned-container",
                    project_name=identity.compose_project,
                    run_id=identity.run_id,
                )
            )
            owned.capture()
            client.resources.append(
                ComposeResource(
                    kind="container",
                    resource_id="unexpected-container",
                    project_name=identity.compose_project,
                    run_id=identity.run_id,
                )
            )

            with self.assertRaisesRegex(
                ResourceOwnershipError, "resource set changed"
            ):
                owned.cleanup()

        self.assertEqual(client.down_calls, [])

    def test_published_port_is_read_from_docker_inspect_json(self) -> None:
        inspect_payload = [
            {
                "NetworkSettings": {
                    "Ports": {
                        "5432/tcp": [
                            {"HostIp": "127.0.0.1", "HostPort": "49153"}
                        ]
                    }
                }
            }
        ]

        self.assertEqual(
            published_loopback_port(inspect_payload, container_port=5432), 49153
        )
        inspect_payload[0]["NetworkSettings"]["Ports"]["5432/tcp"][0][
            "HostIp"
        ] = "0.0.0.0"
        with self.assertRaisesRegex(ValueError, "loopback"):
            published_loopback_port(inspect_payload, container_port=5432)

    def test_docker_inventory_requires_project_and_run_labels(self) -> None:
        responses = {
            ("container", "ls"): "container-1\n",
            ("volume", "ls"): "volume-1\n",
            ("network", "ls"): "network-1\n",
        }

        def runner(
            command: Sequence[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            parts = tuple(command)
            if len(parts) >= 3 and (parts[1], parts[2]) in responses:
                output = responses[(parts[1], parts[2])]
            else:
                resource_id = parts[-1]
                labels = {
                    "com.docker.compose.project": "nf-p0-owned",
                    "novel-forge.qualification.run-id": "p0-owned",
                }
                payload = {
                    "Id": resource_id,
                    "Name": resource_id,
                    "Labels": labels,
                    "Config": {"Labels": labels},
                }
                output = json.dumps([payload])
            return subprocess.CompletedProcess(command, 0, output, "")

        client = DockerComposeClient(repo_root=Path.cwd(), runner=runner)
        snapshot = client.discover("nf-p0-owned")

        self.assertEqual(
            snapshot.identities,
            (
                ("container", "container-1"),
                ("network", "network-1"),
                ("volume", "volume-1"),
            ),
        )
        self.assertTrue(
            all(resource.run_id == "p0-owned" for resource in snapshot.resources)
        )

    def test_docker_timeout_becomes_a_bounded_resource_error(self) -> None:
        def runner(
            command: Sequence[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(command, timeout=0.01)

        client = DockerComposeClient(repo_root=Path.cwd(), runner=runner)

        with self.assertRaisesRegex(DockerCommandError, "timed out"):
            client.discover("nf-p0-timeout")

    def test_server_reported_database_name_must_be_disposable(self) -> None:
        self.assertEqual(
            require_disposable_database_name("migration_window_123_test"),
            "migration_window_123_test",
        )
        for protected in ("postgres", "template0", "template1", "novel_forge", ""):
            with self.subTest(protected=protected), self.assertRaisesRegex(
                ValueError, "refusing"
            ):
                require_disposable_database_name(protected)


if __name__ == "__main__":
    unittest.main()
