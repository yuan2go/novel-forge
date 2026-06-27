# Novel Forge V6.1：名著 / 出版小说解析系统增补设计文档

> 版本：2026-06-26  
> 用途：交给 Codex / Claude Code，在现有 Novel Forge V5/V6 设计基础上继续实现“名著 / 出版小说解析”能力。  
> 核心原则：网文解析、出版小说解析、经典名著解析都属于“小说拆解”，但不得混成一个处理器。  
> 工程目标：把“分析拆解中心”从单一网文拆解升级为“三类解析器 + 通用底座 + 统一资产转换器”。

---

## 0. 当前基线

当前 Novel Forge V5 已经具备：

- 项目空间和生命周期管理。
- 多文件上传、导入、清洗、拆书、知识卡和素材卡生产。
- Claude Code / Codex handoff 人工执行包。
- 稿件阅读、编辑、保存、版本、diff、导出和发布记录。
- 审稿、问题状态、修订计划、修订执行和评分对比。
- 任务中心、失败恢复、dead-letter、worker 健康检查。
- RAG 上下文构建。
- Qdrant、MinIO、PostgreSQL、本地生产环境。
- Next.js Web 管理台和 Studio 页面。

现有资产系统已经有 `source_document`、`cleaned_text`、`decomposition_report`、`knowledge_card`、`material_card`、`draft_chapter`、`review_report`、`revision_plan` 等 schema-backed JSON asset。

本次增补不推翻现有系统，而是在现有能力上增加：

```text
分析拆解中心
  -> 通用小说解析底座
  -> 网文商业结构拆解
  -> 出版小说技法拆解
  -> 经典名著深度拆解
  -> 统一资产转换器
  -> 创作资产库 / 审稿规则库 / 文风库 / 模板库
```

---

## 1. 为什么必须拆成多个解析器

### 1.1 不能只做一个“小说解析器”

网文、出版小说、经典名著的拆解目标不同：

| 类型 | 核心目标 | 生产价值 | 主要风险 |
|---|---|---|---|
| 网文商业结构拆解 | 平台适配、爽点、追读、付费、长篇连载 | 保证读者继续看、愿意追更、适配平台 | 过度套路化、低质、AI 味、同质化 |
| 出版小说技法拆解 | 叙事技巧、人物复杂性、语言质感、心理描写 | 提升正文质感、人物可信度、情绪深度 | 过度文学化，拖慢节奏 |
| 经典名著深度拆解 | 主题、命运结构、社会关系、象征系统、哲学深度 | 提升作品厚度、主题辨识度、长期耐读性 | 抽象过高，难以直接服务连载生产 |

如果统一处理，会导致：

1. 用网文标准误判名著“节奏慢、爽点不足”。
2. 用名著标准误判网文“语言浅、商业化强”。
3. 输出字段混乱，资产无法复用。
4. 审稿标准混乱。
5. 生成器调用时出现风格冲突。

### 1.2 最终定位

```text
网文解析 = 生产发动机
出版小说解析 = 技法质量增强器
经典名著解析 = 主题和深度增强器
```

系统目标不是仿写名著，也不是照搬网文套路，而是：

```text
用网文结构保证读者愿意看；
用出版小说能力提升人物、语言和场景质感；
用经典名著能力提升主题、命运感和社会关系复杂度；
用审核系统控制原创性、节奏、质量和平台适配。
```

---

## 2. 新的信息架构调整

### 2.1 左侧菜单调整

原新 UI 中“分析拆解”应从单一“网文拆解”升级为：

```text
分析拆解
- 分析拆解中心
- 网文商业结构拆解
- 出版小说技法拆解
- 经典名著深度拆解
- 拆解资产转换器
- 拆解结果库
```

### 2.2 页面职责

| 页面 | 主要职责 |
|---|---|
| 分析拆解中心 | 选择资料、选择解析模式、查看解析任务、查看资产转化结果 |
| 网文商业结构拆解 | 平台、题材、开篇三章、爽点循环、章节钩子、付费节点、长篇稳定性 |
| 出版小说技法拆解 | 主题表达、人物弧光、叙事视角、语言风格、心理描写、场景氛围 |
| 经典名著深度拆解 | 命运结构、社会关系、时代背景、象征意象、哲学主题、文学质感 |
| 拆解资产转换器 | 把不同拆解结果转成题材、人物、世界观、文风、冲突、审稿规则、模板 |
| 拆解结果库 | 所有拆解资产的检索、筛选、引用图谱、使用记录 |

---

## 3. 新的模块结构

### 3.1 后端模块建议

新增目录：

```text
src/novel_forge/modules/analysis/
  __init__.py
  common.py
  web_commercial.py
  published_fiction.py
  classic_literary.py
  asset_converter.py
  prompts.py
  rubrics.py
  validators.py
```

职责：

| 文件 | 职责 |
|---|---|
| `common.py` | 通用文本清洗后的章节、人物、事件、时间线、冲突、风格特征提取 |
| `web_commercial.py` | 网文商业结构解析，复用或包裹现有 `decompose` 能力 |
| `published_fiction.py` | 出版小说技法解析 |
| `classic_literary.py` | 经典名著深度解析 |
| `asset_converter.py` | 将解析报告转换为可复用创作资产 |
| `prompts.py` | 分模式 prompt 构建 |
| `rubrics.py` | 分模式验收评分标准 |
| `validators.py` | 输出结构和合规边界校验 |

### 3.2 API router 建议

如果正在执行 V6 的 Product API 拆分，新增：

```text
src/novel_forge/api/routes/analysis.py
```

新增 API：

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/product/analysis/modes` | 返回支持的解析模式 |
| `POST` | `/product/analysis/common/extract` | 通用小说底座解析 |
| `POST` | `/product/analysis/web-commercial/run` | 运行网文商业结构拆解 |
| `POST` | `/product/analysis/published-fiction/run` | 运行出版小说技法拆解 |
| `POST` | `/product/analysis/classic-literary/run` | 运行经典名著深度拆解 |
| `POST` | `/product/analysis/convert-assets` | 将拆解报告转成可复用资产 |
| `POST` | `/product/analysis/handoff/create` | 创建 Claude Code / Codex 解析 handoff |
| `POST` | `/product/analysis/handoff/bind` | 绑定解析输出 |
| `GET` | `/product/analysis/reports` | 查询拆解报告列表 |
| `GET` | `/product/analysis/reports/{asset_id}` | 查看拆解报告详情 |

---

## 4. 解析器设计

## 4.1 通用小说解析底座

### 目标

所有小说类文本先经过通用底座，避免每个解析器重复实现基础工作。

### 输入

- `source_document`
- `cleaned_text`
- `project_id`
- `analysis_mode`
- `rights.authorization`
- `copyright_boundary`

### 输出资产

新增：`common_novel_analysis_report`

目录：

```text
data/analysis/common/
```

核心字段：

```json
{
  "type": "common_novel_analysis_report",
  "content": {
    "source_asset_id": "...",
    "analysis_mode": "web_commercial | published_fiction | classic_literary",
    "chapter_map": [],
    "character_mentions": [],
    "event_timeline": [],
    "conflict_units": [],
    "relationship_graph_summary": [],
    "setting_units": [],
    "style_signals": {
      "sentence_length": "",
      "dialogue_density": "",
      "description_density": "",
      "narrative_distance": "",
      "emotion_density": ""
    },
    "copyright_safety_notes": []
  }
}
```

### 不做什么

- 不输出可直接复刻的剧情桥段。
- 不提取大段原文。
- 不输出可直接套用的专有设定、人物名、组织名、台词。

---

## 4.2 网文商业结构拆解器

### 保持现有资产兼容

现有 `decomposition_report` 已用于网文结构、商业模式、冲突、节奏拆解。本次不强制改名，避免破坏已有流程。

建议在 `decomposition_report.content` 中新增或标准化字段：

```json
{
  "analysis_mode": "web_commercial",
  "platform_profile": {
    "platform": "qidian | fanqie | qimao | jjwxc | faloo | ciweimao | zongheng | other",
    "channel": "male | female | general",
    "ranking_context": "",
    "target_reader_expectation": [],
    "recommendation_fit_notes": []
  },
  "opening_three_chapters": {
    "chapter_1": {
      "protagonist_identity": "",
      "initial_pressure": "",
      "golden_finger_signal": "",
      "first_hook": ""
    },
    "chapter_2": {
      "pleasure_validation": "",
      "conflict_escalation": "",
      "reader_expectation": ""
    },
    "chapter_3": {
      "main_goal": "",
      "upgrade_path": "",
      "long_read_reason": ""
    }
  },
  "pleasure_cycle_models": [],
  "chapter_hook_models": [],
  "paid_conversion_structure": {
    "free_chapter_function": [],
    "pre_vip_build_up": [],
    "vip_conversion_hook": [],
    "post_vip_cycle": []
  },
  "long_form_support": {
    "map_expansion": "",
    "power_growth": "",
    "antagonist_system": "",
    "million_word_risk": []
  }
}
```

### 主要服务对象

- 题材选择。
- 大纲生成。
- 细纲生成。
- 章节生产。
- 平台适配审稿。
- 付费节点设计。
- 长篇稳定性设计。

---

## 4.3 出版小说技法拆解器

### 目标

出版小说解析不服务付费卡点，而服务：

1. 主题表达。
2. 人物复杂性。
3. 叙事视角。
4. 语言风格。
5. 心理描写。
6. 场景氛围。
7. 复杂关系。
8. 结构完整性。

### 输出资产

新增：`published_fiction_analysis_report`

目录：

```text
data/analysis/published_fiction/
```

核心字段：

```json
{
  "type": "published_fiction_analysis_report",
  "content": {
    "source_asset_id": "...",
    "work_profile": {
      "title": "",
      "genre": "",
      "publication_form": "published_fiction",
      "era_background": "",
      "narrative_form": ""
    },
    "theme_structure": {
      "core_theme": "",
      "theme_axes": ["人与命运", "人与社会", "人与欲望", "人与道德", "人与权力", "人与历史", "人与自我"],
      "theme_progression": [],
      "theme_expression_methods": []
    },
    "character_arcs": [
      {
        "role_label": "",
        "initial_state": "",
        "external_pressure": "",
        "internal_conflict": "",
        "irreversible_choices": [],
        "ending_transformation": "",
        "reusable_arc_template": ""
      }
    ],
    "narrative_perspective": {
      "person": "first | third_limited | third_omniscient | multi_pov | other",
      "reliability": "reliable | unreliable | mixed | unknown",
      "narrative_distance": "near | medium | far | variable",
      "information_control": [],
      "narrative_voice_features": []
    },
    "language_style": {
      "sentence_patterns": [],
      "rhetorical_devices": [],
      "imagery_system": [],
      "dialogue_style": "",
      "psychological_description_method": "",
      "scene_atmosphere_method": "",
      "metaphor_and_symbol_usage": []
    },
    "complex_conflict_models": [],
    "reusable_outputs": {
      "theme_expression_templates": [],
      "character_arc_templates": [],
      "relationship_templates": [],
      "psychological_description_templates": [],
      "scene_atmosphere_templates": [],
      "narrative_perspective_templates": [],
      "language_style_templates": [],
      "publication_quality_rules": []
    },
    "migration_safety": {
      "safe_to_reuse": [],
      "requires_abstraction": [],
      "not_safe_to_reuse": [],
      "copyright_notes": []
    }
  }
}
```

### 生产价值

出版小说技法拆解结果主要供：

- 文风库。
- 人物库。
- 心理描写素材库。
- 场景氛围模板库。
- 复杂冲突库。
- 出版级质感审稿规则。
- 重要章节润色。
- 高光场景重写。

---

## 4.4 经典名著深度拆解器

### 目标

经典名著深度拆解不以“写得像名著”为目标，而是提炼更底层的创作机制：

1. 命运结构。
2. 社会关系结构。
3. 阶层和制度压力。
4. 象征系统。
5. 哲学主题。
6. 人性冲突。
7. 历史和时代张力。
8. 文学质感。

### 输出资产

新增：`classic_literary_analysis_report`

目录：

```text
data/analysis/classic_literary/
```

核心字段：

```json
{
  "type": "classic_literary_analysis_report",
  "content": {
    "source_asset_id": "...",
    "work_profile": {
      "title": "",
      "literary_period": "",
      "cultural_context": "",
      "historical_background": "",
      "public_domain_or_rights_status": ""
    },
    "fate_structure": {
      "initial_condition": "",
      "social_forces": [],
      "family_or_group_forces": [],
      "desire_structure": [],
      "moral_pressure": [],
      "irreversible_turning_points": [],
      "final_fate_logic": ""
    },
    "social_relationship_structure": {
      "class_relations": [],
      "family_relations": [],
      "power_relations": [],
      "gender_or_identity_relations": [],
      "community_pressure": []
    },
    "symbolic_imagery_system": [
      {
        "image_label": "",
        "semantic_function": "",
        "emotional_function": "",
        "theme_function": "",
        "safe_abstraction": ""
      }
    ],
    "philosophical_themes": [
      {
        "theme": "",
        "question": "",
        "conflict_expression": "",
        "modern_genre_migration": ""
      }
    ],
    "human_complexity_models": [],
    "literary_texture_methods": {
      "narrative_rhythm": "",
      "emotional_resonance": "",
      "aftertaste_design": "",
      "ambiguity_design": ""
    },
    "reusable_outputs": {
      "fate_model_templates": [],
      "social_relation_templates": [],
      "symbolic_imagery_cards": [],
      "philosophical_theme_templates": [],
      "human_complexity_templates": [],
      "literary_texture_review_rules": []
    },
    "migration_safety": {
      "safe_to_reuse": [],
      "requires_abstraction": [],
      "not_safe_to_reuse": [],
      "copyright_notes": []
    }
  }
}
```

### 生产价值

经典名著拆解结果主要用于：

- 主题库。
- 世界观底层精神。
- 人物命运模型。
- 社会关系结构。
- 象征意象库。
- 哲学主题模板。
- 精品小说深度增强。
- 出版级质感审稿。

---

## 5. 新增可复用资产类型

### 5.1 总表

| 新资产类型 | 目录 | 来源 | 用途 |
|---|---|---|---|
| `common_novel_analysis_report` | `data/analysis/common` | 通用底座 | 章节、人物、事件、时间线、冲突基础解析 |
| `published_fiction_analysis_report` | `data/analysis/published_fiction` | 出版小说解析器 | 技法、人物、语言、叙事、心理、场景 |
| `classic_literary_analysis_report` | `data/analysis/classic_literary` | 名著解析器 | 主题、命运、社会关系、象征、哲学深度 |
| `theme_expression_template` | `data/templates/themes` | 出版/名著 | 主题表达模板 |
| `character_arc_template` | `data/templates/characters` | 出版/名著 | 人物成长、堕落、毁灭、觉醒模板 |
| `complex_relationship_template` | `data/templates/relationships` | 出版/名著 | 复杂人物关系模板 |
| `psychological_description_template` | `data/templates/psychology` | 出版小说 | 心理描写模板 |
| `scene_atmosphere_template` | `data/templates/scenes` | 出版小说 | 场景氛围模板 |
| `narrative_perspective_template` | `data/templates/narrative` | 出版小说 | 叙事视角模板 |
| `symbolic_imagery_card` | `data/materials/imagery` | 名著 | 象征意象素材 |
| `literary_style_profile` | `data/styles/literary` | 出版/名著 | 文学化风格参数，不绑定具体作者 |
| `publication_quality_rule` | `data/review_rules/publication` | 出版/名著 | 出版级质感审稿规则 |
| `analysis_conversion_report` | `data/analysis/conversions` | 资产转换器 | 记录从拆解报告转成哪些资产 |

### 5.2 与现有资产的关系

| 现有资产 | 是否复用 | 调整方式 |
|---|---|---|
| `source_document` | 复用 | 增加 `source_kind: web_novel | published_fiction | classic_literary | academic | other` |
| `cleaned_text` | 复用 | 增加 `text_form` 和 `chapter_detection_confidence` |
| `decomposition_report` | 复用 | 继续作为网文商业结构拆解主资产 |
| `knowledge_card` | 复用 | 可接收名著/出版小说中抽象出的理论、主题、技法知识 |
| `material_card` | 复用 | 可接收心理、场景、关系、象征素材 |
| `style_profile` | 如果 V6 已实现则复用 | 新增 `literary_style_profile` 可作为风格子类或独立资产 |
| `review_report` | 复用 | 审稿器增加 `review_mode`，区分网文、出版、名著质感 |
| `training_exercise` | 复用 | 可由名著/出版小说解析生成作文/写作训练题 |

---

## 6. 统一资产转换器

### 6.1 目标

解析报告本身不直接喂给正文生成器，而是先转成可复用资产。

```text
published_fiction_analysis_report
classic_literary_analysis_report
web_commercial decomposition_report
  -> analysis_asset_converter
  -> theme / character / style / conflict / hook / review_rule / template assets
```

### 6.2 转换规则

| 来源 | 转换目标 |
|---|---|
| 网文商业拆解 | 题材爆款因子、平台适配规则、开篇三章模板、爽点循环模板、章节钩子模板、付费卡点模板、地图升级模型 |
| 出版小说技法拆解 | 主题表达模板、人物弧光模板、心理描写模板、场景氛围模板、叙事视角模板、语言风格模板、复杂关系模板 |
| 经典名著深度拆解 | 命运结构模板、社会关系模板、象征意象卡、哲学主题模板、人性复杂度模板、文学质感审稿规则 |

### 6.3 新增资产转换报告

`analysis_conversion_report` 字段：

```json
{
  "type": "analysis_conversion_report",
  "content": {
    "source_report_id": "...",
    "source_report_type": "published_fiction_analysis_report | classic_literary_analysis_report | decomposition_report",
    "conversion_mode": "auto | handoff | manual",
    "created_assets": [
      {
        "asset_id": "...",
        "asset_type": "theme_expression_template",
        "title": "",
        "reuse_scope": "project | global | genre | platform",
        "copyright_risk": "low | medium | high",
        "requires_human_review": true
      }
    ],
    "rejected_items": [
      {
        "reason": "too_specific | copyright_risk | low_quality | duplicate",
        "summary": ""
      }
    ],
    "safety_notes": []
  }
}
```

---

## 7. Handoff 扩展

### 7.1 新增 handoff 类型

现有 handoff 支持网文拆解和多学科知识解析。新增：

| Handoff 类型 | skill | 期望输出 |
|---|---|---|
| 出版小说技法拆解 | `published-fiction-technique-deconstruction` | `published_fiction_analysis_report` |
| 经典名著深度拆解 | `classic-literary-depth-deconstruction` | `classic_literary_analysis_report` |
| 拆解资产转换 | `analysis-asset-converter` | `analysis_conversion_report` + created assets |

### 7.2 新增 skills 文件

```text
skills/
  published-fiction-technique-deconstruction.md
  classic-literary-depth-deconstruction.md
  analysis-asset-converter.md
```

### 7.3 Handoff 验收项

#### 出版小说技法拆解验收

- 是否区分主题、人物、叙事、语言、心理、场景。
- 是否输出人物弧光阶段。
- 是否输出叙事视角和信息控制方式。
- 是否输出语言风格参数，而不是模仿具体作者。
- 是否输出可复用技法模板。
- 是否标记不可迁移或高版权风险内容。
- 是否没有复制原文长段落。

#### 经典名著深度拆解验收

- 是否提取命运结构。
- 是否提取社会关系和时代压力。
- 是否提取象征意象系统。
- 是否提取哲学主题。
- 是否输出可现代题材迁移的抽象模型。
- 是否明确不安全迁移内容。
- 是否不直接复刻人物、桥段、专有设定。

#### 资产转换验收

- 是否只转换抽象机制，不转换具体桥段。
- 是否为每个资产标记 `reuse_scope`。
- 是否为每个资产标记 `copyright_risk`。
- 是否创建 lineage。
- 是否通过 schema 校验。
- 是否能被 RAG 按项目/题材/用途检索。

---

## 8. 生成器调用策略

### 8.1 新增 `asset_mix_policy`

项目配置新增：

```json
{
  "asset_mix_policy": {
    "web_commercial_weight": 0.55,
    "published_fiction_weight": 0.30,
    "classic_literary_weight": 0.15,
    "usage_by_stage": {
      "topic": ["web_commercial", "classic_literary"],
      "world": ["classic_literary", "published_fiction"],
      "character": ["published_fiction", "classic_literary"],
      "outline": ["web_commercial", "classic_literary"],
      "chapter_plan": ["web_commercial"],
      "draft": ["web_commercial", "published_fiction"],
      "important_scene_revision": ["published_fiction", "classic_literary"],
      "review": ["web_commercial", "published_fiction", "classic_literary"]
    }
  }
}
```

### 8.2 默认策略

| 生产阶段 | 优先资产 |
|---|---|
| 题材选择 | 网文商业结构 + 平台适配 |
| 世界观 | 经典名著主题 + 出版小说结构技法 |
| 人物设定 | 出版小说人物弧光 + 经典名著命运结构 |
| 大纲 | 网文长篇架构 + 经典主题线 |
| 细纲 | 网文爽点循环 + 章节钩子 |
| 正文 | 网文节奏 + 出版小说语言和心理描写 |
| 重点场景润色 | 出版小说场景氛围 + 名著象征意象 |
| 审稿 | 网文平台标准 + 出版质感标准 + 名著深度标准 |

### 8.3 禁止策略

- 不允许“按某本名著写一章”。
- 不允许“复制某本出版小说的人物关系”。
- 不允许“套用某作品的核心设定和专有名词”。
- 不允许把经典名著资产直接当作网文爽点模板。
- 不允许把网文爽点规则用于评价经典名著解析质量。

---

## 9. 审稿系统扩展

### 9.1 新增审稿模式

`review_report.content.review_mode` 增加：

```text
web_platform_review
publication_quality_review
classic_depth_review
hybrid_boutique_review
```

### 9.2 审稿重点

| 审稿模式 | 检查重点 |
|---|---|
| `web_platform_review` | 开篇、冲突、爽点、节奏、钩子、付费节点、平台适配、AI 味、水文 |
| `publication_quality_review` | 主题、人物复杂性、语言质感、心理真实、场景氛围、叙事视角、结构完整 |
| `classic_depth_review` | 命运感、社会关系、象征系统、哲学主题、人性复杂度、结尾余韵 |
| `hybrid_boutique_review` | 商业节奏和文学质感是否平衡，是否既能追读又有辨识度 |

### 9.3 新增精品融合评分

新增 `boutique_balance_score`：

```json
{
  "boutique_balance_score": {
    "platform_readability": 0,
    "chapter_hook_strength": 0,
    "pleasure_density": 0,
    "character_depth": 0,
    "language_texture": 0,
    "theme_depth": 0,
    "emotional_authenticity": 0,
    "originality_safety": 0,
    "overall": 0,
    "risk": "low | medium | high"
  }
}
```

---

## 10. RAG 检索策略扩展

### 10.1 新增 metadata

所有由解析器和资产转换器生成的资产应写入：

```json
{
  "metadata": {
    "analysis_origin": "web_commercial | published_fiction | classic_literary",
    "source_kind": "web_novel | published_fiction | classic_literary",
    "reuse_scope": "project | genre | platform | global",
    "generation_usage": ["topic", "world", "character", "outline", "chapter_plan", "draft", "review", "revision"],
    "copyright_risk": "low | medium | high",
    "abstraction_level": "high | medium | low",
    "style_transfer_risk": "low | medium | high"
  }
}
```

### 10.2 检索过滤

生成器调用 RAG 时必须支持：

- 按 `analysis_origin` 过滤。
- 按 `generation_usage` 过滤。
- 按 `copyright_risk` 过滤。
- 按 `abstraction_level` 过滤。
- 默认排除 `copyright_risk=high`。
- 默认排除 `abstraction_level=low` 的作品特异性资产。

---

## 11. Web UI 设计要求

### 11.1 分析拆解中心首页

页面区域：

1. 解析模式卡片：
   - 网文商业结构拆解。
   - 出版小说技法拆解。
   - 经典名著深度拆解。
   - 多学科知识解析。
2. 资料选择区：
   - 上传资料。
   - 已清洗文本。
   - GitHub / 本地资料。
   - 授权状态。
3. 解析任务区：
   - 自动解析。
   - Claude Code / Codex handoff。
   - 等待验收。
   - 失败重试。
4. 拆解资产转化区：
   - 转成文风资产。
   - 转成主题模板。
   - 转成人物弧光模板。
   - 转成审稿规则。
5. 风险提示区：
   - 版权风险。
   - 风格迁移风险。
   - 过度文学化风险。
   - 过度套路化风险。

### 11.2 出版小说技法拆解页面

Tab：

- 概览。
- 主题结构。
- 人物弧光。
- 叙事视角。
- 语言风格。
- 心理描写。
- 场景氛围。
- 可复用模板。
- 风险边界。

### 11.3 经典名著深度拆解页面

Tab：

- 概览。
- 命运结构。
- 社会关系。
- 时代背景。
- 象征意象。
- 哲学主题。
- 人性复杂度。
- 现代题材迁移。
- 风险边界。

### 11.4 拆解资产转换器页面

功能：

- 选择拆解报告。
- 选择转换目标。
- 预览将创建的资产。
- 标记复用范围。
- 标记版权风险。
- 人工确认。
- 写入资产库。
- 查看 lineage。

---

## 12. CLI 扩展

新增命令：

```bash
novel-forge analyze-common
novel-forge analyze-published-fiction
novel-forge analyze-classic-literary
novel-forge convert-analysis-assets
novel-forge claude-published-fiction
novel-forge claude-classic-literary
novel-forge review-publication-quality
novel-forge review-classic-depth
novel-forge review-boutique-balance
```

命令示例：

```bash
novel-forge analyze-published-fiction \
  --project-id my-project \
  --cleaned-text data/cleaned/example.json \
  --output data/analysis/published_fiction/example.analysis.json
```

```bash
novel-forge convert-analysis-assets \
  --project-id my-project \
  --source-report data/analysis/classic_literary/example.analysis.json \
  --targets theme_expression_template,character_arc_template,symbolic_imagery_card \
  --max-copyright-risk low
```

---

## 13. 测试要求

### 13.1 Schema 测试

新增：

```text
tests/unit/schemas/test_common_novel_analysis_report.py
tests/unit/schemas/test_published_fiction_analysis_report.py
tests/unit/schemas/test_classic_literary_analysis_report.py
tests/unit/schemas/test_analysis_conversion_report.py
```

测试点：

- 必填字段。
- project scope。
- references。
- metadata。
- copyright risk。
- migration safety。
- 空数组默认值。
- 非法 `analysis_mode` 拒绝。

### 13.2 服务测试

```text
tests/unit/modules/analysis/test_common.py
tests/unit/modules/analysis/test_published_fiction.py
tests/unit/modules/analysis/test_classic_literary.py
tests/unit/modules/analysis/test_asset_converter.py
```

测试点：

- mock provider 输出能被解析。
- invalid JSON fail closed。
- 版权风险字段缺失时拒绝入库。
- 高风险资产默认不进入生成可用资产。
- conversion report 正确记录 created/rejected items。

### 13.3 API 测试

```text
tests/integration/api/test_analysis_routes.py
```

测试点：

- 模式列表。
- 运行出版小说解析。
- 运行名著解析。
- 创建 handoff。
- 绑定 handoff 输出。
- 转换资产。
- 查询报告。

### 13.4 UI 测试

如果项目已有前端测试框架，增加：

- 分析拆解中心渲染。
- 三类解析入口存在。
- 出版小说技法 tab 渲染。
- 经典名著 tab 渲染。
- 资产转换器预览和确认。

---

## 14. 实施顺序

### Phase A：Schema 和目录

1. 新增四类 report schema：
   - `common_novel_analysis_report`
   - `published_fiction_analysis_report`
   - `classic_literary_analysis_report`
   - `analysis_conversion_report`
2. 新增模板类资产 schema。
3. 更新 `AssetType` 枚举和目录映射。
4. 更新 validate。

验收：

```bash
make test
make validate
```

### Phase B：模块和服务

1. 新增 `modules/analysis/`。
2. 实现通用底座。
3. 实现出版小说技法解析服务。
4. 实现经典名著深度解析服务。
5. 实现资产转换服务。
6. 复用现有 provider、RAG、storage、task status。

### Phase C：Handoff 扩展

1. 新增三个 skill 文件。
2. Handoff operation 增加：
   - `published-fiction-technique-analysis`
   - `classic-literary-depth-analysis`
   - `analysis-asset-conversion`
3. 绑定输出时校验 expected output type。
4. 增加验收项。

### Phase D：API 和 CLI

1. 新增 `analysis.py` router。
2. 新增 CLI 命令。
3. 接入 Celery 长任务。
4. 接入 task center。

### Phase E：Web UI

1. 新增分析拆解中心。
2. 新增三类解析页面。
3. 新增拆解资产转换器。
4. 新增拆解结果库筛选。
5. 将新页面挂到新版左侧导航。

### Phase F：生成器和审稿器接入

1. 项目配置增加 `asset_mix_policy`。
2. RAG 检索增加 `analysis_origin` 过滤。
3. Draft 生成接入出版小说技法资产。
4. 世界观/人物/大纲接入经典名著资产。
5. Review 增加 `publication_quality_review`、`classic_depth_review`、`hybrid_boutique_review`。

---

## 15. Codex 执行提示词

```text
你是 novel-forge 项目的 Codex 工程实现助手。请在现有 Novel Forge V5/V6 代码基础上，按照《Novel Forge V6.1：名著 / 出版小说解析系统增补设计文档》实现分析拆解中心升级。

目标：把原有以网文拆解为主的分析系统，升级为“通用小说解析底座 + 网文商业结构拆解 + 出版小说技法拆解 + 经典名著深度拆解 + 统一资产转换器”。

硬约束：
1. 不破坏现有 decomposition_report 和网文拆解流程。
2. 不把名著、出版小说、网文混成一个处理器。
3. 不实现模仿具体作者文风。
4. 不复制原文、角色、桥段、专有设定、台词。
5. 所有新增输出必须是 schema-backed asset。
6. 所有新增资产必须带 project_id、workspace_path、references、metadata、copyright_risk、reuse_scope。
7. 高版权风险资产默认不得进入正文生成 RAG。
8. 先实现后端 schema/service/API/CLI，再实现 UI。
9. 每个阶段结束必须运行 make test && make validate。

实施顺序：
Phase A：新增 schema 和目录映射。
Phase B：新增 modules/analysis 服务。
Phase C：扩展 Claude Code / Codex handoff。
Phase D：新增 analysis API router 和 CLI 命令。
Phase E：实现 Web 分析拆解中心、出版小说技法拆解页、经典名著深度拆解页、资产转换器页。
Phase F：接入生成器、RAG 和审稿器。

请先审计当前代码，列出需要修改的文件、可复用模块、风险点和最小实现计划。然后从 Phase A 开始编码。每完成一个阶段，输出变更摘要、测试结果和下一阶段计划。
```

---

## 16. 最终验收标准

### 产品验收

- 用户可以在 Web 中选择“出版小说技法拆解”。
- 用户可以在 Web 中选择“经典名著深度拆解”。
- 用户可以通过 Handoff 让 Claude Code / Codex 完成两类解析。
- 用户可以把解析结果转成主题、人物、文风、心理、场景、象征、审稿规则等资产。
- 用户可以在生成器中控制网文、出版小说、名著资产的调用比例。
- 审稿中心可以分别检查网文平台标准、出版质感标准、经典深度标准、精品融合标准。

### 工程验收

- 新增 schema 全部有单元测试。
- API 有集成测试。
- CLI 可运行。
- Handoff output type 校验有效。
- RAG 支持 `analysis_origin` 过滤。
- 高风险版权资产不会默认进入正文生成。
- `make test` 通过。
- `make validate` 通过。

### 创作系统验收

系统最终形成：

```text
网文解析：解决平台、追读、爽点、付费、连载。
出版小说解析：解决文风、人物、心理、场景、结构技法。
经典名著解析：解决主题、命运、社会关系、象征、哲学深度。
统一资产转换器：把拆解结果转成可复用创作资产。
生成器调用层：根据项目目标和平台选择资产组合。
审核中心：控制商业节奏、文学质感、原创性和精品标准。
```

这能避免系统退化成低质仿写网文，也能避免变成纯文学分析工具，而是服务“精品小说生产系统”。
