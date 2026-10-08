from contextlib import contextmanager

import pytest

from novel_forge.modules.source_authority.public_catalog import (
    CatalogCapture,
    digest,
    parse_page,
    rank_changes,
)
from novel_forge.modules.source_authority.public_catalog_adapter import (
    PublicCatalogAdapter,
)

URL = "https://www.qidian.com/rank/yuepiao/chn22/"
TIME = "2026-10-08T08:00:00+00:00"
HTML = """<title>2026年10月仙侠月票榜</title><li><span class="rank-tag">1</span><div class="book-mid-info"><h2><a href="/book/123/">原创合成榜单样本</a></h2><p class="author"><a class="name">合成作者</a><a>仙侠</a><a>古典仙侠</a><span>连载</span></p><p class="intro">合成简介</p></div><div class="total"><p>𘜸𘜺月票</p></div></li>""".encode()


class Transport:
    def __init__(self, body=HTML, status=200):
        self.body, self.status, self.calls = body, status, 0

    @contextmanager
    def open(self, url, *, timeout):
        self.calls += 1

        class Response:
            status = self.status

            def read(_self, limit):
                return self.body[:limit]

            def getheader(_self, name):
                return None

        yield Response()


def test_obfuscated_metrics_and_missing_data_time_remain_missing():
    page = parse_page(HTML, URL, TIME)
    assert page["records"][0]["metric_value"] is None
    assert page["records"][0]["rank"] == 1
    assert page["ranking_period"] == "2026-10"
    assert page["data_time"] is None
    assert page["records"][0]["synopsis_scope"] == "LISTING_EXCERPT"


@pytest.mark.parametrize(
    "html,reason",
    [
        (b'<script src="/C2/probe.js"></script>', "ACCESS_CHALLENGE"),
        (b"<title>Changed</title><p>No rows</p>", "SCHEMA_CHANGED"),
        (HTML.replace(b'<span class="rank-tag">1</span>', b""), "RANK_MISSING"),
    ],
)
def test_failure_never_becomes_empty_ranking(html, reason):
    with pytest.raises(ValueError, match=reason):
        parse_page(html, URL, TIME)


def test_receipt_replay_and_unknown_query_do_not_refetch(tmp_path):
    transport = Transport()
    adapter = PublicCatalogAdapter(tmp_path, transport=transport)
    payload = CatalogCapture(platform="qidian", url=URL).model_dump(mode="json")
    first = adapter.execute(
        stable_idempotency_key="first",
        capability="source.remote.fetch",
        request_payload=payload,
    )
    replay = PublicCatalogAdapter(tmp_path, transport=transport).query(
        stable_idempotency_key="first",
        capability="source.remote.fetch",
        request_payload={
            **payload,
            "external_effect_id": "kernel-effect",
            "operation_id": "kernel-operation",
            "provider_request_id": "",
        },
    )
    assert first.evidence == replay.evidence
    assert transport.calls == 1
    assert (
        adapter.query(
            stable_idempotency_key="unknown",
            capability="source.remote.fetch",
            request_payload=payload,
        ).outcome
        == "not_found"
    )
    assert transport.calls == 1
    assert first.evidence["generation_context_allowed"] is False
    receipt = adapter.execute(
        stable_idempotency_key="second",
        capability="source.remote.fetch",
        request_payload=payload,
    )
    assert receipt.evidence["cache_reused"]
    assert receipt.evidence["acquired_at"] == first.evidence["acquired_at"]
    assert transport.calls == 1


def test_challenge_has_failure_receipt_and_preserved_response(tmp_path):
    transport = Transport(body=b'<script src="/probe.js"></script>', status=202)
    adapter = PublicCatalogAdapter(tmp_path, transport=transport)
    payload = CatalogCapture(platform="qidian", url=URL).model_dump(mode="json")
    result = adapter.execute(
        stable_idempotency_key="blocked",
        capability="source.remote.fetch",
        request_payload=payload,
    )
    assert result.outcome == "final_failure"
    assert result.evidence["error_code"] == "PUBLIC_CATALOG_ACCESS_CHALLENGE"
    assert list((tmp_path / "snapshots").iterdir())
    assert (
        adapter.execute(
            stable_idempotency_key="blocked",
            capability="source.remote.fetch",
            request_payload=payload,
        ).outcome
        == "final_failure"
    )
    assert transport.calls == 1


def test_offline_snapshot_is_explicit_and_hash_bound(tmp_path):
    offline = tmp_path / "offline"
    offline.mkdir()
    path = offline / "page.html"
    path.write_bytes(HTML)
    capture = CatalogCapture(
        platform="qidian",
        url=URL,
        mode="OFFLINE_AUTHORIZED_SNAPSHOT",
        authorization_ref="synthetic-test-only",
        offline_pages=(
            {
                "url": URL,
                "path": str(path),
                "sha256": digest(HTML),
                "acquired_at": TIME,
            },
        ),
    )
    transport = Transport()
    adapter = PublicCatalogAdapter(
        tmp_path / "receipts", offline_root=offline, transport=transport
    )
    result = adapter.execute(
        stable_idempotency_key="offline",
        capability="source.remote.fetch",
        request_payload=capture.model_dump(mode="json"),
    )
    assert result.evidence["mode"] == "OFFLINE_AUTHORIZED_SNAPSHOT"
    assert result.evidence["acquired_at"] == TIME
    assert transport.calls == 0
    path.write_bytes(b"changed")
    result = adapter.execute(
        stable_idempotency_key="changed",
        capability="source.remote.fetch",
        request_payload=capture.model_dump(mode="json"),
    )
    assert result.outcome == "final_failure"


def test_rank_change_requires_comparable_source_period_and_present_history():
    current = {
        "platform": "qidian",
        "url": URL,
        "ranking_period": "2026-10",
        "parser_version": "v1",
        "mode": "LIVE_HTTP",
        "records": [{"work_id": "1", "rank": 2}, {"work_id": "2", "rank": 3}],
    }
    assert rank_changes(current, None) == {}
    assert rank_changes(current, {**current, "ranking_period": "2026-09"}) == {}
    assert rank_changes(
        current, {**current, "records": [{"work_id": "1", "rank": 5}]}
    ) == {"1": 3}


@pytest.mark.parametrize(
    "url",
    [
        "http://www.qidian.com/rank/yuepiao/",
        "https://evil.com/rank/yuepiao/",
        "https://www.qidian.com/book/123/?token=secret",
        "https://u:p@www.qidian.com/rank/yuepiao/",
    ],
)
def test_origin_and_credentials_fail_before_io(url):
    with pytest.raises(ValueError):
        CatalogCapture(platform="qidian", url=url)
