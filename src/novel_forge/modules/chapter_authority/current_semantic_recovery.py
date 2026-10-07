from __future__ import annotations

from collections import Counter

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash

CONTRACT = "chapter-current-semantic-repair.v1"


def semantic_source(cursor, source):
    from .current_quote_recovery import asset, receipt
    from novel_forge.modules.canon_graph.grounding import (
        grounded_claims,
        validate_support_review,
    )
    from novel_forge.modules.command_kernel.step_successor import (
        has_candidate_domain_outputs,
    )

    if (
        source["definition_name"] != "chapter.canon.propose_changes"
        or source["definition_version"] != "3.9.23"
        or source["status"] not in {"FAILED_RETRYABLE", "FAILED_FINAL"}
        or has_candidate_domain_outputs(cursor, source["operation_id"])
    ):
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_NOT_APPLICABLE",
            "Retain the exact non-producing current independent support",
        )
    cursor.execute(
        "SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number",
        [source["operation_id"]],
    )
    attempts = [row[0] for row in cursor.fetchall()]
    if (
        len(attempts) != 1
        or attempts[0]["status"] != "FAILED_RETRYABLE"
        or attempts[0]["result"].get("error_code")
        != "CANON_GROUNDING_REEXTRACTION_REQUIRED"
    ):
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_NOT_APPLICABLE",
            "Require the original independently recorded semantic diagnostic",
        )
    evidence, review = receipt(cursor, source)
    assets = {}
    for binding in source["input_asset_snapshot"]:
        kind, doc = asset(cursor, source["project_id"], binding)
        if kind in assets:
            raise KernelError(
                "CURRENT_SEMANTIC_REPAIR_INPUT_DRIFT",
                "Require uniquely typed frozen support inputs",
            )
        assets[kind] = (binding, doc)
    extraction_binding, extraction = assets["canon_extraction"]
    target, candidate = assets["best_draft_candidate"]
    try:
        validate_support_review(
            extraction=extraction,
            revision=candidate,
            revision_asset_version_id=target["asset_version_id"],
            result=review,
        )
    except KernelError as error:
        if error.code != "CANON_GROUNDING_REEXTRACTION_REQUIRED":
            raise
    else:
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_NOT_APPLICABLE",
            "Do not repeat a valid independent review",
        )
    claims = {
        item["claim"]["grounded_claim_id"]: item for item in grounded_claims(extraction)
    }
    counts = Counter(item["claim_id"] for item in review["claims"])
    if set(counts) != set(claims) or any(number != 1 for number in counts.values()):
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_COVERAGE_INVALID",
            "Coverage disagreement retains its own owner",
        )
    negative = [
        {
            "field": claims[item["claim_id"]]["field"],
            "claim": claims[item["claim_id"]]["claim"],
            "assessment": item,
        }
        for item in review["claims"]
        if item["assessment"] != "SUPPORTED"
        or item["observed_kind"] != claims[item["claim_id"]]["claim"]["claim_kind"]
    ]
    if not negative:
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_NOT_APPLICABLE",
            "Require exact independent negative claim evidence",
        )
    cursor.execute(
        "SELECT to_jsonb(o) FROM authority_operation o JOIN authority_operation_output_asset output USING(operation_id) WHERE output.asset_version_id=%s AND output.role=%s",
        [extraction_binding["asset_version_id"], "primary"],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_EXTRACTION_INVALID",
            "Retain one completed native extraction",
        )
    canonical = rows[0][0]
    if (
        canonical["definition_name"] != "chapter.canon.extract"
        or canonical["definition_version"] not in {"3.9.29", "3.9.30", "3.9.31"}
        or canonical["status"] != "SUCCEEDED"
        or canonical["root_operation_id"] != source["root_operation_id"]
        or canonical["actor_id"] != source["actor_id"]
    ):
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_EXTRACTION_INVALID",
            "Require the original actor and current completed extraction",
        )
    cursor.execute(
        "SELECT attempt_number,status FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number",
        [canonical["operation_id"]],
    )
    original_limit = canonical["definition_snapshot"]["retry_policy"]["max_attempts"]
    require_unused_extraction_attempt(
        extraction=extraction, maximum=original_limit, attempts=cursor.fetchall()
    )
    extraction_evidence, rejected = receipt(cursor, canonical)
    if (
        evidence["cost_authorization_ref"]
        != extraction_evidence["cost_authorization_ref"]
        or evidence["book_id"] != extraction_evidence["book_id"]
    ):
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_IDENTITY_INVALID",
            "Retain the same real grant and Book",
        )
    inputs = {}
    for binding in canonical["input_asset_snapshot"]:
        kind, doc = asset(cursor, source["project_id"], binding)
        if kind in inputs:
            raise KernelError(
                "CURRENT_SEMANTIC_REPAIR_INPUT_DRIFT",
                "Require uniquely typed extraction inputs",
            )
        inputs[kind] = (binding, doc)
    if inputs["best_draft_candidate"] != (target, candidate):
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_INPUT_DRIFT",
            "Do not alter the selected prose during semantic extraction repair",
        )
    proof = {
        "contract_version": CONTRACT,
        "source_operation_id": source["operation_id"],
        "source_attempt": attempts[0],
        **evidence,
        "source_output_hash": snapshot_hash(review),
        "source_review_input_snapshot": source["input_asset_snapshot"],
        "source_input_snapshot": canonical["input_asset_snapshot"],
        "source_extraction_operation_id": canonical["operation_id"],
        "source_extraction_effect_id": extraction_evidence["source_effect_id"],
        "source_extraction_output_hash": snapshot_hash(rejected),
        "target_asset_version_id": target["asset_version_id"],
        "negative_assessments": negative,
        "original_extraction_maximum_attempts": original_limit,
        "remaining_semantic_reextractions": 1,
        "provider_invoked": True,
        "strict_certification_eligible": False,
        "semantic_assessments_reused_as_pass": False,
    }
    return proof, rejected, canonical, inputs


def retire_semantic_frontier(authority, *, book_run_id, principal):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.runtime import (
        OperationTransitionCommand,
        transition_operation_in_uow,
    )
    from novel_forge.modules.command_kernel.operation_graph import (
        GraphCommandContext,
        terminalize_saga_from_extension,
    )
    from novel_forge.modules.command_kernel.derived_step_revalidation import (
        _settled_graph,
    )

    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    with AuthorityUnitOfWork(authority.database_url) as uow:
        c = uow.cursor
        c.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE",
            [request["chapter_root_operation_id"]],
        )
        root = c.fetchone()[0]
        if root["status"] != "WAITING_CHILDREN":
            return False
        c.execute(
            """SELECT DISTINCT to_jsonb(o) FROM authority_operation o JOIN authority_attempt a USING(operation_id)
            WHERE o.root_operation_id=%s AND o.definition_name='chapter.canon.propose_changes' AND o.definition_version='3.9.23'
            AND o.status IN ('FAILED_RETRYABLE','FAILED_FINAL') AND a.result->>'error_code'='CANON_GROUNDING_REEXTRACTION_REQUIRED' """,
            [root["operation_id"]],
        )
        rows = c.fetchall()
        if not rows:
            return False
        if (
            len(rows) != 1
            or root["actor_id"] != principal.principal_id
            or rows[0][0]["actor_id"] != principal.principal_id
        ):
            raise KernelError(
                "CURRENT_SEMANTIC_REPAIR_ACTOR_INVALID",
                "Require the exact original actor and sole current disagreement",
            )
        source = rows[0][0]
        semantic_source(c, source)
        _settled_graph(c, root["operation_id"])
        c.execute(
            "SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE",
            [book_run_id],
        )
        if c.fetchone() != (
            book["version"],
            book["active_chapter_request_id"],
            book["accepted_through_chapter"],
        ):
            raise KernelError(
                "CURRENT_SEMANTIC_REPAIR_BOOK_CONFLICT",
                "Reload the current unaccepted Book frontier",
            )
        c.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW())",
            [source["operation_id"]],
        )
        if (
            c.fetchone()[0]
            or request["chapter_number"] != book["accepted_through_chapter"] + 1
        ):
            raise KernelError(
                "CURRENT_SEMANTIC_REPAIR_FRONTIER_INVALID",
                "Do not retire leased or accepted work",
            )
        if source["status"] == "FAILED_RETRYABLE":
            transition_operation_in_uow(
                uow,
                OperationTransitionCommand(
                    operation_id=source["operation_id"],
                    project_id=book["project_id"],
                    expected_version=source["version"],
                    expected_status="FAILED_RETRYABLE",
                    target_status="FAILED_FINAL",
                    actor_id=principal.principal_id,
                    reason="Exact independent semantic rejection requires extraction successor; original failed Attempt remains unchanged",
                    trace_id=source["trace_id"],
                    correlation_id=source["correlation_id"],
                    causation_id=source["operation_id"],
                ),
            )
            uow.commit()
    terminalize_saga_from_extension(
        authority.database_url,
        GraphCommandContext(
            book["project_id"],
            principal.principal_id,
            root["trace_id"],
            root["correlation_id"],
        ),
        request["chapter_saga_id"],
        operation_id=source["operation_id"],
    )
    return True


def repair_feedback(request):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.retained_graph import BINDING, source_graph
    from novel_forge.modules.canon_graph.domain import (
        PROVIDER_SEMANTIC_CHANGE_FIELDS,
    )

    binding = (request.command.get("preparation_report") or {}).get(BINDING) or {}
    proof = binding.get("retained_result") or {}
    if proof.get("contract_version") != CONTRACT:
        return None
    with AuthorityUnitOfWork(request.database_url) as uow:
        c = uow.cursor
        c.execute(
            """SELECT j.source_snapshot,j.policy_evidence,o.actor_id,o.input_asset_snapshot FROM authority_graph_continuation j
            JOIN authority_operation o ON o.root_operation_id=j.successor_root_operation_id WHERE o.operation_id=%s""",
            [request.operation_id],
        )
        row = c.fetchone()
        if (
            not row
            or row[1] != binding
            or row[2] != row[0]["root"]["actor_id"]
            or row[3] != proof["source_input_snapshot"]
        ):
            raise KernelError(
                "CURRENT_SEMANTIC_REPAIR_LINEAGE_INVALID",
                "Retain the exact continuation, original actor and frozen inputs",
            )
        c.execute(
            "SELECT attempt_number FROM authority_attempt WHERE attempt_id=%s AND operation_id=%s",
            [request.attempt_id, request.operation_id],
        )
        if c.fetchone() != (1,):
            raise KernelError(
                "CURRENT_SEMANTIC_REPAIR_CONTROL_EXHAUSTED",
                "Only the one unused original extraction send may execute through this semantic successor",
            )
        actual = source_graph(
            c,
            root_id=row[0]["root"]["operation_id"],
            project_id=request.project_id,
            actor_id=row[2],
        )
        if actual != row[0]:
            raise KernelError(
                "CURRENT_SEMANTIC_REPAIR_SOURCE_DRIFT",
                "Do not change the retained independent semantic evidence",
            )
        c.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [proof["source_operation_id"]],
        )
        verified, rejected, _, _ = semantic_source(c, c.fetchone()[0])
    fields = {
        PROVIDER_SEMANTIC_CHANGE_FIELDS[item["field"]]
        for item in verified["negative_assessments"]
        if item["field"] in PROVIDER_SEMANTIC_CHANGE_FIELDS
    }
    return {
        "contract_version": "canon-support-reextraction-feedback.v1",
        "independent_negative_assessments": verified["negative_assessments"],
        "retained_extraction_hash": verified["source_extraction_output_hash"],
        "rejected_fields": {field: rejected[field] for field in sorted(fields)},
        "unassigned_claim_ids": [],
        "instructions": "Repair these actual exact-ID independent semantic disagreements against unchanged prose and native field kinds. Retain the failed review. Do not rewrite its classification, omit real changes or claim it passed. Regenerate a complete grounded extraction; a new full independent support review is required.",
    }


def require_unused_extraction_attempt(*, extraction, maximum, attempts):
    if (extraction.get("retained_result_repair") or {}).get(
        "contract_version"
    ) in {CONTRACT, "chapter-canon-reference-contract-repair.v1"} or attempts != [(1, "SUCCEEDED")]:
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_CONTROL_EXHAUSTED",
            "The original extraction consumed its repair attempt; preserve all receipts",
        )
    if maximum != 2:
        raise KernelError(
            "CURRENT_SEMANTIC_REPAIR_CONTROL_INVALID",
            "Only the original two-attempt extraction contract may supply its unused repair send",
        )
