from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters import (
    PROVIDER_ADAPTERS,
    AdapterNotConfiguredError,
    ChatGPTAdapter,
    DeepSeekAdapter,
    HashEmbeddingAdapter,
    MockModelAdapter,
    cosine_similarity,
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
            adapter = adapter_cls()
            health = adapter.health_check()
            self.assertIn("provider", health)
            self.assertFalse(health["implemented"])
            self.assertIn("external_api", health)
            with self.assertRaises(AdapterNotConfiguredError):
                adapter.generate("test prompt")

    def test_external_provider_health_reports_missing_secrets_without_network(self):
        chatgpt_health = ChatGPTAdapter().health_check()
        deepseek_health = DeepSeekAdapter().health_check()
        self.assertEqual(chatgpt_health["provider"], "chatgpt")
        self.assertIn("OPENAI_API_KEY", chatgpt_health["required_env_vars"])
        self.assertEqual(deepseek_health["provider"], "deepseek")
        self.assertIn("DEEPSEEK_API_KEY", deepseek_health["required_env_vars"])

    def test_hash_embedding_adapter_is_deterministic_and_local(self):
        adapter = HashEmbeddingAdapter(dimensions=16)
        left = adapter.embed_text("hidden bell clue")
        right = adapter.embed_text("hidden bell clue")
        other = adapter.embed_text("romance relationship")

        self.assertEqual(left, right)
        self.assertEqual(len(left), 16)
        self.assertGreater(cosine_similarity(left, right), cosine_similarity(left, other))
        self.assertFalse(adapter.health_check()["external_api"])


if __name__ == "__main__":
    unittest.main()
