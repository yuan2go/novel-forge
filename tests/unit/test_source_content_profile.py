from __future__ import annotations

import pytest

from novel_forge.modules.source_import import (
    analysis_profile,
    classify_source_content,
    plan_analysis_tasks,
)


def _fiction_text() -> str:
    return """第一章\n他说：“你终于来了。”她说：“我一直在等。”\n突然有人走进房间，他看着窗外，后来又问道。\n第二章\n“为什么？”“因为必须如此。”此时她心想，回答已经没有意义。\n第三章\n“走吧。”“现在？”“现在。”他说完便离开。\n"""


def test_auto_profile_routes_explicit_classic_metadata_to_classic_literature() -> None:
    profile = classify_source_content(
        paths=("经典文学/长篇小说.txt",),
        text=_fiction_text(),
    )

    assert profile.selected_analysis_profile == "classic_literature"
    assert profile.content_family == "FICTION"
    assert profile.content_type == "CLASSIC_LITERATURE"
    assert profile.confidence >= 0.72
    assert profile.manual_review_required is False


def test_auto_profile_routes_general_fiction_to_published_fiction() -> None:
    profile = classify_source_content(
        paths=("文学/长篇小说.txt",),
        text=_fiction_text(),
    )

    assert profile.selected_analysis_profile == "published_fiction"
    assert profile.content_type == "PUBLISHED_FICTION"
    assert profile.manual_review_required is False


def test_auto_profile_routes_professional_book_by_domain_and_concept_structure() -> None:
    profile = classify_source_content(
        paths=("经济学/宏观经济学.txt",),
        text=(
            "第一章 理论与定义\n本章定义总需求模型，并说明研究假设、数据、方法和结论。\n"
            "第二章 机制与约束\n讨论模型的适用范围、证据和案例。\n"
        ),
    )

    assert profile.selected_analysis_profile == "professional_knowledge"
    assert profile.content_type == "PROFESSIONAL_KNOWLEDGE"
    assert "economics" in profile.domain_tags
    assert profile.manual_review_required is False


def test_auto_profile_routes_writing_theory_and_platform_rules_separately() -> None:
    writing = classify_source_content(
        paths=("写作理论/小说创作方法.md",),
        text="小说创作需要理解故事结构、人物塑造、情节设计与叙事学。",
    )
    platform = classify_source_content(
        paths=("平台规则/作者签约规则.md",),
        text="作者后台的签约规则、内容规范、上架审核、推荐位和订阅规则如下。",
    )

    assert writing.selected_analysis_profile == "writing_theory"
    assert platform.selected_analysis_profile == "platform_rules"


def test_auto_profile_fails_closed_when_evidence_is_ambiguous() -> None:
    profile = classify_source_content(
        paths=("notes.txt",),
        text="一些零散记录，没有足够上下文。",
    )

    assert profile.selected_analysis_profile == "unknown"
    assert profile.manual_review_required is True
    assert "insufficient_classification_evidence" in profile.signals


def test_explicit_profile_override_remains_authoritative() -> None:
    profile = classify_source_content(
        paths=("unknown.txt",),
        text="ambiguous content",
        requested_profile="professional_knowledge",
    )

    assert profile.selected_analysis_profile == "professional_knowledge"
    assert profile.confidence == 1.0
    assert profile.manual_review_required is False
    assert profile.signals == ("operator_profile_override",)


def test_analysis_profiles_use_source_specific_skills() -> None:
    assert (
        analysis_profile("web_novel").analysis_skill_id
        == "hot-novel-deconstruction"
    )
    assert (
        analysis_profile("published_fiction").analysis_skill_id
        == "published-fiction-craft-analysis"
    )
    assert (
        analysis_profile("classic_literature").analysis_skill_id
        == "classic-literary-depth-analysis"
    )
    assert (
        analysis_profile("professional_knowledge").analysis_skill_id
        == "multidisciplinary-knowledge"
    )


def test_planner_freezes_profile_identity_in_analyzer_contract() -> None:
    tasks = plan_analysis_tasks(
        profile_id="classic_literature",
        source_document_id="source:classic",
        chunks=(
            {"asset_version_id": "chunk:v1", "chunk_index": 0},
            {"asset_version_id": "chunk:v2", "chunk_index": 1},
        ),
    )

    assert tasks
    assert all(task.profile_id == "classic_literature" for task in tasks)
    assert all(
        task.analyzer.skill_id
        in {"classic-literary-depth-analysis", "anti-copy-abstraction"}
        for task in tasks
    )
    assert all("classic_literature" in task.stable_key for task in tasks)


def test_auto_profile_cannot_reach_analysis_planner_unresolved() -> None:
    with pytest.raises(ValueError, match="AUTO Source profile"):
        plan_analysis_tasks(
            profile_id="auto",
            source_document_id="source:auto",
            chunks=({"asset_version_id": "chunk:v1", "chunk_index": 0},),
        )
