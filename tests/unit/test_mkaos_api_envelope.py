from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from novel_forge.api.app import create_app
from novel_forge.infrastructure.settings import IndustrialSettings


class MkaosApiEnvelopeTests(unittest.TestCase):
    def test_standard_query_response_and_invalid_flow_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(IndustrialSettings(root=Path(tmp).resolve())))
            response = client.post("/product/mkaos/query/knowledge", json={"project_id": "api"})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["success"])
            self.assertIn("request_id", body)
            self.assertIn("envelope_id", body)
            invalid = client.post("/product/mkaos/packs/build", json={"flow": "invalid"})
            self.assertEqual(invalid.status_code, 400)

    def test_mutation_response_is_standard_envelope_with_legacy_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(IndustrialSettings(root=Path(tmp).resolve())))
            response = client.post(
                "/api/mkaos/knowledge",
                json={
                    "project_id": "api",
                    "concept_name": "制度冲突",
                    "core_explanation": "制度知识必须转成行动、冲突和选择代价。",
                    "discipline": "历史制度",
                },
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["success"])
            self.assertIn("data", body)
            self.assertIn("asset", body)
            self.assertEqual(body["data"]["asset"]["type"], "knowledge_card")
            self.assertIsNone(body["error"])

    def test_production_mutation_missing_envelope_is_blocked_by_product_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(IndustrialSettings(root=Path(tmp).resolve())))
            response = client.post("/product/mkaos/knowledge", json={"environment": "production", "concept_name": "X", "core_explanation": "Y"})
            self.assertEqual(response.status_code, 400)
