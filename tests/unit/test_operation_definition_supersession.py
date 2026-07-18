from __future__ import annotations

import unittest

from novel_forge.tools.authority_coverage_manifest import operation_catalog


class OperationDefinitionSupersessionTests(unittest.TestCase):
    def test_historical_draft_is_superseded_by_chapter_authority(self) -> None:
        catalog = {item["name"]: item for item in operation_catalog()}
        old = catalog["production.draft.generate"]
        self.assertEqual(old["definition_status"], "superseded")
        self.assertEqual(old["superseded_by"], "chapter.draft.generate")
        self.assertFalse(old["enabled"])

    def test_export_name_is_an_alias_not_a_missing_feature(self) -> None:
        catalog = {item["name"]: item for item in operation_catalog()}
        old = catalog["production.chapter.export"]
        self.assertEqual(old["definition_status"], "alias")
        self.assertEqual(old["alias_of"], "chapter.export.render")

    def test_unimplemented_generators_remain_honest_candidates(self) -> None:
        catalog = {item["name"]: item for item in operation_catalog()}
        self.assertEqual(catalog["production.topic.generate"]["definition_status"], "candidate")
        self.assertEqual(catalog["production.outline.generate"]["definition_status"], "candidate")
        self.assertEqual(
            catalog["production.chapter_plan.generate"]["definition_status"],
            "candidate",
        )

    def test_book_skeleton_definitions_are_catalogued_as_fixture_proven(self) -> None:
        catalog = {item["name"]: item for item in operation_catalog()}
        self.assertEqual(catalog["book.production.run"]["definition_status"], "integration_proven")
        self.assertFalse(catalog["book.production.run"]["production_verified"])


if __name__ == "__main__":
    unittest.main()
