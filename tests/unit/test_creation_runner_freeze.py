import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.creation_freeze import load_frozen_inputs, prepare_freeze
from tests.unit.test_creation_comparison import comparison_contract


def frozen_runner_inputs(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    fixtures = Path(__file__).resolve().parents[2] / "config/production/knowledge-closure"
    for name in ("brief.json", "creation.json", "formation.json", "deny-all.json"):
        (source / name).write_bytes((fixtures / name).read_bytes())
    (source / "budget.json").write_text(json.dumps(comparison_contract()))
    target = tmp_path / "frozen"
    prepare_freeze(target, input_dir=source, input_names=sorted(path.name for path in source.iterdir()))
    digest = "sha256:" + hashlib.sha256((target / "freeze.json").read_bytes()).hexdigest()
    paths = {role: target / name for role, name in {
        "brief": "brief.json", "creation": "creation.json", "formation": "formation.json",
        "knowledge": "deny-all.json", "budget": "budget.json",
    }.items()}
    return target, digest, paths


def runner_arguments(tmp_path, target, digest, paths):
    return [
        "--brief", str(paths["brief"]), "--policy", str(paths["creation"]),
        "--formation-policy", str(paths["formation"]), "--knowledge-policy", str(paths["knowledge"]),
        "--comparison-budget", str(paths["budget"]), "--freeze-dir", str(target),
        "--freeze-manifest-hash", digest, "--project-id", "project-B", "--book-id", "book-B",
        "--workspace-id", "workspace-B", "--root", str(tmp_path / "runtime"),
        "--run-key", "frozen-control", "--evidence-dir", str(tmp_path / "evidence"),
    ]


def test_runner_preview_reads_exact_pinned_files_without_native_calls(tmp_path, monkeypatch):
    from scripts import run_creation_synthesis as runner
    target, digest, paths = frozen_runner_inputs(tmp_path)
    composition = Mock(side_effect=AssertionError("configuration preview must not compose Provider execution"))
    monkeypatch.setattr(runner, "build_production_execution_composition", composition)
    assert runner.main(runner_arguments(tmp_path, target, digest, paths)) == 0
    composition.assert_not_called()
    report = json.loads((tmp_path / "evidence/creation-run.json").read_text())
    assert report["status"] == "CONFIGURATION_VALIDATED_NO_PROVIDER_CALL"
    assert report["input_snapshot"]["manifest_file_hash"] == digest
    assert report["input_snapshot"]["integrity"] == "PINNED_MANIFEST_AND_FILES"
    assert set(report["input_snapshot"]["files"]) == set(paths)
    assert "budget_usage" not in report


def test_semantically_equal_changed_bytes_block_runner_before_execution(tmp_path, monkeypatch):
    from scripts import run_creation_synthesis as runner
    target, digest, paths = frozen_runner_inputs(tmp_path)
    original = json.loads(paths["brief"].read_bytes())
    paths["brief"].write_bytes(paths["brief"].read_bytes() + b" \n")
    assert json.loads(paths["brief"].read_bytes()) == original
    provider = Mock(side_effect=AssertionError("must not reach Provider"))
    monkeypatch.setattr(runner, "build_production_execution_composition", provider)
    with pytest.raises(ValueError, match="bytes"):
        runner.main(runner_arguments(tmp_path, target, digest, paths) + ["--execute"])
    provider.assert_not_called()
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize("fault", ["outside", "missing_pin", "wrong_pin", "symlink"])
def test_inputs_cannot_escape_or_substitute_the_frozen_byte_snapshot(tmp_path, fault):
    target, digest, paths = frozen_runner_inputs(tmp_path)
    if fault == "outside":
        foreign = tmp_path / "identical-brief.json"
        foreign.write_bytes(paths["brief"].read_bytes())
        paths["brief"] = foreign
    elif fault == "missing_pin":
        digest = None
    elif fault == "wrong_pin":
        digest = "sha256:" + "0" * 64
    else:
        alias = tmp_path / "brief-link.json"
        alias.symlink_to(paths["brief"])
        paths["brief"] = alias
    with pytest.raises(ValueError):
        load_frozen_inputs(paths, freeze_dir=target, expected_manifest_hash=digest, required=True)


def test_input_json_comes_from_the_same_bytes_whose_hash_was_checked(tmp_path, monkeypatch):
    from scripts import creation_freeze as freeze
    target, digest, paths = frozen_runner_inputs(tmp_path)
    original = freeze._read_regular
    calls = 0
    def replace_after_read(path):
        nonlocal calls
        data = original(path)
        if Path(path) == paths["brief"]:
            calls += 1
            if calls == 2:
                Path(path).write_text('{"mutated_after_snapshot":true}')
        return data
    monkeypatch.setattr(freeze, "_read_regular", replace_after_read)
    values, snapshot = load_frozen_inputs(paths, freeze_dir=target, expected_manifest_hash=digest, required=True)
    assert "mutated_after_snapshot" not in values["brief"]
    assert snapshot["files"]["brief"]["content_hash"] != "sha256:" + hashlib.sha256(paths["brief"].read_bytes()).hexdigest()


def test_native_verify_cli_preserves_existing_freeze_and_reports_external_pin(tmp_path, capsys):
    from scripts.prepare_knowledge_closure import main
    target, digest, _ = frozen_runner_inputs(tmp_path)
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    assert main(["verify", str(target), "--expected-manifest-hash", digest]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["integrity"] == "PINNED_MANIFEST_AND_FILES"
    assert {path.name: path.read_bytes() for path in target.iterdir()} == before
