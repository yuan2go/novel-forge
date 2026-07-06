from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.long_chain_proof import run_long_chain_proof
from novel_forge.modules.model_router import create_model_route
from novel_forge.storage.local import LocalStorage


class ChapterProviderAdapter:
    def generate(self, payload: str, context: dict):
        return {
            "text": "原创章节候选：目标推进，冲突升级，钩子保留。",
            "usage": {"input_tokens": 900, "output_tokens": 320, "total_tokens": 1220, "usage_source": "provider_fixture"},
            "cost": {"amount": 0.006, "currency": "USD", "source": "provider_fixture"},
        }


class ExternalChapterProviderAdapter:
    external_provider_evidence = {
        "external_call": True,
        "fixture": False,
        "provider_response_id": "resp-long-chain",
        "endpoint_host": "api.provider.example",
        "credential_ref": "env:LONG_CHAIN_PROVIDER_API_KEY",
        "rate_limit_policy": {"requests_per_minute": 30, "burst": 2},
    }

    def generate(self, payload: str, context: dict):
        chapter = context.get("chapter_no", 0)
        return {
            "text": f"外部 provider 原创章节候选 {chapter}：目标推进，冲突升级，钩子保留。",
            "usage": {"input_tokens": 900, "output_tokens": 320, "total_tokens": 1220, "usage_source": "external_provider"},
            "cost": {"amount": 0.006, "currency": "USD", "source": "external_provider"},
            "external_provider_evidence": {**self.external_provider_evidence, "provider_response_id": f"resp-long-chain-{chapter}"},
        }


class LongChainProofTests(unittest.TestCase):
    def test_deterministic_50_chapter_run_writes_acceptance_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)

            result = run_long_chain_proof(storage, project_id="p1", mode="deterministic_50")
            acceptance = result["asset"]

            self.assertEqual(acceptance["type"], "long_chain_acceptance_report")
            self.assertEqual(acceptance["content"]["chapter_count"], 50)
            self.assertEqual(acceptance["content"]["status"], "ready")
            self.assertEqual(acceptance["content"]["recommendation"], "pass")
            self.assertEqual(len(result["checkpoint_paths"]), 5)
            run = storage.read_json(result["run_path"])
            self.assertEqual(run["content"]["recap_chapters"], [10, 20, 30, 40, 50])
            self.assertEqual(run["content"]["volume_review_chapters"], [30])
            self.assertEqual(run["content"]["coverage"]["context_bundle"], 1.0)

    def test_provider_30_slow_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            with self.assertRaises(ValueError):
                run_long_chain_proof(storage, project_id="p1", mode="provider_30_slow")

    def test_provider_50_proof_records_chapter_generation_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            create_model_route(
                storage,
                task_type="chapter_draft",
                provider="unit-provider",
                model_name="chapter-provider-v1",
                project_id="p1",
                environment="production",
                approval_status="approved",
                approval_id="approval-long-chain-1",
                approved_by="runtime-owner",
                production_provider_allowlist=["unit-provider"],
                max_cost_per_run=2.0,
            )

            result = run_long_chain_proof(
                storage,
                project_id="p1",
                mode="provider_50_proof",
                target_chapter_count=50,
                opt_in_slow_provider=True,
                provider_adapter=ChapterProviderAdapter(),
                provider_runtime_guard={"max_total_tokens": 2000},
                environment="production",
                envelope={
                    "project_id": "p1",
                    "task_type": "long_chain_proof",
                    "asset_type": "long_chain_run",
                    "actor_type": "service",
                    "source": "test",
                    "trace_id": "trace-long-chain-provider",
                    "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                    "environment": "production",
                },
            )

            acceptance = result["asset"]
            provider_evidence = acceptance["content"]["provider_generation_evidence"]
            self.assertEqual(acceptance["content"]["status"], "ready")
            self.assertEqual(provider_evidence["mode"], "provider_backed_chapter_generation")
            self.assertEqual(provider_evidence["generated_chapter_count"], 50)
            self.assertEqual(len(provider_evidence["model_call_log_paths"]), 50)
            self.assertEqual(len(provider_evidence["cost_ledger_paths"]), 50)
            self.assertTrue(any(check["check"] == "provider_generation_coverage" and check["passed"] for check in acceptance["content"]["checks"]))

    def test_provider_50_external_proof_blocks_fixture_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            _external_route(storage, provider="unit-provider", approval_id="approval-long-chain-block")

            with self.assertRaisesRegex(ValueError, "external provider proof"):
                run_long_chain_proof(
                    storage,
                    project_id="p1",
                    mode="provider_50_proof",
                    target_chapter_count=50,
                    opt_in_slow_provider=True,
                    provider_adapter=ChapterProviderAdapter(),
                    provider_runtime_guard={"max_total_tokens": 2000},
                    environment="production",
                    envelope=_envelope("trace-long-chain-external-block"),
                    require_external_provider_proof=True,
                )

    def test_provider_50_external_proof_records_per_chapter_proofs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            _external_route(storage, provider="external-provider", approval_id="approval-long-chain-external-pass")

            result = run_long_chain_proof(
                storage,
                project_id="p1",
                mode="provider_50_proof",
                target_chapter_count=50,
                opt_in_slow_provider=True,
                provider_adapter=ExternalChapterProviderAdapter(),
                provider_runtime_guard={"max_total_tokens": 2000},
                environment="production",
                envelope=_envelope("trace-long-chain-external-pass"),
                require_external_provider_proof=True,
            )

            provider_evidence = result["asset"]["content"]["provider_generation_evidence"]
            self.assertEqual(len(provider_evidence["external_provider_proof_paths"]), 50)
            self.assertTrue(any(check["check"] == "external_provider_proof_coverage" and check["passed"] for check in result["asset"]["content"]["checks"]))
            proof = storage.read_json(storage.root / provider_evidence["external_provider_proof_paths"][0])
            self.assertEqual(proof["type"], "external_provider_proof_report")
            self.assertEqual(proof["content"]["status"], "passed")


def _external_route(storage: LocalStorage, *, provider: str, approval_id: str) -> None:
    create_model_route(
        storage,
        task_type="chapter_draft",
        provider=provider,
        model_name="chapter-provider-v1",
        project_id="p1",
        environment="production",
        approval_status="approved",
        approval_id=approval_id,
        approved_by="runtime-owner",
        production_provider_allowlist=[provider],
        max_cost_per_run=2.0,
    )


def _envelope(trace_id: str) -> dict:
    return {
        "project_id": "p1",
        "task_type": "long_chain_proof",
        "asset_type": "long_chain_run",
        "actor_type": "service",
        "source": "test",
        "trace_id": trace_id,
        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
        "environment": "production",
    }


if __name__ == "__main__":
    unittest.main()
