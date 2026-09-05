from __future__ import annotations

import argparse
import ast
from datetime import date, timedelta
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
    build_implementation_tree_identity,
)


SCHEMA_VERSION = "novel-forge.proposal-lifecycle.v1"
LIFECYCLE = frozenset(
    {"ACTIVE", "PARTIALLY_IMPLEMENTED", "BLOCKED", "REJECTED", "RESOLVED"}
)
TERMINAL = frozenset({"REJECTED", "RESOLVED"})
METADATA = re.compile(r"<!-- proposal-lifecycle\s*\n(.*?)\n-->", re.DOTALL)


def _path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("reference must be a repository-relative path")
    path = (root / value).resolve()
    if ".." in Path(value).parts or not path.is_relative_to(root):
        raise ValueError("reference escapes repository")
    return path


def _reference(root: Path, ref: Any) -> bool:
    if not isinstance(ref, dict) or not ref.get("path"):
        raise ValueError("evidence reference requires a path")
    path = _path(root, ref["path"])
    if not path.is_file():
        return False
    if str(ref["path"]).startswith("architecture/proposals/"):
        raise ValueError("proposal cannot be implementation evidence")
    content = path.read_text(encoding="utf-8")
    if ref.get("symbol"):
        tree = ast.parse(content)
        scope = tree.body
        for component in str(ref["symbol"]).split("."):
            found = next(
                (
                    node
                    for node in scope
                    if isinstance(
                        node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                    )
                    and node.name == component
                ),
                None,
            )
            if found is None:
                return False
            scope = found.body
    if "contains" in ref and str(ref["contains"]) not in content:
        return False
    return True


def check_proposal_lifecycle(
    repo_root: str | Path, *, today: date | None = None
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    today = today or date.today()
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    identities: dict[str, dict[str, Any]] = {}
    current_records = build_implementation_tree_identity(root)["records"]
    for path in sorted((root / "architecture/proposals").rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        prefix = relative + ": "
        if path.suffix != ".md":
            errors.append(
                prefix + "only Markdown proposals with inline lifecycle are retained"
            )
            continue
        try:
            content = path.read_text(encoding="utf-8")
            matches = list(METADATA.finditer(content))
            if len(matches) != 1:
                raise ValueError("exactly one proposal-lifecycle record is required")
            metadata = json.loads(matches[0].group(1))
            if not isinstance(metadata, dict):
                raise ValueError("lifecycle metadata must be an object")
            if metadata.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("unsupported lifecycle schema")
            if not re.search(r"\*\*PROPOSAL\*\*", content) or not re.search(
                r"\*\*NOT_RUNTIME_AUTHORITY\*\*", content
            ):
                raise ValueError(
                    "PROPOSAL and NOT_RUNTIME_AUTHORITY markers are required"
                )
            status = metadata.get("status")
            if status not in LIFECYCLE:
                raise ValueError("unsupported lifecycle status")
            if status in TERMINAL:
                errors.append(
                    prefix + "terminal proposal must be projected and deleted"
                )
            reviewed = date.fromisoformat(metadata["reviewed_on"])
            due = date.fromisoformat(metadata["review_due"])
            if (
                reviewed > today
                or due < today
                or not reviewed < due <= reviewed + timedelta(days=30)
            ):
                errors.append(prefix + "stale or invalid lifecycle review window")
            baseline = metadata["reality_baseline"]
            sha = str(baseline["sha"])
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("reality baseline requires exact SHA")
            if sha not in identities:
                identities[sha] = build_git_implementation_tree_identity(root, sha)
            if (
                identities[sha]["implementation_tree_sha"]
                != baseline["implementation_tree_sha"]
            ):
                errors.append(
                    prefix + "reality baseline implementation identity mismatch"
                )
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            if ancestor.returncode:
                errors.append(
                    prefix + "reality baseline is not an ancestor of current HEAD"
                )
            scope = metadata["scope"]
            if not isinstance(scope, list) or not scope:
                raise ValueError("non-empty implementation scope is required")
            for item in scope:
                if not _path(root, item).exists() or item.split("/", 1)[0] not in {
                    "src",
                    "config",
                    "skills",
                }:
                    raise ValueError("scope must resolve to current implementation")

            def scoped(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
                return [
                    record
                    for record in records
                    if any(
                        record["path"] == item
                        or record["path"].startswith(item.rstrip("/") + "/")
                        for item in scope
                    )
                ]

            if scoped(identities[sha]["records"]) != scoped(current_records):
                errors.append(
                    prefix
                    + "stale lifecycle: implementation scope changed since review"
                )
            implemented = metadata["implemented_refs"]
            superseding = metadata["superseding_refs"]
            decisions = metadata["remaining_decisions"]
            remaining = metadata["remaining_work"]
            if not all(
                isinstance(value, list)
                for value in (implemented, superseding, decisions, remaining)
            ):
                raise ValueError(
                    "lifecycle references and remaining items must be lists"
                )
            for ref in implemented + superseding:
                if not _reference(root, ref):
                    errors.append(
                        prefix
                        + "implemented/superseding reference contradicts current code"
                    )
            if implemented and "NOT_IMPLEMENTED" in content:
                errors.append(
                    prefix + "implemented proposal still claims NOT_IMPLEMENTED"
                )
            if status == "PARTIALLY_IMPLEMENTED" and not implemented:
                errors.append(
                    prefix + "partial lifecycle requires implemented evidence"
                )
            if status == "ACTIVE" and implemented:
                errors.append(
                    prefix
                    + "implemented scope requires PARTIALLY_IMPLEMENTED lifecycle"
                )
            if not decisions and not remaining:
                errors.append(
                    prefix
                    + "no remaining decisions or work: project and delete proposal"
                )
            if status == "BLOCKED" and not decisions:
                errors.append(
                    prefix + "blocked lifecycle requires a concrete unresolved decision"
                )
            if not decisions and remaining:
                decision_free_since = date.fromisoformat(
                    metadata["decision_free_since"]
                )
                if (
                    not decision_free_since
                    <= today
                    <= decision_free_since + timedelta(days=30)
                ):
                    errors.append(
                        prefix + "decision-free proposal retained beyond closure window"
                    )
            seen: set[str] = set()
            for item in decisions + remaining:
                if (
                    not isinstance(item, dict)
                    or not item.get("id")
                    or not item.get("description")
                ):
                    raise ValueError(
                        "remaining item requires identity and concrete description"
                    )
                if item["id"] in seen:
                    raise ValueError("duplicate remaining item identity")
                seen.add(item["id"])
                refs = item.get("evidence_refs")
                if (
                    not isinstance(refs, list)
                    or not refs
                    or not all(_reference(root, ref) for ref in refs)
                ):
                    raise ValueError(
                        "remaining item requires current evidence references"
                    )
                for ref in item.get("absent_refs", []):
                    if _reference(root, ref):
                        errors.append(
                            prefix
                            + "remaining work is already implemented: "
                            + item["id"]
                        )
            records.append(
                {
                    "path": relative,
                    "status": status,
                    "remaining_decisions": len(decisions),
                    "remaining_work": len(remaining),
                    "baseline_sha": sha,
                }
            )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            SyntaxError,
            AttributeError,
        ) as exc:
            errors.append(prefix + str(exc))
    authority_paths = [
        root / "architecture/reality-evidence.json",
        root / "architecture/manifests/backend-qualification-manifest.yaml",
        root / "architecture/manifests/test-manifest.yaml",
    ]
    for directory in ("architecture/evidence", "architecture/live-evidence"):
        authority_paths.extend((root / directory).glob("*.json"))
    manifest = root / "architecture/manifests/ai-instruction-manifest.yaml"
    if manifest.is_file():
        try:
            for source in json.loads(manifest.read_text(encoding="utf-8"))["sources"]:
                for pattern in source["patterns"]:
                    authority_paths.extend(
                        path for path in root.glob(pattern) if path.is_file()
                    )
        except (ValueError, KeyError, TypeError) as exc:
            errors.append("cannot inspect instruction authority: " + str(exc))
    for path in sorted(set(authority_paths)):
        if path.is_file() and "architecture/proposals/" in path.read_text(
            encoding="utf-8"
        ):
            errors.append(
                path.relative_to(root).as_posix()
                + ": proposal reference in current/runtime Authority"
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "FAIL" if errors else "PASS",
        "proposal_count": len(records),
        "retained_terminal_count": sum(item["status"] in TERMINAL for item in records),
        "proposals": records,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    report = check_proposal_lifecycle(args.repo_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return int(report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
