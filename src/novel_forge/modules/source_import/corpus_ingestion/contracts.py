from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

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


class ParserProfile(CorpusContract):
    version: Literal["corpus-parser.v1"] = "corpus-parser.v1"
    format: Literal["txt", "epub", "html", "json", "jsonl", "parquet"]
    work_key_encoding: Literal["VALUE", "SHA256"] = "VALUE"
    encoding: Literal["utf-8", "utf-8-sig", "gb18030", "gbk", "big5", "utf-16"] = (
        "utf-8"
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
