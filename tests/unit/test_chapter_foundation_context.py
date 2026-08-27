from __future__ import annotations

import json

import pytest

from novel_forge.modules.chapter_authority.domain_handlers import build_context_bundle
from novel_forge.modules.chapter_authority.domain_handlers import build_canon_patch
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_context_view,
    build_provider_task_view,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_preparation.foundation_context import (
    project_character_foundation_context,
    project_reader_promise_context,
)


def _character_cast(*, executable_identity: bool = True) -> dict:
    identity = (
        {"name": "林遥", "aliases": ["林遥"], "pronouns": ["她"]}
        if executable_identity
        else {}
    )
    return {
        "schema_version": "story_design.authority.v1",
        "generator_operation_name": "character.cast.generate",
        "candidate_payload": {
            "characters": [
                {
                    "character_id": "lin-yao",
                    **identity,
                    "desire": "恢复被抹去的雾桥街",
                    "need": "把地图控制权交给共同程序",
                    "fear": "不完整公开会伤害见证者",
                    "wound": "她曾因独断标注误导救援队",
                    "false_belief": "只有她掌握全部证据时公开才安全",
                    "values": ["truth", "care"],
                    "moral_boundary": "不替见证者签名",
                    "agency": "选择何时公开异常",
                    "capability": "判断地图修改顺序",
                    "weakness": "把隐瞒误认为保护",
                    "voice": "精确克制",
                    "secret": "她私藏半枚印章",
                    "relationship_function": "学习共享责任",
                    "arc_direction": "从独占确定性走向共同保管",
                }
            ]
        },
    }


def _reader_promise() -> dict:
    return {
        "schema_version": "story_design.authority.v1",
        "generator_operation_name": "reader.promise.generate",
        "candidate_payload": {
            "objective": "约束发现、代价、反制和回报的连续节奏",
            "reader_promise": (
                "每章揭示一个可验证的地图异常，迫使主角作出有代价的公开选择，"
                "并使档案署反制升级"
            ),
        },
    }


def _plan() -> dict:
    return {
        "chapter": 1,
        "title": "签名之前",
        "premise": "林遥必须决定是否公开异常。",
        "chapter_objective": "用有代价的选择推进首个异常。",
        "scene_sequence": [{"scene_id": "scene:1", "goal": "公开或撤回"}],
        "character_participation": [
            {"character_id": "林遥", "goal": "保存可复核证据"}
        ],
    }


def _governed_candidate(
    *, asset_type: str, asset_version_id: str, content_hash: str, projection: dict
) -> dict:
    return {
        "asset_version_id": asset_version_id,
        "asset_type": asset_type,
        "physical_asset_type": asset_type,
        "project_id": "project:quality",
        "content_hash": content_hash,
        "content_digest": content_hash,
        "qualification": "ELIGIBLE",
        "governance_status": "CLEAR",
        "source_use_mode": "generation",
        "allowed_use": "generation",
        **projection,
    }


def test_historical_unbound_character_cast_is_rejected_before_provider() -> None:
    with pytest.raises(KernelError, match="CHARACTER_IDENTITY_CONTRACT_INCOMPLETE"):
        project_character_foundation_context(
            asset_type="character_cast",
            content=_character_cast(executable_identity=False),
            source_asset_version_id="character-cast:historical-failure",
        )


def test_character_and_reader_promise_are_protected_in_draft_and_review() -> None:
    character_projection = project_character_foundation_context(
        asset_type="character_cast",
        content=_character_cast(),
        source_asset_version_id="character-cast:v2",
    )
    promise_projection = project_reader_promise_context(
        content=_reader_promise(),
        source_asset_version_id="reader-promise:v1",
    )
    candidates = [
        _governed_candidate(
            asset_type="character_cast",
            asset_version_id="character-cast:v2",
            content_hash="sha256:" + "1" * 64,
            projection=character_projection,
        ),
        _governed_candidate(
            asset_type="reader_promise",
            asset_version_id="reader-promise:v1",
            content_hash="sha256:" + "2" * 64,
            projection=promise_projection,
        ),
    ]
    bundle = build_context_bundle(
        plan=_plan(),
        plan_asset_version_id="chapter-plan:v1",
        plan_content_hash="sha256:" + "3" * 64,
        project_id="project:quality",
        created_by_operation_id="operation:context",
        governed_candidates=candidates,
        required_asset_types=("character_cast", "reader_promise"),
        token_budget=6_000,
        book_id="book:quality",
    )

    protected = {
        item["asset_type"]: item
        for item in bundle["context_segments"]
        if item["asset_type"] in {"character_cast", "reader_promise"}
    }
    assert set(protected) == {"character_cast", "reader_promise"}
    assert {item["context_class"] for item in protected.values()} == {"PROTECTED"}
    assert {item["compression_method"] for item in protected.values()} == {
        "authority_projection"
    }

    draft = build_provider_context_view(
        "draft",
        bundle,
        build_provider_task_view("draft", {"plan": _plan(), "style": {}}),
    )
    review = build_provider_context_view(
        "review",
        bundle,
        build_provider_task_view(
            "review", {"draft": {"chapter": 1, "text": "正文"}}
        ),
    )
    for view in (draft, review):
        serialized = json.dumps(view, ensure_ascii=False, sort_keys=True)
        assert "林遥" in serialized
        assert "lin-yao" in serialized
        assert "她" in serialized
        assert "每章揭示一个可验证的地图异常" in serialized
        assert "provider_generated" not in serialized

    canon = build_canon_patch(
        revision={
            "chapter": 1,
            "text": "收档钟敲过第一遍时，林遥还蹲在路沿边。\n\n他把底图压在膝上。",
        },
        revision_asset_version_id="revision:real-failure:93846845",
        project_id="project:quality",
        context_bundle_version_id="context:v1",
        context_bundle=bundle,
    )
    assert canon["gate"] == "BLOCKED"
    assert "CHARACTER_IDENTITY_PRONOUN_CONTRADICTION" in {
        item["conflict_code"] for item in canon["conflicts"]
    }
