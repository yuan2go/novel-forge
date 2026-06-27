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

