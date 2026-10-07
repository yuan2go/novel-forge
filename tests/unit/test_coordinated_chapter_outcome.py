from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.domain_handlers import build_publish_gate
from novel_forge.modules.chapter_outcome.application import _ChapterOutcomeRegistry, chapter_outcome_operation_definition
from novel_forge.modules.chapter_outcome.handlers import ChapterOutcomeCommitHandler
from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_reviewed_work_admission import evidence


def request(version="2.1.0"):
    text, review, quality = evidence()
    quality["internal_admission"].update(book_id="book")
    quality.update(canon_patch_version_id="canon_patch", review_asset_version_id="review", context_bundle_version_id="context")
    review.update(diagnostic_contract_version="actionable-diagnostics.v1", context_bundle_version_id="context")
    proof = {"contract_version": "reviewed-work-admission.v2", "review_asset_version_id": "review",
        "quality_asset_version_id": "quality", "candidate_asset_version_id": "selection", "source_review_decision": "NEEDS_REVISION",
        "host_admission": "PASSED", "literary_quality_proven": False}
    values = {"chapter_plan": {}, "best_draft_candidate": {"text": text, "selected_source_asset_version_id": "candidate"},
        "re_review_report": review, "canon_patch": {"gate": "PASSED", "conflicts": [], "state_changes": {}, "source_asset_version_id": "selection", "grounding": {
            "contract_version": "grounded-canon.v1", "project_id": "project", "semantic_status": "SUPPORTED_CANDIDATE",
            "candidate_asset_version_id": "selection", "text_hash": review["target_text_hash"], "context_asset_version_id": "context"}},
        "quality_score_report": quality, "release_package": {"release_status": "READY_FOR_BLOB_VERIFICATION"},
        "final_release_gate_report": {"gate": "INTERNAL_ADMITTED", "release_status": "INTERNAL_VALIDATION_FINALIZED",
            "final_gate_contract_version": "creative-internal-finalize.v1", "internal_admission": deepcopy(quality["internal_admission"]),
            "review_admission": proof}}
    ids = {"best_draft_candidate": "selection", "re_review_report": "review", "quality_score_report": "quality"}
    inputs = {key: SimpleNamespace(asset_version_id=ids.get(key, key), content=value) for key, value in values.items()}
    return SimpleNamespace(project_id="project", database_url="unit-only", operation_id="accept", trace_id="trace", definition_version=version,
        command={"payload": {"book_id": "book", "chapter_number": 1, "chapter_acceptance_contract": "coordinated-chapter-acceptance.v1"}},
        require_input=lambda key: inputs[key], inputs_of_type=lambda key: (), inputs=tuple(inputs.values()))


def test_current_acceptance_requires_exact_proof_and_retains_historical_gate(monkeypatch):
    assert callable(build_publish_gate)
    checks = []
    monkeypatch.setattr("novel_forge.modules.chapter_quality_authority.creative_validation.verify_internal_quality",
        lambda database_url, admission, **scope: checks.append((database_url, admission, scope)))
    output = ChapterOutcomeCommitHandler().execute(request())
    assert output.content["accepted_draft_asset_version_id"] == "selection"
    assert output.qualification_policy == "chapter-outcome-acceptance-v5"
    assert checks[0][2] == {"project_id": "project", "book_id": "book"}
    with pytest.raises(KernelError, match="CHAPTER_ACCEPTANCE_EVIDENCE_BLOCKED"):
        ChapterOutcomeCommitHandler().execute(request("1.1.0"))


@pytest.mark.parametrize("field,value", [("candidate_asset_version_id", "foreign"), ("review_asset_version_id", "foreign"),
    ("quality_asset_version_id", "foreign"), ("source_review_decision", "PASSED"), ("literary_quality_proven", True)])
def test_current_acceptance_rejects_substituted_proof_before_receipt_verification(monkeypatch, field, value):
    selected = request()
    selected.require_input("final_release_gate_report").content["review_admission"][field] = value
    monkeypatch.setattr("novel_forge.modules.chapter_quality_authority.creative_validation.verify_internal_quality",
        lambda *args, **kwargs: pytest.fail("Foreign admission must fail before receipt lookup"))
    with pytest.raises(KernelError, match="CHAPTER_ACCEPTANCE_EVIDENCE_BLOCKED"):
        ChapterOutcomeCommitHandler().execute(selected)


def test_new_acceptance_identity_is_explicit_and_old_definition_is_unchanged():
    arguments = {"application_build_id": "build", "commit_sha": "a" * 40}
    old = chapter_outcome_operation_definition(**arguments)
    current = chapter_outcome_operation_definition(**arguments, coordinated_contract=True)
    assert old["definition_version"] == "1.1.0" and current["definition_version"] == "2.1.0"
    assert "chapter_acceptance_contract" not in old["policy"]
    assert current["policy"]["internal_quality_input_contract"] == "creative-quality-admission.v3"
    assert _ChapterOutcomeRegistry().registration("book.chapter.accept", "2.1.0").handler_contract_version == "chapter-outcome-handler-v3"
    with pytest.raises(ValueError):
        chapter_outcome_operation_definition(**arguments, coordinated_contract=True, work_requirements=False)


def test_published_acceptance_definitions_retain_fixed_main_bytes():
    import json
    from pathlib import Path
    frozen = json.loads((Path(__file__).parents[1] / 'fixtures/chapter_outcome_main_9d_definitions.json').read_text())
    for version, work in (('1.0.0', False), ('1.1.0', True)):
        assert chapter_outcome_operation_definition(**frozen['arguments'], work_requirements=work) == frozen['definitions'][version]
