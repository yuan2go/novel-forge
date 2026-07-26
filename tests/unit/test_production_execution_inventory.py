from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from novel_forge.tools.production_execution_inventory import (
    REQUIRED_LEDGER_FIELDS,
    build_execution_inventory,
    write_execution_inventory,
)


class ProductionExecutionInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write(self, relative_path: str, source: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")

    def _find(
        self,
        manifest: dict,
        *,
        source_file: str,
        current_entrypoint: str,
    ) -> dict:
        for finding in manifest["entries"]:
            if (
                finding["source_file"] == source_file
                and finding["current_entrypoint"] == current_entrypoint
            ):
                return finding
        self.fail(f"missing finding: {source_file} {current_entrypoint}")

    def test_ast_inventory_resolves_aliases_dynamic_calls_and_wrappers(self) -> None:
        self._write(
            "src/novel_forge/modules/production_execution/process_supervisor.py",
            """
            import subprocess as process

            def launch_codex():
                return process.Popen(["codex", "exec"])
            """,
        )
        self._write(
            "src/novel_forge/infrastructure/provider_client.py",
            """
            import openai as ai

            client = ai.OpenAI()

            def invoke_provider():
                return client.responses.create(model="gpt", input="x")
            """,
        )
        self._write(
            "src/novel_forge/modules/topics/provider_helper.py",
            """
            from novel_forge.infrastructure.provider_client import invoke_provider

            def second_order_wrapper():
                return invoke_provider()
            """,
        )
        self._write(
            "src/novel_forge/modules/topics/service.py",
            """
            from .provider_helper import second_order_wrapper as execute_topic

            def generate_topic():
                return execute_topic()
            """,
        )
        self._write(
            "src/novel_forge/modules/review/service.py",
            """
            def dynamic_review(adapter, content):
                operation = getattr(adapter, "review")
                return operation(content, {})
            """,
        )

        manifest = build_execution_inventory(self.root)

        process = self._find(
            manifest,
            source_file="src/novel_forge/modules/production_execution/process_supervisor.py",
            current_entrypoint="process.Popen",
        )
        self.assertEqual(
            process["side_effect_type"], "LOCAL_PROCESS_REMOTE_INFERENCE"
        )
        self.assertEqual(process["target_backend"], "codex-cli")

        provider = self._find(
            manifest,
            source_file="src/novel_forge/infrastructure/provider_client.py",
            current_entrypoint="client.responses.create",
        )
        self.assertEqual(provider["side_effect_type"], "MODEL_INFERENCE")
        self.assertEqual(provider["target_backend"], "remote-provider")

        wrapper = self._find(
            manifest,
            source_file="src/novel_forge/modules/topics/service.py",
            current_entrypoint="execute_topic",
        )
        self.assertEqual(wrapper["side_effect_type"], "MODEL_INFERENCE")
        self.assertEqual(wrapper["target_capability"], "creative.topic.generate")
        self.assertIn("indirect wrapper", wrapper["known_risks"])

        dynamic = self._find(
            manifest,
            source_file="src/novel_forge/modules/review/service.py",
            current_entrypoint="getattr:review",
        )
        self.assertEqual(dynamic["side_effect_type"], "MODEL_INFERENCE")
        self.assertEqual(
            dynamic["target_capability"], "review.chapter.evaluate"
        )

    def test_inventory_classifies_external_database_fixture_and_unknown_paths(self) -> None:
        self._write(
            "src/novel_forge/modules/source_intake/service.py",
            """
            import httpx as web

            def fetch_source(url):
                return web.get(url)
            """,
        )
        self._write(
            "src/novel_forge/modules/publishing/service.py",
            """
            import requests

            def publish_release(url, payload):
                return requests.post(url, json=payload)
            """,
        )
        self._write(
            "src/novel_forge/storage/authority.py",
            """
            import psycopg

            def connect_authority(url):
                return psycopg.connect(url)
            """,
        )
        self._write(
            "src/novel_forge/modules/provider_control/scripted.py",
            """
            class ScriptedProvider:
                def invoke(self, request):
                    return {"fixture_protocol_only": True}
            """,
        )
        self._write(
            "src/novel_forge/modules/odd/service.py",
            """
            def run_uncertain(executor):
                return executor.execute_remote_magic()
            """,
        )

        manifest = build_execution_inventory(self.root)

        fetch = self._find(
            manifest,
            source_file="src/novel_forge/modules/source_intake/service.py",
            current_entrypoint="web.get",
        )
        self.assertEqual(fetch["side_effect_type"], "REMOTE_RETRIEVAL")
        self.assertEqual(fetch["target_capability"], "source.remote.fetch")

        publish = self._find(
            manifest,
            source_file="src/novel_forge/modules/publishing/service.py",
            current_entrypoint="requests.post",
        )
        self.assertEqual(
            publish["side_effect_type"], "REMOTE_EXTERNAL_ACTION"
        )
        self.assertEqual(
            publish["target_capability"], "publishing.release.submit"
        )

        database = self._find(
            manifest,
            source_file="src/novel_forge/storage/authority.py",
            current_entrypoint="psycopg.connect",
        )
        self.assertEqual(database["side_effect_type"], "DATABASE_AUTHORITY")
        self.assertEqual(database["current_state_store"], "POSTGRESQL_AUTHORITY")

        fixture = self._find(
            manifest,
            source_file="src/novel_forge/modules/provider_control/scripted.py",
            current_entrypoint="ScriptedProvider.invoke",
        )
        self.assertEqual(fixture["side_effect_type"], "SCRIPTED_FIXTURE")
        self.assertFalse(fixture["production_reachable"])

        unknown = self._find(
            manifest,
            source_file="src/novel_forge/modules/odd/service.py",
            current_entrypoint="executor.execute_remote_magic",
        )
        self.assertEqual(unknown["side_effect_type"], "LEGACY_UNKNOWN")
        self.assertTrue(unknown["production_reachable"])
        self.assertIn(unknown["execution_owner_id"], manifest["blocking_owner_ids"])

    def test_inventory_does_not_treat_container_access_or_type_construction_as_io(self) -> None:
        self._write(
            "src/novel_forge/modules/source_intake/service.py",
            """
            class ProviderConfiguration:
                pass

            def deterministic_lookup(payload):
                config = ProviderConfiguration()
                return payload.get("source"), config
            """,
        )
        self._write(
            "src/novel_forge/storage/authority.py",
            """
            def write_authority(cursor):
                cursor.execute("UPDATE authority_operation SET status = 'RUNNING'")
            """,
        )

        manifest = build_execution_inventory(self.root)

        source_entries = [
            item
            for item in manifest["entries"]
            if item["source_file"]
            == "src/novel_forge/modules/source_intake/service.py"
        ]
        self.assertEqual(source_entries, [])
        database = self._find(
            manifest,
            source_file="src/novel_forge/storage/authority.py",
            current_entrypoint="cursor.execute",
        )
        self.assertEqual(database["side_effect_type"], "DATABASE_AUTHORITY")

    def test_writer_emits_stable_complete_json_and_markdown(self) -> None:
        self._write(
            "src/novel_forge/modules/drafting/service.py",
            """
            def draft(model):
                return model.generate("prompt", {})
            """,
        )
        json_output = self.root / "docs/reports/ledger.json"
        markdown_output = self.root / "docs/reports/ledger.md"

        first = write_execution_inventory(
            self.root, json_output, markdown_output
        )
        second = build_execution_inventory(self.root)

        self.assertEqual(first["artifact_hash"], second["artifact_hash"])
        stored = json.loads(json_output.read_text(encoding="utf-8"))
        self.assertEqual(stored, first)
        self.assertIn("# Production Execution Migration Ledger", markdown_output.read_text(encoding="utf-8"))
        self.assertTrue(first["entries"])
        for entry in first["entries"]:
            self.assertEqual(set(REQUIRED_LEDGER_FIELDS), set(entry))


if __name__ == "__main__":
    unittest.main()
