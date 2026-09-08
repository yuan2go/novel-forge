#!/usr/bin/env python3
"""Reconcile the frozen classical corpus without executing source repository code."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from novel_forge.modules.source_import.classical_corpus import (
    canonical_hash,
    load_corpus_registry,
    parse_classical_work,
    resolve_work_spec,
)


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(checkout), *args),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _selected_files(checkout: Path, globs: tuple[str, ...]) -> dict[str, bytes]:
    selected: dict[str, bytes] = {}
    checkout = checkout.resolve()
    for pattern in globs:
        for candidate in checkout.glob(pattern):
            resolved = candidate.resolve()
            if not resolved.is_relative_to(checkout):
                raise RuntimeError(f"corpus path escapes checkout: {candidate}")
            if candidate.is_symlink() or not candidate.is_file():
                raise RuntimeError(f"corpus path is not a regular file: {candidate}")
            relative = candidate.relative_to(checkout).as_posix()
            selected[relative] = candidate.read_bytes()
    if not selected:
        raise RuntimeError(f"corpus selection matched no files: {globs}")
    return dict(sorted(selected.items()))


def _verify_checkout(checkout: Path, expected_commit: str) -> dict[str, str]:
    if not checkout.is_dir():
        raise RuntimeError(f"source checkout does not exist: {checkout}")
    actual_commit = _git(checkout, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise RuntimeError(
            f"source checkout drift: expected {expected_commit}, got {actual_commit}"
        )
    tracked_status = _git(checkout, "status", "--porcelain", "--untracked-files=no")
    if tracked_status:
        raise RuntimeError(f"source checkout has tracked modifications: {checkout}")
    return {
        "commit_sha": actual_commit,
        "tree_sha": _git(checkout, "rev-parse", "HEAD^{tree}"),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def reconcile(
    *,
    novel_checkout: Path,
    poetry_checkout: Path,
    max_chunk_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = load_corpus_registry()
    checkouts = {
        "chinese-novel": novel_checkout.resolve(),
        "chinese-poetry": poetry_checkout.resolve(),
    }
    repository_evidence = {
        key: {
            **_verify_checkout(
                checkouts[key], str(repository["commit_sha"])
            ),
            "repository_url": str(repository["url"]),
            "license_name": str(repository["license_name"]),
            "license_path": str(repository["license_path"]),
            "license_content_hash": _sha256(
                (checkouts[key] / str(repository["license_path"])).read_bytes()
            ),
        }
        for key, repository in registry["repositories"].items()
    }
    full_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for configured in registry["works"]:
        work_key = str(configured["work_key"])
        spec = resolve_work_spec(work_key, registry=registry)
        files = _selected_files(checkouts[spec.repository_key], spec.include_globs)
        parsed = parse_classical_work(
            spec,
            files,
            max_chunk_bytes=max_chunk_bytes,
            normalization_version="source-normalization.v1",
        )
        selected_manifest = [
            {
                "path": path,
                "size_bytes": len(content),
                "content_hash": _sha256(content),
            }
            for path, content in files.items()
        ]
        structure = parsed.structure_manifest()
        full_row = {
            "work_key": work_key,
            "title": spec.title,
            "repository": spec.repository_key,
            "repository_commit_sha": spec.repository_commit_sha,
            "parser_profile": spec.parser_profile,
            "parser_version": parsed.parser_version,
            "selected_files": selected_manifest,
            "selected_files_manifest_hash": canonical_hash(selected_manifest),
            "structure_manifest": structure,
            "structure_manifest_hash": parsed.manifest_hash,
        }
        full_rows.append(full_row)
        diagnostics = parsed.diagnostics
        summary_rows.append(
            {
                "work_key": work_key,
                "title": spec.title,
                "repository": spec.repository_key,
                "repository_commit_sha": spec.repository_commit_sha,
                "collection_kind": spec.collection_kind,
                "parser_profile": spec.parser_profile,
                "selected_file_count": len(files),
                "selected_source_bytes": sum(len(item) for item in files.values()),
                "unit_count": int(diagnostics["unit_count"]),
                "body_unit_count": int(diagnostics["body_unit_count"]),
                "character_count": int(diagnostics["character_count"]),
                "chunk_count": len(parsed.chunks),
                "empty_unit_ordinals": diagnostics["empty_unit_ordinals"],
                "missing_title_ordinals": diagnostics["missing_title_ordinals"],
                "duplicate_title_groups": diagnostics["duplicate_title_groups"],
                "duplicate_content_groups": diagnostics[
                    "duplicate_content_groups"
                ],
                "parser_failures": diagnostics["parser_failures"],
                "excluded_field_count": len(parsed.excluded_fields),
                "structure_manifest_hash": parsed.manifest_hash,
                "selected_files_manifest_hash": canonical_hash(selected_manifest),
                "source_version_scope": "REPOSITORY_AVAILABLE_AT_FROZEN_COMMIT",
                "authoritative_edition_claim": "NOT_MADE",
            }
        )
    full = {
        "schema_version": "classical-corpus-reconciliation.v1",
        "registry_id": registry["registry_id"],
        "registry_hash": canonical_hash(registry),
        "rights_policy": registry["rights_policy"],
        "repositories": repository_evidence,
        "works": full_rows,
    }
    full["manifest_hash"] = canonical_hash(full)
    summary = {
        "schema_version": "classical-corpus-reconciliation-summary.v1",
        "registry_id": registry["registry_id"],
        "registry_hash": canonical_hash(registry),
        "full_manifest_hash": full["manifest_hash"],
        "repositories": repository_evidence,
        "totals": {
            "work_count": len(summary_rows),
            "repository_work_counts": {
                key: sum(row["repository"] == key for row in summary_rows)
                for key in sorted(repository_evidence)
            },
            "selected_file_count": sum(
                row["selected_file_count"] for row in summary_rows
            ),
            "selected_source_bytes": sum(
                row["selected_source_bytes"] for row in summary_rows
            ),
            "unit_count": sum(row["unit_count"] for row in summary_rows),
            "body_unit_count": sum(
                row["body_unit_count"] for row in summary_rows
            ),
            "character_count": sum(row["character_count"] for row in summary_rows),
            "chunk_count": sum(row["chunk_count"] for row in summary_rows),
            "empty_unit_count": sum(
                len(row["empty_unit_ordinals"]) for row in summary_rows
            ),
            "missing_title_count": sum(
                len(row["missing_title_ordinals"]) for row in summary_rows
            ),
            "duplicate_content_group_count": sum(
                len(row["duplicate_content_groups"]) for row in summary_rows
            ),
            "parser_failure_count": sum(
                len(row["parser_failures"]) for row in summary_rows
            ),
        },
        "works": summary_rows,
        "proof_scope": {
            "proves": [
                "frozen-repository-body-parsing",
                "unit-boundary-preservation",
                "source-location-and-hash-accounting",
            ],
            "does_not_establish": [
                "authoritative-edition-completeness",
                "publication-rights-for-every-modern-editorial-element",
                "model-deconstruction-completion",
                "creative-quality",
            ],
        },
    }
    return full, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--novel-checkout", type=Path, required=True)
    parser.add_argument("--poetry-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--max-chunk-bytes", type=int, default=12_000)
    args = parser.parse_args()
    full, summary = reconcile(
        novel_checkout=args.novel_checkout,
        poetry_checkout=args.poetry_checkout,
        max_chunk_bytes=args.max_chunk_bytes,
    )
    _write_json(args.output, full)
    if args.summary_output is not None:
        _write_json(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
