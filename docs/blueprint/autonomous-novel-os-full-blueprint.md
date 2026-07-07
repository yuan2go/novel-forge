# Autonomous Novel OS 完整功能蓝图

## 0. 系统最终定位

**Novel OS** 不是普通 AI 写作工具，也不是单纯小说生成器，而是：

> 一个根据创作目标自动发现素材、自动构建知识资产、自动孵化创意、自动规划长篇、自动生成正文、自动审稿修订、自动维护长篇稳定性、自动分析反馈，并在关键风险节点请求人工审批的 **精品网络小说生产操作系统**。

最终目标不是“生成很多字”，而是：

```text
稳定产出：
- 可读；
- 有追读感；
- 有爽点兑现；
- 有主角魅力；
- 有反派压力；
- 有题材新意；
- 有哲学/主题内涵；
- 长篇不崩；
- 多本并行可控；
- 可持续复盘优化的精品长篇网络小说。
```

---

# 1. 总体设计原则

## 1.1 不全部 OS 化

最终架构采用三层：

```text
核心 OS 层
+ 创作 Engine 层
+ Module / Tool 层
```

不是所有模块都做成独立 OS。

### 必须 OS 化

这些能力影响长期稳定、无人化、知识安全和多本并行，必须系统化：

```text
1. Agent OS
2. Source / Material Governance OS
3. MKAOS
4. Context Builder OS
5. Story Bible / Long-form OS
6. Quality / Review / Eval OS
7. Ops / Trace / Cost OS
8. Portfolio OS
9. Security / Sandbox OS
```

### 应该 Engine 化

这些是强创作能力，但不需要全部独立 OS 化：

```text
1. Creative Engine
2. Meaning / Philosophy Engine
3. Worldbuilding Engine
4. Character Engine
5. Outline Engine
6. Chapter Blueprint Engine
7. Readable Prose Engine
8. Revision Engine
9. Ending / Closure Engine
10. Feedback Analysis Engine
11. Publishing Adapter Engine
12. Reader Simulation Engine
13. Style Identity Engine
14. Originality Risk Engine
15. Serialization Engine
```

### 保持 Module / Tool 化

这些保持轻量即可：

```text
Git Connector
News / RSS Connector
Public Domain Importer
Open Data Connector
PDF / EPUB Parser
Title Generator
Synopsis Generator
Cover Prompt Generator
Chapter Title Generator
Exporter
Tag Manager
Manual Input
```

---

# 2. 总体架构图

```text
Autonomous Novel OS
│
├── Core OS Layer 核心操作系统层
│   ├── Agent OS 自治调度系统
│   ├── Source / Material Governance OS 来源与素材治理系统
│   ├── MKAOS 多学科知识资产操作系统
│   ├── Context Builder OS 上下文构建系统
│   ├── Story Bible / Long-form OS 设定与长篇稳定系统
│   ├── Quality / Review / Eval OS 质量审稿评测系统
│   ├── Ops / Trace / Cost OS 运维追踪成本系统
│   ├── Portfolio OS 多书项目组合系统
│   └── Security / Sandbox OS 安全与沙箱系统
│
├── Engine Layer 创作引擎层
│   ├── Creative Engine 创意引擎
│   ├── Meaning / Philosophy Engine 哲学与内涵引擎
│   ├── Worldbuilding Engine 世界观引擎
│   ├── Character Engine 人物引擎
│   ├── Outline Engine 大纲引擎
│   ├── Chapter Blueprint Engine 细纲引擎
│   ├── Readable Prose Engine 可读正文引擎
│   ├── Revision Engine 修订引擎
│   ├── Ending / Closure Engine 完结收束引擎
│   ├── Feedback Analysis Engine 反馈分析引擎
│   ├── Publishing Adapter Engine 发布适配引擎
│   ├── Reader Simulation Engine 读者模拟引擎
│   ├── Style Identity Engine 风格身份引擎
│   ├── Originality Risk Engine 原创性风险引擎
│   └── Serialization Engine 连载运营引擎
│
├── Web Novel Enhancement Layer 精品网文增强层
│   ├── Golden Opening Lab 黄金开篇实验室
│   ├── Reader Promise Ledger 读者承诺账本
│   ├── Pleasure Point Ledger 爽点账本
│   ├── Toxic Point & Drop-off Engine 毒点弃读系统
│   ├── Protagonist Charm Engine 主角魅力引擎
│   ├── Antagonist Pressure Engine 反派压迫引擎
│   ├── Chapter Economy Engine 章节商业功能系统
│   ├── Retention & Payoff Engine 追读与兑现系统
│   ├── Mobile Reading Experience Engine 移动端阅读体验系统
│   ├── Volume Arc Engine 卷级弧线系统
│   ├── Trope Fatigue Detector 套路疲劳检测器
│   └── Book Lifecycle Strategy 书籍生命周期策略
│
└── Module / Tool Layer 工具层
    ├── Git Connector
    ├── News / RSS Connector
    ├── Public Domain Importer
    ├── Open Data Connector
    ├── PDF / EPUB Parser
    ├── Title Generator
    ├── Synopsis Generator
    ├── Cover Prompt Generator
    ├── Chapter Title Optimizer
    └── Exporter
```

---

# 3. 核心 OS 层

---

## 3.1 Agent OS：自治调度系统

### 定位

Agent OS 是整个系统的任务调度中心。

它负责：

```text
任务规划
任务拆解
Agent 选择
Skill 选择
上下文请求
模型调用
自动执行
失败重试
审批路由
成本控制
周期任务
执行追踪
```

### 核心 Agent

```text
Source Discovery Agent        来源发现 Agent
Git Ingestion Agent           Git 采集 Agent
News Watch Agent              新闻监控 Agent
License Risk Agent            许可风险 Agent
Material Curator Agent        素材整理 Agent
MKAOS Converter Agent         知识资产转化 Agent
Creative Strategist Agent     创意策略 Agent
Meaning Agent                 哲学内涵 Agent
Worldbuilding Agent           世界观 Agent
Character Agent               人物 Agent
Outline Agent                 大纲 Agent
Blueprint Agent               细纲 Agent
Prose Agent                   正文 Agent
Readability Editor Agent      可读性编辑 Agent
Review Agent                  审稿 Agent
Revision Agent                修订 Agent
Long Review Agent             长篇复盘 Agent
Ending Agent                  完结收束 Agent
Feedback Agent                反馈分析 Agent
Eval Agent                    评测 Agent
Ops Agent                     运维 Agent
Editor-in-Chief Agent         总编 Agent
```

### 自动化等级

```text
A0：手动
A1：系统建议，人工执行
A2：低风险自动，高风险审批
A3：自动推进，重大决策审批
A4：无人值守，异常审批
A5：全自治，不建议初期使用
```

当前推荐目标：

```text
短期：A2—A3
中期：A3
长期：A4
暂不追求：A5
```

---

## 3.2 Source / Material Governance OS：来源与素材治理系统

### 定位

解决系统从哪里获取素材和知识，以及是否安全可用。

### 来源类型

```text
Git 仓库
新闻媒体
RSS
公版书库
开放数据
专业资料
学术资料
平台公告
榜单
社区热点
用户自有资料
系统自产内容
```

### 核心能力

```text
Source Discovery
Git Clone / Pull
News / RSS Watch
License Scanner
Copyright Risk Classifier
Privacy Filter
Source Trust Scorer
Robots / ToS Checker
Source Registry
Material Inbox
Material Card Generator
Narrative Function Annotator
Material Usage Tracker
```

### SourceCard

```yaml
source_id:
source_name:
source_type:
source_url:
license:
copyright_status:
crawl_allowed:
commercial_use_allowed:
generation_context_allowed:
attribution_required:
risk_level:
trust_score:
sync_frequency:
last_checked_at:
allowed_usage:
  - raw_store
  - summary_only
  - structure_only
  - review_only
  - eval_only
  - generation_allowed
```

### 风险分级

```text
R0：自有资料，可全量使用
R1：明确开放许可 / 公版，可使用，保留来源
R2：许可不清，只摘要，不进入生成上下文
R3：版权风险高，只能 structure_only / reference_only
R4：盗版 / 侵权 / 高隐私风险，禁止入库
```

### MaterialCard

```yaml
material_id:
title:
one_line_summary:
source_id:
license:
risk_level:
raw_allowed:
generation_allowed:
material_type:
  - plot
  - character
  - scene
  - conflict
  - suspense
  - pleasure_point
  - worldbuilding
  - profession
  - history
  - folklore
  - language
  - negative_case
tags:
entities:
genre_fit:
platform_fit:
narrative_function:
emotional_function:
conflict_type:
hook_type:
possible_usage:
do_not_use:
quality_score:
converted_assets:
usage_history:
```

---

## 3.3 MKAOS：多学科知识资产操作系统

### 定位

MKAOS 是 Novel OS 的知识中枢。

它不是普通 RAG，而是：

```text
知识资产库
+ 创作原则库
+ 模板库
+ 审稿规则库
+ Eval Case 生成器
+ 知识调用路由器
+ 证据链系统
```

### 输入来源

```text
素材卡
网文拆解
经典小说拆解
专业知识
哲学资料
历史资料
神话资料
心理学资料
社会学资料
平台规则
读者反馈
系统审稿报告
AI 味负例
成功章节案例
```

### 输出资产

```text
创作原则
题材模板
人物模板
世界观模板
冲突模型
爽点模型
悬疑模型
章节钩子模板
正文可读性规则
AI 味负例规则
审稿规则
Eval 测试案例
平台适配规则
反说教规则
原创性风险规则
```

### 核心原则

```text
1. evidence-only：关键资产必须有来源。
2. source isolation：拆解资产不能污染正文生成。
3. structure-only：热门作品只抽象结构，不能复刻剧情。
4. task-specific：按任务返回最小知识包。
5. stage-aware：不同阶段调用不同知识。
6. risk-aware：来源风险影响是否可进入上下文。
7. usage-feedback：知识资产根据使用效果评分和淘汰。
```

### KnowledgeAsset

```yaml
asset_id:
asset_type:
title:
summary:
source_refs:
source_type:
applicable_stages:
  - genre
  - worldbuilding
  - character
  - outline
  - blueprint
  - prose
  - review
  - revision
  - eval
applicable_genres:
narrative_function:
usage_rule:
anti_pattern:
review_rule:
risk:
  copyright:
  hallucination:
  source_pollution:
quality_score:
usage_success_rate:
last_used_at:
```

---

## 3.4 Context Builder OS：上下文构建系统

### 定位

决定每次 Agent 执行时看什么、不能看什么。

### 目标

防止：

```text
token 爆炸
知识污染
参考作品泄露
旧设定覆盖新设定
人物状态错乱
伏笔遗漏
外部资料过量进入正文
```

### 工作流程

```text
Agent 提交任务
→ Context Builder 判断阶段和任务
→ 请求 MKAOS
→ 请求 Canon / 人物 / 时间线 / 伏笔
→ 请求必要素材
→ 压缩上下文
→ 生成 Context Package
→ Agent 执行
```

### ContextPackage

```yaml
context_package_id:
task_id:
project_id:
stage:
selected_canon:
selected_character_states:
selected_timeline:
selected_foreshadows:
selected_world_rules:
selected_materials:
selected_knowledge_assets:
style_rules:
review_rules:
forbidden_content:
token_budget:
source_refs:
selection_reason:
```

### 阶段知识预算

| 阶段   | 知识调用量 | 原则              |
| ---- | ----: | --------------- |
| 题材   |     高 | 广泛探索            |
| 创意   |     高 | 跨学科组合           |
| 世界观  |    中高 | 专业知识和规则         |
| 人物   |     中 | 心理、哲学、人设机制      |
| 大纲   |     中 | 结构、商业逻辑、主题      |
| 细纲   |    中低 | Canon、人物状态、伏笔优先 |
| 正文   |     低 | 只给必要信息，避免污染     |
| 审稿   |     高 | 调用大量规则          |
| 修订   |    中低 | 只调用对应修订规则       |
| 复盘   |     高 | 调用全局记忆          |
| Eval |     高 | 调用测试集和标准        |

---

## 3.5 Story Bible / Long-form OS：设定与长篇稳定系统

### 定位

支撑长篇不崩。

管理：

```text
World Bible
Canon
Character State
Character Arc
Timeline
Foreshadow
Promise Ledger
Pleasure Point Ledger
Conflict Ledger
Power Scale
Faction State
Location State
Reader Promise
Book Lifecycle
Volume Arc
```

### 核心资产

```text
WorldBible
WorldRule
PowerRule
FactionProfile
ResourceRule
LocationProfile

CharacterProfile
CharacterState
CharacterArc
RelationshipEdge
VoiceProfile

CanonFact
TimelineEvent
ForeshadowItem
PromiseItem
ReaderPromise
PleasurePoint
ConflictItem
EventLog
VolumeArc
BookLifecycleState
```

### 自动复盘频率

```text
每 5 章：轻量复盘
每 10 章：正式复盘
每卷结束：卷级复盘
重大反转前：专项复盘
完结前：总复盘
```

### 自动告警

```text
人物动机漂移
伏笔长期未回收
反派压力下降
主线目标模糊
章节质量连续下降
爽点同质化
世界观规则冲突
战力膨胀
读者承诺未兑现
主题推进漂移
主角魅力下降
套路疲劳上升
```

---

## 3.6 Quality / Review / Eval OS：质量审稿评测系统

### 定位

判断作品是否合格，是否值得继续生产，系统是否退化。

### ReviewIssue

```yaml
issue_id:
issue_type:
severity:
location:
evidence_span:
problem_description:
why_it_matters:
fix_suggestion:
blocking:
related_canon:
related_character:
related_rule:
confidence:
```

### 审稿维度

```text
剧情逻辑
人物一致性
世界观一致性
节奏
爽点
悬念
AI 味
水文
正文可读性
追读感
原创性风险
平台合规
哲学主题
反说教
长篇稳定性
主角魅力
反派压力
毒点弃读
移动端阅读体验
章节商业功能
```

### Eval 类型

```text
模块 Eval
流程 Eval
回归 Eval
模型对比 Eval
Prompt 对比 Eval
Agent 对比 Eval
正文可读性 Eval
长篇稳定性 Eval
审稿准确性 Eval
创意退化 Eval
毒点识别 Eval
开篇吸引力 Eval
```

---

## 3.7 Ops / Trace / Cost OS：运维追踪成本系统

### 定位

保证无人化系统可控、可查、可回滚。

### OS Envelope

```yaml
task_id:
project_id:
module:
agent:
model:
prompt_version:
context_package_id:
source_refs:
input:
output:
evidence:
issues:
metrics:
cost:
trace:
decision:
next_action:
approval_status:
```

### 核心能力

```text
Trace Log
Run History
Cost Log
Token Budget
Source Audit
Knowledge Usage Audit
Quality Trend
Failure Recovery
Rollback
Alert Center
Autonomy Report
Approval History
```

> 多模型策略系统可以后置。当前只使用 Codex 时，只需要基础成本、调用日志和任务追踪，不必提前做复杂模型路由。

---

## 3.8 Portfolio OS：多书项目组合系统

### 定位

解决多本小说并行生产。

### 核心问题

```text
同时写哪几本？
哪本优先？
哪本暂停？
哪本砍掉？
哪些题材重复？
哪些人物同质化？
哪些书共享素材？
哪些书必须隔离？
哪些书有精品潜力？
```

### 功能

```text
Book Portfolio Dashboard
Project Priority Scorer
Book Potential Scorer
Resource Allocation Planner
Cross-Book Asset Reuse
Cross-Book Contamination Guard
Book Kill / Pause Gate
Series / Universe Manager
Author Brand Strategy
```

### 关键指标

```text
题材潜力
开篇潜力
长篇容量
读者承诺强度
主角魅力
反派压力
正文质量趋势
连载健康度
素材支撑度
MKAOS 支撑度
原创性风险
与其他项目同质化程度
```

---

## 3.9 Security / Sandbox OS：安全与沙箱系统

### 定位

无人化拉取外部内容时必须有安全边界。

### 功能

```text
Connector Permission Manager
Sandbox Execution
Repository Allowlist / Blocklist
Network Access Policy
File Write Policy
Secret Manager
Audit Log
Prompt Injection Guard
Untrusted Content Filter
Malicious Source Detector
```

### 防护对象

```text
恶意 Git 仓库
提示注入
伪造许可
错误知识污染
隐藏广告
恶意链接
盗版文本
隐私信息
污染性 Prompt
```

---

# 4. Engine 层

---

## 4.1 Creative Engine：创意引擎

### 目标

防止系统稳定但平庸。

### 功能

```text
Concept Incubator
Genre Mutation Lab
Element Recombiner
Anti-Cliche Generator
Novelty Gate
Character Innovation Lab
World Rule Innovation Lab
Conflict Innovation Lab
Plot Experiment Lab
Pleasure Innovation Lab
```

### ConceptCandidate

```yaml
concept_id:
title:
genre:
platform:
core_hook:
reader_promise:
freshness_score:
commercial_score:
long_form_score:
material_support_score:
risk_score:
main_character_seed:
world_rule_seed:
conflict_seed:
pleasure_point_seed:
theme_seed:
recommended_next_step:
```

### 评分

```text
新鲜度
类型爽感
主角吸引力
世界观容量
长篇扩展性
平台适配性
写作可持续性
素材支撑度
原创性风险
```

---

## 4.2 Meaning / Philosophy Engine：哲学与内涵引擎

### 目标

让小说有深层主题，而不是机械爽点堆叠。

### 核心原则

哲学不能直接塞进正文，而要转化为：

```text
人物选择
价值冲突
世界规则
剧情代价
反派理念
主题弧光
对话潜台词
```

### 功能

```text
Philosophical Asset Builder
Theme Engine
Value Conflict Designer
Character Belief System
Worldview Embedding Engine
Plot Embodiment Engine
Dialogue Subtext Engine
Anti-Preaching Gate
Theme Coherence Review
Meaning Arc Tracker
```

### ThemeAsset

```yaml
theme_id:
core_question:
theme_statement:
counter_theme:
protagonist_initial_answer:
antagonist_answer:
world_answer:
final_answer:
value_conflicts:
plot_embodiment:
character_tests:
anti_preaching_rules:
applicable_genres:
source_refs:
```

---

## 4.3 Worldbuilding Engine：世界观引擎

### 功能

```text
世界基础设定
势力系统
能力 / 战力体系
资源体系
社会结构
历史年表
地图 / 地理
法则 / 禁忌
组织关系
世界观一致性检查
世界观变更审批
```

### 门禁

```text
新增设定必须不冲突 Canon
新增能力必须落入 Power Scale
新增势力必须有资源、目标、边界
新增地点必须进入 Location Map
重大世界规则变更必须审批
```

---

## 4.4 Character Engine：人物引擎

### 功能

```text
人物卡生成
欲望
恐惧
缺陷
秘密
信念
成长线
关系图
口吻
行为逻辑
阶段状态
人物一致性检查
人物魅力评分
人物同质化检查
```

### CharacterProfile

```yaml
character_id:
name:
role:
desire:
fear:
flaw:
secret:
false_belief:
core_belief:
moral_boundary:
value_priority:
voice_profile:
behavior_rules:
relationship_edges:
arc_stage:
current_state:
forbidden_actions:
reader_charm_points:
```

---

## 4.5 Outline Engine：大纲引擎

### 功能

```text
一句话故事
核心卖点
读者承诺
主线问题
终局设计
卷结构
阶段目标
反派推进
冲突阶梯
爽点分布
主题推进线
伏笔计划
高潮地图
大纲风险分析
大纲重构
```

### 门禁

```text
主线问题清晰
长篇容量足够
每卷有目标、冲突、高潮、钩子
反派压力递进
爽点不断档
主题推进不说教
伏笔有回收计划
结局回应核心主题
```

---

## 4.6 Chapter Blueprint Engine：细纲引擎

### 功能

```text
章节目标
场景拆分
冲突设计
信息释放
爽点设计
悬念设计
开头钩子
结尾钩子
章节商业功能
主题功能标注
人物状态更新计划
Canon 更新计划
细纲质量检查
细纲重构
```

### ChapterBlueprint

```yaml
chapter_id:
chapter_goal:
chapter_function:
commercial_goal:
reader_question:
opening_hook:
main_conflict:
scene_beats:
info_release:
pleasure_point:
suspense_point:
theme_function:
character_actions:
canon_refs:
foreshadow_refs:
reader_promise_refs:
ending_hook:
forbidden_reveals:
quality_targets:
```

---

## 4.7 Readable Prose Engine：可读正文引擎

### 目标

不是“去 AI 味”，而是让读者愿意继续读。

### 功能

```text
章节初稿生成
场景构建
对话生成
文风控制
节奏控制
开头强化
结尾强化
AI 味检测
文本活性检测
追读感门禁
场景沉浸检测
对话自然度检测
说明书检测
水文检测
移动端阅读体验检查
可读化改写
正文版本管理
```

### 可读性评分

```text
开头吸引力       10
场景沉浸感       10
冲突强度         15
段落推进感       10
人物真实感       10
对话张力         10
情绪曲线         10
信息释放         10
语言活性         10
结尾钩子         15
```

### 自动阻断条件

```text
开头 300 字无事件 / 异常 / 压力 → 自动重写
连续 5 段无推进 → 压缩或重写
AI 味过高 → 去总结腔
水文比例过高 → 重写
结尾钩子弱 → 重写结尾
人物口吻错乱 → 调用 Character Engine 修复
世界观冲突 → 阻断
可读性低于 70 → 自动修订
可读性低于 60 → 退回细纲
```

---

## 4.8 Revision Engine：修订引擎

### 修订策略

| 问题类型 | 修订策略            |
| ---- | --------------- |
| 开头慢  | 重写前 300—800 字   |
| 冲突弱  | 增加阻碍、代价、失败风险    |
| 人物假  | 增加动作、选择、潜台词     |
| 说明书  | 拆成事件、对话、线索      |
| AI 味 | 去总结腔、去抽象词、加具体动作 |
| 结尾弱  | 增加未解决问题或局势反转    |
| 设定冲突 | 回查 Canon，重写冲突段  |
| 主题说教 | 改为人物选择和代价呈现     |
| 爽点弱  | 增强铺垫、释放和反应      |
| 毒点高  | 重构人物行为和冲突逻辑     |

---

## 4.9 Ending / Closure Engine：完结收束引擎

### 目标

防止长篇烂尾、无限扩张、伏笔不收。

### 功能

```text
Ending Designer
Arc Closure Planner
Foreshadow Payoff Planner
Promise Fulfillment Checker
Final Conflict Designer
Character Arc Closure
Theme Resolution Checker
Anti-Rushed Ending Gate
Anti-Endless Expansion Gate
```

### 完结门禁

```text
主线问题是否解决
核心反派是否完成对抗
主角人物弧光是否闭合
主要伏笔是否回收
读者承诺是否兑现
主题问题是否回应
世界观核心规则是否完成展示
重要配角是否有归宿
结局情绪是否足够
是否强行收尾
是否无限开新坑
```

---

## 4.10 Feedback Analysis Engine：反馈分析引擎

### 功能

```text
评论导入
段评导入
平台数据导入
反馈聚类
弃读点分析
读者痛点分析
受欢迎元素分析
毒点检测
爽点验证
反馈转修订任务
反馈转大纲调整
趋势报告
```

---

## 4.11 Publishing Adapter Engine：发布适配引擎

### 功能

```text
平台规则库
平台题材适配
章节长度适配
书名生成
简介生成
封面提示词
章节标题优化
发布包生成
合规门禁
低质风险门禁
导出格式适配
```

---

## 4.12 Reader Simulation Engine：读者模拟引擎

### 目标

发布前预筛弃读风险。

### 模拟读者类型

```text
爽文读者
悬疑读者
慢热读者
短故事读者
起点读者
番茄读者
女性向读者
海外读者
毒舌读者
普通泛读者
高审美读者
跳读读者
```

### 输出

```text
Reader Simulation Report
Drop-off Prediction
Reader Hook Score
Confusion Point
Boredom Point
Toxic Point
Favorite Point
```

---

## 4.13 Style Identity Engine：风格身份引擎

### 目标

防止多本书读起来都像同一本 AI 文。

### 功能

```text
Book Style Identity
Author Voice Profile
Genre Style Profile
Narrative Distance Controller
Sentence Rhythm Profile
Dialogue Voice Differentiator
Style Drift Detector
Style Reuse Guard
```

### Style Bible

```yaml
style_id:
book_id:
narrative_voice:
sentence_rhythm:
paragraph_density:
dialogue_style:
description_level:
humor_level:
darkness_level:
emotional_temperature:
taboo_phrases:
overused_patterns:
signature_moves:
```

---

## 4.14 Originality Risk Engine：原创性风险引擎

### 功能

```text
Similarity Detector
Plot Similarity Graph
Character Similarity Checker
Worldbuilding Similarity Checker
Source Influence Tracker
Reference Leakage Detector
Template Overuse Detector
```

### 检查对象

```text
题材设定是否过近
主角身份是否过近
金手指是否过近
开篇事件是否过近
章节结构是否过近
关键反转是否过近
世界观命名是否过近
人物关系是否过近
语言表达是否过近
```

---

## 4.15 Serialization Engine：连载运营引擎

### 目标

管理网络小说作为连载产品的节奏。

### 功能

```text
Update Calendar
Chapter Backlog Manager
Daily Production Planner
Release Rhythm Planner
Cliffhanger Scheduling
Arc Launch Timing
Emergency Rewrite Queue
Quality-vs-Deadline Gate
Serialization Health Report
```

---

# 5. 精品网文增强层

---

## 5.1 Golden Opening Lab：黄金开篇实验室

### 检查节点

```text
前 300 字 Gate
第 1 章 Gate
前 3 章 Gate
前 10 章 Gate
前 3 万字 Gate
```

### 检查项

```text
主角是否快速登场
主角是否有明确困境
是否有强事件
是否有读者问题
是否展示核心卖点
是否有主角魅力点
是否有第一波情绪回报
是否有下一章动力
是否避免设定说明书
是否明确告诉读者“这本书看什么”
```

---

## 5.2 Reader Promise Ledger：读者承诺账本

### 目标

追踪系统向读者许下的所有期待。

### Promise 类型

```text
复仇承诺
升级承诺
揭秘承诺
情感承诺
身份承诺
反派清算承诺
世界观扩展承诺
金手指成长承诺
伏笔回收承诺
```

### ReaderPromise

```yaml
promise_id:
promise_type:
source_chapter:
reader_expectation:
expected_payoff_window:
status:
risk:
payoff_plan:
```

---

## 5.3 Pleasure Point Ledger：爽点账本

### 记录

```text
爽点类型
爽点来源
爽点铺垫
爽点释放章节
爽点强度
爽点间隔
是否重复
是否升级
读者预期
后续回报
```

### 爽点类型

```text
身份揭露
实力碾压
反杀
打脸
复仇
升级
获得资源
获得认可
破解谜题
救人
夺权
反转
情感确认
反派破防
众人震惊
```

---

## 5.4 Toxic Point & Drop-off Engine：毒点弃读系统

### 常见毒点

```text
主角降智
主角圣母
强行误会
长期压主
反派降智
配角喧宾夺主
金手指失控
剧情拖沓
设定说明书
爽点不兑现
伏笔不回收
强行虐主
强行送资源
前后逻辑冲突
```

---

## 5.5 Protagonist Charm Engine：主角魅力引擎

### 评分维度

```text
代入感
目标清晰度
行动主动性
情绪感染力
独特记忆点
成长期待
爽点承载力
道德边界
反差感
口吻辨识度
```

---

## 5.6 Antagonist Pressure Engine：反派压迫引擎

### 管理内容

```text
反派目标
反派资源
反派行动计划
压迫方式
价值观
阶段性胜利
对主角的限制
反派升级
反派失误
反派破防
最终败因
```

---

## 5.7 Chapter Economy Engine：章节商业功能系统

### 章节功能类型

```text
Hook Chapter
Pressure Chapter
Payoff Chapter
Reveal Chapter
Twist Chapter
Upgrade Chapter
Relationship Chapter
World Expansion Chapter
Transition Chapter
Climax Chapter
Aftermath Chapter
```

---

## 5.8 Retention & Payoff Engine：追读与兑现系统

### 管理

```text
章末钩子
阶段性爽点
大谜团推进
小目标完成
新目标开启
高潮前压迫
高潮后余波
上架前节奏
付费节点情绪设计
```

---

## 5.9 Mobile Reading Experience Engine：移动端阅读体验系统

### 检查项

```text
段落是否太长
句子是否太密
对话是否清晰
动作是否连续
信息是否过载
一屏内是否有变化
是否有视觉停顿
是否有强钩子句
是否适合手机滑读
```

---

## 5.10 Volume Arc Engine：卷级弧线系统

### 每卷必须有

```text
卷主题
卷目标
卷敌人
卷地图
卷爽点
卷反转
卷高潮
卷余波
下一卷钩子
```

---

## 5.11 Trope Fatigue Detector：套路疲劳检测器

### 检测

```text
主角反击方式是否重复
反派挑衅方式是否重复
爽点是否重复
章节结构是否重复
结尾钩子是否重复
人物登场模式是否重复
地图推进是否重复
支线解决方式是否重复
```

---

## 5.12 Book Lifecycle Strategy：书籍生命周期策略

### 阶段

```text
立项期
开篇期
冷启动期
稳定连载期
上升期
中期扩展期
高潮期
疲劳期
收束期
完结期
番外期
```

### 阶段目标

| 阶段    | 核心目标      |
| ----- | --------- |
| 立项期   | 题材和卖点足够强  |
| 开篇期   | 抓人，建立读者承诺 |
| 冷启动期  | 快速展示爽点和主线 |
| 稳定连载期 | 保持追读      |
| 中期扩展期 | 扩大世界但不散   |
| 疲劳期   | 引入新变量     |
| 收束期   | 回收伏笔      |
| 完结期   | 情绪和主题闭合   |

---

# 6. MKAOS 调用矩阵

| 阶段   | 必须调用               | 可选调用       | 禁止 / 限制 |
| ---- | ------------------ | ---------- | ------- |
| 素材   | 来源规则、版权规则、分类规则     | 题材标签       | 高风险原文   |
| 拆解   | 叙事学、类型机制、反抄袭规则     | 商业逻辑       | 复刻具体剧情  |
| 题材   | 平台趋势、题材库、创意规则      | 新闻热点       | 版权正文    |
| 世界观  | 历史、神话、社会结构、哲学      | 科技/法律等专业知识 | 无来源设定   |
| 人物   | 心理学、人物机制、哲学信念      | 真实人物摘要     | 可识别真人隐私 |
| 大纲   | 叙事结构、类型模板、主题规则     | 拆解机制       | 具体作品剧情  |
| 细纲   | Canon、人物状态、伏笔、章节规则 | 少量素材       | 大量外部知识  |
| 正文   | 细纲、Canon、风格、可读性规则  | 少量领域细节     | 热门作品原文  |
| 审稿   | 质量规则、平台规则、主题规则     | 反例库        | 无       |
| 修订   | 修订策略、风格规则、Canon    | 对应模板       | 新设定污染   |
| 复盘   | Canon、时间线、伏笔、人物状态  | 质量趋势       | 无关外部素材  |
| Eval | 测试集、Rubric、失败案例    | 模型对比数据     | 无来源标准   |

---

# 7. 人工审批门禁

即使无人化，也建议保留这些审批：

```text
新小说正式立项
高版权风险素材入库
版权状态不明的资料进入生成上下文
平台发布
大规模改写前 10 章
主线重大变更
人物死亡 / 黑化等重大剧情
世界观底层规则变更
自动化策略变更
每日 / 每周成本上限变更
多本项目暂停 / 砍掉
```

---

# 8. UI 控制台蓝图

```text
自治工作台
├── 今日自治任务
├── 待审批事项
├── 异常告警
├── 成本统计
└── 质量趋势

目标与策略
├── 创作目标
├── 平台目标
├── 题材偏好
├── 禁止方向
├── 自动化等级
└── 采集策略

来源中心
├── Source Registry
├── Git 仓库
├── 新闻源
├── 公版书库
├── 开放数据
├── 平台监控
└── 来源风险

素材工厂
├── Material Inbox
├── 素材卡
├── 素材标签
├── 素材风险
├── 素材使用
└── 素材转化

MKAOS
├── 知识资产
├── 创作原则
├── 模板库
├── 审稿规则
├── Eval Case
└── Source Isolation

创意中心
├── 题材机会
├── 创意候选池
├── 新鲜度评分
├── 反套路检查
└── 立项建议

小说项目
├── 项目管理
├── 世界观
├── 人物
├── 大纲
├── 细纲
├── 正文
├── Canon
├── 伏笔
├── 时间线
├── 读者承诺
├── 爽点账本
├── 反派压力
├── 卷级弧线
└── 导出

网文增强
├── 黄金开篇
├── 毒点弃读
├── 主角魅力
├── 反派压迫
├── 章节商业功能
├── 移动端阅读体验
├── 套路疲劳
└── 连载生命周期

质量中心
├── 审稿报告
├── 可读性报告
├── AI 味报告
├── 长篇复盘
├── 审美总编
├── 原创性风险
└── 发布门禁

Portfolio
├── 多书看板
├── 项目优先级
├── 精品潜力评分
├── 资源分配
├── 跨书污染检测
└── 暂停 / 砍书建议

Agent Center
├── Agent 列表
├── 任务队列
├── 执行日志
├── 失败重试
├── 模型调用
└── 成本统计

Eval Center
├── 测试集
├── 回归测试
├── 失败案例
├── 审稿准确性
├── 正文可读性
├── 长篇稳定性
└── 质量趋势

Ops Center
├── OS Envelope
├── Trace Log
├── Source Audit
├── Knowledge Usage
├── Cost Log
├── Rollback
├── Security Audit
└── Autonomy Report
```

---

# 9. 核心数据模型

```text
Source
SourcePolicy
SourceSyncJob
SourceSnapshot
LicenseCheckResult
SourceRiskReport

RawDocument
CleanDocument
DocumentChunk
ExtractionResult
DedupRecord

MaterialCard
MaterialTag
MaterialFunction
MaterialRisk
MaterialUsage
MaterialConversion

KnowledgeAsset
CreativePrinciple
NarrativeMechanism
TemplateAsset
ReviewRule
EvalCase
SourceEvidence

ConceptCandidate
NoveltyReport
AntiTemplateReport

ThemeAsset
PhilosophicalConceptAsset
ValueConflict
MeaningArc

NovelProject
GenreProfile
PlatformProfile
ReaderProfile

WorldBible
WorldRule
PowerRule
FactionProfile
LocationProfile
ResourceRule

CharacterProfile
CharacterState
CharacterArc
RelationshipEdge
VoiceProfile

CanonFact
TimelineEvent
ForeshadowItem
PromiseItem
ReaderPromise
PleasurePoint
ConflictItem
EventLog

BookOutline
VolumeOutline
MainArc
SubArc
ThemeArc
ConflictLadder
ClimaxMap
ForeshadowPlan

ChapterBlueprint
SceneBeat
ConflictBeat
InfoReleasePoint
HookPlan
EmotionCurve

ChapterDraft
SceneDraft
DialoguePass
StyleProfile
ReadabilityReport
AntiAIReport
PageTurningReport
MobileReadingReport

ReviewReport
ReviewIssue
RevisionPlan
RevisionDraft
RevisionDiff

FeedbackItem
FeedbackCluster
ReaderSignal
PlatformMetric
DropOffReport

PortfolioProject
BookPotentialScore
ResourceAllocationPlan
CrossBookSimilarityReport

AgentTask
AgentRun
TaskPlan
TaskDependency
TaskFailure
ApprovalRequest

OSEnvelope
TraceLog
CostLog
QualityMetric
RegressionReport
FailureCase
SecurityAuditLog
```

---

# 10. 版本路线

## v1：单本小说生产闭环

目标：

```text
题材 → 世界观 → 人物 → 大纲 → 细纲 → 正文 → 审稿 → 修订 → 导出
```

必须完成：

```text
Agent OS 基础版
MKAOS Query Contract
Context Builder 基础版
Story Bible / Canon 基础版
Outline Engine
Blueprint Engine
Readable Prose Engine 基础版
Review Engine
Revision Engine
Trace 基础版
Golden Opening Lab 基础版
Toxic Point 检测基础版
```

验收：

```text
能连续生成前 10—30 章
人物不明显崩
主线不明显断
章节不是提纲式正文
审稿能指出真实问题
修订能提升质量
开篇有吸引力
正文有基本追读感
```

---

## v1.5：长篇稳定与网文追读增强

补充：

```text
Canon 完整管理
Character State
Timeline
Foreshadow Ledger
Reader Promise Ledger
Pleasure Point Ledger
Antagonist Pressure Engine
Protagonist Charm Engine
Volume Arc Engine
Long Review Agent
Quality Trend
```

验收：

```text
能支撑 100 章以内连续创作
第 80 章仍记得第 5 章重要设定
伏笔有记录、有提醒、有回收计划
爽点不长期断档
反派压力递进
主角魅力稳定
```

---

## v2：创意、内涵与风格增强

补充：

```text
Creative Engine
Novelty Gate
Anti-Template Checker
Meaning / Philosophy Engine
Theme Engine
Character Belief System
Anti-Preaching Gate
Aesthetic Editor
Style Identity Engine
Trope Fatigue Detector
```

验收：

```text
题材不是简单换皮
主角和世界观有辨识度
主题能通过冲突和选择体现
正文不说教
每本书有独立风格
长篇中期不套路疲劳
```

---

## v2.5：MKAOS 资产化成熟

补充：

```text
Asset Conversion Pipeline
Template Generator
Review Rule Generator
Eval Case Generator
Knowledge Usage Feedback
Source Isolation Regression
Originality Risk Engine
Asset Lifecycle Manager
Failure Taxonomy Manager
```

验收：

```text
拆解结果能转模板
素材能转创作机制
哲学资料能转主题冲突
读者反馈能转审稿规则
失败案例能转 Eval Case
高风险来源不会污染正文
```

---

## v3：无人化资料与生产

补充：

```text
Source Governance OS
Git Connector
News / RSS Connector
Public Domain Importer
Material Factory
Agent Scheduler 完整版
Cost Control
Approval Router
Security / Sandbox OS
Prompt Injection Guard
```

验收：

```text
系统能自动拉取合规来源
自动生成素材卡
自动转 MKAOS 资产
自动生成题材机会报告
自动推进章节生产和复盘
高风险事项自动提交审批
```

---

## v3.5：多书并行与 Portfolio

补充：

```text
Portfolio OS
Multi-Book Scheduler
Cross-Book Contamination Guard
Book Potential Scorer
Resource Allocation Planner
Book Kill / Pause Gate
Series / Universe Manager
```

验收：

```text
能同时管理多本长篇
能判断哪本优先
能防止多本书人物和文风同质化
能暂停低潜力项目
能优先投入高潜力项目
```

---

## v4：平台化、连载与反馈闭环

补充：

```text
Serialization Engine
Publishing Adapter
Feedback Analysis Engine
Reader Simulation Engine
Platform Metric Importer
Drop-off Analyzer
Conversion Copy Engine
Autonomy Dashboard
Full Regression Harness
```

验收：

```text
能生成发布包
能管理日更和存稿
能分析读者反馈
能预测弃读点
能调整后续大纲和细纲
能多项目并行运行
能根据平台反馈优化策略
```

---

# 11. 最终判断

最新版 Novel OS 的完整形态是：

```text
Autonomous Novel OS
= 核心 OS 层
+ 创作 Engine 层
+ 精品网文增强层
+ 工具层
+ UI 控制台
+ 版本化演进路线
```

它最终解决的不只是“写小说”，而是：

```text
写什么；
为什么值得写；
用什么素材写；
用什么知识支撑；
如何有创意；
如何有内涵；
如何规划长篇；
如何生成可读正文；
如何持续给读者爽点和追读理由；
如何避免毒点和弃读；
如何维护主角魅力和反派压力；
如何保证多卷结构；
如何避免长篇崩坏；
如何完结不烂尾；
如何多本并行；
如何自动采集素材和知识；
如何审稿修订；
如何根据反馈进化。
```

最终目标：

> **让系统从“AI 写作工具”升级为“低人工介入、可追踪、可复盘、可持续进化的精品网络小说生产操作系统”。**
