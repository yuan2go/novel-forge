from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


MANIFEST_PATH = Path("architecture/manifests/ai-instruction-manifest.yaml")
SCHEMA_VERSION = "novel-forge.ai-instruction-surface.v1"
REPORT_SCHEMA_VERSION = "novel-forge.ai-instruction-reality.v1"
REQUIRED_SOURCE_FIELDS = (
    "id",
    "patterns",
    "kind",
    "owner",
    "consumer",
    "qualification_invalidation",
)
HIDDEN_AGENT_ROOTS = (".claude", ".codex", ".cursor", ".windsurf")
ROOT_AGENT_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
EMBEDDED_ASSIGNMENT_NAMES = frozenset(
    {
        "instruction",
        "instructions",
        "prompt_template",
        "prompt_text",
        "system_instruction",
        "system_text",
        "template_text",
    }
)
WEB_EMBEDDED_INSTRUCTION = re.compile(
    r"(?:prompt_template|system_instruction|instructions?|prompt)\s*:\s*[\"'`]"
)


def _error(errors: list[str], message: str) -> None:
    if message not in errors:
        errors.append(message)


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("instruction manifest must be an object")
    return payload


def _relative_pattern(value: object) -> str:
    pattern = str(value or "").strip()
    path = Path(pattern)
    if not pattern or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"instruction pattern is not repository-relative: {pattern!r}")
    return pattern


def _files_matching(root: Path, pattern: str) -> set[Path]:
    if pattern.endswith("/**"):
        base = root / pattern.removesuffix("/**")
        return set(path for path in base.rglob("*") if path.is_file())
    return {
        path
        for path in root.glob(pattern)
        if path.is_file() and ".git" not in path.parts
    }


def _generated_target(relative: str, generated: tuple[Mapping[str, Any], ...]) -> bool:
    for item in generated:
        target = str(item.get("target") or "").rstrip("/")
        if target and (relative == target or relative.startswith(target + "/")):
            return True
    return False


def _literal_instruction(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and len(node.value.strip()) >= 20
    if isinstance(node, ast.JoinedStr):
        return any(_literal_instruction(value) for value in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_instruction(node.left) or _literal_instruction(node.right)
    return False


def _python_has_embedded_instruction(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {
                target.id for target in targets if isinstance(target, ast.Name)
            }
            if names & EMBEDDED_ASSIGNMENT_NAMES and _literal_instruction(node.value):
                return True
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in EMBEDDED_ASSIGNMENT_NAMES
                    and _literal_instruction(value)
                ):
                    return True
    return False


def _discover_instruction_candidates(
    root: Path, generated: tuple[Mapping[str, Any], ...]
) -> set[Path]:
    discovered: set[Path] = set()
    for relative in ROOT_AGENT_FILES:
        path = root / relative
        if path.is_file():
            discovered.add(path)
    skills = root / "skills"
    if skills.is_dir():
        discovered.update(path for path in skills.rglob("*") if path.is_file())
    for name in HIDDEN_AGENT_ROOTS:
        hidden_root = root / name
        if not hidden_root.is_dir():
            continue
        for path in hidden_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if not _generated_target(relative, generated):
                discovered.add(path)
    copilot = root / ".github/copilot-instructions.md"
    if copilot.is_file():
        discovered.add(copilot)
    artifact_root = root / "config/capability_packs/artifacts"
    if artifact_root.is_dir():
        discovered.update(path for path in artifact_root.rglob("*.md") if path.is_file())
    for config_root in (
        root / "config/capability_packs",
        root / "config/proof_campaigns",
    ):
        if not config_root.is_dir():
            continue
        for path in config_root.glob("*.json"):
            content = path.read_text(encoding="utf-8")
            if any(
                marker in content
                for marker in (
                    "system_instruction",
                    "prompt_template",
                    '"skills/',
                )
            ):
                discovered.add(path)
    for code_root in (root / "src", root / "scripts"):
        if code_root.is_dir():
            discovered.update(
                path
                for path in code_root.rglob("*.py")
                if path.is_file() and _python_has_embedded_instruction(path)
            )
    web_root = root / "web"
    if web_root.is_dir():
        for suffix in ("*.js", "*.mjs", "*.ts", "*.tsx"):
            for path in web_root.rglob(suffix):
                if any(part in {"node_modules", ".next"} for part in path.parts):
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if WEB_EMBEDDED_INSTRUCTION.search(content):
                    discovered.add(path)
    return discovered


def _directory_records(path: Path) -> list[tuple[str, str, bytes]]:
    if not path.is_dir():
        return []
    records: list[tuple[str, str, bytes]] = []
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            records.append(
                (
                    child.relative_to(path).as_posix(),
                    "symlink",
                    os.readlink(child).encode("utf-8"),
                )
            )
        elif child.is_file():
            records.append(
                (child.relative_to(path).as_posix(), "file", child.read_bytes())
            )
    return records


def _generated_copy_matches(source: Path, target: Path) -> bool:
    if not target.exists():
        return True
    return _directory_records(source) == _directory_records(target)


def check_instruction_surface(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    errors: list[str] = []
    manifest_path = root / MANIFEST_PATH
    manifest_bytes = b""
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = _load_object(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "FAIL",
            "instruction_identity_sha256": "",
            "source_count": 0,
            "sources": [],
            "errors": [f"cannot load instruction manifest: {exc}"],
        }
    if manifest.get("schema_version") != SCHEMA_VERSION:
        _error(errors, f"instruction manifest schema must be {SCHEMA_VERSION}")
    raw_generated = manifest.get("generated_copies")
    if not isinstance(raw_generated, list):
        _error(errors, "generated_copies must be a list")
        generated: tuple[Mapping[str, Any], ...] = ()
    else:
        generated = tuple(item for item in raw_generated if isinstance(item, Mapping))
        if len(generated) != len(raw_generated):
            _error(errors, "generated_copies entries must be objects")
    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        _error(errors, "instruction sources must be a non-empty list")
        raw_sources = []

    records_by_path: dict[str, dict[str, Any]] = {}
    source_ids: set[str] = set()
    for index, source in enumerate(raw_sources):
        context = f"sources[{index}]"
        if not isinstance(source, Mapping):
            _error(errors, f"{context} must be an object")
            continue
        missing = [field for field in REQUIRED_SOURCE_FIELDS if not source.get(field)]
        if missing:
            _error(errors, f"{context} is missing fields: {', '.join(missing)}")
            continue
        source_id = str(source["id"])
        if source_id in source_ids:
            _error(errors, f"duplicate instruction source id: {source_id}")
        source_ids.add(source_id)
        patterns = source["patterns"]
        if not isinstance(patterns, list) or not patterns:
            _error(errors, f"{context}.patterns must be a non-empty list")
            continue
        matched: set[Path] = set()
        for value in patterns:
            try:
                pattern = _relative_pattern(value)
            except ValueError as exc:
                _error(errors, str(exc))
                continue
            matched.update(_files_matching(root, pattern))
        if not matched:
            _error(errors, f"instruction source group matches no files: {source_id}")
        for path in sorted(matched):
            relative = path.relative_to(root).as_posix()
            if relative in records_by_path:
                _error(errors, f"instruction source classified more than once: {relative}")
                continue
            content = path.read_bytes()
            records_by_path[relative] = {
                "path": relative,
                "source_id": source_id,
                "kind": str(source["kind"]),
                "owner": str(source["owner"]),
                "consumer": str(source["consumer"]),
                "qualification_invalidation": str(
                    source["qualification_invalidation"]
                ),
                "size": len(content),
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            }

    discovered = _discover_instruction_candidates(root, generated)
    discovered_paths = {path.relative_to(root).as_posix() for path in discovered}
    for relative in sorted(discovered_paths - set(records_by_path)):
        _error(errors, f"unmanaged instruction source: {relative}")
    for relative in sorted(set(records_by_path) - discovered_paths):
        _error(errors, f"manifest entry is not an instruction surface: {relative}")

    for item in generated:
        source_relative = str(item.get("source") or "").strip()
        target_relative = str(item.get("target") or "").strip()
        generator_relative = str(item.get("generator") or "").strip()
        if not source_relative or not target_relative or not generator_relative:
            _error(errors, "generated instruction copy requires source, target, and generator")
            continue
        source_path = root / source_relative
        target_path = root / target_relative
        if not source_path.is_dir():
            _error(errors, f"generated instruction source is missing: {source_relative}")
        if not (root / generator_relative).is_file():
            _error(errors, f"instruction generator is missing: {generator_relative}")
        if source_path.is_dir() and not _generated_copy_matches(source_path, target_path):
            _error(errors, f"generated instruction copy drifts: {target_relative}")

    records = [records_by_path[path] for path in sorted(records_by_path)]
    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "sources": records,
    }
    encoded = json.dumps(
        identity_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "FAIL" if errors else "PASS",
        "instruction_identity_sha256": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        "source_count": len(records),
        "sources": records,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify repository-local AI instruction discovery, identity, and copies."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = check_instruction_surface(args.repo_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
