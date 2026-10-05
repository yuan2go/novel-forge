# 40章验证：预算授权与正式路由补齐

本次是预算、路由和冻结/恢复适配的工程推进，证据等级 **STATIC / OFFLINE**。真实调用 **0**，已接纳 **0/40**。尚未发出真实生成请求；不能声称文学质量、40章连续稿或生产验证通过。

## 当前授权与输入

用户“预算按照正常的来就行”授权按正常额度推进；操作者采用此前提出的 **1600次模型调用 / 8000万Token** 累计上限。数值是明确记录的操作者分配，不冒充用户逐字指定。规划、生成、资格取证、修订、压缩与重试共同占用额度；终态和原账本不重写，不更换项目绕过总额。期限为2026-10-12 00:00 UTC；过期不得自动续约。

原生预算 owner 为 `CREATIVE_EXPERIMENT_BUDGET`，合同 `creative-provider-campaign-budget.v4`，绑定hash `sha256:53c94b2cc1e5b68e63ca1d0892ddf690abc8fc28320b097eadfabbfce57b7c59`。预算配置命令重复同一幂等键两次，原生查询的调用/保留/Token均为0，Effect/Dispatch/Receipt也均为0。预算配置当时代码为172bafe3；后续运行装配代码为`5740414f8e2a171ea5df21b59f227d5c86ab3ef7`，历史配置来源不改写。

正文继续固定 **codex-cli / gpt-6-sol / medium**。账户现金费用仍为UNKNOWN；合同中priced USD=0是尚无付费审读授权，不代表Codex免费。DeepSeek仅独立审读/语义评估、最多20美元的选择问题仍等待用户答复，尚未写入付费grant或调用它。

作品采用已登记的作者v2：**玄幻轻喜剧**，暂定《这家灵兽食堂有点忙》，明确禁止武侠和悬疑。40章，每章5000–6000正文汉字，HAN_CHARACTERS_V1。作者输入仍是AI_ASSISTED_AUTHOR_INPUT，尚非获批Foundation/Canon。原始v1、v2冻结、资产、幂等键和失败记录保留；这次只在新目录增加预算组合冻结，作者brief、creation、formation与DENY_ALL字节逐项相同。

## 实际修改与反例

- `authority_dependencies.py`：显式配置 `NOVEL_FORGE_CODEX_ROUTER_REASONING_EFFORT`，进入正式候选ID与RouteSnapshot。旧实现会把medium改为high；新实现Codex-only及mixed选择均保留medium。省略该配置仍high；空值/unknown/不受支持的ultra拒绝。未改独立审读、资格、预算、fallback或质量门。
- `creation_comparison.py`、`run_creation_synthesis.py`：冻结新的Router档位和既有retry policy；恢复语义保留档位，不能把旧冻结重解释为medium。
- `creation_pilot.py`、上述两个入口文件：正式冻结/恢复识别原生v4/v5 campaign合同。修复前原生business_scope在旧适配器被拒绝；修复后整本书预算的现金grant和Codex entitlement分别绑定，现金上限可为0，账户费用仍UNKNOWN。已有Book可按冻结合同继续；设计权限关闭时新Book仍被拒绝。
- `test_cross_model_author_review.py`：修正过时Cursor替身，真实实现先读取项目内精确候选版本，再决定qualification profile。新旧作品合同切换仍拒绝旧资格，不放松实际SQL资格条件。
- `docs/runtime-operations.md`说明实际配置、冻结、预算和兼容边界；`architecture/reality-evidence.json`仅刷新实现树投影身份，未升级任何资格等级。历史准入报告保留，标记为历史快照并指向本次记录。

## 正式入口与版本绑定

`scripts.run_creation_synthesis` -> pinned input freeze -> native CREATIVE_EXPERIMENT_BUDGET -> `build_production_execution_composition` -> existing ProductionProviderRouter -> candidate admission / RouteSnapshot -> CLI invocation。Codex backend由冻结RouteSnapshot生成 `--model` 和 `model_reasoning_effort`，并核对实际启动参数；当前只完成OFFLINE装配，没有Provider声称的observed effort。

`authority-creative-budget configure` -> trusted principal -> owning policy command -> Command Kernel / UoW -> native versioned selection。账本查询与正式adapter消费同一contract/hash/grant。新冻结hash `sha256:e651867fabb02a21a167b1c32b0eb66d79d76c87f1c8bc131cc34c5aeaeba671`；实际作者入口configuration preview通过。原生预算/作者资产及Prompt/Skill/Pack来源依然是Authority，审计文件和组装检查不是Book checkpoint。

## 验证与证据边界

211项定向测试、5个subtest通过：Router选择及调用证据、author review条件、campaign预算契约、冻结/恢复、正式配置入口。覆盖旧实现失败的medium与campaign反例，错误entitlement、超额现金、未知成本被伪称已估价、恢复档位漂移、关闭设计权限后的新Book初始化，以及旧qualification跨合同复用拒绝。JUnit见 `focused-tests.xml`。旧测试首次失败与projection stale保留在STATUS的初始失败记录，不改写为从未失败。

Documentation Reality、Instruction Reality、Test Reality以及改动面Ruff均PASS。完整backend/PostgreSQL资格矩阵本阶段NOT_RUN；不能据此把EXECUTABLE升级为QUALIFIED。隔离真实运行数据库未用于会TRUNCATE的pytest模块。

实际输入与native预算的装配/恢复核对见 `execution-freeze-v1/assembly-and-resume.json`；它明确未调用formal execute、不是生产checkpoint。正式preview只验证配置，不等于E2E。旧作者v1的历史pending预算和high失败报告不是当前状态。

## 剩余准入与当前判定

1. 当前跨Provider门要求Codex稿件由DeepSeek独立审读；不能由同一Codex自证，不能将作者AI提案改称人类原创来逃逸。
2. 收到独立审读授权后仍须检查真实Provider凭据与priced报价/额度、原生Pack编译/批准/激活及独立资格来源，准备本运行独占对象存储，按精确新版本正式启动。预算授权和成功返回JSON本身不能替代这些准入。
3. Foundation处于REVIEW_PLAN；获批方案及10/20/30章的阅读决策仍应走原生作者决策，不伪造人工评价。当前未批准方案，未形成真实章节，下一单元/真实retry/resume也未验证。

| 判定（本次真实40章阶段） | 状态 |
| --- | --- |
| BUDGET_AUTHORIZATION | PASS |
| MEDIUM_ROUTING_AND_FROZEN_IDENTITY | PASS |
| CAMPAIGN_BUDGET_FORMAL_ENTRY_ADAPTER | PASS |
| AUTHOR_INTENT_PROPAGATION（真实完整链） | NOT_VERIFIED |
| FORMAL_PRODUCTION_E2E | BLOCKED |
| ACCEPTANCE_AND_NEXT_UNIT | NOT_VERIFIED |
| RECOVERY_PATH（真实稿件恢复） | NOT_VERIFIED |
| LEGACY_ASSET_SAFETY（本次改动OFFLINE） | PASS |
| REAL_PROVIDER_VALIDATED | NOT_VERIFIED |
| CREATIVE_QUALITY_PROVEN | NOT_VERIFIED |
| PRODUCTION_READY（本次真实运行） | BLOCKED |

先前Quality/Context工作包的MOCK_E2E结论见既有报告，不能转作本次REAL_RUN或当前完整release资格。参考书全文未获取/阅读，继续SOURCE_IMPORT_PENDING；没有把原书表达、角色、场景或独特情节组合放进Draft输入。

受保护原工作区仍是ceb69fa2ff1c56f07005154bb5797616e933e8c2，分支codex/wp02-author-approved-run，所有原未跟踪文件列表相同。实施分支codex/work-intent-context-e2e-20261005；本次代码提交172bafe3、5740414f，证据另提交。没有push、PR、merge、部署、quota reset或付费fallback。

后续工作属于当前已授权验证任务的继续：先关闭真实准入，完成获批方案及少量真实章节，再进入40章连续稿。不存在以本次配置PASS代替该任务完成的结论。
