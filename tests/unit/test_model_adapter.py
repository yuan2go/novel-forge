from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters import (
    PROVIDER_ADAPTERS,
    AdapterNotConfiguredError,
    ChatGPTAdapter,
    ClaudeCodeAdapter,
    CodexAdapter,
    DeepSeekAdapter,
    GuardedModelAdapter,
    HashEmbeddingAdapter,
    ModelOutputValidationError,
    MockModelAdapter,
    OpenAICompatibleEmbeddingAdapter,
    ProviderRuntimeGuardError,
    cosine_similarity,
    embedding_adapter_from_env,
    model_from_env,
    parse_json_object,
    validate_model_output,
)
from novel_forge.modules.agent_runs import list_agent_runs, start_agent_run
from novel_forge.storage.local import LocalStorage


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
            with patch.dict(
                "os.environ",
                {
                    "OPENAI_API_KEY": "",
                    "DEEPSEEK_API_KEY": "",
                    "NOVEL_FORGE_LOCAL_CODEX_CLI_ENABLED": "",
                    "NOVEL_FORGE_CODEX_CLI_ENABLED": "",
                    "NOVEL_FORGE_CLAUDE_CODE_CLI_ENABLED": "0",
                },
                clear=False,
            ):
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

    def test_openai_compatible_adapter_can_use_sdk_streaming_guard(self):
        fake_openai = _fake_openai_sdk_module(
            [
                {"choices": [{"delta": {"content": "{\"text\":\"sdk "}, "finish_reason": None}]},
                {
                    "choices": [{"delta": {"content": "stream result\"}"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 9, "completion_tokens": 7, "total_tokens": 16},
                },
            ]
        )
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "unit-key",
                "NOVEL_FORGE_PROVIDER_SDK_STREAMING": "1",
            },
            clear=False,
        ), patch.dict("sys.modules", {"openai": fake_openai}):
            result = ChatGPTAdapter().generate(
                "write json",
                {
                    "stream": True,
                    "provider_runtime_guard": {
                        "max_total_tokens": 200,
                        "cost_profile": {"input_per_1k": 0.01, "output_per_1k": 0.02},
                    },
                },
            )

        self.assertEqual(result["text"], "sdk stream result")
        self.assertEqual(result["usage"]["usage_source"], "provider_sdk_stream")
        self.assertEqual(result["usage"]["total_tokens"], 16)
        self.assertEqual(result["cost"]["source"], "provider_usage")
        self.assertIn("provider_call_finished", {event["event_type"] for event in result["runtime_events"]})

    def test_model_selection_defaults_to_claude_code_and_can_select_provider(self):
        self.assertIsInstance(model_from_env("draft", {}), ClaudeCodeAdapter)
        self.assertIsInstance(model_from_env("draft", {"NOVEL_FORGE_MODEL_PROVIDER": "mock"}), MockModelAdapter)
        self.assertIsInstance(model_from_env("review", {"NOVEL_FORGE_REVIEW_PROVIDER": "chatgpt"}), ChatGPTAdapter)

    def test_codex_cli_worker_runs_when_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = _write_fake_codex_script(Path(tmp), include_codex_home=False)
            with patch.dict(
                "os.environ",
                {
                    "NOVEL_FORGE_CODEX_CLI_ENABLED": "1",
                    "NOVEL_FORGE_CODEX_COMMAND": f"{sys.executable} {script}",
                    "NOVEL_FORGE_CODEX_WORKDIR": tmp,
                    "NOVEL_FORGE_CODEX_TIMEOUT_SECONDS": "5",
                },
                clear=False,
            ):
                adapter = CodexAdapter()
                health = adapter.health_check()
                result = adapter.generate("write a bounded test response")

            self.assertEqual(health["implemented"], "local_cli_worker")
            self.assertTrue(health["configured"])
            self.assertEqual(result["provider"], "codex")
            self.assertEqual(result["text"], "usable generated prose from local codex")
            self.assertEqual(result["usage"]["total_tokens"], 11)

    def test_claude_code_cli_worker_uses_codex_home_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = _write_fake_codex_script(Path(tmp), include_codex_home=True)
            with patch.dict(
                "os.environ",
                {
                    "NOVEL_FORGE_LOCAL_CODEX_CLI_ENABLED": "",
                    "NOVEL_FORGE_CLAUDE_CODE_CLI_ENABLED": "",
                    "NOVEL_FORGE_CLAUDE_CODE_COMMAND": f"{sys.executable} {script}",
                    "NOVEL_FORGE_CLAUDE_CODE_WORKDIR": tmp,
                    "NOVEL_FORGE_CLAUDE_CODE_TIMEOUT_SECONDS": "5",
                },
                clear=False,
            ):
                adapter = ClaudeCodeAdapter()
                health = adapter.health_check()
                result = adapter.generate("write a bounded test response")

            self.assertEqual(health["implemented"], "local_cli_worker")
            self.assertEqual(health["codex_home"], "~/.codex-claude")
            self.assertTrue(health["automation_isolation"]["ignore_user_config"])
            self.assertTrue(health["automation_isolation"]["ignore_rules"])
            self.assertEqual(result["provider"], "claude-code")
            self.assertTrue(result["codex_home"].endswith(".codex-claude"))

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

    def test_guarded_adapter_enforces_provider_runtime_guard(self):
        class UsageModel(MockModelAdapter):
            def generate(self, prompt: str, context: dict | None = None) -> dict:
                return {"model": self.name, "text": "usable generated prose", "usage": {"total_tokens": 120}}

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run = start_agent_run(storage, agent_key="draft", operation="draft", status="running")
            guarded = GuardedModelAdapter(UsageModel(), storage, run["path"])

            with self.assertRaises(ProviderRuntimeGuardError):
                guarded.generate("draft", {"provider_runtime_guard": {"max_tokens": 50}})

            self.assertEqual(list_agent_runs(storage)[0]["status"], "failed")
            run_types = {storage.read_json(path).get("type") for path in storage.list_json("runs")}
            self.assertIn("agent_gate", run_types)
            self.assertIn("agent_failure_report", run_types)

    def test_guarded_adapter_records_model_call_log_on_success(self):
        class UsageModel(MockModelAdapter):
            def generate(self, prompt: str, context: dict | None = None) -> dict:
                return {
                    "provider": "mock",
                    "model": self.name,
                    "text": "usable generated prose",
                    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                    "cost": {"amount": 0.05, "currency": "USD", "source": "unit_test"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run = start_agent_run(
                storage,
                agent_key="draft",
                operation="draft",
                status="running",
                evidence={"trace_id": "guarded-trace"},
            )
            result = GuardedModelAdapter(UsageModel(), storage, run["path"]).generate("draft", {})

            self.assertTrue(result["model_call_log_path"])
            self.assertTrue(result["cost_ledger_path"])
            run_types = {storage.read_json(path).get("type") for path in storage.list_json("runs")}
            self.assertIn("model_call_log", run_types)
            self.assertIn("cost_ledger", run_types)

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

def _write_fake_codex_script(folder: Path, *, include_codex_home: bool) -> Path:
    script = folder / "fake_codex.py"
    codex_home_fragment = '"codex_home": os.environ.get("CODEX_HOME", ""),' if include_codex_home else ""
    script.write_text(
        f"""
import json
import os
import sys

output_path = ""
for index, value in enumerate(sys.argv):
    if value == "--output-last-message" and index + 1 < len(sys.argv):
        output_path = sys.argv[index + 1]
payload = {{
    "text": "usable generated prose from local codex",
    {codex_home_fragment}
    "usage": {{"total_tokens": 11}}
}}
if not output_path:
    raise SystemExit(2)
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False))
print(json.dumps({{"usage": {{"total_tokens": 11}}}}))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return script


def _fake_openai_sdk_module(chunks):
    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["stream"] is True
            return iter(chunks)

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat = FakeChat()

    return types.SimpleNamespace(OpenAI=FakeOpenAI)


if __name__ == "__main__":
    unittest.main()
