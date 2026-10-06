# Chapter/Draft 位置敏感性离线实验

**PROPOSAL / NOT_RUNTIME_AUTHORITY**。这是可运行的实验规格与冻结输入包，不是生产 Prompt 变更或第二份系统架构。检查基线：`yuan2go/novel-forge main 9bd1d34f24ebe302533ffc26c72bda97336c4152`（PR #128 合并）。实验工具的证据上限为 `EXECUTABLE`；当前模型行为 `NOT_RUN`，真实 Provider 调用 0，不产生 `QUALIFIED` 或 `PRODUCTION_PROVEN` 结论。

邮件已按 Gmail id `1a10cb37c4ee6f1c` 读取，主题为 “The LLM Blindspot: Why Models Forget What’s in the Middle of Your Prompt”，邮件日期 2026-10-05 15:30:51 UTC。其风险假设是：已发送且窗口内的同一证据，仅因位置不同而可能被利用得不同。邮件链接：[ByteByteGo](https://blog.bytebytego.com/p/the-llm-blindspot-why-models-forget)。原论文及适用边界见 [SOURCES.md](SOURCES.md)。不转载邮件，不把 RULER 长度退化当成本仓库位置效应的测量结果。

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-10-06",
  "review_due": "2026-11-05",
  "reality_baseline": {
    "sha": "9bd1d34f24ebe302533ffc26c72bda97336c4152",
    "implementation_tree_sha": "sha256:c02ccccc262ffa9cb6aa5202ebf0b14780e051aa07583ec9a422c78cf7273648"
  },
  "scope": [
    "src/novel_forge/modules/chapter_authority/execution_gateway.py",
    "src/novel_forge/modules/chapter_authority/provider_views.py",
    "src/novel_forge/modules/context_builder/task_context.py",
    "src/novel_forge/modules/production_execution/provider_admission.py"
  ],
  "implemented_refs": [
    {
      "path": "experiments/draft_position_offline/run.py",
      "symbol": "build"
    },
    {
      "path": "experiments/draft_position_offline/run.py",
      "symbol": "verify"
    },
    {
      "path": "experiments/draft_position_offline/run.py",
      "symbol": "score"
    }
  ],
  "superseding_refs": [],
  "remaining_decisions": [
    "Bind an explicitly authorized experiment model revision, tokenizer, protocol and spending limit."
  ],
  "remaining_work": [
    "Run authorized model trials and independent prose reviews.",
    "Expand independent scenario families and prespecify power before any no-effect clearance."
  ]
}
-->

## 实际 Provider 输入顺序

以下都是固定 SHA 的 `CURRENT_RUNTIME_FACT`，不是永久架构约束。

真正的模型 Draft 分支是 `handlers.py::_DraftHandler.execute`：读取 Chapter plan、execution intent、memo、Context，检查 Craft delivery，投影 plan/style、编译 Realization，然后 `self.provider.invoke(stage='draft')`。存在 adopted author draft 分支，因此不能把所有 Chapter/Draft 都算作模型调用。

`PostgresChapterExecutionContractBinder` 冻结 Pack materialization、路由和完整请求 admission；`PostgresProductionExecutionPayloadResolver.resolve` 从 durable ExternalEffect 重取冻结输入，重新渲染并验证 admission/envelope hash，才交给执行 backend。生产入口由 `production-entry-manifest.yaml` 的 `chapter.slice.run` 指向 `ChapterAuthorityApplication.admit`；`worker-manifest.yaml` 的 `chapter-authority` 通过持久任务执行。Chapter Authority/Command Kernel 拥有资产、Operation/Attempt/Lease/Fence/Effect；`AuthorityHandlerRepository`/`AuthorityUnitOfWork` 是事务内持久化边界，外部 I/O 在事务外，UNKNOWN 走 reconciliation/recovery，新 Attempt 不改旧终态。本实验不启动这些服务、不写数据库或接受章节。迁移身份固定到 manifest head `20261005_0149_zero_increment_chapter_outcome`，本次未运行迁移。

核心源代码：

- `src/novel_forge/modules/chapter_authority/handlers.py:1474`：真实 Draft handler。
- `src/novel_forge/modules/chapter_authority/execution_gateway.py:4335`：最终 materializer；`:4553`：section 拼接；`:3164`：冻结 payload resolver。
- `src/novel_forge/modules/chapter_authority/provider_views.py:671`：Draft task projection；`:1267`：Provider Context；`:2767`：Knowledge。
- `src/novel_forge/modules/context_builder/task_context.py:263`：auxiliary 排序、required 优先和 workset receipt。
- `src/novel_forge/modules/production_execution/provider_admission.py`：完整请求计量、reserve、hash；`provider_control/openai_v2.py:171`、`provider_control/deepseek.py:132`：API 参数；`production_execution/backends.py:1834`：Codex schema 和 stdin。

最终 `input_text` 由以下块以两个换行连接。复用 main 所带 `context-native-snapshot.json.gz` 的冻结 Draft，在当前 main 调用真正的 materializer，得到 **33,546 UTF-8 bytes**，哈希 `sha256:3d7c0511d5c05c6eef8f05399d9288551dce6eb4ce904360e8ce5a27a8d9688a`，与原 routing task 的 input hash 完全相同。

| 顺序 | 外层块 | 原冻结输入 byte range，end exclusive |
|---|---|---|
| 1 | `<system_instruction>` | 0–662 |
| 2 | `<governed_skill>` | 664–1931 |
| 3 | `<required_knowledge>` | 1933–2535 |
| 4 | `<prompt_template>`：Task → Frozen task inputs → Authorized story data → 模板尾规则 | 2537–32502 |
| 5 | `<stage_semantic_contract>` | 32504–33044 |
| 6 | `<output_schema>` | 33046–33546 |

该 native materialization 是测试动态 Pack `context-semantic-subeffects-…@1.0.0`，不是宣称部署中的 Pack。它绑定 System v3、Template v9、`prose-generation-v4`、输出 `schema:chapter-provider-output:draft:v3`，与 main 的 Chapter Pack 当前声明对应的方法版本一致。仓库当前静态 `chapter_generation_pack` 是 2.12.0、CANDIDATE/VALIDATION；库存配置不等于当前实例已经批准启用。冻结 Pack、Artifact catalog identity、content hash、Context receipt、原 admission、Effect/Attempt/trace 来源都保存在 `frozen-v2/native-*.json`。快照本身是 `MOCK_E2E`、原 implementation commit 为 `a57b8dbb…`；在新 main 的渲染 replay 是新的离线检查，不升级快照证据类别。

`_canonical` 使用 `ensure_ascii=False, sort_keys=True, separators=(',', ':')`：对象 key 按字典序，数组顺序保留。上述模板内 task JSON 的顺序是 `chapter_plan → contract_version → creative_memo → realization_contract → stage → style`；Context JSON 顺序是 `accepted_state_boundary → context_correctness_receipt_hash → contract_version → narrative_position → segments → selection_explanation → stage → task_narrative_projection`。segment 内是 `asset_type → asset_version_id → narrative_function → safe_summary → structured_facts`。所以 workset 的 required 优先，只是选择/数组顺序的一环；不能推导关键故事证据处于完整输入开头。Writer projection 还会过滤、压缩或移除重复 summary；位置必须在它之后测。

OpenAI `responses.create` 发送整个 `input_text` 作为 `input`，外加 model、timeout、idempotency、output reserve、reasoning。DeepSeek JSON 协议发 **单个 user message**，正文是整个 `input_text`，另带 response_format/thinking/reasoning；严格协议还把 schema 作为 tools，须另计 framing。XML system 标签没有变成 API system message。Codex 路径把这个文本交给 stdin，schema 另存文件传 `--output-schema`，并带忽略用户规则/配置等受控参数。这里证明的是主机输入序列；Provider 内部 chat template 或 Codex 隐藏系统输入没有被本次真实捕获，不能从主机字节数推出它们不存在。

## 单变量实验

1. 保留原 native 渲染作基线审计证据。新实验使用独立 `offline:position:*` project/workspace/book、chapter 21、accepted boundary 20，仅表示 **OFFLINE_FIXTURE**。不伪装成 PostgreSQL accepted Canon。
2. 复用 native exact System/Template/Skill/Knowledge、style、Draft 输出 schema；用生产 `compile_realization_contract`、`compile_task_context`（lossless fast path，模型 callback 硬拒绝）、最终 materializer、Provider projections。
3. `cases.json` 有 4 个手写场景，含不同物品/地点/期限，正反通行前提各两例。一个完整证据 packet 包含 current fact、人物 UNKNOWN、due obligation、因果条件及执行目标；相关依赖整体移动，packet 内顺序/否定/身份不变。其余 11 个 distractor 来自仓库原创 `clockverse_long_fixture.txt`，标为另一故事的档案。不引入邮件或受版权保护的外部原文。
4. 只将 **同一 Provider Context 的一个完整 segment** 插到 distractor 列表的第 0、5、11 个位置，distractor 相对次序不变。保持 role、语义权限、任务、模板、schema、Skill、source 集合、输入总字节相同；逐字删除 target array element 后三份最终输入必须完全相同。事实地点、deadline、秘密表达、前提内容必须仅出现一次；计划中允许相同 identity 作引用，不复述答案。
5. 在完整输入坐标预注册 front 0–20%、middle 40–60%、end 80–100%。当前 UTF-8 坐标满足这些区域：短正文约 11.7%/50.1%/96.1%，长正文约 5.0%/47.4%/98.4%。实际每份 byte 和 Unicode 坐标见 manifest/requests；60000/180000 是 distractor 内容长度目标，不是宣称准确 token 档位。两档完整正文约 87 KB/206 KB。
6. 这是“相关证据存在但利用失败”的位置实验；不重跑 retrieval/压缩，不拿错误检索、截断、漏发、知识投影拒绝冒充中段遗忘。任一输入缺证据、重复答案、长度漂移、schema/role/route drift 都先报实验无效。

`512000`、位置区域、采样数、分数阈值都是 `CONFIGURABLE_POLICY`。真实运行前必须使用实际模型 tokenizer 验证 **完整 message framing 下**的 token 位置及相同 token 总量，并对每份新 request 重新做完整 admission（输入、工具/schema、framing、输出 reserve、安全余量）。不同 BPE 邻接可能造成等字节但不等 token：严格主实验遇到它要 BLOCK，调整实验 filler 后产生新版本；不能当作纯位置效应。没有实际 tokenizer/窗口/模型 revision 就保留 `NOT_RUN`。`audit-token-positions` 接受带 offsets 的离线测量文件，校验完整覆盖和三元组总 token 相同；该命令验证记录结构，tokenizer 真实身份仍须人工/受信执行证据核验。

## 输出臂、指标和判定

**正文臂**保留当前 Draft schema，不追加答题步骤。Host 原样校验 schema，复用 `prose_from_output` 和 `integrate_realization`，再盲审整个正文。**探针臂**独立调用：只在实验副本中替换 stage contract/schema 为固定五问 JSON，绝不成为正文前置步骤，也不把探针答案回填 Draft。它测可检索性，不能代表正文遵守情况。每个臂内部仍只移动证据。48 份唯一请求 × 3 repeats = **144 次拟定调用**，不含另行授权的独立质量 judge。

| 指标 | 探针 | 正文 PASSED 条件 | 硬失败/下限 |
|---|---|---|---|
| 事实召回 | 物品地点精确等于冻结值 | 从正确地点取出同一物品，未发明替代事实 | 各位置 ≥95% |
| 人物知识边界 | 主角 secret 状态必须 UNKNOWN | 全文中不得把世界真相/见证人知识转为主角已知、据此行动或准确说出秘密；人物限定 POV | 任何泄漏为反例，容忍 0 |
| due obligation | exact obligation id + deadline | 到期前实际当面归还，动作和接收成立；承诺/计划/旁白自报不算 | 各位置 ≥95% |
| 因果约束 | frozen prerequisite 决定开门许可 | 未满足时保持关门，不虚构 accepted 支付/批准；满足时按既有因果完成开门 | 任何非法绕过为反例，容忍 0 |
| 正文执行一致性 | 不用探针分数替代 | 行为、物品、主体、期限、门状态、Slot/POV 与冻结目标及证据一致；不能仅列规则 | 各位置 ≥95% |

现有质量接口对应 `canon_consistency / epistemic_consistency / promise_payoff_debt / causal_consistency`，以及 structural/intrinsic 的正文执行判定。评分器从现有 `QUALITY_DIMENSIONS / QUALITY_EVIDENCE_STATUSES` 校验映射和状态，原快照的 exact quality_rubric 也保留在 native baseline；可将盲审结果映射到已有 Quality judgments/ReviewIssue 类别，携带 producer output hash、constraint 和字面证据，**不向真实 Quality Authority 提交或修改已有报告**。现成快照中的质量分数只供 contract 复用，不能沿用为新正文评分。Model self-report 的 `used_fact_ids` 只做范围校验；即使报告合法，正文仍可能泄密或漏做动作，必须独立判断。`UNKNOWN / INSUFFICIENT_EVIDENCE / REQUIRES_HUMAN_REVIEW` 永不计为 PASS。

正文盲审文件隐藏 position/model/repeat/request id，给 reviewer 同一参考证据和完整正文。每项需要 status、理由和 `start/end/quote`（Unicode code points）字面证据；知识边界的“未泄露”需要审阅全文，不可只凭一个正常句子。省略到期动作是 FAILED；纯缺比较证据是 UNKNOWN。至少一个独立 human 或非生成模型完成判定；疑难/分歧建议两位裁决。不能让 generator 自评替代独立质量。

按 case × arm × length × model revision 配对，3 repeats 在 case 内聚合。随机 seed 固定，位置顺序随机，控制/记录缓存命中、reasoning、temperature/seed（不支持者显式 null）、output reserve 和 Provider build/revision。Fresh trial idempotency identity 是控制元数据，不能复用生产 Effect 或让 Provider 返回旧缓存 receipt。禁止成功后选择性重试；UNKNOWN/timeout/截断保留并单列。输出/评审/统计用新文件版本，不覆盖旧终态。

主差值 `((front+end)/2-middle)`，辅报 `front-middle`、`end-middle`、best−worst。按 case cluster bootstrap 给 95% CI；二值 all-repeats-pass endpoint 用 exact McNemar，分层内及同一模型全部臂/长度/指标的检验族 Holm 校正。报警条件为任一差值 ≥10 个百分点；若下界 >0 且对应全检验族 Holm p<0.05，再标记该层有位置效应证据。样本小的报警/硬反例已足够 FAIL，但没有差异只报 **INCONCLUSIVE**。要排除实用位置效应，需要至少 24 独立 case、6 个场景族、功效设计、所有绝对门通过及差值 upper CI<5pp。本包只有 4 个场景，评分器刻意不返回“无位置效应”或资格 PASS。重复与模板变体不能充当独立场景。

## 可直接运行

使用 Python ≥3.11 和仓库已安装的 pydantic 依赖；不安装包、不读取环境密钥、不含 Provider SDK client、HTTP、DB 或付费执行命令。

从固定 main 的仓库根执行：

```bash
python experiments/draft_position_offline/run.py build --output /tmp/nf-position-new-run
python experiments/draft_position_offline/run.py verify /tmp/nf-position-new-run
python experiments/draft_position_offline/selfcheck.py /tmp/nf-position-new-run
python experiments/draft_position_offline/run.py score /tmp/nf-position-new-run --output /tmp/nf-position-results-v1.json
```

最后一条在尚无返回时报告 `NOT_RUN`，不会发出模型调用。`build` 拒绝已存在目录、漂移 SHA、native replay mismatch；`verify` 检查 pinned source hashes、唯一答案、最终输入 byte equality、位置和语义容器；新 case 文件可用 `--cases /path/to/cases.json`。交付的 `frozen-v2/` 可直接 verify，无需重新构建。

**待明确授权的外部执行步骤**：为这次实验选择并冻结 model/revision、协议、窗口、tokenizer、价格、token/调用/金额预算、成本策略；先验证位置，再在现有受控 gateway 或专用授权 runner 中对每个 trial 做新的 admission。执行器读取 `manifest.schedule` 对应的精确 `input_text`，按原真实 role/protocol 发送，抓取最终 wire text/request/usage/cost/trace，写入 `responses/TRIAL_ID.json`。原快照 model 是 scripted，不可借其“admitted”支持真实模型。已有 Book 的授权/密钥可用性也不是新位置实验授权。包内没有通用自动付费 adapter，确保这里无法意外发起付费调用。

返回文件必需字段示例（JSON 中 prose output 必须使用请求原 schema；所有 hash 为真实采集值）：

```json
{
  "trial_id":"bridge-key-60000-front-draft-repeat-0",
  "input_hash":"sha256:...", "wire_input_hash":"sha256:...", "wire_input_text":"完整冻结 input_text",
  "provider":"已授权 Provider", "model":"实际 model", "model_revision":"实际 build/revision",
  "provider_request_id":"实际 request receipt", "trace_id":"trace", "span_id":"span",
  "request_settings":{"protocol":"实际协议", "reasoning_effort":"high", "temperature":null,"seed":null,"max_output_tokens":16384,"cache_policy":"已冻结策略"},
  "usage":{"input_tokens":123,"output_tokens":45}, "cost":{"amount":"实际金额","currency":"USD"},
  "admission":{"status":"ADMITTED","input_hash":"sha256:...","complete_request_coverage":["完整计量记录"],"total_reserved":12345,"applicable_limit":23456},
  "finish_reason":"completed", "output":{"scene_artifacts":[{"slot_id":"s1:skeleton","text":"实际正文","used_fact_ids":["fact:bridge-key"]}]}
}
```

探针输出直接用请求中的 schema。真实运行还应保存 provider receipt、meter、cache hit、router decision 和冻结 grant 的引用；所有未知/超额成本需停发并追加 reconciliation 记录，不能让本评分器代替预算 Authority。

Token 测量文件格式是 `{model, model_revision, tokenizer_identity, tokenizer_version, tokenizer_source_hash, requests:[{request_id,input_hash,token_unicode_offsets:[[start,end],...],prefix_framing_tokens,suffix_framing_tokens}]}`。offsets 必须覆盖全部输入，允许多 token 对同一 Unicode 范围重叠，禁止缺口。未知 hidden framing 不能填 0 来制造 PASS。

```bash
python experiments/draft_position_offline/run.py audit-token-positions /tmp/nf-position-new-run --measurements /path/to/actual-token-offsets.json
python experiments/draft_position_offline/run.py blind /tmp/nf-position-new-run --output /tmp/nf-position-blind-v1
# 只把 blind 输出目录交给 reviewer；不要交给对照映射或整包。
python experiments/draft_position_offline/run.py import-blind-reviews /tmp/nf-position-new-run --reviewed /path/to/reviewed-blind-files
python experiments/draft_position_offline/run.py score /tmp/nf-position-new-run --output /tmp/nf-position-results-v2.json
```

`score` 不静默丢失败：独立评审缺失、身份/计量未知、解码条件随位置改变、token 未审核、wire drift、截断均是 incomplete/invalid；已观察到知识/因果违规或 schema/Slot 硬门失败保留 FAIL。只有完整且可比的三元组做位置统计。盲审分数不会转成 Book acceptance。

## 本次离线验证范围

适用矩阵为 native render replay、48 份输入单变量校验、工具反例自检和所依赖的现有 unit 组。现有 Provider task view、task workset、retrieval、admission、semantic fidelity、compression Provider 参数和完整 token admission 共 204 项通过；包内 8 项 synthetic selfchecks 通过，检查重复/漏发、wire drift、截断、人物范围违规、UNKNOWN、证据 quote、case 聚类。它们测工具与既有约束，不测 LLM 行为。`validation.json` 保留精确执行结果；`frozen-v2/result-not-run.json` 保留当前负边界。

没有生产代码/schema/migration/Prompt 变更，因此 `docs/runtime-operations.md:88` 的完整 P0 后端资格矩阵和 PostgreSQL/Provider/longform 资格矩阵本次均 **NOT_RUN**。不据 focused 检查宣称后端发布、文学质量或生产就绪。待真实模型产生位置反例后，可再提出有依据的独立修复任务；本实验不预设 Prompt 重构。

`documentation_reality` 检查 PASS；`make validate` 在 `proposal-lifecycle-check` FAIL：main 原有 `classical-corpus-codex-validation.md`、`narrative-memory-context-lifecycle-closure.md`、`prompt-and-generation-contract-convergence-01.md` 的 scope 相对其旧基线漂移。本次实现记录与干净固定 main 的 implementation tree 完全相同（`sha256:c02ccccc262ffa9cb6aa5202ebf0b14780e051aa07583ec9a422c78cf7273648`），因此该静态失败不由实验文件引入，且本任务不修复它。`make validate` 后续门保持 NOT_RUN；不能宣称完整静态矩阵通过。
