import argparse
import json
from pathlib import Path
import tempfile
import unicodedata

from novel_forge.modules.source_authority.corpus import validate_corpus_action
from novel_forge.modules.source_import.corpus_ingestion.contracts import ParserProfile
from novel_forge.modules.source_import.corpus_ingestion.review_replay import carry_review
from prepare import BASE, OUT, NAMES, digest, write_new, parse


def profile_v3(name):
    original = json.loads((BASE / "manifests" / (name + ".json")).read_text())["parser"]
    revised = json.loads((OUT / (name + "-parser-v3.json")).read_text())
    assert revised["constants"] == original["constants"], "Stable SourceWork metadata must remain frozen"
    if name != "study-in-scarlet":
        assert revised == original
    else:
        assert {k: v for k, v in revised.items() if k not in {"normalization", "expected_units"}} == {k: v for k, v in original.items() if k not in {"normalization", "expected_units"}}
        assert {k: v for k, v in revised["normalization"].items() if k != "boundaries"} == {k: v for k, v in original["normalization"].items() if k != "boundaries"}
        assert revised["expected_units"] == 18
    return original, revised


def verify():
    results = []
    for name in NAMES:
        original, revised = profile_v3(name)
        with tempfile.TemporaryDirectory(prefix="novel-forge-metadata-preserving-v3-") as temporary:
            before = parse(name, original, Path(temporary) / "before")
            after = parse(name, revised, Path(temporary) / "after")
            assert (before["work_id"], before["edition_id"], before["title"]) == (after["work_id"], after["edition_id"], after["title"])
            assert {(r["work_title"], r["author"]) for r in before["units"]} == {(r["work_title"], r["author"]) for r in after["units"]}
            current_ids = {f["issue_id"] for f in after["integrity"]["issues"]}
            carry_review(after, before["integrity"], parser=ParserProfile.model_validate(revised), boundary_repair=lambda _: False)
            assert {f["issue_id"] for f in after["integrity"]["issues"]} == current_ids
            assert sum(f["blocking"] for f in after["integrity"]["issues"]) == 2
            results.append({"name": name, "metadata_unchanged": True, "stable_work_title": after["title"],
                "unit_count": len(after["units"]), "chapters": after["integrity"]["chapter_count"],
                "profile_sha256": digest((OUT / (name + "-parser-v3.json")).read_bytes()),
                "only_intended_structure_changes": True, "review_still_required": True})
    write_new(OUT / "offline-validation-v3.json", {"evidence_class": "REAL_SOURCE_OFFLINE_PARSER_VALIDATION",
        "supersedes_configuration_recommendation": "v2 work_title addition rejected by unchanged SourceWork identity gate; frozen v2 profiles and failed native operation retained",
        "provider_calls": 0, "database_writes": 0, "results": results})


def review(name, inspect_path, output):
    _, profile = profile_v3(name)
    inspected = json.loads(inspect_path.read_text())
    if name == "study-in-scarlet":
        assert inspected["profile"] == ParserProfile.model_validate(profile).model_dump(mode="json"), "Run Scarlet metadata-preserving parser-v3 first and inspect its new processing"
    raw_path = BASE / "raw" / (name + ".txt")
    raw = raw_path.read_bytes()
    units = {u["unit_id"]: u for u in inspected["assessment"]["units"]}
    decisions = []
    for finding in inspected["assessment"]["issues"]:
        if not finding["blocking"]:
            continue
        assert finding["code"] == "NON_BODY_UNIT" and len(finding["evidence"]) == 1
        evidence = finding["evidence"][0]
        unit = units[evidence["unit_id"]]
        locator = evidence["locator"]
        assert unit["kind"] == "AUTHOR_NOTE" and unit["raw_file_hash"] == digest(raw)
        assert locator["path"] == raw_path.name
        start, end = locator["original_byte_offset"], locator["original_byte_end"]
        text = unicodedata.normalize("NFC", raw[start:end].decode().replace("\r\n", "\n").replace("\r", "\n"))
        assert digest(text.encode()) == evidence["content_hash"]
        if start == 0:
            assert text.startswith("The Project Gutenberg eBook") and end == profile["normalization"]["boundaries"][0]["end"]
            scope = "publisher identity, contents and dedication/preface before the first body/volume boundary"
        else:
            assert text.startswith("*** END OF THE PROJECT GUTENBERG EBOOK") and end == len(raw)
            scope = "end marker, license and trailing project metadata"
        decisions.append({"issue_id": finding["issue_id"], "resolution": "MARK_NON_BODY",
            "reason": "Operator/AI-assisted structural inspection: " + scope + "; preserve bytes/rights and exclude this exact occurrence; not independent human review or Card approval",
            "evidence_refs": [f"{raw_path.as_uri()}#{digest(raw)}:utf8-bytes={start}-{end}",
                              f"{inspect_path.as_uri()}#{digest(inspect_path.read_bytes())}"]})
    assert len(decisions) == 2
    action = {"action": "review_processing", "processing_id": inspected["processing_id"],
        "previous_id": (inspected.get("review") or {}).get("review_id"), "decisions": decisions,
        "reason": "Operator/AI-assisted exact-byte structural exclusion only; no rights transfer, independent human claim or Card approval"}
    validate_corpus_action(action)
    write_new(output, action)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--name", choices=NAMES)
    parser.add_argument("--inspect", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify:
        verify()
    else:
        if not all((args.name, args.inspect, args.output)):
            parser.error("name, inspect and output are required")
        review(args.name, args.inspect.resolve(), args.output.resolve())
