# 多学科知识资产操作系统设计文档

## 1. 定位

多学科知识资产操作系统，简称 MKAOS（Multidisciplinary Knowledge Asset Operating System），是 Novel Forge / Novel Operating System 的知识中枢、规则中枢、审稿中枢和反馈学习中枢。

它不是普通资料库，也不是单纯 RAG 检索层。它的核心职责是把专业书籍、网文拆解、名著拆解、平台规则、读者反馈、审稿历史等来源，转换成可以被小说生产流程稳定调用的创作资产。

核心目标：

1. 将多学科知识转换成题材、世界观、人物、大纲、细纲、正文、审稿、反馈、训练题和模板可用的资产；
2. 让所有 Agent 通过统一 Knowledge Pack 使用知识，而不是直接读取原始资料；
3. 区分通用知识、题材知识、项目 Canon，防止外部知识污染长篇设定；
4. 将知识同时转为生成约束、正文细节和审稿规则；
5. 通过审稿、人工修改、读者反馈、平台表现持续更新知识权重。

---

## 2. 非目标

MKAOS 不做以下事情：

1. 不把专业书籍原文直接塞进小说正文；
2. 不鼓励照抄网文、名著、案例或桥段；
3. 不让正文 Agent 直接读取 source chunk；
4. 不允许任何外部知识自动覆盖项目 Canon；
5. 不以知识数量为目标，而以知识是否能转化为故事效用为目标；
6. 不允许每个 Agent 各自随意检索和解释知识。

---

## 3. 核心原则

### 3.1 知识必须服务故事

错误路径：

```text
知识 → 正文解释 → 百科化段落
```

正确路径：

```text
知识 → 冲突 / 人物 / 世界规则 / 场景 / 伏笔 / 审稿项
```

示例：

```text
知识：土地兼并

题材：王朝末期寒门逆袭
世界观：土地制度、税制、豪强结构
人物：主角家族土地被夺
大纲：地方土地案牵出朝廷财政危机
细纲：逼签田契、县衙审案、粮仓冲突
正文：老农举着田契跪在县衙门口
审稿：土地制度是否实际推动冲突
```

### 3.2 Canon 优先级

固定优先级：

```text
项目 Canon > 当前大纲 > 当前细纲 > 题材承诺 > 平台节奏 > 多学科通用知识 > 原始资料
```

外部知识只能辅助，不可自动推翻已确认设定。

### 3.3 同一知识多流程复用

同一条知识在不同流程中必须有不同形态：

| 流程 | 形态 |
|---|---|
| 题材 | 题材承诺、长篇空间、平台适配 |
| 世界观 | 制度、资源、规则、边界 |
| 人物 | 欲望、恐惧、创伤、行为逻辑 |
| 大纲 | 主线冲突、阶段结构、主题递进 |
| 细纲 | 章节事件、场景冲突、信息释放 |
| 正文 | 动作、对话、物件、场景细节 |
| 审稿 | 检查规则、严重等级、修改建议 |
| 反馈 | 问题归因、权重调整、模板沉淀 |

---

## 4. 总体架构

```text
MKAOS
├── Source Layer 来源层
│   ├── 专业书籍
│   ├── 网文拆解
│   ├── 名著拆解
│   ├── 论文资料
│   ├── 平台规则
│   ├── 读者评论
│   └── 审稿历史
│
├── Knowledge Layer 知识层
│   ├── 概念
│   ├── 机制
│   ├── 原则
│   ├── 案例
│   ├── 反例
│   ├── 风险
│   └── 负面规则
│
├── Asset Layer 资产层
│   ├── 知识卡
│   ├── 素材卡
│   ├── 冲突卡
│   ├── 人物卡
│   ├── 世界观卡
│   ├── 场景卡
│   ├── 规则卡
│   ├── 模板卡
│   └── 审稿项
│
├── Runtime Layer 运行层
│   ├── Knowledge Router
│   ├── Knowledge Pack Builder
│   ├── Flow Adapter
│   ├── Constraint Injector
│   ├── Review Rule Injector
│   ├── Canon Checker
│   ├── Usage Tracker
│   └── Feedback Learner
│
└── Evolution Layer 演化层
    ├── 知识评分
    ├── 知识升权
    ├── 知识降权
    ├── 知识废弃
    ├── 模板沉淀
    ├── 规则升级
    └── 回归测试
```

---

## 5. 核心模块

### 5.1 Knowledge Repository

保存知识卡、素材卡、冲突卡、规则卡、模板卡、来源切片和负面规则。

### 5.2 Knowledge Graph

记录知识之间的关系，例如：

```text
土地兼并 causes 小农破产
小农破产 causes 流民问题
流民问题 causes 地方叛乱
地方叛乱 supports 王朝末期题材
土地兼并 used_for 世界观 / 大纲 / 细纲 / 审稿
```

关系类型包括：`is_a`、`part_of`、`causes`、`conflicts_with`、`supports`、`derived_from`、`used_for`、`contradicts`、`requires`、`limits`。

### 5.3 Knowledge Router

根据任务上下文判断：

1. 当前流程是什么；
2. 当前产物是什么；
3. 需要哪些学科；
4. 每门学科调用到什么粒度；
5. 是否需要 Canon 检查；
6. 是否需要审稿规则注入；
7. 哪些知识必须禁用。

### 5.4 Knowledge Pack Builder

Agent 实际消费的是 Knowledge Pack，而不是原始知识。

Knowledge Pack 包含：

```text
当前任务
当前流程
题材与平台
项目 Canon
必须使用知识
可选知识
禁止知识
生成约束
审稿规则
风格约束
知识预算
风险提醒
输出契约
```

### 5.5 Flow Adapter

将同一条知识转换为不同流程的可用形态。

示例：因果链知识

| 流程 | 转换结果 |
|---|---|
| 大纲 | 阶段事件必须有前因、行动、后果 |
| 细纲 | 每章必须有目标、阻碍、行动、结果 |
| 正文 | 人物反应必须符合动机和压力 |
| 审稿 | 检查强行巧合、降智、动机断裂 |

### 5.6 Constraint Injector

把知识转为生成约束，例如：

```text
1. 重大反转必须有前置线索；
2. 制度矛盾必须影响人物利益；
3. 反派不能只有恶意，必须有利益逻辑；
4. 每章知识点不得超过知识预算；
5. 正文禁止连续百科解释。
```

### 5.7 Review Rule Injector

把知识转为审稿规则，例如：

```text
规则：财政危机有效性检查
触发：大纲或正文出现财政、军饷、税收、粮仓等内容
检查：是否影响军队、官僚、民生或主角利益
阻断：如果只是背景解释且不推动冲突，则标记为高风险
```

### 5.8 Canon Checker

检查外部知识是否与项目 Canon 冲突。若冲突，按照 Canon 优先级处理，并输出：

1. 冲突位置；
2. 冲突类型；
3. 是否阻断；
4. 修正建议；
5. 是否需要总编 Agent 决策。

### 5.9 Usage Tracker

记录每次知识调用：

```text
knowledge_id
project_id
flow
artifact_id
chapter_id
agent_name
used_as
output_span
review_result
reader_feedback
effect_score
```

### 5.10 Feedback Learner

根据审稿、人工修改、读者反馈和平台表现，调整知识状态和权重。

---

## 6. 知识生命周期

```text
原始来源
  ↓
原始切片
  ↓
候选知识
  ↓
已抽取知识
  ↓
已归一化知识
  ↓
已资产化知识
  ↓
已绑定流程知识
  ↓
运行时使用知识
  ↓
已验证知识
  ↓
高价值知识 / 降权知识 / 废弃知识
```

状态枚举：

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

---

## 7. 专业书籍清洗

清洗目标不是摘要，而是：

```text
专业知识 → 小说生产资产
```

清洗流水线：

```text
书籍导入
  ↓
格式识别
  ↓
章节切分
  ↓
段落清理
  ↓
知识点抽取
  ↓
学科分类
  ↓
概念归一化
  ↓
流程用途识别
  ↓
创作资产转换
  ↓
审稿规则转换
  ↓
模板生成
  ↓
质量审核
  ↓
入库
  ↓
回归测试
```

清洗产物必须包括：

1. 知识卡；
2. 素材卡；
3. 冲突卡；
4. 世界观卡；
5. 人物卡；
6. 规则卡；
7. 模板卡；
8. 审稿项；
9. 流程用途绑定；
10. 调用说明。

---

## 8. Agent 交互原则

所有 Agent 统一通过五类接口交互：

```text
Query：查询知识
Pack：构造知识包
Convert：转换创作资产
Validate：使用知识审稿
Feedback：回写使用效果
```

禁止正文 Agent、大纲 Agent、人物 Agent 直接读取原始 source chunk。

---

## 9. 关键运行流程

### 9.1 大纲流程

```text
大纲任务
  ↓
请求大纲 Knowledge Pack
  ↓
调用叙事学、逻辑学、类型文学、哲学、历史、政治、经济、心理学
  ↓
大纲 Agent 生成总纲 / 分卷
  ↓
逻辑 Agent 检查因果链
  ↓
审稿 Agent 检查爽点、节奏、伏笔
  ↓
总编 Agent 判断通过 / 修改 / 回滚
```

### 9.2 正文流程

```text
正文任务
  ↓
请求正文 Knowledge Pack
  ↓
正文 Agent 生成草稿
  ↓
反百科化 Agent 检查
  ↓
文风 Agent 检查
  ↓
Canon Agent 检查
  ↓
审稿 Agent 输出问题
  ↓
修订 Agent 修改
  ↓
Usage Tracker 记录知识使用
```

正文约束：

1. 每章核心知识点 1-3 个；
2. 知识必须转成动作、对话、物件、场景变化；
3. 禁止连续百科解释；
4. 禁止人物替作者讲课；
5. 知识必须影响当前冲突。

---

## 10. UI 设计

左侧导航建议：

```text
多学科知识资产
├── 知识总览
├── 来源管理
├── 知识卡管理
├── 知识图谱
├── 流程用途绑定
├── 创作资产转换台
├── 知识包构造器
├── 审稿规则库
├── 知识使用地图
├── 知识风险看板
├── 知识回归测试
└── 知识权重与演化
```

关键页面：

1. 知识总览：知识总量、学科覆盖度、流程覆盖度、高风险知识、已验证知识；
2. 来源管理：上传、切片、清洗状态、来源可信度、版权状态；
3. 流程用途绑定：设置某知识在各流程的粒度、形态、优先级；
4. 知识包构造器：选择项目、流程、章节，预览 Knowledge Pack；
5. 知识使用地图：查看某知识影响了哪些项目、章节、规则；
6. 知识风险看板：百科化、Canon 冲突、平台违规、专业误用、版权风险。

---

## 11. 工程落地

推荐结构：

```text
Postgres：结构化知识、资产、规则、调用记录
Qdrant：知识向量检索
MinIO：原始书籍、清洗中间产物
Celery：异步清洗、批量抽取、回归测试
FastAPI：知识系统 API
前端管理台：知识中心 UI
Agent Runtime：统一调用 Knowledge Pack
```

服务模块：

```text
knowledge-ingestion-service
knowledge-cleaning-service
knowledge-extraction-service
knowledge-asset-service
knowledge-graph-service
knowledge-router-service
knowledge-pack-service
knowledge-review-rule-service
knowledge-usage-tracker-service
knowledge-feedback-service
knowledge-regression-service
```

当前 v6 实现补充：

1. `knowledge_graph_snapshot`：把 Knowledge Card、Rule Card、Template Card、Usage Binding、Usage Event、Quality Score、Source Chunk evidence ref 统一为多学科知识图谱节点和边。
2. `knowledge_learning_snapshot`：聚合 usage effect、review feedback、reader feedback 和 quality delta，生成可解释的 boost / reduce / review / quarantine 建议。
3. 图谱不包含 `source_chunk.raw_text` 或 `source_chunk.clean_text`，仅保留 source chunk id、hash、source document id 和抽象知识字段。
4. 学习默认只出建议；只有调用方显式传入 `apply_updates: true` 时才通过 MKAOS weight update 写回，保持 selector 行为可审计。
5. 新增 API：
   - `POST /product/mkaos/knowledge-graph/build`
   - `POST /product/mkaos/knowledge-graph/query`
   - `POST /product/mkaos/knowledge-graph/paths`
   - `POST /product/mkaos/learning/effects`

---

## 12. 验收标准

产品验收：

1. 知识能从来源清洗为资产；
2. 知识能绑定多个流程；
3. Agent 使用 Knowledge Pack，而不是直接查原文；
4. 大纲、细纲、正文、审稿都能使用同一知识的不同形态；
5. 正文能防止百科化；
6. 审稿能使用知识规则；
7. 知识使用能留痕；
8. 反馈能回写；
9. 高价值知识能升权和模板化；
10. 低价值知识能降权或废弃。

工程验收：

1. 数据模型完整；
2. API 可用；
3. 清洗任务可异步执行；
4. Knowledge Pack 可稳定生成；
5. Usage Event 可记录；
6. Canon Checker 可阻断冲突；
7. UI 可查看知识、绑定、风险和使用地图；
8. 回归测试可运行；
9. 日志、错误、重试、超时机制完整；
10. 有最小可用示例项目。

---

## 13. 最小闭环示例

输入：

```text
王朝末期，土地兼并严重，小农破产，流民增加，地方豪强扩张，中央税源减少。
```

输出资产：

```text
知识卡：土地兼并
冲突卡：豪强获利，小农受损，主角因家族土地被夺卷入
流程绑定：世界观、大纲、细纲、正文、审稿
审稿规则：土地制度是否实际推动人物利益冲突
```

大纲调用：

```text
第一卷主线：主角调查田契命案，发现地方豪强通过伪造田契吞并土地。
```

正文调用：

```text
县衙门口，老农把田契举过头顶，纸角已经被汗水泡软。
```

审稿结果：

```text
通过：知识没有百科化，已经转化为人物利益冲突。
```

---

## 14. 总结

MKAOS 的最优设计不是：

```text
知识库 + RAG 检索
```

而是：

```text
知识清洗
+ 知识资产化
+ 流程用途绑定
+ Knowledge Pack
+ Agent 统一调用
+ Canon 检查
+ 审稿规则注入
+ 使用追踪
+ 反馈回写
+ 权重演化
```

它是 Novel Forge 从 AI 写作工具升级为长期工业化小说生产系统的核心基础设施。
