import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def verify(before_path, after_path):
    before_path, after_path = Path(before_path), Path(after_path)
    before = json.load(gzip.open(before_path, "rt"))
    after = json.load(gzip.open(after_path, "rt"))
    assert before["identity"]["database"] == after["identity"]["database"] == "nf_author_first_native"
    assert before["identity"]["cluster"] == after["identity"]["cluster"]
    original_assets = {a["version"]["asset_version_id"]: a["version"] for a in before["assets"]}
    current_assets = {a["version"]["asset_version_id"]: a["version"] for a in after["assets"]}
    assert len(original_assets) == 1594
    transitions = []
    expected_compilations = {"c189bbc4-b194-487f-a864-789aeddd9b34", "6c726174-992f-4eb1-9485-1950703407d6"}
    operations = {row["operation_id"]: row for row in after["tables"]["authority_operation"]}
    for identity, original in original_assets.items():
        assert identity in current_assets, identity
        current = current_assets[identity]
        if identity not in expected_compilations:
            assert digest(original) == digest(current), identity
            continue
        assert original["lifecycle"] == "ACTIVE" and current["lifecycle"] == "SUPERSEDED"
        assert {k: v for k, v in original.items() if k != "lifecycle"} == {k: v for k, v in current.items() if k != "lifecycle"}
        old_compilation, = [r for r in after["tables"]["authority_capability_pack_compilation"] if r["compiled_asset_version_id"] == identity]
        assert old_compilation["release_sha"] == original["content"]["release_sha"] == "367194f1d2ffe4d7acf2654f88a4800a03dd9d31"
        activation, = [r for r in after["tables"]["authority_capability_pack_activation"] if r["pack_id"] == old_compilation["pack_id"]]
        deployment, = [r for r in after["tables"]["authority_capability_pack_deployment"] if r["deployment_id"] == activation["active_deployment_id"]]
        successor, = [r for r in after["tables"]["authority_capability_pack_compilation"] if r["compilation_id"] == deployment["compilation_id"]]
        assert successor["release_sha"] == "e5f1da7d1649610370500d960cad4e06083c69d9"
        assert successor["pack_version"] == old_compilation["pack_version"] and successor["manifest_hash"] == old_compilation["manifest_hash"]
        assert operations[successor["compiled_by_operation_id"]]["status"] == "SUCCEEDED"
        assert operations[activation["activated_by_operation_id"]]["status"] == "SUCCEEDED"
        assert current_assets[successor["compiled_asset_version_id"]]["lifecycle"] == "ACTIVE"
        transitions.append({"asset_version_id": identity, "change": "ACTIVE_TO_SUPERSEDED", "content_and_other_fields_unchanged": True,
            "old_compilation": old_compilation["compilation_id"], "native_successor_compilation": successor["compilation_id"],
            "compile_operation": successor["compiled_by_operation_id"], "activation_operation": activation["activated_by_operation_id"]})
    assert {r["asset_version_id"] for r in transitions} == expected_compilations
    original_effects = before["tables"]["authority_external_effect"]
    assert len(original_effects) == 59
    assert Counter(e["status"] for e in original_effects) == {"SUCCEEDED": 55, "UNKNOWN": 4}
    current_effects = {e["external_effect_id"]: e for e in after["tables"]["authority_external_effect"]}
    for effect in original_effects:
        assert digest(effect) == digest(current_effects[effect["external_effect_id"]]), effect["external_effect_id"]
    table_checks = {}
    for name in ["authority_external_effect_dispatch", "authority_external_receipt", "authority_generation_isolation"]:
        original = before["tables"][name]
        current = {digest(row) for row in after["tables"][name]}
        assert all(digest(row) in current for row in original), name
        table_checks[name] = len(original)
    old_formation, = before["tables"]["authority_story_formation_run"]
    new_formation, = after["tables"]["authority_story_formation_run"]
    assert digest(old_formation["frozen_stage_inputs"]) == digest(new_formation["frozen_stage_inputs"])
    frozen_identity = {key: value for key, value in old_formation.items()
                       if "frozen" in key and ("digest" in key or "hash" in key)}
    assert all(new_formation[key] == value for key, value in frozen_identity.items())
    old_book, = before["tables"]["authority_book_production"]
    book, = after["tables"]["authority_book_production"]
    frozen_book_fields = ["book_run_id", "project_id", "workspace_id", "book_id", "book_design_version",
                          "book_plan_version", "production_profile_version", "root_operation_id", "saga_id",
                          "stable_idempotency_key", "target_chapter_count", "input_mode", "input_snapshot_id"]
    assert all(old_book[key] == book[key] for key in frozen_book_fields)
    assert book["current_chapter"] == 5 and book["accepted_through_chapter"] == 0
    assert book["target_chapter_count"] == 100 and book["state"] == "PAUSED"
    assert before["migration_ids"] == after["migration_ids"]
    report = {
        "status": "PASS", "evidence_class": "READ_ONLY_EXACT_NATIVE_HISTORY_PRESERVATION",
        "before": before_path.name, "after": after_path.name,
        "before_file_sha256": "sha256:" + hashlib.sha256(before_path.read_bytes()).hexdigest(),
        "after_file_sha256": "sha256:" + hashlib.sha256(after_path.read_bytes()).hexdigest(),
        "database": after["identity"]["database"], "cluster": after["identity"]["cluster"],
        "old_asset_versions_compared_without_reduced_denominator": len(original_assets),
        "old_terminal_effects_compared_without_reduced_denominator": len(original_effects),
        "native_pack_lifecycle_transitions": transitions,
        "old_asset_content_identity_and_hash_unchanged": True,
        "old_effect_statuses_unchanged": dict(Counter(e["status"] for e in original_effects)),
        "immutable_table_original_rows_retained": table_checks,
        "formation_frozen_stage_inputs_hash": digest(new_formation["frozen_stage_inputs"]),
        "formation_original_frozen_identity": frozen_identity,
        "frozen_book_fields_unchanged": frozen_book_fields,
        "book_run_id": book["book_run_id"], "book_id": book["book_id"],
        "current_chapter": 5, "accepted_through_chapter": 0, "delivery_window": 100,
        "migration_ids_unchanged": True,
    }
    output = after_path.with_name("history-preservation-final-e5.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("History preserved:", len(original_assets), "assets,", len(original_effects), "terminal effects")


if __name__ == "__main__":
    verify(*sys.argv[1:])
