from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters import (
    PROVIDER_ADAPTERS,
    AdapterNotConfiguredError,
    ChatGPTAdapter,
    ClaudeCodeAdapter,
    DeepSeekAdapter,
    HashEmbeddingAdapter,
    ModelOutputValidationError,
    MockModelAdapter,
    OpenAICompatibleEmbeddingAdapter,
    cosine_similarity,
    embedding_adapter_from_env,
    model_from_env,
    parse_json_object,
    validate_model_output,
)


class MockModelTests(unittest.TestCase):
    def test_methods(self):
        model = MockModelAdapter()
        self.assertTrue(model.health_check()["ok"])
        self.assertIn("text", model.generate("hello"))
        self.assertIn("word_count", model.analyze("one two"))
        self.assertIn("score", model.review("long enough content for review"))
        self.assertEqual(len(model.batch(["a", "b"])), 2)

    def test_provider_contract_skeletons_fail_closed(self):
        self.assertEqual(sorted(PROVIDER_ADAPTERS), ["chatgpt", "claude-code", "codex", "deepseek"])
        for adapter_cls in PROVIDER_ADAPTERS.values():
            with patch.dict("os.environ", {"OPENAI_API_KEY": "", "DEEPSEEK_API_KEY": ""}, clear=False):
                adapter = adapter_cls()
                health = adapter.health_check()
                self.assertIn("provider", health)
                if health["provider"] == "claude-code":
                    self.assertEqual(health["implemented"], "manual_handoff_only")
                    with self.assertRaises(AdapterNotConfiguredError):
                        adapter.generate("test prompt")
                elif health["provider"] == "codex":
                    self.assertFalse(health["implemented"])
                    with self.assertRaises(AdapterNotConfiguredError):
                        adapter.generate("test prompt")
                else:
                    self.assertTrue(health["implemented"])
                    self.assertFalse(health["configured"])
                    with self.assertRaises(AdapterNotConfiguredError):
                        adapter.generate("test prompt")
                self.assertIn("external_api", health)

    def test_external_provider_health_reports_missing_secrets_without_network(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "", "DEEPSEEK_API_KEY": ""}, clear=False):
            chatgpt_health = ChatGPTAdapter().health_check()
            deepseek_health = DeepSeekAdapter().health_check()
        self.assertEqual(chatgpt_health["provider"], "chatgpt")
        self.assertIn("OPENAI_API_KEY", chatgpt_health["required_env_vars"])
        self.assertTrue(chatgpt_health["implemented"])
        self.assertEqual(deepseek_health["provider"], "deepseek")
        self.assertIn("DEEPSEEK_API_KEY", deepseek_health["required_env_vars"])
        self.assertTrue(deepseek_health["implemented"])

    def test_model_selection_defaults_to_mock_and_can_select_provider(self):
        self.assertIsInstance(model_from_env("draft", {}), MockModelAdapter)
        self.assertIsInstance(model_from_env("review", {"NOVEL_FORGE_REVIEW_PROVIDER": "chatgpt"}), ChatGPTAdapter)

    def test_model_output_contract_validation(self):
        parsed = parse_json_object('```json\n{"text":"usable generated prose"}\n```')
        self.assertEqual(validate_model_output("generate", parsed)["text"], "usable generated prose")
        review = validate_model_output(
            "review",
            {
                "score": 82,
                "strengths": ["hook"],
                "weaknesses": ["thin sensory detail"],
                "issues": [{"dimension": "detail", "severity": "medium", "message": "add concrete image"}],
                "risk_level": "medium",
                "revision_suggestions": ["add one sensory beat"],
                "next_action": "revise",
            },
        )
        self.assertEqual(review["score"], 82.0)
        with self.assertRaises(ModelOutputValidationError):
            validate_model_output("review", {"score": 200})

    def test_claude_code_adapter_creates_manual_handoff_packet(self):
        packet = ClaudeCodeAdapter().create_handoff_packet(
            "review",
            {"asset_path": "data/drafts/chapter-1.json"},
            {"skill": "quality-review"},
        )

        self.assertEqual(packet["status"], "manual_handoff_required")
        self.assertFalse(packet["automated_model_call"])
        self.assertFalse(packet["external_api"])
        self.assertEqual(packet["context"]["skill"], "quality-review")
        self.assertIn("asset_path", packet["expected_return"])

    def test_hash_embedding_adapter_is_deterministic_and_local(self):
        adapter = HashEmbeddingAdapter(dimensions=16)
        left = adapter.embed_text("hidden bell clue")
        right = adapter.embed_text("hidden bell clue")
        other = adapter.embed_text("romance relationship")

        self.assertEqual(left, right)
        self.assertEqual(len(left), 16)
        self.assertGreater(cosine_similarity(left, right), cosine_similarity(left, other))
        self.assertFalse(adapter.health_check()["external_api"])

    def test_qdrant_embedding_selection_requires_semantic_provider(self):
        with patch.dict("os.environ", {"NOVEL_FORGE_EMBEDDING_PROVIDER": "hash", "NOVEL_FORGE_ALLOW_HASH_QDRANT": ""}, clear=False):
            with self.assertRaises(AdapterNotConfiguredError):
                embedding_adapter_from_env(require_semantic=True)
        with patch.dict("os.environ", {"NOVEL_FORGE_EMBEDDING_PROVIDER": "openai", "OPENAI_API_KEY": ""}, clear=False):
            adapter = embedding_adapter_from_env(require_semantic=True)
            self.assertIsInstance(adapter, OpenAICompatibleEmbeddingAdapter)
            health = adapter.health_check()
            self.assertTrue(health["semantic_model"])
            self.assertFalse(health["ok"])


if __name__ == "__main__":
    unittest.main()
