from __future__ import annotations

import json
import unittest
from pathlib import Path


class TestJsonSchemas(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.schemas_dir = self.root / "schemas"
        self.required_schema_files = [
            "material.schema.json",
            "dissection.schema.json",
            "topic.schema.json",
            "chapter_plan.schema.json",
            "review.schema.json",
        ]

    def load_schema(self, filename: str) -> dict:
        with (self.schemas_dir / filename).open(encoding="utf-8") as file:
            return json.load(file)

    def test_required_schema_files_exist(self) -> None:
        for filename in self.required_schema_files:
            with self.subTest(filename=filename):
                self.assertTrue((self.schemas_dir / filename).is_file())

    def test_schema_files_are_valid_json_objects(self) -> None:
        for filename in self.required_schema_files:
            with self.subTest(filename=filename):
                schema = self.load_schema(filename)
                self.assertIsInstance(schema, dict)
                self.assertEqual(schema.get("type"), "object")
                self.assertIn("$schema", schema)
                self.assertIn("$id", schema)
                self.assertIn("title", schema)
                self.assertIsInstance(schema.get("properties"), dict)
                self.assertIsInstance(schema.get("required"), list)

    def test_required_fields_have_property_definitions(self) -> None:
        for filename in self.required_schema_files:
            with self.subTest(filename=filename):
                schema = self.load_schema(filename)
                properties = schema["properties"]
                for field in schema["required"]:
                    self.assertIn(field, properties)

    def test_schema_ids_match_file_names(self) -> None:
        for filename in self.required_schema_files:
            with self.subTest(filename=filename):
                schema = self.load_schema(filename)
                self.assertTrue(schema["$id"].endswith(filename))


if __name__ == "__main__":
    unittest.main()
