from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.genre_os import build_genre_strategy_pack
from novel_forge.modules.model_router import create_model_route
from novel_forge.modules.style_os import build_style_profile, extract_style_fingerprint, ingest_style_sample
from novel_forge.modules.v7_provider_proof import run_v7_provider_proof
from novel_forge.storage.local import LocalStorage


class ExternalV7ProviderAdapter:
    external_provider_evidence = {
        "external_call": True,
        "fixture": False,
        "provider_response_id": "resp-v7-proof",
        "endpoint_host": "api.provider.example",
        "credential_ref": "env:V7_PROVIDER_API_KEY",
        "rate_limit_policy": {"requests_per_minute": 30, "burst": 2},
    }

    def generate(self, payload: str, context: dict):
        return {
            "text": ("外部 provider 原创单章证明：案件目标清晰，证据链推进，人物必须选择，结尾真相钩子逼近下一章。 " * 30),
            "usage": {"input_tokens": 900, "output_tokens": 360, "total_tokens": 1260, "usage_source": "external_provider"},
            "cost": {"amount": 0.006, "currency": "USD", "source": "external_provider"},
            "external_provider_evidence": {**self.external_provider_evidence, "provider_response_id": f"resp-v7-generate-{context.get('chapter_no', 'single')}"},
        }

    def review(self, payload: str, context: dict):
        return {
            "text": '{"recommendation":"ready","scores":{"genre_promise":91,"platform_rhythm":88,"style_adherence":86,"hook_strength":90,"conflict_density":87,"character_motivation":88,"canon_consistency":92,"ai_flavor_risk":85},"rationale":"external provider v7 proof judgment"}',
            "usage": {"input_tokens": 1200, "output_tokens": 240, "total_tokens": 1440, "usage_source": "external_provider"},
            "cost": {"amount": 0.012, "currency": "USD", "source": "external_provider"},
            "external_provider_evidence": {**self.external_provider_evidence, "provider_response_id": "resp-v7-review"},
        }


class V7ProviderProofTests(unittest.TestCase):
    def test_v7_provider_proof_runs_opening_single_chapter_and_50_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _routes(storage)
            genre = build_genre_strategy_pack(storage, genre="mystery", subgenre="police_procedural", project_id="p1")
            style = _style_profile(storage)

            result = run_v7_provider_proof(
                storage,
                provider_adapter=ExternalV7ProviderAdapter(),
                project_id="p1",
                genre_strategy_pack_path=genre["genre_strategy_pack_path"],
                style_profile_path=style,
                provider_runtime_guard={"max_total_tokens": 3000},
                require_external_provider_proof=True,
                environment="production",
                envelope=_envelope("trace-v7-provider-proof"),
                target_chapter_count=50,
            )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["asset"]["type"], "project_metric_snapshot")
            content = result["asset"]["content"]
            self.assertEqual(content["snapshot_kind"], "v7_provider_proof")
            self.assertTrue(all(check["passed"] for check in content["checks"]))
            self.assertTrue(content["opening_3"]["external_provider_proof"]["path"])
            self.assertEqual(content["long_chain_50"]["status"], "ready")


def _routes(storage: LocalStorage) -> None:
    for task_type in ["chapter_draft", "quality_judge"]:
        create_model_route(
            storage,
            task_type=task_type,
            provider="external-provider",
            model_name="premium-provider-v1",
            project_id="p1",
            environment="production",
            approval_status="approved",
            approval_id=f"approval-v7-{task_type}",
            approved_by="runtime-owner",
            production_provider_allowlist=["external-provider"],
            max_cost_per_run=2.0,
        )


def _style_profile(storage: LocalStorage) -> str:
    sample = ingest_style_sample(
        storage,
        project_id="p1",
        sample_text=("异常现场、证据、嫌疑关系和真相钩子持续推进。 " * 20),
        rights={"license": "project-owned", "allowed_usage": "style_parameter_extraction"},
    )
    fingerprint = extract_style_fingerprint(storage, sample_path=sample["path"])
    profile = build_style_profile(storage, fingerprint_path=fingerprint["path"])
    return profile["style_profile_path"]


def _envelope(trace_id: str) -> dict:
    return {
        "project_id": "p1",
        "task_type": "v7_provider_proof",
        "asset_type": "project_metric_snapshot",
        "actor_type": "service",
        "source": "test",
        "trace_id": trace_id,
        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
        "environment": "production",
    }


if __name__ == "__main__":
    unittest.main()
