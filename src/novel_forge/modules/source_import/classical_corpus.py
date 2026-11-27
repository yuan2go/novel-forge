from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import unicodedata

from .domain import NormalizedChunk, NormalizedSource


REGISTRY_PATH = (
    Path(__file__).resolve().parents[4]
    / "config"
    / "source"
    / "classical-corpus-20260908.json"
)
SUPPORTED_PARSERS = frozenset(
    {"chinese-novel-html.v1", "chinese-poetry-json.v1"}
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_HORIZONTAL_SPACE = re.compile(r"[\t\f\v \u00a0\u3000]+")
_HTML_NUMBER = re.compile(r"^(?P<index>[0-9]+)\.html$")
_HUJIAN_ORDER = re.compile(r"huajianji-(?P<volume>[0-9]+|x)(?:-[^.]+)?\.json$")


class CorpusParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CorpusWorkSpec:
    registry_id: str
    registry_hash: str
    work_key: str
    repository_key: str
    repository_url: str
    repository_commit_sha: str
    license_name: str
    license_path: str
    title: str
    collection_kind: str
    parser_profile: str
    include_globs: tuple[str, ...]
    root_path: str = ""
    paths: tuple[str, ...] = ()
    parser_variant: str = ""

    def __post_init__(self) -> None:
        required = (
            self.registry_id,
            self.registry_hash,
            self.work_key,
            self.repository_key,
            self.repository_url,
            self.repository_commit_sha,
            self.title,
            self.collection_kind,
            self.parser_profile,
        )
        if any(not value.strip() for value in required):
            raise CorpusParseError("CORPUS_SPEC_INCOMPLETE", self.work_key)
        if not _SHA256.fullmatch(self.registry_hash):
            raise CorpusParseError("CORPUS_REGISTRY_HASH_INVALID", self.work_key)
        if not _COMMIT_SHA.fullmatch(self.repository_commit_sha):
            raise CorpusParseError("CORPUS_COMMIT_INVALID", self.work_key)
        if self.parser_profile not in SUPPORTED_PARSERS or not self.include_globs:
            raise CorpusParseError("CORPUS_PARSER_UNSUPPORTED", self.work_key)


@dataclass(frozen=True, slots=True)
class ParsedSourceUnit:
    unit_id: str
    unit_version_id: str
    ordinal: int
    kind: str
    title: str
    author: str
    body: str
    raw_file_path: str
    raw_file_hash: str
    source_locator: dict[str, Any]
    original_content_hash: str
    normalized_content_hash: str
    character_count: int
    line_count: int
    metadata: dict[str, Any]
    status: str
    normalized_byte_start: int = 0
    normalized_byte_end: int = 0
    normalized_character_start: int = 0
    normalized_character_end: int = 0

    def manifest_entry(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("body")
        return value


@dataclass(frozen=True, slots=True)
class AcquiredWorkSpec:
    work_key: str
    title: str
    collection_kind: str
    parser_profile: str
    registry_id: str
    registry_hash: str
    acquisition: dict[str, Any]
    repository_commit_sha: None = None


@dataclass(frozen=True, slots=True)
class ParsedSourceWork:
    spec: CorpusWorkSpec | AcquiredWorkSpec
    units: tuple[ParsedSourceUnit, ...]
    normalized: NormalizedSource
    chunks: tuple[NormalizedChunk, ...]
    diagnostics: dict[str, Any]
    excluded_fields: tuple[dict[str, Any], ...]
    parser_version: str

    @property
    def manifest_hash(self) -> str:
        return canonical_hash(self.structure_manifest())

    def structure_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "source-work-structure.v1",
            "source_work": {
                "work_key": self.spec.work_key,
                "title": self.spec.title,
                "collection_kind": self.spec.collection_kind,
            },
            "parser": {
                "profile": self.spec.parser_profile,
                "version": self.parser_version,
                "registry_id": self.spec.registry_id,
                "registry_hash": self.spec.registry_hash,
            },
            **({"acquisition": self.spec.acquisition} if isinstance(self.spec, AcquiredWorkSpec) else {
                "repository": {
                    "repository_key": self.spec.repository_key,
                    "repository_url": self.spec.repository_url,
                    "commit_sha": self.spec.repository_commit_sha,
                    "license_name": self.spec.license_name,
                    "license_path": self.spec.license_path,
                }
            }),
            "units": [item.manifest_entry() for item in self.units],
            "diagnostics": self.diagnostics,
            "excluded_fields": list(self.excluded_fields),
            "normalized_projection": {
                "content_hash": self.normalized.content_hash,
                "byte_size": self.normalized.byte_size,
                "character_count": self.normalized.character_count,
                "chunk_count": len(self.chunks),
                "traditional_simplified_conversion": "NOT_APPLIED",
            },
            "source_policy": {
                "raw_source_text_in_postgresql": False,
                "raw_source_text_in_generation_context": False,
                "requires_abstraction_before_context": True,
            },
        }


def load_corpus_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CorpusParseError("CORPUS_REGISTRY_INVALID", "registry is not an object")
    if value.get("schema_version") != "classical-corpus-registry.v1":
        raise CorpusParseError("CORPUS_REGISTRY_INVALID", "schema version")
    repositories = value.get("repositories")
    works = value.get("works")
    if not isinstance(repositories, dict) or not isinstance(works, list):
        raise CorpusParseError("CORPUS_REGISTRY_INVALID", "repositories or works")
    keys = [str(item.get("work_key") or "") for item in works if isinstance(item, dict)]
    if len(works) != 20 or len(keys) != 20 or len(set(keys)) != 20:
        raise CorpusParseError(
            "CORPUS_REGISTRY_CARDINALITY_INVALID", "expected 20 unique works"
        )
    counts = {
        key: sum(
            1
            for item in works
            if isinstance(item, dict) and item.get("repository") == key
        )
        for key in repositories
    }
    if counts != {"chinese-novel": 10, "chinese-poetry": 10}:
        raise CorpusParseError(
            "CORPUS_REGISTRY_CARDINALITY_INVALID", str(counts)
        )
    return value


def corpus_registry_hash(registry: Mapping[str, Any]) -> str:
    return canonical_hash(dict(registry))


def resolve_work_spec(
    work_key: str, *, registry: Mapping[str, Any] | None = None
) -> CorpusWorkSpec:
    registry_value = dict(registry or load_corpus_registry())
    repository_rows = dict(registry_value["repositories"])
    matches = [
        dict(item)
        for item in registry_value["works"]
        if isinstance(item, dict) and item.get("work_key") == work_key
    ]
    if len(matches) != 1:
        raise CorpusParseError("CORPUS_WORK_UNKNOWN", work_key)
    row = matches[0]
    repository_key = str(row["repository"])
    try:
        repository = dict(repository_rows[repository_key])
    except KeyError as exc:
        raise CorpusParseError(
            "CORPUS_REPOSITORY_UNKNOWN", repository_key
        ) from exc
    return CorpusWorkSpec(
        registry_id=str(registry_value["registry_id"]),
        registry_hash=corpus_registry_hash(registry_value),
        work_key=work_key,
        repository_key=repository_key,
        repository_url=str(repository["url"]),
        repository_commit_sha=str(repository["commit_sha"]),
        license_name=str(repository.get("license_name") or ""),
        license_path=str(repository.get("license_path") or ""),
        title=str(row["title"]),
        collection_kind=str(row["collection_kind"]),
        parser_profile=str(row["parser_profile"]),
        include_globs=tuple(str(item) for item in row["include_globs"]),
        root_path=str(row.get("root_path") or ""),
        paths=tuple(str(item) for item in row.get("paths") or ()),
        parser_variant=str(row.get("parser_variant") or ""),
    )


def parse_classical_work(
    spec: CorpusWorkSpec,
    files: Mapping[str, bytes],
    *,
    max_chunk_bytes: int,
    normalization_version: str,
) -> ParsedSourceWork:
    if not files:
        raise CorpusParseError("CORPUS_FILES_MISSING", spec.work_key)
    if spec.parser_profile == "chinese-novel-html.v1":
        units, diagnostics, excluded = _parse_chinese_novel(spec, files)
    elif spec.parser_profile == "chinese-poetry-json.v1":
        units, diagnostics, excluded = _parse_chinese_poetry(spec, files)
    else:
        raise CorpusParseError("CORPUS_PARSER_UNSUPPORTED", spec.parser_profile)
    finalized, normalized, chunks = _finalize_units(
        spec,
        units,
        max_chunk_bytes=max_chunk_bytes,
        normalization_version=normalization_version,
    )
    diagnostics = {
        **diagnostics,
        **_unit_diagnostics(finalized),
        "selected_file_count": len(files),
        "unit_count": len(finalized),
        "body_unit_count": sum(item.status == "AVAILABLE" for item in finalized),
        "character_count": sum(item.character_count for item in finalized),
        "parser_failures": [],
    }
    return ParsedSourceWork(
        spec=spec,
        units=finalized,
        normalized=normalized,
        chunks=chunks,
        diagnostics=diagnostics,
        excluded_fields=tuple(excluded),
        parser_version=spec.parser_profile,
    )


def _parse_chinese_novel(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], dict[str, Any], list[dict[str, Any]]]:
    info_path = f"{spec.root_path}/info.json"
    info = _load_json(files, info_path)
    if not isinstance(info, dict) or not isinstance(info.get("catalogues"), list):
        raise CorpusParseError("NOVEL_INFO_SHAPE_INVALID", info_path)
    catalogues = info["catalogues"]
    if any(not isinstance(title, str) or not title.strip() for title in catalogues):
        raise CorpusParseError("NOVEL_CATALOGUE_INVALID", info_path)
    author_row = info.get("author")
    author = (
        str(author_row.get("name") or "")
        if isinstance(author_row, dict)
        else str(author_row or "")
    )
    excluded: list[dict[str, Any]] = []
    if isinstance(author_row, dict) and author_row.get("intro"):
        excluded.append(
            _excluded(
                info_path,
                "/author/intro",
                "author_introduction",
                author_row["intro"],
            )
        )
    units: list[ParsedSourceUnit] = []
    missing: list[str] = []
    expected_paths = {info_path}
    for index, title in enumerate(catalogues):
        path = f"{spec.root_path}/{index}.html"
        expected_paths.add(path)
        raw = files.get(path)
        if raw is None:
            missing.append(path)
            continue
        html_text = _decode_text(raw, path)
        body, paragraph_spans = extract_governed_html(html_text)
        kind = _novel_unit_kind(str(title), spec.collection_kind)
        units.append(
            _make_unit(
                spec=spec,
                ordinal=index + 1,
                kind=kind,
                title=str(title),
                author=author,
                body=body,
                raw_file_path=path,
                raw_file_hash=_bytes_hash(raw),
                source_locator={
                    "kind": "HTML_RANGE",
                    "path": path,
                    "catalogue_index": index,
                    "paragraph_spans": paragraph_spans,
                },
                original_value=html_text,
                metadata={
                    "catalogue_index": index,
                    "dynasty": (
                        str(author_row.get("dynasty") or "")
                        if isinstance(author_row, dict)
                        else ""
                    ),
                },
            )
        )
    if missing:
        raise CorpusParseError(
            "NOVEL_CATALOGUE_BODY_MISSING", ", ".join(missing[:10])
        )
    numeric_html = sorted(
        path
        for path in files
        if path.startswith(f"{spec.root_path}/")
        and _HTML_NUMBER.fullmatch(path.rsplit("/", 1)[-1])
    )
    unexpected = sorted(set(files) - expected_paths)
    for path in unexpected:
        excluded.append(
            {
                "path": path,
                "locator": "",
                "field": "unmapped_repository_file",
                "item_count": 1,
                "content_hash": _bytes_hash(files[path]),
                "reason": "not mapped by info.json catalogue position",
            }
        )
    declared = info.get("catalogueTotal")
    return (
        units,
        {
            "catalogue_declared_count": declared,
            "catalogue_entry_count": len(catalogues),
            "numeric_html_file_count": len(numeric_html),
            "catalogue_count_mismatch": declared != len(catalogues),
            "missing_catalogue_files": [],
            "unexpected_files": unexpected,
            "ordering": "info.json catalogue position -> numeric HTML filename",
        },
        excluded,
    )


def _parse_chinese_poetry(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], dict[str, Any], list[dict[str, Any]]]:
    variant = spec.parser_variant
    handlers = {
        "shijing": _parse_shijing,
        "chuci": _parse_chuci,
        "caocao": _parse_caocao,
        "nalan": _parse_nalan,
        "huajianji": _parse_huajianji,
        "nantang": _parse_nantang,
        "youmengying": _parse_youmengying,
        "lunyu": _parse_lunyu,
        "shenglvqimeng": _parse_shenglvqimeng,
        "tangshisanbaishou": _parse_tangshisanbaishou,
    }
    try:
        handler = handlers[variant]
    except KeyError as exc:
        raise CorpusParseError("POETRY_VARIANT_UNSUPPORTED", variant) from exc
    units, excluded = handler(spec, files)
    return (
        units,
        {
            "parser_variant": variant,
            "piece_boundaries": "PRESERVED",
            "line_boundaries": "PRESERVED",
            "annotations_in_body": False,
        },
        excluded,
    )


def _parse_shijing(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    path, rows = _single_array(spec, files)
    units = [
        _json_lines_unit(
            spec,
            ordinal=index + 1,
            path=path,
            raw_file_hash=_bytes_hash(files[path]),
            pointer=f"/{index}/content",
            row=_object(row, path, f"/{index}"),
            body_field="content",
            title_field="title",
            author="佚名",
            kind="POEM",
            metadata_fields=("chapter", "section"),
        )
        for index, row in enumerate(rows)
    ]
    return units, []


def _parse_chuci(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    path, rows = _single_array(spec, files)
    return (
        [
            _json_lines_unit(
                spec,
                ordinal=index + 1,
                path=path,
                raw_file_hash=_bytes_hash(files[path]),
                pointer=f"/{index}/content",
                row=_object(row, path, f"/{index}"),
                body_field="content",
                title_field="title",
                author=str(_object(row, path, f"/{index}").get("author") or ""),
                kind="POEM",
                metadata_fields=("section",),
            )
            for index, row in enumerate(rows)
        ],
        [],
    )


def _parse_caocao(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    path, rows = _single_array(spec, files)
    return (
        [
            _json_lines_unit(
                spec,
                ordinal=index + 1,
                path=path,
                raw_file_hash=_bytes_hash(files[path]),
                pointer=f"/{index}/paragraphs",
                row=_object(row, path, f"/{index}"),
                body_field="paragraphs",
                title_field="title",
                author="曹操",
                kind="POEM",
            )
            for index, row in enumerate(rows)
        ],
        [],
    )


def _parse_nalan(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    path, rows = _single_array(spec, files)
    units = []
    for index, value in enumerate(rows):
        row = _object(value, path, f"/{index}")
        units.append(
            _json_lines_unit(
                spec,
                ordinal=index + 1,
                path=path,
                raw_file_hash=_bytes_hash(files[path]),
                pointer=f"/{index}/para",
                row=row,
                body_field="para",
                title_field="title",
                author=str(row.get("author") or "纳兰性德"),
                kind="POEM",
            )
        )
    return units, []


def _huajian_sort(path: str) -> tuple[int, str]:
    match = _HUJIAN_ORDER.search(path.rsplit("/", 1)[-1])
    if match is None:
        raise CorpusParseError("HUAJIANJI_FILENAME_INVALID", path)
    volume = match.group("volume")
    return (10 if volume == "x" else int(volume), path)


def _parse_huajianji(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    paths = sorted(files, key=_huajian_sort)
    if len(paths) != 11:
        raise CorpusParseError(
            "HUAJIANJI_VOLUME_COUNT_INVALID", f"observed {len(paths)}"
        )
    return _parse_poetry_files(spec, files, paths, preface_first=True)


def _parse_nantang(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    return _parse_poetry_files(spec, files, list(spec.paths), preface_first=False)


def _parse_poetry_files(
    spec: CorpusWorkSpec,
    files: Mapping[str, bytes],
    paths: list[str],
    *,
    preface_first: bool,
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    units: list[ParsedSourceUnit] = []
    excluded: list[dict[str, Any]] = []
    ordinal = 0
    for file_index, path in enumerate(paths):
        rows = _array(_load_json(files, path), path, "")
        for row_index, value in enumerate(rows):
            row = _object(value, path, f"/{row_index}")
            ordinal += 1
            if "notes" in row:
                excluded.append(
                    _excluded(
                        path,
                        f"/{row_index}/notes",
                        "annotation",
                        row["notes"],
                    )
                )
            units.append(
                _json_lines_unit(
                    spec,
                    ordinal=ordinal,
                    path=path,
                    raw_file_hash=_bytes_hash(files[path]),
                    pointer=f"/{row_index}/paragraphs",
                    row=row,
                    body_field="paragraphs",
                    title_field="title",
                    author=str(row.get("author") or ""),
                    kind=(
                        "PREFACE"
                        if preface_first and file_index == 0 and row_index == 0
                        else "POEM"
                    ),
                    metadata_fields=("rhythmic",),
                    excluded_metadata={
                        "annotation_pointer": f"/{row_index}/notes",
                        "annotation_count": (
                            len(row["notes"])
                            if isinstance(row.get("notes"), list)
                            else int("notes" in row)
                        ),
                        "annotation_content_hash": (
                            canonical_hash(row["notes"]) if "notes" in row else ""
                        ),
                        "volume_file": path.rsplit("/", 1)[-1],
                    },
                )
            )
    return units, excluded


def _parse_youmengying(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    path, rows = _single_array(spec, files)
    units: list[ParsedSourceUnit] = []
    excluded: list[dict[str, Any]] = []
    for index, value in enumerate(rows):
        row = _object(value, path, f"/{index}")
        comments = row.get("comment")
        if comments is not None:
            excluded.append(
                _excluded(path, f"/{index}/comment", "commentary", comments)
            )
        body_value = row.get("content")
        if not isinstance(body_value, str):
            raise CorpusParseError("JSON_BODY_INVALID", f"{path}#/{index}/content")
        units.append(
            _make_unit(
                spec=spec,
                ordinal=index + 1,
                kind="APHORISM",
                title=f"第{index + 1}则",
                author="张潮",
                body=body_value,
                raw_file_path=path,
                raw_file_hash=_bytes_hash(files[path]),
                source_locator={"kind": "JSON_POINTER", "path": path, "pointer": f"/{index}/content"},
                original_value=body_value,
                metadata={
                    "commentary_pointer": f"/{index}/comment",
                    "commentary_count": len(comments) if isinstance(comments, list) else 0,
                    "commentary_content_hash": canonical_hash(comments) if comments is not None else "",
                },
            )
        )
    return units, excluded


def _parse_lunyu(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    path, chapters = _single_array(spec, files)
    units: list[ParsedSourceUnit] = []
    ordinal = 0
    for chapter_index, value in enumerate(chapters):
        chapter = _object(value, path, f"/{chapter_index}")
        paragraphs = _array(
            chapter.get("paragraphs"), path, f"/{chapter_index}/paragraphs"
        )
        chapter_title = str(chapter.get("chapter") or f"第{chapter_index + 1}篇")
        for paragraph_index, paragraph in enumerate(paragraphs):
            if not isinstance(paragraph, str):
                raise CorpusParseError(
                    "JSON_BODY_INVALID",
                    f"{path}#/{chapter_index}/paragraphs/{paragraph_index}",
                )
            ordinal += 1
            pointer = f"/{chapter_index}/paragraphs/{paragraph_index}"
            units.append(
                _make_unit(
                    spec=spec,
                    ordinal=ordinal,
                    kind="APHORISM",
                    title=f"{chapter_title}·{paragraph_index + 1}",
                    author="孔子及弟子",
                    body=paragraph,
                    raw_file_path=path,
                    raw_file_hash=_bytes_hash(files[path]),
                    source_locator={"kind": "JSON_POINTER", "path": path, "pointer": pointer},
                    original_value=paragraph,
                    metadata={
                        "chapter": chapter_title,
                        "chapter_index": chapter_index,
                        "paragraph_index": paragraph_index,
                    },
                )
            )
    return units, []


def _parse_shenglvqimeng(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    path = _only_path(spec, files)
    root = _object(_load_json(files, path), path, "")
    excluded: list[dict[str, Any]] = []
    if root.get("abstract"):
        excluded.append(_excluded(path, "/abstract", "abstract", root["abstract"]))
    volumes = _array(root.get("content"), path, "/content")
    author = str(root.get("author") or "")
    units: list[ParsedSourceUnit] = []
    ordinal = 0
    for volume_index, volume_value in enumerate(volumes):
        volume = _object(volume_value, path, f"/content/{volume_index}")
        volume_title = str(volume.get("title") or f"卷{volume_index + 1}")
        sections = _array(
            volume.get("content"), path, f"/content/{volume_index}/content"
        )
        for section_index, section_value in enumerate(sections):
            section = _object(
                section_value,
                path,
                f"/content/{volume_index}/content/{section_index}",
            )
            ordinal += 1
            pointer = f"/content/{volume_index}/content/{section_index}/paragraphs"
            units.append(
                _json_lines_unit(
                    spec,
                    ordinal=ordinal,
                    path=path,
                    raw_file_hash=_bytes_hash(files[path]),
                    pointer=pointer,
                    row=section,
                    body_field="paragraphs",
                    title_field="chapter",
                    author=author,
                    kind="DIDACTIC_SECTION",
                    excluded_metadata={"volume": volume_title},
                )
            )
    return units, excluded


def _parse_tangshisanbaishou(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[list[ParsedSourceUnit], list[dict[str, Any]]]:
    path = _only_path(spec, files)
    root = _object(_load_json(files, path), path, "")
    groups = _array(root.get("content"), path, "/content")
    units: list[ParsedSourceUnit] = []
    ordinal = 0
    for group_index, group_value in enumerate(groups):
        group = _object(group_value, path, f"/content/{group_index}")
        group_title = str(group.get("type") or f"组{group_index + 1}")
        poems = _array(group.get("content"), path, f"/content/{group_index}/content")
        for poem_index, poem_value in enumerate(poems):
            poem = _object(
                poem_value, path, f"/content/{group_index}/content/{poem_index}"
            )
            ordinal += 1
            pointer = f"/content/{group_index}/content/{poem_index}/paragraphs"
            units.append(
                _json_lines_unit(
                    spec,
                    ordinal=ordinal,
                    path=path,
                    raw_file_hash=_bytes_hash(files[path]),
                    pointer=pointer,
                    row=poem,
                    body_field="paragraphs",
                    title_field="chapter",
                    author=str(poem.get("author") or ""),
                    kind="POEM",
                    excluded_metadata={
                        "group": group_title,
                        "alternate_title": str(poem.get("subchapter") or ""),
                    },
                )
            )
    return units, []


def _json_lines_unit(
    spec: CorpusWorkSpec,
    *,
    ordinal: int,
    path: str,
    raw_file_hash: str,
    pointer: str,
    row: Mapping[str, Any],
    body_field: str,
    title_field: str,
    author: str,
    kind: str,
    metadata_fields: tuple[str, ...] = (),
    excluded_metadata: Mapping[str, Any] | None = None,
) -> ParsedSourceUnit:
    lines = _array(row.get(body_field), path, pointer)
    if any(not isinstance(line, str) for line in lines):
        raise CorpusParseError("JSON_BODY_INVALID", f"{path}#{pointer}")
    title = row.get(title_field)
    if not isinstance(title, str):
        raise CorpusParseError("JSON_TITLE_INVALID", f"{path}#{pointer}")
    metadata = {
        key: str(row.get(key) or "")
        for key in metadata_fields
        if row.get(key) is not None
    }
    metadata.update(dict(excluded_metadata or {}))
    if not title.strip():
        title = f"未题·仓库第{ordinal}项"
        metadata["title_source_status"] = "MISSING"
    return _make_unit(
        spec=spec,
        ordinal=ordinal,
        kind=kind,
        title=title,
        author=author,
        body="\n".join(lines),
        raw_file_path=path,
        raw_file_hash=raw_file_hash,
        source_locator={"kind": "JSON_POINTER", "path": path, "pointer": pointer},
        original_value=lines,
        metadata=metadata,
    )


def _make_unit(
    *,
    spec: CorpusWorkSpec,
    ordinal: int,
    kind: str,
    title: str,
    author: str,
    body: str,
    raw_file_path: str,
    raw_file_hash: str,
    source_locator: dict[str, Any],
    original_value: Any,
    metadata: dict[str, Any],
) -> ParsedSourceUnit:
    normalized = _normalize_body(body)
    content_hash = _text_hash(normalized)
    original_hash = canonical_hash(original_value)
    unit_key = canonical_hash(
        {
            "work_key": spec.work_key,
            "ordinal": ordinal,
            "kind": kind,
            "locator": source_locator,
        }
    ).removeprefix("sha256:")
    unit_id = f"source-unit:{unit_key}"
    version_key = canonical_hash(
        {
            "unit_id": unit_id,
            "parser": spec.parser_profile,
            "original_content_hash": original_hash,
            "normalized_content_hash": content_hash,
        }
    ).removeprefix("sha256:")
    return ParsedSourceUnit(
        unit_id=unit_id,
        unit_version_id=f"source-unit-version:{version_key}",
        ordinal=ordinal,
        kind=kind,
        title=_short_text(title, "title"),
        author=_short_text(author, "author", allow_empty=True),
        body=normalized,
        raw_file_path=raw_file_path,
        raw_file_hash=raw_file_hash,
        source_locator=source_locator,
        original_content_hash=original_hash,
        normalized_content_hash=content_hash,
        character_count=len(normalized),
        line_count=len(normalized.splitlines()) if normalized else 0,
        metadata=metadata,
        status="AVAILABLE" if normalized else "EMPTY",
    )


def _finalize_units(
    spec: CorpusWorkSpec,
    units: Iterable[ParsedSourceUnit],
    *,
    max_chunk_bytes: int,
    normalization_version: str,
) -> tuple[tuple[ParsedSourceUnit, ...], NormalizedSource, tuple[NormalizedChunk, ...]]:
    ordered = tuple(sorted(units, key=lambda item: item.ordinal))
    if not ordered or [item.ordinal for item in ordered] != list(
        range(1, len(ordered) + 1)
    ):
        raise CorpusParseError("CORPUS_UNIT_ORDER_INVALID", spec.work_key)
    available = [item for item in ordered if item.status == "AVAILABLE"]
    if not available:
        raise CorpusParseError("CORPUS_BODY_EMPTY", spec.work_key)
    pieces: list[str] = []
    finalized: list[ParsedSourceUnit] = []
    chunks: list[NormalizedChunk] = []
    byte_offset = 0
    character_offset = 0
    available_index = 0
    chunk_index = 0
    for unit in ordered:
        if unit.status != "AVAILABLE":
            finalized.append(unit)
            continue
        available_index += 1
        separator = "\n" if available_index == len(available) else "\n\n"
        piece = unit.body + separator
        body_bytes = unit.body.encode("utf-8")
        finalized.append(
            replace(
                unit,
                normalized_byte_start=byte_offset,
                normalized_byte_end=byte_offset + len(body_bytes),
                normalized_character_start=character_offset,
                normalized_character_end=character_offset + len(unit.body),
            )
        )
        piece_bytes = piece.encode("utf-8")
        for chunk in _chunk_unit_piece(
            piece,
            unit_id=unit.unit_id,
            first_chunk_index=chunk_index,
            normalized_byte_offset=byte_offset,
            max_chunk_bytes=max_chunk_bytes,
        ):
            chunks.append(
                chunk
            )
            chunk_index += 1
        pieces.append(piece)
        byte_offset += len(piece_bytes)
        character_offset += len(piece)
    text = "".join(pieces)
    encoded = text.encode("utf-8")
    if b"".join(item.content for item in chunks) != encoded:
        raise RuntimeError("source work chunking changed normalized content")
    normalized = NormalizedSource(
        text=text,
        encoding="utf-8",
        media_type="text/plain",
        source_format="source_work_projection",
        normalization_version=normalization_version,
        content_hash=_bytes_hash(encoded),
        byte_size=len(encoded),
        character_count=len(text),
        structural_markers=(),
    )
    return tuple(finalized), normalized, tuple(chunks)


def _chunk_unit_piece(
    text: str,
    *,
    unit_id: str,
    first_chunk_index: int,
    normalized_byte_offset: int,
    max_chunk_bytes: int,
) -> tuple[NormalizedChunk, ...]:
    if max_chunk_bytes < 256:
        raise ValueError("max_chunk_bytes is too small")
    pieces: list[str] = []
    start = 0
    while start < len(text):
        low, high = start + 1, len(text)
        best = start
        while low <= high:
            middle = (low + high) // 2
            if len(text[start:middle].encode("utf-8")) <= max_chunk_bytes:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best == start:
            raise RuntimeError("one source character exceeds the chunk byte limit")
        split = best
        if best < len(text):
            window = text[start:best]
            boundary = max(
                window.rfind("\n"),
                window.rfind("。"),
                window.rfind("；"),
                window.rfind("！"),
                window.rfind("？"),
            )
            if boundary >= max(1, len(window) // 2):
                split = start + boundary + 1
        pieces.append(text[start:split])
        start = split
    chunks: list[NormalizedChunk] = []
    offset = normalized_byte_offset
    for local_index, piece in enumerate(pieces):
        content = piece.encode("utf-8")
        cjk = sum("\u3400" <= character <= "\u9fff" for character in piece)
        other = max(0, len(piece) - cjk)
        chunks.append(
            NormalizedChunk(
                chunk_index=first_chunk_index + local_index,
                content=content,
                content_hash=_bytes_hash(content),
                byte_size=len(content),
                character_count=len(piece),
                token_count=max(1, cjk + math.ceil(other / 4)),
                normalized_byte_start=offset,
                normalized_byte_end=offset + len(content),
                structural_label=f"{unit_id}:segment-{local_index + 1}",
            )
        )
        offset += len(content)
    if "".join(pieces) != text:
        raise RuntimeError("unit chunking changed normalized content")
    return tuple(chunks)


def _unit_diagnostics(units: Iterable[ParsedSourceUnit]) -> dict[str, Any]:
    rows = tuple(units)
    titles: dict[str, list[int]] = {}
    contents: dict[str, list[int]] = {}
    kinds: dict[str, int] = {}
    for item in rows:
        titles.setdefault(item.title, []).append(item.ordinal)
        contents.setdefault(item.normalized_content_hash, []).append(item.ordinal)
        kinds[item.kind] = kinds.get(item.kind, 0) + 1
    return {
        "unit_kind_counts": dict(sorted(kinds.items())),
        "empty_unit_ordinals": [item.ordinal for item in rows if item.status == "EMPTY"],
        "missing_title_ordinals": [
            item.ordinal
            for item in rows
            if item.metadata.get("title_source_status") == "MISSING"
        ],
        "duplicate_title_groups": [
            {"title": title, "ordinals": ordinals}
            for title, ordinals in sorted(titles.items())
            if len(ordinals) > 1
        ],
        "duplicate_content_groups": [
            {"content_hash": digest, "ordinals": ordinals}
            for digest, ordinals in sorted(contents.items())
            if len(ordinals) > 1
        ],
    }


def _novel_unit_kind(title: str, collection_kind: str) -> str:
    compact = title.strip().replace("　", " ")
    if re.match(r"^(前言|序言|序|自序|凡例)(?:\s|$)", compact):
        return "PREFACE"
    if re.match(r"^(附录|附錄|后记|後記|跋)(?:\s|$)", compact):
        return "APPENDIX"
    if collection_kind == "SHORT_STORY_COLLECTION":
        return "STORY"
    return "CHAPTER"


class _GovernedHTMLExtractor(HTMLParser):
    _BLOCKS = frozenset(
        {"p", "div", "li", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}
    )
    _IGNORED = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self._line_char_starts = [0]
        self._line_byte_starts = [0]
        char_total = 0
        byte_total = 0
        for line in source.splitlines(keepends=True):
            char_total += len(line)
            byte_total += len(line.encode("utf-8"))
            self._line_char_starts.append(char_total)
            self._line_byte_starts.append(byte_total)
        self._ignored_depth = 0
        self._parts: list[tuple[str, int, int]] = []
        self.paragraphs: list[tuple[str, int, int]] = []

    def _position(self) -> tuple[int, int]:
        line, column = self.getpos()
        line_index = max(0, line - 1)
        char_start = self._line_char_starts[line_index] + column
        byte_start = self._line_byte_starts[line_index] + len(
            self.source[self._line_char_starts[line_index] : char_start].encode("utf-8")
        )
        return char_start, byte_start

    def _append(self, value: str, token_length: int) -> None:
        if self._ignored_depth or not value:
            return
        char_start, byte_start = self._position()
        raw_token = self.source[char_start : char_start + token_length]
        byte_end = byte_start + len(raw_token.encode("utf-8"))
        cursor = byte_start
        parts = re.split(r"(\r\n|\r|\n)", value)
        for part in parts:
            if part in {"\r", "\n", "\r\n"}:
                self._flush()
                cursor += len(part.encode("utf-8"))
                continue
            if part:
                size = len(part.encode("utf-8"))
                self._parts.append((part, cursor, min(byte_end, cursor + size)))
                cursor += size

    def _flush(self) -> None:
        if not self._parts:
            return
        text = _HORIZONTAL_SPACE.sub(" ", "".join(item[0] for item in self._parts)).strip()
        if text:
            self.paragraphs.append((text, self._parts[0][1], self._parts[-1][2]))
        self._parts.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in self._IGNORED:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "br" or tag in self._BLOCKS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._IGNORED:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if not self._ignored_depth and tag in self._BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        self._append(data, len(data))

    def handle_entityref(self, name: str) -> None:
        token = f"&{name};"
        self._append(unescape(token), len(token))

    def handle_charref(self, name: str) -> None:
        token = f"&#{name};"
        self._append(unescape(token), len(token))

    def close(self) -> None:
        super().close()
        self._flush()


def extract_governed_html(source: str) -> tuple[str, list[dict[str, int]]]:
    parser = _GovernedHTMLExtractor(source)
    parser.feed(source)
    parser.close()
    paragraphs = parser.paragraphs
    body = "\n".join(item[0] for item in paragraphs)
    spans: list[dict[str, int]] = []
    offset = 0
    for text, raw_start, raw_end in paragraphs:
        size = len(text.encode("utf-8"))
        spans.append(
            {
                "raw_byte_start": raw_start,
                "raw_byte_end": raw_end,
                "normalized_byte_start": offset,
                "normalized_byte_end": offset + size,
            }
        )
        offset += size + 1
    return _normalize_body(body), spans


def _excluded(
    path: str, pointer: str, field: str, value: Any
) -> dict[str, Any]:
    return {
        "path": path,
        "locator": pointer,
        "field": field,
        "item_count": len(value) if isinstance(value, list) else 1,
        "content_hash": canonical_hash(value),
        "reason": "typed metadata excluded from body projection",
    }


def _load_json(files: Mapping[str, bytes], path: str) -> Any:
    try:
        raw = files[path]
    except KeyError as exc:
        raise CorpusParseError("CORPUS_REQUIRED_FILE_MISSING", path) from exc
    try:
        return json.loads(_decode_text(raw, path))
    except json.JSONDecodeError as exc:
        raise CorpusParseError(
            "CORPUS_JSON_INVALID", f"{path}:{exc.lineno}:{exc.colno}"
        ) from exc


def _decode_text(raw: bytes, path: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
    raise CorpusParseError("CORPUS_ENCODING_UNSUPPORTED", path)


def _single_array(
    spec: CorpusWorkSpec, files: Mapping[str, bytes]
) -> tuple[str, list[Any]]:
    path = _only_path(spec, files)
    return path, _array(_load_json(files, path), path, "")


def _only_path(spec: CorpusWorkSpec, files: Mapping[str, bytes]) -> str:
    if len(spec.paths) != 1 or set(files) != set(spec.paths):
        raise CorpusParseError(
            "CORPUS_FILE_SET_INVALID",
            f"{spec.work_key}: expected={list(spec.paths)} actual={sorted(files)}",
        )
    return spec.paths[0]


def _array(value: Any, path: str, pointer: str) -> list[Any]:
    if not isinstance(value, list):
        raise CorpusParseError("CORPUS_JSON_ARRAY_REQUIRED", f"{path}#{pointer}")
    return value


def _object(value: Any, path: str, pointer: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CorpusParseError("CORPUS_JSON_OBJECT_REQUIRED", f"{path}#{pointer}")
    return value


def _normalize_body(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    lines = [_HORIZONTAL_SPACE.sub(" ", line).rstrip() for line in normalized.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _short_text(value: str, label: str, *, allow_empty: bool = False) -> str:
    normalized = _HORIZONTAL_SPACE.sub(" ", unicodedata.normalize("NFC", value)).strip()
    if (not normalized and not allow_empty) or len(normalized) > 500:
        raise CorpusParseError("CORPUS_METADATA_INVALID", label)
    return normalized


def _bytes_hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _text_hash(value: str) -> str:
    return _bytes_hash(value.encode("utf-8"))


__all__ = [
    "CorpusParseError",
    "CorpusWorkSpec",
    "ParsedSourceUnit",
    "ParsedSourceWork",
    "REGISTRY_PATH",
    "SUPPORTED_PARSERS",
    "canonical_hash",
    "corpus_registry_hash",
    "extract_governed_html",
    "load_corpus_registry",
    "parse_classical_work",
    "resolve_work_spec",
]
