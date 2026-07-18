from __future__ import annotations

import unittest
import hashlib
import json

from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.handlers import (
    DeterministicFixtureChapterProvider,
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
    admit_single_chapter_saga,
)
from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class ChapterAuthoritySchedulerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_admission_does_not_execute_and_ticks_rebuild_full_saga(self) -> None:
        project_id = identifier("async-chapter-project")
        candidates = self._release_evidence(project_id)
        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="trusted-operator",
            chapter=1,
            title="A Durable Promise",
            premise="A promise creates a visible irreversible cost.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="async-chapter-test",
            commit_sha="f" * 40,
            idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(candidates),
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=request,
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )

        self.assertEqual(admission.status, "ACCEPTED")
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        seen = []
        for _ in ChapterNode:
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            seen.append(tick.node)
            self.assertEqual(tick.operation_status, "SUCCEEDED")

        terminal = scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        self.assertEqual(seen, [node.value for node in ChapterNode])
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        self.assertEqual(terminal.recovery_mode, "terminal_replay")

    @staticmethod
    def _release_evidence(project_id: str) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        with transaction() as connection, connection.cursor() as cursor:
            for asset_type, summary, fact_key in (
                ("operator_checklist", "Operator checklist completed.", "completed"),
                ("operator_approval", "Operator approved fixture release.", "approved"),
            ):
                content = {
                    "safe_summary": summary,
                    "structured_facts": [{"key": fact_key, "value": True}],
                }
                content_hash = "sha256:" + hashlib.sha256(
                    json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                version_id = identifier(asset_type)
                asset_id = identifier(f"{asset_type}-asset")
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
                    """,
                    [version_id, asset_id, json.dumps(content), content_hash],
                )
                candidates.append(
                    {
                        "asset_version_id": version_id,
                        "asset_type": asset_type,
                        "project_id": project_id,
                        "content_hash": content_hash,
                        "estimated_tokens": 20,
                        **content,
                        "narrative_function": "release_evidence",
                    }
                )
        return candidates


if __name__ == "__main__":
    unittest.main()
