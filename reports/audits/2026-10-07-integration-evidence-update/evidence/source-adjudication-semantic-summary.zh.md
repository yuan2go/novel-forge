# PR #133：132 路径裁决的一页语义摘要

固定来源：main `f9e1ee5...`、PR133 `ad1c229...`、共同祖先 `e2064ed...`。逐项路径、32 提交、完整 blob/hash、24 重叠、17 文本冲突及九项旧新迁移映射，以[原来源裁决](./implementation/source-adjudication.json)为准。本页只提炼原判定，不重判历史来源；当前候选为 `e1bd3aa...`。

| 原裁决 | 路径数 | 集成含义 |
| --- | ---: | --- |
| `KEEP_MAIN` | 14 | main 已有等价核心或更强保护；以主线为主体，必要增量另行组合。 |
| `PORT_DELTA` | 107 | 只迁移尚缺的语义和支持项：65 代码、32 测试、5 配置、5 文档/投影路径。不是 107 项新能力，也不表示逐文件覆盖。 |
| `RETIRE_DUPLICATE` | 2 | 退役重复的新运行权限路径；历史 codec/证据与有用校验仍可保留。 |
| `HISTORICAL` | 9 | 旧迁移原身份与 blob 作为来源证据保留，不注册进当前链；所需 schema 责任采用新身份。 |

**main 等价覆盖，必须保留：** native `governed_repair` 的唯一准入与 dispatch 复验；Foundation/Planning 的保留结果恢复核心；`FAILED_FINAL`/`DEAD_LETTER` 已知成功 Effect 读取与 unresolved Effect 阻断；`PRE_SEND_CAPACITY`、注册 capacity cause、有限 successor；World 的 typed/causal 拒绝复现、settled Director receipt 与原 selected action；creation 的取消、原 actor、worker lease、deadline、continuation/progress 控制；Book 原子接纳与 accepted frontier。源分支在这些重叠文件中的删除不能随移植带入。

**必须迁移的增量：** Planning 合法 Foundation 无发送补准入、ordered-input/role-artifact preflight、完整本地 gateway 结果复核、显式 OPTIONAL World 策略及逐阶段有限修复；Kernel 的同作用域 failed-step/derived successor 与有限 window journal；已知 pre-prose Memo timeout replacement、Chapter 候选纠错、Canon grounding/旧 validation 与 Quality applicability 的冻结来源复验。原终态、成功 siblings/Effects、费用与单调计数不清零；accepted、live lease、UNKNOWN 或已提交下游作用域拒绝。配置/Pack/schema/transport 支持只采用显式前向版本，host validation 与原 Context Router 门禁仍有效；对应测试及投影必须按集成树重验。

**退役两条重复权限：** `production_execution/planning_repair_routing.py` 的并行新运行授权并入主线单一 `governed_repair`，保留历史 receipt v1，所需 stage/role 证据采用版本化增量；`story_planning_runtime/world_result_recovery.py` 的并行 typed/causal permission 并入主线原 action 恢复，仅保留兼容 helper 与精确诊断。不是删除所有相关 helper，也不能把 causal/malformed 拒绝自动降为 DEFER。

**迁移身份：** main 已发布0157 continuation control、0158 capacity causation、0159 dead-letter recovery 不改。源分支0157–0165九项按原顺序映射为新0160–0168：result admission、capacity lineage、input order、optional World、gateway revalidation、stage policy、failed successor、contract continuation、derived revalidation。0160依赖main0159，其余连续；旧提交、manifest/SQL、run/receipt/checkpoint身份仍保留。固定main全部160个迁移 body 与当前候选字节一致；异链/hole ledger须在DDL前拒绝，禁止自动转换旧分支数据库。

当前集成另外发生的 Foundation v4/Chapter Plan前向合同、mutation内账务复验、精确 Context binding、FK支撑索引及fixture修正，单列在原裁决的 `integration_forward_fixes` 与[最终来源覆盖](./implementation/final-candidate-source-coverage.json)，不冒称原133增量。[执行工作包](./integration-work-package.md)记录唯一顺序与范围：隔离来源→迁移→Planning/路由→Chapter/Canon/Quality→creation→投影/完整验证→替代PR→merge SHA独立验证。两次当前迁移兼容矩阵各115 PASS/13 subtests仅证明该范围；完整final3 P0 PostgreSQL仍 `RUNNING`，PR/merge验证未完成，真实Provider `NOT_RUN`。
