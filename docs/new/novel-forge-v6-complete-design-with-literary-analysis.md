# Novel Forge V6 差距分析与后续功能设计文档

> 版本：2026-06-26  
> 用途：交给 Codex / Claude Code，基于当前 Novel Forge V5 代码继续实现后续功能。  
> 基线：`current-implementation.md` 描述的当前系统完成情况。  
> 目标：把当前“本地单人小说生产平台雏形”升级为“可按不同小说平台、题材节奏、文风体系、精品标准、审核准入长期生产的个人本地小说工厂系统”。

---

## 0. 执行摘要

当前 Novel Forge V5 已经具备完整的基础闭环：

```text
项目 -> 来源 -> 拆解 -> 知识/素材 -> RAG -> 草稿 -> 审稿 -> 修订 -> 导出 -> 任务恢复 -> 健康审计
```

这说明系统已经不是普通 CLI demo，而是有 Web 管理台、FastAPI、Celery、Postgres、Qdrant、MinIO、Handoff、审稿修订、任务中心和本地生产启动方案的平台雏形。

但距离最新设计仍有明显差距。差距不再是“有没有小说生产流程”，而是：

1. **平台适配不足**：当前项目配置只有目标平台字段，但没有平台画像、题材适配、节奏模板、收益/更新/审核约束、平台读者偏好。
2. **精品小说体系不足**：当前能生成大纲、细纲、正文、审稿，但没有“精品标准配置文件”，不能区分不同平台的精品标准、商业化指标、开篇标准、追读标准、长线稳定标准。
3. **文风系统缺失**：当前没有独立文风库、风格拆解器、风格混合器、风格重写器、风格审稿器，也没有版权/洗稿风险控制下的参数化文风机制。
4. **审核系统需要升级**：当前 review/revision 已成闭环，但还不是“作品信息审核 + 章节正文审核 + 发布前终审 + 平台准入检查 + AI 味检测 + 相似度/原创性控制”的完整审核中心。
5. **UI 与新信息架构不完全一致**：当前是 Studio + Projects/Health/Tasks/Assets/Handoffs/Batch/Drafts/Reviews；新 UI 要明确呈现为“个人本地小说工厂”，并按工作区、创作资产、分析拆解、生产流程、管理工具组织。
6. **长篇稳定性不足**：当前有 RAG、人物、世界观、前文摘要、伏笔检索，但没有百万字级设定锁定、伏笔线程、战力/等级体系、时间线、人物状态变更、章节连续性红线。
7. **读者反馈闭环不足**：已有 reader_feedback / feedback_insight schema 和导入分析命令，但还没有前台反馈中心、反馈聚类、追读风险、评论驱动修订建议和后续章节调整机制。
8. **数据统计不足**：有任务/系统健康数据，但缺小说生产指标：章节产能、审稿分、风格稳定度、平台适配度、追读风险、爽点密度、钩子强度、原创性风险趋势。
9. **Product API 过大**：当前 `src/novel_forge/api/product.py` 已承载过多能力，后续实现前必须拆模块，避免继续堆积。
10. **资产深度编辑器不足**：当前 typed panel 是第一版，各类资产缺平台化、精品化、文风化、审核化的深度领域表单。

---

## 1. 最新设计目标定义

### 1.1 产品定位

Novel Forge 不是普通 AI 写作 SaaS，也不是单次生成小说工具，而是：

```text
个人本地小说工厂系统
= 本地创作项目管理
+ 素材/知识/拆解资产沉淀
+ 平台题材适配
+ 精品小说标准配置
+ 文风参数化控制
+ 大纲/细纲/章节工业化生产
+ 审核准入和原创性控制
+ 长篇稳定性管理
+ 读者反馈闭环
+ 发布与复盘
```

### 1.2 明确非目标

后续实现不得引入以下方向：

- 不做登录、会员、支付、升级、邀请有礼。
- 不做多租户 SaaS 权限系统。
- 不把参考小说原文直接作为正文生成依赖。
- 不实现“模仿某某作者文风”的功能。
- 不鼓励照抄具体作品、角色名、组织名、能力名、地名、关键台词、独特设定、标志性桥段。
- 不把 GitHub/论坛/贴吧/论文资料无授权地直接转成商业正文素材。
- 不牺牲本地单人使用体验去做复杂云平台架构。

### 1.3 新系统目标链路

目标链路应升级为：

```text
平台选择
  -> 题材适配
  -> 精品标准设定
  -> 文风目标设定
  -> 合规来源入库
  -> 网文/经典/专业资料拆解
  -> 抽象结构与素材沉淀
  -> 世界观/人物/长线机制
  -> 大纲
  -> 细纲
  -> 章节生产
  -> 章节审核
  -> 文风审稿
  -> 原创性/相似度审核
  -> 作品信息审核
  -> 发布前终审
  -> 发布记录
  -> 读者反馈导入
  -> 反馈洞察
  -> 后续章节策略调整
```

---

## 2. 当前系统与最新设计差距总表

| 领域 | 当前状态 | 最新设计要求 | 差距等级 | 后续动作 |
|---|---|---|---|---|
| 项目管理 | 有项目生命周期、目标平台、质量阈值 | 项目创建时绑定平台画像、题材策略、精品标准、文风目标 | P0 | 扩展 project config 与项目初始化向导 |
| UI 架构 | Studio + 多专业页 | 左侧导航按本地小说工厂重新分组 | P0 | 重构 Web shell 与页面路由 |
| 题材选择 | 有 topic_seed、topic-development | 需要平台分类、榜单适配、题材热度、差异化定位 | P0 | 新增平台题材库与题材评分器 |
| 精品小说体系 | 无独立标准资产 | 需要按平台/题材/篇幅配置精品标准 | P0 | 新增 quality_standard_profile |
| 文风系统 | 基本缺失 | 文风库、拆解器、混合器、重写器、审稿器、风险控制 | P0 | 新增 style 系列 schema/service/UI |
| 审核系统 | 有 review/revision 闭环 | 作品信息审核、章节正文审核、发布前终审、平台规则、AI 味、原创性 | P0 | 升级 Reviews 为 Audit Center |
| 网文拆解 | 有 decomposition_report 和 handoff | 需要平台结构拆解、付费/免费节奏拆解、精品机制提取 | P1 | 扩展 decomposition schema 与 prompt |
| 经典/出版拆解 | 可通过 knowledge 解析，但未独立 | 与网文拆解分开，输出语言质感、主题、心理、氛围 | P1 | 新增 published/经典拆解模式 |
| 大纲 | 有 outline | 缺百万字级卷结构、主线/副线/升级节奏控制 | P1 | 扩展 outline schema |
| 细纲 | 有 chapter_plan | 缺连续章节节奏曲线、追读钩子、伏笔投放/回收 | P1 | 扩展 chapter_plan schema |
| 章节生产 | 有 draft_chapter | 缺平台节奏参数、文风配置、审核阈值前置 | P1 | draft service 接入 platform/style/quality context |
| 长篇稳定性 | RAG 已有基础 | 需要设定锁、伏笔线程、战力/等级、时间线、人物状态 | P1 | 新增 continuity 模块 |
| 读者反馈 | schema/CLI 基础已有 | 需要前台反馈中心、评论分类、后续策略调整 | P1 | 新增 Feedback Center UI/API |
| 原创性控制 | 来源合规已有 | 需要相似度报告、禁用具体元素、桥段顺序风险 | P0 | 新增 originality_report |
| 发布包装 | 有导出和 publish record | 需要书名/封面/简介/标签/平台上传前检查 | P1 | 新增 Work Packaging / Publish Center |
| 数据统计 | 系统健康和任务状态 | 需要创作质量/效率/风险/趋势统计 | P2 | 新增创作数据统计页 |
| Agent 评测 | Agent 边界已有 | 需要模型/Agent输出质量、失败率、成本、审稿一致性 | P2 | 新增 Evaluation Center |
| API 结构 | product.py 过大 | 模块化 Product API | P0 | 拆分 routers/services |
| 资产编辑 | typed panel 基础版 | 深度领域表单 | P1 | 分资产实现专业编辑器 |

---

## 3. 新信息架构与 UI 重构要求

### 3.1 左侧导航最终结构

必须按以下结构重构，不保留会员/支付/邀请/升级入口。

```text
工作区
- 工作台
- 项目管理

创作资产
- 题材库
- 素材库
- 知识库
- 文风库
- 精品标准库

分析拆解
- 网文拆解
- 出版/经典拆解
- 专业知识解析

生产流程
- 大纲生成
- 细纲生成
- 章节生产
- 审稿中心
- AI 编辑器
- 长篇稳定性

运营反馈
- 作品包装
- 发布中心
- 读者反馈
- 数据统计

管理工具
- 文档管理
- 任务中心
- Handoff 中心
- 系统健康
- 设置中心
```

### 3.2 页面通用规范

每个页面必须具备：

- 页面标题 + 一句话定位。
- 主操作按钮。
- 当前项目选择器。
- 本地状态条：`本地模式 / 数据本机保存 / 模型状态 / 自动保存 / 队列状态`。
- 空状态：说明为什么为空、下一步做什么。
- 加载状态。
- 错误状态：展示错误摘要、重试按钮、打开任务中心按钮。
- 最近产物列表。
- 与当前项目绑定，不混用跨项目资产。
- 所有写操作必须经过 schema validation。

### 3.3 当前页面映射到新 UI

| 当前页面 | 新页面归属 | 处理方式 |
|---|---|---|
| Studio | 工作台 + AI 编辑器 | 拆成“生产总览”和“专业编辑器”两个视角 |
| Projects | 项目管理 | 保留并加入平台/题材/精品/文风初始化向导 |
| Health | 系统健康 | 移入管理工具 |
| Tasks | 任务中心 | 移入管理工具 |
| Assets | 文档管理 + 各资产库 | 拆成通用文档管理和领域资产页 |
| Handoffs | Handoff 中心 | 移入管理工具，同时从拆解页联动 |
| Batch | 网文拆解 / 知识解析 | 拆成上传入库、拆解任务、验收绑定 |
| Drafts | 章节生产 | 加入平台/文风/精品目标输入 |
| Reviews | 审稿中心 | 升级为完整审核中心 |

---

## 4. 平台适配与题材选择系统

### 4.1 为什么要补

当前项目配置只有 `target_platform` 字段，但不同平台的创作逻辑不同。系统不能只做“起点精品小说”，而应做“精品小说体系”，再按不同平台派生不同题材、节奏、开篇、审核、更新、读者反馈策略。

### 4.2 新增资产类型

#### `platform_profile`

目录：`data/platforms`

字段建议：

```json
{
  "type": "platform_profile",
  "content": {
    "platform_id": "qidian|fanqie|jinjiang|qimao|weixin_reading|custom",
    "platform_name": "平台名称",
    "business_model": "paid_serial|free_ad|ip_publish|mixed",
    "reader_expectation": ["快节奏", "强钩子", "情绪爽点"],
    "chapter_length_range": {"min": 1800, "max": 3500, "ideal": 2500},
    "update_frequency": "daily|multi_daily|weekly|custom",
    "opening_rules": {
      "first_3_chapters_goal": "明确冲突、目标、悬念、爽点",
      "first_10_chapters_goal": "建立主线、金手指/核心机制、稳定追读"
    },
    "review_risks": ["低俗书名", "导流广告", "AI套话", "重复水文"],
    "genre_fit": ["都市", "玄幻", "悬疑", "女频", "历史"],
    "style_tendency": ["直接", "情绪强", "钩子密", "对话多"]
  }
}
```

#### `genre_market_profile`

目录：`data/genres`

字段建议：

```json
{
  "type": "genre_market_profile",
  "content": {
    "genre": "悬疑推理",
    "platform_id": "fanqie",
    "reader_promise": "持续反转、强悬念、短周期解谜",
    "common_hooks": ["尸体/异常事件", "身份误导", "倒计时"],
    "common_conflicts": ["主角 vs 真凶", "主角 vs 组织", "主角 vs 自身秘密"],
    "fatigue_points": ["谜题无解", "铺垫过长", "人物工具化"],
    "differentiation_axes": ["职业身份", "城市空间", "规则怪谈", "民俗元素"],
    "chapter_rhythm_template": "hook -> clue -> conflict -> reversal -> next hook"
  }
}
```

#### `topic_fit_report`

目录：`data/topics`

用于给题材打分。

```json
{
  "type": "topic_fit_report",
  "content": {
    "topic_seed_id": "xxx",
    "platform_id": "fanqie",
    "genre": "悬疑推理",
    "scores": {
      "platform_fit": 82,
      "reader_promise": 78,
      "differentiation": 70,
      "serialization_potential": 85,
      "risk": 22
    },
    "recommendation": "可开发",
    "must_adjust": ["开篇冲突提前", "减少设定说明", "强化第一章异常事件"]
  }
}
```

### 4.3 新增服务

- `src/novel_forge/modules/platforms/service.py`
- `src/novel_forge/modules/genres/service.py`
- `src/novel_forge/modules/topics/fit_service.py`

### 4.4 新增 API

```text
GET  /product/platforms
POST /product/platforms
GET  /product/platforms/{platform_id}
POST /product/projects/{project_id}/platform-target

GET  /product/genres
POST /product/genres
POST /product/topics/fit
GET  /product/projects/{project_id}/topic-fit-reports
```

### 4.5 UI 页面

#### 题材库

页面区域：

- 平台选择器。
- 题材分类卡片。
- 题材热度/适配度评分。
- 爽点模型。
- 风险点。
- 差异化方向。
- “生成题材种子”按钮。
- “评估当前题材”按钮。
- “绑定到项目”按钮。

验收标准：

- 创建项目时必须能选择平台和题材。
- 生成 topic_seed 时必须写入 platform_id、genre、reader_promise、differentiation_axes。
- 后续 outline/chapter_plan/draft 必须能读取项目平台和题材配置。

---

## 5. 精品小说体系

### 5.1 定义

精品小说体系不是某个平台单一标准，而是一个可配置的质量目标系统：

```text
精品小说 = 平台适配 + 题材承诺 + 人设抓力 + 结构稳定 + 节奏可追读 + 文风一致 + 原创安全 + 长篇可持续
```

不同平台的精品标准权重不同：

- 付费连载平台：重视追读、付费转化、升级节奏、长线结构。
- 免费广告平台：重视开篇速度、情绪刺激、章节钩子、低理解成本。
- 出版/IP向平台：重视主题、人物弧光、语言质感、结构完整度。
- 女性向/垂类平台：重视关系张力、情绪曲线、人设吸引力、互动爽点。

### 5.2 新增资产类型 `quality_standard_profile`

目录：`data/quality_standards`

```json
{
  "type": "quality_standard_profile",
  "content": {
    "standard_id": "fanqie_suspense_fast_read_v1",
    "name": "番茄悬疑快读精品标准",
    "platform_id": "fanqie",
    "genre": "悬疑推理",
    "target_length": "800k-1500k",
    "dimensions": {
      "opening_hook": {"weight": 0.15, "threshold": 80},
      "reader_promise": {"weight": 0.12, "threshold": 75},
      "plot_causality": {"weight": 0.12, "threshold": 80},
      "character_drive": {"weight": 0.1, "threshold": 75},
      "chapter_rhythm": {"weight": 0.12, "threshold": 80},
      "style_consistency": {"weight": 0.08, "threshold": 75},
      "originality_safety": {"weight": 0.12, "threshold": 85},
      "long_form_stability": {"weight": 0.1, "threshold": 75},
      "platform_compliance": {"weight": 0.09, "threshold": 90}
    },
    "hard_gates": [
      "copyright_boundary_passed",
      "platform_compliance_passed",
      "no_obvious_ai_low_quality",
      "no_major_continuity_break"
    ]
  }
}
```

### 5.3 新增资产类型 `quality_score_report`

目录：`data/reviews`

用于统一收敛各类评分。

```json
{
  "type": "quality_score_report",
  "content": {
    "target_asset_id": "draft_chapter_id",
    "standard_id": "fanqie_suspense_fast_read_v1",
    "total_score": 82,
    "dimension_scores": {
      "opening_hook": 86,
      "chapter_rhythm": 80,
      "style_consistency": 74,
      "originality_safety": 90
    },
    "hard_gate_result": "pass|fail|warning",
    "blocking_issues": [],
    "recommendations": []
  }
}
```

### 5.4 服务与接入点

新增：

- `src/novel_forge/modules/quality/standard_service.py`
- `src/novel_forge/modules/quality/scoring_service.py`
- `src/novel_forge/modules/quality/gate_service.py`

接入：

- `topic-development`：读取 quality_standard_profile。
- `generate-outline`：写入 quality target。
- `generate-chapter-plan`：按标准生成节奏和钩子。
- `draft`：生成时注入精品标准。
- `review`：按精品标准评分。
- `revise`：以失败维度为修订目标。
- `publish`：只允许通过 hard gate 的版本进入发布候选。

### 5.5 UI 页面：精品标准库

页面区域：

- 平台/题材标准列表。
- 质量维度权重编辑。
- 硬门禁配置。
- 当前项目绑定标准。
- 评分历史。
- “生成项目质量目标”按钮。

验收标准：

- 项目可绑定一个主标准。
- 每次 review 都能关联 standard_id。
- 审稿中心能展示标准维度评分，而不是只有通用 summary。

---

## 6. 文风系统

### 6.1 设计原则

文风系统只能学习和组合抽象机制，不允许复制受保护表达。

必须区分三层：

1. **平台文风**：例如短句密度、钩子频率、爽点表达、信息密度。
2. **题材文风**：例如悬疑重氛围和线索，玄幻重气势和设定，都市重对话和情绪。
3. **项目文风**：当前作品自己的语言规则、叙事距离、人物口吻、情绪基调。

文风来源也要区分：

- 网文拆解：提取节奏、爽点、钩子、追读表达机制。
- 出版/经典拆解：提取语言质感、心理描写、氛围、主题、细节组织。
- 项目正文：沉淀当前项目自己的风格指纹。

### 6.2 新增资产类型

#### `style_profile`

目录：`data/styles`

```json
{
  "type": "style_profile",
  "content": {
    "style_id": "suspense_fast_clean_v1",
    "name": "快节奏悬疑清爽风",
    "scope": "platform|genre|project|blend",
    "source_boundary": {
      "source_asset_ids": [],
      "derived_from_protected_text": false,
      "copyright_risk": "low|medium|high",
      "allowed_usage": "parameter_only"
    },
    "language_parameters": {
      "sentence_length": "short|medium|long|mixed",
      "paragraph_density": "low|medium|high",
      "dialogue_ratio": 0.35,
      "description_ratio": 0.25,
      "abstract_exposition_ratio": 0.1,
      "sensory_detail_level": "low|medium|high",
      "metaphor_density": "low|medium|high"
    },
    "narrative_parameters": {
      "pov": "first|third_limited|omniscient",
      "narrative_distance": "close|medium|far",
      "information_release": "direct|layered|misleading",
      "hook_frequency": "chapter_end|scene_end|paragraph_micro"
    },
    "emotion_parameters": {
      "dominant_mood": ["紧张", "压迫", "爽感"],
      "emotion_curve": "压迫->反击->悬念",
      "reader_feeling_target": ["想知道真相", "替主角紧张", "期待反转"]
    },
    "forbidden_patterns": [
      "禁止复用来源作品的标志性比喻",
      "禁止复用来源作品的专有名词",
      "禁止复用来源作品的句式连缀"
    ]
  }
}
```

#### `style_decomposition_report`

目录：`data/styles`

用于从文本中提炼风格参数。

```json
{
  "type": "style_decomposition_report",
  "content": {
    "source_asset_id": "cleaned_text_id",
    "extract_level": "abstract_parameters_only",
    "style_features": {},
    "usable_parameters": {},
    "do_not_copy": [],
    "risk_level": "low|medium|high"
  }
}
```

#### `style_blend_preset`

目录：`data/styles`

```json
{
  "type": "style_blend_preset",
  "content": {
    "name": "番茄悬疑快读 + 出版质感细节",
    "components": [
      {"style_profile_id": "fanqie_fast_read_v1", "weight": 0.65},
      {"style_profile_id": "published_detail_texture_v1", "weight": 0.35}
    ],
    "conflict_resolution": {
      "sentence_length": "prefer_short",
      "description_ratio": "cap_0.25",
      "psychological_depth": "scene_key_only"
    }
  }
}
```

#### `style_review_report`

目录：`data/reviews`

```json
{
  "type": "style_review_report",
  "content": {
    "target_draft_id": "draft_id",
    "expected_style_profile_id": "style_profile_id",
    "style_match_score": 78,
    "drift_points": [],
    "ai_taste_points": [],
    "rewrite_suggestions": [],
    "copyright_style_risk": "low|medium|high"
  }
}
```

### 6.3 新增服务

- `src/novel_forge/modules/style/profile_service.py`
- `src/novel_forge/modules/style/decompose_service.py`
- `src/novel_forge/modules/style/blend_service.py`
- `src/novel_forge/modules/style/rewrite_service.py`
- `src/novel_forge/modules/style/review_service.py`

### 6.4 新增 CLI

```bash
novel-forge style-decompose
novel-forge style-create-profile
novel-forge style-blend
novel-forge style-review
novel-forge style-rewrite
```

### 6.5 新增 API

```text
GET  /product/styles
POST /product/styles
POST /product/styles/decompose
POST /product/styles/blend
POST /product/styles/review
POST /product/styles/rewrite
POST /product/projects/{project_id}/style-target
```

### 6.6 UI 页面：文风库

页面区域：

- 文风 Profile 列表。
- 文风来源边界。
- 平台/题材/项目文风标签。
- 参数雷达图或参数卡片。
- 文风混合器。
- 文风审稿结果。
- 文风重写入口。

验收标准：

- 章节生成可以选择 style_profile 或 style_blend_preset。
- draft metadata 必须记录 style target。
- review 能输出 style_review_report。
- 系统必须明确显示“参数化使用，不模仿具体作者”。

---

## 7. 审核系统升级

### 7.1 当前问题

当前 review/revision 已经能生成 review_report、issue、revision_plan、revision preview，但还不是完整的平台审核系统。需要把 Review 升级为 Audit Center。

### 7.2 审核必须分为三类

#### A. 作品信息审核

检查对象：

- 书名。
- 作者名。
- 封面。
- 简介。
- 分类。
- 标签。
- 题材导向。
- 平台目标。
- 版权/IP 风险。

检查项：

- 书名无低俗、擦边、敏感导向、特殊符号堆砌。
- 封面包含书名和作者名，无外站 logo/水印。
- 简介无导流、广告、违规诱导。
- 分类标签与内容一致。
- 不碰明显平台红线。
- 不使用高风险 IP 近似名称。

#### B. 章节正文审核

检查对象：draft_chapter。

检查项：

- 内容红线。
- 未成年人负面导向。
- 违法违规内容。
- AI 套话。
- 提纲式正文。
- 大段重复。
- 模板化拼接。
- 无意义水文。
- 剧情逻辑。
- 人物一致性。
- 世界观一致性。
- 节奏爽点。
- 章节钩子。
- 文风一致性。
- 排版格式。
- 伏笔/战力/时间线连续性。

#### C. 发布前终审

检查对象：作品包 + 选定章节版本 + 导出文件。

检查项：

- 作品信息审核通过。
- 目标章节全部通过章节审核。
- 原创性/相似度风险低于阈值。
- 文风一致性达标。
- 精品标准 hard gate 通过。
- 导出文件存在且格式正确。
- 发布记录可追溯。

### 7.3 新增资产类型

#### `work_package`

目录：`data/publishing`

```json
{
  "type": "work_package",
  "content": {
    "project_id": "project_id",
    "title": "书名",
    "author_name": "作者名",
    "cover_asset_id": "optional",
    "intro": "简介",
    "platform_id": "fanqie",
    "genre": "悬疑",
    "tags": [],
    "target_audience": "",
    "selling_points": []
  }
}
```

#### `work_package_review`

目录：`data/reviews`

```json
{
  "type": "work_package_review",
  "content": {
    "work_package_id": "xxx",
    "platform_id": "fanqie",
    "result": "pass|warning|fail",
    "checks": [
      {"id": "title_risk", "status": "pass", "severity": "low", "message": ""}
    ],
    "blocking_issues": [],
    "suggested_changes": []
  }
}
```

#### `chapter_audit_report`

目录：`data/reviews`

```json
{
  "type": "chapter_audit_report",
  "content": {
    "draft_chapter_id": "xxx",
    "platform_id": "fanqie",
    "quality_standard_id": "xxx",
    "result": "pass|warning|fail",
    "scores": {
      "plot": 82,
      "rhythm": 78,
      "hook": 85,
      "style": 76,
      "ai_taste": 20,
      "compliance": 96,
      "continuity": 88
    },
    "issues": [],
    "required_actions": []
  }
}
```

#### `originality_report`

目录：`data/reviews`

```json
{
  "type": "originality_report",
  "content": {
    "target_asset_id": "draft_id",
    "reference_scope": "project_sources|all_approved_sources|external_optional",
    "risk_level": "low|medium|high",
    "similarity_scores": {
      "phrase_similarity": 0.05,
      "named_entity_overlap": 0.02,
      "plot_sequence_similarity": 0.12,
      "setting_overlap": 0.08
    },
    "forbidden_element_hits": [],
    "recommendation": "pass|revise|required_human_review"
  }
}
```

#### `publish_gate_report`

目录：`data/publishing`

```json
{
  "type": "publish_gate_report",
  "content": {
    "project_id": "project_id",
    "work_package_id": "xxx",
    "chapter_ids": [],
    "platform_id": "fanqie",
    "result": "pass|warning|fail",
    "gates": {
      "work_package": "pass",
      "chapter_audit": "pass",
      "quality_standard": "pass",
      "style": "warning",
      "originality": "pass",
      "export": "pass"
    },
    "blocking_issues": []
  }
}
```

### 7.4 新增服务

- `src/novel_forge/modules/audit/work_package_service.py`
- `src/novel_forge/modules/audit/chapter_audit_service.py`
- `src/novel_forge/modules/audit/originality_service.py`
- `src/novel_forge/modules/audit/publish_gate_service.py`
- `src/novel_forge/modules/audit/ai_taste_service.py`
- `src/novel_forge/modules/audit/platform_compliance_service.py`

### 7.5 UI 页面：审稿中心

审稿中心应拆为 5 个 tab：

1. **作品信息审核**
2. **章节正文审核**
3. **文风审核**
4. **原创性审核**
5. **发布前终审**

每个 tab 都要展示：

- 当前审核对象。
- 审核结果：pass / warning / fail。
- 阻塞问题。
- 可自动修复问题。
- 需人工确认问题。
- 生成修订计划按钮。
- 应用修订预览按钮。
- 重新审核按钮。

验收标准：

- 作品信息审核和章节审核必须是两个不同入口。
- 发布前终审必须汇总多个审核报告。
- fail 状态不能进入发布中心。
- 所有 audit report 必须可追溯 source/references。

---

## 8. 长篇稳定性系统

### 8.1 当前问题

当前 RAG 能检索人物、世界观、前文摘要、知识卡、素材卡、伏笔和 continuity threads，但缺少专门的长篇稳定性资产和规则引擎。百万字长篇需要显性化管理。

### 8.2 新增资产类型

#### `continuity_bible`

目录：`data/continuity`

```json
{
  "type": "continuity_bible",
  "content": {
    "project_id": "project_id",
    "locked_facts": [],
    "mutable_facts": [],
    "timeline_rules": [],
    "character_state_rules": [],
    "world_rule_constraints": [],
    "power_scale_constraints": []
  }
}
```

#### `foreshadowing_thread`

目录：`data/continuity`

```json
{
  "type": "foreshadowing_thread",
  "content": {
    "thread_id": "xxx",
    "name": "失踪的钥匙",
    "status": "planned|planted|developing|resolved|abandoned",
    "plant_chapter": 3,
    "payoff_chapter": 28,
    "related_assets": [],
    "risk": "forgotten|too_obvious|too_late|none"
  }
}
```

#### `power_scale_rule`

目录：`data/continuity`

```json
{
  "type": "power_scale_rule",
  "content": {
    "system_name": "境界/能力/资源体系",
    "levels": [],
    "upgrade_conditions": [],
    "forbidden_breaks": [],
    "current_character_states": []
  }
}
```

#### `chapter_continuity_report`

目录：`data/reviews`

```json
{
  "type": "chapter_continuity_report",
  "content": {
    "draft_chapter_id": "xxx",
    "result": "pass|warning|fail",
    "fact_conflicts": [],
    "timeline_conflicts": [],
    "character_state_conflicts": [],
    "power_scale_conflicts": [],
    "foreshadowing_updates": []
  }
}
```

### 8.3 新增服务

- `src/novel_forge/modules/continuity/bible_service.py`
- `src/novel_forge/modules/continuity/foreshadowing_service.py`
- `src/novel_forge/modules/continuity/power_scale_service.py`
- `src/novel_forge/modules/continuity/timeline_service.py`
- `src/novel_forge/modules/continuity/review_service.py`

### 8.4 UI 页面：长篇稳定性

页面区域：

- 设定锁定区。
- 人物状态表。
- 时间线。
- 伏笔线程看板。
- 战力/等级体系。
- 本章连续性检查。
- 变更影响分析。

验收标准：

- 修改 world_bible / character_card / outline 时能提示影响章节。
- 章节生成前能读取 continuity_bible。
- 章节审核能生成 chapter_continuity_report。
- 伏笔线程能标记投放、发展、回收、遗忘风险。

---

## 9. 网文拆解与出版/经典拆解分流

### 9.1 原则

网文和经典/出版小说不能用完全同一处理器。它们可以共享底层 source、clean、schema、handoff，但输出重点不同。

### 9.2 网文拆解输出重点

- 平台适配。
- 开篇钩子。
- 章节节奏。
- 爽点结构。
- 人设机制。
- 冲突设计。
- 情绪曲线。
- 追读点。
- 商业化逻辑。
- 读者反馈触发点。

### 9.3 出版/经典拆解输出重点

- 语言质感。
- 叙述视角。
- 心理描写。
- 氛围营造。
- 主题表达。
- 结构完整性。
- 象征与意象。
- 人物弧光。
- 场景细节组织。

### 9.4 新增类型字段

扩展 `decomposition_report.content`：

```json
{
  "decomposition_mode": "web_novel|published_classic|professional_knowledge",
  "platform_focus": {},
  "commercial_logic": {},
  "style_mechanisms": {},
  "do_not_copy": []
}
```

### 9.5 新增 Handoff 类型

| 类型 | skill | 输出 |
|---|---|---|
| 网文拆解 | `hot-novel-deconstruction` | `decomposition_report` |
| 出版/经典拆解 | `published-novel-deconstruction` | `decomposition_report` + `style_decomposition_report` |
| 专业知识解析 | `multidisciplinary-knowledge` | `knowledge_card` |
| 文风拆解 | `style-decomposition` | `style_decomposition_report` |

---

## 10. 读者反馈闭环

### 10.1 当前问题

已有 `reader_feedback`、`feedback_insight` 和 CLI，但 UI、运营流程和后续章节调整机制不足。

### 10.2 新增/扩展资产

#### `reader_feedback_batch`

```json
{
  "type": "reader_feedback_batch",
  "content": {
    "platform_id": "fanqie",
    "source": "manual_import|csv|api|scrape_allowed",
    "chapter_range": [1, 20],
    "items": []
  }
}
```

#### `feedback_strategy_report`

```json
{
  "type": "feedback_strategy_report",
  "content": {
    "project_id": "project_id",
    "summary": "",
    "positive_drivers": [],
    "negative_drivers": [],
    "drop_off_risks": [],
    "next_5_chapter_adjustments": [],
    "do_not_overreact": []
  }
}
```

### 10.3 UI 页面：读者反馈

页面区域：

- 导入评论/反馈。
- 评论聚类。
- 好评驱动。
- 差评原因。
- 追读风险。
- 后续 5 章调整建议。
- 与大纲/细纲联动。

验收标准：

- feedback_insight 可绑定到 project。
- chapter_plan 生成时可选择是否使用 feedback_strategy_report。
- 不允许因为单条评论直接大改主线，必须通过聚类和人工确认。

---

## 11. 作品包装与发布中心

### 11.1 新增页面：作品包装

用于管理：

- 书名。
- 作者名。
- 简介。
- 标签。
- 分类。
- 卖点。
- 封面提示词。
- 平台提交信息。
- 作品信息审核。

### 11.2 新增页面：发布中心

用于管理：

- 发布候选版本。
- 导出文件。
- 发布前终审。
- 发布记录。
- 平台提交状态。
- 修改后重新审核记录。

### 11.3 验收标准

- 未通过 publish_gate_report 的版本不能标记为 publish ready。
- 导出 Markdown/DOCX/EPUB 时必须绑定 publish record。
- 作品信息修改后必须重新生成 work_package_review。

---

## 12. 数据统计与模型/Agent 评测

### 12.1 创作数据统计

新增指标：

- 项目总字数。
- 日产字数。
- 章节生成数量。
- 审稿通过率。
- 平均质量分。
- 文风稳定度。
- 原创性风险趋势。
- 章节钩子强度趋势。
- 伏笔投放/回收数量。
- 反馈正负面趋势。
- 任务失败率。

### 12.2 模型/Agent 评测

新增指标：

- draft provider 质量分。
- review provider 严格度。
- revision 成功率。
- schema invalid rate。
- handoff acceptance pass rate。
- 每类 Agent 输出失败率。
- 人工确认退回率。

### 12.3 新增资产 `model_evaluation_report`

```json
{
  "type": "model_evaluation_report",
  "content": {
    "provider": "deepseek|chatgpt|mock",
    "operation": "draft|review|revise|style_review",
    "sample_size": 20,
    "average_score": 78,
    "schema_failure_rate": 0.05,
    "human_reject_rate": 0.2,
    "recommendation": "usable|needs_prompt_update|do_not_use"
  }
}
```

---

## 13. 后端模块化重构

### 13.1 必须先做的架构动作

当前 `src/novel_forge/api/product.py` 已经过大。后续新增功能前必须拆分 Product API。

目标结构：

```text
src/novel_forge/api/
  product.py                 # 只负责 include_router
  routers/
    projects.py
    tasks.py
    assets.py
    handoffs.py
    batch.py
    drafts.py
    reviews.py
    health.py
    platforms.py
    genres.py
    styles.py
    quality.py
    audit.py
    continuity.py
    feedback.py
    publishing.py
    stats.py
```

服务层目标结构：

```text
src/novel_forge/modules/
  platforms/
  genres/
  topics/
  style/
  quality/
  audit/
  continuity/
  feedback/
  publishing/
  stats/
```

### 13.2 重构验收

- 现有 API 行为不破坏。
- 现有测试全部通过。
- `make test`、`make lint`、`make validate` 通过。
- 新 router 有独立测试。
- `product.py` 只保留 app/router 聚合，不再继续堆业务代码。

---

## 14. Schema 与校验扩展清单

### 14.1 新增 schema 文件建议

```text
src/novel_forge/schemas/platforms.py
src/novel_forge/schemas/genres.py
src/novel_forge/schemas/styles.py
src/novel_forge/schemas/quality.py
src/novel_forge/schemas/audit.py
src/novel_forge/schemas/continuity.py
src/novel_forge/schemas/publishing.py
src/novel_forge/schemas/evaluation.py
```

### 14.2 新增资产类型总表

| 资产类型 | 目录 | 优先级 |
|---|---|---|
| platform_profile | data/platforms | P0 |
| genre_market_profile | data/genres | P0 |
| topic_fit_report | data/topics | P0 |
| quality_standard_profile | data/quality_standards | P0 |
| quality_score_report | data/reviews | P0 |
| style_profile | data/styles | P0 |
| style_decomposition_report | data/styles | P0 |
| style_blend_preset | data/styles | P0 |
| style_review_report | data/reviews | P0 |
| work_package | data/publishing | P0 |
| work_package_review | data/reviews | P0 |
| chapter_audit_report | data/reviews | P0 |
| originality_report | data/reviews | P0 |
| publish_gate_report | data/publishing | P0 |
| continuity_bible | data/continuity | P1 |
| foreshadowing_thread | data/continuity | P1 |
| power_scale_rule | data/continuity | P1 |
| chapter_continuity_report | data/reviews | P1 |
| reader_feedback_batch | data/feedback | P1 |
| feedback_strategy_report | data/feedback | P1 |
| model_evaluation_report | data/runs | P2 |

### 14.3 validate 扩展

`make validate` 必须新增检查：

- project 是否绑定 platform_profile。
- project 是否绑定 quality_standard_profile。
- draft 是否记录 style target。
- audit report 是否有 target_asset_id。
- publish_gate_report 是否汇总必需 gate。
- style_profile 是否包含 source_boundary 和 forbidden_patterns。
- originality_report 是否包含 forbidden_element_hits。
- continuity 资产是否绑定 project_id。

---

## 15. 生成流程改造

### 15.1 项目创建流程

```text
create project
  -> choose platform_profile
  -> choose genre_market_profile
  -> create or bind quality_standard_profile
  -> create style target
  -> initialize continuity_bible
  -> initialize work_package draft
```

### 15.2 章节生成流程

```text
chapter_plan
  -> build RAG context
  -> load platform_profile
  -> load genre_market_profile
  -> load quality_standard_profile
  -> load style_profile/style_blend_preset
  -> load continuity_bible
  -> generate draft
  -> style review
  -> chapter audit
  -> originality check
  -> quality score
  -> revision plan if needed
```

### 15.3 发布流程

```text
work_package
  -> work_package_review
  -> select chapter versions
  -> chapter_audit_report batch check
  -> originality_report check
  -> style_review_report check
  -> quality_score_report check
  -> export
  -> publish_gate_report
  -> publish_record
```

---

## 16. Codex 分阶段实现计划

### Phase 0：保护现有系统，拆 Product API

目标：先降低后续扩展风险。

任务：

1. 把 `src/novel_forge/api/product.py` 拆成 routers。
2. 保持所有现有 endpoint 兼容。
3. 给每个 router 加基础测试。
4. 跑通 `make test && make lint && make validate`。

验收：

- 不减少现有功能。
- 现有 Web 页面仍可调用 API。
- product.py 不再承载大块业务函数。

### Phase 1：平台/题材/精品标准基础

任务：

1. 新增 `platform_profile`、`genre_market_profile`、`topic_fit_report`。
2. 新增 `quality_standard_profile`、`quality_score_report`。
3. 项目配置扩展 platform/genre/quality_standard 绑定。
4. Web 新增“题材库”“精品标准库”。
5. draft/review 读取质量标准。

验收：

- 创建项目时可绑定平台和题材。
- 章节生成 metadata 记录 platform/genre/quality_standard。
- 审稿报告可以按质量标准维度输出分数。

### Phase 2：文风系统

任务：

1. 新增 style schema。
2. 新增 style service。
3. 新增文风库 UI。
4. 章节生成接入 style target。
5. 审稿中心接入 style_review_report。
6. 增加版权/洗稿风险字段和显示。

验收：

- 用户可创建/编辑 style_profile。
- 可从拆解结果生成 style_decomposition_report。
- 可混合两个以上 style_profile。
- draft metadata 记录 style target。
- style_review_report 可显示风格匹配分和 AI 味问题。

### Phase 3：审核中心升级

任务：

1. 新增 work_package、work_package_review。
2. 新增 chapter_audit_report。
3. 新增 originality_report。
4. 新增 publish_gate_report。
5. Reviews 页面升级为 Audit Center。
6. 发布中心只接受 publish gate pass 的版本。

验收：

- 作品信息审核与章节正文审核分离。
- 发布前终审能汇总作品、章节、原创性、文风、导出结果。
- fail 状态不能 publish ready。

### Phase 4：长篇稳定性

任务：

1. 新增 continuity_bible、foreshadowing_thread、power_scale_rule。
2. 新增长篇稳定性 UI。
3. 章节生成前加载 continuity context。
4. 章节审核生成 chapter_continuity_report。
5. 修改设定时给出影响范围。

验收：

- 伏笔线程可跟踪投放/回收。
- 角色状态、时间线、战力体系可以检查冲突。
- chapter_audit_report 能引用 continuity report。

### Phase 5：反馈、发布、统计、评测

任务：

1. 读者反馈中心。
2. 反馈策略报告。
3. 作品包装中心。
4. 发布中心。
5. 创作数据统计。
6. 模型/Agent 评测。

验收：

- 反馈能转成后续章节建议。
- 统计页能展示质量趋势。
- 能比较不同 provider 在 draft/review/revise 上的表现。

---

## 17. 测试要求

### 17.1 单元测试

新增测试目录：

```text
tests/unit/test_platform_profiles.py
tests/unit/test_genre_market_profiles.py
tests/unit/test_quality_standards.py
tests/unit/test_style_profiles.py
tests/unit/test_style_blend.py
tests/unit/test_audit_reports.py
tests/unit/test_originality_report.py
tests/unit/test_continuity_assets.py
```

### 17.2 集成测试

新增集成测试：

```text
tests/integration/test_project_creation_with_platform_quality_style.py
tests/integration/test_draft_with_style_and_quality_context.py
tests/integration/test_audit_center_publish_gate.py
tests/integration/test_continuity_review_flow.py
tests/integration/test_feedback_strategy_flow.py
```

### 17.3 前端测试/验收

至少人工验收以下路径：

1. 创建项目 -> 选择平台/题材/精品标准/文风。
2. 上传素材 -> 拆解 -> 生成知识/素材。
3. 生成大纲 -> 生成细纲 -> 生成章节。
4. 运行章节审核、文风审核、原创性审核。
5. 修改作品信息 -> 作品信息审核。
6. 通过发布前终审 -> 导出 -> 生成发布记录。
7. 导入读者反馈 -> 生成后续章节策略。

---

## 18. Codex 实现约束

Codex 必须遵守：

1. 不删除现有已实现功能。
2. 不引入登录、会员、支付、邀请、升级 UI。
3. 不把受版权保护原文作为正文生成直接上下文。
4. 新资产必须是 schema-backed JSON asset。
5. 所有写操作必须走 LocalStorage 和 schema validation。
6. 所有新功能必须绑定 project_id/workspace_path。
7. 新 API 必须有测试。
8. 新 UI 必须有空状态、加载状态、错误状态和主操作。
9. 新增模型输出必须 fail closed，不能 schema 解析失败还继续写入。
10. Handoff 输出必须检查 expected output type 和 Agent 权限。
11. 先拆 API，再扩功能。
12. 每个阶段结束必须运行：

```bash
make test
make lint
make validate
```

---

## 19. 可以直接交给 Codex 的任务提示词

```text
你是 novel-forge 项目的 Codex 工程实现助手。请读取仓库现有代码和本设计文档，基于当前 Novel Forge V5 实现，按阶段升级到 V6。

目标：把系统从“本地小说生产平台雏形”升级为“个人本地小说工厂系统”，补齐平台题材适配、精品小说标准、文风系统、审核中心、原创性控制、长篇稳定性、作品包装、发布中心、读者反馈、数据统计和模型评测。

硬约束：
1. 不删除现有功能。
2. 不做登录/会员/支付/邀请/升级。
3. 不把参考小说原文直接用于正文生成。
4. 文风只能参数化抽象，不能模仿具体作者。
5. 所有新资产必须 schema-backed。
6. 所有新 API 必须测试覆盖。
7. 所有写入必须保留 project_id/workspace_path。
8. 先拆分 src/novel_forge/api/product.py，再新增功能。
9. 每阶段结束运行 make test && make lint && make validate。

执行顺序：
Phase 0：拆 Product API routers，保持接口兼容。
Phase 1：实现 platform_profile、genre_market_profile、topic_fit_report、quality_standard_profile、quality_score_report，并接入项目配置和章节审稿。
Phase 2：实现文风系统：style_profile、style_decomposition_report、style_blend_preset、style_review_report，以及文风库 UI。
Phase 3：升级审核中心：work_package_review、chapter_audit_report、originality_report、publish_gate_report，并分离作品信息审核、章节正文审核、文风审核、原创性审核、发布前终审。
Phase 4：实现长篇稳定性：continuity_bible、foreshadowing_thread、power_scale_rule、chapter_continuity_report。
Phase 5：实现作品包装、发布中心、读者反馈中心、数据统计和模型/Agent 评测。

请先进行代码审计，输出当前文件结构、可复用模块、风险点和最小变更计划。然后从 Phase 0 开始实施。每完成一个阶段，提交变更摘要、测试结果、剩余风险和下一阶段计划。
```

---

## 20. 最终验收标准

系统达到 V6 后，应满足：

1. 能创建一个绑定平台、题材、精品标准和文风目标的小说项目。
2. 能把网文、出版/经典、专业知识拆解成不同类型资产。
3. 能从拆解结果中沉淀题材、素材、知识、文风参数，而不是复制原文。
4. 能按平台节奏生成大纲、细纲和章节。
5. 能按精品标准对章节评分。
6. 能做作品信息审核、章节审核、文风审核、原创性审核、发布前终审。
7. 能追踪长篇设定、伏笔、战力/等级、时间线、人物状态。
8. 能导入读者反馈并生成后续章节策略。
9. 能在 UI 上按小说工厂信息架构完成主要操作。
10. 能通过 `make test && make lint && make validate`。


---

# 附录 A：V6.1 名著 / 出版小说解析系统增补

> 本附录为 V6 设计的正式补充。后续 Codex 实现时，应把“分析拆解中心”从单一网文拆解升级为：通用小说解析底座 + 网文商业结构拆解 + 出版小说技法拆解 + 经典名著深度拆解 + 统一资产转换器。


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
