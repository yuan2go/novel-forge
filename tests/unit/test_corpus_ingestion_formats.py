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
