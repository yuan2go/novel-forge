from __future__ import annotations

from typing import Any


def bucket_dispatch_result(result: dict[str, Any], buckets: dict[str, list[dict[str, Any]]]) -> None:
    status = str(result.get("queue_status", ""))
    if status == "acked":
        buckets["acked"].append(result)
    elif status == "waiting_human":
        buckets["waiting_human"].append(result)
    elif status == "retry_scheduled":
        buckets["retried"].append(result)
    elif status == "dead_letter":
        buckets["dead_lettered"].append(result)
