# UNKNOWN 恢复链修复交付

恢复链的软件缺口已修复并安装到本机 API；原远端请求结果仍 UNKNOWN，不能宣称旧请求已恢复或三章正文已交付。

## 已修复

- Codex 查询不再永久复用不确定缓存：核对原执行身份、命令和输入摘要，并以原进程回执及 stdout 摘要识别新证据。新结果保留原结果版本，查询不启动模型。
- 孤儿进程已经保存完整单轮完成事件、实测用量和有效结果时，可以经原 Schema/语义校验恢复；不把进程回执改写成正常退出。截断、失败事件、缺用量、错身份均不能判成功；缺 token 字段不再默认伪装为实测零。
- 新 CLI 请求保留本地会话并记录 thread ID、会话策略及命令摘要。旧冻结临时请求不变；本地 thread ID 不冒充远端 request ID，未添加自动重试。
- 原生 external_effect.resolve 入口支持终局 Operation 的可信原回执对账。绑定原项目、Operation、Effect、dispatch/generation、请求摘要、Execution、Attempt/fence、原始输入及 Provider 记录；权限、哈希、Schema、用量、幂等、并发和活动租约均校验。
- HELD_UNKNOWN 预留通过既有 budget owner 一次结算；历史未计量 SETTLED 记录追加修正。保留原派发与 Operation 终局；会员金额仍未知，不启用或扩大 DeepSeek 通道。
- Opening 分类、Planning 原结果读取和数据库 lineage guard 消费同一对账证据。过期恢复写入不能覆盖已经保存的终局结果。
- 原有全链诊断及脱敏原始异常日志保持开启。既有只读数据库迁移状态修复继续保留。

## 部署与数据保护

- origin/main 与基线：`acb6d06befac33d6f9a7f07abe41b16e0fff68b8`。
- 补丁摘要：`1585b6c175253bcfa535b509927d02f310980f973ecc0468fcae7183611ce288`；未创建 Git 提交，任务 worktree 33 个改动文件与实际 release 内容逐项哈希一致。
- API PID：`70874`；release：`/Volumes/DevSSD/Development/Data/novel-runtime/wp-work-adaptation-reader-promise-to-prose-01-20261008/service-recovery/releases/acb6d06befac33d6f9a7f07abe41b16e0fff68b8-original-recovery-1585b6c17525`。
- 原生迁移至 0184；已发布的 184 个历史迁移内容摘要未变，隔离数据库验证全新安装与旧版本升级。
- 原数据库先备份，再执行原生 migration runner。12 张关键业务表行数与内容哈希全部未变。原作品、已选 Foundation、Effect、dispatch、receipt、预算和正文/接纳相关记录均受保护。
- API 存活，模型派发仍暂停，worker 未启动。本轮原请求重发 0、新真实模型推理 0。测试使用独立数据库，测试 PostgreSQL 已关闭。
- 本机原数据库仍是先前明确恢复的备份点；备份之后的原始最新账本状态未核实，不以该恢复点断言任何其他环境没有稿件。

## 验证结果

各批次有重叠，不相加冒充独立测试总数：

| 检查 | 结果 | 证据 |
|---|---|---|
| 单元与架构边界 | 146 passed，19 subtests | unit-architecture.log |
| 最终迟到结果、完整性、用量与日志 | 59 passed | late-evidence-tests.log |
| API 与进程监督器 | 28 passed | api-supervisor.log |
| Kernel/预算/存储集成 | 79 passed，24 subtests | owner-postgres.log |
| 最终恢复及迁移兼容性 | 47 passed，3 subtests | final-recovery-postgres.log |
| 历史/当前预留并发确认 | 2 passed | final-concurrency.log |
| API 越权拦截复核 | 2 passed | final-api-auth.log |
| Book/Planning/Gateway 集成 | 44 passed，2 个既有失败 | downstream-postgres.log |
| 上述 2 失败的未修改 main 对照 | 相同失败 | baseline-routing-failures.log |
| 当前改动 Ruff、diff、文档事实检查 | PASS | final-ruff.log、documentation-final.json |
| make -k validate | FAIL：已有 Ruff 2 项及提案生命周期问题 | validate-all.log |

两个既有 Routing bootstrap 失败均在未修改 main 复现，包含测试替身不接受 work_requirements 参数。完整仓库资格与真实 Provider 长流质量未证明。部署脚本初次健康探针超时，但 API 已启动；禁用探针代理后回环读取成功，未重部署、重迁移或重发模型。该现象不能归因到旧 HTTP/SSE 请求。

## 原请求仍缺什么

- Project：`qid-learning-prose-01`
- Book：`book:qinglan-wendao-20261008`
- Operation：`bf6e1d58-97ec-412d-bf91-19d4687d3f24`，保留 `FAILED_FINAL`。
- Effect：`30421df5-8e89-46ab-8aff-ebb9cf3077c7`；dispatch：`9ab5ccd2-ef1b-4b2e-b83f-5b92e1a3fd68`。
- 原请求摘要：`sha256:428f025271f18aa7d700a811b995f46d02dba3711ede39bff47e553cd05d91b6`。
- 原 CLI 约 254 秒后响应流中断，退出 1；无完整结果、实测用量或远端 request ID。只有本地 thread ID。原错误见上轮保留的 stdout，原回执本轮哈希未变。
- 本轮原生读回仍是 `RECONCILIATION_REQUIRED / RECONCILE_ORIGINAL_EXTERNAL_EFFECTS`。并非数据库仍卡住，也不是会员金额不可观测造成的阻塞。
- 根因中“本地不确定结果无法消费新证据、终局对账入口缺失”已经修复；旧流中断到底发生在代理、网络或服务端仍未确证。新代码不能补造旧请求丢失的远端完成证据。

现有可执行的原身份只读核验命令：

```bash
/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python /Volumes/DevSSD/Development/Data/novel-runtime/wp-work-adaptation-reader-promise-to-prose-01-20261008/recheck-original.py
```

只有取得已认证的原 Provider 记录、结果和实测用量后，才能将其经 Authority 保存为原回执，并使用以下已修复入口：
`POST /product/content-authority/external-effects/30421df5-8e89-46ab-8aff-ebb9cf3077c7/resolve`。
请求必须携带原 Operation ID、项目、观察到的 Operation version、稳定对账幂等键、可信 actor，以及实际 `original_remote_receipt_ref`。当前没有这个原回执，未发送虚假对账请求。终局 Operation 不重开，后续必须由既有领域承接入口消费可信原结果。

工程修复状态：EXECUTABLE，针对性验证通过；全仓 QUALIFIED 未成立。
真实正文交付、文学审稿/修订、作者确认、正式接纳：本轮均未完成或执行。原未知调用仍阻止原 Book 继续写作，不能把这些工程测试当作正文交付。
