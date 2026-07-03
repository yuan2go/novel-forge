# Novel OS v6 Next Roadmap P1/P2

日期：2026-07-03

## P1 推荐顺序

1. Canon Graph 深化
   - 建立 Canon / Character / Arc / Foreshadowing / WorldRule 统一查询和冲突检测服务。
   - 将 Longform Recap 和 ReviewIssue 的证据都落到同一图谱。

2. Agent Center Operation Coverage
   - 将 outline、chapter plan、draft、review、revision、publish、feedback 关键操作注册为 AgentTask。
   - 增加 per-agent hard-stop、budget、rollback 和 retry policy UI。

3. Loop Kernel 主链迁移
   - 把 review -> issue -> revision -> re-review -> publish gate 迁移为标准 LoopRun。
   - 给每步补 checkpoint 和 recovery instruction。

4. Provider fallback policy
   - 保持 hard-stop fail-closed。
   - 增加显式 fallback approval、成本预测、retry boundary、fallback audit report。

5. UI 领域编辑器
   - Canon/Character/Arc/Foreshadowing 专用表单。
   - ReviewIssue 批量处理、RevisionTask 派发、阻断视图。
   - MKAOS Pack debugger 和知识使用轨迹。

## P2 推荐方向

1. 50/100 章 opt-in 长链压力测试。
2. 发布平台 adapter 强 schema 和平台回执 ingestion。
3. Feedback metric warehouse：retention/comment/drop-off/platform review schema。
4. SQL migration acceptance matrix 和 JSON/SQL 一致性校验。
5. 浏览器 Playwright strict smoke 纳入 CI label/manual gate。
6. 生产 SLA 和 failure drill 仪表盘。

## 不建议做的事

- 不要绕过 Context Builder 扩展 Agent prompt。
- 不要把 fallback 做成 provider hard-stop 后自动重试。
- 不要把 UI 先 SaaS 化或加登录/会员/邀请。
- 不要把 raw source text 作为“方便调试”放入 prompt preview、publish package 或 recap context。
