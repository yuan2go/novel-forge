from pathlib import Path
import hashlib
import json
import subprocess


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def verify():
    folder = Path(__file__).resolve().parent
    root = folder.parents[2]
    manifest_file = folder / "candidate-manifest.json"
    manifest = json.loads(manifest_file.read_text())
    comparisons = json.loads((folder / "comparison-evidence.json").read_text())
    assert comparisons["candidate_manifest_file_sha256"] == digest(manifest_file.read_bytes())
    checks = []
    for item in manifest["source_units"]:
        for key in ("source_file", "json_file"):
            path = item[key]
            data = (root / path).read_bytes()
            assert digest(data) == item[key + "_sha256"]
            for commit in (manifest["source_commit"], manifest["pr157_merge_commit"]):
                frozen = subprocess.check_output(["git", "show", commit + ":" + path], cwd=root)
                assert data == frozen
            if item["chapter"] <= 29:
                assert (folder / "source" / Path(path).name).read_bytes() == data
        document = json.loads((root / item["json_file"]).read_text())["units"][0]
        assert digest(document["text"].encode()) == item["text_hash"]
        checks.append("exact-source-" + str(item["chapter"]))
    candidate_bodies = {}
    reader = "# 《青岚问道》结构修订样章\n\n"
    for number, item in enumerate(manifest["candidate_units"], 1):
        data = (folder / item["file"]).read_bytes()
        assert digest(data) == item["file_sha256"]
        body = data.decode().split("\n\n", 1)[1]
        assert digest(body.encode()) == item["text_hash"]
        parent = folder / "candidate-v0" / Path(item["file"]).name
        assert digest(parent.read_bytes()) == item["parent_file_sha256"]
        assert item["native_asset_version_id"] is None
        candidate_bodies[item["local_candidate_id"]] = body
        reader += f'## 样章{number}　{item["title"]}\n\n' + body + "\n\n"
        for mapping in item["source_ranges"]:
            source = next(entry for entry in manifest["source_units"]
                          if entry["asset_version_id"] == mapping["asset_version_id"])
            assert mapping["start"] == 0 and mapping["end"] == source["unicode_body_length"]
            assert mapping["asset_hash"] == source["content_hash"]
            assert mapping["text_hash"] == source["text_hash"]
        checks.append("exact-candidate-" + str(number))
    assert (folder / "修订样章.md").read_text() == reader.rstrip() + "\n"
    assert digest((folder / "修订样章.md").read_bytes()) == manifest["readable_compilation"]["file_sha256"]
    for case in comparisons["cases"]:
        for key in ("original", "candidate", "additional_candidate"):
            if key not in case:
                continue
            location = case[key]
            if key == "original":
                data = json.loads((folder / "source" / f'chapter-{location["original_chapter"]:03}.json').read_text())
                text = data["units"][0]["text"]
            else:
                text = candidate_bodies[location["local_candidate_id"]]
            assert digest(text.encode()) == location["text_hash"]
            assert text[location["unicode_start"]:location["unicode_end"]] == location["quote"]
        checks.append("quote-location-" + case["dimension"])
    for item in manifest["code_evidence_baseline"]:
        assert digest((root / item["file"]).read_bytes()) == item["sha256"]
        assert subprocess.check_output(["git", "show", manifest["source_commit"] + ":" + item["file"]], cwd=root) == (root / item["file"]).read_bytes()
    for item in manifest["provenance"]["skills"]:
        assert digest((root / item["file"]).read_bytes()) == item["sha256"]
    checks.append("frozen-code-and-skill-evidence")
    return {"artifact_integrity": "PASS", "checks": checks,
            "literary_quality": "ASSISTANT_COMPARISON_ONLY", "human_reading": "NOT_RUN",
            "native_plan_change_writer_revision_acceptance": "NOT_RUN",
            "author_decision": "PENDING", "source_commit": manifest["source_commit"]}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
