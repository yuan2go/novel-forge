from __future__ import annotations

import unittest

from novel_forge.modules.book_design_authority.definitions import (
    BOOK_DESIGN_OPERATIONS,
    book_design_definitions,
)
from novel_forge.modules.book_design_authority.domain import (
    BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignPayload,
    BookScope,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority import scripted_qualification


def valid_design(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": BOOK_DESIGN_SCHEMA_VERSION,
        "title": "The Glass Harbor",
        "genre": "speculative mystery",
        "premise": "A harbor cartographer must prove that the city edits its own maps.",
        "theme": "Truth needs witnesses as well as evidence.",
        "core_conflict": "The cartographer races a civic archive that erases inconvenient districts.",
        "reader_promise": "Every solved map anomaly exposes a deeper institutional bargain.",
        "ending": "The hidden district is restored and the archive becomes publicly auditable.",
        "protagonist": {
            "name": "Mara",
            "external_goal": "Restore the missing district.",
            "internal_need": "Trust collaborators with incomplete evidence.",
            "flaw": "Treats uncertainty as personal failure.",
            "arc": "From solitary certainty to accountable collective truth.",
        },
        "world_rules": [
            "Maps change only after a signed archival decision.",
            "A witnessed place cannot be erased for seven days.",
        ],
        "target_chapters": 90,
        "core_characters": [
            {
                "character_id": "mara",
                "role": "protagonist",
                "long_term_goal": "Restore the missing district.",
                "causal_arc": "Isolation becomes accountable collaboration.",
                "conflict_function": "Her need for certainty delays collective action.",
            }
        ],
        "opposition_forces": [
            {
                "force_id": "civic-archive",
                "goal": "Preserve control of public memory.",
                "leverage": "It can rewrite official maps and records.",
                "escalation_pattern": "Denial becomes targeted erasure.",
                "limit": "A witnessed place cannot be erased immediately.",
            }
        ],
        "narrative_dna": {
            "core_question": "Who owns a truth that needs collective witness?",
            "recurring_choice": "Private certainty or accountable disclosure.",
            "cost_logic": "Every recovered fact exposes a witness.",
            "distinctive_mechanism": "Official maps change physical access.",
            "emotional_contract": "Discovery earns hope and a sharper public cost.",
        },
        "narrative_qualification": scripted_qualification("book_design.propose"),
    }
    payload.update(overrides)
    return payload


class BookDesignAuthorityDomainTests(unittest.TestCase):
    def test_typed_payload_has_stable_schema_and_content_hash(self) -> None:
        first = BookDesignPayload.from_mapping(valid_design())
        reordered = BookDesignPayload.from_mapping(
            dict(reversed(list(valid_design().items())))
        )

        self.assertEqual(first.schema_version, BOOK_DESIGN_SCHEMA_VERSION)
        self.assertEqual(first.content_hash, reordered.content_hash)
        self.assertTrue(first.content_hash.startswith("sha256:"))
        self.assertEqual(first.to_dict()["world_rules"], list(first.world_rules))

    def test_payload_rejects_unversioned_arbitrary_or_weak_json(self) -> None:
        cases = (
            valid_design(schema_version=""),
            valid_design(marketing_magic=True),
            valid_design(world_rules=[]),
            valid_design(target_chapters="90"),
            valid_design(protagonist={"name": "decorative"}),
        )
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(KernelError):
                BookDesignPayload.from_mapping(payload)

    def test_progressive_payload_requires_story_intent_and_foundation_evaluation(
        self,
    ) -> None:
        payload = valid_design()
        payload.pop("narrative_qualification")

        with self.assertRaises(KernelError) as raised:
            BookDesignPayload.from_mapping(payload)

        self.assertEqual(
            raised.exception.code,
            "NARRATIVE_SEMANTIC_EVALUATION_REQUIRED",
        )

    def test_book_scope_requires_release_and_runtime_authority(self) -> None:
        scope = BookScope.from_mapping(
            project_id="project-1",
            workspace_id="workspace-1",
            book_id="book-1",
            principal="operator-1",
            service_identity="authority-api",
            payload={
                "schema_version": "book-authority.v1",
                "title": "The Glass Harbor",
                "production_profile": {"environment": "production"},
                "runtime_policy": {"legacy_write": False, "silent_fallback": False},
                "release_identity": "build-1@" + "a" * 40,
            },
        )

        self.assertEqual(scope.book_id, "book-1")
        self.assertFalse(scope.runtime_policy["legacy_write"])
        self.assertEqual(scope.content(title="The Glass Harbor")["book_scope"]["book_id"], "book-1")

        with self.assertRaises(KernelError):
            BookScope.from_mapping(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                principal="operator-1",
                service_identity="authority-api",
                payload={"production_profile": {}, "runtime_policy": {}, "release_identity": ""},
            )

    def test_operation_definitions_are_transaction_commands_and_fail_closed(self) -> None:
        definitions = book_design_definitions(
            application_build_id="build-1", commit_sha="a" * 40
        )

        self.assertEqual({item["name"] for item in definitions}, set(BOOK_DESIGN_OPERATIONS))
        for definition in definitions:
            with self.subTest(definition=definition["name"]):
                self.assertEqual(definition["execution_mode"], "transactional")
                self.assertEqual(
                    definition["policy"]["execution_classification"],
                    "transaction_command",
                )
                self.assertEqual(definition["policy"]["legacy_writer"], "disabled")
                self.assertFalse(definition["policy"]["silent_fallback"])
                self.assertTrue(definition["completion_contract"]["required_outbox_events"])


if __name__ == "__main__":
    unittest.main()
