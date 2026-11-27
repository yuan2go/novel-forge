from dataclasses import asdict
from time import monotonic
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.production import SubmitBookChapterCommand
from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from scripts.narrative_closure_campaign import drive_chapter
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_cross_chapter_prose_review_postgres import (
    ProseTransport, ReceiptCommitLoss, make_book,
)


def test_campaign_native_drive_recovers_receipt_loss_and_replays_acceptance(tmp_path):
    transport = ProseTransport(loss=True)
    project, authority, chapter, principal, worker, book, candidates, plans, restart = make_book(tmp_path, transport)
    composition = SimpleNamespace(authority=authority, query=PostgresBookProductionQuery(DATABASE_URL))
    events = []
    for number in (1, 2):
        plan = plans[number]
        command = SubmitBookChapterCommand(book_run_id=book.book_run_id, chapter_number=number,
            title=f"Chapter {number}", premise="A choice has an irreversible cost.",
            chapter_plan_asset_version_id=plan["asset_version_id"], chapter_plan_content_hash=plan["content_hash"],
            context_candidates=tuple(plan if item["asset_type"] == "chapter_plan" else item for item in candidates),
            preparation_report={"stage_context_token_budgets": {"review": 64000, "rereview": 64000, "revision": 64000}})
        payload = asdict(command)
        payload.pop("book_run_id")
        arm = {"project_id": project, "book_run_id": book.book_run_id, "chapter_command": payload}
        arguments = {"composition": composition, "chapter": chapter, "principal": principal, "worker": worker,
                     "arm": arm, "deadline": monotonic() + 180, "max_ticks": 100, "record": events.append}
        if number == 2:
            with pytest.raises(ReceiptCommitLoss):
                drive_chapter(**arguments)
            sends_before = sum(stage == "review" and bool(inputs["cross_chapter_window"]["sources"]) for stage, inputs in transport.calls)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("""UPDATE authority_lease_acquisition lease SET expires_at=acquired_at+INTERVAL '1 microsecond'
                    FROM authority_attempt attempt JOIN authority_operation operation USING(operation_id)
                    WHERE lease.attempt_id=attempt.attempt_id AND operation.project_id=%s
                    AND operation.definition_name='chapter.review.evaluate' AND lease.status='HELD'""", [project])
                uow.commit()
            arguments["chapter"] = restart()
        result = drive_chapter(**arguments)
        assert result["status"] == "ACCEPTED_TARGET"
        if number == 2:
            assert sum(stage == "review" and bool(inputs["cross_chapter_window"]["sources"]) for stage, inputs in transport.calls) == sends_before
        before_replay = len(transport.calls)
        replay = drive_chapter(**arguments)
        assert replay["replayed"] is True
        assert len(transport.calls) == before_replay
    assert authority.require(book.book_run_id)["accepted_through_chapter"] == 2
    assert any(event["kind"] == "NATIVE_CHAPTER_ADMISSION" for event in events)
