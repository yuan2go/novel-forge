# Chunked Prefill 技术选型与 Provider 端点边界

本轮选型核查完成；性能收益尚未证明。采用决策仍为当前跳过 Chunked Prefill 调优、
不引入 vLLM，但收窄理由：本次可核查范围没有确认具备可控调优入口和适用性能需求的
推理服务。不能推导所有环境均为托管推理、所有环境不存在 vLLM，或非流式任务无收益。
当前决策投影在 `docs/current-system.md`，隔离基准设计在 `docs/runtime-operations.md`；
本文件是冻结审计证据，不是额外运行时 Authority 或生产门禁。

## 基线、范围与保护

- 2026-10-07 只读 `git ls-remote origin refs/heads/main` 核验远端 main：
  `3c4d6dc5fa5370288bad6e1302b4b3fd5e80b5df`。完整本地 Git 对象可读。
  本次最新 main 恰好等于用户给定的历史报告基线；以下代码证据均重新读取该 SHA。
- 原工作区 HEAD 为 `ceb69fa2ff1c56f07005154bb5797616e933e8c2`，分支为
  `codex/wp02-author-approved-run`，与 main 不同，且已有修改与未跟踪证据/Skills。
  没有 checkout、reset、stash、覆盖或清理原工作区。
- 从固定 main 建立隔离工作树
  `/Users/yuan/.codex/worktrees/chunked-prefill-endpoint-audit/novel-forge`。
  只改两份现行文档及本审计记录；生产代码、依赖、配置、Pack、迁移、Reality 投影均不改。
- 先读 AGENTS、canonical allowlist、current-system 的资源策略/Provider/部署/Context/
  Authority/恢复/资格边界，以及 runtime-operations 的配置、验证矩阵、资源、Provider、
  部署和恢复段落，development 的变更/文档规则。必要代码核对后先清理下述两处说明，
  再补端点说明和决策。没有开展全仓文档整顿。
- main 的 canonical docs、`reports/audits/` 与 `architecture/` 中按
  Chunked/Prefill/vLLM 搜索，未定位到上一轮专门选型记录；用户所述旧结论作为待核验命题。
  复用现有 canonical 决策/操作位置及 `reports/audits/`，仅保留这一份审计记录。
  搜索结果不用于证明部署不存在，历史审计、冻结合同与原始证据均保留。

## 代码证据索引

下列行号绑定上述 main，不能用于原工作区旧分支或任意运行实例。路径均相对仓库根目录。

| 路径、函数与行号 | 证据及边界 |
|---|---|
| `pyproject.toml:54–65` 的 scripts；`src/novel_forge/workers/chapter_authority.py:40,51,131` | 正式 CLI/worker 进入现有 PostgreSQL 应用和生产 composition。 |
| `src/novel_forge/api/authority_app.py:182–202`，`create_authority_app` | API 验证 storage/release，构造 registry、Production Execution、Chapter application。 |
| `src/novel_forge/api/authority_dependencies.py:379–480,710–774,1047–1169,1220–1279`，`build_production_execution_composition` | 从 process environment/显式 mapping 选择 routes，校验 Codex 可执行文件/身份，注册 CLI 与 RemoteProvider backend；不是从名称推断端点。 |
| `src/novel_forge/modules/provider_control/composition.py:45–112`，`configured_router_provider_ids` / `build_provider_adapter_registry` | production 或显式 quality-cost Router 仅选 DeepSeek/Codex；registry 仍可因 stage 配置构造 OpenAI。OpenAI 必须有 credential 和可选 SDK；构造不保证某一任务已通过 routing。 |
| `src/novel_forge/modules/provider_control/registry.py:89–136`，`register` / `resolve` / `qualify` | 注册与 route capability conformance 是可达条件，不是远端资格或服务归属证明。 |
| `src/novel_forge/modules/chapter_authority/execution_gateway.py:775,1088,1368,1410`，`freeze_before_external_effect` / `bind` | Chapter 正式冻结和 dispatch 时调用 Router；Prompt/Skill、输入、route 和 admission 绑定后才允许 Effect。Planning/Source 复用 production composition，不产生独立端点 Authority。 |
| `src/novel_forge/modules/production_execution/routing_runtime.py:780,835`，`ProductionProviderRouter.select` | 当前选择受原生 policy、benchmark、预算/身份等条件约束；adapter 存在不能替代 selection。 |
| `src/novel_forge/modules/production_execution/gateway.py:401–427`，`submit` / `resume_planned_execution` | 从冻结 route 解析 backend，恢复提交必须有现有 recovery authorization。 |
| `src/novel_forge/modules/production_execution/backends.py:1060–1105`，`RemoteProviderExecutionBackend._submit` | 校验完整 envelope/admission 和 route，构造 ProviderInvocationRequest 后调用 adapter，外部 I/O 不属于业务事务。 |
| `src/novel_forge/modules/production_execution/provider_admission.py:181–205`，`ProviderRequestEnvelope.to_identity_dict` | hash 绑定 provider/model/protocol/input/output/timeout/idempotency，但没有实际 HTTP base URL 或 proxy 归属。 |
| `src/novel_forge/api/authority_dependencies.py:1206–1210`；`src/novel_forge/modules/production_execution/recovery.py:209`，`AuthorityExecutionRecoveryStore` | 当前 production composition 使用 PostgreSQL recovery store，不把旧 transient session cache 当作当前持久 Authority。 |
| `src/novel_forge/modules/command_kernel/external_effect_runtime.py:398,453,526,646,772`，`plan_external_effect` / `dispatch_external_effect`；`src/novel_forge/storage/authority_uow.py:15`，`AuthorityUnitOfWork` | 现有 Kernel/UoW/repository 持久化 intent 和 dispatch/receipt；adapter.execute 发生在业务事务外。没有新建持久边界或改迁移。 |
| `src/novel_forge/modules/provider_control/deepseek.py:45–49,55–79,85–218,416,495`，`invoke` / `_completed` / `_failure` | 默认 urllib opener 禁止重定向；HTTPS POST 到 `https://api.deepseek.com/chat/completions`，strict-tools 到 `/beta/chat/completions`；Bearer credential，`stream=false`。计时从发送前至读完/解析/成功或失败处理，不是 token 时序。测试 transport 注入不能算真实端点。 |
| `src/novel_forge/modules/provider_control/openai_v2.py:153–218,270–284`，`OpenAISdkTransport.execute` / `build_openai_provider_adapter` | `OpenAI(api_key=..., max_retries=0)` 没有显式 base_url；发送 Responses input/model/timeout/Idempotency-Key/max_output_tokens/可选 reasoning。读取 id/output_text/usage，JSON object 和下游 schema 验证仍适用。没有设置 stream，SDK 默认 False；query/cancel 分别为 retrieve/cancel。 |
| `src/novel_forge/modules/production_execution/backends.py:1555–1599,1687–1692,1706–1748,1805–1877`，`CodexCliExecutionBackend` | 初次提交、授权 recovered submit 共用 `_submit`/`_prepare_payload`；同 execution id 返回已有 handle。reconcile 读取 supervisor/receipt，没有 CLI session resume 或自动新 send。 |
| `src/novel_forge/modules/production_execution/codex_configuration.py:10–64`，`codex_retry_overrides` / `codex_local_binding_hash` | input-only overrides；诊断 no-retry 改用 custom provider，requires_openai_auth/Responses/HTTP+stream retries=0；未显式设置 base_url。策略进入 binding hash；旧请求保留原配置。 |
| `src/novel_forge/modules/production_execution/backends.py:1834–1876`，`_prepare_payload` | membership 校验后 force ChatGPT login；未配置 no-retry 时选 `model_provider=openai`；忽略用户配置/规则、ephemeral、read-only sandbox、无跨 Book resume，显式 CODEX_HOME。命令没有 oss/local-provider 模型服务器参数。 |
| `src/novel_forge/modules/production_execution/process_supervisor.py:28–40,97–118,662,696–703`，`EnvironmentAllowlist.build` / `launch` | 子进程白名单含 HOME/CODEX_HOME/证书及 HTTP_PROXY/HTTPS_PROXY/NO_PROXY；不含 OPENAI_BASE_URL/API keys/ALL_PROXY。配置隔离不等于网络直连。 |
| `src/novel_forge/modules/production_execution/membership_identity.py:9–29`，`observe_membership_identity` / `require_membership_identity` | 仅 ChatGPT auth、非 API key、完整 tokens 和 hashed account identity 可通过；它校验登录/账号，不证明服务器实现。 |
| `src/novel_forge/infrastructure/settings.py:55–85`，`IndustrialSettings.from_env` | settings 合并 .env 与环境，但没有把 Provider keys 导出 os.environ；registry 与 SDK ambient env 是不同来源。 |

Owner/recovery 边界仍为现有 Command Kernel Operation/Attempt/Lease/Fence/ExternalEffect、
Production Execution backend 和 PostgreSQL record/UoW；业务候选由 Chapter/Planning/Source
Authority 验证发布，Book acceptance 才原子绑定 accepted chapter/Canon/Narrative State。
本轮无 schema 或 mutation 变更。已核对 production-entry、worker、migration manifests；
不以 manifest 声明替代上述可执行入口，也不重跑迁移或业务状态。

## 潜在路径、配置选择、实际运行证据

| 路径 | 代码允许 | 本次读取的配置/运行证据 | 不能据此声称 |
|---|---|---|---|
| DeepSeek | 默认官方 HTTPS URL；urllib 的 proxy 环境/系统代理可能影响实际传输。没有 base-url 配置项。 | 既有私有配置选择 DeepSeek；历史原生回执有真实调用和整体 latency。当前代理链/请求没有重新观察。 | 不能证明官方服务内部使用何种 engine，也不能证明所有网络路径均无代理。 |
| Codex membership 初次/重试 | 显式 ChatGPT auth、固定 CLI/home、版本化 retry；默认白名单挡住 OPENAI_BASE_URL，但保留 HTTP(S) proxy。custom no-retry 不等于 API-key paid replacement。 | 既有私有配置选 `codex-cli,deepseek` 和 `codex-no-transport-retry.v1`；配置 CLI 0.155.1 及 digest 当前匹配。当前认证为 ChatGPT membership，但账号引用与配置记录不匹配。 | 配置文件不是当前已启动服务；身份 drift 不是部署了 vLLM；本地 CLI 不是本地模型推理。 |
| Codex 恢复 | 已有 handle/receipt replay 或有 recovery authorization 的同一 command builder；UNKNOWN 不盲目重发。 | 历史 local no-retry proof 明确只有 configuration parse、model_calls=0、remote success NOT_RUN。 | 该 proof 不能升级为实际 endpoint 或跨版本运行证明；本轮没有触发恢复。 |
| OpenAI SDK | stage route 配置可构造 adapter；base_url 可继承进程 OPENAI_BASE_URL，允许外部/代理/自托管服务候选。production cost Router 没有 OpenAI candidate。 | 当前 shell 的 OPENAI_BASE_URL/API key 未设置；项目 .venv 未安装 openai/httpx；读取的私有配置没有这两个 key。Docker 内版本未知。 | 不等于所有运行环境都未设置、adapter 永远不可达或已经连接 vLLM。 |
| 仓库部署 | compose.yml 是 PostgreSQL/对象存储/API/worker 栈；其他 Compose 为检查/兼容/测试等资产。Dockerfile 仅安装 industrial extra，未安装 provider-openai。 | 核对 compose.yml、override/postgres-test/worker-e2e/qualification、docker-compose.yml、Dockerfile、.env.example、config/provider 示例；没有登记可调 Chunked Prefill 实例。 | 服务清单或没有 vLLM 依赖不能证明外部 server 不存在；示例也不是当前部署。 |

### 当前可访问环境的有限观察（2026-10-07）

只读取必要字段/返回布尔值和安全版本；没有输出 auth.json 内容、token、key 或带凭证 URL。

- 执行宿主 shell：OPENAI_BASE_URL、OPENAI_API_KEY、DEEPSEEK_API_KEY、HTTP_PROXY、HTTPS_PROXY、
  ALL_PROXY 和本次检查的 NOVEL_FORGE route/home/executable/retry keys 均 UNSET。
  原工作区 `.env` 存在，但未声明这些 keys；`.env.local`、`.env.production` 不存在。
  这只覆盖该文件和进程环境，不代表私有 launcher 的继承环境。
- 原工作区 `.venv` 的 importlib.metadata：pydantic 2.13.5；openai/httpx NOT_INSTALLED。
  main 的依赖合同是可选 `openai>=1.99.0,<2`，无 Python lock。不能伪报某一已部署 SDK 版本。
- `docker info --format '{{.ServerVersion}}'` 退出 1：不能连接
  `unix:///Users/yuan/.docker/run/docker.sock`。未启动 Docker、切换 context、检查其他 daemon、
  枚举容器环境或扩大到远端。
- 进程清单仅投影模块名/可执行文件，不输出完整参数或环境；未识别到运行的
  novel_forge 模块进程。该有限 inventory 不证明所有自托管/代理进程不存在。
- 已登记历史部署：`architecture/live-evidence/narrative-capability-admission-closure-02/20260928-deepseek-json/deployment.json:1–9`
  绑定旧 implementation `9605c212d95aa51f2e1c2643cff4d6a8fa51eefe` 和私有目录
  `/Users/yuan/novel-runtime/wp02-security-handoff-20260928/deepseek-docs-20260928`。
  仅核查其 `environment-author.json`、`evidence-environment-docs.json`、两个 launcher 的
  白名单字段/环境继承，以及配置指向的 CLI 和会员身份；launcher 有 os.environ 继承，
  其未捕获的启动环境未知。未读取无关日志/认证存储，也未执行 launcher。
- 配置指向的 CLI 返回 `codex-cli 0.155.1`，digest
  `8eaf1ad12fe6bf89b1710330f58900014322c7c5af677e43be116d8ac5fc0a9e` 与配置相符。
  配置 home 存在；现有安全 helper 返回 ChatGPT/ACCOUNT_ENTITLEMENT；account-reference match=False。
  这是配置快照的身份 drift；按当前 main membership 合同，用该旧引用新发会被拒绝，
  不应静默改引用、renew 或重发。helper 内部读取认证文件；没有导出其内容或修改文件。
- 已登记 `http://127.0.0.1:8141/health` 只读请求返回 RemoteDisconnected；没有确认活跃服务的
  release/endpoint lineage。它不是 inference 请求，也不是当前实例已采用上述私有配置的证明。
- 当前 App 附带另一 CLI 为 0.159.2，仅版本可读；不把它当成已登记 Novel Forge CLI。
  远端未登记部署、Docker 内依赖/环境/服务、managed CLI policy 和实际 upstream routing 均未验证。
  当前没有足以推翻采用建议的实际可控自托管证据。

### 现有延迟证据

`architecture/live-evidence/narrative-capability-admission-closure-02/20260928-deepseek-json/docs-native-receipt.json:1830–1846`
保留 `deepseek-flash` / DeepSeek-V4.1-Flash、real_model_call=True、输入 5850、输出 3336、
整体 latency 22.306626875011716 秒，以及 MALFORMED_STRUCTURED_OUTPUT。
request hash 为 `sha256:433c0ff2ce1f69c4519d872235e741a7f2864542e87d094a2ed090a7fb0d9ad4`。
同一回执在多处投影重复，不能按出现次数计算独立样本；null latency 保留 UNKNOWN。
这是一条历史失败调用证据，不是新成功、当前性能分布、TTFT/ITL 或 Chunked Prefill A/B。

## 邮件与版本适用性

Gmail message `1a113b2bdf887b91` 已通过只读 full 读取；Subject 精确匹配
“Chunked Prefill, clearly explained”，邮件日期 2026-10-07 00:10:42 UTC。
只用于问题来源；不复制整封邮件、推广链接或私人 headers。邮件讲述 prefill/decode
调度及大小 tradeoff；“工作不减少”只能理解为仍需处理完整提示，不能据此断言执行
开销、GPU 利用率或墙钟时间不变。一次预算是所有已调度 tokens 的预算，不是请求固定 chunk。

官方版本化来源（读取原文/源码，tag 不表示本系统部署了该版本）：

| 来源 | 核验 |
|---|---|
| [vLLM v0.10.2 V1 optimization](https://github.com/vllm-project/vllm/blob/v0.10.2/docs/configuration/optimization.md#chunked-prefill)，25–48 行 | 同一次请求 prefill 被分块，与 decode 混批；V1 默认启用；大小预算的 ITL/TTFT 趋势需按实际负载验证。 |
| [vLLM v0.10.2 SchedulerConfig](https://github.com/vllm-project/vllm/blob/v0.10.2/vllm/config/scheduler.py#L34)，34–38、80–82 行；[V1 scheduler](https://github.com/vllm-project/vllm/blob/v0.10.2/vllm/v1/core/sched/scheduler.py#L196)，196–218、296–297 行 | max_num_batched_tokens 是每次 iteration 总预算，逐个 request 消耗其余量；不是每次应用请求提交长度。 |
| [OpenAI SDK v1.99.0 constructor](https://github.com/openai/openai-python/blob/v1.99.0/src/openai/_client.py#L140)，140–149 行；[Responses](https://github.com/openai/openai-python/blob/v1.99.0/src/openai/resources/responses/responses.py#L780)，780–817 行 | 未传 base_url 时读取 ambient OPENAI_BASE_URL，否则 api.openai.com/v1；create POST /responses，stream 默认 False。这是本仓库可选版本合同下界的源码核验，宿主 SDK 未安装；不能外推所有环境实际 installed version。 |
| [Codex rust-v0.155.1 ModelProviderInfo](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/model-provider-info/src/lib.rs#L350)，350–368、415–427 行；[config](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/core/src/config/mod.rs#L3738)，3738–3744 行 | 版本匹配配置 CLI。显式 provider base_url 优先，ChatGPT auth 默认 chatgpt.com/backend-api/codex，其余默认 api.openai.com/v1；built-in provider 与 configured providers 合并。默认源代码解释不能代替实际网络证据或二进制源码 attestation。 |
| [vLLM v0.10.2 API server](https://github.com/vllm-project/vllm/blob/v0.10.2/vllm/entrypoints/openai/api_server.py#L580)，580–665 行 | 该版本有 Responses create/retrieve/cancel 路由，但 handler 不支持时返回 error。因此既不能把 Chat Completions 兼容等同于本 adapter 合同，也不能笼统声称 vLLM 不支持 Responses。具体实例仍需核验模型、fields、JSON/schema、usage、存储/query/cancel、timeout/idempotency 和 recovery 语义。 |

主要下载内容 SHA-256（用于复核原文身份，不是运行证据）：

- vLLM optimization：`3e1569ff97083516ee6a7df4da07712ace4c5d7cfafb9e7a328ce2583d24dacb`。
- vLLM SchedulerConfig：`abc834f0ac14781be70a7cc91e38b0c443c8aa576515bd4777025934e9216b33`。
- vLLM V1 scheduler：`2bd28fc32cea71370298bb8da0d9a0bbd163ab315b2c6428540131e3999a255f`。
- OpenAI client：`41f32d302ea7f7344440527fe6caca1c8a23f258d1728f1fb54acfb6f328c24e`。
- OpenAI Responses：`0088789b83661846ae88792195d99034ff7c3dc881e046ad5c51dcf61db24f95`。
- Codex 0.155.1 provider：`e2e7dbd6c5475c40eb89e5c8160e515b8957c161e8d1ade1b78e755511153f93`。
- Codex 0.155.1 config：`99f4fff7d17c72af3feae3a36fd022522c312148c6e99287b66223989668373f`。
- vLLM API server：`40b1245fcfa5a18f215a232fc25c99293f16c37dac9c4bf0238d49a1614d7563`。

## 独立缺口与处置建议（本轮不修复）

1. **OpenAI 隐式端点/冻结身份缺口**：factory 的 credential 来自传入 mapping，但 SDK URL 来自
   ambient environment；provider admission hash 不包含实际 endpoint。同 provider/model/request
   身份不能保证跨进程仍到同服务，可能产生协议/凭证目标或 recovery 归属偏差。
   这是可复核代码风险，不是发现了恶意流量或 vLLM 部署。另开 scoped 工作核验预期环境合同，
   再决定是否显式绑定端点身份；不在本轮新增开关/资格门禁或修改行为。
2. **旧配置会员身份 drift**：当前安全检查与旧配置引用不匹配；只报告阻塞影响。
   真正需要新运行时由现有授权/配置/recovery owner 检查当前 identity，不自动续期或重发。
3. **OpenAI 部署资格未知**：默认 Dockerfile 不装可选 SDK，production Router 不含 OpenAI candidate；
   自定义部署仍可能构造 adapter。不能据 registry 能力声明确认远端 idempotency/query/cancel。
   若未来选择该路线，应按实际 endpoint 和安装版本核验现有合同，不增加本轮生产前置条件。

## 清理、结论与重审

确认保留：当前不增加 vLLM 基础设施/Provider/依赖，Chunked Prefill 属于推理服务调度。
修订：从“托管/非流式所以跳过”改为“没有确认可控候选和适用需求”；不宣称全环境不存在。
未知：当前实际 upstream/代理链、自托管登记之外的环境、服务内部 enablement，以及性能收益。

先清理两处确认过强/混淆的现行表述：

- current-system 中 no-retry 的 “same authenticated OpenAI route” 改为 custom Responses
  Provider 的认证/retry 配置事实，补充 parse-only 不能证明实际 endpoint。
- runtime-operations 中笼统的 .env 配置加载说明改为 settings-file 与 Provider process-env
  的真实区分。没有删除历史 local parse proof 或其 frozen retry policy。

最终变更仅为 `docs/current-system.md`、`docs/runtime-operations.md` 和本记录；增加准确端点边界、
技术说明、采用决定和窄隔离基准设计。没有复制一套决策治理、归档/删除原证据或改变 evidence ceiling。
Provider 链的代码/wiring 本轮上限为 `WIRED`；历史真实调用证据仍限其原 SHA/identity。
本轮未执行 inference，不能升级为当前 `EXECUTABLE`、`QUALIFIED` 或 `PRODUCTION_PROVEN`。

重审触发条件是有明确可控服务候选、代表性负载及预先定义的任务性能目标；不要求先接生产。
先核对实际版本/enablement，再固定模型/硬件/输入输出长度/请求集/到达模式/并发/缓存，
比较现配置与少量有效 token budgets。保留 TTFT/ITL p50/p95、整体 request latency、
完整有效任务吞吐、timeout/failure；最终根据 Novel Forge 完整任务交付和质量/可靠性取舍。
非流式计时不能还原 ITL，但非流式负载仍可受益；缺指标保持 NOT_OBSERVED，未做实验保持 NOT_RUN。

## 检查记录

只读配置/源码/版本/历史回执、Gmail 和官方原文核验已执行；Docker 与健康探测的不成功原样保留。
`git diff --check` 通过；`PYTHONPATH=src <现有项目 .venv/bin/python> -m
novel_forge.tools.documentation_reality --repo-root . --expected-sha
3c4d6dc5fa5370288bad6e1302b4b3fd5e80b5df` 退出 0，status=PASS、errors=[]，
canonical documents=5、capabilities=26，comment ratchet PASS。它是当前静态文档/投影一致性检查，
不是实时 Provider、小说质量或性能验证。另核对新增 Markdown 本地链接/anchors、冻结源码引用行号、
版本化官方来源及本轮只含三个文档文件的变更边界。
未执行：业务测试、完整资格矩阵、迁移、
真实 Provider 调用、恢复发送、性能基准、部署、push、PR、merge；推理调用次数为 0，无新增推理费用。
这些 NOT_RUN 不成为小说生产的新门槛，也不转换为能力或性能 PASS。
