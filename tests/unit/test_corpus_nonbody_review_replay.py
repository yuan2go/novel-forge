"""TEST: Exact nonbody evidence survives derived ordinal changes and explicit volume splits."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from novel_forge.modules.source_import.corpus_ingestion.contracts import IngestionBudget, ParserProfile
from novel_forge.modules.source_import.corpus_ingestion.parsers import compile_work_index
from novel_forge.modules.source_import.corpus_ingestion.review_replay import carry_review, source_evidence_key


def volume_fixture(tmp_path):
    parts = ["Publisher identity\n", "PART I.\n", "CHAPTER I.\n" + "An original choice incurs a cost.\n" * 8,
             "PART II.\n", "CHAPTER I.\n" + "Another original choice fulfils the promise.\n" * 8,
             "*** END OF THE PROJECT GUTENBERG EBOOK ORIGINAL FIXTURE ***\nLicense fixture.\n"]
    path = tmp_path / "original.txt"
    raw = "".join(parts).encode()
    path.write_bytes(raw)
    offsets = [0]
    for part in parts:
        offsets.append(offsets[-1] + len(part.encode()))
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()

    def boundary(left, right, kind, title, volume="", number=None):
        return {"path": path.name, "checksum": digest, "start": offsets[left], "end": offsets[right],
                "kind": kind, "title": title, "volume": volume, "number": number,
                "evidence": "Original synthetic fixture; exact authored byte offsets"}

    original = {"version": "corpus-parser.v3", "format": "txt", "constants": {"work_id": "original", "work_title": "Original"},
                "normalization": {"version": "chinese-longform.v2", "segmentation": "EXPLICIT", "min_body_chars": 80,
                    "boundaries": [boundary(0, 2, "AUTHOR_NOTE", "Publisher identity"),
                        boundary(2, 4, "CHAPTER", "CHAPTER I.", "Part I", 1),
                        boundary(4, 5, "CHAPTER", "CHAPTER I.", "Part II", 1),
                        boundary(5, 6, "AUTHOR_NOTE", "License")]}}
    revised = deepcopy(original)
    revised["normalization"]["boundaries"] = [boundary(0, 1, "AUTHOR_NOTE", "Publisher identity"),
        boundary(1, 2, "VOLUME", "PART I.", "Part I"), boundary(2, 3, "CHAPTER", "CHAPTER I.", "Part I", 1),
        boundary(3, 4, "VOLUME", "PART II.", "Part II"), boundary(4, 5, "CHAPTER", "CHAPTER I.", "Part II", 1),
        boundary(5, 6, "AUTHOR_NOTE", "License")]
    return path, original, revised


def parsed(path, profile, root):
    raw = path.read_bytes()
    compiled = compile_work_index([{"path": path.name, "cache_path": str(path),
        "checksum": "sha256:" + hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}],
        ParserProfile.model_validate(profile), IngestionBudget(), root)
    return json.loads(Path(compiled["works"][0]["cache_path"]).read_text())


def test_physical_evidence_does_not_depend_on_derived_record_number():
    old = {"content_hash": "sha256:" + "a" * 64, "locator": {"path": "original.txt", "record": 4,
           "original_byte_offset": 100, "original_byte_end": 120}}
    revised = deepcopy(old)
    revised["locator"]["record"] = 6
    assert source_evidence_key(old) == source_evidence_key(revised)
    for field, changed in (("path", "different.txt"), ("original_byte_offset", 101), ("original_byte_end", 121)):
        other = deepcopy(revised)
        other["locator"][field] = changed
        assert source_evidence_key(old) != source_evidence_key(other)
    revised["content_hash"] = "sha256:" + "b" * 64
    assert source_evidence_key(old) != source_evidence_key(revised)
    old["locator"]["original_byte_offset"] = revised["locator"]["original_byte_offset"] = None
    revised["content_hash"] = old["content_hash"]
    assert source_evidence_key(old) != source_evidence_key(revised)


def test_nonbody_partition_replaces_old_issue_but_preserves_current_blockers(tmp_path):
    path, original, revised = volume_fixture(tmp_path)
    old = parsed(path, original, tmp_path / "old")
    new = parsed(path, revised, tmp_path / "new")
    current = deepcopy(new["integrity"]["issues"])
    carry_review(new, old["integrity"], parser=ParserProfile.model_validate(revised), boundary_repair=lambda _: False)
    assert {f["issue_id"] for f in new["integrity"]["issues"]} == {f["issue_id"] for f in current}
    assert sum(f["blocking"] for f in new["integrity"]["issues"]) == 2
    assert new["integrity"]["structure_usable"] is False
    assert new["integrity"]["coverage"] == "REVIEW_REQUIRED"


def test_nonbody_partition_cannot_hide_unresolved_issues_or_changed_source(tmp_path):
    path, original, revised = volume_fixture(tmp_path)
    old = parsed(path, original, tmp_path / "old")
    new = parsed(path, revised, tmp_path / "new")
    front = next(f for f in old["integrity"]["issues"] if f["evidence"][0]["locator"]["original_byte_offset"] == 0)
    for defect in ("omitted_issue", "changed_text", "changed_span", "only_volume"):
        broken = deepcopy(new)
        note = next(row for row in broken["units"] if row["source_locator"]["original_byte_offset"] == 0)
        if defect == "omitted_issue":
            broken["integrity"]["issues"] = [f for f in broken["integrity"]["issues"] if not f["blocking"]]
        elif defect == "changed_text":
            note["text"] += "Hidden source change"
        elif defect == "changed_span":
            note["source_locator"]["original_byte_end"] -= 1
        else:
            note["unit_kind"] = "VOLUME"
        carry_review(broken, old["integrity"], parser=ParserProfile.model_validate(revised), boundary_repair=lambda _: False)
        assert any(f["issue_id"] == front["issue_id"] and f["blocking"] for f in broken["integrity"]["issues"]), defect
        assert not broken["integrity"]["structure_usable"]


def test_exact_reviewed_license_carries_across_volume_insertions(tmp_path):
    path, original, revised = volume_fixture(tmp_path)
    old = parsed(path, original, tmp_path / "old")
    new = parsed(path, revised, tmp_path / "new")
    finding = next(f for f in old["integrity"]["issues"] if f["evidence"][0]["locator"]["original_byte_offset"] > 0)
    resolution = {"issue_id": finding["issue_id"], "resolution": "MARK_NON_BODY",
                  "reason": "Synthetic exact license inspection", "evidence": finding["evidence"]}
    old["integrity"]["resolutions"] = [resolution]
    finding.update(resolution=resolution, blocking=False)
    carry_review(new, old["integrity"], parser=ParserProfile.model_validate(revised), boundary_repair=lambda _: False)
    excluded = [row for row in new["units"] if row.get("excluded_from_analysis")]
    assert len(excluded) == 1 and excluded[0]["title"] == "License"
    assert sum(f["blocking"] for f in new["integrity"]["issues"]) == 1
    assert not new["integrity"]["structure_usable"]
