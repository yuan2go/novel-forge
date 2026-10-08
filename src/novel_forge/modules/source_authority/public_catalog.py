
from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


CATALOG_OPERATION = "source.public_catalog.capture"
CATALOG_VERSION = "1.0.0"
CATALOG_HANDLER = "novel_forge.source_authority.public_catalog_capture"
PARSER_VERSION = "qidian-public-catalog.v1"
BOARDS = frozenset(
    {
        "yuepiao",
        "hotsales",
        "readindex",
        "newfans",
        "recom",
        "collect",
        "signNewBkAll",
        "pubnewbook",
    }
)


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def public_url(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.hostname != "www.qidian.com"
        or url.username
        or url.password
        or url.port not in (None, 443)
        or url.query
        or url.fragment
        or not re.fullmatch(r"/(?:rank/[A-Za-z0-9_/-]+|book/[0-9]+/)", url.path)
    ):
        raise ValueError("PUBLIC_CATALOG_ORIGIN_FORBIDDEN")
    return value


class CatalogCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    platform: Literal["qidian"]
    url: str
    max_pages: int = Field(default=1, ge=1, le=5)
    cache_ttl_seconds: int = Field(default=900, ge=0, le=86400)
    page_timeout_seconds: int = Field(default=20, ge=1, le=30)
    minimum_interval_seconds: float = Field(default=2, ge=1, le=60)
    mode: Literal["LIVE_HTTP", "OFFLINE_AUTHORIZED_SNAPSHOT"] = "LIVE_HTTP"
    offline_pages: tuple[dict[str, str], ...] = ()
    authorization_ref: str = ""
    snapshot_scope: Literal["FULL_PAGE", "RENDERED_DOM_EXCERPT"] = "FULL_PAGE"

    @model_validator(mode="after")
    def validate_contract(self) -> CatalogCapture:
        public_url(self.url)
        if self.mode == "LIVE_HTTP" and (
            self.offline_pages
            or self.authorization_ref
            or self.snapshot_scope != "FULL_PAGE"
        ):
            raise ValueError("live capture cannot accept offline inputs")
        if self.mode == "OFFLINE_AUTHORIZED_SNAPSHOT":
            if (
                not self.authorization_ref.strip()
                or not 1 <= len(self.offline_pages) <= self.max_pages
            ):
                raise ValueError(
                    "offline snapshot requires exact pages and authorization"
                )
            if self.offline_pages[0].get("url") != self.url:
                raise ValueError("offline first page must match capture URL")
            for page in self.offline_pages:
                if set(page) != {"url", "path", "sha256", "acquired_at"}:
                    raise ValueError(
                        "offline page requires URL, path, hash and acquisition time"
                    )
                public_url(page["url"])
                acquired = datetime.fromisoformat(page["acquired_at"])
                if acquired.tzinfo is None or not re.fullmatch(
                    r"sha256:[0-9a-f]{64}", page["sha256"]
                ):
                    raise ValueError("offline time or hash is invalid")
        return self


def parse_page(html: bytes, url: str, acquired_at: str) -> dict[str, Any]:
    from bs4 import BeautifulSoup

    public_url(url)
    acquired = datetime.fromisoformat(acquired_at)
    if acquired.tzinfo is None:
        raise ValueError("catalog acquisition time requires timezone")
    soup = BeautifulSoup(html.decode("utf-8", errors="strict"), "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if not title or soup.select_one('script[src*="/probe.js"]'):
        raise ValueError("PUBLIC_CATALOG_ACCESS_CHALLENGE")
    period = re.search(r"(20\d\d)年(\d{1,2})月", title)
    result: dict[str, Any] = {
        "parser_version": PARSER_VERSION,
        "source_url": url,
        "raw_snapshot_hash": digest(html),
        "acquired_at": acquired_at,
        "data_time": None,
        "data_time_status": "NOT_PUBLISHED",
        "ranking_period": f"{period[1]}-{int(period[2]):02}" if period else None,
        "records": [],
        "next_url": None,
    }
    if urlsplit(url).path.startswith("/book/"):
        info = soup.select_one(".book-info-top, .book-info")
        if info is None or info.select_one("h1") is None:
            raise ValueError("PUBLIC_CATALOG_DETAIL_SCHEMA_CHANGED")
        record = {
            "work_id": urlsplit(url).path.split("/")[2],
            "title": info.select_one("h1").get_text(" ", strip=True),
            "author": (
                _text(info.select_one(".book-meta .author"))
                or _text(info.select_one(".writer"))
                or ""
            )
            .removeprefix("作者:")
            .strip()
            or None,
            "category": None,
            "subcategory": None,
            "serial_status": None,
            "synopsis": _text(soup.select_one(".book-intro-detail, .book-intro")),
            "synopsis_scope": "DETAIL",
            "detail_url": url,
            "rank": None,
            "board": None,
            "metric_value": None,
            "metric_status": "NOT_REQUESTED",
        }
        record["latest_update_time"] = (
            _text(info.select_one(".update-time")) or ""
        ).removeprefix("更新时间:") or None
        tags = info.select(".book-attribute a, .book-attribute span, .tag a, .tag span")
        for tag in tags:
            text = tag.get_text(strip=True)
            if text in {"连载", "完本"}:
                record["serial_status"] = text
            elif tag.name == "a" and record["category"] is None:
                record["category"] = text
            elif tag.name == "a" and record["subcategory"] is None:
                record["subcategory"] = text
        result["records"] = [record]
        return result
    board = urlsplit(url).path.split("/")[2]
    if board not in BOARDS:
        raise ValueError("PUBLIC_CATALOG_BOARD_UNSUPPORTED")
    rows = soup.select("li:has(.book-mid-info h2 a)")
    if not rows:
        raise ValueError("PUBLIC_CATALOG_LIST_SCHEMA_CHANGED")
    seen: dict[str, dict[str, Any]] = {}
    ranks: set[int] = set()
    for row in rows:
        name = row.select_one(".book-mid-info h2 a")
        detail = public_url(urljoin(url, str(name.get("href", ""))))
        rank_text = _text(row.select_one(".rank-tag"))
        if not rank_text or not re.fullmatch(r"[0-9]+", rank_text):
            raise ValueError("PUBLIC_CATALOG_RANK_MISSING")
        author = row.select_one("p.author")
        categories = author.select("a:not(.name)") if author else []
        metric = row.select_one(".total p")
        raw_metric = _text(metric)
        number = re.search(r"^([0-9]+)\s*(?:月票|推荐票|收藏数)?$", raw_metric or "")
        record = {
            "work_id": urlsplit(detail).path.split("/")[2],
            "title": name.get_text(strip=True),
            "author": _text(row.select_one(".author .name")),
            "category": _text(categories[0]) if categories else None,
            "subcategory": _text(categories[1]) if len(categories) > 1 else None,
            "serial_status": _text(row.select_one(".author span")),
            "synopsis": _text(row.select_one(".intro")),
            "synopsis_scope": "LISTING_EXCERPT",
            "detail_url": detail,
            "rank": int(rank_text),
            "board": board,
            "metric_value": int(number[1]) if number else None,
            "metric_status": "PUBLISHED" if number else "UNAVAILABLE_OR_OBFUSCATED",
            "latest_update_time": _text(row.select_one(".update span")),
        }
        if record["work_id"] in seen:
            if record != seen[record["work_id"]]:
                raise ValueError("PUBLIC_CATALOG_DUPLICATE_CONFLICT")
            continue
        if record["rank"] in ranks:
            raise ValueError("PUBLIC_CATALOG_RANK_CONFLICT")
        seen[record["work_id"]] = record
        ranks.add(record["rank"])
    result["records"] = list(seen.values())
    following = soup.select_one("a.lbf-pagination-next:not(.lbf-pagination-disabled)")
    if following and following.get("href", "").startswith(("/", "https://")):
        result["next_url"] = public_url(urljoin(url, following["href"]))
        if result["next_url"] == url:
            raise ValueError("PUBLIC_CATALOG_PAGINATION_LOOP")
    return result


def _text(element: Any) -> str | None:
    return element.get_text(" ", strip=True) or None if element is not None else None


def rank_changes(
    current: dict[str, Any], previous: dict[str, Any] | None
) -> dict[str, int]:
    if previous is None or any(
        current.get(k) != previous.get(k)
        for k in ("platform", "url", "ranking_period", "parser_version", "mode")
    ):
        return {}
    prior = {r["work_id"]: r for r in previous["records"]}
    return {
        r["work_id"]: prior[r["work_id"]]["rank"] - r["rank"]
        for r in current["records"]
        if r["rank"] is not None
        and r["work_id"] in prior
        and prior[r["work_id"]]["rank"] is not None
    }
