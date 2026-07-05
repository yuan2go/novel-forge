# Novel OS Skill Selection Log

审计日期：2026-07-05  
基线 commit：`8733acf`
本轮继续治理基线 commit：`2f1f0bc`
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
| 第二轮 Agent operation | `agent-loop-governance` | 项目 `skills/` | Longform Recap 必须进入 AgentRun/dispatch/checkpoint 证据链 | `skills/agent-loop-governance/SKILL.md` | 否 | 低；只读 | `run-longform-recap` 改为 Longform Recap Agent operation 并补 scheduler 测试 |
| 第二轮 Provider/Eval | `provider-runtime-policy` | 项目 `skills/` | Provider hard-stop 不得 silent fallback，Eval/Publish 需阻断缺失证据 | `skills/provider-runtime-policy/SKILL.md` | 否 | 低；只读 | EvaluationGate/PublishGate 接入 provider runtime policy |
| 第二轮 Publish | `publish-release-gate-os` | 项目 `skills/` | 发布入口必须通过 schema-backed gate 和 release facade | `skills/publish-release-gate-os/SKILL.md` | 否 | 低；只读 | 生产调用迁移到 `modules.publishing` facade |
| 第三轮 Agent operation | `agent-loop-governance` | 项目 `skills/` | Platform Compliance / Training 需要从 runtime profile 升级到可调度 operation | `skills/agent-loop-governance/SKILL.md` | 否 | 低；只读 | 新增 `create-platform-strategy-pack`、`generate-training-exercise` Agent operation 和 scheduler 测试 |
| 第三轮 Provider/Eval | `provider-runtime-policy` | 项目 `skills/` | Provider gate 需要同时证明 hard-stop 失败路径和成功调用路径 | `skills/provider-runtime-policy/SKILL.md` | 否 | 低；只读 | provider evidence status 要求成功 guard/model_call，补 production publish success fixture |
| 第三轮 Publish | `publish-release-gate-os` | 项目 `skills/` | Release package 不能只依赖 publish gate decision，需自校验证据路径和状态 | `skills/publish-release-gate-os/SKILL.md` | 否 | 低；只读 | Release package 自检 EvaluationGate、ProviderRuntimeGate、PlatformStrategyGate |
| 第四轮大 service 拆分 | `codebase-design` | 全局 `/Users/yuan/.agents/skills` | 选择先抽公共只读 seam，而不是直接改私有实现细节 | `/Users/yuan/.agents/skills/codebase-design/SKILL.md`、`/Users/yuan/.agents/skills/codebase-design/DEEPENING.md` | 否 | 低；只读 | 新增 `asset_scan`、`mkaos.asset_index`、`product_asset_index`、`workflow_nodes.query` |
| 第四轮测试保护 | `tdd` | 全局 `/Users/yuan/.agents/skills` | 先写 characterization tests，再拆 service 和治理 broad exception | `/Users/yuan/.agents/skills/tdd/SKILL.md`、`/Users/yuan/.agents/skills/tdd/tests.md` | 否 | 低；只读 | 新增 `tests/unit/test_asset_scan_seams.py` 并跑 focused regression |
| 第五轮 Release/Scheduler | `tdd` | 全局 `/Users/yuan/.agents/skills` | 先补 release package 正向 fixture 和 scheduler runner 红测，再修实现 | `/Users/yuan/.agents/skills/tdd/SKILL.md`、`/Users/yuan/.agents/skills/tdd/tests.md` | 否 | 低；只读 | 新增 production-ready release fixture、scheduler production policy test |
| 第五轮 Runner seam | `codebase-design` | 全局 `/Users/yuan/.agents/skills` | 按 deep module seam 拆出 scheduler publishing runner，不扩大 registry 接口 | `/Users/yuan/.agents/skills/codebase-design/SKILL.md`、`/Users/yuan/.agents/skills/codebase-design/DEEPENING.md` | 否 | 低；只读 | 新增 `agent_scheduler.publishing_runners`，audit reference lookup 接入 `core.asset_scan` |
| 第六轮 Scheduler/Publishing seam | `codebase-design` | 全局 `/Users/yuan/.agents/skills` | 继续按 deep module 思路拆 queue lifecycle，并把 release gate evidence 迁入 publishing 边界 | `/Users/yuan/.agents/skills/codebase-design/SKILL.md`、`/Users/yuan/.agents/skills/codebase-design/DEEPENING.md` | 否 | 低；只读 | 新增 `agent_scheduler.queue_lifecycle`、`publishing.release_gate` |
| 第六轮 回归保护 | `tdd` | 全局 `/Users/yuan/.agents/skills` | 使用既有 characterization/focused regression 验证拆分不改变 scheduler/publishing/workflow/product 行为 | `/Users/yuan/.agents/skills/tdd/SKILL.md`、`/Users/yuan/.agents/skills/tdd/tests.md` | 否 | 低；只读 | 99 个 scheduler/publishing/workflow/product/seam focused tests 通过 |
| 第七轮 Scheduler/Publishing seam | `codebase-design` | 全局 `/Users/yuan/.agents/skills` | 继续拆 registry/dead-letter，并把 release package 主实现从 audit 迁到 publishing | `/Users/yuan/.agents/skills/codebase-design/SKILL.md`、`/Users/yuan/.agents/skills/codebase-design/DEEPENING.md` | 否 | 低；只读 | 新增 `agent_scheduler.operation_registry`、`agent_scheduler.dead_letter_runner`，release package 主实现迁入 publishing |
| 第七轮 回归保护 | `tdd` | 全局 `/Users/yuan/.agents/skills` | 通过公共 scheduler/publishing/release seam 验证迁移，不测试私有实现细节 | `/Users/yuan/.agents/skills/tdd/SKILL.md`、`/Users/yuan/.agents/skills/tdd/tests.md` | 否 | 低；只读 | 37 个 focused tests 与第二批 99 个 focused tests 通过 |

## 未安装新 Skill

本轮本地项目 Skill 已足够覆盖 Novel OS 工程审计、Agent 运行、Context、MKAOS、Provider、Canon、Publish 和 ReviewIssue。没有访问第三方 Skill 仓库，也没有执行未知 Skill 脚本。
