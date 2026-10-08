# 原 Codex 请求 UNKNOWN 诊断

本轮已恢复数据库读写和对象读回，增加并部署执行链日志。原请求远端结果仍为 UNKNOWN；本轮新增 Provider 派发 0。没有以新 Book、run、请求键或手工正文替代原作品。恢复环境来自 2026-10-08 20:18:23 CST 的原库备份，备份之后的原库最新状态仍未核实。

## 当前故障证据

原请求 stdout 明确报告：

`stream disconnected before completion: Transport error: network error: error decoding response body`

本地进程启动成功，出现 thread.started、turn.started，约 253911 ms 后 returncode=1。没有 turn.completed、measured usage 或 last-message.json；stderr 为空。原回执、execution metadata、stdout 和 stderr 的 SHA256 在本轮读回前后完全一致。

这定位到 Codex 返回流接收阶段。已有记录没有 HTTP 状态、响应头或 authenticated remote result；无法进一步确认网络、代理或服务端根因。工具配置警告不是已证实原因；没有证据把原因归为预算、认证、容量或数据库。金额不可观测是会员计费事实，与远端请求结果未知分别保存。

原本地 FAILED 被现有 Codex backend 映射为 ExecutionOutcome.UNKNOWN；Planning adapter 映射为 unknown/ambiguous；Kernel 保留 UNKNOWN Dispatch/Effect；预算保留 HELD_UNKNOWN；Opening 评估返回 UNKNOWN_AMBIGUOUS。当前 reconcile 会复用本地 cached UNKNOWN，不是查询原远端执行。原 CLI 请求使用 --ephemeral；原 thread/read 只读 RPC 返回 thread not loaded。未取得可清除 UNKNOWN 的原始远端结果和用量。

## 原身份

- Project: qid-learning-prose-01；Workspace: workspace:qid-learning-prose-01
- Book: book:qinglan-wendao-20261008
- Operation: bf6e1d58-97ec-412d-bf91-19d4687d3f24，FAILED_FINAL / v3
- Effect: 30421df5-8e89-46ab-8aff-ebb9cf3077c7，UNKNOWN
- Dispatch: 9ab5ccd2-ef1b-4b2e-b83f-5b92e1a3fd68，UNKNOWN
- Execution: planning-execution:30421df5-8e89-46ab-8aff-ebb9cf3077c7:6192d1cd-06d9-4480-9684-95b7db23de1e
- Attempt: 6192d1cd-06d9-4480-9684-95b7db23de1e；fence 1
- Frozen request hash: sha256:428f025271f18aa7d700a811b995f46d02dba3711ede39bff47e553cd05d91b6
- Original CLI thread: 01a11b3c-af18-7c31-aed1-93488738769d
- Original model / reasoning: gpt-6.1-sol / high；原模型实际 observed version 不可得
- CLI: codex-cli 0.159.2；原已认证会员身份 hash 匹配；未输出凭证
- Schema: schema:planning-provider-output:book:v1:work-v4:host-selectors-v2
- Definition 1.21.0；system instruction v11；long-outline-v3；原 no-transport-retry.v1 不变

## 日志与测试

现有 owner 链加日志：Kernel 意图/派发/回执/恢复，Planning adapter/预算与模型证据保存，网关准入、Codex payload 准备、进程回执保存与恢复、返回流观察、JSONL/结构/语义校验、Authority AssetVersion 保存与读回、Book Opening 评估与恢复。ContextVar 嵌套 span + 原请求身份关联，不增加业务 Authority 或修改冻结请求。

`NOVEL_FORGE_EXECUTION_DIAGNOSTICS=1` 启用结构日志；`NOVEL_FORGE_EXECUTION_DIAGNOSTICS_EXCEPTION_TEXT=1` 增加原异常消息、异常链堆栈及 Codex error-event 原消息，凭证模式脱敏。全部实际日志在本机私有目录，权限 0600；无日志内容进入公开仓库。原 stdout/stderr 保留。

- unit.log：161 passed + 5 subtests，执行/进程/网关/Book 恢复。
- planning-unit.log：208 passed（含部分上面重复测试），Planning 与延续。
- postgres.log：34 passed + 10 subtests，Authority 持久化、Kernel Effect、Opening 恢复。
- planning-postgres.log：18 passed，Hierarchical Planning 与迁移只读兼容。
- final-diagnostics-test.log：9 passed，补充真实 Planning adapter 的 cached UNKNOWN -> ambiguous、原始异常链保留/凭证脱敏、日志 sink 故障不改变执行、回执保存错误、重复恢复无重新派发。
- controlled-log-coverage.json：699 个受控诊断事件、31 个实际观测步骤；不是原请求的历史全链日志，也不证明真实 Provider 完成。
- Ruff focused 与 git diff --check：PASS；documentation-final.json：PASS。
- make -k validate：完整执行；首次本次新增注释/docstring违反注释 ratchet，已修正并复检通过；仍 FAIL 的是 main 已存在的 Ruff 基线与 4 个过期提案，见旧 baseline scope 比较证据。未以本次窄范围诊断冒充全平台资格。

所有 PostgreSQL 测试使用 port55690 的隔离测试集群，已停止。首次测试实例启动漏了端口参数，尝试默认5432失败，补回明确55690后通过；未触碰5432服务。API 初次默认代理访问连接关闭，改为显式 loopback direct；一次错误 URL 404 后依原生 OpenAPI 修正。失败记录保留。没有真实新模型测试、付费 DeepSeek 调用或长篇资格矩阵。

## 发布身份与边界

实际运行 release：base acb6d06befac33d6f9a7f07abe41b16e0fff68b8 + patch 59d9cd2acad9aeb6d0033fd8d7d4144150787e30b49c7aa1ca1e2405b1f409cf，路径见 release-manifest.json。修改未提交、未推送。原 checkout 未提交工作保持。API health=alive；dispatch suspended；没有启动 worker。私有环境配置绑定这个快照，原历史配置、原请求及回执未改写。

## 正文与下一步

原 Book 的传统修仙 Brief 和 6 个已选 Foundation 沿用；当前是 Formation COMPLETE，而不是正文任务完成。恢复备份点无选定 BookPlan / BookProduction / 已保存稿件、审稿、修订或交稿；备份后原库最新正文状态仍 UNVERIFIED。正文交付、文学修订、作者选稿与正式接纳均未完成；没有本轮三章正文可供导出。

原身份上的下一条可执行核对命令：

```sh
/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python /Volumes/DevSSD/Development/Data/novel-runtime/wp-work-adaptation-reader-promise-to-prose-01-20261008/recheck-original.py
```

该命令只读，不派发，不消除 UNKNOWN。原生 Opening 评估可使用 original-opening-assessment-command.json 的同一键重放；最终 API 已确认同一 recovery_assessment_id 和 snapshot_hash、replayed=true、UNKNOWN_AMBIGUOUS。

责任入口：原 Provider authenticated result/usage 对账，Kernel ExternalEffect / Planning gateway，Book Opening recovery。只有取得原请求的可验证远端终局证据才能清除 UNKNOWN。终局 Operation 的现有 fenced reconcile 也要求原 owner 的合法恢复/承接路径；没有证据时不能换 ID 重发或解除 HELD_UNKNOWN。正文继续、显式 Prose Review、修订候选、作者选择及正式接纳保持未执行。
