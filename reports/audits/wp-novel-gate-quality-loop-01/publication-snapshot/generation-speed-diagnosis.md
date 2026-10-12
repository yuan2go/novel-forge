# Historical read-only assistant diagnosis

Source task: `01a13110-6df3-7150-b2a5-63bd2d3a9905`. This is the completed
assistant diagnosis, not a new runtime check or current production result.
Local source links reflect the original task checkout and may drift later.

**慢主要来自三件事：首章前的规划调用太多、每次模型任务很重、Writer 超时后又重复同样的失败。** 我核对了当前代码和《山河有路》10 月 11—12 日的保存记录。

| 原因 | 实际证据 | 对速度的影响 |
|---|---|---|
| 前置规划及返工多 | 第一章正文前已有 **79 次成功调用**，累计 **7 小时 9 分钟**；卷纲 29 次、事件弧 25 次，共约 **5 小时 5 分钟** | 大量时间花在写正文之前 |
| 单次调用负担重 | 79 次全部使用 `high` 推理强度；中位耗时 **333 秒**，95 分位约 **533 秒** | 一次调用通常就需数分钟 |
| Writer 时限分配不匹配 | 总时限 600 秒，按两次尝试分配并扣结算余量，实际每次只有 **270 秒** | 两次均约 271 秒结束，没有完整结果 |
| 重试没有改变失败条件 | 两次 Writer 使用相同模型、相同输入、相同时间边界 | 又等了一轮，最终仍交付 **0 章** |

超时公式在当前代码中仍然存在：`600 ÷ 2 − 30 = 270 秒`。[代码位置](/Volumes/DevSSD/Development/Workspace/projects/novel-forge/src/novel_forge/modules/chapter_authority/execution_gateway.py:2980)

另外，第一章 Writer 的完整提示词有 **84,791 个字符**，保守估算约 **39,635 tokens**，却只要求输出 4000—5000 汉字。输入负担值得精简，但目前没有对照实验，不能量化它造成了多少延迟。

还有两个需要分开的事实：

- 从首个成功调用开始，到 Writer 前，墙钟时间约 **10 小时 57 分钟**。其中约 **3 小时 49 分钟处于调用间隙**，包含修复、检查、暂停和编排等待；现有记录不足以继续精确归因。
- 正式章节还要经过审阅、修订、复审、事实提取和五组质量评审。这会增加交付时间，但上述失败样本尚未走到这些阶段，不能把它们算成本次超时的原因。[依赖链](/Volumes/DevSSD/Development/Workspace/projects/novel-forge/src/novel_forge/modules/chapter_authority/orchestrator.py:774)

**优先改进顺序是：先修正 Writer 的时限分配和重复失败策略，再减少首章前的规划返工，随后精简各阶段上下文、按任务配置推理强度。** 延长超时只能减少过早终止，真正提高速度还需要减少调用次数和每次调用的负担。

本次是只读诊断，没有修改代码或重新调用模型。以上交付数量属于历史检查点；尚无证据证明数据库是主要瓶颈，也不能保证延长超时就一定生成成功。
