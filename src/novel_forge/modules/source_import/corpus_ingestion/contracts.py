from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator, model_serializer

from novel_forge.modules.source_authority.corpus import (
    CorpusContract,
    CorpusPurpose,
    Digest,
    Identity,
    Text,
    corpus_hash,
)


class IngestionFailure(ValueError):
    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        super().__init__(f"{reason}: {detail}" if detail else reason)


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(char) < 32 for char in value)
    ):
        raise IngestionFailure("UNSAFE_PATH", value[:160])
    return path.as_posix()


class IngestionBudget(CorpusContract):
    version: Literal["corpus-resource-policy.v1"] = "corpus-resource-policy.v1"
    max_files: int = Field(default=100, ge=1, le=1000)
    max_file_bytes: int = Field(default=64_000_000, ge=1, le=4_000_000_000)
    max_total_bytes: int = Field(default=256_000_000, ge=1, le=16_000_000_000)
    max_expanded_bytes: int = Field(default=512_000_000, ge=1, le=32_000_000_000)
    max_archive_ratio: int = Field(default=100, ge=1, le=200)
    max_records: int = Field(default=10_000, ge=1, le=1_000_000)
    max_works: int = Field(default=100, ge=1, le=1000)
    max_units_per_work: int = Field(default=2000, ge=1, le=10_000)
    max_record_bytes: int = Field(default=2_000_000, ge=1024, le=8_000_000)
    max_work_bytes: int = Field(default=16_000_000, ge=1024, le=64_000_000)
    max_chunk_bytes: int = Field(default=12_000, ge=256, le=64_000)
    memory_bytes: int = Field(default=256_000_000, ge=64_000_000, le=2_000_000_000)
    min_free_disk_bytes: int = Field(default=256_000_000, ge=0)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    max_retries: int = Field(default=2, ge=0, le=3)
    concurrency: Literal[1] = 1

    @model_validator(mode="after")
    def bounded_working_set(self) -> IngestionBudget:
        if self.max_file_bytes > self.max_total_bytes:
            raise ValueError("file limit exceeds total acquisition limit")
        if self.max_work_bytes * 8 > self.memory_bytes:
            raise ValueError(
                "memory must cover the bounded per-work Unicode/serialization working set"
            )
        if self.max_record_bytes > self.max_work_bytes:
            raise ValueError("record limit exceeds work limit")
        return self


class SourceBoundary(CorpusContract):
    path: Text
    checksum: Digest
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    title: str = Field(default="", max_length=2048)
    kind: Literal["CHAPTER", "EXTRA", "AUTHOR_NOTE", "VOLUME", "UNSTRUCTURED"] = (
        "CHAPTER"
    )
    number: int | None = Field(default=None, ge=0)
    volume: str = Field(default="", max_length=2048)
    evidence: Text

    @model_validator(mode="after")
    def positive_span(self) -> SourceBoundary:
        if self.end <= self.start:
            raise ValueError("boundary must cover a positive exact raw span")
        safe_relative_path(self.path)
        return self


class NormalizationProfile(CorpusContract):
    version: Literal["chinese-longform.v1", "chinese-longform.v2"] = (
        "chinese-longform.v1"
    )
    duplicate_body_min_chars: int = Field(default=128, ge=32, le=10000)

    @model_serializer(mode="wrap")
    def frozen_profile(self, handler: Any) -> dict[str, Any]:
        result = handler(self)
        if self.version == "chinese-longform.v1":
            result.pop("duplicate_body_min_chars", None)
        return result

    unicode_form: Literal["NFC", "NONE"] = "NFC"
    segmentation: Literal["EXPLICIT", "CHINESE_HEADINGS"] = "CHINESE_HEADINGS"
    heading_max_chars: int = Field(default=100, ge=8, le=200)
    min_body_chars: int = Field(default=80, ge=1, le=10000)
    max_unit_bytes: int = Field(default=2_000_000, ge=1024, le=8_000_000)
    expected_toc: tuple[str, ...] = Field(default=(), max_length=10000)
    toc_evidence: str = Field(default="", max_length=2048)
    candidate_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    boundaries: tuple[SourceBoundary, ...] = Field(default=(), max_length=10000)
    external_work_ids: tuple[str, ...] = Field(default=(), max_length=16)
    work_completion: Literal["FINISHED", "ONGOING", "UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def require_toc_evidence(self) -> NormalizationProfile:
        if self.expected_toc and not self.toc_evidence:
            raise ValueError("expected ToC needs an exact evidence locator")
        return self


class EpubContinuation(CorpusContract):
    left_href: str
    right_href: str
    checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence: str = Field(min_length=1, max_length=2048)


class ParserProfile(CorpusContract):
    version: Literal[
        "corpus-parser.v1", "corpus-parser.v2", "corpus-parser.v3", "corpus-parser.v4"
    ] = "corpus-parser.v1"
    normalization: NormalizationProfile | None = None

    @model_serializer(mode="wrap")
    def preserve_frozen_v1(self, handler: Any) -> dict[str, Any]:
        result = handler(self)
        if self.version != "corpus-parser.v4":
            result.pop("epub_continuations", None)
        if self.normalization is None:
            result.pop("normalization", None)
        return result

    format: Literal["txt", "epub", "html", "json", "jsonl", "parquet"]
    work_key_encoding: Literal["VALUE", "SHA256"] = "VALUE"
    encoding: Literal["utf-8", "utf-8-sig", "gb18030", "gbk", "big5", "utf-16"] = (
        "utf-8"
    )
    epub_continuations: tuple[EpubContinuation, ...] = Field(
        default=(), max_length=1000
    )
    records_path: str = Field(default="item", max_length=256)
    layout: Literal["WORK_ROWS", "CHAPTER_ROWS", "SINGLE_WORK"] = "SINGLE_WORK"
    fields: dict[str, str] = Field(
        default_factory=lambda: {"text": "text"}, max_length=16
    )
    constants: dict[str, str | int] = Field(default_factory=dict, max_length=16)
    html_body_selector: str = Field(default="body", min_length=1, max_length=256)
    html_remove_selectors: tuple[str, ...] = (
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "noscript",
    )
    completeness: Literal["COMPLETE", "EXCERPT", "UNKNOWN"] = "UNKNOWN"
    expected_units: int | None = Field(default=None, ge=1, le=10000)
    filters: dict[str, str | int | bool] = Field(default_factory=dict, max_length=8)

    @model_validator(mode="after")
    def mapping_contract(self) -> ParserProfile:
        if self.epub_continuations and (
            self.version != "corpus-parser.v4" or self.format != "epub"
        ):
            raise ValueError("continuation evidence requires EPUB parser v4")
        if self.normalization is not None and self.version not in {
            "corpus-parser.v2",
            "corpus-parser.v3",
            "corpus-parser.v4",
        }:
            raise ValueError(
                "normalization requires corpus-parser.v2; frozen v1 is not reinterpreted"
            )
        if self.version in {"corpus-parser.v3", "corpus-parser.v4"} and (
            self.normalization is None
            or self.normalization.version != "chinese-longform.v2"
        ):
            raise ValueError("parser v3 requires chinese-longform.v2")
        if (
            self.normalization
            and self.normalization.version == "chinese-longform.v2"
            and self.version not in {"corpus-parser.v3", "corpus-parser.v4"}
        ):
            raise ValueError("new integrity semantics require parser v3")
        if self.format in {"epub", "parquet"} and self.encoding != "utf-8":
            raise ValueError(
                "container-defined encoding: EPUB/Parquet do not accept a text encoding override"
            )
        allowed = {
            "work_id",
            "edition_id",
            "chapter_id",
            "order",
            "title",
            "work_title",
            "text",
            "volume",
            "author",
        }
        if set(self.fields) - allowed or set(self.constants) - allowed:
            raise ValueError("unsupported mapping key")
        if any(
            not re.fullmatch(r"[\w-]+(?:\.[\w-]+)*", value)
            for value in (*self.fields.values(), *self.filters)
        ):
            raise ValueError(
                "field mappings are dotted keys, never executable expressions"
            )
        if not re.fullmatch(r"[\w.-]+", self.records_path):
            raise ValueError("records_path must be an ijson field/item prefix")
        if self.layout == "CHAPTER_ROWS" and not all(
            key in self.fields or key in self.constants
            for key in ("work_id", "chapter_id", "order")
        ):
            raise ValueError(
                "chapter rows require explicit work, chapter and order mappings"
            )
        if self.completeness == "COMPLETE" and self.expected_units is None:
            raise ValueError("complete works require a verifiable expected unit count")
        if self.format in {"txt", "epub", "html"} and self.layout != "SINGLE_WORK":
            raise ValueError(
                "text/container documents use SINGLE_WORK with explicit structural units"
            )
        return self


class IngestionFile(CorpusContract):
    path: Text
    checksum: Digest | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    parser: ParserProfile | None = None

    @model_validator(mode="after")
    def safe_path(self) -> IngestionFile:
        safe_relative_path(self.path)
        return self


class SourceLocator(CorpusContract):
    kind: Literal["LOCAL", "GITHUB", "HUGGING_FACE", "INTERNET_ARCHIVE"]
    location: Text
    revision: str = Field(default="", max_length=128)
    config: str = Field(default="", max_length=128)
    split: str = Field(default="", max_length=128)
    files: tuple[IngestionFile, ...] = Field(default=(), max_length=1000)
    include: tuple[Text, ...] = ("*", "**/*")
    exclude: tuple[Text, ...] = (".git/**", "**/.git/**", ".DS_Store")

    @model_validator(mode="before")
    @classmethod
    def canonical_local_locator(cls, value: Any) -> Any:
        if (
            isinstance(value, dict)
            and value.get("kind") == "LOCAL"
            and isinstance(value.get("location"), str)
        ):
            path = Path(value["location"]).expanduser().absolute()
            if ".." in path.parts:
                raise ValueError("local source must not contain parent traversal")
            return {**value, "location": str(path)}
        return value

    @model_validator(mode="after")
    def exact_source(self) -> SourceLocator:
        if self.kind == "GITHUB":
            parsed = urlsplit(self.location)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "github.com"
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or parsed.port
            ):
                raise ValueError(
                    "GitHub requires a credential-free https://github.com repository URL"
                )
        elif self.kind in {"HUGGING_FACE", "INTERNET_ARCHIVE"}:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", self.location):
                raise ValueError(
                    "remote source requires dataset/item identity, not a credential URL"
                )
        if self.kind in {"GITHUB", "HUGGING_FACE"} and not re.fullmatch(
            r"[0-9a-f]{40}", self.revision
        ):
            raise ValueError("GitHub/Hugging Face require a full frozen commit")
        if self.kind != "LOCAL" and not self.files:
            raise ValueError("remote discovery requires an explicit bounded file list")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("duplicate source paths")
        return self


class IngestionManifest(CorpusContract):
    schema_version: Literal["corpus-ingestion-manifest.v1"] = (
        "corpus-ingestion-manifest.v1"
    )
    adapter_version: Literal["corpus-adapters.v1"] = "corpus-adapters.v1"
    source: SourceLocator
    parser: ParserProfile
    purpose: CorpusPurpose
    rights: dict[str, Any]
    source_id: Identity | None = None
    rights_id: Identity | None = None
    previous_snapshot_id: Identity | None = None
    budget: IngestionBudget = Field(default_factory=IngestionBudget)
    analyze: bool = False

    @property
    def identity(self) -> str:
        return corpus_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def no_ambient_authorization(self) -> IngestionManifest:
        if len(self.source.files) > self.budget.max_files:
            raise ValueError("file selection exceeds frozen budget")
        if bool(self.source_id) != bool(self.rights_id):
            raise ValueError("existing sources require an exact rights reference")
        if self.purpose == CorpusPurpose.BENCHMARK and self.analyze:
            raise ValueError(
                "Benchmark data cannot enter the production Source analysis pipeline"
            )
        return self
