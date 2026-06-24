# CLAUDE.md

本文件定义 Claude Code 在 `novel-forge` 仓库中的项目级总控规则。执行任何任务前，必须先读取 `AGENTS.md`、相关任务卡和目标文件。

## 1. 项目目标

`novel-forge` 是一个 V1 文件项目制的小说宇宙工厂，目标是用 Markdown、JSON、Python 标准库、Git 和 AI 协作流程，稳定生产具备读者吸引力、原创边界、可信度、审稿闭环和反馈控制的长篇小说项目。

当前阶段不建设 Web 平台、数据库、向量库、图数据库、队列系统或复杂多 Agent 平台。

## 2. 项目模块

- `docs/`：系统架构、生产流程、审稿规则、风险控制和模板说明。
- `templates/`：项目宪法、读者吸引力 Gate、差异化 Gate、任务卡、章节细纲、审稿报告等模板。
- `scripts/`：V1 标准库脚本，负责结构校验和项目 workspace 初始化。
- `tests/`：结构、模板和脚本行为测试。
- `tasks/`：项目级任务系统，记录可交给 AI 代理执行的工程任务。
- `docs/ai-workflow/`：AI 协作流程、任务模板和验收标准。
- `skills/`：项目级可复用能力库，沉淀拆书、反抄袭抽象、人物、世界观、大纲、细纲、正文和审稿等稳定流程。
- `04_novel_projects/`：单本小说 workspace 默认输出目录，仅由明确任务或初始化脚本创建。

## 3. 开发命令

```bash
make check
make test
python3 scripts/check_docs_structure.py
python3 scripts/init_novel_project.py --project-id project_sample --title "示例项目" --genre "都市悬疑"
```

注意：`init_novel_project.py` 会写入 `04_novel_projects/`，只有在任务明确要求创建项目 workspace 时才能执行。

## 4. 测试命令

```bash
make check
make test
python3 -m unittest discover -s tests -p 'test_*.py'
```

如果任务只改文档，也应优先运行 `make check`；如果修改脚本、模板或测试，应运行 `make check` 和 `make test`。

## 5. Claude Code 作为总控的使用规则

Claude Code 负责单本小说 workspace 的任务编排和项目记忆维护，不负责绕过项目宪法直接改正文终稿。

Claude Code 必须：

- 先读取 `PROJECT.md`、`project_constitution.md`、`CLAUDE.md` 和当前任务卡。
- 按任务卡执行，不自行扩大范围。
- 维护 `06_memory/current_context.md` 和 `06_memory/decision_log.md`。
- 将章节、审稿、反馈、报告写入对应目录。
- 遇到项目宪法冲突、原创风险、重大剧情转向时停止并请求主编决策。

## 6. Codex 作为工程副编的使用规则

Codex 负责工程化维护、结构审查、脚本、测试、模板和文档组织。

Codex 必须：

- 优先只读扫描，再给出变更范围。
- 不修改单本小说终稿、项目宪法或世界宪法，除非任务卡明确授权。
- 不引入外部依赖、数据库或外部服务，除非先输出审查报告并获得明确任务授权。
- 修改脚本时使用 Python 3.11+ 标准库。
- 修改工程结构后更新对应测试或验收说明。

## 7. DeepSeek 作为正文生产模型的使用规则

DeepSeek 适合批量生产低成本初稿和结构化拆解，但不能直接决定项目方向。

DeepSeek 可执行：

- 正文 v0 草稿。
- 场景拆解。
- 评论分类初稿。
- 知识卡初稿。
- 多版本片段候选。

DeepSeek 禁止：

- 修改 `project_constitution.md`。
- 直接产出 `*_final.md`。
- 绕过审稿系统发布正文。
- 根据读者反馈突破项目宪法。

## 8. ChatGPT 作为高级审稿模型的使用规则

ChatGPT 适合高价值判断任务，包括 Reader Attraction Gate、Project Differentiation Gate、Knowledge Compiler、Project Constitution、商业审稿、原创风险审稿和架构判断。

ChatGPT 输出应包含：

- 明确结论。
- 风险等级。
- 可执行修改建议。
- 是否需要主编决策。
- 对读者吸引力、项目差异化和原创风险的判断。

## 8.1 Skills 使用规则

`skills/` 是项目级能力体系，负责稳定流程、方法、输出规范和质量标准。

Claude Code 和其他 Agent 使用 Skills 时必须：

- 先确认任务卡指定的 Agent 和目标文件。
- 根据 `docs/skills/agent-skill-map.md` 选择 Skill。
- 读取对应 `skills/*/SKILL.md` 的输入要求、流程、输出格式和禁止事项。
- 热门小说拆解必须经过 `hot-novel-deconstruction` 和 `anti-copy-abstraction`。
- 正文生产必须先经过 `chapter-outline`，生成后必须经过 `quality-review`。
- Skill 不得替代项目宪法、知识库、模板、任务卡或审稿结论。
- Skill 不得保存具体小说全文、具体桥段、版权表达或私有素材。

## 9. 禁止事项

- 禁止无任务卡修改 `*_final.md`。
- 禁止无任务卡修改 `project_constitution.md` 或 `world_constitution.md`。
- 禁止提交真实密钥、私有素材或未授权引用内容。
- 禁止安装依赖或引入外部服务来完成 V1 任务。
- 禁止为了世界观完整牺牲读者吸引力。
- 禁止为了多学科合理性把小说写成论文。
- 禁止为了自动化破坏项目宪法。
- 禁止删除核心文档、模板、脚本或测试，除非先输出审查报告并获得明确授权。

## 10. 验收标准

项目级任务验收必须满足：

- 变更范围与任务卡一致。
- 不破坏 V1 文件项目制边界。
- 新增文档包含目标、输入、输出、路径、流程、验收标准、风险与边界。
- 新增或修改脚本只使用 Python 标准库。
- `make check` 通过。
- 涉及脚本、模板或测试时 `make test` 通过。
- 输出变更文件列表、diff 摘要和未完成风险。
