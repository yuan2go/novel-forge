from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
RUN_LABEL = "novel-forge.qualification.run-id"
OPERATOR_DOCS = (
    ROOT / "README.md",
    ROOT / "docs/operations/local-development.md",
    ROOT / "docs/development/testing.md",
)


class BackendQualificationBoundaryTests(unittest.TestCase):
    def test_operator_docs_define_backend_scope_and_operational_exit_gates(
        self,
    ) -> None:
        docs = "\n".join(path.read_text(encoding="utf-8") for path in OPERATOR_DOCS)

        self.assertNotIn(".[dev]", docs)
        self.assertIn(".[test,industrial]", docs)
        self.assertIn("make p0-backend-qualification", docs)
        self.assertIn("Docker-assigned", docs)
        self.assertIn("DEFERRED / NOT_RUN_BY_SCOPE", docs)
        self.assertIn("Git SHA alone", docs)
        self.assertIn("resolved dependency digest", docs)
        self.assertIn("branch governance", docs)
        self.assertIn("OPEN / NOT_CLOSED", docs)
        for ceiling in (
            "REAL_PROVIDER",
            "HISTORICAL_ORPHAN_MUTATION",
            "EIGHT_CHAPTER",
            "HUMAN_REVIEW",
            "LONGFORM",
            "MULTIBOOK",
            "PRODUCTION",
        ):
            self.assertIn(ceiling, docs)

    def test_backend_make_entry_is_python_only_and_has_no_fixed_port(self) -> None:
        source = (ROOT / "Makefile").read_text(encoding="utf-8")
        recipe = source.split("p0-backend-qualification:", 1)[1].split(
            "\n\n", 1
        )[0]

        self.assertIn("scripts/run_p0_backend_qualification.py", recipe)
        self.assertIn("--profile $(P0_PROFILE)", recipe)
        self.assertIn("$(P0_EVIDENCE_DIR)", recipe)
        self.assertNotIn("npm", recipe)
        self.assertNotIn("55432", source)

    def test_qualification_compose_paths_disable_implicit_env_files(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        config_recipe = makefile.split("authority-compose-config-check:", 1)[
            1
        ].split("\n\n", 1)[0]
        worker = (ROOT / "scripts/verify_authority_worker_e2e.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("COMPOSE_DISABLE_ENV_FILE=1", makefile)
        self.assertIn("NOVEL_FORGE_DOCKER_COMPOSE_BIN", makefile)
        self.assertEqual(config_recipe.count("$(QUALIFICATION_COMPOSE)"), 4)
        self.assertNotIn("docker compose", config_recipe)
        self.assertIn('"COMPOSE_DISABLE_ENV_FILE": "1"', worker)
        self.assertIn('if key != "COMPOSE_ENV_FILES"', worker)

    def test_qualification_compose_resources_are_labeled_and_ports_are_dynamic(
        self,
    ) -> None:
        postgres = yaml.safe_load(
            (ROOT / "compose.postgres-test.yml").read_text(encoding="utf-8")
        )
        service = postgres["services"]["authority-postgres-test"]
        self.assertEqual(service["labels"][RUN_LABEL], "${NOVEL_FORGE_QUALIFICATION_RUN_ID:?qualification run id required}")
        self.assertEqual(
            service["environment"]["POSTGRES_DB"],
            "${NOVEL_FORGE_POSTGRES_TEST_DATABASE:?qualification database required}",
        )
        self.assertEqual(
            service["ports"],
            [
                {
                    "target": 5432,
                    "host_ip": "127.0.0.1",
                    "published": "0",
                    "protocol": "tcp",
                }
            ],
        )
        self.assertEqual(
            postgres["networks"]["default"]["labels"][RUN_LABEL],
            "${NOVEL_FORGE_QUALIFICATION_RUN_ID:?qualification run id required}",
        )

        qualification = yaml.safe_load(
            (ROOT / "compose.qualification.yml").read_text(encoding="utf-8")
        )
        canonical = yaml.safe_load(
            (ROOT / "compose.yml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(qualification["services"]), set(canonical["services"])
        )
        for declared in qualification["services"].values():
            self.assertEqual(
                declared["labels"][RUN_LABEL],
                "${NOVEL_FORGE_QUALIFICATION_RUN_ID:?qualification run id required}",
            )
        for declared in qualification["volumes"].values():
            self.assertEqual(
                declared["labels"][RUN_LABEL],
                "${NOVEL_FORGE_QUALIFICATION_RUN_ID:?qualification run id required}",
            )

        worker_e2e = yaml.safe_load(
            (ROOT / "compose.worker-e2e.yml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            worker_e2e["services"]["postgresql"]["ports"],
            [
                {
                    "target": 5432,
                    "host_ip": "127.0.0.1",
                    "published": "0",
                    "protocol": "tcp",
                }
            ],
        )
        self.assertEqual(
            worker_e2e["services"]["object-store"]["ports"],
            [
                {
                    "target": 9000,
                    "host_ip": "127.0.0.1",
                    "published": "0",
                    "protocol": "tcp",
                }
            ],
        )

    def test_postgresql_runner_has_no_curated_filename_or_fixed_port_contract(
        self,
    ) -> None:
        source = (ROOT / "scripts/run_authority_postgres_tests.py").read_text(
            encoding="utf-8"
        )

        manifest = yaml.safe_load(
            (
                ROOT
                / "architecture/manifests/backend-qualification-manifest.yaml"
            ).read_text(encoding="utf-8")
        )
        integration = next(
            item
            for item in manifest["pytest_collections"]
            if item["name"] == "integration"
        )
        self.assertEqual(integration["paths"], ["tests/integration"])
        self.assertTrue(integration["complete_collection"])
        self.assertIn("build_postgres_pytest_command", source)
        self.assertNotIn(".glob(", source)
        self.assertNotIn("pytest.main", source)
        self.assertNotIn("55432", source)


if __name__ == "__main__":
    unittest.main()
