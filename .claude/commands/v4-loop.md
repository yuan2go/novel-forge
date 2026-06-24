# V4 Goal Loop

你现在执行 novel-forge 小说工厂 V4 目标循环开发模式。

请严格按以下流程执行：

1. 读取 `CLAUDE.md`、`README.md`、`docs/` 下全部文档；
2. 检查 `docs/progress/v4-goal-pool.md` 是否存在；
3. 如果不存在，先创建目标池；
4. 如果已经存在，从目标池选择最高优先级未完成目标；
5. 每轮只处理一个目标；
6. 每轮必须先说明目标、涉及文件、验收标准；
7. 开发完成后必须运行测试；
8. 测试结果必须写入 `docs/progress/v4-test-log.md`；
9. 目标状态必须更新到 `docs/progress/v4-goal-pool.md`；
10. 本轮总结必须追加到 `docs/progress/v4-loop-report.md`；
11. 遇到阻塞必须写入 `docs/progress/v4-open-issues.md`；
12. 禁止跳过测试；
13. 禁止把未验证功能标记为完成；
14. 禁止一次性修改多个无关模块。

当前任务：继续推进 V4，下一个目标由你基于目标池选择。选择后先说明计划，等待确认后再修改代码。

