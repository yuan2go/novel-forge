import os
import unittest
import threading
from uuid import uuid4

from novel_forge.storage.production_uow import ProductionUnitOfWork

URL=os.environ.get("NOVEL_FORGE_DATABASE_URL", "")

@unittest.skipUnless(URL, "NOVEL_FORGE_DATABASE_URL required")
class TransactionalOutboxPostgresTests(unittest.TestCase):
    def test_claim_ack_and_dead_letter_are_owner_guarded(self):
        project,op=f"outbox-{uuid4()}",f"op-{uuid4()}"
        event,outbox=f"event-{uuid4()}",f"outbox-{uuid4()}"
        with ProductionUnitOfWork(URL) as u:
            u.create_operation(operation={"operation_id":op,"operation_type":"test","project_id":project,"parent_operation_id":"","status":"pending","idempotency_key":op,"request_digest":"d","environment":"test","metadata":{}},scope=project,event={"event_id":event,"aggregate_type":"operation","aggregate_id":op,"project_id":project,"event_type":"created","event_version":1,"sequence_number":1,"correlation_id":"","causation_id":"","payload":{}},outbox={"outbox_id":outbox,"event_id":event,"project_id":project,"topic":"test","payload":{}},audit={"audit_id":f"audit-{uuid4()}","project_id":project,"operation_id":op,"action":"created","payload":{}});u.commit()
        with ProductionUnitOfWork(URL) as u:
            claimed=u.outbox.claim("worker-a",project,1,30);self.assertEqual([x["outbox_id"] for x in claimed],[outbox]);self.assertFalse(u.outbox.ack(outbox,"worker-b"));self.assertTrue(u.outbox.ack(outbox,"worker-a"));u.commit()

    def test_consumer_delivery_is_idempotent_in_postgres(self):
        project,op=f"dedup-{uuid4()}",f"op-{uuid4()}"; event=f"event-{uuid4()}"
        with ProductionUnitOfWork(URL) as u:
            u.create_operation(operation={"operation_id":op,"operation_type":"test","project_id":project,"parent_operation_id":"","status":"pending","idempotency_key":op,"request_digest":"d","environment":"test","metadata":{}},scope=project,event={"event_id":event,"aggregate_type":"operation","aggregate_id":op,"project_id":project,"event_type":"created","event_version":1,"sequence_number":1,"correlation_id":"","causation_id":"","payload":{}},outbox={"outbox_id":f"outbox-{uuid4()}","event_id":event,"project_id":project,"topic":"test","payload":{}},audit={"audit_id":f"audit-{uuid4()}","project_id":project,"operation_id":op,"action":"created","payload":{}});self.assertTrue(u.consumer_deliveries.record_once("consumer",event));self.assertFalse(u.consumer_deliveries.record_once("consumer",event));u.commit()

    def test_two_real_connections_claim_one_event_once(self):
        project,op=f"race-{uuid4()}",f"op-{uuid4()}"; event,outbox=f"event-{uuid4()}",f"outbox-{uuid4()}"
        with ProductionUnitOfWork(URL) as u:
            u.create_operation(operation={"operation_id":op,"operation_type":"test","project_id":project,"parent_operation_id":"","status":"pending","idempotency_key":op,"request_digest":"d","environment":"test","metadata":{}},scope=project,event={"event_id":event,"aggregate_type":"operation","aggregate_id":op,"project_id":project,"event_type":"created","event_version":1,"sequence_number":1,"correlation_id":"","causation_id":"","payload":{}},outbox={"outbox_id":outbox,"event_id":event,"project_id":project,"topic":"test","payload":{}},audit={"audit_id":f"audit-{uuid4()}","project_id":project,"operation_id":op,"action":"created","payload":{}});u.commit()
        barrier=threading.Barrier(2); results=[]
        def worker(name):
            barrier.wait()
            with ProductionUnitOfWork(URL) as u:
                results.extend((name,row["outbox_id"]) for row in u.outbox.claim(name,project,1,30));u.commit()
        threads=[threading.Thread(target=worker,args=(name,)) for name in ("a","b")]
        [t.start() for t in threads];[t.join() for t in threads]
        self.assertEqual(results, [(results[0][0],outbox)])
