from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS, DOC_FILES
from novel_forge.core.ids import utc_now
from novel_forge.evaluation.quality import QUALITY_DIMENSIONS
from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.schemas import (
    ChapterPlan,
    CharacterCard,
    CleanedText,
    DecompositionReport,
    DraftChapter,
    FeedbackInsight,
    KnowledgeCard,
    MaterialCard,
    Outline,
    ReaderFeedback,
    ReviewReport,
    RevisionPlan,
    SourceDocument,
    TopicSeed,
    WorkflowRun,
    WorldBible,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


def resolve_path(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


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


def _read_previous(storage: LocalStorage, category: str, input_path: str | None) -> Any:
    path = resolve_path(storage.root, input_path) if input_path else storage.latest(category)
    return storage.read_asset(path)


def ingest(root: str | Path, input_path: str, title: str | None = None) -> Path:
    storage = ensure_project(root)
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    text = path.read_text(encoding="utf-8")
    asset = SourceDocument(
        title=title or path.stem,
        source=str(path),
        tags=["imported", "raw"],
        content={"text": text},
        metadata={"original_path": str(path), "ingested_at": utc_now()},
    )
    return storage.write_asset("raw", asset)


def clean(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    source = _read_previous(storage, "raw", input_path)
    text = source.content.get("text", "")
    normalized = "\n".join(line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip())
    asset = CleanedText(
        title=f"{source.title} cleaned",
        source=source.id,
        tags=["cleaned"],
        content={"text": normalized},
        metadata={"steps": ["normalize_newlines", "trim_blank_lines"]},
        references=[source.id],
    )
    return storage.write_asset("cleaned", asset)


def decompose(root: str | Path, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    model = model or MockModelAdapter()
    cleaned = _read_previous(storage, "cleaned", input_path)
    text = cleaned.content.get("text", "")
    analysis = model.analyze(text)
    asset = DecompositionReport(
        title=f"{cleaned.title} decomposition",
        source=cleaned.id,
        tags=["decomposition", "abstracted", "commercial-patterns"],
        content={
            "summary": analysis["summary"],
            "commercial_patterns": ["reader question raised before explanation", "visible consequence per scene"],
            "narrative_patterns": ["problem -> investigation -> obstacle -> cost -> hook"],
            "character_mechanisms": ["protagonist pressure increases through external deadline"],
            "conflict_patterns": ["truth-seeking vs institutional silence"],
            "emotion_curve": ["curiosity", "tension", "uncertainty", "anticipation"],
            "hook_patterns": ["unanswered clue at chapter end"],
            "word_count": analysis["word_count"],
        },
        metadata={
            "model": model.name,
            "copyright_boundary": "abstract structure and mechanism only; no protected expression copied",
        },
        references=[cleaned.id],
    )
    return storage.write_asset("decompositions", asset)


def extract_knowledge(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    report = _read_previous(storage, "decompositions", input_path)
    asset = KnowledgeCard(
        title=f"Knowledge from {report.title}",
        source=report.id,
        tags=["knowledge", "suspense", "structure"],
        content={
            "principles": [
                "open with a concrete question before exposition",
                "attach each clue to a cost or relationship pressure",
                "turn chapter endings into decision pressure rather than mere mystery",
            ],
            "derived_from": report.content,
        },
        metadata={"copyright_boundary": "abstracted writing principles derived from structure"},
        references=[report.id],
    )
    return storage.write_asset("knowledge", asset)


def build_materials(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    knowledge = _read_previous(storage, "knowledge", input_path)
    asset = MaterialCard(
        title="Suspense production material card",
        source=knowledge.id,
        tags=["material", "suspense", "reusable"],
        content={
            "usable_patterns": knowledge.content.get("principles", []),
            "prompt_fragments": [
                "Design a clue that changes the protagonist's available choices.",
                "End the chapter with a new obligation, not just a question.",
            ],
            "do_not_copy": ["names", "sentences", "unique settings", "plot sequence combinations"],
        },
        metadata={"copyright_boundary": "reusable abstract production material only"},
        references=[knowledge.id],
    )
    return storage.write_asset("materials", asset)


def generate_topic(root: str | Path, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    model = model or MockModelAdapter()
    material = _read_previous(storage, "materials", input_path)
    generated = model.generate("generate a differentiated suspense topic", {"material": material.content})
    asset = TopicSeed(
        title="钟楼回声调查",
        source=material.id,
        tags=["topic", "suspense", "original"],
        content={
            "logline": "A novice investigator tracks a sequence of public signals that expose a hidden civic bargain.",
            "reader_attraction": "mystery clock signal, escalating public stakes, ethical choice pressure",
            "differentiation": "focus on civic memory systems instead of copying any existing detective plot",
            "model_output": generated,
        },
        metadata={"originality_boundary": "new premise generated from abstract materials"},
        references=[material.id],
    )
    return storage.write_asset("topics", asset)


def generate_world(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    topic = _read_previous(storage, "topics", input_path)
    asset = WorldBible(
        title="Echo Clock City World Bible",
        source=topic.id,
        tags=["world", "urban-suspense"],
        content={
            "setting": "A rain-heavy port city where public clocks archive civic announcements and rumors.",
            "rules": ["every public signal has a logged maintainer", "archives are incomplete after a reform year"],
            "conflict_system": "public memory vs private survival",
            "boundaries": "no imported settings or protected unique world elements",
        },
        references=[topic.id],
    )
    return storage.write_asset("worlds", asset)


def generate_characters(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    world = _read_previous(storage, "worlds", input_path)
    asset = CharacterCard(
        title="Lin Qiao character card",
        source=world.id,
        tags=["character", "protagonist"],
        content={
            "role": "novice archive investigator",
            "external_goal": "identify who is manipulating the clock signals",
            "internal_need": "stop treating neutrality as safety",
            "motivation_chain": ["mentor's disgrace", "public accusation", "deadline before archive purge"],
            "risk": "may protect evidence at the cost of personal future",
        },
        references=[world.id],
    )
    return storage.write_asset("characters", asset)


def generate_outline(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    character = _read_previous(storage, "characters", input_path)
    asset = Outline(
        title="Echo Clock three-act outline",
        source=character.id,
        tags=["outline", "three-act"],
        content={
            "acts": [
                {"act": 1, "goal": "discover the clock signal pattern", "turn": "first clue implicates the archive"},
                {"act": 2, "goal": "trace the maintainer network", "turn": "ally is exposed as compromised"},
                {"act": 3, "goal": "force a public reveal", "turn": "protagonist must sacrifice neutrality"},
            ]
        },
        references=[character.id],
    )
    return storage.write_asset("outlines", asset)


def generate_chapter_plan(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    outline = _read_previous(storage, "outlines", input_path)
    asset = ChapterPlan(
        title="Chapter 1 plan",
        source=outline.id,
        tags=["chapter-plan", "chapter-1"],
        content={
            "chapter": 1,
            "objective": "introduce the impossible clock signal and protagonist pressure",
            "beats": [
                "rainy public square signal",
                "protagonist notices archive mismatch",
                "supervisor orders silence",
                "anonymous note predicts next bell",
            ],
            "hook": "the next bell rings from a dismantled tower",
            "quality_targets": ["causal chain", "chapter hook", "originality boundary"],
        },
        references=[outline.id],
    )
    return storage.write_asset("chapter_plans", asset)


def draft(root: str | Path, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    model = model or MockModelAdapter()
    plan = _read_previous(storage, "chapter_plans", input_path)
    generated = model.generate("draft chapter from plan", {"plan": plan.content})
    asset = DraftChapter(
        title="Chapter 1 draft v0",
        source=plan.id,
        tags=["draft", "v0", "mock"],
        content={
            "chapter": 1,
            "text": (
                "雨水把广场的钟声压得很低。林乔抬头时，停用三年的钟楼忽然响了一下。"
                "档案表显示维护员早已离职，但新登记的巡检号正贴在门缝里。"
                "她把纸条塞进口袋，听见第二声钟从城市另一端传来。"
            ),
            "model_output": generated,
            "copyright_boundary": "mock original draft; no reference expression copied",
        },
        references=[plan.id],
    )
    return storage.write_asset("drafts", asset)


def review(root: str | Path, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    model = model or MockModelAdapter()
    draft_asset = _read_previous(storage, "drafts", input_path)
    result = model.review(draft_asset.content.get("text", ""), {"rubric": QUALITY_DIMENSIONS})
    asset = ReviewReport(
        title=f"Review for {draft_asset.title}",
        source=draft_asset.id,
        tags=["review", "quality"],
        content={"rubric": QUALITY_DIMENSIONS, "summary": "mock review completed"},
        score=float(result["score"]),
        strengths=result["strengths"],
        weaknesses=result["weaknesses"],
        issues=result["issues"],
        risk_level=result["risk_level"],
        revision_suggestions=result["revision_suggestions"],
        next_action=result["next_action"],
        references=[draft_asset.id],
    )
    return storage.write_asset("reviews", asset)


def revise(root: str | Path, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    storage = ensure_project(root)
    model = model or MockModelAdapter()
    review_asset = _read_previous(storage, "reviews", input_path)
    result = model.revise("", review_asset.to_dict())
    asset = RevisionPlan(
        title=f"Revision plan for {review_asset.title}",
        source=review_asset.id,
        tags=["revision", "plan"],
        content={
            "steps": result["plan"],
            "target_score": max(80, int(review_asset.score) + 8 if hasattr(review_asset, "score") else 80),
            "must_preserve": ["original premise", "copyright boundary", "chapter hook"],
        },
        references=[review_asset.id],
    )
    return storage.write_asset("reviews", asset)


def import_feedback(root: str | Path, input_path: str) -> Path:
    storage = ensure_project(root)
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"feedback file not found: {path}")
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))
    asset = ReaderFeedback(
        title=path.stem,
        source=str(path),
        tags=["feedback", "reader"],
        content={"rows": rows},
        metadata={"imported_at": utc_now(), "row_count": len(rows)},
    )
    return storage.write_asset("feedback", asset)


def analyze_feedback(root: str | Path, input_path: str | None = None) -> Path:
    storage = ensure_project(root)
    feedback = _read_previous(storage, "feedback", input_path)
    rows = feedback.content.get("rows", [])
    comments = " ".join(row.get("comment", "") for row in rows)
    asset = FeedbackInsight(
        title=f"Insight from {feedback.title}",
        source=feedback.id,
        tags=["feedback", "insight"],
        content={
            "signals": ["reader noticed hook", "motivation pressure should increase"],
            "average_rating": _average_rating(rows),
            "next_generation_constraints": [
                "make motivation pressure explicit by beat 2",
                "preserve high hook clarity",
            ],
            "raw_comment_summary": comments[:240],
        },
        references=[feedback.id],
    )
    return storage.write_asset("feedback", asset)


def _average_rating(rows: list[dict[str, str]]) -> float:
    values: list[float] = []
    for row in rows:
        try:
            values.append(float(row.get("rating", "")))
        except ValueError:
            continue
    return round(sum(values) / len(values), 2) if values else 0.0


def run_pipeline(root: str | Path, sample: bool = False) -> Path:
    storage = ensure_project(root)
    sample_path = storage.root / "examples" / "sample_inputs" / "sample_novel.txt"
    feedback_path = storage.root / "examples" / "sample_inputs" / "sample_feedback.csv"
    outputs = []
    outputs.append(ingest(storage.root, str(sample_path if sample else sample_path)))
    outputs.append(clean(storage.root, str(outputs[-1])))
    outputs.append(decompose(storage.root, str(outputs[-1])))
    outputs.append(extract_knowledge(storage.root, str(outputs[-1])))
    outputs.append(build_materials(storage.root, str(outputs[-1])))
    outputs.append(generate_topic(storage.root, str(outputs[-1])))
    outputs.append(generate_world(storage.root, str(outputs[-1])))
    outputs.append(generate_characters(storage.root, str(outputs[-1])))
    outputs.append(generate_outline(storage.root, str(outputs[-1])))
    outputs.append(generate_chapter_plan(storage.root, str(outputs[-1])))
    outputs.append(draft(storage.root, str(outputs[-1])))
    outputs.append(review(storage.root, str(outputs[-1])))
    outputs.append(revise(storage.root, str(outputs[-1])))
    outputs.append(import_feedback(storage.root, str(feedback_path)))
    outputs.append(analyze_feedback(storage.root, str(outputs[-1])))
    run = WorkflowRun(
        title="sample pipeline run" if sample else "pipeline run",
        source=str(sample_path),
        tags=["pipeline", "sample" if sample else "manual"],
        content={"outputs": [str(path.relative_to(storage.root)) for path in outputs], "status": "completed"},
        metadata={"completed_at": utc_now(), "sample": sample},
        references=[path.name for path in outputs],
    )
    run_path = storage.write_asset("runs", run)
    summary = {
        "run_id": run.id,
        "status": "completed",
        "outputs": [str(path.relative_to(storage.root)) for path in outputs],
        "run_record": str(run_path.relative_to(storage.root)),
    }
    storage.write_json("examples/sample_outputs/pipeline-summary.json", summary)
    final_asset = outputs[-1]
    shutil.copyfile(final_asset, storage.root / "examples" / "sample_outputs" / final_asset.name)
    return run_path


def validate_project(root: str | Path = ".") -> tuple[bool, list[str]]:
    storage = LocalStorage(root)
    errors: list[str] = []
    for category in DATA_DIRS:
        if not (storage.data_root / category).exists():
            errors.append(f"missing data directory: data/{category}")
    for doc in DOC_FILES:
        if not (storage.root / doc).exists():
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
    return not errors, errors
