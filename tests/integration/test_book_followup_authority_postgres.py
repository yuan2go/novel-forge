from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from novel_forge.api.authority_dependencies import (
    build_production_execution_composition,
    build_reader_outcome_model_port,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
    BookFollowupCommand,
)
from novel_forge.modules.book_followup_authority.reader_policy import ReaderProxyPolicy
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_followup_authority.contracts import (
    BOOK_FOLLOWUP_DEFINITION_VERSION,
    LONGFORM_RECAP_DEFINITION,
    READER_OUTCOME_DEFINITION,
)
from novel_forge.modules.book_followup_authority.definitions import (
    book_followup_operation_definitions,
)
from novel_forge.modules.book_followup_authority.query import (
    BookFollowupProjectionQuery,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.modules.capability_packs.longform_profiles import build_reader_outcome_pack_profile
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration.capability_pack_postgres_support import (
    RELEASE_SHA,
    CapabilityPackPostgresHarness,
)


def _activate_reader_outcome_pack(harness: CapabilityPackPostgresHarness) -> None:
    definition = next(
        item
        for item in book_followup_operation_definitions(
            application_build_id="reader-outcome-pack-fixture",
            commit_sha=RELEASE_SHA,
        )
        if item["name"] == READER_OUTCOME_DEFINITION
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(definition)
        uow.cursor.execute(
            """
            SELECT definition_hash
            FROM authority_operation_definition
            WHERE name=%s AND definition_version=%s
            """,
            [READER_OUTCOME_DEFINITION, BOOK_FOLLOWUP_DEFINITION_VERSION],
        )
        definition_hash = str(uow.cursor.fetchone()[0])
        uow.commit()
    profile = build_reader_outcome_pack_profile(
        Path(__file__).resolve().parents[2],
        operation_definition_hash=definition_hash,
        pack_id=harness.pack_id,
    )
    harness._base_manifest = profile.manifest
    harness._base_catalog = profile.artifact_catalog
    scope = harness.approval_scope()
    scope["allowed_workflow_definition_refs"] = ["book_followup_reader_outcome@1.1.0"]
    pack = harness.register_compile_approve("1.0.0", generation=1, approval_scope=scope,
        proof_skill_ref=profile.agent_skill_ref)
    harness.activate(harness.deploy(pack))


class BookFollowupAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("book-followup-project")
        seed_authority_project_book(
            project_id=self.project_id, book_id=f"book:{self.project_id}"
        )
        self.temp = tempfile.TemporaryDirectory()
        settings = IndustrialSettings(
            root=Path(self.temp.name),
            environment="test",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                Path(self.temp.name) / "objects"
            ),
            "NOVEL_FORGE_AUTHORITY_WORKER_ID": "book-followup-pep",
        }
        execution = build_production_execution_composition(settings, env=env)
        self.assertTrue(execution.gateway.production_execution_gateway_backed)
        reader_port = build_reader_outcome_model_port(
            settings,
            execution=execution,
            env=env,
        )
        self.app = BookFollowupAuthorityApplication(
            DATABASE_URL,
            application_build_id="book-followup-integration",
            commit_sha=RELEASE_SHA,
            model_port=reader_port,
            worker_id="book-followup-worker",
        )
        self.principal = Principal(
            principal_id="book-followup-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "book.authority.execute",
                    "book.followup:*",
                }
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def seed(self, asset_type: str, content: dict, label: str) -> dict[str, str]:
        version_id = f"{self.project_id}:{label}:v1"
        content_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, %s)
                """,
                [f"{version_id}:asset", self.project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                """,
                [
                    version_id,
                    f"{version_id}:asset",
                    json.dumps(content),
                    content_hash,
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id, policy_version,
                    decision, evidence
                ) VALUES (%s, %s, 'book-followup-fixture-v1',
                          'ELIGIBLE', '{}'::jsonb)
                """,
                [f"{version_id}:qualification", version_id],
            )
            uow.commit()
        return {"asset_version_id": version_id, "content_hash": content_hash}

    def test_reader_outcome_uses_pep_external_effect_and_replays_once(self) -> None:
        draft = self.seed(
            "draft_version",
            {
                "contract_version": "draft-version-v1",
                "text": "A public choice exacts an irreversible cost.",
            },
            "draft",
        )
        canon = self.seed(
            "canon_snapshot",
            {"contract_version": "canon-snapshot-v1", "facts": []},
            "canon",
        )
        command = BookFollowupCommand(
            definition_name=READER_OUTCOME_DEFINITION,
            project_id=self.project_id,
            workspace_id=f"workspace:{self.project_id}",
            actor_id=self.principal.principal_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            idempotency_key=f"{self.project_id}:reader-outcome:chapter:1",
            payload=self.reader_payload(draft, canon),
            input_assets=(draft, canon),
        )

        admission = self.app.admit(command, principal=self.principal)
        self.app.reader_policies.configure(
            project_id=self.project_id,
            workspace_id=f"workspace:{self.project_id}",
            principal=self.principal,
            idempotency_key="reader-policy:v2",
            trace_id=identifier("policy-trace"),
            correlation_id=command.correlation_id,
            policy=ReaderProxyPolicy(policy_version="stricter-v2", confusion=0.05),
        )
        result = self.app.run_or_recover(admission)
        replay = self.app.admit(command, principal=self.principal)
        replay_result = self.app.run_or_recover(replay)

        self.assertFalse(admission.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(
            result.output.asset_version_id, replay_result.output.asset_version_id
        )
        self.assertEqual(
            {item.asset_type for item in result.output.materialized_outputs},
            {"reader_outcome_report", "reader_state_transition", "reader_issue_set"},
        )
        projection = BookFollowupProjectionQuery(DATABASE_URL)
        # The standalone operation is projected through its output binding. Book
        # linkage is tested separately by the Book Authority slice.
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), MIN(capability), MIN(status),
                       MIN(request_payload #>> '{_production_execution,execution_binding_domain}')
                FROM authority_external_effect
                WHERE operation_id=%s
                """,
                [admission.operation_id],
            )
            effect = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_attempt
                WHERE operation_id=%s
                """,
                [admission.operation_id],
            )
            attempts = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT binding.output_key, version.content
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s
                  AND binding.output_key IN (
                    'reader_outcome.report',
                    'reader_outcome.state_transition',
                    'reader_outcome.issue_set'
                  )
                """,
                [admission.operation_id],
            )
            reader_outputs = {
                str(row[0]): dict(row[1]) for row in uow.cursor.fetchall()
            }
        self.assertEqual(
            effect,
            (1, "model.reader_outcome", "SUCCEEDED", "reader_outcome"),
        )
        self.assertEqual(attempts, 1)
        self.assertEqual(
            {content["evidence_class"] for content in reader_outputs.values()},
            {"READER_PROXY_ADVISORY"},
        )
        report = reader_outputs["reader_outcome.report"]
        self.assertEqual(
            report["reader_proxy_policy_snapshot"]["policy"]["policy_version"],
            "reader-proxy-thresholds-v1",
        )
        self.assertFalse(report["canon_mutation_allowed"])
        self.assertFalse(report["future_intent_actualization_allowed"])
        self.assertFalse(report["direct_plan_activation_allowed"])
        self.assertTrue(
            projection
        )  # query type is production-wired; link view is Book-owned

    def test_reader_outcome_freezes_its_own_governed_pack_snapshot(self) -> None:
        self._assert_reader_pack_and_receipt_recovery(retry_after_receipt=False)

    def test_reader_new_attempt_reuses_original_context_receipt_and_accounting(self) -> None:
        self._assert_reader_pack_and_receipt_recovery(retry_after_receipt=True)

    def _assert_reader_pack_and_receipt_recovery(self, *, retry_after_receipt: bool) -> None:
        harness = CapabilityPackPostgresHarness("reader_outcome")
        _activate_reader_outcome_pack(harness)
        self.project_id = harness.project_id
        draft = self.seed(
            "draft_version",
            {
                "contract_version": "draft-version-v1",
                "text": "The accepted chapter converts trust into a public cost.",
            },
            "governed-reader-draft",
        )
        canon = self.seed(
            "canon_snapshot",
            {"contract_version": "canon-snapshot-v1", "facts": []},
            "governed-reader-canon",
        )
        settings = IndustrialSettings(
            root=Path(self.temp.name),
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "development",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID": harness.pack_id,
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                Path(self.temp.name) / "governed-reader-objects"
            ),
        }
        execution = build_production_execution_composition(settings, env=env)
        reader_port = build_reader_outcome_model_port(
            settings, execution=execution, env=env
        )
        interrupted = False

        def interrupt_after_receipt(checkpoint):
            nonlocal interrupted
            if retry_after_receipt and checkpoint == "after_provider_success" and not interrupted:
                interrupted = True
                raise KernelError("MODEL_EFFECT_RETRYABLE_HOST_INTERRUPTION", "Known completed fixture receipt before host commit")

        reader_port.fault_injector = interrupt_after_receipt
        app = BookFollowupAuthorityApplication(
            DATABASE_URL,
            application_build_id="reader-outcome-pack-fixture",
            commit_sha=RELEASE_SHA,
            model_port=reader_port,
            worker_id="governed-reader-worker",
        )
        principal = harness.principal(
            "reader-operator",
            "book.authority.execute",
            "book.followup:*",
        )
        payload = self.reader_payload(draft, canon)
        payload["book_id"] = harness.book_ids[0]
        admission = app.admit(
            BookFollowupCommand(
                definition_name=READER_OUTCOME_DEFINITION,
                project_id=harness.project_id,
                workspace_id=harness.workspace_id,
                actor_id=principal.principal_id,
                trace_id=identifier("governed-reader-trace"),
                correlation_id=identifier("governed-reader-correlation"),
                idempotency_key=f"{harness.project_id}:reader-outcome:governed",
                payload=payload,
                input_assets=(draft, canon),
            ),
            principal=principal,
        )

        original = None
        if retry_after_receipt:
            with self.assertRaisesRegex(KernelError, "MODEL_EFFECT_RETRYABLE_HOST_INTERRUPTION"):
                app.run_or_recover(admission)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                original = uow.cursor.execute("SELECT external_effect_id,request_hash,request_payload FROM authority_external_effect WHERE operation_id=%s", [admission.operation_id]).fetchone()
        result = app.run_or_recover(admission)

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT snapshot.pack_id,
                       snapshot.snapshot_payload->>'workflow_definition_ref',
                       snapshot.workflow_node_id, snapshot.snapshot_hash,
                       effect.status
                FROM authority_attempt_capability_pack_snapshot AS snapshot
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=snapshot.operation_id
                 AND effect.request_payload #>>
                     '{_production_execution,attempt_id}'=snapshot.attempt_id
                WHERE snapshot.operation_id=%s
                """,
                [admission.operation_id],
            )
            evidence = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s
                  AND binding.output_key='reader_outcome.report'
                """,
                [admission.operation_id],
            )
            report = dict(uow.cursor.fetchone()[0])
        self.assertEqual(evidence[0], harness.pack_id)
        self.assertEqual(
            evidence[1:3], ("book_followup_reader_outcome@1.1.0", "reader_outcome")
        )
        self.assertTrue(str(evidence[3]).startswith("sha256:"))
        self.assertEqual(evidence[4], "SUCCEEDED")
        self.assertEqual(report["mode"], "SHADOW")
        self.assertEqual(report["evidence_class"], "READER_PROXY_ADVISORY")
        self.assertEqual(report["confidence_status"], "NOT_MEASURED")
        if retry_after_receipt:
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                effects = uow.cursor.execute("SELECT external_effect_id,request_hash,request_payload FROM authority_external_effect WHERE operation_id=%s", [admission.operation_id]).fetchall()
                attempts = uow.cursor.execute("SELECT attempt_id,status FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [admission.operation_id]).fetchall()
                reservations = uow.cursor.execute("SELECT status FROM authority_budget_reservation WHERE operation_id=%s", [admission.operation_id]).fetchall()
            self.assertEqual(effects, [original])
            self.assertEqual([row[1] for row in attempts], ["FAILED_RETRYABLE", "SUCCEEDED"])
            self.assertEqual(reservations, [("SETTLED",)])
            context_pointer = next(item for item in original[2]["_production_execution"]["input_artifacts"] if item["artifact_type"] == "context_bundle")
            retained = reader_port.capability_binder._reader_context_bundle(operation_id=admission.operation_id,
                attempt_id=attempts[-1][0], project_id=harness.project_id, trace_id="source-retention", correlation_id="source-retention",
                artifacts=[item for item in original[2]["_production_execution"]["input_artifacts"] if item["artifact_type"] in {"draft_version", "canon_snapshot"}])
            self.assertEqual((retained.asset_version_id, retained.content_hash), (context_pointer["asset_version_id"], context_pointer["content_hash"]))
        self.assertFalse(report["publish_blocking"])
        self.assertTrue(result.output.asset_version_id)

    def test_longform_recap_materializes_deviation_and_authority_proposals(
        self,
    ) -> None:
        reader = self.seed(
            "reader_state",
            {"contract_version": "reader-state-v1", "confusion": 0.8},
            "reader-state",
        )
        canon = self.seed(
            "canon_snapshot",
            {
                "contract_version": "canon-snapshot-v2",
                "project_id": self.project_id,
                "book_id": f"book:{self.project_id}",
                "accepted_through_chapter": 10,
                "current_facts": [],
            },
            "canon-recap",
        )
        story_state = self.seed(
            "story_state_snapshot",
            {
                "contract_version": "story-state-snapshot-v2",
                "project_id": self.project_id,
                "book_id": f"book:{self.project_id}",
                "accepted_through_chapter": 10,
                "current_state": {},
            },
            "story-state-recap",
        )
        chapter_outcome = self.seed(
            "chapter_outcome",
            {
                "contract_version": "chapter-outcome-v3",
                "project_id": self.project_id,
                "book_id": f"book:{self.project_id}",
                "chapter_number": 10,
            },
            "chapter-outcome-recap",
        )
        payload = {
            "book_id": f"book:{self.project_id}",
            "checkpoint_type": "ARC_CHECKPOINT",
            "chapter_range": [1, 10],
            "book_design_version": "book-design:v1",
            "book_plan_version": "book-plan:v1",
            "volume_plan_version": "volume-plan:v1",
            "arc_plan_versions": ["arc-plan:v1"],
            "canon_snapshot_version": canon["asset_version_id"],
            "story_state_version": story_state["asset_version_id"],
            "reader_state_version": reader["asset_version_id"],
            "quality_trend_version": "quality-trend:v1",
            "chapter_outcome_versions": [chapter_outcome["asset_version_id"]],
            "observations": {
                "reader_state": {"confusion": 0.8},
                "canon": {"conflicts": [{"id": "c1"}]},
                "quality_trend": {"direction": "DECLINING"},
            },
        }
        admission = self.app.admit(
            BookFollowupCommand(
                definition_name=LONGFORM_RECAP_DEFINITION,
                project_id=self.project_id,
                workspace_id=f"workspace:{self.project_id}",
                actor_id=self.principal.principal_id,
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                idempotency_key=f"{self.project_id}:longform:arc:1",
                payload=payload,
                input_assets=(reader, canon, story_state, chapter_outcome),
            ),
            principal=self.principal,
        )
        result = self.app.run_or_recover(admission)

        self.assertEqual(
            {item.asset_type for item in result.output.materialized_outputs},
            {
                "longform_recap",
                "longform_deviation_report",
                "plan_adjustment_proposal",
                "replan_request",
            },
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s
                  AND binding.output_key='longform.recap.adjustment_proposal'
                """,
                [admission.operation_id],
            )
            proposal = dict(uow.cursor.fetchone()[0])
        self.assertFalse(proposal["mutates_plan"])
        self.assertFalse(proposal["activation_allowed"])
        self.assertEqual(proposal["required_authority"], "PLAN_CHANGE_AUTHORITY")
        self.assertEqual(proposal["decision_status"], "AUTHORITY_PENDING")

    def reader_payload(
        self, draft: dict[str, str], canon: dict[str, str]
    ) -> dict[str, object]:
        return {
            "book_id": f"book:{self.project_id}",
            "chapter_id": "chapter:1",
            "chapter_number": 1,
            "final_draft_asset_version": draft["asset_version_id"],
            "chapter_plan_asset_version": "chapter-plan:v1",
            "book_design_version": "book-design:v1",
            "book_plan_version": "book-plan:v1",
            "parent_plan_versions": {
                "volume_plan_version": "volume-plan:v1",
                "arc_plan_versions": ["arc-plan:v1"],
            },
            "reader_segment_version": "reader-segment:v1",
            "reader_contract_version": "reader-contract:v1",
            "platform_profile_version": "platform-profile:v1",
            "canon_snapshot_version": canon["asset_version_id"],
            "chapter_outcome_version": "chapter-outcome:v1",
            "story_state_version": "story-state:v1",
            "quality_evidence_version": "quality:v1",
            "input_manifest_ref": "input-manifest:v1",
            "previous_reader_state_version": "reader-state:none",
            "evaluation_profile_version": "reader-evaluation:v1",
            "model_strategy_version": "model-strategy:v1",
            "context_token_budget": 8_000,
        }


if __name__ == "__main__":
    unittest.main()
