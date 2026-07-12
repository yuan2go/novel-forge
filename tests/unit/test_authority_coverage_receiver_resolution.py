from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_forge.tools.authority_coverage_manifest import build_manifest


class AuthorityCoverageReceiverResolutionTests(unittest.TestCase):
    def test_resolves_imports_aliases_clients_and_owner_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src/novel_forge/modules/publishing/service.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "import httpx as hx",
                        "from requests import post as request_post",
                        "",
                        "class PublishingService:",
                        "    async def submit(self):",
                        "        async with hx.AsyncClient() as client:",
                        "            send = client.post",
                        "            await send('https://example.test')",
                        "        request_post('https://example.test')",
                        "        helper = object()",
                        "        helper.post('not-an-external-client')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            manifest = build_manifest(root, generated_at="2026-07-12T00:00:00+00:00")

        effects = [item for item in manifest["findings"] if item["usage_type"] == "external_effect"]
        self.assertEqual(len(effects), 2)
        self.assertEqual(
            {item["called_symbol"] for item in effects},
            {"httpx.AsyncClient.post", "requests.post"},
        )
        for finding in effects:
            self.assertEqual(finding["class_name"], "PublishingService")
            self.assertEqual(finding["function_name"], "submit")
            self.assertEqual(
                finding["qualified_symbol"],
                "novel_forge.modules.publishing.service.PublishingService.submit",
            )


if __name__ == "__main__":
    unittest.main()
