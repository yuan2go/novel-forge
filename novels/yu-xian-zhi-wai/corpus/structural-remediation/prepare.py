import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unicodedata

from novel_forge.modules.source_authority.corpus import validate_corpus_action
from novel_forge.modules.source_import.corpus_ingestion.contracts import IngestionBudget, ParserProfile
from novel_forge.modules.source_import.corpus_ingestion.parsers import compile_work_index
from novel_forge.modules.source_import.corpus_ingestion.review_replay import carry_review

BASE = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
NAMES = ("railway-children", "thirty-nine-steps", "study-in-scarlet")


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def write_new(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text() != text:
        raise ValueError(f"Immutable prepared file already differs: {path}")
    path.write_text(text)


def revised_profile(name):
    profile = deepcopy(json.loads((BASE / "manifests" / (name + ".json")).read_text())["parser"])
    profile["constants"]["work_title"] = profile["constants"]["title"]
    if name == "study-in-scarlet":
        raw = (BASE / "raw" / (name + ".txt")).read_bytes()
        original = profile["normalization"]["boundaries"]
        boundaries = []
        cuts = [(raw.index(b"\nPART I.\r\n") + 1, 1780, "PART I.", "Part I"),
                (raw.index(b"\nPART II.\r\n") + 1, 127485, "PART II.", "Part II")]
        assert cuts == [(1650, 1780, "PART I.", "Part I"), (127437, 127485, "PART II.", "Part II")]
        for boundary in original:
            row = deepcopy(boundary)
            for start, end, title, volume in cuts:
                if row["start"] < start and row["end"] == end:
                    row["end"] = start
                    boundaries.append(row)
                    boundaries.append({**row, "start": start, "end": end, "title": title,
                        "volume": volume, "kind": "VOLUME", "number": None,
                        "evidence": f"Operator/AI-assisted structural inspection of actual {name}.txt {digest(raw)} UTF-8 bytes [{start},{end}); exact PART heading and subtitle, outside chapter prose"})
                    break
            else:
                boundaries.append(row)
        profile["normalization"]["boundaries"] = boundaries
        profile["expected_units"] = len(boundaries)
    ParserProfile.model_validate(profile)
    return profile


def parse(name, profile, target):
    path = BASE / "raw" / (name + ".txt")
    raw = path.read_bytes()
    result = compile_work_index([{"path": path.name, "cache_path": str(path), "checksum": digest(raw),
        "size_bytes": len(raw)}], ParserProfile.model_validate(profile), IngestionBudget(), target)
    return json.loads(Path(result["works"][0]["cache_path"]).read_text())


def prepare_profiles():
    report = {"evidence_class": "OPERATOR_AI_ASSISTED_STRUCTURAL_INSPECTION", "provider_calls": 0,
              "persistent_database_writes": 0, "independent_human_review": False, "card_approval": False, "works": []}
    for name in NAMES:
        manifest_path = BASE / "manifests" / (name + ".json")
        raw_path = BASE / "raw" / (name + ".txt")
        original = json.loads(manifest_path.read_text())["parser"]
        inspected = json.loads((BASE / "native-imports" / (name + "-inspect.json")).read_text())
        profile = revised_profile(name)
        output = OUT / (name + "-parser-v2.json")
        write_new(output, profile)
        with tempfile.TemporaryDirectory(prefix="novel-forge-structural-parse-") as temporary:
            before = parse(name, original, Path(temporary) / "before")
            after = parse(name, profile, Path(temporary) / "after")
            assert {i["issue_id"] for i in before["integrity"]["issues"]} == {i["issue_id"] for i in inspected["assessment"]["issues"]}
            current = {i["issue_id"] for i in after["integrity"]["issues"]}
            carry_review(after, before["integrity"], parser=ParserProfile.model_validate(profile), boundary_repair=lambda _: False)
            assert {i["issue_id"] for i in after["integrity"]["issues"]} == current
            blockers = [i for i in after["integrity"]["issues"] if i["blocking"]]
            assert len(blockers) == 2 and all(i["code"] == "NON_BODY_UNIT" for i in blockers)
            chapter_rows = [u for u in after["units"] if u["unit_kind"] == "CHAPTER"]
            assert len(chapter_rows) == (10 if name == "thirty-nine-steps" else 14)
            if name == "study-in-scarlet":
                assert sum(u["unit_kind"] == "VOLUME" for u in after["units"]) == 2
                assert all("\nPART II." not in u["text"] for u in chapter_rows)
            report["works"].append({"work": name, "raw_sha256": digest(raw_path.read_bytes()),
                "original_manifest_sha256": digest(manifest_path.read_bytes()), "parser_v2_sha256": digest(output.read_bytes()),
                "original_processing_id": inspected["processing_id"], "edition_id": inspected["edition_id"],
                "original_issue_ids_reproduced": True, "original_expected_units": original["expected_units"],
                "revised_expected_units": profile["expected_units"], "main_chapters": len(chapter_rows),
                "nonbody_review_still_required": True, "coverage_after_review_without_catalogue": "UNKNOWN",
                "structural_issues_after_reprocess": [{"code": i["code"], "blocking": i["blocking"]} for i in after["integrity"]["issues"]]})
    write_new(OUT / "offline-validation.json", report)


def prepare_review(name, inspect_path, output):
    inspected = json.loads(inspect_path.read_text())
    profile = revised_profile(name)
    raw_path = BASE / "raw" / (name + ".txt")
    raw = raw_path.read_bytes()
    if name == "study-in-scarlet":
        assert inspected["profile"] == ParserProfile.model_validate(profile).model_dump(mode="json"), "First run Scarlet v2 boundary reprocessing and inspect its new processing ID"
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
            assert text.startswith("The Project Gutenberg eBook")
            assert end == profile["normalization"]["boundaries"][0]["end"]
            scope = "publisher identity, table of contents and dedication/preface before the first body/volume boundary"
        else:
            assert text.startswith("*** END OF THE PROJECT GUTENBERG EBOOK") and end == len(raw)
            scope = "end marker, Project Gutenberg license and trailing project metadata"
        decisions.append({"issue_id": finding["issue_id"], "resolution": "MARK_NON_BODY",
            "reason": "Operator/AI-assisted structural inspection: " + scope + "; retain source bytes and rights evidence, exclude this exact occurrence from analysis; not independent human review or knowledge approval",
            "evidence_refs": [f"{raw_path.as_uri()}#{digest(raw)}:utf8-bytes={start}-{end}",
                              f"{inspect_path.as_uri()}#{digest(inspect_path.read_bytes())}"]})
    assert len(decisions) == 2
    action = {"action": "review_processing", "processing_id": inspected["processing_id"],
        "previous_id": (inspected.get("review") or {}).get("review_id"), "decisions": decisions,
        "reason": "Operator/AI-assisted exact-byte structural exclusion of nonbody source units; no change to source rights and no Card approval"}
    validate_corpus_action(action)
    write_new(output, action)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-profiles", action="store_true")
    parser.add_argument("--name", choices=NAMES)
    parser.add_argument("--inspect", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.prepare_profiles:
        prepare_profiles()
    else:
        if not all((args.name, args.inspect, args.output)):
            parser.error("name, inspect and output are required for an exact review input")
        prepare_review(args.name, args.inspect.resolve(), args.output.resolve())
