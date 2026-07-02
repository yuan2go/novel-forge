# Novel Operating System 长篇稳定性优化方案

> 建议文件路径：`docs/novel-os-optimization-plan.md`  
> 适用对象：Codex / Claude Code / 后端工程 / 产品设计 / 审稿系统  
> 文档目标：基于当前测试小说暴露的问题，明确 Novel Operating System 下一阶段需要补齐的核心能力，并将文学问题转译为可实现的系统模块、数据结构、质量闸门和验收标准。

---

## 0. 背景与总判断

当前测试小说已经证明：系统具备较强的**单章正文生成能力**，能够稳定产出氛围感强、文笔成熟、具有中式案牍悬疑气质的章节。但长篇连续生产出现严重失控：人物名称漂移、机构名称漂移、主线外溢、章节模板重复、伏笔只开不收、反派长期缺席、正文元信息泄漏。

因此，下一阶段优化重点不应继续堆叠正文生成 Prompt，而应补齐 Novel Operating System 的**长篇控制层**。

当前系统的核心问题可以概括为：

```text
Writer 已经够强。
Controller 不够强。
State 不够稳。
Reviewer 不够硬。
Gate 几乎没有。
```

优化目标不是“让 AI 更会写一章”，而是让系统能够稳定生产一部长篇：

```text
正典稳定
→ 状态连续
→ 卷级推进
→ 伏笔可追踪
→ 章节不重复
→ 反派有行动
→ 人物有代价
→ 审稿能拦截
→ 坏章能返修
→ 发布前有门禁
```

---

# 第一部分：病灶清单

## 1. 严重等级定义

| 等级 | 含义 | 处理原则 |
|---|---|---|
| P0 | 致命问题 | 不修复则不应继续生成或发布；必须优先进入下一轮开发。 |
| P1 | 高危问题 | 会显著破坏长篇质量、追读率和结构完整性；应在 P0 后立即处理。 |
| P2 | 中危问题 | 影响商业化表现、读者体验和精品化程度；可在系统稳定后优化。 |

---

## 2. 总体病灶表

| 编号 | 病灶类型 | 具体表现 | 系统根因 | 严重等级 | 对小说的影响 | 必须补齐的系统能力 |
|---:|---|---|---|---|---|---|
| 1 | 角色姓名漂移 | 主角从顾砚秋、沈砚、江砚漂移到阿照；师父、搭档、反派代理人也频繁换名 | 缺少全局正典库 | P0 | 读者无法建立人物认同，长篇连续性崩坏 | Canon Database / 正典库 |
| 2 | 机构名称漂移 | 夜档司、巡遗司、北档房、夜档库、遗簿库等反复切换 | 缺少机构正典表和禁用别名检查 | P0 | 官署体系失真，世界观版图混乱 | Organization Canon / 机构正典 |
| 3 | 主角槽位漂移 | 江砚曾是主视角，后期阿照接管，但没有明确主角交接 | 缺少 POV 控制与主角状态锁定 | P0 | 人物弧线断裂，读者不知道谁是核心主角 | POV Controller / 主视角控制器 |
| 4 | 正文元信息泄漏 | 正文中出现 JSON 包装、notes、copyright_boundary、metadata 等 | 缺少正文清洗和发布门禁 | P0 | 直接暴露 AI 生产痕迹，稿件不可发布 | Output Sanitizer / 正文清洗器 |
| 5 | 章节模板死循环 | 大量章节遵循“异物出现→验痕→官署施压→主角反压→旧债钩子” | 缺少章节结构去重器 | P0 | AI感强，追读疲劳，商业化风险高 | Pattern Similarity Checker / 结构去重器 |
| 6 | 卷级目标缺失 | 每章有钩子，但每卷没有明确阶段问题和阶段答案 | 缺少卷级规划器 | P0 | 故事只扩张不收束，70W 字后疲态明显 | Arc Planner / 卷级规划器 |
| 7 | 线索无限扩张 | 桥纸、竹灰、税筹、灯契、泥契、税井、纸秤、灰井、竹课连续新增 | 缺少线索预算与伏笔图 | P0 | 世界观看似丰富，实则失控，读者抓不住主线 | Clue Budget + Foreshadowing Graph |
| 8 | 师父债被滥用 | 每个案子都能用“师父债”强行牵引主角入局 | 缺少人物状态账本与债务状态表 | P0 | 核心悬念变成万能借口，缺乏进度和爆雷机制 | Character State Manager + Debt Ledger |
| 9 | 反派长期缺席 | 多数章节只有“有人”或临时小吏，没有稳定反派代理人 | 缺少反派行动模型 | P0 | 没有宿敌，没有追捕目标，没有阶段性胜负 | Villain Operation Model |
| 10 | 章节入库无门禁 | 坏章、漂移章、重复章、元信息污染章可能直接进入正文库 | 缺少 Publishing Gate | P0 | 系统不能工业化生产，后期人工清理成本极高 | Publishing Gate / 发布门禁 |
| 11 | 因果链不稳 | 已查明事实后续可能变成未查明；人物动机前后跳跃 | 缺少事实账本和因果校验 | P1 | 悬疑逻辑不可靠，推理可信度下降 | Fact Ledger + Causal Link Checker |
| 12 | 官署压力同质化 | 每章都有某司、某房、某书办来封存、移交、问责、追税 | 缺少压力类型预算 | P1 | 官场压迫从爽点变成噪音 | Pressure Budget / 压力预算 |
| 13 | 验物手段同质化 | 石灰、明矾、胆矾、鱼胶、米浆、盐卤、贝灰反复出现 | 缺少调查手段预算 | P1 | 物证勘验从特色变成套路 | Investigation Method Budget |
| 14 | 母题严重过载 | 纸、灰、盐、井、灯、税、印、签持续高频重复 | 缺少母题预算管理 | P1 | 风格统一退化为词库复读 | Motif Budget Manager |
| 15 | 单章强、长线弱 | 每章有氛围和钩子，但十章、二十章连读没有大高潮 | 缺少阶段收束闸门 | P1 | 读者觉得“好看但累”，追读下滑 | Arc Payoff Gate / 卷级回收闸门 |
| 16 | 人物功能单一 | 搭档多为害怕、提问、吐槽、捧哏；换名不换功能 | 缺少角色功能矩阵 | P1 | 群像不成立，配角记忆点弱 | Character Function Matrix |
| 17 | 主角主动目标弱 | 主角总是被旧案找上门，被动救火 | 缺少主角主动任务规划 | P1 | 情绪驱动力不足，中长期期待弱 | Protagonist Goal Planner |
| 18 | 反派压迫不足 | 官吏常被主角几句话、几条规矩压制 | 缺少反派胜利机制 | P1 | 爽点阈值衰减，敌人不够强 | Villain Win Ledger |
| 19 | 超自然规则摇摆 | 旧物成精感强，但很快被材料学、机关术解释消解 | 缺少超自然比例控制 | P1 | 志怪悬疑感被过度祛魅 | Supernatural Rule Controller |
| 20 | 地图扩张无层级 | 南篾市、白水沟、铜井坊、灰井街、北瓦仓等不断出现，但缺少城市地图层级 | 缺少地点图谱 | P1 | 城市世界观碎片化 | Location Graph |
| 21 | 支线伪装成主线 | 每个新旧规都像主线，但没有汇入核心阴谋 | 缺少主线关联校验 | P1 | 读者分不清哪些线索重要 | Mainline Relevance Checker |
| 22 | 章节钩子通胀 | 每章结尾都抛出下一件旧物或旧债 | 缺少钩子预算 | P1 | 悬念阈值升高，钩子失效 | Hook Budget Manager |
| 23 | 民生压力重复 | 百姓围堵、商户停业、货路被卡、误工赔偿反复出现 | 缺少情绪曲线管理 | P2 | 压迫感变平，缺少情绪变化 | Emotion Curve Planner |
| 24 | 风格动态不足 | 调查章、高潮章、过渡章、反派章笔法趋同 | 缺少动态风格控制器 | P2 | 文笔好但章法单一 | Style Controller |
| 25 | 平台适配缺失 | 当前题材适合知乎盐言、豆瓣、番茄悬疑，但不适合起点/飞卢 | 缺少平台适配器 | P2 | 商业定位模糊 | Platform Adapter |
| 26 | 爽点升级不足 | 前期“规矩反杀官差”有效，后期重复疲软 | 缺少爽点升级表 | P2 | 读者获得感递减 | Payoff / Reward Ledger |
| 27 | 破案奖励不足 | 主角破案后常只背更多债，缺少权力、资源、名望收益 | 缺少奖励账本 | P2 | 长期压抑，缺乏正反馈 | Reward Ledger |
| 28 | 审稿结果不可执行 | 审稿能指出问题，但不能自动拦截坏章 | 缺少结构化审稿结果 | P0 | 同类问题会反复出现 | Review Result Schema |
| 29 | 修订闭环缺失 | 坏章发现后没有自动生成重写任务 | 缺少修订任务生成器 | P1 | 人工修复成本高，问题难闭环 | Revision Task Generator |
| 30 | 系统目标偏生成而非控制 | 系统重视写出一章，不重视维护整部长篇 | 架构目标错误 | P0 | 越写越散，无法工业化 | Operating System 化重构 |

---

## 3. 测试小说暴露出的典型失败模式

### 3.1 正典失败

现象：同一人物功能被不同名字继承，同一机构被多个名称替换。

系统判断：

```text
这不是“人物多”，而是正典未锁定。
这不是“机构丰富”，而是机构命名无治理。
```

必须禁止未经注册的核心实体进入正文。

---

### 3.2 模板失败

重复章法：

```text
异物异动
→ 主角验物
→ 官署施压
→ 搭档吐槽
→ 主角用规矩反制
→ 百姓暂时获救
→ 更深旧债出现
```

系统判断：

```text
每章都有冲突，不等于长篇有推进。
每章都有钩子，不等于主线有收束。
```

---

### 3.3 主线失败

测试小说从“师父旧债”扩展到“旧城隐税”，但系统没有及时把主线升级为明确卷级问题。

应锁定为：

```text
谁在复活旧城隐税机制？
谁在把旧规、民生设施、官署税课变成收债工具？
师父当年到底压下了什么？
阿照到底是在还债，还是在被迫成为新的代偿者？
```

而不是继续无限新增桥、井、灯、纸、灰、税。

---

### 3.4 状态失败

师父债明明已经成为核心计量单位，却没有状态表。

错误表现：

```text
每章都说阿照又担责。
但读者不知道已经担了多少。
也不知道担到什么程度会爆雷。
```

正确处理：

```text
每一次签责、代押、动用债牌，都必须写入 Character State Ledger。
超过阈值必须触发剧情事件。
```

---

### 3.5 反派失败

当前很多章节背后都有“有人”，但没有固定对手。

错误表现：

```text
有人换桥纸。
有人糊竹铃。
有人倒签税筹。
有人藏灯契。
有人动泥契。
有人唤醒纸秤。
```

这不能撑起长篇。系统必须要求每卷至少有一个可识别的反派代理人。

---

# 第二部分：系统优化路径

## 1. 总体目标

将 Novel Operating System 从“章节生成器”升级为“长篇生产操作系统”。

### 1.1 当前形态

```text
输入大纲 / 章节要求
↓
生成正文
↓
人工审稿
```

### 1.2 目标形态

```text
正典库
↓
项目状态包
↓
卷级规划器
↓
章节任务生成器
↓
正文生成器
↓
正文清洗器
↓
事实抽取器
↓
一致性校验器
↓
结构去重器
↓
伏笔图更新器
↓
母题预算器
↓
审稿器
↓
修订任务生成器
↓
发布门禁
```

---

## 2. P0 模块设计

## 2.1 Canon Database：全局正典库

### 2.1.1 目标

解决人物、机构、地点、主线术语、关键物证的漂移问题。

### 2.1.2 管理对象

| 对象 | 必须字段 |
|---|---|
| 人物 | id、标准名、允许别名、禁用名、身份、阵营、当前状态、首次出现章节 |
| 机构 | id、标准名、层级、职责、允许别名、禁用名、上级机构、下级机构 |
| 地点 | id、标准名、所属区域、关联机构、关联案件、旧规类型 |
| 物证 | id、标准名、类型、首次出现章节、当前持有人、关联伏笔 |
| 主线术语 | id、标准名、定义、禁用替代表述、关联卷 |

### 2.1.3 示例 Schema

```json
{
  "character_id": "azhao",
  "name": "阿照",
  "role": "protagonist",
  "status": "active",
  "allowed_aliases": [],
  "forbidden_aliases": ["江砚", "沈砚", "顾砚秋"],
  "affiliation": "夜档司",
  "first_chapter": 1,
  "current_arc": "桥南隐税卷"
}
```

```json
{
  "organization_id": "night_archive_office",
  "name": "夜档司",
  "type": "core_organization",
  "allowed_aliases": [],
  "forbidden_aliases": ["巡遗司", "北档房", "夜档库", "遗簿库"],
  "responsibility": "处理旧档、旧规、夜间复醒机制相关案件"
}
```

### 2.1.4 校验规则

| 规则 | 失败处理 |
|---|---|
| 正文出现 forbidden_aliases | 章节 fail，生成修订任务 |
| 出现未注册核心人物 | warning，要求确认是否新增正典 |
| 出现未注册核心机构 | warning 或 fail，取决于章节功能 |
| 人物身份与正典冲突 | fail |
| 机构上下级关系冲突 | fail |

### 2.1.5 验收标准

```text
同一小说连续生成 50 章，不出现主角名漂移。
同一小说连续生成 50 章，不出现核心机构名漂移。
新增人物、地点、机构必须显式注册或进入待确认队列。
```

---

## 2.2 Output Sanitizer：正文清洗器

### 2.2.1 目标

防止 JSON、YAML、Prompt、notes、metadata 等非正文内容进入章节正文。

### 2.2.2 检测项

```text
{"text":
"notes":
"metadata":
copyright_boundary
本章目标
写作策略
生成说明
prompt
system
assistant
YAML front matter
markdown code fence around full chapter
```

### 2.2.3 处理策略

| 类型 | 处理 |
|---|---|
| JSON wrapper，且正文在 text 字段 | 自动提取 text，但记录 warning |
| notes / metadata 混入正文 | fail |
| prompt / system 指令混入正文 | fail |
| 章节标题缺失 | fail |
| 章节编号异常 | fail |
| 正文字数异常偏短 | fail |

### 2.2.4 输出 Schema

```json
{
  "chapter_id": "chapter_097",
  "sanitizer_status": "fail",
  "issues": [
    {
      "type": "json_wrapper_detected",
      "severity": "P0",
      "message": "正文被 JSON text 字段包裹"
    }
  ],
  "action": "extract_text_and_create_revision_task"
}
```

### 2.2.5 验收标准

```text
任何章节正文中不得出现 JSON/YAML/notes/metadata/prompt 残留。
检测失败的章节不得进入 canon chapter store。
```

---

## 2.3 Chapter State Package：动态章节状态包

### 2.3.1 目标

每章生成后抽取结构化状态，下一章生成前强制注入，避免模型依赖上下文记忆。

### 2.3.2 状态包字段

```json
{
  "chapter_no": 110,
  "active_arc": "桥南隐税卷",
  "active_characters": ["阿照", "崔掌案"],
  "active_locations": ["油篾巷"],
  "active_organizations": ["夜档司", "城课司"],
  "confirmed_facts": [
    "竹筹被藏入各家招牌",
    "东七坊竹器铺课残簿出现"
  ],
  "open_clues": [
    "缺齿印",
    "竹筹穿册",
    "右手缺拇指的人"
  ],
  "character_state_changes": [
    "阿照继续被卷入旧城隐税案"
  ],
  "new_liabilities": [],
  "forbidden_next": [
    "不得新增新税种",
    "不得继续以验灰作为主破解手段",
    "不得新增无关司署"
  ]
}
```

### 2.3.3 使用方式

```text
生成第 N 章后：
1. 抽取状态包。
2. 写入 chapter_state。
3. 更新 canon / fact / clue / motif / debt ledger。
4. 生成第 N+1 章前，必须读取最近状态包 + 卷级状态包。
```

### 2.3.4 验收标准

```text
每章必须有 chapter_state。
缺少 chapter_state，不允许生成下一章。
状态包必须包含 confirmed_facts、open_clues、forbidden_next。
```

---

## 2.4 Pattern Similarity Checker：章节结构去重器

### 2.4.1 目标

识别并阻止重复副本。

### 2.4.2 结构指纹字段

```json
{
  "chapter_no": 110,
  "anomaly_type": "铺牌倒字",
  "investigation_method": "验竹粉 / 验铁胆墨",
  "pressure_type": "城课司封铺",
  "counterattack_type": "主角以规矩反压",
  "assistant_function": "吐槽 / 提问",
  "emotional_payoff": "百姓暂时获救",
  "ending_hook": "缺拇指人"
}
```

### 2.4.3 检测规则

| 检测项 | 阈值 | 动作 |
|---|---|---|
| 连续3章核心结构相似 | similarity > 0.7 | fail |
| 连续3章使用同类验物手段 | 3次 | fail |
| 连续5章出现官署封存/移交 | 5次 | fail |
| 每10章主角签责超过2次 | >2 | fail |
| 每10章新增旧规超过3个 | >3 | fail |

### 2.4.4 验收标准

```text
系统能对最近3章计算结构相似度。
结构相似度超阈值时自动生成 revision_task。
失败章节不得入库。
```

---

## 2.5 Publishing Gate：发布门禁

### 2.5.1 目标

所有章节入库、导出、发布前必须通过统一门禁。

### 2.5.2 检查项

```text
1. Canon consistency check
2. Output sanitizer check
3. Chapter state completeness check
4. Fact consistency check
5. Pattern similarity check
6. Arc progress check
7. Foreshadowing graph update check
8. Motif budget check
9. Review score threshold check
```

### 2.5.3 输出 Schema

```json
{
  "chapter_id": "chapter_110",
  "gate_status": "fail",
  "failed_checks": [
    {
      "check": "motif_budget",
      "severity": "P1",
      "message": "最近10章 tax_motif 超预算"
    },
    {
      "check": "pattern_similarity",
      "severity": "P0",
      "message": "连续3章结构高度相似"
    }
  ],
  "allowed_to_publish": false,
  "action": "generate_revision_task"
}
```

### 2.5.4 验收标准

```text
所有章节必须经过 publishing_gate。
gate_status != pass 的章节不得进入最终正文目录。
```

---

# 3. P1 模块设计

## 3.1 Arc Planner：卷级规划器

### 3.1.1 目标

解决“有章节推进，无卷级推进”的问题。

### 3.1.2 Arc Schema

```json
{
  "arc_id": "arc_03",
  "title": "桥南隐税卷",
  "chapter_range": "81-110",
  "arc_question": "谁在复活旧城隐税机制？",
  "protagonist_goal": "阿照要找到隐税机制源头，而不是继续救火",
  "villain_goal": "逼夜档司和阿照承接旧债",
  "required_payoffs": [
    "桥纸税与灯契税同源",
    "师父当年压下第一批隐税案",
    "反派代理人第一次露出身份"
  ],
  "forbidden_expansion": [
    "不得无限新增税种",
    "不得新增无关司署",
    "不得每章都以官署封存推进"
  ]
}
```

### 3.1.3 章节功能类型

| 类型 | 作用 |
|---|---|
| 开案章 | 引出核心异常，不允许同时新增过多机构 |
| 调查章 | 推进线索，不允许只重复验灰验水 |
| 误导章 | 给出假解释或假嫌疑人 |
| 反派行动章 | 展示对手主动布局 |
| 主角失败章 | 让主角付出实质代价 |
| 关系推进章 | 推动主角与师父、搭档、上官、百姓关系 |
| 阶段收束章 | 回收伏笔，回答阶段问题 |
| 高潮章 | 公开对决，必须有不可逆后果 |

### 3.1.4 验收标准

```text
每卷必须有 arc_question。
每章必须有 chapter_function。
连续3章不得为同一 chapter_function。
每10章必须至少包含1个阶段收束章。
```

---

## 3.2 Foreshadowing Graph：伏笔图

### 3.2.1 目标

让每个伏笔都能追踪来源、指向、状态和回收计划。

### 3.2.2 Schema

```json
{
  "clue_id": "missing_tooth_seal",
  "name": "缺齿印",
  "first_seen_chapter": 94,
  "linked_truths": ["旧城隐税机制", "反派代理人身份"],
  "planned_payoff_chapter": 110,
  "status": "active",
  "last_updated_chapter": 105
}
```

### 3.2.3 状态类型

| 状态 | 含义 |
|---|---|
| seeded | 已埋下，但尚未推进 |
| active | 正在被多章推进 |
| paid_off | 已回收 |
| deprecated | 被废弃或重构 |
| overdue | 超过计划章节未回收 |

### 3.2.4 校验规则

```text
新伏笔必须绑定 target_truth。
超过20章未推进，warning。
超过30章未回收，fail。
每10章必须 paid_off 至少2个伏笔。
```

---

## 3.3 Motif Budget Manager：母题预算器

### 3.3.1 目标

防止纸、灰、盐、井、灯、税、印、签等母题过载。

### 3.3.2 预算示例

```json
{
  "arc_id": "arc_03",
  "budget_window": 10,
  "limits": {
    "paper_core_clue": 2,
    "grey_core_clue": 2,
    "tax_core_conflict": 2,
    "well_case": 1,
    "lamp_case": 1,
    "mentor_debt_trigger": 3,
    "bureau_pressure_scene": 3
  }
}
```

### 3.3.3 超预算处理

| 情况 | 动作 |
|---|---|
| 轻微超预算 | warning，提示下一章禁用该母题 |
| 严重超预算 | fail，要求重写章节功能 |
| 连续两轮超预算 | 触发 Arc Planner 重构建议 |

---

## 3.4 Character State Manager：人物状态管理器

### 3.4.1 目标

统一管理人物身份、关系、资源、风险、伤势、债务、声望等状态。

### 3.4.2 通用结构

```json
{
  "character_id": "azhao",
  "name": "阿照",
  "role": "protagonist",
  "authority": "夜档司巡遗人",
  "physical_state": "normal",
  "emotional_state": "high_pressure",
  "reputation": {
    "commoners": "mixed",
    "bureaucracy": "hostile"
  },
  "resources": ["债牌", "铜尺"],
  "active_risks": ["停职", "代偿", "师父旧罪公开"]
}
```

### 3.4.3 题材专用子账本

| 子账本 | 适用题材 |
|---|---|
| Debt Ledger | 当前测试小说、官场、复仇、家族债务文 |
| Cultivation Ledger | 玄幻升级 |
| Relationship Ledger | 恋爱、群像 |
| Reputation Ledger | 官场、娱乐圈、商战 |
| Resource Ledger | 末世、创业、战争 |
| Suspicion Ledger | 悬疑、推理 |

当前测试小说必须启用：

```text
Debt Ledger
Case Liability Ledger
Reputation Risk Ledger
```

---

## 3.5 Debt Ledger：债务状态表

### 3.5.1 目标

让“师父债”从情绪设定变成可计算的主线进度。

### 3.5.2 Schema

```json
{
  "character_id": "azhao",
  "inherited_debt": {
    "source": "师父温砚",
    "total": 100,
    "cleared": 79,
    "remaining": 21
  },
  "new_liabilities": [
    {
      "chapter": 94,
      "event": "使用债牌调阅契料所",
      "risk": "桥纸案正式记入夜档司责任",
      "severity": "medium"
    },
    {
      "chapter": 96,
      "event": "封桥承责",
      "risk": "若误封，承担桥南误工与修补责任",
      "severity": "high"
    }
  ],
  "risk_level": "high"
}
```

### 3.5.3 触发规则

| 条件 | 剧情触发 |
|---|---|
| new_liabilities >= 3 | 上级要求阿照交出债牌 |
| new_liabilities >= 5 | 夜档司暂停阿照独立巡遗资格 |
| remaining <= 10 | 师父旧案真相反噬 |
| reputation.commoners = low | 百姓误认夜档司为祸源 |
| bureaucracy_hostility = high | 官署联合审查夜档司 |

---

## 3.6 Villain Operation Model：反派行动模型

### 3.6.1 目标

让反派从“模糊的有人”变成有目标、有行动、有收益、有标记的阶段性敌人。

### 3.6.2 Schema

```json
{
  "arc_id": "arc_03",
  "visible_agent": {
    "name": "陶承砚",
    "identity": "井税司并查书办",
    "public_face": "负责并查桥纸税、井税、灯契税"
  },
  "hidden_goal": [
    "复活旧城隐税机制",
    "逼夜档司承接旧债",
    "把师父旧案变成公开罪证"
  ],
  "signatures": ["缺齿印", "三行白泡", "倒签税筹", "红印米粒", "竹筹穿册"],
  "current_wins": [
    "阿照已签下封桥承责",
    "民众开始怀疑夜档司",
    "城课司获得封铺理由"
  ]
}
```

### 3.6.3 每章反派动作记录

```json
{
  "chapter": 110,
  "villain_action": "将旧竹筹藏入铺牌",
  "target": "油篾巷商户",
  "method": "利用竹器铺课残簿激活旧课机制",
  "expected_gain": "城课司获得封铺名义",
  "protagonist_loss": "阿照被迫介入竹课旧案"
}
```

---

# 4. P2 模块设计

## 4.1 Style Controller：动态风格控制器

| 章型 | 风格要求 |
|---|---|
| 开案章 | 氛围强、信息少、悬念重 |
| 调查章 | 动作清晰、解释克制、线索递进 |
| 官场对峙章 | 对话锋利、权责清楚、节奏紧 |
| 反派章 | 冷静、压迫、少解释、多布局 |
| 高潮章 | 短句、快节奏、强代价 |
| 余波章 | 情绪沉淀、关系变化、奖励结算 |

---

## 4.2 Reader Fatigue Detector：读者疲劳检测器

### 检测指标

```json
{
  "repeated_terms": ["灰", "纸", "税", "井", "灯"],
  "repeated_scenes": ["百姓围堵", "官署封存", "主角签责"],
  "repeated_dialogue": ["你夜档越权", "按例移交", "谁担责"],
  "repeated_payoff": ["逼对方签字", "暂时封存", "新旧债出现"]
}
```

### 输出示例

```json
{
  "fatigue_score": 82,
  "risk": "high",
  "recommendation": [
    "下一章切换为反派视角",
    "禁止新增官署",
    "禁止验灰/验水",
    "必须回收一个旧伏笔"
  ]
}
```

---

## 4.3 Platform Adapter：平台适配器

| 平台 | 适配方向 |
|---|---|
| 知乎盐言 | 短卷、强反转、悬疑闭环、情绪价值高 |
| 豆瓣阅读 | 文笔、制度隐喻、人物关系、文学质感 |
| 番茄悬疑 | 更快节奏、更直观爽点、更频繁阶段回报 |
| 起点 | 需要明确升级体系、势力升级、主角成长线 |
| 飞卢 | 当前题材不适配，除非大幅增加高频强爽点 |

---

# 5. 建议开发路线

## 阶段一：止血版本 V1

目标：不再生成明显坏章。

开发模块：

```text
Canon Database
Output Sanitizer
Chapter State Package
Pattern Similarity Checker
Publishing Gate
Fact Ledger
```

验收标准：

```text
1. 不再出现主角名漂移。
2. 不再出现机构名漂移。
3. 不再出现 JSON / notes / metadata 入正文。
4. 连续3章不得使用同一核心章法。
5. 每章生成后必须生成状态包。
6. 状态包缺失时禁止生成下一章。
```

---

## 阶段二：控线版本 V2

目标：让长篇具备卷级推进。

开发模块：

```text
Arc Planner
Foreshadowing Graph
Motif Budget Manager
Clue Budget
Character State Manager
Debt Ledger
Arc Payoff Gate
```

验收标准：

```text
1. 每卷必须有 arc_question。
2. 每10章至少回收2个伏笔。
3. 每10章至少回答1个阶段问题。
4. 新线索不得无限增长。
5. 师父债必须有明确数值状态。
6. 每次签责、代押、动用债牌都写入 Debt Ledger。
```

---

## 阶段三：精品化版本 V3

目标：提升追读、商业化和平台适配能力。

开发模块：

```text
Villain Operation Model
Reader Fatigue Detector
Style Controller
Reward Ledger
Platform Adapter
Revision Task Generator
```

验收标准：

```text
1. 每卷有稳定反派代理人。
2. 每5章至少有一次反派主动行动。
3. 每卷至少一次主角失败或重大代价。
4. 每卷至少一次明确奖励或权力变化。
5. 不同章型有不同风格。
6. 审稿失败项必须自动生成 revision_task。
```

---

# 6. 推荐数据表设计

| 表名 | 作用 |
|---|---|
| `novel_project` | 小说项目基础信息 |
| `canon_character` | 人物正典 |
| `canon_organization` | 机构正典 |
| `canon_location` | 地点正典 |
| `canon_item` | 物证与关键道具正典 |
| `chapter` | 章节正文与版本 |
| `chapter_state` | 每章状态包 |
| `chapter_pattern` | 章节结构指纹 |
| `fact_ledger` | 已确认事实 |
| `clue` | 线索表 |
| `foreshadowing_edge` | 伏笔图关系 |
| `motif_usage` | 母题使用记录 |
| `arc_plan` | 卷级规划 |
| `character_state` | 人物状态 |
| `debt_ledger` | 债务状态 |
| `villain_operation` | 反派行动表 |
| `review_result` | 审稿结果 |
| `revision_task` | 修订任务 |
| `publishing_gate_log` | 发布门禁日志 |

---

# 7. Codex 执行任务清单

## 7.1 第一批任务：P0 止血

```text
1. 新增 Canon Database 数据模型和校验服务。
2. 新增 Output Sanitizer，拦截 JSON/YAML/metadata/prompt 泄漏。
3. 新增 Chapter State Package 抽取器。
4. 新增 Pattern Similarity Checker。
5. 新增 Publishing Gate。
6. 新增 revision_task 生成逻辑。
7. 在章节入库流程前接入所有 P0 校验。
```

## 7.2 第二批任务：P1 控线

```text
1. 新增 Arc Planner。
2. 新增 Foreshadowing Graph。
3. 新增 Motif Budget Manager。
4. 新增 Character State Manager。
5. 新增 Debt Ledger。
6. 新增 Arc Payoff Gate。
7. 将卷级规划接入章节生成前的 Chapter Task Builder。
```

## 7.3 第三批任务：P2 精品化

```text
1. 新增 Villain Operation Model。
2. 新增 Reader Fatigue Detector。
3. 新增 Style Controller。
4. 新增 Reward Ledger。
5. 新增 Platform Adapter。
6. 将审稿结果结构化，自动生成修订任务。
```

---

# 8. 最终验收标准

系统优化完成后，必须满足以下标准：

```text
1. 连续生成 50 章，不出现主角、师父、核心机构名称漂移。
2. 任意章节不得出现 JSON / notes / prompt / metadata 残留。
3. 连续3章不得使用高度相似的章节结构。
4. 每章必须有结构化 chapter_state。
5. 每卷必须有明确 arc_question。
6. 每10章至少回收2个伏笔。
7. 每10章至少回答1个阶段性问题。
8. 每卷必须有稳定反派代理人。
9. 每5章至少记录一次反派主动行动。
10. 人物状态必须持续更新。
11. 当前测试小说必须启用 Debt Ledger。
12. 所有失败章节不得进入最终正文库。
13. 所有失败项必须生成 revision_task。
14. 发布前必须通过 Publishing Gate。
```

---

# 9. 最终结论

当前 Novel Operating System 欠缺的不是“更强的写作模型”，而是“长篇稳定性控制系统”。

下一步优化必须从正文生成转向系统治理：

```text
正典治理
状态治理
结构治理
伏笔治理
母题治理
反派治理
人物代价治理
审稿门禁治理
```

只有完成这些模块，Novel OS 才能从：

```text
能写一章小说
```

升级为：

```text
能稳定生产一部长篇精品小说
```
