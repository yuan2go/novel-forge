# 雨线之外

这是首部长篇试生产项目的素材、创作输入与历史证据快照。按用户要求保存到 GitHub main，业务权威仍在原生 PostgreSQL 和对象存储中。

当前实际状态：真实模型调用 0，批准 Card 0，接纳章节 0，独立评审 NOT_REVIEWED。长篇目标为 180 章，近期停止游标为 6；目前没有真实生成的章节正文。

本轮可阅读的首弧作者设计、素材适配和新操作入口见 [当前创作导航](current/README.md)。它们是未审批草案，与下列历史冻结、fixture 和交付证据分开保存。

- [原创方向、人物、读者承诺与约束](frozen-pilot-final/brief.json)
- [长篇及近期章组创作输入](frozen-pilot-final/creation.json)
- [Formation 输入](frozen-pilot-final/formation.json)
- [素材目录](corpus/index.html)与[可直接浏览的目录数据](corpus/catalogue-native-export.json)
- [原始材料及来源许可](corpus/catalogue.json)、[精选版本](corpus/selections.json)、[问题清单](corpus/issues.json)
- [Source 分析计划](source-analysis-plan.json)与[待确认调用范围](authorization-assessment.json)
- [原生操作与恢复说明](OPERATIONS.md)
- [前一工作包交付报告](DELIVERY.md)与[完整证据索引](DELIVERY.json)
- [文件哈希、压缩及脱敏记录](publication-manifest.json)

`development/` 中的章节文件属于工程 fixture，不是《雨线之外》的真实正文。`final-qualification/` 是此前验证过的代码版本的历史证据；最初上传归档的 PR #80 没有运行测试。历史报告中的“未 push / PR / 合并”描述其生成时点，本目录的上传以 Git 历史为准。

原文件基本按原路径保留，源文件没有改写。唯一超过 GitHub 单文件限制的 PostgreSQL JUnit XML 采用 `.xml.gz` 无损保存，可用 `gzip -dk <文件>.xml.gz` 还原；源文件和压缩文件哈希见清单。三份历史命令/失败日志中的带口令连接地址在上传副本中脱敏，清单保留原始哈希及变换类型。

`runtime/local-environment.json` 含数据库与对象存储凭据，仅保留在本机，不上传。8 项可重建的解释器/pytest 缓存也仅留本地；其余本包原有产物（含原文、对象快照、数据库备份及恢复记录）均已保存。运行说明和历史记录中的绝对路径属于原执行环境，换机器时需配置自己的私有环境。不要将备份恢复到已有业务库。

本目录不会授予新的模型调用或知识批准权限，也不能证明知识增强收益、六章试生产或长篇质量已完成。
