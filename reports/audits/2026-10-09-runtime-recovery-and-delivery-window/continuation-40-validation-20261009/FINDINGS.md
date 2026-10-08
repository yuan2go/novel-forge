# 《青岚问道》推进到 40 章：验证与当前交付状态

本轮没有核实可交付的本书正文。成功读取的原恢复点中，draft_chapter、draft_version、review_report、re_review_report 均为 0，BookProduction 尚未创建。该端点来自 2026-10-08 20:18:23 CST 的原库备份恢复；备份之后的原始最新状态仍未核实。不能据此声称其他位置没有正文。

## 状态分别报告

| 项目 | 本轮状态 |
| --- | --- |
| 工程窗口延长 | EXECUTABLE；原生 owner、CLI/API、事务、版本/幂等和读回通过受控验证并已部署 |
| 《青岚问道》40 章交付 | NOT_RUN / RECONCILIATION_REQUIRED；未生成、未替换其他 Book、未变更原窗口 |
| 文学审稿与修订 | 本书 NOT_RUN；没有模型审稿冒充读者反馈或修订候选冒充作者采用 |
| 作者确认 | 本轮 40 章推进授权来自用户；作品方案/修订选择没有伪造 |
| 正式接纳 | 原恢复点 accepted cursor 为 0；本轮未推进 |
| 原模型结果及用量 | UNKNOWN；会员费用不可观测另列 UNKNOWN，不能当作未知远端执行结果 |

## 原身份与输入

- Project: qid-learning-prose-01；Workspace: workspace:qid-learning-prose-01。
- Book: book:qinglan-wendao-20261008。
- Formation: story-formation:0a8aa0c2dc447a252fad800a5a31b0663fd6f167087d18bfeb5a980a8afe261d；READY / COMPLETE / v14，已有 6 个选定 Foundation，未重跑。
- Opening: book-opening:6cdfa1d6a184d7fb840be300c488e6b70b42889dcf1149eaff99327dc512e113。
- Operation: bf6e1d58-97ec-412d-bf91-19d4687d3f24；FAILED_FINAL / v3。
- Effect: 30421df5-8e89-46ab-8aff-ebb9cf3077c7；UNKNOWN。
- Dispatch: 9ab5ccd2-ef1b-4b2e-b83f-5b92e1a3fd68；UNKNOWN。
- Production profile: authority-output:e028f0a6-b242-4990-b707-b2f4b09ca34f:book.bootstrap.production_profile:v1；SHA256 461bc496bf591908b24377a3adb228076641a569c19771bb5ad03ec2b449180d。
- 原冻结全书目标 240；交付窗口 3；AUTHOR_FIRST / deep_review=false。用户要求 40 是本轮交付范围，未被转写为全书长度。
- 原请求 hash: sha256:428f025271f18aa7d700a811b995f46d02dba3711ede39bff47e553cd05d91b6。
- 原路线 codex-cli / gpt-6.1-sol / high / ChatGPT membership；原请求为 HTTP Responses/SSE，冻结零 HTTP/stream retries，含 ephemeral。原失败输出和 process receipt 保持原样；本轮没有实测模型用量或新增真实派发。
- Prompt/Skill/Schema/冻结请求和本书资料生成的既有精确证据沿用 ../material-provenance-20261009/provenance.json、../unknown-followup-20261009/FINDINGS.md、../unknown-repair-20261009/REPAIR.md；未改公共 Prompt/Skill。

## 真实入口缺口与修复

原代码把冻结 window.stop_after_chapter 作为 BookRun 目标，没有同一 Run 延长入口。新入口在现有 Book Authority 内原子追加 book-delivery-window-extension.v1、原生 Operation/审计/Outbox 回执，仅增加交付目标和 Book version，保留旧政策链和冻结 profile。原稿、计划、上下文依赖、正式 Canon/State、接纳游标不被写入。

CLI: authority-manuscript extend-delivery-window --book-run-id <原 BookRun> --stop-after-chapter 40 --expected-version <读取的 Book version> --idempotency-key <该次稳定键>。
API: POST /product/editor/manuscripts/extend-delivery-window。
必须为已结算的 READY/PAUSED 作者优先 checkpoint；UNKNOWN、HELD_UNKNOWN、活动子请求或执行 Lease 均拒绝。相同参数/键重试只读回原回执。变更上限或主体不能复用同一键。API 直接使用已有 book_authority_application，不装配模型执行组件。

实际已部署基线 acb6d06befac33d6f9a7f07abe41b16e0fff68b8；无新提交。
Patch SHA256: 57e155e644f28b439d5597f3ae2f26853ee6584ffec7453bf8d2eb250e9c7286。
Release: /Volumes/DevSSD/Development/Data/novel-runtime/wp-work-adaptation-reader-promise-to-prose-01-20261008/service-recovery/releases/acb6d06befac33d6f9a7f07abe41b16e0fff68b8-delivery-window-57e155e644f2。
API PID: 86161；8144；provider_dispatch_suspended=true，worker 未启动，原项目保持暂停。
Migration head 20261009_0184_cli_original_reconciliation；本轮未增加迁移。
部署前已备份原恢复点，部署后 12 个原业务/执行表的行数与完整行 hash 全部相同。原安装配置、对象存储、已认证会员身份沿用；敏感配置、原始参考作品没有进入仓库。

## 验证批次与限制

- Opening recovery: 71 passed；10 个现有恢复/崩溃边界/并发/旧协议文件，attempt-03/opening-recovery.xml。
- 补充既有 creation/resource/template 单元批次: 106 passed；remaining-unit.xml。
- 窗口/API 单元: 14 passed；window-unit-final.xml。
- Book window PostgreSQL: 最终 9 passed；extension-check-04/delivery-window-final.xml。验证 3→40→80 的同 Run 版本链、原启动重放、响应丢失、回滚、并发抢同 checkpoint、越界/旧版本/错主体、UNKNOWN 拒绝和暂停保留。
- Author-first native controlled: 最终 2 passed；extension-check-03/author-first-extended.xml。原 6 章保存、中断恢复，API 延长至 8，原 6 个版本保持、第 7 章消费正确第 6 章版本，继续到 8，审稿服务故障不扣稿，作者编辑/选择与精确导出，接纳游标仍为 0。是受控传输测试，8 章不是《青岚问道》的产出。
- Manifest、architecture fitness、authority-only/compose config、documentation reality、修改 Python 的 Ruff 与 git diff --check 通过。Compose config 没有证明整个真实服务栈或真实 Provider 新请求成功。
- 跨章严格审稿 3 个测试仍 FAIL：STYLE_PROJECTION_MIGRATION_REQUIRED。pristine origin/main 同 SHA 上复现，原夹具缺当前 Foundation style projection。未放宽生产门或把失败写成 PASS，baseline-check 保留差分证据。
- 批次可能重叠，不将次数相加冒充唯一测试总数。不运行无关全平台资格/压测或跨题材真实生成矩阵；全仓 QUALIFIED / PRODUCTION_PROVEN 未成立。
- 失败和修复保留：最初隔离 DB 名称不满足 _test 安全规则，test-only NO_MODEL_DISPATCH 误挡受控任务，导入 unittest class 意外扩大收集，第二次窗口更新漏 AssetVersion CAS，首版 API 误装配 Provider。后两项代码问题已修复，前述终态测试通过。原日志/JUnit 保留；复制 runner 覆盖了 attempt-03 的 results 索引，原测试日志/XML 未改，junit-evidence-index.json 从保留文件重建索引且未猜测丢失的运行元数据。
- 隔离 PostgreSQL 55690 的本轮临时数据库由 runner 删除，服务已停止；原 55489、MinIO、API 保留。

## 阻塞责任与下一条命令

当前阻塞是原模型执行回执缺失，责任入口为 RUNTIME_OWNER / 原 Codex Provider 记录。冻结请求的本地 receipt 为 FAILED，进程退出不证明服务端失败或未执行。完整结果与实测 tokens 不可恢复，原 UNKNOWN 不得用新 Run/Book/幂等键绕过。用户的原记录入口/回执文件定位问题仍待回答。

当前可执行并已验证的原身份检查命令（只读，不重复派发）：

```bash
/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python /Volumes/DevSSD/Development/Data/novel-runtime/wp-work-adaptation-reader-promise-to-prose-01-20261008/service-recovery/continuation-40-validation-20261009/original-status-command.py
```

取得真实已认证的原执行记录、结果与实测用量，并经现有 Authority 保存为可信原回执 AssetVersion 后，使用已修复入口 POST /product/content-authority/external-effects/30421df5-8e89-46ab-8aff-ebb9cf3077c7/resolve，绑定原 Operation v3 与真实 original_remote_receipt_ref。当前没有该回执；未构造假的对账材料或执行解析命令。

实际后续顺序：对账原 Effect → 原 Opening 恢复及原 BookRun 启动 → 原 3 章窗口完成/保存/导出 → 同一闲置 BookRun 延长至 40 → 按真实 frontier 继续逐章保存和精确读回 → 显式 Prose Review、必要未采用修订候选和差异。正式接纳仍是单独授权操作。

当前无可核实完整正文可导出，因此没有正文阅读文件。本书生成、40 章交稿、文学审稿修订、作者修订选择与正式接纳均未宣称完成。
