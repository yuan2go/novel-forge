# Novel OS Code Quality Audit

审计日期：2026-07-05  
基线 commit：`8733acf`
本轮继续治理基线 commit：`2f1f0bc`
范围：TODO/FIXME/mock/fallback/placeholder、硬编码、重复、超长文件、异常处理、测试缺口。  

## 总体判断

代码库已经有生产化治理结构，但仍带有快速工业化阶段遗留的“大 service + 兼容 facade + 多后端 fallback”。最优修复方式不是一次性重写，而是先补 contract 测试，再逐步拆分。

## 主要发现

| 类型 | 证据 | 风险 | 优先级 |
| --- | --- | --- | --- |
| 超长 service | `modules/mkaos/service.py` 7334 行，已抽出 `mkaos.asset_index` 和 `mkaos.risk_policy` | 单文件仍承担 ingestion/quality/lineage/asset 操作，回归风险高 | P1 |
| 超长 API facade | `api/services/product.py` 5703 行，已抽出 `product_asset_index` 和 Postgres fallback policy | API use case 边界仍不清，路由和 domain 紧耦合 | P1 |
| 超长 workflow service | `modules/workflow_nodes/service.py` 4723 行，已抽出 `workflow_nodes.query` 和 `publishing_ops` | node 执行、错误恢复、状态更新仍难局部测试 | P1 |
| 超长 scheduler service | `modules/agent_scheduler/service.py` 已抽出 `agent_scheduler.publishing_runners` 与 `agent_scheduler.queue_lifecycle` | registry、retry/dead-letter runner 仍混合 | P1 |
| schema 集中 | `schemas/base.py` 1957 行 | required fields 和 validation 难以按域演进 | P1 |
| 过渡层 | `api/routers/README.md` 标注 `_bindings.py` 和 product facade 为 transitional | 过渡结构可能固化 | P1 |
| fallback 路径 | `api/app.py` Postgres list 失败后可退到本地 list | 严格环境下可能掩盖数据库问题 | P1 |
| broad exception | `workflow_nodes`、`product` 仍有外部系统/副作用路径 `except Exception`；`mkaos/service.py` 目标文件已清零 | 静默失败或错误语义不清 | P1，部分治理：已新增 `core.exception_policy`/`core.asset_scan` 并接入只读资产扫描、qdrant preview、workflow scheduler scan、scheduler dead-letter 副作用 |
| mock provider | `model_adapters/mock.py`、`mkaos_model_extraction/provider_runner.py` | 测试有用，但生产入口必须 fail-closed | P0/P1，部分治理：provider evidence 现在要求 hard-stop + success 双证据 |
| placeholder 描述 | `modules/topics/__init__.py`、`modules/review/__init__.py`、`modules/knowledge/__init__.py` | 小风险，影响代码导航质量 | P2，已修复运行时代码占位文案 |
| 版本命名漂移 | `pyproject.toml`、`api/app.py`、`__init__.py` 曾保留 V5 runtime 命名 | 版本和能力沟通不一致 | P1，已修复为 Novel Forge v6 / Novel OS |
| Agent Skill map 漂移 | `agents/runtime.py` 原映射缺 root Skills | 权限和职责选择不稳定 | P0，已修复 |

## 硬编码和 prompt 风险

当前项目已经通过 Skill、runtime policy、provider adapters 把多数 prompt/runtime 边界向外提取。但仍需持续检查：

- 代码中直接声明的 operation policy 是否和 `skills/provider-runtime-policy` 一致；
- deterministic/mock 输出是否只在测试或明确 offline mode 使用；
- API/UI 是否出现硬编码模型名、平台名、asset type 字符串；
- `CONTENT_REQUIRED_FIELDS` 是否继续集中膨胀。

## 测试缺口

已存在 unit/integration/acceptance 结构，但缺口集中在：

- 所有 model-producing operation 的 OS Envelope coverage；
- Longform Recap、Platform Compliance、Training AgentRun integration 已补第一批 scheduler tests；
- Eval -> provider routing -> publish gate 的阻断和 success fixture 已补第一批测试；
- Release package 已补 production-ready 正向 fixture；下一步应扩展到 publish gate generator 端到端 ready；
- publishing facade 和 audit implementation 的一致性；
- MKAOS service 拆分前 characterization tests。

## 本轮修复

新增 `tests/unit/test_agent_runtime_profiles.py`，覆盖：

- 目标 Agent alias 解析；
- 所有 root project Skill 必须显式映射；
- OS governance Skills 不得退回默认 Quality Agent。
- Platform Compliance / Training 注册为 scheduler operation，并加入 MKAOS operation coverage。
- Provider runtime evidence 需要 hard-stop 四维覆盖和成功 guard/model_call 证据。
- Release package production 路径自检 EvaluationGate、ProviderRuntimeGate、PlatformStrategyGate。
- 运行时版本命名统一为 v6/Novel OS。
- 新增 `core.asset_scan`，统一坏 JSON/编码/FileNotFound 可恢复扫描策略，权限和系统错误 fail-closed。
- 抽出 `mkaos.asset_index`、`product_asset_index`、`workflow_nodes.query`，让大 service 的只读索引/query 职责先迁出。
- Product/Workflow/MKAOS 扫描类 broad exception 接入 recoverable-only policy；Postgres read fallback 接入显式环境策略。
- Release package production-ready 正向路径覆盖 EvaluationGate、ProviderRuntimeGate、PlatformStrategyGate、MKAOS risk、ReviewIssue clear。
- Scheduler release package runner 现在传递 environment/envelope/source_policy，并抽出 publishing runner seam。
- Audit asset reference lookup 接入 `core.asset_scan`。
- Agent Scheduler queue lifecycle 抽出到 `agent_scheduler.queue_lifecycle`，主 service 不再直接实现 dispatch id、queue path、resolve、lease expiry、claim、status update、row projection。
- Release package gate evidence 判定迁入 `modules.publishing.release_gate`，audit release package 改为调用 publishing 侧策略。
- Product qdrant preview、Workflow scheduler scan/prepared agent scan、resume/node lookup、asset refs 继续收窄 broad exception。
