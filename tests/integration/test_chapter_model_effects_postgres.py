from __future__ import annotations

import unittest
import tempfile
import hashlib
import json
from pathlib import Path

from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
from novel_forge.modules.chapter_authority.model_effects import (
    ChapterModelExternalEffectAdapter,
    ChapterModelRoute,
    ExternalEffectChapterModelPort,
    ModelProviderResult,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
)
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    FakeDeterministicProvider,
    LocalFileObjectStoreAdapter,
    ProviderResult,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class _ModelAdapter:
    provider = "fixture_model_effect_provider"

    def __init__(self, *, fail_after_send: bool = False) -> None:
        self.fail_after_send = fail_after_send
        self.calls = 0

    def execute(self, *, stable_idempotency_key, capability, request_payload):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail_after_send:
            raise ExternalEffectAdapterError("connection lost", request_sent=True)
        if capability == "model.draft":
            output = {"text": "The promise is public, but its cost remains abstract."}
        elif capability == "model.review":
            output = {
                "decision": "NEEDS_REVISION",
                "score": 70,
                "issues": [
                    {
                        "code": "COST_NOT_CONCRETE",
                        "severity": "blocking",
                        "message": "The cost must be visible.",
                    }
                ],
            }
        else:
            output = {
                "text": "The protagonist surrenders the only safe route home before every witness.",
                "resolved_issue_codes": ["COST_NOT_CONCRETE"],
            }
        result = ModelProviderResult(
            output=output,
            provider_id=self.provider,
            model_id="fixture-model-v1",
            prompt_version="draft-prompt-v1",
            skill_version="prose-generation-v1",
            input_tokens=120,
            output_tokens=40,
            cost_amount="0.0042",
            currency="USD",
            real_model_call=True,
        )
        return ProviderResult(
            outcome="success",
            provider_correlation_id=f"fixture:{stable_idempotency_key}",
            evidence=result.to_evidence(),
        )

    def query(self, *, stable_idempotency_key, capability, request_payload):  # type: ignore[no-untyped-def]
        return ProviderResult("ambiguous", "", {"provider_state": "unknown"})


class _StageModelAdapter:
    name = "stage-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt, context=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if "canon-semantic-extraction-v2" in prompt:
            return {
                "canon_facts": [
                    {
                        "subject": "protagonist", "predicate": "gave_up",
                        "object": "safe_route_home", "evidence_start": 0,
                        "evidence_end": 10, "confidence": 0.95,
                    }
                ],
                "character_state_changes": [], "relationship_changes": [],
                "timeline_events": [], "foreshadow_changes": [],
                "promise_changes": [], "reward_changes": [],
                "world_rule_usages": [], "power_state_changes": [],
                "narrative_pattern_fingerprints": [], "theme_movements": [],
                "antagonist_pressure_changes": [],
                "usage": {"input_tokens": 30, "output_tokens": 20},
                "cost": {"amount": "0.001", "currency": "USD"},
            }
        return {
            "text": "The promise is public, but its cost remains abstract.",
            "usage": {"input_tokens": 12, "output_tokens": 8},
            "cost": {"amount": "0.001", "currency": "USD"},
        }

    def review(self, content, context=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if (context or {}).get("rubric") == "chapter-authority-rereview-v1":
            return {
                "score": 91,
                "issues": [],
                "cost": {"amount": "0.001", "currency": "USD"},
            }
        return {
            "score": 70,
            "issues": [
                {
                    "dimension": "cost_not_concrete",
                    "severity": "high",
                    "message": "The cost must be visible.",
                }
            ],
            "cost": {"amount": "0.001", "currency": "USD"},
        }

    def revise(self, content, review, context=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        return {
            "text": "The protagonist surrenders the only safe route home before every witness.",
            "resolved_issue_codes": ["COST_NOT_CONCRETE"],
            "cost": {"amount": "0.001", "currency": "USD"},
        }


class ChapterModelEffectsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def _request(self) -> ChapterHandlerRequest:
        project_id = identifier("model-project")
        operation_id = identifier("model-operation")
        definition_name = identifier("model-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
            )
        return ChapterHandlerRequest(
            operation_id=operation_id,
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            command={"chapter": 1},
            inputs=(),
        )

    def _release_evidence(self, project_id: str) -> tuple[dict[str, object], ...]:
        candidates: list[dict[str, object]] = [
            {
                "asset_version_id": f"{project_id}:checklist-v1",
                "asset_type": "operator_checklist",
                "project_id": project_id,
                "safe_summary": "Release checklist completed.",
                "structured_facts": [{"key": "completed", "value": True}],
                "estimated_tokens": 8,
                "narrative_function": "release_evidence",
            },
            {
                "asset_version_id": f"{project_id}:approval-v1",
                "asset_type": "operator_approval",
                "project_id": project_id,
                "safe_summary": "Fixture release approval.",
                "structured_facts": [{"key": "approved", "value": True}],
                "estimated_tokens": 8,
                "narrative_function": "release_evidence",
            },
        ]
        with transaction() as connection, connection.cursor() as cursor:
            for candidate in candidates:
                content = {
                    "safe_summary": candidate["safe_summary"],
                    "structured_facts": candidate["structured_facts"],
                }
                content_hash = "sha256:" + hashlib.sha256(
                    json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                candidate["content_hash"] = content_hash
                asset_id = f"{candidate['asset_version_id']}:asset"
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, candidate["asset_type"]],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
                    """,
                    [candidate["asset_version_id"], asset_id, json.dumps(content), content_hash],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_qualification (
                        qualification_id, asset_version_id, policy_version, decision, evidence
                    ) VALUES (%s, %s, 'model-fixture-release-v1', 'ELIGIBLE', '{}'::jsonb)
                    """,
                    [f"{candidate['asset_version_id']}:qualification", candidate["asset_version_id"]],
                )
        return tuple(candidates)

    def test_success_records_effect_receipt_model_call_and_cost_once(self) -> None:
        request = self._request()
        adapter = _ModelAdapter()
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id="model-worker",
            max_cost_per_call="0.01",
        )

        first = port.invoke(request, stage="draft", payload={"prompt": "write"})
        replay = port.invoke(request, stage="draft", payload={"prompt": "write"})

        self.assertEqual(first.output, replay.output)
        self.assertEqual(adapter.calls, 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_external_effect WHERE operation_id = %s",
                [request.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "SUCCEEDED")
            cursor.execute(
                """
                SELECT asset.asset_type, COUNT(*)
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                WHERE binding.operation_id = %s
                GROUP BY asset.asset_type
                """,
                [request.operation_id],
            )
            self.assertEqual(dict(cursor.fetchall()), {"cost_ledger": 1, "model_call_log": 1})

    def test_exception_after_send_is_unknown_and_not_blindly_retried(self) -> None:
        request = self._request()
        adapter = _ModelAdapter(fail_after_send=True)
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id="model-worker",
        )

        with self.assertRaisesRegex(KernelError, "EFFECT_ADAPTER_EXCEPTION_RECORDED"):
            port.invoke(request, stage="draft", payload={"prompt": "write"})
        with self.assertRaises(KernelError):
            port.invoke(request, stage="draft", payload={"prompt": "write"})

        self.assertEqual(adapter.calls, 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_external_effect WHERE operation_id = %s",
                [request.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "UNKNOWN")

    def test_full_chapter_slice_uses_five_model_effects_and_authority_ledgers(self) -> None:
        project_id = identifier("model-slice-project")
        stage_model = _StageModelAdapter()
        adapter = ChapterModelExternalEffectAdapter(
            {
                stage: ChapterModelRoute(
                    adapter=stage_model,
                    provider_id="fixture-provider",
                    model_id=f"fixture-{stage}-model",
                    prompt_version=f"fixture-{stage}-prompt-v1",
                    skill_version=f"fixture-{stage}-skill-v1",
                    real_model_call=False,
                )
                for stage in ("draft", "review", "revision", "canon_extraction")
            }
        )
        export_directory = tempfile.TemporaryDirectory()
        self.addCleanup(export_directory.cleanup)
        application = ChapterAuthorityApplication(
            DATABASE_URL,
            model_adapter=adapter,
            object_store_adapter=LocalFileObjectStoreAdapter(Path(export_directory.name)),
            worker_id="model-worker",
            max_cost_per_model_call="0.01",
        )
        result = application.run(
            SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="chapter-slice-worker",
                chapter=1,
                title="A Visible Cost",
                premise="A public promise becomes irreversible.",
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                application_build_id="chapter-model-effect-test",
                commit_sha="d" * 40,
                context_candidates=self._release_evidence(project_id),
            ),
        )

        self.assertEqual(result.root_status, "SUCCEEDED")
        self.assertEqual(stage_model.calls, 5)
        exported = Path(export_directory.name) / f"chapters/{project_id}/1/chapter.txt"
        self.assertIn("surrenders the only safe route home", exported.read_text())
        query = application.query
        listed = query.list_runs(project_id=project_id)
        detail = query.require_run(
            project_id=project_id,
            root_operation_id=result.root_operation_id,
        )
        self.assertEqual(listed[0]["root_operation_id"], result.root_operation_id)
        self.assertEqual(listed[0]["status"], "SUCCEEDED")
        self.assertEqual(detail["saga"]["status"], "SUCCEEDED")
        self.assertEqual(len(detail["operations"]), 13)
        self.assertEqual(len(detail["primary_outputs"]), 12)
        self.assertEqual(len(detail["model_effects"]), 5)
        self.assertEqual(query.list_runs(project_id=identifier("other-project")), [])
        with self.assertRaisesRegex(KernelError, "CHAPTER_RUN_NOT_FOUND"):
            query.require_run(
                project_id=identifier("other-project"),
                root_operation_id=result.root_operation_id,
            )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT capability, status, COUNT(*)
                FROM authority_external_effect
                WHERE project_id = %s AND provider = %s
                GROUP BY capability, status
                ORDER BY capability
                """,
                [project_id, adapter.provider],
            )
            self.assertEqual(
                cursor.fetchall(),
                [
                    ("model.canon_extraction", "SUCCEEDED", 1),
                    ("model.draft", "SUCCEEDED", 1),
                    ("model.review", "SUCCEEDED", 2),
                    ("model.revision", "SUCCEEDED", 1),
                ],
            )
            cursor.execute(
                """
                SELECT asset.asset_type, COUNT(*)
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                WHERE operation.root_operation_id = %s
                  AND asset.asset_type IN ('model_call_log', 'cost_ledger')
                GROUP BY asset.asset_type
                """,
                [result.root_operation_id],
            )
            self.assertEqual(dict(cursor.fetchall()), {"cost_ledger": 5, "model_call_log": 5})


if __name__ == "__main__":
    unittest.main()
