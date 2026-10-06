from copy import deepcopy

import pytest

from novel_forge.modules.book_authority import execution_recovery as recovery
from novel_forge.modules.command_kernel.errors import KernelError


class Cursor:
    def __init__(self, root, effects, *, lease=False, accepted=False, cancelled=False):
        self.responses = iter([(root,), (cancelled,), effects, (lease,), (accepted,)])

    def execute(self, *args):
        pass

    def fetchone(self):
        return next(self.responses)

    def fetchall(self):
        return next(self.responses)


class Principal:
    principal_id = "operator"

    def require(self, permission, project):
        assert permission in {"book.authority.execute", "chapter.authority.execute"}
        assert project == "project"


@pytest.fixture
def source(monkeypatch):
    template = {
        "mode": "CREATIVE_VALIDATION",
        "book_id": "book",
        "member_authorization_ref": "grant",
        "require_literary_qualification": False,
        "require_independent_review": True,
    }
    monkeypatch.setattr(
        recovery,
        "selected_book_template",
        lambda *a, **k: {
            "policy_snapshot": {"policy": {"execution_templates": [template]}}
        },
    )
    monkeypatch.setattr(
        recovery, "verify_template_provenance", lambda *a: deepcopy(template)
    )
    root = {
        "operation_id": "root",
        "definition_version": "3.8.0",
        "command_payload": {},
        "actor_id": "operator",
        "status": "WAITING_CHILDREN",
    }
    book = {
        "project_id": "project",
        "book_id": "book",
        "state": "CHAPTER_RUNNING",
        "active_chapter_request_id": "request",
        "accepted_through_chapter": 0,
    }
    request = {
        "chapter_root_operation_id": "root",
        "chapter_request_id": "request",
        "chapter_number": 1,
    }
    candidate = {
        "provider": "codex-cli",
        "pricing": {"accounting_basis": "ACCOUNT_ENTITLEMENT"},
        "authorization_ref": "grant",
    }
    payload = {
        "_production_execution": {
            "capability_runtime": {
                "pack_ref": "chapter-pack@2.12.0",
                "routing_decision": {"selected": {"candidate": candidate}}
            }
        }
    }
    error = {
        "production_execution": {
            "execution_result": {"outcome": "TIMED_OUT", "process_receipt_ref": "receipt"},
            "process_evidence": {"failure_code": "PROCESS_TIMEOUT"},
        }
    }
    effect = [
        "effect",
        "FAILED_RETRYABLE",
        "hash",
        payload,
        error,
        "SETTLED",
        "chapter.memo.generate",
        "60",
        "2",
    ]
    return root, book, request, effect, candidate, error


@pytest.mark.parametrize(
    "boundary",
    [
        "known",
        "unknown",
        "success",
        "held-reserve",
        "paid",
        "output",
        "foreign-actor",
        "accepted-frontier",
        "changed-grant",
        "lease",
        "accepted",
        "strict",
        "cancelled",
        "missing-attempt",
        "missing-receipt",
        "foreign-stage",
    ],
)
def test_only_known_preprose_member_timeout_is_eligible(source, monkeypatch, boundary):
    root, book, request, effect, candidate, error = source
    if boundary == "unknown":
        effect[1] = "UNKNOWN"
    if boundary == "success":
        effect[1] = "SUCCEEDED"
    if boundary == "held-reserve":
        effect[5] = "HELD"
    if boundary == "paid":
        candidate["pricing"]["accounting_basis"] = "API_USAGE"
    if boundary == "output":
        error["production_execution"]["execution_result"]["output_manifest_ref"] = (
            "partial"
        )
    if boundary == "foreign-actor":
        root["actor_id"] = "foreign"
    if boundary == "accepted-frontier":
        book["accepted_through_chapter"] = 1
    if boundary == "changed-grant":
        candidate["authorization_ref"] = "other-grant"
    if boundary == "strict":
        monkeypatch.setattr(recovery, "selected_book_template", lambda *a, **k: None)
    effects = [deepcopy(effect), effect]
    effects[0][0] = "earlier-effect"
    if boundary == "missing-attempt":
        effects.pop(0)
    if boundary == "missing-receipt":
        error["production_execution"]["execution_result"]["process_receipt_ref"] = None
    if boundary == "foreign-stage":
        effect[6] = "chapter.draft.generate"
    cursor = Cursor(
        root, effects, lease=boundary == "lease", accepted=boundary == "accepted",
        cancelled=boundary == "cancelled",
    )
    if boundary == "lease":
        with pytest.raises(KernelError, match="Wait for the original execution lease"):
            recovery.source_evidence(
                cursor, book=book, request=request, principal=Principal()
            )
    else:
        result = recovery.source_evidence(
            cursor, book=book, request=request, principal=Principal()
        )
        assert bool(result) == (boundary == "known")


@pytest.mark.parametrize(
    "binding", [{}, [], "foreign", {"contract_version": recovery.CONTRACT}]
)
def test_malformed_execution_binding_fails_before_database(binding):
    with pytest.raises(KernelError, match="Invalid native execution successor binding"):
        recovery.require_dispatch(
            "must-not-connect",
            command_payload={"preparation_report": {recovery.BINDING: binding}},
            root_operation_id="root",
        )


@pytest.mark.parametrize("position", [0, 1])
@pytest.mark.parametrize("field,value", [(1, "UNKNOWN"), (1, "SUCCEEDED"), (5, "HELD"), (6, "chapter.draft.generate")])
def test_each_attempt_must_be_known_stopped_and_accounted(source, position, field, value):
    root, book, request, effect, _, _ = source
    effects = [deepcopy(effect), deepcopy(effect)]
    effects[position][field] = value
    assert recovery.source_evidence(Cursor(root, effects), book=book, request=request,
                                    principal=Principal()) is None
