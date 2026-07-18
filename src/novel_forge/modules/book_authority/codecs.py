from __future__ import annotations

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest
from novel_forge.modules.content_authority.codecs import ContentHandlerCodec


def _payload(request: AuthorityHandlerRequest) -> dict:
    return dict(request.command.get("payload") or {})


def _prepare(request: AuthorityHandlerRequest) -> dict:
    payload = _payload(request)
    return {
        "type": "BookProductionManifest", "project_id": request.project_id,
        "target_chapter_count": int(payload["target_chapter_count"]),
        "policy": dict(payload["policy"]), "fixture_protocol_only": True,
        "real_model_call": False, "production_verified": False,
        "contract_version": "book-production-manifest-v1",
    }


def _chapter_dispatch(request: AuthorityHandlerRequest) -> dict:
    payload = _payload(request)
    return {
        "type": "ChapterAcceptanceRecord", "project_id": request.project_id,
        "chapter": int(payload["chapter"]), "decision": "ACCEPTED_FIXTURE_PROTOCOL",
        "chapter_root_operation_id": "scripted-fixture:no-prose-generated",
        "fixture_protocol_only": True, "real_model_call": False,
        "longform_proven": False, "production_verified": False,
        "contract_version": "chapter-acceptance-record-v1",
    }


def _recap(request: AuthorityHandlerRequest) -> dict:
    payload = _payload(request)
    cadence = str(payload["cadence"])
    return {
        "type": "BookRecapSchedule", "project_id": request.project_id,
        "through_chapter": int(payload["through_chapter"]), "cadence": cadence,
        "recap_status": "FIXTURE_PROTOCOL_COMPLETE",
        "plan_mutation_allowed": False, "fixture_protocol_only": True,
        "longform_proven": False, "production_verified": False,
        "contract_version": "book-recap-schedule-v1",
    }


def _plan_adjustment(request: AuthorityHandlerRequest) -> dict:
    payload = _payload(request)
    return {
        "type": "PlanAdjustmentProposal", "project_id": request.project_id,
        "through_chapter": int(payload["through_chapter"]),
        "risk_classification": "REQUIRES_APPROVAL",
        "mutates_frozen_chapters": False, "proposed_changes": [],
        "fixture_protocol_only": True, "production_verified": False,
        "contract_version": "plan-adjustment-proposal-v1",
    }


BOOK_CODECS = {
    codec.definition_name: codec
    for codec in (
        ContentHandlerCodec("book.production.prepare", "book_production_manifest", "book.production.manifest", _prepare),
        ContentHandlerCodec("book.chapter.dispatch", "chapter_acceptance_record", "book.chapter.acceptance", _chapter_dispatch),
        ContentHandlerCodec("book.recap.light", "recap_schedule", "book.recap.light", _recap),
        ContentHandlerCodec("book.recap.formal", "recap_schedule", "book.recap.formal", _recap),
        ContentHandlerCodec("book.plan_adjustment.propose", "plan_adjustment_proposal", "book.plan_adjustment.proposal", _plan_adjustment),
    )
}
