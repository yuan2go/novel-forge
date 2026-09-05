from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from novel_forge.tools.implementation_tree_identity import build_git_implementation_tree_identity


METADATA = re.compile(r"<!-- proposal-lifecycle\s*(\{.*?\})\s*-->", re.DOTALL)
STATUSES = {"ACTIVE", "PARTIALLY_IMPLEMENTED", "BLOCKED", "REJECTED", "RESOLVED"}
PROPOSAL_PREFIX = "architecture/proposals/"


def _target(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("reference requires a repository path")
    relative = Path(value)
    target = root / relative
    if relative.is_absolute() or ".." in relative.parts or not target.is_file():
        raise ValueError("reference missing or outside repository: " + value)
    if not target.resolve().is_relative_to(root):
        raise ValueError("reference resolves outside repository: " + value)
    return target


def review_witness(root: Path, ref: dict[str, Any]) -> str:
    if "symbol" in ref and "json_pointer" in ref:
        raise ValueError("review witness cannot combine executable and projection selectors")
    source = _target(root, ref.get("path")).read_bytes()
    if "symbol" in ref:
        symbol = ref["symbol"]
        if not isinstance(symbol, str) or not symbol or type(ref.get("present", True)) is not bool:
            raise ValueError("symbol witness requires a name and boolean presence")
        nodes = [
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == symbol
        ]
        if bool(nodes) != ref.get("present", True):
            raise ValueError("proposal contradicts executable symbol: " + symbol)
        source = json.dumps([ast.dump(node) for node in nodes], sort_keys=True).encode()
    if "json_pointer" in ref:
        pointer = ref["json_pointer"]
        if not isinstance(pointer, str) or not pointer.startswith("/") or "expected" not in ref:
            raise ValueError("projection witness requires a JSON pointer and expected value")
        value = json.loads(source)
        try:
            for part in pointer.split("/")[1:]:
                key = part.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) else value[key]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError("proposal projection witness is missing: " + pointer) from exc
        if value != ref["expected"]:
            raise ValueError("proposal contradicts current projection: " + pointer)
        source = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(source).hexdigest()


def _check_record(root: Path, record: dict[str, Any], content: str) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != "proposal-lifecycle.v1":
        errors.append("unsupported lifecycle schema")
    status = record.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        errors.append("unsupported lifecycle status")
    if isinstance(status, str) and status in {"RESOLVED", "REJECTED"}:
        errors.append("closed proposal must be projected then deleted")
    baseline = record.get("reality_baseline")
    try:
        if not isinstance(baseline, dict):
            raise ValueError("exact reality baseline required")
        sha = baseline.get("commit_sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("exact reality baseline required")
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=root,
            capture_output=True, check=False, timeout=10,
        ).returncode:
            raise ValueError("reality baseline must be an available ancestor")
        actual = build_git_implementation_tree_identity(root, sha)
        if baseline.get("implementation_tree_sha") != actual["implementation_tree_sha"]:
            raise ValueError("reality baseline implementation identity differs")
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        errors.append(str(exc))
    for field in ("scope", "remaining_decisions", "reviewed_sources"):
        if not isinstance(record.get(field), list) or not record[field]:
            errors.append(field + " must be nonempty; retire resolved proposals")
    implemented = record.get("implemented_refs")
    superseding = record.get("superseding_refs")
    sources = record.get("reviewed_sources")
    if not all(isinstance(value, list) for value in (implemented, superseding, sources)):
        return errors + ["implemented/superseding/reviewed refs must be arrays"]
    if implemented and (status == "ACTIVE" or re.search(r"\bNOT_IMPLEMENTED\b", content)):
        errors.append("implemented work contradicts lifecycle/NOT_IMPLEMENTED")
    if status == "PARTIALLY_IMPLEMENTED" and not implemented:
        errors.append("partial implementation requires executable witnesses")
    scope = record.get("scope")
    scope_paths = set()
    if isinstance(scope, list):
        for item in scope:
            try:
                scope_paths.add(_target(root, item).relative_to(root).as_posix())
            except ValueError as exc:
                errors.append("invalid scope: " + str(exc))
    reviewed_paths = {
        ref["path"] for ref in sources
        if isinstance(ref, dict) and isinstance(ref.get("path"), str)
    }
    if scope_paths != reviewed_paths:
        errors.append("every scoped production path requires a reviewed source witness")
    for refs, reviewed in ((implemented, False), (superseding, False), (sources, True)):
        for ref in refs:
            if not isinstance(ref, dict):
                errors.append("reference must be an object")
                continue
            try:
                digest = review_witness(root, ref)
                if reviewed and ref.get("sha256") != digest:
                    errors.append("stale lifecycle review: " + str(ref.get("path")))
                if refs is implemented:
                    if ref.get("path") not in scope_paths or ref.get("present", True) is not True:
                        errors.append("implementation must have a positive scoped witness")
                    if not str(ref.get("path", "")).startswith(("src/", "config/")):
                        errors.append("implementation requires executable/schema production evidence")
            except (ValueError, SyntaxError, UnicodeDecodeError, OSError) as exc:
                errors.append(str(exc))
    decisions = record.get("remaining_decisions")
    seen = set()
    for item in decisions if isinstance(decisions, list) else []:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) and item[key].strip() for key in ("id", "decision")
        ) or not isinstance(item.get("evidence_refs"), list) or not item["evidence_refs"]:
            errors.append("remaining decision requires identity, question and evidence")
            continue
        if item["id"] in seen:
            errors.append("remaining decision identity must be unique")
        seen.add(item["id"])
        for ref in item["evidence_refs"]:
            try:
                _target(root, ref)
                if ref not in reviewed_paths:
                    errors.append("remaining decision evidence requires a scoped review witness: " + ref)
            except ValueError as exc:
                errors.append(str(exc))
    return errors


def _authority_errors(root: Path) -> list[str]:
    errors: list[str] = []
    inventory = root / "architecture/reality-evidence.json"
    if inventory.is_file():
        try:
            payload = json.loads(inventory.read_text(encoding="utf-8"))
            if PROPOSAL_PREFIX in json.dumps(payload):
                errors.append("proposal cannot supply current capability/qualification/authority")
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append("current reality cannot be read: " + str(exc))
    runtime_paths = [root / "AGENTS.md", root / "CLAUDE.md"]
    for directory in ("src/novel_forge/modules", "config", "skills", "architecture/manifests"):
        runtime_paths.extend((root / directory).rglob("*"))
    for path in runtime_paths:
        if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".yml", ".md"}:
            if PROPOSAL_PREFIX in path.read_text(encoding="utf-8"):
                errors.append("proposal cannot enter runtime instruction/authority: " + path.relative_to(root).as_posix())
    return errors


def check_proposal_lifecycle(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    errors = _authority_errors(root)
    records: list[dict[str, Any]] = []
    for path in sorted((root / "architecture/proposals").rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        content = path.read_text(encoding="utf-8")
        prefix = relative + ": "
        if "**PROPOSAL**" not in content or "**NOT_RUNTIME_AUTHORITY**" not in content:
            errors.append(prefix + "explicit proposal/authority labels required")
        matches = METADATA.findall(content)
        if len(matches) != 1:
            errors.append(prefix + "exactly one lifecycle metadata object required")
            continue
        try:
            record = json.loads(matches[0])
            if not isinstance(record, dict):
                raise ValueError("metadata must be an object")
        except ValueError as exc:
            errors.append(prefix + str(exc))
            continue
        records.append({"path": relative, "status": record.get("status")})
        errors.extend(prefix + error for error in _check_record(root, record, content))
    return {
        "schema_version": "proposal-lifecycle-report.v1",
        "status": "FAIL" if errors else "PASS",
        "proposal_count": len(records),
        "stale_resolved_proposals": sum(
            "stale lifecycle" in error or "closed proposal" in error for error in errors
        ),
        "proposals": records,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = check_proposal_lifecycle(args.repo_root)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
