# 14. 多项目调度系统 Multi-Project Scheduler

## 1. 模块目标

多项目调度系统用于管理多本小说并行推进，避免项目混乱、同质化和上下文污染。

NovelForge 的长期目标不是只生产一本小说，而是形成项目池：

```text
主力连载项目
备用孵化项目
实验项目
暂停项目
完结项目
```

## 2. 项目注册表

路径：

```text
03_project_registry/project_registry.md
```

记录字段：

```text
项目 ID
项目名称
类型
世界实例
哲学命题
目标读者
当前章节
当前状态
今日任务
风险等级
主模型
审稿模型
最近更新时间
```

## 3. 项目状态

```text
idea：创意阶段
incubating：孵化中
approved：已立项
drafting：生产中
serializing：连载中
paused：暂停
revision：重构中
finished：完结
abandoned：放弃
```

## 4. 项目优先级

| 优先级 | 项目状态 | 处理方式 |
|---|---|---|
| P0 | 正在连载且反馈异常 | 优先处理 |
| P1 | 正在连载且需要今日更新 | 正常处理 |
| P2 | 已立项，需要细纲或存稿 | 空闲处理 |
| P3 | 孵化中项目 | 周期性处理 |
| P4 | 实验项目 | 低优先级 |
| P5 | 暂停项目 | 不自动处理 |

## 5. 第一阶段并发建议

V1 阶段建议最多维护：

```text
1 本主力连载项目
1 本备用孵化项目
1 本实验项目
```

不建议一开始同时运行大量项目。原因是主编判断会被分散，评论反馈处理会复杂，同质化风险也会升高。

## 6. 日常调度流程

```text
读取 project_registry.md
  ↓
识别高优先级项目
  ↓
检查每个项目 current_sprint.md
  ↓
生成今日任务队列
  ↓
逐个进入对应 Novel Workspace
  ↓
执行任务卡
  ↓
更新项目 daily_report.md
  ↓
汇总 global_daily_report.md
```

## 7. 项目隔离原则

1. 每本小说必须拥有独立 Novel Workspace；
2. 每本小说有独立 project_constitution.md；
3. 每本小说有独立 feedback、reviews、memory；
4. 共享知识只能通过 project_knowledge_pack 进入项目；
5. 共享世界只能通过 world_pack 或 world_branch 引用；
6. 不允许一个项目的评论直接影响另一个项目。

## 8. project_registry.md 模板

```markdown
# Project Registry

## project_001_black_archive

项目名称：黑档案
类型：都市悬疑
世界实例：world_black_archive_v1
哲学命题：自由 vs 秩序
目标读者：悬疑、身份反转、旧案揭秘读者
状态：serializing
当前章节：18
风险等级：medium
主模型：DeepSeek
审稿模型：ChatGPT/Codex
今日任务：生成第 19 章 v0，处理昨日反馈

## project_002_spirit_market

项目名称：灵市
类型：玄幻经营
世界实例：world_spirit_market_v1
哲学命题：力量 vs 代价
目标读者：玄幻升级、经营流读者
状态：incubating
当前章节：0
风险等级：low
今日任务：完善 Reader Attraction Gate
```

## 9. global_daily_report.md 模板

```markdown
# Global Daily Report

## 日期

## 今日运行项目

## 今日产出章节

## 今日审稿结果

## 今日反馈风险

## 今日项目异常

## 今日新增知识卡

## 今日暂停 / 重构项目

## 明日重点

## 需要主编决策的问题
```

## 10. 周复盘机制

每周检查：

1. 哪些项目追读风险升高；
2. 哪些项目同质化风险升高；
3. 哪些项目偏离项目宪法；
4. 哪些反馈可以升级为全局规律；
5. 哪些世界模板被验证有效；
6. 哪些项目应暂停或重构。

## 11. 验收标准

多项目调度系统可用标准：

1. 有 project_registry.md；
2. 有 project_matrix.md；
3. 能区分项目状态；
4. 能识别每日优先级；
5. 能保持项目文件隔离；
6. 能生成 global_daily_report.md；
7. 能识别同质化风险；
8. 能把稳定反馈回流全局资产。
