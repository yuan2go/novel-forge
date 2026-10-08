from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2048, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class MarketContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def official_url(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.hostname != "www.qidian.com"
        or url.username
        or url.password
        or url.port not in {None, 443}
        or url.fragment
    ):
        raise ValueError("Only an exact official HTTPS Qidian URL is admitted")
    return urlunsplit(("https", "www.qidian.com", url.path or "/", url.query, ""))


class UseScope(MarketContract):
    scope_version: Literal["source-use-scope.v1"] = "source-use-scope.v1"
    acquire: Literal["ALLOW", "DENY", "UNKNOWN"] = "UNKNOWN"
    save: Literal["ALLOW", "DENY", "UNKNOWN"] = "UNKNOWN"
    analyze: Literal["ALLOW", "DENY", "UNKNOWN"] = "UNKNOWN"
    cloud_model: Literal["ALLOW", "DENY", "UNKNOWN"] = "UNKNOWN"
    abstract_use: Literal["ALLOW", "DENY", "UNKNOWN"] = "UNKNOWN"
    training: Literal["ALLOW", "DENY", "UNKNOWN"] = "DENY"
    evidence_refs: tuple[Text, ...] = Field(min_length=1, max_length=20)
    access_rules_ref: Text
    terms_ref: Text
    reviewed_at: datetime
    expires_at: datetime
    retention_days: int = Field(default=30, ge=1, le=3650)

    @model_validator(mode="after")
    def timestamps(self) -> UseScope:
        if (
            any(t.tzinfo is None for t in (self.reviewed_at, self.expires_at))
            or self.expires_at <= self.reviewed_at
        ):
            raise ValueError("Rights need timezone-aware review and expiry")
        return self

    def require_metadata(self, now: datetime) -> None:
        if (
            self.acquire != "ALLOW"
            or self.save != "ALLOW"
            or not self.reviewed_at <= now < self.expires_at
        ):
            raise ValueError(
                "MARKET_USE_NOT_AUTHORIZED: acquisition/storage evidence absent or expired"
            )

    def require_use(self, use: str, now: datetime) -> None:
        permissions = {
            "LOCAL_PROCESSING": (self.acquire, self.save),
            "SOURCE_ANALYSIS": (self.analyze, self.cloud_model),
            "ABSTRACT_GENERATION": (self.abstract_use,),
        }
        if not self.reviewed_at <= now < self.expires_at or any(
            permission != "ALLOW" for permission in permissions[use]
        ):
            raise ValueError("CORPUS_PURPOSE_SCOPE_NOT_GRANTED:" + use)


class UpdatePolicy(MarketContract):
    enabled: bool = False
    interval_seconds: int = Field(default=86400, ge=60, le=2678400)
    site_min_interval_seconds: int = Field(default=10, ge=1, le=3600)
    timeout_seconds: int = Field(default=20, ge=1, le=60)
    retries: int = Field(default=2, ge=0, le=3)
    max_backoff_seconds: int = Field(default=60, ge=1, le=300)
    top_n: int = Field(default=20, ge=1, le=100)
    page_size: int = Field(default=20, ge=1, le=100)
    max_pages: int = Field(default=5, ge=1, le=10)
    max_response_bytes: int = Field(default=1000000, ge=1024, le=4000000)
    stale_after_seconds: int = Field(default=172800, ge=60, le=2678400)

    @model_validator(mode="after")
    def bounded(self) -> UpdatePolicy:
        if (
            self.top_n > self.page_size * self.max_pages
            or self.interval_seconds < self.site_min_interval_seconds
        ):
            raise ValueError("Update range/interval exceeds the frozen site policy")
        return self


class RankDefinition(MarketContract):
    schema_version: Literal["source-market-rank-definition.v1"] = (
        "source-market-rank-definition.v1"
    )
    platform: Literal["qidian"] = "qidian"
    key: Text
    official_name: Text
    category: Literal["ALL", "XUANHUAN", "WUXIA", "XIANXIA"]
    category_label: Text
    period: Text
    metric_label: Text
    metric_explanation: Text
    url: Text
    page_urls: tuple[Text, ...] = Field(default=(), max_length=10)
    comparison_mode: Literal["FIXED_WINDOW", "ROLLING_WINDOW", "UNKNOWN"] = "UNKNOWN"
    navigation_ref: Text
    navigation_verified_at: datetime | None = None
    support: Literal["VERIFIED", "UNVERIFIED", "UNSUPPORTED"] = "UNVERIFIED"
    parser_version: Literal["qidian-rank-html.v1", "authorized-rank-json.v1"]
    period_selector: Annotated[str, Field(max_length=200)] = ""
    category_selector: Annotated[str, Field(max_length=200)] = ""
    update: UpdatePolicy = Field(default_factory=UpdatePolicy)

    @model_validator(mode="after")
    def verified(self) -> RankDefinition:
        official_url(self.url)
        for url in self.page_urls:
            official_url(url)
        if (
            self.parser_version == "qidian-rank-html.v1"
            and self.update.top_n > self.update.page_size
            and len(self.page_urls)
            < (self.update.top_n + self.update.page_size - 1) // self.update.page_size
        ):
            raise ValueError(
                "Multiple-page updates require frozen official pagination URLs"
            )
        if self.support == "VERIFIED" and (
            not self.navigation_verified_at
            or self.navigation_verified_at.tzinfo is None
        ):
            raise ValueError(
                "Verified rank names/filters require actual dated navigation evidence"
            )
        if self.update.enabled and (
            self.support != "VERIFIED" or self.parser_version != "qidian-rank-html.v1"
        ):
            raise ValueError(
                "Unverified/file-only definitions cannot automatically fetch"
            )
        return self


class DefineMarketRank(MarketContract):
    action: Literal["define_market_rank"]
    source_id: Text
    previous_definition_id: str = ""
    resume_access: bool = False
    definition: RankDefinition
    use_scope: UseScope


class PublicMetric(MarketContract):
    label: Text
    value: Text
    source_locator: Text


class RankedWork(MarketContract):
    work_id: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    url: Text
    aliases: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(
        default=(), max_length=20
    )
    author: Annotated[str, Field(max_length=200)] = ""
    category: Annotated[str, Field(max_length=200)] = ""
    rank: int = Field(ge=1, le=10000)
    public_metrics: tuple[PublicMetric, ...] = Field(default=(), max_length=10)
    field_sources: dict[str, Text] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def stable_identity(self) -> RankedWork:
        if official_url(self.url) != f"https://www.qidian.com/book/{self.work_id}/":
            raise ValueError("Work ID must agree with its canonical URL")
        if not {"work_id", "title", "rank"} <= self.field_sources.keys():
            raise ValueError("Work identity/title/rank require exact field provenance")
        return self


class RankPage(MarketContract):
    page: int = Field(ge=1, le=10)
    url: Text
    content_hash: Digest
    entries: tuple[RankedWork, ...] = Field(default=(), max_length=100)


class ObserveMarketRank(MarketContract):
    schema_version: Literal["source-market-observation.v1"] = (
        "source-market-observation.v1"
    )
    action: Literal["observe_market_rank"]
    source_id: Text
    definition_id: Text
    acquisition: Literal["AUTHORIZED_FILE", "OWN_READING_NOTES", "OFFICIAL_PUBLIC_PAGE"]
    receipt_ref: Text
    fetch_operation_id: str = Field(default="", max_length=512)
    acquired_at: datetime
    observed_at: datetime
    site_data_at: datetime | None = None
    site_time_missing_reason: str = Field(default="", max_length=2048)
    period_value: Text
    requested_top_n: int = Field(ge=1, le=100)
    pages: tuple[RankPage, ...] = Field(default=(), max_length=10)
    status: Literal[
        "COMPLETE",
        "PARTIAL",
        "NOT_MODIFIED",
        "ACCESS_DENIED",
        "RATE_LIMITED",
        "CHALLENGE",
        "LOGIN_REQUIRED",
        "PARSE_DRIFT",
        "TIMEOUT",
        "UNSUPPORTED",
        "REVOKED",
        "REMOVED",
        "TRANSPORT_FAILURE",
    ]
    missing_reasons: tuple[Text, ...] = Field(default=(), max_length=20)
    etag: str = Field(default="", max_length=512)
    last_modified: str = Field(default="", max_length=512)

    @model_validator(mode="after")
    def coverage(self) -> ObserveMarketRank:
        times = [self.acquired_at, self.observed_at] + (
            [self.site_data_at] if self.site_data_at else []
        )
        if any(t.tzinfo is None for t in times) or self.acquired_at < self.observed_at:
            raise ValueError(
                "Observations/acquisition need ordered timezone-aware times"
            )
        if not self.site_data_at and not self.site_time_missing_reason:
            raise ValueError("Absent site time requires a reason")
        if self.site_data_at and self.site_data_at > self.acquired_at:
            raise ValueError("Site data time cannot be in the future")
        if self.status == "COMPLETE":
            if [p.page for p in self.pages] != list(range(1, len(self.pages) + 1)):
                raise ValueError(
                    "Complete observations require contiguous ordered pages"
                )
            entries = [e for p in self.pages for e in p.entries]
            if [e.rank for e in entries] != list(
                range(1, self.requested_top_n + 1)
            ) or len({e.work_id for e in entries}) != len(entries):
                raise ValueError(
                    "Complete Top N requires each rank once and distinct platform IDs"
                )
        elif not self.missing_reasons and self.status != "NOT_MODIFIED":
            raise ValueError("Incomplete/failed acquisition needs a reason")
        if self.status not in {"COMPLETE", "PARTIAL"} and self.pages:
            raise ValueError("A failed acquisition cannot provide a snapshot")
        return self


class LinkMarketEdition(MarketContract):
    action: Literal["link_market_edition"]
    source_id: Text
    book_source_id: Text
    edition_id: Text
    evidence_ref: Text


def observation_status(observation: dict, definition: dict, now: datetime) -> str:
    if observation["status"] != "COMPLETE":
        return observation["status"]
    moment = datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
    return (
        "STALE"
        if (now - moment).total_seconds() > definition["update"]["stale_after_seconds"]
        else "COMPLETE"
    )


def rank_changes(old: dict, new: dict, definition: dict | None = None) -> dict:
    if (
        not definition
        or definition.get("comparison_mode") != "FIXED_WINDOW"
        or old["status"] != "COMPLETE"
        or new["status"] != "COMPLETE"
        or old["definition_id"] != new["definition_id"]
        or old["period_value"] != new["period_value"]
        or old["requested_top_n"] != new["requested_top_n"]
    ):
        return {
            "comparable": False,
            "reason": "definition, period or complete coverage differs",
            "changes": [],
        }
    previous = {e["work_id"]: e["rank"] for p in old["pages"] for e in p["entries"]}
    current = {e["work_id"]: e["rank"] for p in new["pages"] for e in p["entries"]}
    return {
        "comparable": True,
        "changes": [
            {
                "work_id": key,
                "old_rank": previous.get(key),
                "new_rank": current.get(key),
                "delta": previous[key] - current[key]
                if key in previous and key in current
                else None,
                "status": "OBSERVED" if key in current else "OUTSIDE_OBSERVED_RANGE",
            }
            for key in sorted(previous.keys() | current.keys())
        ],
    }
