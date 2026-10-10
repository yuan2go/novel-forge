"""Verify located evidence and projection coverage; never grade Writer ownership or literature."""

from argparse import ArgumentParser
from copy import deepcopy
import json
from pathlib import Path

from novel_forge.modules.book_authority.working_prose import validate_working_projection
from novel_forge.modules.chapter_authority.author_editor import text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


def verify(root: Path, directory: Path) -> dict:
    cases = json.loads((directory / "ownership-cases.json").read_text())
    projections = json.loads((directory / "working-projections.json").read_text())
    baseline, enhanced = projections["baseline"], projections["enhanced"]
    validate_working_projection(
        enhanced, project_id=enhanced["project_id"], book_id=enhanced["book_id"]
    )
    manifest = json.loads(
        (
            root
            / "reports/audits/2026-10-10-qinglan-chapters-1-16/qinglan-forty-chapters-20261010/青岚问道-工作版本第1—16章.json"
        ).read_text()
    )
    selected = {unit["chapter"]: unit for unit in manifest["units"]}
    rows = []
    for case in cases["rows"]:
        result = {"sample_id": case["sample_id"], "semantic_ownership": "NOT_RUN"}
        quote = case["quote"]
        if case["source_class"].startswith("SYNTHETIC_"):
            result["locator"] = "NOT_APPLICABLE_SYNTHETIC"
        elif case["source_class"] == "SELECTED_UNACCEPTED_WORKING_PROSE":
            source = selected[case["chapter"]]
            assert source["asset_version_id"] == case["asset_version_id"]
            assert source["content_hash"] == case["content_hash"]
            assert source["text"][case["start"] : case["end"]] == quote
            result["locator"] = "PASS"
            for name, snapshot in (("baseline", baseline), ("enhanced", enhanced)):
                included = False
                for row in snapshot["sources"]:
                    if (
                        row["chapter"] != case["chapter"]
                        or row["asset_version_id"] != case["asset_version_id"]
                    ):
                        continue
                    if name == "baseline":
                        start = len(source["text"]) - len(row["excerpt"])
                        included = (
                            start <= case["start"]
                            and source["text"][start:] == row["excerpt"]
                        )
                    else:
                        included = any(
                            p["start"] <= case["start"]
                            and p["end"] >= case["end"]
                            and source["text"][p["start"] : p["end"]] == p["text"]
                            for p in row["passages"]
                        )
                result[name + "_coverage"] = "INCLUDED" if included else "OMITTED"
        else:
            value = json.loads((root / case["source_path"]).read_text())
            for component in case["json_pointer"].split("/")[1:]:
                value = (
                    value[int(component)]
                    if isinstance(value, list)
                    else value[component]
                )
            assert value == quote
            result["locator"] = "PASS"
        assert text_hash(quote) == case["text_hash"]
        rows.append(result)
    probes = []
    for name in (
        "foreign_book",
        "future_source",
        "selected_version_missing",
        "character_knowledge_promotion",
        "canon_promotion",
        "nested_promotion",
        "range_overlap",
    ):
        changed = deepcopy(enhanced)
        if name == "foreign_book":
            changed["book_id"] = "foreign"
        if name == "future_source":
            changed["sources"][-1]["chapter"] = enhanced["target_chapter"]
        if name == "selected_version_missing":
            changed["sources"].pop(0)
        if name == "character_knowledge_promotion":
            changed["sources"][0]["character_knowledge"] = "VERIFIED"
        if name == "canon_promotion":
            changed["structured_facts"] = [{"fact_id": "invented"}]
        if name == "nested_promotion":
            changed["sources"][0]["accepted_fact_ids"] = ["invented"]
        if name == "range_overlap":
            changed["sources"][-1]["passages"][0]["start"] = 1
        changed["snapshot_hash"] = canonical_hash(
            {k: v for k, v in changed.items() if k != "snapshot_hash"}
        )
        try:
            validate_working_projection(
                changed, project_id=enhanced["project_id"], book_id=enhanced["book_id"]
            )
        except KernelError as exc:
            probes.append({"probe": name, "result": "REJECTED", "error_code": exc.code})
        else:
            raise AssertionError("Invalid projection admitted: " + name)
    return {
        "status": "PASS",
        "evidence_state": "EXECUTABLE",
        "source_locator_errors": {"errors": 0, "denominator": 76},
        "coverage": {
            name: {
                "included": sum(r.get(name + "_coverage") == "INCLUDED" for r in rows),
                "denominator": 64,
            }
            for name in ("baseline", "enhanced")
        },
        "boundary_probes": probes,
        "writer_semantic_ownership_error_rate": "NOT_EVALUATED",
        "literary_improvement": "NOT_PROVEN",
        "human_validation": "NOT_READY",
        "rows": rows,
    }


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--evidence-directory",
        type=Path,
        default=Path("reports/audits/wp-longform-ownership-craft-evidence-01"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.repo_root.resolve(), args.evidence_directory.resolve())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "rows"},
            ensure_ascii=False,
        )
    )
