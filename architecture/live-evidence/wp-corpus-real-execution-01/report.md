# WP-CORPUS-REAL-EXECUTION-01 / R1

总体：**RUNTIME_BLOCKED**。本轮授权有效，真实调用已经发生；首章观察在本地超时，缺少远端最终结果和用量，按用户停止条件暂停。没有将分类成功或工程修复当作真实分析验收完成。

## 代码与执行身份

| 身份 | 完整 SHA |
|---|---|
| fetch 时 baseline / 结束时 origin/main | `16660337a0a2d8060e3aa778b274827779b637e0` |
| 首次真实执行 | `d754449c9eb13c1035e93f5ce8a2ed5e9eaf60a7` |
| 最终 implementation | `3d9153b427fdc55ee63673aa382ee9c5729db83f` |
| 最后适用测试 / status / evidence parent | `f41c61c654f7417f07b5ae9b3bb2175837fc9ff9` |

最终实现身份 `sha256:2b531528bd376286acb715bbc137fd70abdf6de86115089b45eab489ab43286a`。本文件及 evidence.json 所在提交是证据 HEAD；完整提交号同时记录在交付响应和 Git 外 final-git-state.json，避免自引用 SHA。main 未漂移。独立 worktree/分支保留；没有 push、PR 或 merge。原工作区保持 `1493d392e70665b4b77184fb14dde1ff1d678202`，干净未改。

- 实际 Codex：`/Users/yuan/.local/share/fnm/node-versions/v22.22.2/installation/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex`。
- 版本 `codex-cli 0.154.0`；摘要 `sha256:4f85982624b3898c8991cb80c0981b2aa71070e3537046c9a95950318a95afcc`。
- 第一 PATH 安装缺少 native package；沿正常 PATH 中第二个可用 npm wrapper 定位上述已有 binary，未升级安装。
- 当前环境实际 CODEX_HOME 为 `/Users/yuan/.codex-claude`；`login status` 返回 ChatGPT 登录。模型 `gpt-6-astra`、推理 `xhigh` 来自该目录 config.toml 的显式有效配置，无 profile、无第三方 Provider。
- Source 路由冻结账户目录、模型、推理、Schema 与计量身份。requested/invocation 均为 `gpt-6-astra`；返回 JSONL 未暴露独立 provider-observed model 或远端账户 ID，不能声称独立核实这两项。
- 受控空工作目录、忽略宿主配置/规则与 Skill 发现、无外部内容工具/MCP/hooks、返回工具检查均保留。六次日志未发现工具调用事件。未读取认证文件内容。

真实授权来自本轮用户“我授权使用这台 Mac 上现有、能够正常运行并已通过 ChatGPT 登录的 Codex CLI……”指令；原文、范围、18/240000 上限及停止条件保存在 Git 外 `r1/authorization.json`，摘要 `sha256:bb953946cb4037144ee4bfeaa76ce1ff96f5fdc1f005fcfa36c920608625df14`。预览中的 reference 不是授权证明；本轮会话授权已独立核对，无需再次确认账户目录或手填模型。

## 素材、预检与实际读取

复用原任务停机集群与对象，直接重启，没有第二次恢复或导入。项目 `wp-corpus-real-analysis-01`，工作区 `ws-corpus-real-analysis-01`，私有库 `corpus_real_execution`（127.0.0.1:52112）。schema `20260910_0128_corpus_operations`，129 项迁移，无 DDL。

采用 Gutenberg 23962《西遊記》，原文件 2264069 字节，SHA256 `af3c9e408c0c58595b666ed9981b6fa1e9343f4bbc78309b1cb0818c32fc1f58`。已核验 Edition/Processing/当前精选、研究用途、前三回顺序和六个对象字节/hash；具体 Authority 身份见 evidence.json 和原生 preflight。

- Processing：`corpus-processing:5a3968b6c14b0c799f126d560009b43b59c2c82a5055ccdc56f8ade919e1f67b`。
- 精选 revision：`corpus-curated-revision:365bc0c3dcf692b8ace2a9bab9f6e52c803d7d669a946ae486bafcbda0a536bb`。
- 阅读身份：`sha256:5dfb49f178b529844d20378ead896431461a2b291560456b4a02bb14a2711db3`。
- 三章标准化正文 65082 字节，六个 Chunk 含分隔空白共 65086 字节；无相邻章上下文。全本覆盖保持 UNKNOWN。
- 范围文件 hash：`4d191f81617d0a3307259cdb8d7f86ae7913208a04d7a63ab2e6bc40d04acc2a`。

原生 reading-preview 使用真实 Codex 路由，无模型探测调用。实际字节、工具约束、context 258400、输出预留 4096、共享预算和停止原因可查询；远端可用性由正常分类阶段确认。最终预览报告原超时 Effect 的阻断及新实现的实际进程时限；预览不是远端可用性保证。

分类三次各确认接收同一组三个短样本：Chunk 0 `[0,5998)`、Chunk 3 `[0,5998)`、Chunk 5 `[0,5999)`，去重 **17995 字节**，覆盖三回中的局部片段。样本 hash 与输入/执行资产绑定在 evidence.json，不用当前文本补造历史回执。首章观察装配 21936 字节，但没有确认返回，记 UNKNOWN。

| 章节 | 观察展开 | 完整章输入确认 | 审查 | 接受 |
|---|---|---|---|---|
| 第一回 | 已展开；超时待核对 | UNKNOWN | 未运行 | 未接受 |
| 第二回 | 未展开 | 未确认 | 未运行 | 未接受 |
| 第三回 | 未展开 | 未确认 | 未运行 | 未接受 |

完整章节**已确认 0/3、已审查 0/3、已接受 0/3**。分类片段读取不膨胀此分母；未展开不等于无发现。当前任务暂停，覆盖 incomplete，综合未展开。

## 六次真实调用及实际修复

| 调用 | 阶段 / 结果 | 已观测 token | 未计量保守预留 |
|---|---|---:|---:|
| 1 | v1 分类成功 | 21986 | 0 |
| 2 | v1 观察：HTTP 400，wire Schema 不接受 uniqueItems | UNKNOWN | 36392 |
| 3 | v2 分类成功 | 22023 | 0 |
| 4 | v2 观察：HTTP 400，enum/const 缺显式 type | UNKNOWN | 36392 |
| 5 | v3 分类成功 | 21896 | 0 |
| 6 | v3 观察：135 秒本地超时，无最终输出/usage | UNKNOWN | 36392 |

首次运行 SHA 为 d754449c…；v2 为 `240e12670c579de962f940700ca38682f3f2ea94`；v3 为 `913c465e65f26f0fefd1337c3124570dd297656e`。完整逐次 Operation/Attempt、输入 hash、命令 hash、process receipt 摘要和 SHA 见 [calls-final.json](r1/calls-final.json)。三次分类因冻结路由变化实际重新执行，均计入，不宣称缓存复用。

累计 **6/18 次**；已观测输入 64383、输出 1522，共 **65905 token**。reasoning 1051 已包含在输出内，不重复相加。三笔缺少 usage 的保守预留共 **109176**，总占用 **175081/240000**，剩余 **12 次 / 64919 token**，当前不可执行。隐藏 Codex 开销、货币成本 UNKNOWN；不是完整远端硬上限。首个失败历史记录 RELEASED 仍按已启动回执纳入累计，没有把历史 actual_tokens=0 当作真实零用量。

实际代码修复：

1. `production_execution/codex_configuration.py::codex_output_schema` 与 `backends.py::_prepare_payload`：版本化 wire projection 省略 Provider 不支持的 uniqueItems、为 enum/const 派生显式类型；保留 canonical Schema 的原有机械约束及双 hash。Source reading-preview 编译四类 Schema。符合 [OpenAI Structured Outputs 的子集约束](https://developers.openai.com/api/docs/guides/structured-outputs)，两次真实 HTTP 400 是本轮直接复现依据。
2. `backends.py::codex_protocol_failure`、`source_import/execution.py`：明确识别 invalid_json_schema 为协议拒绝，保留受限原始输出与回执；新版本冻结请求不能将失败误作瞬态重试。
3. `command_kernel/budget_runtime.py`：已启动、无用量的 Codex 调用保留预算；历史 RELEASED 通过既有 dispatch receipt 只读保守计数。Source 新请求与查询共享项目累计，不重写旧状态、不新增表。
4. `source_import/execution.py::_source_gateway_provider_result`：local-only timeout/cancel 无 usage 应为 UNKNOWN；预留单次 Codex 调用完整时限。旧配置 Effect 300 秒被两次尝试分割，实际仅 135 秒；新实现单次为 270 秒，保留 30 秒结算余量。**未用新时限再发真实调用**。
5. `curated_analysis.py::require_known_cli_outcomes`、`reading_scope.py`、`reading_evidence.py`、`source_import_operations_records.py`：将历史超时的 process receipt、准确装配 manifest、UNKNOWN 输入和共享余额呈现在原生查询；未核对时同时阻断原任务发送和新任务准入。启动前取消不列入未知推理；孤儿状态仍保守阻断。
6. `analysis_query.py::analysis_job`：暂停不能覆盖未知结果诊断，下一步优先 `RECONCILE_CLI_OUTCOME`。

当前 Operation `38e09dd1-eb47-4b9f-87ee-e5174baf426d` 为 WAITING_EXTERNAL_RESULT；原 Effect `b4f35df4-70b5-4aba-9b9c-263acef51ae2` 保留历史 FAILED_RETRYABLE。受限 receipt 为 `authority-asset-version:8210911a-05d2-43b6-b392-7f1633211c02`。stdout 只有开始事件和本地 feature 提示，没有输出、usage 或 provider_request_id；SIGTERM 仅证明本地停止。原生恢复检查没有再次调用，新请求也在创建前被阻断，没有人工伪造远端未执行事实。

## 拆解、审稿与知识

真实最新分类为 CLASSIC_LITERATURE，自报 confidence 0.995，证据等级 PROVIDER_UNCALIBRATED；这只支持路由分类，不是理解准确率。没有完成的逐章 Observation、跨章综合或定向语义修订，因此无法提供这些产物的真实实例或修订前后比较。

冻结基准 v1 hash `6fcd4ceef1fececa053c93434dc7d47a7089e9964c6af929d07767b62668a17a` 未改变，也未作为答案送入模型。8 项 Agent 检查（C1-ACTION、C1-CHOICE、C2-INFORMATION、C2-COST、C2-RESULT、C3-BELIEF、C3-ACTION、C3-INFORMATION）及 4 项负向控制（未来章、现实因果证明、普遍商业规律、复制迁移）全部 **UNKNOWN / 未评价**：没有叙事输出可对照。准确 Source span、预期、未评价理由在 Git 外 quality-review.json。

没有独立人工标注，不报告语义准确率/召回率；观察机械检查分母为 0，不报告通过率。工程 Schema 修复不冒充语义修订改善。尚不具备进入知识接受验证的条件。

原生 API 与数据库 Authority 查询一致：**Candidate 0 / Card 0 / Pack 0**。没有批准、生产消费、Canon 或正文写入。没有用名著先验、空 findings 或虚构机制补齐结果。

## 验证、资源与下一步

| tested SHA | 适用验证 |
|---|---|
| `240e12670c579de962f940700ca38682f3f2ea94` | 70 tests + 15 subtests；Codex/Source 契约、composition、真实 PostgreSQL 预算 |
| `913c465e65f26f0fefd1337c3124570dd297656e` | 37 tests；enum/const 与无模型 wire 编译 |
| `14cf7845dffe8a525234e83604cc6db573252a7e` | 50 tests + 10 subtests；未知 timeout/cancel、历史诊断、跨请求阻断 |
| `a3450d4e4a7c7b50e205743bab80edabb76a3e3f` | 2 tests；暂停下一步；原生 CLI/API 查询一致与受限 evidence 拒绝 |
| `f41c61c654f7417f07b5ae9b3bb2175837fc9ff9` | 1 PostgreSQL test + 3 subtests；启动前取消、已启动超时和孤儿结果区分；原生 status 仍阻断且累计 6 次 |

各行集合重叠，不合并计数或宣称全部在最终 SHA 重跑。每个变更阶段的 `make validate head-integrity-check` 均通过；脱敏 JUnit 在 r1/，命令、退出码和日志 hash 在 [evidence.json](evidence.json)。原生 run 恢复退出 3、新 analyze 拒绝退出 1；status/targets/results 退出 0。API 正常查询 200；未知输入、未发送 Chunk、跨项目 evidence 为 409。测试使用独立 PostgreSQL 库和受控 transport；真实账户未注入崩溃。未运行无关全仓/P0/UI、重复历史迁移或第二套恢复验证。

Git 外持久目录：`/Volumes/DevSSD/Development/Workspace/task-data/WP-CORPUS-REAL-EXECUTION-01/`。数据库与对象已备份为 `backups/corpus_real_execution-r1.dump`、`backups/objects-r1.tar.gz`，命令/退出码/hash 见 r1/backup-and-cleanup.json。470 个对象保留；原始模型返回、失败 stdout/stderr、原文和认证之外的配置保留在 Git 外。私有测试库已删除，任务 API/PG 和模型进程已停止，端口 53332/52112 关闭。

直接恢复查询：

```bash
cd /Volumes/DevSSD/Development/Workspace/projects/novel-forge-wp-corpus-real-execution-01
export CORPUS_RUN_ROOT=/Volumes/DevSSD/Development/Workspace/task-data/WP-CORPUS-REAL-EXECUTION-01
bash "$CORPUS_RUN_ROOT/start-database.sh"
source "$CORPUS_RUN_ROOT/r1/runtime.delivery.env"
export JOB=source-import:00693992-26dc-4564-b50b-9927b3aaf52c
.venv/bin/python -m novel_forge.cli.authority corpus status --project-id "$PROJECT" --job-id "$JOB"
.venv/bin/python -m novel_forge.cli.authority corpus results --project-id "$PROJECT" --job-id "$JOB" --limit 10
bash "$CORPUS_RUN_ROOT/stop-database.sh"
```

完整原生预览、targets/evidence/API 命令和恢复边界见 Git 外 **r1/NATIVE-OPERATIONS.md**。当前需要原超时调用可核对的远端最终状态/用量证据，再沿既有 reconciliation/人工决策处理；没有该证据不能盲目重发或直接改写历史。既有授权仍有效，真实模型远端身份未独立暴露、三章质量与候选谱系均尚未证明。

## 判定

| 项目 | 结果 |
|---|---|
| LOCAL_RUNTIME_RESTORATION | PASS |
| REAL_ROUTE_CONFIGURATION | PASS（invocation 已绑定；独立 observed model 未暴露） |
| REAL_EXECUTION_AUTHORIZATION | VERIFIED |
| NATIVE_REAL_ANALYSIS | BLOCKED |
| ACTUAL_READING_COVERAGE | 已确认完整章 0/3；已审查 0/3；已接受 0/3 |
| EVIDENCE_VALIDATION | PARTIAL |
| SEMANTIC_REVIEW | NOT_EVALUATED |
| REPAIR_OUTCOME | NOT_RUN（语义修订） |
| MKAOS_CANDIDATES | 0；Card 0；Pack 0；无批准 |
| FOCUSED_REGRESSION | PASS |
| REMOTE_MAIN_INCLUDES_DELIVERY | NO |
