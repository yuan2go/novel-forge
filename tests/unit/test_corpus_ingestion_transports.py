import hashlib
import io
from contextlib import contextmanager

import pytest

from novel_forge.modules.source_import.corpus_ingestion.acquisition import (
    CorpusAcquisitionAdapter,
)
from novel_forge.modules.source_import.corpus_ingestion.contracts import (
    IngestionManifest,
    IngestionFailure,
)
from novel_forge.modules.source_import.corpus_ingestion.http_transport import (
    CorpusHttpTransport,
)
from novel_forge.modules.source_import.git_adapter import (
    GitRepositoryExternalEffectAdapter,
)


class ScriptedHttp:
    def __init__(self, kind, body):
        self.kind, self.body = kind, body
        self.reads = 0
        self.metadata_reads = 0
        self.change_after_read = False
        self.refuse = False

    def metadata(self, url, *, timeout):
        self.metadata_reads += 1
        if self.kind == "HUGGING_FACE":
            return {
                "sha": "a" * 40,
                "cardData": {
                    "license": "mit",
                    "configs": [
                        {
                            "config_name": "original",
                            "data_files": [{"split": "train", "path": "data/*.txt"}],
                        }
                    ],
                },
                "siblings": [
                    {
                        "rfilename": "data/original.txt",
                        "size": len(self.body),
                        "lfs": {"sha256": hashlib.sha256(self.body).hexdigest()},
                    }
                ],
            }
        return {
            "metadata": {"identifier": "original-test", "licenseurl": "unknown"},
            "files": [
                {
                    "name": "original.txt",
                    "size": str(len(self.body)),
                    "md5": hashlib.md5(self.body).hexdigest(),
                    "sha1": hashlib.sha1(self.body).hexdigest(),
                    "mtime": "changed"
                    if self.change_after_read and self.reads
                    else "frozen",
                }
            ],
        }

    @contextmanager
    def open(self, url, *, timeout):
        self.reads += 1
        if self.refuse:
            raise IngestionFailure("REMOTE_ACCESS_NOT_AUTHORIZED", "403")
        yield io.BytesIO(self.body)


@pytest.mark.parametrize("kind", ["HUGGING_FACE", "INTERNET_ARCHIVE"])
def test_exact_remote_acquisition_receipt_replay_and_fail_closed(tmp_path, kind):
    transport = ScriptedHttp(kind, "原创字节；传输边界脚本证据。".encode())
    path = "data/original.txt" if kind == "HUGGING_FACE" else "original.txt"
    source = {"kind": kind, "location": "original-test", "files": [{"path": path}]}
    if kind == "HUGGING_FACE":
        source.update(revision="a" * 40, config="original", split="train")
    manifest = IngestionManifest(
        source=source, parser={"format": "txt"}, purpose="RESEARCH", rights={}
    )
    adapter = CorpusAcquisitionAdapter(
        tmp_path / "cache",
        local_roots=(),
        git_adapter=GitRepositoryExternalEffectAdapter(tmp_path / "git"),
        http=transport,
    )
    request = {"manifest": manifest.model_dump(mode="json"), "mode": "PREVIEW"}
    preview = adapter.execute(
        stable_idempotency_key="preview",
        capability="source.remote.fetch",
        request_payload=request,
    )
    assert (
        preview.outcome == "success"
        and not preview.evidence["content_verified"]
        and transport.reads == 0
    )
    request["mode"] = "IMPORT"
    acquired = adapter.execute(
        stable_idempotency_key="import",
        capability="source.remote.fetch",
        request_payload=request,
    )
    assert acquired.outcome == "success" and acquired.evidence["actual_bytes"] == len(
        transport.body
    )
    assert (
        acquired.evidence["files"][0]["checksum"]
        == "sha256:" + hashlib.sha256(transport.body).hexdigest()
    )
    assert not acquired.evidence["source"]["underlying_rights_inferred"]
    assert (
        adapter.query(
            stable_idempotency_key="import",
            capability="source.remote.fetch",
            request_payload=request,
        )
        == acquired
    )
    assert transport.reads == 1
    changed = {**request, "mode": "PREVIEW"}
    assert (
        adapter.execute(
            stable_idempotency_key="import",
            capability="source.remote.fetch",
            request_payload=changed,
        ).outcome
        == "final_failure"
    )
    if kind == "INTERNET_ARCHIVE":
        transport.reads = 0
        transport.change_after_read = True
        assert (
            adapter.execute(
                stable_idempotency_key="drift",
                capability="source.remote.fetch",
                request_payload=request,
            ).evidence["error_code"]
            == "SOURCE_CHANGED_DURING_ACQUISITION"
        )
    else:
        transport.refuse = True
        failed = adapter.execute(
            stable_idempotency_key="gated",
            capability="source.remote.fetch",
            request_payload=request,
        )
        assert (
            failed.outcome == "final_failure"
            and failed.evidence["error_code"] == "REMOTE_ACCESS_NOT_AUTHORIZED"
        )
        assert transport.reads == 2


def test_remote_private_dns_and_credential_url_are_rejected(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    for url, reason in (
        ("https://archive.org/download/x/y", "REMOTE_ADDRESS_FORBIDDEN"),
        ("https://token@huggingface.co/file", "REMOTE_ORIGIN_FORBIDDEN"),
        ("https://evil.example/file", "REMOTE_ORIGIN_FORBIDDEN"),
    ):
        with pytest.raises(IngestionFailure, match=reason):
            with CorpusHttpTransport().open(url, timeout=1):
                pytest.fail("unsafe origin reached transport")
