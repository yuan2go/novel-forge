from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import (
    AgentContract,
    AgentDispatchQueue,
    AgentRun,
    AgentTask,
    AnalysisConversionReport,
    CanonGraphSnapshot,
    ChapterAuditReport,
    ChapterProductionRun,
    ChapterPlanVersion,
    ClaudeCodeHandoff,
    CommonNovelAnalysisReport,
    ContextBuildPlan,
    ContextBundle,
    CreativeStrategyProfile,
    DraftVersion,
    FeedbackImportBatch,
    GenerationRun,
    ChangeImpactReport,
    LocalSettingsProfile,
    LoopRun,
    LongformRecapReport,
    NovelKGSnapshot,
    NodeRun,
    OriginalityReport,
    OutlineVersion,
    ProjectMetricSnapshot,
    ProductionGovernanceReport,
    PublishGateReport,
    RagQualityReport,
    ProjectWorkspaceState,
    ReaderFeedbackBackflowReport,
    ReaderSimulationReport,
    ReaderSentimentReport,
    ReleasePackage,
    FallbackDecision,
    ReviewReport,
    SCHEMA_CLASSES,
    SourceDocument,
    StyleProfile,
    validate_common_fields,
)


class SchemaTests(unittest.TestCase):
    def test_required_schema_count(self):
        self.assertEqual(len(SCHEMA_CLASSES), 265)
        self.assertIn("source_document", SCHEMA_CLASSES)
        self.assertIn("source_chunk", SCHEMA_CLASSES)
        self.assertIn("asset_collection", SCHEMA_CLASSES)
        self.assertIn("knowledge_usage_binding", SCHEMA_CLASSES)
        self.assertIn("rule_card", SCHEMA_CLASSES)
        self.assertIn("template_card", SCHEMA_CLASSES)
        self.assertIn("knowledge_pack", SCHEMA_CLASSES)
        self.assertIn("knowledge_pack_item", SCHEMA_CLASSES)
        self.assertIn("knowledge_usage_event", SCHEMA_CLASSES)
        self.assertIn("knowledge_quality_score", SCHEMA_CLASSES)
        self.assertIn("knowledge_graph_snapshot", SCHEMA_CLASSES)
        self.assertIn("knowledge_learning_snapshot", SCHEMA_CLASSES)
        self.assertIn("review_report", SCHEMA_CLASSES)
        self.assertIn("review_issue", SCHEMA_CLASSES)
        self.assertIn("loop_run", SCHEMA_CLASSES)
        self.assertIn("loop_step", SCHEMA_CLASSES)
        self.assertIn("loop_checkpoint", SCHEMA_CLASSES)
        self.assertIn("loop_report", SCHEMA_CLASSES)
        self.assertIn("project_workspace_state", SCHEMA_CLASSES)
        self.assertIn("task_dead_letter", SCHEMA_CLASSES)
        self.assertIn("batch_task_item", SCHEMA_CLASSES)
        self.assertIn("claude_code_handoff", SCHEMA_CLASSES)
        self.assertIn("platform_profile", SCHEMA_CLASSES)
        self.assertIn("platform_rhythm_rule", SCHEMA_CLASSES)
        self.assertIn("platform_opening_gate", SCHEMA_CLASSES)
        self.assertIn("platform_chapter_gate", SCHEMA_CLASSES)
        self.assertIn("platform_retention_risk", SCHEMA_CLASSES)
        self.assertIn("platform_publish_adapter", SCHEMA_CLASSES)
        self.assertIn("platform_feedback_backflow", SCHEMA_CLASSES)
        self.assertIn("reader_simulation_report", SCHEMA_CLASSES)
        self.assertIn("reader_feedback_backflow_report", SCHEMA_CLASSES)
        self.assertIn("platform_strategy_pack", SCHEMA_CLASSES)
        self.assertIn("genre_market_profile", SCHEMA_CLASSES)
        self.assertIn("genre_profile", SCHEMA_CLASSES)
        self.assertIn("subgenre_mechanic", SCHEMA_CLASSES)
        self.assertIn("genre_strategy_pack", SCHEMA_CLASSES)
        self.assertIn("genre_risk_gate", SCHEMA_CLASSES)
        self.assertIn("platform_genre_fit", SCHEMA_CLASSES)
        self.assertIn("genre_template_binding", SCHEMA_CLASSES)
        self.assertIn("production_governance_report", SCHEMA_CLASSES)
        self.assertIn("fallback_decision", SCHEMA_CLASSES)
        self.assertIn("creative_strategy_profile", SCHEMA_CLASSES)
        self.assertIn("style_profile", SCHEMA_CLASSES)
        self.assertIn("style_sample", SCHEMA_CLASSES)
        self.assertIn("style_fingerprint", SCHEMA_CLASSES)
        self.assertIn("style_generation_policy", SCHEMA_CLASSES)
        self.assertIn("style_review_rule", SCHEMA_CLASSES)
        self.assertIn("style_drift_report", SCHEMA_CLASSES)
        self.assertIn("style_rewrite_task", SCHEMA_CLASSES)
        self.assertIn("quality_standard_profile", SCHEMA_CLASSES)
        self.assertIn("quality_rubric_pack", SCHEMA_CLASSES)
        self.assertIn("opening_3_report", SCHEMA_CLASSES)
        self.assertIn("golden_10_report", SCHEMA_CLASSES)
        self.assertIn("volume_30_report", SCHEMA_CLASSES)
        self.assertIn("longform_100_report", SCHEMA_CLASSES)
        self.assertIn("continuity_bible", SCHEMA_CLASSES)
        self.assertIn("fantasy_power_scale_report", SCHEMA_CLASSES)
        self.assertIn("mystery_evidence_chain_report", SCHEMA_CLASSES)
        self.assertIn("romance_relationship_state_report", SCHEMA_CLASSES)
        self.assertIn("historical_faction_network_report", SCHEMA_CLASSES)
        self.assertIn("sci_fi_rule_consistency_report", SCHEMA_CLASSES)
        self.assertIn("horror_rule_contamination_report", SCHEMA_CLASSES)
        self.assertIn("chapter_audit_report", SCHEMA_CLASSES)
        self.assertIn("originality_report", SCHEMA_CLASSES)
        self.assertIn("publish_gate_report", SCHEMA_CLASSES)
        self.assertIn("release_package", SCHEMA_CLASSES)
        self.assertIn("content_quality_loop_report", SCHEMA_CLASSES)
        self.assertIn("common_novel_analysis_report", SCHEMA_CLASSES)
        self.assertIn("web_fiction_business_analysis_report", SCHEMA_CLASSES)
        self.assertIn("published_fiction_analysis_report", SCHEMA_CLASSES)
        self.assertIn("classic_literary_analysis_report", SCHEMA_CLASSES)
        self.assertIn("analysis_conversion_report", SCHEMA_CLASSES)
        self.assertIn("context_build_plan", SCHEMA_CLASSES)
        self.assertIn("context_bundle", SCHEMA_CLASSES)
        self.assertIn("rag_quality_report", SCHEMA_CLASSES)
        self.assertIn("outline_version", SCHEMA_CLASSES)
        self.assertIn("chapter_plan_version", SCHEMA_CLASSES)
        self.assertIn("draft_version", SCHEMA_CLASSES)
        self.assertIn("generation_run", SCHEMA_CLASSES)
        self.assertIn("chapter_production_run", SCHEMA_CLASSES)
        self.assertIn("canon_database", SCHEMA_CLASSES)
        self.assertIn("chapter_state", SCHEMA_CLASSES)
        self.assertIn("chapter_pattern_report", SCHEMA_CLASSES)
        self.assertIn("fact_ledger", SCHEMA_CLASSES)
        self.assertIn("arc_plan", SCHEMA_CLASSES)
        self.assertIn("foreshadowing_graph", SCHEMA_CLASSES)
        self.assertIn("motif_budget_report", SCHEMA_CLASSES)
        self.assertIn("character_state_ledger", SCHEMA_CLASSES)
        self.assertIn("villain_operation_plan", SCHEMA_CLASSES)
        self.assertIn("reader_fatigue_report", SCHEMA_CLASSES)
        self.assertIn("style_control_plan", SCHEMA_CLASSES)
        self.assertIn("platform_adapter_report", SCHEMA_CLASSES)
        self.assertIn("reward_ledger", SCHEMA_CLASSES)
        self.assertIn("review_score_system_report", SCHEMA_CLASSES)
        self.assertIn("workflow_definition", SCHEMA_CLASSES)
        self.assertIn("workflow_node", SCHEMA_CLASSES)
        self.assertIn("node_run", SCHEMA_CLASSES)
        self.assertIn("change_impact_report", SCHEMA_CLASSES)
        self.assertIn("agent_contract", SCHEMA_CLASSES)
        self.assertIn("agent_task", SCHEMA_CLASSES)
        self.assertIn("agent_run", SCHEMA_CLASSES)
        self.assertIn("agent_checkpoint", SCHEMA_CLASSES)
        self.assertIn("agent_event", SCHEMA_CLASSES)
        self.assertIn("agent_budget", SCHEMA_CLASSES)
        self.assertIn("agent_gate", SCHEMA_CLASSES)
        self.assertIn("agent_metric", SCHEMA_CLASSES)
        self.assertIn("agent_failure_report", SCHEMA_CLASSES)
        self.assertIn("agent_sla_report", SCHEMA_CLASSES)
        self.assertIn("agent_rollback_report", SCHEMA_CLASSES)
        self.assertIn("agent_dispatch_queue", SCHEMA_CLASSES)
        self.assertIn("agent_registry_entry", SCHEMA_CLASSES)
        self.assertIn("agent_version", SCHEMA_CLASSES)
        self.assertIn("agent_capability", SCHEMA_CLASSES)
        self.assertIn("agent_lifecycle_event", SCHEMA_CLASSES)
        self.assertIn("agent_evaluation_binding", SCHEMA_CLASSES)
        self.assertIn("agent_registry_snapshot", SCHEMA_CLASSES)
        self.assertIn("audit_log", SCHEMA_CLASSES)
        self.assertIn("audit_trail_report", SCHEMA_CLASSES)
        self.assertIn("audit_export_package", SCHEMA_CLASSES)
        self.assertIn("evaluation_suite", SCHEMA_CLASSES)
        self.assertIn("evaluation_case", SCHEMA_CLASSES)
        self.assertIn("evaluation_run", SCHEMA_CLASSES)
        self.assertIn("evaluation_result", SCHEMA_CLASSES)
        self.assertIn("evaluation_metric", SCHEMA_CLASSES)
        self.assertIn("evaluation_gate", SCHEMA_CLASSES)
        self.assertIn("evaluation_regression_report", SCHEMA_CLASSES)
        self.assertIn("evaluation_dashboard_snapshot", SCHEMA_CLASSES)
        self.assertIn("analytics_event", SCHEMA_CLASSES)
        self.assertIn("analytics_sync_job", SCHEMA_CLASSES)
        self.assertIn("analytics_dashboard_snapshot", SCHEMA_CLASSES)
        self.assertIn("analytics_metric_definition", SCHEMA_CLASSES)
        self.assertIn("operation_transaction", SCHEMA_CLASSES)
        self.assertIn("rollback_plan", SCHEMA_CLASSES)
        self.assertIn("rollback_result", SCHEMA_CLASSES)
        self.assertIn("editor_patch", SCHEMA_CLASSES)
        self.assertIn("draft_diff_report", SCHEMA_CLASSES)
        self.assertIn("long_form_macro_plan", SCHEMA_CLASSES)
        self.assertIn("canon_patch", SCHEMA_CLASSES)
        self.assertIn("model_routing_policy", SCHEMA_CLASSES)
        self.assertIn("operational_metric_snapshot", SCHEMA_CLASSES)
        self.assertIn("publishing_plan", SCHEMA_CLASSES)
        self.assertIn("publishing_log", SCHEMA_CLASSES)
        self.assertIn("local_ops_drill_report", SCHEMA_CLASSES)
        self.assertIn("long_chain_acceptance_report", SCHEMA_CLASSES)
        self.assertIn("longform_recap_report", SCHEMA_CLASSES)
        self.assertIn("long_chain_run", SCHEMA_CLASSES)
        self.assertIn("long_chain_checkpoint", SCHEMA_CLASSES)
        self.assertIn("long_chain_failure_report", SCHEMA_CLASSES)
        self.assertIn("platform_upload_package", SCHEMA_CLASSES)
        self.assertIn("platform_publish_receipt", SCHEMA_CLASSES)
        self.assertIn("platform_metric_snapshot", SCHEMA_CLASSES)
        self.assertIn("platform_comment_batch", SCHEMA_CLASSES)
        self.assertIn("comment_cluster_report", SCHEMA_CLASSES)
        self.assertIn("feedback_plan_mutation_proposal", SCHEMA_CLASSES)
        self.assertIn("feedback_mutation_patch", SCHEMA_CLASSES)
        self.assertIn("chapter_continuity_report", SCHEMA_CLASSES)
        self.assertIn("continuity_graph_snapshot", SCHEMA_CLASSES)
        self.assertIn("canon_graph_snapshot", SCHEMA_CLASSES)
        self.assertIn("canon_state_machine_ledger", SCHEMA_CLASSES)
        self.assertIn("novel_kg_snapshot", SCHEMA_CLASSES)
        self.assertIn("semantic_extraction_report", SCHEMA_CLASSES)
        self.assertIn("kg_identity_resolution", SCHEMA_CLASSES)
        self.assertIn("model_profile", SCHEMA_CLASSES)
        self.assertIn("model_benchmark_task", SCHEMA_CLASSES)
        self.assertIn("model_benchmark_run", SCHEMA_CLASSES)
        self.assertIn("model_comparison_report", SCHEMA_CLASSES)
        self.assertIn("prompt_version", SCHEMA_CLASSES)
        self.assertIn("prompt_regression_report", SCHEMA_CLASSES)
        self.assertIn("model_route", SCHEMA_CLASSES)
        self.assertIn("model_route_resolution", SCHEMA_CLASSES)
        self.assertIn("prompt_template", SCHEMA_CLASSES)
        self.assertIn("prompt_release", SCHEMA_CLASSES)
        self.assertIn("prompt_node_binding", SCHEMA_CLASSES)
        self.assertIn("tool_definition", SCHEMA_CLASSES)
        self.assertIn("tool_invocation", SCHEMA_CLASSES)
        self.assertIn("tool_permission_policy", SCHEMA_CLASSES)
        self.assertIn("mcp_server_registry", SCHEMA_CLASSES)
        self.assertIn("state_event", SCHEMA_CLASSES)
        self.assertIn("state_snapshot", SCHEMA_CLASSES)
        self.assertIn("state_replay", SCHEMA_CLASSES)
        self.assertIn("state_conflict_report", SCHEMA_CLASSES)
        self.assertIn("agent_message", SCHEMA_CLASSES)
        self.assertIn("agent_inbox", SCHEMA_CLASSES)
        self.assertIn("agent_outbox", SCHEMA_CLASSES)
        self.assertIn("agent_handoff", SCHEMA_CLASSES)
        self.assertIn("agent_conversation_trace", SCHEMA_CLASSES)
        self.assertIn("memory_record", SCHEMA_CLASSES)
        self.assertIn("memory_selection", SCHEMA_CLASSES)
        self.assertIn("memory_retrieval_report", SCHEMA_CLASSES)
        self.assertIn("memory_chunk", SCHEMA_CLASSES)
        self.assertIn("knowledge_chunk", SCHEMA_CLASSES)
        self.assertIn("artifact_embedding", SCHEMA_CLASSES)
        self.assertIn("review_memory_chunk", SCHEMA_CLASSES)
        self.assertIn("entity_memory_chunk", SCHEMA_CLASSES)
        self.assertIn("pgvector_schema_plan", SCHEMA_CLASSES)
        self.assertIn("embedding_job", SCHEMA_CLASSES)
        self.assertIn("hybrid_retrieval_report", SCHEMA_CLASSES)
        self.assertIn("feedback_import_batch", SCHEMA_CLASSES)
        self.assertIn("reader_sentiment_report", SCHEMA_CLASSES)
        self.assertIn("feedback_cluster", SCHEMA_CLASSES)
        self.assertIn("feedback_backflow_plan", SCHEMA_CLASSES)
        self.assertIn("plan_adjustment_proposal", SCHEMA_CLASSES)
        self.assertIn("review_rule_update_proposal", SCHEMA_CLASSES)
        self.assertIn("feedback_kg_patch", SCHEMA_CLASSES)
        self.assertIn("project_metric_snapshot", SCHEMA_CLASSES)
        self.assertIn("local_settings_profile", SCHEMA_CLASSES)

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

    def test_creative_strategy_and_canon_graph_assets_validate(self):
        strategy = CreativeStrategyProfile(
            title="Strategy",
            content={
                "strategy_id": "strategy_v1",
                "reader_promise": "clear promise",
                "volume_goals": {"volume_1": "setup and payoff"},
                "pleasure_rhythm": {"chapter_loop": ["hook", "choice", "payoff"]},
                "long_hooks": [{"hook_id": "mystery", "status": "seeded"}],
                "platform_pacing": {"chapter_length_target": 2500},
                "verification_rules": ["chapter plan states reader promise"],
            },
        )
        canon = CanonGraphSnapshot(
            title="Canon",
            content={
                "snapshot_id": "canon_1",
                "project_id": "project_1",
                "entities": [],
                "relationships": [],
                "state_machines": {"characters": []},
                "lifecycle_threads": [],
                "event_graph": [],
                "violations": [],
            },
        )
        self.assertEqual(validate_common_fields(strategy.to_dict()), [])
        self.assertEqual(validate_common_fields(canon.to_dict()), [])

        kg = NovelKGSnapshot(
            title="Novel KG",
            content={
                "kg_id": "kg_1",
                "ontology_version": "novel-kg-0.1.0",
                "project_id": "project_1",
                "entities": [],
                "relations": [],
                "events": [],
                "rules": [],
                "timelines": [],
                "foreshadowing": [],
                "factions": [],
                "locations": [],
                "props": [],
                "power_scales": [],
                "review_rules": [],
                "templates": [],
                "summary": {"counts": {}},
                "built_at": "2026-01-01T00:00:00Z",
            },
        )
        self.assertEqual(validate_common_fields(kg.to_dict()), [])

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

    def test_production_governance_and_fallback_decision_validation(self):
        governance = ProductionGovernanceReport(
            title="governance",
            content={
                "report_id": "gov-1",
                "operation": "publishing.publish_gate",
                "environment": "production",
                "target_asset_id": "draft1",
                "target_asset_path": "data/drafts/draft1.json",
                "required_gates": ["os_envelope", "provider_runtime_gate"],
                "gate_statuses": {"os_envelope": {"status": "passed"}, "provider_runtime_gate": {"status": "passed"}},
                "status": "passed",
                "blocking": False,
                "blocking_issues": [],
                "rollback_plan": {"rollback_action": "do_not_create_release_package"},
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        decision = FallbackDecision(
            title="fallback",
            content={
                "decision_id": "fallback-1",
                "fallback_type": "provider",
                "mode": "manual_operator_approval",
                "allowed": True,
                "approval_required": True,
                "silent_fallback_allowed": False,
                "reason": "operator approved",
                "rollback_plan": {"rollback_action": "return_to_primary_route"},
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        self.assertEqual(validate_common_fields(governance.to_dict()), [])
        self.assertEqual(validate_common_fields(decision.to_dict()), [])

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

    def test_context_and_versioned_production_asset_validation(self):
        plan = ContextBuildPlan(
            title="context plan",
            content={
                "target_asset_id": "chapter_plan_1",
                "target_asset_type": "chapter_plan",
                "target_path": "data/chapter_plans/chapter_plan_1.json",
                "query": "chapter objective",
                "top_k": 3,
                "token_budget": {"max_tokens": 2000, "reserved_for_prompt": 300, "reserved_for_response": 700},
                "selection_policy": {"project_scoped": True},
                "candidate_assets": [],
                "exclusions": [],
            },
        )
        self.assertEqual(validate_common_fields(plan.to_dict()), [])

        bundle = ContextBundle(
            title="context bundle",
            content={
                "build_plan_id": plan.id,
                "target_asset_id": "chapter_plan_1",
                "selected_assets": [],
                "compressed_context": {},
                "token_budget": {"max_tokens": 2000},
                "token_estimate": 16,
                "actual_context": "No eligible project-scoped context assets were selected.",
                "source_asset_ids": [],
            },
        )
        self.assertEqual(validate_common_fields(bundle.to_dict()), [])

        rag_report = RagQualityReport(
            title="rag quality",
            content={
                "target_asset_id": "chapter_plan_1",
                "retrieval_backend": "local",
                "recall_explanation": {"items": []},
                "omission_check": {"missing_buckets": []},
                "copyright_filter": {"filtered_assets": []},
                "context_budget_score": {"score": 86, "status": "healthy"},
                "recommendation": "pass",
            },
        )
        self.assertEqual(validate_common_fields(rag_report.to_dict()), [])

        outline_version = OutlineVersion(
            title="outline v0",
            content={
                "outline_id": "outline_1",
                "version_index": 0,
                "base_outline_id": "outline_1",
                "acts": [],
                "change_summary": "initial",
                "status": "active",
            },
        )
        chapter_plan_version = ChapterPlanVersion(
            title="plan v0",
            content={
                "chapter_plan_id": "plan_1",
                "version_index": 0,
                "base_chapter_plan_id": "outline_1",
                "chapter": 1,
                "objective": "open conflict",
                "beats": ["hook"],
                "hook": "bell rings",
                "word_budget": {"target": 2500},
                "conflict": "public risk",
                "information_points": ["clock clue"],
                "status": "active",
            },
        )
        draft_version = DraftVersion(
            title="draft v0",
            content={
                "draft_id": "draft_1",
                "version_index": 0,
                "chapter": 1,
                "text": "original draft",
                "source_draft_id": "draft_1",
                "change_summary": "initial",
                "status": "active",
            },
        )
        run = GenerationRun(
            title="run",
            content={
                "run_id": "run_1",
                "input_asset_id": "plan_1",
                "input_asset_path": "data/chapter_plans/plan_1.json",
                "context_bundle_id": bundle.id,
                "output_asset_id": "draft_1",
                "provider": "mock",
                "model": "mock",
                "prompt_version": "prompt-v1",
                "status": "succeeded",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:00Z",
            },
        )
        self.assertEqual(validate_common_fields(outline_version.to_dict()), [])
        self.assertEqual(validate_common_fields(chapter_plan_version.to_dict()), [])
        self.assertEqual(validate_common_fields(draft_version.to_dict()), [])
        self.assertEqual(validate_common_fields(run.to_dict()), [])

        bad_run = run.to_dict()
        bad_run["content"]["status"] = "done"
        self.assertIn("generation_run status must be planned, prepared, running, succeeded, failed, or cancelled", validate_common_fields(bad_run))

    def test_workflow_impact_and_agent_asset_validation(self):
        node_run = NodeRun(
            title="node run",
            content={
                "run_id": "run-1",
                "node_id": "draft",
                "node_type": "generation",
                "operation": "draft",
                "status": "succeeded",
                "input_assets": [],
                "output_assets": [],
                "processor": {"kind": "local_service"},
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:00Z",
            },
        )
        impact = ChangeImpactReport(
            title="impact",
            content={
                "target_asset_id": "outline-1",
                "target_path": "data/outlines/outline-1.json",
                "impacted_assets": [],
                "impact_edges": [],
                "severity_summary": {"blocking": 0, "high": 0, "medium": 0, "low": 0},
                "recommendation": "no_action",
            },
        )
        contract = AgentContract(
            title="contract",
            content={
                "contract_id": "contract-1",
                "agent_type": "Draft Agent",
                "operation": "draft",
                "input_types": ["chapter_plan"],
                "output_types": ["draft_chapter"],
                "permissions": {"permission_profile": "draft_generation_from_approved_context"},
                "tool_allowlist": ["read_asset", "call_model_adapter"],
                "allowed_write_types": ["draft_chapter"],
                "quality_gates": [{"gate": "schema_validation", "required": True}],
            },
        )
        agent_run = AgentRun(
            title="agent run",
            content={
                "run_id": "agent-run-1",
                "agent_type": "Draft Agent",
                "operation": "draft",
                "status": "waiting_human",
                "input_assets": [],
                "output_assets": [],
                "contract_id": "contract-1",
                "permissions": {"tool_allowlist": ["read_asset"]},
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        dispatch_queue = AgentDispatchQueue(
            title="dispatch",
            content={
                "dispatch_id": "dispatch-1",
                "idempotency_key": "workflow:node:agent:contract",
                "status": "queued",
                "agent_run_id": "agent-run-1",
                "agent_run_path": "data/runs/agent-run-1.json",
                "operation": "draft",
                "attempt_count": 0,
                "max_attempts": 3,
                "priority": 100,
                "result": {},
                "trace": {},
            },
        )
        self.assertEqual(validate_common_fields(node_run.to_dict()), [])
        self.assertEqual(validate_common_fields(impact.to_dict()), [])
        self.assertEqual(validate_common_fields(contract.to_dict()), [])
        self.assertEqual(validate_common_fields(agent_run.to_dict()), [])
        self.assertEqual(validate_common_fields(dispatch_queue.to_dict()), [])

        bad_run = agent_run.to_dict()
        bad_run["content"]["status"] = "done"
        self.assertIn("agent_run status is invalid", validate_common_fields(bad_run))

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

    def test_feedback_metrics_and_settings_assets_validate(self):
        batch = FeedbackImportBatch(
            title="batch",
            content={
                "batch_id": "batch1",
                "source": "feedback.csv",
                "rows": [{"chapter": "1", "rating": "5", "comment": "hook works"}],
                "row_count": 1,
                "columns": ["chapter", "rating", "comment"],
                "status": "imported",
                "imported_at": "2026-01-01T00:00:00Z",
            },
        )
        sentiment = ReaderSentimentReport(
            title="sentiment",
            content={
                "feedback_asset_ids": ["feedback1"],
                "sentiment_distribution": {"positive": 1, "neutral": 0, "negative": 0},
                "clusters": [{"label": "hook", "polarity": "positive", "count": 1}],
                "reader_expectations": ["preserve hook clarity"],
                "poison_points": [],
                "sweet_points": ["hook"],
                "recommendations": ["continue"],
                "confidence": "low",
            },
        )
        simulation = ReaderSimulationReport(
            title="simulation",
            content={
                "simulation_id": "sim1",
                "project_id": "p1",
                "personas": [{"persona_id": "shuangwen_reader", "predicted_score": 80, "dropout_risk": "low"}],
                "aggregate": {"predicted_score": 80, "dropout_risk": "low", "revision_suggestions": []},
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        snapshot = ProjectMetricSnapshot(
            title="snapshot",
            content={
                "project_id": "p1",
                "snapshot_at": "2026-01-01T00:00:00Z",
                "throughput": {"asset_count": 1},
                "quality": {"average_review_score": 80, "review_pass_rate": 1.0, "originality_risk_rate": 0.0},
                "task_health": {"failed": 0, "running": 0, "waiting_handoff": 0, "dead_letters": 0},
                "agent_health": {"runs": 0, "failed": 0},
                "storage_health": {"data_dirs": 1},
                "recommendations": ["ok"],
            },
        )
        settings = LocalSettingsProfile(
            title="settings",
            content={
                "profile_id": "local",
                "local_mode": True,
                "model_routing": {"default_provider": "local-rules"},
                "storage": {"root": "."},
                "agent_defaults": {"tool_allowlist_enforced": True},
                "validation": {"strict_local_prod": False},
                "status": "active",
            },
        )
        backflow = ReaderFeedbackBackflowReport(
            title="real feedback backflow",
            content={
                "backflow_report_id": "backflow1",
                "project_id": "p1",
                "metric_snapshot_path": "feedback/snapshot.json",
                "target_updates": {"mkaos_weight": {"status": "updated"}},
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        for asset in [batch, sentiment, simulation, snapshot, settings, backflow]:
            self.assertEqual(validate_common_fields(asset.to_dict()), [])

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
