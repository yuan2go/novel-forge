from __future__ import annotations
from novel_forge.modules.command_kernel.errors import KernelError

_METHODS = {
    "reader-feedback": {"reader_outcome": "Reader outcome"},
    "topic-development": {"creative.candidates.generate": "Creative direction", "reader.promise.generate": "Reader promise"},
    "long-outline": {"ending.intent.generate": "Ending intent", "book_plan.generate": "Book planning", "volume_plan.generate": "Volume planning", "arc_plan.generate": "Arc planning", "chapter_group_plan.generate": "Chapter-group planning"},
    "worldbuilding": {"world.design.generate": "World design", "world_candidates.generate": "World design", "world_candidates.evaluate": "World design"},
    "character-design": {"character.cast.generate": "Character cast"},
    "narrative-beat-design": {"theme.candidates.generate": "Theme question"},
    "chapter-outline": {"chapter_plan.generate": "Chapter planning", "memo": "Memo", "world_candidates.generate": "World transition proposals", "world_candidates.evaluate": "World transition evaluation", **{f"world_candidates.actor_{index}": "Actor intention" for index in range(3)}},
    "context-builder-source-isolation": {"retrieval": "Retrieval expansion", "retrieval_query_expansion": "Retrieval expansion", "context_compress": "Context compression", "context_fidelity": "Context fidelity"},
    "prose-generation": {"draft": "Draft", "revision": "Full revision", "screenplay_generate": "Screenplay generation", "screenplay_revision": "Screenplay revision"},
    "quality-review": {"review": "Chapter review", "rereview": "Chapter review", "narrative_semantic_evaluation": "Design evaluation", "longform_prose_review": "Longform review", "screenplay_review": "Screenplay review"},
}
_VERSIONS = {
    "reader-feedback": "reader-feedback-v2",
    "prose-generation": "prose-generation-v4",
    "chapter-outline": "chapter-plan-skill-v3",
    "quality-review": "quality-review-v5",
    "context-builder-source-isolation": "context-builder-source-isolation-v2",
    "long-outline": "long-outline-v2",
}


def project_sections(text: str, *headings: str) -> str:
    sections: dict[str, str] = {}
    for part in ("\n" + text).split("\n## ")[1:]:
        heading, separator, body = part.partition("\n")
        if not separator or heading in sections:
            raise KernelError("PROMPT_METHOD_PROJECTION_INVALID", "frozen method headings must be distinct")
        sections[heading] = body.strip()
    if any(heading not in sections for heading in headings):
        raise KernelError("PROMPT_METHOD_PROJECTION_INVALID", "frozen artifact is missing its declared stage method")
    return "\n\n".join("## " + heading + "\n\n" + sections[heading] for heading in headings)


def project_skill_method(text: str, *, ref: str, version: str, stage: str, targeted: bool) -> str:
    calibrated = version == _VERSIONS.get(ref) or (ref == "long-outline" and version in {"long-outline-v3", "long-outline-v4", "long-outline-v5"}) or (ref == "narrative-beat-design" and version == "narrative-beat-design-qualification-v3") or (ref in _METHODS and version == ref + "-qualification-v2")
    calibrated = calibrated or (ref in _METHODS and version == ref + "-qualification-v4")
    calibrated = calibrated or (ref == "quality-review" and version in {"quality-review-v3", "quality-review-v4"})
    calibrated = calibrated or (ref == "prose-generation" and version == "prose-generation-v5")
    if not calibrated:
        return text
    method = "Quality dimension" if ref == "quality-review" and stage.startswith("quality_") else _METHODS[ref].get(stage)
    if ref == "prose-generation" and stage == "revision" and targeted:
        method = "Targeted revision"
    if method is None:
        raise KernelError("PROMPT_METHOD_STAGE_UNSUPPORTED", "calibrated Skill has no method for the frozen stage")
    return project_sections(text, "Shared rules", method)


def project_planning_system(text: str, *, stage: str, narrative_intent_boundary: bool = False) -> str:
    methods = {
        "creative.candidates.generate": "Foundation", "theme.candidates.generate": "Foundation",
        "ending.intent.generate": "Foundation", "reader.promise.generate": "Foundation",
        "world.design.generate": "Foundation", "character.cast.generate": "Foundation",
        "book_plan.generate": "Book plan", "volume_plan.generate": "Volume plan",
        "arc_plan.generate": "Arc plan", "chapter_group_plan.generate": "Chapter group",
        "chapter_plan.generate": "Chapter plan", "world_candidates.generate": "World proposals", "world_candidates.evaluate": "World evaluation",
        **{f"world_candidates.actor_{index}": "Actor intention" for index in range(3)},
    }
    if stage not in methods:
        raise KernelError("PROMPT_METHOD_STAGE_UNSUPPORTED", "calibrated Planning System has no method for the frozen stage")
    headings = ["Shared rules", methods[stage]]
    if stage in {"world.design.generate", "character.cast.generate"} or stage.endswith("_plan.generate"):
        headings.append("Realization references")
    if narrative_intent_boundary:
        headings.append("Narrative intent boundary")
        if stage == "chapter_plan.generate":
            headings.append("Chapter serialization realization")
        if stage.endswith("_plan.generate"):
            headings.append("Host source selectors and scheduled Arc scope")
        if stage.startswith("world_candidates."):
            headings.append("World agency")
    return project_sections(text, *headings)


def project_chapter_template(text: str, *, stage: str) -> str:
    method = ("Review" if stage in {"review", "rereview", "longform_prose_review"}
              else "Revision" if stage == "revision"
              else "Canon" if stage in {"canon_extraction", "canon_support"}
              else "Quality" if stage.startswith("quality_") else None)
    return project_sections(text, "Shared rules", *([method] if method else []))
