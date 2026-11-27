from __future__ import annotations

from pathlib import Path

from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.definitions import (
    chapter_root_operation_definition,
)
from novel_forge.tools.authority_reachability import (
    build_authority_import_graph,
    production_paths,
)


ROOT = Path(__file__).resolve().parents[2]


def test_production_runtime_exposes_one_postgresql_authority_plane() -> None:
    graph = build_authority_import_graph(ROOT)
    assert {
        "api-app",
        "authority-cli",
        "agent-worker",
        "chapter-worker",
        "content-worker",
        "source-worker",
        "source-import-worker",
        "mkaos-worker",
        "book-worker",
    } <= graph.entrypoints.keys()
    assert not any(
        production_paths(paths)
        for path, paths in graph.paths_by_file.items()
        if path.startswith("src/novel_forge/modules/legacy_migration/")
    )


def test_chapter_saga_contract_remains_closed_without_claiming_runtime_proof() -> None:
    definition = chapter_root_operation_definition(
        application_build_id="acceptance-contract",
        commit_sha="a" * 40,
        model_effects_required=True,
    )
    children = definition["completion_contract"]["required_child_operations"]

    assert [item["definition_name"] for item in children] == [
        node.definition_name for node in ChapterNode
    ]
    assert len(children) == 22
    assert definition["evidence_status"]["integration_proven"] is False
    assert definition["evidence_status"]["real_provider_proven"] is False
