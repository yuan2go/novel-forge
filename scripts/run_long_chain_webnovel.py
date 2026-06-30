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
from novel_forge.schemas import DraftVersion, KnowledgeCard, ReviewReport, validate_common_fields
from novel_forge.storage.local import LocalStorage


PROJECT_ID = "real-longchain-webnovel"


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
    parser.add_argument("--force", action="store_true")
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
    existing_summaries = _load_existing_summaries(export_dir)
    chapter_limit = max(1, int(args.max_chapters_this_run))
    generated_this_run = 0
    previous_summary = existing_summaries[-1]["summary"] if existing_summaries else ""

    _configure_codex_timeout(args.codex_timeout_seconds)
    adapter = ClaudeCodeAdapter()
    for chapter in range(1, max(1, int(args.chapters)) + 1):
        chapter_path = export_dir / "chapters" / f"chapter_{chapter:03d}.md"
        if chapter_path.exists() and not args.force:
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
            text = str(generated.get("text", "")).strip()
            warnings = _quality_warnings(text, args.target_chars)
            chapter_path.write_text(f"# 第{chapter:03d}章\n\n{text}\n", encoding="utf-8")
            run.guard("write_draft_version", "draft_version")
            draft = _write_draft_version(storage, chapter, text, generated, run.path, chapter_path)
            run.succeed(output_assets=[draft["path"], str(chapter_path)], token_used=len(text))
        review = _write_review_report(storage, chapter, text, warnings, draft["path"])
        summary = _chapter_summary(text, chapter)
        existing_summaries.append({"chapter": chapter, "summary": summary, "char_count": len(text), "warnings": warnings})
        previous_summary = summary
        record = ChapterRecord(
            chapter=chapter,
            path=chapter_path,
            asset_path=draft["path"],
            char_count=len(text),
            quality_score=_quality_score(text, warnings, args.target_chars),
            warnings=warnings,
            cost_paths=[str(model_result.get("cost_ledger_path", ""))] if isinstance(model_result, dict) and model_result.get("cost_ledger_path") else [],
        )
        records.append(record)
        generated_this_run += 1
        _write_progress(export_dir, args.chapters, args.target_chars, existing_summaries, records)

    acceptance = create_long_chain_acceptance_report(storage, project_id=PROJECT_ID, chapter_count=args.chapters)
    report = _quality_report(export_dir, args.chapters, args.target_chars, existing_summaries, records, acceptance)
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
        "provider_runtime_guard": {"timeout_ms": int(os.environ.get("NOVEL_FORGE_CLAUDE_CODE_TIMEOUT_SECONDS", "900")) * 1000, "max_total_tokens": max(32000, target_chars * 7)},
        "copyright_boundary": bible["originality_boundary"],
        "output_contract": "Return JSON only: {\"text\":\"...\"}. The text must be original Chinese prose.",
        "codex_workdir": str(Path.cwd()),
    }


def _chapter_prompt(chapter: int, target_chars: int) -> str:
    return (
        f"Write chapter {chapter} of an original Chinese web-novel, about {target_chars} Chinese characters. "
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
    for pattern in _forbidden_source_patterns():
        if pattern in text:
            warnings.append("protected reference pattern appeared and must be removed")
            break
    return warnings


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


def _load_existing_summaries(export_dir: Path) -> list[dict[str, Any]]:
    path = export_dir / "progress.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data.get("chapters", []) if isinstance(data.get("chapters", []), list) else []


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


def _quality_report(export_dir: Path, chapters: int, target_chars: int, summaries: list[dict[str, Any]], records: list[ChapterRecord], acceptance: dict[str, Any]) -> dict[str, Any]:
    generated = len(summaries)
    char_counts = [int(item.get("char_count", 0) or 0) for item in summaries]
    warnings = [warning for item in summaries for warning in item.get("warnings", []) if isinstance(item.get("warnings", []), list)]
    return {
        "project_id": PROJECT_ID,
        "export_dir": str(export_dir),
        "target": {"chapters": chapters, "chars_per_chapter": target_chars, "total_chars": chapters * target_chars},
        "observed": {"chapters": generated, "total_chars": sum(char_counts), "average_chars": round(sum(char_counts) / max(generated, 1), 2)},
        "completion": round(generated / max(chapters, 1), 4),
        "quality": {
            "latest_scores": [{"chapter": record.chapter, "score": record.quality_score, "warnings": record.warnings} for record in records],
            "warning_count": len(warnings),
            "warning_samples": warnings[:20],
            "recommendation": "continue" if generated < chapters else "revise_then_publish_gate",
        },
        "pressure_dimensions": ["cost drift via cost ledger", "quality drift via heuristic review", "foreshadow lifecycle via series_bible.long_hooks", "feedback backflow via future reader feedback import"],
        "acceptance_report": acceptance.get("path", ""),
        "created_at": utc_now(),
    }


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    target = report["target"]
    observed = report["observed"]
    quality = report["quality"]
    text = (
        "# Long-chain Web Novel Quality Report\n\n"
        f"- Project: `{report['project_id']}`\n"
        f"- Target: {target['chapters']} chapters x {target['chars_per_chapter']} chars = {target['total_chars']} chars\n"
        f"- Observed: {observed['chapters']} chapters, {observed['total_chars']} chars, avg {observed['average_chars']}\n"
        f"- Completion: {report['completion'] * 100:.2f}%\n"
        f"- Warning count: {quality['warning_count']}\n"
        f"- Recommendation: {quality['recommendation']}\n"
        f"- Acceptance report: `{report['acceptance_report']}`\n\n"
        "## Pressure Coverage\n\n"
        + "\n".join(f"- {item}" for item in report["pressure_dimensions"])
        + "\n\n## Latest Chapter Scores\n\n"
        + "\n".join(f"- Chapter {item['chapter']}: {item['score']} ({'; '.join(item['warnings']) or 'no warnings'})" for item in quality["latest_scores"])
        + "\n"
    )
    path.write_text(text, encoding="utf-8")


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
