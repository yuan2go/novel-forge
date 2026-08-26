from __future__ import annotations

from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority.evaluation_execution import (
    PostgresNarrativeEvaluationExecutionContractBinder,
    _canonical_hash,
)
from novel_forge.storage.authority_asset_store import AuthorityAssetDocument


FOUNDATION_TYPES = {
    "CREATIVE_FOUNDATION": "creative_foundation",
    "THEME_CONTRACT": "theme_contract",
    "ENDING_INTENT": "ending_intent",
    "READER_PROMISE": "reader_promise",
    "WORLD_BIBLE": "world_bible",
    "CHARACTER_CAST": "character_cast",
}


def _document(
    *,
    asset_version_id: str,
    asset_type: str,
    content_hash: str,
    content: dict[str, object],
    lifecycle: str = "ACTIVE",
    eligibility: str = "ELIGIBLE",
) -> AuthorityAssetDocument:
    return AuthorityAssetDocument(
        project_id="project:test",
        logical_ref=f"test/{asset_version_id}.json",
        category="test",
        asset_id=f"asset:{asset_version_id}",
        asset_type=asset_type,
        asset_version_id=asset_version_id,
        version_number=1,
        lifecycle=lifecycle,
        eligibility=eligibility,
        governance="CLEAR",
        content_hash=content_hash,
        content=content,
        updated_at="2026-08-26T00:00:00Z",
    )


class _Query:
    def __init__(self, documents: dict[str, AuthorityAssetDocument]) -> None:
        self.documents = documents

    def require(
        self,
        *,
        project_id: str,
        asset_version_id: str | None = None,
        logical_ref: str | None = None,
    ) -> AuthorityAssetDocument:
        assert project_id == "project:test"
        if logical_ref is not None:
            raise KernelError("AUTHORITY_ASSET_NOT_FOUND", logical_ref)
        assert asset_version_id is not None
        return self.documents[asset_version_id]


class _Writer:
    def __init__(self) -> None:
        self.command = None

    def materialize_output(self, command):  # type: ignore[no-untyped-def]
        self.command = command
        return command


def _binder_fixture() -> tuple[
    PostgresNarrativeEvaluationExecutionContractBinder,
    AuthorityAssetDocument,
    _Writer,
    dict[str, AuthorityAssetDocument],
]:
    bindings: list[dict[str, str]] = []
    documents: dict[str, AuthorityAssetDocument] = {}
    for index, (role, asset_type) in enumerate(FOUNDATION_TYPES.items(), start=1):
        source_id = f"foundation:{index}"
        source_hash = "sha256:" + str(index) * 64
        qualification_id = f"qualification:{index}"
        qualification_hash = "sha256:" + format(index + 6, "x") * 64
        source = _document(
            asset_version_id=source_id,
            asset_type=asset_type,
            content_hash=source_hash,
            content={
                "candidate_payload": {"role": role, "evidence": f"evidence-{index}"}
            },
        )
        qualification = _document(
            asset_version_id=qualification_id,
            asset_type="narrative_design_evaluation",
            content_hash=qualification_hash,
            content={
                "candidate_asset_version_id": source_id,
                "candidate_content_hash": source_hash,
                "qualification": {"status": "PASS"},
            },
        )
        documents[source_id] = source
        documents[qualification_id] = qualification
        bindings.append(
            {
                "role": role,
                "authority": "STORY_DESIGN_AUTHORITY",
                "asset_version_id": source_id,
                "content_hash": source_hash,
                "schema_version": f"{asset_type.replace('_', '-')}.v1",
                "qualification_evidence_asset_version_id": qualification_id,
                "qualification_hash": qualification_hash,
                "activation_id": f"activation:{index}",
                "upstream_digest": "" if index == 1 else "sha256:" + "f" * 64,
            }
        )
    candidate = _document(
        asset_version_id="book-design:v5",
        asset_type="book_design",
        content_hash="sha256:" + "a" * 64,
        lifecycle="CANDIDATE",
        eligibility="INELIGIBLE",
        content={
            "schema_version": "book-design.v5",
            "foundation_set": {
                "schema_version": "qualified-foundation-set.v1",
                "bindings": bindings,
                "set_digest": _canonical_hash(bindings),
            },
        },
    )
    documents[candidate.asset_version_id] = candidate
    binder = object.__new__(PostgresNarrativeEvaluationExecutionContractBinder)
    binder.evaluation_query = _Query(documents)
    writer = _Writer()
    binder.evaluation_writer = writer
    return binder, candidate, writer, documents


def test_book_design_v5_evaluation_resolves_exact_foundation_without_prior_verdicts() -> (
    None
):
    binder, candidate, writer, _ = _binder_fixture()

    binder._evaluation_context_bundle(
        operation_id="operation:evaluate",
        attempt_id="attempt:evaluate",
        project_id="project:test",
        trace_id="trace:test",
        correlation_id="correlation:test",
        pointer={
            "asset_version_id": candidate.asset_version_id,
            "artifact_type": candidate.asset_type,
            "content_hash": candidate.content_hash,
        },
        metadata={
            "generation_operation_id": "operation:generate",
            "generator_operation_name": "book_design.propose",
        },
    )

    assert writer.command is not None
    content = writer.command.content
    assert content["source_isolation"] == ("EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES")
    assert content["dependency_resolution"] == (
        "EVALUATOR_RESOLVED_FROM_CANDIDATE_LINEAGE"
    )
    assert [item.get("dependency_role") for item in content["selected_inputs"]] == [
        None,
        *FOUNDATION_TYPES,
    ]
    assert len(content["dependency_lineage"]) == 6
    assert all(
        item["asset_type"] != "narrative_design_evaluation"
        for item in content["selected_inputs"]
    )
    assert len(writer.command.reference_asset_ids) == 13


def test_book_design_v5_evaluation_fails_closed_on_dependency_hash_drift() -> None:
    binder, candidate, _, documents = _binder_fixture()
    documents["foundation:4"] = replace(
        documents["foundation:4"],
        content_hash="sha256:" + "0" * 64,
    )

    with pytest.raises(KernelError, match="NARRATIVE_EVALUATION_DEPENDENCY_DRIFT"):
        binder._evaluation_context_bundle(
            operation_id="operation:evaluate",
            attempt_id="attempt:evaluate",
            project_id="project:test",
            trace_id="trace:test",
            correlation_id="correlation:test",
            pointer={
                "asset_version_id": candidate.asset_version_id,
                "artifact_type": candidate.asset_type,
                "content_hash": candidate.content_hash,
            },
            metadata={
                "generation_operation_id": "operation:generate",
                "generator_operation_name": "book_design.propose",
            },
        )
