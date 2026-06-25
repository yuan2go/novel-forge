from __future__ import annotations

from copy import deepcopy
from typing import Any

from novel_forge.schemas import SourceDocument
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
