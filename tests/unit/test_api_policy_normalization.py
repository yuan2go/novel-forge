from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.models import EditorPatchApplyRequest
from novel_forge.api.routers.runtime_request import normalize_product_api_runtime_request


class ApiPolicyNormalizationTests(unittest.TestCase):
    def test_runtime_helper_reads_environment_from_os_envelope(self):
        request = EditorPatchApplyRequest(
            patch_path="data/drafts/patch.json",
            os_envelope={
                "project_id": "api-policy-p",
                "task_type": "revision",
                "asset_type": "draft_chapter",
                "actor_type": "unit_test",
                "source": "unit",
                "trace_id": "trace-api-policy",
                "source_policy": {"raw_source_text_allowed": False},
                "environment": "operating_system",
            },
        )

        policy = normalize_product_api_runtime_request(request, operation="editor.apply_patch")

        self.assertTrue(policy["production"])
        self.assertEqual(policy["environment"], "production")
        self.assertEqual(policy["source_policy"]["empty_pack_policy"], "block")
        self.assertFalse(policy["source_policy"]["compat_warning_allowed"])

    def test_product_api_middleware_normalizes_every_product_route(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(IndustrialSettings(root=Path(tmp).resolve()))
            client = TestClient(app)

            response = client.get("/product/system/health")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["x-novel-forge-runtime-policy"], "normalized")
            self.assertEqual(response.headers["x-novel-forge-runtime-production"], "false")

    def test_product_api_middleware_blocks_production_mutation_without_envelope(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(IndustrialSettings(root=Path(tmp).resolve()))
            client = TestClient(app)

            response = client.post("/product/settings/profile", json={"environment": "production"})

            self.assertEqual(response.status_code, 400)
            self.assertIn("OS envelope required", response.json()["detail"])
            self.assertEqual(response.headers["x-novel-forge-runtime-environment"], "production")


if __name__ == "__main__":
    unittest.main()
