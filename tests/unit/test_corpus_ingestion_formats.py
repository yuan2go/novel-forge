import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

from novel_forge.modules.source_import.corpus_ingestion.contracts import (
    IngestionBudget,
    IngestionFailure,
    ParserProfile,
)
from novel_forge.modules.source_import.corpus_ingestion.parsers import (
    compile_work_index,
)
from novel_forge.modules.source_import.corpus_ingestion.safety import (
    expand_container,
    file_identity,
    local_identity,
    stable_local_file,
)


@pytest.mark.parametrize("format", ["txt", "html", "json", "jsonl", "parquet", "epub"])
def test_real_parsers_preserve_chinese_text_and_declared_structure(tmp_path, format):
    text = "阿青决定归还钥匙。第二天，守门人打开了仓门。"
    path = tmp_path / f"original.{format}"
    options = {"format": format, "completeness": "EXCERPT"}
    if format == "txt":
        path.write_bytes(text.encode("gb18030"))
        options["encoding"] = "gb18030"
    elif format == "html":
        path.write_text(
            f"<html><body><nav>不要读导航</nav><p>{text}</p><script>leak()</script></body></html>"
        )
    elif format in {"json", "jsonl"}:
        value = {"text": text}
        path.write_text(
            json.dumps([value] if format == "json" else value, ensure_ascii=False)
        )
    elif format == "parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq

        pq.write_table(pa.table({"text": [text]}), path)
    else:
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier("original")
        book.set_title("原创片段")
        book.set_language("zh")
        chapter = epub.EpubHtml(title="片段", file_name="chapter.xhtml", lang="zh")
        chapter.content = f"<html><body><p>{text}</p></body></html>"
        book.add_item(chapter)
        book.spine = [chapter]
        book.toc = (chapter,)
        book.add_item(epub.EpubNcx())
        epub.write_epub(str(path), book)
    digest, size = file_identity(path)
    result = compile_work_index(
        [
            {
                "path": path.name,
                "cache_path": str(path),
                "checksum": digest,
                "size_bytes": size,
            }
        ],
        ParserProfile(**options),
        IngestionBudget(),
        tmp_path / "parse",
    )
    work = json.loads(Path(result["works"][0]["cache_path"]).read_text())
    assert work["completeness"] == "EXCERPT" and work["units"][0]["text"] == text
    assert work["units"][0]["source_locator"]["path"] == path.name
    assert work["units"][0]["source_locator"]["original_byte_offset"] == (
        0 if format in {"txt", "jsonl"} else None
    )


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_containers_reject_escape_and_enforce_expansion(tmp_path, kind):
    path = tmp_path / ("unsafe." + kind)
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../escape.txt", "不允许")
    else:
        with tarfile.open(path, "w") as archive:
            item = tarfile.TarInfo("../escape.txt")
            item.size = 3
            archive.addfile(item, io.BytesIO(b"bad"))
    with pytest.raises(IngestionFailure, match="UNSAFE_PATH"):
        list(
            expand_container(path, path.name, tmp_path / "expanded", IngestionBudget())
        )
    assert not (tmp_path / "escape.txt").exists()
    payload = "只展开声明的原始字节。".encode()
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("book/chapter.txt", payload)
    else:
        with tarfile.open(path, "w") as archive:
            item = tarfile.TarInfo("book/chapter.txt")
            item.size = len(payload)
            archive.addfile(item, io.BytesIO(payload))
    expanded = list(
        expand_container(path, path.name, tmp_path / "valid", IngestionBudget())
    )
    assert len(expanded) == 1
    assert Path(expanded[0]["cache_path"]).read_bytes() == payload
    with pytest.raises(IngestionFailure, match="ARCHIVE_BUDGET_EXCEEDED"):
        list(
            expand_container(
                path,
                path.name,
                tmp_path / "limited",
                IngestionBudget(max_expanded_bytes=1),
            )
        )


def test_input_drift_and_malformed_encoding_are_not_success(tmp_path):
    path = tmp_path / "input.txt"
    path.write_bytes(b"before")
    before = local_identity(path)
    path.write_bytes(b"after")
    with pytest.raises(IngestionFailure, match="LOCAL_SOURCE_DRIFT"):
        with stable_local_file(path, before):
            pass
    path.write_bytes(b"\xffinvalid")
    digest, size = file_identity(path)
    with pytest.raises(UnicodeDecodeError):
        compile_work_index(
            [
                {
                    "path": path.name,
                    "cache_path": str(path),
                    "checksum": digest,
                    "size_bytes": size,
                }
            ],
            ParserProfile(format="txt"),
            IngestionBudget(),
            tmp_path / "parse",
        )


def test_cross_shard_gap_conflict_and_replay_are_explicit(tmp_path):
    parser = ParserProfile(
        format="jsonl",
        layout="CHAPTER_ROWS",
        fields={
            "work_id": "book",
            "chapter_id": "chapter",
            "order": "order",
            "text": "text",
        },
        completeness="COMPLETE",
        expected_units=3,
    )
    files = []
    for n in (1, 3):
        path = tmp_path / f"part-{n}.jsonl"
        path.write_text(
            json.dumps(
                {
                    "book": "original",
                    "chapter": str(n),
                    "order": n,
                    "text": f"第{n}个明确的章节。",
                },
                ensure_ascii=False,
            )
        )
        digest, size = file_identity(path)
        files.append(
            {
                "path": path.name,
                "cache_path": str(path),
                "checksum": digest,
                "size_bytes": size,
            }
        )
    first = compile_work_index(files, parser, IngestionBudget(), tmp_path / "first")
    second = compile_work_index(
        list(reversed(files)), parser, IngestionBudget(), tmp_path / "second"
    )
    assert first["work_count"] == second["work_count"] == 1
    assert first["works"][0]["completeness"] == "REVIEW_REQUIRED"
    assert first["works"][0]["checksum"] == second["works"][0]["checksum"]
    path = tmp_path / "conflict.jsonl"
    path.write_text(
        json.dumps(
            {
                "book": "original",
                "chapter": "1",
                "order": 1,
                "text": "同一身份不能悄悄覆盖成新正文。",
            },
            ensure_ascii=False,
        )
    )
    digest, size = file_identity(path)
    files.append(
        {
            "path": path.name,
            "cache_path": str(path),
            "checksum": digest,
            "size_bytes": size,
        }
    )
    with pytest.raises(IngestionFailure, match="DUPLICATE_UNIT_CONFLICT"):
        compile_work_index(files, parser, IngestionBudget(), tmp_path / "conflict")


def test_sparse_chapter_numbers_never_allocate_by_number_span(tmp_path, monkeypatch):
    import builtins
    from novel_forge.modules.source_import.corpus_ingestion import parsers

    def bounded_range(*args):
        result = builtins.range(*args)
        assert len(result) <= 100, "chapter gap must not allocate by numeric span"
        return result

    monkeypatch.setattr(parsers, "range", bounded_range, raising=False)
    path = tmp_path / "sparse.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {"book": "excerpt", "chapter": str(n), "order": n, "text": "正文。"}
            )
            for n in (1, 10**12)
        )
    )
    digest, size = file_identity(path)
    result = compile_work_index(
        [
            {
                "path": path.name,
                "cache_path": str(path),
                "checksum": digest,
                "size_bytes": size,
            }
        ],
        ParserProfile(
            format="jsonl",
            layout="CHAPTER_ROWS",
            fields={
                "work_id": "book",
                "chapter_id": "chapter",
                "order": "order",
                "text": "text",
            },
            completeness="EXCERPT",
        ),
        IngestionBudget(),
        tmp_path / "index",
    )
    assert result["works"][0]["completeness"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "gb18030"])
def test_jsonl_encoding_contract_has_exact_raw_record_spans(tmp_path, encoding):
    from novel_forge.modules.source_import.corpus_ingestion.parsers import parse_records

    texts = ["甲𠀀" * 12000, "乙知道秘密。"]
    content = (
        "\r\n".join(json.dumps({"text": text}, ensure_ascii=False) for text in texts)
        + "\r\n"
    )
    raw = content.encode(encoding)
    path = tmp_path / "input.jsonl"
    path.write_bytes(raw)
    rows = list(
        parse_records(
            {"path": path.name, "cache_path": str(path)},
            ParserProfile(format="jsonl", encoding=encoding),
            IngestionBudget(),
        )
    )
    assert [row["text"] for row in rows] == texts
    assert rows[0]["source_locator"]["original_byte_offset"] == 0
    assert rows[-1]["source_locator"]["original_byte_end"] == len(raw)
    for row in rows:
        location = row["source_locator"]
        segment = raw[location["original_byte_offset"] : location["original_byte_end"]]
        codec = "utf-16-le" if encoding == "utf-16" else encoding
        assert json.loads(segment.decode(codec).lstrip("\ufeff"))["text"] == row["text"]


def test_longform_volume_reset_raw_coverage_and_review(tmp_path):
    from novel_forge.modules.source_import.corpus_ingestion.segmentation import (
        chinese_number,
    )

    assert chinese_number("一二○") == 120
    original = (
        "来源说明\r\n第一卷 初识\r\n第一章 起因\r\n"
        + "正文只是提到第一章，不是新边界。" * 20
        + "\r\n第二章 选择\r\n"
        + "她选择承担代价。" * 30
        + "\r\n第二卷 代价\r\n第001章 兑现\r\n"
        + "他终于归还钥匙。" * 30
        + "\r\n作者附言\r\n感谢阅读。"
    )
    path = tmp_path / "long.txt"
    raw = original.encode("utf-16")
    path.write_bytes(raw)
    digest, size = file_identity(path)
    parser = ParserProfile(
        version="corpus-parser.v2",
        format="txt",
        encoding="utf-16",
        normalization={"min_body_chars": 10},
        completeness="COMPLETE",
        expected_units=3,
    )
    work = compile_work_index(
        [
            {
                "path": path.name,
                "cache_path": str(path),
                "checksum": digest,
                "size_bytes": size,
            }
        ],
        parser,
        IngestionBudget(max_record_bytes=1024),
        tmp_path / "long-index",
    )
    document = json.loads(Path(work["works"][0]["cache_path"]).read_text())
    assert document["integrity"]["chapter_count"] == 3
    assert document["integrity"]["coverage"] == "REVIEW_REQUIRED"
    assert not any(
        i["code"] == "MISSING_OR_UNORDERED_CHAPTER"
        for i in document["integrity"]["issues"]
    )
    units = document["units"]
    assert units[0]["source_locator"]["original_byte_offset"] == 0
    assert units[-1]["source_locator"]["original_byte_end"] == len(raw)
    assert all(
        a["source_locator"]["original_byte_end"]
        == b["source_locator"]["original_byte_offset"]
        for a, b in zip(units, units[1:])
    )
    for row in units:
        loc = row["source_locator"]
        source = (
            raw[loc["original_byte_offset"] : loc["original_byte_end"]]
            .decode("utf-16-le")
            .lstrip("\ufeff")
        )
        assert source.replace("\r\n", "\n") == row["text"]


def test_matching_projection_does_not_rewrite_or_authorize_source():
    from novel_forge.modules.source_import.corpus_ingestion.similarity import (
        fingerprint,
    )

    original = "門外的人終於歸還鑰匙。" * 300
    altered = original.replace("鑰匙", "钥匙").replace("。", "！\n")
    first, second = fingerprint([original]), fingerprint([altered])
    assert first == second
    assert "鑰匙" in original and "钥匙" in altered
    assert fingerprint(["同名作品讲另一件完全不同的事情。" * 100]) != first


def test_v2_toc_evidence_and_v1_replay_contract(tmp_path):
    from pydantic import ValidationError

    assert "normalization" not in ParserProfile(format="txt").model_dump(mode="json")
    with pytest.raises(ValidationError, match="container-defined encoding"):
        ParserProfile(format="parquet", encoding="utf-16")
    with pytest.raises(ValidationError, match="normalization requires"):
        ParserProfile(format="txt", normalization={})
    with pytest.raises(ValidationError, match="ToC needs"):
        ParserProfile(
            version="corpus-parser.v2",
            format="txt",
            normalization={"expected_toc": ["第一章 起因"]},
        )


def test_exact_boundary_override_cannot_drop_raw_bytes_or_change_source(tmp_path):
    from novel_forge.modules.source_import.corpus_ingestion.parsers import parse_records

    raw = "无标题的第一段。\n后续无标题的第二段。".encode()
    path = tmp_path / "explicit.txt"
    path.write_bytes(raw)
    digest, size = file_identity(path)
    cut = len("无标题的第一段。\n".encode())
    boundaries = [
        {
            "path": path.name,
            "checksum": digest,
            "start": start,
            "end": end,
            "title": title,
            "number": i,
            "evidence": "agent-inspected original boundary",
        }
        for i, (start, end, title) in enumerate(
            ((0, cut, "第一章"), (cut, len(raw), "第二章")), 1
        )
    ]
    profile = ParserProfile(
        version="corpus-parser.v2",
        format="txt",
        normalization={"boundaries": boundaries, "min_body_chars": 1},
    )
    file = {
        "path": path.name,
        "cache_path": str(path),
        "checksum": digest,
        "size_bytes": size,
    }
    rows = list(parse_records(file, profile, IngestionBudget()))
    assert "".join(r["text"] for r in rows).encode() == raw
    assert len(rows) == 2
    with pytest.raises(IngestionFailure, match="BOUNDARY_SOURCE_DRIFT"):
        list(
            parse_records(
                {**file, "checksum": "sha256:" + "0" * 64}, profile, IngestionBudget()
            )
        )
    boundaries[1]["start"] += 3
    with pytest.raises(IngestionFailure, match="BOUNDARY_COVERAGE_INVALID"):
        list(
            parse_records(
                file,
                ParserProfile(
                    version="corpus-parser.v2",
                    format="txt",
                    normalization={"boundaries": boundaries},
                ),
                IngestionBudget(),
            )
        )


def test_multifile_chapters_preserve_physical_order_and_explicit_mode(tmp_path):
    files = []
    for index, heading in enumerate(("第一章 起因", "第二章 后果"), 1):
        path = tmp_path / f"{index}.txt"
        path.write_text(heading + "\n" + "甲承担代价，乙因而得救。e\u0301" * 20)
        digest, size = file_identity(path)
        files.append(
            {
                "path": path.name,
                "cache_path": str(path),
                "checksum": digest,
                "size_bytes": size,
            }
        )
    parser = ParserProfile(
        version="corpus-parser.v2",
        format="txt",
        constants={"work_id": "original"},
        normalization={"unicode_form": "NONE"},
    )
    output = compile_work_index(
        list(reversed(files)), parser, IngestionBudget(), tmp_path / "multi-index"
    )
    document = json.loads(Path(output["works"][0]["cache_path"]).read_text())
    assert [r["order"] for r in document["units"]] == [1, 2]
    assert [r["physical_order"] for r in document["units"]] == [1, 1]
    assert document["parser_profile"]["normalization"]["unicode_form"] == "NONE"
    assert all(set(r["parser"]) == {"profile_hash"} for r in document["units"])
    assert document["integrity"]["structure_usable"]
    assert all(
        "NFC" not in r["normalization_evidence"]["steps"] for r in document["units"]
    )
    assert "e\u0301" in document["units"][0]["text"]
    explicit = ParserProfile(
        version="corpus-parser.v2",
        format="txt",
        normalization={"segmentation": "EXPLICIT"},
    )
    output = compile_work_index(
        files[:1], explicit, IngestionBudget(), tmp_path / "explicit-index"
    )
    document = json.loads(Path(output["works"][0]["cache_path"]).read_text())
    assert not document["integrity"]["structure_usable"]
    assert document["integrity"]["chapter_count"] == 0
