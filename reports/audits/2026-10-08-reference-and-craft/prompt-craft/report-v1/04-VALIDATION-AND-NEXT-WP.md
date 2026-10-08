# 最小充分验证与下一工作包

## 本轮已做与未做

- PASS：冻结main、导出对应源码；42份真实历史策划请求按冻结Artifact离线组装，42/42全文哈希相符，42/42有匹配stdin receipt。保留原SUCCEEDED/UNKNOWN，不重发。
- PASS（SYNTHETIC/OFFLINE）：6项窄验证：无公共不可逆代价必选；v4章合同不要求通用chapter_hook；本书style_constraints保留；普通Review审美建议不进入自动修订、语义冲突可进入；同一最小Scene的旧core slots为5、当前continuous为1。只证明指令/字段行为。
- BLOCKED：一次只读PostgreSQL连接未成功；Docker daemon不可用。没有查询成功的最新Pack、已接纳正文、Review或release身份。保持未核实，未反复尝试、未恢复服务。
- NOT_RUN：新真实Provider调用、完整P0/后端/迁移矩阵、模型评测、读者盲评、传统修仙正式章、跨章文学质量验证、生产接纳/恢复。此次不改变实现，因此没有工程完成或QUALIFIED声明。

执行保护：离线脚本禁socket connect、subprocess、psycopg connect；脚本写入限制为审查目录，禁止main快照。导出正文时只读本地保留的last-message与receipt。早期合成检查漏了两个required lineage字段导致KeyError，补齐**审查脚本的合成输入**后才得最终结果；不改生产源。Default constructor导出的Schema仅为work-mode构造视图；真实Schema由catalog和42份冻结请求记录，不混为部署Schema。

可复核脚本：`offline_audit.py`（不需要网络或数据库）；结果：[offline-checks.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/offline-checks.json)、[retained-request-verification.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/retained-request-verification.json)。不能为了复核文学观点启动全仓资格测试。

## 必要补证（不发模型请求）

在原数据库/服务恢复可读后，一次限定只读导出：当前Book作者简报、选题记录及hash；Foundation/Plan版本；当前安装Pack及release；同章Draft/Review/Revision/ReReview/selection；final Provider stdin与schema；ChapterOutcome与Book acceptance；Canon/State cursor。按native ID取，不换run，不将本地5份顺序推为父子。每条列出model/profile、prompt/Skill版本、调用成本/回执及接纳状态；未知成本保持UNKNOWN。

这能改变两个结论：样本解释密度是规划要求、Prompt表现还是修订引入；现成作者授权的文学改稿是否已经可执行。若数据库仍不可读，仅凭文件不得升级。

## 对照1：本书目标是否形成可写行动（改规划）

固定同一本传统修仙作者brief、选定人物与世界、同阶段/章节范围、相同模型路线和预算。A用原当前规划输入；B只把**已明确的本书**修仙成长/连载阅读期待绑定到既有Reader Promise和Chapter Mission，明确人物目标、对方利益、阶段进展；不添加每章升级、代价或固定结构。父事实/知识/版本保持一致，输出Plan候选。只在作者批准某个候选后才能用于正式Draft。

比较：编辑能否从Plan说明“人物下一步为什么行动、读者在等什么、进展如何带来后续问题”；是否仍只是在验证资格或解释规则；是否把配角独立目标压成纠错；是否固定了非必要对白心理结论。先只比较计划，**不把B正文的差异归因于文笔**。若A已充分落实作者目标，则停止这项修改。

## 对照2：说明密度与作者判断（只改文笔）

选两处已有明确行动目标、不同叙事负荷的Scene：资源/机会争取中的人物交锋，和修炼/宗门日常中的较轻段落。固定完整Plan/World/知识/结果、目标篇幅、上下文、模型路线、当前continuous-scene合同。A使用当前Draft方法；B只加入建议的“行动已能说明的判断不再同义翻译；核验留宿主证据，除非本为剧情”的指导。不能改变事件、删因果或另造冲突。

各条件在同一场景至少有重复样本，避免单次幸运。最小探索规模可为2场景×2条件×2输出＝8次Draft调用；**这是计划，不是授权**。Review/压缩/重试等额外真实调用须计入未来总上限与成本，不能隐藏在8次之外。

盲读时先不出总分，记录：能否自然跟住人物行动；哪些句子替读者解释了已有信息；哪些说明确有必要；人物说话是否可辨；细节是否改变理解；幽默/潜台词是否保住；哪一稿更愿继续读，以及相反理由。Schema、因果、知识和事实检查独立；有效说明不得因偏好留白被扣掉。若B只缩短而损失清晰度/声音，否决B。

## 条件性对照3：审美修订能否改善且不磨平

只有选定一个有具体文本证据、作者明确采纳的文学目的才做。冻结旧稿及精确范围，列保留项；A保留旧稿，B由既有可用改稿入口执行所选目的。只比较相同事实/规划下的阅读效果。人物行动或事件结果需要改变时另走Plan Change，不能伪称局部文笔编辑。对读“问题是否改善”和“优势是否丢失”；旧稿可获选，不因模型分数增加采用B。

## 真实调用授权条件

未来另一个执行任务须绑定：选定Book与完整作者输入/来源用途；确切模型路线/推理与相同上下文；包含生成、语义Review、压缩、失败和恢复的调用/token/金额上限；输出位置与native identities；明确仅候选/是否允许接纳；unknown对账与暂停条件。本轮无这些新调用授权，未发送。既有历史授权不自动续用到新Book或新实验。

## 下一项：WP-TRADITIONAL-XIUXIAN-READER-PROMISE-TO-PROSE-01（建议，未执行）

目标：用现有生产链取得本书可读的传统修仙正文与作者判断，先消除作品要求到正文的空档。

1. 将本轮完整阅读目标作为**本书要求**，经既有creative input selection / brief / author design登记；主题、具体人物、文风、篇幅及长度保留作者选择，不沿用历史测试数值。
2. 复用Foundation候选与作者选择，审清主角实际追求、配角独立利益、阶段承诺和易懂规则；选定方案后复用Book/Arc/Group/Chapter规划。已有原生版本与授权可用则复用，不建设新Agent或评分资格。
3. 在一个开始阶段取得少量相连完整章节，读者能跟住一次行动、实际阻力和阶段结果；不要先跑整本，也不宣称这些章足以证明长篇质量。先只运行当前主链，暴露的问题决定是否做上述对照。
4. 作者读完整章，选一个最影响阅读的文学问题和保留项，经现有作者改稿路径或最小必要补接实施；若须改上游，明确Plan Change。保存旧稿、改稿、选择及理由。
5. 交付完整正文、精确请求/版本/成本、阅读反馈、修订前后及选择证据。工程必要checks与文学判断分别报告。完成标准是具体阅读目标在这段文字得到作者确认或明确未达成；不是分数达标或精品承诺。

仅在上述链条确认缺实际入口时，另授权最小实现工作；不要顺便扩大平台或将本报告例子固化为公共模板。


补充环境取证：当前PATH的Codex CLI版本检查返回ENOENT；未修复、安装或重新绑定。实际运行版本应通过原生配置/运行回执核查，不能拿外层会话模型或全局npm包代替。末次仓库状态检查与开工相同。
