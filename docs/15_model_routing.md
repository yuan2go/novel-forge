# 15. 模型路由策略 Model Routing

## 1. 模块目标

模型路由模块用于决定不同任务由 Claude Code、ChatGPT/Codex、DeepSeek 中的哪一类工具或模型处理。

当前可用环境约束：

```text
Claude Code + ChatGPT/Codex
Claude Code + DeepSeek
```

因此系统设计必须围绕这两种组合切换，而不是假设复杂模型生态。

## 2. 总体分工

| 工具 / 模型 | 定位 | 主要任务 |
|---|---|---|
| Claude Code | 单本小说项目总编 | 管理文件、执行任务卡、更新 memory、调度模型 |
| ChatGPT/Codex | 高质量判断 | 立项、知识编译、哲学方向、审稿、重构建议 |
| DeepSeek | 生产与批处理 | 网文拆解、知识卡初稿、正文 v0、评论分类 |

## 3. 按任务价值路由

| 任务 | 推荐模型 |
|---|---|
| 项目立项 | ChatGPT/Codex |
| Reader Attraction Gate | ChatGPT/Codex |
| Project Differentiation Gate | ChatGPT/Codex |
| 知识卡初抽取 | DeepSeek |
| 网文批量拆解 | DeepSeek |
| 学科书籍摘要 | DeepSeek |
| Project Knowledge Pack 编译 | ChatGPT/Codex |
| Project Constitution 生成 | ChatGPT/Codex |
| 前 30 章节奏规划 | ChatGPT/Codex |
| 章节细纲 | ChatGPT/Codex 或 DeepSeek 初稿后审稿 |
| 正文 v0 | DeepSeek |
| 正文 v1 初修 | DeepSeek |
| 多维审稿 | ChatGPT/Codex |
| 评论分类 | DeepSeek |
| 反馈采纳判断 | ChatGPT/Codex |
| 项目复盘 | ChatGPT/Codex |
| 代码与脚本开发 | Codex / Claude Code |

## 4. 路由原则

### 4.1 高价值判断任务优先 ChatGPT/Codex

包括：

```text
是否立项；
是否有吸引力；
是否同质化；
哲学命题是否成立；
世界宪法是否合理；
审稿是否通过；
评论是否采纳；
是否需要重构。
```

### 4.2 批量生产任务优先 DeepSeek

包括：

```text
批量拆解；
摘要；
初稿；
评论分类；
知识卡初稿；
低成本多版本扩写。
```

### 4.3 Claude Code 只做项目调度和文件维护

Claude Code 不应该直接承担所有创造和判断。

它负责：

```text
读取上下文；
执行任务卡；
调用模型；
整理输出；
写入文件；
更新 memory；
生成报告。
```

## 5. model_routing.yaml

路径：

```text
.novelforge/model_routing.yaml
```

示例：

```yaml
default:
  analysis_model: deepseek
  writing_model: deepseek
  review_model: chatgpt_codex
  planning_model: chatgpt_codex
  feedback_model: deepseek

tasks:
  reader_attraction_gate:
    model: chatgpt_codex
    reason: requires high-quality commercial judgment

  project_differentiation_gate:
    model: chatgpt_codex
    reason: requires comparison and editorial judgment

  knowledge_card_extraction:
    model: deepseek
    reason: low-cost batch processing

  project_knowledge_compilation:
    model: chatgpt_codex
    reason: requires synthesis and conflict resolution

  project_constitution_generation:
    model: chatgpt_codex
    reason: requires stable high-level rules

  chapter_draft_v0:
    model: deepseek
    reason: production efficiency

  chapter_review:
    model: chatgpt_codex
    reason: quality judgment

  comment_classification:
    model: deepseek
    reason: batch classification

  feedback_decision:
    model: chatgpt_codex
    reason: must avoid story drift
```

## 6. 任务卡中的模型声明

每个 task_card 必须明确使用模型：

```markdown
## 使用模型

DeepSeek

## 模型职责

生成第 12 章 v0 初稿，不做项目宪法修改，不做最终审稿。

## 质量复核

由 ChatGPT/Codex 执行商业、逻辑、心理、世界观、原创风险审稿。
```

## 7. 模型输出边界

### DeepSeek 输出边界

DeepSeek 输出可以作为：

```text
初稿；
草稿；
候选项；
分类结果；
摘要结果；
知识卡初稿。
```

不能直接作为：

```text
项目宪法最终版；
最终审稿结论；
重大反馈采纳决策；
final 发布稿。
```

### ChatGPT/Codex 输出边界

ChatGPT/Codex 可以作为高质量判断来源，但仍需要主编确认 final 和重大重构。

### Claude Code 输出边界

Claude Code 负责写入文件，但不能绕过任务卡和项目宪法。

## 8. 验收标准

模型路由系统必须满足：

1. 每个任务都有默认模型；
2. 每个任务都有模型职责说明；
3. 高价值判断不交给低成本批处理模型独立决定；
4. DeepSeek 生成内容必须经过审稿；
5. ChatGPT/Codex 审稿结论必须写入 reviews/；
6. Claude Code 必须记录模型调用和产出文件。
