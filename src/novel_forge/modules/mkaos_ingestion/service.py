from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules import mkaos as mkaos_service
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

from .bilingual_pair_parser import parse_bitext_text, parse_parallel_pair_files
from .classical_modern_adapter import scan_classical_modern_repository
from .format_adapters import read_source_file
from .import_quality_report import build_import_quality_report
from .manifest_builder import build_repository_manifest
from .repository_importer import validate_repository_request
from .source_rights import source_policy_for_kind
from .source_type_extractors import extract_by_source_type


INGESTION_CATEGORIES = {
    "source_repository": "raw",
    "repository_manifest": "raw",
    "book_source": "raw",
    "book_chapter_source": "raw",
    "parallel_text_pair": "raw",
    "mkaos_ingestion_job": "runs",
    "mkaos_extraction_job": "runs",
    "import_quality_report": "runs",
}


def create_repository(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    validated = validate_repository_request(payload)
    project_id = str(payload.get("project_id") or "local-system")
    source_kind = str(payload.get("source_kind") or ("github_repo" if validated.get("requires_local_clone") else "local_folder"))
    local_path = str(payload.get("local_path") or validated.get("local_path") or "")
    source_uri = str(payload.get("source_uri") or validated.get("source_uri") or local_path)
    rights = source_policy_for_kind(str(payload.get("source_type") or payload.get("detected_corpus_type") or "manual_note"), payload.get("rights") if isinstance(payload.get("rights"), dict) else {})
    detected = {"corpus_type": "github_pending_local_clone"} if validated.get("requires_local_clone") else scan_classical_modern_repository(local_path).get("detected_structure", {})
    content = {
        "repository_id": "",
        "project_id": project_id,
        "name": str(payload.get("name") or Path(local_path or source_uri).stem or "MKAOS Repository"),
        "source_uri": source_uri,
        "local_path": local_path,
        "source_kind": source_kind,
        "detected_corpus_type": detected.get("corpus_type", ""),
        "rights": rights,
        "manifest_path": "",
        "import_status": "pending_local_clone" if validated.get("requires_local_clone") else "pending",
        "content_hash": _hash_text(f"{source_uri}|{local_path}|{project_id}"),
        "stats": {"book_count": 0, "chapter_count": 0, "file_count": 0, "parallel_pair_count": 0},
        "source_policy": _source_policy(),
    }
    repository_id = make_id("source_repository", content["name"])
    content["repository_id"] = repository_id
    asset = _asset(
        "source_repository",
        repository_id,
        title=content["name"],
        source=source_uri,
        tags=["mkaos", "ingestion", source_kind],
        content=content,
        metadata=_metadata(project_id, payload, rights),
    )
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path), "requires_local_clone": bool(validated.get("requires_local_clone"))}


def list_repositories(storage: LocalStorage, *, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return _list(storage, "source_repository", project_id=project_id, limit=limit)


def scan_repository(storage: LocalStorage, repository_ref: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    repo_path, repo = _find(storage, repository_ref, "source_repository")
    content = repo.get("content", {}) if isinstance(repo.get("content", {}), dict) else {}
    if content.get("import_status") == "pending_local_clone":
        raise ValueError("GitHub repository is recorded only; clone it locally and update local_path before scan")
    local_path = str(payload.get("local_path") or content.get("local_path") or "")
    manifest = build_repository_manifest(local_path, repository_id=str(repo.get("id") or repository_ref))
    project_id = str(content.get("project_id") or repo.get("metadata", {}).get("project_id") or "local-system")
    manifest_asset = _asset(
        "repository_manifest",
        make_id("repository_manifest", str(repo.get("id") or repository_ref)),
        title=f"{repo.get('title')} manifest",
        source=str(repo.get("id") or repository_ref),
        tags=["mkaos", "ingestion", "manifest"],
        content={**manifest, "project_id": project_id, "source_policy": _source_policy()},
        metadata=_metadata(project_id, payload, content.get("rights", {})),
        references=[str(repo.get("id") or "")],
    )
    manifest_path = _write(storage, manifest_asset)
    content["manifest_path"] = _display_path(storage, manifest_path)
    content["import_status"] = "scanned"
    content["stats"] = manifest.get("stats", {})
    repo["content"] = content
    repo["updated_at"] = utc_now()
    storage.write_json(repo_path, repo)
    return {"repository": storage.read_json(repo_path), "manifest": storage.read_json(manifest_path), "path": _display_path(storage, manifest_path)}


def import_repository(storage: LocalStorage, repository_ref: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    scan = scan_repository(storage, repository_ref, payload) if payload.get("rescan") else _load_or_scan_manifest(storage, repository_ref, payload)
    repo = scan["repository"]
    manifest = scan["manifest"]
    project_id = str(repo.get("content", {}).get("project_id") or repo.get("metadata", {}).get("project_id") or "local-system")
    local_root = Path(str(repo.get("content", {}).get("local_path") or manifest.get("content", {}).get("root_path") or ""))
    job = _create_job(storage, "mkaos_ingestion_job", project_id, "repository_import", {"repository_id": repo.get("id", ""), "manifest_id": manifest.get("id", ""), "status": "running"}, payload)
    imported_books: dict[str, dict[str, Any]] = {}
    imported_chapters: list[dict[str, Any]] = []
    parallel_pairs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    duplicate_count = 0
    seen_file_hashes: set[str] = set()
    files = manifest.get("content", {}).get("files", []) if isinstance(manifest.get("content", {}).get("files", []), list) else []
    for file_row in files:
        try:
            sha256 = str(file_row.get("sha256") or "")
            if sha256 and sha256 in seen_file_hashes:
                duplicate_count += 1
                continue
            seen_file_hashes.add(sha256)
            file_path = local_root / str(file_row.get("path") or "")
            book = _ensure_book(storage, project_id, repo, file_row, imported_books, payload)
            if str(file_row.get("file_type")) == "parallel_text":
                parallel_pairs.extend(_import_parallel_pairs(storage, project_id, book, file_path, file_row, payload))
                continue
            read = read_source_file(file_path)
            source = mkaos_service.import_source_document(
                storage,
                {
                    "project_id": project_id,
                    "title": f"{book['content']['book_name']} / {'/'.join(file_row.get('chapter_path') or [])}",
                    "source_kind": str(file_row.get("file_type") or "manual_note"),
                    "source_uri": str(file_path),
                    "text": read.get("text", ""),
                    "rights": book["content"].get("rights", {}),
                    "trace_id": str(payload.get("trace_id") or ""),
                    "bypass_reason": str(payload.get("bypass_reason") or "local ingestion import"),
                },
            )
            chapter = _write_chapter(storage, project_id, book, file_row, source, read, payload)
            imported_chapters.append(chapter["asset"])
        except Exception as exc:
            failures.append({"path": str(file_row.get("path") or ""), "error": str(exc), "retryable": True})
    report_payload = build_import_quality_report(
        repository_id=str(repo.get("id") or ""),
        manifest=manifest.get("content", {}),
        imported_books=list(imported_books.values()),
        imported_chapters=imported_chapters,
        parallel_pairs=parallel_pairs,
        duplicate_count=duplicate_count,
        failures=failures,
    )
    report_asset = _asset("import_quality_report", make_id("import_quality_report", str(repo.get("id") or "")), title=f"{repo.get('title')} import quality", source=str(repo.get("id") or ""), tags=["mkaos", "ingestion", "quality"], content={**report_payload, "project_id": project_id}, metadata=_metadata(project_id, payload, repo.get("content", {}).get("rights", {})), references=[str(repo.get("id") or ""), str(manifest.get("id") or "")])
    report_path = _write(storage, report_asset)
    _complete_job(storage, job["path"], status="succeeded" if not failures else "completed_with_failures", outputs={"report_path": _display_path(storage, report_path), "failure_count": len(failures)})
    repo_path, repo_data = _find(storage, str(repo.get("id")), "source_repository")
    repo_content = repo_data.get("content", {})
    repo_content["import_status"] = "imported" if not failures else "imported_with_failures"
    repo_content["stats"] = {**repo_content.get("stats", {}), "book_count": len(imported_books), "chapter_count": len(imported_chapters), "parallel_pair_count": len(parallel_pairs)}
    repo_data["content"] = repo_content
    storage.write_json(repo_path, repo_data)
    return {"repository": storage.read_json(repo_path), "job": storage.read_json(storage.root / job["path"]), "report": storage.read_json(report_path), "books": list(imported_books.values()), "chapters": imported_chapters, "parallel_pairs": parallel_pairs}


def create_extraction_job(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    source_type = str(payload.get("source_type") or "professional_book")
    rows: list[dict[str, Any]] = []
    if payload.get("chapter_id"):
        _, chapter = _find(storage, str(payload.get("chapter_id")), "book_chapter_source")
        rows.append(chapter)
    elif payload.get("book_id"):
        rows = [row.get("asset", row) for row in list_book_chapters(storage, str(payload.get("book_id")), limit=1000)]
    else:
        rows = [row.get("asset", row) for row in list_books(storage, project_id=project_id, limit=1000)]
    created: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("content", {}).get("abstract_preview") or row.get("title") or "")
        candidates = extract_by_source_type(source_type, {**payload, "text": text, "evidence_refs": row.get("references", [])})
        for candidate in candidates:
            created.append(create_creative_knowledge_card(storage, {**candidate, "project_id": project_id, "source": row.get("id", ""), "evidence_refs": row.get("references", [])})["asset"])
    job = _create_job(storage, "mkaos_extraction_job", project_id, "creative_knowledge_extraction", {"status": "succeeded", "source_type": source_type, "created_count": len(created)}, payload)
    return {"job": storage.read_json(storage.root / job["path"]), "created": created, "created_count": len(created)}


def run_source_type_extractor(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    cards = [create_creative_knowledge_card(storage, {**candidate, "project_id": project_id})["asset"] for candidate in extract_by_source_type(str(payload.get("source_type") or "professional_book"), payload)]
    return {"created": cards, "created_count": len(cards)}


def create_creative_knowledge_card(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    quality = payload.get("quality_dimensions") if isinstance(payload.get("quality_dimensions"), dict) else {}
    merged = {
        **payload,
        "knowledge_subtype": "creative_knowledge_card",
        "metadata": {
            **(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
            "knowledge_subtype": "creative_knowledge_card",
            "source_policy": _source_policy(),
        },
        "quality_dimensions": {
            "abstraction_score": float(quality.get("abstraction_score", payload.get("abstraction_score", 0.78))),
            "transferability_score": float(quality.get("transferability_score", 0.76)),
            "actionability_score": float(quality.get("actionability_score", 0.76)),
            "copyright_risk_score": float(quality.get("copyright_risk_score", 0.1)),
            "effectiveness_score": float(quality.get("effectiveness_score", 0.5)),
            "review_pass_score": float(quality.get("review_pass_score", 0.5)),
            "reader_feedback_score": float(quality.get("reader_feedback_score", 0.5)),
            "source_reliability_score": float(quality.get("source_reliability_score", 0.72)),
            "freshness_score": float(quality.get("freshness_score", 0.7)),
            "consistency_score": float(quality.get("consistency_score", 0.72)),
            "creative_usability_score": float(quality.get("creative_usability_score", payload.get("creative_usability_score", 0.78))),
            "flow_binding_score": float(quality.get("flow_binding_score", payload.get("flow_binding_score", 0.78))),
            "anti_exposition_score": float(quality.get("anti_exposition_score", payload.get("anti_exposition_score", 0.78))),
            "originality_safety_score": float(quality.get("originality_safety_score", payload.get("originality_safety_score", 0.82))),
        },
    }
    result = mkaos_service.create_knowledge_card(storage, merged)
    path = resolve_path(storage.root, result["path"])
    asset = storage.read_json(path)
    content = asset.get("content", {})
    for key in [
        "source_type",
        "abstraction_level",
        "creative_principle",
        "narrative_function",
        "conflict_function",
        "character_function",
        "worldbuilding_function",
        "prose_function",
        "review_function",
        "positive_usage",
        "negative_usage",
        "anti_patterns",
        "applicable_flows",
        "originality_boundary",
        "knowledge_subtype",
    ]:
        if key in merged:
            content[key] = merged[key]
    existing_quality = content.get("quality_dimensions") if isinstance(content.get("quality_dimensions"), dict) else {}
    content["quality_dimensions"] = {**existing_quality, **merged["quality_dimensions"]}
    content["creative_usability_score"] = merged["quality_dimensions"]["creative_usability_score"]
    content["flow_binding_score"] = merged["quality_dimensions"]["flow_binding_score"]
    content["anti_exposition_score"] = merged["quality_dimensions"]["anti_exposition_score"]
    content["originality_safety_score"] = merged["quality_dimensions"]["originality_safety_score"]
    asset["content"] = content
    asset["metadata"] = {**asset.get("metadata", {}), "knowledge_subtype": "creative_knowledge_card", "source_policy": _source_policy()}
    storage.write_json(path, asset)
    return {"path": result["path"], "asset": storage.read_json(path), "validation": result.get("validation", {"ok": True, "errors": []})}


def list_books(storage: LocalStorage, *, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return _list(storage, "book_source", project_id=project_id, limit=limit)


def list_book_chapters(storage: LocalStorage, book_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    rows = _list(storage, "book_chapter_source", limit=limit)
    return [row for row in rows if str(row.get("content", {}).get("book_id") or "") == book_id]


def list_parallel_pairs(storage: LocalStorage, *, project_id: str | None = None, book_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    rows = _list(storage, "parallel_text_pair", project_id=project_id, limit=limit)
    if book_id:
        rows = [row for row in rows if str(row.get("content", {}).get("book_id") or "") == book_id]
    return rows


def list_ingestion_jobs(storage: LocalStorage, *, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = [*_list(storage, "mkaos_ingestion_job", project_id=project_id, limit=limit), *_list(storage, "mkaos_extraction_job", project_id=project_id, limit=limit)]
    return sorted(rows, key=lambda row: str(row.get("updated_at") or ""), reverse=True)[:limit]


def _load_or_scan_manifest(storage: LocalStorage, repository_ref: str, payload: dict[str, Any]) -> dict[str, Any]:
    repo_path, repo = _find(storage, repository_ref, "source_repository")
    manifest_path = str(repo.get("content", {}).get("manifest_path") or "")
    if not manifest_path:
        return scan_repository(storage, repository_ref, payload)
    manifest = storage.read_json(resolve_path(storage.root, manifest_path))
    return {"repository": repo, "manifest": manifest, "path": manifest_path}


def _ensure_book(storage: LocalStorage, project_id: str, repo: dict[str, Any], file_row: dict[str, Any], cache: dict[str, dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    book_name = str(file_row.get("book_name") or "Untitled Book")
    if book_name in cache:
        return cache[book_name]
    rights = repo.get("content", {}).get("rights", {})
    book_id = make_id("book_source", f"{repo.get('id')} {book_name}")
    content = {
        "book_id": book_id,
        "project_id": project_id,
        "repository_id": str(repo.get("id") or ""),
        "book_name": book_name,
        "source_type": str(file_row.get("file_type") or "plain_text"),
        "discipline_tags": [],
        "chapter_count": 0,
        "has_parallel_text": False,
        "rights": rights,
        "risk_level": rights.get("risk_level", "low"),
        "source_policy": _source_policy(),
    }
    asset = _asset("book_source", book_id, title=book_name, source=str(repo.get("id") or ""), tags=["mkaos", "book-source", content["source_type"]], content=content, metadata=_metadata(project_id, payload, rights), references=[str(repo.get("id") or "")])
    path = _write(storage, asset)
    cache[book_name] = storage.read_json(path)
    return cache[book_name]


def _write_chapter(storage: LocalStorage, project_id: str, book: dict[str, Any], file_row: dict[str, Any], source: dict[str, Any], read: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    title = " / ".join(file_row.get("chapter_path") or []) or str(file_row.get("path") or "")
    source_asset = source.get("asset", {}) if isinstance(source.get("asset", {}), dict) else {}
    chunks = source.get("chunks", []) if isinstance(source.get("chunks", []), list) else []
    content = {
        "chapter_id": "",
        "project_id": project_id,
        "book_id": str(book.get("id") or book.get("content", {}).get("book_id") or ""),
        "title": title,
        "chapter_path": file_row.get("chapter_path") or [],
        "source_file": str(file_row.get("path") or ""),
        "text_length": len(str(read.get("text") or "")),
        "source_document_id": str(source_asset.get("id") or ""),
        "source_chunk_ids": [str(chunk.get("id") or "") for chunk in chunks],
        "parallel_pair_ids": [],
        "extraction_status": "pending",
        "abstract_preview": _abstract_preview(str(read.get("text") or "")),
        "source_policy": _source_policy(),
    }
    content["chapter_id"] = make_id("book_chapter_source", f"{content['book_id']} {title}")
    asset = _asset("book_chapter_source", content["chapter_id"], title=title, source=str(source_asset.get("id") or ""), tags=["mkaos", "book-chapter-source"], content=content, metadata=_metadata(project_id, payload, book.get("content", {}).get("rights", {})), references=[str(book.get("id") or ""), str(source_asset.get("id") or ""), *content["source_chunk_ids"]])
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path)}


def _import_parallel_pairs(storage: LocalStorage, project_id: str, book: dict[str, Any], file_path: Path, file_row: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    if file_path.name.lower() == "source.txt" and file_path.with_name("target.txt").exists():
        pairs = parse_parallel_pair_files(file_path, file_path.with_name("target.txt"), book_id=str(book.get("id") or ""), chapter_id="")
    elif file_path.name.lower() == "target.txt":
        return []
    else:
        pairs = parse_bitext_text(file_path.read_text(encoding="utf-8", errors="ignore"), book_id=str(book.get("id") or ""), source_file=str(file_path))
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        asset = _asset(
            "parallel_text_pair",
            str(pair["pair_id"]),
            title=f"{book.get('title')} pair {pair['pair_index']}",
            source=str(book.get("id") or ""),
            tags=["mkaos", "parallel-text-pair", "evidence-only"],
            content={**pair, "project_id": project_id, "source_policy": _source_policy()},
            metadata={**_metadata(project_id, payload, book.get("content", {}).get("rights", {})), "evidence_layer_only": True, "raw_text_allowed_for_prose": False},
            references=[str(book.get("id") or "")],
        )
        rows.append(storage.read_json(_write(storage, asset)))
    return rows


def _create_job(storage: LocalStorage, asset_type: str, project_id: str, operation: str, content: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    job_id = make_id(asset_type, f"{operation} {utc_now()}")
    asset = _asset(asset_type, job_id, title=f"MKAOS {operation}", source="mkaos-ingestion", tags=["mkaos", "job", operation], content={**content, "job_id": job_id, "operation": operation, "project_id": project_id, "trace_id": str(payload.get("trace_id") or "")}, metadata=_metadata(project_id, payload, {}))
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path)}


def _complete_job(storage: LocalStorage, job_path: str, *, status: str, outputs: dict[str, Any]) -> None:
    path = resolve_path(storage.root, job_path)
    data = storage.read_json(path)
    content = data.get("content", {})
    content["status"] = status
    content["outputs"] = outputs
    content["completed_at"] = utc_now()
    data["content"] = content
    data["updated_at"] = utc_now()
    storage.write_json(path, data)


def _asset(asset_type: str, asset_id: str, *, title: str, source: str, tags: list[str], content: dict[str, Any], metadata: dict[str, Any], references: list[str] | None = None) -> BaseAsset:
    return BaseAsset(id=asset_id, type=asset_type, title=title, source=source, tags=tags, content=content, metadata=metadata, references=references or [])


def _write(storage: LocalStorage, asset: BaseAsset) -> Path:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return storage.write_asset(INGESTION_CATEGORIES.get(asset.type, "knowledge"), asset)


def _metadata(project_id: str, payload: dict[str, Any], rights: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "mkaos": True,
        "source_policy": _source_policy(),
        "rights": rights,
        "use_in_generation_rag": False,
        "trace_id": str(payload.get("trace_id") or ""),
        "os_envelope": payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else {},
        "run_metadata": run_metadata("mkaos.ingestion", BaseAsset(title="mkaos-ingestion", content={})),
    }


def _source_policy() -> dict[str, bool]:
    return {"raw_source_text_allowed": False, "source_chunk_raw_text_allowed": False, "parallel_pair_text_allowed": False, "generation_rag_allowed": False}


def _list(storage: LocalStorage, asset_type: str, *, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    category = INGESTION_CATEGORIES.get(asset_type, "knowledge")
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json(category)):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
        if project_id and str(metadata.get("project_id") or content.get("project_id") or "") != project_id:
            continue
        rows.append({"path": _display_path(storage, path), "id": data.get("id", ""), "type": data.get("type", ""), "title": data.get("title", ""), "source": data.get("source", ""), "content": content, "metadata": metadata, "references": data.get("references", []), "asset": data, "updated_at": data.get("updated_at", "")})
    return rows


def _find(storage: LocalStorage, ref: str, asset_type: str) -> tuple[Path, dict[str, Any]]:
    category = INGESTION_CATEGORIES.get(asset_type, "knowledge")
    value = str(ref)
    if "/" in value or value.endswith(".json"):
        path = resolve_path(storage.root, value)
        data = storage.read_json(path)
        if data.get("type") == asset_type:
            return path, data
    for path in reversed(storage.list_json(category)):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == asset_type and value in {str(data.get("id") or ""), str(path.relative_to(storage.root))}:
            return path, data
    raise FileNotFoundError(ref)


def _display_path(storage: LocalStorage, path: str | Path) -> str:
    p = Path(path)
    return str(p.relative_to(storage.root)) if p.is_absolute() and p.is_relative_to(storage.root) else str(p)


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _abstract_preview(text: str) -> str:
    compact = " ".join(str(text or "").split())
    return compact[:240]
