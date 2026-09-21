# 原生校准实现与进展报告发布

本次按用户明确指令，将已保存的业务代码、测试代码和进展报告提交、推送并通过 PR 合入 main；不再运行测试。发布代码不代表原 Real Provider Calibration / 12 章 Novel Production 工作包完成。

[完整进展报告](progress-20260921-0843.md) 保留 2026-09-21 08:43 快照的原始字节，说明已实现内容、未实现目标、耗时原因、调用数和八项验收结论。该快照中的“P0 正在运行、报告未入 Git”等描述仅适用于其记录时刻；当前发布状态以本文件和 [发布记录](publication.json) 为准。

## 本次发布边界

- 代码基点：`dce49a68597e302c1c6c97a8a3eb4f3e4f42d864`。
- 发布前已获取的 main：`e41a2c22e4f24fdb89e6bb2db8a3e00039e7e332`。
- 本地已有 28 个祖先提交：14 个涉及实现/测试、13 个文档/证据、1 个合并。本次另提交报告和发布状态；最终提交 SHA 与数量由 Git / PR 记录确定。
- 当前改动包含原生 Chapter / World / reference 采样、独立标注与回执绑定、既有 Router 反馈投影、campaign 累计预算和混合计费隔离；未新建 Router 或预算事实源。
- 全族生成器准入、部分 Source / Canon / Reader / Quality 冷启动、完整冻结实验和恢复入口仍未闭合。
- 本 campaign 真实调用、真实 Codex 升级、新接纳章节均为 0；质量不劣、成本下降、生产就绪与长篇稳定性均 NOT_PROVEN。

## 测试状态

用户明确要求“不测试”后，没有启动新的测试、工程门禁或测试 hooks。此前在 `dce49a68` 上运行的 canonical P0 已发送 SIGINT 并退出，阶段为 PostgreSQL 全量集成；记录为 `INTERRUPTED_BY_USER`，不是 PASS，也不是模型质量失败。本次提交与合并的测试状态为 `NOT_RUN_USER_REQUEST`。

中断前已经产生的后端、迁移及定向回归结果在进展快照中保留；它们不替代完整 exact-SHA P0。中断日志保留在任务私有证据目录，其摘要在发布记录中。未修改历史测试结果或旧报告。发布时只读 GitHub 查询显示 Actions disabled，没有开启 CI 或更改分支保护。

本次报告提交只新增当前 evidence 目录，不改动业务实现、迁移、既有作品、秘密配置或历史接纳稿。早期证据入口继续保留于 `../real-provider-campaign-20260920/index.json`；其中旧 SHA 的 PASS 不转移到当前版本。
