from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Sequence
import unicodedata

from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy


AXES = ("knowledge_accuracy", "natural_integration", "causality", "character", "pacing", "voice", "desire_to_continue")
DEFAULT_INPUT_NAMES = frozenset({
    "brief.json", "creation.json", "formation.json", "experiment.json", "deny-all.json",
    "professional.jsonl", "fiction.jsonl", "professional-import.json", "fiction-import.json",
})
RESERVED_OUTPUT_NAMES = frozenset({"freeze.json", "review-form.json", "allow-only.json"})
INTEGRITY_VERSION = "creation-freeze-integrity.v1"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _name(value: str) -> str:
    if (not isinstance(value, str) or not value or value in {".", ".."}
        or Path(value).name != value or "/" in value or "\\" in value
        or value != value.strip() or any(ord(char) < 32 for char in value)):
        raise ValueError("Freeze file names must be plain relative file names")
    return unicodedata.normalize("NFC", value).casefold()


def _read_regular(path: Path) -> bytes:
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode):
        raise ValueError("Freeze inputs and outputs must be regular files without symlinks")
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read()
        after = os.fstat(stream.fileno())
    final = path.lstat()
    identities = {(item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
                  for item in (initial, before, after, final)}
    if len(identities) != 1 or not stat.S_ISREG(final.st_mode):
        raise ValueError("Freeze file changed during its byte snapshot")
    return data


def _input_snapshot(source: Path, input_names: Sequence[str] | None) -> dict[str, bytes]:
    available = sorted(path.name for path in source.iterdir())
    if not available:
        raise ValueError("Freeze requires an explicit nonempty input file set")
    if input_names is None:
        requested = available
        if set(requested) - DEFAULT_INPUT_NAMES:
            raise ValueError("Unknown freeze input name; declare an explicit input_names set")
    else:
        if not isinstance(input_names, Sequence) or isinstance(input_names, (str, bytes)):
            raise ValueError("input_names must be an explicit sequence of file names")
        requested = list(input_names)
        for name in requested:
            _name(name)
        if len(set(requested)) != len(requested) or set(requested) != set(available):
            raise ValueError("Explicit freeze input names must exactly match the source directory")
    normalized = [_name(name) for name in requested]
    if len(set(normalized)) != len(normalized) or set(normalized) & RESERVED_OUTPUT_NAMES:
        raise ValueError("Freeze input names collide with each other or reserved output names")
    result = {}
    for name in sorted(requested):
        suffix = Path(name).suffix.lower()
        if suffix not in {".json", ".jsonl", ".txt"}:
            raise ValueError("Freeze inputs must be explicit JSON, JSONL or UTF-8 text files")
        data = _read_regular(source / name)
        try:
            text = data.decode("utf-8")
            if suffix == ".json":
                json.loads(text)
            elif suffix == ".jsonl":
                for line in text.splitlines():
                    if line.strip():
                        json.loads(line)
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Freeze input is not valid declared text/JSON") from exc
        result[name] = data
    return result



def _check_knowledge_policy_inputs(inputs: dict[str, bytes], approved_versions: list[str] | None) -> None:
    for name, data in inputs.items():
        if Path(name).suffix.lower() != ".json":
            continue
        value = json.loads(data)
        if not isinstance(value, dict):
            continue
        policies = [value] if "allowed_knowledge_card_asset_version_ids" in value else []
        embedded = value
        for key in ("profiles", "production_profile", "content", "knowledge_access_policy"):
            embedded = embedded.get(key) if isinstance(embedded, dict) else None
        if isinstance(embedded, dict):
            policies.append(embedded)
        for policy in policies:
            versions = policy.get("allowed_knowledge_card_asset_version_ids") or []
            if policy.get("mode") == "ALLOW_ONLY" and (
                approved_versions is None or not isinstance(versions, list) or sorted(versions) != sorted(approved_versions)
            ):
                raise ValueError("Frozen input whitelist must match the explicit approved versions argument")


def _write_file(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_directory(stage: Path, destination: Path) -> None:
    if os.name == "nt":
        os.rename(stage, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(stage), os.fsencode(destination), 4)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        arguments = (-100, os.fsencode(stage), -100, os.fsencode(destination), 1)
    else:
        raise RuntimeError("This platform lacks atomic directory publication without replacement")
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def _generated_inputs(destination: Path) -> dict[str, bytes]:
    return {f"{name}-import.json": _json_bytes({
        "source": {"kind": "LOCAL", "location": str(destination / f"{name}.jsonl")},
        "parser": {"version": "corpus-parser.v3", "format": "jsonl", "layout": "CHAPTER_ROWS",
                   "normalization": {"version": "chinese-longform.v2", "segmentation": "EXPLICIT", "min_body_chars": 1},
                   "fields": {"work_id": "book", "text": "text", "chapter_id": "chapter", "order": "order"},
                   "completeness": "COMPLETE", "expected_units": count},
        "purpose": "PRODUCTION_REFERENCE", "analyze": False,
        "rights": {"dataset_license": "CC0-1.0", "scope": "ALL_WORKS_IN_SNAPSHOT", "underlying_rights": "OWNED",
                   "allowed_purposes": ["PRODUCTION_REFERENCE"],
                   "allowed_uses": ["LOCAL_PROCESSING", "SOURCE_ANALYSIS", "ABSTRACT_GENERATION"],
                   "evidence_refs": ["repository:original-synthetic-knowledge-closure-fixture"],
                   "copyright_boundary": "Original synthetic test material; abstract learning only; no real-world professional qualification"},
    }) for name, count in (("professional", 3), ("fiction", 6))}


def prepare_freeze(destination: Path, approved_versions: list[str] | None = None, *,
                   target_book_id: str = "", input_dir: Path | None = None,
                   input_names: Sequence[str] | None = None, synthetic_source_imports: bool = False) -> dict:
    if input_dir is None:
        raise ValueError("Freeze requires an explicit input_dir; no historical sample is selected by default")
    source = Path(input_dir)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Freeze source must be a real input directory")
    source = source.resolve()
    supplied_destination = Path(destination)
    destination = supplied_destination.resolve()
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Freeze source and destination must not overlap")
    if os.path.lexists(supplied_destination) or os.path.lexists(destination):
        raise FileExistsError("Freeze destination already exists; use verify_freeze for read-only recovery")
    inputs = _input_snapshot(source, input_names)
    _check_knowledge_policy_inputs(inputs, approved_versions)
    output = dict(inputs)
    if synthetic_source_imports:
        if not {"professional.jsonl", "fiction.jsonl"} <= inputs.keys():
            raise ValueError("Synthetic imports require the explicitly selected synthetic Source fixtures")
        generated = _generated_inputs(destination)
        if output.keys() & generated.keys():
            raise ValueError("Built-in inputs collide with generated Source admission files")
        output.update(generated)
    binding = "KNOWLEDGE_APPROVAL_AND_EXACT_VERSION_BINDING_REQUIRED"
    if approved_versions is not None:
        policy = {"policy_id": "knowledge-closure-treatment", "policy_version": 1,
                  "mode": "ALLOW_ONLY", "allowed_knowledge_card_asset_version_ids": approved_versions}
        resolve_book_knowledge_access_policy(production_profile={"knowledge_access_policy": policy},
                                             project_id="configuration-check", book_id="configuration-check")
        output["allow-only.json"] = _json_bytes(policy)
        binding = "EXACT_VERSIONS_BOUND_AUTHORITY_RECHECK_REQUIRED"
    output["review-form.json"] = _json_bytes({
        "status": "NOT_REVIEWED", "reviewer_id": None, "sample_token": None,
        "scale": {"minimum": 1, "maximum": 5, "unknown": "CANNOT_JUDGE"},
        "axes": {axis: {"score": None, "chapter": None, "quote": None, "reason": None} for axis in AXES},
        "knowledge_accuracy_reference": "Use the same approved abstract mechanism reference sheet for both samples after prose-only evaluation; keep treatment identity hidden.",
    })
    frozen = {
        "contract_version": "knowledge-closure-freeze.v1", "freeze_integrity_version": INTEGRITY_VERSION,
        "status": "READY_FOR_AUTHORIZATION", "input_directory": str(source), "output_directory": str(destination),
        "input_files": sorted(inputs), "source_files": {name: _hash(data) for name, data in inputs.items()},
        "input_mode": "EXPLICIT_SYNTHETIC_FIXTURE" if synthetic_source_imports else "EXPLICIT_DIRECTORY",
        "arm_a_binding": binding, "real_provider_execution": "NOT_RUN", "human_editorial": "NOT_RUN",
        "analysis_target": {"intended_use": "ABSTRACT_GENERATION", "target_book_id": target_book_id,
                            "status": "PENDING_AUTHORITY_PREFLIGHT" if target_book_id else "TARGET_BOOK_ID_REQUIRED"},
        "source_production_qualification": {"required_scope": "EXACT_SOURCE_CAPABILITY_D0",
            "supported_accounting_bases": ["PRICED", "ACCOUNT_ENTITLEMENT"],
            "account_entitlement": "EXACT_AUTHORIZATION_ACCOUNT_AND_ENTITLEMENT_SNAPSHOT_REQUIRED",
            "card_approval": "SEPARATE_GOVERNANCE_REVIEW_AND_AUTHORITY_RECHECK_REQUIRED"},
        "model_binding": "REQUIRED_AUTHORIZED_EXACT_ROUTE_FOR_BOTH_ARMS",
        "required_authorization": ["provider/backend and exact model", "account identity and permitted purpose",
            "total calls, input/output tokens and priced cost or explicit accounting basis",
            "revision/retry allocation within the same total", "independent Books and upper plans; frozen project sublimits sum within the shared grant"],
        "files": {name: _hash(data) for name, data in sorted(output.items())},
    }
    frozen["manifest_content_hash"] = _hash(_json_bytes(frozen))
    output["freeze.json"] = _json_bytes(frozen)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.freeze-", dir=destination.parent))
    try:
        for name, data in output.items():
            _write_file(stage / name, data)
        _verify(stage, expected_manifest_hash=_hash(output["freeze.json"]), output_directory=destination)
        if _input_snapshot(source, input_names) != inputs:
            raise ValueError("Freeze source input set or bytes changed before publication")
        _sync_directory(stage)
        _publish_directory(stage, destination)
        _sync_directory(destination.parent)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return frozen


def _verify(directory: Path, *, expected_manifest_hash: str | None, output_directory: Path) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Freeze verification requires a real directory")
    raw = _read_regular(directory / "freeze.json")
    actual_hash = _hash(raw)
    if expected_manifest_hash is not None and expected_manifest_hash != actual_hash:
        raise ValueError("Frozen manifest final-byte hash differs from the pinned hash")
    try:
        frozen = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Frozen manifest is not valid JSON") from exc
    if not isinstance(frozen, dict) or frozen.get("contract_version") != "knowledge-closure-freeze.v1":
        raise ValueError("Unknown freeze manifest contract")
    files = frozen.get("files")
    if not isinstance(files, dict) or not files or "freeze.json" in files:
        raise ValueError("Freeze manifest must contain a nonempty file set without a self-reference")
    names = [_name(name) for name in files]
    if len(set(names)) != len(names):
        raise ValueError("Frozen file names collide")
    if set(path.name for path in directory.iterdir()) != set(files) | {"freeze.json"}:
        raise ValueError("Frozen final file set differs from its manifest")
    for name, digest in files.items():
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or _hash(_read_regular(directory / name)) != digest:
            raise ValueError("Frozen final file bytes differ from their manifest hashes")
    has_policy = "allow-only.json" in files
    if has_policy != (frozen.get("arm_a_binding") == "EXACT_VERSIONS_BOUND_AUTHORITY_RECHECK_REQUIRED"):
        raise ValueError("Frozen whitelist differs from its explicit version-binding state")
    integrity = frozen.get("freeze_integrity_version")
    if integrity is None:
        state = "LEGACY_FILE_HASHES_ONLY"
        limitations = ["Legacy manifest has no self-integrity hash, explicit source file set or final-path binding"]
    else:
        body = {key: value for key, value in frozen.items() if key != "manifest_content_hash"}
        if (integrity != INTEGRITY_VERSION or frozen.get("manifest_content_hash") != _hash(_json_bytes(body))
            or raw != _json_bytes(frozen) or frozen.get("output_directory") != str(output_directory.resolve())):
            raise ValueError("Frozen manifest integrity or final-path binding differs")
        sources = frozen.get("source_files")
        if (not isinstance(sources, dict) or not sources or frozen.get("input_files") != sorted(sources)
            or any(name not in files or files[name] != digest for name, digest in sources.items())):
            raise ValueError("Frozen source file set differs from final byte hashes")
        state = "PINNED_MANIFEST_AND_FILES" if expected_manifest_hash else "MANIFEST_AND_FILES_INTERNAL_CONSISTENCY"
        limitations = [] if expected_manifest_hash else ["No external manifest hash was supplied; internal consistency is not independent authenticity"]
    return {"status": "VERIFIED", "integrity": state, "manifest_file_hash": actual_hash,
            "limitations": limitations, "manifest": frozen, "files_verified": len(files)}


def verify_freeze(directory: Path, *, expected_manifest_hash: str | None = None) -> dict:
    supplied = Path(directory)
    if supplied.is_symlink():
        raise ValueError("Freeze verification cannot follow a directory symlink")
    return _verify(supplied.resolve(), expected_manifest_hash=expected_manifest_hash, output_directory=supplied.resolve())


def load_frozen_inputs(paths: dict[str, Path], *, freeze_dir: Path | None = None,
                       expected_manifest_hash: str | None = None, required: bool = False) -> tuple[dict, dict]:
    if required and (freeze_dir is None or not expected_manifest_hash):
        raise ValueError("Experiment execution requires a frozen input directory and pinned manifest file hash")
    if expected_manifest_hash and freeze_dir is None:
        raise ValueError("A pinned manifest hash requires its frozen directory")
    verified = verify_freeze(freeze_dir, expected_manifest_hash=expected_manifest_hash) if freeze_dir else None
    if required and verified["integrity"] != "PINNED_MANIFEST_AND_FILES":
        raise ValueError("Experiment execution requires a complete pinned input freeze")
    documents, files = {}, {}
    for role, supplied in paths.items():
        path = Path(supplied)
        if not path.exists() and freeze_dir is None:
            from novel_forge.modules.creative.input_paths import resolve_historical_input_path
            path = resolve_historical_input_path(path)
        if path.is_symlink():
            raise ValueError("Runner inputs cannot follow file symlinks")
        resolved = path.resolve()
        data = _read_regular(path)
        digest = _hash(data)
        if verified and (
            resolved.parent != Path(freeze_dir).resolve()
            or verified["manifest"]["files"].get(resolved.name) != digest
        ):
            raise ValueError("Runner input is outside the exact frozen file set or has changed bytes")
        try:
            documents[role] = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Runner input is not valid JSON") from exc
        files[role] = {"name": resolved.name, "content_hash": digest}
    return documents, {
        "manifest_file_hash": verified["manifest_file_hash"] if verified else None,
        "integrity": verified["integrity"] if verified else "EXPLICIT_INPUT_BYTES_ONLY",
        "files": files,
    }
