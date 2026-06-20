# 08. Project Constitution 项目宪法

## 1. 模块目标

项目宪法是单本小说的最高规则。

它约束：

```text
Claude Code
DeepSeek
ChatGPT/Codex
任务卡
审稿系统
评论反馈
后续重构
```

任何模型、任何任务、任何评论反馈都不能绕过项目宪法。

## 2. 为什么需要项目宪法

没有项目宪法，小说生产会出现：

1. 写到后期偏离开局卖点；
2. 主角欲望漂移；
3. 反派行为失控；
4. 世界规则随剧情变化；
5. 评论反馈带偏大纲；
6. 多学科知识越加越多；
7. 哲学方向变成说教；
8. Claude Code 修改边界不清。

项目宪法用于固定这本小说的核心身份。

## 3. 输入

```text
reader_attraction_gate.md
project_differentiation_gate.md
project_knowledge_pack/commercial_pack.md
project_knowledge_pack/philosophy_pack.md
project_knowledge_pack/credibility_pack.md
project_knowledge_pack/world_pack.md
project_knowledge_pack/character_pack.md
project_knowledge_pack/plot_logic_pack.md
project_knowledge_pack/style_pack.md
project_knowledge_pack/feedback_control_pack.md
project_knowledge_pack/originality_risk_pack.md
```

## 4. 输出路径

```text
04_novel_projects/{project_id}/project_constitution.md
```

## 5. 项目宪法模板

```markdown
# 项目宪法

## 1. 项目身份

项目名称：
类型：
目标读者：
核心卖点：
连载目标：
预计规模：

## 2. 读者吸引力

读者为什么点进来：
读者为什么追读：
前 3 章必须提供什么：
前 10 章必须兑现什么：
每章最低商业单元：

## 3. 哲学方向

核心命题：
价值冲突：
主角初始信念：
主角中段崩塌：
主角最终答案：
反派代表的合理价值：
哲学如何通过选择和代价体现：
禁止说教方式：

## 4. 主角核心

主角欲望：
主角恐惧：
主角压迫：
主角能力：
能力代价：
主角不能做的事：
主角阶段性成长：

## 5. 反派核心

反派目标：
反派资源：
反派价值观：
反派限制：
反派为什么不直接杀死主角：
反派失败的必要原因：

## 6. 世界宪法

世界第一规则：
力量边界：
资源规则：
权力规则：
社会规则：
法律规则：
代价机制：
不可修改项：

## 7. 商业爽点边界

允许使用的爽点：
禁止滥用的爽点：
每章最低奖励：
连续压迫上限：
前 10 章必须兑现的奖励：

## 8. 反馈红线

评论可以影响：
评论不能影响：
不可修改项：
可局部调整项：
需要主编确认的调整：

## 9. 原创风险边界

不可复用内容：
必须抽象使用的知识：
相似度风险处理方式：
禁用表达：

## 10. 执行规则

Claude Code 每次必须读取哪些文件：
DeepSeek 负责什么：
ChatGPT/Codex 负责什么：
哪些文件不能直接修改：
每次任务必须更新哪些文件：
```

## 6. 不可修改项

项目宪法中必须明确以下不可修改项：

```text
世界第一规则
主角核心欲望
主角能力代价
反派核心逻辑
哲学终局方向
原创风险边界
目标读者核心期待
```

普通评论、普通任务卡、普通章节生成任务不能修改这些内容。

修改不可修改项必须进入重大重构流程。

## 7. 重大重构流程

如果确实需要修改项目宪法中的核心规则，必须生成：

```text
constitution_change_proposal.md
```

模板：

```markdown
# 项目宪法变更申请

## 变更项

## 变更原因

## 影响范围

## 是否影响前文

## 是否影响已发布章节

## 是否影响主角成长线

## 是否影响哲学终局

## 是否影响世界宪法

## 可替代方案

## 主编决策

接受 / 拒绝 / 延后 / 仅作为分支实验
```

## 8. Claude Code 必读规则

Claude Code 每次执行任务前必须读取：

```text
project_constitution.md
PROJECT.md
CLAUDE.md
06_memory/current_context.md
08_tasks/current_sprint.md
```

涉及章节生成时，还必须读取：

```text
02_outline/chapter_plans/{chapter}_plan.md
06_memory/character_state.md
06_memory/unresolved_foreshadowing.md
```

## 9. 模型边界

### DeepSeek

可以：

```text
生成正文 v0
批量摘要
评论分类
知识卡初稿
```

不能：

```text
修改项目宪法
决定是否采纳重大反馈
改变哲学终局
```

### ChatGPT/Codex

可以：

```text
立项判断
项目知识包编译
审稿
重大反馈判断
重构建议
```

不能：

```text
绕过主编确认直接改 final
直接复制已有作品结构
```

### Claude Code

可以：

```text
管理项目文件
执行任务卡
整理结果
更新 memory
```

不能：

```text
无任务卡自由重构
直接改 final
直接修改项目宪法不可修改项
```

## 10. 验收标准

一个项目宪法必须满足：

1. 目标读者明确；
2. 核心卖点明确；
3. 主角欲望明确；
4. 反派合理性明确；
5. 哲学命题能转化为剧情压力；
6. 世界第一规则明确；
7. 评论反馈红线明确；
8. 原创风险边界明确；
9. 模型分工明确；
10. Claude Code 可直接读取并执行。
