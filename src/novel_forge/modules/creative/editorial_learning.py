from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.story_design_authority.author_input import (
    TARGETS,
    author_binding_from_inputs,
    compile_planning_author_projection,
    text_hash,
    validate_author_design,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise KernelError("EDITORIAL_LEARNING_INPUT_INVALID", message)


def validate_editorial_learning(raw: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(raw, Mapping) and set(raw) == {"contract_version", "book_id", "version", "evidence_class", "reader_promise", "decisions"}, "Editorial learning requires versioned author decisions and a Book boundary")
    _require(raw["contract_version"] == "editorial-learning.v1" and raw["evidence_class"] in {"OPERATOR_AUTHORED_INPUT", "AI_ASSISTED_AUTHOR_INPUT"}, "Editorial discussion is author intent, not model qualification or Canon")
    _require(all(isinstance(raw[k], str) and 0 < len(raw[k].strip()) <= 2000 for k in ("book_id", "version", "reader_promise")), "Editorial learning needs a bounded identity and reading promise")
    decisions = raw["decisions"]
    _require(isinstance(decisions, list) and 0 < len(decisions) <= 12, "Editorial decisions must be bounded")
    seen: set[str] = set()
    hashes: dict[str, str] = {}
    active = False
    for item in decisions:
        _require(isinstance(item, Mapping) and set(item) == {"decision_id", "choice", "finding", "application", "reader_effect", "tradeoff", "targets", "chapter_range", "knowledge_cards"}, "Each editorial decision needs a finding, original application, reading effect, tradeoff and exact knowledge versions")
        _require(all(isinstance(item[k], str) and 0 < len(item[k].strip()) <= 2000 for k in ("decision_id", "finding", "application", "reader_effect", "tradeoff")), "Editorial decisions need bounded explanations")
        _require(item["decision_id"] not in seen and item["choice"] in {"KEEP", "ADAPT", "AVOID", "DEFER"}, "Editorial decisions must have distinct identities and explicit choices")
        seen.add(item["decision_id"])
        targets, bounds, cards = item["targets"], item["chapter_range"], item["knowledge_cards"]
        _require(isinstance(targets, list) and bool(targets) and all(isinstance(t, str) for t in targets) and len(set(targets)) == len(targets) and set(targets) <= TARGETS, "Editorial decisions require governed creation stages")
        _require(isinstance(bounds, list) and len(bounds) == 2 and all(type(n) is int for n in bounds) and 1 <= bounds[0] <= bounds[1] <= 10000, "Editorial decisions require an explicit chapter range")
        _require(isinstance(cards, list) and len(cards) <= 6 and (bool(cards) or item["choice"] == "DEFER"), "Active editorial learning needs approved knowledge; deferred findings are not applied")
        ids: set[str] = set()
        for card in cards:
            _require(isinstance(card, Mapping) and set(card) == {"asset_version_id", "content_hash"}, "Editorial knowledge must bind exact asset versions and hashes")
            identity, digest = card["asset_version_id"], card["content_hash"]
            _require(isinstance(identity, str) and bool(identity.strip()) and len(identity) <= 512 and identity not in ids and isinstance(digest, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", digest)), "Editorial knowledge identity is invalid or repeated")
            _require(identity not in hashes or hashes[identity] == digest, "Editorial knowledge versions cannot have conflicting hashes")
            hashes[identity] = digest
            ids.add(identity)
        active = active or item["choice"] != "DEFER"
    _require(active and len(hashes) <= 12, "Editorial learning needs at least one active decision and a bounded knowledge set")
    return deepcopy(dict(raw))


def editorial_author_design(raw: Mapping[str, Any], *, project_id: str) -> dict[str, Any]:
    learning = validate_editorial_learning(raw)
    documents, fragments = [], []
    labels = {"KEEP": "保留抽象机制", "ADAPT": "有条件改编抽象机制", "AVOID": "避免此失效模式"}
    for item in learning["decisions"]:
        if item["choice"] == "DEFER":
            continue
        text = "\n".join((
            f"阅读承诺：{learning['reader_promise']}",
            f"编辑取舍：{labels[item['choice']]}",
            f"抽象发现：{item['finding']}",
            f"原创应用与适用条件：{item['application']}",
            f"预期阅读效果：{item['reader_effect']}",
            f"副作用与取舍：{item['tradeoff']}",
            "只采用抽象方法；不复制参考作品的人物、设定、句段或独特事件组合。专业依据服务于剧情，不要求把校核过程写进正文。",
        ))
        path = f"editorial/decision-{len(documents) + 1}.txt"
        documents.append({"path": path, "content": text, "content_hash": text_hash(text)})
        fragments.append({"fragment_id": f"editorial:{item['decision_id']}", "source_path": path, "start": 0, "end": len(text), "content_hash": text_hash(text), "targets": item["targets"], "chapter_range": item["chapter_range"], "visibility": "SCENE_INTENT", "strength": "REQUIRED"})
    return validate_author_design({"contract_version": "author-design-input.v1", "project_id": project_id, "book_id": learning["book_id"], "version": learning["version"], "evidence_class": learning["evidence_class"], "source_task": "reference-editorial-learning", "documents": documents, "fragments": fragments})


def bind_editorial_inputs(inputs: list[Mapping[str, Any]], *, project_id: str, book_id: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for item in inputs:
        content = item["content"]
        value = (content.get("constraint_envelope") or {}).get("editorial_learning")
        if not value:
            value = ((content.get("candidate_payload") or {}).get("constraint_envelope") or {}).get("editorial_learning")
        if item.get("role") == "creative_brief" and content.get("editorial_learning"):
            learning = validate_editorial_learning(content["editorial_learning"])
            _require(content.get("author_design") == editorial_author_design(learning, project_id=project_id), "Editorial intent differs from its compiled author input")
            value = {"contract_version": "editorial-learning-binding.v1", "project_id": project_id, "book_id": book_id, "brief_asset_version_id": item["asset_version_id"], "brief_content_hash": item["content_hash"], "learning": learning}
            value["binding_digest"] = narrative_hash(value)
        if not value:
            continue
        _require(isinstance(value, Mapping) and set(value) == {"contract_version", "project_id", "book_id", "brief_asset_version_id", "brief_content_hash", "learning", "binding_digest"}, "Editorial binding must retain its complete frozen identity")
        learning = validate_editorial_learning(value["learning"])
        _require(value["contract_version"] == "editorial-learning-binding.v1" and value["project_id"] == project_id and value["book_id"] == book_id and learning["book_id"] == book_id and narrative_hash({k: v for k, v in value.items() if k != "binding_digest"}) == value["binding_digest"], "Editorial binding has stale bytes or another Book boundary")
        _require(not found or found == value, "Conflicting editorial versions require a governed future PlanChange")
        found = deepcopy(dict(value))
    return found


def required_editorial_knowledge(inputs: list[Mapping[str, Any]], *, command: Any) -> tuple[str, ...]:
    if not any(item["content"].get("editorial_learning") or (item["content"].get("constraint_envelope") or {}).get("editorial_learning") or ((item["content"].get("candidate_payload") or {}).get("constraint_envelope") or {}).get("editorial_learning") for item in inputs):
        return ()
    binding = bind_editorial_inputs(inputs, project_id=command.project_id, book_id=command.book_id)
    if not binding:
        return ()
    author = author_binding_from_inputs(inputs, project_id=command.project_id, book_id=command.book_id)
    _require(bool(author), "Editorial binding requires its frozen author intent")
    projection = compile_planning_author_projection(author, command=command, selected_inputs=inputs)
    selected = {item["fragment_id"] for item in projection["fragments"]}
    return tuple(sorted({card["asset_version_id"] for decision in binding["learning"]["decisions"] if f"editorial:{decision['decision_id']}" in selected for card in decision["knowledge_cards"]}))
