from __future__ import annotations

import unittest

from novel_forge.modules.legacy_migration.references import (
    MigrationRelationType,
    parse_migration_reference,
    topological_activation_order,
)


class LegacyMigrationReferenceTests(unittest.TestCase):
    def test_legacy_string_is_normalized_with_compatibility_evidence(self) -> None:
        reference = parse_migration_reference("plan-volume-1", ordinal=3)

        self.assertEqual(reference.business_key, "plan-volume-1")
        self.assertEqual(reference.relation_type, MigrationRelationType.RELATED_ASSET)
        self.assertFalse(reference.optional)
        self.assertEqual(reference.ordinal, 3)
        self.assertEqual(reference.compatibility_mode, "LEGACY_STRING_V1")

    def test_structured_reference_freezes_type_hash_optional_and_cardinality(self) -> None:
        reference = parse_migration_reference(
            {
                "business_key": "plan-volume-1",
                "relation_type": "PARENT_PLAN",
                "optional": False,
                "expected_source_type": "volume_plan",
                "expected_target_asset_type": "volume_plan",
                "expected_content_hash": "sha256:" + "a" * 64,
                "cardinality": "ONE",
                "ordinal": 7,
            },
            ordinal=1,
        )

        self.assertEqual(reference.relation_type, MigrationRelationType.PARENT_PLAN)
        self.assertEqual(reference.expected_source_type, "volume_plan")
        self.assertEqual(reference.expected_target_asset_type, "volume_plan")
        self.assertEqual(reference.cardinality, "ONE")
        self.assertEqual(reference.ordinal, 7)
        self.assertEqual(reference.compatibility_mode, "STRUCTURED_V1")

    def test_invalid_expected_hash_and_relation_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected_content_hash"):
            parse_migration_reference(
                {
                    "business_key": "target",
                    "relation_type": "PARENT_PLAN",
                    "expected_content_hash": "not-a-hash",
                },
                ordinal=0,
            )
        with self.assertRaisesRegex(ValueError, "relation_type"):
            parse_migration_reference(
                {"business_key": "target", "relation_type": "INVENTED"},
                ordinal=0,
            )

    def test_topological_order_places_dependencies_first_and_rejects_cycles(self) -> None:
        order = topological_activation_order(
            nodes=("book", "volume", "group", "chapter"),
            dependencies={
                "volume": ("book",),
                "group": ("volume",),
                "chapter": ("group",),
            },
        )
        self.assertLess(order.index("book"), order.index("volume"))
        self.assertLess(order.index("volume"), order.index("group"))
        self.assertLess(order.index("group"), order.index("chapter"))

        with self.assertRaisesRegex(ValueError, "cycle"):
            topological_activation_order(
                nodes=("a", "b"), dependencies={"a": ("b",), "b": ("a",)}
            )


if __name__ == "__main__":
    unittest.main()
