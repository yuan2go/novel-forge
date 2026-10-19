import gzip
import hashlib
import json
import sys
from pathlib import Path


def verify(path):
    path = Path(path)
    data = json.load(gzip.open(path, "rt"))
    tables = data["tables"]
    unknowns = [row for row in tables["authority_external_effect"] if row["status"] == "UNKNOWN"]
    operations = {row["operation_id"]: row for row in tables["authority_operation"]}
    rows = []
    assert len(unknowns) >= 7
    for effect in unknowns:
        op = effect["operation_id"]
        isolation, = [row for row in tables["authority_generation_isolation"]
                      if row["operation_id"] == op and row["external_effect_id"] == effect["external_effect_id"]]
        proof = isolation["proof"]
        assert isolation["request_hash"] == effect["request_hash"]
        assert proof["business_commit_right"] == "REVOKED"
        assert proof["remote_outcome"] == proof["usage"] == "UNKNOWN"
        assert operations[op]["status"] in {"FAILED_FINAL", "CANCELLED"}
        attempts = [row for row in tables["authority_attempt"] if row["operation_id"] == op]
        assert attempts and all(row["status"] == "CANCELLED" for row in attempts)
        reservation, = [row for row in tables["authority_budget_reservation"]
                         if row["external_effect_id"] == effect["external_effect_id"]]
        assert reservation["status"] == "HELD_UNKNOWN"
        assert reservation["settled_amount"] is None and reservation["settled_cost_status"] == "PENDING"
        assert reservation["actual_tokens"] == 0
        successors = [row for row in tables["authority_saga_step_successor"]
                      if row["predecessor_operation_id"] == op]
        if successors:
            successor, = successors
            target = operations[successor["successor_operation_id"]]
            chain = []
            visited = {op}
            while True:
                assert target["operation_id"] not in visited
                visited.add(target["operation_id"])
                assert target["root_operation_id"] == operations[op]["root_operation_id"]
                chain.append({"operation_id": target["operation_id"], "status": target["status"]})
                following = [row for row in tables["authority_saga_step_successor"]
                             if row["predecessor_operation_id"] == target["operation_id"]]
                if not following:
                    break
                next_link, = following
                target = operations[next_link["successor_operation_id"]]
            assert target["status"] == "SUCCEEDED"
            linked = {"family": "NATIVE_SAGA_STEP_SUCCESSOR", "record_id": successor["successor_id"],
                      "immediate_successor_operation_id": successor["successor_operation_id"],
                      "final_successor_operation_id": target["operation_id"], "successor_chain": chain}
        else:
            continuation, = [row for row in tables["authority_story_planning_runtime_continuation"]
                              if row["continuation_id"] == proof["continuation_id"]]
            assert continuation["source_operation_id"] == op
            assert continuation["book_id"] == isolation["book_id"]
            linked = {"family": "NATIVE_PLANNING_RUNTIME_CONTINUATION", "record_id": continuation["continuation_id"],
                      "successor_operation_id": continuation["successor_operation_id"]}
        rows.append({"operation_id": op, "external_effect_id": effect["external_effect_id"],
            "stage": effect["request_payload"]["stage"], "effect_status": "UNKNOWN",
            "isolation_id": isolation["isolation_id"], "old_business_commit_right": "REVOKED",
            "attempt_ids": [row["attempt_id"] for row in attempts], "attempt_status": "CANCELLED",
            "reservation_id": reservation["reservation_id"], "reservation_status": "HELD_UNKNOWN",
            "settled_amount": None, "settled_cost_status": "PENDING", "raw_actual_tokens": 0,
            "actual_token_usage": "UNKNOWN; pending zero is not a measured zero", "linked_successor": linked})
    report = {"status": "PASS", "evidence_class": "READ_ONLY_NATIVE_UNKNOWN_RIGHTS_ACCOUNTING_AND_CAUSAL_SUCCESSOR",
        "source_snapshot": path.name, "source_file_sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        "unknown_effects_checked_without_reduced_denominator": len(unknowns),
        "original_unknowns_not_settled_or_relabelled": True,
        "no_cancelled_source_attempt_has_commit_authority": True,
        "ledger_zero_interpretation": "Existing pending placeholder, not measured zero usage or zero spend",
        "rows": rows}
    path.with_name("unknown-isolation-final.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("UNKNOWN preserved with revoked rights and native links:", len(rows))


if __name__ == "__main__":
    verify(sys.argv[1])
