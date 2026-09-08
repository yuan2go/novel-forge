"""Compare exported immutable manuscripts and evidence; never infer literary quality from scores."""

from __future__ import annotations

import argparse
from decimal import Decimal
import difflib
import json
from pathlib import Path


from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript


def chapter_results(directory: Path) -> tuple[dict[int, dict], list[dict]]:
    result, errors = {}, []
    try:
        rows = json.loads((directory / "chapter-workspaces.json").read_text())
    except (OSError, ValueError) as error:
        return {}, [{"directory": str(directory), "error": str(error)}]
    if not isinstance(rows, list):
        return {}, [{"directory": str(directory), "error": "workspace export must be a list"}]
    for workspace in rows:
        if not isinstance(workspace, dict):
            errors.append({"error": "workspace must be an object"})
            continue
        accepted = workspace.get("acceptance")
        if not accepted or accepted.get("status") != "COMMITTED":
            continue
        try:
            resolved = resolve_accepted_manuscript(workspace)
            if not workspace.get("run", {}).get("command", {}).get("chapter_plan_content_hash"):
                raise ValueError("frozen chapter plan hash is missing")
            number = accepted["accepted_through_chapter"]
            entry = {**resolved, "workspace": workspace}
            if number in result:
                previous = result[number]
                if previous["workspace"]["acceptance"] != accepted:
                    raise ValueError("conflicting accepted chapter in export")
                if previous["candidate"] != resolved["candidate"]:
                    raise ValueError("conflicting replayed candidate in export")
            result[number] = entry
        except (KeyError, TypeError, ValueError) as error:
            errors.append({"root_operation_id": workspace.get("root_operation_id"),
                           "acceptance_id": accepted.get("acceptance_id"),
                           "error": str(error)})
    return result, errors


def chapters(directory: Path) -> dict[int, dict]:
    result, errors = chapter_results(directory)
    if errors:
        raise ValueError(json.dumps(errors, ensure_ascii=False))
    return result


def cost_evidence(directory: Path) -> dict:
    path = directory / "cost_ledger.json"
    if not path.exists():
        return {"status": "NOT_EXPORTED"}
    effects, unavailable = {}, []
    for item in json.loads(path.read_text()):
        value = item["content"]
        key = value.get("external_effect_id")
        if not key or value.get("availability") != "AVAILABLE" or "amount" not in value:
            unavailable.append(item["asset_version_id"])
            continue
        entry = {
            field: value.get(field)
            for field in (
                "amount",
                "currency",
                "estimated",
                "provider_billed",
                "total_tokens",
            )
        }
        if key in effects and effects[key] != entry:
            raise ValueError(f"conflicting cost evidence for {key}")
        effects[key] = entry
    totals = {}
    for value in effects.values():
        currency = value["currency"]
        amount = Decimal(value["amount"])
        if not amount.is_finite() or amount < 0 or not currency:
            raise ValueError("invalid cost receipt")
        totals[currency] = totals.get(currency, Decimal(0)) + amount
    return {
        "status": "PARTIAL_RECEIPTS_NOT_TOTAL_COST" if unavailable else "RECEIPTS_ONLY_NOT_PROVIDER_INVOICE",
        "totals": {key: str(value) for key, value in totals.items()},
        "effects": effects,
        "unavailable": unavailable,
    }


def run_identity(directory: Path) -> dict:
    path = directory / "creation-run.json"
    if not path.exists():
        return {"status": "NOT_EXPORTED"}
    value = json.loads(path.read_text())
    return {
        key: value.get(key)
        for key in (
            "source_sha",
            "implementation_identity",
            "brief_input_hash",
            "invocation_elapsed_seconds",
            "formation_policy",
            "real_provider",
        )
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    left, left_errors = chapter_results(args.baseline)
    right, right_errors = chapter_results(args.candidate)
    records = []
    for number in sorted(set(left) & set(right)):
        old, new = left[number], right[number]
        plans = [
            item["workspace"]["run"]["command"]["chapter_plan_content_hash"]
            for item in (old, new)
        ]
        text_before, text_after = (
            item["candidate"]["content"]["text"] for item in (old, new)
        )
        diff = "\n".join(
            difflib.unified_diff(
                text_before.splitlines(),
                text_after.splitlines(),
                fromfile="frozen baseline",
                tofile="candidate",
                lineterm="",
            )
        )
        (args.output / f"chapter-{number}.diff").write_text(diff + "\n")
        (args.output / f"chapter-{number}-baseline.txt").write_text(text_before)
        (args.output / f"chapter-{number}-candidate.txt").write_text(text_after)
        records.append(
            {
                "chapter": number,
                "comparison_scope": "NONCOMPARABLE_UNLESS_FROZEN_INPUTS_AND_MODEL_MATCH",
                "same_plan_hash": plans[0] == plans[1],
                "accepted_input_boundaries": [item["context"]["content"].get("chapter_execution", {}).get("accepted_boundary") for item in (old, new)],
                "acceptance_ids": [item["workspace"]["acceptance"]["acceptance_id"] for item in (old, new)],
                "plan_hashes": plans,
                "candidate_refs": [
                    {
                        "asset_version_id": item["candidate"]["asset_version_id"],
                        "content_hash": item["candidate"]["content_hash"],
                    }
                    for item in (old, new)
                ],
                "memos": [item["memo"] for item in (old, new)],
                "diagnoses": [
                    item["workspace"]["artifacts"]["diagnoses"] for item in (old, new)
                ],
                "grounding": [
                    item["workspace"]["artifacts"]["facts"] for item in (old, new)
                ],
                "editorial_axes": {
                    key: "WAITING_INDEPENDENT_EVIDENCE"
                    for key in (
                        "causality",
                        "character_choice",
                        "knowledge_boundary",
                        "promise_payoff",
                        "repetition",
                        "voice",
                        "revision_benefit",
                    )
                },
            }
        )
    costs, cost_errors = {}, []
    for label, directory in (("baseline", args.baseline), ("candidate", args.candidate)):
        try:
            costs[label] = cost_evidence(directory)
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
            costs[label] = {"status": "INVALID_OR_INCOMPLETE", "error": str(error)}
            cost_errors.append({"side": label, "error": str(error)})
    errors = [{"side": "baseline", **item} for item in left_errors] + [{"side": "candidate", **item} for item in right_errors] + cost_errors
    report = {
        "status": "PARTIAL_EXPORT" if errors else "EXPORTED_COMPARISON_NOT_QUALITY_JUDGMENT",
        "errors": errors,
        "compared_chapters": records,
        "unmatched_baseline_chapters": sorted(set(left) - set(right)),
        "unmatched_candidate_chapters": sorted(set(right) - set(left)),
        "baseline_cost": costs["baseline"],
        "candidate_cost": costs["candidate"],
        "baseline_run": run_identity(args.baseline),
        "candidate_run": run_identity(args.candidate),
        "human_editorial": "WAITING_EVIDENCE",
        "model_support_is_accuracy": False,
        "longitudinal_quality": "NOT_PROVEN",
    }
    (args.output / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    return 0 if records and not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
