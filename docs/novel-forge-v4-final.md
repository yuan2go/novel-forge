# novel-forge v4 最终项目文档

## 1. 项目定位

`novel-forge` 是一个工业级小说创作系统，不是单次生成小说章节的聊天式工具。

项目目标是建立一套可以长期运行、持续积累、持续生产、持续修正的内容创作工厂，覆盖从热门小说拆解、专业书籍知识提炼、多学科知识融合，到题材设计、世界观构建、人物系统、大纲、细纲、正文生成、审稿、读者反馈迭代的完整链路。

当前 v4 阶段的核心定位：

> 以 Claude Code 为项目总控，以 Codex / ChatGPT / DeepSeek 为协作模型，以结构化知识库和项目文件为长期记忆，构建面向东方玄幻、西幻悬疑及其他商业类型小说的工业化创作系统。

---

## 2. 项目总目标

### 2.1 业务目标

1. 建立可复用的小说创作生产线。
2. 支持批量拆解热门小说，但不照抄具体作品。
3. 支持专业书籍、多学科知识进入小说系统。
4. 支持东方玄幻优先，后续扩展到西幻、悬疑、推理、都市、科幻等类型。
5. 支持从题材库到正文发布的完整链路。
6. 支持读者评论导入，反向修正后续剧情和创作策略。
7. 支持长期沉淀为个人原创 IP 资产库。

### 2.2 技术目标

1. 使用 Claude Code 作为本地项目主编和执行总控。
2. 使用 Codex 作为工程副编、结构分析和规范执行模型。
3. 使用 DeepSeek 作为低成本正文生产、批量提取和长文本草稿模型。
4. 使用 ChatGPT 作为高级审稿、逻辑校验、商业化分析、多学科审核模型。
5. 使用 Markdown / JSON / YAML / SQLite / MySQL / 向量数据库作为长期知识存储。
6. 使用 Git 管理所有创作资产、结构化数据、提示词、模板和版本。
7. 建立标准化目录、数据结构、任务协议和质量门禁。

---

## 3. 核心原则

### 3.1 不照抄，只抽象

热门小说只能作为分析对象，不能作为直接仿写对象。

允许提炼：

1. 结构；
2. 节奏；
3. 爽点；
4. 人设机制；
5. 冲突设计；
6. 情绪曲线；
7. 章节钩子；
8. 商业化逻辑；
9. 读者反馈规律；
10. 毒点规避规则。

禁止直接复用：

1. 原角色；
2. 原世界观；
3. 原剧情桥段；
4. 原设定名称；
5. 原文表达；
6. 高相似章节结构；
7. 可识别的标志性人物关系；
8. 可识别的核心金手指设计。

### 3.2 文件是唯一长期记忆

聊天记录不能作为长期项目状态。

所有关键内容必须沉淀到仓库文件中：

1. 项目状态；
2. 当前目标；
3. 模型分工；
4. 题材库；
5. 世界观；
6. 人物设定；
7. 大纲；
8. 细纲；
9. 正文；
10. 审稿意见；
11. 读者反馈；
12. 模板；
13. 提示词；
14. 决策记录。

### 3.3 结构先于正文

正文生成不是第一步。

正确顺序是：

```text
素材 → 拆解 → 题材 → 世界观 → 人物 → 大纲 → 细纲 → 正文 → 审稿 → 修改 → 发布 → 反馈 → 迭代
```

没有题材机制，不写正文。

没有世界观规则，不写正文。

没有人物欲望和冲突，不写正文。

没有章节细纲，不批量写正文。

### 3.4 多模型分工，不混乱调用

每个模型必须有明确职责。

| 模型 / 工具 | 核心角色 | 主要任务 | 禁止事项 |
|---|---|---|---|
| Claude Code | 项目总控 / 主编 / 调度器 | 读写仓库、拆任务、调用模型、维护状态、执行质量门禁 | 不直接无结构地长篇创作 |
| Codex | 工程副编 / 结构建模 / 规范执行 | 目录、脚本、Schema、结构化拆解、校验器、流程自动化 | 不作为最终正文主力 |
| DeepSeek | 正文生产 / 批量提取 / 草稿生成 | 章节初稿、批量小说解析、评论粗分类、长文本生成 | 不直接作为最终审稿结论 |
| ChatGPT | 高级审稿 / 商业分析 / 多学科审核 | 逻辑审查、结构审查、爽点审查、知识融合审查、毒点判断 | 不直接绕过项目文件做临时创作 |

---

## 4. 项目对象分层

本项目所有内容必须区分以下 12 类对象。

| 对象 | 定义 | 主要产物 | 存储位置 |
|---|---|---|---|
| 素材 | 原始输入，包括小说、评论、书籍、文章、灵感 | 原文、摘录、清洗文本 | `data/raw/` |
| 拆解 | 对素材的结构化分析 | 结构、节奏、爽点、毒点、人物机制 | `knowledge/dissections/` |
| 题材 | 可开发的商业故事方向 | 题材卡、卖点卡、差异化卡 | `factory/topics/` |
| 世界观 | 故事运行规则 | 地图、势力、修炼体系、制度、资源、历史 | `factory/worlds/` |
| 人物 | 角色系统 | 主角、反派、配角、关系网、成长线 | `factory/characters/` |
| 大纲 | 全书 / 分卷 / 主线结构 | 总纲、卷纲、主线、阶段目标 | `factory/outlines/` |
| 细纲 | 章节级剧情设计 | 章节目标、冲突、钩子、信息点 | `factory/chapter_plans/` |
| 正文 | 小说文本 | 初稿、修订稿、定稿 | `manuscripts/` |
| 审稿 | 对创作结果的质量检查 | 审稿报告、修改建议、风险清单 | `reviews/` |
| 反馈 | 读者评论和市场反应 | 评论分类、爽点反馈、毒点反馈 | `feedback/` |
| 训练题 | 写作训练和阅读训练 | 拆解题、仿结构练习、作文训练 | `training/` |
| 可复用模板 | 流程、提示词、文档格式 | Prompt、Schema、检查表、任务模板 | `templates/` |

---

## 5. v4 总体架构

```text
                      用户 / 作者 / 主编
                              │
                              ▼
                    Claude Code 总控层
       ┌──────────────────────┼──────────────────────┐
       │                      │                      │
       ▼                      ▼                      ▼
  Codex 工程副编        ChatGPT 高级审稿        DeepSeek 正文生产
  结构 / Schema          逻辑 / 商业 / 知识        长文本 / 批量生成
       │                      │                      │
       └──────────────────────┼──────────────────────┘
                              ▼
                        novel-forge 仓库
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
   素材与拆解库           创作资产库              生产输出库
 小说 / 评论 / 书籍       题材 / 世界观 / 人物       细纲 / 正文 / 审稿
                              │
                              ▼
                         向量库 / 结构库
                              │
                              ▼
                      发布反馈与迭代系统
```

---

## 6. 仓库目录结构

```text
novel-forge/
├── README.md
├── CLAUDE.md
├── PROJECT_STATE.md
├── CURRENT_GOAL.md
├── CHANGELOG.md
├── DECISIONS.md
│
├── docs/
│   ├── novel-forge-v4-final.md
│   ├── architecture.md
│   ├── workflow.md
│   ├── model-collaboration.md
│   ├── quality-gates.md
│   └── originality-policy.md
│
├── configs/
│   ├── models.yaml
│   ├── pipeline.yaml
│   ├── rag.yaml
│   ├── review_rules.yaml
│   └── genre_rules.yaml
│
├── data/
│   ├── raw/
│   │   ├── novels/
│   │   ├── books/
│   │   ├── articles/
│   │   └── comments/
│   ├── cleaned/
│   ├── chunks/
│   └── metadata/
│
├── knowledge/
│   ├── materials/
│   ├── dissections/
│   │   ├── hot_novels/
│   │   ├── professional_books/
│   │   └── reader_comments/
│   ├── discipline/
│   │   ├── philosophy/
│   │   ├── history/
│   │   ├── psychology/
│   │   ├── sociology/
│   │   ├── economics/
│   │   ├── politics/
│   │   ├── military/
│   │   ├── law/
│   │   ├── religion_mythology/
│   │   ├── geography_ecology/
│   │   ├── science/
│   │   ├── mathematics_logic/
│   │   ├── medicine_body/
│   │   ├── architecture_city/
│   │   └── language_rhetoric/
│   ├── tropes/
│   ├── hooks/
│   ├── conflicts/
│   ├── poison_points/
│   └── commercial_patterns/
│
├── factory/
│   ├── topics/
│   ├── worlds/
│   ├── characters/
│   ├── relationships/
│   ├── outlines/
│   ├── chapter_plans/
│   ├── plot_devices/
│   └── revision_plans/
│
├── manuscripts/
│   ├── drafts/
│   ├── revised/
│   ├── final/
│   └── published/
│
├── reviews/
│   ├── structure/
│   ├── logic/
│   ├── genre/
│   ├── prose/
│   ├── originality/
│   ├── discipline/
│   └── final_reports/
│
├── feedback/
│   ├── raw_comments/
│   ├── cleaned_comments/
│   ├── sentiment/
│   ├── reader_needs/
│   ├── poison_points/
│   └── iteration_suggestions/
│
├── training/
│   ├── reading/
│   ├── writing/
│   ├── structure_drills/
│   ├── suspense_drills/
│   └── composition/
│
├── templates/
│   ├── task_packet.md
│   ├── novel_dissection_template.md
│   ├── discipline_card_template.md
│   ├── topic_card_template.md
│   ├── worldview_template.md
│   ├── character_card_template.md
│   ├── outline_template.md
│   ├── chapter_plan_template.md
│   ├── chapter_draft_template.md
│   ├── review_report_template.md
│   └── feedback_report_template.md
│
├── prompts/
│   ├── claude_code/
│   ├── codex/
│   ├── chatgpt/
│   ├── deepseek/
│   └── shared/
│
├── schemas/
│   ├── material.schema.json
│   ├── dissection.schema.json
│   ├── discipline_card.schema.json
│   ├── topic.schema.json
│   ├── world.schema.json
│   ├── character.schema.json
│   ├── outline.schema.json
│   ├── chapter_plan.schema.json
│   ├── manuscript.schema.json
│   ├── review.schema.json
│   └── feedback.schema.json
│
├── scripts/
│   ├── ingest/
│   ├── clean/
│   ├── chunk/
│   ├── extract/
│   ├── validate/
│   ├── index/
│   ├── review/
│   └── publish/
│
├── tests/
│   ├── schema_tests/
│   ├── pipeline_tests/
│   ├── originality_tests/
│   └── quality_gate_tests/
│
└── output/
    ├── reports/
    ├── exports/
    └── release_packages/
```

---

## 7. Claude Code 总控框架

### 7.1 Claude Code 的定位

Claude Code 不是单纯聊天工具，而是 `novel-forge` 的本地项目总控。

它负责：

1. 读取项目状态；
2. 理解当前目标；
3. 拆分任务；
4. 调用合适模型；
5. 管理文件；
6. 执行脚本；
7. 校验结构；
8. 汇总结果；
9. 触发审稿；
10. 更新项目状态；
11. 形成可追踪的版本记录。

### 7.2 Claude Code 工作模式

Claude Code 必须按照以下模式运行：

```text
PLAN → CONTEXT → EXECUTE → VERIFY → REVIEW → REPAIR → ARCHIVE
```

| 阶段 | 说明 |
|---|---|
| PLAN | 明确目标、输入、输出、约束、验收标准 |
| CONTEXT | 读取必要文件，不依赖聊天记忆 |
| EXECUTE | 调用模型或脚本执行任务 |
| VERIFY | 校验文件格式、Schema、逻辑完整性 |
| REVIEW | 调用 ChatGPT / Codex 做审稿或检查 |
| REPAIR | 根据问题修复内容 |
| ARCHIVE | 写入项目状态、变更日志、决策记录 |

### 7.3 Claude Code 必读文件

每次进入项目，Claude Code 必须优先读取：

```text
CLAUDE.md
PROJECT_STATE.md
CURRENT_GOAL.md
DECISIONS.md
configs/models.yaml
configs/pipeline.yaml
configs/review_rules.yaml
```

### 7.4 `CLAUDE.md` 标准内容

```markdown
# CLAUDE.md

## 项目身份

你是 novel-forge 项目的本地项目总控、主编和执行协调器。

你的任务不是直接随机创作小说，而是维护一个工业级小说创作系统。

## 核心原则

1. 文件是唯一长期记忆。
2. 所有任务必须有输入、输出、验收标准。
3. 热门小说只允许抽象拆解，不允许照抄。
4. 正文生成前必须存在题材、世界观、人物、大纲和细纲。
5. 每次修改必须更新 PROJECT_STATE.md 或 CHANGELOG.md。
6. 复杂任务必须拆分给 Codex / ChatGPT / DeepSeek。
7. 生成内容必须经过质量门禁。

## 模型分工

- Codex：结构、Schema、脚本、流程、结构化拆解。
- DeepSeek：批量提取、正文初稿、长文本生成。
- ChatGPT：高级审稿、逻辑校验、多学科知识审查、商业化分析。
- Claude Code：总控、调度、文件治理、质量门禁。

## 禁止事项

1. 禁止直接照搬已有小说设定。
2. 禁止跳过大纲直接批量写正文。
3. 禁止只在聊天中保存重要设定。
4. 禁止没有审稿就进入 final。
5. 禁止把读者反馈当成无条件修改命令。
```

---

## 8. 多模型协作机制

### 8.1 总体协作逻辑

```text
Claude Code 负责判断任务类型
        │
        ├── 工程 / 结构 / Schema / 校验 → Codex
        ├── 正文 / 批量提取 / 长文本草稿 → DeepSeek
        ├── 审稿 / 逻辑 / 商业化 / 多学科审核 → ChatGPT
        └── 文件写入 / 状态更新 / 流程推进 → Claude Code
```

### 8.2 Codex 职责

Codex 是工程副编。

主要负责：

1. 仓库结构优化；
2. Schema 编写；
3. JSON / YAML 校验；
4. 数据清洗脚本；
5. 文本切分脚本；
6. 向量库索引脚本；
7. 批量处理 pipeline；
8. 文件命名规范；
9. 任务模板优化；
10. 结构化小说拆解；
11. 对 DeepSeek 输出进行格式修复；
12. 对章节细纲进行结构一致性检查。

Codex 输出要求：

```text
必须结构化、可验证、可落盘。
```

### 8.3 DeepSeek 职责

DeepSeek 是正文生产和批量处理模型。

主要负责：

1. 长篇素材粗拆解；
2. 热门小说批量解析；
3. 专业书籍批量摘要；
4. 评论粗分类；
5. 正文初稿；
6. 多版本章节草稿；
7. 场景扩写；
8. 对话扩写；
9. 动作戏扩写；
10. 氛围描写扩写。

DeepSeek 输出要求：

```text
可以粗糙，但必须完整。
可以生成初稿，但不能直接定稿。
```

### 8.4 ChatGPT 职责

ChatGPT 是高级审稿和认知分析模型。

主要负责：

1. 小说结构审查；
2. 章节节奏审查；
3. 爽点密度审查；
4. 毒点风险审查；
5. 人物动机审查；
6. 世界观规则审查；
7. 悬疑逻辑审查；
8. 多学科知识使用审查；
9. 商业化可读性判断；
10. 是否存在照抄风险；
11. 修改方案设计；
12. 读者反馈策略分析。

ChatGPT 输出要求：

```text
必须给出问题、原因、修改方向、优先级。
```

### 8.5 Claude Code 职责

Claude Code 是主编和调度器。

主要负责：

1. 读取上下文；
2. 拆分任务；
3. 选择模型；
4. 整合输出；
5. 写入文件；
6. 运行校验；
7. 记录决策；
8. 推进 pipeline；
9. 管理版本；
10. 防止系统偏离目标。

Claude Code 输出要求：

```text
必须让项目状态可追踪、可恢复、可继续。
```

---

## 9. 多学科知识融合系统

### 9.1 多学科知识的定位

多学科知识不是用来堆设定，也不是用来炫知识。

在小说中，多学科知识必须转化为：

1. 世界规则；
2. 冲突来源；
3. 人物动机；
4. 势力制度；
5. 修炼体系；
6. 悬疑线索；
7. 资源分配；
8. 社会秩序；
9. 叙事隐喻；
10. 情绪压迫；
11. 选择困境；
12. 商业爽点。

错误用法：

```text
作者直接解释一大段知识。
```

正确用法：

```text
知识变成角色必须面对的规则、代价、诱惑、限制和冲突。
```

### 9.2 核心学科库

| 学科 | 小说中的主要用途 |
|---|---|
| 哲学 | 价值冲突、修行终点、命运观、自由意志、道心 |
| 历史 | 王朝兴衰、宗门更替、战争逻辑、制度演化 |
| 心理学 | 人物欲望、创伤、执念、恐惧、操控、背叛 |
| 社会学 | 阶层、身份、群体秩序、宗门生态、家族结构 |
| 经济学 | 资源稀缺、灵石体系、丹药市场、利益交换 |
| 政治学 | 权力结构、联盟、背叛、统治合法性 |
| 军事学 | 战役、阵法、后勤、指挥、伏击、消耗战 |
| 法律 | 门规、契约、审判、罪责、秩序冲突 |
| 宗教 / 神话 | 信仰体系、祭祀、神权、禁忌、天命 |
| 地理 / 生态 | 地图、秘境、资源分布、灾害、族群生态 |
| 自然科学 | 炼器、阵法、术法规则、能量守恒、材料限制 |
| 数学 / 逻辑 | 推理结构、谜题、阵法规则、因果链 |
| 医学 / 身体 | 修炼代价、伤势、毒、丹药、副作用 |
| 建筑 / 城市 | 宗门、洞府、古城、迷宫、空间叙事 |
| 语言 / 修辞 | 命名系统、古籍文本、谶语、伏笔表达 |
| 叙事学 | 结构、节奏、钩子、反转、情绪曲线 |

### 9.3 多学科知识提炼流程

```text
专业书籍 / 文章 / 课程
        │
        ▼
知识清洗
        │
        ▼
概念卡提取
        │
        ▼
叙事功能转译
        │
        ▼
类型小说适配
        │
        ▼
题材 / 世界观 / 人物 / 情节复用
```

### 9.4 知识卡标准结构

```yaml
id: discipline_0001
title: 资源稀缺导致权力垄断
discipline:
  - economics
  - sociology
source:
  type: book
  name: ""
  chapter: ""
core_concept: >
  当关键资源稀缺且不可替代时，掌握资源分配权的一方会形成稳定权力结构。
story_function:
  - 世界观规则
  - 宗门制度
  - 主角压迫
  - 爽点反转
genre_usage:
  eastern_fantasy: >
    灵脉、丹药、功法、秘境名额被大宗门垄断，小人物必须打破资源封锁。
  western_fantasy_suspense: >
    魔法材料被议会控制，谋杀案背后是资源走私和权力黑幕。
conflict_design:
  external_conflict: 资源被垄断，主角无法正常晋升。
  internal_conflict: 主角是否也会成为新的垄断者。
  climax_usage: 主角公开打破资源分配规则，引发秩序重组。
usable_elements:
  - 垄断者
  - 黑市
  - 名额制度
  - 资源税
  - 禁术交易
avoid:
  - 不要写成经济学讲义
  - 不要直接解释概念
  - 必须转化为剧情压力
```

---

## 10. 东方玄幻创作子系统

### 10.1 东方玄幻的核心资产

东方玄幻优先建设以下资产：

1. 修炼体系；
2. 境界体系；
3. 功法体系；
4. 灵气 / 资源体系；
5. 宗门体系；
6. 王朝体系；
7. 家族体系；
8. 秘境体系；
9. 丹药体系；
10. 炼器体系；
11. 阵法体系；
12. 妖族 / 魔族 / 神族体系；
13. 天道 / 因果 / 气运体系；
14. 主角金手指；
15. 升级节奏；
16. 爽点模型；
17. 反派压迫模型；
18. 打脸与反转模型。

### 10.2 东方玄幻的世界观规则

东方玄幻世界观必须回答：

1. 力量从哪里来？
2. 资源为什么稀缺？
3. 境界为什么有门槛？
4. 主角为什么能破局？
5. 强者为什么不随便碾压弱者？
6. 宗门为什么需要弟子？
7. 王朝为什么能存在？
8. 家族为什么重要？
9. 秘境为什么定期开启？
10. 天道 / 因果 / 气运如何限制人物？
11. 主角变强需要付出什么代价？
12. 反派为什么不是纯粹愚蠢？

### 10.3 东方玄幻爽点机制

| 爽点类型 | 说明 |
|---|---|
| 压迫反弹 | 主角被压迫后反击 |
| 资源逆袭 | 主角获得别人无法获得的资源 |
| 认知差 | 主角知道别人不知道的规则 |
| 境界反杀 | 低境界击败高境界 |
| 身份反转 | 被轻视者暴露隐藏价值 |
| 规则破局 | 主角打破旧制度 |
| 长线伏笔兑现 | 前文小信息在后文变成关键优势 |
| 群体认可 | 从被排斥到被承认 |
| 敌人震惊 | 反派认知崩塌 |
| 代价成长 | 主角通过痛苦换取真正提升 |

---

## 11. 西幻悬疑扩展子系统

### 11.1 西幻悬疑的核心资产

西幻悬疑方向需要额外建设：

1. 魔法规则；
2. 城市结构；
3. 教会体系；
4. 贵族体系；
5. 学院体系；
6. 冒险者 / 公会体系；
7. 禁忌知识；
8. 神秘仪式；
9. 密室规则；
10. 谋杀动机；
11. 线索链；
12. 误导线；
13. 反转机制；
14. 调查流程；
15. 公平推理规则；
16. 证据系统；
17. 伪证系统；
18. 真相揭示节奏。

### 11.2 悬疑推理基本规则

悬疑推理必须保证：

1. 真相提前存在；
2. 线索提前埋入；
3. 误导必须合理；
4. 反转不能靠临时设定；
5. 凶手动机必须成立；
6. 作案手法必须可复盘；
7. 主角推理不能跳跃；
8. 读者回看时能发现伏笔；
9. 魔法不能破坏公平推理；
10. 结局必须同时解决情节问题和情绪问题。

---

## 12. 热门小说拆解系统

### 12.1 拆解目标

热门小说拆解不是为了复制，而是为了建立商业叙事数据库。

必须提取：

1. 题材定位；
2. 开局钩子；
3. 主角欲望；
4. 初始压迫；
5. 金手指机制；
6. 升级节奏；
7. 反派配置；
8. 爽点分布；
9. 情绪曲线；
10. 章节钩子；
11. 毒点；
12. 读者评论反馈；
13. 商业化原因；
14. 可借鉴抽象结构；
15. 不可模仿具体元素。

### 12.2 拆解流程

```text
原始小说
  │
  ▼
文本清洗
  │
  ▼
章节切分
  │
  ▼
DeepSeek 粗拆解
  │
  ▼
Codex 结构化整理
  │
  ▼
ChatGPT 高级分析
  │
  ▼
原创性风险过滤
  │
  ▼
写入拆解库 / 向量库 / 模板库
```

### 12.3 小说拆解报告结构

```yaml
id: dissection_0001
source_type: hot_novel
genre: eastern_fantasy
title_placeholder: ""
analysis_date: ""
core_positioning:
  main_hook: ""
  reader_expectation: ""
  commercial_label: []
structure:
  opening:
    hook: ""
    conflict: ""
    protagonist_pressure: ""
  first_30_chapters:
    rhythm: ""
    upgrade_points: []
    reversals: []
  middle:
    expansion_method: ""
    conflict_escalation: ""
  later:
    power_scaling: ""
    world_expansion: ""
character_mechanism:
  protagonist:
    desire: ""
    weakness: ""
    growth_engine: ""
  antagonist:
    pressure_function: ""
    resource_advantage: ""
  supporting_roles:
    functions: []
cool_points:
  - type: ""
    chapter_range: ""
    emotional_effect: ""
poison_points:
  - issue: ""
    reader_reaction: ""
    avoid_rule: ""
abstract_patterns:
  reusable:
    - ""
  forbidden:
    - ""
commercial_logic: ""
```

---

## 13. 专业书籍拆解系统

### 13.1 书籍拆解目标

专业书籍拆解不是为了写读书笔记，而是为了获得小说可用的认知资产。

必须提取：

1. 核心概念；
2. 因果机制；
3. 冲突模型；
4. 制度模型；
5. 人性模型；
6. 权力模型；
7. 资源模型；
8. 决策模型；
9. 可故事化场景；
10. 可转化为世界观的规则；
11. 可转化为人物动机的心理机制；
12. 可转化为悬疑线索的逻辑结构。

### 13.2 专业书籍拆解流程

```text
专业书籍
  │
  ▼
章节摘要
  │
  ▼
概念卡
  │
  ▼
因果链
  │
  ▼
叙事功能
  │
  ▼
类型适配
  │
  ▼
题材 / 世界观 / 人物 / 情节资产
```

---

## 14. 题材库系统

### 14.1 题材卡结构

```yaml
id: topic_0001
title: 被灵脉垄断压制的底层阵修
genre:
  primary: eastern_fantasy
  secondary:
    - suspense
    - sect_politics
core_hook: >
  主角出身低微，却能看见灵脉流动中的阵法缺陷，因此被卷入宗门资源垄断的斗争。
reader_expectation:
  - 底层逆袭
  - 规则破解
  - 宗门斗争
  - 阵法爽点
commercial_tags:
  - 玄幻
  - 修仙
  - 阵法
  - 宗门
  - 逆袭
differentiation:
  - 将经济学资源垄断转化为灵脉分配制度
  - 将推理结构用于破解阵法阴谋
core_conflict:
  external: 宗门高层垄断灵脉和秘境名额
  internal: 主角变强后是否会复制旧秩序
  social: 底层弟子与核心弟子的阶层冲突
world_requirements:
  - 灵脉制度
  - 阵法体系
  - 宗门资源分配
  - 黑市交易
character_requirements:
  protagonist: 具备规则洞察能力，但缺少资源
  antagonist: 掌握资源分配权
  mentor: 理解旧制度但失败过
risk:
  - 容易写成普通废柴流
  - 阵法规则必须清楚
  - 资源压迫不能只靠口头羞辱
```

### 14.2 题材评估标准

每个题材必须通过以下问题：

1. 一句话卖点是否清晰？
2. 主角欲望是否强？
3. 初始压迫是否明确？
4. 爽点是否可持续？
5. 世界观是否能扩展？
6. 人物关系是否能产生长期冲突？
7. 是否有差异化？
8. 是否能写出前 30 章？
9. 是否能写到 100 万字以上？
10. 是否存在明显照抄风险？

---

## 15. 世界观系统

### 15.1 世界观不是设定堆砌

世界观必须服务于：

1. 冲突；
2. 爽点；
3. 人物选择；
4. 升级路径；
5. 长线伏笔；
6. 商业可读性。

### 15.2 世界观模板

```yaml
id: world_0001
name: ""
genre: eastern_fantasy
core_rule: ""
power_system:
  source: ""
  levels: []
  limitations: []
  cost: ""
resource_system:
  key_resources: []
  distribution: ""
  monopoly_structure: ""
  black_market: ""
political_system:
  sects: []
  dynasties: []
  clans: []
  hidden_powers: []
geography:
  regions: []
  forbidden_areas: []
  secret_realms: []
history:
  ancient_event: ""
  current_order: ""
  hidden_truth: ""
conflict_engine:
  resource_conflict: ""
  class_conflict: ""
  belief_conflict: ""
  personal_conflict: ""
plot_usage:
  early_stage: ""
  middle_stage: ""
  late_stage: ""
risk:
  - ""
```

---

## 16. 人物系统

### 16.1 人物不是标签

人物必须由以下机制驱动：

1. 欲望；
2. 恐惧；
3. 创伤；
4. 缺陷；
5. 误判；
6. 资源处境；
7. 社会位置；
8. 关系压力；
9. 道德选择；
10. 成长代价。

### 16.2 人物卡模板

```yaml
id: character_0001
name: ""
role: protagonist
genre_function:
  - 承载主线
  - 制造爽点
  - 推动世界观破解
basic_info:
  age: ""
  origin: ""
  identity: ""
external_goal: ""
internal_need: ""
core_wound: ""
core_fear: ""
core_strength: ""
core_flaw: ""
resource_position: ""
relationship_network:
  allies: []
  enemies: []
  ambiguous: []
growth_arc:
  start: ""
  middle: ""
  end: ""
conflict_usage:
  personal_conflict: ""
  social_conflict: ""
  worldview_conflict: ""
scene_usage:
  opening: ""
  first_turning_point: ""
  climax: ""
risk:
  - ""
```

---

## 17. 大纲系统

### 17.1 大纲层级

大纲分为四层：

```text
全书总纲
  ↓
分卷卷纲
  ↓
阶段剧情线
  ↓
章节细纲
```

### 17.2 总纲模板

```yaml
id: outline_0001
title: ""
genre: eastern_fantasy
one_sentence_hook: ""
core_theme: ""
commercial_positioning: ""
protagonist_arc: ""
world_arc: ""
main_conflict: ""
volume_plan:
  - volume: 1
    title: ""
    chapter_range: "1-80"
    core_goal: ""
    main_enemy: ""
    upgrade_stage: ""
    climax: ""
  - volume: 2
    title: ""
    chapter_range: "81-180"
    core_goal: ""
    main_enemy: ""
    upgrade_stage: ""
    climax: ""
long_term_hooks:
  - ""
hidden_truths:
  - ""
risk:
  - ""
```

---

## 18. 细纲系统

### 18.1 章节细纲必须包含

每章细纲必须包含：

1. 本章目标；
2. 主冲突；
3. 出场人物；
4. 场景；
5. 信息增量；
6. 爽点；
7. 伏笔；
8. 悬念；
9. 结尾钩子；
10. 与前后章节关系。

### 18.2 章节细纲模板

```yaml
id: chapter_plan_0001
chapter_no: 1
title: ""
volume: 1
position: opening
pov: protagonist
scene:
  location: ""
  time: ""
  atmosphere: ""
characters:
  present: []
  mentioned: []
chapter_goal: ""
main_conflict: ""
emotional_curve:
  start: ""
  pressure: ""
  turn: ""
  release: ""
plot_beats:
  - beat: 1
    content: ""
    function: ""
information_gain:
  - ""
cool_points:
  - ""
foreshadowing:
  - ""
suspense:
  - ""
ending_hook: ""
continuity:
  previous: ""
  next: ""
draft_instructions:
  style: ""
  pacing: ""
  avoid:
    - ""
```

---

## 19. 正文生产系统

### 19.1 正文生产原则

正文必须基于章节细纲生成。

DeepSeek 可生成初稿，但必须经过：

1. 结构检查；
2. 逻辑检查；
3. 人物一致性检查；
4. 世界观一致性检查；
5. 爽点密度检查；
6. 毒点检查；
7. 原创性风险检查；
8. 语言修订。

### 19.2 正文版本流转

```text
draft_v1        DeepSeek 初稿
draft_v2        根据结构问题修订
reviewed_v1     ChatGPT 审稿后版本
revised_v1      修改后版本
final_v1        可发布版本
published_v1    已发布版本
```

### 19.3 正文文件命名

```text
manuscripts/drafts/volume_01/chapter_001_draft_v1.md
manuscripts/revised/volume_01/chapter_001_revised_v1.md
manuscripts/final/volume_01/chapter_001_final_v1.md
manuscripts/published/volume_01/chapter_001_published_v1.md
```

---

## 20. 审稿系统

### 20.1 审稿不是润色

审稿必须判断：

1. 这一章是否值得读者继续看；
2. 这一章是否推进剧情；
3. 这一章是否制造情绪；
4. 这一章是否兑现或制造期待；
5. 这一章是否破坏人物；
6. 这一章是否破坏世界观；
7. 这一章是否有毒点；
8. 这一章是否有商业阅读价值。

### 20.2 审稿维度

| 维度 | 检查内容 |
|---|---|
| 结构 | 是否有目标、冲突、转折、钩子 |
| 节奏 | 是否拖沓，是否有信息增量 |
| 爽点 | 是否有期待、压迫、反击、释放 |
| 人物 | 动机是否成立，行为是否一致 |
| 世界观 | 规则是否自洽，设定是否临时补丁 |
| 悬疑 | 线索是否公平，反转是否合理 |
| 多学科 | 知识是否转化为剧情，而不是说明文 |
| 商业化 | 是否符合类型读者期待 |
| 原创性 | 是否有可识别照抄风险 |
| 语言 | 是否清楚、有画面、有张力 |

### 20.3 审稿报告模板

```yaml
id: review_0001
target_file: ""
review_type:
  - structure
  - logic
  - commercial
  - discipline
  - originality
score:
  structure: 0
  pacing: 0
  cool_points: 0
  character: 0
  world_logic: 0
  prose: 0
  originality: 0
major_issues:
  - issue: ""
    severity: high
    reason: ""
    fix: ""
minor_issues:
  - issue: ""
    severity: medium
    reason: ""
    fix: ""
keep:
  - ""
revise_priority:
  - ""
final_decision: revise
```

---

## 21. 读者反馈系统

### 21.1 反馈来源

反馈包括：

1. 章节评论；
2. 追读数据；
3. 收藏数据；
4. 打赏数据；
5. 读者吐槽；
6. 读者催更；
7. 弃书点；
8. 爽点反馈；
9. 毒点反馈；
10. 角色人气反馈。

### 21.2 反馈分类

| 类型 | 说明 | 用途 |
|---|---|---|
| 爽点有效 | 读者明确喜欢某个桥段 | 后续强化 |
| 毒点明显 | 读者集中反感 | 优先修复 |
| 节奏问题 | 读者觉得拖 | 压缩剧情 |
| 角色人气 | 某角色被喜欢或讨厌 | 调整戏份 |
| 设定疑问 | 世界观不清楚 | 补充规则 |
| 期待方向 | 读者想看某类情节 | 进入候选池 |
| 误读 | 读者理解偏差 | 检查表达 |
| 噪声 | 无明确价值的情绪输出 | 降权处理 |

### 21.3 反馈处理原则

读者反馈不能直接决定剧情。

正确流程：

```text
评论导入
  │
  ▼
分类
  │
  ▼
聚合
  │
  ▼
判断是否高频
  │
  ▼
判断是否符合主线
  │
  ▼
生成修改建议
  │
  ▼
主编决策
  │
  ▼
进入后续细纲
```

---

## 22. 向量数据库与结构化数据库

### 22.1 向量库作用

向量库用于检索，不是唯一事实源。

适合存储：

1. 小说拆解片段；
2. 专业书籍概念；
3. 多学科知识卡；
4. 爽点案例；
5. 毒点案例；
6. 章节钩子；
7. 人物机制；
8. 读者评论片段。

### 22.2 结构化库作用

结构化库用于精确查询。

适合存储：

1. 作品元数据；
2. 章节信息；
3. 标签；
4. 评分；
5. 读者反馈统计；
6. 审稿结果；
7. 任务状态；
8. 版本信息。

### 22.3 推荐存储策略

```text
Markdown / JSON / YAML：人类可读的主资产
SQLite / MySQL：结构化查询
向量数据库：语义检索
Git：版本管理
```

---

## 23. v4 生产流程

### 23.1 完整流程

```text
阶段 0：项目立项
阶段 1：素材导入
阶段 2：热门小说拆解
阶段 3：专业知识提炼
阶段 4：题材生成
阶段 5：题材评估
阶段 6：世界观设计
阶段 7：人物系统设计
阶段 8：总纲设计
阶段 9：卷纲设计
阶段 10：前 30 章细纲
阶段 11：正文初稿
阶段 12：审稿
阶段 13：修改
阶段 14：发布
阶段 15：读者反馈导入
阶段 16：后续细纲迭代
```

### 23.2 阶段职责表

| 阶段 | 主模型 | 辅助模型 | 输出 |
|---|---|---|---|
| 素材导入 | Claude Code | Codex | 清洗文件、元数据 |
| 热门小说拆解 | DeepSeek | ChatGPT / Codex | 拆解报告 |
| 专业知识提炼 | DeepSeek | ChatGPT | 知识卡 |
| 题材生成 | ChatGPT | DeepSeek | 题材卡 |
| 题材评估 | ChatGPT | Codex | 题材评分 |
| 世界观设计 | ChatGPT | DeepSeek | 世界观文档 |
| 人物设计 | ChatGPT | DeepSeek | 人物卡 |
| 大纲设计 | ChatGPT | Codex | 总纲 / 卷纲 |
| 细纲设计 | ChatGPT | DeepSeek | 章节细纲 |
| 正文初稿 | DeepSeek | Claude Code | draft_v1 |
| 结构检查 | Codex | ChatGPT | 结构问题 |
| 高级审稿 | ChatGPT | Claude Code | 审稿报告 |
| 修改 | DeepSeek | ChatGPT | revised_v1 |
| 发布准备 | Claude Code | Codex | final_v1 |
| 反馈分析 | DeepSeek | ChatGPT | 反馈报告 |
| 后续迭代 | Claude Code | ChatGPT | 新细纲 |

---

## 24. 质量门禁

### 24.1 QG-0 原创性门禁

必须检查：

1. 是否直接复用热门小说核心设定；
2. 是否直接复用人物关系；
3. 是否直接复用桥段；
4. 是否出现高相似章节结构；
5. 是否只做了换名仿写。

未通过则不得进入正文阶段。

### 24.2 QG-1 题材门禁

必须回答：

1. 一句话卖点是否清晰；
2. 主角是否有强欲望；
3. 读者为什么要看；
4. 前 30 章是否能持续制造期待；
5. 题材是否有差异化；
6. 是否有长篇扩展空间。

### 24.3 QG-2 世界观门禁

必须回答：

1. 力量体系是否自洽；
2. 资源体系是否清楚；
3. 阶层结构是否能制造冲突；
4. 主角破局是否合理；
5. 强者限制是否合理；
6. 后续升级空间是否存在。

### 24.4 QG-3 人物门禁

必须回答：

1. 主角欲望是否明确；
2. 主角缺陷是否存在；
3. 主角成长是否需要代价；
4. 反派是否有资源优势；
5. 配角是否有功能；
6. 人物关系是否能持续制造冲突。

### 24.5 QG-4 细纲门禁

每章必须有：

1. 目标；
2. 冲突；
3. 信息增量；
4. 情绪变化；
5. 爽点或压迫；
6. 伏笔或悬念；
7. 结尾钩子。

### 24.6 QG-5 正文门禁

正文必须检查：

1. 是否符合细纲；
2. 是否拖沓；
3. 是否有画面感；
4. 是否有人物行动；
5. 是否有冲突推进；
6. 是否有章节钩子；
7. 是否存在设定解释过多；
8. 是否有毒点；
9. 是否有逻辑漏洞；
10. 是否可发布。

---

## 25. 标准任务包模板

所有复杂任务必须使用任务包。

```markdown
# Task Packet

## 任务 ID

task_yyyyMMdd_001

## 任务目标

明确本次任务要完成什么。

## 任务类型

- 素材
- 拆解
- 题材
- 世界观
- 人物
- 大纲
- 细纲
- 正文
- 审稿
- 反馈
- 训练题
- 模板
- 工程

## 输入文件

- `path/to/input.md`

## 输出文件

- `path/to/output.md`

## 使用模型

- Claude Code:
- Codex:
- ChatGPT:
- DeepSeek:

## 上下文范围

只允许读取以下文件：

- `...`

## 约束

1. 不得照抄。
2. 必须结构化输出。
3. 必须符合对应模板。
4. 必须写入指定目录。

## 验收标准

1. 文件存在。
2. 格式正确。
3. 通过 Schema 校验。
4. 通过质量门禁。
5. 更新 PROJECT_STATE.md。

## 禁止事项

1. 禁止新增未记录设定。
2. 禁止跳过审稿。
3. 禁止只在聊天中返回结果。
```

---

## 26. 核心提示词模板

### 26.1 热门小说拆解提示词

```markdown
你是 novel-forge 的小说结构拆解模型。

任务：拆解输入小说，但不得鼓励照抄。

请输出以下内容：

1. 题材定位；
2. 开局钩子；
3. 主角欲望；
4. 初始压迫；
5. 金手指机制；
6. 升级节奏；
7. 反派压力；
8. 爽点分布；
9. 情绪曲线；
10. 章节钩子；
11. 毒点；
12. 可抽象复用的结构；
13. 禁止模仿的具体元素；
14. 商业化逻辑；
15. 对原创项目的启发。

要求：

- 不复述大段原文；
- 不输出可直接仿写的桥段；
- 只提炼抽象机制；
- 输出结构化 Markdown 或 JSON。
```

### 26.2 多学科知识提炼提示词

```markdown
你是 novel-forge 的多学科知识提炼模型。

任务：将输入内容转化为小说可用的知识卡。

请提取：

1. 核心概念；
2. 因果机制；
3. 人性机制；
4. 权力机制；
5. 资源机制；
6. 冲突模型；
7. 可故事化场景；
8. 可转化为世界观的规则；
9. 可转化为人物动机的机制；
10. 可转化为悬疑线索的逻辑；
11. 东方玄幻用法；
12. 西幻悬疑用法；
13. 禁止写成说明文的提醒。

要求：

- 知识必须转化为剧情功能；
- 不要写读书笔记；
- 不要堆概念；
- 每条知识必须说明如何进入小说。
```

### 26.3 正文生成提示词

```markdown
你是 novel-forge 的小说正文初稿模型。

任务：根据章节细纲生成正文初稿。

输入包括：

1. 世界观规则；
2. 人物卡；
3. 前文摘要；
4. 本章细纲；
5. 章节目标；
6. 爽点要求；
7. 结尾钩子；
8. 禁止事项。

要求：

- 严格遵守细纲；
- 不新增重大设定；
- 不跳过冲突；
- 不写成设定说明；
- 每个场景必须有人物行动；
- 每章必须有情绪变化；
- 结尾必须有钩子；
- 输出 draft_v1。
```

### 26.4 高级审稿提示词

```markdown
你是 novel-forge 的高级审稿模型。

任务：审查输入章节是否具备商业连载价值。

请检查：

1. 是否符合细纲；
2. 是否有明确章节目标；
3. 是否有冲突；
4. 是否有信息增量；
5. 是否有爽点；
6. 是否有毒点；
7. 人物行为是否合理；
8. 世界观是否自洽；
9. 多学科知识是否自然进入剧情；
10. 是否拖沓；
11. 结尾钩子是否有效；
12. 是否存在照抄风险。

输出：

1. 总评分；
2. 核心问题；
3. 高优先级修改；
4. 中优先级修改；
5. 可保留部分；
6. 修改后方向；
7. 是否允许进入 revised_v1。
```

---

## 27. 训练题系统

### 27.1 训练目标

训练题用于提升作者能力，不直接进入正式正文。

训练范围：

1. 热门小说拆解训练；
2. 章节钩子训练；
3. 爽点设计训练；
4. 人物动机训练；
5. 世界观规则训练；
6. 悬疑线索训练；
7. 多学科知识转剧情训练；
8. 中考 / 作文结构训练；
9. 阅读理解训练；
10. 语言表达训练。

### 27.2 作文 / 阅读训练输出标准

作文或阅读训练必须包含：

1. 题目理解；
2. 立意；
3. 结构；
4. 论证；
5. 语言表达；
6. 可模仿模板；
7. 思维能力训练点。

---

## 28. 版本管理规则

### 28.1 分支建议

```text
main                稳定版本
dev                 当前开发版本
factory-v4          v4 生产系统开发
story/{project}     单本小说项目
review/{project}    审稿分支
experiment/{name}   实验分支
```

### 28.2 Commit 规范

```text
docs: update v4 final architecture
schema: add chapter plan schema
prompt: add deepseek chapter draft prompt
factory: add topic card for xxx
world: update cultivation system
character: revise protagonist arc
outline: add volume 01 outline
chapter: draft chapter 001
review: add chapter 001 review report
feedback: import reader comments
fix: repair schema validation issue
```

### 28.3 状态文件规则

`PROJECT_STATE.md` 必须记录：

1. 当前阶段；
2. 当前小说项目；
3. 已完成内容；
4. 待完成内容；
5. 当前风险；
6. 下一步任务；
7. 最近一次质量门禁结果。

`CURRENT_GOAL.md` 必须记录：

1. 当前唯一目标；
2. 输入文件；
3. 输出文件；
4. 允许调用的模型；
5. 验收标准；
6. 完成后动作。

---

## 29. v4 最小可运行闭环

v4 必须至少实现以下闭环：

```text
导入 5-10 本同类型热门小说
        │
        ▼
批量拆解结构、节奏、爽点、毒点
        │
        ▼
导入 3-5 本专业书籍或知识材料
        │
        ▼
生成多学科知识卡
        │
        ▼
生成 10 个题材卡
        │
        ▼
筛选 1 个主项目
        │
        ▼
生成世界观
        │
        ▼
生成人物系统
        │
        ▼
生成总纲和第一卷卷纲
        │
        ▼
生成前 30 章细纲
        │
        ▼
生成前 3 章正文初稿
        │
        ▼
完成审稿和修改
        │
        ▼
形成可发布样章
```

---

## 30. v4 Definition of Done

v4 完成标准如下。

### 30.1 工程完成

1. 仓库目录完整；
2. `CLAUDE.md` 完成；
3. `PROJECT_STATE.md` 完成；
4. `CURRENT_GOAL.md` 完成；
5. 核心模板完成；
6. 核心 Schema 完成；
7. 基础 pipeline 可运行；
8. 至少支持素材导入、拆解、生成、审稿、反馈五个环节。

### 30.2 内容完成

1. 至少完成一个主类型方向；
2. 至少完成一个题材库；
3. 至少完成一个世界观；
4. 至少完成一组核心人物；
5. 至少完成一份总纲；
6. 至少完成一份卷纲；
7. 至少完成前 30 章细纲；
8. 至少完成前 3 章正文；
9. 至少完成审稿报告；
10. 至少形成修改后版本。

### 30.3 质量完成

1. 不存在明显照抄风险；
2. 题材卖点清晰；
3. 世界观规则自洽；
4. 人物动机成立；
5. 前 30 章有持续推进；
6. 前 3 章有开局钩子；
7. 章节结尾有追读动力；
8. 审稿报告指出的问题已处理；
9. 读者反馈系统可接入；
10. 后续章节可继续生产。

---

## 31. v4 后续扩展方向

v4 之后可以进入 v5，但 v5 不应推翻 v4。

v5 重点方向：

1. 自动化批量拆书；
2. 自动化评论分析；
3. 多项目并行；
4. 类型小说模板库；
5. 商业化评分模型；
6. 章节追读预测；
7. 角色人气预测；
8. 悬疑逻辑校验器；
9. 世界观一致性校验器；
10. 原创性相似度检测；
11. 发布平台适配；
12. IP 资产管理。

---

## 32. 最终工作方式

从 v4 开始，所有小说项目必须按以下方式推进：

```text
先建资产，再写正文。
先做拆解，再做原创。
先有规则，再有剧情。
先有细纲，再有章节。
先有审稿，再有发布。
先有反馈，再有迭代。
```

Claude Code 负责让系统持续运转。

Codex 负责让结构可靠。

DeepSeek 负责让产量充足。

ChatGPT 负责让质量过关。

作者负责最终判断、方向选择和价值取舍。

`novel-forge v4` 的核心不是“让 AI 写小说”，而是建立一个可以持续生产原创小说资产的工业化创作系统。
