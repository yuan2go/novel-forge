from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .blind_export import _assert_public_keys


MANUSCRIPT_PROTOCOL = "unassigned-manuscript-comparison.v1"
MANUSCRIPT_DIMENSIONS = (
    "character_credibility", "action_consequence", "dialogue_voice",
    "repetition_skipping", "desire_to_continue", "editing_burden",
)


def content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def manuscript_reading_input(public: Mapping[str, Any], pack_id: str) -> str:
    capsule = {"contract_version": "reader-manuscript-input.v1", "public_pack_asset_version_id": pack_id,
        "public_content_hash": content_digest(public), "public": dict(public)}
    return "<manuscript_reading_input>\n" + json.dumps(capsule, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n</manuscript_reading_input>"


def require_manuscript_reading_input(instruction: str, public: Mapping[str, Any], pack_id: str) -> None:
    matches = re.findall(r"<manuscript_reading_input>\s*(.*?)\s*</manuscript_reading_input>", instruction, re.DOTALL)
    if len(matches) != 1:
        raise ValueError("MODEL_READING_COMPLETE_INPUT_REQUIRED")
    capsule = json.loads(matches[0])
    if capsule != {"contract_version": "reader-manuscript-input.v1", "public_pack_asset_version_id": pack_id,
            "public_content_hash": content_digest(public), "public": dict(public)}:
        raise ValueError("MODEL_READING_INPUT_SNAPSHOT_DRIFT")


def extract_manuscript_chapter(
    *, asset_type: str, content: Mapping[str, Any], chapter_number: int, selector: str,
) -> dict[str, Any]:
    if type(chapter_number) is not int or chapter_number <= 0:
        raise ValueError("MANUSCRIPT_CHAPTER_RANGE_INVALID")
    if asset_type == "draft_chapter" and selector == "/text":
        if content.get("chapter") != chapter_number:
            raise ValueError("MANUSCRIPT_CHAPTER_IDENTITY_MISMATCH")
        title, text = content.get("title"), content.get("text")
    elif asset_type == "execution_evidence":
        match = re.fullmatch(r"/payload/final_response/chapters/(0|[1-9][0-9]*)/body", selector)
        payload = content.get("payload") or {}
        final = payload.get("final_response") or {}
        chapters = final.get("chapters") or []
        if (content.get("kind") != "normalized-output" or payload.get("action") != "FINAL"
                or final.get("contract_version") not in {
                    "writing-craft-reference-originals.v1", "controlled-reference-manuscript.v1",
                } or not match or not isinstance(chapters, list) or int(match[1]) >= len(chapters)):
            raise ValueError("MANUSCRIPT_REFERENCE_SOURCE_INVALID")
        chapter = chapters[int(match[1])]
        if not isinstance(chapter, dict) or chapter.get("chapter_number") != chapter_number:
            raise ValueError("MANUSCRIPT_CHAPTER_IDENTITY_MISMATCH")
        title, text = chapter.get("title"), chapter.get("body")
    else:
        raise ValueError("MANUSCRIPT_SOURCE_TYPE_FORBIDDEN")
    if not isinstance(title, str) or not isinstance(text, str) or not text.strip():
        raise ValueError("MANUSCRIPT_TEXT_REQUIRED")
    return {"chapter_number": chapter_number, "title": title, "text": text,
            "text_sha256": text_digest(text)}


def build_unassigned_manuscript_pack(
    manuscripts: list[dict[str, Any]], *, secret: str, pack_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(secret) < 16 or not pack_key or len(manuscripts) < 2:
        raise ValueError("MANUSCRIPT_BLIND_SCOPE_INVALID")
    keys = [item["manuscript_key"] for item in manuscripts]
    if len(set(keys)) != len(keys) or any(not isinstance(key, str) or not key for key in keys):
        raise ValueError("MANUSCRIPT_IDENTITY_REQUIRED")
    ranges = []
    bindings = []
    for manuscript in manuscripts:
        chapters = manuscript["chapters"]
        numbers = [item["chapter_number"] for item in chapters]
        if not numbers or numbers != list(range(numbers[0], numbers[-1] + 1)):
            raise ValueError("MANUSCRIPT_CONTIGUOUS_RANGE_REQUIRED")
        ranges.append(numbers)
        bindings.extend((item["parent_asset_version_id"], item["selector"]) for item in chapters)
    if any(numbers != ranges[0] for numbers in ranges) or len(set(bindings)) != len(bindings):
        raise ValueError("MANUSCRIPT_COMPARISON_SCOPE_MISMATCH")
    def token(*parts: str) -> str:
        return hashlib.sha256("\x1f".join((secret, pack_key, *parts)).encode()).hexdigest()[:32]
    ordered = sorted(manuscripts, key=lambda item: token(item["manuscript_key"]))
    public_rows, mappings = [], []
    for ordinal, manuscript in enumerate(ordered, start=1):
        manuscript_token = "manuscript:" + token(manuscript["manuscript_key"])
        chapters = []
        for chapter in manuscript["chapters"]:
            chapter_token = "reading-chapter:" + token(manuscript["manuscript_key"], str(chapter["chapter_number"]))
            chapters.append({"chapter_token": chapter_token, **{key: chapter[key] for key in (
                "chapter_number", "title", "text", "text_sha256",
            )}})
            mappings.append({"manuscript_token": manuscript_token, "chapter_token": chapter_token,
                "manuscript_key": manuscript["manuscript_key"], **chapter})
        public_rows.append({"manuscript_token": manuscript_token,
            "display_name": f"作品 {ordinal}", "chapters": chapters})
    public = _public_payload("manuscript-pack:" + token("pack"), public_rows, [ranges[0][0], ranges[0][-1]])
    private = {"protocol_version": MANUSCRIPT_PROTOCOL, "pack_key": pack_key,
        "pack_token": public["pack_token"], "public_content_hash": content_digest(public),
        "mapping": mappings, "human_feedback_status": "PENDING_HUMAN_FEEDBACK",
        "book_mutation_authorized": False}
    return public, private


def _public_payload(pack_token: str, public_rows: list[dict[str, Any]], chapter_range: list[int]) -> dict[str, Any]:
    public = {
        "protocol_version": MANUSCRIPT_PROTOCOL, "pack_token": pack_token,
        "scope": "INDEPENDENT_CONTIGUOUS_MANUSCRIPTS", "chapter_range": chapter_range,
        "instructions": "先按顺序阅读每篇作品，再记录阅读体验、跳读位置和修改负担；可以无法判断或不偏好任何作品。",
        "dimensions": list(MANUSCRIPT_DIMENSIONS),
        "score_scale": "1—5；除修改负担外，数值越高体验越好；修改负担1为很小、5为很大。无法判断可留空。",
        "manuscripts": public_rows,
        "response_template": {"reviewer_id": "", "human_attestation": False, "was_blinded": None,
            "preferred_manuscript_token": None, "ratings": {
                row["manuscript_token"]: {dimension: None for dimension in MANUSCRIPT_DIMENSIONS}
                for row in public_rows}, "reading_notes": "", "evidence_spans": []},
    }
    _assert_public_keys(public)
    return public


def public_from_private_mapping(private: Mapping[str, Any]) -> dict[str, Any]:
    if (private.get("protocol_version") != MANUSCRIPT_PROTOCOL
            or not re.fullmatch(r"manuscript-pack:[0-9a-f]{32}", str(private.get("pack_token")))
            or private.get("book_mutation_authorized") is not False
            or private.get("human_feedback_status") != "PENDING_HUMAN_FEEDBACK"):
        raise ValueError("MANUSCRIPT_MAPPING_INVALID")
    mappings = private.get("mapping")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("MANUSCRIPT_MAPPING_INVALID")
    groups: dict[str, list[dict[str, Any]]] = {}
    seen_sources, seen_tokens = set(), set()
    previous_token = None
    for binding in mappings:
        if (not isinstance(binding, dict)
                or not re.fullmatch(r"manuscript:[0-9a-f]{32}", str(binding.get("manuscript_token")))
                or not re.fullmatch(r"reading-chapter:[0-9a-f]{32}", str(binding.get("chapter_token")))
                or not isinstance(binding.get("text"), str)
                or not binding["text"].strip()
                or not isinstance(binding.get("title"), str)
                or binding.get("text_sha256") != text_digest(binding["text"])):
            raise ValueError("MANUSCRIPT_MAPPING_TEXT_DRIFT")
        identity = (binding.get("parent_asset_version_id"), binding.get("selector"))
        if identity in seen_sources or binding["chapter_token"] in seen_tokens:
            raise ValueError("MANUSCRIPT_COMPARISON_SCOPE_MISMATCH")
        seen_sources.add(identity)
        seen_tokens.add(binding["chapter_token"])
        group = groups.setdefault(binding["manuscript_token"], [])
        if group and previous_token != binding["manuscript_token"]:
            raise ValueError("MANUSCRIPT_MAPPING_ORDER_INVALID")
        group.append(binding)
        previous_token = binding["manuscript_token"]
    if len(groups) < 2:
        raise ValueError("MANUSCRIPT_COMPARISON_SCOPE_MISMATCH")
    keys, books, ranges, public_rows = [], [], [], []
    for ordinal, (manuscript_token, group) in enumerate(groups.items(), start=1):
        key, book_id = group[0].get("manuscript_key"), group[0].get("book_id")
        if (not isinstance(key, str) or not key or not isinstance(book_id, str) or not book_id
                or any(row.get("manuscript_key") != key or row.get("book_id") != book_id for row in group)):
            raise ValueError("INDEPENDENT_MANUSCRIPT_BOOKS_REQUIRED")
        numbers = [row.get("chapter_number") for row in group]
        if (any(type(number) is not int or number <= 0 for number in numbers)
                or numbers != list(range(numbers[0], numbers[-1] + 1))):
            raise ValueError("MANUSCRIPT_CONTIGUOUS_RANGE_REQUIRED")
        keys.append(key)
        books.append(book_id)
        ranges.append(numbers)
        public_rows.append({"manuscript_token": manuscript_token, "display_name": f"作品 {ordinal}",
            "chapters": [{key: row[key] for key in (
                "chapter_token", "chapter_number", "title", "text", "text_sha256",
            )} for row in group]})
    if (len(set(keys)) != len(keys) or len(set(books)) != len(books)
            or any(numbers != ranges[0] for numbers in ranges)):
        raise ValueError("MANUSCRIPT_COMPARISON_SCOPE_MISMATCH")
    public = _public_payload(private["pack_token"], public_rows, [ranges[0][0], ranges[0][-1]])
    if content_digest(public) != private.get("public_content_hash"):
        raise ValueError("MANUSCRIPT_PUBLIC_SNAPSHOT_DRIFT")
    return public


def validate_manuscript_human_response(public: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
    if (response.get("human_attestation") is not True or not isinstance(response.get("reviewer_id"), str)
            or not response["reviewer_id"].strip() or type(response.get("was_blinded")) is not bool):
        raise ValueError("ACTUAL_HUMAN_DECLARATION_REQUIRED")
    manuscripts = {row["manuscript_token"]: row for row in public["manuscripts"]}
    preference = response.get("preferred_manuscript_token")
    if preference is not None and preference not in manuscripts:
        raise ValueError("MANUSCRIPT_PREFERENCE_SCOPE_INVALID")
    ratings = response.get("ratings")
    if not isinstance(ratings, dict) or set(ratings) != set(manuscripts):
        raise ValueError("MANUSCRIPT_RATINGS_SCOPE_INVALID")
    for scores in ratings.values():
        if not isinstance(scores, dict) or set(scores) != set(MANUSCRIPT_DIMENSIONS) or any(
                score is not None and (type(score) is not int or not 1 <= score <= 5) for score in scores.values()):
            raise ValueError("MANUSCRIPT_RATING_INVALID")
    chapters = {chapter["chapter_token"]: chapter for row in manuscripts.values() for chapter in row["chapters"]}
    spans = response.get("evidence_spans") or []
    if not isinstance(spans, list):
        raise ValueError("MANUSCRIPT_READING_LOCATION_INVALID")
    for span in spans:
        if not isinstance(span, dict) or span.get("chapter_token") not in chapters:
            raise ValueError("MANUSCRIPT_READING_LOCATION_INVALID")
        text = chapters[span["chapter_token"]]["text"]
        start, end = span.get("start"), span.get("end")
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or span.get("quote") != text[start:end] or not isinstance(span.get("observation"), str)):
            raise ValueError("MANUSCRIPT_READING_LOCATION_INVALID")
    notes = response.get("reading_notes")
    if not isinstance(notes, str) or not notes.strip():
        raise ValueError("MANUSCRIPT_READING_EXPERIENCE_REQUIRED")
    return {"protocol_version": MANUSCRIPT_PROTOCOL, "pack_token": public["pack_token"],
        "public_content_hash": content_digest(public), "evaluator_origin": "HUMAN_SUBMISSION",
        "human_attestation": True,
        "identity_verification": "DECLARED_NOT_INDEPENDENTLY_VERIFIED",
        "reviewer_id": response["reviewer_id"].strip(), "was_blinded": response["was_blinded"],
        "preferred_manuscript_token": preference, "ratings": ratings, "reading_notes": notes,
        "evidence_spans": spans, "book_mutation_authorized": False, "author_acceptance": False}


def validate_manuscript_write(definition: str, payload: dict[str, Any], inputs) -> None:
    if definition == "reader.manuscript.mapping.record":
        sources = {item.asset_version_id: item for item in inputs}
        if payload.get("protocol_version") != MANUSCRIPT_PROTOCOL or not payload.get("mapping"):
            raise ValueError("MANUSCRIPT_MAPPING_INVALID")
        for binding in payload["mapping"]:
            source = sources.get(binding["parent_asset_version_id"])
            if source is None or source.content_hash != binding["parent_content_hash"]:
                raise ValueError("MANUSCRIPT_MAPPING_SOURCE_DRIFT")
            actual = extract_manuscript_chapter(asset_type=source.asset_type, content=source.content,
                chapter_number=binding["chapter_number"], selector=binding["selector"])
            if any(binding.get(key) != actual[key] for key in ("title", "text", "text_sha256")):
                raise ValueError("MANUSCRIPT_MAPPING_TEXT_DRIFT")
        public_from_private_mapping(payload)
    elif definition == "reader.manuscript.pack.export":
        if len(inputs) != 1 or inputs[0].asset_type != "manuscript_blind_private_mapping":
            raise ValueError("MANUSCRIPT_MAPPING_PARENT_REQUIRED")
        public = payload.get("public")
        _assert_public_keys(public)
        parent = inputs[0].content
        expected = public_from_private_mapping(parent)
        if (not isinstance(public, dict) or public != expected
                or content_digest(expected) != payload.get("public_content_hash")):
            raise ValueError("MANUSCRIPT_PUBLIC_SNAPSHOT_DRIFT")
    elif definition == "reader.manuscript.feedback.record":
        if len(inputs) != 1 or inputs[0].asset_type != "manuscript_blind_evaluation_pack":
            raise ValueError("MANUSCRIPT_READING_PACK_REQUIRED")
        actual = validate_manuscript_human_response(inputs[0].content["public"], payload)
        if any(payload.get(key) != value for key, value in actual.items()):
            raise ValueError("MANUSCRIPT_HUMAN_RESPONSE_DRIFT")
    elif definition == "reader.manuscript.diagnosis.record":
        packs = [item for item in inputs if item.asset_type == "manuscript_blind_evaluation_pack"]
        normalized = [item for item in inputs if item.asset_type == "execution_evidence"]
        if len(packs) != 1 or len(normalized) != 1:
            raise ValueError("MODEL_READING_SOURCE_REQUIRED")
        if (normalized[0].asset_version_id != payload.get("normalized_asset_version_id")
                or normalized[0].content_hash != payload.get("normalized_content_hash")):
            raise ValueError("MODEL_READING_SOURCE_DRIFT")
        raw = normalized[0].content.get("payload", {}).get("final_response")
        actual = normalize_manuscript_model_diagnosis(packs[0].content["public"], raw)
        if any(payload.get(key) != value for key, value in actual.items()):
            raise ValueError("MODEL_READING_RESPONSE_DRIFT")


def normalize_manuscript_model_diagnosis(public: Mapping[str, Any], raw: Any) -> dict[str, Any]:
    if (not isinstance(raw, dict) or raw.get("contract_version") != "reader-manuscript-model-diagnosis.v1"
            or raw.get("pack_token") != public["pack_token"]
            or raw.get("public_content_hash") != content_digest(public)):
        raise ValueError("MODEL_READING_SNAPSHOT_DRIFT")
    manuscripts = {row["manuscript_token"]: row for row in public["manuscripts"]}
    assessments = raw.get("assessments")
    if (not isinstance(assessments, list) or len(assessments) != len(manuscripts)
            or {item.get("manuscript_token") for item in assessments if isinstance(item, dict)} != set(manuscripts)):
        raise ValueError("MODEL_READING_MANUSCRIPT_SCOPE_INVALID")
    resolved = []
    for assessment in assessments:
        scores = assessment.get("scores")
        if not isinstance(scores, dict) or set(scores) != set(MANUSCRIPT_DIMENSIONS) or any(
                value is not None and (type(value) is not int or not 1 <= value <= 5) for value in scores.values()):
            raise ValueError("MODEL_READING_RATING_INVALID")
        if not isinstance(assessment.get("reading_experience"), str) or not assessment["reading_experience"].strip():
            raise ValueError("MODEL_READING_EXPERIENCE_REQUIRED")
        chapters = {chapter["chapter_token"]: chapter for chapter in manuscripts[assessment["manuscript_token"]]["chapters"]}
        locations = []
        for finding in assessment.get("evidence_spans") or []:
            if not isinstance(finding, dict) or finding.get("chapter_token") not in chapters:
                raise ValueError("MODEL_READING_LOCATION_SCOPE_INVALID")
            quote = finding.get("quote")
            if not isinstance(quote, str) or not quote:
                raise ValueError("MODEL_READING_QUOTE_REQUIRED")
            if (not isinstance(finding.get("observation"), str) or not finding["observation"].strip()
                    or finding.get("dimension") is not None and finding["dimension"] not in MANUSCRIPT_DIMENSIONS):
                raise ValueError("MODEL_READING_OBSERVATION_REQUIRED")
            text = chapters[finding["chapter_token"]]["text"]
            matches = []
            offset = text.find(quote)
            while offset >= 0:
                matches.append(offset)
                offset = text.find(quote, offset + 1)
            location = {**finding, "location_status": "LOCATED" if len(matches) == 1 else "AMBIGUOUS" if matches else "NOT_FOUND"}
            if len(matches) == 1:
                location.update(start=matches[0], end=matches[0] + len(quote),
                    text_sha256=chapters[finding["chapter_token"]]["text_sha256"])
            else:
                location.pop("start", None)
                location.pop("end", None)
            locations.append(location)
        resolved.append({**assessment, "evidence_spans": locations})
    return {"protocol_version": MANUSCRIPT_PROTOCOL, "pack_token": public["pack_token"],
        "public_content_hash": content_digest(public), "evaluator_origin": "MODEL_AUXILIARY_DIAGNOSIS",
        "assessments": resolved, "raw_diagnosis": raw, "human_feedback": False,
        "author_acceptance": False, "book_mutation_authorized": False}
