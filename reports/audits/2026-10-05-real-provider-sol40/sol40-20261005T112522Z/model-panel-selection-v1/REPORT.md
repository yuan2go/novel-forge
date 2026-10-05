# Codex 6.1 high 三角色选型与正式准入预检

依据直接用户指令“盲评者和裁决者用codex 6.1sol high来实现”，两位盲评者和一位裁决者均选择 `codex-cli / gpt-6.1-sol / high`；创作端仍为 `gpt-6-sol / medium`。

**只完成模型选择与冻结；正式接入尚未实现，没有评审结果。** selection.json 是 operator intent，不是运行时 Authority、资格、Provider receipt 或 HumanEvaluation。源码预检绑定 `427433aac3d78bbc7d48fdaa782d5d2a50209110`，原运行仍绑定22，没有改写旧Book、budget、freeze或失败历史。

## 已完成的独立工作

- 三角色选择及hash已冻结；每个未来角色必须使用不同的native Effect/session，两个盲评者不读取彼此输出，裁决者读取两份精确版本报告。
- 盲化要求保留原作者/作品约束与稿件语义，去掉来源Provider/model/route及既有分数。不得去掉裁决所必需的事实或通过盲化混入另一书的Context。
- 本机CLI模型目录列出gpt-6.1-sol/high。该STATIC目录读不证明账户当前推理可用、容量实测或模型质量。
- 正式生产装配预检：当前实际Router没有gpt-6.1-sol候选，只有gpt-6-sol/medium的Codex升级候选及DeepSeek候选。没有把新模型名称伪装成现有候选身份。
- 原生只读查询确认无候选稿/样本可供评审，Effect、dispatch、receipt、章节接纳、Pack approval/activation/deployment均0。
- 总预算仍1600 calls / 80m tokens / priced USD20；没有增额、续期、重分配或写入新原生授权。没有调用模型或花费DeepSeek额度。
- 用户原checkout HEAD/branch和10条未跟踪路径保持原样。此轮没有修改生产代码、Prompt、Skill、Schema或生成虚构human记录。

## 当前真实实现约束

- `authority_dependencies.py:918` 的单Codex型号限制是CURRENT_RUNTIME_FACT / UNRESOLVED_DESIGN_CONSTRAINT，不能当作不可变架构。正式装配需要显式支持创作6-sol和参考评审6.1-sol各自model/effort/task scope、精确授权及恢复身份。
- `AdjudicatedEvaluation` 和native Chapter/Planning参考准入只接纳至少两份HumanEvaluation及独立真人裁决。AUTOMATED_JUDGE不是这些真人身份类别之一。
- 现有`JudgeEvaluation`记录允许模型输出，但明确未校准且禁止自资格，不能通过改evaluator_id或actor字符串转成HumanEvaluation。
- 三次同型号会话可以隔离输入和调用身份，仍属于相关的模型共识，不能声称三个统计独立真人或读者偏好。
- ACTIVE Pack部署缺失及Codex主生成lane/严格冷启动缺口仍是独立阻断。

因此，给三角色写上模型名不足以完成模型资格替换。若选择模型共识作本次参考，应在现有Quality/Content/Router/Kernel中实现明确版本的模型参考证据合同，保留实际ModelCallLog、source/hash/baseline、两个原始盲评和独立裁决、失败/分歧/UNCERTAIN、预算及恢复，并与真人合同分开；不能改旧资产的含义或宣称HUMAN_CALIBRATED。若仅选辅助审读，旧真人资格门保持。

已发出一次作用范围澄清：模型共识用于本次资格参考，还是仅辅助审读。两种选择都不允许宣称文学质量已证明。当前预检的BLOCKED来自已证实的正式合同/路由/部署/样本缺口；不是把未回复当作拒绝，也没有把经过时间当作审批。

## 证据状态

MODEL_SELECTION = PASS（STATIC）
FORMAL_MODEL_PANEL = BLOCKED（当前尚未WIRED）
INDEPENDENT_MODEL_REVIEW = NOT_VERIFIED
MODEL_ADJUDICATION = NOT_VERIFIED
HUMAN_CALIBRATION = NOT_VERIFIED
REAL_PROVIDER_VALIDATED = NOT_VERIFIED
CREATIVE_QUALITY_PROVEN = NOT_VERIFIED

真实模型推理0；接纳0/40。没有后台三角色worker正在运行。既有严格启动报告保留其冻结范围。
