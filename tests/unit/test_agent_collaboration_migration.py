from __future__ import annotations

import unittest

from novel_forge.storage.migrations.runner import (
    LATEST_MIGRATION_ID,
    MIGRATIONS,
    validate_migration_chain,
)


class AgentCollaborationMigrationTests(unittest.TestCase):
    def test_collaboration_migration_is_latest_and_chain_is_valid(self) -> None:
        validate_migration_chain()
        self.assertEqual(
            LATEST_MIGRATION_ID,
            "20260729_0034_unified_business_authority",
        )
        self.assertEqual(
            MIGRATIONS[-1].down_revision,
            "20260728_0033_agent_collaboration_v1",
        )

    def test_schema_reuses_authority_execution_and_asset_identities(self) -> None:
        sql = self._collaboration_sql()

        for table in (
            "authority_agent_definition",
            "authority_agent_capability",
            "authority_agent_scope_snapshot",
            "authority_agent_participant_snapshot",
            "authority_agent_collaboration_session",
            "authority_agent_collaboration_turn",
            "authority_agent_work_order",
            "authority_agent_output_envelope",
            "authority_agent_conversation_message",
            "authority_agent_candidate_version",
            "authority_agent_candidate_parent",
            "authority_agent_conflict_record",
            "authority_agent_scope_expansion_request",
            "authority_agent_collaboration_decision",
            "authority_agent_collaboration_commit",
        ):
            self.assertIn(f"CREATE TABLE {table}", sql)

        self.assertIn(
            "REFERENCES authority_operation(operation_id)",
            sql,
        )
        self.assertIn(
            "REFERENCES authority_attempt(attempt_id)",
            sql,
        )
        self.assertIn(
            "REFERENCES authority_saga(saga_id)",
            sql,
        )
        self.assertIn(
            "REFERENCES authority_asset_version(asset_version_id)",
            sql,
        )
        self.assertNotIn("agent_attempts", sql.lower())
        self.assertNotIn("conversation_execution_attempts", sql.lower())

    def test_schema_has_idempotency_queries_and_immutability_guards(self) -> None:
        sql = self._collaboration_sql()

        self.assertIn(
            "UNIQUE(session_id, turn_number)",
            sql,
        )
        self.assertIn(
            "UNIQUE(session_id, stable_idempotency_key)",
            sql,
        )
        self.assertIn(
            "UNIQUE(turn_id)",
            sql,
        )
        self.assertIn(
            "authority_agent_candidate_parent_parent_idx",
            sql,
        )
        self.assertIn(
            "authority_agent_conflict_open_idx",
            sql,
        )
        self.assertIn(
            "authority_agent_collaboration_immutable",
            sql,
        )
        self.assertIn(
            "authority_agent_scope_snapshot_immutable",
            sql,
        )
        self.assertIn(
            "authority_agent_candidate_version_immutable",
            sql,
        )

    def test_session_and_decision_statuses_are_database_constrained(self) -> None:
        sql = self._collaboration_sql()

        for status in (
            "SCOPE_FROZEN",
            "DELIBERATING",
            "AUTHORITY_DECISION_PENDING",
            "SCOPE_VIOLATION",
            "HUMAN_DECISION_REQUIRED",
            "COMMITTED",
        ):
            self.assertIn(f"'{status}'", sql)
        for decision in (
            "ACCEPTED",
            "REPAIR_REQUIRED",
            "REPLAN_REQUIRED",
            "SCOPE_EXPANSION_APPROVED",
            "SCOPE_EXPANSION_REJECTED",
        ):
            self.assertIn(f"'{decision}'", sql)

    @staticmethod
    def _collaboration_sql() -> str:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260728_0033_agent_collaboration_v1"
        )
        return "\n".join(migration.upgrade_statements)


if __name__ == "__main__":
    unittest.main()
