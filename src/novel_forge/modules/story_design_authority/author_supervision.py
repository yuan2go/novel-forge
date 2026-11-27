from __future__ import annotations

from novel_forge.modules.story_design_authority.qualification import (
    qualification_profiles_for_asset,
)

from typing import Any, Mapping

from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.author_supervision import (
    MODE, verify_frozen_supervision, verify_policy_provenance,
)


def candidate_supervision(cursor: Any, *, project_id: str, asset_version_id: str, author_input: bool = False) -> dict[str, Any] | None:
    cursor.execute(
        """SELECT v.content, v.content_hash, e.request_payload #> '{_production_execution,capability_runtime,routing_decision}'
           FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
           JOIN authority_operation_output_asset output ON output.asset_version_id=v.asset_version_id
           JOIN authority_external_effect e ON e.operation_id=output.operation_id AND e.project_id=a.project_id
           WHERE a.project_id=%s AND v.asset_version_id=%s AND e.status='SUCCEEDED'
             AND e.request_payload #>> '{_production_execution,capability_runtime,routing_decision,status}'='AUTHOR_SUPERVISED_SELECTED'""",
        [project_id, asset_version_id],
    )
    rows = cursor.fetchall()
    if not rows:
        cursor.execute("""SELECT state.source_kind,state.execution_evidence,v.content,v.content_hash
            FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            LEFT JOIN authority_story_design_version_state state ON state.asset_version_id=v.asset_version_id
            WHERE a.project_id=%s AND v.asset_version_id=%s""", [project_id, asset_version_id])
        row = cursor.fetchone()
        if row and row[0] == "OPERATOR_AUTHORED" and row[1].get("author_supervision"):
            from novel_forge.modules.production_execution.author_supervision import verify_book_supervision
            receipt = dict(row[1]["author_supervision"])
            verify_book_supervision(cursor, receipt)
            return receipt
        if not row or not author_input or not row[2].get("book_id"):
            return None
        if row[2].get("routing_eligibility") == "BENCHMARK_ONLY" or row[2].get("routing_bootstrap_authorization"):
            raise KernelError("PLANNING_BENCHMARK_ONLY", "Diagnostic samples cannot become author input")
        from novel_forge.modules.production_execution.author_supervision import selected_book_supervision
        policy = selected_book_supervision(cursor, project_id=project_id, book_id=row[2]["book_id"])
        return ({**policy, "asset_version_id": asset_version_id, "content_hash": row[3],
                 "source_kind": "OPERATOR_AUTHORED"} if policy else None)
    if len(rows) != 1:
        raise KernelError("AUTHOR_SUPERVISION_CANDIDATE_AMBIGUOUS", "Candidate requires one exact supervised model receipt")
    content, digest, decision = rows[0]
    if content.get("routing_eligibility") == "BENCHMARK_ONLY" or content.get("routing_bootstrap_authorization"):
        raise KernelError("PLANNING_BENCHMARK_ONLY", "Diagnostic samples cannot become author-supervised design")
    if content.get("execution_evidence", {}).get("fixture_protocol_only"):
        raise KernelError("AUTHOR_SUPERVISION_FIXTURE_FORBIDDEN", "Fixture evidence cannot enter supervised production")
    verify_frozen_supervision(decision)
    verify_policy_provenance(cursor, decision)
    if content.get("book_id") != decision["task"]["work_id"]:
        raise KernelError("AUTHOR_SUPERVISION_CANDIDATE_SCOPE", "Candidate and frozen route name different Books")
    return {"mode": MODE, "asset_version_id": asset_version_id, "content_hash": digest,
            "project_id": project_id, "book_id": content["book_id"],
            "route_decision_id": decision["decision_id"], **decision["author_supervision"]}


def validate_author_review(review: Any, *, principal: Any, supervision: Mapping[str, Any],
                           asset_version_id: str, content_hash: str, cursor: Any = None) -> list[dict[str, Any]]:
    principal.require("story_design.authority.execute", supervision["project_id"])
    if (principal.principal_type is not PrincipalType.LOCAL_OPERATOR
            or principal.principal_id != supervision.get("author_id", supervision.get("authorization", {}).get("author_id"))):
        raise PermissionError("Only the scoped authenticated author may judge supervised design")
    if (not isinstance(review, dict) or set(review) != {"asset_version_id", "content_hash", "decision", "reason", "findings"}
            or review["asset_version_id"] != asset_version_id or review["content_hash"] != content_hash
            or review["decision"] != "ACCEPT" or not isinstance(review["reason"], str) or not review["reason"].strip()
            or not isinstance(review["findings"], list)):
        raise KernelError("AUTHOR_SUPERVISION_EXACT_REVIEW_REQUIRED", "Author must review the exact candidate and record reasons")
    ids = set()
    for finding in review["findings"]:
        if (not isinstance(finding, dict) or set(finding) != {"finding_id", "disposition", "reason"}
                or not finding["finding_id"] or finding["finding_id"] in ids
                or finding["disposition"] not in {"PRESERVE", "DISMISSED_WITH_EVIDENCE", "RESOLVED"}
                or not isinstance(finding["reason"], str) or not finding["reason"].strip()):
            raise KernelError("AUTHOR_SUPERVISION_UNRESOLVED_FINDING", "Every recorded dispute needs an explicit evidenced disposition")
        ids.add(finding["finding_id"])
    if cursor is None:
        raise KernelError("AUTHOR_SUPERVISION_REVIEW_STORE_REQUIRED", "Author judgment requires native review evidence")
    cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content->'evaluation'
        FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=v.asset_version_id
        JOIN authority_operation op ON op.operation_id=output.operation_id AND op.project_id=a.project_id AND op.status='SUCCEEDED'
        WHERE a.project_id=%s AND a.asset_type='narrative_design_evaluation'
          AND v.content->>'candidate_asset_version_id'=%s AND v.content->>'candidate_content_hash'=%s
          AND v.content->>'evaluation_purpose'='AUTHOR_ADVISORY'""", [supervision["project_id"], asset_version_id, content_hash])
    receipts = []
    dispositions = {f["finding_id"]: f for f in review["findings"]}
    for version, digest, evaluation in cursor.fetchall():
        receipts.append({"asset_version_id": version, "content_hash": digest, "purpose": "AUTHOR_ADVISORY"})
        for profile in evaluation["evaluations"]:
            for finding in profile["criteria"]:
                if finding["verdict"] == "PASS":
                    continue
                finding_id = version + ":" + profile["layer"] + ":" + finding["criterion"]
                if dispositions.get(finding_id, {}).get("disposition") not in {"RESOLVED", "DISMISSED_WITH_EVIDENCE"}:
                    raise KernelError("AUTHOR_SUPERVISION_UNRESOLVED_FINDING", "Author must address model finding " + finding_id)
    return receipts


def supervised_state(state: Mapping[str, Any]) -> bool:
    return (state.get("execution_evidence", {}).get("author_supervision", {}).get("mode") == MODE
            and state.get("qualification") in {"STRUCTURALLY_VALID", "SEMANTICALLY_VALID"})


def approved_design_receipt(cursor: Any, *, project_id: str, book_id: str,
                            asset_version_id: str) -> dict[str, Any] | None:
    cursor.execute(
        """SELECT state.qualification, state.approval, state.freshness, candidate.content_hash,
                  receipt.asset_version_id, receipt.content_hash, receipt.content, op.actor_id,
                  state.execution_evidence, state.lifecycle
           FROM authority_story_design_version_state state
           JOIN authority_asset_version candidate ON candidate.asset_version_id=state.asset_version_id
           JOIN authority_story_design_transition transition ON transition.project_id=state.project_id
             AND transition.asset_version_id=state.asset_version_id AND transition.transition_type='APPROVE'
           JOIN authority_operation op ON op.operation_id=transition.transition_operation_id AND op.status='SUCCEEDED'
           JOIN authority_operation_output_asset output ON output.operation_id=op.operation_id
           JOIN authority_asset_version receipt ON receipt.asset_version_id=output.asset_version_id
           WHERE state.project_id=%s AND state.asset_version_id=%s
             AND candidate.content->>'book_id'=%s ORDER BY transition.to_version DESC""",
        [project_id, asset_version_id, book_id],
    )
    rows = cursor.fetchall()
    if not rows or rows[0][0] == "QUALIFIED" or rows[0][8].get("creative_validation", {}).get("mode") == "CREATIVE_VALIDATION":
        return None
    row = rows[0]
    evidence = row[6].get("evidence", {})
    supervision = row[8].get("author_supervision", {})
    review = evidence.get("author_review", {})
    if (row[0:3] != ("SEMANTICALLY_VALID", "APPROVED", "CURRENT")
            or supervision.get("mode") != MODE or evidence.get("author_supervision") != supervision
            or row[7] != supervision.get("author_id", supervision.get("authorization", {}).get("author_id"))
            or review.get("asset_version_id") != asset_version_id or review.get("content_hash") != row[3]
            or review.get("decision") != "ACCEPT" or row[6].get("transition") != "APPROVE"):
        raise KernelError("AUTHOR_SUPERVISION_APPROVAL_REQUIRED", "Design needs its exact native author decision")
    return {"mode": MODE, "asset_version_id": asset_version_id, "content_hash": row[3],
            "decision_asset_version_id": row[4], "decision_content_hash": row[5],
            "author_id": row[7], "author_review": review, "lifecycle": row[9], "literary_qualification": "NOT_PROVEN"}


def reusable_qualified_design_receipt(
    cursor: Any, *, project_id: str, book_id: str, asset_version_id: str, generator: str
) -> dict[str, Any]:
    cursor.execute("""SELECT q.design_layer,q.profile_id,q.profile_version,q.profile_hash,
        q.qualification_hash,q.evaluation_hash,e.evaluation_asset_version_id,v.content_hash
        FROM authority_current_narrative_design_qualification q
        JOIN authority_narrative_design_qualification e USING(qualification_id)
        JOIN authority_asset_version v ON v.asset_version_id=q.asset_version_id
        JOIN authority_operation op ON op.operation_id=q.source_operation_id AND op.project_id=q.project_id
        WHERE q.project_id=%s AND q.book_id=%s AND q.asset_version_id=%s
          AND q.freshness='CURRENT' AND q.qualification_status='PASS'
          AND e.trust_boundary='INDEPENDENT' AND q.evaluator_execution_class='MODEL_PROVIDER'
          AND e.provider_model_call_asset_version_id IS NOT NULL AND e.provider_model_call_content_hash IS NOT NULL
          AND e.provider_evidence_hash IS NOT NULL AND e.provider_result_hash IS NOT NULL AND e.provider_route_snapshot_id IS NOT NULL
          AND op.status IN ('WAITING_GATE','SUCCEEDED')
          AND v.lifecycle='ACTIVE' AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR'
        ORDER BY q.design_layer""", [project_id, book_id, asset_version_id])
    rows = cursor.fetchall()
    profiles = qualification_profiles_for_asset(
        cursor,
        project_id=project_id,
        asset_version_id=asset_version_id,
        generator=generator,
    )
    expected = {(p.layer.value,p.profile_id,p.profile_version,p.profile_hash) for p in profiles}
    if len(rows) != len(expected) or {tuple(row[:4]) for row in rows} != expected:
        raise KernelError("LONGFORM_DESIGN_QUALIFICATION_INCOMPLETE", "Existing strict design must retain all current real independent qualification receipts")
    return {"mode":"STRICT_QUALIFIED", "asset_version_id":asset_version_id, "content_hash":rows[0][7],
        "design_layer":generator, "lifecycle":"ACTIVE", "receipts":[dict(zip(
            ("design_layer","profile_id","profile_version","profile_hash","qualification_hash","evaluation_hash","evaluation_asset_version_id"), row[:7])) for row in rows]}
