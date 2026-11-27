from __future__ import annotations

import json
from pathlib import Path
import unittest

from novel_forge.modules.production_preparation.policies import STAGE_PROFILES


ROOT = Path(__file__).resolve().parents[2]


class KnowledgeContractTests(unittest.TestCase):
    def test_capability_pack_and_preparation_use_capability_optional_knowledge(self) -> None:
        pack = json.loads(
            (
                ROOT
                / "config/capability_packs/chapter_generation_pack.json"
            ).read_text(encoding="utf-8")
        )
        policy = pack["assets"]["knowledge"]["project_knowledge_pack"]
        self.assertEqual(policy["default_requirement"], "OPTIONAL")
        self.assertEqual(policy["required_stages"], [])
        self.assertEqual(policy["required_capability_ids"], [])
        self.assertTrue(
            all(
                profile.knowledge_pack_policy == "CAPABILITY_OPTIONAL"
                for profile in STAGE_PROFILES.values()
            )
        )

    def test_context_skill_does_not_claim_universal_knowledge_pack_requirement(self) -> None:
        source = (
            ROOT / "skills/context-builder-source-isolation/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Capability Pack / stage", source)
        self.assertIn("OPTIONAL", source)
        self.assertNotIn(
            "所有核心生产动作必须通过 Context Builder 形成 `context_bundle_id` 和 `knowledge_pack_id`",
            source,
        )


if __name__ == "__main__":
    unittest.main()
