from __future__ import annotations

import shutil
import os
from pathlib import Path

from novel_forge.core.constants import DATA_DIRS, DOC_FILES, SKILL_NAMES, SKILL_REQUIRED_SECTIONS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.model_adapters import ModelAdapter
from novel_forge.modules.chapter_plan.service import generate_chapter_plan as generate_chapter_plan_service
from novel_forge.modules.characters.service import generate_characters as generate_characters_service
from novel_forge.modules.cleaning.service import clean as clean_service
from novel_forge.modules.common import resolve_path as resolve_module_path
from novel_forge.modules.decomposition.service import decompose as decompose_service
from novel_forge.modules.drafting.service import draft as draft_service
from novel_forge.modules.feedback.service import analyze_feedback as analyze_feedback_service
from novel_forge.modules.feedback.service import import_feedback as import_feedback_service
from novel_forge.modules.handoff.service import create_deconstruction_handoff as create_deconstruction_handoff_service
from novel_forge.modules.handoff.service import create_knowledge_handoff as create_knowledge_handoff_service
from novel_forge.modules.ingestion.service import ingest as ingest_service
from novel_forge.modules.ingestion.service import ingest_many as ingest_many_service
from novel_forge.modules.knowledge.service import extract_knowledge as extract_knowledge_service
from novel_forge.modules.materials.service import build_materials as build_materials_service
from novel_forge.modules.outline.service import generate_outline as generate_outline_service
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.review.service import compare_reviews as compare_reviews_service
from novel_forge.modules.review.service import review as review_service
from novel_forge.modules.revision.service import revise as revise_service
from novel_forge.modules.training.service import generate_training_exercise as generate_training_exercise_service
from novel_forge.modules.topics.service import develop_topic as develop_topic_service
from novel_forge.modules.topics.service import generate_topic as generate_topic_service
from novel_forge.modules.workspace.service import init_workspace as init_workspace_service
from novel_forge.modules.workspace.service import update_workspace as update_workspace_service
from novel_forge.modules.workspace.service import workspace_status as workspace_status_service
from novel_forge.modules.worldbuilding.service import generate_world as generate_world_service
from novel_forge.schemas import WorkflowRun, validate_common_fields
from novel_forge.storage.local import LocalStorage
from novel_forge.workflows.industrial import industrial_status as industrial_status_service
from novel_forge.workflows.industrial import minio_sync as minio_sync_service
from novel_forge.workflows.industrial import neo4j_status as neo4j_status_service
from novel_forge.workflows.industrial import postgres_init as postgres_init_service
from novel_forge.workflows.industrial import postgres_sync as postgres_sync_service
from novel_forge.workflows.industrial import qdrant_index as qdrant_index_service
from novel_forge.workflows.industrial import qdrant_search as qdrant_search_service
from novel_forge.storage.asset_manifest import rebuild_asset_manifest as rebuild_asset_manifest_service
from novel_forge.storage.asset_manifest import manifest_counts as manifest_counts_service
from novel_forge.storage.retrieval_index import build_retrieval_index as build_retrieval_index_service
from novel_forge.storage.search import search_assets as search_assets_service
from novel_forge.storage.vector_index import build_vector_index as build_vector_index_service
from novel_forge.storage.vector_index import vector_search_assets as vector_search_assets_service
from novel_forge.workflows.status import (
    build_recovery_instruction,
    build_run_log,
    execute_task,
    write_recovery_note,
)


def resolve_path(root: Path, path: str | Path) -> Path:
    return resolve_module_path(root, path)


def ensure_project(root: str | Path = ".") -> LocalStorage:
    storage = LocalStorage(root)
    storage.ensure_layout()
    ensure_sample_inputs(storage.root)
    return storage


def ensure_sample_inputs(root: Path) -> None:
    sample_dir = root / "examples" / "sample_inputs"
    sample_dir.mkdir(parents=True, exist_ok=True)
    novel_path = sample_dir / "sample_novel.txt"
    if not novel_path.exists():
        novel_path.write_text(
            "第一章 雨夜的回声\n"
            "城市边缘的旧钟楼在午夜响起，年轻调查员发现每一次钟声都对应一条被掩盖的线索。\n"
            "他不能复制任何旧案，只能从结构中识别节奏：疑问、阻碍、选择、代价、钩子。\n",
            encoding="utf-8",
        )
    feedback_path = sample_dir / "sample_feedback.csv"
    if not feedback_path.exists():
        feedback_path.write_text(
            "reader,chapter,rating,comment\n"
            "r1,1,4,hook is clear but character motive needs more pressure\n"
            "r2,1,5,strong suspense rhythm\n",
            encoding="utf-8",
        )


def ingest(
    root: str | Path,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
) -> Path:
    storage = ensure_project(root)
    return ingest_service(
        storage,
        input_path,
        title,
        rights_authorization,
        license_name,
        copyright_note,
        source_url,
        allow_downstream_generation,
    )


def ingest_many(
    root: str | Path,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
) -> list[Path]:
    storage = ensure_project(root)
    return ingest_many_service(
        storage,
        input_path,
        title,
        rights_authorization,
        license_name,
        copyright_note,
        source_url,
        allow_downstream_generation,
    )


def clean(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return clean_service(storage, input_path)


def decompose(root: str | Path, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    return decompose_service(storage, input_path, model)


def extract_knowledge(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return extract_knowledge_service(storage, input_path)


def build_materials(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return build_materials_service(storage, input_path)


def generate_topic(root: str | Path, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    return generate_topic_service(storage, input_path, model)


def develop_topic(root: str | Path, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    return develop_topic_service(storage, input_path, model)


def generate_training_exercise(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return generate_training_exercise_service(storage, input_path)


def generate_world(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return generate_world_service(storage, input_path)


def generate_characters(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return generate_characters_service(storage, input_path)


def generate_outline(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return generate_outline_service(storage, input_path)


def generate_chapter_plan(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return generate_chapter_plan_service(storage, input_path)


def draft(root: str | Path, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    return draft_service(storage, input_path, model)


def review(root: str | Path, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    return review_service(storage, input_path, model)


def compare_reviews(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return compare_reviews_service(storage, input_path)


def revise(root: str | Path, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    return revise_service(storage, input_path, model)


def import_feedback(root: str | Path, input_path: str) -> Path:
    storage = ensure_project(root)
    return import_feedback_service(storage, input_path)


def analyze_feedback(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    return analyze_feedback_service(storage, input_path)


def claude_deconstruct(
    root: str | Path,
    input_path: str | None = None,
    genre: str = "",
    target_reader: str = "",
    purpose: str = "",
) -> Path:
    storage = ensure_project(root)
    return create_deconstruction_handoff_service(storage, input_path, genre, target_reader, purpose)


def claude_knowledge(
    root: str | Path,
    input_path: str | None = None,
    discipline: str = "",
    credibility: str = "",
    scope: str = "",
    project_context: str = "",
) -> Path:
    storage = ensure_project(root)
    return create_knowledge_handoff_service(storage, input_path, discipline, credibility, scope, project_context)


def search_assets(
    root: str | Path,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    keyword: str | None = None,
    limit: int = 50,
    use_index: bool = True,
    rebuild_index: bool = False,
    rank: str = "path",
) -> list[dict]:
    storage = ensure_project(root)
    return search_assets_service(
        storage,
        category=category,
        asset_type=asset_type,
        tags=tags,
        keyword=keyword,
        limit=limit,
        use_index=use_index,
        rebuild_index=rebuild_index,
        rank=rank,
    )


def build_retrieval_index(root: str | Path) -> Path:
    storage = ensure_project(root)
    return build_retrieval_index_service(storage)


def build_asset_manifest(root: str | Path) -> Path:
    storage = ensure_project(root)
    return rebuild_asset_manifest_service(storage)


def asset_manifest_status(root: str | Path) -> dict[str, int]:
    storage = ensure_project(root)
    return manifest_counts_service(storage)


def build_vector_index(root: str | Path) -> Path:
    storage = ensure_project(root)
    return build_vector_index_service(storage)


def vector_search_assets(
    root: str | Path,
    query: str,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
    rebuild_index: bool = False,
) -> list[dict]:
    storage = ensure_project(root)
    return vector_search_assets_service(
        storage,
        query=query,
        category=category,
        asset_type=asset_type,
        tags=tags,
        limit=limit,
        force_rebuild=rebuild_index,
    )


def industrial_status(root: str | Path) -> dict:
    return industrial_status_service(root)


def postgres_init(root: str | Path) -> dict:
    return postgres_init_service(root)


def postgres_sync(root: str | Path) -> dict:
    return postgres_sync_service(root)


def qdrant_index(
    root: str | Path,
    recreate_collection: bool = False,
    batch_size: int = 32,
    resume: bool = True,
    force_reembed: bool = False,
) -> dict:
    return qdrant_index_service(
        root,
        recreate_collection=recreate_collection,
        batch_size=batch_size,
        resume=resume,
        force_reembed=force_reembed,
    )


def qdrant_search(
    root: str | Path,
    query: str,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 50,
) -> list[dict]:
    return qdrant_search_service(
        root,
        query=query,
        category=category,
        asset_type=asset_type,
        tags=tags,
        project_id=project_id,
        workspace_path=workspace_path,
        limit=limit,
    )


def minio_sync(root: str | Path, categories: list[str] | None = None) -> dict:
    return minio_sync_service(root, categories=categories)


def neo4j_status(root: str | Path) -> dict:
    return neo4j_status_service(root)


def init_workspace(
    root: str | Path,
    title: str = "Sample Novel Workspace",
    series_title: str | None = None,
    book_number: int | None = None,
) -> Path:
    storage = ensure_project(root)
    return init_workspace_service(storage, title, series_title, book_number)


def update_workspace(
    root: str | Path,
    input_path: str | None = None,
    workspace_path: str | None = None,
    chapter: int | None = None,
    status: str = "drafted",
) -> Path:
    storage = ensure_project(root)
    return update_workspace_service(storage, input_path, workspace_path, chapter, status)


def workspace_status(root: str | Path, workspace_path: str | None = None) -> dict:
    storage = ensure_project(root)
    return workspace_status_service(storage, workspace_path)


def run_pipeline(root: str | Path, sample: bool = False) -> Path:
    storage = ensure_project(root)
    sample_path = storage.root / "examples" / "sample_inputs" / "sample_novel.txt"
    feedback_path = storage.root / "examples" / "sample_inputs" / "sample_feedback.csv"
    cleaned_previous_sample_paths = clean_previous_sample_run(storage) if sample else []
    title = "sample pipeline run" if sample else "pipeline run"
    run_id = make_id("workflow_run", title)
    outputs: list[Path] = []
    status_paths: list[Path] = []

    def run_step(step: str, input_paths: list[str | Path], action) -> Path:
        output, _ = execute_task(storage, run_id, step, input_paths, action, status_collector=status_paths)
        return output

    try:
        outputs.append(
            run_step(
                "ingest",
                [sample_path],
                lambda: ingest(
                    storage.root,
                    str(sample_path),
                    rights_authorization="test_fixture",
                    license_name="project-sample",
                    copyright_note="self-authored fixture for workflow testing",
                    allow_downstream_generation=True,
                ),
            )
        )
        outputs.append(run_step("clean", [outputs[-1]], lambda: clean(storage.root, str(outputs[-1]))))
        outputs.append(run_step("decompose", [outputs[-1]], lambda: decompose(storage.root, str(outputs[-1]))))
        outputs.append(
            run_step("extract-knowledge", [outputs[-1]], lambda: extract_knowledge(storage.root, str(outputs[-1])))
        )
        outputs.append(run_step("build-materials", [outputs[-1]], lambda: build_materials(storage.root, str(outputs[-1]))))
        outputs.append(run_step("generate-topic", [outputs[-1]], lambda: generate_topic(storage.root, str(outputs[-1]))))
        outputs.append(run_step("generate-world", [outputs[-1]], lambda: generate_world(storage.root, str(outputs[-1]))))
        outputs.append(
            run_step("generate-characters", [outputs[-1]], lambda: generate_characters(storage.root, str(outputs[-1])))
        )
        outputs.append(run_step("generate-outline", [outputs[-1]], lambda: generate_outline(storage.root, str(outputs[-1]))))
        outputs.append(
            run_step(
                "generate-chapter-plan",
                [outputs[-1]],
                lambda: generate_chapter_plan(storage.root, str(outputs[-1])),
            )
        )
        outputs.append(run_step("draft", [outputs[-1]], lambda: draft(storage.root, str(outputs[-1]))))
        draft_path = outputs[-1]
        outputs.append(run_step("init-workspace", [draft_path], lambda: init_workspace(storage.root, "Sample Novel Workspace")))
        workspace_path = outputs[-1]
        outputs.append(
            run_step(
                "update-workspace-draft",
                [draft_path, workspace_path],
                lambda: update_workspace(storage.root, str(draft_path), str(workspace_path), status="drafted"),
            )
        )
        workspace_path = outputs[-1]
        outputs.append(run_step("review", [draft_path], lambda: review(storage.root, str(draft_path))))
        review_path = outputs[-1]
        outputs.extend(_review_derived_outputs(storage, review_path))
        outputs.append(
            run_step(
                "update-workspace-review",
                [review_path, workspace_path],
                lambda: update_workspace(storage.root, str(review_path), str(workspace_path), status="reviewed"),
            )
        )
        outputs.append(run_step("revise", [review_path], lambda: revise(storage.root, str(review_path))))
        outputs.append(run_step("import-feedback", [feedback_path], lambda: import_feedback(storage.root, str(feedback_path))))
        outputs.append(run_step("analyze-feedback", [outputs[-1]], lambda: analyze_feedback(storage.root, str(outputs[-1]))))
        _attach_run_assets_to_workspace(storage, workspace_path, [*outputs, *status_paths])
        binding_outputs = _workspace_binding_outputs(storage, workspace_path)
        if binding_outputs:
            outputs.extend(path for path in binding_outputs if path not in outputs)
            _attach_run_assets_to_workspace(storage, workspace_path, binding_outputs)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        run_log = build_run_log(storage, status_paths)
        recovery_instruction = build_recovery_instruction(run_log, error_message)
        recovery_path = write_recovery_note(storage, run_id, run_log, recovery_instruction)
        run = WorkflowRun(
            id=run_id,
            title=title,
            source=str(sample_path),
            tags=["pipeline", "sample" if sample else "manual", "failed"],
            content={
                "outputs": _relative_paths(storage, outputs),
                "task_statuses": _relative_paths(storage, status_paths),
                "run_log": run_log,
                "status": "failed",
                "error_message": error_message,
                "recovery_instruction": recovery_instruction,
                "recovery_path": str(recovery_path.relative_to(storage.root)),
                "cleaned_previous_sample_paths": cleaned_previous_sample_paths,
            },
            metadata={"failed_at": utc_now(), "sample": sample},
            references=[path.name for path in outputs + status_paths + [recovery_path]],
        )
        storage.write_asset("runs", run)
        raise

    run_log = build_run_log(storage, status_paths)
    run = WorkflowRun(
        id=run_id,
        title=title,
        source=str(sample_path),
        tags=["pipeline", "sample" if sample else "manual"],
        content={
            "outputs": _relative_paths(storage, outputs),
            "task_statuses": _relative_paths(storage, status_paths),
            "run_log": run_log,
            "status": "completed",
            "error_message": "",
            "recovery_instruction": "",
            "recovery_path": "",
            "cleaned_previous_sample_paths": cleaned_previous_sample_paths,
        },
        metadata={"completed_at": utc_now(), "sample": sample},
        references=[path.name for path in outputs + status_paths],
    )
    run_path = storage.write_asset("runs", run)
    _attach_run_assets_to_workspace(storage, workspace_path, [run_path])
    final_asset = outputs[-1]
    summary = {
        "run_id": run.id,
        "status": "completed",
        "outputs": _relative_paths(storage, outputs),
        "task_statuses": _relative_paths(storage, status_paths),
        "run_log": run_log,
        "run_record": str(run_path.relative_to(storage.root)),
        "copied_final_output": f"examples/sample_outputs/{final_asset.name}",
        "cleaned_previous_sample_paths": cleaned_previous_sample_paths,
    }
    storage.write_json("examples/sample_outputs/pipeline-summary.json", summary)
    shutil.copyfile(final_asset, storage.root / "examples" / "sample_outputs" / final_asset.name)
    return run_path


def _relative_paths(storage: LocalStorage, paths: list[Path]) -> list[str]:
    return [str(path.relative_to(storage.root)) if path.is_absolute() else str(path) for path in paths]


def _review_derived_outputs(storage: LocalStorage, review_path: Path) -> list[Path]:
    try:
        data = storage.read_json(review_path)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    outputs: list[Path] = []
    for key in [
        "quality_score_report_path",
        "style_review_report_path",
        "originality_report_path",
        "chapter_audit_report_path",
    ]:
        value = metadata.get(key)
        if isinstance(value, str) and value:
            path = resolve_path(storage.root, value)
            if path.exists():
                outputs.append(path)
    return outputs


def _workspace_binding_outputs(storage: LocalStorage, workspace_path: Path | str) -> list[Path]:
    try:
        data = storage.read_json(resolve_path(storage.root, workspace_path))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    config = content.get("project_config", {}) if isinstance(content.get("project_config", {}), dict) else {}
    outputs: list[Path] = []
    for key in [
        "platform_profile_path",
        "genre_market_profile_path",
        "quality_standard_profile_path",
        "style_profile_path",
        "style_blend_preset_path",
        "continuity_bible_path",
    ]:
        value = config.get(key)
        if isinstance(value, str) and value:
            path = resolve_path(storage.root, value)
            if path.exists() and path.is_file():
                outputs.append(path)
    return outputs


def clean_previous_sample_run(storage: LocalStorage) -> list[str]:
    summary_path = storage.root / "examples" / "sample_outputs" / "pipeline-summary.json"
    if not summary_path.exists():
        return []
    try:
        summary = storage.read_json(summary_path)
    except Exception:
        return []
    if not isinstance(summary, dict):
        return []

    candidates: list[str] = []
    for key in ["outputs", "task_statuses"]:
        values = summary.get(key, [])
        if isinstance(values, list):
            candidates.extend(str(value) for value in values)
    for key in ["run_record", "copied_final_output", "recovery_path"]:
        value = summary.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    outputs = summary.get("outputs", [])
    if isinstance(outputs, list) and outputs:
        candidates.append(f"examples/sample_outputs/{Path(str(outputs[-1])).name}")
    candidates.append(str(summary_path.relative_to(storage.root)))

    removed: list[str] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = resolve_path(storage.root, candidate)
        if path in seen:
            continue
        seen.add(path)
        if not _is_safe_sample_cleanup_path(storage, path):
            continue
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(storage.root)))
    return removed


def _is_safe_sample_cleanup_path(storage: LocalStorage, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(storage.root)
    except ValueError:
        return False
    if ".." in relative.parts:
        return False
    return relative.parts[:1] == ("data",) or relative.parts[:2] == ("examples", "sample_outputs")


def validate_project(root: str | Path = ".") -> tuple[bool, list[str]]:
    storage = LocalStorage(root)
    contract_root = _contract_root(storage.root)
    errors: list[str] = []
    for category in DATA_DIRS:
        if not (storage.data_root / category).exists():
            errors.append(f"missing data directory: data/{category}")
    for doc in DOC_FILES:
        if not (contract_root / doc).exists():
            errors.append(f"missing documentation file: {doc}")
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception as exc:  # pragma: no cover - defensive reporting
                errors.append(f"invalid JSON {path}: {exc}")
                continue
            if isinstance(data, dict):
                errors.extend(f"{path.relative_to(storage.root)}: {error}" for error in validate_common_fields(data))
            else:
                errors.append(f"asset JSON must be object: {path.relative_to(storage.root)}")
    errors.extend(validate_skills(contract_root))
    if os.environ.get("NOVEL_FORGE_SKIP_PROJECT_SCOPE_VALIDATE", "").strip().lower() not in {"1", "true", "yes"}:
        errors.extend(_validate_project_scope(storage))
    return not errors, errors


def _contract_root(runtime_root: Path) -> Path:
    if (runtime_root / "skills").is_dir() and all((runtime_root / doc).exists() for doc in DOC_FILES):
        return runtime_root
    return Path(__file__).resolve().parents[3]


def _validate_project_scope(storage: LocalStorage) -> list[str]:
    if not storage.list_json("workspaces"):
        return []
    try:
        from novel_forge.api.product import project_scope_audit

        audit = project_scope_audit(storage, repair=False)
    except Exception as exc:
        return [f"project-scope audit failed: {exc}"]
    errors = []
    for issue in audit.get("issues", []):
        if not isinstance(issue, dict):
            continue
        severity = issue.get("severity", "error")
        if severity in {"error", "warning"}:
            errors.append(
                "project-scope "
                f"{issue.get('kind', 'issue')}: {issue.get('path', '')}: {issue.get('message', '')}"
            )
    return errors


def _attach_run_assets_to_workspace(storage: LocalStorage, workspace_path: Path, asset_paths: list[Path]) -> None:
    try:
        workspace = storage.read_json(workspace_path)
    except Exception:
        return
    if not isinstance(workspace, dict):
        return
    content = workspace.get("content", {}) if isinstance(workspace.get("content", {}), dict) else {}
    project_id = str(content.get("project_id") or workspace.get("id") or "")
    workspace_id = str(workspace.get("id") or "")
    workspace_ref = str(workspace_path.relative_to(storage.root))
    for path in asset_paths:
        try:
            resolved = Path(path).resolve()
            resolved.relative_to(storage.root)
            data = storage.read_json(resolved)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") == "project_workspace_state":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if not metadata.get("project_id"):
            metadata["project_id"] = project_id
        if not metadata.get("workspace_id"):
            metadata["workspace_id"] = workspace_id
        if not metadata.get("workspace_path"):
            metadata["workspace_path"] = workspace_ref
        if not metadata.get("project_asset_role"):
            metadata["project_asset_role"] = str(data.get("type", ""))
        if not metadata.get("project_attached_at"):
            metadata["project_attached_at"] = utc_now()
        data["metadata"] = metadata
        references = [str(item) for item in data.get("references", []) if str(item).strip()]
        for ref in [project_id, workspace_id]:
            if ref and ref not in references:
                references.append(ref)
        data["references"] = filter_project_safe_references(storage, project_id, references)
        data["updated_at"] = utc_now()
        storage.write_json(resolved, data)


def validate_skills(root: Path) -> list[str]:
    errors: list[str] = []
    skills_root = root / "skills"
    if not skills_root.is_dir():
        return ["missing skills directory: skills/"]

    for skill_name in SKILL_NAMES:
        path = skills_root / skill_name / "SKILL.md"
        relative = path.relative_to(root)
        if not path.exists():
            errors.append(f"missing skill file: {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read skill file {relative}: {exc}")
            continue

        lines = text.splitlines()
        if len(lines) < 4 or lines[0].strip() != "---":
            errors.append(f"{relative}: missing YAML frontmatter start")
            continue
        try:
            frontmatter_end = lines[1:].index("---") + 1
        except ValueError:
            errors.append(f"{relative}: missing YAML frontmatter end")
            continue

        frontmatter = "\n".join(lines[1:frontmatter_end])
        if f"name: {skill_name}" not in frontmatter:
            errors.append(f"{relative}: frontmatter missing name: {skill_name}")
        if "description:" not in frontmatter:
            errors.append(f"{relative}: frontmatter missing description")
        for section in SKILL_REQUIRED_SECTIONS:
            if section not in text:
                errors.append(f"{relative}: missing required section: {section}")

    return errors
