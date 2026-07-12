import os
import threading
import unittest
from uuid import uuid4

from novel_forge.storage.production_uow import ProductionUnitOfWork

URL=os.environ.get("NOVEL_FORGE_DATABASE_URL", "")

@unittest.skipUnless(URL, "NOVEL_FORGE_DATABASE_URL required")
class OperationLeasePostgresTests(unittest.TestCase):
    def test_two_connections_acquire_one_lease_once(self):
        project,op=f"lease-{uuid4()}",f"op-{uuid4()}"
        with ProductionUnitOfWork(URL) as u:
            u.operations.create({"operation_id":op,"operation_type":"test","project_id":project,"parent_operation_id":"","status":"pending","idempotency_key":op,"request_digest":"d","environment":"test","metadata":{}});u.commit()
        barrier=threading.Barrier(2); got=[]
        def worker(name):
            barrier.wait()
            with ProductionUnitOfWork(URL) as u:
                if u.leases.acquire(op,name,30): got.append(name)
                u.commit()
        threads=[threading.Thread(target=worker,args=(x,)) for x in ("a","b")]
        [t.start() for t in threads];[t.join() for t in threads]
        self.assertEqual(len(got),1)
