from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import math
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.source_authority.market import (
    RankDefinition,
    UseScope,
    ObserveMarketRank,
)
from .corpus_ingestion.contracts import IngestionFailure
from .corpus_ingestion.http_transport import CorpusHttpTransport

USER_AGENT = "NovelForge-Corpus/1"
STOP_STATUSES = {
    "ACCESS_DENIED",
    "CHALLENGE",
    "LOGIN_REQUIRED",
    "RATE_LIMITED",
    "PARSE_DRIFT",
    "REMOVED",
}


def response_status(status: int, body: str) -> str:
    if status in {401, 403}:
        return "ACCESS_DENIED"
    if status == 429:
        return "RATE_LIMITED"
    if status in {404, 410}:
        return "REMOVED"
    if status == 304:
        return "NOT_MODIFIED"
    if status == 202 or any(
        token in body.lower()
        for token in ("probe.js", "captcha", "验证码", "安全验证", "访问异常")
    ):
        return "CHALLENGE"
    if "登录后" in body or 'id="login-form"' in body or 'class="login-form"' in body:
        return "LOGIN_REQUIRED"
    return "COMPLETE" if status == 200 else "TRANSPORT_FAILURE"


def retry_after(value: str, now: datetime) -> float:
    if re.fullmatch(r"[0-9]{1,10}", value.strip()):
        return float(value)
    try:
        return max(0, (parsedate_to_datetime(value) - now).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 0


def parse_rank_page(
    body: str, *, url: str, definition: RankDefinition, page: int
) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    heading = soup.select_one(".rank-header h3, .rank-header h2, .rank-title h3")
    if heading is None or definition.official_name not in heading.get_text(
        " ", strip=True
    ):
        raise ValueError("Official rank heading missing or changed")
    for selector, expected in (
        (definition.period_selector, definition.period),
        (definition.category_selector, definition.category_label),
    ):
        marker = soup.select_one(selector) if selector else None
        if marker is None or marker.get_text(" ", strip=True) != expected:
            raise ValueError(
                "Exact official period/category marker missing or changed; inspect navigation"
            )
    rows = soup.select(
        ".rank-body .book-img-text li, .main-content-wrap .book-img-text li"
    )
    if not rows:
        raise ValueError("Rank list structure missing or changed")
    entries = []
    for row in rows:
        title = row.select_one(".book-mid-info h2 a")
        rank = row.select_one(".book-img-box .num-box, .book-img-box .num, .rank-index")
        if title is None or rank is None:
            raise ValueError("Explicit rank or book identity missing")
        href = urljoin(url, title.get("href", ""))
        match = re.fullmatch(r"/book/([0-9]+)/?", urlsplit(href).path)
        if not match or urlsplit(href).hostname != "www.qidian.com":
            raise ValueError("Book link changed platform or identity")
        identity = match[1]
        rank_text = rank.get_text(strip=True)
        if not rank_text.isdecimal():
            raise ValueError("Rank is not a public integer")
        author = row.select_one(".book-mid-info .author .name")
        metrics = []
        for metric in row.select(".book-right-info .total"):
            raw = metric.get_text(" ", strip=True)
            if definition.metric_label in raw:
                metrics.append(
                    {
                        "label": definition.metric_label,
                        "value": raw,
                        "source_locator": f"{url}#rank-{rank_text}:total",
                    }
                )
        entries.append(
            {
                "work_id": identity,
                "title": title.get_text(strip=True),
                "url": f"https://www.qidian.com/book/{identity}/",
                "author": author.get_text(strip=True) if author else "",
                "rank": int(rank_text),
                "public_metrics": metrics,
                "field_sources": {
                    key: f"{url}#rank-{rank_text}:{key}"
                    for key in ("work_id", "title", "rank", "author")
                },
            }
        )
    return {
        "page": page,
        "url": url,
        "content_hash": "sha256:" + hashlib.sha256(body.encode()).hexdigest(),
        "entries": entries,
    }


class QidianRankAdapter:
    provider = "qidian_public_metadata"
    reconciliation_mode = "query"
    production_execution_gateway_backed = True
    capability_profile = {
        "provider": provider,
        "control_level": "V2_CONTROLLED",
        "supports_request_timeout": True,
        "supports_provider_idempotency": False,
        "supports_query": True,
        "supports_cancel": False,
        "supports_callback": False,
        "supports_usage_receipt": False,
        "supports_cost_receipt": False,
        "reconciliation_mode": "query",
        "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def __init__(
        self, *, transport=None, site_slot=None, stop_site=None, sleep=time.sleep
    ):
        self.transport = transport or CorpusHttpTransport(
            allowed_hosts=("www.qidian.com",), max_redirects=0
        )
        self.site_slot = site_slot or (lambda _interval: None)
        self.stop_site = stop_site or (lambda _status, _delay: None)
        self.sleep = sleep

    def _get(self, url: str, policy, headers=None):
        for attempt in range(policy.retries + 1):
            self.site_slot(policy.site_min_interval_seconds)
            with self.transport.open(
                url,
                timeout=policy.timeout_seconds,
                conditional_headers=headers,
                accepted_statuses=(
                    200,
                    202,
                    304,
                    401,
                    403,
                    404,
                    410,
                    429,
                    500,
                    502,
                    503,
                    504,
                ),
            ) as response:
                data = response.read(policy.max_response_bytes + 1)
                if len(data) > policy.max_response_bytes:
                    raise ValueError("Response exceeds bounded metadata size")
                result = (
                    response.status,
                    data.decode("utf-8", errors="strict"),
                    response.getheader("ETag") or "",
                    response.getheader("Last-Modified") or "",
                    response.getheader("Retry-After") or "",
                )
            if result[0] not in {502, 503, 504} or attempt == policy.retries:
                return result
            delay = max(2**attempt, retry_after(result[4], datetime.now(timezone.utc)))
            if delay > policy.max_backoff_seconds:
                return result
            self.sleep(delay)
        raise AssertionError("bounded retry exhausted")

    def execute(
        self, *, stable_idempotency_key: str, capability: str, request_payload: dict
    ) -> ProviderResult:
        if capability != "source.remote.fetch":
            return ProviderResult(
                "final_failure",
                stable_idempotency_key,
                {"error": "unsupported_capability"},
            )
        definition = RankDefinition.model_validate(request_payload["definition"])
        use = UseScope.model_validate(request_payload["use_scope"])
        use.require_metadata(datetime.now(timezone.utc))
        if (
            definition.support != "VERIFIED"
            or definition.parser_version != "qidian-rank-html.v1"
        ):
            raise ValueError("Only actual verified official page definitions can fetch")
        observed = datetime.now(timezone.utc)
        rate_delay = 0.0
        pages, reasons, status, etag, modified = [], [], "COMPLETE", "", ""
        try:
            robot_response = self._get(
                "https://www.qidian.com/robots.txt", definition.update
            )
            status = response_status(robot_response[0], robot_response[1])
            if status != "COMPLETE" or "<html" in robot_response[1].lower():
                status = "CHALLENGE" if status == "COMPLETE" else status
                reasons.append(
                    "Robots rules unavailable or challenged; acquisition stopped"
                )
            else:
                robot = RobotFileParser()
                robot.parse(robot_response[1].splitlines())
                crawl_delay = (
                    robot.crawl_delay(USER_AGENT) or robot.crawl_delay("*") or 0
                )
                if crawl_delay > 3600:
                    raise ValueError(
                        "Robots crawl delay exceeds configured bounded worker policy"
                    )
                definition = definition.model_copy(
                    update={
                        "update": definition.update.model_copy(
                            update={
                                "site_min_interval_seconds": max(
                                    definition.update.site_min_interval_seconds,
                                    crawl_delay,
                                )
                            }
                        )
                    }
                )
                for page in range(
                    1,
                    math.ceil(definition.update.top_n / definition.update.page_size)
                    + 1,
                ):
                    url = (
                        definition.page_urls[page - 1]
                        if definition.page_urls
                        else definition.url
                    )
                    if not robot.can_fetch(USER_AGENT, url):
                        status, reasons = (
                            "ACCESS_DENIED",
                            ["Robots rules disallow this path"],
                        )
                        break
                    headers = (
                        {
                            k: v
                            for k, v in {
                                "If-None-Match": request_payload.get("etag", ""),
                                "If-Modified-Since": request_payload.get(
                                    "last_modified", ""
                                ),
                            }.items()
                            if v
                        }
                        if page == 1
                        and math.ceil(
                            definition.update.top_n / definition.update.page_size
                        )
                        == 1
                        else {}
                    )
                    response = self._get(url, definition.update, headers)
                    status = response_status(response[0], response[1])
                    if status == "RATE_LIMITED":
                        rate_delay = retry_after(
                            response[4], datetime.now(timezone.utc)
                        )
                        self.stop_site(status, rate_delay)
                    if status != "COMPLETE":
                        if status != "NOT_MODIFIED":
                            reasons.append(
                                f"Official page stopped with HTTP {response[0]}: {status}"
                            )
                        break
                    parsed = parse_rank_page(
                        response[1], url=url, definition=definition, page=page
                    )
                    parsed["entries"] = [
                        e
                        for e in parsed["entries"]
                        if e["rank"] <= definition.update.top_n
                    ]
                    pages.append(parsed)
                    etag, modified = response[2:4]
        except IngestionFailure as exc:
            status = {
                "REMOTE_TIMEOUT": "TIMEOUT",
                "REMOTE_REDIRECT_REVIEW_REQUIRED": "ACCESS_DENIED",
            }.get(exc.reason, "TRANSPORT_FAILURE")
            reasons.append(exc.reason)
        except (ValueError, UnicodeError) as exc:
            status, reasons = "PARSE_DRIFT", [str(exc)[:500]]
        if status in STOP_STATUSES:
            self.stop_site(status, rate_delay)
        if pages and status != "COMPLETE":
            status = "PARTIAL"
        raw = {
            "action": "observe_market_rank",
            "source_id": request_payload["source_id"],
            "definition_id": request_payload["definition_id"],
            "fetch_operation_id": stable_idempotency_key.removeprefix("market-fetch:"),
            "acquisition": "OFFICIAL_PUBLIC_PAGE",
            "receipt_ref": stable_idempotency_key,
            "observed_at": observed.isoformat(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "site_time_missing_reason": "Page provides no verified site data timestamp",
            "period_value": request_payload["period_value"],
            "requested_top_n": definition.update.top_n,
            "pages": pages,
            "status": status,
            "missing_reasons": reasons,
            "etag": etag,
            "last_modified": modified,
        }
        try:
            observation = ObserveMarketRank.model_validate(raw)
        except ValueError:
            raw.update(
                status="PARTIAL" if pages else "PARSE_DRIFT",
                missing_reasons=["Rank/page coverage does not match requested Top N"],
            )
            observation = ObserveMarketRank.model_validate(raw)
        return ProviderResult(
            "success",
            stable_idempotency_key,
            {
                "observation": observation.model_dump(mode="json"),
                "raw_response_retained": False,
            },
        )

    def query(self, **kwargs) -> ProviderResult:
        return ProviderResult(
            "unknown",
            kwargs["stable_idempotency_key"],
            {
                "reason": "No historical server receipt; do not replace an uncertain fetch with current page bytes"
            },
        )
