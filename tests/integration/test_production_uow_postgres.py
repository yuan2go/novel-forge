import os
import unittest
from uuid import uuid4

from novel_forge.storage.production_uow import ProductionUnitOfWork


URL = os.environ.get("NOVEL_FORGE_DATABASE_URL", "")


@unittest.skipUnless(URL, "NOVEL_FORGE_DATABASE_URL is required for PostgreSQL integration")
class ProductionUowPostgresTests(unittest.TestCase):
    def test_explicit_commit_persists_and_default_exit_rolls_back(self):
        project, operation = f"uow-{uuid4()}", f"op-{uuid4()}"
        row = {"operation_id": operation, "operation_type": "test", "project_id": project, "parent_operation_id": "", "status": "pending", "idempotency_key": operation, "request_digest": "digest", "environment": "test", "metadata": {}}
        with ProductionUnitOfWork(URL) as uow:
            uow.operations.create(row)
            uow.commit()
        with ProductionUnitOfWork(URL) as uow:
            self.assertEqual(uow.operations.get_by_id(operation, project)["operation_id"], operation)
        with ProductionUnitOfWork(URL) as uow:
            uow.operations.create({**row, "operation_id": f"op-{uuid4()}", "idempotency_key": f"key-{uuid4()}"})
        with ProductionUnitOfWork(URL) as uow:
            self.assertIsNone(uow.operations.get_by_id(row["operation_id"], "other-project"))

    def test_atomic_operation_evidence_rolls_back_on_outbox_failure(self):
        project, operation = f"atomic-{uuid4()}", f"op-{uuid4()}"
        base = {"operation_id": operation, "operation_type": "test", "project_id": project, "parent_operation_id": "", "status": "pending", "idempotency_key": operation, "request_digest": "digest", "environment": "test", "metadata": {}}
        with self.assertRaises(Exception):
            with ProductionUnitOfWork(URL) as uow:
                uow.create_operation(operation=base, scope=project, event={"event_id": f"event-{uuid4()}", "aggregate_type": "operation", "aggregate_id": operation, "project_id": project, "event_type": "created", "event_version": 1, "sequence_number": 1, "correlation_id": "", "causation_id": "", "payload": {}}, outbox={"outbox_id": f"outbox-{uuid4()}", "event_id": "missing-event", "project_id": project, "topic": "operation", "payload": {}}, audit={"audit_id": f"audit-{uuid4()}", "project_id": project, "operation_id": operation, "action": "created", "payload": {}})
                uow.commit()
        with ProductionUnitOfWork(URL) as uow:
            self.assertIsNone(uow.operations.get_by_id(operation, project))
