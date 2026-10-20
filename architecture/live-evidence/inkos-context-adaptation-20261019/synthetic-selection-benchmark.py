from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter


REPRODUCER_PATH = "architecture/live-evidence/inkos-context-adaptation-20261019/synthetic-selection-benchmark.py"


def arguments():
    parser = argparse.ArgumentParser(description="Pure synthetic v8/v9 source-selection comparison; no Provider or database calls.")
    parser.add_argument("--repo-root", type=Path, help="Repository root; defaults to the current repository or this script's repository.")
    parser.add_argument("--output", required=True, type=Path, help="Explicit JSON destination outside the repository.")
    args = parser.parse_args()
    candidates = [args.repo_root] if args.repo_root else [Path.cwd(), *Path.cwd().parents, *Path(__file__).resolve().parents]
    root = next((candidate.expanduser().resolve() for candidate in candidates
                 if (candidate.expanduser() / "src/novel_forge").is_dir()
                 and (candidate.expanduser() / "config/execution_templates/creation_inputs.json").is_file()), None)
    if root is None:
        parser.error("Unable to locate Novel Forge; supply --repo-root.")
    output = args.output.expanduser().resolve()
    if output == root or root in output.parents:
        parser.error("--output must be outside the repository; this reproducer cannot overwrite checked-in evidence.")
    if not output.parent.is_dir():
        parser.error("The --output parent directory must already exist.")
    return root, output


ROOT, OUTPUT = arguments()
SOURCE_FILES = ["src/novel_forge/modules/book_authority/working_task.py", "src/novel_forge/modules/book_authority/task_retrieval.py",
    "src/novel_forge/modules/book_authority/working_selection.py", "src/novel_forge/modules/book_authority/working_prose.py",
    "src/novel_forge/modules/narrative_state/working_memory.py",
    "src/novel_forge/modules/book_authority/manuscript.py", "src/novel_forge/modules/book_authority/manuscript_memory.py",
    "src/novel_forge/modules/chapter_authority/character_references.py",
    "src/novel_forge/modules/chapter_authority/author_editor.py",
    "src/novel_forge/modules/context_builder/task_context.py",
    "src/novel_forge/modules/review/diagnostics.py", "src/novel_forge/modules/story_planning_runtime/domain.py",
    "config/execution_templates/creation_inputs.json"]
SOURCE_SHA256 = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCE_FILES}
sys.path.insert(0, str(ROOT / "src"))

working_prose = importlib.import_module("novel_forge.modules.book_authority.working_prose")
working_selection = importlib.import_module("novel_forge.modules.book_authority.working_selection")
working_task = importlib.import_module("novel_forge.modules.book_authority.working_task")
working_memory = importlib.import_module("novel_forge.modules.narrative_state.working_memory")
author_editor = importlib.import_module("novel_forge.modules.chapter_authority.author_editor")
planning_domain = importlib.import_module("novel_forge.modules.story_planning_runtime.domain")
_project_ranges = working_prose._project_ranges
freeze_source_history = working_prose.freeze_source_history
project_working_sources = working_prose.project_working_sources
working_prose_policy = working_prose.working_prose_policy
select_working_context = working_selection.select_working_context
selected_memory_ranges = working_selection.selected_memory_ranges
build_working_task = working_task.build_working_task
validate_working_task = working_task.validate_working_task
text_hash = author_editor.text_hash
bind_packet_coverage = working_memory.bind_packet_coverage
compile_working_memory = working_memory.compile_working_memory
validate_memory_packet = working_memory.validate_memory_packet
canonical_hash = planning_domain.canonical_hash


CLUE = "林殊交给渡者一枚玄铁鱼符，背面刻着七点红砂；这是前往北岸旧渡口的唯一凭记。"
GOAL = "林殊追查玄铁鱼符背面的七点红砂"
SCENE_GOAL = "林殊寻找北岸旧渡口"
FILLERS = (
    "晨光越过低矮的屋檐，露水沿着叶脉缓缓滑落。远处传来木轮转动的响声，院里的孩子仍在互相追逐。",
    "小街旁的竹篱被昨夜的雨水洗得发亮，店家将新烘的麦饼摆好，墙边的猫伸了一个懒腰。",
    "午后的云影落在田埂上，溪水绕过石头轻轻流去。乡人坐在树荫下面歇脚，鞋底沾着细软的泥土。",
    "傍晚有人推开木窗，灶间慢慢升起炊烟，花盆里的新芽迎着暖风摇动，邻舍的狗趴在门边。",
    "林殊走过小院，听见远处有人轻声唱歌。衣架上的布衫刚刚晾好，几只麻雀从屋顶跳到树梢。",
)
BOOK = {"project_id": "synthetic:project", "book_id": "synthetic:book", "book_run_id": "synthetic:run",
        "workspace_id": "synthetic:workspace", "input_snapshot_id": "synthetic:input-snapshot"}


def han(character):
    return "\u4e00" <= character <= "\u9fff"


def paragraph(number, index):
    prefix = CLUE if number == 1 and index == 12 else "林殊又走过一段普通的路。"
    repeated = prefix + FILLERS[(number + index) % len(FILLERS)] * 10
    count = 0
    for end, character in enumerate(repeated, 1):
        count += han(character)
        if count == 200:
            return repeated[:end] + "。"
    raise AssertionError("not enough deterministic filler")


def source(number):
    separator = ("", "\n\n", "\n", "\r\n")[number % 4]
    text = separator.join(paragraph(number, index) for index in range(25))
    version = f"synthetic:draft:{number}"
    content_hash = canonical_hash({"text": text})
    pointer = {"asset_version_id": version, "content_hash": content_hash}
    return {"chapter": number, **pointer, "text_hash": text_hash(text), "text": text,
            "observations": None, "memory_provenance": {"status": "MISSING"},
            "source_resolution": {"native_basis": "NATIVE_DRAFT_OUTPUT",
                                  "native_source": pointer, "effective_source": pointer, "overrides": []}}


def find_policy(value):
    if isinstance(value, dict):
        if "working_prose_policy" in value:
            return value["working_prose_policy"]
        for child in value.values():
            found = find_policy(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_policy(child)
            if found is not None:
                return found
    return None


def task_for(chapter):
    plan = {"chapter_number": chapter, "chapter_intent": GOAL,
            "scene_plan": [{"scene_id": "synthetic:current-scene", "goal": SCENE_GOAL,
                            "participants": ["synthetic:lin-shu"], "pov_character_id": "synthetic:lin-shu"}]}
    cast = {"book_id": BOOK["book_id"], "characters": [{"character_id": "synthetic:lin-shu", "name": "林殊", "aliases": ["小林"]}]}
    sources = [{"asset_version_id": f"synthetic:chapter-plan:{chapter}", "asset_type": "chapter_plan", "content": plan, "content_hash": canonical_hash(plan)},
               {"asset_version_id": "synthetic:cast:1", "asset_type": "character_cast", "content": cast, "content_hash": canonical_hash(cast)}]
    task = build_working_task(sources=sources, book=BOOK, chapter=chapter, stage="CHAPTER", extra_queries=[])
    validate_working_task(task, sources=sources, book=BOOK, chapter=chapter, stage="CHAPTER", extra_queries=[])
    return task


def measure(sources, chapter, policy, task):
    started = perf_counter()
    selection = None
    is_v9 = policy["version"] == "working-prose-projection.v9"
    frozen_sources = None
    if is_v9:
        frozen_sources = {row["asset_version_id"]: {
            "version": working_memory.FROZEN_MEMORY_SOURCE_VERSION, "kind": "WRITER_SELF_OBSERVATION",
            "asset_version_id": row["asset_version_id"], "content_hash": row["content_hash"],
            "observations_hash": canonical_hash(row["observations"])} for row in sources}
        selection = select_working_context(sources, target_chapter=chapter, policy=policy, task=task)
    packet = compile_working_memory(sources, queries=[], max_characters=None, dependency_closed=True,
        recent_complete_from=chapter-policy["recent_complete_chapters"],
        **({"task": task, "selected_ranges": selected_memory_ranges(selection), "frozen_sources": frozen_sources} if is_v9 else {}))
    if is_v9:
        selection = select_working_context(sources, target_chapter=chapter, policy=policy, task=task, memory=packet)
        projected = _project_ranges(sources, {(row["chapter"], row["start"], row["end"]) for row in selection["passages"]},
                                    passage_characters=policy["passage_characters"])
    else:
        projected = project_working_sources(sources, target_chapter=chapter, policy=policy, memory=packet)
    packet = bind_packet_coverage(packet, projected)
    history = freeze_source_history(projected, book=BOOK, target_chapter=chapter)
    elapsed = perf_counter() - started
    validate_memory_packet(packet, projected)
    assert packet["entries"] == []
    assert all(row["status"] == "MISSING" for row in packet["source_coverage"])
    assert history["source_count"] == chapter - 1
    if is_v9:
        assert all(row["memory_source"] == frozen_sources[row["asset_version_id"]] for row in packet["source_coverage"])
    visible = [row for row in projected if row["passages"]]
    original = sources[0]["text"]
    clue_start = original.index(CLUE)
    clue_end = clue_start + len(CLUE)
    clue_passages = [{"start": passage["start"], "end": passage["end"]}
                     for passage in projected[0]["passages"] if passage["start"] <= clue_start and clue_end <= passage["end"]]
    result = {"policy": policy["version"], "target_chapter": chapter,
              "full_historical_source_characters": sum(len(row["text"]) for row in sources),
              "full_historical_han_characters": sum(sum(han(character) for character in row["text"]) for row in sources),
              "selected_prose_characters": sum(len(passage["text"]) for row in visible for passage in row["passages"]),
              "selected_source_chapters": [row["chapter"] for row in visible],
              "selected_passage_count": sum(len(row["passages"]) for row in visible),
              "host_source_identity_count": history["source_count"],
              "frozen_memory_source_reference_count": sum("memory_source" in row for row in packet["source_coverage"]),
              "memory_entry_count": len(packet["entries"]), "missing_memory_sources": len(packet["source_coverage"]),
              "old_clue_quote_recalled": bool(clue_passages), "old_clue_original_ranges": clue_passages,
              "elapsed_seconds_single_run": round(elapsed, 6),
              "source_history_hash": history["content_hash"],
              "selected_prose_hash": canonical_hash([{key: row[key] for key in ("chapter", "asset_version_id", "passages")} for row in visible])}
    if is_v9:
        result.update(task_hash=task["task_hash"], selection_hash=selection["selection_hash"],
                      index_unit_count=selection["retrieval"]["input_unit_count"],
                      lexical_candidate_count=selection["retrieval"]["candidate_count"],
                      historical_retrieval_hits=len(selection["retrieval"]["selected"]),
                      semantic_completeness=selection["retrieval"]["semantic_completeness"],
                      old_clue_hit_queries=[hit["matched_queries"] for hit in selection["retrieval"]["selected"]
                          if hit["chapter"] == 1 and hit["start"] <= clue_start and clue_end <= hit["end"]])
    return result


def main():
    corpus_started = perf_counter()
    corpus = [source(chapter) for chapter in range(1, 601)]
    build_seconds = perf_counter() - corpus_started
    assert all(sum(han(character) for character in row["text"]) == 5000 for row in corpus)
    assert sum(row["text"].count(CLUE) for row in corpus) == 1
    v8 = {"version": "working-prose-projection.v8", "history_chapters": 128, "recent_complete_chapters": 2,
          "max_characters": None, "queries": [], "guidance_mode": "COMBINED"}
    v9 = find_policy(json.loads((ROOT/"config/execution_templates/creation_inputs.json").read_text()))
    assert v9["version"] == "working-prose-projection.v9" and v9["queries"] == []
    for policy in (v8, v9):
        working_prose_policy({"working_prose_policy": policy})
    results = []
    for chapter in (21, 130, 600):
        task = task_for(chapter)
        sources = corpus[:chapter-1]
        for policy in (v8, v9):
            row = measure(sources, chapter, policy, task)
            results.append(row)
            print(json.dumps({key: row[key] for key in ("policy", "target_chapter", "full_historical_source_characters",
                "selected_prose_characters", "host_source_identity_count", "old_clue_quote_recalled", "elapsed_seconds_single_run")}), flush=True)
    source_sha256_after = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    assert source_sha256_after == SOURCE_SHA256, "Implementation/config changed during the run; rerun to bind stable source identities"
    old_start = corpus[0]["text"].index(CLUE)
    report = {"record_type": "SYNTHETIC_SOURCE_SELECTION_COMPARISON", "authority": "NOT_RUNTIME_AUTHORITY",
        "created_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
        "reproducer": {"path": REPRODUCER_PATH, "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "reproduce": f"PYTHONHASHSEED=0 python {REPRODUCER_PATH} --repo-root . --output /tmp/novel-forge-synthetic-selection.json",
        "reproduce_environment": "Run from the repository root with its Python dependencies installed; output must be outside that repository.",
        "executed_command": [sys.executable, *sys.argv], "executed_repo_root": str(ROOT), "executed_output": str(OUTPUT),
        "source_sha256": SOURCE_SHA256, "source_identity_stable_during_run": True,
        "dataset": {"chapters": len(corpus), "han_characters_per_chapter": 5000,
            "unicode_codepoints_min": min(len(row["text"]) for row in corpus), "unicode_codepoints_max": max(len(row["text"]) for row in corpus),
            "unicode_codepoints_total": sum(len(row["text"]) for row in corpus),
            "source_texts_hash": canonical_hash([row["text_hash"] for row in corpus]),
            "construction_elapsed_seconds": round(build_seconds, 6),
            "paragraph_layouts": {"chapter_mod_4_0": "no newline, one overlong paragraph", "chapter_mod_4_1": "blank lines",
                                  "chapter_mod_4_2": "single newline", "chapter_mod_4_3": "CRLF"},
            "memory": "All source observations are absent and explicitly report MISSING; v9 freezes every synthetic writer-source reference and observations digest",
            "source_identity_kind": "Synthetic source/version/hash pointers only; no native delivery or database source resolution was performed",
            "old_clue": {"chapter": 1, "paragraph_one_based": 13, "line_one_based": corpus[0]["text"][:old_start].count("\n")+1,
                         "start": old_start, "end": old_start+len(CLUE), "quote": CLUE, "occurrences_in_corpus": 1}},
        "fixed_task": {"chapter_intent": GOAL, "scene_goal": SCENE_GOAL, "participants": ["synthetic:lin-shu"],
            "frozen_name": "林殊", "extra_queries": [], "stage": "CHAPTER",
            "scope_note": "Demand text is identical; target Chapter and its exact synthetic ChapterPlan source identity change together as required by the frozen-task contract. V8 does not consume the new task field."},
        "policies": {"v8_reviewed_default": v8, "v9_current_template": v9},
        "comparison_scope": "Both policies execute the current hashed code. This compares reviewed v8 defaults with current v9 defaults plus its frozen task; it does not isolate the contribution of each changed setting.",
        "timing_scope": "Single local run per pair, including memory compilation, selection/materialization and host history freeze. V9 performs the existing two selection passes around optional memory. Excludes corpus/task construction, source/UoW DB reads, final provider rendering, capacity admission, transport and model execution.",
        "results": results,
        "evidence_limits": ["Synthetic repeated Chinese filler and one deliberately distinctive lexical clue are not a representative retrieval-quality corpus.",
            "Reported character counts are Unicode codepoints, not Provider tokens, billing cost or the complete prompt size.",
            "The full 600-chapter corpus exists locally for reproducibility; each target receives only its actual predecessor prefix.",
            "Host identity preservation is metadata provenance; it does not mean omitted original prose reached a model.",
            "This synthetic run performs no PostgreSQL, real Provider request, literary evaluation, author acceptance or semantic-completeness proof.",
            "These timings are single runs in a shared environment, not production latency or a statistical performance qualification."]}
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(str(OUTPUT), flush=True)


if __name__ == "__main__":
    main()
