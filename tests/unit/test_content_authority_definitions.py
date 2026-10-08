from __future__ import annotations
import unittest
from novel_forge.modules.content_authority import (
    CONTENT_DOMAIN_HANDLERS,
    content_operation_definitions,
)


class ContentAuthorityDefinitionTests(unittest.TestCase):
    def test_every_definition_has_a_codec_handler_and_postgresql_proof_maturity(self):
        definitions = content_operation_definitions(
            application_build_id="test", commit_sha="a" * 40
        )
        names = {item["name"] for item in definitions}
        self.assertEqual(names, set(CONTENT_DOMAIN_HANDLERS) - {
            "quality.model_reference_evaluation.record", "quality.model_reference_adjudication.record"})
        self.assertTrue(
            {
                "book.production_profile.author",
                "book.previous_volume_outcome.author",
                "book.previous_chapter_group_outcome.author",
                "book.previous_chapter_outcome.author",
                "book.arc_portfolio.author",
                "book.ending_reachability.author",
                "book.character_arc_portfolio.author",
                "book.conflict_state.author",
                "book.foreshadowing_ledger.author",
                "book.reader_segment.author",
                "book.reader_contract.author",
                "book.reader_state.author",
                "book.character_state.author",
                "book.foreshadowing_state.author",
                "book.quality_trend.author",
                "book.reward_ledger.author",
                "book.promise_ledger.author",
                "book.initial_story_state.author",
                "book.initial_canon.author",
                "story_design.creative_foundation.author",
                "story_design.theme_contract.author",
                "story_design.ending_intent.author",
                "story_design.reader_promise.author",
                "story_design.world_bible.author",
                "story_design.character_cast.author",
                "story_design.review.author",
                "chapter.fixture_waiver_approval.author",
            }.issubset(names)
        )
        for item in definitions:
            self.assertTrue(callable(CONTENT_DOMAIN_HANDLERS[item["name"]]))
            self.assertEqual(item["definition_status"], "integration_proven")
            self.assertTrue(item["enabled"])
            self.assertTrue(item["evidence_status"]["implemented"])
            self.assertTrue(item["evidence_status"]["integration_proven"])
            self.assertTrue(item["evidence_status"]["product_entrypoint_integrated"])
            self.assertFalse(item["evidence_status"]["real_provider_proven"])
            self.assertTrue(item["completion_contract"]["required_asset_selectors"])
            self.assertIn(
                "POST /product/content-authority/commands", item["current_entrypoints"]
            )
            self.assertEqual(
                item["agent_capability"]["execution_authority"], "authority_operation"
            )
            self.assertEqual(item["permissions"], [f"content.operation:{item['name']}"])

    def test_explicit_unproven_registration_remains_disabled(self):
        definitions = content_operation_definitions(
            application_build_id="test",
            commit_sha="a" * 40,
            integration_proven=(),
        )
        self.assertTrue(all(not item["enabled"] for item in definitions))
        self.assertTrue(
            all(item["definition_status"] == "handler_bound" for item in definitions)
        )

    def test_reference_annotation_exception_is_versioned_and_scoped(self):
        ordinary = content_operation_definitions(application_build_id="test", commit_sha="a" * 40)
        references = content_operation_definitions(application_build_id="test", commit_sha="a" * 40,
                                                   reference_annotations=True)
        self.assertEqual({item["name"] for item in references}, {
            "quality.human_evaluation.record", "quality.adjudication.record"})
        self.assertTrue(all(item["definition_version"] == "2.2.0" and
                            item["policy"]["reference_sample_annotation_input_allowed"] for item in references))
        self.assertTrue(all(item["definition_version"] == ("2.1.2" if item["name"] == "story_design.review.author" else "2.1.5" if item["name"] == "creative.brief.create" else "2.1.4" if item["name"] == "chapter.style_policy.compile" else "2.1.1") and
                            "reference_sample_annotation_input_allowed" not in item["policy"] for item in ordinary))
        model = content_operation_definitions(application_build_id="test", commit_sha="a" * 40,
            model_reference_annotations=True)
        self.assertEqual({item["name"] for item in model}, {
            "quality.model_reference_evaluation.record", "quality.model_reference_adjudication.record"})
        self.assertTrue(all(item["definition_version"] == "2.5.0" and
            item["policy"]["model_reference_annotation_input_allowed"] for item in model))
        world = content_operation_definitions(application_build_id="test", commit_sha="a" * 40,
            reference_annotations=True, world_reference_annotations=True)
        self.assertTrue(all(item["definition_version"] == "2.3.0" and item["policy"]["world_reference_sample_annotation"] for item in world))
        self.assertTrue(all("world_reference_sample_annotation" not in item["policy"] for item in references))


if __name__ == "__main__":
    unittest.main()
