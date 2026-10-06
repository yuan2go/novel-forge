from __future__ import annotations

from decimal import Decimal
from math import ceil
from typing import Any, Mapping

from .execution_template import BOOK_USAGE_SQL


def rolling_work_estimate(cursor: Any, *, project_id: str, book_id: str,
                          input_tokens: int, output_tokens: int, template: Mapping[str, Any]) -> dict[str, Any]:
    cursor.execute("""SELECT target_chapter_count,accepted_through_chapter FROM authority_book_production
        WHERE project_id=%s AND book_id=%s ORDER BY created_at DESC LIMIT 1""", [project_id, book_id])
    goal = cursor.fetchone()
    if goal is None:
        cursor.execute("""SELECT (frozen_stage_inputs #>> '{generation_policy,target_chapters}')::integer,0
            FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s
            ORDER BY created_at DESC LIMIT 1""", [project_id, book_id])
        goal = cursor.fetchone()
    cursor.execute(f"""SELECT r.provider,count(*),COALESCE(avg(r.actual_tokens),0),COALESCE(avg(r.settled_amount),0)
        FROM authority_budget_reservation r JOIN authority_external_effect e USING(external_effect_id)
        WHERE r.project_id=%s AND {BOOK_USAGE_SQL}
          AND r.status='SETTLED' GROUP BY r.provider""", [project_id, book_id, book_id, book_id])
    history = {row[0]: {"calls": int(row[1]), "average_tokens": ceil(row[2]),
                        "average_paid_amount": str(row[3]) if row[0] == "deepseek" else None}
               for row in cursor.fetchall()}
    cursor.execute(f"""SELECT CASE WHEN e.request_payload #>>
        '{{_production_execution,capability_runtime,routing_decision,task,task_type}}'
        IN ('model_reference_evaluate','model_reference_adjudicate')
        OR e.request_payload #>> '{{_production_execution,capability_runtime,routing_decision,mode}}'='BENCHMARK_CHALLENGER'
        OR r.evidence #>> '{{creative_experiment,phase}}' IN ('REFERENCE','SCREENING','CALIBRATION','HOLDOUT','QUALIFICATION')
        THEN 'ENGINEERING_VALIDATION' ELSE 'BOOK_PRODUCTION' END,
        count(*),COALESCE(sum(r.actual_tokens),0),
        COALESCE(sum(CASE WHEN r.provider='deepseek' AND r.currency='USD' THEN r.settled_amount ELSE 0 END),0)
        FROM authority_budget_reservation r JOIN authority_external_effect e USING(external_effect_id)
        WHERE r.project_id=%s AND {BOOK_USAGE_SQL}
          AND r.status='SETTLED' GROUP BY 1""", [project_id, book_id, book_id, book_id])
    accounting = {row[0]: {"settled_calls": int(row[1]), "observed_tokens": int(row[2]),
                           "settled_deepseek_usd": str(row[3])} for row in cursor.fetchall()}
    remaining = max(0, int(goal[0]) - int(goal[1])) if goal else None
    settled_calls = sum(row["calls"] for row in history.values())
    accepted = int(goal[1]) if goal else 0
    density = ceil(settled_calls / accepted) if accepted else None
    initial_buffer = max(0, 32 - settled_calls) if goal and not accepted else 0
    calls_range = [remaining * 16, remaining * max(40, ceil(density * 1.25) if density else 40) + initial_buffer] if remaining is not None else None
    member_tokens = max(input_tokens + output_tokens, history.get("codex-cli", {}).get("average_tokens", 0))
    paid = template["deepseek"]
    paid_plan = {"enabled": paid is not None, "currency": paid["currency"] if paid else None,
                 "maximum_amount": paid["maximum_amount"] if paid else None,
                 "estimate_status": "HISTORY_RANGE" if history.get("deepseek", {}).get("calls", 0) >= 3 else "COLD_START_REQUEST_RANGE"}
    if paid:
        from .execution_template import paid_usage
        used = paid_usage(cursor, project_id=project_id, book_id=book_id)
        paid_plan.update(used_or_reserved=str(used), remaining_amount=str(max(Decimal(0), Decimal(paid["maximum_amount"]) - used)))
        observed = Decimal(history.get("deepseek", {}).get("average_paid_amount") or "0")
        paid_plan["remaining_cost_range"] = [str(observed * count) for count in calls_range] if calls_range and history.get("deepseek", {}).get("calls", 0) >= 3 and observed > 0 else None
    return {"version": "work-resource-estimate.v1", "goal_chapters": int(goal[0]) if goal else None,
            "accepted_through_chapter": int(goal[1]) if goal else None, "remaining_chapters": remaining,
            "provider_calls_range": calls_range, "history": history, "consumption_by_purpose": accounting,
            "paid_ceiling_scope": "ALL_SAME_BOOK_PURPOSES_AND_STAGES",
            "codex": {"billing_channel": "ACCOUNT_ENTITLEMENT", "estimated_tokens_per_call": member_tokens,
                      "fee_budget": None, "availability": "RECHECK_AT_DISPATCH"}, "deepseek": paid_plan,
            "assumptions": ["cold start: 16-40 calls per remaining chapter plus an initial buffer of 32 calls",
                            "upper range rolls upward with observed same-Book calls per accepted chapter plus 25 percent repair headroom",
                            "observed same-Book averages do not establish literary quality",
                            "estimates never alter work scope or quality floor"]}
