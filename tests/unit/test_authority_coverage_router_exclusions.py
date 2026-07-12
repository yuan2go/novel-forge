from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_forge.tools.authority_coverage_manifest import build_manifest


class AuthorityCoverageRouterExclusionTests(unittest.TestCase):
    def test_fastapi_route_registration_is_not_an_external_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src/novel_forge/api/routers/projects.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "import httpx",
                        "from fastapi import APIRouter, FastAPI",
                        "router = APIRouter()",
                        "app = FastAPI()",
                        "",
                        "@router.post('/projects')",
                        "async def create_project():",
                        "    async with httpx.AsyncClient() as client:",
                        "        return await client.post('https://example.test')",
                        "",
                        "app.post('/health')",
                        "FastAPI.post(app, '/other')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            manifest = build_manifest(root, generated_at="2026-07-12T00:00:00+00:00")

        effects = [item for item in manifest["findings"] if item["usage_type"] == "external_effect"]
        self.assertEqual([item["called_symbol"] for item in effects], ["httpx.AsyncClient.post"])


if __name__ == "__main__":
    unittest.main()
