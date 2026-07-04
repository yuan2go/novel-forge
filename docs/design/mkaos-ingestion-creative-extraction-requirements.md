# MKAOS Ingestion 与 Creative Extraction 设计文档

日期：2026-07-04  
目标分支：`feat/v6-post-mkaos-industrialization`  
适用系统：本地自用 Novel Operating System，不面向 SaaS、多租户或团队协作

---

## 1. 需求结论

当前 MKAOS 已经完成 P0 知识资产治理内核：Source Document、Source Chunk、Knowledge Card、Usage Binding、Rule Card、Template Card、Knowledge Pack、Query / Convert、Knowledge Graph、Effect Feedback、Artifact validation、Canon conflict check、Usage event、Review feedback、weight update 等能力已经具备。

但如果 Novel OS 要稳定导入并解析大型文本资产，例如：

- 古籍仓库：`NiuTrans/Classical-Modern`；
- 网文拆解库；
- 出版小说拆解库；
- 专业书籍；
- 论文；
- 平台规则；
- 论坛、评论、贴吧、读者反馈；
- 本地 TXT / MD / JSON / CSV / EPUB / PDF / DOCX；

那么当前 MKAOS 仍不能只停留在“文本导入 + 切块 + 知识卡”。下一阶段必须建设：

> MKAOS Ingestion Center + Source Type Extractors + Creative Knowledge Conversion + Extraction Quality Gate + MKAOS Knowledge Graph Deepening。

核心升级方向：

```text
外部文本 / 仓库 / 书籍 / 语料
  -> 证据层导入与清洗
  -> 类型化拆解
  -> CreativeKnowledgeCard
  -> 创作资产转换
  -> Knowledge Pack
  -> 题材 / 世界观 / 人物 / 大纲 / 细纲 / 正文 / 审稿 / 复盘 / 反馈
```

---

## 2. 当前 MKAOS 能力边界

### 2.1 已具备能力

当前 MKAOS 已满足以下基础能力：

1. 来源文档导入；
2. 来源切块；
3. 知识卡创建和编辑；
4. 用途绑定；
5. Rule Card / Template Card；
6. Knowledge Pack 构建；
7. Query / Convert；
8. Multidisciplinary Knowledge Graph；
9. Effect Feedback Learning Snapshot；
10. Artifact validation；
11. Canon conflict check；
12. Usage event；
13. Review feedback；
14. weight update；
15. risk knowledge 列表；
16. P0 acceptance fixture。

支持 flow：

- `outline`
- `chapter_outline`
- `prose`
- `review`
- `revision`
- `recap`
- `publish`
- `feedback`

这说明 MKAOS 已经具备“知识资产操作系统内核”，但还不是完整的“多类型文本资产加工厂”。

### 2.2 当前不足

当前 MKAOS 的主要不足不是“没有知识卡”，而是：

1. 缺仓库级导入；
2. 缺书籍级 manifest；
3. 缺章节级 manifest；
4. 缺句对级 parallel text pair；
5. 缺 source type 专用 extractor；
6. 缺古籍、网文、专业书、推理小说、平台规则等类型化拆解；
7. 缺 KnowledgeCard 到创作资产的自动转换；
8. 缺拆解结果质量评估；
9. 缺 quote leakage / near duplicate / anti exposition gate；
10. 缺知识图谱深层血缘；
11. 缺拆解结果进入 Novel OS 主链的验收标准；
12. 缺对应 UI、API、测试和长链验证。

---

## 3. 设计目标

### 3.1 产品目标

将 MKAOS 从：

```text
知识卡管理模块
```

升级为：

```text
本地 Novel OS 的多学科知识资产操作系统与创作资产加工厂
```

### 3.2 工程目标

新增一套可扩展的 ingestion / extraction / conversion pipeline，使系统能够：

1. 批量导入大型文本仓库；
2. 自动识别文本类型和结构；
3. 按 source type 调用专用拆解器；
4. 将原始文本安全地沉淀到 evidence layer；
5. 将文本抽象成 CreativeKnowledgeCard；
6. 将 CreativeKnowledgeCard 转成 Novel OS 可用创作资产；
7. 对拆解质量、原创边界、引用泄露、百科化风险进行 gate；
8. 将合格资产注入 Knowledge Pack；
9. 被题材、世界观、人物、大纲、细纲、正文、审稿、复盘、反馈稳定调用；
10. 在 reader feedback / review issue / publish gate 中持续调权。

### 3.3 非目标

本阶段不做：

1. SaaS 多租户；
2. 团队权限系统；
3. 复杂 RBAC；
4. 商业计费；
5. 外部平台真实发布 API；
6. 在线大规模分布式爬虫；
7. 侵权文本的下游生成直用。

本系统仍定位为本地自用 Novel Operating System。

---

## 4. MKAOS 当前最关键的 12 个缺口

| 编号 | 缺口 | 当前问题 | 设计目标 | 优先级 |
|---|---|---|---|---|
| 1 | Repository Importer | 只能导入单文本，不能导入 GitHub/本地仓库结构 | 支持本地目录、GitHub URL、压缩包、文件集合 | P0 |
| 2 | Book Manifest Builder | 不能识别书籍、篇章、文件 hash、导入状态 | 生成 repository/book/chapter/file manifest | P0 |
| 3 | Format Adapter | txt 之外格式弱 | 支持 txt/md/html/json/csv/epub/pdf/docx/source-target-bitext | P0 |
| 4 | Bilingual Pair Parser | 不能保存古文-现代文句对 | 新增 ParallelTextPair 资产 | P0 |
| 5 | Source Rights Registry | 来源和授权风险粒度不足 | 每个 source/book/chapter/pair 记录 rights 与 risk | P0 |
| 6 | Batch Chunking Pipeline | 大规模导入缺断点续跑和失败重试 | Job 化、manifest 化、可恢复、可重跑 | P0 |
| 7 | Source Type Cleaner | 通用 clean_source_text 不足以处理古籍/网文/专业书 | 按类型清洗、分章、去注释、去噪、规范化 | P0 |
| 8 | Knowledge Extraction Job | 缺大批量抽卡作业 | 支持按 book/chapter/source_type 批量抽 CreativeKnowledgeCard | P0 |
| 9 | Creative Asset Converter | 知识卡未稳定转创作资产 | 转题材、世界观、人物、冲突、钩子、审稿规则、模板 | P0 |
| 10 | Quote Leakage Detector | 只靠 source isolation 不足 | 检测 prompt / prose / package 中的原文、近似复用 | P0 |
| 11 | MKAOS Import UI | `/mkaos` 仍偏控制台 | 新增 import、books、jobs、review、graph、quality 页面 | P1 |
| 12 | Import Evaluation Report | 不能判断拆解质量是否可用于 Novel OS | 输出 coverage、abstraction、creative usability、risk、gate report | P0 |

---

## 5. 扩展项目总览

新增项目名建议：

```text
MKAOS Creative Ingestion & Extraction Pipeline
```

可简称：

```text
MKAOS CIEP
```

核心能力：

1. Ingestion Center：大型文本资产导入中心；
2. Source Type Registry：文本类型注册中心；
3. Format Adapter：文件格式适配器；
4. Classical-Modern Adapter：古文-现代文平行语料适配器；
5. Source Cleaner：类型化清洗器；
6. Creative Extractor：创作机制抽取器；
7. CreativeKnowledgeCard：升级版知识卡；
8. Asset Converter：创作资产转换器；
9. Extraction Report：拆解质量报告；
10. Quality Gate：拆解验收门禁；
11. Leakage Gate：引用泄露检测；
12. MKAOS Knowledge Graph 深化；
13. UI 管理台；
14. API；
15. 单元测试、集成测试、压力测试。

---

## 6. 新增资产模型

### 6.1 SourceRepository

用途：记录一个外部或本地文本仓库。

核心字段：

```json
{
  "asset_type": "source_repository",
  "repository_id": "repo_xxx",
  "name": "Classical-Modern",
  "source_uri": "https://github.com/NiuTrans/Classical-Modern",
  "local_path": "data/imports/Classical-Modern",
  "source_kind": "github_repo|local_folder|zip|manual_collection",
  "detected_corpus_type": "classical_modern_parallel_corpus",
  "rights": {
    "authorization": "unknown|public_dataset|licensed|user_owned",
    "copyright_boundary": "evidence_only",
    "allow_downstream_generation": false
  },
  "manifest_path": "...",
  "import_status": "pending|scanned|imported|failed",
  "content_hash": "...",
  "stats": {
    "book_count": 327,
    "chapter_count": 0,
    "file_count": 0,
    "parallel_pair_count": 0
  }
}
```

### 6.2 RepositoryManifest

用途：保存仓库扫描结果。

```json
{
  "asset_type": "repository_manifest",
  "repository_id": "repo_xxx",
  "root_path": "...",
  "files": [
    {
      "path": "古文原文/论语/学而篇/text.txt",
      "file_type": "classical_text",
      "book_name": "论语",
      "chapter_path": ["学而篇"],
      "sha256": "...",
      "size_bytes": 1234,
      "import_status": "pending|imported|skipped|failed"
    }
  ],
  "detected_structure": {
    "has_classical_original": true,
    "has_bilingual_data": true,
    "has_bitext": true
  }
}
```

### 6.3 BookSource

用途：记录一本书。

```json
{
  "asset_type": "book_source",
  "book_id": "book_xxx",
  "repository_id": "repo_xxx",
  "book_name": "论语",
  "source_type": "classical_text|webnovel|professional_book|mystery|platform_rule",
  "discipline_tags": ["儒家", "伦理", "政治秩序"],
  "chapter_count": 20,
  "has_parallel_text": true,
  "rights": {},
  "risk_level": "low|medium|high"
}
```

### 6.4 BookChapterSource

用途：记录一章/一篇/一节。

```json
{
  "asset_type": "book_chapter_source",
  "chapter_id": "chapter_xxx",
  "book_id": "book_xxx",
  "title": "学而篇",
  "chapter_path": ["学而篇"],
  "source_file": "古文原文/论语/学而篇/text.txt",
  "text_length": 0,
  "source_chunk_ids": [],
  "parallel_pair_ids": [],
  "extraction_status": "pending|extracted|failed"
}
```

### 6.5 ParallelTextPair

用途：保存古文-现代文句对、原文-译文句对、外语-中文句对。

```json
{
  "asset_type": "parallel_text_pair",
  "pair_id": "pair_xxx",
  "book_id": "book_xxx",
  "chapter_id": "chapter_xxx",
  "source_text": "子曰：学而时习之，不亦说乎？",
  "target_text": "孔子说：学了知识然后按一定的时间复习它，不也是很愉快吗？",
  "source_language": "classical_chinese",
  "target_language": "modern_chinese",
  "pair_index": 1,
  "source_file": "双语数据/论语/学而篇/bitext.txt",
  "raw_text_allowed_for_prose": false,
  "evidence_layer_only": true,
  "content_hash": "..."
}
```

### 6.6 CreativeKnowledgeCard

用途：升级现有 KnowledgeCard，使知识卡直接服务 Novel OS。

建议在现有 KnowledgeCard content 中扩展字段，不一定立即新增独立 schema。

```json
{
  "asset_type": "knowledge_card",
  "knowledge_subtype": "creative_knowledge_card",
  "concept_name": "孝悌作为秩序绑定机制",
  "source_type": "classical_text",
  "discipline": "儒家伦理 / 宗族秩序 / 社会制度",
  "knowledge_type": "world_rule|conflict_pattern|character_archetype|plot_motif|scene_material|review_rule|template",
  "abstraction_level": "mechanism",
  "core_explanation": "孝悌不是单纯道德评价，而是将家庭秩序、社会秩序与政治秩序连接起来的价值系统。",
  "creative_principle": "当人物个人欲望与家族伦理冲突时，孝悌可成为压迫机制或自我约束来源。",
  "narrative_function": "制造个人目标 vs 家族义务的冲突。",
  "conflict_function": "让主角的选择改变家族资源、声望、婚约、继承权。",
  "character_function": "适合克制型主角、伪善长辈、家族牺牲品、破局型谋士。",
  "worldbuilding_function": "适合宗族社会、门阀秩序、礼法压迫型世界。",
  "prose_function": "用于场景压力和对白潜台词，不直接解释概念。",
  "review_function": "检查伦理知识是否推动人物行动和利益变化。",
  "positive_usage": ["用礼法内部矛盾反制掌权者"],
  "negative_usage": ["长篇解释孝悌概念", "直接复用古文原句"],
  "anti_patterns": ["百科化", "说教化", "原文堆砌"],
  "applicable_flows": ["worldbuilding", "character_design", "outline", "chapter_outline", "review"],
  "applicable_genres": ["历史权谋", "东方玄幻", "家族宅斗", "古代悬疑"],
  "applicable_platforms": ["qidian", "fanqie", "jinjiang"],
  "originality_boundary": "不得复用原文长句，只使用抽象后的秩序机制。",
  "source_evidence_refs": [],
  "quality_dimensions": {
    "abstraction_score": 0.9,
    "creative_usability_score": 0.85,
    "flow_binding_score": 0.8,
    "anti_exposition_score": 0.8,
    "originality_safety_score": 0.9
  }
}
```

### 6.7 Creative Asset Cards

建议新增或复用现有资产类型扩展以下内容：

1. `genre_seed_card`：题材种子；
2. `world_rule_card`：世界观规则；
3. `character_archetype_card`：人物原型；
4. `conflict_pattern_card`：冲突模式；
5. `scene_material_card`：场景素材；
6. `plot_template_card`：情节模板；
7. `chapter_hook_card`：章节钩子；
8. `review_rule_card`：审稿规则；
9. `style_rule_card`：风格规则；
10. `originality_boundary_card`：原创边界。

---

## 7. 新增模块设计

### 7.1 mkaos_ingestion

路径建议：

```text
src/novel_forge/modules/mkaos_ingestion/
  __init__.py
  service.py
  repository_importer.py
  manifest_builder.py
  file_type_detector.py
  format_adapters.py
  classical_modern_adapter.py
  bilingual_pair_parser.py
  source_rights.py
  batch_chunker.py
  import_quality_report.py
```

职责：

1. 接收导入请求；
2. 扫描本地目录 / GitHub URL / 压缩包；
3. 生成 repository manifest；
4. 检测 corpus type；
5. 创建 SourceRepository / BookSource / BookChapterSource / ParallelTextPair；
6. 复用 MKAOS SourceDocument / SourceChunk；
7. 记录 ingestion job；
8. 输出 import report。

### 7.2 mkaos_extractors

路径建议：

```text
src/novel_forge/modules/mkaos_extractors/
  __init__.py
  service.py
  source_type_registry.py
  base.py
  classical_text_extractor.py
  webnovel_extractor.py
  professional_book_extractor.py
  mystery_extractor.py
  historical_source_extractor.py
  philosophy_extractor.py
  psychology_extractor.py
  platform_rule_extractor.py
```

职责：

按 source type 抽取 CreativeKnowledgeCard。

| Extractor | 输出重点 |
|---|---|
| classical_text_extractor | 制度、礼法、人物原型、志怪母题、古典意象、古代场景 |
| webnovel_extractor | 爽点、钩子、节奏、付费点、人设机制、平台节奏 |
| professional_book_extractor | 概念、理论、方法、案例、审稿规则、实践模板 |
| mystery_extractor | 线索、误导、动机、证据链、反转、读者认知控制 |
| historical_source_extractor | 官制、战争、阶层、资源分配、势力结构 |
| philosophy_extractor | 价值冲突、主题命题、人物信念、终局表达 |
| psychology_extractor | 欲望、人格、行为动机、关系模式 |
| platform_rule_extractor | 审核规则、发布门槛、章节要求、收益和违规边界 |

### 7.3 mkaos_converters

路径建议：

```text
src/novel_forge/modules/mkaos_converters/
  __init__.py
  service.py
  knowledge_to_genre.py
  knowledge_to_world_rule.py
  knowledge_to_character.py
  knowledge_to_conflict.py
  knowledge_to_scene.py
  knowledge_to_plot_template.py
  knowledge_to_chapter_hook.py
  knowledge_to_review_rule.py
  knowledge_to_style_rule.py
```

职责：

将 CreativeKnowledgeCard 转换为 Novel OS 可直接使用的创作资产。

转换链路：

```text
CreativeKnowledgeCard
  -> GenreSeedCard
  -> WorldRuleCard
  -> CharacterArchetypeCard
  -> ConflictPatternCard
  -> SceneMaterialCard
  -> PlotTemplateCard
  -> ChapterHookCard
  -> ReviewRuleCard
  -> TemplateCard / RuleCard
```

### 7.4 mkaos_quality

路径建议：

```text
src/novel_forge/modules/mkaos_quality/
  __init__.py
  service.py
  extraction_report.py
  creative_usability_gate.py
  anti_exposition_gate.py
  quote_leakage_detector.py
  near_duplicate_detector.py
  flow_binding_gate.py
  source_risk_gate.py
```

职责：

1. 评估拆解质量；
2. 检查百科化；
3. 检查原文泄露；
4. 检查 flow binding；
5. 检查 creative usability；
6. 低质量资产不允许进入 production KnowledgePack。

---

## 8. 新增 API 设计

### 8.1 Ingestion API

```text
POST /product/mkaos/ingestion/repositories
GET  /product/mkaos/ingestion/repositories
GET  /product/mkaos/ingestion/repositories/{repository_id}
POST /product/mkaos/ingestion/repositories/{repository_id}/scan
POST /product/mkaos/ingestion/repositories/{repository_id}/import
GET  /product/mkaos/ingestion/jobs
GET  /product/mkaos/ingestion/jobs/{job_id}
POST /product/mkaos/ingestion/jobs/{job_id}/resume
POST /product/mkaos/ingestion/jobs/{job_id}/cancel
GET  /product/mkaos/ingestion/reports/{report_id}
```

### 8.2 Book / Chapter API

```text
GET /product/mkaos/books
GET /product/mkaos/books/{book_id}
GET /product/mkaos/books/{book_id}/chapters
GET /product/mkaos/chapters/{chapter_id}
GET /product/mkaos/parallel-pairs
```

### 8.3 Extraction API

```text
POST /product/mkaos/extraction/jobs
GET  /product/mkaos/extraction/jobs
GET  /product/mkaos/extraction/jobs/{job_id}
POST /product/mkaos/extraction/jobs/{job_id}/resume
POST /product/mkaos/extraction/jobs/{job_id}/cancel
GET  /product/mkaos/extraction/reports/{report_id}
```

### 8.4 Converter API

```text
POST /product/mkaos/convert/creative-assets
POST /product/mkaos/convert/world-rules
POST /product/mkaos/convert/characters
POST /product/mkaos/convert/conflicts
POST /product/mkaos/convert/chapter-hooks
POST /product/mkaos/convert/review-rules
```

### 8.5 Quality / Gate API

```text
POST /product/mkaos/quality/evaluate-extraction
POST /product/mkaos/quality/check-leakage
POST /product/mkaos/quality/check-anti-exposition
POST /product/mkaos/quality/check-flow-binding
POST /product/mkaos/quality/gate-knowledge-pack
GET  /product/mkaos/quality/reports
```

---

## 9. UI 设计

在 Web Admin 中新增 MKAOS 子页面：

```text
/mkaos/import
/mkaos/repositories
/mkaos/books
/mkaos/extraction-jobs
/mkaos/creative-assets
/mkaos/quality
/mkaos/knowledge-graph
```

### 9.1 /mkaos/import

功能：

1. 输入 GitHub URL / 本地路径 / ZIP 路径；
2. 选择 source type；
3. 自动检测 corpus type；
4. 设置 rights；
5. 设置 allow_downstream_generation，默认 false；
6. 设置 extraction profile；
7. 启动扫描；
8. 展示 manifest 预览。

### 9.2 /mkaos/books

功能：

1. 查看导入书籍列表；
2. 按 source type / discipline / risk / extraction status 筛选；
3. 查看章节；
4. 查看句对；
5. 查看 evidence chunk；
6. 启动单书/单章抽取。

### 9.3 /mkaos/extraction-jobs

功能：

1. 查看任务进度；
2. 断点续跑；
3. 失败重试；
4. 查看错误；
5. 查看生成的 CreativeKnowledgeCard；
6. 查看质量报告。

### 9.4 /mkaos/creative-assets

功能：

1. 查看从 KnowledgeCard 转换出的创作资产；
2. 按题材、世界观、人物、冲突、钩子、审稿规则筛选；
3. 手工批准进入 KnowledgePack；
4. 手工标记 deprecated / do_not_select / active。

### 9.5 /mkaos/quality

功能：

1. 抽象评分；
2. 创作可用性评分；
3. flow binding 覆盖率；
4. 原创边界评分；
5. quote leakage 风险；
6. anti exposition 风险；
7. 进入 production pack 的 gate 结果。

---

## 10. 关键流程

### 10.1 Classical-Modern 导入流程

```text
用户输入 Classical-Modern 本地路径或 GitHub URL
  -> create SourceRepository
  -> scan repository
  -> detect classical_modern_parallel_corpus
  -> build RepositoryManifest
  -> detect 古文原文 / 双语数据
  -> create BookSource
  -> create BookChapterSource
  -> parse text.txt as SourceDocument / SourceChunk
  -> parse source.txt / target.txt / bitext.txt as ParallelTextPair
  -> generate ImportQualityReport
```

### 10.2 古籍知识抽取流程

```text
BookChapterSource / ParallelTextPair
  -> classical_text_extractor
  -> CreativeKnowledgeCard
      - world_rule
      - conflict_pattern
      - character_archetype
      - plot_motif
      - scene_material
      - review_rule
  -> extraction quality report
  -> gate
  -> approved cards enter knowledge pool
```

### 10.3 创作资产转换流程

```text
CreativeKnowledgeCard
  -> mkaos_converters
  -> WorldRuleCard / CharacterArchetypeCard / ConflictPatternCard / ChapterHookCard / ReviewRuleCard
  -> bind applicable flows
  -> build KnowledgePack
  -> Context Builder injects pack
  -> Novel OS production chain uses it
```

### 10.4 正文安全流程

```text
KnowledgePack for prose
  -> remove source raw text
  -> remove parallel pair raw text
  -> keep creative principle / constraints / review rules
  -> generate prose
  -> quote leakage detector
  -> anti exposition gate
  -> ReviewIssue if failed
```

---

## 11. 质量门禁

### 11.1 CreativeKnowledgeCard Gate

阻断条件：

```text
block if:
- creative_usability_score < 0.70
- abstraction_score < 0.70
- applicable_flows is empty
- originality_boundary is empty
- negative_usage is empty
- source risk high and prose usage allowed
- no review_function for review-capable cards
- no conflict_function for outline/chapter_outline cards
```

### 11.2 KnowledgePack Gate

进入 production KnowledgePack 前必须检查：

1. 是否包含 raw source text；
2. 是否包含 source chunk raw text；
3. 是否包含 parallel pair source_text / target_text；
4. 是否有 high risk source 被 prose 使用；
5. 是否有 do_not_select/deprecated/quarantined 卡片；
6. 是否有 creative_usability_score 低于阈值；
7. 是否有 flow mismatch；
8. 是否有 Canon conflict；
9. 是否缺 review rules；
10. 是否缺 originality boundary。

### 11.3 Anti-Exposition Gate

对 outline、chapter_outline、prose、review 进行检查：

1. 知识是否只停留在摘要；
2. 是否有连续说明性段落；
3. 是否没有改变人物行动；
4. 是否没有制造利益冲突；
5. 是否没有转化为场景、道具、动作、对白或选择成本。

### 11.4 Quote Leakage Gate

检测对象：

1. prompt preview；
2. context bundle；
3. generated outline；
4. generated chapter outline；
5. generated prose；
6. publish package；
7. recap report。

检查内容：

1. 连续原文复用；
2. 近似译文复用；
3. 古文句式连续堆砌；
4. source chunk raw_text 泄露；
5. parallel pair source/target 泄露；
6. 高风险来源下游使用。

---

## 12. 测试方案

### 12.1 单元测试

新增测试文件：

```text
tests/unit/test_mkaos_ingestion.py
tests/unit/test_mkaos_classical_modern_adapter.py
tests/unit/test_mkaos_parallel_pair_parser.py
tests/unit/test_mkaos_creative_knowledge_card.py
tests/unit/test_mkaos_creative_converters.py
tests/unit/test_mkaos_extraction_quality.py
tests/unit/test_mkaos_quote_leakage_detector.py
tests/unit/test_mkaos_anti_exposition_gate.py
tests/unit/test_mkaos_source_type_extractors.py
```

必须覆盖：

1. 本地目录扫描；
2. Classical-Modern 目录识别；
3. text.txt 解析；
4. bitext.txt 解析；
5. source/target 对齐；
6. manifest 生成；
7. 导入去重；
8. 断点续跑；
9. CreativeKnowledgeCard schema；
10. converter 输出；
11. quality gate 阻断；
12. source leakage 检测。

### 12.2 集成测试

新增：

```text
tests/integration/test_mkaos_classical_modern_ingestion_flow.py
tests/integration/test_mkaos_creative_extraction_to_context_builder.py
tests/integration/test_mkaos_ingestion_knowledge_pack_gate.py
```

测试链路：

```text
fixture Classical-Modern mini repo
  -> import repository
  -> build manifest
  -> parse book/chapter/pair
  -> extract CreativeKnowledgeCard
  -> convert creative assets
  -> build KnowledgePack
  -> Context Builder inject
  -> prose prompt preview must not contain raw source
  -> generated asset must pass anti-exposition / leakage gate
```

### 12.3 慢测试

新增 opt-in：

```text
tests/slow/test_mkaos_large_repository_ingestion.py
tests/slow/test_mkaos_50_book_extraction_pressure.py
```

不要默认跑全量 Classical-Modern，默认使用 mini fixture。全量导入应 opt-in。

---

## 13. 实施阶段

### Phase 1：MKAOS Ingestion Center P0

目标：大型文本仓库可以被安全导入。

交付：

1. `mkaos_ingestion` 模块；
2. SourceRepository；
3. RepositoryManifest；
4. BookSource；
5. BookChapterSource；
6. ParallelTextPair；
7. Classical-Modern mini fixture；
8. ingestion API；
9. ingestion tests。

### Phase 2：CreativeKnowledgeCard P0

目标：知识卡升级为 Novel OS 可用创作知识卡。

交付：

1. KnowledgeCard 扩展字段；
2. schema validation；
3. creative quality dimensions；
4. source type registry；
5. classical_text_extractor v1；
6. professional_book_extractor v1；
7. webnovel_extractor v1；
8. mystery_extractor v1。

### Phase 3：Creative Asset Converter P0

目标：知识卡转生产资产。

交付：

1. world rule converter；
2. character archetype converter；
3. conflict pattern converter；
4. chapter hook converter；
5. review rule converter；
6. template converter；
7. converter API；
8. converter tests。

### Phase 4：Quality Gate P0

目标：低质量拆解不能进入 production pack。

交付：

1. extraction report；
2. creative usability gate；
3. anti exposition gate；
4. quote leakage detector；
5. flow binding gate；
6. KnowledgePack gate；
7. ReviewIssue integration。

### Phase 5：UI P1

目标：用户可以在本地管理导入、拆解、审核、批准。

交付：

1. `/mkaos/import`；
2. `/mkaos/repositories`；
3. `/mkaos/books`；
4. `/mkaos/extraction-jobs`；
5. `/mkaos/creative-assets`；
6. `/mkaos/quality`。

### Phase 6：Knowledge Graph Deepening P1

目标：形成 source -> knowledge -> creative asset -> generated asset -> feedback 的血缘。

交付：

1. graph relation 扩展；
2. derived_from / abstracted_to / converted_to / used_in / improved_by / hurt_by；
3. graph path API；
4. UI lineage view；
5. feedback weight update integration。

---

## 14. 验收标准

### 14.1 P0 验收

必须满足：

1. 可以导入 Classical-Modern mini fixture；
2. 可以识别 `古文原文`、`双语数据`、`text.txt`、`source.txt`、`target.txt`、`bitext.txt`；
3. 可以生成 SourceRepository / RepositoryManifest / BookSource / BookChapterSource / ParallelTextPair；
4. 可以从 mini fixture 抽取 CreativeKnowledgeCard；
5. 可以将 CreativeKnowledgeCard 转成 WorldRule / CharacterArchetype / ConflictPattern / ChapterHook / ReviewRule；
6. 可以构建 KnowledgePack；
7. Prose prompt preview 不包含 raw source text；
8. Quote leakage detector 可以识别原文复用；
9. Anti-exposition gate 可以识别百科化输出；
10. 低质量知识卡不能进入 production pack；
11. 全量单元测试通过；
12. 现有 MKAOS、Context Builder、Loop、Longform Recap、Publish/Feedback 测试不能回退。

### 14.2 P1 验收

必须满足：

1. UI 可导入仓库；
2. UI 可查看 books/chapters/pairs；
3. UI 可查看 extraction jobs；
4. UI 可批准/禁用 CreativeKnowledgeCard；
5. UI 可查看 quality report；
6. Knowledge Graph 可查看 source -> creative asset -> flow 使用链路；
7. feedback 可以影响 knowledge weight。

---

## 15. 最终判断

本需求不是把 MKAOS 做成更大的 RAG，而是把 MKAOS 升级成：

```text
大型文本资产导入系统
+ 多类型文本拆解系统
+ 创作机制抽象系统
+ 小说生产资产转换系统
+ 质量门禁系统
+ 知识图谱与反馈调权系统
```

完成后，MKAOS 才能真正满足本地 Novel Operating System 对以下链路的要求：

1. 热门小说拆解；
2. 悬疑推理阅读；
3. 题材库；
4. 世界观；
5. 人物设定；
6. 大纲；
7. 细纲；
8. 正文；
9. 审稿；
10. 读者反馈；
11. 作文训练；
12. 图像 / 建筑提示词；
13. AI 创作工作流。

