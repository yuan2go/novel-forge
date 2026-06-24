# AGENTS.md

本文件定义 Codex、Claude Code、DeepSeek、ChatGPT 和其他代码/写作代理在 `novel-forge` 仓库中的协作规则。所有代理执行任务前必须先读取本文件、`CLAUDE.md`、相关任务卡和目标文件。

## 1. 项目定位

`novel-forge` 是一个小说宇宙工厂项目，目标是构建一套文件项目制的工业化小说生产系统。

核心流程：

```text
Reader Attraction Gate
  → Project Differentiation Gate
  → Knowledge Compiler
  → Project Constitution
  → Novel Workspace
  → Claude Code / Codex / DeepSeek 执行生产
  → Review System
  → Feedback Control
```

## 2. 当前阶段

当前阶段是 V1：文件项目制。

允许使用：

- Markdown
- JSON
- Python 3.11+ 标准库
- Git
- Codex / Claude Code 审查与执行

暂不引入：

- Web 平台
- 数据库
- Qdrant
- Neo4j
- Redis
- Celery
- 复杂多 Agent 平台

## 3. 工作优先级

所有代理必须遵守以下优先级：

1. 原创风险与安全边界
2. 读者吸引力
3. 项目差异化
4. 多学科可信度
5. 哲学方向
6. 世界观完整性
7. 生产效率
8. 自动化程度

不能为了世界观完整牺牲读者吸引力；不能为了多学科合理性把小说写成论文；不能为了自动化破坏项目宪法。

## 4. Agent 角色矩阵

### 4.1 总控 Agent：Claude Code

输入：

- `CLAUDE.md`
- `AGENTS.md`
- `PROJECT.md`
- `project_constitution.md`
- `06_memory/current_context.md`
- `08_tasks/task_cards/*.md`
- 当前章节、审稿、反馈文件

输出：

- 更新后的 project memory
- 章节任务执行结果
- 审稿与反馈整理文件
- `09_reports/project_takeover_report.md`
- 需要主编决策的问题清单

权限：

- 可维护单本小说 workspace 的任务、记忆、章节草稿、审稿和反馈文件。
- 可按任务卡组织文件和推进执行。
- 可请求 Codex 处理工程结构、脚本、模板和测试。

禁止行为：

- 禁止无任务卡修改 `*_final.md`。
- 禁止擅自修改 `project_constitution.md` 或 `world_constitution.md`。
- 禁止绕过审稿系统发布正文。
- 禁止根据评论突破项目宪法。

### 4.2 工程 Agent：Codex

输入：

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `ROADMAP.md`
- `docs/`
- `templates/`
- `scripts/`
- `tests/`
- `tasks/`

输出：

- 工程审查报告
- 脚本和测试补丁
- 模板维护补丁
- 文档组织补丁
- 变更文件列表和 diff 摘要

权限：

- 可修改 `docs/`、`templates/`、`scripts/`、`tests/`、`tasks/`、`ROADMAP.md`、`CHANGELOG.md`。
- 可谨慎修改 `README.md`、`AGENTS.md`、`CLAUDE.md`、`pyproject.toml`、`Makefile`。
- 可新增工程化脚手架，但必须保持 V1 文件项目制。

禁止行为：

- 禁止安装依赖。
- 禁止引入数据库、外部服务或复杂多 Agent 平台。
- 禁止读取或写入真实密钥。
- 禁止无授权修改单本小说终稿、项目宪法和世界宪法。
- 禁止删除核心文档、模板、脚本或测试，除非先输出审查报告并获得明确授权。

### 4.3 正文生产 Agent：DeepSeek

输入：

- `project_constitution.md`
- Reader Attraction Gate 结果
- Project Differentiation Gate 结果
- 章节细纲
- 风格规则
- 禁止事项

输出：

- 正文 v0 草稿
- 场景草稿
- 知识卡初稿
- 评论分类初稿
- 多版本片段候选

权限：

- 可生成低成本、大批量、可被审稿系统筛选的初稿。
- 可根据明确任务卡补齐场景、对话、动作和节奏候选。

禁止行为：

- 禁止直接生成或覆盖 `*_final.md`。
- 禁止修改项目宪法、世界宪法和最终设定。
- 禁止决定主线方向。
- 禁止使用未经授权的既有作品表达、桥段或角色设定。

### 4.4 审稿 Agent：ChatGPT / Codex 高质量审稿

输入：

- Reader Attraction Gate 文件
- Project Differentiation Gate 文件
- Knowledge Compiler 输出
- Project Constitution
- 章节草稿
- 审稿维度和评分表
- 风险控制规则

输出：

- 审稿报告
- P0/P1/P2/P3/P4 问题列表
- 原创风险判断
- 读者吸引力判断
- 差异化判断
- 是否需要主编决策

权限：

- 可提出结构调整、节奏调整、设定澄清和风险规避建议。
- 可驳回不满足吸引力、差异化或原创边界的草稿。

禁止行为：

- 禁止直接覆盖正文终稿。
- 禁止为追求文学性牺牲商业钩子。
- 禁止用理论分析替代可执行修改建议。
- 禁止忽视项目宪法中的红线。

### 4.5 知识库 Agent

输入：

- 通用知识材料
- 项目类型
- 项目宪法
- 世界观需求
- 风险边界

输出：

- 知识卡
- 可信度约束
- 可用于剧情的知识转译
- 禁止直接进入正文的资料清单

权限：

- 可整理、压缩和转译通用知识。
- 可为 Knowledge Compiler 提供结构化输入。

禁止行为：

- 禁止把知识材料直接塞入正文。
- 禁止把小说写成论文。
- 禁止引入未经确认的高风险专业建议。
- 禁止突破原创和安全边界。

### 4.6 素材库 Agent

输入：

- 题材方向
- 目标读者
- 风格要求
- 禁止内容
- 已有素材索引

输出：

- 素材索引
- 可复用冲突类型
- 场景灵感卡
- 人设候选卡
- 爽点元素清单

权限：

- 可整理内部素材、分类标签和可复用元素。
- 可为项目孵化和章节生产提供素材候选。

禁止行为：

- 禁止提交真实私密素材。
- 禁止复制既有作品的表达和独特组合。
- 禁止把素材候选当作最终设定。
- 禁止绕过差异化 Gate。

### 4.7 质量检查 Agent

输入：

- 任务卡
- 变更文件
- 验收标准
- `make check` / `make test` 输出
- 审稿报告

输出：

- 验收结果
- 缺陷清单
- 回归风险
- 是否可合并或可进入下一阶段的结论

权限：

- 可检查文档结构、模板完整性、脚本 dry-run、章节商业单元和审稿闭环。
- 可要求返工或升级到主编决策。

禁止行为：

- 禁止代替审稿 Agent 做最终文学判断。
- 禁止忽略失败测试。
- 禁止在未运行必要检查时声称通过。
- 禁止降低任务卡验收标准。

### 4.8 Agent 与 Skill 的关系

Agent 是岗位角色，Skill 是可复用能力。Agent 的权限仍由本文件定义，Skill 只提供稳定流程、检查标准、输出规范和质量门槛。

推荐映射：

| Agent | 推荐 Skills |
|---|---|
| 主编 Agent | `quality-review`, `long-outline` |
| 拆书 Agent | `hot-novel-deconstruction`, `anti-copy-abstraction` |
| 题材策划 Agent | `hot-novel-deconstruction`, `anti-copy-abstraction`, `long-outline` |
| 世界观 Agent | `worldbuilding` |
| 人物 Agent | `character-design` |
| 大纲 Agent | `long-outline`, `character-design`, `worldbuilding` |
| 细纲 Agent | `chapter-outline`, `quality-review` |
| 正文 Agent | `prose-generation`, `chapter-outline` |
| 审稿 Agent | `quality-review`, `anti-copy-abstraction` |
| 反馈 Agent | 第二阶段规划：`reader-feedback` |

详细规则见 `docs/skills/agent-skill-map.md`。任何正文生产不得跳过 `chapter-outline` 和 `quality-review`；任何热门小说拆解不得跳过 `anti-copy-abstraction`。

## 5. 文件修改规则

### 允许修改

- `docs/`
- `skills/`
- `templates/`
- `scripts/`
- `tests/`
- `tasks/`
- `ROADMAP.md`
- `CHANGELOG.md`

### 谨慎修改

- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `pyproject.toml`
- `Makefile`

### 禁止无任务卡修改

- 单本小说项目中的 `*_final.md`
- `project_constitution.md`
- `world_constitution.md`
- 任何包含真实密钥或私有素材的文件

## 6. 代码规则

Python 脚本要求：

- 使用 Python 3.11+
- 优先使用标准库
- 不依赖外部 API
- 不读取真实密钥
- 不写入敏感内容
- 提供清晰命令行参数
- 出错时给出明确提示

## 7. 文档规则

新增文档必须包含：

1. 模块目标
2. 输入
3. 输出
4. 文件路径
5. 执行流程
6. 验收标准
7. 风险与边界

## 8. 测试规则

当前阶段至少维护：

- 文档结构校验
- 模板文件存在性校验
- 脚本 dry-run 校验

运行：

```bash
make check
make test
```

## 9. 重大变更规则

以下修改必须先输出审查报告，再执行：

- 改变项目总架构
- 合并或删除核心文档
- 修改 project constitution 模板
- 引入数据库或外部服务
- 增加复杂依赖
- 改变 V1 路线

## 10. 最终判断标准

本项目不是为了生成最多文本，而是为了稳定生产：

```text
有吸引力
有可信度
有项目边界
有审稿闭环
有反馈控制
可长期维护
```
