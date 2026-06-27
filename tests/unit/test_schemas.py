from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import (
    AnalysisConversionReport,
    ChapterAuditReport,
    ClaudeCodeHandoff,
    CommonNovelAnalysisReport,
    OriginalityReport,
    PublishGateReport,
    ProjectWorkspaceState,
    ReleasePackage,
    ReviewReport,
    SCHEMA_CLASSES,
    SourceDocument,
    StyleProfile,
    validate_common_fields,
)


class SchemaTests(unittest.TestCase):
    def test_required_schema_count(self):
        self.assertEqual(len(SCHEMA_CLASSES), 54)
        self.assertIn("source_document", SCHEMA_CLASSES)
        self.assertIn("asset_collection", SCHEMA_CLASSES)
        self.assertIn("review_report", SCHEMA_CLASSES)
        self.assertIn("project_workspace_state", SCHEMA_CLASSES)
        self.assertIn("task_dead_letter", SCHEMA_CLASSES)
        self.assertIn("batch_task_item", SCHEMA_CLASSES)
        self.assertIn("claude_code_handoff", SCHEMA_CLASSES)
        self.assertIn("platform_profile", SCHEMA_CLASSES)
        self.assertIn("genre_market_profile", SCHEMA_CLASSES)
        self.assertIn("style_profile", SCHEMA_CLASSES)
        self.assertIn("quality_standard_profile", SCHEMA_CLASSES)
        self.assertIn("continuity_bible", SCHEMA_CLASSES)
        self.assertIn("chapter_audit_report", SCHEMA_CLASSES)
        self.assertIn("originality_report", SCHEMA_CLASSES)
        self.assertIn("publish_gate_report", SCHEMA_CLASSES)
        self.assertIn("release_package", SCHEMA_CLASSES)
        self.assertIn("common_novel_analysis_report", SCHEMA_CLASSES)
        self.assertIn("web_fiction_business_analysis_report", SCHEMA_CLASSES)
        self.assertIn("published_fiction_analysis_report", SCHEMA_CLASSES)
        self.assertIn("classic_literary_analysis_report", SCHEMA_CLASSES)
        self.assertIn("analysis_conversion_report", SCHEMA_CLASSES)

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

    def test_release_gate_asset_validation(self):
        originality = OriginalityReport(
            title="originality",
            content={
                "target_asset_id": "draft1",
                "source_asset_ids": [],
                "similarity_checks": [],
                "forbidden_element_hits": [],
                "plot_skeleton_risk": "low",
                "character_setup_risk": "low",
                "style_expression_risk": "low",
                "risk_level": "low",
                "recommendation": "pass",
                "human_gate_required": False,
            },
        )
        self.assertEqual(validate_common_fields(originality.to_dict()), [])
        bad_gate = PublishGateReport(title="bad", content={"target_asset_id": "draft1", "gates": {}, "decision": "ship"})
        errors = validate_common_fields(bad_gate.to_dict())
        self.assertIn("publish_gate_report content missing required field: blocking_issues", errors)
        self.assertIn("publish_gate_report decision must be ready, needs_revision, or blocked", errors)

        audit = ChapterAuditReport(
            title="audit",
            content={
                "target_asset_id": "draft1",
                "dimension_scores": {"plot": 80},
                "issues": [],
                "gate_results": {"plot": True},
                "linked_reports": {},
                "recommendation": "pass",
            },
        )
        release = ReleasePackage(
            title="release",
            content={
                "target_asset_id": "draft1",
                "publish_gate_report_id": "gate1",
                "title_candidates": ["Chapter 1"],
                "summary": "summary",
                "tags": [],
                "channel": "local",
                "status": "ready",
            },
        )
        self.assertEqual(validate_common_fields(audit.to_dict()), [])
        self.assertEqual(validate_common_fields(release.to_dict()), [])

    def test_analysis_assets_reject_direct_generation_rag(self):
        report = CommonNovelAnalysisReport(
            title="analysis",
            content={
                "source_asset_id": "source1",
                "analysis_scope": "structure",
                "structure_map": {},
                "character_map": {},
                "conflict_map": {},
                "theme_map": {},
                "risk_boundary": "abstract only",
                "reusable_findings": ["hook density"],
            },
            metadata={
                "copyright_boundary": "abstract structure only",
                "copyright_risk": "low",
                "abstraction_level": "abstract",
                "use_in_generation_rag": True,
            },
        )
        errors = validate_common_fields(report.to_dict())
        self.assertIn("common_novel_analysis_report must not enter generation RAG directly; convert to abstract assets first", errors)

        conversion = AnalysisConversionReport(
            title="conversion",
            content={
                "source_report_id": "report1",
                "source_report_type": "web_fiction_business_analysis_report",
                "conversion_targets": ["material_card"],
                "created_assets": [],
                "rejected_items": [],
                "reuse_scope": "project",
                "copyright_risk": "low",
                "abstraction_level": "template",
            },
            metadata={"copyright_boundary": "abstract structure only"},
        )
        self.assertEqual(validate_common_fields(conversion.to_dict()), [])

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

    def test_style_profile_rejects_specific_author_imitation(self):
        profile = StyleProfile(
            title="bad style",
            content={
                "style_id": "bad",
                "name": "bad",
                "scope": "project",
                "source_boundary": {
                    "source_asset_ids": [],
                    "derived_from_protected_text": False,
                    "copyright_risk": "low",
                    "allowed_usage": "parameter_only",
                },
                "language_parameters": {},
                "narrative_parameters": {},
                "emotion_parameters": {},
                "forbidden_patterns": ["do not copy source text"],
                "target_author": "protected author",
            },
            metadata={"copyright_boundary": "abstract structure only"},
        )

        errors = validate_common_fields(profile.to_dict())

        self.assertIn("style_profile must not request specific author imitation", errors)


if __name__ == "__main__":
    unittest.main()
