from copy import deepcopy

import pytest

from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW
from novel_forge.modules.book_authority.plan_recovery import require_reference_failure, replacement_binding
from novel_forge.modules.command_kernel.errors import KernelError


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)

    def execute(self, *_):
        pass

    def fetchone(self):
        return next(self.rows)

    def fetchall(self):
        return next(self.rows)


def source():
    book = {"project_id":"p","workspace_id":"w","book_id":"b","book_run_id":"run","active_chapter_request_id":"request",
        "current_chapter":1,"accepted_through_chapter":0,"author_workflow":AUTHOR_WORKFLOW,"state":"CHAPTER_SUBMITTED"}
    request = {"project_id":"p","book_run_id":"run","chapter_request_id":"request","chapter_number":2,"chapter_root_operation_id":"root"}
    root = {"project_id":"p","workspace_id":"w","actor_id":"actor","operation_id":"root","status":"WAITING_CHILDREN",
        "command_payload":{"book_id":"b","chapter":2}}
    failures = [("intent",1,{"error_code":"CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID"})]
    return book,request,root,failures


def test_author_first_recovery_uses_delivered_frontier_without_faking_acceptance():
    book,request,root,failures = source()
    original = deepcopy((book,request,root,failures))
    proof = require_reference_failure(Cursor([(root,),failures,(False,False,False,False)]),book=book,request=request,actor_id="actor")
    assert proof["failures"][0]["attempt_number"] == 1
    assert (book,request,root,failures) == original


def test_failed_terminal_root_is_retained_without_rewriting_it_as_cancelled():
    book,request,root,failures = source()
    root["status"] = "FAILED_FINAL"
    require_reference_failure(Cursor([(root,),failures,(False,)*4]),book=book,request=request,actor_id="actor")
    assert root["status"] == "FAILED_FINAL"


@pytest.mark.parametrize("field,value", [("project_id","other"),("workspace_id","other"),("actor_id","other"),("status","SUCCEEDED")])
def test_foreign_or_completed_roots_cannot_be_retired(field,value):
    book,request,root,failures = source()
    root[field] = value
    with pytest.raises(KernelError):
        require_reference_failure(Cursor([(root,),failures,(False,)*4]),book=book,request=request,actor_id="actor")


@pytest.mark.parametrize("position",range(4))
def test_any_external_effect_produced_body_lease_or_acceptance_preserves_existing_recovery(position):
    book,request,root,failures = source()
    blocked = [False]*4
    blocked[position] = True
    with pytest.raises(KernelError,match="dispatched, leased, produced or accepted"):
        require_reference_failure(Cursor([(root,),failures,tuple(blocked)]),book=book,request=request,actor_id="actor")


@pytest.mark.parametrize("code",["PROVIDER_STREAM_INTERRUPTED","CHAPTER_MEMO_MISSION_DRIFT",None])
def test_provider_or_character_semantic_problems_do_not_enter_reference_plan_recovery(code):
    book,request,root,failures = source()
    failures[0][2]["error_code"] = code
    with pytest.raises(KernelError,match="actual frozen-reference"):
        require_reference_failure(Cursor([(root,),failures]),book=book,request=request,actor_id="actor")


def test_pending_journal_restarts_into_exact_plan_and_predecessor_only():
    book,request,_,_ = source()
    content = {"contract_version":"book-preprose-plan-replacement.v1","book_run_id":"run","proposal_id":"change",
        "predecessor_request_id":"request","predecessor_root_operation_id":"root","generation":2,
        "corrected_plan_asset_version_id":"new-plan","corrected_plan_content_hash":"hash"}
    uow = type("Uow",(),{"cursor":Cursor([("journal",content)])})()
    result = replacement_binding(uow,book=book,chapter=2,plan_version="new-plan",plan_hash="hash")
    assert result["generation"] == 2 and result["predecessor_request_id"] == request["chapter_request_id"]
    uow.cursor = Cursor([("journal",content)])
    with pytest.raises(KernelError,match="exact corrected Plan"):
        replacement_binding(uow,book=book,chapter=2,plan_version="new-plan",plan_hash="changed")


def test_recovery_cli_requires_exact_proposal():
    from novel_forge.cli.authority import _authority_parser
    args = _authority_parser().parse_args(["authority-manuscript","recover-plan-references","--book-run-id","run","--proposal-id","change"])
    assert args.proposal_id == "change"
