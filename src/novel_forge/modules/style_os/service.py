from __future__ import annotations

import re
from pathlib import Path
from statistics import mean
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment
from novel_forge.modules.review_issue import persist_issue_candidates
from novel_forge.schemas import (
    RevisionTask,
    StyleDriftReport,
    StyleFingerprint,
    StyleGenerationPolicy,
    StyleProfile,
    StyleReviewRule,
    StyleRewriteTask,
    StyleSample,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?", re.MULTILINE)
DIALOGUE_RE = re.compile(r"[“\"].+?[”\"]|^\\s*[A-Za-z\\u4e00-\\u9fff]{0,8}\\s*[:：]", re.MULTILINE)
PSYCHOLOGICAL_MARKERS = {"想", "觉得", "意识到", "明白", "害怕", "愤怒", "犹豫", "后悔", "hope", "fear", "realized"}
DESCRIPTION_MARKERS = {"看见", "声音", "颜色", "风", "雨", "灯", "街", "room", "light", "voice", "sound"}
RHETORIC_MARKERS = {"像", "仿佛", "似乎", "如同", "metaphor", "like", "as if"}
EMOTION_WORDS = {
    "tension": {"怕", "紧张", "危险", "怀疑", "fear", "danger"},
    "pleasure": {"爽", "笑", "轻松", "赢", "joy", "relief"},
    "sadness": {"痛", "哭", "失去", "孤独", "sad", "loss"},
    "anger": {"怒", "恨", "不甘", "rage", "anger"},
}


def ingest_style_sample(
    storage: LocalStorage,
    *,
    sample_text: str,
    project_id: str = "",
    rights: dict[str, Any] | None = None,
    title: str = "Style sample",
    source: str = "operator-provided",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not sample_text.strip():
        raise ValueError("sample_text is required")
    resolved_rights = rights or {"license": "project-owned-or-authorized", "allowed_usage": "style_parameter_extraction"}
    if is_production_environment(environment or (envelope or {}).get("environment")) and not resolved_rights.get("license"):
        raise ValueError("rights.license is required for production style sample ingestion")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="ingest-style-sample",
        project_id=project_id,
        task_type="style_ingestion",
        asset_type="style_sample",
        source_policy={"raw_source_text_allowed": True, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    asset = StyleSample(
        title=title,
        source=source,
        tags=["style-os", "raw-sample", "source-isolated"],
        content={
            "sample_id": make_id("style_sample", title),
            "project_id": project_id or str(env.get("project_id") or ""),
            "rights": resolved_rights,
            "source_policy": {
                "raw_text_in_generation_allowed": False,
                "generation_rag_allowed": False,
                "allowed_derivative": "abstract_style_parameters",
            },
            "sample_text": sample_text,
        },
        metadata={
            "project_id": project_id or str(env.get("project_id") or ""),
            "source_isolation": "raw text must not enter generation context",
            "use_in_generation_rag": False,
            **envelope_asset_metadata(env),
        },
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def extract_style_fingerprint(
    storage: LocalStorage,
    *,
    sample_path: str | Path,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sample_file = resolve_path(storage.root, sample_path)
    sample = storage.read_json(sample_file)
    content = sample.get("content", {}) if isinstance(sample.get("content"), dict) else {}
    sample_text = str(content.get("sample_text") or "")
    if is_production_environment(environment or (envelope or {}).get("environment")) and not content.get("rights"):
        raise ValueError("rights evidence is required for production style fingerprint extraction")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="extract-style-fingerprint",
        project_id=str(content.get("project_id") or sample.get("metadata", {}).get("project_id") or ""),
        task_type="style_fingerprint",
        asset_type="style_fingerprint",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    fingerprint = _fingerprint(sample_text)
    asset = StyleFingerprint(
        title=f"Style fingerprint for {sample.get('title') or sample.get('id')}",
        source=str(sample.get("id") or ""),
        tags=["style-os", "fingerprint", "abstract-only"],
        content={
            "fingerprint_id": make_id("style_fingerprint", str(sample.get("id") or "")),
            "source_sample_id": str(content.get("sample_id") or sample.get("id") or ""),
            **fingerprint,
            "confidence": _confidence(sample_text),
        },
        metadata={
            "project_id": str(content.get("project_id") or sample.get("metadata", {}).get("project_id") or ""),
            "source_sample_path": _display_path(storage.root, sample_file),
            "raw_text_excluded_from_context": True,
            **envelope_asset_metadata(env),
        },
        references=[_display_path(storage.root, sample_file)],
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def build_style_profile(
    storage: LocalStorage,
    *,
    fingerprint_path: str | Path,
    style_name: str = "Project style profile",
    scope: str = "project",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fp_file = resolve_path(storage.root, fingerprint_path)
    fingerprint = storage.read_json(fp_file)
    content = fingerprint.get("content", {}) if isinstance(fingerprint.get("content"), dict) else {}
    project_id = str(fingerprint.get("metadata", {}).get("project_id") or "")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="build-style-profile",
        project_id=project_id,
        task_type="style_profile",
        asset_type="style_profile",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": True},
        environment=environment,
        require_for_production=True,
    )
    style_id = make_id("style_profile", style_name)
    profile = StyleProfile(
        title=style_name,
        tags=["style-os", "style-profile", scope],
        content={
            "style_id": style_id,
            "name": style_name,
            "scope": scope,
            "source_boundary": {
                "allowed_usage": "parameter_only",
                "derived_from_protected_text": False,
                "copyright_risk": "low",
                "raw_sample_context_allowed": False,
            },
            "language_parameters": {
                "avg_sentence_length": content.get("avg_sentence_length", 0),
                "sentence_length_distribution": content.get("sentence_length_distribution", {}),
                "dialogue_ratio": content.get("dialogue_ratio", 0),
                "rhetoric_density": content.get("rhetoric_density", 0),
                "ai_flavor_markers": content.get("ai_flavor_markers", []),
            },
            "narrative_parameters": {
                "description_ratio": content.get("description_ratio", 0),
                "psychological_ratio": content.get("psychological_ratio", 0),
                "narrative_distance": content.get("narrative_distance", "medium"),
                "pov": content.get("pov", "third_limited"),
                "rhythm_profile": content.get("rhythm_profile", {}),
            },
            "emotion_parameters": {"emotion_distribution": content.get("emotion_distribution", {})},
            "forbidden_patterns": ["copy sample sentences", "imitate a named author", "quote style sample raw text"],
            "source_fingerprint_id": content.get("fingerprint_id", ""),
        },
        metadata={
            "project_id": project_id,
            "fingerprint_path": _display_path(storage.root, fp_file),
            "copyright_boundary": "abstract style structure parameters only",
            **envelope_asset_metadata(env),
        },
        references=[_display_path(storage.root, fp_file)],
    )
    profile_path = _write_asset(storage, profile)
    policy = _style_generation_policy(profile, project_id=project_id, envelope=env)
    rule = _style_review_rule(profile, project_id=project_id, envelope=env)
    policy_path = _write_asset(storage, policy)
    rule_path = _write_asset(storage, rule)
    return {
        "style_profile_path": profile_path,
        "style_generation_policy_path": policy_path,
        "style_review_rule_path": rule_path,
        "asset": storage.read_json(resolve_path(storage.root, profile_path)),
        "envelope": env,
    }


def run_style_drift_gate(
    storage: LocalStorage,
    *,
    style_profile_path: str | Path,
    target_path: str | Path,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    persist_issues: bool = True,
) -> dict[str, Any]:
    profile_file = resolve_path(storage.root, style_profile_path)
    target_file = resolve_path(storage.root, target_path)
    profile = storage.read_json(profile_file)
    target = storage.read_json(target_file)
    project_id = str(profile.get("metadata", {}).get("project_id") or target.get("metadata", {}).get("project_id") or "")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-style-drift-gate",
        project_id=project_id,
        task_type="style_drift_gate",
        asset_type="style_drift_report",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    observed = _fingerprint(_target_text(target))
    expected = profile.get("content", {}) if isinstance(profile.get("content"), dict) else {}
    scores = _drift_scores(expected, observed)
    level = _drift_level(scores)
    issues = _style_issues(level, scores)
    rewrite_candidate = {
        "task_type": "style_rewrite",
        "instructions": _rewrite_instructions(issues),
        "human_gate_required": level in {"high", "critical"},
    }
    target_asset_id = str(target.get("id") or "")
    target_asset_type = str(target.get("type") or "")
    issue_paths: list[str] = []
    if persist_issues and level in {"medium", "high", "critical"}:
        issue_summary = persist_issue_candidates(
            storage,
            [
                {
                    "issue_type": "style_drift",
                    "severity": "critical" if level == "critical" else "high" if level == "high" else "medium",
                    "blocking": level in {"high", "critical"},
                    "target_asset_id": target_asset_id,
                    "target_asset_type": target_asset_type,
                    "target_asset_path": _display_path(storage.root, target_file),
                    "project_id": project_id,
                    "message": f"style drift level is {level}",
                    "fix_suggestion": "; ".join(rewrite_candidate["instructions"]),
                    "evidence_refs": [_display_path(storage.root, profile_file), _display_path(storage.root, target_file)],
                }
            ],
            source_system="style_os.drift_gate",
        )
        issue_paths = [str(path) for path in issue_summary.get("issue_paths", [])]
    report = StyleDriftReport(
        title=f"Style drift report for {target_asset_id}",
        source=target_asset_id,
        tags=["style-os", "drift-gate", level],
        content={
            "target_style_id": str(expected.get("style_id") or profile.get("id") or ""),
            "target_asset_id": target_asset_id,
            "observed_fingerprint": observed,
            "drift_scores": scores,
            "drift_level": level,
            "issues": issues,
            "rewrite_task_candidate": rewrite_candidate,
            "review_issue_paths": issue_paths,
        },
        metadata={"project_id": project_id, **envelope_asset_metadata(env)},
        references=[_display_path(storage.root, profile_file), _display_path(storage.root, target_file), *issue_paths],
    )
    report_path = _write_asset(storage, report)
    rewrite_path = ""
    revision_task_path = ""
    if level in {"high", "critical"}:
        rewrite = StyleRewriteTask(
            title=f"Style rewrite task for {target_asset_id}",
            source=target_asset_id,
            tags=["style-os", "rewrite-task"],
            content={
                "task_id": make_id("style_rewrite_task", target_asset_id),
                "source_drift_report_id": report.id,
                "target_asset_id": target_asset_id,
                "instructions": rewrite_candidate["instructions"],
                "human_gate": {"required": True, "status": "pending"},
            },
            metadata={"project_id": project_id, **envelope_asset_metadata(env)},
            references=[report_path, _display_path(storage.root, target_file)],
        )
        rewrite_path = _write_asset(storage, rewrite)
        revision_task_path = _write_revision_task(storage, report_path=report_path, target_path=_display_path(storage.root, target_file), issues=issues, project_id=project_id)
    asset = storage.read_json(resolve_path(storage.root, report_path))
    asset["content"]["rewrite_task_path"] = rewrite_path
    asset["content"]["revision_task_path"] = revision_task_path
    storage.write_json(resolve_path(storage.root, report_path), asset)
    return {
        "path": report_path,
        "asset": storage.read_json(resolve_path(storage.root, report_path)),
        "review_issues": issue_paths,
        "style_rewrite_task_path": rewrite_path,
        "revision_task_path": revision_task_path,
        "envelope": env,
    }


def _style_generation_policy(profile: StyleProfile, *, project_id: str, envelope: dict[str, Any]) -> StyleGenerationPolicy:
    language = profile.content.get("language_parameters", {})
    narrative = profile.content.get("narrative_parameters", {})
    return StyleGenerationPolicy(
        title=f"Generation policy for {profile.content.get('name')}",
        source=profile.id,
        tags=["style-os", "generation-policy"],
        content={
            "policy_id": make_id("style_generation_policy", profile.id),
            "style_id": profile.content.get("style_id", profile.id),
            "generation_controls": {
                "target_avg_sentence_length": language.get("avg_sentence_length", 0),
                "dialogue_ratio": language.get("dialogue_ratio", 0),
                "description_ratio": narrative.get("description_ratio", 0),
                "psychological_ratio": narrative.get("psychological_ratio", 0),
                "rhythm_profile": narrative.get("rhythm_profile", {}),
            },
            "forbidden_patterns": profile.content.get("forbidden_patterns", []),
            "context_contract": {
                "raw_sample_text_allowed": False,
                "allowed_context_asset_types": ["style_profile", "style_fingerprint", "style_generation_policy", "style_review_rule"],
                "injection_role": "abstract_style_parameters",
            },
        },
        metadata={"project_id": project_id, **envelope_asset_metadata(envelope)},
        references=[profile.id],
    )


def _style_review_rule(profile: StyleProfile, *, project_id: str, envelope: dict[str, Any]) -> StyleReviewRule:
    language = profile.content.get("language_parameters", {})
    return StyleReviewRule(
        title=f"Review rule for {profile.content.get('name')}",
        source=profile.id,
        tags=["style-os", "review-rule"],
        content={
            "rule_id": make_id("style_review_rule", profile.id),
            "style_id": profile.content.get("style_id", profile.id),
            "checks": ["sentence_length_drift", "dialogue_ratio_drift", "description_ratio_drift", "ai_flavor_markers"],
            "thresholds": {
                "avg_sentence_length_delta": max(6, int(language.get("avg_sentence_length", 12) * 0.35)),
                "ratio_delta": 0.25,
                "ai_flavor_marker_count": 3,
            },
            "blocking_policy": {"high_or_critical_drift_blocks_release": True, "medium_requires_review": True},
        },
        metadata={"project_id": project_id, **envelope_asset_metadata(envelope)},
        references=[profile.id],
    )


def _fingerprint(text: str) -> dict[str, Any]:
    sentences = _sentences(text)
    lengths = [len(sentence) for sentence in sentences] or [0]
    token_count = max(1, len(text))
    dialogue_chars = sum(len(match.group(0)) for match in DIALOGUE_RE.finditer(text))
    psychological_hits = _marker_hits(text, PSYCHOLOGICAL_MARKERS)
    description_hits = _marker_hits(text, DESCRIPTION_MARKERS)
    rhetoric_hits = _marker_hits(text, RHETORIC_MARKERS)
    return {
        "avg_sentence_length": round(mean(lengths), 2),
        "sentence_length_distribution": {
            "short": sum(1 for value in lengths if value <= 18),
            "medium": sum(1 for value in lengths if 18 < value <= 45),
            "long": sum(1 for value in lengths if value > 45),
            "count": len(lengths),
        },
        "dialogue_ratio": round(dialogue_chars / token_count, 3),
        "description_ratio": round(min(1.0, description_hits / max(1, len(sentences))), 3),
        "psychological_ratio": round(min(1.0, psychological_hits / max(1, len(sentences))), 3),
        "rhetoric_density": round(rhetoric_hits / max(1, len(sentences)), 3),
        "emotion_distribution": _emotion_distribution(text),
        "narrative_distance": "close" if psychological_hits / max(1, len(sentences)) > 0.35 else "medium",
        "pov": "first_person" if any(marker in text for marker in ["我", "I "]) else "third_limited",
        "rhythm_profile": {"pace": "fast" if mean(lengths) < 24 else "measured", "sentence_count": len(lengths)},
        "ai_flavor_markers": _ai_flavor_markers(text),
    }


def _sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in SENTENCE_RE.finditer(text) if match.group(0).strip()] or [text.strip()]


def _marker_hits(text: str, markers: set[str]) -> int:
    lower = text.lower()
    return sum(lower.count(marker.lower()) for marker in markers)


def _emotion_distribution(text: str) -> dict[str, int]:
    lower = text.lower()
    return {bucket: sum(lower.count(word.lower()) for word in words) for bucket, words in EMOTION_WORDS.items()}


def _ai_flavor_markers(text: str) -> list[str]:
    markers = []
    for phrase in ["不禁", "与此同时", "空气仿佛凝固", "眸光微闪", "it was as if", "a sense of"]:
        if phrase.lower() in text.lower():
            markers.append(phrase)
    return markers


def _confidence(text: str) -> float:
    if len(text) >= 2000:
        return 0.9
    if len(text) >= 800:
        return 0.75
    if len(text) >= 200:
        return 0.55
    return 0.35


def _target_text(asset: dict[str, Any]) -> str:
    content = asset.get("content", {}) if isinstance(asset.get("content"), dict) else {}
    for key in ["text", "draft_text", "chapter_text", "body", "summary"]:
        if content.get(key):
            return str(content.get(key))
    return " ".join(str(value) for value in content.values() if isinstance(value, (str, int, float)))


def _drift_scores(profile_content: dict[str, Any], observed: dict[str, Any]) -> dict[str, float]:
    language = profile_content.get("language_parameters", {}) if isinstance(profile_content.get("language_parameters"), dict) else {}
    narrative = profile_content.get("narrative_parameters", {}) if isinstance(profile_content.get("narrative_parameters"), dict) else {}
    expected_avg = float(language.get("avg_sentence_length") or 0)
    observed_avg = float(observed.get("avg_sentence_length") or 0)
    avg_score = min(1.0, abs(observed_avg - expected_avg) / max(1.0, expected_avg or observed_avg or 1.0))
    return {
        "sentence_length": round(avg_score, 3),
        "dialogue_ratio": round(abs(float(observed.get("dialogue_ratio") or 0) - float(language.get("dialogue_ratio") or 0)), 3),
        "description_ratio": round(abs(float(observed.get("description_ratio") or 0) - float(narrative.get("description_ratio") or 0)), 3),
        "psychological_ratio": round(abs(float(observed.get("psychological_ratio") or 0) - float(narrative.get("psychological_ratio") or 0)), 3),
        "ai_flavor": round(min(1.0, len(observed.get("ai_flavor_markers", [])) / 4), 3),
    }


def _drift_level(scores: dict[str, float]) -> str:
    max_score = max(scores.values()) if scores else 0
    if max_score >= 0.7:
        return "critical"
    if max_score >= 0.45:
        return "high"
    if max_score >= 0.25:
        return "medium"
    return "low"


def _style_issues(level: str, scores: dict[str, float]) -> list[dict[str, Any]]:
    if level == "low":
        return []
    return [
        {
            "dimension": dimension,
            "score": score,
            "severity": "high" if score >= 0.45 else "medium",
            "message": f"{dimension} drift score {score}",
        }
        for dimension, score in scores.items()
        if score >= 0.25
    ]


def _rewrite_instructions(issues: list[dict[str, Any]]) -> list[str]:
    if not issues:
        return ["Keep current style parameters; no rewrite required."]
    instructions = []
    for issue in issues:
        dimension = issue.get("dimension", "")
        if dimension == "sentence_length":
            instructions.append("Adjust sentence length toward the target style profile without copying sample text.")
        elif dimension == "dialogue_ratio":
            instructions.append("Rebalance dialogue and exposition according to the style generation policy.")
        elif dimension == "description_ratio":
            instructions.append("Rebalance sensory description density.")
        elif dimension == "psychological_ratio":
            instructions.append("Rebalance interiority and external action.")
        elif dimension == "ai_flavor":
            instructions.append("Remove generic AI-flavored phrasing and replace it with scene-specific detail.")
    return instructions or ["Revise toward abstract style profile parameters."]


def _write_revision_task(storage: LocalStorage, *, report_path: str, target_path: str, issues: list[dict[str, Any]], project_id: str) -> str:
    task = RevisionTask(
        title="Style drift revision task",
        source=target_path,
        tags=["style-os", "revision-task"],
        content={
            "task_id": make_id("revision_task", f"style-drift-{target_path}"),
            "review_path": report_path,
            "source_draft_path": target_path,
            "issue_indexes": list(range(len(issues))),
            "issues": issues,
            "status": "open",
            "created_at": utc_now(),
            "outputs": {"style_rewrite_required": True},
        },
        metadata={"project_id": project_id, "source_system": "style_os.drift_gate"},
        references=[report_path, target_path],
    )
    return _write_asset(storage, task)


def _write_asset(storage: LocalStorage, asset: Any) -> str:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return _display_path(storage.root, storage.write_asset_auto(asset))


def _display_path(root: Path, path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return str(resolved.relative_to(root)) if resolved.is_relative_to(root) else str(resolved)
