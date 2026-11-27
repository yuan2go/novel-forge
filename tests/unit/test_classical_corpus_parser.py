from __future__ import annotations

import json

from novel_forge.modules.source_import.classical_corpus import (
    extract_governed_html,
    load_corpus_registry,
    parse_classical_work,
    resolve_work_spec,
)


def test_registry_freezes_twenty_unique_works_and_two_exact_commits() -> None:
    registry = load_corpus_registry()

    works = registry["works"]
    assert len(works) == 20
    assert len({row["work_key"] for row in works}) == 20
    assert [row["repository"] for row in works].count("chinese-novel") == 10
    assert [row["repository"] for row in works].count("chinese-poetry") == 10
    assert registry["repositories"]["chinese-novel"]["commit_sha"] == (
        "aecdc1a1b8153011f3446ebc5a0d89c3a24fc122"
    )
    assert registry["repositories"]["chinese-poetry"]["commit_sha"] == (
        "b8594f81a89752241442f2ce267d6f66f96704ee"
    )


def test_governed_html_preserves_breaks_entities_and_byte_mapping() -> None:
    source = (
        "<p>甲&nbsp;乙<br>第二行</p>"
        "<script>不得进入正文</script><div>第三段&amp;尾</div>"
    )

    body, spans = extract_governed_html(source)

    assert body == "甲 乙\n第二行\n第三段&尾"
    assert "不得进入正文" not in body
    assert len(spans) == 3
    assert [row["normalized_byte_start"] for row in spans] == [0, 8, 18]
    assert all(row["raw_byte_end"] > row["raw_byte_start"] for row in spans)


def test_novel_parser_uses_catalogue_numeric_mapping_and_excludes_author_intro() -> None:
    spec = resolve_work_spec("chinese-novel.sanguoyanyi")
    root = spec.root_path
    info = {
        "catalogueTotal": 3,
        "catalogues": ["序言", "第一回", "附录"],
        "author": {"name": "作者", "dynasty": "朝代", "intro": "作者介绍"},
    }
    files = {
        f"{root}/info.json": json.dumps(info, ensure_ascii=False).encode(),
        f"{root}/0.html": "序文<br>序二".encode(),
        f"{root}/1.html": "正文一<br><br>正文二".encode(),
        f"{root}/2.html": "附录内容".encode(),
    }

    parsed = parse_classical_work(
        spec,
        files,
        max_chunk_bytes=256,
        normalization_version="source-normalization.v1",
    )

    assert [(unit.ordinal, unit.kind, unit.title) for unit in parsed.units] == [
        (1, "PREFACE", "序言"),
        (2, "CHAPTER", "第一回"),
        (3, "APPENDIX", "附录"),
    ]
    assert parsed.units[1].body == "正文一\n正文二"
    assert parsed.units[1].source_locator["catalogue_index"] == 1
    assert parsed.excluded_fields[0]["field"] == "author_introduction"
    assert "作者介绍" not in parsed.normalized.text
    assert b"".join(chunk.content for chunk in parsed.chunks) == (
        parsed.normalized.text.encode()
    )
    assert all("body" not in unit for unit in parsed.structure_manifest()["units"])


def test_poetry_json_keeps_piece_and_line_boundaries_but_excludes_comments() -> None:
    spec = resolve_work_spec("chinese-poetry.youmengying")
    path = spec.paths[0]
    source = [
        {"content": "第一则正文", "comment": ["甲评", "乙评"]},
        {"content": "第二则正文", "comment": []},
    ]

    parsed = parse_classical_work(
        spec,
        {path: json.dumps(source, ensure_ascii=False).encode()},
        max_chunk_bytes=256,
        normalization_version="source-normalization.v1",
    )

    assert [unit.body for unit in parsed.units] == ["第一则正文", "第二则正文"]
    assert [unit.source_locator["pointer"] for unit in parsed.units] == [
        "/0/content",
        "/1/content",
    ]
    assert parsed.units[0].metadata["commentary_count"] == 2
    assert len(parsed.excluded_fields) == 2
    assert "甲评" not in parsed.normalized.text
    assert parsed.diagnostics["piece_boundaries"] == "PRESERVED"
    assert parsed.structure_manifest()["normalized_projection"][
        "traditional_simplified_conversion"
    ] == "NOT_APPLIED"
