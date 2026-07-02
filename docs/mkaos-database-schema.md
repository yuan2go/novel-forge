# MKAOS 数据库 Schema 设计文档

## 1. 目标

本文档定义多学科知识资产操作系统 MKAOS 的 P0/P1 数据模型。

设计目标：

1. 支持专业书籍、网文拆解、名著拆解、平台规则、读者反馈等来源入库；
2. 支持 source chunk 到 knowledge card 的可追溯链路；
3. 支持知识资产化：素材卡、冲突卡、人物卡、世界观卡、规则卡、模板卡；
4. 支持同一知识在多个流程中的用途绑定；
5. 支持 Knowledge Pack 构造；
6. 支持 Agent 调用留痕；
7. 支持审稿、反馈、权重演化和回归测试。

---

## 2. 存储分层

```text
Postgres
├── 来源层：source_documents, source_chunks
├── 知识层：knowledge_cards, knowledge_relations
├── 资产层：material_cards, conflict_cards, worldbuilding_cards, character_asset_cards, rule_cards, template_cards
├── 用途层：knowledge_usage_bindings
├── 运行层：knowledge_packs, knowledge_pack_items, knowledge_usage_events
├── 反馈层：knowledge_feedback_events, knowledge_quality_scores
└── 测试层：knowledge_regression_cases, knowledge_regression_runs

Qdrant
├── source_chunks_vector
├── knowledge_cards_vector
├── asset_cards_vector
└── rule_cards_vector

MinIO
├── original_sources/
├── cleaned_sources/
├── extraction_artifacts/
└── regression_outputs/
```

---

## 3. Enum 设计

### 3.1 source_type

```text
professional_book
webnovel_analysis
classic_novel_analysis
paper
forum_material
reader_feedback
platform_rule
manual_note
review_history
```

### 3.2 knowledge_type

```text
concept
mechanism
principle
case
counterexample
rule
pattern
risk
negative_rule
```

### 3.3 knowledge_status

```text
raw_candidate
extracted
normalized
asset_converted
flow_bound
runtime_used
validated
high_value
deprecated
```

### 3.4 flow

```text
material
analysis
genre
worldbuilding
character
outline
chapter_outline
prose
review
feedback
training
template
```

### 3.5 usage_granularity

```text
L1_discipline_principle
L2_mechanism_model
L3_creation_rule
L4_plot_material
L5_scene_detail
L6_sentence_expression
L7_review_check
```

### 3.6 rule_type

```text
generation_constraint
review_rule
canon_rule
platform_rule
style_rule
anti_encyclopedia_rule
logic_rule
safety_rule
```

### 3.7 severity

```text
info
low
medium
high
critical
```

---

## 4. 来源层 Schema

### 4.1 source_documents

保存原始来源元信息。

```sql
CREATE TABLE source_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    author TEXT,
    publisher TEXT,
    edition TEXT,
    source_type TEXT NOT NULL,
    discipline TEXT,
    language TEXT DEFAULT 'zh',
    copyright_status TEXT,
    source_uri TEXT,
    minio_object_key TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    import_status TEXT DEFAULT 'pending',
    import_time TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_source_documents_type ON source_documents(source_type);
CREATE INDEX idx_source_documents_discipline ON source_documents(discipline);
CREATE INDEX idx_source_documents_metadata ON source_documents USING GIN(metadata);
```

### 4.2 source_chunks

保存清洗后的原文切片。该表是证据层，不直接给正文 Agent 使用。

```sql
CREATE TABLE source_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    chapter_title TEXT,
    section_title TEXT,
    page_start INT,
    page_end INT,
    raw_text TEXT NOT NULL,
    cleaned_text TEXT NOT NULL,
    token_count INT,
    content_hash TEXT NOT NULL,
    quality_flags JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_source_chunks_source ON source_chunks(source_id);
CREATE INDEX idx_source_chunks_hash ON source_chunks(content_hash);
CREATE INDEX idx_source_chunks_cleaned_text_tsv ON source_chunks USING GIN(to_tsvector('simple', cleaned_text));
```

---

## 5. 知识层 Schema

### 5.1 knowledge_cards

MKAOS 的核心知识资产。

```sql
CREATE TABLE knowledge_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_name TEXT NOT NULL,
    concept_aliases TEXT[] DEFAULT '{}',
    discipline TEXT NOT NULL,
    sub_discipline TEXT,
    knowledge_type TEXT NOT NULL,
    core_explanation TEXT NOT NULL,
    source_chunk_ids UUID[] DEFAULT '{}',
    confidence NUMERIC(5,2) DEFAULT 0,
    source_reliability NUMERIC(5,2) DEFAULT 0,
    applicable_genres TEXT[] DEFAULT '{}',
    applicable_platforms TEXT[] DEFAULT '{}',
    risk_level TEXT DEFAULT 'medium',
    risk_notes TEXT,
    status TEXT DEFAULT 'extracted',
    quality_score NUMERIC(5,2) DEFAULT 0,
    weight NUMERIC(8,4) DEFAULT 1.0,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_knowledge_cards_concept ON knowledge_cards(concept_name);
CREATE INDEX idx_knowledge_cards_discipline ON knowledge_cards(discipline);
CREATE INDEX idx_knowledge_cards_type ON knowledge_cards(knowledge_type);
CREATE INDEX idx_knowledge_cards_status ON knowledge_cards(status);
CREATE INDEX idx_knowledge_cards_genres ON knowledge_cards USING GIN(applicable_genres);
CREATE INDEX idx_knowledge_cards_platforms ON knowledge_cards USING GIN(applicable_platforms);
CREATE INDEX idx_knowledge_cards_metadata ON knowledge_cards USING GIN(metadata);
```

### 5.2 knowledge_relations

知识图谱关系表。

```sql
CREATE TABLE knowledge_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_knowledge_id UUID NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    target_knowledge_id UUID NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    relation_strength NUMERIC(5,2) DEFAULT 1.0,
    evidence TEXT,
    source_chunk_ids UUID[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(source_knowledge_id, target_knowledge_id, relation_type)
);

CREATE INDEX idx_knowledge_relations_source ON knowledge_relations(source_knowledge_id);
CREATE INDEX idx_knowledge_relations_target ON knowledge_relations(target_knowledge_id);
CREATE INDEX idx_knowledge_relations_type ON knowledge_relations(relation_type);
```

relation_type 建议值：

```text
is_a
part_of
causes
conflicts_with
supports
similar_to
derived_from
used_for
appears_in
contradicts
requires
limits
```

---

## 6. 资产层 Schema

### 6.1 material_cards

```sql
CREATE TABLE material_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    material_name TEXT NOT NULL,
    material_type TEXT NOT NULL,
    description TEXT NOT NULL,
    usable_scenes TEXT[] DEFAULT '{}',
    conflict_potential NUMERIC(5,2) DEFAULT 0,
    character_potential NUMERIC(5,2) DEFAULT 0,
    genre_fit TEXT[] DEFAULT '{}',
    platform_fit TEXT[] DEFAULT '{}',
    risk_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_material_cards_knowledge ON material_cards(knowledge_id);
CREATE INDEX idx_material_cards_type ON material_cards(material_type);
CREATE INDEX idx_material_cards_genre ON material_cards USING GIN(genre_fit);
```

### 6.2 conflict_cards

```sql
CREATE TABLE conflict_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    conflict_name TEXT NOT NULL,
    beneficiary TEXT,
    victim TEXT,
    maintainer TEXT,
    challenger TEXT,
    protagonist_entry TEXT,
    conflict_escalation TEXT,
    suitable_genres TEXT[] DEFAULT '{}',
    risk_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_conflict_cards_knowledge ON conflict_cards(knowledge_id);
CREATE INDEX idx_conflict_cards_genres ON conflict_cards USING GIN(suitable_genres);
```

### 6.3 worldbuilding_cards

```sql
CREATE TABLE worldbuilding_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    rule_name TEXT NOT NULL,
    scope TEXT,
    resource_logic TEXT,
    power_structure TEXT,
    limitations TEXT,
    cost TEXT,
    conflict_source TEXT,
    canon_candidate BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_worldbuilding_cards_knowledge ON worldbuilding_cards(knowledge_id);
CREATE INDEX idx_worldbuilding_cards_canon_candidate ON worldbuilding_cards(canon_candidate);
```

### 6.4 character_asset_cards

```sql
CREATE TABLE character_asset_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    character_mechanism TEXT NOT NULL,
    desire TEXT,
    fear TEXT,
    trauma TEXT,
    behavior_pattern TEXT,
    relationship_pattern TEXT,
    breakdown_risk TEXT,
    growth_direction TEXT,
    suitable_roles TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_character_asset_cards_knowledge ON character_asset_cards(knowledge_id);
CREATE INDEX idx_character_asset_cards_roles ON character_asset_cards USING GIN(suitable_roles);
```

### 6.5 rule_cards

```sql
CREATE TABLE rule_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID REFERENCES knowledge_cards(id) ON DELETE SET NULL,
    rule_name TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    trigger_condition TEXT NOT NULL,
    check_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    severity TEXT DEFAULT 'medium',
    blocking BOOLEAN DEFAULT false,
    fix_suggestion TEXT,
    applicable_flows TEXT[] DEFAULT '{}',
    applicable_genres TEXT[] DEFAULT '{}',
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_rule_cards_knowledge ON rule_cards(knowledge_id);
CREATE INDEX idx_rule_cards_type ON rule_cards(rule_type);
CREATE INDEX idx_rule_cards_enabled ON rule_cards(enabled);
CREATE INDEX idx_rule_cards_flows ON rule_cards USING GIN(applicable_flows);
```

### 6.6 template_cards

```sql
CREATE TABLE template_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID REFERENCES knowledge_cards(id) ON DELETE SET NULL,
    template_name TEXT NOT NULL,
    template_type TEXT NOT NULL,
    input_fields JSONB DEFAULT '[]'::jsonb,
    output_structure JSONB NOT NULL DEFAULT '{}'::jsonb,
    applicable_genres TEXT[] DEFAULT '{}',
    applicable_platforms TEXT[] DEFAULT '{}',
    example TEXT,
    risk_notes TEXT,
    success_score NUMERIC(5,2) DEFAULT 0,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_template_cards_knowledge ON template_cards(knowledge_id);
CREATE INDEX idx_template_cards_type ON template_cards(template_type);
CREATE INDEX idx_template_cards_genres ON template_cards USING GIN(applicable_genres);
```

---

## 7. 用途绑定 Schema

### 7.1 knowledge_usage_bindings

一条知识可绑定多个流程。

```sql
CREATE TABLE knowledge_usage_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    flow TEXT NOT NULL,
    usage_type TEXT NOT NULL,
    usage_granularity TEXT NOT NULL,
    input_role TEXT,
    output_form TEXT NOT NULL,
    prompt_fragment TEXT,
    constraint_text TEXT,
    review_rule_id UUID REFERENCES rule_cards(id) ON DELETE SET NULL,
    template_id UUID REFERENCES template_cards(id) ON DELETE SET NULL,
    priority INT DEFAULT 100,
    risk_level TEXT DEFAULT 'medium',
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(knowledge_id, flow, usage_type, output_form)
);

CREATE INDEX idx_usage_bindings_knowledge ON knowledge_usage_bindings(knowledge_id);
CREATE INDEX idx_usage_bindings_flow ON knowledge_usage_bindings(flow);
CREATE INDEX idx_usage_bindings_priority ON knowledge_usage_bindings(priority);
CREATE INDEX idx_usage_bindings_enabled ON knowledge_usage_bindings(enabled);
```

示例：

| knowledge | flow | usage_type | output_form |
|---|---|---|---|
| 土地兼并 | worldbuilding | 制度设定 | worldbuilding_constraint |
| 土地兼并 | outline | 主线冲突 | outline_constraint |
| 土地兼并 | chapter_outline | 章节事件 | beat_design |
| 土地兼并 | prose | 场景细节 | prose_detail |
| 土地兼并 | review | 制度合理性检查 | review_rule |

---

## 8. Knowledge Pack Schema

### 8.1 knowledge_packs

```sql
CREATE TABLE knowledge_packs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id TEXT,
    project_id UUID,
    flow TEXT NOT NULL,
    genre TEXT,
    platform TEXT,
    chapter_id UUID,
    current_goal TEXT NOT NULL,
    canon_context JSONB DEFAULT '{}'::jsonb,
    generation_constraints JSONB DEFAULT '[]'::jsonb,
    review_rules JSONB DEFAULT '[]'::jsonb,
    style_constraints JSONB DEFAULT '[]'::jsonb,
    knowledge_budget JSONB DEFAULT '{}'::jsonb,
    risk_warnings JSONB DEFAULT '[]'::jsonb,
    output_contract JSONB DEFAULT '{}'::jsonb,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_knowledge_packs_project ON knowledge_packs(project_id);
CREATE INDEX idx_knowledge_packs_flow ON knowledge_packs(flow);
CREATE INDEX idx_knowledge_packs_chapter ON knowledge_packs(chapter_id);
```

### 8.2 knowledge_pack_items

```sql
CREATE TABLE knowledge_pack_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_pack_id UUID NOT NULL REFERENCES knowledge_packs(id) ON DELETE CASCADE,
    knowledge_id UUID REFERENCES knowledge_cards(id) ON DELETE SET NULL,
    asset_type TEXT,
    asset_id UUID,
    item_role TEXT NOT NULL,
    flow TEXT NOT NULL,
    usage_instruction TEXT,
    forbidden_reason TEXT,
    priority INT DEFAULT 100,
    source_refs JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_pack_items_pack ON knowledge_pack_items(knowledge_pack_id);
CREATE INDEX idx_pack_items_knowledge ON knowledge_pack_items(knowledge_id);
CREATE INDEX idx_pack_items_role ON knowledge_pack_items(item_role);
```

item_role：

```text
required
optional
forbidden
constraint
review_rule
canon_context
style_constraint
risk_warning
```

---

## 9. 运行与反馈 Schema

### 9.1 knowledge_usage_events

```sql
CREATE TABLE knowledge_usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID REFERENCES knowledge_cards(id) ON DELETE SET NULL,
    knowledge_pack_id UUID REFERENCES knowledge_packs(id) ON DELETE SET NULL,
    project_id UUID,
    flow TEXT NOT NULL,
    target_artifact_id UUID,
    chapter_id UUID,
    agent_name TEXT NOT NULL,
    used_as TEXT,
    prompt_context TEXT,
    output_span TEXT,
    review_result JSONB DEFAULT '{}'::jsonb,
    reader_feedback JSONB DEFAULT '{}'::jsonb,
    effect_score NUMERIC(5,2),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_usage_events_knowledge ON knowledge_usage_events(knowledge_id);
CREATE INDEX idx_usage_events_project ON knowledge_usage_events(project_id);
CREATE INDEX idx_usage_events_flow ON knowledge_usage_events(flow);
CREATE INDEX idx_usage_events_chapter ON knowledge_usage_events(chapter_id);
```

### 9.2 knowledge_feedback_events

```sql
CREATE TABLE knowledge_feedback_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID REFERENCES knowledge_cards(id) ON DELETE SET NULL,
    project_id UUID,
    source_type TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    feedback_text TEXT,
    normalized_signal JSONB DEFAULT '{}'::jsonb,
    suggested_action TEXT,
    confidence NUMERIC(5,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_feedback_events_knowledge ON knowledge_feedback_events(knowledge_id);
CREATE INDEX idx_feedback_events_project ON knowledge_feedback_events(project_id);
CREATE INDEX idx_feedback_events_type ON knowledge_feedback_events(feedback_type);
```

### 9.3 knowledge_quality_scores

```sql
CREATE TABLE knowledge_quality_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id UUID NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    accuracy_score NUMERIC(5,2) DEFAULT 0,
    story_convertibility_score NUMERIC(5,2) DEFAULT 0,
    flow_callability_score NUMERIC(5,2) DEFAULT 0,
    reviewability_score NUMERIC(5,2) DEFAULT 0,
    templateability_score NUMERIC(5,2) DEFAULT 0,
    risk_score NUMERIC(5,2) DEFAULT 0,
    usage_effect_score NUMERIC(5,2) DEFAULT 0,
    final_score NUMERIC(5,2) DEFAULT 0,
    calculated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_quality_scores_knowledge ON knowledge_quality_scores(knowledge_id);
CREATE INDEX idx_quality_scores_final ON knowledge_quality_scores(final_score);
```

---

## 10. 回归测试 Schema

### 10.1 knowledge_regression_cases

```sql
CREATE TABLE knowledge_regression_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_name TEXT NOT NULL,
    case_type TEXT NOT NULL,
    flow TEXT NOT NULL,
    genre TEXT,
    platform TEXT,
    input_payload JSONB NOT NULL,
    expected_checks JSONB NOT NULL,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_regression_cases_type ON knowledge_regression_cases(case_type);
CREATE INDEX idx_regression_cases_flow ON knowledge_regression_cases(flow);
```

### 10.2 knowledge_regression_runs

```sql
CREATE TABLE knowledge_regression_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES knowledge_regression_cases(id) ON DELETE CASCADE,
    run_status TEXT NOT NULL,
    output_payload JSONB DEFAULT '{}'::jsonb,
    passed BOOLEAN DEFAULT false,
    failed_checks JSONB DEFAULT '[]'::jsonb,
    metrics JSONB DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX idx_regression_runs_case ON knowledge_regression_runs(case_id);
CREATE INDEX idx_regression_runs_passed ON knowledge_regression_runs(passed);
```

---

## 11. Qdrant Collection 设计

### 11.1 source_chunks_vector

payload：

```json
{
  "source_id": "uuid",
  "chunk_id": "uuid",
  "source_type": "professional_book",
  "discipline": "历史学",
  "chapter_title": "...",
  "copyright_status": "..."
}
```

用途：证据追溯、清洗复核，不直接给正文生成。

### 11.2 knowledge_cards_vector

payload：

```json
{
  "knowledge_id": "uuid",
  "concept_name": "土地兼并",
  "discipline": "历史学",
  "knowledge_type": "mechanism",
  "status": "flow_bound",
  "applicable_genres": ["历史", "权谋", "玄幻王朝"],
  "quality_score": 88.5
}
```

### 11.3 asset_cards_vector

payload：

```json
{
  "asset_id": "uuid",
  "asset_type": "conflict_card",
  "knowledge_id": "uuid",
  "genre_fit": ["历史", "权谋"],
  "conflict_potential": 92
}
```

### 11.4 rule_cards_vector

payload：

```json
{
  "rule_id": "uuid",
  "rule_type": "review_rule",
  "applicable_flows": ["outline", "prose", "review"],
  "severity": "high",
  "blocking": true
}
```

---

## 12. 数据一致性规则

1. `knowledge_cards.source_chunk_ids` 必须至少包含一个来源，人工创建知识除外；
2. `knowledge_cards.status = flow_bound` 时，必须存在至少一条 `knowledge_usage_bindings`；
3. `status = high_value` 时，必须存在 usage event 或人工验证记录；
4. 正文流程 Knowledge Pack 不得包含 `source_chunk` 作为直接 required item；
5. `forbidden` item 必须包含 `forbidden_reason`；
6. 审稿规则如果 `blocking = true`，必须有 `fix_suggestion`；
7. 任何 Canon 更新必须经过 Canon Checker，不由 MKAOS 直接写入项目 Canon。

---

## 13. P0 最小表清单

P0 必须实现：

```text
source_documents
source_chunks
knowledge_cards
knowledge_usage_bindings
rule_cards
template_cards
knowledge_packs
knowledge_pack_items
knowledge_usage_events
knowledge_quality_scores
```

P1 再实现：

```text
material_cards
conflict_cards
worldbuilding_cards
character_asset_cards
knowledge_relations
knowledge_feedback_events
knowledge_regression_cases
knowledge_regression_runs
```

---

## 14. 验收标准

1. 导入一本专业书后，可以保存 source document 和 source chunks；
2. 至少能抽取知识卡，并追溯到 source chunks；
3. 每条有效知识至少能绑定一个流程；
4. 能构造 outline、chapter_outline、prose、review 四类 Knowledge Pack；
5. 正文 Knowledge Pack 不允许直接暴露原始 source chunk；
6. 使用知识生成产物后，必须写入 usage event；
7. 审稿规则可以通过 rule_cards 注入；
8. 质量评分可以根据审稿和反馈更新；
9. 所有关键查询均有索引；
10. 所有写入接口必须可审计。
