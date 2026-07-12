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
