# 04. 项目孵化层 Project Incubation

## 1. 模块目标

项目孵化层负责把用户的创意转化为可执行的小说项目。

它位于全局资产层与单本小说项目层之间，是 NovelForge 的“总编室”。

## 2. 核心职责

```text
1. 与用户进行创意访谈；
2. 生成多个项目候选；
3. 判断读者吸引力；
4. 判断项目差异化；
5. 检索通用知识；
6. 选择世界模板或共享世界；
7. 选择哲学方向；
8. 编译项目知识包；
9. 生成项目宪法；
10. 初始化 Novel Workspace。
```

## 3. 总体流程

```text
用户创意输入
  ↓
总编 Agent 访谈
  ↓
生成 3-5 个项目候选
  ↓
Reader Attraction Gate
  ↓
Project Differentiation Gate
  ↓
Knowledge Compiler
  ↓
Project Constitution
  ↓
Novel Workspace Initializer
  ↓
Claude Code 接管
```

## 4. 总编 Agent 的定位

总编 Agent 不是正文作者，而是项目孵化者。

它负责：

```text
创意澄清
题材定位
读者定位
卖点测试
世界选择
哲学方向选择
商业吸引力判断
同质化风险判断
项目知识包生成
```

不负责：

```text
逐章写正文
每日评论处理
直接改 final
绕过项目宪法
```

## 5. 创意访谈模板

```markdown
# 新小说项目孵化请求

## 1. 想写的类型

玄幻 / 都市 / 悬疑 / 科幻 / 权谋 / 系统流 / 末日 / 历史 / 其他

## 2. 目标读者

他们喜欢什么？
他们讨厌什么？
他们希望获得什么情绪？

## 3. 核心爽点

打脸 / 反杀 / 升级 / 揭秘 / 权谋 / 赚钱 / 探案 / 复仇 / 生存 / 争霸 / 经营

## 4. 哲学方向

自由 vs 秩序
命运 vs 意志
复仇 vs 救赎
真相 vs 幸福
力量 vs 代价
个人 vs 集体
其他

## 5. 世界类型

新建世界 / 使用已有共享世界 / 从世界模板生成 / 不确定

## 6. 禁止内容

不想写什么？
不想接近哪些作品？
不想出现哪些设定？

## 7. 风格

热血 / 黑暗 / 诡异 / 爽快 / 冷峻 / 轻松 / 压迫感强

## 8. 连载目标

前 10 章目标：
前 30 章目标：
预计字数：
更新频率：
```

## 6. 项目候选输出格式

总编 Agent 每次至少输出 3 个候选方案。

```markdown
# 项目候选方案 A

## 项目名

## 类型

## 一句话卖点

## 目标读者

## 主角

身份：
欲望：
恐惧：
压迫：
能力：
代价：

## 核心爽点

## 哲学命题

## 世界来源

新建世界 / 世界模板 / 共享世界实例

## 前 3 章钩子

1.
2.
3.

## 前 10 章回报

## 主要风险

## 初步评分

读者吸引力：
差异化：
可信度潜力：
原创风险：
```

## 7. 项目孵化的四个关口

### 7.1 Reader Attraction Gate

先判断是否好看。没有足够吸引力，不进入世界构建。

### 7.2 Project Differentiation Gate

判断是否和已有项目太像。相似度过高则重构。

### 7.3 Knowledge Compiler

把通用知识编译成本书专属知识包。

### 7.4 Project Constitution

生成项目最高规则，交给 Claude Code 执行。

## 8. 项目孵化输出物

一个可交接给 Claude Code 的项目必须包含：

```text
reader_attraction_gate.md
project_differentiation_gate.md
project_knowledge_pack/
project_constitution.md
PROJECT.md
CLAUDE.md
01_bible/world_constitution.md
02_outline/serialization_plan.md
06_memory/current_context.md
```

## 9. 立项否决条件

出现以下情况，不能进入 Claude Code 执行：

```text
1. 一句话卖点说不清；
2. 目标读者不明确；
3. 主角欲望不清；
4. 主角压迫不具体；
5. 前 3 章没有钩子；
6. 前 10 章没有奖励兑现；
7. 与已有项目高度相似；
8. 哲学命题只是口号；
9. 世界规则明显自相矛盾；
10. 原创风险过高。
```

## 10. 模块验收标准

项目孵化模块完成一次任务，必须输出：

1. 至少 3 个候选项目；
2. 每个候选项目有一句话卖点；
3. 每个候选项目有目标读者；
4. 每个候选项目有主角欲望和压迫；
5. 通过 Reader Attraction Gate 的评分；
6. 通过 Project Differentiation Gate 的评分；
7. 生成项目知识包；
8. 生成项目宪法；
9. 初始化小说 workspace；
10. 形成 Claude Code 可接管状态。
