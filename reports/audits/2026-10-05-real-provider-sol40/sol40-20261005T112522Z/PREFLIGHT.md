> 历史启动准入快照：下文的旧题材、pending预算和high问题是当时状态。作者v2已改为玄幻轻喜剧；最新预算、路由和剩余准入见 [预算与路由记录](budget-authorized-v1/REPORT.md)。原始记录保留，不作为当前运行Authority。

# 40章真实 Provider 与连续稿验证：启动准入记录

状态：**BLOCKED**。本记录是启动准备与准入证据，不是已完成作品、REAL_CAPTURE、REAL_RUN或文学质量证明。

- 冻结代码 SHA：`b710aeec29eb06ca9ca560863a82e7736a7596cc`；分支 `codex/work-intent-context-e2e-20261005`。
- 项目：`nf-sol40-20261005T112522Z`；预定 Book：`nf-sol40-20261005T112522Z-book`。
- 作品作者输入：暂定名《潮灯藏火》，原创仙侠；40章，每章正文5000–6000汉字，计量为 `HAN_CHARACTERS_V1`（不计标点、数字、空白和拉丁字符）。暂定世界与人物属于 AI_ASSISTED_AUTHOR_INPUT，尚非获批 Foundation、Planning 或 Canon。
- 指定 Provider/model/reasoning：`codex-cli / gpt-6-sol / medium`。用户已授权真实验证与章节范围；1600次调用、8000万Token仍为提案，未登记为原生预算授权。
- Provider 实际调用 **0**；已接纳 **0/40**；尚无真实连续稿。

## 已完成且有证据的准备

1. 找到已有可用执行器，CLI 0.155.1；本地 `login status` 显示 ChatGPT 登录。这只证明本地进程/登录状态，不证明远端模型请求、账户续航或运行资格。全局PATH上的CLI缺少二进制，未覆盖其安装。
2. 使用任务独占、持久化的 pgvector PostgreSQL 容器，正常运行全部当前 migrations；既有数据库和生产服务未修改。容器/卷/端口见 `resources.json`。
3. 作者输入通过 Project Authority / Content Authority 登记；随后从正式 `scripts.run_creation_synthesis --register-input-only` 入口重复执行，返回同一精确资产与hash。见 `native-author-input-receipt.json`、`official-author-entry.json`。
4. 使用既有 `creation_freeze.prepare_freeze` 冻结作者输入、creation/Formation policy和DENY_ALL知识边界。原始manifest字节hash为 `sha256:4b21599e1fc49e2713f2d47485835ccccff931fd336ebfb649ec58e1c3ac5de7`；复制件仅用于审计，后续运行沿用runtime中的原冻结目录。
5. 通过真实 `build_production_execution_composition` 构造启用 Router 的受控配置，未替换路由器、registry observations或Provider。该次构造使用明确标为提案的预算值与 `PENDING-BUDGET-CONFIRMATION` 本地身份，只用于OFFLINE装配检查；没有配置原生grant、编译/批准Pack、调用dispatch或生成结果。
6. PostgreSQL中ExternalEffect、Dispatch、Receipt均为0。原用户工作区的HEAD、分支和未跟踪文件列表逐项相同；代码和公共配置未修改。

## 实际阻断与控制权

- **medium 被覆盖**：正式装配输入 `NOVEL_FORGE_REASONING_EFFORT=medium`、`NOVEL_FORGE_PLANNING_REASONING_EFFORT=medium`，但Codex-only Router把基础reasoning写成high，候选亦固定high；Draft及正式候选不能满足本次作者授权。见 `formal-composition-preflight.json`，实现位于 `src/novel_forge/api/authority_dependencies.py` 的Codex Router模板与候选构造。不得以high实际运行后宣称medium。
- **独立审读 Provider**：当前 `cross_model_review.COUNTERPART` 规定Codex→DeepSeek。独立OFFLINE policy例对同一Codex reviewer返回 `CROSS_MODEL_REVIEW_DIFFERENT_PROVIDER_REQUIRED`；该例不是生成receipt或实际Review产物。正式 `freeze_review_requirement` 和Router继续执行此限制，作者监督也保留它。正文模型不需要替换，但完整接纳闭环需要审读方授权、预算和资格。
- **有限预算待确认**：正式 `validate_configuration` 与 `authorize_execution` 要求受控账户身份和正数的项目调用/Token限制；账户可用额度与40章范围不能替代累计grant。预算提案包括规划、资格验证、正文、审读、修订、压缩及恢复；达到上限、quota或UNKNOWN均停止/核对，不能改项目或调用键重置。
- **真实资格未验证**：不写入fixture calibration、受控cohort或模型自评为真实资格。必须先检查真实 task/Producer/model/revision的独立评估与资格来源；预算确认和Provider返回成功本身都不放行Quality。

## 参考作品与版本安全

参考标题来自用户：《苟在女魔头身边偷偷修炼》。尝试读取起点书籍页（https://book.qidian.com/info/1033280302/）得到403；未获取或阅读原书全文，保留 `SOURCE_IMPORT_PENDING`。没有从非正式网站下载文本、生成原书拆解或建立Source/KnowledgeCard。当前原创方向采用低调积累、谨慎决策和信息差等通用机制，是明确标注的AI辅助作者提案；参考标题仅在档案中保留，不进入模仿指令，原文、人物组合和可识别情节不进入Draft。

冻结输入选择新生产合同并保留作者范围/来源hash。未复用旧作品、旧预算或历史审计的生产资格；未启动章节运行，因而不能声称attempt/accepted baseline绑定已在真实稿件中成立。

## 后续恢复

原native输入、幂等键、runtime、数据库和冻结目录均保留。预算与独立审读授权答复之后，先处理Codex medium路由并完成适用回归，再核对真实资格与正式Pack批准，才可发出第一笔真实请求。新运行版本必须另行冻结实际SHA，不把本次失败前置检查改写为PASS。后续十章边界按已冻结reading checkpoints `[10,20,30,40]` 审阅真实接纳文本；AI审阅保持AI_EDITORIAL_REVIEW，不冒充独立人工评价。全部40章接纳及状态核对完成前，连续稿验证保持未完成。

运行目录：`/Users/yuan/.local/share/novel-forge/runs/sol40-20261005T112522Z`。没有push、PR、部署、quota reset或自动付费API fallback。证据等级仅STATIC/OFFLINE；真实Provider、文学质量和长期运行均NOT_VERIFIED。
