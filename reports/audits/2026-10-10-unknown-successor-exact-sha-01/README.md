# WP-UNKNOWN-SUCCESSOR-0194-EXACT-SHA-01 工程验收

受测代码提交：`ea83597df52322a48114a9e7f64450668ab0e5be`。证据归档提交另计，不能替代该受测 SHA。
开工 main 为 `70ac89b1fedb304e10422d78e4bd231ebfc52831`／PR #149；实施中合并后续 PR #150/#151/#153，最终纳入的 main 为 `f067d189a63f644a3a49f78abda557035b5fa59a`。历史 PR #148 边界 `f30abd74…`→`247ccb33…` 只用于追溯。

完整迁移头：`20261010_0198_recovery_reference_indexes`，父链 `0194_multi_model_generation_isolation`→`0195_prose_review_generation_isolation`→`0196_stopped_cli_timeout_isolation`→`0197_authorized_planning_capacity`→当前0198。registry 为199个完整迁移身份（数字前缀不是身份）。已发布迁移正文逐字节不变；本包只追加六个既有外键引用索引的0198。实施中尚未发布的本包0196名称被0198取代，旧一次性库账本保留，未改名或清空历史。

## 原问题关闭方式

| 原问题 | 开工状态与最终实现 | 最终证据 |
|---|---|---|
| 旧尝试隔离、整书解冻 | 已有原生隔离能力，补当前证据；旧 UNKNOWN、Attempt/fence与历史保持不变，后继业务执行与原远端未知分开 | PASS，见144项原生节点清单 |
| Context共享失败耗尽 | 缺失/不一致；复用Kernel已存派发失败账本，跨Planning续接及Saga前驱血缘计数，冻结策略取最小原额度；派发/恢复/后继均检查，同一耗尽检查点幂等 | PASS，见144项原生节点清单 |
| 可信完整结果零重发 | 已有底层能力但Chapter恢复入口未先调用；接入原生saved-result恢复，复用既有绑定、ValidationManifest和计费证据 | PASS，见144项原生节点清单 |
| 原生唯一关联后继 | 原提交权撤销、后继血缘与原生调度意图在现有协调UoW内原子提交；接纳失败整体回滚，并发/重放不产生第二个直接后继 | PASS，见144项原生节点清单 |
| 隔离后迟到API回执 | 采用PR #150唯一原生owner；扩展到每个隔离dispatch generation，可信完整原身份绑定，逐代幂等/冲突拒绝；全部可核算原代齐备才聚合结算原reservation，后继独立 | PASS，见144项原生节点清单 |
| 迁移及联合备份恢复 | 以完整registry/父链为准；升级保留UNKNOWN与预算历史，非空测试库+Authority Artifact版本+原执行目录真正dump/restore逐表/逐文件核验 | PASS，完整迁移与两份联合恢复指纹 |

会员授权与付费上限仍由原资源owner控制；没有新增会员累计额度或计数体系。未测得用量/费用继续UNKNOWN或HELD；只有可信测量的零值可记零。旧结果不得进候选、接纳或正式发布，旧写权永不恢复。

## 必要验证

最终独立canonical命令：`P0_PROFILE=local P0_EVIDENCE_DIR=<canonical-p0-18> make p0-backend-qualification`。
运行UUID：`p0-30862295395c4081aaa32c160d75b1e6`；工作包UUID：`848aa181-9f94-4f6a-a7e9-704a6c6c07a7`。
源码投影身份：`sha256:9bf26a9e8147e1afc03882524c56f0c9997cff61c5295b77598b89`。源码树、构建/依赖、命令、退出码、日志/JUnit摘要和完整迁移身份由机器证据绑定。

| 门 | 结果 |
|---|---|
| documentation/static/manifests | PASS |
| backend | 5294 PASS＋1508 subtests PASS，0 FAIL，0 SKIP |
| fresh→H198 | PASS，全部199个迁移身份 |
| 0148→0194→H；0184→0194→H及兼容矩阵 | 571 PASS＋13 subtests PASS，0 FAIL/ERROR/SKIP |
| 原生PostgreSQL全矩阵 | FAIL：222 FAIL、11 ERROR、0 SKIP；1666 collected / 1781 JUnit cases |
| 本包选定原生节点 | 144 PASS，0 FAIL/ERROR；Chapter7、API43、CLI40、迁移7、Kernel lease/fence10、取消16、effects21 |
| canonical migration-head/query-plan/Compose | NOT_RUN，前置原生门失败 |
| 同SHA独立query-plan诊断 | PASS，11个计划及3条Reality访问路径；不是P0 PASS |
| 同SHA独立Compose/API/worker诊断 | PASS，全部10进程、原生提交/过期lease/stale fence/重启恢复/排空；18资源清理后0 |
| 联合恢复与副本完整性 | PASS，Chapter337表/600执行文件、API339表/0执行文件；dump与副本哈希验证，恢复后稿件/幂等对账/旧写权拒绝均通过 |
| canonical及开发实验资源清理 | PASS，剩余0；私有联合备份留在仓库外 |

早先不同SHA的PASS仅诊断，不拼接为最终通过。P0-1至P0-17失败/中断及基线归属原始记录保留。P0-16的7项backend失败均在未修改f067复现，已修正现行绑定和合成fixture兼容，最终backend已通过；未删除断言、扩大skip或降低门槛。P0-17只读审查发现普通Chapter manifest误取journal-only repair版本，立即中止该轮并纠正；当前3.0.2候选Pack普通节点严格绑定3.10.0，repair版本仍仅从原journal接续。旧冻结Planning Skill原字节/hash与logical identity保留，现行v4单独绑定。

## 边界与结论

**工程验收结论：FAIL / NO-GO；当前能力证据为`EXECUTABLE`，不能宣布`QUALIFIED`。** 原生恢复与迁移闭环在上述隔离替身证据范围成立；完整canonical P0未通过。不启用真实Provider；真实模型调用、micro-probe、生产迁移/部署、原书续写及文学质量均`NOT_RUN`。联合恢复对象为本轮非空一次性原测试库，不是生产原库，也不是新建空库冒充恢复。历史失败、未知用量、原稿及accepted history保护仍在。


## 失败归属与具体下一动作

canonical P0退出码2，原生全矩阵失败后，migration-head/query-plan/Compose/evidence-finalization按原规则`NOT_RUN`，canonical清理PASS。额外诊断使用独立UUID，不能拼接成一轮P0通过。

本轮233个失败节点均在未修改当前main `f067d189…` 失败过；其中118个错误类别一致，115个从旧绑定前置失败进入其他错误，**根因等同未闭合**。唯一新增到早先失败集之外的timeout节点也已在干净main独立复现同一断言差异。没有把这些失败删除、跳过或归零。全量节点、原错误、当前错误与分类见 `final-native-baseline-attribution.json`。

下一动作按owner拆分，先做能改变结论的窄验证，再在新受测提交重跑canonical P0：

1. Chapter/Context：核对`REALIZATION_SOURCE_BINDING_REQUIRED`、`STYLE_PROJECTION_MIGRATION_REQUIRED`、protected预算不足的第一处真实输入/Artifact与冻结Scope；补有效fixture或修复原owner接线，保留拒绝断言与完整输入预算门。
2. Planning/Kernel：核对raw-result repair的`external_effect.resolve`权限边界、bounded repair和定义版本冲突；沿原权限/回执owner修复，不授予作者额外管理权限、不放宽UNKNOWN重发。
3. 对115项类别变化逐项或按同一根因分组核验；同名失败节点不能证明同一根因。原timeout测试将已调用后的未知结果当作普通可重试失败，当前main同样拒绝；修复该fixture的可信结果分类，保留UNKNOWN fail-closed及共享耗尽断言。
4. 新源码/运行配置如有变化，已有受影响证据失效；冻结新SHA补验。CI目前未报告checks，远端治理仍OPEN，PR保持Draft，未合并/部署。

本报告是非canonical交付记录；当前行为文档仍以`docs/README.md`列出的文档为准。证据归档提交只增加本目录，Git历史及PR记录分别绑定受测代码SHA与归档SHA；归档提交未另执行P0，不作为新的受测代码版本。
