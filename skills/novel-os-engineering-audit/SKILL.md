---
name: novel-os-engineering-audit
description: Use when auditing Novel Forge or Novel Operating System implementation against product docs, architecture docs, tests, runtime gates, source isolation, and acceptance evidence without making code changes unless explicitly requested.
---

# Novel OS Engineering Audit

## 适用场景

- 对比设计文档、审计报告、代码、API、UI、测试和运行资产，判断 Novel OS 能力是否真实完成。
- 审核 MKAOS、Context Builder、ReviewIssue、Loop Kernel、Agent Center、Publish/Feedback、Platform Strategy、Evaluation Center。
- 生成逐项矩阵、风险台账、修复计划和测试缺口报告。

## 输入要求

- 目标范围、相关 docs、src、tests、web/admin 路径、当前 git 状态和已知验收命令。
- 设计要求、当前实现声明、测试结果、关键 API 或 UI 路由。
- 若涉及外部事实或官方 API，必须使用可信来源或官方文档。

## Novel OS Runtime Contract

- 审计结论必须引用具体文件、函数、API、测试或文档路径。
- 不得凭印象判断；找不到实现时必须记录搜索路径。
- 不得把“超前实现”简单判错，需区分 MATCH、PARTIAL、MISSING、EXTRA_VALID、EXTRA_RISKY、CONFLICT、NEEDS_DECISION。
- 审计本身不修改业务代码；需要改代码时必须另开实现任务。

## 操作流程

1. 读取目标文档、历史报告、代码入口、测试和 UI 注册。
2. 建立设计索引和实现索引，识别主设计、补充设计、过时设计和版本差异。
3. 按模块逐项对比产品目标、信息架构、数据模型、流程接入、门禁、反馈闭环、测试覆盖。
4. 标注一致性、严重级别、证据和建议处理。
5. 输出风险台账、修复计划、测试补充清单和是否可进入下一阶段的判断。
6. 运行只读或指定验收命令，并记录未运行原因。

## 输出格式

```markdown
# Novel OS Engineering Audit

## Scope

## Evidence Index

## Implementation Matrix
| Module | Design Requirement | Current Implementation | Evidence | Judgment | Severity | Recommendation |

## Risks

## Test Results

## Next Actions
```

## 质量标准

- 报告必须能让后续 Agent 直接执行修复，不需要重新猜上下文。
- 严重级别必须服务工业化主线，不能只做文档性排序。
- 测试缺口必须写明缺什么、影响什么、建议在哪个文件补。

## 禁止事项

- 禁止无证据结论。
- 禁止把业务代码修改混入审计任务。
- 禁止忽略 source isolation、fail-closed、ReviewIssue blocking、OS Envelope 和 Context Builder 这些主线约束。

## 与其他模块的关系

- 上游：docs、reports、src、tests、web/admin、runtime assets。
- 下游：remediation plan、phase plan、GitHub issue、Agent handoff。
- 关联 Skill：`agent-loop-governance`、`mkaos-knowledge-asset-os`、`context-builder-source-isolation`。
