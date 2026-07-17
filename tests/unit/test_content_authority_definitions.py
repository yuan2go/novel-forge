from __future__ import annotations
import unittest
from novel_forge.modules.content_authority import CONTENT_DOMAIN_HANDLERS, content_operation_definitions

class ContentAuthorityDefinitionTests(unittest.TestCase):
    def test_every_definition_has_a_concrete_storage_free_handler_and_honest_maturity(self):
        definitions = content_operation_definitions(application_build_id="test", commit_sha="a" * 40)
        self.assertEqual(len(definitions), 22)
        self.assertEqual({item["name"] for item in definitions}, set(CONTENT_DOMAIN_HANDLERS))
        for item in definitions:
            self.assertTrue(callable(CONTENT_DOMAIN_HANDLERS[item["name"]]))
            self.assertEqual(item["definition_status"], "handler_bound")
            self.assertFalse(item["enabled"])
            self.assertTrue(item["evidence_status"]["implemented"])
            self.assertFalse(item["evidence_status"]["integration_proven"])
            self.assertFalse(item["evidence_status"]["real_provider_proven"])
            self.assertTrue(item["completion_contract"]["required_asset_selectors"])

if __name__ == "__main__": unittest.main()
