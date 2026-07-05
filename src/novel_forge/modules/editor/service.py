from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.model_adapters import (
    GuardedModelAdapter,
    ModelAdapter,
    ModelOutputValidationError,
    model_from_env,
    parse_json_object,
    validate_model_output,
)
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.context_builder import build_flow_context_bundle, knowledge_context_contract_from_result, knowledge_context_contract_metadata, require_knowledge_context_contract
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment, normalize_runtime_request_policy
from novel_forge.modules.production_governance import build_production_governance_report
from novel_forge.modules.production_chain import create_draft_version, create_generation_run
from novel_forge.modules.production_context import build_production_context, filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review_issue import assert_no_blocking_review_issues
from novel_forge.schemas import DraftChapter, DraftDiffReport, EditorPatch, validate_common_fields
from novel_forge.storage.local import LocalStorage

REVISION_EXECUTOR_PROMPT_VERSION = "revision-executor-v1-paragraph-patch"


def create_editor_patch(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    instructions: str = "",
    operations: list[dict[str, Any]] | None = None,
    workspace_path: str | None = None,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    if draft.type != "draft_chapter":
        raise ValueError("draft_path must point to a draft_chapter asset")
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=os_envelope,
        environment=environment,
        source_policy=source_policy,
        operation="editor.create_patch",
    )
    environment = str(runtime_request["environment"])
    os_envelope = runtime_request["envelope"] if runtime_request.get("envelope") else None
    context = build_flow_context_bundle(
        storage,
        path,
        flow="editor_patch",
        project_id=str(project.get("project_id", "")),
        workspace_path=str(project.get("workspace_path", "")),
        chapter_id=str(draft.content.get("chapter", "")) if isinstance(draft.content, dict) else "",
        current_goal=instructions or "create editor patch",
        token_budget=2500,
        environment=environment,
        os_envelope=os_envelope,
        source_policy=runtime_request["source_policy"],
    )
    knowledge_contract = knowledge_context_contract_from_result(context)
    normalized_operations = _normalize_operations(operations or [], instructions=instructions, draft_text=str(draft.content.get("text", "")))
    with AgentExecutionContext(
        storage,
        agent_key="ai_editor",
        operation="create-editor-patch",
        input_assets=[path],
        output_types=["editor_patch"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=600,
        knowledge_context_contract=knowledge_contract,
    ) as run:
        run.guard("read_asset")
        run.guard("write_editor_patch", "editor_patch")
        now = utc_now()
        asset = EditorPatch(
            title=f"Editor patch for {draft.title or draft.id}",
            source=draft.id,
            tags=["editor", "patch", "proposed"],
            content={
                "patch_id": make_id("editor_patch", draft.id),
                "target_draft_id": draft.id,
                "target_draft_path": _display_path(storage.root, path),
                "instructions": instructions,
                "operations": normalized_operations,
                "status": "proposed",
                "risk_flags": _operation_risks(normalized_operations),
                "knowledge_context_contract": knowledge_contract,
                "created_at": now,
                "applied_at": "",
            },
            metadata={
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
                "agent_run_path": run.path,
                **knowledge_context_contract_metadata(knowledge_contract),
            },
            references=filter_project_safe_references(
                storage,
                str(project.get("project_id", "")),
                [draft.id, _display_path(storage.root, path)],
            ),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def apply_editor_patch(
    storage: LocalStorage,
    patch_path: str | Path,
    *,
    apply: bool = True,
    change_summary: str = "editor patch applied",
    operation_ids: list[str] | None = None,
    operation_indexes: list[int] | None = None,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, patch_path)
    patch = storage.read_asset(path)
    if patch.type != "editor_patch":
        raise ValueError("patch_path must point to an editor_patch asset")
    target_path = resolve_path(storage.root, str(patch.content.get("target_draft_path", "")))
    draft = storage.read_asset(target_path)
    if draft.type != "draft_chapter":
        raise ValueError("editor_patch target must point to a draft_chapter asset")
    project = project_scope_from_asset(storage, draft, input_path=target_path)
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=os_envelope,
        environment=environment,
        source_policy=source_policy,
        operation="editor.apply_patch",
    )
    environment = str(runtime_request["environment"])
    os_envelope = runtime_request["envelope"] if runtime_request.get("envelope") else None
    knowledge_contract = _patch_knowledge_context_contract(patch)
    require_knowledge_context_contract(knowledge_contract, operation="apply-editor-patch", environment=environment)
    applied_envelope = {}
    if is_production_environment(environment):
        applied_envelope = enforce_os_envelope(
            storage,
            envelope_payload=os_envelope,
            operation="editor.apply_patch",
            project_id=str(project.get("project_id", "")),
            task_type="revision",
            asset_type="draft_chapter",
            actor_type="editor_service",
            source="editor.apply_editor_patch",
            context_bundle_id=str(knowledge_contract.get("context_bundle_id", "")),
            source_policy=runtime_request["source_policy"],
            environment=environment,
            require_for_production=True,
        )
    before_text = str(draft.content.get("text", ""))
    selected_operations = _selected_operations(
        patch.content.get("operations", []),
        operation_ids=operation_ids or [],
        operation_indexes=operation_indexes or [],
    )
    after_text = _apply_operations(before_text, selected_operations)
    with AgentExecutionContext(
        storage,
        agent_key="ai_editor",
        operation="apply-editor-patch",
        input_assets=[path, target_path],
        output_types=["draft_diff_report", "draft_version"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=900,
    ) as run:
        run.guard("read_asset")
        run.guard("write_draft_diff_report", "draft_diff_report")
        diff_report = _write_diff_report(
            storage,
            base_draft=draft,
            base_path=target_path,
            target_draft=draft,
            target_path=target_path,
            before_text=before_text,
            after_text=after_text,
            operations=selected_operations,
            title=f"Patch diff for {draft.title or draft.id}",
            source=patch.id,
            project=project,
            extra_references=[patch.id, _display_path(storage.root, path)],
        )
        version: dict[str, Any] | None = None
        if apply:
            run.guard("write_draft_version", "draft_version")
            draft_data = storage.read_json(target_path)
            content = draft_data.get("content", {}) if isinstance(draft_data.get("content", {}), dict) else {}
            content["text"] = after_text
            content["last_editor_patch_id"] = patch.id
            content["last_editor_patch_path"] = _display_path(storage.root, path)
            draft_data["content"] = content
            draft_data["updated_at"] = utc_now()
            storage.write_json(target_path, draft_data)
            version = create_draft_version(storage, target_path, change_summary=change_summary, status="active")
            patch_data = storage.read_json(path)
            patch_content = patch_data.get("content", {}) if isinstance(patch_data.get("content", {}), dict) else {}
            patch_content["status"] = "partially_applied" if len(selected_operations) != len(patch.content.get("operations", [])) else "applied"
            patch_content["applied_at"] = utc_now()
            patch_content["applied_operation_ids"] = [str(operation.get("op_id", "")) for operation in selected_operations]
            patch_content["diff_report_path"] = diff_report["path"]
            patch_content["draft_version_path"] = version["path"]
            patch_data["content"] = patch_content
            patch_data["updated_at"] = utc_now()
            storage.write_json(path, patch_data)
        run.succeed(output_assets=[diff_report["path"], *( [version["path"]] if version else [] )])
        _annotate_apply_editor_patch_metadata(
            storage,
            diff_report_path=diff_report["path"],
            version_path=version["path"] if version else "",
            patch_path=_display_path(storage.root, path),
            environment=environment,
            os_envelope=applied_envelope,
            knowledge_contract=knowledge_contract,
        )
        return {
            "patch_path": _display_path(storage.root, path),
            "diff_report": diff_report,
            "draft_version": version,
            "applied": apply,
            "applied_operations": [str(operation.get("op_id", "")) for operation in selected_operations],
        }


def create_draft_diff_report(
    storage: LocalStorage,
    base_path: str | Path,
    target_path: str | Path,
) -> dict[str, Any]:
    base_file = resolve_path(storage.root, base_path)
    target_file = resolve_path(storage.root, target_path)
    base = storage.read_asset(base_file)
    target = storage.read_asset(target_file)
    if base.type not in {"draft_chapter", "draft_version"}:
        raise ValueError("base_path must point to draft_chapter or draft_version")
    if target.type not in {"draft_chapter", "draft_version"}:
        raise ValueError("target_path must point to draft_chapter or draft_version")
    project = project_scope_from_asset(storage, target, input_path=target_file)
    with AgentExecutionContext(
        storage,
        agent_key="ai_editor",
        operation="create-draft-diff-report",
        input_assets=[base_file, target_file],
        output_types=["draft_diff_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        run.guard("write_draft_diff_report", "draft_diff_report")
        result = _write_diff_report(
            storage,
            base_draft=base,
            base_path=base_file,
            target_draft=target,
            target_path=target_file,
            before_text=str(base.content.get("text", "")),
            after_text=str(target.content.get("text", "")),
            operations=[],
            title=f"Draft diff: {base.title or base.id} -> {target.title or target.id}",
            source=base.id,
            project=project,
            extra_references=[target.id, _display_path(storage.root, target_file)],
        )
        run.succeed(output_assets=[result["path"]])
        return result


def execute_revision_plan(
    storage: LocalStorage,
    *,
    draft_path: str | Path,
    review_path: str | Path,
    revision_path: str | Path,
    context_bundle_path: str | Path,
    model: ModelAdapter | None = None,
    workspace_path: str | None = None,
    chapter_production_run_id: str = "",
    chapter_production_run_path: str = "",
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
    provider_runtime_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a revision plan as model-backed paragraph patches.

    The source draft is never overwritten. The executor creates a new final
    draft, an applied forward patch, a proposed rollback patch, a paragraph
    diff report, a draft version, and a generation run.
    """

    model = model or model_from_env("revision_executor")
    draft_file = resolve_path(storage.root, draft_path)
    review_file = resolve_path(storage.root, review_path)
    revision_file = resolve_path(storage.root, revision_path)
    bundle_file = resolve_path(storage.root, context_bundle_path)
    draft = storage.read_asset(draft_file)
    review = storage.read_asset(review_file)
    revision = storage.read_asset(revision_file)
    bundle = storage.read_asset(bundle_file)
    if draft.type != "draft_chapter" or review.type != "review_report" or revision.type != "revision_plan":
        raise ValueError("execute_revision_plan requires draft_chapter, review_report, and revision_plan inputs")
    if bundle.type != "context_bundle":
        raise ValueError("context_bundle_path must point to a context_bundle asset")
    knowledge_contract = bundle.content.get("knowledge_context_contract", {}) if isinstance(bundle.content, dict) and isinstance(bundle.content.get("knowledge_context_contract", {}), dict) else {}
    project = project_scope_from_asset(storage, draft, input_path=draft_file, workspace_path=workspace_path)
    production_context = build_production_context(storage, draft, input_path=draft_file, workspace_path=str(project.get("workspace_path", "")))
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", ""))
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=os_envelope,
        environment=environment,
        source_policy=source_policy,
        operation="editor.execute_revision_plan",
    )
    environment = str(runtime_request["environment"])
    source_policy = runtime_request["source_policy"]
    os_envelope = runtime_request["envelope"] if runtime_request.get("envelope") else None
    assert_no_blocking_review_issues(storage, target_asset_id=draft.id, project_id=project_id or None, gate="canonical_chapter")
    applied_envelope: dict[str, Any] = {}
    preflight_governance: dict[str, Any] = {}
    if is_production_environment(environment):
        require_knowledge_context_contract(knowledge_contract, operation="execute-revision-plan", environment=environment)
        applied_envelope = enforce_os_envelope(
            storage,
            envelope_payload=os_envelope,
            operation="editor.execute_revision_plan",
            project_id=project_id,
            task_type="revision",
            asset_type="draft_chapter",
            actor_type="editor_service",
            source="editor.execute_revision_plan",
            context_bundle_id=str(knowledge_contract.get("context_bundle_id") or bundle.id),
            provider=str((provider_runtime_gate or {}).get("provider") or getattr(model, "name", "local")),
            model=str((provider_runtime_gate or {}).get("model") or getattr(model, "name", "local")),
            source_policy=source_policy,
            environment=environment,
            require_for_production=True,
        )
        preflight_governance = build_production_governance_report(
            storage,
            operation="editor.execute_revision_plan.preflight",
            environment=environment,
            target_asset_id=draft.id,
            target_asset_path=draft_file,
            project_id=project_id,
            workspace_path=workspace,
            gate_statuses={
                "os_envelope": {"status": "passed", "path": applied_envelope.get("trace_span_path", ""), "summary": {"envelope_id": applied_envelope.get("envelope_id", "")}},
                "context_bundle": {"status": "passed", "path": _display_path(storage.root, bundle_file), "summary": {"context_bundle_id": bundle.id}},
                "source_isolation": {"status": "passed", "path": _display_path(storage.root, bundle_file), "summary": source_policy},
                "review_issue": {"status": "passed", "summary": {"gate": "canonical_chapter"}},
                "provider_runtime_gate": provider_runtime_gate or {"status": "missing", "blocking": True, "summary": {"reason": "provider runtime evidence is required for production final draft promotion"}},
            },
            required_gates=["os_envelope", "context_bundle", "source_isolation", "review_issue", "provider_runtime_gate"],
            source_policy=source_policy,
            evidence_refs=[_display_path(storage.root, bundle_file), _display_path(storage.root, review_file), _display_path(storage.root, revision_file)],
            rollback_plan={"rollback_action": "do_not_promote_final_draft", "rollback_ref": _display_path(storage.root, draft_file), "requires_operator_review": True},
            trace={"trace_id": applied_envelope.get("trace_id", "")},
        )
        if preflight_governance["blocking"]:
            raise ValueError("production governance blocked final draft promotion: " + "; ".join(issue["message"] for issue in preflight_governance["blocking_issues"]))
    before_text = str(draft.content.get("text", ""))
    with AgentExecutionContext(
        storage,
        agent_key="ai_editor",
        operation="execute-revision-plan",
        input_assets=[draft_file, review_file, revision_file, bundle_file],
        output_types=["editor_patch", "draft_chapter", "draft_version", "draft_diff_report", "generation_run"],
        model_provider=getattr(model, "name", "local"),
        model_name=getattr(model, "name", "local"),
        prompt_version=REVISION_EXECUTOR_PROMPT_VERSION,
        token_budget=5000,
        sla_seconds=1200,
        workspace_path=workspace,
        knowledge_context_contract=knowledge_contract,
    ) as run:
        run.guard("read_asset")
        guarded_model = GuardedModelAdapter(model, storage, run.path)
        generated = validate_model_output(
            "generate",
            guarded_model.generate(
                "Execute the revision plan as paragraph-level patch operations. Return JSON only.",
                {
                    "required_output": {
                        "operations": [
                            {
                                "kind": "replace_text",
                                "target": "paragraph:1",
                                "paragraph_index": 1,
                                "before": "original paragraph text",
                                "after": "revised paragraph text",
                                "instruction": "revision reason",
                                "rationale": "why this fixes the review issue",
                                "risk": "low",
                            }
                        ],
                        "revision_summary": "string",
                        "quality_notes": ["string"],
                        "risk_controls": ["string"],
                    },
                    "draft": draft.to_dict(),
                    "review": review.to_dict(),
                    "revision_plan": revision.to_dict(),
                    "context_bundle": bundle.to_dict(),
                    "production_context": production_context,
                    "copyright_boundary": "Rewrite only project-owned draft text. Do not copy protected reference expression.",
                },
            ),
        )
        packet = _revision_execution_packet(
            generated,
            before_text=before_text,
            draft=draft.to_dict(),
            review=review.to_dict(),
            revision=revision.to_dict(),
            model_name=getattr(model, "name", ""),
        )
        operations = _normalize_operations(packet["operations"], instructions=packet["revision_summary"], draft_text=before_text)
        after_text = _apply_operations(before_text, operations)
        if not after_text.strip():
            raise ValueError("revision executor produced an empty final draft")
        rollback_operations = _rollback_operations(operations)
        now = utc_now()
        run.guard("write_editor_patch", "editor_patch")
        forward_patch = EditorPatch(
            title=f"Applied revision patch for {draft.title or draft.id}",
            source=revision.id,
            tags=["editor", "patch", "revision-executor", "applied"],
            content={
                "patch_id": make_id("editor_patch", f"forward-{draft.id}-{revision.id}"),
                "target_draft_id": draft.id,
                "target_draft_path": _display_path(storage.root, draft_file),
                "instructions": packet["revision_summary"],
                "operations": operations,
                "status": "applied",
                "risk_flags": _operation_risks(operations),
                "created_at": now,
                "applied_at": now,
                "executor": {
                    "agent_run_path": run.path,
                    "provider": str(generated.get("provider", getattr(model, "name", "local"))),
                    "model": str(generated.get("model", getattr(model, "name", "local"))),
                    "prompt_version": REVISION_EXECUTOR_PROMPT_VERSION,
                },
                "quality_notes": packet.get("quality_notes", []),
                "risk_controls": packet.get("risk_controls", []),
                "knowledge_context_contract": knowledge_contract,
                "production_governance_preflight": {
                    "status": preflight_governance.get("status", ""),
                    "path": preflight_governance.get("path", ""),
                    "gate_result_path": preflight_governance.get("gate_result_path", ""),
                },
            },
            metadata={
                "project_id": project_id,
                "workspace_path": workspace,
                "agent_run_path": run.path,
                **envelope_asset_metadata(applied_envelope),
                **knowledge_context_contract_metadata(knowledge_contract),
                "revision_plan_id": revision.id,
                "review_id": review.id,
                "patch_role": "forward_revision",
            },
            references=filter_project_safe_references(
                storage,
                project_id,
                [draft.id, _display_path(storage.root, draft_file), review.id, _display_path(storage.root, review_file), revision.id, _display_path(storage.root, revision_file)],
            ),
        )
        forward_patch_result = _write(storage, forward_patch)
        run.guard("write_draft_chapter", "draft_chapter")
        final = DraftChapter(
            title=f"{draft.title or 'Chapter draft'} final",
            source=draft.id,
            tags=_dedupe([*draft.tags, "draft", "final", "revision-executor"]),
            content={
                **draft.content,
                "text": after_text,
                "chapter": draft.content.get("chapter", 1),
                "copyright_boundary": draft.content.get("copyright_boundary", "final draft produced from project-owned draft and revision executor"),
                "revision_execution": {
                    "agent_run_path": run.path,
                    "forward_patch_id": forward_patch_result["id"],
                    "forward_patch_path": forward_patch_result["path"],
                    "review_id": review.id,
                    "review_path": _display_path(storage.root, review_file),
                    "revision_plan_id": revision.id,
                    "revision_plan_path": _display_path(storage.root, revision_file),
                    "revision_summary": packet["revision_summary"],
                    "quality_notes": packet.get("quality_notes", []),
                    "risk_controls": packet.get("risk_controls", []),
                    "chapter_production_run_id": chapter_production_run_id,
                    "chapter_production_run_path": chapter_production_run_path,
                    "knowledge_context_contract": knowledge_contract,
                    "production_governance_preflight": {
                        "status": preflight_governance.get("status", ""),
                        "path": preflight_governance.get("path", ""),
                        "gate_result_path": preflight_governance.get("gate_result_path", ""),
                    },
                },
            },
            metadata={
                **draft.metadata,
                "project_id": project_id,
                "workspace_path": workspace,
                **envelope_asset_metadata(applied_envelope),
                "draft_status": "final",
                "previous_draft_id": draft.id,
                "previous_draft_path": _display_path(storage.root, draft_file),
                "review_id": review.id,
                "review_path": _display_path(storage.root, review_file),
                "revision_plan_id": revision.id,
                "revision_plan_path": _display_path(storage.root, revision_file),
                "forward_patch_id": forward_patch_result["id"],
                "forward_patch_path": forward_patch_result["path"],
                "agent_run_path": run.path,
                **knowledge_context_contract_metadata(knowledge_contract),
                "provider": str(generated.get("provider", getattr(model, "name", "local"))),
                "model": str(generated.get("model", getattr(model, "name", "local"))),
                "prompt_version": REVISION_EXECUTOR_PROMPT_VERSION,
                "chapter_production_run_id": chapter_production_run_id,
                "finalized_at": now,
                "run_metadata": run_metadata(
                    "execute-revision-plan",
                    draft,
                    provider=str(generated.get("provider", getattr(model, "name", "local"))),
                    model=str(generated.get("model", getattr(model, "name", "local"))),
                    prompt_version=REVISION_EXECUTOR_PROMPT_VERSION,
                ),
            },
            references=filter_project_safe_references(
                storage,
                project_id,
                _dedupe([
                    draft.id,
                    _display_path(storage.root, draft_file),
                    review.id,
                    _display_path(storage.root, review_file),
                    revision.id,
                    _display_path(storage.root, revision_file),
                    bundle.id,
                    _display_path(storage.root, bundle_file),
                    forward_patch_result["id"],
                    forward_patch_result["path"],
                    *draft.references,
                ]),
            ),
        )
        final_path = storage.write_asset("drafts", final)
        final_ref = _display_path(storage.root, final_path)
        run.guard("write_editor_patch", "editor_patch")
        rollback_patch = EditorPatch(
            title=f"Rollback revision patch for {final.title or final.id}",
            source=final.id,
            tags=["editor", "patch", "revision-executor", "rollback"],
            content={
                "patch_id": make_id("editor_patch", f"rollback-{final.id}-{revision.id}"),
                "target_draft_id": final.id,
                "target_draft_path": final_ref,
                "instructions": "rollback final draft to the pre-revision draft text",
                "operations": rollback_operations,
                "status": "proposed",
                "risk_flags": _operation_risks(rollback_operations),
                "created_at": now,
                "applied_at": "",
                "rollback_for_patch_id": forward_patch_result["id"],
                "rollback_for_patch_path": forward_patch_result["path"],
            },
            metadata={
                "project_id": project_id,
                "workspace_path": workspace,
                "agent_run_path": run.path,
                "revision_plan_id": revision.id,
                "review_id": review.id,
                "patch_role": "rollback_revision",
                "target_final_draft_id": final.id,
                "target_final_draft_path": final_ref,
            },
            references=filter_project_safe_references(
                storage,
                project_id,
                [final.id, final_ref, draft.id, _display_path(storage.root, draft_file), forward_patch_result["id"], forward_patch_result["path"]],
            ),
        )
        rollback_patch_result = _write(storage, rollback_patch)
        run.guard("write_draft_diff_report", "draft_diff_report")
        diff = _write_diff_report(
            storage,
            base_draft=draft,
            base_path=draft_file,
            target_draft=final,
            target_path=final_path,
            before_text=before_text,
            after_text=after_text,
            operations=operations,
            title=f"Revision executor diff for {draft.title or draft.id}",
            source=forward_patch_result["id"],
            project=project,
            extra_references=[
                forward_patch_result["id"],
                forward_patch_result["path"],
                rollback_patch_result["id"],
                rollback_patch_result["path"],
                review.id,
                _display_path(storage.root, review_file),
                revision.id,
                _display_path(storage.root, revision_file),
            ],
        )
        final_governance: dict[str, Any] = {}
        if is_production_environment(environment):
            final_governance = build_production_governance_report(
                storage,
                operation="editor.execute_revision_plan.final_draft",
                environment=environment,
                target_asset_id=final.id,
                target_asset_path=final_path,
                project_id=project_id,
                workspace_path=workspace,
                gate_statuses={
                    "os_envelope": {"status": "passed", "path": applied_envelope.get("trace_span_path", ""), "summary": {"envelope_id": applied_envelope.get("envelope_id", "")}},
                    "context_bundle": {"status": "passed", "path": _display_path(storage.root, bundle_file), "summary": {"context_bundle_id": bundle.id}},
                    "source_isolation": {"status": "passed", "path": _display_path(storage.root, bundle_file), "summary": source_policy},
                    "review_issue": {"status": "passed", "summary": {"gate": "canonical_chapter"}},
                    "provider_runtime_gate": provider_runtime_gate or {"status": "missing", "blocking": True},
                    "rollback": {"status": "passed", "path": rollback_patch_result["path"], "summary": {"rollback_patch_id": rollback_patch_result["id"]}},
                },
                required_gates=["os_envelope", "context_bundle", "source_isolation", "review_issue", "provider_runtime_gate", "rollback"],
                source_policy=source_policy,
                evidence_refs=[
                    preflight_governance.get("path", ""),
                    forward_patch_result["path"],
                    rollback_patch_result["path"],
                    diff["path"],
                    _display_path(storage.root, review_file),
                    _display_path(storage.root, revision_file),
                ],
                rollback_plan={"rollback_action": "apply_editor_rollback_patch", "rollback_ref": rollback_patch_result["path"], "requires_operator_review": True},
                trace={"trace_id": applied_envelope.get("trace_id", "")},
            )
            if final_governance["blocking"]:
                raise ValueError("production governance blocked final draft promotion: " + "; ".join(issue["message"] for issue in final_governance["blocking_issues"]))
            final_data = storage.read_json(final_path)
            final_content = final_data.get("content", {}) if isinstance(final_data.get("content"), dict) else {}
            final_metadata = final_data.get("metadata", {}) if isinstance(final_data.get("metadata"), dict) else {}
            final_content["production_governance"] = {
                "status": final_governance["status"],
                "path": final_governance["path"],
                "gate_result_path": final_governance["gate_result_path"],
                "blocking": final_governance["blocking"],
            }
            final_metadata["production_governance_status"] = final_governance["status"]
            final_data["content"] = final_content
            final_data["metadata"] = final_metadata
            final_refs = final_data.get("references", []) if isinstance(final_data.get("references", []), list) else []
            final_data["references"] = _dedupe([*final_refs, final_governance["path"], final_governance["gate_result_path"]])
            storage.write_json(final_path, final_data)
        run.guard("write_draft_version", "draft_version")
        version = create_draft_version(storage, final_path, change_summary="model revision executor final draft", status="active")
        run.guard("write_generation_run", "generation_run")
        generation = create_generation_run(
            storage,
            revision_file,
            bundle_file,
            output_path=final_path,
            provider=str(generated.get("provider", getattr(model, "name", "local"))),
            model=str(generated.get("model", getattr(model, "name", "local"))),
            prompt_version=REVISION_EXECUTOR_PROMPT_VERSION,
            status="succeeded",
            metrics={
                "operation_count": len(operations),
                "rollback_operation_count": len(rollback_operations),
                "before_chars": len(before_text),
                "after_chars": len(after_text),
                "changed_paragraph_count": len(_paragraph_diffs(operations)),
            },
        )
        _link_revision_executor_outputs(
            storage,
            forward_patch_result["path"],
            rollback_patch_result["path"],
            final_ref,
            diff["path"],
            version["path"],
            generation["path"],
        )
        production_governance_path = str(final_governance.get("path", ""))
        output_assets = [forward_patch_result["path"], rollback_patch_result["path"], final_ref, version["path"], diff["path"], generation["path"]]
        if production_governance_path:
            output_assets.append(production_governance_path)
        run.succeed(
            output_assets=output_assets,
            token_used=len(before_text) + len(after_text),
        )
        return {
            "final_draft_path": final_ref,
            "final_draft_version_path": version["path"],
            "final_diff_report_path": diff["path"],
            "final_generation_run_path": generation["path"],
            "forward_patch_path": forward_patch_result["path"],
            "rollback_patch_path": rollback_patch_result["path"],
            "agent_run_path": run.path,
            "production_governance_path": production_governance_path,
            "production_governance_preflight_path": str(preflight_governance.get("path", "")),
            "operations": operations,
            "rollback_operations": rollback_operations,
            "output_paths": output_assets,
        }


def list_editor_artifacts(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category, asset_types in {"drafts": {"editor_patch", "draft_diff_report"}}.items():
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in asset_types:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) != project_id:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            rows.append(
                {
                    "path": _display_path(storage.root, path),
                    "id": data.get("id", ""),
                    "type": data.get("type", ""),
                    "title": data.get("title") or data.get("name", ""),
                    "status": content.get("status", ""),
                    "target_draft_path": content.get("target_draft_path") or content.get("target_draft_path", ""),
                    "summary": content.get("diff_summary", {}),
                    "operations": content.get("operations", []),
                    "project_id": metadata.get("project_id", ""),
                    "workspace_path": metadata.get("workspace_path", ""),
                    "updated_at": data.get("updated_at", ""),
                }
            )
    return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)[:limit]


def _patch_knowledge_context_contract(patch: Any) -> dict[str, Any]:
    content = patch.content if isinstance(getattr(patch, "content", {}), dict) else {}
    metadata = patch.metadata if isinstance(getattr(patch, "metadata", {}), dict) else {}
    contract = content.get("knowledge_context_contract") if isinstance(content.get("knowledge_context_contract"), dict) else {}
    if contract:
        return contract
    metadata_contract = metadata.get("knowledge_context_contract") if isinstance(metadata.get("knowledge_context_contract"), dict) else {}
    if metadata_contract:
        return metadata_contract
    if metadata.get("context_bundle_id") or metadata.get("knowledge_pack_id"):
        return {
            "context_bundle_id": str(metadata.get("context_bundle_id", "")),
            "knowledge_pack_id": str(metadata.get("knowledge_pack_id", "")),
            "source_policy": metadata.get("source_policy", {}) if isinstance(metadata.get("source_policy", {}), dict) else {},
            "source_isolation": metadata.get("source_isolation", {}) if isinstance(metadata.get("source_isolation", {}), dict) else {"source_chunk_raw_text_allowed": False},
            "mkaos_flow": str(metadata.get("mkaos_flow", "revision")),
        }
    return {}


def _annotate_apply_editor_patch_metadata(
    storage: LocalStorage,
    *,
    diff_report_path: str,
    version_path: str,
    patch_path: str,
    environment: str,
    os_envelope: dict[str, Any],
    knowledge_contract: dict[str, Any],
) -> None:
    for output_path in [diff_report_path, version_path]:
        if not output_path:
            continue
        try:
            path = resolve_path(storage.root, output_path)
            data = storage.read_json(path)
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            metadata.update(
                {
                    "apply_editor_patch_policy": "production_enforced" if is_production_environment(environment) else "compat_warning",
                    "apply_editor_patch_source": patch_path,
                    **knowledge_context_contract_metadata(knowledge_contract),
                    **envelope_asset_metadata(os_envelope),
                }
            )
            if not is_production_environment(environment):
                metadata["runtime_policy_warning"] = "apply-editor-patch compat path; production requires upstream knowledge context contract and OS envelope"
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            storage.write_json(path, data)
        except Exception:
            continue


def _write_diff_report(
    storage: LocalStorage,
    *,
    base_draft: Any,
    base_path: Path,
    target_draft: Any,
    target_path: Path,
    before_text: str,
    after_text: str,
    operations: list[dict[str, Any]],
    title: str,
    source: str,
    project: dict[str, Any],
    extra_references: list[str] | None = None,
) -> dict[str, Any]:
    diff_lines = list(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    summary = _diff_summary(before_text, after_text, diff_lines)
    asset = DraftDiffReport(
        title=title,
        source=source,
        tags=["draft", "diff", "editor"],
        content={
            "diff_id": make_id("draft_diff", f"{base_draft.id}-{target_draft.id}-{summary['changed_lines']}"),
            "base_draft_id": base_draft.id,
            "base_draft_path": _display_path(storage.root, base_path),
            "target_draft_id": target_draft.id,
            "target_draft_path": _display_path(storage.root, target_path),
            "diff_summary": summary,
            "operations": operations,
            "paragraph_diffs": _paragraph_diffs(operations),
            "unified_diff": diff_lines[:400],
            "created_at": utc_now(),
        },
        metadata={
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
        },
        references=filter_project_safe_references(
            storage,
            str(project.get("project_id", "")),
            [
                base_draft.id,
                _display_path(storage.root, base_path),
                target_draft.id,
                _display_path(storage.root, target_path),
                *(extra_references or []),
            ],
        ),
    )
    return _write(storage, asset)


def _revision_execution_packet(
    generated: dict[str, Any],
    *,
    before_text: str,
    draft: dict[str, Any],
    review: dict[str, Any],
    revision: dict[str, Any],
    model_name: str,
) -> dict[str, Any]:
    text = str(generated.get("text", "")).strip()
    if model_name != "mock-model":
        packet = _parse_json_payload(text)
        return _normalize_revision_execution_packet(packet, before_text=before_text, revision=revision)
    try:
        return _normalize_revision_execution_packet(_parse_json_payload(text), before_text=before_text, revision=revision)
    except ModelOutputValidationError:
        return _fallback_revision_execution_packet(before_text=before_text, draft=draft, review=review, revision=revision)


def _normalize_revision_execution_packet(packet: dict[str, Any], *, before_text: str, revision: dict[str, Any]) -> dict[str, Any]:
    operations = packet.get("operations")
    if not isinstance(operations, list) or not operations:
        revised_text = str(packet.get("revised_text") or "").strip()
        if revised_text:
            operations = _operations_from_revised_text(before_text, revised_text)
    if not isinstance(operations, list) or not operations:
        raise ModelOutputValidationError("revision executor JSON must contain operations or revised_text")
    normalized_operations = [_normalize_operation(index, operation) for index, operation in enumerate(operations, start=1) if isinstance(operation, dict)]
    if not normalized_operations:
        raise ModelOutputValidationError("revision executor operations must contain at least one object")
    summary = str(packet.get("revision_summary") or "").strip() or _revision_summary(revision)
    return {
        "operations": normalized_operations,
        "revision_summary": summary,
        "quality_notes": _strings(packet.get("quality_notes")),
        "risk_controls": _strings(packet.get("risk_controls")),
    }


def _fallback_revision_execution_packet(
    *,
    before_text: str,
    draft: dict[str, Any],
    review: dict[str, Any],
    revision: dict[str, Any],
) -> dict[str, Any]:
    operations = _fallback_revision_operations(before_text, review=review, revision=revision)
    return {
        "operations": operations,
        "revision_summary": _revision_summary(revision),
        "quality_notes": [
            "local fallback converted revision plan into paragraph-level patch operations",
            f"source draft: {draft.get('id', '')}",
        ],
        "risk_controls": [
            "preserve original project draft premise",
            "do not copy protected reference expression",
            "keep final draft rollback patch available",
        ],
    }


def _parse_json_payload(text: str) -> dict[str, Any]:
    try:
        return parse_json_object(text)
    except ModelOutputValidationError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return parse_json_object(text[start : end + 1])
        raise


def _normalize_operations(operations: list[dict[str, Any]], *, instructions: str, draft_text: str) -> list[dict[str, Any]]:
    if operations:
        return [_normalize_operation(index, operation) for index, operation in enumerate(operations, start=1)]
    return _suggest_paragraph_operations(draft_text, instructions=instructions)


def _normalize_operation(index: int, operation: dict[str, Any]) -> dict[str, Any]:
    kind = str(operation.get("kind") or operation.get("op") or "replace_text")
    return {
        "op_id": str(operation.get("op_id") or f"op-{index}"),
        "kind": kind,
        "target": str(operation.get("target", "document")),
        "paragraph_index": operation.get("paragraph_index", index),
        "before": str(operation.get("before", "")),
        "after": str(operation.get("after", "")),
        "instruction": str(operation.get("instruction", "")),
        "rationale": str(operation.get("rationale", "")),
        "status": str(operation.get("status", "proposed")),
        "risk": str(operation.get("risk", "low")),
    }


def _suggest_paragraph_operations(draft_text: str, *, instructions: str) -> list[dict[str, Any]]:
    paragraphs = _paragraphs(draft_text)
    note = instructions.strip() or "tighten paragraph while preserving continuity and originality boundary"
    if not paragraphs:
        return [
            {
                "op_id": "op-1",
                "kind": "append_text",
                "target": "document:end",
                "paragraph_index": 0,
                "before": "",
                "after": "\n\n[manual editor note] Add a concrete paragraph-level revision here after reviewing context.",
                "instruction": note,
                "status": "proposed",
                "risk": "low",
            }
        ]
    candidates = _candidate_paragraphs(paragraphs)
    operations: list[dict[str, Any]] = []
    for op_index, paragraph_index in enumerate(candidates[:5], start=1):
        before = paragraphs[paragraph_index]
        after = _paragraph_revision(before, instructions=note)
        operations.append(
            {
                "op_id": f"op-{op_index}",
                "kind": "replace_text",
                "target": f"paragraph:{paragraph_index + 1}",
                "paragraph_index": paragraph_index + 1,
                "before": before,
                "after": after,
                "instruction": note,
                "rationale": "paragraph-level tightening suggestion generated by local editor rules",
                "status": "proposed",
                "risk": _paragraph_risk(before, after),
            }
        )
    return operations


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def _candidate_paragraphs(paragraphs: list[str]) -> list[int]:
    scored = sorted(
        enumerate(paragraphs),
        key=lambda item: (
            len(item[1]) > 180,
            item[1].count("，") + item[1].count(",") + item[1].count(";") + item[1].count("；"),
            len(item[1]),
        ),
        reverse=True,
    )
    return [index for index, _ in scored] or [0]


def _paragraph_revision(paragraph: str, *, instructions: str) -> str:
    text = " ".join(paragraph.split())
    if len(text) > 360:
        text = text[:330].rstrip(" ,，。.") + "..."
    if "tighten" in instructions.lower() or "收紧" in instructions:
        text = _tighten_sentence(text)
    return text


def _tighten_sentence(text: str) -> str:
    replacements = {
        "very ": "",
        "really ": "",
        "just ": "",
        "其实": "",
        "非常": "",
        "有些": "",
        "似乎": "",
    }
    result = text
    for before, after in replacements.items():
        result = result.replace(before, after)
    return result


def _paragraph_risk(before: str, after: str) -> str:
    delta = abs(len(after) - len(before))
    if delta > 800 or len(before) > 1800:
        return "medium"
    return "low"


def _operations_from_revised_text(before_text: str, after_text: str) -> list[dict[str, Any]]:
    before_paragraphs = _paragraphs(before_text)
    after_paragraphs = _paragraphs(after_text)
    operations: list[dict[str, Any]] = []
    max_count = max(len(before_paragraphs), len(after_paragraphs))
    for index in range(max_count):
        before = before_paragraphs[index] if index < len(before_paragraphs) else ""
        after = after_paragraphs[index] if index < len(after_paragraphs) else ""
        if before == after:
            continue
        if before and after:
            kind = "replace_text"
        elif after:
            kind = "append_text"
        else:
            kind = "delete_text"
        operations.append(
            {
                "op_id": f"op-{len(operations) + 1}",
                "kind": kind,
                "target": f"paragraph:{index + 1}" if before else "document:end",
                "paragraph_index": index + 1,
                "before": before,
                "after": after if kind != "delete_text" else "",
                "instruction": "model-provided revised_text paragraph diff",
                "rationale": "derived from revised_text because explicit operations were not provided",
                "status": "proposed",
                "risk": _paragraph_risk(before, after),
            }
        )
    return operations


def _fallback_revision_operations(before_text: str, *, review: dict[str, Any], revision: dict[str, Any]) -> list[dict[str, Any]]:
    paragraphs = _paragraphs(before_text)
    steps = _revision_steps(revision)
    issues = _review_issues(review)
    instruction = _revision_summary(revision)
    if not paragraphs:
        return [
            {
                "op_id": "op-1",
                "kind": "append_text",
                "target": "document:end",
                "paragraph_index": 1,
                "before": "",
                "after": _fallback_revision_note(steps, issues),
                "instruction": instruction,
                "rationale": "empty draft requires explicit revision execution note",
                "status": "proposed",
                "risk": "low",
            }
        ]
    candidate_indexes = _candidate_paragraphs(paragraphs)[: max(1, min(3, len(paragraphs)))]
    operations: list[dict[str, Any]] = []
    for op_index, paragraph_index in enumerate(candidate_indexes, start=1):
        before = paragraphs[paragraph_index]
        after = _paragraph_revision_executor_text(before, step=steps[op_index - 1] if op_index <= len(steps) else instruction, issues=issues)
        operations.append(
            {
                "op_id": f"op-{op_index}",
                "kind": "replace_text",
                "target": f"paragraph:{paragraph_index + 1}",
                "paragraph_index": paragraph_index + 1,
                "before": before,
                "after": after,
                "instruction": instruction,
                "rationale": "local fallback applies revision plan at paragraph level while preserving original draft text",
                "status": "proposed",
                "risk": _paragraph_risk(before, after),
            }
        )
    return operations


def _paragraph_revision_executor_text(paragraph: str, *, step: str, issues: list[str]) -> str:
    note_parts = [step.strip()]
    if issues:
        note_parts.append(f"addresses: {issues[0]}")
    note = "；".join(part for part in note_parts if part)
    if not note:
        note = "tighten causal chain and preserve chapter hook"
    suffix = f"【修订执行：{note}】"
    if suffix in paragraph:
        return paragraph
    return f"{paragraph.rstrip()} {suffix}"


def _fallback_revision_note(steps: list[str], issues: list[str]) -> str:
    lines = ["\n\n【修订执行】"]
    for index, step in enumerate(steps or ["apply revision plan"], start=1):
        lines.append(f"{index}. {step}")
    if issues:
        lines.append("【对应审稿问题】")
        for issue in issues[:5]:
            lines.append(f"- {issue}")
    return "\n".join(lines)


def _rollback_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rollback: list[dict[str, Any]] = []
    for index, operation in enumerate(reversed(operations), start=1):
        kind = str(operation.get("kind", "replace_text"))
        before = str(operation.get("before", ""))
        after = str(operation.get("after", ""))
        if kind == "replace_text":
            rollback_kind = "replace_text"
            rollback_before = after
            rollback_after = before
        elif kind == "append_text":
            rollback_kind = "delete_text"
            rollback_before = after
            rollback_after = ""
        elif kind == "prepend_text":
            rollback_kind = "delete_text"
            rollback_before = after
            rollback_after = ""
        elif kind == "delete_text":
            rollback_kind = "append_text"
            rollback_before = ""
            rollback_after = before
        else:
            rollback_kind = "noop"
            rollback_before = ""
            rollback_after = ""
        rollback.append(
            {
                "op_id": f"rollback-op-{index}",
                "kind": rollback_kind,
                "target": operation.get("target", "document"),
                "paragraph_index": operation.get("paragraph_index", index),
                "before": rollback_before,
                "after": rollback_after,
                "instruction": f"rollback {operation.get('op_id', '')}",
                "rationale": "inverse operation for model revision executor rollback",
                "status": "proposed",
                "risk": operation.get("risk", "low"),
            }
        )
    return rollback


def _paragraph_diffs(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        before = str(operation.get("before", ""))
        after = str(operation.get("after", ""))
        rows.append(
            {
                "op_id": str(operation.get("op_id", "")),
                "paragraph_index": operation.get("paragraph_index", 0),
                "target": str(operation.get("target", "")),
                "kind": str(operation.get("kind", "")),
                "before": before,
                "after": after,
                "char_delta": len(after) - len(before),
                "risk": str(operation.get("risk", "low")),
                "rationale": str(operation.get("rationale", "")),
            }
        )
    return rows


def _revision_summary(revision: dict[str, Any]) -> str:
    content = revision.get("content", {}) if isinstance(revision.get("content", {}), dict) else {}
    steps = _revision_steps(revision)
    if steps:
        return "；".join(steps[:4])
    return str(content.get("summary") or "execute revision plan with paragraph-level patch operations")


def _revision_steps(revision: dict[str, Any]) -> list[str]:
    content = revision.get("content", {}) if isinstance(revision.get("content", {}), dict) else {}
    return [str(item).strip() for item in content.get("steps", []) if str(item).strip()] if isinstance(content.get("steps", []), list) else []


def _review_issues(review: dict[str, Any]) -> list[str]:
    issues = review.get("issues", []) if isinstance(review.get("issues", []), list) else []
    rows: list[str] = []
    for issue in issues:
        if isinstance(issue, dict):
            rows.append(str(issue.get("message") or issue.get("dimension") or "").strip())
        elif str(issue).strip():
            rows.append(str(issue).strip())
    return [row for row in rows if row]


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _selected_operations(
    operations: Any,
    *,
    operation_ids: list[str],
    operation_indexes: list[int],
) -> list[dict[str, Any]]:
    if not isinstance(operations, list):
        raise ValueError("editor_patch operations must be a list")
    normalized = [operation for operation in operations if isinstance(operation, dict)]
    selected_ids = {str(value) for value in operation_ids if str(value).strip()}
    selected_indexes = {int(value) for value in operation_indexes if int(value) > 0}
    if not selected_ids and not selected_indexes:
        return normalized
    selected: list[dict[str, Any]] = []
    for index, operation in enumerate(normalized, start=1):
        if str(operation.get("op_id", "")) in selected_ids or index in selected_indexes:
            selected.append(operation)
    if not selected:
        raise ValueError("no editor patch operations matched operation_ids or operation_indexes")
    return selected


def _apply_operations(text: str, operations: Any) -> str:
    if not isinstance(operations, list):
        raise ValueError("editor_patch operations must be a list")
    result = text
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        kind = str(operation.get("kind", "replace_text"))
        before = str(operation.get("before", ""))
        after = str(operation.get("after", ""))
        if kind == "replace_text":
            if before and before in result:
                result = result.replace(before, after, 1)
            elif before:
                raise ValueError(f"replace_text target not found for {operation.get('op_id', '')}")
        elif kind == "append_text":
            result = result + after
        elif kind == "prepend_text":
            result = after + result
        elif kind == "delete_text":
            if before and before in result:
                result = result.replace(before, "", 1)
            elif before:
                raise ValueError(f"delete_text target not found for {operation.get('op_id', '')}")
        elif kind == "noop":
            continue
        else:
            raise ValueError(f"unsupported editor operation kind: {kind}")
    return result


def _diff_summary(before: str, after: str, diff_lines: list[str]) -> dict[str, Any]:
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    changed_paragraphs = sum(1 for before_item, after_item in zip(_paragraphs(before), _paragraphs(after), strict=False) if before_item != after_item)
    changed_paragraphs += abs(len(_paragraphs(before)) - len(_paragraphs(after)))
    return {
        "before_chars": len(before),
        "after_chars": len(after),
        "char_delta": len(after) - len(before),
        "added_lines": added,
        "removed_lines": removed,
        "changed_lines": added + removed,
        "changed_paragraphs": changed_paragraphs,
    }


def _operation_risks(operations: list[dict[str, Any]]) -> list[str]:
    risks = sorted({str(operation.get("risk", "low")) for operation in operations if str(operation.get("risk", "")).strip()})
    if any(operation.get("kind") in {"delete_text", "replace_text"} and len(str(operation.get("before", ""))) > 2000 for operation in operations):
        risks.append("large_rewrite")
    return risks


def _link_revision_executor_outputs(
    storage: LocalStorage,
    forward_patch_path: str,
    rollback_patch_path: str,
    final_draft_path: str,
    diff_path: str,
    version_path: str,
    generation_path: str,
) -> None:
    links = {
        "forward_patch_path": forward_patch_path,
        "rollback_patch_path": rollback_patch_path,
        "final_draft_path": final_draft_path,
        "diff_report_path": diff_path,
        "draft_version_path": version_path,
        "generation_run_path": generation_path,
    }
    for asset_path in [forward_patch_path, rollback_patch_path, final_draft_path, diff_path]:
        path = resolve_path(storage.root, asset_path)
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata["revision_executor_outputs"] = links
        if data.get("type") in {"editor_patch", "draft_diff_report"}:
            content["revision_executor_outputs"] = links
        if data.get("type") == "draft_chapter":
            execution = content.get("revision_execution", {}) if isinstance(content.get("revision_execution", {}), dict) else {}
            execution.update(links)
            execution["revision_executor_outputs"] = links
            content["revision_execution"] = execution
        data["metadata"] = metadata
        data["content"] = content
        data["updated_at"] = utc_now()
        storage.write_json(path, data)


def _write(storage: LocalStorage, asset: EditorPatch | DraftDiffReport) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
