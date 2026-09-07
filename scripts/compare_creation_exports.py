"""Compare exported immutable manuscripts and evidence; never infer literary quality from scores."""

from __future__ import annotations

import argparse
from decimal import Decimal
import difflib
import json
from pathlib import Path


def chapters(directory: Path) -> dict[int, dict]:
    rows = json.loads((directory / "chapter-workspaces.json").read_text())
    result = {}
    for workspace in rows:
        accepted = workspace.get("acceptance")
        if not accepted or accepted["status"] != "COMMITTED":
            continue
        number = accepted["accepted_through_chapter"]
        targets = {
            item["content"]["target_asset_version_id"]
            for item in workspace["artifacts"]["gates"]
            if item["asset_type"] == "quality_score_report"
        }
        if len(targets) != 1:
            raise ValueError("export lacks one unambiguous final Quality candidate")
        candidate = next(
            item
            for item in workspace["artifacts"]["candidates"]
            if item["asset_version_id"] in targets
        )
        memos = workspace["artifacts"]["memo"]
        if len(memos) != 1:
            raise ValueError("export lacks one frozen Memo")
        memo = memos[0]
        if number in result:
            raise ValueError("duplicate accepted chapter in export")
        result[number] = {"candidate": candidate, "memo": memo, "workspace": workspace}
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
        "status": "RECEIPTS_ONLY_NOT_PROVIDER_INVOICE",
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
    left, right = chapters(args.baseline), chapters(args.candidate)
    args.output.mkdir(parents=True, exist_ok=False)
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
                "comparison_scope": "SAME_FROZEN_PLAN"
                if plans[0] == plans[1]
                else "FULL_CHAIN_DIFFERENT_PLANS",
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
    report = {
        "status": "EXPORTED_COMPARISON_NOT_QUALITY_JUDGMENT",
        "compared_chapters": records,
        "unmatched_baseline_chapters": sorted(set(left) - set(right)),
        "unmatched_candidate_chapters": sorted(set(right) - set(left)),
        "baseline_cost": cost_evidence(args.baseline),
        "candidate_cost": cost_evidence(args.candidate),
        "baseline_run": run_identity(args.baseline),
        "candidate_run": run_identity(args.candidate),
        "human_editorial": "WAITING_EVIDENCE",
        "model_support_is_accuracy": False,
        "longitudinal_quality": "NOT_PROVEN",
    }
    (args.output / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    return 0 if records else 2


if __name__ == "__main__":
    raise SystemExit(main())
