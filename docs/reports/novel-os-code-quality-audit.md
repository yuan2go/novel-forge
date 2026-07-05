# Novel OS Code Quality Audit

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：TODO/FIXME/mock/fallback/placeholder、硬编码、重复、超长文件、异常处理、测试缺口。  

## 总体判断

代码库已经有生产化治理结构，但仍带有快速工业化阶段遗留的“大 service + 兼容 facade + 多后端 fallback”。最优修复方式不是一次性重写，而是先补 contract 测试，再逐步拆分。

## 主要发现

| 类型 | 证据 | 风险 | 优先级 |
| --- | --- | --- | --- |
| 超长 service | `modules/mkaos/service.py` 7415 行 | 单文件承担 ingestion/quality/lineage/asset 操作，回归风险高 | P1 |
| 超长 API facade | `api/services/product.py` 5762 行 | API use case 边界不清，路由和 domain 紧耦合 | P1 |
| 超长 workflow service | `modules/workflow_nodes/service.py` 4820 行 | node 执行、错误恢复、状态更新难局部测试 | P1 |
| 超长 scheduler service | `modules/agent_scheduler/service.py` 3740 行 | queue lease、retry、dead-letter、registry 混合 | P1 |
| schema 集中 | `schemas/base.py` 1957 行 | required fields 和 validation 难以按域演进 | P1 |
| 过渡层 | `api/routers/README.md` 标注 `_bindings.py` 和 product facade 为 transitional | 过渡结构可能固化 | P1 |
| fallback 路径 | `api/app.py` Postgres list 失败后可退到本地 list | 严格环境下可能掩盖数据库问题 | P1 |
| broad exception | `workflow_nodes`、`agent_scheduler`、`storage/*` 多处 `except Exception` | 静默失败或错误语义不清 | P1 |
| mock provider | `model_adapters/mock.py`、`mkaos_model_extraction/provider_runner.py` | 测试有用，但生产入口必须 fail-closed | P0/P1 |
| placeholder 描述 | `modules/topics/__init__.py`、`modules/review/__init__.py`、`modules/knowledge/__init__.py` | 小风险，影响代码导航质量 | P2 |
| 版本命名漂移 | `pyproject.toml` version `5.0.0`，文档和 AGENTS.md 指向 v6 | 版本和能力沟通不一致 | P1 |
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
- Longform Recap AgentRun integration；
- Eval -> provider routing -> publish gate 的阻断测试；
- publishing facade 和 audit implementation 的一致性；
- MKAOS service 拆分前 characterization tests。

## 本轮修复

新增 `tests/unit/test_agent_runtime_profiles.py`，覆盖：

- 目标 Agent alias 解析；
- 所有 root project Skill 必须显式映射；
- OS governance Skills 不得退回默认 Quality Agent。

