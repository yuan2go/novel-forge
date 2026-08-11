"""Deterministic, fail-closed profiling for heterogeneous imported text sources."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Iterable

from .analysis_profiles import analysis_profile


CLASSIFIER_VERSION = "source-content-profiler.1.0"
_UNKNOWN = "unknown"
_CHAPTER_HEADING = re.compile(
    r"(?m)^\s*(?:第[零一二三四五六七八九十百千万0-9]+[章节回部卷]|chapter\s+\d+)\b",
    re.IGNORECASE,
)

_DOMAIN_MARKERS = {
    "economics": ("经济", "economics", "宏观经济", "微观经济", "金融", "财政", "货币"),
    "history": ("历史", "通史", "史学", "history", "historical"),
    "philosophy": ("哲学", "philosophy", "伦理学", "认识论", "形而上学"),
    "psychology": ("心理学", "psychology", "认知", "人格", "行为科学"),
    "military": ("军事", "战争史", "战略", "战役", "military"),
    "law": ("法律", "法学", "司法", "law", "legal"),
    "medicine": ("医学", "临床", "病理", "medical", "medicine"),
    "technology": ("技术", "工程", "计算机", "软件", "algorithm", "technology"),
    "sociology": ("社会学", "社会科学", "sociology", "社会结构"),
    "politics": ("政治学", "政治", "治理", "politics", "political"),
    "biography": ("传记", "自传", "回忆录", "生平", "biography", "memoir"),
}

_WRITING_MARKERS = (
    "写作理论",
    "小说创作",
    "文学创作",
    "叙事学",
    "写作技巧",
    "故事结构",
    "人物塑造",
    "情节设计",
    "剧作",
    "编剧",
    "creative writing",
    "storytelling",
)
_PLATFORM_MARKERS = (
    "平台规则",
    "作者后台",
    "签约规则",
    "内容规范",
    "违规",
    "推荐位",
    "上架",
    "订阅",
    "稿费",
    "审核规则",
    "publishing policy",
)
_WEB_NOVEL_MARKERS = (
    "网络小说",
    "网文",
    "起点",
    "纵横",
    "晋江",
    "番茄小说",
    "飞卢",
    "连载",
    "日更",
    "web novel",
)
_CLASSIC_MARKERS = (
    "经典文学",
    "经典小说",
    "文学名著",
    "世界名著",
    "古典文学",
    "classic literature",
)
_FICTION_PATH_MARKERS = ("小说", "文学", "fiction", "novel")
_NONFICTION_MARKERS = (
    "定义",
    "理论",
    "模型",
    "研究",
    "方法",
    "机制",
    "证据",
    "数据",
    "结论",
    "案例",
    "参考文献",
    "假设",
    "约束",
    "适用范围",
)
_NARRATIVE_MARKERS = (
    "他说",
    "她说",
    "问道",
    "回答",
    "走进",
    "看着",
    "突然",
    "后来",
    "此时",
    "心想",
)


@dataclass(frozen=True, slots=True)
class SourceContentProfile:
    classifier_version: str
    content_family: str
    content_type: str
    selected_analysis_profile: str
    domain_tags: tuple[str, ...]
    confidence: float
    manual_review_required: bool
    signals: tuple[str, ...]
    source_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("Source profile confidence must be within [0, 1]")
        if self.selected_analysis_profile != _UNKNOWN:
            analysis_profile(self.selected_analysis_profile)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "source-content-profile.v1",
            **asdict(self),
            "domain_tags": list(self.domain_tags),
            "signals": list(self.signals),
            "source_paths": list(self.source_paths),
        }


def classify_source_content(
    *,
    paths: Iterable[str],
    text: str,
    requested_profile: str = "auto",
) -> SourceContentProfile:
    """Classify one immutable content identity without spending Provider tokens.

    Explicit operator profiles remain authoritative. AUTO uses path metadata and
    bounded content signals; ambiguous content is left for review rather than
    silently routed through the wrong analysis methodology.
    """

    normalized_paths = tuple(
        sorted({str(path).replace("\\", "/").strip() for path in paths if str(path).strip()})
    )
    if not normalized_paths:
        normalized_paths = ("unknown",)
    requested = requested_profile.strip().lower()
    if requested != "auto":
        profile = analysis_profile(requested)
        if profile.profile_id == "auto":
            raise ValueError("explicit Source profile cannot resolve back to AUTO")
        family, content_type = _profile_identity(profile.profile_id)
        return SourceContentProfile(
            classifier_version=CLASSIFIER_VERSION,
            content_family=family,
            content_type=content_type,
            selected_analysis_profile=profile.profile_id,
            domain_tags=_domain_tags("\n".join(normalized_paths), text),
            confidence=1.0,
            manual_review_required=False,
            signals=("operator_profile_override",),
            source_paths=normalized_paths,
        )

    sample = text[:160_000]
    haystack = ("\n".join(normalized_paths) + "\n" + sample).lower()
    path_text = "\n".join(normalized_paths).lower()
    domains = _domain_tags(path_text, sample)
    scores = {
        "web_novel": 0,
        "published_fiction": 0,
        "classic_literature": 0,
        "writing_theory": 0,
        "platform_rules": 0,
        "professional_knowledge": 0,
    }
    signals: list[str] = []

    chapter_count = len(_CHAPTER_HEADING.findall(sample))
    dialogue_count = sum(sample.count(marker) for marker in ("“", "”", "「", "」"))
    narrative_count = _marker_count(sample, _NARRATIVE_MARKERS)
    fiction_score = 0
    if chapter_count >= 3:
        fiction_score += 2
        signals.append("chapter_sequence")
    elif chapter_count:
        fiction_score += 1
    if dialogue_count >= 8:
        fiction_score += 1
        signals.append("dialogue_density")
    if narrative_count >= 4:
        fiction_score += 1
        signals.append("narrative_language")
    if _contains_any(path_text, _FICTION_PATH_MARKERS):
        fiction_score += 2
        signals.append("fiction_path_hint")

    web_hits = _marker_count(haystack, _WEB_NOVEL_MARKERS)
    classic_hits = _marker_count(path_text, _CLASSIC_MARKERS)
    writing_hits = _marker_count(haystack, _WRITING_MARKERS)
    platform_hits = _marker_count(haystack, _PLATFORM_MARKERS)
    nonfiction_hits = _marker_count(sample, _NONFICTION_MARKERS)

    if fiction_score:
        scores["published_fiction"] += fiction_score + 1
        scores["web_novel"] += fiction_score
        scores["classic_literature"] += fiction_score
    if web_hits:
        scores["web_novel"] += min(5, web_hits * 2)
        signals.append("web_novel_metadata")
    if classic_hits:
        scores["classic_literature"] += min(6, classic_hits * 3)
        signals.append("classic_literature_metadata")
    if writing_hits:
        scores["writing_theory"] += min(8, writing_hits * 2)
        signals.append("writing_theory_markers")
    if platform_hits:
        scores["platform_rules"] += min(8, platform_hits * 2)
        signals.append("platform_rule_markers")
    if domains:
        scores["professional_knowledge"] += min(6, 2 + len(domains))
        signals.append("professional_domain_metadata")
    if nonfiction_hits >= 3:
        scores["professional_knowledge"] += min(6, 1 + nonfiction_hits // 2)
        signals.append("nonfiction_concept_structure")

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    selected, top = ranked[0]
    second = ranked[1][1]
    if top < 3 or (top == second and top < 6):
        return SourceContentProfile(
            classifier_version=CLASSIFIER_VERSION,
            content_family="UNKNOWN",
            content_type="UNKNOWN",
            selected_analysis_profile=_UNKNOWN,
            domain_tags=domains,
            confidence=_confidence(top, second),
            manual_review_required=True,
            signals=tuple(sorted(set(signals + ["insufficient_classification_evidence"]))),
            source_paths=normalized_paths,
        )

    confidence = _confidence(top, second)
    manual_review = confidence < 0.72
    # "Classic" is partly bibliographic rather than purely textual. Only an
    # explicit classic/major-literature metadata hint can route automatically;
    # otherwise fiction falls back to published-fiction analysis.
    if selected == "classic_literature" and not classic_hits:
        selected = "published_fiction"
        manual_review = False
        signals.append("classic_status_unverified_routed_as_published_fiction")
    family, content_type = _profile_identity(selected)
    return SourceContentProfile(
        classifier_version=CLASSIFIER_VERSION,
        content_family=family,
        content_type=content_type,
        selected_analysis_profile=selected,
        domain_tags=domains,
        confidence=confidence,
        manual_review_required=manual_review,
        signals=tuple(sorted(set(signals))),
        source_paths=normalized_paths,
    )


def _profile_identity(profile_id: str) -> tuple[str, str]:
    mapping = {
        "web_novel": ("FICTION", "WEB_NOVEL"),
        "published_fiction": ("FICTION", "PUBLISHED_FICTION"),
        "classic_literature": ("FICTION", "CLASSIC_LITERATURE"),
        "writing_theory": ("NONFICTION", "WRITING_THEORY"),
        "platform_rules": ("REFERENCE", "PLATFORM_RULES"),
        "professional_knowledge": ("NONFICTION", "PROFESSIONAL_KNOWLEDGE"),
    }
    try:
        return mapping[profile_id]
    except KeyError as exc:
        raise ValueError(f"unsupported resolved Source profile: {profile_id}") from exc


def _domain_tags(path_text: str, text: str) -> tuple[str, ...]:
    sample = (path_text + "\n" + text[:80_000]).lower()
    return tuple(
        domain
        for domain, markers in _DOMAIN_MARKERS.items()
        if _contains_any(sample, markers)
    )


def _contains_any(value: str, markers: Iterable[str]) -> bool:
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in markers)


def _marker_count(value: str, markers: Iterable[str]) -> int:
    lowered = value.lower()
    return sum(lowered.count(marker.lower()) for marker in markers)


def _confidence(top: int, second: int) -> float:
    if top <= 0:
        return 0.0
    margin = max(0, top - second)
    score = 0.48 + min(0.28, top * 0.035) + min(0.22, margin * 0.055)
    return round(min(0.98, max(0.0, score)), 4)


__all__ = [
    "CLASSIFIER_VERSION",
    "SourceContentProfile",
    "classify_source_content",
]
