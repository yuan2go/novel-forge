from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.operation_checkpoint import (
    CHECKPOINT_STAGES,
    assemble_raw_output_segments,
    build_checkpoint_state,
    checkpoint_idempotency_key,
    checkpoint_resume_plan,
    create_operation_checkpoint,
    latest_operation_checkpoint,
    operation_checkpoint_chain,
    operation_checkpoint_schema,
    record_raw_output_segment,
    record_operation_stage_checkpoint,
)
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class OperationCheckpointTests(unittest.TestCase):
    def test_schema_declares_stage_resume_protocol(self):
        schema = operation_checkpoint_schema("draft")

        self.assertEqual(schema["version"], "1.0")
        self.assertEqual(schema["stages"], CHECKPOINT_STAGES)
        self.assertIn("operation", schema["idempotency_key_fields"])
        self.assertIn("provider_completed", {item["stage"] for item in schema["resume_points"]})

    def test_idempotency_key_changes_when_input_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset_auto(
                DraftChapter(
                    title="Draft",
                    content={"chapter": 1, "text": "first version", "copyright_boundary": "original"},
                )
            )
            rel = str(draft_path.relative_to(storage.root))
            first = checkpoint_idempotency_key(storage, operation="review", input_assets=[rel], prompt_version="p1", model="mock")
            data = storage.read_json(draft_path)
            data["content"]["text"] = "second version"
            storage.write_json(draft_path, data)
            second = checkpoint_idempotency_key(storage, operation="review", input_assets=[rel], prompt_version="p1", model="mock")

            self.assertNotEqual(first, second)

    def test_resume_plan_reuses_committed_outputs_and_resumes_provider_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset_auto(
                DraftChapter(
                    title="Draft",
                    content={"chapter": 1, "text": "committed output", "copyright_boundary": "original"},
                )
            )
            rel = str(draft_path.relative_to(storage.root))
            committed = build_checkpoint_state(storage, operation="draft", stage="output_committed", output_assets=[rel])

            reuse = checkpoint_resume_plan(storage, committed)

            self.assertEqual(reuse["status"], "reusable")
            self.assertEqual(reuse["resume_action"], "reuse_committed_outputs")
            self.assertEqual(reuse["output_assets"], [rel])

            raw_output = storage.root / "data" / "runs" / "provider-output.json"
            raw_output.write_text('{"text":"raw"}\n', encoding="utf-8")
            provider_completed = build_checkpoint_state(
                storage,
                operation="draft",
                stage="provider_completed",
                raw_output_path=str(raw_output.relative_to(storage.root)),
            )

            resume = checkpoint_resume_plan(storage, provider_completed)

            self.assertEqual(resume["status"], "resumable")
            self.assertEqual(resume["resume_action"], "resume_output_validation")

    def test_persists_operation_checkpoint_and_reads_latest_resume_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            raw_output = storage.root / "data" / "runs" / "provider-output.json"
            raw_output.parent.mkdir(parents=True, exist_ok=True)
            raw_output.write_text('{"text":"raw provider output"}\n', encoding="utf-8")

            checkpoint = create_operation_checkpoint(
                storage,
                operation="draft",
                stage="provider_completed",
                raw_output_path=str(raw_output.relative_to(storage.root)),
                project_id="checkpoint-project",
                model="mock",
                provider_request_id="req-1",
            )
            latest = latest_operation_checkpoint(
                storage,
                operation="draft",
                idempotency_key=checkpoint["state"]["idempotency_key"],
                project_id="checkpoint-project",
            )

            self.assertEqual(checkpoint["asset"]["type"], "agent_checkpoint")
            self.assertEqual(checkpoint["asset"]["content"]["status"], "provider_completed")
            self.assertEqual(latest["status"], "found")
            self.assertEqual(latest["resume_plan"]["resume_action"], "resume_output_validation")

    def test_stage_checkpoint_chain_records_prompt_provider_validation_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            raw_output = storage.root / "data" / "runs" / "raw-stage-output.json"
            raw_output.parent.mkdir(parents=True, exist_ok=True)
            raw_output.write_text('{"text":"raw"}', encoding="utf-8")
            idempotency = "draft-stage-chain"

            for stage in ["prompt_built", "provider_completed", "output_validated", "output_committed"]:
                record_operation_stage_checkpoint(
                    storage,
                    operation="draft",
                    stage=stage,
                    idempotency_key=idempotency,
                    raw_output_path=str(raw_output.relative_to(storage.root)) if stage in {"provider_completed", "output_validated"} else "",
                    stage_payload={"stage": stage, "evidence": "unit"},
                    project_id="checkpoint-project",
                )

            chain = operation_checkpoint_chain(storage, operation="draft", idempotency_key=idempotency, project_id="checkpoint-project")

            self.assertEqual(chain["status"], "partial")
            self.assertIn("prompt_built", chain["completed_stages"])
            self.assertIn("provider_completed", chain["completed_stages"])
            self.assertEqual(chain["latest"]["stage"], "output_committed")

    def test_raw_output_segments_resume_validation_without_rerunning_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            idempotency = "draft-segment-chain"
            first = record_raw_output_segment(
                storage,
                operation="draft",
                idempotency_key=idempotency,
                segment_index=0,
                text='{"text":"part ',
                provider="claude-code",
                model="codex",
                project_id="checkpoint-project",
            )
            second = record_raw_output_segment(
                storage,
                operation="draft",
                idempotency_key=idempotency,
                segment_index=1,
                text='two"}',
                provider="claude-code",
                model="codex",
                project_id="checkpoint-project",
            )
            manifest = assemble_raw_output_segments(storage, operation="draft", idempotency_key=idempotency, project_id="checkpoint-project")
            checkpoint = create_operation_checkpoint(
                storage,
                operation="draft",
                stage="provider_completed",
                idempotency_key=idempotency,
                raw_output_segments=[first["path"], second["path"]],
                project_id="checkpoint-project",
                model="codex",
            )

            self.assertEqual(manifest["text"], '{"text":"part two"}')
            self.assertEqual(manifest["segment_count"], 2)
            self.assertEqual(checkpoint["asset"]["content"]["resume_plan"]["resume_action"], "resume_output_validation")
            self.assertEqual(checkpoint["asset"]["content"]["resume_plan"]["segment_count"], 2)
            self.assertIn(first["path"], checkpoint["asset"]["content"]["state"]["raw_output_segments"])


if __name__ == "__main__":
    unittest.main()
