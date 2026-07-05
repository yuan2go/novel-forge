# Novel OS Skill Selection Log

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：本轮自主 Skill 发现、阅读、采用和风险判断。  

| 阶段 | 使用 Skill | 来源 | 使用原因 | 读取的 Skill 文件 | 是否安装新 Skill | 风险判断 | 实际产出 |
| -- | -------- | -- | ---- | ------------ | ----------- | ---- | ---- |
| Skill 发现 | `skill-governance` | 项目 `skills/` | 判断项目源 Skill 与 runtime copy 的治理边界 | `skills/skill-governance/SKILL.md` | 否 | 低；只读 | 确认不直接修改 `.claude/skills/`，报告记录 Skill 来源 |
| 工程扫描 | `novel-os-engineering-audit` | 项目 `skills/` | Novel OS 工程审计的本地业务约束最匹配 | `skills/novel-os-engineering-audit/SKILL.md` | 否 | 低；只读 | 形成 codebase map、architecture audit、risk register |
| 计划治理 | `project-planning` | 项目 `skills/` | 将审计结果拆为 P0/P1/P2 执行计划 | `skills/project-planning/SKILL.md` | 否 | 低；只读 | 输出优化计划和执行日志 |
| Agent 循环 | `agent-loop-governance` | 项目 `skills/` | 检查 AgentRun、scheduler、checkpoint、gate、budget | `skills/agent-loop-governance/SKILL.md` | 否 | 低；只读 | Agent audit 和 Agent optimization plan |
| Context/RAG | `context-builder-source-isolation` | 项目 `skills/` | 验证 Context Builder 与 source isolation 是否是主路径 | `skills/context-builder-source-isolation/SKILL.md` | 否 | 低；只读 | Functional inventory 和 architecture audit |
| MKAOS | `mkaos-knowledge-asset-os` | 项目 `skills/` | 检查多学科知识资产系统与生产链路 | `skills/mkaos-knowledge-asset-os/SKILL.md` | 否 | 低；只读 | MKAOS 风险进入临时方案登记 |
| Provider | `provider-runtime-policy` | 项目 `skills/` | 审计 provider、license、subprocess、network 边界 | `skills/provider-runtime-policy/SKILL.md` | 否 | 低；只读 | Provider hard-stop 风险进入 P0/P1 路线 |
| Continuity | `canon-continuity-graph` | 项目 `skills/` | 审计 Canon/Character/Foreshadowing/Arc 闭环 | `skills/canon-continuity-graph/SKILL.md` | 否 | 低；只读 | Data model audit 和 Agent target structure |
| Publish | `publish-release-gate-os` | 项目 `skills/` | 审计 publish release gate 和 rollback | `skills/publish-release-gate-os/SKILL.md` | 否 | 低；只读 | Publish 模块边界风险和计划 |
| ReviewIssue | `review-issue-gate` | 项目 `skills/` | 保证审稿、发布、MKAOS gate 使用统一阻断对象 | `skills/review-issue-gate/SKILL.md` | 否 | 低；只读 | ReviewIssue 风险项和 acceptance 标准 |
| 通用仓库审计 | `analyze-project` | 全局 `/Users/yuan/.agents/skills` | 仓库结构、入口、测试和配置盘点 | `/Users/yuan/.agents/skills/analyze-project/SKILL.md` | 否 | 低；只读 | 顶层目录和大文件扫描 |
| 架构设计 | `codebase-design` | 全局 `/Users/yuan/.agents/skills` | 模块边界、deep module、拆分策略 | `/Users/yuan/.agents/skills/codebase-design/SKILL.md` | 否 | 低；只读 | Target architecture 和拆分路线 |

## 未安装新 Skill

本轮本地项目 Skill 已足够覆盖 Novel OS 工程审计、Agent 运行、Context、MKAOS、Provider、Canon、Publish 和 ReviewIssue。没有访问第三方 Skill 仓库，也没有执行未知 Skill 脚本。

