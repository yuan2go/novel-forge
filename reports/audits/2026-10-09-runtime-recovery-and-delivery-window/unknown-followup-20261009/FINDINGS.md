# 原请求 UNKNOWN 继续排查

结论：已确认 UNKNOWN 的产生与持续机制。原请求在 HTTP/SSE 响应流接收阶段失败；没有完整结果和 measured usage，本系统把本地进程失败映射为 UNKNOWN。现有恢复路径仅复用本地记录，没有原远端查询身份；原临时会话无可读取的历史。因此原请求仍未知。网络、代理或服务端究竟哪一层触发原断流，仍没有足够证据。

## 本轮新证据

1. 原生只读 recheck 再次返回 author_state=RECONCILIATION_REQUIRED、next_action=RECONCILE_ORIGINAL_EXTERNAL_EFFECTS，数据库可以查询。原 process receipt、metadata、stdout、stderr 的哈希与上轮一致。
2. 配置和网络对照：同一已安装 Codex CLI 0.159.2，原 Provider 六项冻结覆盖配置 `novel_forge_openai_no_retry`，模型 gpt-6.1-sol。doctor 显示 supports_websockets=false，使用 Responses HTTP/SSE；本地用户配置没有预先定义这个自定义 Provider。doctor 会加载当前客户端其他配置，所以这只证明相同 Provider 配置下当前连接表现，并非重放原模型请求。
3. 系统代理是 Shadowrocket 127.0.0.1:1082。默认内建 OpenAI Provider 的 WebSocket 自检曾失败，错误 tls handshake eof；只为诊断子进程显式设置 HTTP_PROXY/HTTPS_PROXY 后，握手返回 HTTP101。没有更改系统代理或业务运行配置。这个差异不能归因到原请求，因为原 Provider 未启用 WebSocket。
4. 原 Provider 配置下，无显式代理和有显式代理的当前 HTTP 连接检查都收到 inference URL 的 HTTP405。无凭证 GET /backend-api/codex/models 两种路径都返回 HTTP401，TLS校验成功；普通GET返回401/405是本次只读连接探针预期，不是模型生成成功或失败的证据。禁用显式代理仍可能经过系统 PacketTunnel，不能称作物理直连互联网。
5. 当前可选桌面 CDN 自检出现超时，仅是可选资源告警，不作为正文或对账前置门。
6. 原 thread_id=01a11b3c-af18-7c31-aed1-93488738769d 的原生 thread/read(includeTurns=false) 和 thread/turns/list 均返回 thread not loaded。thread/items/list 虽在生成 schema 中出现，实际 CLI 返回 not supported yet。没有执行 thread/start、thread/resume 或推理请求。
7. 本机 Codex logs_2.sqlite 使用 query_only + mode=ro 检查原调用时间窗 2026-10-08 19:17–19:25 CST：原 thread 0 行；一个文本命中属于其他执行，已排除，不用于推断原请求。Shadowrocket 已发现数据库只有规则/配置表，没有发现这次调用的逐连接历史日志；未读取节点凭证或配置内容。

## 代码链

- production_execution/backends.py:1475：ProcessReceiptStatus.FAILED -> PROCESS_EXIT_FAILURE / ExecutionOutcome.UNKNOWN。UNKNOWN 不是 Codex 服务返回的业务状态。
- 同文件:1721：record.result 已存在时直接返回，包含已存 UNKNOWN。这里不会向 Provider 远端查询原结果。
- story_planning_runtime/execution.py:3325：query 模式把 UNKNOWN 映射为 ambiguous。
- command_kernel/external_effect_runtime.py:1345：普通 fenced reconcile 只接受可恢复的 Operation 状态；原 FAILED_FINAL 不满足直接恢复条件。不能重写终局历史或换 Effect 绕过。
- 原命令使用 --ephemeral，进程退出后不保存会话状态；provider_request_id=null。原 stdout 只有 CLI thread ID，不能当作远端 Response ID。
- 原 no-transport-retry.v1 的 request_max_retries=0 / stream_max_retries=0 已冻结。这使原流中断后不会自动再请求；不能修改原请求来补做重试。

“流断开”是已观测的直接故障，“恢复链没有可补取的原终局证据”是持续卡在 UNKNOWN 的原因。不能把本地失败解释成远端未执行，也不能把会员金额未知解释成请求结果未知。

## 假设判定

| 假设 | 判定 | 依据 |
|---|---|---|
| 数据库当前不可达导致 UNKNOWN | 排除为当前主因 | 原生只读查询成功；原 CLI 的独立进程文件已记录传输错误 |
| 原请求是 WebSocket 握手失败 | 不支持 | 原 Provider 配置未启用 WebSocket；原报错为 HTTP/SSE 流错误 |
| 当前系统代理/隧道路径完全健康 | 尚不能证明 | 内建 WebSocket 默认路径失败、显式代理成功；HTTP短请求可达并不证明长流稳定 |
| 原结果保存在当前本地会话/日志中 | 未找到 | 精确 thread 查询、原时间窗、原执行目录没有完整结果或用量 |
| 多点几次现有恢复即可补回结果 | 不支持 | 缓存 UNKNOWN 直接返回，远端 request ID 缺失，Operation 已终局 |

## 完成边界与可执行下一步

本轮新增真实模型生成 0、业务数据库写入 0、源代码修改 0。既有日志修复版本仍为 acb6d06befac33d6f9a7f07abe41b16e0fff68b8 + patch59d9cd2acad9aeb6d0033fd8d7d4144150787e30b49c7aa1ca1e2405b1f409cf。没有把网络探针作为真实正文交付。

原请求的下一步仍是取得绑定原 Operation bf6e1d58-97ec-412d-bf91-19d4687d3f24 / Effect 30421df5-8e89-46ab-8aff-ebb9cf3077c7 的可验证远端结果和用量，经原 owner 的对账入口登记。当前已安装 CLI 未提供从这个临时 thread 补取原远端结果的可执行接口；这是具体能力缺口，不是继续等待数据库。

新诊断推理可测试当前 HTTP/SSE 长流，但它无法判定旧请求成败；本轮没有发起该新推理，也没有扩大为资格或长篇矩阵。未来工程修复应保存原响应身份/分段结果及可恢复会话，并提供保留终局历史的原身份对账入口；单纯把 UNKNOWN 改成 FAILED、去掉缓存或提高重试次数都不足以修复旧调用。

## 官方行为参考

- [Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)：request_max_retries、stream_max_retries、SSE idle timeout、supports_websockets。
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)：thread/read 和分页历史读取不启动新 turn；以现场 CLI 实际支持为准。
- [Codex 术语](https://learn.chatgpt.com/docs/glossary)：ephemeral session 跳过会话状态保存。

文档用于核对配置语义，原结果状态以本机原身份记录和原生查询为准。
