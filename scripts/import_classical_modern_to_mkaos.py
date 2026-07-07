#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from novel_forge.modules import mkaos_model_extraction
from novel_forge.core.ids import make_id, slugify, utc_now
from novel_forge.modules.mkaos_ingestion import (
    create_repository,
    import_repository,
    list_repositories,
    scan_repository,
)
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage


def main() -> int:
    args = _parse_args()
    repo_path = Path(args.repo_path).expanduser().resolve()
    if not repo_path.exists():
        raise FileNotFoundError(repo_path)
    storage = LocalStorage(Path(args.storage_root).expanduser().resolve())
    storage.ensure_layout()
    _configure_codex(args)
    run_paths = _run_paths(storage.root, args)
    provider_health = _check_provider_health(args) if args.run_provider else {"available": False, "status": "not_requested", "reason": "provider not requested"}

    max_books = args.max_books if args.confirm_full_run else (args.max_books or 3)
    max_files = args.max_files if args.confirm_full_run else (args.max_files or 5)
    max_extraction_jobs = _provider_call_limit(args)

    repository = _find_or_create_repository(storage, repo_path, args)
    scanned = scan_repository(storage, repository["id"], {"rescan": True, "actor": args.actor})
    if args.scan_only or args.dry_run:
        selected_files = _selected_manifest_files(scanned.get("manifest", {}).get("content", {}), args, max_books=max_books, max_files=max_files)
        imported = {
            "report": {
                "content": {
                    "book_count": len({str(row.get("book_name") or "") for row in selected_files if row.get("book_name")}),
                    "chapter_count": len([row for row in selected_files if str(row.get("file_type") or "") != "parallel_text"]),
                    "parallel_pair_count": len([row for row in selected_files if str(row.get("file_type") or "") == "parallel_text"]),
                    "scan_only": bool(args.scan_only),
                    "dry_run": bool(args.dry_run),
                    "planned_file_count": len(selected_files),
                    "import_window": {
                        "max_books": max_books,
                        "max_files": max_files,
                        "include_parallel_pairs": args.include_parallel_pairs,
                        "processed_file_count": 0,
                        "skipped_file_count": max(0, _manifest_file_count(scanned.get("manifest", {})) - len(selected_files)),
                        "resume_recommended": True,
                    },
                }
            },
            "chapters": [],
        }
        extraction_runs: list[dict[str, Any]] = []
        _append_ledger(
            run_paths["ledger"],
            {
                "status": "dry_run" if args.dry_run else "scan_only",
                "provider_called": False,
                "planned_file_count": len(selected_files),
                "provider_health": provider_health,
            },
        )
        _write_checkpoint(
            run_paths["checkpoint"],
            _checkpoint_payload(args, repository, scanned, imported, extraction_runs, provider_health, run_paths),
        )
        report = _build_report(
            args=args,
            repo_path=repo_path,
            repository=repository,
            scanned=scanned,
            imported=imported,
            extraction_runs=extraction_runs,
            max_books=max_books,
            max_files=max_files,
            max_extraction_jobs=max_extraction_jobs,
            run_paths=run_paths,
            provider_health=provider_health,
        )
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = _render_report(report)
        report_path.write_text(rendered, encoding="utf-8")
        run_paths["slow_report"].write_text(rendered, encoding="utf-8")
        print(json.dumps({"ok": True, "scan_only": bool(args.scan_only), "dry_run": bool(args.dry_run), "report_path": str(report_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))
        return 0
    import_payload = {
        "actor": args.actor,
        "max_books": max_books,
        "max_files": max_files,
        "book_names": args.book_names,
        "include_parallel_pairs": args.include_parallel_pairs,
        "trace_id": args.trace_id,
        "skip_existing": bool(args.skip_existing),
    }
    imported = _import_repository_index(storage, repository, scanned["manifest"], args, import_payload) if args.index_only else import_repository(storage, repository["id"], import_payload)
    extraction_runs = _run_extractions(
        storage,
        imported["chapters"],
        args,
        max_extraction_jobs=max_extraction_jobs,
        run_paths=run_paths,
        provider_health=provider_health,
    )
    _write_checkpoint(
        run_paths["checkpoint"],
        _checkpoint_payload(args, repository, scanned, imported, extraction_runs, provider_health, run_paths),
    )
    report = _build_report(
        args=args,
        repo_path=repo_path,
        repository=repository,
        scanned=scanned,
        imported=imported,
        extraction_runs=extraction_runs,
        max_books=max_books,
        max_files=max_files,
        max_extraction_jobs=max_extraction_jobs,
        run_paths=run_paths,
        provider_health=provider_health,
    )
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _render_report(report)
    report_path.write_text(rendered, encoding="utf-8")
    run_paths["slow_report"].write_text(rendered, encoding="utf-8")
    print(json.dumps({"ok": True, "report_path": str(report_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import NiuTrans/Classical-Modern into MKAOS and optionally run Codex model extraction.")
    parser.add_argument("--repo-path", default=".local/external/Classical-Modern")
    parser.add_argument("--storage-root", default=os.environ.get("NOVEL_FORGE_ROOT", ".local/workspace"))
    parser.add_argument("--project-id", default="classical-modern-mkaos")
    parser.add_argument("--repository-name", default="NiuTrans Classical-Modern")
    parser.add_argument("--source-uri", default="https://github.com/NiuTrans/Classical-Modern")
    parser.add_argument("--actor", default="codex-operator")
    parser.add_argument("--trace-id", default="classical-modern-mkaos-import")
    parser.add_argument("--book-names", nargs="*", default=[])
    parser.add_argument("--max-books", type=int)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--max-extraction-jobs", type=int)
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--index-only", action="store_true", help="Write full book/chapter evidence index without copying raw text into source_document chunks.")
    parser.add_argument("--dry-run", action="store_true", help="Plan catalog/import/provider work without writing chapter evidence or calling provider.")
    parser.add_argument("--resume", action="store_true", help="Read checkpoint/ledger and continue from previously unprocessed content hashes.")
    parser.add_argument("--checkpoint-path", default="", help="Path for resumable import/provider checkpoint JSON.")
    parser.add_argument("--ledger-path", default="", help="Path for provider extraction JSONL ledger.")
    parser.add_argument("--provider-batch-size", type=int, default=1, help="Number of provider calls between sleeps; default 1.")
    parser.add_argument("--provider-max-calls", type=int, help="Maximum provider calls for this invocation. Capped at 50 per safety policy.")
    parser.add_argument("--provider-source-chars", type=int, default=3600, help="Maximum source characters sent to provider for each chapter; raw excerpt is not persisted.")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="Sleep between provider batches.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip content hashes already present in the checkpoint or ledger.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop the batch on first provider extraction failure.")
    parser.add_argument("--limit-provider-tokens", type=int, help="Compatibility guard: treated as an additional provider call limit because the local Codex adapter does not expose hard token pre-limits.")
    parser.add_argument("--include-parallel-pairs", action="store_true")
    parser.add_argument("--confirm-full-run", action="store_true")
    parser.add_argument("--run-provider", action="store_true")
    parser.add_argument("--provider", default="claude-code")
    parser.add_argument("--provider-mode", default="model")
    parser.add_argument("--provider-approval-ref", default="operator-approved-classical-modern-mkaos-import")
    parser.add_argument("--codex-command", default=os.environ.get("NOVEL_FORGE_CLAUDE_CODE_COMMAND", "codex"))
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", "~/.codex-claude"))
    parser.add_argument("--codex-model", default=os.environ.get("NOVEL_FORGE_CLAUDE_CODE_MODEL", ""))
    parser.add_argument("--codex-timeout-seconds", type=int, default=300)
    parser.add_argument("--approve-auto-candidates", action="store_true", help="Deprecated compatibility flag; ignored because Classical-Modern extraction must remain reviewable candidates.")
    parser.add_argument("--report-path", default="docs/reports/classical-modern-mkaos-import-report.md")
    return parser.parse_args()


def _configure_codex(args: argparse.Namespace) -> None:
    args.codex_command = _resolve_codex_command(args.codex_command, args.codex_home)
    os.environ.setdefault("CODEX_HOME", str(Path(args.codex_home).expanduser()))
    os.environ["NOVEL_FORGE_CLAUDE_CODE_CODEX_HOME"] = args.codex_home
    os.environ["NOVEL_FORGE_CLAUDE_CODE_COMMAND"] = args.codex_command
    os.environ["NOVEL_FORGE_CLAUDE_CODE_CLI_ENABLED"] = "1"
    os.environ["NOVEL_FORGE_CLAUDE_CODE_TIMEOUT_SECONDS"] = str(args.codex_timeout_seconds)
    os.environ["NOVEL_FORGE_CLAUDE_CODE_WORKDIR"] = str(ROOT)
    if args.codex_model:
        os.environ["NOVEL_FORGE_CLAUDE_CODE_MODEL"] = args.codex_model
    if args.run_provider:
        os.environ["NOVEL_FORGE_ANALYZE_PROVIDER"] = args.provider


def _resolve_codex_command(command: str, codex_home: str) -> str:
    if str(command).strip() != "codex":
        return command
    package_root = os.environ.get("CODEX_MANAGED_PACKAGE_ROOT", "").strip() or _codex_package_root_from_shell_snapshots(codex_home)
    if package_root:
        script = Path(package_root).expanduser() / "bin" / "codex.js"
        if script.exists():
            return f"node {script}"
    return command


def _codex_package_root_from_shell_snapshots(codex_home: str) -> str:
    snapshots = Path(codex_home).expanduser() / "shell_snapshots"
    if not snapshots.exists():
        return ""
    newest = sorted(snapshots.glob("*.sh"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in newest[:10]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in reversed(text.splitlines()):
            line = line.strip()
            prefix = "export CODEX_MANAGED_PACKAGE_ROOT="
            if line.startswith(prefix):
                value = line[len(prefix) :].strip().strip('"').strip("'")
                if value:
                    return value
    return ""


def _run_paths(storage_root: Path, args: argparse.Namespace) -> dict[str, Path]:
    base = storage_root / args.project_id
    checkpoint = Path(args.checkpoint_path).expanduser() if args.checkpoint_path else base / "checkpoints" / "import-checkpoint.json"
    ledger = Path(args.ledger_path).expanduser() if args.ledger_path else base / "ledgers" / "provider-extraction-ledger.jsonl"
    slow_report = base / "reports" / "provider-slow-run-summary.md"
    for path in [checkpoint, ledger, slow_report]:
        path.parent.mkdir(parents=True, exist_ok=True)
    return {"checkpoint": checkpoint.resolve(), "ledger": ledger.resolve(), "slow_report": slow_report.resolve()}


def _check_provider_health(args: argparse.Namespace) -> dict[str, Any]:
    if str(args.provider).strip().lower() in {"mock", "local", "offline"}:
        return {"available": False, "status": "mock_denied", "reason": "mock/local/offline provider is not allowed for Classical-Modern slow-run"}
    command = [*shlex.split(args.codex_command), "--version"]
    env = dict(os.environ)
    env["CODEX_HOME"] = str(Path(args.codex_home).expanduser())
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, env=env, timeout=15)
    except Exception as exc:
        return {"available": False, "status": "unavailable", "reason": str(exc), "command": " ".join(command)}
    output = (completed.stdout or completed.stderr or "").strip()
    return {
        "available": completed.returncode == 0,
        "status": "available" if completed.returncode == 0 else "unavailable",
        "reason": output[:1000],
        "command": " ".join(command),
        "codex_home": args.codex_home,
    }


def _provider_call_limit(args: argparse.Namespace) -> int:
    candidates = [
        args.provider_max_calls,
        args.limit_provider_tokens,
        args.max_extraction_jobs,
    ]
    raw = next((value for value in candidates if value is not None), 5 if args.run_provider else 0)
    try:
        limit = max(0, int(raw))
    except (TypeError, ValueError):
        limit = 0
    return min(limit, 50)


def _find_or_create_repository(storage: LocalStorage, repo_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    for row in list_repositories(storage, project_id=args.project_id, limit=1000):
        content = row.get("content", {}) if isinstance(row.get("content"), dict) else {}
        if str(content.get("local_path") or "") == str(repo_path) or str(content.get("source_uri") or "") == args.source_uri:
            return row.get("asset", row)
    created = create_repository(
        storage,
        {
            "project_id": args.project_id,
            "name": args.repository_name,
            "source_uri": args.source_uri,
            "local_path": str(repo_path),
            "source_type": "classical_modern_parallel_corpus",
            "rights": {
                "license": "MIT repository license; per-book upstream source recorded in 数据来源.txt when present",
                "authorization": "licensed",
                "copyright_boundary": "evidence_only",
                "allow_downstream_generation": False,
                "generation_rag_allowed": False,
                "raw_text_allowed_for_prose": False,
                "risk_level": "medium",
            },
            "actor": args.actor,
        },
    )
    return created["asset"]


def _import_repository_index(
    storage: LocalStorage,
    repository: dict[str, Any],
    manifest_asset: dict[str, Any],
    args: argparse.Namespace,
    payload: dict[str, Any],
) -> dict[str, Any]:
    manifest = manifest_asset.get("content", {}) if isinstance(manifest_asset.get("content"), dict) else {}
    files = _selected_manifest_files(manifest, args, max_books=payload.get("max_books"), max_files=payload.get("max_files"))
    if args.skip_existing or args.resume:
        existing_chapter_keys = _existing_chapter_keys(storage, args.project_id)
    else:
        existing_chapter_keys = set()
    repo_id = str(repository.get("id") or "")
    repo_root = Path(str(manifest.get("root_path") or args.repo_path)).expanduser().resolve()
    by_book: dict[str, list[dict[str, Any]]] = {}
    for row in files:
        if str(row.get("file_type") or "") == "parallel_text":
            continue
        by_book.setdefault(str(row.get("book_name") or "Untitled Book"), []).append(row)

    books: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    skipped_existing = 0
    failures: list[dict[str, Any]] = []
    for book_name, rows in by_book.items():
        book_id = _stable_id("book_source", repo_id, book_name)
        book = _index_book_asset(args, repo_id, book_id, book_name, rows, repository)
        try:
            storage.write_asset("raw", book)
            books.append(book.to_dict())
        except Exception as exc:
            failures.append({"book": book_name, "error": str(exc), "retryable": True})
            continue
        for row in rows:
            content_hash = str(row.get("sha256") or "")
            chapter_key = _index_chapter_key(row)
            if chapter_key and chapter_key in existing_chapter_keys:
                skipped_existing += 1
                existing_chapter = _existing_index_chapter_asset(storage, repo_id, row)
                if existing_chapter:
                    chapters.append(existing_chapter)
                continue
            try:
                chapter = _index_chapter_asset(args, repo_root, repo_id, book_id, book_name, row)
                storage.write_asset("raw", chapter)
                chapters.append(chapter.to_dict())
                if chapter_key:
                    existing_chapter_keys.add(chapter_key)
            except Exception as exc:
                failures.append({"path": str(row.get("path") or ""), "error": str(exc), "retryable": True})

    total_files = len(manifest.get("files", []) if isinstance(manifest.get("files"), list) else [])
    skipped_files = max(0, total_files - len(files)) + skipped_existing
    report_content = {
        "repository_id": repo_id,
        "source_count": total_files,
        "book_count": len(books),
        "chapter_count": len(chapters),
        "parallel_pair_count": 0,
        "duplicate_count": skipped_existing,
        "failure_count": len(failures),
        "extraction_coverage": round(len(chapters) / max(1, total_files), 4),
        "duplicate_rate": round(skipped_existing / max(1, len(chapters) + skipped_existing), 4),
        "cleaning_warnings": [],
        "copyright_boundary": "evidence_only_index_no_raw_text_copy",
        "recommended_next_actions": ["run_provider_slow_extraction", "review_candidates_before_approval"],
        "failures": failures,
        "import_window": {
            "index_only": True,
            "max_books": payload.get("max_books"),
            "max_files": payload.get("max_files"),
            "include_parallel_pairs": False,
            "selected_book_names": sorted(str(item) for item in args.book_names if str(item).strip()),
            "processed_file_count": len(chapters),
            "skipped_file_count": skipped_files,
            "skipped_existing_count": skipped_existing,
            "resume_recommended": skipped_files > 0,
        },
        "source_isolation": {
            "raw_text_copied": False,
            "source_document_chunks_created": False,
            "generation_rag_allowed": False,
            "evidence_path_only": True,
        },
        "project_id": args.project_id,
        "created_at": _now(),
    }
    report = BaseAsset(
        id=make_id("import_quality_report", f"{repo_id} index {utc_now()}"),
        type="import_quality_report",
        title=f"{repository.get('title') or repo_id} index import quality",
        source="classical-modern-index",
        tags=["mkaos", "ingestion", "quality", "classical-modern", "index-only"],
        content=report_content,
        metadata={"project_id": args.project_id, "mkaos": True, "use_in_generation_rag": False},
        references=[],
    )
    _validate_asset(report)
    report_path = storage.write_asset("runs", report)
    return {
        "repository": repository,
        "job": {"content": {"status": "succeeded" if not failures else "completed_with_failures", "operation": "repository_index_import"}},
        "report": storage.read_json(report_path),
        "books": books,
        "chapters": chapters,
        "parallel_pairs": [],
    }


def _index_book_asset(args: argparse.Namespace, repo_id: str, book_id: str, book_name: str, rows: list[dict[str, Any]], repository: dict[str, Any]) -> BaseAsset:
    rights = repository.get("content", {}).get("rights", {}) if isinstance(repository.get("content"), dict) else {}
    return BaseAsset(
        id=book_id,
        type="book_source",
        title=book_name,
        source="classical-modern-index",
        tags=["mkaos", "book-source", "classical-modern", "evidence-only"],
        content={
            "book_id": book_id,
            "project_id": args.project_id,
            "repository_id": repo_id,
            "book_name": book_name,
            "source_type": "classical_text",
            "discipline_tags": ["classical_chinese", "history", "craft_source"],
            "chapter_count": len(rows),
            "has_parallel_text": False,
            "rights": rights,
            "risk_level": rights.get("risk_level", "medium") if isinstance(rights, dict) else "medium",
            "source_policy": _source_policy(),
            "index_only": True,
        },
        metadata=_index_metadata(args, rights if isinstance(rights, dict) else {}),
        references=[],
    )


def _index_chapter_asset(args: argparse.Namespace, repo_root: Path, repo_id: str, book_id: str, book_name: str, row: dict[str, Any]) -> BaseAsset:
    rel_path = str(row.get("path") or "")
    file_path = repo_root / rel_path
    line_count = _line_count(file_path)
    content_hash = str(row.get("sha256") or "")
    chapter_title = " / ".join(row.get("chapter_path") or []) or rel_path
    chapter_id = _stable_id("book_chapter_source", repo_id, rel_path, content_hash)
    return BaseAsset(
        id=chapter_id,
        type="book_chapter_source",
        title=chapter_title,
        source="classical-modern-index",
        tags=["mkaos", "book-chapter-source", "classical-modern", "evidence-only", "index-only"],
        content={
            "chapter_id": chapter_id,
            "project_id": args.project_id,
            "book_id": book_id,
            "book_title": book_name,
            "title": chapter_title,
            "chapter_path": row.get("chapter_path") or [],
            "source_file": rel_path,
            "source_path": rel_path,
            "source_uri": str(file_path),
            "content_hash": content_hash,
            "size_bytes": int(row.get("size_bytes") or 0),
            "line_range": {"start": 1, "end": line_count},
            "text_length": 0,
            "source_document_id": "",
            "source_chunk_ids": [],
            "parallel_pair_ids": [],
            "extraction_status": "pending",
            "abstract_preview": chapter_title,
            "toc": [],
            "section_manifest": [],
            "page_manifest": [],
            "parser_metadata": {"parser_adapter": "index_only", "parser_quality": "path_hash_line_range"},
            "parser_warnings": [],
            "parser_quality": "index_only",
            "source_policy": _source_policy(),
            "source_isolation": {
                "raw_text_included": False,
                "clean_text_included": False,
                "section_text_included": False,
                "page_text_included": False,
                "evidence_layer_only_refs": True,
                "source_path_only": True,
            },
            "index_only": True,
        },
        metadata=_index_metadata(args, {}),
        references=[],
    )


def _index_chapter_key(row: dict[str, Any]) -> str:
    rel_path = str(row.get("path") or "")
    content_hash = str(row.get("sha256") or "")
    return f"{rel_path}::{content_hash}" if rel_path and content_hash else ""


def _existing_chapter_keys(storage: LocalStorage, project_id: str) -> set[str]:
    keys: set[str] = set()
    for path in storage.list_json("raw"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if data.get("type") != "book_chapter_source":
            continue
        content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
        if str(content.get("project_id") or metadata.get("project_id") or "") != project_id:
            continue
        rel_path = str(content.get("source_path") or content.get("source_file") or "")
        content_hash = str(content.get("content_hash") or "")
        if rel_path and content_hash:
            keys.add(f"{rel_path}::{content_hash}")
    return keys


def _existing_index_chapter_asset(storage: LocalStorage, repo_id: str, row: dict[str, Any]) -> dict[str, Any]:
    rel_path = str(row.get("path") or "")
    content_hash = str(row.get("sha256") or "")
    if not rel_path or not content_hash:
        return {}
    path = storage.data_dir("raw") / f"{_stable_id('book_chapter_source', repo_id, rel_path, content_hash)}.json"
    if not path.exists():
        return {}
    try:
        data = storage.read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) and data.get("type") == "book_chapter_source" else {}


def _line_count(path: Path) -> int:
    try:
        count = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                count += chunk.count(b"\n")
        return max(1, count + 1)
    except Exception:
        return 1


def _source_policy() -> dict[str, bool]:
    return {"raw_source_text_allowed": False, "source_chunk_raw_text_allowed": False, "parallel_pair_text_allowed": False, "generation_rag_allowed": False}


def _index_metadata(args: argparse.Namespace, rights: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": args.project_id,
        "mkaos": True,
        "source_policy": _source_policy(),
        "rights": rights,
        "use_in_generation_rag": False,
        "trace_id": str(args.trace_id or ""),
        "index_only": True,
    }


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\0".join(str(part) for part in parts if str(part))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{slugify(prefix)}-{digest}"


def _validate_asset(asset: BaseAsset) -> None:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))


def _run_extractions(
    storage: LocalStorage,
    chapters: list[dict[str, Any]],
    args: argparse.Namespace,
    *,
    max_extraction_jobs: int | None,
    run_paths: dict[str, Path],
    provider_health: dict[str, Any],
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    if not args.run_provider:
        return runs
    if not provider_health.get("available"):
        event = {"status": "provider_unavailable", "provider_called": False, "provider_health": provider_health}
        _append_ledger(run_paths["ledger"], event)
        return [{**event, "candidate_count": 0}]
    if max_extraction_jobs == 0:
        return runs
    processed_hashes = _processed_content_hashes(run_paths["checkpoint"], run_paths["ledger"]) if (args.resume or args.skip_existing) else set()
    selected = chapters
    provider_calls = 0
    skipped_existing = 0
    for chapter in selected:
        key = _chapter_key(chapter)
        if args.skip_existing and key["content_hash"] and key["content_hash"] in processed_hashes:
            skipped_existing += 1
            continue
        if provider_calls >= int(max_extraction_jobs or 0):
            break
        if provider_calls > 0 and args.provider_batch_size > 0 and provider_calls % args.provider_batch_size == 0 and args.sleep_seconds > 0:
            time.sleep(float(args.sleep_seconds))
        content = chapter.get("content", {}) if isinstance(chapter.get("content"), dict) else {}
        source_excerpt = _chapter_source_excerpt(content, max_chars=args.provider_source_chars)
        source_excerpt_hash = hashlib.sha256(source_excerpt.encode("utf-8")).hexdigest() if source_excerpt else ""
        input_summary = _provider_input_summary(content, chapter, source_excerpt_hash=source_excerpt_hash, source_excerpt_chars=len(source_excerpt))
        job = mkaos_model_extraction.create_model_extraction_job(
            storage,
            {
                "project_id": args.project_id,
                "source_type": "classical_text",
                "input_summary": input_summary,
                "source_refs": [chapter.get("id", "")],
                "evidence_refs": chapter.get("references", []),
                "asset_categories": _classical_modern_categories(),
                "provider_mode": args.provider_mode if args.run_provider else "disabled",
                "runtime_policy": {
                    "provider_approval_ref": args.provider_approval_ref,
                    "explicit_operator_approval": bool(args.run_provider),
                    "max_seconds": args.codex_timeout_seconds,
                    "source_excerpt_hash": source_excerpt_hash,
                    "source_excerpt_chars": len(source_excerpt),
                    "source_path": str(content.get("source_path") or content.get("source_file") or ""),
                },
            },
        )
        try:
            provider_calls += 1
            run = mkaos_model_extraction.run_model_extraction_job(
                storage,
                job["id"],
                {
                    "project_id": args.project_id,
                    "source_type": "classical_text",
                    "provider_mode": args.provider_mode if args.run_provider else "disabled",
                    "provider": args.provider if args.run_provider else "",
                    "provider_approval_ref": args.provider_approval_ref,
                    "environment": "local",
                    "asset_categories": _classical_modern_categories(),
                    "allow_evidence_text": bool(source_excerpt),
                    "text": source_excerpt,
                    "runtime_policy": {
                        "provider_approval_ref": args.provider_approval_ref,
                        "explicit_operator_approval": bool(args.run_provider),
                        "max_seconds": args.codex_timeout_seconds,
                        "source_excerpt_hash": source_excerpt_hash,
                        "source_excerpt_chars": len(source_excerpt),
                        "source_path": str(content.get("source_path") or content.get("source_file") or ""),
                    },
                },
            )
            row = {
                **key,
                "job_id": job["id"],
                "status": run.get("status", ""),
                "provider_called": True,
                "candidate_count": run.get("candidate_count", 0),
                "provider_evidence_path": run.get("provider_evidence", {}).get("path", ""),
                "source_excerpt_hash": source_excerpt_hash,
                "source_excerpt_chars": len(source_excerpt),
                "approved_count": 0,
                "auto_approve_requested_ignored": bool(args.approve_auto_candidates),
            }
            _append_ledger(run_paths["ledger"], row)
            processed_hashes.add(key["content_hash"])
            runs.append(row)
        except Exception as exc:
            row = {**key, "job_id": job["id"], "status": "failed", "provider_called": True, "candidate_count": 0, "error": str(exc)}
            _append_ledger(run_paths["ledger"], row)
            runs.append(row)
            if args.fail_fast:
                raise
    if skipped_existing:
        row = {"status": "skipped_existing_batch", "provider_called": False, "candidate_count": 0, "skipped_existing": skipped_existing}
        _append_ledger(run_paths["ledger"], row)
        runs.insert(0, row)
    return runs


def _provider_input_summary(content: dict[str, Any], chapter: dict[str, Any], *, source_excerpt_hash: str, source_excerpt_chars: int) -> str:
    source_path = str(content.get("source_path") or content.get("source_file") or "")
    title = str(content.get("abstract_preview") or content.get("title") or chapter.get("title") or "")
    parts = [
        f"Classical-Modern evidence-only chapter: {title}",
        f"source_path={source_path}",
    ]
    if source_excerpt_hash:
        parts.extend(
            [
                f"source_excerpt_hash={source_excerpt_hash}",
                f"source_excerpt_chars={source_excerpt_chars}",
                "Extract abstract reusable mechanisms only. Do not quote source wording, do not preserve source-specific plot sequence, and do not output raw source text.",
            ]
        )
    else:
        parts.append("source excerpt unavailable; use only path/title metadata.")
    return "\n".join(parts)


def _chapter_source_excerpt(content: dict[str, Any], *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    source_uri = str(content.get("source_uri") or "")
    source_path = str(content.get("source_path") or content.get("source_file") or "")
    path = Path(source_uri) if source_uri else Path(source_path)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    return _bounded_source_text(text, max_chars=max_chars)


def _bounded_source_text(text: str, *, max_chars: int) -> str:
    compact = "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    head = compact[: max_chars // 2]
    tail = compact[-max(0, max_chars - len(head)) :]
    return f"{head}\n[...source excerpt truncated...]\n{tail}"


def _selected_manifest_files(manifest_content: dict[str, Any], args: argparse.Namespace, *, max_books: int | None, max_files: int | None) -> list[dict[str, Any]]:
    files = manifest_content.get("files", []) if isinstance(manifest_content.get("files"), list) else []
    selected: list[dict[str, Any]] = []
    seen_books: set[str] = set()
    requested_books = {str(item).strip() for item in args.book_names if str(item).strip()}
    for row in files:
        book_name = str(row.get("book_name") or "")
        if requested_books and book_name not in requested_books:
            continue
        if str(row.get("file_type") or "") == "parallel_text" and not args.include_parallel_pairs:
            continue
        if max_books is not None and book_name and book_name not in seen_books and len(seen_books) >= max_books:
            continue
        if max_files is not None and len(selected) >= max_files:
            continue
        selected.append(row)
        if book_name:
            seen_books.add(book_name)
    return selected


def _manifest_file_count(manifest: dict[str, Any]) -> int:
    content = manifest.get("content", {}) if isinstance(manifest.get("content"), dict) else {}
    files = content.get("files", []) if isinstance(content.get("files"), list) else []
    return len(files)


def _chapter_key(chapter: dict[str, Any]) -> dict[str, str]:
    content = chapter.get("content", {}) if isinstance(chapter.get("content"), dict) else {}
    return {
        "book_id": str(content.get("book_id") or ""),
        "book_title": str(content.get("book_title") or ""),
        "file_path": str(content.get("source_path") or content.get("source_file") or ""),
        "chapter_id": str(chapter.get("id") or content.get("chapter_id") or ""),
        "chapter_title": str(content.get("title") or chapter.get("title") or ""),
        "content_hash": str(content.get("content_hash") or ""),
    }


def _processed_content_hashes(checkpoint_path: Path, ledger_path: Path) -> set[str]:
    hashes: set[str] = set()
    if checkpoint_path.exists():
        try:
            data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        for item in data.get("processed_content_hashes", []) if isinstance(data, dict) else []:
            if str(item).strip():
                hashes.add(str(item))
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("status") == "succeeded" and str(row.get("content_hash") or "").strip():
                hashes.add(str(row.get("content_hash")))
    return hashes


def _append_ledger(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": _now(), **row}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _checkpoint_payload(
    args: argparse.Namespace,
    repository: dict[str, Any],
    scanned: dict[str, Any],
    imported: dict[str, Any],
    extraction_runs: list[dict[str, Any]],
    provider_health: dict[str, Any],
    run_paths: dict[str, Path],
) -> dict[str, Any]:
    processed = sorted(
        {
            *_processed_content_hashes(run_paths["checkpoint"], run_paths["ledger"]),
            *{str(row.get("content_hash") or "") for row in extraction_runs if row.get("status") == "succeeded" and str(row.get("content_hash") or "")},
        }
    )
    failed = [row for row in extraction_runs if row.get("status") == "failed"]
    skipped_existing_count = _skipped_existing_count(extraction_runs)
    manifest_content = scanned.get("manifest", {}).get("content", {}) if isinstance(scanned.get("manifest"), dict) else {}
    import_content = imported.get("report", {}).get("content", {}) if isinstance(imported.get("report"), dict) else {}
    return {
        "updated_at": _now(),
        "project_id": args.project_id,
        "repository_id": repository.get("id", ""),
        "repo_commit": _git_commit(Path(args.repo_path).expanduser().resolve()),
        "manifest": {
            "file_count": len(manifest_content.get("files", []) if isinstance(manifest_content.get("files"), list) else []),
            "book_count": manifest_content.get("stats", {}).get("book_count", 0) if isinstance(manifest_content.get("stats"), dict) else 0,
        },
        "import": {
            "book_count": import_content.get("book_count", 0),
            "chapter_count": import_content.get("chapter_count", 0),
            "parallel_pair_count": import_content.get("parallel_pair_count", 0),
            "dry_run": bool(args.dry_run),
        },
        "provider": {
            "requested": bool(args.run_provider),
            "health": provider_health,
            "processed_count": len(processed),
            "failed_count": len(failed),
            "skipped_existing_count": skipped_existing_count,
        },
        "processed_content_hashes": processed,
        "last_runs": extraction_runs[-20:],
        "paths": {key: str(value) for key, value in run_paths.items()},
    }


def _classical_modern_categories() -> list[str]:
    return ["素材", "拆解", "题材", "世界观", "人物", "大纲", "细纲", "正文", "审稿", "反馈", "训练题", "可复用模板"]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _skipped_existing_count(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        if row.get("status") == "skipped_existing":
            total += 1
        elif row.get("status") == "skipped_existing_batch":
            total += int(row.get("skipped_existing") or 0)
    return total


def _build_report(
    *,
    args: argparse.Namespace,
    repo_path: Path,
    repository: dict[str, Any],
    scanned: dict[str, Any],
    imported: dict[str, Any],
    extraction_runs: list[dict[str, Any]],
    max_books: int | None,
    max_files: int | None,
    max_extraction_jobs: int | None,
    run_paths: dict[str, Path],
    provider_health: dict[str, Any],
) -> dict[str, Any]:
    manifest_content = scanned.get("manifest", {}).get("content", {}) if isinstance(scanned.get("manifest"), dict) else {}
    report_content = imported.get("report", {}).get("content", {}) if isinstance(imported.get("report"), dict) else {}
    provider_successes = [row for row in extraction_runs if row.get("status") == "succeeded"]
    provider_failures = [row for row in extraction_runs if row.get("status") in {"failed", "provider_unavailable"}]
    skipped_existing_count = _skipped_existing_count(extraction_runs)
    summary = {
        "repository_id": repository.get("id", ""),
        "repo_commit": _git_commit(repo_path),
        "manifest_files": len(manifest_content.get("files", []) if isinstance(manifest_content.get("files"), list) else []),
        "manifest_books": manifest_content.get("stats", {}).get("book_count", 0) if isinstance(manifest_content.get("stats"), dict) else 0,
        "imported_books": report_content.get("book_count", 0),
        "imported_chapters": report_content.get("chapter_count", 0),
        "parallel_pairs": report_content.get("parallel_pair_count", 0),
        "provider_jobs": len(extraction_runs),
        "provider_successes": len(provider_successes),
        "provider_failures": len(provider_failures),
        "max_books": max_books,
        "max_files": max_files,
        "max_extraction_jobs": max_extraction_jobs,
        "full_run": bool(args.confirm_full_run),
        "dry_run": bool(args.dry_run),
        "provider_batch_size": args.provider_batch_size,
        "provider_max_calls": max_extraction_jobs,
        "provider_source_chars": args.provider_source_chars,
        "skipped_existing": skipped_existing_count,
        "approved_knowledge_cards": sum(int(row.get("approved_count") or 0) for row in extraction_runs),
    }
    return {
        "summary": summary,
        "source": {
            "repo_path": str(repo_path),
            "source_uri": args.source_uri,
            "license_boundary": "MIT repository license; per-book upstream source retained as evidence metadata when present",
            "source_isolation": "raw text and parallel text remain evidence-only and are not allowed in generation RAG/prose context",
        },
        "import_report": report_content,
        "extraction_runs": extraction_runs,
        "slow_run": {
            "checkpoint_path": str(run_paths["checkpoint"]),
            "ledger_path": str(run_paths["ledger"]),
            "provider_slow_summary_path": str(run_paths["slow_report"]),
            "provider_health": provider_health,
            "supported_parameters": [
                "--max-books",
                "--max-files",
                "--index-only",
                "--run-provider",
                "--include-parallel-pairs",
                "--resume",
                "--checkpoint-path",
                "--provider-batch-size",
                "--provider-max-calls",
                "--provider-source-chars",
                "--sleep-seconds",
                "--dry-run",
                "--report-path",
                "--skip-existing",
                "--fail-fast",
                "--limit-provider-tokens",
            ],
            "asset_categories": _classical_modern_categories(),
        },
        "next_full_run_command": _full_run_command(args),
        "next_safe_batch_command": _next_safe_batch_command(args, run_paths),
    }


def _git_commit(repo_path: Path) -> str:
    try:
        completed = subprocess.run(["git", "-C", str(repo_path), "rev-parse", "HEAD"], check=False, capture_output=True, text=True, timeout=10)
    except Exception:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _full_run_command(args: argparse.Namespace) -> str:
    parts = [
        "CODEX_HOME=~/.codex-claude",
        "python3",
        "scripts/import_classical_modern_to_mkaos.py",
        "--confirm-full-run",
        "--repo-path",
        args.repo_path,
        "--storage-root",
        args.storage_root,
        "--project-id",
        args.project_id,
    ]
    if args.include_parallel_pairs:
        parts.append("--include-parallel-pairs")
    if args.index_only:
        parts.append("--index-only")
    if args.resume:
        parts.append("--resume")
    if args.skip_existing:
        parts.append("--skip-existing")
    return " ".join(parts)


def _next_safe_batch_command(args: argparse.Namespace, run_paths: dict[str, Path]) -> str:
    next_calls = 20 if _provider_call_limit(args) <= 5 else 50
    return " ".join(
        [
            "CODEX_HOME=~/.codex-claude",
            "python3",
            "scripts/import_classical_modern_to_mkaos.py",
            "--repo-path",
            args.repo_path,
            "--storage-root",
            args.storage_root,
            "--project-id",
            args.project_id,
            "--confirm-full-run",
            "--index-only",
            "--run-provider",
            "--provider-batch-size",
            "1",
            "--provider-max-calls",
            str(next_calls),
            "--provider-source-chars",
            str(args.provider_source_chars),
            "--sleep-seconds",
            "2",
            "--resume",
            "--skip-existing",
            "--checkpoint-path",
            str(run_paths["checkpoint"]),
            "--ledger-path",
            str(run_paths["ledger"]),
            "--report-path",
            args.report_path,
        ]
    )


def _render_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    runs = report["extraction_runs"]
    slow_run = report["slow_run"]
    run_lines = "\n".join(
        f"| {row.get('book_title', '')} | {row.get('file_path', '')} | {row.get('chapter_id', '')} | {row.get('content_hash', '')} | {row.get('status', '')} | {row.get('candidate_count', 0)} | {row.get('provider_evidence_path', '')} | {row.get('error', '')} |"
        for row in runs
    )
    return f"""# Classical-Modern MKAOS Import Report

Audit date: generated by `scripts/import_classical_modern_to_mkaos.py`

## Summary

```json
{json.dumps(summary, ensure_ascii=False, indent=2)}
```

## Source Boundary

- Repository: `{report['source']['source_uri']}`
- Local path: `{report['source']['repo_path']}`
- License/source note: {report['source']['license_boundary']}
- Source isolation: {report['source']['source_isolation']}

## Slow-Run Controls

- Checkpoint: `{slow_run['checkpoint_path']}`
- Ledger: `{slow_run['ledger_path']}`
- Provider slow summary: `{slow_run['provider_slow_summary_path']}`
- Provider health: `{slow_run['provider_health'].get('status')}` / `{slow_run['provider_health'].get('reason', '')}`
- Supported parameters: `{', '.join(slow_run['supported_parameters'])}`
- Candidate categories: `{', '.join(slow_run['asset_categories'])}`

## Import Report

```json
{json.dumps(report['import_report'], ensure_ascii=False, indent=2)}
```

## Provider Extraction Runs

| Book | File | Chapter | Content hash | Status | Candidates | Provider evidence | Error |
| -- | -- | -- | -- | -- | --: | -- | -- |
{run_lines or '| none | none | none | none | not_run | 0 |  |  |'}

## Next Safe Batch

```bash
{report['next_safe_batch_command']}
```

## Operator-Gated Full Source Import Command

```bash
{report['next_full_run_command']}
```

Notes:
- The default run is intentionally bounded. Full source import is separated from provider extraction.
- Full provider extraction across all books is intentionally not emitted as a one-shot command. Use `Next Safe Batch` and keep each provider batch at or below 50 calls.
- Parallel sentence pairs are evidence-only and disabled by default because the upstream corpus contains close to one million aligned pairs.
"""


if __name__ == "__main__":
    raise SystemExit(main())
