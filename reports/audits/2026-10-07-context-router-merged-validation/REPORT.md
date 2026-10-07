# WP-CONTEXT-ROUTER-MERGED-VALIDATION-01

裁定：**PARTIAL**。冻结修复提交的定向工程执行通过；原始 merged main 未通过。真实 Provider 切片在发送前 BLOCKED，Router 资格与独立保真校准没有证明。

| 报告标签 | 判定 | 证据范围 |
|---|---|---|
| CODE_WIRED | PASS | 修复提交：原生 Chapter Scheduler、Router/Pack、Kernel 子效果、冻结 bundle 和 Draft 预发送请求实际闭合；受控 Provider，证据状态 EXECUTABLE |
| MERGED_HEAD_VERIFIED | FAIL | 开始时远端 main 的干净定向集成失败；修复尚未合并，不能迁移分支 PASS |
| REAL_PROVIDER_VERIFIED | BLOCKED | 真实发送 0 次，详情见 real-provider-preflight.json |
| ROUTER_QUALIFIED | NOT_PROVEN | 当前 producer/model/service/task 身份下没有本轮可复用的真实独立资格样本；受控样本不充当资格 |
| FIDELITY_CALIBRATED | NOT_RUN | 没有盲标签、可独立判定的真实模型正反例校准；host 保护与 fidelity 自报不能替代 |

## 冻结身份与修复

- 基线：`3c4d6dc5fa5370288bad6e1302b4b3fd5e80b5df`，执行开始 fetch 远端 main 后固定。
- 最终：`8d8f0b21fa945d8cbe3db559adc5edb0fc5f597c`，分支 `codex/wp-context-router-merged-validation-01`，提交后干净 worktree。
- 工作区：`/Users/yuan/.codex/worktrees/wp-context-router-validation-01/novel-forge`。原用户 checkout 的未提交修改未动。
- PR #132 的真实 merge 为 `f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609`；其发布说明明确测试/Provider NOT_RUN。后续 main 已引入 Pack 3.0 / Chapter 3.10。本轮没有沿用旧 2cb74ed/a736a443 报告的 PASS。

仅修改两处生产调用点，无 schema、迁移、路由策略或质量阈值变化：

1. `chapter_authority/execution_gateway.py:2190`：当前 Chapter 3.10 绑定其原始 workflow 3.10；此前落到配置默认 3.9，无法解析当前已部署 Pack。新增精确回归在基线生产文件上得到 FAIL；修复后通过，同时保留 3.4.1、3.9 及派生 3.9.16 的 workflow 语义。
2. `chapter_authority/orchestrator.py:397`：同步 fixture 入口为 3.10 保留 Style 输入，与已支持该版本的 Scheduler 对齐；此前触发 STYLE_PROJECTION_MIGRATION_REQUIRED。没有放宽 Style gate。

测试装配补登记当前 definitions，保留旧 definitions；复用当前 typed plan/Style 构造，提供绑定项目、Book、hash 和 accepted-through 的 genesis State。定向用例通过原生 admit → Scheduler 执行到 Review，补断言精确 Context 版本/hash、最终 Prompt 事实、Prompt/admission hash、重放不新增发送。原来的完整 slice 质量阻断断言仍保留。

预验证范围/缺口/清理记录：`scope-and-document-cleanup.json`。当前文档将 Pack 2.7 标为历史 profile 引入点，指向现行 3.0/3.10；说明已实现的 reasoning 授权例外、membership 资源合同与 Context bootstrap 边界。仅更新 reality-evidence 的当前 projection_source identity；旧执行、FAIL/BLOCKED/UNKNOWN、合同、迁移及历史资格记录未改。9 个变更文件及哈希见 acceptance-result.json；可应用补丁为 repair.patch。

## 正式链路与必要验证

入口和所有者：`api/authority_dependencies.py:379,1440` 装配 Chapter Application、生产 Gateway 和模型 effect adapter；Chapter Context Handler 编译候选上下文，Kernel 管理持久化 intent/dispatch/receipt、Attempt/Lease/Fence；PG Authority UoW 承载资产与操作。ContextBuilder 不拥有 accepted Canon/State 写入权。

关键位置：

- `production_execution/cost_routing.py:158,193,208`：两个独立 HIGH task，v13 / DOMAIN_GATE_ACCEPTANCE；重试失败保留分母。它们不是 REVIEW task。复用 REVIEW 环境路由配置槽不复用 review 资格。
- `config/capability_packs/chapter_generation_pack.json:1082` 与 `api/authority_dependencies.py:222,583`：Context Skill 和子阶段工具授权。
- `chapter_authority/handlers.py:1020,1318,1347,1513`：Context 真正执行两子阶段、冻结 bundle；Draft 绑定并使用 Context。
- `context_builder/task_compression.py:90`：未超预算不发送；仅允许的冻结历史来源；完整原文单元选择和宿主重建；精确正文/必要状态/voice/private 边界保护；缺失补回、有限复查、原文恢复、恢复仍超限阻断。
- `chapter_authority/execution_gateway.py`、`production_execution/provider_admission.py`：完整预发送请求覆盖 System/Prompt/Skill/Tool/Schema/Context/Knowledge/封装、输出预留与 margin；未知计量/容量、请求或路由漂移拒绝。
- `authority_handler_runtime/context_feedback.py:59,87`：最新 generation、receipt/dispatch/evidence/source/hash 校验。UNKNOWN 不借旧成功；负例/失败没有从分母消失。

受控测试证明 host 工程合同；Codex 的现有 admission 只具有 APPLICATION_VISIBLE_UPPER_BOUND，隐藏 CLI framing/远端最终请求仍未证明。不得将其提升为完整远端请求容量证明。20 样本下限、窗口/输出/重试/分块预算为 CONFIGURABLE_POLICY；它们不等于能力通过条件。冻结策略与旧合同是 HISTORICAL_COMPATIBILITY；host 原文重建、精确保护和漂移阻断在所测边界有 CURRENT_PROVEN_INVARIANT 证据。真实服务身份/容量 UNKNOWN 是 CURRENT_RUNTIME_FACT；隐藏远端请求边界仍为 UNRESOLVED_DESIGN_CONSTRAINT。

## 测试与证据

| 执行 | 结果 | 索引 |
|---|---|---|
| 干净固定 main，四个指定 unit 文件 | 124 PASS | main-unit.log/xml |
| 干净固定 main，feedback + 指定 E2E | 19 PASS / 1 FAIL：测试 harness 未登记 3.10 | main-postgres.log/xml |
| 基线生产 binder + 精确当前 workflow 回归 | FAIL：3.9 代替 3.10 | baseline-binder-regression.json/log/xml |
| 修复演进 | 原始 Style、Pack admission、旧 genesis 及后续失败逐次保留 | fixture-repair-e2e-1、repair-e2e-2 至 5、repair-native-e2e-1 至 3 |
| 最终 SHA，新建第二隔离数据库 | **270 PASS，0 FAIL，0 SKIP** | final-focused.log/xml |
| Ruff、documentation reality、instruction、worker、migration manifest | PASS | final-*.log |
| 全仓 required-test manifest 校验 | FAIL，基线同一规则 | final-required-test-manifest.log |

最终 270 个用例为：四个指定 unit 文件 124、直接受影响的冻结 workflow/legacy recovery 文件 126、feedback 19、原生 Context E2E 1。未启动全量 P0、全仓回归或重复构建；未修改公共 Router/冻结 routing policy，所以没有追加 cost-aware / quality-calibration 全文件回归。

原生 E2E 项目 `project-b17ed368d3cf46b1a78808c0aa30438d`：
Context 76,309 → 30,703 / budget 32,768；Context hash 为
`sha256:551028ed91869969eedbd77025fb0a43aaf85a4d7945c4a0b602e7aa862c80b0`。
7 effect / 7 dispatch / 7 receipt：Memo、两个重放探针、原生 compress/fidelity、Draft、Review。探针是同一 Context 的受控恢复检查，不是独立模型样本。实际 task_type 和 producer hash 位于 final-native-summary.json；完整输入、bundle、下游请求、资产和账本位于 final-native-ledger.json。Context 正向资格反馈为 {}，没有把 fixture 成功写成任务资格。

明确保留的范围外失败：
- 完整 slice 后续 Canon extraction 在 `handlers.py:2030` 导入不存在的 `canon_history`，见 repair-e2e-5.log。本次停止于已授权的 Context→Draft/Review，不修 Canon、不宣称 Book/Chapter acceptance。
- required-test manifest 的 `coordinated-current-planning-controlled-wire` 规则将无 test 函数的 helper 文件按测试文件匹配。文件存在，但 inventory 报 pattern matches no test files。规则与基线字节一致；未删除测试或规则以制造通过。

## 真实 Provider、资格与保真

本轮实际模型发送 **0**、实际新增模型 tokens **0**、DeepSeek 增量支出 **USD 0**。Codex subscription 成本维持 NOT_ESTIMABLE_ACCOUNT_ENTITLEMENT，不人为增加金额、累计调用或 token 上限。

已有 membership 通过原生 observe_membership_identity 只读验证；保存的是 account hash 和 executable/version/hash，不含 token。models_cache 没有 confirmed 完整输出容量；当前任务所需原生 route/config、容量与计量证据尚未提供。因此在新发送前停止。已授权 membership 不代表 admission 已成立。Codex 远端实际 served model/service 身份为 UNKNOWN（没有调用），不能推断为已知。

DeepSeek 没有本次可加载的既有付费模板及明确 maximum_amount、匹配账户/私有 credential 配置，不能估算并预留完成切片的合法支出，不能自行追加金额或切换付费通道。

现有 Chapter bootstrap 不注册 Context 两 task，Draft/Review grant 不能借用；现有 creative_validation 模板可合法承载隔离原生链路执行，但模板和单次成功本身不赋予资格。没有新增 sampler、伪造 observations 或形成先资格后采样的替代系统。

未获得当前 producer/task 身份下可复用的独立真实 Context 样本。受控 qualification 数据仅测试规则；real_model_call 测试字段本身不证明真实发送。失败分母、UNKNOWN、hash drift 已工程验证；Router confidence/样本独立性/模型服务身份须在真实证据上另行裁定。最低 20 个样本并非自动 PASS。

独立盲保真正反例模型评测未执行；否定/条件、时间/因果、人物认知、承诺、关键语气的模型校准均 NOT_RUN。既有 host 保护单测不是该校准。没有向被测模型提供评测标签，也没有用 compressor/fidelity 一致或 fidelity 自报代替独立判定。

## 复现与资源收尾

完整命令、工作区、返回码见 commands-and-results.json；基线 PG 命令另见 main-postgres-command.json。在最终工作区、迁移后的全新隔离库执行：

```bash
NOVEL_FORGE_DATABASE_URL='<caller-owned fresh isolated test DB>' PYTHONPATH=src:. \
  /Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python -m pytest -q \
  tests/unit/test_context_compression_routing.py \
  tests/unit/test_context_compression_provider.py \
  tests/unit/test_task_context_admission.py \
  tests/unit/test_task_scoped_context.py \
  tests/unit/test_chapter_legacy_contract_recovery.py \
  tests/integration/test_context_feedback_postgres.py \
  tests/integration/test_quality_context_formal_e2e_postgres.py::test_native_overflow_compression_fidelity_draft_review_and_frozen_resume
```

自有私有 PG16.15 + pgvector0.8.6，迁移至当前 20261007_0180；新 cluster、socket、port、DB/OID 与最终库身份分别在 owned-postgres.json、final-postgres.json、final-native-ledger.json。只复制工具链并向私有目录安装扩展；没有连接生产库或改系统 PG 工具链。原始失败库和最终库各有 custom-format dump，均已成功导出；私有 PG 已关闭，见 postgres-stop.json。证据与内容 SHA-256 见 evidence-index.json。

后续所需：补齐原生 membership 路由/确认输出容量及 admission 证据，或提供既有 DeepSeek 付费模板和私有配置；再完成真实切片和独立校准。修复合并后必须绑定真实 merge SHA 重验受影响范围。本交付不包含合并、部署或平台发布资格。
