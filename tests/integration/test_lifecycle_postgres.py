import os
import unittest
from uuid import uuid4
from novel_forge.storage.production_uow import ProductionUnitOfWork

URL=os.environ.get("NOVEL_FORGE_DATABASE_URL","")
@unittest.skipUnless(URL,"NOVEL_FORGE_DATABASE_URL required")
class LifecyclePostgresTests(unittest.TestCase):
 def test_cas_rejects_second_complete(self):
  project,op=f"life-{uuid4()}",f"op-{uuid4()}"
  with ProductionUnitOfWork(URL) as u:
   u.operations.create({"operation_id":op,"operation_type":"test","project_id":project,"parent_operation_id":"","status":"running","idempotency_key":op,"request_digest":"d","environment":"test","metadata":{}});u.commit()
  with ProductionUnitOfWork(URL) as u:
   self.assertEqual(u.operations.compare_and_set_status(op,project,0,"running","completed"),1);u.commit()
  with ProductionUnitOfWork(URL) as u:
   with self.assertRaises(Exception): u.operations.compare_and_set_status(op,project,0,"running","completed")
