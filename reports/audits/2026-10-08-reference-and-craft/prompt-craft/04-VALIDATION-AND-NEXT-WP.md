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

## 必要对照优先级：叙事方式与写作问题交叉

本轮追加8个同方法选择合成对照及11项窄检查，全部PASS；包括同题材换POV、同问题换题材、只有题材/POV时的选择、通用Skill回退、可选Card为空、作者required Card保持阻断和评价NA边界。详见[离线结果](evidence/multigenre-offline-checks.json)。不代表模型质量，也不表示现行偏差已经修复。

### 对照A：同题材不同叙事方式

先复用同一传统修仙Book的既有事实、人物利益和场景任务，用两份**实验用**叙事参数，例如近距离第三人称与第一人称；作者实际采用的写法仍由作者选择。每种写法分别冻结其POV知识边界，不通过实验越过已批准计划。若任务/合同已固定视角，需要另有实验计划投影；不能冒充只改Prompt的同Plan对照。

在每种写法内部A/B仅改变一项：通用方法选择是否以当前“说明重复/潜台词”等问题为依据，或只改变对应Draft表达指导。方法选择与文笔试验分开，不同时改规划。看方法是否由实际需求匹配、留白在该叙述距离是否合适，人物声音、必要说明和继续阅读的理由是否保留。不能预设两种写法应得到同一方法组合或同样的信息密度。

### 对照B：不同题材使用同一种写作方法

选择一个确有同类问题的其他Book场景，例如当代生活或作者已选其他题材的对话隐瞒/过度说明；与传统修仙场景都使用同一种通用方法（如intentional-gap或对话潜台词）。各Book保留自己的世界、人物、承诺、篇幅及任务；不得移植具体剧情/表达。对同一方法的适用性做跨题材检查，**阅读效果采用各Book内部A/B**，不以两个不同故事的总分互相排名。

最小探索网格可为三种场景条件：同一修仙场景的两种叙事方式＋另一题材同问题场景；每种条件两种指令×两次重复，共12个Draft候选。模型路线/篇幅目标/预算在每个比较内一致。少量结果只能发现适配风险，不能证明普遍提升；Review/Revision/压缩/重试等额外调用另计未来总额。若第二Book缺授权输入，跨题材文学对照保持NOT_RUN，**不阻断首轮完整正文交付**。此规模是必要验证设计，不是新调用授权。

### 规划问题与文笔问题分别处理

若已选Book没有清楚行动目标/阶段承诺，先在同Book、同阶段做原规划与“只补作者已选正向目标”的候选对读，不能将改变事件的收益说成文笔提高。若Plan已有戏，只改变表达指导，保留事实与结果。不得把修仙场景中的修炼、宗门、资源或升级写入公共条件。

### 审稿、修订与选稿须一同检查

盲读记录人物行动、必要说明、独立声音、潜台词、幽默、节奏和继续读的理由及反对意见。Review须按每份冻结Style/承诺判，不因选了某POV或没用某题材常见方法扣稿。作者选择一个具体文学目的和保留项后才进行改稿，旧稿可获选；事件/知识变化转Plan Change。检查新稿是否消冲突或磨平个性，不因模型分高采用。无正文证据时不能判质量，通过Schema/工程检查也不能代替阅读。

## 真实调用授权条件

未来另一个执行任务须绑定：选定Book与完整作者输入/来源用途；确切模型路线/推理与相同上下文；包含生成、语义Review、压缩、失败和恢复的调用/token/金额上限；输出位置与native identities；明确仅候选/是否允许接纳；unknown对账与暂停条件。本轮无这些新调用授权，未发送。既有历史授权不自动续用到新Book或新实验。

## 下一项：WP-WORK-ADAPTATION-AND-READER-PROMISE-TO-PROSE-01（建议，未执行）

目标：复用通用生产链将本书作者目标落实为完整正文。首轮Book为传统修仙；工作包职责与方法保持多题材，不建立题材框架，不以完备题材库为交付前提。

1. 将本轮完整阅读目标作为**本书要求**，经既有creative input selection / brief / author design登记；主题、具体人物、文风、篇幅及长度保留作者选择，不沿用历史测试数值。
2. 复用Foundation候选与作者选择，审清主角实际追求、配角独立利益、阶段承诺和易懂规则；选定方案后复用Book/Arc/Group/Chapter规划。已有原生版本与授权可用则复用，不建设新Agent或评分资格。
3. 在一个开始阶段取得少量相连完整章节，读者能跟住一次行动、实际阻力和阶段结果；不要先跑整本，也不宣称这些章足以证明长篇质量。先只运行当前主链，暴露的问题决定是否做上述对照。
4. 作者读完整章，选一个最影响阅读的文学问题和保留项，经现有作者改稿路径或最小必要补接实施；若须改上游，明确Plan Change。保存旧稿、改稿、选择及理由。
5. 若方法选择确实受本补充确认的窄affinity排序影响，另授权既有MKAOS内的最小元数据/评分修正，保持typed适用边界、作者required资料、版本与依赖，不复制题材Skill。首批正文不必等此调整。
6. 交付完整正文、精确请求/版本/成本、阅读反馈、修订前后及选择证据。工程必要checks与文学判断分别报告。完成标准是具体阅读目标在这段文字得到作者确认或明确未达成；不是分数达标或精品承诺。

仅在上述链条确认缺实际入口时，另授权最小实现工作；不要顺便扩大平台或将本报告例子固化为公共模板。


补充环境取证：当前PATH的Codex CLI版本检查返回ENOENT；未修复、安装或重新绑定。实际运行版本应通过原生配置/运行回执核查，不能拿外层会话模型或全局npm包代替。末次仓库状态检查与开工相同。
