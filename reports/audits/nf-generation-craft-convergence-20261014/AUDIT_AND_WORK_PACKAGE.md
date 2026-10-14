# Completed read-only compatibility audit

Source task: `01a13896-cf12-7821-a94f-b2279d800c88`.
Original assessment is preserved below; frozen SHA and historical state claims
remain historical. This is a proposal, not implemented integration or runtime
authority. Local file links refer to audit-time source checkouts.

已确认真实兼容风险，并找到本地完整 craft 提交；可以按代码制定方案。[PR #169](https://github.com/yuan2go/novel-forge/pull/169) 的归档不代表 craft 已整合。

**Codex 工作包：`WP-NF-GENERATION-CRAFT-CONVERGENCE-01`**  
状态：`PROPOSAL / NOT_RUNTIME_AUTHORITY`；本轮完成只读审查，实施尚未开始。

| 固定对象 | 审查结果 |
|---|---|
| 最新 main `fd335a5d` | PR #169 已合并，迁移 head 为 `0209` |
| PR #168 `8af490d0` | 仍为 Draft；最新代码已有 `0210`、`0211`，正文中的旧 HEAD 已过期 |
| craft `833b0bcc1280bee76bc8b7f99d6939df0f5e05a6` | 本地 Git 对象完整；新增另一组 `0205–0207` |
| craft 当前本地 HEAD `1ce122e3` | 另有 `0208`、Book 方法上下文及 CLI 输出余量改动，需要单独评审增量 |

GitHub API 仍不能解析 `833b0bcc`，但本地源码可核验。实际数据库目录、已应用迁移及部署状态本轮未核验。《炉火照仙途》4390 汉字、正式接纳为 0，是 [PR #168 已公布的历史证据](https://github.com/yuan2go/novel-forge/pull/168)，不作为当前运行状态声明。

**必须解决的兼容边界**

| 优先级 | 已核实风险 | 整合要求 |
|---|---|---|
| P0：迁移历史 | 两条链从 `0204` 分叉；当前运行器拒绝 foreign/discontinuous 历史 | 保留完整迁移身份、父链和历史正文；不能删除或伪造 applied IDs |
| P0：容量 SQL | craft `0207` 从旧 `0203` 重建 `authority_unsent_context_continuation_permitted`，缺少生成链后续的 World 恢复条件 | 新增组合迁移，保留双方有效条件；不能直接采用一侧函数 |
| P0：Book 作用域 | craft `0206` 修改 Story Design 活跃版本主键并回填 Book 血缘 | 先检查血缘歧义与命名空间冲突；恢复通过原 Owner 追加 `RECONCILE_SCOPE` |
| P0：Schema／Writer | craft 增加输出 Schema、方法召回投影；PR #168 增加完整 World 正文传输和恢复证明 | 按冻结版本分派；旧请求保持原渲染，新投影不得丢失方法条件、作者篇幅或选定正文 |
| P0：正文与执行血缘 | 工作选定、正式接纳、完整结果复用和 UNKNOWN 各有不同边界 | 保留原 AssetVersion、选稿根、依赖、Attempt、Effect、回执及用量状态；参考 Agent 样本不得成为生产正文 |

容量覆盖风险可直接见 [craft 0207 源码](/private/tmp/nf-generation-craft-audit-20261014/craft833/src/novel_forge/storage/migrations/versions/v20261014_0207_foundation_method_context.py:3)；分叉库拒绝规则见 [迁移运行器](https://github.com/yuan2go/novel-forge/blob/fd335a5d6ec937a30afdb08cb916d5a52809b7dc/src/novel_forge/storage/migrations/runner.py#L54)。

**实施顺序**

1. **先完成文档对账。** 已读取 canonical 文档及相关恢复、Context、Craft 章节。开工时重新冻结远端 SHA，整理旧 PR HEAD、旧冲突树和旧迁移范围；历史报告保留其原 SHA，仅更新现行 canonical 投影，不新增平行架构文档。
2. **建立独立整合候选。** 从最新 main 开隔离分支，逐项纳入已审查的 PR #168 增量，保持 Draft 原样。若目标链保留 `0210/0211`，craft 新语义从其后追加新迁移；开工时重新确认编号。历史迁移文件保持原字节。
3. **组合恢复契约。** 保留 World 完整结果、工作前沿及 unsent 输入恢复，再增加 craft 的精确 Foundation 方法恢复分支。共同保留 actor、Book、输入哈希、授权、Lease/Fence、取消与暂停检查；不同恢复模式分别验证 Effect 条件，不能统一要求“零 Effect”。
4. **证明数据保存。** 在隔离副本上对比正文正文哈希、选定版本、前文依赖、accepted cursor、执行回执、恢复 journal 和 UNKNOWN 账目；恢复还须包含匹配的对象存储与 CLI 目录。
5. **单列 craft 分叉库收敛。** 当前普通升级路径不支持其 ledger。保持原库和原 release，另行设计有界、可审计的历史转换；未在副本证明前标记 `BLOCKED`，不通过放宽 foreign-history 检查绕过。

**保留技法能力的方式**

保留 `Evidence → Observation → Abstraction → MKAOS 审批 → 有界选择 → Planning → Writer` 链及版本血缘。保留真正的前提、禁忌、依赖和作者明确要求；每项方法允许 `ADOPT/ADAPT/REJECT`，交付候选不等于必须使用。

人物反应、对话目的、行动后条件可以作为局部创作工具。不能把“每场必须反转、每次行动必须付出损失、每句对话必须有潜台词”升级为通用硬门禁。错误抽象通过新版本修正；原文、教学例子和审批行政语句不进入人物行为要求。当前实验审批也不能自动升级为生产资格。

**只安排结论相关的验证**

- **迁移／SQL：** 首装、main `0209` 升级、候选 `0211` 升级、craft foreign-history 拒绝；容量与 World guard 同时覆盖合法恢复和错 Book、漂移哈希、暂停、取消、活跃 Lease、未解决 Effect 的拒绝。
- **Source／作用域：** 运行 Source isolation、abstraction Schema recovery、Story Design namespace/reconciliation 的相关用例，验证旧 Schema 回放、完整结果复用和历史保存。
- **原生 Writer／正文：** 使用真实组装器和禁止外部发送的替身，检查完整 stdin：作者篇幅、选定正文、技法条件均到达，正文只传一份；前文改选仍显示依赖变化，精确导出保持内容。
- **治理：** 检查迁移注册、manifest、Reality、指令绑定与受影响 canonical 文档。

本轮静态链及历史迁移字节检查为 `PASS`；PostgreSQL、恢复、Provider、完整发布矩阵为 `NOT_RUN`。后续定向验证最多支持相应 `EXECUTABLE` 证据，不升级为 `QUALIFIED` 或 `PRODUCTION_PROVEN`。工作包不触发第2章生成、Draft 合并或原始生产实例操作。
