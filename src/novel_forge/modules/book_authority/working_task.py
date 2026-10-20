from __future__ import annotations

from typing import Any, Mapping, Sequence
import re

from novel_forge.modules.chapter_authority.character_references import compile_character_references
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.task_context import task_references
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


WORKING_TASK_VERSION = "working-retrieval-task.v1"
CURRENT_WORKING_TASK_VERSION = "working-retrieval-task.v6"
DELIVERY_WORKING_TASK_VERSIONS = frozenset({"working-retrieval-task.v3", "working-retrieval-task.v4", "working-retrieval-task.v5", CURRENT_WORKING_TASK_VERSION})
STATEFUL_WORKING_TASK_VERSIONS = frozenset({"working-retrieval-task.v2", *DELIVERY_WORKING_TASK_VERSIONS})
TASK_DELIVERY_CONTRACT = "source-bound-full-provider-request.v1"
WORKING_TASK_AUTHORITY = "FROZEN_PLAN_RETRIEVAL_ONLY"
_PLAN_TYPES = frozenset({"chapter_plan", "chapter_group_plan", "arc_plan"})
_SOURCE_TYPES = _PLAN_TYPES | {"character_cast"}
_CURRENT_SOURCE_TYPES = _SOURCE_TYPES | {"volume_plan"}
_LIST_FIELDS = ("queries", "subjects", "event_refs", "object_refs", "place_refs")
_TEXT_FIELDS = ("conflict", "stakes", "premise", "ending_hook", "entry_state", "exit_state")
_EVENT_TEXT_FIELDS = ("action", "motivation", "resistance", "decision", "consequence", "stakes")
_REFERENCE_FIELDS = {
    "subjects": ("participants", "pov_character_id", "character_id", "character_ids", "actor_id", "actor_ref", "linked_character_ids"),
    "event_refs": ("event_id", "event_refs", "required_event_ids", "required_event_refs", "required_source_event_ids", "source_event_id", "cause_refs", "causes", "realization_event_ids"),
    "object_refs": ("object_id", "object_ids", "object_refs"),
    "place_refs": ("location_id", "location_ids", "location_refs", "place_id", "place_ids", "place_refs"),
}


def _invalid(message: str) -> KernelError:
    return KernelError("WORKING_TASK_INVALID", message)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _invalid(f"{field} requires a nonempty exact string")
    return value


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise _invalid(f"{field} requires a string collection")
    return list(dict.fromkeys(_required_string(item, field) for item in value))


def _scope(book: Mapping[str, Any], chapter: int, stage: str) -> dict[str, Any]:
    if not isinstance(book, Mapping) or not isinstance(chapter, int) or isinstance(chapter, bool) or chapter <= 0 or not isinstance(stage, str) or stage not in {"PLANNING", "CHAPTER"}:
        raise _invalid("working task requires a Book, positive Chapter and explicit Planning or Chapter stage")
    return {**{key: _required_string(book.get(key), key) for key in ("project_id", "book_id", "book_run_id")},
            "target_chapter": chapter, "stage": stage}


def _source(source: Mapping[str, Any], book: Mapping[str, Any], *, current: bool = False) -> tuple[dict[str, str], Mapping[str, Any], str]:
    if not isinstance(source, Mapping) or not isinstance(source.get("content"), Mapping):
        raise _invalid("working task sources require exact frozen plan content")
    binding = {key: _required_string(source.get(key), key) for key in ("asset_version_id", "content_hash", "asset_type")}
    content = source["content"]
    if current and canonical_hash(content) != binding["content_hash"]:
        raise _invalid("Current task source failed its frozen digest")
    for key in ("project_id", "book_id"):
        if key in content and content[key] != book[key]:
            raise _invalid("working task source belongs to another Book scope")
    kind = binding["asset_type"]
    generator = content.get("generator_operation_name")
    generated_kind = generator.removesuffix(".generate") if isinstance(generator, str) and generator.endswith(".generate") else ""
    if generated_kind == "character.cast":
        generated_kind = "character_cast"
    if kind == "planning_generation_candidate":
        kind = generated_kind
    if kind not in (_CURRENT_SOURCE_TYPES if current else _SOURCE_TYPES) or generated_kind and generated_kind != kind:
        raise _invalid("working task source must identify an exact supported frozen Plan or cast kind")
    binding["plan_kind"] = kind
    markers = {"chapter_plan": ("chapter_number", "chapter"), "chapter_group_plan": ("chapter_function_matrix",),
               "arc_plan": ("arc_segments", "objective", "target_window"), "character_cast": ("characters",), "volume_plan": ("narrative_segments", "chapter_range")}[kind]
    pointer = ""
    if not any(key in content for key in markers) and isinstance(content.get("candidate_payload"), Mapping):
        content = content["candidate_payload"]
        pointer = "/candidate_payload"
    return binding, content, pointer


def _in_window(value: Mapping[str, Any], chapter: int) -> bool | None:
    window = value.get("target_window")
    if isinstance(window, Mapping):
        start = window.get("from_chapter", window.get("start_chapter"))
        end = window.get("to_chapter", window.get("end_chapter"))
    elif "chapter_range" in value:
        boundaries = value["chapter_range"]
        if not isinstance(boundaries, (list, tuple)) or len(boundaries) != 2:
            raise _invalid("task source chapter range requires two exact boundaries")
        start, end = boundaries
    else:
        return None
    if start is None and end is None:
        return None
    if any(not isinstance(item, int) or isinstance(item, bool) for item in (start, end)) or start <= 0 or end < start:
        raise _invalid("task source chapter window requires ordered positive integers")
    return start <= chapter <= end


def _current_rows(kind: str, content: Mapping[str, Any], pointer: str, chapter: int) -> list[tuple[Mapping[str, Any], str]]:
    if kind == "chapter_plan":
        number = content.get("chapter_number", content.get("chapter"))
        if not isinstance(number, int) or isinstance(number, bool) or number != chapter:
            raise _invalid("ChapterPlan task source must match the exact target Chapter")
        if "chapter" in content and content["chapter"] != number:
            raise _invalid("ChapterPlan task source has conflicting Chapter identities")
        return [(content, pointer)]
    if kind == "volume_plan":
        if _in_window(content, chapter) is not True:
            raise _invalid("Volume task source must contain the current Chapter")
        segments = content.get("narrative_segments")
        if segments is None:
            return [(content, pointer)]
        if not isinstance(segments, list):
            raise _invalid("Volume task segments require their frozen ordered rows")
        rows = [(row, f"{pointer}/narrative_segments/{index}") for index, row in enumerate(segments)
                if isinstance(row, Mapping) and _in_window(row, chapter) is True]
        if len(rows) != 1:
            raise _invalid("Volume task must bind exactly one current narrative segment")
        return rows
    if kind == "chapter_group_plan":
        if _in_window(content, chapter) is False:
            raise _invalid("ChapterGroup task source lies outside the target Chapter")
        matrix = content.get("chapter_function_matrix")
        if not isinstance(matrix, list):
            raise _invalid("ChapterGroup task source requires its frozen Chapter function matrix")
        rows = [(row, f"{pointer}/chapter_function_matrix/{index}") for index, row in enumerate(matrix)
                if isinstance(row, Mapping) and type(row.get("chapter_number")) is int and row["chapter_number"] == chapter]
        if len(rows) != 1:
            raise _invalid("ChapterGroup task source must bind exactly one current Chapter row")
        return rows
    return []


class _TaskFields:
    def __init__(self, field_sources: list[dict[str, str]], asset_version_id: str, scene_id: str = "") -> None:
        self.values: dict[str, list[str]] = {key: [] for key in ("goal", *_LIST_FIELDS)}
        self.field_sources = field_sources
        self.asset_version_id = asset_version_id
        self.scene_id = scene_id

    def add(self, field: str, value: Any, pointer: str, *, source_text: str | None = None) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        text = value.strip()
        if text not in self.values[field]:
            self.values[field].append(text)
        evidence = {"asset_version_id": self.asset_version_id, "pointer": pointer, "field": field, "scene_id": self.scene_id, "text": value if source_text is None else source_text}
        if evidence not in self.field_sources:
            self.field_sources.append(evidence)

    def refs(self, content: Mapping[str, Any], pointer: str) -> None:
        for field, keys in _REFERENCE_FIELDS.items():
            for key in keys:
                if key not in content:
                    continue
                value = content[key]
                values = enumerate(value) if isinstance(value, (list, tuple)) else [(None, value)]
                for index, item in values:
                    location = f"{pointer}/{key}" + (f"/{index}" if index is not None else "")
                    if isinstance(item, str):
                        refs = task_references({"entity_ids": [item]})
                        for ref in sorted(refs):
                            self.add(field, ref, location)
                    elif isinstance(item, Mapping):
                        for reference_key in ("entity_id", "character_id", "actor_id", "event_id", "source_event_id", "entity_key"):
                            raw = item.get(reference_key)
                            if isinstance(raw, str):
                                for ref in sorted(task_references({reference_key: raw})):
                                    self.add(field, ref, f"{location}/{reference_key}", source_text=raw)

    def extract(self, content: Mapping[str, Any], pointer: str, *, goals: tuple[str, ...] = ("chapter_intent", "objective", "goal"), texts: tuple[str, ...] = _TEXT_FIELDS) -> None:
        for key in goals:
            self.add("goal", content.get(key), f"{pointer}/{key}")
        for key in texts:
            self.add("queries", content.get(key), f"{pointer}/{key}")
        queries = content.get("queries")
        if isinstance(queries, (list, tuple)):
            for index, query in enumerate(queries):
                self.add("queries", query, f"{pointer}/queries/{index}")
        self.refs(content, pointer)

    def export(self) -> dict[str, Any]:
        return {"goal": "\n".join(self.values["goal"]), **{key: list(self.values[key]) for key in _LIST_FIELDS}}


def _events(fields: _TaskFields, value: Any, pointer: str, chapter: int, *, inherited_chapter: bool = False) -> None:
    if not isinstance(value, list):
        return
    for index, event in enumerate(value):
        event_pointer = f"{pointer}/{index}"
        if isinstance(event, str) and inherited_chapter:
            fields.add("queries", event, event_pointer)
        elif isinstance(event, Mapping):
            number = event.get("chapter_number", chapter if inherited_chapter else None)
            if type(number) is int and number == chapter:
                fields.extract(event, event_pointer, goals=(), texts=_EVENT_TEXT_FIELDS)


def _bind_character_subjects(task: dict[str, Any], sources: list[tuple[dict[str, str], Mapping[str, Any], str]], book: Mapping[str, Any]) -> None:
    casts = [(binding, content, pointer) for binding, content, pointer in sources if binding["plan_kind"] == "character_cast"]
    if not casts:
        return
    if len(casts) != 1:
        raise _invalid("working task must bind one exact frozen Book cast")
    binding, cast, pointer = casts[0]
    characters = cast.get("characters")
    if not isinstance(characters, list) or any(not isinstance(row, Mapping) for row in characters):
        raise _invalid("frozen task cast requires typed character rows")
    references = compile_character_references(project_id=book["project_id"],
        workspace_id=_required_string(book.get("workspace_id"), "workspace_id"), book_id=book["book_id"],
        snapshot_id=_required_string(book.get("input_snapshot_id"), "input_snapshot_id"),
        cast_version_id=binding["asset_version_id"], cast_content_hash=binding["content_hash"], cast=cast, scenes=None)
    tokens = references["token_bindings"]
    for scope in [task, *task["scenes"]]:
        if task["contract_version"] in STATEFUL_WORKING_TASK_VERSIONS:
            text_fields = [field for field in list(task["field_sources"]) if field["scene_id"] == scope.get("scene_id", "") and field["field"] in {"goal", "queries"}]
            for field in text_fields:
                matches = []
                for token in sorted(tokens, key=lambda item: (-len(item), item)):
                    if len(token) < 2 and field["text"].strip() != token:
                        continue
                    pattern = re.escape(token) if re.search(r"[\u3400-\u9fff]", token) else r"(?<![\w])" + re.escape(token) + r"(?![\w])"
                    for match in re.finditer(pattern, field["text"]):
                        if any(low <= match.start() and match.end() <= high for low, high in matches):
                            continue
                        matches.append(match.span())
                        if token not in scope["subjects"]:
                            scope["subjects"].append(token)
                        evidence = {**field, "field": "subjects"}
                        if evidence not in task["field_sources"]:
                            task["field_sources"].append(evidence)
        selected_ids = {tokens[token] for token in scope["subjects"] if token in tokens}
        fields = _TaskFields(task["field_sources"], binding["asset_version_id"], scope.get("scene_id", ""))
        for index, row in enumerate(characters):
            identity = row["character_id"]
            if identity not in selected_ids:
                continue
            for key in ("character_id", "name"):
                if tokens.get(row[key]) == identity:
                    fields.add("subjects", row[key], f"{pointer}/characters/{index}/{key}")
            for alias_index, alias in enumerate(row.get("aliases", [])):
                if tokens.get(alias) == identity:
                    fields.add("subjects", alias, f"{pointer}/characters/{index}/aliases/{alias_index}")
        scope["subjects"] = list(dict.fromkeys([*scope["subjects"], *fields.values["subjects"]]))


def build_working_task(*, sources: Sequence[Mapping[str, Any]], book: Mapping[str, Any], chapter: int,
                       stage: str, extra_queries: Sequence[str] = (), version: str = WORKING_TASK_VERSION) -> dict[str, Any]:
    scope = _scope(book, chapter, stage)
    if version not in {WORKING_TASK_VERSION, *STATEFUL_WORKING_TASK_VERSIONS}:
        raise _invalid("Unknown working task algorithm")
    explicit_queries = _strings(extra_queries, "extra_queries")
    if not isinstance(sources, (list, tuple)):
        raise _invalid("working task sources require a collection of exact frozen Plans")
    normalized = sorted((_source(source, book, current=version in STATEFUL_WORKING_TASK_VERSIONS) for source in sources), key=lambda item: item[0]["asset_version_id"])
    identities = [binding["asset_version_id"] for binding, _, _ in normalized]
    if len(identities) != len(set(identities)):
        raise _invalid("working task source identities must be unique")
    fields: list[dict[str, str]] = []
    task: dict[str, Any] = {"contract_version": version, "authority": WORKING_TASK_AUTHORITY, **scope,
                            "goal": "", **{key: [] for key in _LIST_FIELDS}, "explicit_queries": explicit_queries,
                            "scenes": [], "sources": [binding for binding, _, _ in normalized], "field_sources": fields}
    if version in STATEFUL_WORKING_TASK_VERSIONS:
        task["handoff_predecessor"] = chapter - 1
    if version in DELIVERY_WORKING_TASK_VERSIONS:
        task["delivery_contract"] = TASK_DELIVERY_CONTRACT
    task["queries"] = list(explicit_queries)
    current = [(binding, content, pointer, _current_rows(binding["plan_kind"], content, pointer, chapter))
               for binding, content, pointer in normalized]
    segment_refs = {(ref.get("volume_plan_version_id"), ref.get("segment_id"))
                    for _, content, _, rows in current if rows
                    if isinstance((ref := content.get("narrative_segment_ref")), Mapping)
                    and isinstance(ref.get("volume_plan_version_id"), str) and isinstance(ref.get("segment_id"), str)}
    segment_refs.update((binding["asset_version_id"], row.get("segment_id"))
        for binding, _, _, rows in current if binding["plan_kind"] == "volume_plan" for row, _ in rows if row.get("segment_id"))
    demand_kinds = None
    if version in {"working-retrieval-task.v5", "working-retrieval-task.v6"}:
        demand_kinds = next(({kind} for kind in ("chapter_plan", "chapter_group_plan")
            if any(binding["plan_kind"] == kind and rows for binding, _, _, rows in current)), None)
    goals: list[str] = []
    for binding, content, pointer, rows in current:
        if demand_kinds is not None and binding["plan_kind"] not in demand_kinds:
            continue
        selected = _TaskFields(fields, binding["asset_version_id"])
        if binding["plan_kind"] == "arc_plan":
            in_window = _in_window(content, chapter)
            if in_window is not False:
                for index, segment in enumerate(content.get("arc_segments") or ()):
                    if not isinstance(segment, Mapping):
                        continue
                    segment_window = _in_window(segment, chapter)
                    bound_segment = (segment.get("volume_plan_version_id"), segment.get("narrative_segment_id")) in segment_refs
                    if segment_window is True or bound_segment and segment_window is not False:
                        rows.append((segment, f"{pointer}/arc_segments/{index}"))
                if not rows and in_window is True:
                    selected.extract(content, pointer, goals=("objective",), texts=())
        for row, row_pointer in rows:
            if version in {"working-retrieval-task.v5", "working-retrieval-task.v6"} and binding["plan_kind"] == "chapter_group_plan":
                selected.extract(row, row_pointer, goals=("chapter_intent", "objective", "goal", "primary_function"))
                for index, function in enumerate(row.get("secondary_functions") or ()):
                    selected.add("queries", function, f"{row_pointer}/secondary_functions/{index}")
            else:
                selected.extract(row, row_pointer)
            for key in ("required_state_delta", "exit_state_spec"):
                if isinstance(row.get(key), Mapping):
                    selected.add("queries", row[key].get("summary"), f"{row_pointer}/{key}/summary")
            for index, participant in enumerate(row.get("character_participation") or ()):
                if isinstance(participant, Mapping):
                    selected.refs(participant, f"{row_pointer}/character_participation/{index}")
            for index, scene in enumerate(row.get("scene_plan") or ()):
                if not isinstance(scene, Mapping):
                    raise _invalid("Chapter task scenes require addressable objects")
                scene_id = _required_string(scene.get("scene_id"), "scene_id")
                if scene_id in {item["scene_id"] for item in task["scenes"]}:
                    raise _invalid("working task scenes require unique identities")
                scene_fields = _TaskFields(fields, binding["asset_version_id"], scene_id)
                scene_fields.extract(scene, f"{row_pointer}/scene_plan/{index}")
                task["scenes"].append({"scene_id": scene_id, **scene_fields.export()})
            _events(selected, row.get("required_events"), f"{row_pointer}/required_events", chapter, inherited_chapter=True)
            realization = row.get("narrative_realization_slice")
            if isinstance(realization, Mapping) and realization.get("chapter_number", chapter) == chapter:
                _events(selected, realization.get("events"), f"{row_pointer}/narrative_realization_slice/events", chapter, inherited_chapter=True)
        if binding["plan_kind"] == "chapter_group_plan":
            _events(selected, content.get("narrative_event_chain"), f"{pointer}/narrative_event_chain", chapter)
        for goal in selected.values["goal"]:
            if goal not in goals:
                goals.append(goal)
        for key in _LIST_FIELDS:
            task[key] = list(dict.fromkeys([*task[key], *selected.values[key]]))
    task["goal"] = "\n".join(goals)
    _bind_character_subjects(task, normalized, book)
    if version in STATEFUL_WORKING_TASK_VERSIONS and not (task["goal"] or task["queries"] or task["scenes"]):
        raise _invalid("Current task requires native demand; retain historical empty tasks only through their original version")
    task["task_hash"] = canonical_hash(task)
    return task


def validate_working_task(task: Mapping[str, Any], *, book: Mapping[str, Any], chapter: int, stage: str,
                          sources: Sequence[Mapping[str, Any]] | None = None,
                          extra_queries: Sequence[str] | None = None) -> None:
    scope = _scope(book, chapter, stage)
    current = isinstance(task, Mapping) and task.get("contract_version") in STATEFUL_WORKING_TASK_VERSIONS
    source_types = _CURRENT_SOURCE_TYPES if current else _SOURCE_TYPES
    keys = {"contract_version", "authority", *scope, "goal", *_LIST_FIELDS, "explicit_queries", "scenes", "sources", "field_sources", "task_hash"} | ({"handoff_predecessor"} if current else set()) | ({"delivery_contract"} if task.get("contract_version") in DELIVERY_WORKING_TASK_VERSIONS else set())
    if not isinstance(task, Mapping) or set(task) != keys or task.get("contract_version") not in {WORKING_TASK_VERSION, *STATEFUL_WORKING_TASK_VERSIONS} or task.get("authority") != WORKING_TASK_AUTHORITY:
        raise _invalid("working task requires the frozen retrieval-only contract")
    if task.get("contract_version") in DELIVERY_WORKING_TASK_VERSIONS and task.get("delivery_contract") != TASK_DELIVERY_CONTRACT:
        raise _invalid("Current task requires its complete source-bound request delivery contract")
    if current and (type(task.get("handoff_predecessor")) is not int or task["handoff_predecessor"] != chapter - 1):
        raise _invalid("Working task handoff must bind the exact delivered predecessor")
    if any(task.get(key) != value or type(task.get(key)) is not type(value) for key, value in scope.items()):
        raise _invalid("working task belongs to another Book, Chapter or stage")
    for value in [task, *task["scenes"]] if isinstance(task["scenes"], list) else []:
        if not isinstance(value, Mapping) or not isinstance(value.get("goal"), str):
            raise _invalid("working task requires text goals and typed scene fields")
        for key in _LIST_FIELDS:
            if _strings(value.get(key), key) != value[key]:
                raise _invalid("working task selectors must be unique exact strings")
    if not isinstance(task["scenes"], list) or any(set(scene) != {"scene_id", "goal", *_LIST_FIELDS} for scene in task["scenes"]):
        raise _invalid("working task scenes have an invalid contract")
    scene_ids = [_required_string(scene.get("scene_id"), "scene_id") for scene in task["scenes"]]
    if len(scene_ids) != len(set(scene_ids)):
        raise _invalid("working task scene identities must be unique")
    if _strings(task["explicit_queries"], "explicit_queries") != task["explicit_queries"]:
        raise _invalid("working task explicit queries must be unique exact strings")
    if extra_queries is not None and _strings(extra_queries, "extra_queries") != task["explicit_queries"]:
        raise _invalid("working task explicit queries differ from the frozen policy")
    if not isinstance(task["sources"], list) or not isinstance(task["field_sources"], list):
        raise _invalid("working task requires source and field provenance collections")
    source_ids = []
    for binding in task["sources"]:
        if not isinstance(binding, Mapping) or set(binding) != {"asset_version_id", "content_hash", "asset_type", "plan_kind"}:
            raise _invalid("working task source identity contract is invalid")
        source_ids.append(_required_string(binding.get("asset_version_id"), "asset_version_id"))
        for key in ("content_hash", "asset_type", "plan_kind"):
            _required_string(binding.get(key), key)
        if binding["plan_kind"] not in source_types or binding["asset_type"] not in {*source_types, "planning_generation_candidate"} or binding["asset_type"] != "planning_generation_candidate" and binding["asset_type"] != binding["plan_kind"]:
            raise _invalid("working task source kind is invalid")
    if source_ids != sorted(set(source_ids)):
        raise _invalid("working task sources require ordered unique identities")
    for field in task["field_sources"]:
        if not isinstance(field, Mapping) or set(field) != {"asset_version_id", "pointer", "field", "scene_id", "text"} or any(not isinstance(item, str) for item in field.values()) or field["asset_version_id"] not in source_ids or field["field"] not in {"goal", *_LIST_FIELDS} or field["scene_id"] not in {"", *scene_ids}:
            raise _invalid("working task field provenance is invalid")
        if not isinstance(field["pointer"], str) or not field["pointer"].startswith("/") or not isinstance(field["text"], str) or not field["text"].strip():
            raise _invalid("working task field provenance requires an exact source pointer and text")
    if task.get("task_hash") != canonical_hash({key: value for key, value in task.items() if key != "task_hash"}):
        raise _invalid("working task hash differs from its frozen demand and source identities")
    if sources is not None:
        expected = build_working_task(sources=sources, book=book, chapter=chapter, stage=stage, extra_queries=task["explicit_queries"], version=task["contract_version"])
        if dict(task) != expected:
            raise _invalid("working task differs from its exact frozen Plan source fields")
