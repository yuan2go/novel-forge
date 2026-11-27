---
name: world-consequence-modeling
description: Use when deriving long-term economic, political, military, infrastructural, technological, religious, educational, criminal, class, geographic, cultural, or generational consequences from accepted world rules.
---

# World Consequence Modeling

## Novel OS Runtime Contract

- `worldbuilding` 定义世界规则；本 Skill 推演规则长期存在的后果，不创建第二套 WorldBible 或 Canon Graph。
- 正式 provider 输出必须经 `world.consequence.analyze`，保留 input WorldRule / WorldBible version、provider receipt、trace、qualification 和 evidence。
- Provider 结果只能成为 Candidate；语义激活属于 Story Design Authority，Canon 接受仍受 Canon Authority / Gate 管辖。
- 任何 conflict 必须成为 ReviewIssue / impact evidence，不能自动覆盖 Accepted Canon。

## 适用场景

- 推演世界规则对经济、政治、军事、基础设施、科技、宗教、教育、犯罪、阶层、地理、文化和世代的长期影响。
- 检查世界设定是否有系统性后果、制度是否会适应、受影响群体是否完整。
- 为 Outline / Arc / ChapterPlan 提供 story opportunity candidate，而不是补写新 Canon。

## 输入要求

- `project_id`、accepted WorldBible / WorldRule version 和 Canon refs。
- 分析范围、时间尺度、受影响群体、禁用项、Context Builder / MKAOS refs。
- Provider Runtime profile、trace context 和候选激活边界。

## 操作流程

1. 识别 WorldRule、约束、成本、资源流和适用群体。
2. 推导 DirectConsequence，再逐层推导 SystemicConsequence、CulturalConsequence 和 InstitutionalAdaptation。
3. 为每条边记录 AffectedGroup、前置 consequence、证据、反例和不确定性。
4. 检查图完整性、循环、悬空规则和与 Accepted Canon 的 contradiction。
5. 提取 StoryOpportunity，但保持 `CANDIDATE`，不写入 Canon 或 Active plan。
6. 通过 Story Design Authority 审核激活；冲突进入 ReviewIssue / Gate。

## 输出格式

```markdown
# World Consequence Candidate

## Source Rules
- world rule / asset version:

## Consequence Graph
- direct:
- systemic:
- cultural:
- affected groups:
- institutional adaptations:
- contradictions:

## Story Opportunities
- opportunity / consequence refs:

## Authority
- status: CANDIDATE
- activation required:
- trace / provider qualification:
```

## 质量标准

- 每个 consequence 必须能回溯到 WorldRule 或上游 consequence，不能凭空生成。
- affected group 和 institutional response 必须显式；图不得有跨项目或悬空引用。
- contradiction 与 opportunity 分开，候选状态和激活权限清晰。
- Provider 证据不等于 Canon 接受证据。

## 禁止事项

- 禁止重复实现 `worldbuilding`、WorldBible、Canon Graph、Context Builder 或 MKAOS。
- 禁止把 candidate 自动写入 Accepted Canon、StoryState 或 Active plan。
- 禁止复制外部作品的具体设定组合或受保护表达。
- 禁止因 provider 返回完整 JSON 就宣称 production / longform proof。

## 与其他模块的关系

- 上游：WorldBible、WorldRule、Accepted Canon、AssetVersion、Context Builder、MKAOS。
- 下游：Story Design Authority、Outline、ChapterPlan、ReviewIssue、Canon impact report。
- 关联 Skill：`worldbuilding`、`canon-continuity-graph`、`multidisciplinary-knowledge`。
