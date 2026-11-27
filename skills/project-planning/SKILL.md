---
name: project-planning
description: Use when planning a new novel project, phase, sprint, roadmap, or task sequence so goals, inputs, outputs, risks, acceptance criteria, and downstream workflow dependencies are explicit and testable.
---

# Project Planning

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 新项目立项、阶段规划、冲刺计划或任务池整理。
- 需要把产品目标转成可执行开发/写作任务。
- 需要判断哪些工作属于 P0/P1/P2，以及是否能进入 pipeline。
- 已有 spec、审计报告或需求清单，需要拆成可交给 Engineering Agent 执行的文件级、接口级、测试级计划。

## 输入要求

- Product vision、roadmap、current state、open issues 或用户目标。
- 已有 schema、workflow、data 目录、docs 和测试入口。
- 业务边界：原创安全、读者吸引力、长期连载和可验证输出。

## 操作流程

1. 明确目标、当前状态、约束和不可做事项。
2. 拆分业务链路：输入、清洗、拆解、知识、素材、题材、世界、人物、大纲、细纲、正文、审稿、反馈。
3. 先建立文件结构图：每个将创建或修改的文件负责什么、依赖什么、对外提供什么接口。
4. 标记每个任务的输入、输出、涉及文件、接口、验收标准和测试方式。
5. 将任务拆成可独立 review 的最小垂直切片；每个切片必须有自己的测试或验证命令。
6. 按 P0/P1/P2 排序：先闭环、再效率、再增强质量。
7. 标记风险、依赖、阻塞项、rollback 建议和 commit 边界。
8. 输出任务清单、阶段计划和下一步最小可验收动作。
9. 需要代码或数据变更时，交给 Engineering Agent 或对应模块 Agent。

## 输出格式

```markdown
# Project Plan

## 目标
## 当前状态
## 约束与禁止事项
## 文件结构与职责
## 任务池
## 接口与依赖
## P0 路线
## P1 路线
## P2 路线
## 风险与依赖
## 验收标准
## 测试命令
## 回滚建议
## 下一步动作
```

## 质量标准

- 每个任务必须有明确输入、输出和验收标准。
- 工程任务必须列出具体文件路径、接口/函数/数据结构、测试命令和预期结果。
- 每个任务边界必须足够小，能被 reviewer 独立接受或拒绝。
- P0 必须优先服务主链路闭环。
- 不把不可测试的愿景标记为完成任务。
- 计划必须能被后续 Agent 接手。

## 禁止事项

- 禁止用宏大愿景替代可执行任务。
- 禁止一次性重构无关模块。
- 禁止写 `TBD`、`TODO`、`类似上一步`、`补充适当测试` 这类不可执行占位。
- 禁止跳过测试、状态记录或验收标准。
- 禁止把未实现能力写成已完成。

## 与其他模块的关系

- 上游：product docs、roadmap、audit、open issues。
- 下游：task pool、workflow plan、Engineering Agent、Quality Agent。
- Agent：Chief Editor Agent、Engineering Agent、Quality Agent。
