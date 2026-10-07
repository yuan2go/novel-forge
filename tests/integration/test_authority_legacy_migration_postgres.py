from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.legacy_migration import (
    LegacyMigrationApprovalApplication,
    LegacyMigrationDecisionCommand,
    LegacyMigrationService,
    MigrationDecision,
)
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
    ProjectAuthorityQuery,
)
from novel_forge.modules.source_authority import (
    CommitSourceTransformCommand,
    RegisterSourceDocumentCommand,
    SourceAuthorityApplication,
    SourceChunkCandidate,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.database_runtime import DatabaseRuntime, DatabaseRuntimeConfig
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, run_migrations
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
    materialize_historical_fixture_at_migration,
)


def _migration_plan_content(
    *, project_id: str, book_id: str, plan_type: str, logical_key: str
) -> dict:
    content = {
        "contract_id": f"contract:{project_id}:{logical_key}",
        "project_id": project_id,
        "book_id": book_id,
        "logical_key": logical_key,
        "objective": f"objective for {logical_key}",
        "entry_state_ref": "story-state:entry",
        "exit_state_spec": {"pressure": "advanced"},
        "hard_constraints": ["preserve accepted history"],
        "soft_constraints": ["vary rhythm"],
        "required_events": ["meaningful escalation"],
        "forbidden_events": ["premature ending"],
        "required_payoffs": ["local consequence"],
        "forbidden_payoffs": ["final mystery closure"],
        "character_deltas": [{"character": "protagonist"}],
        "world_deltas": [{"rule": "pressure rises"}],
        "relationship_deltas": [{"pair": "protagonist:rival"}],
        "arc_contributions": ["mainline advances"],
        "canon_dependencies": [],
        "quality_targets": {"minimum": "qualified"},
        "budget_policy_ref": "budget:planning:v1",
        "context_profile_ref": "context:planning:v1",
    }
    if plan_type in {"book_plan", "outline_version"}:
        content.update(
            {
                "reader_promise": "progress with meaningful cost",
                "central_conflict_engine": "agency versus control",
                "protagonist_transformation": "reactive to responsible",
                "antagonist_escalation": "adapts to every public win",
                "world_evolution": "institutions polarize",
                "relationship_evolution": "trust becomes negotiated",
                "theme_evolution": "power tests responsibility",
                "ending_contract": "costly self-authored choice",
                "volume_skeleton": ["volume one", "volume two"],
                "major_turns": ["first reversal"],
                "climax_distribution": ["volume climax"],
                "long_promise_payoff": ["identity truth"],
                "length_strategy": {"target_chapters": 100},
                "risk_register": ["power inflation"],
            }
        )
    elif plan_type == "volume_plan":
        content.update(
            {
                "volume_function": "establish and overturn local order",
                "stage_conflict": "institutional capture",
                "stage_antagonist": "regional operator",
                "irreversible_change": "public commitment",
                "midpoint": "ally defects",
                "climax": "costly local victory",
                "settlement": "new obligation",
                "next_volume_bridge": "central power responds",
                "chapter_range": [1, 20],
            }
        )
    elif plan_type == "arc_plan":
        content.update(
            {
                "arc_type": "mainline",
                "resistance": "adaptive antagonist",
                "escalation": "cost moves from private to public",
                "turn": "apparent ally reveals leverage",
                "choice": "protect status or reveal truth",
                "cost": "loss of safe identity",
                "result": "temporary strategic access",
                "consequence": "antagonist changes tactics",
                "dependencies": ["book reader promise"],
                "closure_conditions": ["choice paid for"],
                "cross_volume_scope": [],
            }
        )
    elif plan_type == "chapter_group_plan":
        content.update(
            {
                "local_objective": "force a public commitment",
                "trigger": "resource is seized",
                "resistance_escalation": "each move reveals a deeper cost",
                "turn": "trusted route is compromised",
                "local_climax": "commitment under surveillance",
                "information_release": ["antagonist knows the mechanism"],
                "emotion_curve": ["uncertainty", "resolve", "cost"],
                "antagonist_actions": ["observe", "contain", "counter"],
                "chapter_function_matrix": [
                    _migration_chapter_row(1, "DISCOVERY", "new threat"),
                    _migration_chapter_row(2, "ESCALATION", "cost revealed"),
                    _migration_chapter_row(3, "REVERSAL", "choice demanded"),
                ],
                "chapter_range": [1, 3],
                "cost_range": [100, 300],
                "primary_arc_ids": ["arc:main"],
                "secondary_arc_ids": [],
                "required_arc_contributions": ["arc:main"],
                "arc_checkpoint_expectations": [
                    {
                        "arc_plan_version_id": "arc:main",
                        "expectation": "the public commitment advances the main Arc",
                    }
                ],
            }
        )
    else:
        content.update(_migration_chapter_row(1, "DISCOVERY", "new threat"))
        content["required_arc_contributions"] = []
    return content


def _migration_chapter_row(
    chapter: int, primary_function: str, ending_hook: str
) -> dict:
    return {
        "chapter_number": chapter,
        "primary_function": primary_function,
        "secondary_functions": ["continuity"],
        "required_state_delta": {"pressure": chapter},
        "required_arc_contributions": ["mainline"],
        "promise_action": "advance",
        "foreshadow_action": "plant",
        "reward_action": "partial",
        "ending_hook": ending_hook,
        "prohibited_outcomes": ["premature closure"],
        "narrative_density": "MEDIUM",
        "arc_cadence": [
            {
                "arc_plan_version_id": "arc:main",
                "action": "ADVANCE",
            }
        ],
        "obligation_actions": [],
        "reader_experience": {
            "target_emotion": {
                "DISCOVERY": "uneasy curiosity",
                "ESCALATION": "mounting pressure",
                "REVERSAL": "costly surprise",
            }.get(primary_function, "uncertain momentum"),
            "reward_mode": {
                "DISCOVERY": "DISCOVERY",
                "ESCALATION": "PROGRESS",
                "REVERSAL": "REVERSAL",
            }.get(primary_function, "PROGRESS"),
        },
    }


class LegacyMigrationAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_import_is_resumable_ineligible_and_reconciled(self) -> None:
        project_id = identifier("legacy-project")
        workspace_id = identifier("legacy-workspace")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-migration-integration",
            commit_sha="b" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspaces = root / "data" / "workspaces"
            materials = root / "data" / "materials"
            workspaces.mkdir(parents=True)
            materials.mkdir(parents=True)
            self._write(
                workspaces / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Imported Project",
                    "content": {
                        "project_id": project_id,
                        "memory": {"project_title": "Imported Project"},
                        "project_config": {
                            "genre": "mystery",
                            "style_profile_path": "data/styles/legacy.json",
                        },
                    },
                    "references": [],
                },
            )
            self._write(
                materials / "material.json",
                {
                    "id": "material-1",
                    "type": "material_card",
                    "project_id": project_id,
                    "content": {"mechanism": "pressure escalates through visible cost"},
                    "references": [],
                },
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            first = service.import_snapshot(root)
            second = service.import_snapshot(root, resume=True)
            verified = service.verify(first["migration_run_id"], snapshot_root=root)

        self.assertEqual(first["status"], "DOMAIN_REVIEW_PENDING")
        self.assertEqual(second["migration_run_id"], first["migration_run_id"])
        self.assertEqual(second["counts"], first["counts"])
        self.assertEqual(verified["status"], "DOMAIN_REVIEW_PENDING")
        self.assertEqual(verified["verification_status"], "PASS")
        self.assertEqual(verified["production_assets_activated"], 0)
        self.assertEqual(verified["needs_review_count"], 2)
        self.assertEqual(verified["target_asset_version_count"], 2)
        self.assertEqual(verified["distinct_target_asset_version_count"], 2)
        self.assertEqual(verified["target_hash_match_count"], 2)
        self.assertEqual(verified["qualification_count"], 2)
        project = ProjectAuthorityQuery(DATABASE_URL).require_project(project_id)
        self.assertEqual(project["status"], "PAUSED")
        self.assertNotIn("style_profile_path", project["content"]["config"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE item.status='ACTIVATED'),
                       COUNT(*) FILTER (WHERE item.status='NEEDS_REVIEW'),
                       ARRAY_AGG(asset.asset_type ORDER BY asset.asset_type)
                FROM authority_legacy_migration_item AS item
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = item.target_asset_version_id
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                JOIN authority_asset_qualification AS qualification
                  ON qualification.asset_version_id = version.asset_version_id
                WHERE item.migration_run_id = %s
                """,
                [first["migration_run_id"]],
            )
            count, activated, needs_review, asset_types = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_operation
                WHERE project_id=%s
                  AND definition_name='legacy_migration.material_card.convert'
                """,
                [project_id],
            )
            operation_count = int(uow.cursor.fetchone()[0])
        self.assertEqual(int(count), 2)
        self.assertEqual((int(activated), int(needs_review)), (0, 2))
        self.assertEqual(list(asset_types), ["material_card", "project_record"])
        self.assertEqual(operation_count, 1)

    def test_synthetic_snapshot_fault_resume_conflicts_and_quarantine(self) -> None:
        project_id = identifier("legacy-synthetic-project")
        other_project_id = identifier("legacy-other-project")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-migration-fault-integration",
            commit_sha="c" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "data" / "assets"
            workspaces = root / "data" / "workspaces"
            sources = root / "data" / "sources"
            assets.mkdir(parents=True)
            workspaces.mkdir(parents=True)
            sources.mkdir(parents=True)
            self._write(
                workspaces / "project-1.json",
                {
                    "id": identifier("workspace-1"),
                    "type": "project_workspace_state",
                    "title": "Synthetic Project",
                    "content": {"project_id": project_id},
                    "references": [],
                },
            )
            self._write(
                workspaces / "project-2.json",
                {
                    "id": identifier("workspace-2"),
                    "type": "project_workspace_state",
                    "title": "Other Project",
                    "content": {"project_id": other_project_id},
                    "references": [],
                },
            )
            duplicate = {
                "id": "material-duplicate",
                "type": "material_card",
                "project_id": project_id,
                "content": {"mechanism": "bounded pressure"},
                "references": [],
            }
            self._write(assets / "01-material.json", duplicate)
            self._write(assets / "02-material-duplicate.json", duplicate)
            self._write(
                assets / "03-material-conflict.json",
                {**duplicate, "content": {"mechanism": "conflicting content"}},
            )
            self._write(
                assets / "04-other-project.json",
                {
                    "id": "other-asset",
                    "type": "material_card",
                    "project_id": other_project_id,
                    "content": {"mechanism": "other scope"},
                    "references": [],
                },
            )
            self._write(
                assets / "05-cross-project.json",
                {
                    "id": "cross-project-plan",
                    "type": "chapter_plan",
                    "project_id": project_id,
                    "content": {"goal": "must quarantine"},
                    "references": ["other-asset"],
                },
            )
            self._write(
                assets / "06-missing-reference.json",
                {
                    "id": "missing-reference-plan",
                    "type": "chapter_plan",
                    "project_id": project_id,
                    "content": {"goal": "must quarantine"},
                    "references": ["not-present"],
                },
            )
            self._write(
                assets / "07-approved-plan.json",
                {
                    "id": "approved-plan",
                    "type": "book_plan",
                    "status": "APPROVED",
                    "project_id": project_id,
                    "content": {"volumes": []},
                    "metadata": {"migration_approved": True},
                    "references": [],
                },
            )
            self._write(
                sources / "08-unverified-source.json",
                {
                    "id": "unverified-source",
                    "type": "source_document",
                    "project_id": project_id,
                    "content": {"rights_authorization": "unknown"},
                    "references": [],
                },
            )
            (assets / "09-large-blob.json").write_text(
                json.dumps({"type": "binary_blob", "payload": "x" * (8 * 1024 * 1024)}),
                encoding="utf-8",
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)

            with self.assertRaisesRegex(RuntimeError, "MIGRATION_FAULT_INJECTED"):
                service.import_snapshot(root, fault_after_items=2)
            resumed = service.import_snapshot(root, resume=True)
            replayed = service.import_snapshot(root, resume=True)
            verified = service.verify(resumed["migration_run_id"], snapshot_root=root)

        self.assertEqual(resumed["migration_run_id"], replayed["migration_run_id"])
        self.assertEqual(resumed["item_counts"], replayed["item_counts"])
        self.assertIn(verified["status"], {"FAILED", "QUARANTINED"})
        self.assertEqual(verified["verification_status"], "FAIL")
        self.assertFalse(verified["reconciled"])
        # Bootstrap shells remain PAUSED and are not domain activation proof.
        # The self-declared approved BookPlan also remains NEEDS_REVIEW.
        self.assertEqual(verified["production_assets_activated"], 0)
        self.assertGreaterEqual(verified["needs_review_count"], 1)
        self.assertEqual(verified["unresolved_reference_count"], 0)
        self.assertTrue(verified["reference_integrity"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT reason_code, source_payload, object_reference
                FROM authority_data_quarantine
                WHERE migration_run_id=%s
                ORDER BY reason_code
                """,
                [resumed["migration_run_id"]],
            )
            quarantine = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT target_asset_version_id)
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND target_asset_version_id IS NOT NULL
                """,
                [resumed["migration_run_id"]],
            )
            target_count, distinct_target_count = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT status, materialization_level, next_phase,
                       phase_version, reference_state
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                  AND source_ref='data/assets/07-approved-plan.json'
                """,
                [resumed["migration_run_id"]],
            )
            approved_plan = uow.cursor.fetchone()
        reasons = {row[0] for row in quarantine}
        self.assertTrue(
            {
                "BUSINESS_IDENTITY_CONTENT_CONFLICT",
                "CROSS_PROJECT_REFERENCE",
                "MISSING_REFERENCE",
                "SOURCE_RIGHTS_UNVERIFIED",
                "OBJECT_STORE_REQUIRED",
            }
            <= reasons
        )
        large = next(row for row in quarantine if row[0] == "OBJECT_STORE_REQUIRED")
        self.assertEqual(large[1], {})
        self.assertEqual(large[2]["verification_status"], "REQUIRED")
        self.assertEqual(int(target_count), int(distinct_target_count))
        self.assertEqual(
            tuple(approved_plan),
            ("NEEDS_REVIEW", "ARCHIVAL_NATIVE", "ACTIVATE", 6, "RESOLVED"),
        )

    def test_independent_approval_is_versioned_audited_and_does_not_activate(
        self,
    ) -> None:
        project_id = identifier("migration-approval-project")
        workspace_id = identifier("migration-approval-workspace")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-migration-approval-integration",
            commit_sha="d" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "workspaces").mkdir(parents=True)
            (root / "data" / "assets").mkdir(parents=True)
            self._write(
                root / "data" / "workspaces" / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Approval Project",
                    "content": {"project_id": project_id},
                },
            )
            self._write(
                root / "data" / "assets" / "draft.json",
                {
                    "id": "draft-approval-1",
                    "type": "draft",
                    "status": "APPROVED",
                    "project_id": project_id,
                    "metadata": {"migration_approved": True},
                    "content": {"chapter": 1, "text_digest": "fixture-only"},
                },
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            imported = service.import_snapshot(root)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id, item_version, source_hash,
                       target_asset_version_id, status
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND source_asset_type='draft'
                """,
                [imported["migration_run_id"]],
            )
            item_id, item_version, source_hash, target_version_id, status = (
                uow.cursor.fetchone()
            )
        self.assertEqual(status, "NEEDS_REVIEW")
        validation = service.validate_domain_item(
            str(item_id), expected_item_version=int(item_version)
        )
        command = LegacyMigrationDecisionCommand(
            migration_run_id=imported["migration_run_id"],
            migration_item_id=str(item_id),
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id="migration-reviewer",
            decision=MigrationDecision.APPROVE,
            reason="archival envelope and source hash independently verified",
            expected_item_version=int(validation["item_version"]),
            source_hash=str(source_hash),
            target_asset_version_id=str(target_version_id),
            migration_validation_id=str(validation["migration_validation_id"]),
            idempotency_key=f"approve:{item_id}:{source_hash}",
            trace_id=f"trace:{imported['migration_run_id']}",
            correlation_id=f"correlation:{project_id}",
        )
        application = LegacyMigrationApprovalApplication(
            DATABASE_URL,
            application_build_id="legacy-migration-approval-integration",
            commit_sha="d" * 40,
        )
        approved = application.execute(command)
        replayed = application.execute(command)
        self.assertEqual(approved["operation_id"], replayed["operation_id"])
        self.assertTrue(replayed["replayed"])
        self.assertEqual(approved["status"], "QUALIFIED")
        self.assertTrue(approved["activation_pending"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT item.status, version.lifecycle, version.eligibility,
                       COUNT(decision.migration_decision_id)
                FROM authority_legacy_migration_item AS item
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=item.target_asset_version_id
                LEFT JOIN authority_legacy_migration_decision AS decision
                  ON decision.migration_item_id=item.migration_item_id
                WHERE item.migration_item_id=%s
                GROUP BY item.status, version.lifecycle, version.eligibility
                """,
                [item_id],
            )
            persisted = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(DISTINCT audit.audit_id),
                       COUNT(DISTINCT outbox.outbox_id)
                FROM audit_log AS audit
                JOIN outbox_event AS outbox
                  ON outbox.payload->>'operation_id'=audit.operation_id
                WHERE audit.operation_id=%s
                  AND outbox.topic='legacy_migration.item.decided'
                """,
                [approved["operation_id"]],
            )
            audit_count, outbox_count = uow.cursor.fetchone()
        self.assertEqual(
            tuple(persisted), ("QUALIFIED", "IMPORTED", "PENDING_EVALUATION", 1)
        )
        self.assertGreaterEqual(int(audit_count), 1)
        self.assertEqual(int(outbox_count), 1)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id, item_version, source_hash,
                       target_asset_version_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                  AND source_asset_type='project_workspace_state'
                """,
                [imported["migration_run_id"]],
            )
            project_item = uow.cursor.fetchone()
        rejected = application.execute(
            LegacyMigrationDecisionCommand(
                migration_run_id=imported["migration_run_id"],
                migration_item_id=str(project_item[0]),
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id="migration-reviewer",
                decision=MigrationDecision.REJECT,
                reason="project migration requires explicit remediation",
                expected_item_version=int(project_item[1]),
                source_hash=str(project_item[2]),
                target_asset_version_id=str(project_item[3]),
                migration_validation_id="",
                idempotency_key=f"reject:{project_item[0]}:{project_item[2]}",
                trace_id=f"trace:{imported['migration_run_id']}",
                correlation_id=f"correlation:{project_id}",
            )
        )
        self.assertEqual(rejected["status"], "INELIGIBLE")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT status, domain_state
                FROM authority_legacy_migration_item
                WHERE migration_item_id=%s
                """,
                [str(project_item[0])],
            )
            self.assertEqual(uow.cursor.fetchone(), ("INELIGIBLE", "DOMAIN_REJECTED"))

    def test_server_validation_record_supersedes_stale_validation_and_binds_decision(
        self,
    ) -> None:
        nonce = str(uuid4())
        project_id = identifier(f"migration-validation-project:{nonce}")
        workspace_id = identifier(f"migration-validation-workspace:{nonce}")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-migration-validation-integration",
            commit_sha="9" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "workspaces").mkdir(parents=True)
            (root / "data" / "assets").mkdir(parents=True)
            self._write(
                root / "data" / "workspaces" / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Validation Project",
                    "content": {"project_id": project_id},
                },
            )
            self._write(
                root / "data" / "assets" / "draft.json",
                {
                    "id": "validation-draft-1",
                    "type": "draft",
                    "project_id": project_id,
                    "content": {"chapter": 1, "text_digest": "fixture-only"},
                },
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            imported = service.import_snapshot(root)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id, item_version, source_hash,
                       target_asset_version_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND source_asset_type='draft'
                """,
                [imported["migration_run_id"]],
            )
            item = uow.cursor.fetchone()
        first = service.validate_domain_item(
            str(item[0]), expected_item_version=int(item[1])
        )
        self.assertEqual(first["validation_status"], "PASS")
        second = service.validate_domain_item(
            str(item[0]), expected_item_version=int(first["item_version"])
        )
        self.assertEqual(second["validation_status"], "PASS")
        self.assertNotEqual(
            first["migration_validation_id"], second["migration_validation_id"]
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT validation_version, status
                FROM authority_legacy_migration_validation
                WHERE migration_item_id=%s
                ORDER BY validation_version
                """,
                [str(item[0])],
            )
            validation_states = list(uow.cursor.fetchall())
        self.assertEqual(validation_states, [(1, "STALE"), (2, "PASS")])
        approval = LegacyMigrationApprovalApplication(
            DATABASE_URL,
            application_build_id="legacy-migration-validation-integration",
            commit_sha="9" * 40,
        )
        common = {
            "migration_run_id": imported["migration_run_id"],
            "migration_item_id": str(item[0]),
            "project_id": project_id,
            "workspace_id": workspace_id,
            "actor_id": "migration-validation-reviewer",
            "decision": MigrationDecision.APPROVE,
            "reason": "server validation accepted",
            "expected_item_version": int(second["item_version"]),
            "source_hash": str(item[2]),
            "target_asset_version_id": str(item[3]),
            "trace_id": f"trace:{imported['migration_run_id']}",
            "correlation_id": f"correlation:{project_id}",
        }
        with self.assertRaises(KernelError) as raised:
            approval.execute(
                LegacyMigrationDecisionCommand(
                    **common,
                    migration_validation_id=str(first["migration_validation_id"]),
                    idempotency_key=f"approve-stale:{item[0]}",
                )
            )
        self.assertEqual(raised.exception.code, "MIGRATION_VALIDATION_STALE")
        decided = approval.execute(
            LegacyMigrationDecisionCommand(
                **common,
                migration_validation_id=str(second["migration_validation_id"]),
                idempotency_key=f"approve-current:{item[0]}",
            )
        )
        self.assertEqual(
            decided["migration_validation_id"],
            second["migration_validation_id"],
        )
        self.assertEqual(decided["validation_result_hash"], second["result_hash"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT decision.migration_validation_id,
                       decision.validation_result_hash,
                       decision.domain_validation_evidence->>'server_authoritative',
                       COUNT(DISTINCT validation.validated_by_operation_id),
                       COUNT(DISTINCT event.event_id),
                       COUNT(DISTINCT outbox.outbox_id)
                FROM authority_legacy_migration_decision AS decision
                JOIN authority_legacy_migration_validation AS validation
                  ON validation.migration_validation_id=
                     decision.migration_validation_id
                LEFT JOIN state_event AS event
                  ON event.aggregate_id=validation.migration_validation_id
                 AND event.event_type='legacy_migration.item.validated'
                LEFT JOIN outbox_event AS outbox
                  ON outbox.event_id=event.event_id
                 AND outbox.topic='legacy_migration.item.validated'
                WHERE decision.migration_decision_id=%s
                GROUP BY decision.migration_validation_id,
                         decision.validation_result_hash,
                         decision.domain_validation_evidence
                """,
                [decided["migration_decision_id"]],
            )
            persisted = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT validation_scope, domain_state
                FROM authority_legacy_migration_item
                WHERE migration_item_id=%s
                """,
                [str(item[0])],
            )
            item_semantics = uow.cursor.fetchone()
        self.assertEqual(str(persisted[0]), second["migration_validation_id"])
        self.assertEqual(str(persisted[1]), second["result_hash"])
        self.assertEqual(str(persisted[2]), "true")
        self.assertEqual(tuple(int(value) for value in persisted[3:]), (1, 1, 1))
        self.assertEqual(tuple(item_semantics), ("ARCHIVAL", "DOMAIN_NOT_APPLICABLE"))

    def test_book_and_book_design_use_real_domain_authority_after_approval(
        self,
    ) -> None:
        project_id = identifier("domain-book-project")
        workspace_id = identifier("domain-book-workspace")
        book_id = identifier("domain-book")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-domain-book-integration",
            commit_sha="e" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "workspaces").mkdir(parents=True)
            (root / "data" / "assets").mkdir(parents=True)
            self._write(
                root / "data" / "workspaces" / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Domain Book Project",
                    "content": {"project_id": project_id},
                },
            )
            self._write(
                root / "data" / "assets" / "01-book.json",
                {
                    "id": book_id,
                    "type": "book",
                    "project_id": project_id,
                    "content": {
                        "book_id": book_id,
                        "title": "Migration Harbor",
                        "production_profile": {
                            "environment": "fixture",
                            "real_provider_proven": False,
                        },
                        "runtime_policy": {
                            "legacy_write": False,
                            "silent_fallback": False,
                        },
                        "release_identity": "legacy-domain-book@" + "e" * 40,
                    },
                },
            )
            self._write(
                root / "data" / "assets" / "02-design.json",
                {
                    "id": "design-1",
                    "type": "book_design_candidate",
                    "project_id": project_id,
                    "references": [
                        {
                            "business_key": book_id,
                            "relation_type": "BOOK_DESIGN_OF_BOOK",
                            "optional": False,
                            "expected_source_type": "book",
                            "expected_target_asset_type": "book_record",
                            "cardinality": "ONE",
                            "ordinal": 0,
                        }
                    ],
                    "content": {
                        "book_id": book_id,
                        "title": "Migration Harbor",
                        "genre": "mystery",
                        "premise": "A keeper must expose a falsified harbor ledger.",
                        "theme": "Truth requires accountable witnesses.",
                        "core_conflict": "Evidence and loyalty pull in opposite directions.",
                        "reader_promise": "Every discovery changes the cost of speaking.",
                        "ending": "The ledger becomes public through collective testimony.",
                        "protagonist": {
                            "name": "Lin",
                            "external_goal": "Protect the harbor",
                            "internal_need": "Trust accountable allies",
                            "flaw": "Controls every risk alone",
                            "arc": "From isolation to shared responsibility",
                        },
                        "world_rules": [
                            "Every cargo transfer leaves an immutable public receipt"
                        ],
                        "target_chapters": 12,
                    },
                },
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            imported = service.import_snapshot(root)
            verification_root = self._retain_snapshot(root)
        activation_order = service.domain_activation_order(imported["migration_run_id"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT source_asset_type, migration_item_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                """,
                [imported["migration_run_id"]],
            )
            item_ids = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        self.assertLess(
            activation_order.index(item_ids["book"]),
            activation_order.index(item_ids["book_design_candidate"]),
        )
        self._validate_approve_activate(
            service, imported["migration_run_id"], "project_workspace_state"
        )
        approval = LegacyMigrationApprovalApplication(
            DATABASE_URL,
            application_build_id="legacy-domain-book-integration",
            commit_sha="e" * 40,
        )
        activated: dict[str, dict] = {}
        for source_type in ("book", "book_design_candidate"):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT migration_item_id, item_version, source_hash,
                           target_asset_version_id, status, next_phase
                    FROM authority_legacy_migration_item
                    WHERE migration_run_id=%s AND source_asset_type=%s
                    """,
                    [imported["migration_run_id"], source_type],
                )
                item = uow.cursor.fetchone()
            self.assertEqual((item[4], item[5]), ("NEEDS_REVIEW", "ACTIVATE"))
            validation = service.validate_domain_item(
                str(item[0]), expected_item_version=int(item[1])
            )
            decision = approval.execute(
                LegacyMigrationDecisionCommand(
                    migration_run_id=imported["migration_run_id"],
                    migration_item_id=str(item[0]),
                    project_id=project_id,
                    workspace_id=workspace_id,
                    actor_id="domain-migration-reviewer",
                    decision=MigrationDecision.APPROVE,
                    reason=f"{source_type} domain schema independently accepted",
                    expected_item_version=int(validation["item_version"]),
                    source_hash=str(item[2]),
                    target_asset_version_id=str(item[3]),
                    migration_validation_id=str(validation["migration_validation_id"]),
                    idempotency_key=f"approve:{item[0]}:{item[2]}",
                    trace_id=f"trace:{imported['migration_run_id']}",
                    correlation_id=f"correlation:{project_id}",
                )
            )
            if source_type == "book":
                one_connection_runtime = DatabaseRuntime(
                    DatabaseRuntimeConfig(
                        DATABASE_URL,
                        role="migration",
                        service="legacy-domain-activation-one-connection",
                        min_size=0,
                        max_size=1,
                        max_waiting=1,
                        timeout=0.5,
                    )
                )
                try:
                    with patch(
                        "novel_forge.storage.authority_uow.get_database_runtime",
                        return_value=one_connection_runtime,
                    ):
                        activated[source_type] = service.activate_domain_item(
                            str(item[0]),
                            expected_item_version=int(decision["item_version"]),
                        )
                finally:
                    one_connection_runtime.close()
            else:
                activated[source_type] = service.activate_domain_item(
                    str(item[0]),
                    expected_item_version=int(decision["item_version"]),
                )
        verified = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(verified["status"], "DOMAIN_RECONCILED")
        self.assertEqual(verified["verification_status"], "PASS")
        self.assertEqual(verified["pending_domain_native_count"], 0)
        self.assertEqual(verified["actual_domain_failures"], 0)
        self.assertTrue(verified["domain_native_core_proven"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT source_asset_type, migration_item_id, item_version
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                  AND source_asset_type IN ('book','book_design_candidate')
                """,
                [imported["migration_run_id"]],
            )
            current_items = {
                str(source_type): (str(item_id), int(item_version))
                for source_type, item_id, item_version in uow.cursor.fetchall()
            }
        book_revalidation = service.validate_domain_item(
            current_items["book"][0],
            expected_item_version=current_items["book"][1],
        )
        self.assertEqual(book_revalidation["validation_status"], "PASS")
        stale_dependency = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(stale_dependency["verification_status"], "FAIL")
        self.assertGreaterEqual(stale_dependency["domain_validation_failures"], 1)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT item_version FROM authority_legacy_migration_item
                WHERE migration_item_id=%s
                """,
                [current_items["book_design_candidate"][0]],
            )
            current_design_version = int(uow.cursor.fetchone()[0])
        design_revalidation = service.validate_domain_item(
            current_items["book_design_candidate"][0],
            expected_item_version=current_design_version,
        )
        self.assertEqual(design_revalidation["validation_status"], "PASS")
        refreshed = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(refreshed["verification_status"], "PASS")

        # A release verification must be one run-consistent observation. Pause
        # after BookDesign freshness is read, then prove a concurrent upstream
        # Book revalidation cannot commit until verification releases the run
        # advisory lock. The next verification must observe the new dependency
        # version and fail closed until BookDesign is explicitly revalidated.
        snapshot_read = threading.Event()
        release_verify = threading.Event()
        design_snapshot_reads = 0
        from novel_forge.modules.legacy_migration import service as service_module

        original_load_validation_snapshot = service_module.load_validation_snapshot

        def pause_after_design_snapshot(*args, **kwargs):
            nonlocal design_snapshot_reads
            snapshot = original_load_validation_snapshot(*args, **kwargs)
            if str(args[1]) == current_items["book_design_candidate"][0]:
                design_snapshot_reads += 1
                if design_snapshot_reads == 2:
                    snapshot_read.set()
                    self.assertTrue(release_verify.wait(timeout=5))
            return snapshot

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT item_version FROM authority_legacy_migration_item "
                "WHERE migration_item_id=%s",
                [current_items["book"][0]],
            )
            concurrent_book_version = int(uow.cursor.fetchone()[0])
        with (
            patch.object(
                service_module,
                "load_validation_snapshot",
                side_effect=pause_after_design_snapshot,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            verify_future = executor.submit(
                service.verify,
                imported["migration_run_id"],
                snapshot_root=verification_root,
                required_level="DOMAIN_NATIVE",
            )
            self.assertTrue(snapshot_read.wait(timeout=5))
            revalidate_future = executor.submit(
                service.validate_domain_item,
                current_items["book"][0],
                expected_item_version=concurrent_book_version,
            )
            with self.assertRaises(FutureTimeoutError):
                revalidate_future.result(timeout=0.2)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM authority_operation
                    WHERE definition_name='migration.item.validate'
                      AND command_payload->>'migration_item_id'=%s
                      AND (command_payload->>'expected_item_version')::bigint=%s
                    """,
                    [current_items["book"][0], concurrent_book_version],
                )
                blocked_admission_count = int(uow.cursor.fetchone()[0])
            self.assertEqual(blocked_admission_count, 0)
            release_verify.set()
            concurrent_verification = verify_future.result(timeout=5)
            concurrent_revalidation = revalidate_future.result(timeout=5)
        self.assertEqual(concurrent_verification["verification_status"], "PASS")
        self.assertEqual(concurrent_revalidation["validation_status"], "PASS")
        self.assertEqual(
            service.verify(
                imported["migration_run_id"],
                snapshot_root=verification_root,
                required_level="DOMAIN_NATIVE",
            )["verification_status"],
            "FAIL",
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT item_version FROM authority_legacy_migration_item "
                "WHERE migration_item_id=%s",
                [current_items["book_design_candidate"][0]],
            )
            post_concurrency_design_version = int(uow.cursor.fetchone()[0])
        post_concurrency_design_validation = service.validate_domain_item(
            current_items["book_design_candidate"][0],
            expected_item_version=post_concurrency_design_version,
        )
        self.assertEqual(
            post_concurrency_design_validation["validation_status"], "PASS"
        )
        self.assertEqual(
            service.verify(
                imported["migration_run_id"],
                snapshot_root=verification_root,
                required_level="DOMAIN_NATIVE",
            )["verification_status"],
            "PASS",
        )
        self.assertNotEqual(
            activated["book_design_candidate"]["target_asset_version_id"],
            str(item[3]),
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT book.current_book_asset_version_id,
                       book.current_book_design_asset_version_id,
                       book.status, book.version
                FROM authority_book AS book
                WHERE book.project_id=%s AND book.book_id=%s
                """,
                [project_id, book_id],
            )
            book = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT reference.target_asset_version_id,
                       reference.target_domain_projection_id,
                       reference.relation_type, reference.optional,
                       reference.cardinality,
                       reference.compatibility_evidence
                FROM authority_legacy_migration_reference AS reference
                JOIN authority_legacy_migration_item AS source
                  ON source.migration_item_id=reference.source_item_id
                WHERE source.migration_run_id=%s
                  AND source.source_asset_type='book_design_candidate'
                """,
                [imported["migration_run_id"]],
            )
            reference = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT status, run_completion_level,
                       required_verification_level
                FROM authority_migration_run
                WHERE migration_run_id=%s
                """,
                [imported["migration_run_id"]],
            )
            run_semantics = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT source_asset_type, materialization_stage,
                       archival_state, domain_state, validation_scope
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                  AND source_asset_type IN (
                      'book','book_design_candidate'
                  )
                ORDER BY source_asset_type
                """,
                [imported["migration_run_id"]],
            )
            item_semantics = list(uow.cursor.fetchall())
        self.assertEqual(str(book[0]), activated["book"]["target_asset_version_id"])
        self.assertEqual(
            str(book[1]), activated["book_design_candidate"]["target_asset_version_id"]
        )
        self.assertEqual((str(book[2]), int(book[3])), ("DESIGN_ACTIVE", 2))
        self.assertEqual(
            tuple(str(value) for value in reference[:5]),
            (
                activated["book"]["target_asset_version_id"],
                book_id,
                "BOOK_DESIGN_OF_BOOK",
                "False",
                "ONE",
            ),
        )
        self.assertEqual(
            reference[5]["input_format"],
            "STRUCTURED_V1",
        )
        self.assertEqual(
            tuple(run_semantics),
            ("DOMAIN_RECONCILED", "DOMAIN_RECONCILED", "DOMAIN_NATIVE"),
        )
        self.assertEqual(
            item_semantics,
            [
                (
                    "book",
                    "DOMAIN",
                    "ARCHIVAL_RECONCILED",
                    "DOMAIN_RECONCILED",
                    "DOMAIN",
                ),
                (
                    "book_design_candidate",
                    "DOMAIN",
                    "ARCHIVAL_RECONCILED",
                    "DOMAIN_RECONCILED",
                    "DOMAIN",
                ),
            ],
        )
        for level in ("ARCHIVAL_NATIVE", "DOMAIN_NATIVE", "RELEASE_READY"):
            proof_without_snapshot = service.verify(
                imported["migration_run_id"], required_level=level
            )
            self.assertEqual(proof_without_snapshot["verification_status"], "FAIL")
            self.assertFalse(proof_without_snapshot["source_snapshot_verified"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_validation AS validation
                SET status='REVOKED'
                FROM authority_legacy_migration_item AS item
                WHERE validation.migration_validation_id=
                      item.evidence->>'migration_validation_id'
                  AND item.migration_run_id=%s
                  AND item.source_asset_type='book'
                """,
                [imported["migration_run_id"]],
            )
            self.assertEqual(uow.cursor.rowcount, 1)
            uow.commit()
        revoked = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(revoked["verification_status"], "FAIL")
        self.assertEqual(revoked["domain_validation_failures"], 1)
        self.assertFalse(revoked["domain_native_core_proven"])

    def test_structured_reference_cycles_optional_edges_and_type_mismatch_fail_closed(
        self,
    ) -> None:
        project_id = identifier("structured-reference-project")
        workspace_id = identifier("structured-reference-workspace")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="structured-reference-integration",
            commit_sha="6" * 40,
        )

        def book_record(book_id: str, references: list[dict] | None = None) -> dict:
            return {
                "id": book_id,
                "type": "book",
                "project_id": project_id,
                "references": references or [],
                "content": {
                    "book_id": book_id,
                    "title": f"Structured {book_id}",
                    "production_profile": {
                        "environment": "fixture",
                        "real_provider_proven": False,
                    },
                    "runtime_policy": {
                        "legacy_write": False,
                        "silent_fallback": False,
                    },
                    "release_identity": f"structured-reference@{book_id}",
                },
            }

        cycle_a = identifier("cycle-a")
        cycle_b = identifier("cycle-b")
        stable_target = identifier("stable-target")
        type_mismatch = identifier("type-mismatch")
        optional_source = identifier("optional-source")
        optional_cycle_a = identifier("optional-cycle-a")
        optional_cycle_b = identifier("optional-cycle-b")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "workspaces").mkdir(parents=True)
            (root / "data" / "assets").mkdir(parents=True)
            self._write(
                root / "data" / "workspaces" / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Structured Reference Project",
                    "content": {"project_id": project_id},
                },
            )
            fixtures = (
                book_record(
                    cycle_a,
                    [{"business_key": cycle_b, "relation_type": "RELATED_ASSET"}],
                ),
                book_record(
                    cycle_b,
                    [{"business_key": cycle_a, "relation_type": "RELATED_ASSET"}],
                ),
                book_record(stable_target),
                book_record(
                    type_mismatch,
                    [
                        {
                            "business_key": stable_target,
                            "relation_type": "RELATED_ASSET",
                            "expected_source_type": "story_design",
                            "expected_target_asset_type": "book_record",
                        }
                    ],
                ),
                book_record(
                    optional_source,
                    [
                        {
                            "business_key": "missing-optional-book",
                            "relation_type": "OPTIONAL_REFERENCE",
                            "optional": True,
                            "expected_source_type": "book",
                            "expected_target_asset_type": "book_record",
                        }
                    ],
                ),
                book_record(
                    optional_cycle_a,
                    [
                        {
                            "business_key": optional_cycle_b,
                            "relation_type": "OPTIONAL_REFERENCE",
                            "optional": True,
                            "expected_source_type": "book",
                            "expected_target_asset_type": "book_record",
                        }
                    ],
                ),
                book_record(
                    optional_cycle_b,
                    [
                        {
                            "business_key": optional_cycle_a,
                            "relation_type": "OPTIONAL_REFERENCE",
                            "optional": True,
                            "expected_source_type": "book",
                            "expected_target_asset_type": "book_record",
                        }
                    ],
                ),
            )
            for ordinal, fixture in enumerate(fixtures, start=1):
                self._write(
                    root / "data" / "assets" / f"{ordinal:02d}.json",
                    fixture,
                )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            imported = service.import_snapshot(root)

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT stable_business_key, status, error_code, reference_state
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s
                  AND stable_business_key=ANY(%s)
                ORDER BY stable_business_key
                """,
                [
                    imported["migration_run_id"],
                    [
                        cycle_a,
                        cycle_b,
                        stable_target,
                        type_mismatch,
                        optional_source,
                        optional_cycle_a,
                        optional_cycle_b,
                    ],
                ],
            )
            items = {
                str(row[0]): (str(row[1]), str(row[2] or ""), str(row[3]))
                for row in uow.cursor.fetchall()
            }
            uow.cursor.execute(
                """
                SELECT source.stable_business_key, reference.resolution_status,
                       reference.relation_type,
                       reference.compatibility_evidence->>'input_format'
                FROM authority_legacy_migration_reference AS reference
                JOIN authority_legacy_migration_item AS source
                  ON source.migration_item_id=reference.source_item_id
                WHERE reference.migration_run_id=%s
                ORDER BY source.stable_business_key
                """,
                [imported["migration_run_id"]],
            )
            references = {
                str(row[0]): tuple(str(value) for value in row[1:])
                for row in uow.cursor.fetchall()
            }

        self.assertEqual(
            items[cycle_a][0:2],
            ("QUARANTINED", "MIGRATION_DEPENDENCY_CYCLE"),
        )
        self.assertEqual(
            items[cycle_b][0:2],
            ("QUARANTINED", "MIGRATION_DEPENDENCY_CYCLE"),
        )
        self.assertEqual(
            items[type_mismatch][0:2],
            ("QUARANTINED", "REFERENCE_SOURCE_TYPE_MISMATCH"),
        )
        self.assertEqual(
            items[optional_source],
            ("NEEDS_REVIEW", "", "OPTIONAL_MISSING"),
        )
        self.assertEqual(
            references[optional_source],
            ("OPTIONAL_MISSING", "OPTIONAL_REFERENCE", "STRUCTURED_V1"),
        )
        self.assertEqual(items[optional_cycle_a], ("NEEDS_REVIEW", "", "RESOLVED"))
        self.assertEqual(items[optional_cycle_b], ("NEEDS_REVIEW", "", "RESOLVED"))
        self.assertEqual(references[optional_cycle_a][0], "RESOLVED")
        self.assertEqual(references[optional_cycle_b][0], "RESOLVED")
        self.assertEqual(references[cycle_a][0], "CONFLICT")
        self.assertEqual(references[cycle_b][0], "CONFLICT")
        self.assertEqual(references[type_mismatch][0], "CONFLICT")
        activation_order = service.domain_activation_order(imported["migration_run_id"])
        self.assertEqual(len(activation_order), 5)

    def test_planning_migration_builds_active_hierarchy_after_approval(self) -> None:
        project_id = identifier("domain-planning-project")
        workspace_id = identifier("domain-planning-workspace")
        book_id = identifier("domain-planning-book")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-domain-planning-integration",
            commit_sha="f" * 40,
        )
        plan_rows = (
            ("book_plan", "plan-book", "book:main", []),
            ("outline_version", "plan-book-alias", "book:alternate", []),
            ("volume_plan", "plan-volume", "volume:1", ["plan-book"]),
            ("arc_plan", "plan-arc", "arc:main", ["plan-volume"]),
            (
                "chapter_group_plan",
                "plan-group",
                "chapter-group:1",
                ["plan-volume"],
            ),
            ("chapter_plan", "plan-chapter", "chapter:1", ["plan-group"]),
            (
                "chapter_plan_version",
                "plan-chapter-alias",
                "chapter:2",
                ["plan-group"],
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "workspaces").mkdir(parents=True)
            (root / "data" / "assets").mkdir(parents=True)
            self._write(
                root / "data" / "workspaces" / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Planning Migration Project",
                    "content": {"project_id": project_id},
                },
            )
            self._write(
                root / "data" / "assets" / "00-book.json",
                {
                    "id": book_id,
                    "type": "book_record",
                    "project_id": project_id,
                    "content": {
                        "book_id": book_id,
                        "title": "Planning Migration",
                        "production_profile": {
                            "environment": "fixture",
                            "real_provider_proven": False,
                        },
                        "runtime_policy": {
                            "legacy_write": False,
                            "silent_fallback": False,
                        },
                        "release_identity": "legacy-domain-planning@" + "f" * 40,
                    },
                },
            )
            self._write(
                root / "data" / "assets" / "00-book-design.json",
                {
                    "id": "planning-book-design",
                    "type": "book_design",
                    "project_id": project_id,
                    "references": [book_id],
                    "content": {
                        "book_id": book_id,
                        "title": "Planning Migration",
                        "genre": "speculative",
                        "premise": "A planner must expose a falsified dependency graph.",
                        "theme": "Plans remain legitimate only when changes are traceable.",
                        "core_conflict": "Speed conflicts with accountable sequencing.",
                        "reader_promise": "Every shortcut creates a visible later cost.",
                        "ending": "The plan becomes durable through independent review.",
                        "protagonist": {
                            "name": "Yan",
                            "external_goal": "Complete the migration",
                            "internal_need": "Accept bounded sequencing",
                            "flaw": "Treats urgency as authority",
                            "arc": "From unilateral action to auditable coordination",
                        },
                        "world_rules": [
                            "Every plan revision produces an immutable version"
                        ],
                        "target_chapters": 20,
                    },
                },
            )
            for ordinal, (source_type, key, logical_key, references) in enumerate(
                plan_rows, start=1
            ):
                self._write(
                    root / "data" / "assets" / f"{ordinal:02d}-{key}.json",
                    {
                        "id": key,
                        "type": source_type,
                        "project_id": project_id,
                        "references": references,
                        "content": _migration_plan_content(
                            project_id=project_id,
                            book_id=book_id,
                            plan_type=source_type,
                            logical_key=logical_key,
                        ),
                    },
                )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            imported = service.import_snapshot(root)
            verification_root = self._retain_snapshot(root)
        self._validate_approve_activate(
            service, imported["migration_run_id"], "project_workspace_state"
        )
        approval = LegacyMigrationApprovalApplication(
            DATABASE_URL,
            application_build_id="legacy-domain-planning-integration",
            commit_sha="f" * 40,
        )
        activation_order = (
            "book_record",
            "book_design",
            "book_plan",
            "outline_version",
            "volume_plan",
            "arc_plan",
            "chapter_group_plan",
            "chapter_plan",
            "chapter_plan_version",
        )
        activated: dict[str, dict] = {}
        for source_type in activation_order:
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT migration_item_id, item_version, source_hash,
                           target_asset_version_id
                    FROM authority_legacy_migration_item
                    WHERE migration_run_id=%s AND source_asset_type=%s
                    """,
                    [imported["migration_run_id"], source_type],
                )
                item = uow.cursor.fetchone()
            validation = service.validate_domain_item(
                str(item[0]), expected_item_version=int(item[1])
            )
            decision = approval.execute(
                LegacyMigrationDecisionCommand(
                    migration_run_id=imported["migration_run_id"],
                    migration_item_id=str(item[0]),
                    project_id=project_id,
                    workspace_id=workspace_id,
                    actor_id="planning-migration-reviewer",
                    decision=MigrationDecision.APPROVE,
                    reason=f"{source_type} schema, scope, and references accepted",
                    expected_item_version=int(validation["item_version"]),
                    source_hash=str(item[2]),
                    target_asset_version_id=str(item[3]),
                    migration_validation_id=str(validation["migration_validation_id"]),
                    idempotency_key=f"approve:{item[0]}:{item[2]}",
                    trace_id=f"trace:{imported['migration_run_id']}",
                    correlation_id=f"correlation:{project_id}",
                )
            )
            if source_type in {"chapter_plan", "chapter_plan_version"}:
                for attempt in (service, LegacyMigrationService(
                    DATABASE_URL,
                    application_build_id="legacy-domain-planning-restarted",
                    commit_sha="f" * 40,
                )):
                    with self.assertRaisesRegex(KernelError, "CHAPTER_CONTRACT_VERSION_REQUIRED"):
                        attempt.activate_domain_item(
                            str(item[0]), expected_item_version=int(decision["item_version"])
                        )
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute(
                            "SELECT item_version, source_hash, target_asset_version_id FROM authority_legacy_migration_item WHERE migration_item_id=%s",
                            [str(item[0])],
                        )
                        self.assertEqual(uow.cursor.fetchone(), (int(decision["item_version"]), str(item[2]), str(item[3])))
                        uow.cursor.execute("SELECT COUNT(*) FROM story_plan_binding WHERE asset_version_id=%s", [str(item[3])])
                        self.assertEqual(uow.cursor.fetchone()[0], 0)
                        uow.cursor.execute("SELECT lifecycle FROM authority_asset_version WHERE asset_version_id=%s", [str(item[3])])
                        self.assertNotEqual(uow.cursor.fetchone()[0], "ACTIVE")
                continue
            if source_type == "chapter_group_plan":
                from novel_forge.modules.hierarchical_planning.application import (
                    PostgresHierarchicalPlanningAuthority,
                )

                execute = PostgresHierarchicalPlanningAuthority._execute_transaction

                def rollback_binding(authority, uow, operation_id, checkpoint):
                    def fail_after_write(event):
                        checkpoint(event)
                        if event == "after_business_projection_update":
                            raise RuntimeError("rollback imported group binding")

                    return execute(authority, uow, operation_id, fail_after_write)

                with patch.object(PostgresHierarchicalPlanningAuthority, "_execute_transaction", rollback_binding):
                    with self.assertRaisesRegex(RuntimeError, "rollback imported group binding"):
                        service.activate_domain_item(str(item[0]), expected_item_version=int(decision["item_version"]))
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT COUNT(*) FROM story_plan_binding WHERE asset_version_id=%s", [str(item[3])])
                    self.assertEqual(uow.cursor.fetchone()[0], 0)

                bind = PostgresHierarchicalPlanningAuthority.bind_active_contract
                receipts = []
                commands = []

                def capture_binding(authority, **command):
                    commands.append(command)
                    result = bind(authority, **command)
                    receipts.append(result)
                    return result

                with patch.object(PostgresHierarchicalPlanningAuthority, "bind_active_contract", capture_binding):
                    activated[source_type] = service.activate_domain_item(str(item[0]), expected_item_version=int(decision["item_version"]))
                restarted = PostgresHierarchicalPlanningAuthority(
                    DATABASE_URL,
                    application_build_id="legacy-domain-planning-integration",
                    commit_sha="f" * 40,
                )
                replay = restarted.bind_active_contract(**commands[0])
                self.assertEqual(receipts[0]["operation_id"], replay["operation_id"])
                self.assertFalse(receipts[0]["replayed"])
                self.assertTrue(replay["replayed"])
            else:
                activated[source_type] = service.activate_domain_item(
                    str(item[0]), expected_item_version=int(decision["item_version"])
                )
        verified = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(verified["status"], "FAILED", verified)
        self.assertEqual(verified["run_completion_level"], "ARCHIVAL_RECONCILED")
        self.assertEqual(verified["domain_validation_failures"], 2)
        self.assertEqual(verified["verification_status"], "FAIL")
        self.assertFalse(verified["domain_native_core_proven"])
        self.assertTrue(verified["source_snapshot_verified"])
        self.assertEqual(verified["actual_domain_failures"], 0)
        self.assertEqual(verified["pending_domain_native_count"], 2)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT binding.contract_type, binding.parent_version_id,
                       active.asset_version_id, COUNT(hierarchy.hierarchy_id)
                FROM story_plan_binding AS binding
                JOIN active_story_plan_version AS active
                  ON active.binding_id=binding.binding_id
                LEFT JOIN story_plan_hierarchy AS hierarchy
                  ON hierarchy.child_binding_id=binding.binding_id
                WHERE binding.project_id=%s AND binding.book_id=%s
                GROUP BY binding.binding_id, binding.contract_type,
                         binding.parent_version_id, active.asset_version_id
                ORDER BY binding.contract_type
                """,
                [project_id, book_id],
            )
            bindings = list(uow.cursor.fetchall())
        self.assertEqual(len(bindings), 5)
        counts_by_type = {
            contract_type: sum(1 for row in bindings if str(row[0]) == contract_type)
            for contract_type in {str(row[0]) for row in bindings}
        }
        self.assertEqual(
            counts_by_type,
            {"BOOK": 2, "VOLUME": 1, "ARC": 1, "CHAPTER_GROUP": 1},
        )
        for contract_type, parent, _active, hierarchy_count in bindings:
            expected_hierarchy = (
                1
                if str(contract_type)
                in {
                    "VOLUME",
                    "CHAPTER_GROUP",
                    "CHAPTER",
                }
                else 0
            )
            self.assertEqual(int(hierarchy_count), expected_hierarchy)
            if str(contract_type) == "CHAPTER_GROUP":
                self.assertEqual(
                    str(parent),
                    activated["volume_plan"]["target_asset_version_id"],
                )

    def test_story_design_migration_uses_versioned_server_validator_receipts(
        self,
    ) -> None:
        project_id = identifier("domain-story-design-project")
        workspace_id = identifier("domain-story-design-workspace")
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-story-design-validation-integration",
            commit_sha="2" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "workspaces").mkdir(parents=True)
            (root / "data" / "assets").mkdir(parents=True)
            self._write(
                root / "data" / "workspaces" / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Story Design Migration Project",
                    "content": {"project_id": project_id},
                },
            )
            self._write(
                root / "data" / "assets" / "story-design.json",
                {
                    "id": "story-design-main",
                    "type": "story_design",
                    "project_id": project_id,
                    "content": {
                        "generator_operation_name": "book_plan.generate",
                        "planning_scope": "BOOK",
                        "logical_key": "book-plan:main",
                        "candidate_payload": {
                            "objective": (
                                "Escalate the central conflict through irreversible choices"
                            )
                        },
                    },
                },
            )
            self._write(
                root / "data" / "assets" / "story-design-candidate.json",
                {
                    "id": "story-design-alias",
                    "type": "story_design_candidate",
                    "project_id": project_id,
                    "content": {
                        "generator_operation_name": "book_plan.generate",
                        "planning_scope": "BOOK",
                        "logical_key": "book-plan:alternate",
                        "candidate_payload": {
                            "objective": (
                                "Test an alternate conflict path without copying expression"
                            )
                        },
                    },
                },
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            imported = service.import_snapshot(root)
            verification_root = self._retain_snapshot(root)
        self._validate_approve_activate(
            service, imported["migration_run_id"], "project_workspace_state"
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id, item_version, source_hash,
                       target_asset_version_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND source_asset_type='story_design'
                """,
                [imported["migration_run_id"]],
            )
            item = uow.cursor.fetchone()
        validation = service.validate_domain_item(
            str(item[0]), expected_item_version=int(item[1])
        )
        self.assertEqual(validation["validation_status"], "PASS")
        approval = LegacyMigrationApprovalApplication(
            DATABASE_URL,
            application_build_id="legacy-story-design-validation-integration",
            commit_sha="2" * 40,
        )
        decision = approval.execute(
            LegacyMigrationDecisionCommand(
                migration_run_id=imported["migration_run_id"],
                migration_item_id=str(item[0]),
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id="story-design-migration-reviewer",
                decision=MigrationDecision.APPROVE,
                reason="versioned Story Design validator suite accepted",
                expected_item_version=int(validation["item_version"]),
                source_hash=str(item[2]),
                target_asset_version_id=str(item[3]),
                migration_validation_id=str(validation["migration_validation_id"]),
                idempotency_key=f"approve:{item[0]}:{item[2]}",
                trace_id=f"trace:{imported['migration_run_id']}",
                correlation_id=f"correlation:{project_id}",
            )
        )
        activated = service.activate_domain_item(
            str(item[0]), expected_item_version=int(decision["item_version"])
        )
        alias_activation = self._validate_approve_activate(
            service,
            imported["migration_run_id"],
            "story_design_candidate",
        )
        verified = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(verified["verification_status"], "PASS")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id, item_version
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND source_asset_type='story_design'
                """,
                [imported["migration_run_id"]],
            )
            activated_item_id, activated_item_version = uow.cursor.fetchone()
        revalidation = service.validate_domain_item(
            str(activated_item_id),
            expected_item_version=int(activated_item_version),
        )
        self.assertEqual(revalidation["validation_status"], "PASS")
        reverified = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(reverified["verification_status"], "PASS")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT evidence, validator_version,
                       validator_implementation_hash, result_hash
                FROM authority_legacy_migration_validation
                WHERE migration_validation_id=%s
                """,
                [validation["migration_validation_id"]],
            )
            validation_row = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT lifecycle, qualification, approval, version
                FROM authority_story_design_version_state
                WHERE project_id=%s AND asset_version_id=%s
                """,
                [project_id, activated["target_asset_version_id"]],
            )
            state = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT transition_type, evidence
                FROM authority_story_design_transition
                WHERE project_id=%s AND asset_version_id=%s
                  AND transition_type IN (
                      'STRUCTURAL_VALIDATE','SEMANTIC_VALIDATE','QUALIFY'
                  )
                ORDER BY to_version
                """,
                [project_id, activated["target_asset_version_id"]],
            )
            transitions = list(uow.cursor.fetchall())
        validation_evidence = dict(validation_row[0])
        self.assertEqual(validation_evidence["validator"], "StoryDesignValidatorSuite")
        self.assertEqual(len(validation_evidence["receipts"]), 5)
        self.assertTrue(str(validation_row[2]).startswith("sha256:"))
        self.assertTrue(str(validation_row[3]).startswith("sha256:"))
        self.assertEqual(tuple(state), ("ACTIVE", "QUALIFIED", "APPROVED", 7))
        self.assertNotEqual(
            alias_activation["target_asset_version_id"],
            activated["target_asset_version_id"],
        )
        self.assertEqual(
            [str(row[0]) for row in transitions],
            ["STRUCTURAL_VALIDATE", "SEMANTIC_VALIDATE", "QUALIFY"],
        )
        for transition_type, evidence in transitions:
            receipt_key = (
                "qualification_receipt"
                if str(transition_type) == "QUALIFY"
                else "validator_receipt"
            )
            self.assertNotIn("passed", evidence)
            self.assertEqual(
                str(evidence["migration_validation_id"]),
                validation["migration_validation_id"],
            )
            self.assertEqual(str(evidence[receipt_key]["status"]), "PASS")

    def test_source_migration_requires_verified_blob_and_real_projection(self) -> None:
        with disposable_database_at_migration(
            DATABASE_URL,
            prefix="legacy_source_binding",
            target_migration_id=LATEST_MIGRATION_ID,
        ) as database_url, patch(f"{__name__}.DATABASE_URL", database_url):
            self._source_migration_requires_verified_blob_and_real_projection()

    def _source_migration_requires_verified_blob_and_real_projection(self) -> None:
        project_id = identifier("domain-source-project")
        workspace_id = identifier("domain-source-workspace")
        ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="legacy-domain-source-integration",
            commit_sha="1" * 40,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id="source-migration-bootstrap",
                idempotency_key=f"source-migration-project:{project_id}",
                trace_id=f"trace:{project_id}",
                correlation_id=f"correlation:{project_id}",
                payload={"title": "Source Migration Project"},
            )
        )
        blob_id = identifier("legacy-source-blob")
        source_bytes = b"synthetic source evidence only"
        source_digest = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
        object_key = f"sources/{project_id}/{blob_id}"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_blob(
                    blob_id, project_id, provider, object_key,
                    expected_hash, expected_size, media_type,
                    actual_object_key, actual_hash, actual_size,
                    receipt_provider, status
                ) VALUES (%s, %s, 'fixture_object_store', %s, %s, %s,
                          'text/plain', %s, %s, %s,
                          'fixture_object_store', 'AVAILABLE')
                """,
                [
                    blob_id,
                    project_id,
                    object_key,
                    source_digest,
                    len(source_bytes),
                    object_key,
                    source_digest,
                    len(source_bytes),
                ],
            )
            uow.commit()
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id="legacy-domain-source-integration",
            commit_sha="1" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "workspaces").mkdir(parents=True)
            (root / "data" / "sources").mkdir(parents=True)
            self._write(
                root / "data" / "workspaces" / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "title": "Source Migration Project",
                    "content": {"project_id": project_id},
                },
            )
            self._write(
                root / "data" / "sources" / "source.json",
                {
                    "id": "legacy-source-1",
                    "type": "source_document",
                    "project_id": project_id,
                    "content": {
                        "blob_id": blob_id,
                        "title": "Verified Synthetic Source",
                        "source_kind": "test_fixture",
                        "source_uri": "urn:fixture:legacy-source-1",
                        "rights_authorization": "test_fixture",
                        "license_name": "",
                        "copyright_boundary": "fixture-only no production claim",
                        "allow_downstream_generation": True,
                    },
                },
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            imported = service.import_snapshot(root)
            verification_root = self._retain_snapshot(root)
        self._validate_approve_activate(
            service, imported["migration_run_id"], "project_workspace_state"
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id, item_version, source_hash,
                       target_asset_version_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND source_asset_type='source_document'
                """,
                [imported["migration_run_id"]],
            )
            item = uow.cursor.fetchone()
        validation = service.validate_domain_item(
            str(item[0]), expected_item_version=int(item[1])
        )
        decision = LegacyMigrationApprovalApplication(
            DATABASE_URL,
            application_build_id="legacy-domain-source-integration",
            commit_sha="1" * 40,
        ).execute(
            LegacyMigrationDecisionCommand(
                migration_run_id=imported["migration_run_id"],
                migration_item_id=str(item[0]),
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id="source-migration-reviewer",
                decision=MigrationDecision.APPROVE,
                reason="verified Blob receipt and rights independently accepted",
                expected_item_version=int(validation["item_version"]),
                source_hash=str(item[2]),
                target_asset_version_id=str(item[3]),
                migration_validation_id=str(validation["migration_validation_id"]),
                idempotency_key=f"approve:{item[0]}:{item[2]}",
                trace_id=f"trace:{imported['migration_run_id']}",
                correlation_id=f"correlation:{project_id}",
            )
        )
        activated = service.activate_domain_item(
            str(item[0]), expected_item_version=int(decision["item_version"])
        )
        verified = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(verified["status"], "DOMAIN_RECONCILED")
        self.assertEqual(verified["verification_status"], "PASS")
        self.assertEqual(verified["actual_domain_failures"], 0)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT item_version FROM authority_legacy_migration_item "
                "WHERE migration_item_id=%s",
                [str(item[0])],
            )
            current_source_item_version = int(uow.cursor.fetchone()[0])
        source_revalidation = service.validate_domain_item(
            str(item[0]), expected_item_version=current_source_item_version
        )
        self.assertEqual(source_revalidation["validation_status"], "PASS")
        self.assertEqual(
            service.verify(
                imported["migration_run_id"],
                snapshot_root=verification_root,
                required_level="DOMAIN_NATIVE",
            )["verification_status"],
            "PASS",
        )

        # Simulate a populated 0066 database produced before archival binding
        # evidence was stored on activated items. The 0067 forward migration
        # must recover the immutable archival AssetVersion from the activation-
        # bound Validation record and make server revalidation possible.
        later_fixture_tables = materialize_historical_fixture_at_migration(
            DATABASE_URL,
            target_migration_id="20260804_0066_runtime_job_attempt_lease_existence",
        )
        self.assertEqual(
            set(later_fixture_tables), {"authority_operation_definition_release"}
        )
        ambiguous_asset_id = identifier("ambiguous-archival-asset")
        ambiguous_version_id = identifier("ambiguous-archival-version")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT item.operation_id, version.content, version.content_hash,
                       version.schema_version
                FROM authority_legacy_migration_item AS item
                JOIN authority_legacy_migration_validation AS validation
                  ON validation.migration_validation_id=%s
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=validation.target_asset_version_id
                WHERE item.migration_item_id=%s
                """,
                [validation["migration_validation_id"], str(item[0])],
            )
            archival_source = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_item
                SET evidence=(evidence
                    - 'archival_target_asset_id'
                    - 'archival_target_asset_version_id'
                    - 'archival_target_content_hash'
                    - 'migration_validation_id')
                WHERE migration_item_id=%s
                """,
                [str(item[0])],
            )
            uow.cursor.execute(
                "INSERT INTO authority_asset(asset_id, project_id, asset_type) "
                "VALUES (%s, %s, 'legacy_archival_ambiguity_fixture')",
                [ambiguous_asset_id, project_id],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'IMPORTED', 'PENDING_EVALUATION',
                          'CLEAR', %s, %s, %s)
                """,
                [
                    ambiguous_version_id,
                    ambiguous_asset_id,
                    Jsonb(dict(archival_source[1])),
                    str(archival_source[2]),
                    str(archival_source[3]),
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_operation_output_asset(
                    operation_id, asset_id, asset_version_id,
                    output_key, role, content_hash
                ) VALUES (%s, %s, %s, 'ambiguous-archival', 'PRIMARY', %s)
                """,
                [
                    str(archival_source[0]),
                    ambiguous_asset_id,
                    ambiguous_version_id,
                    str(archival_source[2]),
                ],
            )
            uow.commit()
        with self.assertRaisesRegex(
            RuntimeError,
            "activated_domain_item_without_unique_archival_binding=1",
        ):
            run_migrations(DATABASE_URL)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "DELETE FROM authority_operation_output_asset "
                "WHERE asset_version_id=%s",
                [ambiguous_version_id],
            )
            uow.cursor.execute(
                "DELETE FROM authority_asset_version WHERE asset_version_id=%s",
                [ambiguous_version_id],
            )
            uow.cursor.execute(
                "DELETE FROM authority_asset WHERE asset_id=%s",
                [ambiguous_asset_id],
            )
            uow.cursor.execute(
                """
                UPDATE authority_legacy_migration_item
                SET evidence=evidence || jsonb_build_object(
                    'migration_validation_id', %s::text
                )
                WHERE migration_item_id=%s
                """,
                [validation["migration_validation_id"], str(item[0])],
            )
            uow.commit()
        migration_status = run_migrations(DATABASE_URL)
        self.assertTrue(migration_status["ok"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT item.evidence->>'archival_target_asset_version_id',
                       validation.target_asset_version_id,
                       item.item_version
                FROM authority_legacy_migration_item AS item
                JOIN authority_legacy_migration_validation AS validation
                  ON validation.migration_validation_id=
                     item.evidence->>'migration_validation_id'
                WHERE item.migration_item_id=%s
                """,
                [str(item[0])],
            )
            recovered_binding = uow.cursor.fetchone()
        self.assertEqual(str(recovered_binding[0]), str(recovered_binding[1]))
        recovered_revalidation = service.validate_domain_item(
            str(item[0]), expected_item_version=int(recovered_binding[2])
        )
        self.assertEqual(recovered_revalidation["validation_status"], "PASS")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT source.blob_id, source.source_content_hash,
                       source.governance_status, version.lifecycle,
                       version.eligibility, version.governance
                FROM authority_source_document AS source
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=source.asset_version_id
                WHERE source.source_document_id=%s
                """,
                [activated["domain_projection_id"]],
            )
            source = uow.cursor.fetchone()
        self.assertEqual(
            tuple(str(value) for value in source),
            (
                blob_id,
                source_digest,
                "ELIGIBLE",
                "ACTIVE",
                "ELIGIBLE",
                "CLEAR",
            ),
        )

    def test_mkaos_migration_builds_candidate_card_and_pack_with_fixture_boundary(
        self,
    ) -> None:
        project_id = identifier("domain-mkaos-project")
        workspace_id = identifier("domain-mkaos-workspace")
        build_id = "legacy-domain-mkaos-integration"
        commit_sha = "2" * 40
        ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id=build_id,
            commit_sha=commit_sha,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id="mkaos-migration-bootstrap",
                idempotency_key=f"mkaos-migration-project:{project_id}",
                trace_id=f"trace:{project_id}",
                correlation_id=f"correlation:{project_id}",
                payload={"title": "MKAOS Migration Project"},
            )
        )

        def insert_blob(content: bytes) -> str:
            blob_id = identifier("migration-mkaos-blob")
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            object_key = f"mkaos/{project_id}/{blob_id}"
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    INSERT INTO authority_blob(
                        blob_id, project_id, provider, object_key,
                        expected_hash, expected_size, media_type,
                        actual_object_key, actual_hash, actual_size,
                        receipt_provider, status
                    ) VALUES (%s, %s, 'fixture_object_store', %s, %s, %s,
                              'text/plain', %s, %s, %s,
                              'fixture_object_store', 'AVAILABLE')
                    """,
                    [
                        blob_id,
                        project_id,
                        object_key,
                        digest,
                        len(content),
                        object_key,
                        digest,
                        len(content),
                    ],
                )
                uow.commit()
            return blob_id

        source_application = SourceAuthorityApplication(
            DATABASE_URL,
            application_build_id=build_id,
            commit_sha=commit_sha,
        )
        source_blob = insert_blob(b"S" * 100)
        source = source_application.execute(
            RegisterSourceDocumentCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                blob_id=source_blob,
                title="MKAOS migration evidence",
                source_kind="test_fixture",
                source_uri="urn:fixture:mkaos-migration",
                rights_authorization="test_fixture",
                license_name="",
                copyright_boundary="fixture evidence only",
                actor_id="mkaos-source-operator",
                idempotency_key=f"source:{source_blob}",
                trace_id=f"trace:{source_blob}",
                correlation_id=f"correlation:{source_blob}",
            )
        )
        chunk_bytes = b"normalized evidence bytes for abstract analysis"
        chunk_blob = insert_blob(chunk_bytes)
        transformed = source_application.execute_transform(
            CommitSourceTransformCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                source_document_id=str(source["source_document_id"]),
                normalization_version="normalize:v1",
                chunking_version="evidence:v1",
                chunking_policy_hash=(
                    "sha256:" + hashlib.sha256(b"mkaos-migration-chunk-v1").hexdigest()
                ),
                chunks=(
                    SourceChunkCandidate(
                        chunk_index=0,
                        blob_id=chunk_blob,
                        content_hash=(
                            "sha256:" + hashlib.sha256(chunk_bytes).hexdigest()
                        ),
                        byte_size=len(chunk_bytes),
                        character_count=len(chunk_bytes.decode()),
                        token_count=6,
                        source_byte_start=0,
                        source_byte_end=100,
                    ),
                ),
                actor_id="mkaos-source-operator",
                idempotency_key=f"transform:{source['asset_version_id']}",
                trace_id=f"trace:transform:{source_blob}",
                correlation_id=f"correlation:transform:{source_blob}",
            )
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT asset_version_id FROM authority_source_chunk
                WHERE source_transform_id=%s AND chunk_index=0
                """,
                [transformed["source_transform_id"]],
            )
            chunk_version_id = str(uow.cursor.fetchone()[0])
            execution_asset_id = identifier("mkaos-execution")
            execution_version_id = f"{execution_asset_id}:v1"
            execution_content = {
                "execution_id": identifier("mkaos-execution-proof"),
                "gateway": "ProductionExecutionGateway",
                "fixture_protocol_only": True,
                "real_provider_proven": False,
                "production_verified": False,
            }
            execution_hash = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        execution_content, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
            )
            uow.cursor.execute(
                "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s, %s, 'model_call_log')",
                [execution_asset_id, project_id],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number,
                    lifecycle, eligibility, governance, content,
                    content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR',
                          %s, %s, 'integration-fixture.v1')
                """,
                [
                    execution_version_id,
                    execution_asset_id,
                    Jsonb(execution_content),
                    execution_hash,
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id, policy_version,
                    decision, evidence
                ) VALUES (%s, %s, 'integration-fixture-v1', 'ELIGIBLE', %s)
                """,
                [
                    f"{execution_version_id}:qualification:v1",
                    execution_version_id,
                    Jsonb(
                        {
                            "fixture_protocol_only": True,
                            "real_provider_proven": False,
                            "production_verified": False,
                        }
                    ),
                ],
            )
            uow.commit()
        service = LegacyMigrationService(
            DATABASE_URL,
            application_build_id=build_id,
            commit_sha=commit_sha,
            allow_fixture_domain_activation=True,
        )
        knowledge_key = "legacy-knowledge-1"
        knowledge_candidate_key = "legacy-knowledge-candidate-1"
        pack_key = "legacy-pack-1"
        candidate = {
            "concept_name": "Escalating obligation",
            "discipline": "organizational behavior",
            "abstract_principle": (
                "A favor creates conflict when repayment criteria change after consent."
            ),
            "constraints": [
                "Every escalation exposes who changed the repayment criterion."
            ],
            "conflict_generators": [
                "Beneficiary and patron disagree whether the debt is settled."
            ],
            "review_checks": ["Reject proper nouns and source-specific expressions."],
            "copyright_boundaries": ["Retain only the abstract obligation mechanism."],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "workspaces").mkdir(parents=True)
            (root / "data" / "assets").mkdir(parents=True)
            self._write(
                root / "data" / "workspaces" / "workspace.json",
                {
                    "id": workspace_id,
                    "type": "project_workspace_state",
                    "content": {"project_id": project_id},
                },
            )
            self._write(
                root / "data" / "assets" / "01-knowledge-candidate.json",
                {
                    "id": knowledge_candidate_key,
                    "type": "knowledge_card_candidate",
                    "project_id": project_id,
                    "content": {
                        "candidate": {
                            **candidate,
                            "concept_name": "Escalating obligation candidate alias",
                        },
                        "execution_asset_version_id": execution_version_id,
                        "evidence_spans": [
                            {
                                "source_chunk_asset_version_id": chunk_version_id,
                                "chunk_byte_start": 0,
                                "chunk_byte_end": 10,
                                "evidence_hash": (
                                    "sha256:" + hashlib.sha256(b"span-0-10").hexdigest()
                                ),
                            }
                        ],
                        "abstraction_policy_version": "anti-copy-abstraction:v1",
                    },
                },
            )
            self._write(
                root / "data" / "assets" / "02-knowledge.json",
                {
                    "id": knowledge_key,
                    "type": "knowledge_card",
                    "project_id": project_id,
                    "content": {
                        "candidate": candidate,
                        "execution_asset_version_id": execution_version_id,
                        "evidence_spans": [
                            {
                                "source_chunk_asset_version_id": chunk_version_id,
                                "chunk_byte_start": 0,
                                "chunk_byte_end": 10,
                                "evidence_hash": (
                                    "sha256:" + hashlib.sha256(b"span-0-10").hexdigest()
                                ),
                            }
                        ],
                        "abstraction_policy_version": "anti-copy-abstraction:v1",
                    },
                },
            )
            self._write(
                root / "data" / "assets" / "03-pack.json",
                {
                    "id": pack_key,
                    "type": "knowledge_pack",
                    "project_id": project_id,
                    "references": [knowledge_key, workspace_id],
                    "content": {
                        "target_legacy_business_key": workspace_id,
                        "selector_policy_version": "mkaos-explicit-selector:v1",
                        "selector_policy_hash": (
                            "sha256:" + hashlib.sha256(b"selector-v1").hexdigest()
                        ),
                        "selections": [
                            {
                                "legacy_business_key": knowledge_key,
                                "usage_role": "CONSTRAINT",
                                "frozen_weight": "2.5",
                            }
                        ],
                    },
                },
            )
            for path in root.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            root.chmod(0o555)
            imported = service.import_snapshot(root)
            verification_root = self._retain_snapshot(root)
        self._validate_approve_activate(
            service, imported["migration_run_id"], "project_workspace_state"
        )
        approval = LegacyMigrationApprovalApplication(
            DATABASE_URL,
            application_build_id=build_id,
            commit_sha=commit_sha,
        )
        activations: dict[str, dict] = {}
        for source_type in (
            "knowledge_card_candidate",
            "knowledge_card",
            "knowledge_pack",
        ):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT migration_item_id, item_version, source_hash,
                           target_asset_version_id
                    FROM authority_legacy_migration_item
                    WHERE migration_run_id=%s AND source_asset_type=%s
                    """,
                    [imported["migration_run_id"], source_type],
                )
                item = uow.cursor.fetchone()
            validation = service.validate_domain_item(
                str(item[0]), expected_item_version=int(item[1])
            )
            decision = approval.execute(
                LegacyMigrationDecisionCommand(
                    migration_run_id=imported["migration_run_id"],
                    migration_item_id=str(item[0]),
                    project_id=project_id,
                    workspace_id=workspace_id,
                    actor_id="mkaos-migration-reviewer",
                    decision=MigrationDecision.APPROVE,
                    reason=f"{source_type} lineage independently accepted",
                    expected_item_version=int(validation["item_version"]),
                    source_hash=str(item[2]),
                    target_asset_version_id=str(item[3]),
                    migration_validation_id=str(validation["migration_validation_id"]),
                    idempotency_key=f"approve:{item[0]}:{item[2]}",
                    trace_id=f"trace:{imported['migration_run_id']}",
                    correlation_id=f"correlation:{project_id}",
                )
            )
            activations[source_type] = service.activate_domain_item(
                str(item[0]), expected_item_version=int(decision["item_version"])
            )
        verified = service.verify(
            imported["migration_run_id"],
            snapshot_root=verification_root,
            required_level="DOMAIN_NATIVE",
        )
        self.assertEqual(verified["status"], "DOMAIN_RECONCILED")
        self.assertEqual(verified["verification_status"], "PASS")
        self.assertEqual(verified["actual_domain_failures"], 0)
        for source_type in (
            "knowledge_card_candidate",
            "knowledge_card",
            "knowledge_pack",
        ):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT migration_item_id, item_version
                    FROM authority_legacy_migration_item
                    WHERE migration_run_id=%s AND source_asset_type=%s
                    """,
                    [imported["migration_run_id"], source_type],
                )
                active_item_id, active_item_version = uow.cursor.fetchone()
            revalidation = service.validate_domain_item(
                str(active_item_id), expected_item_version=int(active_item_version)
            )
            self.assertEqual(revalidation["validation_status"], "PASS")
        self.assertEqual(
            service.verify(
                imported["migration_run_id"],
                snapshot_root=verification_root,
                required_level="DOMAIN_NATIVE",
            )["verification_status"],
            "PASS",
        )
        self.assertFalse(
            activations["knowledge_card"]["evidence"]["production_verified"]
        )
        self.assertTrue(
            activations["knowledge_card"]["evidence"]["fixture_protocol_only"]
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT card.status, version.lifecycle, version.eligibility,
                       version.governance
                FROM authority_mkaos_knowledge_card AS card
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=card.asset_version_id
                WHERE card.knowledge_card_id=%s
                """,
                [activations["knowledge_card"]["domain_projection_id"]],
            )
            card = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT pack.status, pack.item_count, COUNT(item.ordinal)
                FROM authority_mkaos_knowledge_pack AS pack
                JOIN authority_mkaos_knowledge_pack_item AS item
                  ON item.knowledge_pack_id=pack.knowledge_pack_id
                WHERE pack.knowledge_pack_id=%s
                GROUP BY pack.status, pack.item_count
                """,
                [activations["knowledge_pack"]["domain_projection_id"]],
            )
            pack = uow.cursor.fetchone()
        self.assertEqual(tuple(card), ("ACTIVE", "ACTIVE", "ELIGIBLE", "CLEAR"))
        self.assertEqual(
            tuple(
                int(value) if index else str(value) for index, value in enumerate(pack)
            ),
            ("ACTIVE", 1, 1),
        )

    def _validate_approve_activate(
        self,
        service: LegacyMigrationService,
        migration_run_id: str,
        source_type: str,
    ) -> dict:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT migration_item_id, item_version, source_hash,
                       target_asset_version_id, project_id, workspace_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id=%s AND source_asset_type=%s
                """,
                [migration_run_id, source_type],
            )
            item = uow.cursor.fetchone()
        if item is None:
            raise AssertionError(f"missing migration item for {source_type}")
        validation = service.validate_domain_item(
            str(item[0]), expected_item_version=int(item[1])
        )
        self.assertEqual(validation["validation_status"], "PASS")
        decision = LegacyMigrationApprovalApplication(
            DATABASE_URL,
            application_build_id=service.application_build_id,
            commit_sha=service.commit_sha,
        ).execute(
            LegacyMigrationDecisionCommand(
                migration_run_id=migration_run_id,
                migration_item_id=str(item[0]),
                project_id=str(item[4]),
                workspace_id=str(item[5]),
                actor_id=f"{source_type}-migration-reviewer",
                decision=MigrationDecision.APPROVE,
                reason=f"{source_type} server validation independently accepted",
                expected_item_version=int(validation["item_version"]),
                source_hash=str(item[2]),
                target_asset_version_id=str(item[3]),
                migration_validation_id=str(validation["migration_validation_id"]),
                idempotency_key=f"approve:{item[0]}:{item[2]}",
                trace_id=f"trace:{migration_run_id}",
                correlation_id=f"correlation:{item[4]}",
            )
        )
        return service.activate_domain_item(
            str(item[0]), expected_item_version=int(decision["item_version"])
        )

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _retain_snapshot(self, root: Path) -> Path:
        retained = tempfile.TemporaryDirectory()
        self.addCleanup(retained.cleanup)
        retained_root = Path(retained.name)
        shutil.copytree(root, retained_root, dirs_exist_ok=True)
        return retained_root


if __name__ == "__main__":
    unittest.main()
