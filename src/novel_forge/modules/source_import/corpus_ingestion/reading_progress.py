from __future__ import annotations


def target_progress(plans: dict, stages: list[dict], cancelled: bool = False) -> dict:
    targets = []
    synthesis = []
    for plan in plans.values():
        units = [u for u in plan["units"] if u["role"] == "TARGET"]
        for index, unit in enumerate(units):
            rows = [
                r
                for r in stages
                if r["reading_identity"] == plan["identity"]
                and int(r["unit_index"]) == index
            ]
            observed = [r for r in rows if r["phase"] == "OBSERVE"]
            reviewed = [
                r
                for r in rows
                if r["phase"] == "REVIEW"
                and r.get("decision")
                and not r.get("validation_error")
            ]
            accepted = [
                r
                for r in reviewed
                if r.get("semantic_evidence") == "AGENT_REVIEW_ONLY"
                and r.get("decision") == "ACCEPT_IN_SCOPE"
            ]
            status = (
                (
                    "ACCEPTED"
                    if accepted[-1]["has_observation"]
                    else "NO_APPLICABLE_FINDINGS"
                )
                if accepted
                else "CANCELLED"
                if cancelled
                else "NEEDS_REVIEW"
                if any(r["status"] == "BLOCKED" for r in rows)
                else "FAILED"
                if any(
                    r["status"] in {"FAILED_FINAL", "FAILED_RETRYABLE"} for r in rows
                )
                else "PENDING_REVIEW"
                if reviewed
                or any(r.get("phase_status") == "COMPLETED" for r in observed)
                else "PENDING"
                if rows
                else "NOT_EXPANDED"
            )
            targets.append(
                {
                    "processing_id": plan["processing_id"],
                    "source_unit_version_id": unit["source_unit_version_id"],
                    "ordinal": unit["ordinal"],
                    "status": status,
                    "expanded": bool(observed),
                    "processed": any(
                        r.get("input_state") == "CONFIRMED_RETURNED" for r in observed
                    ),
                    "reviewed": bool(reviewed),
                    "accepted": bool(accepted),
                    "latest_operation_id": rows[-1]["operation_id"] if rows else None,
                }
            )
        aggregate = [
            r
            for r in stages
            if r["reading_identity"] == plan["identity"]
            and int(r["unit_index"]) == len(units)
        ]
        synthesis.append(
            {
                "processing_id": plan["processing_id"],
                "expanded": bool(aggregate),
                "reviewed": any(
                    r.get("semantic_evidence") == "AGENT_REVIEW_ONLY" for r in aggregate
                ),
            }
        )
    return {
        "target_units": len(targets),
        "expanded_target_units": sum(t["expanded"] for t in targets),
        "processed_target_units": sum(t["processed"] for t in targets),
        "reviewed_target_units": sum(t["reviewed"] for t in targets),
        "accepted_target_units": sum(t["accepted"] for t in targets),
        "unprocessed_target_units": sum(not t["processed"] for t in targets),
        "unexpanded_target_units": sum(not t["expanded"] for t in targets),
        "no_applicable_findings": sum(
            t["status"] == "NO_APPLICABLE_FINDINGS" for t in targets
        ),
        "target_outcomes": targets,
        "synthesis": synthesis,
        "coverage_complete": bool(targets) and all(t["accepted"] for t in targets),
    }
