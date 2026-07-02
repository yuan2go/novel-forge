# MKAOS P0 实施任务清单与测试方案

## 1. P0 目标

P0 的目标不是一次性完成完整多学科知识资产操作系统，而是打通最小可用闭环：

```text
来源导入
  ↓
知识清洗
  ↓
知识卡生成
  ↓
流程用途绑定
  ↓
Knowledge Pack 构造
  ↓
大纲 / 细纲 / 正文 / 审稿调用
  ↓
知识使用留痕
  ↓
审稿反馈回写
```

P0 必须证明：

1. 知识不只是被存储，而是能进入创作流程；
2. 同一知识能在大纲、细纲、正文、审稿中呈现不同形态；
3. 正文 Agent 不直接读取原始 source chunk；
4. 审稿规则可以由知识资产注入；
5. 知识使用结果可以被记录和回写。

---

## 2. P0 范围

### 2.1 必做功能

```text
1. Source Document 管理
2. Source Chunk 管理
3. Knowledge Card 管理
4. Knowledge Usage Binding 管理
5. Rule Card 管理
6. Template Card 管理
7. Knowledge Pack Builder
8. Flow Adapter：outline / chapter_outline / prose / review
9. Usage Tracker
10. 基础 Feedback 回写
11. 基础 UI 页面
12. P0 回归测试集
```

### 2.2 暂不进入 P0

```text
1. 完整知识图谱可视化
2. 自动跨学科组合模板
3. 自动高价值模板沉淀
4. 读者评论深度归因
5. 多平台发布表现回写
6. 完整长篇 100 章压力测试
7. 全自动知识权重演化
```

这些进入 P1/P2。

---

## 3. P0 里程碑

```text
M1：数据库与基础模型
M2：来源导入与清洗流水线
M3：知识卡与流程用途绑定
M4：Knowledge Pack Builder
M5：四个 Flow Adapter
M6：审稿规则注入与反百科化检查
M7：Usage Tracker 与 Feedback 回写
M8：UI 最小管理台
M9：回归测试与验收
```

---

## 4. M1：数据库与基础模型

### 4.1 任务

实现以下表：

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

### 4.2 要求

1. 所有表具备 created_at / updated_at；
2. 关键字段有索引；
3. knowledge_cards 能追溯 source_chunk_ids；
4. knowledge_usage_bindings 支持同一知识多流程绑定；
5. knowledge_pack_items 支持 required / optional / forbidden / constraint / review_rule；
6. usage_events 能记录 Agent、flow、artifact、chapter、used_as、effect_score。

### 4.3 验收

```text
1. migration 可重复执行；
2. 单元测试覆盖核心表 CRUD；
3. 删除 source_document 后 source_chunks 级联删除；
4. 删除 knowledge_card 后 usage bindings 级联删除；
5. rule_card 删除不破坏历史 knowledge_pack。
```

---

## 5. M2：来源导入与清洗流水线

### 5.1 任务

实现基础导入：

```text
1. 上传 markdown / txt / pdf 提取后的文本；
2. 保存 source_document；
3. 切分 source_chunks；
4. 清理页眉页脚、空行、重复段落；
5. 计算 content_hash；
6. 支持重新清洗。
```

### 5.2 清洗输出

P0 阶段允许半自动：

```text
source_text → cleaned_text → candidate knowledge cards
```

生成知识卡时必须包含：

```text
concept_name
discipline
sub_discipline
knowledge_type
core_explanation
source_chunk_ids
confidence
risk_level
applicable_genres
```

### 5.3 验收

1. 导入一份历史制度资料，可生成 source_document；
2. source_chunks 不为空；
3. 重复文本不重复生成 chunk；
4. 清洗日志可查询；
5. 失败任务可重试。

---

## 6. M3：知识卡与流程用途绑定

### 6.1 任务

实现知识卡编辑和流程绑定。

绑定字段：

```text
knowledge_id
flow
usage_type
usage_granularity
input_role
output_form
prompt_fragment
constraint_text
review_rule_id
template_id
priority
risk_level
enabled
```

### 6.2 P0 必须支持的 flow

```text
outline
chapter_outline
prose
review
```

### 6.3 示例

知识：土地兼并

```text
outline：主线冲突 / outline_constraint
chapter_outline：章节事件 / beat_design
prose：场景细节 / prose_detail
review：制度有效性检查 / review_rule
```

### 6.4 验收

1. 一条知识可以绑定多个 flow；
2. 禁用 binding 后不会进入 Knowledge Pack；
3. prose flow 必须具备知识预算和反百科化约束；
4. review flow 必须能关联 rule_card。

---

## 7. M4：Knowledge Pack Builder

### 7.1 任务

实现：

```http
POST /api/mkaos/packs/build
GET /api/mkaos/packs/{id}
GET /api/mkaos/packs/{id}/prompt-preview
```

### 7.2 构造逻辑

输入：

```text
project_id
flow
genre
platform
chapter_id
task_goal
constraints
```

处理步骤：

```text
1. 根据 flow 和 task_goal 查询 usage bindings；
2. 按 genre / platform / discipline 过滤；
3. 排除 deprecated knowledge；
4. 注入 Canon context；
5. 注入 required / optional / forbidden knowledge；
6. 注入 generation constraints；
7. 注入 review rules；
8. 注入 knowledge budget；
9. 输出 Knowledge Pack。
```

### 7.3 验收

1. outline pack 返回机制、结构、冲突类知识；
2. chapter_outline pack 返回章节事件、场景冲突、信息释放类知识；
3. prose pack 返回微观细节、表达约束、知识预算；
4. review pack 返回 rule_cards；
5. prose pack 不得直接包含 source_chunk raw_text；
6. pack 构造结果可持久化。

---

## 8. M5：Flow Adapter

### 8.1 Outline Adapter

输入：大纲任务上下文。  
输出：

```text
主线结构约束
阶段冲突模型
因果链要求
爽点节奏
伏笔计划要求
反派利益逻辑
```

验收：

1. 不输出正文句段；
2. 必须包含逻辑约束；
3. 必须包含审稿规则引用。

### 8.2 Chapter Outline Adapter

输出：

```text
章节目标
场景列表
行动闭环
信息释放
伏笔表现
钩子要求
禁止提前透露的信息
```

验收：

1. 每章必须有目标、阻碍、行动、结果、钩子；
2. 不允许修改主线 Canon；
3. 不允许直接揭露超纲信息。

### 8.3 Prose Adapter

输出：

```text
允许使用的知识点
动作表达建议
对话表达建议
物件表达建议
场景表达建议
禁止百科化说明
知识预算
```

验收：

1. 每章核心知识点不超过预算；
2. 知识必须转成动作、对话、物件或场景；
3. 禁止连续解释性段落；
4. 禁止人物替作者讲课。

### 8.4 Review Adapter

输出：

```text
结构检查
逻辑检查
人物一致性检查
Canon 检查
专业知识检查
平台风险检查
反百科化检查
```

验收：

1. 每条问题必须关联 rule_card；
2. 必须有 severity；
3. 必须有 blocking 判断；
4. 必须有 fix_suggestion。

---

## 9. M6：审稿规则注入与反百科化检查

### 9.1 P0 必须实现的规则

```text
1. 反百科化检查
2. 因果链检查
3. 人物行为一致性检查
4. Canon 冲突检查
5. 知识有效性检查
6. 章节钩子检查
```

### 9.2 反百科化规则

触发：正文出现专业知识、制度解释、世界观说明。

检查：

```text
1. 是否存在连续解释性段落；
2. 是否人物替作者讲课；
3. 知识是否影响当前冲突；
4. 是否可改写成动作、对话、物件或场景；
5. 是否破坏情绪推进。
```

### 9.3 验收

1. 对明显百科式正文必须命中；
2. 对自然场景化知识不应误报；
3. 命中后必须给出修改方向；
4. high/critical 级问题可阻断发布。

---

## 10. M7：Usage Tracker 与 Feedback 回写

### 10.1 任务

实现：

```http
POST /api/mkaos/usage-events
POST /api/mkaos/feedback/review
POST /api/mkaos/feedback/apply-weight-update
```

### 10.2 使用记录字段

```text
knowledge_id
knowledge_pack_id
project_id
flow
target_artifact_id
chapter_id
agent_name
used_as
prompt_context
output_span
review_result
reader_feedback
effect_score
```

### 10.3 权重调整逻辑

P0 使用简单规则：

```text
审稿通过 + 人工确认有效：+0.05
有效推动冲突：+0.10
正文百科化命中：prose flow -0.15
Canon 冲突命中：对应 flow -0.25
连续 3 次低效：status 标记为 needs_review
人工废弃：status = deprecated
```

### 10.4 验收

1. 每次 Knowledge Pack 被用于生成后产生 usage event；
2. 审稿结果可回写到知识；
3. 权重调整有日志；
4. 支持按 project / flow / chapter 查询使用记录。

---

## 11. M8：UI 最小管理台

### 11.1 页面清单

```text
1. 知识总览
2. 来源管理
3. 知识卡管理
4. 流程用途绑定
5. Knowledge Pack 预览
6. 审稿规则库
7. 知识使用记录
8. 知识风险列表
```

### 11.2 知识总览

显示：

```text
知识总量
已绑定流程数量
高风险知识数量
deprecated 数量
各学科覆盖度
各流程覆盖度
最近使用知识
最近审稿命中
```

### 11.3 知识卡管理

功能：

```text
查询
筛选
查看来源
查看流程绑定
查看规则
手工修正
降权
废弃
```

### 11.4 Knowledge Pack 预览

功能：

```text
选择 project / flow / chapter / task_goal
构造 pack
查看 required / optional / forbidden
查看约束和规则
预览注入给 Agent 的 prompt sections
```

---

## 12. M9：回归测试与验收

### 12.1 单元测试

覆盖：

```text
source_documents CRUD
source_chunks CRUD
knowledge_cards CRUD
usage_bindings CRUD
rule_cards CRUD
Knowledge Pack Builder
Flow Adapter
Usage Tracker
Feedback 更新
```

### 12.2 集成测试

标准链路：

```text
导入文本
  ↓
生成 source chunks
  ↓
生成 knowledge cards
  ↓
绑定 outline / chapter_outline / prose / review
  ↓
构造 Knowledge Pack
  ↓
模拟 Agent 使用
  ↓
审稿
  ↓
记录 usage event
  ↓
回写 feedback
```

### 12.3 回归样例

P0 至少准备 10 个样例：

```text
1. 历史制度知识：土地兼并
2. 逻辑学知识：因果链
3. 叙事学知识：伏笔与回收
4. 心理学知识：创伤反应
5. 推理学知识：证词矛盾
6. 正文百科化反例
7. 自然场景化正例
8. Canon 冲突样例
9. 大纲阶段有效调用样例
10. 细纲阶段有效调用样例
```

### 12.4 验收指标

| 指标 | P0 标准 |
|---|---|
| Flow Match Rate | >= 80% |
| Prose Source Isolation | 100% 不直接暴露 raw chunk |
| Review Rule Link Rate | >= 90% 问题关联 rule_card |
| Usage Event Coverage | >= 95% pack 调用有记录 |
| Anti-Encyclopedia Hit | 明显反例必须命中 |
| Canon Conflict Blocking | critical 冲突必须阻断 |
| Pack Build Time | 普通任务 < 5 秒 |

---

## 13. 开发任务拆分

### 13.1 Backend

```text
TASK-BE-001：新增 MKAOS 数据表 migration
TASK-BE-002：实现 source document / chunk service
TASK-BE-003：实现 knowledge card service
TASK-BE-004：实现 usage binding service
TASK-BE-005：实现 rule card / template card service
TASK-BE-006：实现 Knowledge Pack Builder
TASK-BE-007：实现 outline / chapter_outline / prose / review adapters
TASK-BE-008：实现 validate artifact API
TASK-BE-009：实现 usage event / feedback API
TASK-BE-010：实现基础回归测试 runner
```

### 13.2 Frontend

```text
TASK-FE-001：新增多学科知识资产导航
TASK-FE-002：知识总览页
TASK-FE-003：来源管理页
TASK-FE-004：知识卡管理页
TASK-FE-005：流程用途绑定页
TASK-FE-006：Knowledge Pack 预览页
TASK-FE-007：审稿规则库页
TASK-FE-008：知识使用记录页
TASK-FE-009：知识风险列表页
```

### 13.3 Agent Runtime

```text
TASK-AGENT-001：所有 Agent 请求 Knowledge Pack
TASK-AGENT-002：ProseAgent 禁止读取 source chunk
TASK-AGENT-003：OutlineAgent 接入 outline adapter
TASK-AGENT-004：ChapterOutlineAgent 接入 chapter_outline adapter
TASK-AGENT-005：ReviewAgent 接入 rule_cards
TASK-AGENT-006：生成后写入 usage event
TASK-AGENT-007：审稿后写入 feedback event
```

### 13.4 Testing

```text
TASK-TEST-001：单元测试
TASK-TEST-002：集成测试
TASK-TEST-003：回归样例集
TASK-TEST-004：Knowledge Pack snapshot 测试
TASK-TEST-005：反百科化测试
TASK-TEST-006：Canon 冲突测试
TASK-TEST-007：Usage Event 覆盖率测试
```

---

## 14. Definition of Done

P0 完成必须满足：

1. 数据库 migration 已合入；
2. 可以导入一个来源并生成 chunks；
3. 可以创建知识卡并绑定四个核心流程；
4. 可以构造 outline / chapter_outline / prose / review Knowledge Pack；
5. Prose Pack 不直接暴露 source chunk；
6. Review Pack 可以注入 rule_cards；
7. Agent 使用 Knowledge Pack 后写入 usage event；
8. 审稿结果可以回写 feedback；
9. UI 能查看知识、绑定、pack、规则、使用记录；
10. 回归测试集通过；
11. 有最小示例：土地兼并知识从来源进入大纲、细纲、正文、审稿；
12. 文档、API、测试报告同步更新。

---

## 15. 最小验收示例

输入来源：

```text
王朝末期，土地兼并严重，小农破产，流民增加，地方豪强扩张，中央税源减少。
```

系统应生成：

```text
Knowledge Card：土地兼并
Flow Bindings：outline / chapter_outline / prose / review
Conflict Card：豪强获利、小农受损、主角因田契案卷入
Rule Card：制度知识是否推动人物利益冲突
Template Card：地方土地案主线模板
```

Outline Pack 应包含：

```text
地方土地案作为第一卷主线冲突
制度矛盾必须影响主角利益
反派必须有经济和权力动机
```

Prose Pack 应包含：

```text
允许使用：田契、县衙、粮仓、佃户
禁止：大段解释土地制度
表达方式：动作、物件、对话、场景变化
```

Review Pack 应包含：

```text
反百科化检查
制度有效性检查
因果链检查
人物利益冲突检查
```

最终通过标准：

```text
知识没有停留在摘要层，而是进入了大纲、细纲、正文和审稿。
```
