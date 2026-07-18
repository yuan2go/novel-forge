from __future__ import annotations

import unittest

from novel_forge.modules.chapter_authority.model_effects import (
    ChapterModelExternalEffectAdapter,
    ChapterModelRoute,
)
from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.model_adapters.selection import model_for_explicit_route


class _Adapter:
    name = "provider-model"

    def generate(self, prompt, context=None):  # type: ignore[no-untyped-def]
        if "canon-semantic-extraction-v2" in prompt:
            return {
                "canon_facts": [
                    {
                        "subject": "protagonist",
                        "predicate": "paid",
                        "object": "visible_cost",
                        "evidence_start": 0,
                        "evidence_end": 8,
                        "confidence": 0.91,
                    }
                ],
                "character_state_changes": [], "relationship_changes": [],
                "timeline_events": [], "foreshadow_changes": [],
                "promise_changes": [], "reward_changes": [],
                "world_rule_usages": [], "power_state_changes": [],
                "narrative_pattern_fingerprints": [], "theme_movements": [],
                "antagonist_pressure_changes": [],
            }
        if "Evaluate only the requested chapter quality dimensions" in prompt:
            dimensions = list((context or {}).get("dimensions") or [])
            return {
                "dimensions": [
                    {
                        "dimension": dimension,
                        "gate_status": "PASSED",
                        "score": 82,
                        "confidence": 0.84,
                        "evidence_locations": [{"start": 0, "end": 12}],
                        "issue_codes": [],
                        "revision_strategies": [],
                    }
                    for dimension in dimensions
                ],
                "usage": {"input_tokens": 20, "output_tokens": 10},
                "cost": {"amount": "0.02", "currency": "USD"},
            }
        return {
            "text": "A public promise creates a visible debt.",
            "usage": {"input_tokens": 12, "output_tokens": 8},
            "cost": {"amount": "0.01", "currency": "USD"},
        }

    def review(self, content, context=None):  # type: ignore[no-untyped-def]
        return {
            "score": 68,
            "issues": [
                {
                    "dimension": "visible_cost",
                    "severity": "high",
                    "message": "Make the loss irreversible.",
                }
            ],
        }

    def revise(self, content, review, context=None):  # type: ignore[no-untyped-def]
        return {
            "text": "The protagonist surrenders the only safe route home.",
            "resolved_issue_codes": ["VISIBLE_COST"],
        }


class ChapterModelExternalEffectAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ChapterModelExternalEffectAdapter(
            {
                stage: ChapterModelRoute(
                    adapter=_Adapter(),
                    provider_id="provider",
                    model_id=f"model-{stage}",
                    prompt_version=f"prompt-{stage}-v1",
                    skill_version=f"skill-{stage}-v1",
                    real_model_call=True,
                )
                for stage in (
                    "draft", "review", "revision", "canon_extraction",
                    "quality_structural",
                )
            }
        )

    def test_normalizes_stage_specific_model_results(self) -> None:
        draft = self.adapter.execute(
            stable_idempotency_key="draft-key",
            capability="model.draft",
            request_payload={
                "stage": "draft",
                "input": {
                    "plan": {"premise": "promise", "beats": ["choice"]},
                    "context": {"actual_context": {"canon": "fact"}},
                    "style": {"contract_version": "draft-style-view-v1"},
                },
            },
        )
        review = self.adapter.execute(
            stable_idempotency_key="review-key",
            capability="model.review",
            request_payload={
                "stage": "review",
                "input": {"draft": {"text": draft.evidence["result"]["text"]}},
            },
        )
        revision = self.adapter.execute(
            stable_idempotency_key="revision-key",
            capability="model.revision",
            request_payload={
                "stage": "revision",
                "input": {
                    "draft": {"text": draft.evidence["result"]["text"]},
                    "review": review.evidence["result"],
                },
            },
        )

        self.assertEqual(draft.outcome, "success")
        self.assertEqual(draft.evidence["usage"]["total_tokens"], 20)
        self.assertEqual(review.evidence["result"]["decision"], "NEEDS_REVISION")
        self.assertEqual(review.evidence["result"]["issues"][0]["code"], "VISIBLE_COST")
        self.assertEqual(
            revision.evidence["result"]["resolved_issue_codes"],
            ["VISIBLE_COST"],
        )
        extraction = self.adapter.execute(
            stable_idempotency_key="canon-key",
            capability="model.canon_extraction",
            request_payload={
                "stage": "canon_extraction",
                "input": {"revision": {"text": "A visible cost."}, "context": {}},
            },
        )
        self.assertEqual(extraction.outcome, "success")
        self.assertEqual(
            extraction.evidence["result"]["canon_facts"][0]["predicate"], "paid"
        )

        quality = self.adapter.execute(
            stable_idempotency_key="quality-key",
            capability="model.quality_structural",
            request_payload={
                "stage": "quality_structural",
                "input": {
                    "revision": {"text": "A visible cost changes the next choice."},
                    "quality_context": {"type": "StructuralQualityContextView"},
                    "dimensions": ["readability", "scene_completeness"],
                },
            },
        )
        self.assertEqual(quality.outcome, "success")
        self.assertEqual(
            {item["dimension"] for item in quality.evidence["result"]["dimensions"]},
            {"readability", "scene_completeness"},
        )

    def test_quality_response_must_cover_the_exact_frozen_dimension_contract(self) -> None:
        class _Partial(_Adapter):
            def generate(self, prompt, context=None):  # type: ignore[no-untyped-def]
                return {
                    "dimensions": [{
                        "dimension": "readability",
                        "gate_status": "PASSED",
                        "score": 90,
                        "confidence": .9,
                        "evidence_locations": [{"start": 0, "end": 5}],
                    }]
                }

        adapter = ChapterModelExternalEffectAdapter({
            "quality_structural": ChapterModelRoute(
                adapter=_Partial(), provider_id="provider", model_id="model",
                prompt_version="quality-v1", skill_version="quality-skill-v1",
                real_model_call=True,
            )
        })
        result = adapter.execute(
            stable_idempotency_key="quality-partial",
            capability="model.quality_structural",
            request_payload={
                "stage": "quality_structural",
                "input": {
                    "revision": {"text": "A complete chapter."},
                    "quality_context": {"type": "StructuralQualityContextView"},
                    "dimensions": ["readability", "scene_completeness"],
                },
            },
        )

        self.assertEqual(result.outcome, "final_failure")
        self.assertEqual(result.evidence["error_code"], "MODEL_RESPONSE_INVALID")

    def test_quality_response_rejects_unstructured_evidence_locations(self) -> None:
        class _InvalidEvidence(_Adapter):
            def generate(self, prompt, context=None):  # type: ignore[no-untyped-def]
                return {
                    "dimensions": [{
                        "dimension": "readability", "gate_status": "PASSED",
                        "score": 101, "confidence": .9,
                        "evidence_locations": ["chapter looks readable"],
                    }]
                }

        adapter = ChapterModelExternalEffectAdapter({
            "quality_structural": ChapterModelRoute(
                adapter=_InvalidEvidence(), provider_id="provider", model_id="model",
                prompt_version="quality-v1", skill_version="quality-skill-v1",
                real_model_call=True,
            )
        })
        result = adapter.execute(
            stable_idempotency_key="quality-invalid-evidence",
            capability="model.quality_structural",
            request_payload={
                "stage": "quality_structural",
                "input": {
                    "revision": {"text": "A complete chapter."},
                    "quality_context": {"type": "StructuralQualityContextView"},
                    "dimensions": ["readability"],
                },
            },
        )

        self.assertEqual(result.outcome, "final_failure")
        self.assertEqual(result.evidence["error_code"], "MODEL_RESPONSE_INVALID")

    def test_invalid_model_response_is_final_failure_and_query_is_ambiguous(self) -> None:
        class _Invalid(_Adapter):
            def generate(self, prompt, context=None):  # type: ignore[no-untyped-def]
                return {"text": ""}

        adapter = ChapterModelExternalEffectAdapter(
            {
                "draft": ChapterModelRoute(
                    adapter=_Invalid(),
                    provider_id="provider",
                    model_id="model",
                    prompt_version="prompt-v1",
                    skill_version="skill-v1",
                    real_model_call=True,
                )
            }
        )
        result = adapter.execute(
            stable_idempotency_key="key",
            capability="model.draft",
            request_payload={"stage": "draft", "input": {"plan": {}, "context": {}, "style": {}}},
        )
        query = adapter.query(
            stable_idempotency_key="key",
            capability="model.draft",
            request_payload={"stage": "draft", "input": {}},
        )

        self.assertEqual(result.outcome, "final_failure")
        self.assertEqual(result.evidence["error_code"], "MODEL_RESPONSE_INVALID")
        self.assertEqual(query.outcome, "ambiguous")

    def test_explicit_model_route_never_requires_filesystem_policy_lookup(self) -> None:
        adapter = model_for_explicit_route("mock")

        self.assertIsInstance(adapter, MockModelAdapter)
        with self.assertRaisesRegex(ValueError, "explicit model provider is required"):
            model_for_explicit_route("")


if __name__ == "__main__":
    unittest.main()
