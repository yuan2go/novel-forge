from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.schemas import LicenseCheckResult, SourceDocument, SourcePolicy, SourceRefreshReport, SourceRiskReport, SourceSnapshot, SourceSyncJob, validate_common_fields
from novel_forge.storage.local import LocalStorage


SOURCE_POLICIES: list[dict[str, Any]] = [
    {
        "id": "chinese_text_project",
        "name": "Chinese Text Project",
        "url": "https://ctext.org/",
        "category": "classical_chinese",
        "method": "manual_reference_only",
        "crawler_allowed": False,
        "license_policy": "site_blocks_automatic_downloads",
        "commercial_risk": "medium_high",
        "allowed_pipeline": ["bibliographic_index", "manual_notes", "knowledge_card_extraction"],
        "forbidden_pipeline": ["web_crawling", "bulk_full_text_vectorization", "raw_text_redistribution"],
        "use_in_pipeline": "metadata_and_operator_notes_only",
    },
    {
        "id": "cbeta",
        "name": "CBETA",
        "url": "https://github.com/cbeta-org/xml-p5",
        "category": "buddhist_texts",
        "method": "official_github_xml_or_download",
        "crawler_allowed": False,
        "license_policy": "non_commercial_or_cc_by_nc_sa_with_exceptions",
        "commercial_risk": "high",
        "allowed_pipeline": ["research_reference", "concept_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_raw_corpus", "raw_text_redistribution", "direct_prose_generation"],
        "use_in_pipeline": "mechanism_extraction_only",
    },
    {
        "id": "cbdb",
        "name": "China Biographical Database",
        "url": "https://cbdb.hsites.harvard.edu/",
        "category": "historical_people",
        "method": "official_database_api_or_linked_open_data",
        "crawler_allowed": False,
        "license_policy": "cc_by_nc_sa_academic_branch",
        "commercial_risk": "medium_high",
        "allowed_pipeline": ["research_reference", "relationship_modeling", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_redistribution", "raw_database_packaging"],
        "use_in_pipeline": "structure_extraction_not_raw_redistribution",
    },
    {
        "id": "chgis",
        "name": "China Historical GIS",
        "url": "https://chgis.fas.harvard.edu/data/chgis/v6/",
        "category": "historical_geography",
        "method": "official_dataverse_download",
        "crawler_allowed": False,
        "license_policy": "academic_research_only_no_commercial_resale_or_redistribution",
        "commercial_risk": "high",
        "allowed_pipeline": ["research_reference", "map_structure_reference", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_embedded_dataset", "raw_gis_redistribution"],
        "use_in_pipeline": "fictional_map_rule_reference",
    },
    {
        "id": "project_gutenberg",
        "name": "Project Gutenberg",
        "url": "https://www.gutenberg.org/policy/robot_access.html",
        "category": "public_domain_texts",
        "method": "official_robot_harvest_or_mirror",
        "crawler_allowed": True,
        "license_policy": "public_domain_catalog_with_country_specific_copyright_checks",
        "commercial_risk": "low_medium",
        "allowed_pipeline": ["robot_harvest", "public_domain_corpus", "knowledge_card_extraction"],
        "forbidden_pipeline": ["human_site_crawling", "ignoring_local_copyright_status"],
        "use_in_pipeline": "public_domain_text_corpus_after_jurisdiction_check",
    },
]


GITHUB_KNOWLEDGE_SOURCES: list[dict[str, Any]] = [
    {
        "id": "niutrans_classical_modern",
        "repo": "NiuTrans/Classical-Modern",
        "url": "https://github.com/NiuTrans/Classical-Modern",
        "category": "ancient_chinese",
        "type": "classical_modern_parallel_corpus",
        "disciplines": ["classical_chinese", "translation", "philology"],
        "use_for": ["古文理解", "古典表达转译", "文白语义对齐"],
        "allowed_pipeline": ["research", "knowledge_card_extraction", "manual_handoff"],
        "forbidden_pipeline": ["direct_text_generation_without_rewrite", "raw_text_redistribution"],
        "license_check": "required",
        "commercial_risk": "medium",
    },
    {
        "id": "dayihengliu_a2m_chinese_nmt",
        "repo": "dayihengliu/a2m_chineseNMT",
        "url": "https://github.com/dayihengliu/a2m_chineseNMT",
        "category": "ancient_chinese",
        "type": "ancient_modern_parallel_corpus",
        "disciplines": ["classical_chinese", "translation"],
        "use_for": ["古籍语义理解", "古风表达转换", "转译质量检查"],
        "allowed_pipeline": ["research", "knowledge_card_extraction", "manual_handoff"],
        "forbidden_pipeline": ["direct_text_generation_without_rewrite", "raw_text_redistribution"],
        "license_check": "required",
        "commercial_risk": "medium",
    },
    {
        "id": "ethan_yt_guwenbert",
        "repo": "Ethan-yt/guwenbert",
        "url": "https://github.com/Ethan-yt/guwenbert",
        "category": "ancient_chinese",
        "type": "classical_chinese_bert_and_ner_data",
        "disciplines": ["classical_chinese", "named_entity_recognition"],
        "use_for": ["古籍实体识别", "人名地名书名抽取", "命名规律分析"],
        "allowed_pipeline": ["research", "entity_pattern_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["direct_text_generation_without_rewrite", "raw_model_or_data_redistribution"],
        "license_check": "required",
        "commercial_risk": "medium",
    },
    {
        "id": "ancient_chinese_allusion_resource_database",
        "repo": "QSJDAMTX/Ancient-Chinese-Allusion-Resource-Database",
        "url": "https://github.com/QSJDAMTX/Ancient-Chinese-Allusion-Resource-Database",
        "category": "ancient_chinese",
        "type": "allusion_resource_database",
        "disciplines": ["classical_chinese", "literary_allusion", "cultural_symbols"],
        "use_for": ["典故卡", "意象卡", "章名素材卡", "宗门命名参考"],
        "allowed_pipeline": ["research", "knowledge_card_extraction", "manual_handoff"],
        "forbidden_pipeline": ["raw_allusion_text_redistribution", "direct_prose_generation"],
        "license_check": "required",
        "commercial_risk": "medium_high",
    },
    {
        "id": "mescoder_ancient_chinese_project",
        "repo": "MescoCoder/AncientChineseProject",
        "url": "https://github.com/MescoCoder/AncientChineseProject",
        "category": "ancient_chinese",
        "type": "ancient_chinese_dataset_collection",
        "disciplines": ["classical_chinese", "historical_text_mining"],
        "use_for": ["历史实体", "古代文本结构", "古籍处理方法"],
        "allowed_pipeline": ["research", "knowledge_card_extraction", "manual_handoff"],
        "forbidden_pipeline": ["raw_corpus_redistribution", "direct_text_generation_without_rewrite"],
        "license_check": "required",
        "commercial_risk": "medium",
    },
    {
        "id": "tangxuemei_chisiec",
        "repo": "tangxuemei1995/CHisIEC",
        "url": "https://github.com/tangxuemei1995/CHisIEC",
        "category": "ancient_chinese",
        "type": "ancient_history_information_extraction_corpus",
        "disciplines": ["history", "information_extraction", "entity_relation_extraction"],
        "use_for": ["历史人物关系", "实体关系抽取", "朝代制度结构"],
        "allowed_pipeline": ["research", "relation_pattern_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["raw_corpus_redistribution", "direct_story_generation"],
        "license_check": "required",
        "commercial_risk": "medium_high",
    },
    {
        "id": "iris2hu_ancient_chinese_sense_annotation",
        "repo": "iris2hu/ancient_chinese_sense_annotation",
        "url": "https://github.com/iris2hu/ancient_chinese_sense_annotation",
        "category": "ancient_chinese",
        "type": "ancient_chinese_semantic_annotation",
        "disciplines": ["classical_chinese", "semantics"],
        "use_for": ["古文歧义消解", "词义转译", "古籍知识抽取"],
        "allowed_pipeline": ["research", "knowledge_card_extraction", "manual_handoff"],
        "forbidden_pipeline": ["raw_annotation_redistribution", "direct_text_generation_without_rewrite"],
        "license_check": "required",
        "commercial_risk": "medium",
    },
    {
        "id": "guofeng_webnovel",
        "repo": "longyuewangdcu/GuoFeng-Webnovel",
        "url": "https://github.com/longyuewangdcu/GuoFeng-Webnovel",
        "category": "webnovel_research",
        "type": "multilingual_webnovel_corpus",
        "disciplines": ["webnovel_structure", "genre_analysis", "translation_studies"],
        "use_for": ["类型结构", "章节分布", "翻译表达对照", "题材规律观察"],
        "allowed_pipeline": ["research", "decomposition_research", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_generation_from_raw_text", "raw_text_vectorization_without_rights"],
        "license_check": "required",
        "commercial_risk": "high",
    },
    {
        "id": "multigenre_chinese_novel",
        "repo": "hjzhao73/MultiGenre-ChineseNovel",
        "url": "https://github.com/hjzhao73/MultiGenre-ChineseNovel",
        "category": "webnovel_research",
        "type": "multi_genre_chinese_novel_ner",
        "disciplines": ["named_entity_recognition", "webnovel_entity_patterns"],
        "use_for": ["人物命名规律", "地点组织实体抽取", "网文实体关系"],
        "allowed_pipeline": ["research", "entity_pattern_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_generation_from_raw_text", "raw_dataset_redistribution"],
        "license_check": "required",
        "commercial_risk": "high",
    },
    {
        "id": "gen_webnovel",
        "repo": "hjzhao73/GenWebNovel",
        "url": "https://github.com/hjzhao73/GenWebNovel",
        "category": "webnovel_research",
        "type": "webnovel_entity_recognition_code_data",
        "disciplines": ["webnovel_entity_patterns", "information_extraction"],
        "use_for": ["人物组织识别", "类型实体规律", "章节实体密度分析"],
        "allowed_pipeline": ["research", "entity_pattern_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_generation_from_raw_text", "raw_dataset_redistribution"],
        "license_check": "required",
        "commercial_risk": "high",
    },
    {
        "id": "bfsujason_mac",
        "repo": "bfsujason/mac",
        "url": "https://github.com/bfsujason/mac",
        "category": "literary_parallel_corpus",
        "type": "chinese_english_literary_parallel_corpus",
        "disciplines": ["translation_studies", "literary_expression"],
        "use_for": ["文学翻译对照", "表达层级观察", "跨语叙事转译"],
        "allowed_pipeline": ["research", "knowledge_card_extraction", "manual_handoff"],
        "forbidden_pipeline": ["direct_style_imitation", "raw_text_redistribution"],
        "license_check": "required",
        "commercial_risk": "medium_high",
    },
    {
        "id": "acl_anthology_corpus",
        "repo": "shauryr/ACL-anthology-corpus",
        "url": "https://github.com/shauryr/ACL-anthology-corpus",
        "category": "paper_metadata",
        "type": "acl_paper_fulltext_metadata_corpus",
        "disciplines": ["nlp", "information_extraction", "summarization"],
        "use_for": ["信息抽取方法", "摘要方法", "主题聚类", "文本分析方法"],
        "allowed_pipeline": ["research", "method_card_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["bulk_pdf_rag_without_rights", "raw_paper_redistribution"],
        "license_check": "required",
        "commercial_risk": "medium",
    },
    {
        "id": "ydli_ai_csl",
        "repo": "ydli-ai/CSL",
        "url": "https://github.com/ydli-ai/CSL",
        "category": "paper_metadata",
        "type": "chinese_scientific_literature_dataset",
        "disciplines": ["scientific_literature", "classification", "keyword_extraction"],
        "use_for": ["中文论文摘要", "关键词抽取", "领域分类", "知识机制卡"],
        "allowed_pipeline": ["research", "abstract_only_synthesis", "knowledge_card_extraction"],
        "forbidden_pipeline": ["bulk_fulltext_rag_without_rights", "raw_dataset_redistribution"],
        "license_check": "required",
        "commercial_risk": "medium",
    },
    {
        "id": "chinese_rc_datasets",
        "repo": "ymcui/Chinese-RC-Datasets",
        "url": "https://github.com/ymcui/Chinese-RC-Datasets",
        "category": "paper_metadata",
        "type": "chinese_reading_comprehension_dataset_index",
        "disciplines": ["reading_comprehension", "question_answering", "text_analysis"],
        "use_for": ["阅读理解评估", "资料问答结构", "知识抽取测试"],
        "allowed_pipeline": ["research", "evaluation_method_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["raw_dataset_packaging", "direct_story_generation"],
        "license_check": "required",
        "commercial_risk": "medium",
    },
    {
        "id": "cdial_gpt",
        "repo": "thu-coai/CDial-GPT",
        "url": "https://github.com/thu-coai/CDial-GPT",
        "category": "dialogue_research",
        "type": "chinese_dialogue_model_and_data",
        "disciplines": ["dialogue", "conversation_style", "reader_feedback"],
        "use_for": ["对话风格观察", "口语表达模式", "闲聊场景约束"],
        "allowed_pipeline": ["research", "aggregate_pattern_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_dialogue_generation_from_raw_text", "raw_chat_corpus_storage"],
        "license_check": "required",
        "commercial_risk": "high",
    },
    {
        "id": "chinese_dialogue_dataset",
        "repo": "YouTaoBaBa/Chinese-Dialogue-Dataset",
        "url": "https://github.com/YouTaoBaBa/Chinese-Dialogue-Dataset",
        "category": "dialogue_research",
        "type": "chinese_dialogue_dataset_collection",
        "disciplines": ["dialogue", "conversation_style"],
        "use_for": ["中文对话数据索引", "口语表达观察", "角色对话约束"],
        "allowed_pipeline": ["research", "aggregate_pattern_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["raw_chat_corpus_storage", "commercial_generation_from_raw_dialogue"],
        "license_check": "required",
        "commercial_risk": "high",
    },
    {
        "id": "chinese_forum_corpus",
        "repo": "JaniceZhao/Chinese-Forum-Corpus",
        "url": "https://github.com/JaniceZhao/Chinese-Forum-Corpus",
        "category": "forum_research",
        "type": "chinese_forum_corpus",
        "disciplines": ["reader_feedback", "social_language", "sentiment_analysis"],
        "use_for": ["论坛语言分析", "读者情绪分析", "吐槽点聚类"],
        "allowed_pipeline": ["aggregate_statistics", "comment_pattern_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_generation", "redistribution", "raw_text_storage_in_product"],
        "license_check": "non_commercial_only_or_required",
        "commercial_risk": "high",
    },
    {
        "id": "chinese_chatbot_corpus",
        "repo": "codemayq/chinese-chatbot-corpus",
        "url": "https://github.com/codemayq/chinese-chatbot-corpus",
        "category": "forum_research",
        "type": "mixed_chinese_chatbot_corpus_collection",
        "disciplines": ["dialogue", "forum_language", "social_media_language"],
        "use_for": ["对话语气观察", "论坛回帖模式", "闲聊表达风险识别"],
        "allowed_pipeline": ["research", "aggregate_pattern_extraction", "risk_review"],
        "forbidden_pipeline": ["commercial_generation_from_raw_text", "raw_user_content_storage"],
        "license_check": "source_by_source_required",
        "commercial_risk": "high",
    },
    {
        "id": "open_domain_dialog_corpus",
        "repo": "Aman-4-Real/OpenDomainDialogCorpus",
        "url": "https://github.com/Aman-4-Real/OpenDomainDialogCorpus",
        "category": "forum_research",
        "type": "open_domain_dialog_corpus",
        "disciplines": ["dialogue", "conversation_style"],
        "use_for": ["开放域对话结构", "口语互动模式", "角色交流节奏"],
        "allowed_pipeline": ["research", "aggregate_pattern_extraction", "knowledge_card_extraction"],
        "forbidden_pipeline": ["commercial_generation_from_raw_text", "raw_user_content_storage"],
        "license_check": "required",
        "commercial_risk": "high",
    },
    {
        "id": "tieba_spider_tools",
        "repo": "ankanch/tieba-zhuaqu",
        "url": "https://github.com/ankanch/tieba-zhuaqu",
        "category": "crawler_tool_reference",
        "type": "tieba_crawler_tool",
        "disciplines": ["data_collection", "reader_feedback"],
        "use_for": ["技术参考", "风险识别", "采集边界设计"],
        "allowed_pipeline": ["tool_risk_review"],
        "forbidden_pipeline": ["bypassing_platform_limits", "raw_post_storage", "commercial_user_content_collection"],
        "license_check": "required",
        "commercial_risk": "very_high",
    },
    {
        "id": "tieba_spider_scrapy",
        "repo": "XylonFu/TiebaSpider",
        "url": "https://github.com/XylonFu/TiebaSpider",
        "category": "crawler_tool_reference",
        "type": "tieba_crawler_tool",
        "disciplines": ["data_collection", "reader_feedback"],
        "use_for": ["技术参考", "风险识别", "采集边界设计"],
        "allowed_pipeline": ["tool_risk_review"],
        "forbidden_pipeline": ["bypassing_platform_limits", "raw_post_storage", "commercial_user_content_collection"],
        "license_check": "required",
        "commercial_risk": "very_high",
    },
    {
        "id": "tieba_meow_scraper",
        "repo": "TiebaMeow/TiebaScraper",
        "url": "https://github.com/TiebaMeow/TiebaScraper",
        "category": "crawler_tool_reference",
        "type": "tieba_crawler_tool",
        "disciplines": ["data_collection", "reader_feedback"],
        "use_for": ["技术参考", "风险识别", "采集边界设计"],
        "allowed_pipeline": ["tool_risk_review"],
        "forbidden_pipeline": ["bypassing_platform_limits", "raw_post_storage", "commercial_user_content_collection"],
        "license_check": "required",
        "commercial_risk": "very_high",
    },
    {
        "id": "tieba_fetch",
        "repo": "910JQK/tieba-fetch",
        "url": "https://github.com/910JQK/tieba-fetch",
        "category": "crawler_tool_reference",
        "type": "tieba_crawler_tool",
        "disciplines": ["data_collection", "reader_feedback"],
        "use_for": ["技术参考", "风险识别", "采集边界设计"],
        "allowed_pipeline": ["tool_risk_review"],
        "forbidden_pipeline": ["bypassing_platform_limits", "raw_post_storage", "commercial_user_content_collection"],
        "license_check": "required",
        "commercial_risk": "very_high",
    },
]

SOURCE_CONNECTOR_ALLOWLIST = {
    "manual_metadata_connector": {"connector_kind": "manual", "network_access": False, "file_access": False, "risk_level": "low"},
    "local_manifest_connector": {"connector_kind": "local_file", "network_access": False, "file_access": True, "risk_level": "medium"},
    "classical_modern_local_manifest": {"connector_kind": "local_file", "network_access": False, "file_access": True, "risk_level": "medium"},
}


def list_source_policies(category: str | None = None) -> list[dict[str, Any]]:
    rows = deepcopy(SOURCE_POLICIES)
    if category:
        rows = [row for row in rows if row["category"] == category or row["id"] == category]
    return rows


def list_github_knowledge_sources(
    category: str | None = None,
    allowed_pipeline: str | None = None,
    max_risk: str | None = None,
) -> list[dict[str, Any]]:
    rows = deepcopy(GITHUB_KNOWLEDGE_SOURCES)
    if category:
        rows = [row for row in rows if row["category"] == category]
    if allowed_pipeline:
        rows = [row for row in rows if allowed_pipeline in row.get("allowed_pipeline", [])]
    if max_risk:
        rows = [row for row in rows if _risk_rank(row.get("commercial_risk", "")) <= _risk_rank(max_risk)]
    return rows


def get_github_knowledge_source(ref: str) -> dict[str, Any]:
    normalized = _normalize_ref(ref)
    for row in GITHUB_KNOWLEDGE_SOURCES:
        if normalized in {_normalize_ref(row["id"]), _normalize_ref(row["repo"]), _normalize_ref(row["url"])}:
            return deepcopy(row)
    raise KeyError(f"unknown GitHub knowledge source: {ref}")


def create_github_source_note(
    storage: LocalStorage,
    refs: list[str],
    discipline: str = "",
    project_context: str = "",
) -> tuple[Any, list[dict[str, Any]]]:
    if not refs:
        raise ValueError("repo_refs must include at least one registered GitHub source")
    sources = [get_github_knowledge_source(ref) for ref in refs]
    categories = sorted({str(source.get("category", "")) for source in sources if source.get("category")})
    source_urls = [str(source.get("url", "")) for source in sources if source.get("url")]
    note = SourceDocument(
        title=f"GitHub knowledge source intake: {', '.join(categories) or 'mixed'}",
        source="github-source-registry",
        tags=["github-source", "knowledge-intake", "license-review-required", *categories],
        content={
            "text": _source_note_text(sources, discipline, project_context),
            "sources": sources,
            "discipline": discipline,
            "project_context": project_context,
            "intake_policy": {
                "storage_policy": "metadata_only_until_license_review",
                "fetch_policy": "use official GitHub repository access only after operator license review",
                "raw_text_policy": "do not store raw forum/user text or protected novel text in reusable production assets",
                "knowledge_policy": "extract abstract mechanisms, constraints, review checks, and story functions",
            },
        },
        metadata={
            "source_kind": "github_source_registry",
            "source_urls": source_urls,
            "license_review_required": True,
            "rights": {
                "authorization": "unknown",
                "license": "per-source license check required before fetching or storing raw files",
                "copyright_boundary": "metadata-only GitHub source registry; no repository raw text copied",
                "source_url": ", ".join(source_urls),
                "allow_downstream_generation": False,
            },
            "allowed_pipeline": ["manual_handoff", "knowledge_card_extraction", "aggregate_pattern_extraction"],
            "forbidden_pipeline": [
                "direct_text_generation_without_rewrite",
                "raw_text_redistribution",
                "commercial_generation_from_high_risk_user_content",
            ],
        },
        references=[source["repo"] for source in sources],
    )
    return storage.write_asset("raw", note), sources


def create_source_policy(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    registry = _registry_source(source_ref)
    tier = _normalize_source_risk_tier(payload.get("risk_tier") or payload.get("risk_level") or registry.get("risk_tier") or registry.get("commercial_risk"))
    permissions = _permissions_for_tier(tier, payload)
    policy_id = str(payload.get("policy_id") or make_id("source_policy", f"{source_ref}:{tier}:{utc_now()}"))
    content = {
        "policy_id": policy_id,
        "source_ref": source_ref,
        "source_url": str(payload.get("source_url") or registry.get("url") or ""),
        "source_kind": str(payload.get("source_kind") or registry.get("category") or registry.get("type") or "unknown"),
        "risk_tier": tier,
        "risk_level": permissions["risk_level"],
        "allowed_pipeline": _strings(payload.get("allowed_pipeline")) or _strings(registry.get("allowed_pipeline")) or permissions["allowed_pipeline"],
        "forbidden_pipeline": _strings(payload.get("forbidden_pipeline")) or _strings(registry.get("forbidden_pipeline")) or permissions["forbidden_pipeline"],
        "generation_context_allowed": permissions["generation_context_allowed"],
        "raw_source_context_allowed": permissions["raw_source_context_allowed"],
        "evidence_only": permissions["evidence_only"],
        "structure_only": permissions["structure_only"],
        "quarantine": permissions["quarantine"],
        "review_status": str(payload.get("review_status") or permissions["review_status"]),
        "approval_required": permissions["approval_required"],
        "usage_rule": permissions["usage_rule"],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = SourcePolicy(
        id=policy_id,
        title=str(payload.get("title") or f"Source policy: {source_ref}"),
        source=source_ref,
        tags=_dedupe(["source-governance", "source-policy", tier, permissions["risk_level"], *(_strings(payload.get("tags")))]),
        content=content,
        metadata=_governance_metadata(payload, permissions),
        references=_strings(payload.get("evidence_refs")) or _strings(payload.get("references")),
    )
    return _write_governance_asset(storage, asset)


def create_source_sync_job(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    job_id = str(payload.get("job_id") or make_id("source_sync_job", f"{source_ref}:{utc_now()}"))
    content = {
        "job_id": job_id,
        "source_ref": source_ref,
        "status": str(payload.get("status") or "planned"),
        "sync_mode": str(payload.get("sync_mode") or "metadata_only"),
        "policy_ref": str(payload.get("policy_ref") or payload.get("source_policy_path") or ""),
        "checkpoint": payload.get("checkpoint", {}) if isinstance(payload.get("checkpoint", {}), dict) else {},
        "limits": payload.get("limits", {}) if isinstance(payload.get("limits", {}), dict) else {},
        "connector_execution": payload.get("connector_execution", {}) if isinstance(payload.get("connector_execution", {}), dict) else {},
        "approval_request_ref": str(payload.get("approval_request_ref") or ""),
        "refresh_report_ref": str(payload.get("refresh_report_ref") or ""),
        "execution_receipt": payload.get("execution_receipt", {}) if isinstance(payload.get("execution_receipt", {}), dict) else {},
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = SourceSyncJob(
        id=job_id,
        title=str(payload.get("title") or f"Source sync job: {source_ref}"),
        source=source_ref,
        tags=_dedupe(["source-governance", "source-sync", content["status"], content["sync_mode"]]),
        content=content,
        metadata=_governance_metadata(payload, _permissions_for_tier(_normalize_source_risk_tier(payload.get("risk_tier") or "R2"), payload)),
        references=_strings(payload.get("evidence_refs")) or _strings(payload.get("references")),
    )
    return _write_governance_asset(storage, asset)


def plan_source_connector_execution(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    connector_id = str(payload.get("connector_id") or "manual_metadata_connector").strip()
    connector_policy = SOURCE_CONNECTOR_ALLOWLIST.get(connector_id)
    environment = str(payload.get("environment") or "local")
    execute_requested = bool(payload.get("execute") or payload.get("execute_requested"))
    policy = _resolve_governance_asset(storage, payload.get("source_policy_path") or payload.get("policy_ref"), "source_policy") or _latest_related_asset(storage, "source_policy", source_ref)
    refresh = _resolve_governance_asset(storage, payload.get("source_refresh_report_path") or payload.get("refresh_report_ref"), "source_refresh_report") or _latest_related_asset(storage, "source_refresh_report", source_ref)
    approval_status = _approval_status(storage, payload.get("approval_request_path") or payload.get("approval_request_ref"))
    if not connector_policy:
        receipt = _connector_execution_receipt(
            connector_id=connector_id,
            source_ref=source_ref,
            status="blocked_connector_not_allowed",
            reason="connector is not in SOURCE_CONNECTOR_ALLOWLIST",
            approval_status=approval_status,
            execute_requested=execute_requested,
        )
        sync_job = create_source_sync_job(
            storage,
            {
                **payload,
                "source_ref": source_ref,
                "status": "blocked",
                "sync_mode": "connector_execution_plan",
                "policy_ref": _asset_ref(policy) or "missing_source_policy",
                "connector_execution": receipt["connector_execution"],
                "execution_receipt": receipt,
                "refresh_report_ref": _asset_ref(refresh),
            },
        )
        return {"status": "blocked", "allowed": False, "sync_job": sync_job, "approval_request": {}, "execution_receipt": receipt}
    approval_required = bool(execute_requested or is_production_environment(environment) or connector_policy["network_access"] or connector_policy["file_access"])
    approval_request: dict[str, Any] = {}
    if approval_required and approval_status != "approved":
        from novel_forge.modules.permission_center import create_approval_request

        approval_request = create_approval_request(
            storage,
            {
                "project_id": str(payload.get("project_id") or ""),
                "workspace_path": str(payload.get("workspace_path") or ""),
                "scope": "source",
                "action": "approve_source_connector_execution",
                "environment": environment,
                "risk_level": str(connector_policy.get("risk_level") or "medium"),
                "blocking": True,
                "target_type": "source_connector",
                "target_id": source_ref,
                "target_path": str(payload.get("source_path") or ""),
                "target_refs": [source_ref, connector_id],
                "evidence_refs": _dedupe([_asset_ref(refresh), *_strings(payload.get("evidence_refs")), *_strings(payload.get("references"))]),
                "reason": f"Approval required before connector {connector_id} can access source {source_ref}",
                "source_policy": {
                    "source_ref": source_ref,
                    "connector_id": connector_id,
                    "network_access": bool(connector_policy["network_access"]),
                    "file_access": bool(connector_policy["file_access"]),
                },
            },
        )
        approval_status = "pending"
    allowed = bool(connector_policy and (not execute_requested or approval_status == "approved") and not connector_policy["network_access"])
    status = "approved_execution_ready" if execute_requested and approval_status == "approved" else "approval_required" if approval_required and approval_status != "approved" else "dry_run_ready"
    receipt = _connector_execution_receipt(
        connector_id=connector_id,
        source_ref=source_ref,
        status=status,
        reason="execution is planned only; connector runner must use this receipt and approval evidence",
        approval_status=approval_status,
        execute_requested=execute_requested,
        connector_policy=connector_policy,
    )
    approval_ref = str(approval_request.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or "")
    sync_job = create_source_sync_job(
        storage,
        {
            **payload,
            "source_ref": source_ref,
            "status": status,
            "sync_mode": "connector_execution_plan",
            "policy_ref": _asset_ref(policy) or "missing_source_policy",
            "connector_execution": receipt["connector_execution"],
            "approval_request_ref": approval_ref,
            "refresh_report_ref": _asset_ref(refresh),
            "execution_receipt": receipt,
        },
    )
    return {"status": status, "allowed": allowed, "sync_job": sync_job, "approval_request": approval_request, "execution_receipt": receipt}


def create_license_check_result(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    authorization = str(payload.get("authorization") or payload.get("rights_authorization") or "unknown").strip().lower() or "unknown"
    license_name = str(payload.get("license_name") or payload.get("license") or "unknown")
    tier = _normalize_source_risk_tier(payload.get("risk_tier") or _tier_from_authorization(authorization, license_name))
    permissions = _permissions_for_tier(tier, payload)
    check_id = str(payload.get("check_id") or make_id("license_check_result", f"{source_ref}:{authorization}:{utc_now()}"))
    content = {
        "check_id": check_id,
        "source_ref": source_ref,
        "license_name": license_name,
        "authorization": authorization,
        "risk_tier": tier,
        "risk_level": permissions["risk_level"],
        "allowed_pipeline": _strings(payload.get("allowed_pipeline")) or permissions["allowed_pipeline"],
        "forbidden_pipeline": _strings(payload.get("forbidden_pipeline")) or permissions["forbidden_pipeline"],
        "generation_context_allowed": permissions["generation_context_allowed"],
        "raw_source_context_allowed": permissions["raw_source_context_allowed"],
        "evidence_refs": _strings(payload.get("evidence_refs")) or _strings(payload.get("references")),
        "checked_by": str(payload.get("checked_by") or "operator"),
        "checked_at": utc_now(),
        "notes": str(payload.get("notes") or payload.get("copyright_note") or ""),
    }
    asset = LicenseCheckResult(
        id=check_id,
        title=str(payload.get("title") or f"License check: {source_ref}"),
        source=source_ref,
        tags=_dedupe(["source-governance", "license-check", tier, permissions["risk_level"], authorization]),
        content=content,
        metadata=_governance_metadata(payload, permissions),
        references=content["evidence_refs"],
    )
    return _write_governance_asset(storage, asset)


def create_source_risk_report(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    policy = _resolve_governance_asset(storage, payload.get("source_policy_path") or payload.get("policy_ref"), "source_policy")
    license_result = _resolve_governance_asset(storage, payload.get("license_check_path") or payload.get("license_ref"), "license_check_result")
    tier = _normalize_source_risk_tier(
        payload.get("risk_tier")
        or payload.get("risk_level")
        or _content_value(policy, "risk_tier")
        or _content_value(license_result, "risk_tier")
        or _registry_source(source_ref).get("commercial_risk")
    )
    permissions = _permissions_for_tier(tier, payload)
    risk_flags = _source_risk_flags(source_ref, tier, payload, policy=policy, license_result=license_result)
    report_id = str(payload.get("report_id") or make_id("source_risk_report", f"{source_ref}:{tier}:{utc_now()}"))
    content = {
        "report_id": report_id,
        "source_ref": source_ref,
        "source_policy_ref": _asset_ref(policy),
        "license_check_ref": _asset_ref(license_result),
        "risk_tier": tier,
        "risk_level": permissions["risk_level"],
        "risk_flags": risk_flags,
        "generation_context_allowed": permissions["generation_context_allowed"],
        "raw_source_context_allowed": permissions["raw_source_context_allowed"],
        "evidence_only": permissions["evidence_only"],
        "structure_only": permissions["structure_only"],
        "quarantine": permissions["quarantine"],
        "approval_required": permissions["approval_required"],
        "recommendation": _risk_recommendation(tier, permissions),
        "created_at": utc_now(),
    }
    asset = SourceRiskReport(
        id=report_id,
        title=str(payload.get("title") or f"Source risk report: {source_ref}"),
        source=source_ref,
        tags=_dedupe(["source-governance", "source-risk", tier, permissions["risk_level"], *risk_flags]),
        content=content,
        metadata=_governance_metadata(payload, permissions),
        references=_dedupe([_asset_ref(policy), _asset_ref(license_result), *_strings(payload.get("evidence_refs")), *_strings(payload.get("references"))]),
    )
    return _write_governance_asset(storage, asset)


def create_source_snapshot(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    source_path = str(payload.get("source_path") or payload.get("asset_path") or source_ref)
    source_asset = _resolve_governance_asset(storage, source_path, "")
    source_type = str(payload.get("source_type") or (source_asset or {}).get("type") or "external_source")
    content_text = _snapshot_text(storage, payload, source_asset=source_asset)
    content_hash = str(payload.get("content_hash") or hashlib.sha256(content_text.encode("utf-8")).hexdigest())
    policy = _resolve_governance_asset(storage, payload.get("source_policy_path") or payload.get("policy_ref"), "source_policy")
    risk = _resolve_governance_asset(storage, payload.get("risk_report_path") or payload.get("risk_ref"), "source_risk_report")
    snapshot_id = str(payload.get("snapshot_id") or make_id("source_snapshot", f"{source_ref}:{content_hash}"))
    content = {
        "snapshot_id": snapshot_id,
        "source_ref": source_ref,
        "source_type": source_type,
        "content_hash": content_hash,
        "source_path": source_path,
        "line_range": payload.get("line_range", {}) if isinstance(payload.get("line_range", {}), dict) else {},
        "span": payload.get("span", {}) if isinstance(payload.get("span", {}), dict) else {},
        "captured_at": utc_now(),
        "source_policy_ref": _asset_ref(policy),
        "risk_report_ref": _asset_ref(risk),
        "evidence_only": True,
        "raw_text_included": False,
    }
    asset = SourceSnapshot(
        id=snapshot_id,
        title=str(payload.get("title") or f"Source snapshot: {source_ref}"),
        source=source_ref,
        tags=_dedupe(["source-governance", "source-snapshot", "evidence-only", source_type]),
        content=content,
        metadata={
            **_governance_metadata(payload, _permissions_for_tier(_normalize_source_risk_tier(payload.get("risk_tier") or _content_value(risk, "risk_tier") or "R2"), payload)),
            "content_hash": content_hash,
            "raw_text_included": False,
            "use_in_generation_rag": False,
        },
        references=_dedupe([source_path, _asset_ref(policy), _asset_ref(risk), *_strings(payload.get("evidence_refs")), *_strings(payload.get("references"))]),
    )
    return _write_governance_asset(storage, asset)


def create_source_refresh_report(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    policy = _resolve_governance_asset(storage, payload.get("source_policy_path") or payload.get("policy_ref"), "source_policy") or _latest_related_asset(storage, "source_policy", source_ref)
    license_result = _resolve_governance_asset(storage, payload.get("license_check_path") or payload.get("license_ref"), "license_check_result") or _latest_related_asset(storage, "license_check_result", source_ref)
    risk_report = _resolve_governance_asset(storage, payload.get("risk_report_path") or payload.get("risk_ref"), "source_risk_report") or _latest_related_asset(storage, "source_risk_report", source_ref)
    snapshot = _resolve_governance_asset(storage, payload.get("snapshot_path") or payload.get("snapshot_ref"), "source_snapshot") or _latest_related_asset(storage, "source_snapshot", source_ref)
    sync_job = _resolve_governance_asset(storage, payload.get("sync_job_path") or payload.get("sync_job_ref"), "source_sync_job") or _latest_related_asset(storage, "source_sync_job", source_ref)
    stale_flags = _source_refresh_stale_flags(payload, policy=policy, license_result=license_result, risk_report=risk_report, snapshot=snapshot, sync_job=sync_job)
    decision = _source_refresh_decision(stale_flags, risk_report=risk_report)
    approval_required = decision in {"missing_governance", "blocked_quarantined", "needs_policy_review"} or bool(payload.get("connector_execution_requested"))
    report_id = str(payload.get("refresh_report_id") or make_id("source_refresh_report", f"{_short_ref_key(source_ref)}:{decision}:{utc_now()}"))
    governance_refs = {
        "source_policy_ref": _asset_ref(policy),
        "license_check_ref": _asset_ref(license_result),
        "source_risk_report_ref": _asset_ref(risk_report),
        "source_snapshot_ref": _asset_ref(snapshot),
        "source_sync_job_ref": _asset_ref(sync_job),
    }
    content = {
        "refresh_report_id": report_id,
        "source_ref": source_ref,
        "refresh_mode": "audit_only",
        "decision": decision,
        "stale_flags": stale_flags,
        "connector_execution_allowed": False,
        "approval_required": approval_required,
        "governance_refs": governance_refs,
        "source_isolation": {
            "raw_text_included": False,
            "connector_executed": False,
            "network_access_used": False,
            "report_is_evidence_only": True,
        },
        "snapshot": _refresh_asset_digest(snapshot, ["snapshot_id", "source_type", "content_hash", "captured_at", "source_path"]),
        "sync_job": _refresh_asset_digest(sync_job, ["job_id", "status", "sync_mode", "checkpoint", "updated_at"]),
        "risk": _refresh_asset_digest(risk_report, ["report_id", "risk_tier", "risk_level", "generation_context_allowed", "evidence_only", "quarantine"]),
        "next_actions": _source_refresh_next_actions(decision, stale_flags),
        "created_at": utc_now(),
    }
    asset = SourceRefreshReport(
        id=report_id,
        title=str(payload.get("title") or f"Source refresh report: {source_ref}"),
        source=source_ref,
        tags=_dedupe(["source-governance", "source-refresh", decision, "audit-only", *[str(flag.get("code", "")) for flag in stale_flags if isinstance(flag, dict)]]),
        content=content,
        metadata={
            **_governance_metadata(payload, _permissions_for_tier(_normalize_source_risk_tier(_content_value(risk_report, "risk_tier") or _content_value(policy, "risk_tier") or "R2"), payload)),
            "refresh_mode": "audit_only",
            "decision": decision,
            "connector_execution_allowed": False,
            "network_access_used": False,
            "use_in_generation_rag": False,
        },
        references=_dedupe([value for value in governance_refs.values() if value] + _strings(payload.get("evidence_refs")) + _strings(payload.get("references"))),
    )
    return _write_governance_asset(storage, asset)


def evaluate_source_context_eligibility(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    source_asset = _resolve_governance_asset(storage, payload.get("asset_path") or payload.get("source_path"), "")
    policy = _resolve_governance_asset(storage, payload.get("source_policy_path") or payload.get("policy_ref"), "source_policy") or _latest_related_asset(storage, "source_policy", source_ref)
    license_result = _resolve_governance_asset(storage, payload.get("license_check_path") or payload.get("license_ref"), "license_check_result") or _latest_related_asset(storage, "license_check_result", source_ref)
    risk_report = _resolve_governance_asset(storage, payload.get("risk_report_path") or payload.get("risk_ref"), "source_risk_report") or _latest_related_asset(storage, "source_risk_report", source_ref)
    inferred = _tier_from_source_asset(source_asset) if source_asset else ""
    tier = _normalize_source_risk_tier(
        payload.get("risk_tier")
        or _content_value(risk_report, "risk_tier")
        or _content_value(policy, "risk_tier")
        or _content_value(license_result, "risk_tier")
        or inferred
        or _registry_source(source_ref).get("commercial_risk")
    )
    permissions = _permissions_for_tier(tier, payload)
    source_type = str((source_asset or {}).get("type") or payload.get("source_type") or "external_source")
    raw_request = bool(payload.get("request_raw_context") or payload.get("raw_source_context_requested"))
    raw_allowed = bool(permissions["raw_source_context_allowed"] and _raw_context_request_allowed(source_asset, payload))
    production = is_production_environment(str(payload.get("environment") or ""))
    blocking = bool(production and (not permissions["generation_context_allowed"] or raw_request and not raw_allowed))
    approval_payload = _approval_request_payload(payload, source_ref=source_ref, tier=tier, permissions=permissions, source_asset=source_asset, blocking=blocking)
    approval_request: dict[str, Any] | None = None
    if bool(payload.get("create_approval_request")) and approval_payload:
        from novel_forge.modules.permission_center import create_approval_request

        approval_request = create_approval_request(storage, approval_payload)
    return {
        "source_ref": source_ref,
        "source_type": source_type,
        "risk_tier": tier,
        "risk_level": permissions["risk_level"],
        "generation_context_allowed": bool(permissions["generation_context_allowed"]),
        "raw_source_context_allowed": raw_allowed,
        "evidence_only": bool(permissions["evidence_only"]),
        "structure_only": bool(permissions["structure_only"]),
        "quarantine": bool(permissions["quarantine"]),
        "approval_required": bool(permissions["approval_required"] or blocking),
        "requires_approval_request": bool(approval_payload),
        "blocking": blocking,
        "environment": str(payload.get("environment") or "local"),
        "intended_stage": str(payload.get("intended_stage") or payload.get("stage") or ""),
        "usable_context_form": _usable_context_form(tier, source_type, raw_allowed=raw_allowed),
        "reason": _eligibility_reason(tier, permissions, raw_request=raw_request, raw_allowed=raw_allowed),
        "policy_ref": _asset_ref(policy),
        "license_check_ref": _asset_ref(license_result),
        "risk_report_ref": _asset_ref(risk_report),
        "approval_request": approval_request,
        "source_governance": {
            "policy_present": bool(policy),
            "license_check_present": bool(license_result),
            "risk_report_present": bool(risk_report),
            "registry_entry_present": bool(_registry_source(source_ref)),
        },
    }


def _source_note_text(sources: list[dict[str, Any]], discipline: str, project_context: str) -> str:
    lines = [
        "GitHub knowledge source intake note.",
        "This asset records source metadata and policy only; it does not contain repository raw text.",
        f"Discipline: {discipline or 'unspecified'}",
        f"Project context: {project_context or 'unspecified'}",
        "",
        "Registered sources:",
    ]
    for source in sources:
        lines.extend(
            [
                f"- {source['repo']}",
                f"  URL: {source['url']}",
                f"  Category: {source['category']}",
                f"  Type: {source['type']}",
                f"  Use for: {', '.join(source['use_for'])}",
                f"  Allowed pipeline: {', '.join(source['allowed_pipeline'])}",
                f"  Forbidden pipeline: {', '.join(source['forbidden_pipeline'])}",
                f"  License check: {source['license_check']}",
                f"  Commercial risk: {source['commercial_risk']}",
            ]
        )
    lines.extend(
        [
            "",
            "Operator instructions:",
            "1. Verify each repository license before cloning, downloading, or reading raw files.",
            "2. Prefer metadata, papers, README descriptions, aggregate statistics, and schema notes before raw corpus text.",
            "3. Convert permitted information into abstract KnowledgeCard principles, constraints, conflict generators, or review checks.",
            "4. Do not preserve raw forum posts, private user identifiers, protected novel text, or crawler outputs as production material.",
        ]
    )
    return "\n".join(lines)


def _write_governance_asset(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _source_ref(payload: dict[str, Any]) -> str:
    for key in ["source_ref", "source_id", "source_url", "repo", "asset_path", "source_path"]:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    raise ValueError("source_ref, source_id, source_url, repo, asset_path, or source_path is required")


def _registry_source(source_ref: str) -> dict[str, Any]:
    normalized = _normalize_ref(source_ref)
    for row in GITHUB_KNOWLEDGE_SOURCES:
        if normalized in {_normalize_ref(row["id"]), _normalize_ref(row["repo"]), _normalize_ref(row["url"])}:
            return deepcopy(row)
    for row in SOURCE_POLICIES:
        if normalized in {_normalize_ref(row["id"]), _normalize_ref(row["name"]), _normalize_ref(row["url"])}:
            return deepcopy(row)
    return {}


def _normalize_source_risk_tier(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "r0": "R0",
        "owned": "R0",
        "self_owned": "R0",
        "test_fixture": "R0",
        "r1": "R1",
        "public_domain": "R1",
        "licensed": "R1",
        "permission_granted": "R1",
        "open": "R1",
        "low": "R1",
        "low_medium": "R1",
        "r2": "R2",
        "unknown": "R2",
        "unclear": "R2",
        "medium": "R2",
        "r3": "R3",
        "high": "R3",
        "medium_high": "R3",
        "reference_only": "R3",
        "structure_only": "R3",
        "r4": "R4",
        "very_high": "R4",
        "infringing": "R4",
        "pirated": "R4",
        "private": "R4",
        "forbidden": "R4",
        "critical": "R4",
    }
    return aliases.get(normalized, "R2")


def _permissions_for_tier(tier: str, payload: dict[str, Any]) -> dict[str, Any]:
    allow_raw = bool(payload.get("allow_raw_context") or payload.get("raw_source_context_allowed"))
    base = {
        "R0": {
            "risk_level": "low",
            "generation_context_allowed": True,
            "raw_source_context_allowed": allow_raw,
            "evidence_only": False,
            "structure_only": False,
            "quarantine": False,
            "approval_required": bool(allow_raw),
            "review_status": "approved" if payload.get("review_status") else "needs_review",
            "allowed_pipeline": ["catalog", "evidence", "knowledge_card_extraction", "context_after_policy"],
            "forbidden_pipeline": ["untracked_raw_redistribution"],
            "usage_rule": "owned/test-fixture source may support generation only through explicit policy and traceable source refs",
        },
        "R1": {
            "risk_level": "low",
            "generation_context_allowed": True,
            "raw_source_context_allowed": False,
            "evidence_only": False,
            "structure_only": False,
            "quarantine": False,
            "approval_required": False,
            "review_status": "needs_review",
            "allowed_pipeline": ["catalog", "evidence", "knowledge_card_extraction", "abstract_context"],
            "forbidden_pipeline": ["raw_text_redistribution", "uncited_generation_context"],
            "usage_rule": "licensed/public-domain source may feed abstracted assets and cited evidence, not raw prose context by default",
        },
        "R2": {
            "risk_level": "medium",
            "generation_context_allowed": False,
            "raw_source_context_allowed": False,
            "evidence_only": True,
            "structure_only": False,
            "quarantine": False,
            "approval_required": True,
            "review_status": "needs_license_review",
            "allowed_pipeline": ["catalog", "evidence", "reviewable_candidate"],
            "forbidden_pipeline": ["generation_context", "raw_text_redistribution"],
            "usage_rule": "unclear source remains evidence-only until license review resolves the boundary",
        },
        "R3": {
            "risk_level": "high",
            "generation_context_allowed": False,
            "raw_source_context_allowed": False,
            "evidence_only": True,
            "structure_only": True,
            "quarantine": False,
            "approval_required": True,
            "review_status": "restricted",
            "allowed_pipeline": ["catalog", "evidence", "structure_only_analysis"],
            "forbidden_pipeline": ["generation_context", "raw_text_redistribution", "style_imitation"],
            "usage_rule": "high-risk source may only produce abstract structure/mechanism evidence",
        },
        "R4": {
            "risk_level": "critical",
            "generation_context_allowed": False,
            "raw_source_context_allowed": False,
            "evidence_only": True,
            "structure_only": False,
            "quarantine": True,
            "approval_required": True,
            "review_status": "quarantined",
            "allowed_pipeline": ["catalog", "quarantine_record"],
            "forbidden_pipeline": ["generation_context", "knowledge_card_activation", "raw_storage", "redistribution"],
            "usage_rule": "forbidden source must stay quarantined and cannot activate production assets",
        },
    }
    return dict(base.get(tier, base["R2"]))


def _governance_metadata(payload: dict[str, Any], permissions: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(payload.get("project_id") or ""),
        "workspace_path": str(payload.get("workspace_path") or ""),
        "risk_level": permissions["risk_level"],
        "generation_context_allowed": bool(permissions["generation_context_allowed"]),
        "raw_source_context_allowed": bool(permissions["raw_source_context_allowed"]),
        "evidence_only": bool(permissions["evidence_only"]),
        "quarantine": bool(permissions["quarantine"]),
        "use_in_generation_rag": bool(permissions["generation_context_allowed"]) and not bool(permissions["evidence_only"]),
        "copyright_boundary": "source governance asset; raw source text remains isolated unless an explicit owned-source policy allows it",
    }


def _tier_from_authorization(authorization: str, license_name: str) -> str:
    if authorization in {"owned", "test_fixture"}:
        return "R0"
    if authorization in {"licensed", "public_domain", "permission_granted"}:
        return "R1"
    lowered = license_name.lower()
    if any(marker in lowered for marker in ["non-commercial", "noncommercial", "cc by-nc", "by-nc", "nc-sa"]):
        return "R3"
    if authorization in {"forbidden", "pirated", "infringing", "private"}:
        return "R4"
    return "R2"


def _tier_from_source_asset(source_asset: dict[str, Any] | None) -> str:
    if not source_asset:
        return ""
    metadata = source_asset.get("metadata", {}) if isinstance(source_asset.get("metadata", {}), dict) else {}
    rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
    if metadata.get("quarantine") or rights.get("authorization") in {"forbidden", "pirated", "infringing", "private"}:
        return "R4"
    if rights.get("authorization") in {"owned", "test_fixture"}:
        return "R0"
    if rights.get("authorization") in {"licensed", "public_domain", "permission_granted"}:
        return "R1"
    if metadata.get("copyright_risk") in {"high", "critical"} or metadata.get("risk_level") in {"high", "critical"}:
        return "R3"
    if rights.get("allow_downstream_generation") is False:
        return "R2"
    return ""


def _source_risk_flags(
    source_ref: str,
    tier: str,
    payload: dict[str, Any],
    *,
    policy: dict[str, Any] | None,
    license_result: dict[str, Any] | None,
) -> list[str]:
    flags = [tier.lower()]
    registry = _registry_source(source_ref)
    if not policy:
        flags.append("policy_missing")
    if not license_result:
        flags.append("license_check_missing")
    if registry.get("license_check") in {"required", "non_commercial_only_or_required", "source_by_source_required"} and not license_result:
        flags.append("registry_requires_license_check")
    if tier in {"R2", "R3", "R4"}:
        flags.append("generation_context_blocked")
    if tier == "R4":
        flags.append("quarantine_required")
    if payload.get("include_parallel_pairs"):
        flags.append("parallel_pair_source_leakage_risk")
    return _dedupe(flags)


def _risk_recommendation(tier: str, permissions: dict[str, Any]) -> str:
    if tier in {"R0", "R1"}:
        return "usable after evidence refs and source policy are attached; prefer abstract assets over raw source context"
    if tier == "R2":
        return "keep evidence-only; run license review before activating knowledge cards or generation context"
    if tier == "R3":
        return "allow structure-only analysis; do not activate raw text, style imitation, or prose context"
    return "quarantine source; do not activate production assets without explicit operator/legal decision"


def _usable_context_form(tier: str, source_type: str, *, raw_allowed: bool) -> str:
    if tier == "R4":
        return "none_quarantined"
    if tier in {"R2", "R3"}:
        return "evidence_only_structure_only" if tier == "R3" else "evidence_only"
    if raw_allowed and source_type not in {"source_chunk"}:
        return "raw_context_with_traceable_policy"
    return "abstracted_assets_only"


def _eligibility_reason(tier: str, permissions: dict[str, Any], *, raw_request: bool, raw_allowed: bool) -> str:
    if raw_request and not raw_allowed:
        return f"raw source context denied for {tier}; {permissions['usage_rule']}"
    if permissions["generation_context_allowed"]:
        return permissions["usage_rule"]
    return f"generation context denied for {tier}; {permissions['usage_rule']}"


def _raw_context_request_allowed(source_asset: dict[str, Any] | None, payload: dict[str, Any]) -> bool:
    if not source_asset:
        return False
    metadata = source_asset.get("metadata", {}) if isinstance(source_asset.get("metadata", {}), dict) else {}
    rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
    return bool(payload.get("allow_raw_context")) and rights.get("authorization") in {"owned", "test_fixture"} and source_asset.get("type") == "source_document"


def _approval_request_payload(
    payload: dict[str, Any],
    *,
    source_ref: str,
    tier: str,
    permissions: dict[str, Any],
    source_asset: dict[str, Any] | None,
    blocking: bool,
) -> dict[str, Any] | None:
    if not permissions["approval_required"] and not blocking:
        return None
    return {
        "project_id": str(payload.get("project_id") or _metadata_value(source_asset, "project_id")),
        "workspace_path": str(payload.get("workspace_path") or _metadata_value(source_asset, "workspace_path")),
        "scope": "source",
        "action": str(payload.get("approval_action") or "approve_source_context_eligibility"),
        "environment": str(payload.get("environment") or "local"),
        "risk_level": "critical" if tier == "R4" else ("high" if tier == "R3" else "medium"),
        "blocking": blocking,
        "target_type": str((source_asset or {}).get("type") or "source"),
        "target_id": str((source_asset or {}).get("id") or source_ref),
        "target_path": str(payload.get("asset_path") or payload.get("source_path") or ""),
        "target_refs": _strings(payload.get("target_refs")),
        "evidence_refs": _strings(payload.get("evidence_refs")) or _strings(payload.get("references")),
        "reason": f"Source {source_ref} is {tier}; {permissions['usage_rule']}",
        "source_policy": {"source_ref": source_ref, "risk_tier": tier, "generation_context_allowed": permissions["generation_context_allowed"]},
    }


def _source_refresh_stale_flags(
    payload: dict[str, Any],
    *,
    policy: dict[str, Any] | None,
    license_result: dict[str, Any] | None,
    risk_report: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    sync_job: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    if not policy:
        flags.append({"code": "source_policy_missing", "severity": "high", "message": "SourcePolicy evidence is missing"})
    if not license_result:
        flags.append({"code": "license_check_missing", "severity": "medium", "message": "LicenseCheckResult evidence is missing"})
    if not risk_report:
        flags.append({"code": "source_risk_report_missing", "severity": "high", "message": "SourceRiskReport evidence is missing"})
    if not snapshot:
        flags.append({"code": "source_snapshot_missing", "severity": "medium", "message": "SourceSnapshot evidence is missing"})
    if not sync_job:
        flags.append({"code": "source_sync_job_missing", "severity": "low", "message": "SourceSyncJob evidence is missing"})
    if _content_value(risk_report, "quarantine"):
        flags.append({"code": "source_quarantined", "severity": "critical", "message": "Latest SourceRiskReport marks the source as quarantined"})
    sync_status = str(_content_value(sync_job, "status") or "").strip().lower()
    if sync_status and sync_status not in {"succeeded", "completed", "current", "noop", "skipped_existing"}:
        flags.append({"code": "sync_not_current", "severity": "medium", "message": f"Latest SourceSyncJob status is {sync_status}"})
    expected_hash = str(payload.get("expected_content_hash") or payload.get("content_hash") or "").strip()
    snapshot_hash = str(_content_value(snapshot, "content_hash") or "").strip()
    if expected_hash and snapshot_hash and expected_hash != snapshot_hash:
        flags.append({"code": "content_hash_drift", "severity": "high", "message": "Expected content hash differs from latest SourceSnapshot hash"})
    max_age_days = _int(payload.get("max_snapshot_age_days"), 0)
    captured_at = str(_content_value(snapshot, "captured_at") or "").strip()
    age_days = _age_days(captured_at)
    if max_age_days > 0 and age_days is not None and age_days > max_age_days:
        flags.append({"code": "source_snapshot_stale", "severity": "medium", "message": f"Latest SourceSnapshot is {age_days} days old", "age_days": age_days, "max_age_days": max_age_days})
    return flags


def _source_refresh_decision(stale_flags: list[dict[str, Any]], *, risk_report: dict[str, Any] | None) -> str:
    codes = {str(flag.get("code") or "") for flag in stale_flags if isinstance(flag, dict)}
    if "source_quarantined" in codes or _content_value(risk_report, "quarantine"):
        return "blocked_quarantined"
    if {"source_policy_missing", "source_risk_report_missing"} & codes:
        return "missing_governance"
    if "content_hash_drift" in codes or "source_snapshot_stale" in codes:
        return "needs_snapshot_refresh"
    if "license_check_missing" in codes or "source_snapshot_missing" in codes:
        return "needs_policy_review"
    if "sync_not_current" in codes or "source_sync_job_missing" in codes:
        return "needs_sync_review"
    return "current"


def _source_refresh_next_actions(decision: str, stale_flags: list[dict[str, Any]]) -> list[str]:
    actions = {
        "current": ["keep current governance evidence; do not execute connector"],
        "missing_governance": ["create or refresh SourcePolicy and SourceRiskReport before source-derived assets are used"],
        "blocked_quarantined": ["keep source quarantined; require explicit operator/legal approval before any future connector or context use"],
        "needs_snapshot_refresh": ["create a new SourceSnapshot through an approval-gated connector or manual evidence import", "rerun SourceRiskReport after snapshot refresh"],
        "needs_policy_review": ["complete license and policy review before promoting source-derived assets"],
        "needs_sync_review": ["review latest SourceSyncJob checkpoint before connector execution; keep execution approval-gated"],
    }
    selected = list(actions.get(decision, ["review source governance evidence"]))
    if any(str(flag.get("code") or "") == "content_hash_drift" for flag in stale_flags if isinstance(flag, dict)):
        selected.append("invalidate downstream source-derived material until the refreshed snapshot is reviewed")
    return selected


def _connector_execution_receipt(
    *,
    connector_id: str,
    source_ref: str,
    status: str,
    reason: str,
    approval_status: str,
    execute_requested: bool,
    connector_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = connector_policy or {}
    return {
        "receipt_id": make_id("source_connector_execution_receipt", f"{_short_ref_key(source_ref)}:{connector_id}:{status}:{utc_now()}"),
        "status": status,
        "source_ref": source_ref,
        "connector_id": connector_id,
        "approval_status": approval_status or "missing",
        "execute_requested": execute_requested,
        "execution_performed": False,
        "network_access_used": False,
        "file_access_used": False,
        "connector_execution": {
            "connector_id": connector_id,
            "connector_kind": str(policy.get("connector_kind") or "unknown"),
            "allowlisted": bool(connector_policy),
            "network_access_allowed": bool(policy.get("network_access")),
            "file_access_allowed": bool(policy.get("file_access")),
            "execution_boundary": "plan_only_no_connector_invocation",
        },
        "reason": reason,
        "rollback_plan": ["no external side effects were performed", "discard SourceSyncJob plan if approval is rejected"],
        "created_at": utc_now(),
    }


def _approval_status(storage: LocalStorage, ref: Any) -> str:
    text = str(ref or "").strip()
    if not text:
        return ""
    try:
        data = storage.read_json(resolve_path(storage.root, text))
    except (OSError, TypeError, ValueError):
        return ""
    if not isinstance(data, dict) or data.get("type") != "approval_request":
        return ""
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(content.get("status") or "")


def _refresh_asset_digest(asset: dict[str, Any] | None, fields: list[str]) -> dict[str, Any]:
    if not asset:
        return {"present": False}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return {
        "present": True,
        "asset_id": str(asset.get("id") or ""),
        "type": str(asset.get("type") or ""),
        **{field: content.get(field) for field in fields if field in content},
    }


def _short_ref_key(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _age_days(timestamp: str) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 86400))


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _snapshot_text(storage: LocalStorage, payload: dict[str, Any], *, source_asset: dict[str, Any] | None) -> str:
    explicit = payload.get("content") or payload.get("text") or payload.get("content_preview")
    if isinstance(explicit, str):
        return explicit
    if source_asset:
        content = source_asset.get("content", {}) if isinstance(source_asset.get("content", {}), dict) else {}
        text = str(content.get("text") or content.get("clean_text") or "")
        if text:
            return text
    source_path = str(payload.get("source_path") or payload.get("asset_path") or "")
    if source_path:
        try:
            path = resolve_path(storage.root, source_path)
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, TypeError, ValueError):
            return source_path
    return str(payload)


def _resolve_governance_asset(storage: LocalStorage, ref: Any, expected_type: str) -> dict[str, Any] | None:
    ref_text = str(ref or "").strip()
    if not ref_text:
        return None
    try:
        path = resolve_path(storage.root, ref_text)
        data = storage.read_json(path)
        if isinstance(data, dict) and (not expected_type or data.get("type") == expected_type):
            return data
    except (OSError, TypeError, ValueError):
        pass
    for category in ["raw", "runs"]:
        for path in reversed(storage.list_json(category)):
            try:
                data = storage.read_json(path)
            except (OSError, TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            if expected_type and data.get("type") != expected_type:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            if ref_text in {
                str(data.get("id", "")),
                str(content.get("policy_id", "")),
                str(content.get("check_id", "")),
                str(content.get("report_id", "")),
                str(content.get("snapshot_id", "")),
                _display_path(storage.root, path),
            }:
                return data
    return None


def _latest_related_asset(storage: LocalStorage, asset_type: str, source_ref: str) -> dict[str, Any] | None:
    normalized = _normalize_ref(source_ref)
    for category in ["runs", "raw"]:
        for path in reversed(storage.list_json(category)):
            try:
                data = storage.read_json(path)
            except (OSError, TypeError, ValueError):
                continue
            if not isinstance(data, dict) or data.get("type") != asset_type:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            if normalized == _normalize_ref(str(content.get("source_ref") or data.get("source") or "")):
                return data
    return None


def _content_value(asset: dict[str, Any] | None, key: str) -> Any:
    if not asset:
        return ""
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return content.get(key) or asset.get(key) or ""


def _asset_ref(asset: dict[str, Any] | None) -> str:
    if not asset:
        return ""
    return str(asset.get("id") or "")


def _metadata_value(asset: dict[str, Any] | None, key: str) -> str:
    if not asset:
        return ""
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    return str(metadata.get(key) or "")


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _normalize_ref(value: str) -> str:
    return value.strip().lower().removeprefix("https://github.com/").removesuffix("/")


def _risk_rank(value: str) -> int:
    ranks = {
        "low": 1,
        "low_medium": 2,
        "medium": 3,
        "medium_high": 4,
        "high": 5,
        "very_high": 6,
    }
    return ranks.get(value, 999)
