# 首本长篇试生产：本地操作入口

工作树：/Users/yuan/projects/novel-forge-first-novel-pilot（本地分支，未 push）。本文件是操作说明；业务权威仍为 PostgreSQL。

## 已完成的素材操作

打开 [素材目录](corpus/index.html)。20 个条目来自 4 部作品，分为 6 / 6 / 8 三批：
17 个 NWTC / LibreTexts 教材片段，及《铁路少年》《三十九级台阶》《血字的研究》英文原著。
原文、版本、hash、许可、原生 Job、处理与章节定位都保存在目录中。

专业资料有图表未解析的部分不进入首批；hydraulics-09 的 psi/kPa 矛盾单独隔离。
三部小说已通过精确边界和 MARK_NON_BODY → reprocess 排除前言/许可说明，
《血字的研究》为两卷各七章。完整性仍为 UNKNOWN，不能据此声称版本无缺。
[问题清单](corpus/issues.json)与失败操作均保留；未用新处理覆盖旧历史。

以下命令使用原生 CLI。包装器只加载本机私有环境并执行 CLI，不持有业务状态：

```bash
NF='/Users/yuan/projects/novel-forge-first-novel-pilot-evidence-20260912-a1661483/runtime/nf'
"$NF" corpus jobs --project-id first-novel-pilot-20260912 --run-key-prefix 'pilot-materials-' --limit 10
# 后页使用上页 next_after，保留相同筛选。
"$NF" corpus jobs --project-id first-novel-pilot-20260912 --status IMPORTED --limit 10
```

具体每项的 `import_job_id` / `processing_id` 见 [原生目录导出](corpus/catalogue-native-export.json)。
用原值替换下列变量：

```bash
"$NF" corpus status --project-id first-novel-pilot-20260912 --job-id "$JOB"
"$NF" corpus lineage --project-id first-novel-pilot-20260912 --job-id "$JOB"
"$NF" corpus inspect --project-id first-novel-pilot-20260912 --processing-id "$PROCESSING"
"$NF" corpus chapters --project-id first-novel-pilot-20260912 --processing-id "$PROCESSING" --limit 100
```

本地 API 地址是 http://127.0.0.1:51009。读取接口可用：

```bash
curl --noproxy 127.0.0.1 'http://127.0.0.1:51009/product/source-imports?project_id=first-novel-pilot-20260912&run_key_prefix=pilot-materials-&limit=10'
curl --noproxy 127.0.0.1 'http://127.0.0.1:51009/product/mkaos/knowledge-candidates?project_id=first-novel-pilot-20260912'
curl --noproxy 127.0.0.1 'http://127.0.0.1:51009/product/mkaos/knowledge-cards?project_id=first-novel-pilot-20260912'
```

API 仅监听回环地址，未启动 Source/Book worker。若停机，在工作树执行上述 `"$NF" serve-api --host 127.0.0.1 --port 51009`。
私有环境 `runtime/local-environment.json` 权限为 0600；不要复制到仓库、日志或共享包。

## 冻结范围与授权边界

[Source 分析计划](source-analysis-plan.json)绑定两个原生精选版本：
先 hydraulics-12（泄压阀），再 hydraulics-14 / 16（止回阀 / 流量控制）和
《铁路少年》第二至第七章；小说第一、八章为辅助上下文，不能计入目标覆盖率。
阅读预检已通过 MinIO 回读验证，仍为 NOT_SENT。

真实调用尚未授权。旧授权仅覆盖另一项目的《西游记》前三章 RESEARCH，
不得用于本包；其未知结果也未重试。待确认建议：
Codex CLI、gpt-6-astra / xhigh、账户引用 /Users/yuan/.codex-claude、
ACCOUNT_ENTITLEMENT、仅本包 Source / 设计 / A+B 各六章 / 审稿与恢复。
总上限 480 次、12,000,000 可观测 Token、并发 1；金额与不可观测 CLI 开销 UNKNOWN，
不改用付费 API。这份说明和任意 authorization_ref 都不授予额度。

子额度总和不超过共享总额：
Source 60 / 1,500,000（小样 10 / 250,000；下一批 50 / 1,250,000），
A 180 / 4,500,000，B 180 / 4,500,000，恢复修复 60 / 1,500,000。
两个项目分别固定绝对上限 A+Source=270 / 6,750,000、B=210 / 5,250,000，
各含一半恢复额度；不能互相复制总额度、自动转移或新建项目重置用量。
Source D0 在原 extraction operation 上执行并消费原 Source 额度，不另起免费调用。

授权到位后，先按原运行手册配置同一真实 Codex 路线与精确账户快照，
重新执行 reading-preview，然后仅 admit 小样：

```bash
"$NF" corpus analyze --project-id first-novel-pilot-20260912 \
  --revision-id corpus-curated-revision:d7202836d9753903ba45e9f8ef3d4282696cdde7580f45c7c6cd92deee12bb10 \
  --reading-scopes '/Users/yuan/projects/novel-forge-first-novel-pilot-evidence-20260912-a1661483/corpus/canary-reading-scopes.json' \
  --intended-use ABSTRACT_GENERATION --target-book-id first-novel-pilot-a \
  --run-key first-novel-source-canary-v1 --limit 1 --max-calls 10 --max-tokens 250000 \
  --authorization-ref "$CONFIRMED_REF"
```
每次 `corpus run --max-stages 1`；用 `corpus results` 检查所有分页。
遇到 READY 的 MKAOS_EXTRACTION，沿现有
`scripts.run_real_provider_qualification --source-project-id ... --source-operation-id ...`
完成相同计量方式的资格回执与恢复检查。详见仓库 docs/runtime-operations.md，
不使用第二套 Provider 通道。

未知结果核对原 Effect / process receipt，不盲目重发；未完成任务可用
`corpus pause / resume / cancel --job-id ... --reason ...`，恢复使用原身份。
旧 failed reprocess / curation 是已被新版本解决的操作记录，不重新执行这些旧输入。

Candidate 出现后，逐个检查版本、原文位置、条件、例外和不确定性。
正式批准使用已有 `POST /product/mkaos/knowledge-candidates/{version}/approve`，
须由有权限审核者给出具体理由；AI 建议不等于独立人工批准。
HTTP 202 只表示受理：在同一私有环境与正确 worker principal 下运行已有
`python -m novel_forge.workers.mkaos_authority`，等待批准操作成功，再查询
`/product/mkaos/knowledge-cards` 获取正式 APPROVED Card 的精确 AssetVersion ID。
不能把 Candidate ID 或受理回执当成已批准 Card。当前 0 Candidate、0 Card。
本机同环境启动包装器为 `runtime/mkaos-worker`，它只执行该原生模块；当前未启动。
待实际审核命令提交后运行，处理完成用 Ctrl-C 正常停止。

## 原创长篇与十二章试生产

[frozen-pilot-final](frozen-pilot-final/freeze.json)保存原创可修改假设《雨线之外》：
山城汛期物资转运与记录悬疑，岑禾限知视角；长篇目标 180 章、三卷，
近期两组三章滚动细化。输入包括读者承诺、资源/知情/延迟兑现约束、
人物方向、风格与审稿要求，以及第三章后的未来改纲指令。
它们是创作输入，尚无原生 Formation/Opening/规划产物，不能称为已交付分层设计。

A 使用现有 Source 项目/主工作区：
first-novel-pilot-20260912 / first-novel-pilot-workspace / first-novel-pilot-a。
B 在独立项目/工作区创建：
first-novel-control-20260912 / first-novel-control-workspace / first-novel-pilot-b。
两书独立生成全部上层设计。A 尚无精确批准版本，因此没有伪造 ALLOW_ONLY 文件；
B 的 DENY_ALL 已冻结，保留其未来自身 Canon/记忆。

批准 Card 后，把真实 AssetVersion ID 数组保存成 JSON 文件，再将文件路径交给 helper：
```bash
cd '/Users/yuan/projects/novel-forge-first-novel-pilot'
PYTHONPATH=src:. .venv/bin/python -m scripts.prepare_knowledge_closure prepare \
  --input-dir config/production/first-novel-pilot --target-book-id first-novel-pilot-a \
  --approved-card-versions "$APPROVED_VERSIONS_FILE" --output "$NEW_FROZEN_A"
```

使用 `scripts.run_creation_synthesis`，传入 frozen brief / creation / formation、精确
knowledge-policy、独立 project/book/workspace、隔离 runtime root、稳定 run-key、
evidence-dir 和 expected-sha。仅在已确认真实额度时添加
`--initialize --execute --authorization-ref "$CONFIRMED_REF"`，其中引用必须与配置一致。
每次预览、执行或恢复使用新的、尚不存在的 evidence-dir；项目、Book、run-key、
runtime-root 和冻结输入保持原身份，不用新业务身份重置预算。
原生初始化现在能复用 Source 项目，不覆盖项目/素材或重置账本。
第三章后按 runner 返回的 Future PlanChange 入口修改未来范围，
保留前三章接纳版本；第六章关闭真实 ChapterGroup 后暂停，书仍未完。
B 配置预检结果见 [creation-b-config-preview](creation-b-config-preview/creation-run.json)。

原生导出保存原稿、诊断、修订、选择、正式接纳、状态和请求。
`chapter-groups.json` 验证真实两组执行血缘；
`knowledge-runtime-usage.json` 提供送达回执，结合 chapter workspace 和 knowledge trace
区分选择/送达/声明/正文核对；独立评审仍须另有真实评审证据。
任意卡可用 `authority-knowledge-trace --project-id ... --knowledge-card-asset-version-id ...`
追溯，传入真实版本和可选的 `--book-id`。
A 无实际送达及接纳正文体现时处理组无效，不能评价创作收益。

两组都实际接纳六章并导出完整证据后，运行
`scripts.prepare_knowledge_closure blind "$A_EXPORT" "$B_EXPORT" --output "$BLIND"`。
目前没有真实正文，只有空白七维评审表；盲评材料未生成，独立评审 NOT_REVIEWED。
不得将模型评分或本次工程测试当成人工阅读结论。

## 数据保留

保留两个本地 Docker 数据卷：
novel-forge-first-novel-pilot-data-pg16 与 novel-forge-first-novel-pilot-objects-data。
数据库名 novel_forge_first_novel_pilot_test 仅为满足现有隔离 runner 命名门禁；
它是本次素材业务数据，绝不能交给清库型 pytest。

[数据库备份](backup/corpus-pilot.pgcustom)和[对象备份](backup/immutable-objects.tar.gz)
保留历史、失败、审核及原文字节。对象迁移前后 359 个 key/字节/hash 完全一致。
备份未包含本机私有环境；恢复只允许到新建空库/桶，不能覆盖现有业务库。
已在临时空库完成一次恢复演练：187 个 Operation、379 个 ExternalEffect、
430 个 AssetVersion 数量一致，原生查询得到 20 项导入，精选原文 MinIO 回读校验通过。
临时库随后删除，见 backup/restore-verification.json。
