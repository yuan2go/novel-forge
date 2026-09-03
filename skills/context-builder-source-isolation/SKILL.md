---
name: context-builder-source-isolation
description: Use when building, reviewing, or debugging ContextBundle and KnowledgePack inputs for outline, chapter plan, draft, review, revision, recap, publish, and feedback flows with strict source isolation and token-budget governance.
---

# Context Builder Source Isolation

## 适用场景

- 为核心 Agent 生产 ContextBundle、ContextBuildPlan 或 prompt preview。
- 审计 RAG、MKAOS pack、Canon/Character/Arc/Foreshadowing/WorldRule、ReviewIssue 是否被安全注入。
- 修复或验证 raw source text、parallel pair、runtime asset 污染生成链路的问题。

## 输入要求

- `project_id`、target asset、task type、flow、token budget、source policy、runtime environment。
- KnowledgePack、ContextBundle、RAG retrieval report、evidence refs、ReviewIssue 和 prior issue 引用。
- 禁止项清单：raw text、clean text、quote、source_text、target_text、unreviewed provider output。

## Novel OS Runtime Contract

- 所有核心生产动作必须通过 Context Builder 形成 `context_bundle_id`；`knowledge_pack_id` 仅在 active Capability Pack / stage 明确要求或本次选择了项目 Knowledge Pack 时存在。
- ContextBundle 必须记录 source policy、source isolation、selected knowledge ids、review rules、risk warnings、selector policy version。
- controlled runtime 下缺 context bundle、缺 Capability 所要求的 knowledge pack 或 source isolation 失败必须 fail closed；Capability 未要求时不得为了形式完整强塞空 Knowledge Pack。
- compat fallback 只能用于旧 fixture/sample，并必须写 trace、policy warning 和 metadata。

## 操作流程

1. 收集 flow 所需的 canon、arc、character、foreshadowing、world rule、MKAOS pack、ReviewIssue 和 revision constraints。
2. 对每个输入执行 source isolation lint，拒绝 raw/clean/source/target text 进入生成上下文。
3. 按 token budget、质量、风险和任务目标裁剪上下文。
4. 生成 ContextBundle，并记录 evidence refs、selector decision、risk warnings 和 trace。
5. 运行 MKAOS production gate 或对应 flow gate。
6. 输出可审计的 bundle 摘要，不展开受保护来源正文。

## 输出格式

```markdown
# Context Bundle Report

## Contract
- context_bundle_id:
- knowledge_pack_id: # optional unless Capability/stage requires it
- knowledge_requirement: # OPTIONAL / REQUIRED
- flow:
- source_policy:

## Included Context
- canon:
- mkaos:
- review rules:
- prior issues:

## Gates
- source isolation:
- token budget:
- blocking issues:
```

## 质量标准

- ContextBundle 可从 AgentRun、Chapter Saga、PublishGate、FeedbackBackflow 反查。
- 所有上下文片段都有来源类型、允许用途和裁剪理由。
- 必须记录 `knowledge_requirement`；REQUIRED 不允许空 pack，OPTIONAL 未选择时记录 `NOT_REQUESTED`，不得伪造空 pack。

## 禁止事项

- 禁止 Agent 各自拼 prompt 绕过 Context Builder。
- 禁止把 `.local/workspace` 的 runtime asset 当作 generation RAG 内容。
- 禁止 source_chunk、source_document、parallel_pair 的原文或清洗文本进入正文上下文。

## 与其他模块的关系

- 上游：MKAOS、Canon Graph、RAG、ReviewIssue、Runtime Policy。
- 下游：Agent Runtime、Command Kernel、Draft/Review/Revision/Recap/Publish/Feedback flows。
- 关联 Skill：`mkaos-knowledge-asset-os`、`review-issue-gate`、`agent-loop-governance`。
