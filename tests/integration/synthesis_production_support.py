from __future__ import annotations

from tests.integration.creative_grounding_support import CreativeGroundingTransport

import json

from novel_forge.modules.provider_control.scripted import ScriptedProviderAdapterV2
from novel_forge.modules.story_planning_runtime.foundation_generation import (
    FOUNDATION_GENERATORS,
    foundation_output_schema,
)
from novel_forge.modules.book_design_authority.foundation import FoundationRole
from tests.integration.hierarchy_closure_postgres_support import _payload


class SynthesisTransport(ScriptedProviderAdapterV2):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.chapter = SynthesisChapterTransport()

    def planning(self, stage, inputs):
        if stage not in FOUNDATION_GENERATORS:
            return self.chapter.planning(stage, inputs)
        self.calls.append({"stage": stage, "input": inputs})
        role = FOUNDATION_GENERATORS[stage]
        parents = {
            parent: {
                "asset_version_id": "provider-must-not-author-authority-ref",
                "content_hash": "provider-must-not-author-authority-ref",
            }
            for parent in role.required_parents
        }
        result = _payload(role, parent_candidates=parents)
        result.pop("foundation_parent_bindings", None)
        result["constraints"] = [
            "Every discovery forces a costly choice; uncertainty cannot be erased by narration"
        ]
        result["prohibited_outcomes"] = [
            "Do not resolve conflict by inventing new powers"
        ]
        if role is FoundationRole.CREATIVE_FOUNDATION:
            result["style_profile"] = {
                "narrator": "Concrete observations before interpretation",
                "pov": "Limited to the witness whose uncertainty drives the scene",
                "genre_conventions": ["Reveal evidence before explanations"],
                "constraints": [
                    "Do not disclose knowledge unavailable to the viewpoint"
                ],
                "original_examples": [
                    {
                        "purpose": "Let hesitation expose uncertainty",
                        "example": "她按住地图的一角，没有把那个名字念出来。",
                        "explanation": "A physical choice carries the withheld knowledge",
                    }
                ],
            }
        elif role is FoundationRole.THEME_CONTRACT:
            result.pop("genre")
            result.update(
                opposing_answers=["Collective witness", "Private certainty"],
                choice_tests=[
                    {
                        "choice": "Publish incomplete evidence",
                        "cost": "Expose a witness",
                        "thematic_pressure": "Truth must remain accountable",
                    }
                ],
            )
        elif role is FoundationRole.ENDING_INTENT:
            result.pop("genre")
            result.update(
                closure_conditions=["People can contest the public record"],
                unacceptable_shortcuts=["An omniscient archive solves trust"],
            )
        elif role is FoundationRole.READER_PROMISE:
            result.pop("genre")
            result.update(
                setup_progress_payoff=[
                    {
                        "promise": "Explain the erased district",
                        "setup": "An inconsistent map",
                        "progress": "A witness pays for a public correction",
                        "payoff": "Collective custody preserves access",
                    }
                ],
                disappointment_risks=["A revelation without cost"],
            )
        elif role is FoundationRole.WORLD_BIBLE:
            from tests.integration.narrative_reality_vertical_support import (
                compiled_world_fixture,
            )

            world = compiled_world_fixture()
            world["compiled_scope"] = "BOOK"
            result["world_foundation_json"] = json.dumps(world)
            result.update(
                dimensions=[
                    {
                        "dimension": "information",
                        "scope": "harbor district",
                        "current_need": "Witnesses contest erasure",
                        "definition": "Public testimony resists erasure",
                        "constraints": "The witness can recant",
                        "extension_trigger": "A second district disputes jurisdiction",
                    }
                ],
                factions=[],
                deferred_dimensions=[
                    {
                        "dimension": "religion",
                        "reason": "Not involved in this conflict",
                        "trigger": "Religious institutions claim custody",
                    }
                ],
            )
        else:
            result.update(relationships=[])
            for character in result["characters"]:
                character["private_history"] = character.pop("secret")
                character.update(
                    narrative_function="Force public choices about incomplete evidence",
                    background="An apprentice who trusted one map too much",
                    contradiction="Values truth but withholds uncertainty",
                    behavioral_pattern="Checks a boundary before naming its cause",
                    risk_preference="Accepts personal exposure before risking a witness",
                    voice_anchors=[
                        {
                            "situation": "Asked for certainty",
                            "utterance": "我只能担保我亲眼看见的。",
                            "motivation": "A former error makes certainty costly",
                        }
                    ],
                )
        if (inputs.get("foundation_task") or {}).get("contract_version") in {"foundation-generation.v2", "foundation-generation.v3", "foundation-generation.v4"}:
            result["applicability"] = []
            def declare(value, schema, path="$", parent_present=True):
                if isinstance(schema.get("type"), list) and "null" in schema["type"]:
                    result["applicability"].append({"field_path": path,
                        "status": "APPLICABLE" if value is not None else "NOT_APPLICABLE",
                        "rationale": "Explicit strategy of this synthetic design fixture"})
                if isinstance(value, dict):
                    for key, child in schema.get("properties", {}).items():
                        if key in value:
                            declare(value[key], child, path+"."+key)
                elif isinstance(value, list):
                    for index, child in enumerate(value):
                        declare(child, schema.get("items", {}), f"{path}[{index}]")
            declare(result, foundation_output_schema(stage, work_requirements=True))
        return result


class SynthesisChapterTransport(CreativeGroundingTransport):
    def planning(self, stage, inputs):
        if stage == "world_candidates.generate":
            if inputs["world_preparation"]["accepted_through_chapter"] >= 2:
                result = {
                    "disposition": "NO_OP",
                    "reason": "This bounded scripted arc proposes no further world event after its disclosure chapter.",
                    "candidates": [],
                }
                self.calls.append({"stage": stage, "input": inputs, "output": result})
                return result
        result = super().planning(stage, inputs)
        if (inputs.get("planning_command") or {}).get("creative_requirements_contract") in {"work-requirements.v1", "work-requirements.v2"}:
            for row in result.get("chapter_function_matrix", []):
                row["required_state_delta"] = {"status": "CHANGED", **row["required_state_delta"]}
            for event in result.get("narrative_event_chain", []):
                event["feature_status"] = {name: {"status": "APPLICABLE", "rationale": "Selected causal strategy of this synthetic mystery fixture"} for name in ("decision", "resistance", "irreversible_change")}
            if stage == "chapter_plan.generate":
                if inputs["planning_command"].get("execution_contract_version") == "1.19.0":
                    result["chapter_contract_schema_version"] = "chapter-mission-scene.v4"
                    result["serialization_function"] = "payoff_and_new_obligation"
                else:
                    result["chapter_contract_schema_version"] = "chapter-mission-scene.v3"
                result["required_state_delta"] = {"status": "CHANGED", **result["required_state_delta"]}
        return result


class AdviceOnlySynthesisChapterTransport(SynthesisChapterTransport):
    def __init__(self):
        super().__init__(retain_original=True)

    def __call__(self, stage, inputs):
        from copy import deepcopy

        result = super().__call__(stage, inputs)
        if stage == "review":
            text = inputs["draft"]["text"]
            result["issues"] = [{
                "code": "OPTIONAL_SHORTER_SENTENCE", "severity": "minor",
                "category": "STYLE_PREFERENCE", "judgment_kind": "AESTHETIC_SUGGESTION",
                "message": "A shorter sentence is an optional taste suggestion.",
                "evidence": {"start": 0, "end": min(30, len(text)), "quote": text[:30]},
                "violated_constraint": "No selected requirement is violated.",
                "revision_goal": "Optional suggestion only.",
                "preserve": ["All accepted author choices and current prose."],
                "acceptance_criteria": ["Keep current prose unless the author chooses otherwise."],
                **({"supporting_evidence": [], "lineage_code": None, "confidence": "LOW", "interpretation": "UNCERTAIN"} if inputs.get("cross_chapter_window") else {}),
            }]
            if inputs.get("cross_chapter_window"):
                result["preservation_checks"] = []
        elif stage == "revision":
            review = inputs["review"]
            result = (
                {"edits": [], "resolved_issue_codes": []}
                if review.get("cross_chapter_window") or review.get("craft_targets")
                else {
                    "text": inputs["draft"]["text"],
                    "scene_artifacts": deepcopy(inputs["draft"]["scene_artifacts"]),
                    "resolved_issue_codes": [],
                }
            )
        elif stage == "rereview":
            result["resolution_checks"] = []
            if inputs["review"].get("cross_chapter_window"):
                from novel_forge.modules.review.prose_window import PRESERVATION_DIMENSIONS

                text = inputs["revision"]["text"]
                evidence = {"start": 0, "end": min(30, len(text)), "quote": text[:30]}
                result["resolution_checks"] = [{
                    "code": issue["code"], "status": "NOT_APPLICABLE", "preservation": "PRESERVED",
                    "evidence": evidence, "supporting_evidence": [],
                    "reason": "Optional taste advice creates no required prose repair.",
                } for issue in inputs["review"]["issues"]]
                result["preservation_checks"] = [{
                    "dimension": dimension, "status": "PRESERVED", "evidence": evidence,
                    "reason": "The exact source prose and slots are unchanged in this synthetic run.",
                } for dimension in PRESERVATION_DIMENSIONS]
        self.calls[-1]["output"] = deepcopy(result)
        return result
