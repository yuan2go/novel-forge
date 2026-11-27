from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import json
from threading import Barrier

import pytest

from scripts import creation_freeze as freeze


def source_directory(tmp_path, contents=None):
    source = tmp_path / "source"
    source.mkdir()
    for name, data in (contents or {"brief.json": b'{"brief":"original"}\n'}).items():
        (source / name).write_bytes(data)
    return source


@pytest.mark.parametrize(
    "name", ["freeze.json", "review-form.json", "allow-only.json", "creation-run.json"]
)
def test_default_inputs_reject_output_or_unknown_names_without_output(tmp_path, name):
    source = source_directory(tmp_path, {name: b"{}"})
    with pytest.raises(ValueError):
        freeze.prepare_freeze(tmp_path / "frozen", input_dir=source)
    assert not (tmp_path / "frozen").exists()
    assert (source / name).read_bytes() == b"{}"


@pytest.mark.parametrize(
    "name", ["freeze.json", "review-form.json", "allow-only.json", "FREEZE.JSON"]
)
def test_explicit_input_names_cannot_override_reserved_outputs(tmp_path, name):
    source = source_directory(tmp_path, {name: b"{}"})
    with pytest.raises(ValueError):
        freeze.prepare_freeze(
            tmp_path / "frozen",
            ["exact-card-version"],
            input_dir=source,
            input_names=[name],
        )
    assert not (tmp_path / "frozen").exists()


def test_explicit_custom_inputs_preserve_exact_rights_and_bytes(tmp_path):
    data = b'{"rights":{"evidence_refs":["operator:owned-license"]}}\n'
    source = source_directory(tmp_path, {"custom-import.json": data})
    with pytest.raises(ValueError):
        freeze.prepare_freeze(tmp_path / "not-explicit", input_dir=source)
    target = tmp_path / "frozen"
    manifest = freeze.prepare_freeze(
        target, input_dir=source, input_names=["custom-import.json"]
    )
    assert (target / "custom-import.json").read_bytes() == data
    assert manifest["input_files"] == ["custom-import.json"]
    assert not (target / "professional-import.json").exists()
    assert not (target / "allow-only.json").exists()
    assert (
        freeze.verify_freeze(target)["integrity"]
        == "MANIFEST_AND_FILES_INTERNAL_CONSISTENCY"
    )


@pytest.mark.parametrize(
    "kind",
    [
        "file_symlink",
        "source_symlink",
        "subdirectory",
        "fifo",
        "invalid_json",
        "invalid_utf8",
    ],
)
def test_nonregular_or_invalid_source_input_is_blocked(tmp_path, kind):
    source = source_directory(tmp_path)
    target = tmp_path / "frozen"
    path = source / "brief.json"
    if kind == "file_symlink":
        path.unlink()
        (tmp_path / "foreign").write_text("{}")
        path.symlink_to(tmp_path / "foreign")
    elif kind == "source_symlink":
        link = tmp_path / "source-link"
        link.symlink_to(source, target_is_directory=True)
        source = link
    elif kind == "subdirectory":
        path.unlink()
        path.mkdir()
    elif kind == "fifo":
        import os

        path.unlink()
        os.mkfifo(path)
    elif kind == "invalid_json":
        path.write_text("{broken")
    else:
        path.write_bytes(b"\xff")
    with pytest.raises(ValueError):
        freeze.prepare_freeze(target, input_dir=source)
    assert not target.exists()


@pytest.mark.parametrize("relation", ["same", "inside", "ancestor"])
def test_source_and_destination_cannot_overlap(tmp_path, relation):
    source = source_directory(tmp_path)
    destination = (
        source
        if relation == "same"
        else source / "frozen"
        if relation == "inside"
        else tmp_path
    )
    with pytest.raises(ValueError, match="overlap"):
        freeze.prepare_freeze(destination, input_dir=source)
    assert (source / "brief.json").read_bytes() == b'{"brief":"original"}\n'


def test_invalid_approval_or_existing_target_never_changes_files(tmp_path):
    source = source_directory(tmp_path)
    with pytest.raises(Exception):
        freeze.prepare_freeze(tmp_path / "invalid", [], input_dir=source)
    assert not (tmp_path / "invalid").exists()
    target = tmp_path / "frozen"
    manifest = freeze.prepare_freeze(target, input_dir=source)
    original = {path.name: path.read_bytes() for path in target.iterdir()}
    with pytest.raises(FileExistsError, match="verify_freeze"):
        freeze.prepare_freeze(target, input_dir=source)
    assert original == {path.name: path.read_bytes() for path in target.iterdir()}
    assert freeze.verify_freeze(target)["manifest"] == manifest


def test_write_failure_cleans_only_own_unpublished_stage(tmp_path, monkeypatch):
    source = source_directory(tmp_path)
    previous = tmp_path / ".frozen.freeze-history"
    previous.mkdir()
    (previous / "retained").write_text("previous evidence")
    original = freeze._write_file
    calls = []

    def fail(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "injected disk full")
        original(path, data)

    monkeypatch.setattr(freeze, "_write_file", fail)
    with pytest.raises(OSError):
        freeze.prepare_freeze(tmp_path / "frozen", input_dir=source)
    assert not (tmp_path / "frozen").exists()
    assert list(tmp_path.glob(".frozen.freeze-*")) == [previous]
    assert (previous / "retained").read_text() == "previous evidence"


def test_concurrent_publish_has_one_winner_without_overwrite(tmp_path, monkeypatch):
    source = source_directory(tmp_path)
    target = tmp_path / "frozen"
    barrier = Barrier(2)
    original = freeze._publish_directory

    def synchronize(stage, destination):
        barrier.wait(timeout=5)
        original(stage, destination)

    monkeypatch.setattr(freeze, "_publish_directory", synchronize)

    def execute():
        try:
            return freeze.prepare_freeze(target, input_dir=source)
        except FileExistsError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: execute(), range(2)))
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum(isinstance(item, FileExistsError) for item in outcomes) == 1
    assert freeze.verify_freeze(target)["status"] == "VERIFIED"
    assert not list(tmp_path.glob(".frozen.freeze-*"))


def test_directory_created_at_publish_is_not_replaced_even_when_empty(
    tmp_path, monkeypatch
):
    source = source_directory(tmp_path)
    target = tmp_path / "frozen"
    original = freeze._publish_directory
    identity = []

    def race(stage, destination):
        destination.mkdir()
        identity.append(destination.stat().st_ino)
        original(stage, destination)

    monkeypatch.setattr(freeze, "_publish_directory", race)
    with pytest.raises(FileExistsError):
        freeze.prepare_freeze(target, input_dir=source)
    assert target.stat().st_ino == identity[0] and not list(target.iterdir())


@pytest.mark.parametrize("change", ["source_bytes", "source_set", "staged_bytes"])
def test_source_change_or_stage_corruption_prevents_publication(
    tmp_path, monkeypatch, change
):
    source = source_directory(tmp_path)
    target = tmp_path / "frozen"
    original = freeze._write_file

    def mutate(path, data):
        original(path, data)
        if path.name == "freeze.json":
            if change == "source_bytes":
                (source / "brief.json").write_text('{"changed":true}')
            elif change == "source_set":
                (source / "creation.json").write_text("{}")
            else:
                (path.parent / "brief.json").write_text("{}")

    monkeypatch.setattr(freeze, "_write_file", mutate)
    with pytest.raises(ValueError):
        freeze.prepare_freeze(target, input_dir=source)
    assert not target.exists() and not list(tmp_path.glob(".frozen.freeze-*"))


def test_post_publish_failure_requires_read_only_reconciliation(tmp_path, monkeypatch):
    source = source_directory(tmp_path)
    target = tmp_path / "frozen"
    original = freeze._sync_directory

    def uncertain(path):
        if path == target.parent:
            raise OSError("injected post-publication sync result lost")
        original(path)

    monkeypatch.setattr(freeze, "_sync_directory", uncertain)
    with pytest.raises(OSError):
        freeze.prepare_freeze(target, input_dir=source)
    assert freeze.verify_freeze(target)["status"] == "VERIFIED"
    before = (target / "freeze.json").read_bytes()
    with pytest.raises(FileExistsError):
        freeze.prepare_freeze(target, input_dir=source)
    assert (target / "freeze.json").read_bytes() == before


def test_final_byte_hashes_and_default_source_use_chain_are_frozen(tmp_path):
    target = tmp_path / "frozen"
    manifest = freeze.prepare_freeze(
        target, ["approved-exact-version"], target_book_id="planned-book",
        input_dir=Path(__file__).resolve().parents[2] / "tests/fixtures/creation/knowledge-closure", synthetic_source_imports=True
    )
    assert manifest == json.loads((target / "freeze.json").read_bytes())
    assert "freeze.json" not in manifest["files"]
    for name, digest in manifest["files"].items():
        assert (
            digest
            == "sha256:" + hashlib.sha256((target / name).read_bytes()).hexdigest()
        )
    pinned = (
        "sha256:" + hashlib.sha256((target / "freeze.json").read_bytes()).hexdigest()
    )
    verified = freeze.verify_freeze(target, expected_manifest_hash=pinned)
    assert verified["integrity"] == "PINNED_MANIFEST_AND_FILES"
    assert verified["manifest_file_hash"] == pinned and verified["limitations"] == []
    assert manifest["analysis_target"]["intended_use"] == "ABSTRACT_GENERATION"
    for kind in ("professional", "fiction"):
        imported = json.loads((target / f"{kind}-import.json").read_bytes())
        assert imported["source"]["location"] == str(target / f"{kind}.jsonl")
        assert imported["purpose"] == "PRODUCTION_REFERENCE"
        assert imported["rights"]["allowed_purposes"] == ["PRODUCTION_REFERENCE"]
        assert imported["rights"]["allowed_uses"] == [
            "LOCAL_PROCESSING",
            "SOURCE_ANALYSIS",
            "ABSTRACT_GENERATION",
        ]
    assert (
        manifest["real_provider_execution"] == manifest["human_editorial"] == "NOT_RUN"
    )


@pytest.mark.parametrize(
    "change",
    ["input", "generated", "manifest", "extra", "missing", "symlink", "pinned_hash"],
)
def test_recovery_rejects_changed_bytes_or_file_set(tmp_path, change):
    target = tmp_path / "frozen"
    freeze.prepare_freeze(target, input_dir=source_directory(tmp_path))
    pinned = (
        "sha256:" + hashlib.sha256((target / "freeze.json").read_bytes()).hexdigest()
    )
    if change == "input":
        (target / "brief.json").write_text("{}")
    elif change == "generated":
        (target / "review-form.json").write_text("{}")
    elif change == "manifest":
        path = target / "freeze.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "extra":
        (target / "untracked.json").write_text("{}")
    elif change == "missing":
        (target / "brief.json").unlink()
    elif change == "symlink":
        original = target / "brief.json"
        (tmp_path / "foreign").write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(tmp_path / "foreign")
    else:
        pinned = "sha256:" + "0" * 64
    with pytest.raises((ValueError, OSError)):
        freeze.verify_freeze(target, expected_manifest_hash=pinned)


def test_legacy_verification_is_read_only_and_states_missing_integrity_evidence(
    tmp_path,
):
    target = tmp_path / "legacy"
    target.mkdir()
    payload = b'{"input":"original"}\n'
    (target / "brief.json").write_bytes(payload)
    legacy = {
        "contract_version": "knowledge-closure-freeze.v1",
        "arm_a_binding": "KNOWLEDGE_APPROVAL_AND_EXACT_VERSION_BINDING_REQUIRED",
        "files": {"brief.json": "sha256:" + hashlib.sha256(payload).hexdigest()},
    }
    raw = (json.dumps(legacy, ensure_ascii=False, indent=2) + "\n").encode()
    (target / "freeze.json").write_bytes(raw)
    result = freeze.verify_freeze(target)
    assert (
        result["status"] == "VERIFIED"
        and result["integrity"] == "LEGACY_FILE_HASHES_ONLY"
    )
    assert result["limitations"] and (target / "freeze.json").read_bytes() == raw
    assert set(path.name for path in target.iterdir()) == {"brief.json", "freeze.json"}


@pytest.mark.parametrize("shape", ["creation", "policy"])
def test_old_whitelist_cannot_be_inherited_from_input_configuration(tmp_path, shape):
    policy = {
        "mode": "ALLOW_ONLY",
        "allowed_knowledge_card_asset_version_ids": ["old-card-version"],
    }
    content = (
        {
            "profiles": {
                "production_profile": {"content": {"knowledge_access_policy": policy}}
            }
        }
        if shape == "creation"
        else policy
    )
    name = "creation.json" if shape == "creation" else "old-policy.json"
    source = source_directory(tmp_path, {name: json.dumps(content).encode()})
    explicit = None if shape == "creation" else [name]
    with pytest.raises(ValueError, match="explicit approved versions"):
        freeze.prepare_freeze(
            tmp_path / "implicit", input_dir=source, input_names=explicit
        )
    with pytest.raises(ValueError, match="explicit approved versions"):
        freeze.prepare_freeze(
            tmp_path / "wrong",
            ["different-version"],
            input_dir=source,
            input_names=explicit,
        )
    manifest = freeze.prepare_freeze(
        tmp_path / "matched",
        ["old-card-version"],
        input_dir=source,
        input_names=explicit,
    )
    assert (
        manifest["arm_a_binding"] == "EXACT_VERSIONS_BOUND_AUTHORITY_RECHECK_REQUIRED"
    )
    assert (tmp_path / "matched" / name).read_bytes() == (source / name).read_bytes()


def test_missing_current_input_never_selects_the_historical_fixture(tmp_path):
    with pytest.raises(ValueError, match="explicit input_dir"):
        freeze.prepare_freeze(tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


def test_historical_paths_resolve_only_exact_original_bytes_without_changing_input_identity():
    from pathlib import Path
    from novel_forge.modules.creative.input_paths import resolve_historical_input_path
    root = Path(__file__).resolve().parents[2]
    original = root / "config/production/chinese-pilot-brief.json"
    mapped = resolve_historical_input_path(original)
    assert mapped == root / "config/archive/creative-inputs-legacy/chinese-pilot-brief.json"
    legacy, identity = freeze.load_frozen_inputs({"brief": original})
    archived, current_identity = freeze.load_frozen_inputs({"brief": mapped})
    assert legacy == archived and identity == current_identity
    assert identity["files"]["brief"]["name"] == "chinese-pilot-brief.json"
    missing = root / "config/production/not-a-previous-input.json"
    assert resolve_historical_input_path(missing) == missing
    with pytest.raises(FileNotFoundError):
        freeze.load_frozen_inputs({"brief": missing})
