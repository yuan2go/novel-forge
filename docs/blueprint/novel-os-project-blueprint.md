# Novel OS 项目蓝图

## 0. 项目名称

```text
Autonomous Novel OS
自治型精品网络小说生产操作系统
```

简称：

```text
Novel OS
```

项目底层代号可继续使用：

```text
novel-forge
```

---

# 1. 项目最终定位

Novel OS 不是普通 AI 写作工具，也不是单次小说生成器，而是：

> 一个面向长期创作、低人工介入、多本并行、质量可控、可持续进化的 **精品网络小说生产操作系统**。

它要解决的不是：

```text
让 AI 写一章小说
```

而是：

```text
让系统持续生产有追读感、有爽点、有主角魅力、有长篇稳定性、有题材新意、有主题内涵的精品网络小说。
```

---

# 2. 项目核心目标

## 2.1 短期目标

构建一个可用的单本小说生产闭环：

```text
题材
→ 世界观
→ 人物
→ 大纲
→ 细纲
→ 正文
→ 审稿
→ 修订
→ Canon 更新
→ 长篇复盘
→ 导出
```

验收目标：

```text
可以连续生成一本小说前 10—30 章；
章节不是提纲式正文；
人物、设定、伏笔不明显崩坏；
每章有审稿、修订和质量报告；
系统能记录 Canon、人物状态、时间线和伏笔。
```

---

## 2.2 中期目标

构建精品网文增强能力：

```text
黄金开篇
读者承诺
爽点账本
毒点弃读检测
主角魅力
反派压力
卷级弧线
移动端阅读体验
正文可读性
主题内涵嵌入
原创性风险控制
```

验收目标：

```text
前 3 章有明确钩子；
前 10 章建立主线和读者承诺；
每 3—5 章有小回报；
每卷有明确目标、高潮和余波；
主角有持续魅力点；
反派压力递进；
正文具备场景感、冲突感和追读感。
```

---

## 2.3 长期目标

构建无人化、多本并行的小说工业系统：

```text
自动采集素材
自动建设 MKAOS 知识资产
自动生成题材机会
自动生产多本小说
自动审稿修订
自动维护长篇稳定性
自动复盘失败案例
自动分析读者反馈
自动优化后续生产策略
```

验收目标：

```text
系统能同时管理多本小说；
能判断项目优先级；
能暂停低潜力项目；
能防止多本书同质化；
能根据反馈调整大纲、细纲和正文策略；
能形成长期知识资产、模板资产和审稿规则资产。
```

---

# 3. 项目不做什么

为了避免项目失控，需要明确边界。

Novel OS 暂时不以以下内容为第一阶段目标：

```text
1. 不做公开 SaaS 写作平台；
2. 不做多人协同创作平台；
3. 不优先做付费、会员、账号体系；
4. 不优先做多模型策略系统；
5. 不追求一开始全自动发布；
6. 不鼓励爬取或复刻版权期小说正文；
7. 不以批量生成低质网文为目标；
8. 不把所有模块都做成独立 OS；
9. 不以生成“很多字”为核心指标；
10. 不把热门作品拆解结果直接进入正文生成上下文。
```

当前阶段核心是：

```text
个人本地精品小说生产系统
```

---

# 4. 项目成功标准

## 4.1 生产成功标准

```text
能稳定从一个创作目标生成一本小说前 30 章；
每章都有细纲、正文、审稿、修订和质量记录；
系统能自动维护人物、伏笔、Canon、时间线；
正文具备基本可读性和追读感。
```

---

## 4.2 长篇成功标准

```text
第 80 章仍能保持：
- 人物状态连续；
- 主线目标清晰；
- 伏笔未丢失；
- 战力或能力体系不崩；
- 读者承诺有兑现；
- 反派压力持续；
- 章节质量无明显下滑。
```

---

## 4.3 精品网文成功标准

```text
开篇抓人；
主角有魅力；
反派有压力；
爽点有铺垫和兑现；
章节结尾有追读动力；
正文没有明显 AI 味；
没有大段说明书；
人物行动有动机；
题材有新鲜变量；
主题内涵通过剧情体现，不说教。
```

---

## 4.4 多本并行成功标准

```text
能同时管理多本小说项目；
每本书有独立风格身份；
跨书人物、世界观、爽点不明显重复；
系统能给出项目优先级；
系统能建议暂停或砍掉低潜力项目；
高潜力项目获得更多资源。
```

---

# 5. 项目总体架构

Novel OS 采用三层架构：

```text
核心 OS 层
+ 创作 Engine 层
+ Module / Tool 层
```

---

## 5.1 核心 OS 层

核心 OS 层负责长期状态、知识资产、调度、质量、追踪、安全和多项目管理。

```text
Core OS Layer
│
├── Agent OS
├── Source / Material Governance OS
├── MKAOS
├── Context Builder OS
├── Story Bible / Long-form OS
├── Quality / Review / Eval OS
├── Ops / Trace / Cost OS
├── Portfolio OS
└── Security / Sandbox OS
```

---

## 5.2 创作 Engine 层

Engine 层负责具体创作生产任务。

```text
Engine Layer
│
├── Creative Engine
├── Meaning / Philosophy Engine
├── Worldbuilding Engine
├── Character Engine
├── Outline Engine
├── Chapter Blueprint Engine
├── Readable Prose Engine
├── Revision Engine
├── Ending / Closure Engine
├── Feedback Analysis Engine
├── Publishing Adapter Engine
├── Reader Simulation Engine
├── Style Identity Engine
├── Originality Risk Engine
└── Serialization Engine
```

---

## 5.3 Module / Tool 层

工具层保持轻量，作为连接器、解析器、导出器和辅助工具。

```text
Tool Layer
│
├── Git Connector
├── News / RSS Connector
├── Public Domain Importer
├── Open Data Connector
├── PDF / EPUB Parser
├── Title Generator
├── Synopsis Generator
├── Cover Prompt Generator
├── Chapter Title Optimizer
├── Exporter
└── Tag Manager
```

---

# 6. 项目核心业务链路

## 6.1 无人化素材与知识链路

```text
用户目标
→ Agent OS 生成采集计划
→ Source OS 发现 Git / 新闻 / 公版 / 开放数据
→ Source Governance 检查许可和风险
→ Material OS 生成素材卡
→ MKAOS 转成知识资产 / 模板 / 审稿规则
→ Eval OS 生成测试案例
→ Ops OS 记录来源、成本、质量
```

---

## 6.2 小说生产链路

```text
创作目标
→ Creative Engine 生成题材候选
→ Novelty Gate / 商业可读性评分
→ 立项
→ Meaning Engine 生成主题问题
→ Worldbuilding Engine 生成世界观
→ Character Engine 生成人物体系
→ Outline Engine 生成整本大纲
→ Blueprint Engine 生成前 30 章细纲
→ Prose Engine 生成第 1 章正文
→ Review OS 审稿
→ Revision Engine 修订
→ Review OS 复审
→ Canon / 人物 / 伏笔 / 时间线更新
→ 继续下一章
→ 每 5 / 10 章自动复盘
```

---

## 6.3 精品网文增强链路

```text
章节细纲
→ 章节商业功能标注
→ 读者承诺检查
→ 爽点账本检查
→ 主角魅力检查
→ 反派压力检查
→ 毒点弃读预测
→ 移动端阅读体验检查
→ 追读感门禁
→ 正文生成 / 修订
```

---

## 6.4 长篇稳定链路

```text
章节正文
→ Canon Fact 抽取
→ Character State 更新
→ Timeline Event 更新
→ Foreshadow Ledger 更新
→ Reader Promise 更新
→ Pleasure Point Ledger 更新
→ Conflict Ledger 更新
→ Long Review Agent 周期复盘
→ 后续大纲 / 细纲调整
```

---

## 6.5 多本并行链路

```text
多个小说项目
→ Portfolio OS 统一看板
→ 项目潜力评分
→ 资源分配
→ 风格隔离
→ 跨书同质化检测
→ 暂停 / 砍书建议
→ 高潜力项目优先生产
```

---

# 7. 核心模块项目定义

---

## 7.1 Agent OS

### 项目职责

负责系统无人化调度。

### 核心能力

```text
任务规划
任务拆解
任务依赖图
Agent 注册
Skill 选择
上下文请求
任务执行
失败重试
审批路由
周期运行
执行记录
```

### 项目验收

```text
可以自动执行一个完整创作任务链；
任务失败后能重试或暂停；
高风险任务能提交审批；
每次执行都有 OS Envelope。
```

---

## 7.2 Source / Material Governance OS

### 项目职责

负责外部来源发现、风险检查和素材资产化。

### 核心能力

```text
Source Registry
License Scanner
Git / News / RSS / Open Data 采集
Material Inbox
MaterialCard 生成
风险分级
素材去重
素材使用追踪
```

### 项目验收

```text
能拉取合规 Git 仓库；
能生成 SourceCard；
能识别高风险来源；
能把资料转成素材卡；
高风险资料不会进入正文生成上下文。
```

---

## 7.3 MKAOS

### 项目职责

负责知识资产管理、创作规则生成和知识调用。

### 核心能力

```text
知识资产化
模板生成
审稿规则生成
Eval Case 生成
source isolation
evidence-only
stage-aware query
task-specific context
knowledge usage feedback
```

### 项目验收

```text
素材卡能转成知识资产；
拆解结果能转成模板；
哲学资料能转成主题冲突；
审稿报告能转成规则；
正文 Agent 不能直接接触高风险参考原文。
```

---

## 7.4 Context Builder OS

### 项目职责

负责每次 Agent 执行前组装最小、正确、安全的上下文。

### 核心能力

```text
任务识别
上下文选择
Canon 检索
人物状态检索
伏笔检索
MKAOS 知识调用
上下文压缩
禁止内容注入
Context Package 生成
```

### 项目验收

```text
正文阶段只获得必要素材；
审稿阶段能获得完整审稿规则；
大纲阶段能获得题材和结构知识；
所有上下文包有来源和选择理由。
```

---

## 7.5 Story Bible / Long-form OS

### 项目职责

负责长篇稳定性。

### 核心能力

```text
World Bible
Character State
Canon Fact
Timeline
Foreshadow
Reader Promise
Pleasure Point
Conflict Ledger
Power Scale
Volume Arc
Long Review
```

### 项目验收

```text
每章后能自动更新 Canon；
人物状态能随剧情变化；
伏笔能记录和提醒；
每 10 章能生成复盘报告；
系统能发现人物漂移和伏笔遗忘。
```

---

## 7.6 Quality / Review / Eval OS

### 项目职责

负责质量门禁、审稿、修订验证和系统回归。

### 核心能力

```text
ReviewIssue
可读性审稿
AI 味审稿
毒点审稿
人物一致性审稿
世界观一致性审稿
平台规则审稿
原创性风险审稿
Eval Case
Regression Test
```

### 项目验收

```text
每章能生成审稿报告；
问题有严重等级和证据位置；
严重问题能阻断下一章；
修订后能复审；
系统更新后能跑回归测试。
```

---

## 7.7 Portfolio OS

### 项目职责

负责多本小说项目组合管理。

### 核心能力

```text
多书看板
项目优先级评分
精品潜力评分
跨书同质化检测
资源分配
暂停 / 砍书建议
系列宇宙管理
```

### 项目验收

```text
能同时显示多本书状态；
能判断哪本更值得继续；
能发现多个项目题材、人设、风格重复；
能给出暂停低潜力项目建议。
```

---

## 7.8 Security / Sandbox OS

### 项目职责

负责外部内容安全和无人化执行边界。

### 核心能力

```text
Connector Permission
Sandbox Execution
Repository Allowlist / Blocklist
Prompt Injection Guard
Untrusted Content Filter
Security Audit
Secret Manager
```

### 项目验收

```text
外部 Git / 网页 / PDF 内容不能直接污染系统提示；
恶意内容能被识别；
高风险连接器动作需要权限；
所有外部执行有审计日志。
```

---

# 8. 精品网文关键能力

---

## 8.1 黄金开篇

### 项目目标

让小说开篇能抓住读者。

### 关键门禁

```text
前 300 字是否有事件 / 异常 / 压力
第 1 章是否有主角困境
前 3 章是否建立读者承诺
前 10 章是否展示核心卖点
前 3 万字是否形成稳定追读
```

---

## 8.2 读者承诺

### 项目目标

追踪系统向读者许下的所有期待。

### 承诺类型

```text
复仇承诺
升级承诺
揭秘承诺
身份承诺
情感承诺
反派清算承诺
世界观扩展承诺
伏笔回收承诺
```

---

## 8.3 爽点账本

### 项目目标

防止爽点断档、重复和无铺垫。

### 检查规则

```text
最近 3 章是否有小爽点
最近 10 章是否有中爽点
每卷是否有大爽点
爽点是否重复
爽点是否升级
爽点是否有铺垫
爽点是否有代价
```

---

## 8.4 毒点与弃读

### 项目目标

提前发现读者可能弃读的风险。

### 常见毒点

```text
主角降智
主角圣母
强行误会
长期压主
反派降智
配角喧宾夺主
剧情拖沓
设定说明书
爽点不兑现
伏笔不回收
强行虐主
前后逻辑冲突
```

---

## 8.5 主角魅力

### 项目目标

防止主角正确但无趣。

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

## 8.6 反派压力

### 项目目标

保证主线对抗持续升级。

### 管理内容

```text
反派目标
反派资源
反派行动计划
压迫方式
阶段性胜利
反派升级
反派破防
最终败因
```

---

## 8.7 移动端阅读体验

### 项目目标

让正文适合手机阅读。

### 检查项

```text
段落是否太长
句子是否太密
对话是否清晰
一屏内是否有变化
是否有视觉停顿
是否有强钩子句
信息是否过载
```

---

# 9. 项目数据资产

## 9.1 来源资产

```text
Source
SourcePolicy
SourceSyncJob
SourceSnapshot
LicenseCheckResult
SourceRiskReport
```

## 9.2 素材资产

```text
MaterialCard
MaterialTag
MaterialFunction
MaterialRisk
MaterialUsage
MaterialConversion
```

## 9.3 知识资产

```text
KnowledgeAsset
CreativePrinciple
NarrativeMechanism
TemplateAsset
ReviewRule
EvalCase
SourceEvidence
```

## 9.4 小说资产

```text
NovelProject
WorldBible
CharacterProfile
CharacterState
CanonFact
TimelineEvent
ForeshadowItem
ReaderPromise
PleasurePoint
ConflictItem
BookOutline
VolumeOutline
ChapterBlueprint
ChapterDraft
ReviewIssue
RevisionDraft
```

## 9.5 运营资产

```text
PortfolioProject
BookPotentialScore
ResourceAllocationPlan
CrossBookSimilarityReport
AgentTask
AgentRun
OSEnvelope
TraceLog
CostLog
QualityMetric
FailureCase
SecurityAuditLog
```

---

# 10. UI 项目蓝图

## 10.1 自治工作台

```text
今日任务
待审批
异常告警
成本统计
质量趋势
自动化等级
```

## 10.2 目标与策略

```text
创作目标
平台目标
题材偏好
禁止方向
采集策略
成本策略
审批策略
```

## 10.3 来源中心

```text
Source Registry
Git 仓库
新闻源
公版书库
开放数据
平台监控
来源风险
```

## 10.4 素材工厂

```text
Material Inbox
素材卡
素材标签
素材风险
素材使用
素材转化
```

## 10.5 MKAOS

```text
知识资产
创作原则
模板库
审稿规则
Eval Case
Source Isolation
Knowledge Usage
```

## 10.6 创意中心

```text
题材机会
创意候选池
新鲜度评分
反套路检查
立项建议
```

## 10.7 小说项目

```text
项目管理
世界观
人物
大纲
细纲
正文
Canon
伏笔
时间线
读者承诺
爽点账本
反派压力
卷级弧线
导出
```

## 10.8 网文增强

```text
黄金开篇
毒点弃读
主角魅力
反派压迫
章节商业功能
移动端阅读体验
套路疲劳
连载生命周期
```

## 10.9 质量中心

```text
审稿报告
可读性报告
AI 味报告
长篇复盘
审美总编
原创性风险
发布门禁
```

## 10.10 Portfolio

```text
多书看板
项目优先级
精品潜力评分
资源分配
跨书污染检测
暂停 / 砍书建议
```

## 10.11 Agent Center

```text
Agent 列表
任务队列
执行日志
失败重试
模型调用
成本统计
```

## 10.12 Eval Center

```text
测试集
回归测试
失败案例
审稿准确性
正文可读性
长篇稳定性
质量趋势
```

## 10.13 Ops Center

```text
OS Envelope
Trace Log
Source Audit
Knowledge Usage
Cost Log
Rollback
Security Audit
Autonomy Report
```

---

# 11. 项目落地路线

## Phase 1：单本小说生产闭环

### 目标

完成最小可用 Novel OS。

### 范围

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

### 验收

```text
能连续生成一本小说前 10—30 章；
每章有细纲、正文、审稿、修订；
系统能维护基础 Canon 和人物状态；
正文不是提纲扩写；
开篇具备基本吸引力。
```

---

## Phase 2：长篇稳定与网文追读增强

### 范围

```text
完整 Canon
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

### 验收

```text
能支撑 100 章以内连续生产；
伏笔不丢；
爽点不长期断档；
反派压力递进；
主角魅力稳定；
每 10 章有复盘和调整建议。
```

---

## Phase 3：创意、内涵与风格增强

### 范围

```text
Creative Engine
Novelty Gate
Anti-Template Checker
Meaning / Philosophy Engine
Theme Engine
Character Belief System
Anti-Preaching Gate
Style Identity Engine
Trope Fatigue Detector
```

### 验收

```text
题材不是简单换皮；
人物和世界观有辨识度；
哲学主题通过冲突和选择体现；
每本书有独立风格；
长篇中期不明显套路疲劳。
```

---

## Phase 4：MKAOS 资产化成熟

### 范围

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

### 验收

```text
素材能转创作机制；
拆解能转模板；
审稿问题能转规则；
失败案例能转 Eval；
知识资产有评分、淘汰和复用机制。
```

---

## Phase 5：无人化资料与生产

### 范围

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

### 验收

```text
系统能自动拉取合规来源；
能生成素材卡；
能转成 MKAOS 资产；
能自动生成题材机会报告；
能自动推进章节生产和复盘；
高风险事项进入审批。
```

---

## Phase 6：多书并行与 Portfolio

### 范围

```text
Portfolio OS
Multi-Book Scheduler
Cross-Book Contamination Guard
Book Potential Scorer
Resource Allocation Planner
Book Kill / Pause Gate
Series / Universe Manager
```

### 验收

```text
能同时管理多本小说；
能判断项目优先级；
能防止多书同质化；
能暂停低潜力项目；
能优先支持高潜力项目。
```

---

## Phase 7：平台化、连载与反馈闭环

### 范围

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

### 验收

```text
能生成发布包；
能管理日更和存稿；
能分析读者反馈；
能预测弃读点；
能调整后续大纲和细纲；
能根据平台反馈优化策略。
```

---

# 12. 项目风险

## 12.1 过度工程化风险

风险：

```text
系统模块过多，迟迟不能生产正文。
```

控制：

```text
先完成 v1 单本生产闭环；
核心 OS 化，创作能力 Engine 化，外围能力 Tool 化；
禁止一开始全部做成独立系统。
```

---

## 12.2 版权污染风险

风险：

```text
外部资料、热门小说拆解、新闻原文污染生成上下文。
```

控制：

```text
Source Governance
source isolation
structure-only
summary-only
generation_context_allowed
Originality Risk Engine
```

---

## 12.3 AI 味与低质正文风险

风险：

```text
生成大量“像正文但不好看”的文本。
```

控制：

```text
Readable Prose Engine
Text Vitality Checker
Page-Turning Gate
Mobile Reading Experience
Review OS
Revision Engine
```

---

## 12.4 长篇崩坏风险

风险：

```text
人物漂移、伏笔丢失、战力崩坏、主线断裂。
```

控制：

```text
Story Bible / Long-form OS
Canon
Character State
Foreshadow Ledger
Promise Ledger
Long Review Agent
```

---

## 12.5 多本同质化风险

风险：

```text
多本书主角、文风、爽点、世界观高度重复。
```

控制：

```text
Portfolio OS
Style Identity Engine
Cross-Book Similarity Report
Trope Fatigue Detector
Originality Risk Engine
```

---

## 12.6 无人化安全风险

风险：

```text
自动拉取外部资料时引入恶意提示、错误知识、隐私内容。
```

控制：

```text
Security / Sandbox OS
Prompt Injection Guard
Connector Permission
Untrusted Content Filter
Security Audit
```

---

# 13. 项目验收总标准

## 13.1 v1 验收

```text
1. 创建小说项目；
2. 生成世界观；
3. 生成人物体系；
4. 生成整本大纲；
5. 生成前 30 章细纲；
6. 连续生成前 10 章正文；
7. 每章自动审稿；
8. 每章至少一轮修订；
9. 自动更新 Canon / 人物 / 伏笔；
10. 输出前 10 章质量报告。
```

---

## 13.2 精品网文验收

```text
1. 前 300 字有事件或压力；
2. 前 3 章建立读者承诺；
3. 前 10 章展示核心卖点；
4. 主角有明确魅力点；
5. 反派压力逐步递进；
6. 爽点有铺垫和兑现；
7. 没有明显毒点；
8. 移动端阅读体验合格；
9. 章节结尾有追读动力；
10. 主题内涵不说教。
```

---

## 13.3 长篇验收

```text
1. 连续 100 章不明显崩设定；
2. 人物状态连续；
3. 伏笔账本完整；
4. 读者承诺有兑现计划；
5. 每卷有目标、高潮、余波；
6. 主线不丢失；
7. 质量趋势不持续下降；
8. 完结前有收束计划。
```

---

## 13.4 多本并行验收

```text
1. 同时管理至少 3 本小说；
2. 每本书有独立风格档案；
3. 系统能识别项目同质化；
4. 系统能输出项目优先级；
5. 系统能建议暂停低潜力项目；
6. 高潜力项目获得更多生产资源。
```

---

# 14. 最终项目结论

Novel OS 项目的最终形态是：

```text
一个由核心 OS 层、创作 Engine 层、精品网文增强层、工具层和 UI 控制台组成的自治型小说生产系统。
```

它不是简单的 AI 写作软件，而是一套：

```text
创作目标驱动；
素材自动采集；
知识自动资产化；
创意自动孵化；
长篇自动规划；
正文自动生成；
质量自动审稿；
问题自动修订；
读者承诺自动追踪；
爽点自动管理；
毒点自动检测；
长篇自动复盘；
多书自动调度；
反馈自动反哺；
高风险人工审批；
全链路可追踪可回滚的精品网文生产操作系统。
```

最终目标：

> **让一个人可以用低人工介入的方式，长期经营多个小说项目，并持续提高精品长篇网络小说的命中率。**
