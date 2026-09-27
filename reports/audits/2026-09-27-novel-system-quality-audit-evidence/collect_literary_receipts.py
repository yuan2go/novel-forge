"""Read retained files only; never opens a database, Provider or object service."""
from pathlib import Path
import argparse
import collections
import datetime
import gzip
import hashlib
import json
import re
import statistics
import tarfile

parser = argparse.ArgumentParser(description="Recompute audit inventory from a frozen source snapshot and explicitly referenced retained local files. No DB/network/model access.")
parser.add_argument("--source-root", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
BASE = args.source_root.resolve()
OUT = args.output_dir.resolve()
OUT.mkdir(parents=True, exist_ok=False)
SHA = "d69053557e5dd16ccfa4217fde234245a90fdc50"

def identity(path):
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

rows = []
for book in ("guofeng-xuanhuan-01", "yu-xian-zhi-wai"):
    root = Path("/Users/yuan/novel-runtime") / book / "codex-executions"
    for path in sorted(root.glob("*/process-receipt.json")):
        receipt = json.loads(path.read_text())
        stdout = path.parent / "stdout.log"
        usage = None
        for line in stdout.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "turn.completed":
                usage = event.get("usage")
        result_path = path.parent / "last-message.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else None
        result_kind = "NO_FINAL_RESULT"
        task = "world.design.generate" if "47ddae96" in path.parent.name else "planning.book.generate"
        if result is not None:
            if "evaluations" in result:
                result_kind = "DESIGN_SEMANTIC_EVALUATION"
                task = ",".join(e.get("profile_id", "") for e in result["evaluations"])
            else:
                result_kind = "DESIGN_GENERATION"
                task = next((v for k, v in [
                    ("core_conflict", "creative.proposal.generate"),
                    ("thematic_question", "theme.question.generate"),
                    ("ending_direction", "ending.intent.generate"),
                    ("reader_promise", "reader.promise.generate"),
                    ("world_foundation_json", "world.design.generate"),
                    ("characters", "character.cast.generate")
                ] if k in result), "UNKNOWN")
        row = {
            "book_directory": book,
            "book_id": "guofeng-xuanhuan-01" if book.startswith("guofeng") else "first-novel-pilot-a",
            "project_id": "first-novel-pilot-20260912",
            "receipt": identity(path),
            "stdout": identity(stdout),
            "execution_metadata": identity(path.parent / "execution-metadata.json"),
            "result": identity(result_path) if result_path.exists() else None,
            "receipt_id": receipt.get("receipt_id"),
            "execution_id": receipt.get("execution_id"),
            "external_effect_id_from_execution_id": receipt.get("execution_id", "").split(":")[1],
            "operation_id": receipt.get("operation_id"),
            "attempt_id": receipt.get("attempt_id"),
            "status": receipt.get("status"),
            "result_kind": result_kind,
            "task": task,
            "task_label_status": "AUDIT_INFERRED_NOT_ROUTER_TASK_ID",
            "schema_version": result.get("schema_version") if result else None,
            "result_integrity": receipt.get("result_integrity"),
            "transport": receipt.get("transport"),
            "process_started_at": receipt.get("process_started_at"),
            "completed_at": receipt.get("completed_at"),
            "elapsed_ms": receipt.get("elapsed_ms"),
            "local_termination_only": receipt.get("local_termination_only"),
            "input_sha256": receipt.get("input_sha256"),
            "command_sha256": receipt.get("command_sha256"),
            "request_digest": receipt.get("request_digest"),
            "requested_model": "gpt-6-astra",
            "requested_reasoning_effort": "high",
            "requested_identity_source": "retained route configuration/native model authority evidence; not a server model attestation",
            "provider_served_model": None,
            "provider_served_revision": None,
            "provider_served_identity_status": "NOT_REPORTED",
            "raw_cli_usage": usage,
            "observable_input_plus_output_tokens": (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) if usage else None,
            "monetary_cost": None,
            "monetary_cost_status": "UNKNOWN_ACCOUNT_ENTITLEMENT",
            "accepted_chapter_evidence": "NONE_IN_THIS_RESULT",
            "full_transmitted_prompt_text": "NOT_FOUND_IN_SCOPED_RETAINED_FILES",
        }
        if result and "evaluations" in result:
            row["evaluation_criteria"] = [{"profile_id": e.get("profile_id"), "criterion": c.get("criterion"), "verdict": c.get("verdict")} for e in result["evaluations"] for c in e.get("criteria", [])]
        rows.append(row)

effects = collections.defaultdict(list)
for row in rows:
    effects[row["external_effect_id_from_execution_id"]].append(row["execution_id"])
stats = {
    "audit_main_sha": SHA,
    "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "scope": "Two explicitly referenced local runtime codex-executions directories; retained September 13 records, not a current main run or a full account ledger",
    "process_receipts": len(rows),
    "unique_external_effect_ids": len(effects),
    "effects_with_multiple_process_receipts": {k: v for k, v in effects.items() if len(v) > 1},
    "process_status_counts": dict(collections.Counter(r["status"] for r in rows)),
    "result_kind_counts": dict(collections.Counter(r["result_kind"] for r in rows)),
    "observable_input_plus_output_tokens": sum(r["observable_input_plus_output_tokens"] or 0 for r in rows),
    "raw_usage_missing_processes": sum(r["raw_cli_usage"] is None for r in rows),
    "reasoning_tokens_not_added_twice": True,
    "historical_ledger_conservative_total": 1174027,
    "historical_ledger_unknown_ceiling_total": 332319,
    "ledger_source": "novels/guofeng-xuanhuan-01/output/00_导航与进度/progress.json:131-152",
    "monetary_cost": None,
    "cost_basis": "ACCOUNT_ENTITLEMENT; not zero-dollar paid inference",
    "elapsed_process_sum_ms": sum(r["elapsed_ms"] for r in rows),
    "elapsed_process_median_ms": statistics.median(r["elapsed_ms"] for r in rows),
    "by_book": {},
    "qualification_note": "Process SUCCEEDED is not schema/domain accepted; the Rain world process succeeded but the native business operation failed. No chapter task exists in these receipts; chapter-execution prefix is also used for semantic evaluators.",
    "unique_novel_chapter_texts_from_these_receipts": 0,
    "evaluation_criteria_counts": dict(collections.Counter(c["verdict"] for r in rows for c in r.get("evaluation_criteria", []))),
    "unknown_outcome_note": "Two timeout process receipts, one world Effect has a separate later succeeded attempt. Do not call these 28 independent business targets or equate timeout with proven remote failure."
}
for book in sorted({r["book_directory"] for r in rows}):
    subset = [r for r in rows if r["book_directory"] == book]
    stats["by_book"][book] = {
        "process_receipts": len(subset), "status_counts": dict(collections.Counter(r["status"] for r in subset)),
        "observable_input_plus_output_tokens": sum(r["observable_input_plus_output_tokens"] or 0 for r in subset),
        "process_elapsed_median_ms": statistics.median(r["elapsed_ms"] for r in subset)
    }
save("literary-receipts.json", {"schema_version": "novel-system-audit.receipt-inventory.v1", "audit_main_sha": SHA, "classification_method": "Result kind and task labels are audit-inferred from readable JSON and known Effect identities, not current Router task attestation; requested model comes from retained route configuration.", "records": rows})
save("literary-statistics.json", stats)

styles = []
for p in sorted((BASE / "novels/guofeng-xuanhuan-01/output/03_分层规划/题材与读者承诺/创作基础").glob("authority*.json")):
    doc = json.loads(p.read_text())
    asset = doc["native_asset"]
    examples = asset["content"]["candidate_payload"]["style_profile"]["original_examples"]
    operation_id = asset["content"]["execution_evidence"]["operation_id"]
    row = next(r for r in rows if r["operation_id"] == operation_id)
    raw = json.loads(Path(row["result"]["path"]).read_text())
    styles.append({
        "asset_path": str(p.relative_to(BASE)), "asset_version_id": asset["asset_version_id"],
        "native_content_hash": asset["content_hash"], "adoption_lifecycle": doc["adoption"]["lifecycle"],
        "qualification": doc["adoption"]["qualification"], "qualification_scope": "DESIGN_CANDIDATE_NOT_LITERARY_CHAPTER",
        "semantic_repair_count": doc["adoption"]["semantic_repair_count"],
        "raw_result": row["result"], "exported_examples_equal_raw_result": examples == raw["style_profile"]["original_examples"],
        "example_count": len(examples), "read_count": len(examples),
        "example_characters": sum(len(x["example"]) for x in examples),
        "example_han_characters": sum(len(re.findall(r"[\u4e00-\u9fff]", x["example"])) for x in examples),
        "examples": examples,
        "chapter_acceptance": "NONE; explicitly design examples only"
    })
save("literary-style-samples.json", {"audit_main_sha": SHA, "samples": styles, "proof_ceiling": "REAL_MODEL_MICRO_SCENES_INSIDE_DESIGN_NOT_FULL_CHAPTER_OR_LONGFORM"})

search = {"audit_main_sha": SHA, "plain_txt_inventory": [str(p.relative_to(BASE)) for p in sorted(BASE.rglob("*.txt"))], "compressed_provenance_checks": []}
for p in sorted((BASE / "architecture").rglob("*.gz")):
    if not any(s in p.name for s in ("model_call", "provider", "historical-native")):
        continue
    entry = {"path": str(p.relative_to(BASE)), "file_sha256": identity(p)["sha256"]}
    if p.name.endswith(".tar.gz"):
        with tarfile.open(p) as archive:
            members = [m for m in archive.getmembers() if m.name.endswith("model_call_log.json")]
            entry["model_log_members"] = []
            for m in members:
                data = archive.extractfile(m).read()
                text = data.decode()
                entry["model_log_members"].append({"member": m.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "scripted_provider_mentions": text.count("scripted_provider"), "real_model_call_true_mentions": text.count('"real_model_call": true')})
    else:
        text = gzip.open(p, "rt").read()
        entry.update({"uncompressed_characters": len(text), "scripted_provider_mentions": text.count("scripted_provider"), "scripted_uppercase_mentions": text.count("SCRIPTED"), "real_model_call_true_mentions": text.count('"real_model_call": true')})
    search["compressed_provenance_checks"].append(entry)
save("literary-search-scope.json", search)
print(json.dumps({"receipts": stats["process_receipts"], "unique_effects": stats["unique_external_effect_ids"], "tokens": stats["observable_input_plus_output_tokens"], "sample_examples": sum(x["example_count"] for x in styles), "sample_raw_matches": all(x["exported_examples_equal_raw_result"] for x in styles)}, ensure_ascii=False))
