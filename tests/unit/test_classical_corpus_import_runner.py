from novel_forge.modules.project_authority.domain import build_project_snapshot
from scripts.run_classical_corpus_import import _project_payload


def test_classical_corpus_runner_uses_an_authoritative_project_stage() -> None:
    snapshot = build_project_snapshot(
        project_id="project:classical-corpus",
        workspace_id="workspace:classical-corpus",
        payload=_project_payload(),
    )

    assert snapshot["stage"] == "DESIGN"
    assert snapshot["config"] == {
        "validation_scope": "CLASSICAL_CORPUS_SOURCE_ONLY",
        "publication_policy": "FORBIDDEN",
    }
