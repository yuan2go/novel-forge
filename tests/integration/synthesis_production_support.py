from __future__ import annotations

import json

from novel_forge.modules.provider_control.scripted import ScriptedProviderAdapterV2
from novel_forge.modules.story_planning_runtime.foundation_generation import (
    FOUNDATION_GENERATORS,
)
from novel_forge.modules.book_design_authority.foundation import FoundationRole
from tests.integration.hierarchy_closure_postgres_support import _payload


class SynthesisTransport(ScriptedProviderAdapterV2):
    def __init__(self):
        super().__init__()
        self.calls = []

    def planning(self, stage, inputs):
        if stage not in FOUNDATION_GENERATORS:
            from novel_forge.modules.story_planning_runtime.execution import (
                planning_fixture_response,
            )

            return planning_fixture_response(stage, inputs)
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

            result["world_foundation_json"] = json.dumps(compiled_world_fixture())
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
        return result
