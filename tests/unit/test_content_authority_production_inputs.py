from __future__ import annotations

import pytest

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority import CONTENT_CODECS


def _request(name: str, content: dict) -> AuthorityHandlerRequest:
    return AuthorityHandlerRequest(
        operation_id="operation:input",
        project_id="project:input",
        workspace_id="workspace:input",
        actor_id="operator:input",
        trace_id="trace:input",
        correlation_id="correlation:input",
        definition_name=name,
        definition_version="2.1.1",
        command={
            "project_id": "project:input",
            "input_asset_version_ids": [],
            "payload": {"content": content},
        },
        inputs=(),
    )


@pytest.mark.parametrize(
    ("name", "asset_type", "specific"),
    (
        (
            "chapter.plan.author",
            "chapter_plan",
            {
                "chapter": 1,
                "title": "The Cost of Memory",
                "premise": "A clerk must expose a falsified public record.",
                "chapter_objective": "Make the clerk choose proof over safety.",
                "scene_sequence": [{"scene_id": "s1", "goal": "find proof"}],
                "chapter_hook": "The erased witness returns.",
            },
        ),
        (
            "chapter.style_policy.author",
            "style_policy",
            {"profile_id": "style:proof", "constraints": ["close third person"]},
        ),
        (
            "chapter.quality_rubric.author",
            "quality_rubric",
            {"profile_id": "quality:proof", "dimensions": ["continuity"]},
        ),
        (
            "chapter.platform_profile.author",
            "platform_profile",
            {"profile_id": "platform:proof", "constraints": ["strong hook"]},
        ),
    ),
)
def test_operator_authored_production_input_is_typed_and_source_safe(
    name: str,
    asset_type: str,
    specific: dict,
) -> None:
    output = CONTENT_CODECS[name].execute(
        _request(
            name,
            {
                **specific,
                "type": asset_type,
                "safe_summary": f"Safe {asset_type} production input.",
                "structured_facts": [{"kind": asset_type, "value": "proof"}],
            },
        )
    )

    assert output.asset_type == asset_type
    assert output.content["evidence_level"] == "OPERATOR_AUTHORED"
    assert output.content["raw_source"] is False
    assert output.content["source_expression_included"] is False


def test_operator_authored_input_rejects_raw_source() -> None:
    with pytest.raises(KernelError, match="cannot contain raw source"):
        CONTENT_CODECS["chapter.style_policy.author"].execute(
            _request(
                "chapter.style_policy.author",
                {
                    "type": "style_policy",
                    "profile_id": "style:proof",
                    "constraints": ["concise"],
                    "safe_summary": "Safe policy.",
                    "structured_facts": [],
                    "raw_source": True,
                },
            )
        )
