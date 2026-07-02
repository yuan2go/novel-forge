# MKAOS Agent API 协议设计文档

## 1. 目标

本文档定义 Novel Forge 中各类 Agent 与多学科知识资产操作系统 MKAOS 的交互协议。

核心要求：

1. 所有创作 Agent 通过统一 API 获取知识；
2. Agent 消费 Knowledge Pack，而不是直接读取原始资料；
3. 同一知识在不同流程中返回不同使用形态；
4. 所有知识调用必须记录 usage event；
5. 审稿、人工修改、读者反馈可以回写知识权重。

---

## 2. 交互模式

Agent 与 MKAOS 的交互统一为五类：

```text
Query：查询知识
Pack：构造知识包
Convert：转换创作资产
Validate：使用知识审稿
Feedback：回写使用结果
```

标准链路：

```text
Agent 提交任务上下文
  ↓
MKAOS 构造 Knowledge Pack
  ↓
Agent 基于 Knowledge Pack 生成 / 审稿 / 反馈
  ↓
MKAOS 记录 usage event
  ↓
Feedback Learner 调整权重
```

---

## 3. Agent 权限模型

| Agent | 可读 | 可写 | 约束 |
|---|---|---|---|
| EditorAgent | 全部知识包、Canon、报告 | 调度决策、回滚决策 | 不直接改原始知识 |
| GenreAgent | 类型、平台、读者心理、爆款拆解 | 题材候选、题材评估 | 不修改项目 Canon |
| WorldbuildingAgent | 历史、政治、经济、神话、地理 | 世界观草稿 | 生成 Canon 候选，不直接落库 |
| CharacterAgent | 心理、社会、哲学、类型人设 | 人物草稿 | 不覆盖核心人设 |
| OutlineAgent | 结构、逻辑、题材、世界观 | 大纲草稿 | 需经过逻辑和审稿检查 |
| ChapterOutlineAgent | 大纲、Canon、章节知识包 | 章节细纲 | 不修改主线 Canon |
| ProseAgent | 细纲、文风、正文知识包 | 正文草稿 | 不引入未批准核心设定 |
| ReviewAgent | 规则库、Canon、产物 | 审稿报告 | 不直接改正文 |
| CanonAgent | 项目设定、外部知识 | Canon 更新建议 | 需要证据链 |
| FeedbackAgent | 评论、数据、审稿历史 | 反馈归因、权重建议 | 不直接改正文 |
| KnowledgeCuratorAgent | 来源、知识卡、图谱 | 通用知识库、资产库 | 不修改项目剧情 |

---

## 4. 通用协议

请求头建议：

```http
X-Agent-Name: OutlineAgent
X-Project-Id: <project_uuid>
X-Request-Id: <uuid>
X-Trace-Id: <uuid>
```

通用响应：

```json
{
  "success": true,
  "request_id": "uuid",
  "trace_id": "uuid",
  "data": {},
  "warnings": [],
  "errors": []
}
```

错误响应：

```json
{
  "success": false,
  "request_id": "uuid",
  "trace_id": "uuid",
  "data": null,
  "warnings": [],
  "errors": [
    {
      "code": "CANON_CONFLICT",
      "message": "候选知识与项目 Canon 冲突",
      "severity": "high",
      "blocking": true,
      "fix_suggestion": "按项目 Canon 修正设定"
    }
  ]
}
```

---

## 5. Query API

### 5.1 查询知识

```http
POST /api/mkaos/query/knowledge
```

请求：

```json
{
  "project_id": "project_uuid",
  "flow": "outline",
  "genre": "历史权谋",
  "platform": "起点",
  "task_goal": "设计第一卷地方土地案主线",
  "disciplines": ["历史学", "政治学", "经济学", "叙事学", "逻辑学"],
  "usage_granularity": ["L2_mechanism_model", "L3_creation_rule", "L4_plot_material"],
  "limit": 20,
  "include_assets": true,
  "include_rules": true,
  "exclude_deprecated": true
}
```

响应重点：

```json
{
  "knowledge_items": [
    {
      "knowledge_id": "uuid",
      "concept_name": "土地兼并",
      "discipline": "历史学",
      "knowledge_type": "mechanism",
      "matched_flows": ["worldbuilding", "outline", "chapter_outline", "prose", "review"],
      "usage_hint": "适合用于王朝末期地方矛盾和主角家族破产动机。",
      "quality_score": 88.5,
      "risk_level": "medium"
    }
  ]
}
```

---

## 6. Pack API

### 6.1 构造 Knowledge Pack

```http
POST /api/mkaos/packs/build
```

请求：

```json
{
  "project_id": "project_uuid",
  "flow": "chapter_outline",
  "genre": "悬疑修仙",
  "platform": "起点",
  "chapter_id": "chapter_uuid",
  "task_goal": "主角调查宗门禁地尸体",
  "constraints": {
    "avoid_spoiler": true,
    "knowledge_budget": 3,
    "must_include_disciplines": ["推理学", "宗教学", "逻辑学"],
    "forbidden_patterns": ["直接揭露真凶", "大段解释宗门历史"]
  }
}
```

响应：

```json
{
  "knowledge_pack_id": "kp_uuid",
  "flow": "chapter_outline",
  "current_goal": "主角调查宗门禁地尸体",
  "required_knowledge": [],
  "optional_knowledge": [],
  "forbidden_knowledge": [],
  "canon_context": [],
  "generation_constraints": [],
  "review_rules": [],
  "knowledge_budget": {
    "max_core_knowledge_points": 3,
    "prose_explanation_limit": "no_continuous_expository_paragraph"
  },
  "risk_warnings": [],
  "output_contract": {
    "must_output": ["章节目标", "场景列表", "信息释放", "结尾钩子"],
    "must_not_output": ["真凶身份", "超纲设定"]
  }
}
```

### 6.2 读取 Knowledge Pack

```http
GET /api/mkaos/packs/{knowledge_pack_id}
```

### 6.3 预览 Agent 注入文本

```http
GET /api/mkaos/packs/{knowledge_pack_id}/prompt-preview
```

---

## 7. Convert API

### 7.1 知识转创作资产

```http
POST /api/mkaos/convert/assets
```

请求：

```json
{
  "knowledge_id": "uuid",
  "target_assets": ["material_card", "conflict_card", "rule_card", "template_card"],
  "genre": "历史权谋",
  "platform": "起点",
  "conversion_goal": "将土地兼并知识转换为地方冲突资产"
}
```

响应：

```json
{
  "created_assets": {
    "material_cards": [],
    "conflict_cards": [],
    "rule_cards": [],
    "template_cards": []
  }
}
```

### 7.2 知识转审稿规则

```http
POST /api/mkaos/convert/rules
```

请求：

```json
{
  "knowledge_id": "uuid",
  "rule_type": "review_rule",
  "applicable_flows": ["outline", "chapter_outline", "prose"],
  "goal": "检查制度知识是否实际推动剧情"
}
```

---

## 8. Validate API

### 8.1 知识审稿

```http
POST /api/mkaos/validate/artifact
```

请求：

```json
{
  "project_id": "project_uuid",
  "flow": "prose",
  "artifact_id": "chapter_draft_uuid",
  "knowledge_pack_id": "kp_uuid",
  "artifact_text": "...",
  "validation_scope": ["canon", "logic", "anti_encyclopedia", "knowledge_usage", "platform"]
}
```

响应：

```json
{
  "passed": false,
  "score": 72,
  "issues": [
    {
      "issue_id": "uuid",
      "rule_id": "uuid",
      "rule_name": "反百科化检查",
      "severity": "high",
      "blocking": true,
      "message": "本章存在连续制度解释，未转化为冲突或场景。",
      "fix_suggestion": "改写为人物行动、对话、物件或场景变化。",
      "rollback_level": "prose"
    }
  ],
  "usage_assessment": []
}
```

### 8.2 Canon 冲突检查

```http
POST /api/mkaos/validate/canon-conflict
```

响应字段：

```json
{
  "has_conflict": true,
  "blocking": true,
  "conflicts": [
    {
      "canon_item_id": "canon_uuid",
      "canon_statement": "项目既有设定",
      "candidate_statement": "候选设定",
      "severity": "critical",
      "fix_suggestion": "按 Canon 优先级修正"
    }
  ]
}
```

---

## 9. Feedback API

### 9.1 记录知识使用

```http
POST /api/mkaos/usage-events
```

请求：

```json
{
  "knowledge_id": "uuid",
  "knowledge_pack_id": "kp_uuid",
  "project_id": "project_uuid",
  "flow": "outline",
  "target_artifact_id": "outline_uuid",
  "chapter_id": null,
  "agent_name": "OutlineAgent",
  "used_as": "制度冲突",
  "prompt_context": "第一卷地方土地案主线",
  "output_span": "第一卷第三阶段",
  "effect_score": 0.82
}
```

### 9.2 回写审稿结果

```http
POST /api/mkaos/feedback/review
```

请求：

```json
{
  "knowledge_id": "uuid",
  "project_id": "project_uuid",
  "source_type": "review",
  "feedback_type": "anti_encyclopedia_hit",
  "feedback_text": "该知识在正文阶段导致百科化解释。",
  "normalized_signal": {
    "flow": "prose",
    "problem": "encyclopedia_exposition",
    "severity": "high"
  },
  "suggested_action": "decrease_prose_weight",
  "confidence": 0.91
}
```

---

## 10. Agent 调用约定

### 10.1 OutlineAgent

1. 使用机制和结构，不使用正文细节；
2. 每个阶段事件必须有因果链；
3. 制度知识必须转为人物利益冲突；
4. 必须输出伏笔计划和爽点计划。

### 10.2 ChapterOutlineAgent

1. 每章必须有目标、阻碍、行动、结果、钩子；
2. 只调用章节级 Knowledge Pack；
3. 不提前揭露超出当前章节的信息；
4. 不修改主线 Canon。

### 10.3 ProseAgent

1. 知识必须转成动作、对话、物件、场景；
2. 不新增核心设定；
3. 不超过知识预算；
4. 不直接解释制度原理；
5. 需要记录知识使用片段。

### 10.4 ReviewAgent

输出必须包含：

1. 问题类型；
2. 触发规则；
3. 严重等级；
4. 是否阻断；
5. 是否回滚；
6. 修改建议；
7. 涉及知识 ID。

---

## 11. 错误码

| code | 含义 | blocking |
|---|---|---|
| KNOWLEDGE_NOT_FOUND | 未找到可用知识 | false |
| FLOW_BINDING_MISSING | 知识缺少流程绑定 | true |
| CANON_CONFLICT | 与项目 Canon 冲突 | true |
| KNOWLEDGE_BUDGET_EXCEEDED | 超出知识预算 | true for prose |
| DIRECT_SOURCE_CHUNK_FORBIDDEN | Agent 试图直接读取 source chunk | true |
| DEPRECATED_KNOWLEDGE_USED | 使用废弃知识 | true |
| REVIEW_RULE_MISSING | 当前流程缺少审稿规则 | false |
| PACK_BUILD_FAILED | Knowledge Pack 构造失败 | true |
| PERMISSION_DENIED | Agent 权限不足 | true |
| ANTI_ENCYCLOPEDIA_HIT | 百科化命中 | depends on severity |

---

## 12. API 验收标准

1. Agent 可以按 flow 构造 Knowledge Pack；
2. ProseAgent 的 Knowledge Pack 不包含原始 source chunk 直接内容；
3. 同一知识可在 outline、chapter_outline、prose、review 中返回不同形态；
4. Canon 冲突检查可以阻断不合规知识注入；
5. 审稿 API 能返回触发规则、严重等级和修改建议；
6. Feedback API 能记录审稿命中并调整权重；
7. 所有 API 响应包含 request_id 和 trace_id；
8. 权限不足时返回 PERMISSION_DENIED；
9. 所有 usage event 可被长篇复盘 Agent 查询；
10. API 能支撑 P0 流程：清洗 → 知识包 → 大纲/细纲/正文 → 审稿 → 回写。
