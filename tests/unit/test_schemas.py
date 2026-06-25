from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import (
    ClaudeCodeHandoff,
    ProjectWorkspaceState,
    ReviewReport,
    SCHEMA_CLASSES,
    SourceDocument,
    validate_common_fields,
)


class SchemaTests(unittest.TestCase):
    def test_required_schema_count(self):
        self.assertEqual(len(SCHEMA_CLASSES), 30)
        self.assertIn("source_document", SCHEMA_CLASSES)
        self.assertIn("asset_collection", SCHEMA_CLASSES)
        self.assertIn("review_report", SCHEMA_CLASSES)
        self.assertIn("project_workspace_state", SCHEMA_CLASSES)
        self.assertIn("task_dead_letter", SCHEMA_CLASSES)
        self.assertIn("batch_task_item", SCHEMA_CLASSES)
        self.assertIn("claude_code_handoff", SCHEMA_CLASSES)

    def test_common_fields_validate(self):
        asset = SourceDocument(
            title="Sample",
            source="input.txt",
            content={"text": "hello"},
            metadata={
                "rights": {
                    "authorization": "test_fixture",
                    "copyright_boundary": "schema test fixture",
                    "allow_downstream_generation": True,
                }
            },
        )
        data = asset.to_dict()
        self.assertEqual(validate_common_fields(data), [])
        self.assertEqual(data["type"], "source_document")
        self.assertTrue(data["id"])

    def test_type_level_content_validation(self):
        asset = SourceDocument(title="Sample", source="input.txt", content={})
        errors = validate_common_fields(asset.to_dict())
        self.assertIn("source_document content missing required field: text", errors)

    def test_type_validation_checks_collection_types(self):
        data = SourceDocument(title="Sample", source="input.txt", content={"text": "hello"}).to_dict()
        data["tags"] = "raw"
        data["references"] = "source"
        errors = validate_common_fields(data)
        self.assertIn("tags must be a list", errors)
        self.assertIn("references must be a list", errors)

    def test_review_report_shape(self):
        report = ReviewReport(title="review", score=75, strengths=["hook"], weaknesses=["motive"])
        data = report.to_dict()
        self.assertEqual(data["score"], 75)
        self.assertIn("revision_suggestions", data)

    def test_project_workspace_state_required_content(self):
        workspace = ProjectWorkspaceState(title="workspace", content={})
        errors = validate_common_fields(workspace.to_dict())
        self.assertIn("project_workspace_state content missing required field: project_id", errors)

    def test_claude_code_handoff_required_content(self):
        handoff = ClaudeCodeHandoff(title="handoff", content={})
        errors = validate_common_fields(handoff.to_dict())
        self.assertIn("claude_code_handoff content missing required field: operation", errors)
        self.assertIn("claude_code_handoff content missing required field: input_files", errors)

    def test_project_workspace_state_semantic_validation(self):
        workspace = ProjectWorkspaceState(
            title="workspace",
            content={
                "project_id": "p1",
                "memory": {},
                "chapter_states": [{"chapter": "1", "status": "", "asset_id": ""}],
                "continuity_threads": {},
                "open_issues": [],
            },
        )
        errors = validate_common_fields(workspace.to_dict())
        self.assertIn("project_workspace_state chapter_states[0].chapter must be an integer", errors)
        self.assertIn("project_workspace_state chapter_states[0].status must not be empty", errors)
        self.assertIn("project_workspace_state chapter_states[0].asset_id must not be empty", errors)

    def test_feedback_insight_semantic_validation(self):
        data = {
            "id": "feedback_insight_bad",
            "type": "feedback_insight",
            "title": "bad insight",
            "name": "bad insight",
            "source": "feedback",
            "tags": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "version": "0.1.0",
            "content": {
                "signals": ["x"],
                "average_rating": 3,
                "next_generation_constraints": ["x"],
                "chapter_trends": [{"chapter": "1", "average_rating": "bad"}],
                "retention_risk": {"level": "urgent"},
                "trend_metrics": {"rating_slope": "down", "confidence": "certain"},
            },
            "metadata": {},
            "references": [],
        }
        errors = validate_common_fields(data)
        self.assertIn("feedback_insight chapter_trends[0].chapter must be an integer", errors)
        self.assertIn("feedback_insight chapter_trends[0].average_rating must be numeric", errors)
        self.assertIn("feedback_insight retention_risk.level must be low, medium, high, or unknown", errors)
        self.assertIn("feedback_insight trend_metrics.rating_slope must be numeric", errors)
        self.assertIn("feedback_insight trend_metrics.confidence must be none, low, medium, or high", errors)

    def test_source_document_requires_rights_metadata(self):
        data = {
            "id": "source_document_bad",
            "type": "source_document",
            "title": "bad source",
            "name": "bad source",
            "source": "source.txt",
            "tags": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "version": "0.1.0",
            "content": {"text": "x"},
            "metadata": {},
            "references": [],
        }

        errors = validate_common_fields(data)

        self.assertIn("source_document metadata.rights must be recorded", errors)


if __name__ == "__main__":
    unittest.main()
