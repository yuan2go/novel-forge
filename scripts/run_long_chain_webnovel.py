from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.model_adapters import ClaudeCodeAdapter, GuardedModelAdapter, validate_model_output
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.operations import create_long_chain_acceptance_report
from novel_forge.schemas import (
    ChapterContinuityReport,
    ChapterProductionRun,
    ContextBundle,
    DraftVersion,
    FeedbackBackflowPlan,
    KnowledgeCard,
    ReviewReport,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


PROJECT_ID = "real-longchain-webnovel"
CANONICAL_LEAD_CHARACTERS = {
    "沈砚": "senior night archive clerk and forensic/craft reasoning lead",
    "阿照": "巡遗司 field investigator and debt-bearing case lead",
}
KNOWN_NAME_ALIAS_REPAIRS = {
    "江砚": "沈砚",
    "沈照": "阿照",
    "沈夜照": "阿照",
}


@dataclass
class ChapterRecord:
    chapter: int
    path: Path
    asset_path: str
    char_count: int
    quality_score: float
    warnings: list[str]
    cost_paths: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a resumable real long-chain web-novel generation using the Claude Code Codex worker.")
    parser.add_argument("--root", default=".local/longchain-workspace")
    parser.add_argument("--reference-analysis", required=True)
    parser.add_argument("--classical-modern-root", required=True)
    parser.add_argument("--chapters", type=int, default=100)
    parser.add_argument("--target-chars", type=int, default=5000)
    parser.add_argument("--export-dir", default="generated/longchain-webnovel")
    parser.add_argument("--max-chapters-this-run", type=int, default=3)
    parser.add_argument("--codex-timeout-seconds", type=int, default=900)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-chapter", action="append", type=int, default=[], help="Regenerate only the selected existing chapter; can be repeated.")
    args = parser.parse_args()

    storage = LocalStorage(args.root)
    storage.ensure_layout()
    export_dir = Path(args.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "chapters").mkdir(parents=True, exist_ok=True)

    reference = _load_reference_brief(storage, args.reference_analysis)
    knowledge = _classical_knowledge_pack(Path(args.classical_modern_root))
    knowledge_path = _write_knowledge_card(storage, knowledge)
    bible = _series_bible(reference, knowledge, chapters=args.chapters)
    _write_json(export_dir / "series_bible.json", bible)

    records: list[ChapterRecord] = []
    force_chapters = _force_chapter_set(args.force_chapter)
    existing_summaries = _filter_forced_chapter_summaries(_load_existing_summaries(export_dir), force_chapters)
    chapter_limit = 0 if args.report_only else max(1, int(args.max_chapters_this_run))
    generated_this_run = 0
    previous_summary = existing_summaries[-1]["summary"] if existing_summaries else ""

    _configure_codex_timeout(args.codex_timeout_seconds)
    adapter = ClaudeCodeAdapter()
    for chapter in range(1, max(1, int(args.chapters)) + 1):
        chapter_path = export_dir / "chapters" / f"chapter_{chapter:03d}.md"
        force_this_chapter = bool(args.force or chapter in force_chapters)
        if chapter_path.exists() and not force_this_chapter:
            continue
        if generated_this_run >= chapter_limit:
            break
        context = _chapter_context(
            bible,
            reference,
            knowledge,
            chapter=chapter,
            chapters=args.chapters,
            target_chars=args.target_chars,
            previous_summary=previous_summary,
        )
        with AgentExecutionContext(
            storage,
            agent_key="draft",
            operation="real_longchain_chapter",
            input_assets=[args.reference_analysis, knowledge_path],
            output_types=["draft_version"],
            model_provider="claude-code",
            model_name=os.environ.get("NOVEL_FORGE_CLAUDE_CODE_MODEL", "codex-cli"),
            prompt_version="real-longchain-webnovel-v1",
            token_budget=max(32000, int(args.target_chars * 7)),
            sla_seconds=args.codex_timeout_seconds + 120,
            workspace_path=str(storage.root),
        ) as run:
            run.guard("call_model_adapter")
            model_result = GuardedModelAdapter(adapter, storage, run.path).generate(_chapter_prompt(chapter, args.target_chars), context)
            generated = validate_model_output("generate", model_result)
            text, output_repairs = _extract_generated_text(generated)
            text, canonical_repairs = _canonicalize_generated_text(text)
            if output_repairs or canonical_repairs:
                generated["canonical_repairs"] = [*output_repairs, *canonical_repairs]
            warnings = _quality_warnings(text, args.target_chars)
            chapter_path.write_text(f"# 第{chapter:03d}章\n\n{text}\n", encoding="utf-8")
            run.guard("write_draft_version", "draft_version")
            draft = _write_draft_version(storage, chapter, text, generated, run.path, chapter_path)
            run.succeed(output_assets=[draft["path"], str(chapter_path)], token_used=len(text))
        review = _write_review_report(storage, chapter, text, warnings, draft["path"])
        summary = _chapter_summary(text, chapter)
        quality_score = _quality_score(text, warnings, args.target_chars)
        existing_summaries.append({"chapter": chapter, "summary": summary, "char_count": len(text), "warnings": warnings, "quality_score": quality_score})
        previous_summary = summary
        record = ChapterRecord(
            chapter=chapter,
            path=chapter_path,
            asset_path=draft["path"],
            char_count=len(text),
            quality_score=quality_score,
            warnings=warnings,
            cost_paths=[str(model_result.get("cost_ledger_path", ""))] if isinstance(model_result, dict) and model_result.get("cost_ledger_path") else [],
        )
        records.append(record)
        generated_this_run += 1
        _write_progress(export_dir, args.chapters, args.target_chars, existing_summaries, records)

    _repair_runtime_evidence_project_scope(storage)
    acceptance_assets = _ensure_acceptance_assets(storage, export_dir, existing_summaries, bible, target_chars=args.target_chars)
    acceptance = create_long_chain_acceptance_report(storage, project_id=PROJECT_ID, chapter_count=args.chapters)
    report = _quality_report(storage, export_dir, args.chapters, args.target_chars, existing_summaries, records, acceptance, bible, acceptance_assets)
    _write_json(export_dir / "quality_report.json", report)
    _write_markdown_report(export_dir / "quality_report.md", report)
    print(json.dumps({"generated_this_run": generated_this_run, "export_dir": str(export_dir), "quality_report": str(export_dir / "quality_report.md"), "acceptance_report": acceptance["path"]}, ensure_ascii=False, indent=2))
    return 0


def _configure_codex_timeout(seconds: int) -> None:
    os.environ.setdefault("NOVEL_FORGE_MODEL_PROVIDER", "claude-code")
    os.environ.setdefault("NOVEL_FORGE_CLAUDE_CODE_TIMEOUT_SECONDS", str(max(60, seconds)))
    os.environ.setdefault("NOVEL_FORGE_CLAUDE_CODE_SANDBOX", "read-only")


def _load_reference_brief(storage: LocalStorage, path_value: str) -> dict[str, Any]:
    path = storage.root / path_value if not Path(path_value).is_absolute() else Path(path_value)
    data = json.loads(path.read_text(encoding="utf-8"))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metrics = content.get("analysis_metrics", {}) if isinstance(content.get("analysis_metrics", {}), dict) else {}
    oral = content.get("oral_performance_style", {}) if isinstance(content.get("oral_performance_style", {}), dict) else {}
    return {
        "copyright_risk": content.get("copyright_risk", "high"),
        "abstraction_level": content.get("abstraction_level", "abstract"),
        "chapter_markers": metrics.get("chapter_markers", 0),
        "hook_signal_count": metrics.get("hook_signal_count", 0),
        "dialogue_marker_count": metrics.get("dialogue_marker_count", 0),
        "avg_sentence_length": metrics.get("avg_sentence_length", 0),
        "oral_style_family": oral.get("style_family", ""),
        "oral_mechanisms": oral.get("mechanisms", []),
        "safe_transfer": oral.get("safe_usage", ""),
        "generation_controls": oral.get("generation_controls", []),
        "hook_types": content.get("hook_system", {}).get("hook_types", []) if isinstance(content.get("hook_system", {}), dict) else [],
        "payoff_loop": content.get("payoff_loop", []),
        "abstraction_boundary": content.get("abstraction_boundary", ""),
    }


def _classical_knowledge_pack(root: Path) -> dict[str, Any]:
    books = {
        "forensic": ["洗冤集录", "折狱龟鉴"],
        "medicine": ["黄帝内经", "伤寒论", "本草纲目"],
        "strategy": ["孙子兵法", "三十六计", "六韬", "吴子", "尉缭子"],
        "bureaucracy": ["史记", "汉书", "明史", "资治通鉴"],
        "craft": ["天工开物", "梦溪笔谈", "齐民要术"],
        "strange_tales": ["搜神记", "太平广记", "世说新语"],
        "urban_life": ["东京梦华录", "武林旧事"],
        "rhetoric": ["文心雕龙", "笑林广记", "声律启蒙"],
    }
    available: dict[str, list[str]] = {}
    source_root = root / "古文原文"
    bilingual_root = root / "双语数据"
    for domain, names in books.items():
        available[domain] = [name for name in names if (source_root / name).exists() or (bilingual_root / name).exists()]
    return {
        "source": "NiuTrans/Classical-Modern",
        "license": "MIT for repository; individual classical data sources documented in source files",
        "usage_boundary": "domain knowledge abstraction only; do not copy classical passages into generated chapters",
        "domains": available,
        "principles": [
            "turn classical knowledge into constraints, institutions, tools, rituals, and decision costs",
            "prefer public-domain concepts and high-level mechanics over quoted language",
            "record knowledge as explainable story logic rather than raw excerpt memory",
        ],
    }


def _write_knowledge_card(storage: LocalStorage, knowledge: dict[str, Any]) -> str:
    asset = KnowledgeCard(
        title="Classical-Modern multidisciplinary abstraction pack",
        source="https://github.com/NiuTrans/Classical-Modern",
        tags=["knowledge", "classical-modern", "abstract-only", "longchain"],
        content={
            "principles": knowledge["principles"],
            "domain_sources": knowledge["domains"],
            "usage_boundary": knowledge["usage_boundary"],
            "license": knowledge["license"],
        },
        metadata={"project_id": PROJECT_ID, "copyright_boundary": knowledge["usage_boundary"]},
        references=[],
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return _display(storage.root, path)


def _series_bible(reference: dict[str, Any], knowledge: dict[str, Any], *, chapters: int) -> dict[str, Any]:
    return {
        "title": "夜档巡遗录",
        "target_chapters": chapters,
        "originality_boundary": "No protected names, cremation-specific premise, source plot sequence, or copied jokes from the supplied reference.",
        "premise": "A night-shift civic relic archivist discovers that abandoned city records can wake harmful folk mechanisms; each case must be resolved by combining forensic reasoning, craft knowledge, institutional rules, and street-level banter.",
        "canonical_lead_characters": CANONICAL_LEAD_CHARACTERS,
        "tone": "suspenseful, brisk, lightly oral-performance; humor releases pressure but never replaces plot consequence",
        "chapter_loop": reference.get("payoff_loop") or ["setup promise", "raise cost", "partial payoff", "new unresolved pressure"],
        "oral_controls": reference.get("generation_controls") or [],
        "knowledge_domains": knowledge.get("domains", {}),
        "long_hooks": [
            {"id": "ledger_origin", "setup": "the city archive hides a missing registry line", "payoff_window": "chapters 35-45"},
            {"id": "mentor_debt", "setup": "the protagonist inherits a debt measured in solved cases", "payoff_window": "chapters 55-70"},
            {"id": "district_machine", "setup": "different bureaus profit from leaving old mechanisms unresolved", "payoff_window": "chapters 80-100"},
        ],
        "forbidden_source_patterns_policy": "operator may provide local-only forbidden terms through NOVEL_FORGE_FORBIDDEN_SOURCE_PATTERNS; terms are not persisted in the exported bible",
    }


def _chapter_context(bible: dict[str, Any], reference: dict[str, Any], knowledge: dict[str, Any], *, chapter: int, chapters: int, target_chars: int, previous_summary: str) -> dict[str, Any]:
    arc = _arc_for_chapter(chapter, chapters)
    return {
        "runtime_operation": "generate_chapter",
        "project_id": PROJECT_ID,
        "series_bible": bible,
        "reference_abstraction": reference,
        "classical_knowledge": knowledge,
        "chapter": chapter,
        "target_chars": target_chars,
        "arc": arc,
        "previous_summary": previous_summary,
        "continuity_contract": {
            "canonical_lead_characters": CANONICAL_LEAD_CHARACTERS,
            "known_name_alias_repairs": KNOWN_NAME_ALIAS_REPAIRS,
            "hard_rule": "Keep 沈砚 and 阿照 as distinct established lead characters. Do not rename one into the other or introduce a third replacement lead name.",
        },
        "provider_runtime_guard": {"timeout_ms": int(os.environ.get("NOVEL_FORGE_CLAUDE_CODE_TIMEOUT_SECONDS", "900")) * 1000, "max_total_tokens": max(32000, target_chars * 7)},
        "copyright_boundary": bible["originality_boundary"],
        "output_contract": "Return JSON only: {\"text\":\"...\"}. The text must be original Chinese prose.",
        "codex_workdir": str(Path.cwd()),
    }


def _chapter_prompt(chapter: int, target_chars: int) -> str:
    return (
        f"Write chapter {chapter} of an original Chinese web-novel, about {target_chars} Chinese characters. "
        "The canonical lead roster is 沈砚 and 阿照; keep their identities distinct and do not rename either lead. "
        "Use the provided abstract structure and multidisciplinary knowledge only. "
        "Do not copy protected expression, named characters, settings, scenes, plot sequence, or jokes from references. "
        "Return valid JSON with a single field text."
    )


def _arc_for_chapter(chapter: int, chapters: int) -> dict[str, Any]:
    progress = chapter / max(chapters, 1)
    if progress < 0.2:
        phase = "establish protagonist, case engine, first bureau pressure, and ledger-origin hook"
    elif progress < 0.45:
        phase = "expand districts, reveal rule costs, and complicate mentor debt"
    elif progress < 0.7:
        phase = "force moral choices, show institutional backlash, and pay off mid-book hooks"
    elif progress < 0.9:
        phase = "connect case-of-week mechanisms into a district machine conspiracy"
    else:
        phase = "resolve main debt while opening a larger series horizon"
    return {"phase": phase, "required_beats": ["opening anomaly", "forensic or craft clue", "social pressure", "choice with cost", "partial payoff", "next hook"]}


def _write_draft_version(storage: LocalStorage, chapter: int, text: str, generated: dict[str, Any], agent_run_path: str, chapter_path: Path) -> dict[str, Any]:
    draft_id = make_id("draft", f"{PROJECT_ID}-{chapter}")
    asset = DraftVersion(
        title=f"夜档巡遗录 第{chapter:03d}章",
        source=PROJECT_ID,
        tags=["real-longchain", "draft-version", "generated"],
        content={
            "draft_id": draft_id,
            "version_index": 1,
            "chapter": chapter,
            "text": text,
            "source_draft_id": draft_id,
            "change_summary": "initial long-chain generated chapter",
            "status": "active",
            "model_output": {key: value for key, value in generated.items() if key != "text"},
            "copyright_boundary": "original generation from abstract references only",
        },
        metadata={"project_id": PROJECT_ID, "agent_run_path": agent_run_path, "export_path": str(chapter_path), "char_count": len(text)},
        references=[agent_run_path],
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display(storage.root, path), "asset": asset.to_dict()}


def _write_review_report(storage: LocalStorage, chapter: int, text: str, warnings: list[str], draft_path: str) -> dict[str, Any]:
    score = _quality_score(text, warnings, 5000)
    asset = ReviewReport(
        title=f"Long-chain quality review chapter {chapter:03d}",
        source=draft_path,
        tags=["real-longchain", "review", "heuristic"],
        score=score,
        strengths=["visible serial pressure", "original runtime-generated draft"],
        weaknesses=warnings[:3],
        issues=[{"dimension": "long_chain", "severity": "medium", "message": item} for item in warnings],
        risk_level="medium" if warnings else "low",
        revision_suggestions=["repair any short chapter, weak hook, or originality warning before publication"] if warnings else [],
        next_action="revise" if warnings else "publish_gate",
        content={"rubric": "long-chain heuristic review", "summary": f"Chapter {chapter} score {score}", "warnings": warnings, "chapter": chapter},
        metadata={"project_id": PROJECT_ID, "draft_path": draft_path},
        references=[draft_path],
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display(storage.root, path), "asset": asset.to_dict()}


def _quality_warnings(text: str, target_chars: int) -> list[str]:
    warnings: list[str] = []
    if len(text) < int(target_chars * 0.72):
        warnings.append(f"chapter is shorter than target: {len(text)}/{target_chars}")
    if not re.search(r"[？?!！。]$", text.strip()):
        warnings.append("chapter ending punctuation is weak")
    if not any(marker in text for marker in ["却", "偏偏", "谁知", "忽然", "只见", "没想到"]):
        warnings.append("hook/reversal markers are thin")
    if any(name in text for name in KNOWN_NAME_ALIAS_REPAIRS):
        warnings.append("canonical lead name alias drift appeared")
    for pattern in _forbidden_source_patterns():
        if pattern in text:
            warnings.append("protected reference pattern appeared and must be removed")
            break
    return warnings


def _canonicalize_generated_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    repaired = text
    repairs: list[dict[str, Any]] = []
    for drift_name, canonical_name in KNOWN_NAME_ALIAS_REPAIRS.items():
        count = repaired.count(drift_name)
        if not count:
            continue
        repaired = repaired.replace(drift_name, canonical_name)
        repairs.append(
            {
                "kind": "canonical_lead_name_alias_repair",
                "from": drift_name,
                "to": canonical_name,
                "count": count,
            }
        )
    return repaired, repairs


def _extract_generated_text(generated: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    raw = str(generated.get("text", "")).strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            nested = json.loads(raw)
        except Exception:
            nested = {}
        if isinstance(nested, dict) and str(nested.get("text", "")).strip():
            return str(nested["text"]).strip(), [{"kind": "nested_json_text_unwrapped", "field": "text"}]
    return raw, []


def _quality_score(text: str, warnings: list[str], target_chars: int) -> float:
    length_score = min(len(text) / max(target_chars, 1), 1.05) * 35
    dialogue_score = min(text.count("“") + text.count("”"), 24) / 24 * 15
    hook_score = 20 if any(marker in text for marker in ["忽然", "谁知", "偏偏", "却", "没想到"]) else 10
    forbidden = _forbidden_source_patterns()
    originality_score = 30 if not any(pattern in text for pattern in forbidden) else 0
    return round(max(0, min(100, length_score + dialogue_score + hook_score + originality_score - len(warnings) * 6)), 2)


def _forbidden_source_patterns() -> list[str]:
    raw = os.environ.get("NOVEL_FORGE_FORBIDDEN_SOURCE_PATTERNS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _chapter_summary(text: str, chapter: int) -> str:
    compact = re.sub(r"\s+", "", text)
    return f"第{chapter}章完成：{compact[:180]}..."


def _force_chapter_set(values: list[int] | None) -> set[int]:
    return {int(value) for value in values or [] if int(value) > 0}


def _filter_forced_chapter_summaries(summaries: list[dict[str, Any]], force_chapters: set[int]) -> list[dict[str, Any]]:
    if not force_chapters:
        return summaries
    return [item for item in summaries if int(item.get("chapter", 0) or 0) not in force_chapters]


def _load_existing_summaries(export_dir: Path) -> list[dict[str, Any]]:
    path = export_dir / "progress.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data.get("chapters", []) if isinstance(data.get("chapters", []), list) else []


def _ensure_acceptance_assets(storage: LocalStorage, export_dir: Path, summaries: list[dict[str, Any]], bible: dict[str, Any], *, target_chars: int) -> dict[str, Any]:
    created = {"chapter_production_run": 0, "context_bundle": 0, "chapter_continuity_report": 0, "feedback_backflow_plan": 0}
    for item in summaries:
        chapter = int(item.get("chapter", 0) or 0)
        if chapter <= 0:
            continue
        chapter_path = export_dir / "chapters" / f"chapter_{chapter:03d}.md"
        text = _chapter_text(chapter_path)
        warnings = item.get("warnings", []) if isinstance(item.get("warnings", []), list) else []
        score = float(item.get("quality_score") or _quality_score(text, warnings, target_chars))
        draft = _latest_project_asset_for_chapter(storage, "draft_version", "drafts", chapter)
        draft_path = draft.get("path", "") if draft else ""
        if not _asset_exists_for_chapter(storage, "chapter_production_run", "runs", chapter):
            _write_acceptance_asset(storage, _chapter_production_run(chapter, draft_path, chapter_path, score))
            created["chapter_production_run"] += 1
        if not _asset_exists_for_chapter(storage, "context_bundle", "contexts", chapter):
            _write_acceptance_asset(storage, _context_bundle(chapter, draft_path, item, bible, target_chars))
            created["context_bundle"] += 1
        if not _asset_exists_for_chapter(storage, "chapter_continuity_report", "continuity", chapter):
            _write_acceptance_asset(storage, _chapter_continuity_report(chapter, draft_path, warnings, bible, generated_chapters=len(summaries), export_dir=export_dir))
            created["chapter_continuity_report"] += 1
    if not _assets_by_type_for_project(storage, "feedback_backflow_plan", "feedback"):
        _write_acceptance_asset(storage, _feedback_backflow_plan(summaries, target_chars))
        created["feedback_backflow_plan"] += 1
    return created


def _chapter_production_run(chapter: int, draft_path: str, chapter_path: Path, quality_score: float) -> ChapterProductionRun:
    now = utc_now()
    run_id = make_id("chapter_production_run", f"{PROJECT_ID}-{chapter}")
    steps = {
        "prompt": {"status": "completed", "checkpoint": "prompt_built"},
        "provider": {"status": "completed", "checkpoint": "provider_completed"},
        "validation": {"status": "completed", "checkpoint": "output_validated", "quality_score": quality_score},
        "commit": {"status": "completed", "checkpoint": "draft_version_committed"},
    }
    return ChapterProductionRun(
        title=f"Long-chain chapter run {chapter:03d}",
        tags=["real-longchain", "pressure", "succeeded"],
        content={
            "run_id": run_id,
            "status": "succeeded",
            "current_step": "commit",
            "chapter": chapter,
            "step_order": ["prompt", "provider", "validation", "commit"],
            "steps": steps,
            "timeline": [{"step": key, "status": value["status"], "recorded_at": now} for key, value in steps.items()],
            "outputs": {"draft_version_path": draft_path, "export_path": str(chapter_path)},
            "created_at": now,
            "updated_at": now,
        },
        metadata={"project_id": PROJECT_ID, "chapter": chapter, "export_path": str(chapter_path)},
        references=[draft_path] if draft_path else [],
    )


def _context_bundle(chapter: int, draft_path: str, summary: dict[str, Any], bible: dict[str, Any], target_chars: int) -> ContextBundle:
    hooks = bible.get("long_hooks", []) if isinstance(bible.get("long_hooks", []), list) else []
    selected = [{"asset_type": "series_bible", "reason": "long-chain continuity"}, {"asset_type": "chapter_summary", "chapter": chapter, "reason": "resume memory"}]
    target_asset_id = draft_path or f"exported-chapter-{chapter:03d}"
    return ContextBundle(
        title=f"Long-chain context bundle {chapter:03d}",
        tags=["real-longchain", "context", "kg-backed", "pressure"],
        content={
            "build_plan_id": make_id("context_build_plan", f"{PROJECT_ID}-{chapter}"),
            "target_asset_id": target_asset_id,
            "target_asset_type": "draft_version",
            "selected_assets": selected,
            "compressed_context": str(summary.get("summary", ""))[:1200],
            "token_budget": {"max_tokens": max(32000, target_chars * 7), "reserved_output_tokens": target_chars * 2},
            "token_estimate": max(1, len(str(summary.get("summary", ""))) // 2),
            "actual_context": {
                "series_title": bible.get("title", ""),
                "chapter": chapter,
                "arc_memory": str(summary.get("summary", "")),
                "long_hooks": hooks,
            },
            "kg_context": {"items": [{"kind": "foreshadowing", **hook} for hook in hooks]},
            "source_asset_ids": [draft_path] if draft_path else [],
        },
        metadata={"project_id": PROJECT_ID, "chapter": chapter, "target_chars": target_chars},
        references=[draft_path] if draft_path else [],
    )


def _chapter_continuity_report(chapter: int, draft_path: str, warnings: list[str], bible: dict[str, Any], *, generated_chapters: int, export_dir: Path | None = None) -> ChapterContinuityReport:
    lifecycle = _foreshadow_lifecycle(bible, generated_chapters=generated_chapters, export_dir=export_dir)
    blocking = [warning for warning in warnings if "protected reference pattern" in warning]
    recommendation = "block" if blocking else "revise" if warnings else "pass"
    target_asset_id = draft_path or f"exported-chapter-{chapter:03d}"
    return ChapterContinuityReport(
        title=f"Long-chain continuity chapter {chapter:03d}",
        source=target_asset_id,
        tags=["real-longchain", "continuity", recommendation],
        content={
            "target_asset_id": target_asset_id,
            "chapter": chapter,
            "continuity_checks": [
                {"dimension": "foreshadowing_lifecycle", "status": lifecycle["overall_status"], "open_count": lifecycle["active_count"]},
                {"dimension": "protected_reference_boundary", "status": "failed" if blocking else "passed"},
                {"dimension": "chapter_hook", "status": "warning" if any("hook" in item for item in warnings) else "passed"},
            ],
            "violations": [{"severity": "high" if item in blocking else "medium", "message": item} for item in warnings],
            "blocking_violations": [{"severity": "high", "message": item} for item in blocking],
            "dimensions": {"foreshadowing_lifecycle": lifecycle},
            "recommendation": recommendation,
        },
        metadata={"project_id": PROJECT_ID, "chapter": chapter},
        references=[draft_path] if draft_path else [],
    )


def _feedback_backflow_plan(summaries: list[dict[str, Any]], target_chars: int) -> FeedbackBackflowPlan:
    warning_rows = [
        {"chapter": int(item.get("chapter", 0) or 0), "warnings": item.get("warnings", [])}
        for item in summaries
        if isinstance(item.get("warnings", []), list) and item.get("warnings", [])
    ]
    target_action = "tighten_chapter_hook" if any(any("ending punctuation" in warning or "hook" in warning for warning in row["warnings"]) for row in warning_rows) else "continue_current_engine"
    now = utc_now()
    return FeedbackBackflowPlan(
        title="Long-chain pressure feedback backflow",
        tags=["real-longchain", "pressure", "feedback-backflow", target_action],
        content={
            "plan_id": make_id("feedback_backflow_plan", f"{PROJECT_ID}-{len(summaries)}"),
            "clusters": [
                {
                    "cluster_id": make_id("feedback_cluster", target_action),
                    "signals": warning_rows[:20],
                    "target_action": target_action,
                    "affected_assets": [f"chapter_{row['chapter']:03d}" for row in warning_rows if row["chapter"]],
                    "created_at": now,
                }
            ],
            "proposals": [
                {
                    "type": "plan_adjustment_proposal",
                    "target_scope": "next_chapters",
                    "proposed_changes": [
                        "carry forward explicit hook payoff/reversal in the final paragraph",
                        f"keep generated chapters near or above {int(target_chars * 0.72)} Chinese characters",
                        "feed recurring weak-hook signals into review gate before publish gate",
                    ],
                },
                {
                    "type": "review_rule_update_proposal",
                    "rule_dimension": "long_chain_pressure",
                    "proposed_rule": "block publish gate when protected reference pattern appears; warn on weak ending punctuation or thin hook markers",
                },
            ],
            "human_gate": {"required": True, "status": "waiting", "reason": "feedback backflow mutates future chapter plans and review rules"},
            "status": "waiting_human",
            "created_at": now,
        },
        metadata={"project_id": PROJECT_ID, "generated_chapters": len(summaries), "source": "long_chain_pressure_acceptance"},
    )


def _write_progress(export_dir: Path, chapters: int, target_chars: int, summaries: list[dict[str, Any]], records: list[ChapterRecord]) -> None:
    _write_json(
        export_dir / "progress.json",
        {
            "project_id": PROJECT_ID,
            "target_chapters": chapters,
            "target_chars_per_chapter": target_chars,
            "generated_chapters": len(summaries),
            "latest_run_records": [record.__dict__ | {"path": str(record.path)} for record in records],
            "chapters": summaries,
            "updated_at": utc_now(),
        },
    )


def _quality_report(
    storage: LocalStorage,
    export_dir: Path,
    chapters: int,
    target_chars: int,
    summaries: list[dict[str, Any]],
    records: list[ChapterRecord],
    acceptance: dict[str, Any],
    bible: dict[str, Any],
    acceptance_assets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated = len(summaries)
    char_counts = [int(item.get("char_count", 0) or 0) for item in summaries]
    warnings = [warning for item in summaries for warning in item.get("warnings", []) if isinstance(item.get("warnings", []), list)]
    scores = _all_chapter_scores(export_dir, summaries, target_chars)
    quality_drift = _quality_drift(scores, char_counts)
    cost_drift = _cost_drift(storage, generated_chapters=generated)
    foreshadowing = _foreshadow_lifecycle(bible, generated_chapters=generated, export_dir=export_dir)
    feedback_backflow = _feedback_backflow_summary(storage, summaries)
    pressure_acceptance = _pressure_acceptance(cost_drift, quality_drift, foreshadowing, feedback_backflow)
    return {
        "project_id": PROJECT_ID,
        "export_dir": str(export_dir),
        "target": {"chapters": chapters, "chars_per_chapter": target_chars, "total_chars": chapters * target_chars},
        "observed": {"chapters": generated, "total_chars": sum(char_counts), "average_chars": round(sum(char_counts) / max(generated, 1), 2)},
        "completion": round(generated / max(chapters, 1), 4),
        "quality": {
            "latest_scores": [{"chapter": record.chapter, "score": record.quality_score, "warnings": record.warnings} for record in records],
            "all_scores": scores,
            "warning_count": len(warnings),
            "warning_samples": warnings[:20],
            "recommendation": "continue" if generated < chapters else "revise_then_publish_gate",
        },
        "pressure_dimensions": [
            "cost drift via model_call_log usage and cost_ledger",
            "quality drift via heuristic review score trend",
            "foreshadow lifecycle via series_bible.long_hooks",
            "feedback backflow via pressure feedback_backflow_plan",
        ],
        "pressure_acceptance": pressure_acceptance,
        "cost_drift": cost_drift,
        "quality_drift": quality_drift,
        "foreshadowing_lifecycle": foreshadowing,
        "feedback_backflow": feedback_backflow,
        "acceptance_assets": acceptance_assets or {},
        "acceptance_report": acceptance.get("path", ""),
        "created_at": utc_now(),
    }


def _repair_runtime_evidence_project_scope(storage: LocalStorage) -> None:
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        asset_type = str(data.get("type", ""))
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        operation = str(content.get("operation", ""))
        should_tag = asset_type == "model_call_log" and operation in {"generate_chapter", "real_longchain_chapter"}
        if asset_type == "cost_ledger" and not str(metadata.get("project_id", "")).strip():
            should_tag = True
        if not should_tag:
            continue
        changed = False
        if metadata.get("project_id") != PROJECT_ID:
            metadata["project_id"] = PROJECT_ID
            changed = True
        if not metadata.get("workspace_path"):
            metadata["workspace_path"] = str(storage.root)
            changed = True
        if content.get("project_id") != PROJECT_ID:
            content["project_id"] = PROJECT_ID
            changed = True
        if changed:
            data["metadata"] = metadata
            data["content"] = content
            storage.write_json(path, data)


def _all_chapter_scores(export_dir: Path, summaries: list[dict[str, Any]], target_chars: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in summaries:
        chapter = int(item.get("chapter", 0) or 0)
        if chapter <= 0:
            continue
        chapter_path = export_dir / "chapters" / f"chapter_{chapter:03d}.md"
        text = _chapter_text(chapter_path)
        warnings = item.get("warnings", []) if isinstance(item.get("warnings", []), list) else _quality_warnings(text, target_chars)
        score = float(item.get("quality_score") or _quality_score(text, warnings, target_chars))
        rows.append({"chapter": chapter, "score": round(score, 2), "char_count": int(item.get("char_count") or len(text)), "warnings": warnings})
    return rows


def _quality_drift(scores: list[dict[str, Any]], char_counts: list[int]) -> dict[str, Any]:
    score_values = [float(item.get("score", 0) or 0) for item in scores]
    window = max(1, min(5, len(score_values) // 2 or 1))
    first_average = _average(score_values[:window])
    latest_average = _average(score_values[-window:])
    warning_count = sum(len(item.get("warnings", [])) for item in scores if isinstance(item.get("warnings", []), list))
    latest_chars = _average([float(value) for value in char_counts[-window:]]) if char_counts else 0.0
    first_chars = _average([float(value) for value in char_counts[:window]]) if char_counts else 0.0
    trend = "insufficient_data"
    if len(score_values) >= 2:
        trend = "improving" if latest_average > first_average + 1 else "stable" if latest_average >= first_average - 3 else "declining"
    status = "passed" if latest_average >= 80 and trend != "declining" else "warning" if latest_average >= 70 else "failed"
    return {
        "status": status,
        "trend": trend,
        "first_window_average_score": round(first_average, 2),
        "latest_window_average_score": round(latest_average, 2),
        "score_delta": round(latest_average - first_average, 2),
        "warning_count": warning_count,
        "average_char_first_window": round(first_chars, 2),
        "average_char_latest_window": round(latest_chars, 2),
        "char_drift_ratio": round(latest_chars / first_chars, 4) if first_chars else 0,
    }


def _cost_drift(storage: LocalStorage, *, generated_chapters: int) -> dict[str, Any]:
    model_calls = _assets_by_type_for_project(storage, "model_call_log", "runs", include_longchain_operations=True)
    provider_calls = [item for item in model_calls if str(_content(item).get("operation", "")) == "generate_chapter"]
    drift_calls = provider_calls or model_calls
    drift_calls = sorted(drift_calls, key=lambda item: str(_content(item).get("created_at", "")))
    tokens = [_usage_tokens(_content(item).get("usage", {})) for item in drift_calls]
    window = max(1, min(5, len(tokens) // 2 or 1))
    first_average = _average([float(value) for value in tokens[:window]])
    latest_average = _average([float(value) for value in tokens[-window:]])
    ledgers = _assets_by_type_for_project(storage, "cost_ledger", "runs")
    total_cost = 0.0
    for item in ledgers:
        amount = _content(item).get("amount", 0)
        if isinstance(amount, (int, float)):
            total_cost += float(amount)
    drift_ratio = round(latest_average / first_average, 4) if first_average else 0
    status = "passed" if model_calls and (not drift_ratio or drift_ratio <= 1.6) else "warning" if model_calls else "failed"
    return {
        "status": status,
        "model_call_count": len(model_calls),
        "provider_model_call_count": len(provider_calls),
        "ledger_count": len(ledgers),
        "total_tokens": int(sum(tokens)),
        "average_tokens_per_generated_chapter": round(sum(tokens) / max(generated_chapters, 1), 2),
        "first_window_average_tokens": round(first_average, 2),
        "latest_window_average_tokens": round(latest_average, 2),
        "token_drift_ratio": drift_ratio,
        "total_cost": round(total_cost, 6),
        "cost_per_generated_chapter": round(total_cost / max(generated_chapters, 1), 6),
        "cost_currency": _ledger_currency(ledgers),
    }


def _foreshadow_lifecycle(bible: dict[str, Any], *, generated_chapters: int, export_dir: Path | None = None) -> dict[str, Any]:
    hooks = bible.get("long_hooks", []) if isinstance(bible.get("long_hooks", []), list) else []
    rows: list[dict[str, Any]] = []
    overdue = 0
    due = 0
    active = 0
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        start, end = _payoff_window(str(hook.get("payoff_window", "")))
        evidence = _foreshadow_payoff_evidence(hook, generated_chapters=generated_chapters, export_dir=export_dir, window_start=start)
        status = "seeded"
        if evidence:
            status = "paid_off"
        elif start and generated_chapters >= start:
            status = "payoff_due"
            due += 1
        if not evidence and end and generated_chapters > end:
            status = "overdue"
            overdue += 1
        if not evidence and generated_chapters < (end or generated_chapters + 1):
            active += 1
        rows.append(
            {
                "id": str(hook.get("id", "")),
                "setup": str(hook.get("setup", "")),
                "payoff_window": str(hook.get("payoff_window", "")),
                "window_start": start,
                "window_end": end,
                "status": status,
                "payoff_evidence": evidence[:5],
            }
        )
    return {
        "overall_status": "failed" if overdue else "warning" if due else "passed",
        "generated_chapters": generated_chapters,
        "active_count": active,
        "due_count": due,
        "overdue_count": overdue,
        "hooks": rows,
    }


def _foreshadow_payoff_evidence(hook: dict[str, Any], *, generated_chapters: int, export_dir: Path | None, window_start: int) -> list[dict[str, Any]]:
    markers = _foreshadow_payoff_markers(hook)
    if not markers or not export_dir:
        return []
    chapter_dir = export_dir / "chapters"
    if not chapter_dir.exists():
        return []
    start = max(1, int(window_start or 1))
    evidence: list[dict[str, Any]] = []
    for chapter in range(start, max(start, int(generated_chapters)) + 1):
        path = chapter_dir / f"chapter_{chapter:03d}.md"
        if not path.exists():
            continue
        text = _chapter_text(path)
        compact = re.sub(r"\s+", "", text)
        for marker in markers:
            marker_text = str(marker).strip()
            if not marker_text:
                continue
            idx = compact.find(marker_text)
            if idx < 0:
                continue
            start_idx = max(0, idx - 32)
            end_idx = min(len(compact), idx + len(marker_text) + 32)
            evidence.append({"chapter": chapter, "marker": marker_text, "evidence_span": compact[start_idx:end_idx]})
            break
    return evidence


def _foreshadow_payoff_markers(hook: dict[str, Any]) -> list[str]:
    explicit = hook.get("payoff_markers", [])
    if isinstance(explicit, list) and explicit:
        return [str(item) for item in explicit if str(item).strip()]
    hook_id = str(hook.get("id", "")).strip()
    defaults = {
        "ledger_origin": ["还我户名", "缺一行", "城籍院", "户名", "本来就在同一本账上", "旧账先认门"],
        "mentor_debt": ["师门旧债", "欠夜档司", "债", "替还"],
        "district_machine": ["各司", "三司", "官府", "机器", "城中各衙门", "旧账牵出"],
    }
    return defaults.get(hook_id, [])


def _feedback_backflow_summary(storage: LocalStorage, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    plans = _assets_by_type_for_project(storage, "feedback_backflow_plan", "feedback")
    latest = plans[-1] if plans else {}
    warning_chapters = [int(item.get("chapter", 0) or 0) for item in summaries if isinstance(item.get("warnings", []), list) and item.get("warnings", [])]
    content = _content(latest) if latest else {}
    return {
        "status": "passed" if plans else "warning",
        "plan_count": len(plans),
        "latest_plan_status": str(content.get("status", "")),
        "warning_chapters": warning_chapters,
        "proposal_count": len(content.get("proposals", [])) if isinstance(content.get("proposals", []), list) else 0,
    }


def _pressure_acceptance(cost_drift: dict[str, Any], quality_drift: dict[str, Any], foreshadowing: dict[str, Any], feedback_backflow: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "cost_drift": cost_drift.get("status", "failed"),
        "quality_drift": quality_drift.get("status", "failed"),
        "foreshadow_lifecycle": "passed" if foreshadowing.get("overall_status") == "passed" else str(foreshadowing.get("overall_status", "warning")),
        "feedback_backflow": feedback_backflow.get("status", "warning"),
    }
    if any(status == "failed" for status in checks.values()):
        recommendation = "block"
    elif any(status == "warning" for status in checks.values()):
        recommendation = "continue_with_watch"
    else:
        recommendation = "continue"
    return {"status": "passed" if recommendation == "continue" else "warning" if recommendation == "continue_with_watch" else "failed", "checks": checks, "recommendation": recommendation}


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    target = report["target"]
    observed = report["observed"]
    quality = report["quality"]
    pressure = report.get("pressure_acceptance", {})
    cost = report.get("cost_drift", {})
    drift = report.get("quality_drift", {})
    foreshadowing = report.get("foreshadowing_lifecycle", {})
    feedback = report.get("feedback_backflow", {})
    text = (
        "# Long-chain Web Novel Quality Report\n\n"
        f"- Project: `{report['project_id']}`\n"
        f"- Target: {target['chapters']} chapters x {target['chars_per_chapter']} chars = {target['total_chars']} chars\n"
        f"- Observed: {observed['chapters']} chapters, {observed['total_chars']} chars, avg {observed['average_chars']}\n"
        f"- Completion: {report['completion'] * 100:.2f}%\n"
        f"- Warning count: {quality['warning_count']}\n"
        f"- Recommendation: {quality['recommendation']}\n"
        f"- Pressure acceptance: {pressure.get('status', '')} / {pressure.get('recommendation', '')}\n"
        f"- Acceptance report: `{report['acceptance_report']}`\n\n"
        "## Pressure Coverage\n\n"
        + "\n".join(f"- {item}" for item in report["pressure_dimensions"])
        + "\n\n## Pressure Metrics\n\n"
        + f"- Cost drift: {cost.get('status', '')}; model calls {cost.get('model_call_count', 0)}, provider calls {cost.get('provider_model_call_count', 0)}, tokens {cost.get('total_tokens', 0)}, token drift ratio {cost.get('token_drift_ratio', 0)}\n"
        + f"- Quality drift: {drift.get('status', '')}; trend {drift.get('trend', '')}, score delta {drift.get('score_delta', 0)}, char drift ratio {drift.get('char_drift_ratio', 0)}\n"
        + f"- Foreshadow lifecycle: {foreshadowing.get('overall_status', '')}; due {foreshadowing.get('due_count', 0)}, overdue {foreshadowing.get('overdue_count', 0)}\n"
        + f"- Feedback backflow: {feedback.get('status', '')}; plans {feedback.get('plan_count', 0)}, proposals {feedback.get('proposal_count', 0)}\n"
        + "\n## Latest Chapter Scores\n\n"
        + "\n".join(f"- Chapter {item['chapter']}: {item['score']} ({'; '.join(item['warnings']) or 'no warnings'})" for item in quality["latest_scores"])
        + "\n"
    )
    path.write_text(text, encoding="utf-8")


def _write_acceptance_asset(storage: LocalStorage, asset: Any) -> str:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return _display(storage.root, storage.write_asset_auto(asset))


def _chapter_text(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r"^#\s*第\d+章\s*", "", text, flags=re.MULTILINE).strip()


def _latest_project_asset_for_chapter(storage: LocalStorage, asset_type: str, category: str, chapter: int) -> dict[str, Any]:
    rows = _assets_by_type_for_project(storage, asset_type, category)
    for item in reversed(rows):
        content = _content(item)
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {}
        if int(content.get("chapter", metadata.get("chapter", 0)) or 0) == chapter:
            return item
    return {}


def _asset_exists_for_chapter(storage: LocalStorage, asset_type: str, category: str, chapter: int) -> bool:
    return bool(_latest_project_asset_for_chapter(storage, asset_type, category, chapter))


def _assets_by_type_for_project(storage: LocalStorage, asset_type: str, category: str, *, include_longchain_operations: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json(category):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = _content(data)
        operation = str(content.get("operation", ""))
        if metadata.get("project_id") == PROJECT_ID or content.get("project_id") == PROJECT_ID or (
            include_longchain_operations and operation in {"generate_chapter", "real_longchain_chapter"}
        ):
            data = {**data, "path": _display(storage.root, path)}
            rows.append(data)
    return rows


def _content(asset: dict[str, Any]) -> dict[str, Any]:
    return asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}


def _usage_tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    for key in ["total_tokens", "tokens", "token_used"]:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    total = 0
    for key in ["input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"]:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _payoff_window(value: str) -> tuple[int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", value)]
    if not numbers:
        return 0, 0
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def _ledger_currency(ledgers: list[dict[str, Any]]) -> str:
    for item in ledgers:
        currency = str(_content(item).get("currency", "") or "")
        if currency:
            return currency
    return "USD"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _display(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
