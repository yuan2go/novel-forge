import pytest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    validate_chapter_provider_output_against_schema,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    PostgresChapterExecutionContractBinder,
)


def contract(targets):
    return PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="review",
        request_payload={
            "input": {
                "draft": {"text": "实际正文", "chapter": 1},
                "knowledge_check_scope": "review-target-scope.v1",
                "knowledge_review_targets": targets,
            }
        },
        prompt_contract_version="v9",
    )


def judgment(identity):
    return {
        "score": 97,
        "issues": [],
        "resolution_checks": [],
        "knowledge_checks": [
            {
                "knowledge_card_asset_version_id": identity,
                "status": "VERIFIED_IN_PROSE",
                "reason": "正文证据",
                "conditions_checked": ["条件已呈现"],
                "exceptions_checked": [],
                "issue_codes": [],
                "evidence": {"quote": "实际正文"},
            }
        ],
    }


def test_no_review_targets_rejects_pack_guidance_as_required_fact_check():
    schema, ref = contract([])
    assert ref.endswith(":v7")
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"):
        validate_chapter_provider_output_against_schema(
            "review", schema, judgment("knowledge:instruction-guidance:v2")
        )
    output = judgment("unused")
    output["knowledge_checks"] = []
    validate_chapter_provider_output_against_schema("review", schema, output)


def test_required_review_card_rejects_other_identity_and_omission():
    schema, ref = contract([{"knowledge_card_asset_version_id": "frozen-card-version"}])
    validate_chapter_provider_output_against_schema(
        "review", schema, judgment("frozen-card-version")
    )
    for output in (
        judgment("some-other-card"),
        {**judgment("unused"), "knowledge_checks": []},
    ):
        with pytest.raises(KernelError, match="CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"):
            validate_chapter_provider_output_against_schema("review", schema, output)
