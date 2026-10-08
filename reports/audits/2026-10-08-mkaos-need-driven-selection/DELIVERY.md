# WP-MKAOS-NEED-DRIVEN-SELECTION-01 交付核对

基线：`a3f8a6a71c2d0131cad9d948e0287848a8023847`（执行时获取的最新 main）。用户此前 SHA `75d99e6bad802929ab1a47cf1f9d5c0886249835` 至本基线未修正核心 catalog/scoring。
提交：`897968a777f4cdadfbe29a89d67a0e0a8bf029a9`。
草稿 PR：https://github.com/yuan2go/novel-forge/pull/145 （未合并）。

## 根因与实现

原 43 张卡统一携带 wuxia/xuanhuan/chinese_serial 与 limited/first_person，scene_type 按 family 分配；评分把需求、亲和、卡片其他内容放在混合词项池。题材/POV 可单独给通用方法加分，亲和又进入 signature、selection_tags 和最终上下文。

新策略 `craft-need-driven-selection.v2` 将 writing_problem、scene_goal、scene_demand、chapter_function、reader_effect、emotion、conflict、information、relationship、style 按各自语义字段检索；genre/POV/scene_type 不能独立产生需求得分。词项检索是可解释的工程匹配，不是文学理解或质量证据。作者必选、依赖及既有保护仍走原可行性组合；无匹配可选卡不入选。非 Craft 行为保持。

亲和是另一步调整：有效需求 + APPLICABLE + 精确的资产证据，才可加分，总上限 2。无证据中立，适用性未知不产生亲和奖励，但不因此新增禁用。真实禁忌、边界、资源、作者约束、频率、冷却、反馈与组合约束不变。各候选给出需求维度、词项、调整状态、惩罚及最终必选/依赖/组合原因。

新语义签名仅取 abstract_mechanism；使用历史从原冻结 mechanism 增补读时语义投影，不删除旧签名或历史。无法安全比较的旧签名有明确状态。新策略 neutralize Craft genre/conflict selection_tags，并在新采用计划/Provider task/context projection 明确亲和及 family 是描述信息。旧冻结合同保持原投影。

## 策略与资产兼容

- 新 Need 与 Selection 冻结 v2；缺少版本的历史 Selection 按 v1 解释。历史修复重选继承 predecessor 策略及旧 context 维度，避免新增字段改变回放。
- 原 v1 Card 仍不可变，新策略可直接安全解释。旧候选/schema/source discovery 保持原形；旧完整 Selection/digest 有来自基线的 golden。
- catalog 43 张卡均发布版本 2，schema `narrative-craft-mechanism.v2` 增加明确的 affinity_evidence。全部原实际技法、前提、禁忌、依赖、保留和修复规则 semantic_hash 与 v1 一致；改动仅描述性亲和及其证据结构。
- 证据必须属于当前项目、CLEAR、允许的效果证据类别，并绑定精确 mechanism_id、dimension、value、applicability_conditions 与 mechanism_semantic_hash。结构测试或模型自评不能充当亲和实证。
- 初次安装无既往版本才允许当前 catalog genesis；已有项目必须依现有 version/supersedes 路径从 immediate active predecessor 升级，未执行旧 Admission 同样保护血缘。项目/机制事务锁阻止并发跳版本；审批、hash 与 provenance 校验保留。无数据库 schema migration。
- 当前 docs/current-system.md 与 runtime-operations.md 仅更新本范围过期说明；历史审计原文未改。

## 逐卡语义

所有卡都有通用保护：批准的场景目标/POV/事件边界；不创造未批准事件、人物知识或世界规则；保留 Canon、声音、空间时间因果和其他已成功效果。以下表列个别必要前提/禁忌原文，全部保留。scene/POV/genre 都是描述标签，所有 catalog 卡 affinity_evidence 为空，不默认加分。family 不决定可用范围。

| mechanism_id | 适用语义 | 描述性 scene / POV / genre | 保留的必要前提 | 保留的禁忌 |
|---|---|---|---|---|
| attention-relay | 通用机制，须满足本卡真实条件 | description, investigation / limited, first_person / — | POV人物能感知连续线索 | 需要刻意迷失方向或全知概览 |
| object-escalation | 通用机制，须满足本卡真实条件 | recurrence / — / — | 计划已有可再次遇到的物件 | 重复物件只用于维持场景定位 |
| action-causal-relay | 通用机制，须满足本卡真实条件 | action, chase / — / — | 计划包含至少两个相互影响的动作 | 蒙太奇只需概括过程 |
| spatial-anchor | 通用机制，须满足本卡真实条件 | movement, combat / — / — | 场景有位置变化且空间事实已知 | 梦境故意不遵循稳定空间 |
| exchange-response-cost | 通用机制，须满足本卡真实条件 | combat / — / — | 双方目标和可用资源在计划中明确 | 单方瞬间结束且没有交换空间 |
| tactical-purpose-break | 通用机制，须满足本卡真实条件 | combat / — / — | 计划已给出胜负转折及其规则依据 | 转折依赖未授权的新能力 |
| indirect-mastery | 通用机制，须满足本卡真实条件 | comparison, power_display / — / — | 已授权实力关系且POV能观察后果 | 需要隐瞒真实强弱或反应者无判断依据 |
| subtext-pressure | 通用机制，须满足本卡真实条件 | dialogue, negotiation / — / — | 人物存在不宜直说但已知的诉求 | 急救指令或明确协作需要直白信息 |
| answer-adjacent | 通用机制，须满足本卡真实条件 | questioning / — / — | 人物有回避理由且问题有压力 | 读者尚不知道最基本的情境 |
| dialogue-power-transfer | 通用机制，须满足本卡真实条件 | negotiation / — / — | 双方有不同筹码和可选择的回应 | 纯信息告知或无选择余地的服从 |
| behavior-inference | 通用机制，须满足本卡真实条件 | character_action / — / — | 场景允许角色作出可观察选择 | 必须概括跨越很长时间的习惯 |
| choice-exposes-value | 通用机制，须满足本卡真实条件 | choice / — / — | 计划已有真实取舍且人物拥有行动权 | 没有任何可选项或强行制造道德考试 |
| social-refraction | 通用机制，须满足本卡真实条件 | social_interaction / — / — | 在场者身份、知识及关系已明确 | 只有单一POV且旁人反应不可感知 |
| emotional-residue | 通用机制，须满足本卡真实条件 | aftermath / — / — | 前一情绪事件与当前时间相近 | 已明确长时间消解或人物需要真实恢复 |
| restraint-release | 通用机制，须满足本卡真实条件 | emotion / — / — | 人物有压抑理由且计划允许释放 | 急迫行动不允许长时内心积累 |
| delayed-satisfaction | 通用机制，须满足本卡真实条件 | anticipation / — / — | 目标对读者已有价值且存在合理障碍 | 已经承诺本场兑现且再拖会违约 |
| information-asymmetry | 通用机制，须满足本卡真实条件 | suspense / — / — | 现有POV与叙述方式允许该信息分配 | 会泄露不应进入当前POV的事实 |
| answer-delay | 通用机制，须满足本卡真实条件 | investigation / — / — | 问题已明确且答案暂时不可合理取得 | 人物可以立即询问却被作者强行阻止 |
| plausible-misreading | 通用机制，须满足本卡真实条件 | investigation / — / — | 计划已有真实解释和可误读证据 | 错误解释必须依赖叙述者直接撒谎 |
| progressive-reveal | 通用机制，须满足本卡真实条件 | reveal / — / — | 信息可拆层且每层会影响当前选择 | 安全或因果理解要求一次完整说明 |
| result-before-cause | 通用机制，须满足本卡真实条件 | discovery / — / — | POV先遇到结果且计划已确定原因 | 会遮掉人物当时明明知道的重要原因 |
| setup-progress-payoff | 通用机制，须满足本卡真实条件 | payoff / — / — | 计划包含同一目标的铺垫与兑现 | 一次性偶遇不承担长期承诺 |
| seed-recovery | 通用机制，须满足本卡真实条件 | setup, payoff / — / — | 计划已指定可回收事实及其后续用途 | 尚未授权未来结果或必须保密的Canon事实 |
| earned-expectation-turn | 通用机制，须满足本卡真实条件 | surprise / — / — | 场景允许轻度意外且存在双重解释 | 严肃创伤表达会被笑点削弱 |
| meaningful-callback | 通用机制，须满足本卡真实条件 | recurrence / — / — | 旧标记可被当前人物合理记得 | 近期已连续重复或旧段落是创伤事件 |
| deadpan-contrast | 通用机制，须满足本卡真实条件 | humor / — / — | 人物确有认真对待的理由且场景容许轻松 | 威胁正在造成真实重大损失 |
| scene-value-turn | 通用机制，须满足本卡真实条件 | state_change / — / — | 批准计划已给出场景结果与价值轴 | 过渡片段只承担必要定位 |
| entry-escalation-exit | 通用机制，须满足本卡真实条件 | goal_obstacle / — / — | 场景有批准目标、障碍及交接点 | 静观片段的目标就是停留体验 |
| duration-allocation | 通用机制，须满足本卡真实条件 | narrative_duration / — / — | 场景允许略写无新增信息的过程 | 跳过过程会破坏因果或掩盖关键信息 |
| acceleration-pause | 通用机制，须满足本卡真实条件 | action_interval / — / — | 行动链存在可承受的短暂间隙 | 停顿会违反时间压力或物理因果 |
| functional-detail | 通用机制，须满足本卡真实条件 | description / — / — | 环境已有事实且人物正在追求目标 | 纯抒情段落的主要目的就是感官停留 |
| pov-filtered-description | 通用机制，须满足本卡真实条件 | description / limited, first_person / — | 当前POV身份和感知范围已确定 | 全知叙述正在明确承担不同功能 |
| boundary-test-retreat | 通用机制，须满足本卡真实条件 | relationship / — / — | 双方有行动自主性且计划允许关系变化 | 明确拒绝仍被写成需要继续追逐的邀请 |
| shared-risk-bond | 通用机制，须满足本卡真实条件 | shared_risk / — / — | 计划已有共同风险及双方可选行动 | 强迫保密或共同伤害被包装成亲密 |
| satisfaction-settlement | 通用机制，须满足本卡真实条件 | payoff / — / — | 计划已批准成果且前文建立了期待 | 胜利代价仍需严肃处理不宜狂欢 |
| cognitive-reframe | 通用机制，须满足本卡真实条件 | cognitive_change / — / — | 计划已有认知变化及其证据 | 变化要求人物获得不可接触的信息 |
| unfinished-action-hook | 通用机制，须满足本卡真实条件 | chapter_ending / — / — | 章节计划允许把结果交给下一章 | 本章已承诺完整兑现或中断造成虚假危机 |
| new-question-hook | 通用机制，须满足本卡真实条件 | chapter_ending / — / — | 当前问题确已解决且计划有后续问题 | 尚欠旧问题关键答案或新问题完全无关 |
| sentence-pulse | 通用机制，须满足本卡真实条件 | prose_rhythm / — / — | 片段有清楚的动作或情绪重音 | 角色声音或文体要求稳定节律 |
| intentional-gap | 通用机制，须满足本卡真实条件 | inference / — / — | 关键推断有充分可见依据 | 会省去因果、空间或知识边界必要环节 |
| paragraph-handoff | 通用机制，须满足本卡真实条件 | transition / — / — | 相邻段落处于可连接的时间与POV | 有意场景切换需要明确断开 |
| martial-intent-consequence | 武学专用，须已批准武学规则 | combat / — / wuxia, xuanhuan | 世界规则已定义武学作用与限制 | 新武学能力尚未获Canon批准 |
| power-cost-shadow | 通用机制，须满足本卡真实条件 | power_use, aftermath / — / — | Canon已有力量成本及当前资源事实 | 成本尚未定义或计划规定此次无需支付 |

`indirect-mastery` 的 WUXIA_XUANHUAN family 不限制题材：已授权能力差距与可观察后果是必要条件。`power-cost-shadow` 同样依据已批准力量/资源代价，可用于其他具有真实力量成本的场景。两个 POV 描述标签只在 attention-relay 与 pov-filtered-description 保留，真实感知/知识边界仍由条件约束。

## 前后对照（不可变旧 v1 intentional-gap）

| 输入 | v1 分数 | v2 分数 | v2 结果 |
|---|---:|---:|---|
| genre-only xuanhuan | 2 | 0 | CRAFT_NO_CONTEXT_MATCH |
| genre-only romance | 0 | 0 | CRAFT_NO_CONTEXT_MATCH |
| pov-only first_person | 2 | 0 | CRAFT_NO_CONTEXT_MATCH |
| pov-only omniscient | 0 | 0 | CRAFT_NO_CONTEXT_MATCH |
| same need xuanhuan/limited | 5 | 3 | 保留有效需求匹配 |
| same need romance/omniscient | 3 | 3 | 保留有效需求匹配 |

同一需求“省去说明”仅改变题材/POV，旧 5/3 → 新 3/3；题材/POV-only 由旧无依据分数 2 → 新 0。单元测试同时检查最终可行组合与必选/依赖/冲突，不只检查 raw score。

## 验证与证据边界

| 项目 | 状态 / 结果 | 边界 |
|---|---|---|
| 聚焦单元测试 | PASS：362 tests + 9 subtests | 43 卡 × 6 genre/POV、串维、证据上限、组合、旧 golden、历史、非 Craft、请求边界 |
| 定向 PostgreSQL | PASS：18 tests，10 deselected | 新项目 43 卡安装、v1→v2 升级、旧 Admission、不可变哈希、冻结候选、证据作用域与真实 Planning context 入口 |
| Planning 调用链 | EXECUTABLE | 真实 preparer ContextBundle/Need/selection/persistence 与 Provider task/context projection；两个跨题材/POV author brief。没有 Provider dispatch，也不是完整 Book 正文运行 |
| Ruff（改动文件）/compileall | PASS | 静态检查 |
| architecture fitness/module manifest/test reality/documentation reality | PASS | 当前 commit docs/source SHA 校验通过 |
| make validate | FAIL | 未改动 tests/unit/test_source_runtime_qualification.py 的 E402=1 与 test_creative_domain.py 的 lint debt 8；未扩大修复 |
| 较宽 Craft Planning 原夹具 | FAIL | 两类代表性失败在原基线复现：计划链 APPROVAL_PENDING→REJECTED；native Opening selectors 无效。不能推断全部 deselected 项通过 |
| accepted-history 较宽夹具 | FAIL | STYLE_PROJECTION_MIGRATION_REQUIRED，原基线复现一个代表性变体；保持原 Style/Book 保护 |
| 标准 P0 入口 | FAIL | backend manifest migration_matrix 缺 tests/integration/test_source_market_migration_postgres.py；原基线同样缺失 |
| P0 全部后续门 / 完整资格矩阵 | NOT_RUN | 入口 precondition 失败，没有生成成功资格报告 |
| 生产项目实地安装/升级 | NOT_RUN | 隔离 PostgreSQL 测试证明路径可执行，不等于生产部署 |
| 多题材实稿/编辑/读者效果/文学质量 | NOT_RUN | 无新增真实 Provider 调用；不能宣称质量提升 |

代码与调用链证据最高 EXECUTABLE；未升级为 QUALIFIED 或 PRODUCTION_PROVEN。

## 可复核命令

使用原工作区现有 Python runtime，不改 venv。临时 PostgreSQL 16.15，端口 55439，独立测试库；没有触及生产数据库。

```sh
PYTHONPATH=src /Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python -m pytest -q tests/unit/test_craft_need_driven_selection.py tests/unit/test_craft_selection.py tests/unit/test_craft_solver.py tests/unit/test_craft_usage.py tests/unit/test_narrative_craft_catalog.py tests/unit/test_mkaos_authority_domain.py tests/unit/test_craft_execution.py tests/unit/test_craft_closure.py tests/unit/test_craft_discovery.py tests/unit/test_knowledge_translation.py tests/unit/test_story_planning_runtime.py tests/unit/test_authority_production_preparation.py tests/unit/test_provider_task_views.py tests/unit/test_provider_context_policy_compilation.py --tb=short

PYTHONPATH=src NOVEL_FORGE_DATABASE_URL=postgresql://yuan@127.0.0.1:55439/novel_forge_mkaos_need_test /Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python -m pytest -q tests/integration/test_narrative_craft_authoring_postgres.py tests/integration/test_narrative_craft_catalog_replay_postgres.py tests/integration/test_craft_discovery_postgres.py tests/integration/test_mkaos_authority_postgres.py tests/integration/test_craft_planning_postgres.py -k 'not frozen_selection and not native_opening and not reselection' --tb=short

make validate PYTHON=/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python

P0_PROFILE=local P0_EVIDENCE_DIR=/tmp/novel-forge-mkaos-need-p0 make p0-backend-qualification PYTHON=/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python
```

日志在本目录：focused-unit.log、final-focused-pg.log、architecture.log、module-manifest.log、test-reality.log、documentation.log、validate.log、p0.log、baseline-planning.log、baseline-accepted-history.log、accepted-history-pg.log；before-after.json 记录上述受控分数对照。

首次同时运行两个使用清库 fixture 的集成组发生临时测试库死锁，已停止并顺序重跑；最终 PASS 和基线失败结果均来自顺序执行。此运行问题不属于生产数据库或修复行为证据。

临时 PostgreSQL 已停止；保留日志与测试数据以供复核。主工作区原有改动未动；交付 worktree clean。
