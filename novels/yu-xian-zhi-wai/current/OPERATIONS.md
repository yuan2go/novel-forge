# 作者指导型单书操作与恢复

从已验证的干净提交运行。私有连接、账户和授权证据放在仓库外；保留已有素材业务库和对象，名称含`test`也不能交给清库型pytest。以下路径可配置，不覆盖历史冻结和配置。

```bash
NF_ROOT="${NF_ROOT:-$PWD}"
export PYTHONPATH="$NF_ROOT/src:$NF_ROOT"
PYTHON="$NF_ROOT/.venv/bin/python"
INPUTS="$NF_ROOT/config/production/author-guided-twelve"
```

`NF`指向本交付仓库外`runtime/nf`包装器（路径由操作者配置）；它加载私有环境后执行原生CLI，并支持`--module`运行同环境下的原生脚本。包装器不会把连接变量导出到父shell，因此需要数据库的脚本也通过它运行。另设置`RUN_ROOT`、`EVIDENCE_ROOT`、`FROZEN`和实际验证过的`VERIFIED_SHA`，不将凭据写进文件。

## 查询、冻结、登记作者输入

```bash
"$NF" corpus jobs --project-id first-novel-pilot-20260912 --limit 10
"$NF" authority-creative-budget query --project-id first-novel-pilot-20260912
"$PYTHON" -m scripts.prepare_knowledge_closure prepare \
  --input-dir "$INPUTS" --target-book-id first-novel-pilot-a --output "$FROZEN"
"$PYTHON" -m scripts.prepare_knowledge_closure verify "$FROZEN"
```

`FROZEN`必须尚不存在。保存最终`freeze.json`字节SHA-256为外部`FREEZE_HASH`；变化产生新版本，不改旧freeze。当前明确使用`deny-all.json`，不以空白名单冒充知识处理。

```bash
"$NF" --module scripts.run_creation_synthesis \
  --brief "$FROZEN/brief.json" --policy "$FROZEN/creation.json" \
  --formation-policy "$FROZEN/formation.json" --knowledge-policy "$FROZEN/deny-all.json" \
  --production-budget "$FROZEN/experiment.json" --freeze-dir "$FROZEN" \
  --freeze-manifest-hash "$FREEZE_HASH" --project-id first-novel-pilot-20260912 \
  --book-id first-novel-pilot-a --workspace-id first-novel-pilot-workspace \
  --root "$RUN_ROOT" --run-key yu-xian-zhi-wai-author-twelve-v1 \
  --expected-sha "$VERIFIED_SHA" --evidence-dir "$EVIDENCE_ROOT/preview-v1"
```

上面仅预览。加入`--register-input-only`并使用新evidence目录，通过已有Content Command登记精确作者输入，无Provider、原生设计生成或审批。后续沿用同一run key复用brief。完整源文用于追溯，Provider只获得角色和范围允许的片段；04不能送给正文。

## 授权与Source小样

`experiment.json`只是待确认分配：Source20次/50万可观测Token，设计60/150万，1—6章150/375万，7—12章150/375万，共享修复恢复100/250万，总计最多480/1200万。不是授权、账户权益证明或费用预测；可只确认首个有限阶段。金额及不可观测开销保留`UNKNOWN`，不能切换付费API。

确认实际项目、账户、模型、用途和额度后，由有权限操作者登记授权。`authorization.business_scope`分别限制`source_allowed`、`design_allowed`、`max_chapter_number`；五阶段`authorized_cumulative_caps`只填累计已获准额度，未获准阶段不能填建议额度。查询旧策略，不能改名清账；未知请求保留预留。

```bash
"$NF" authority-creative-budget configure --project-id first-novel-pilot-20260912 \
  --workspace-id first-novel-pilot-workspace --policy-file "$CONFIRMED_POLICY_FILE" \
  --authorization-evidence-file "$CONFIRMED_EVIDENCE_FILE" --idempotency-key "$GRANT_KEY"
"$NF" corpus reading-preview --project-id first-novel-pilot-20260912 \
  --revision-id corpus-curated-revision:d7202836d9753903ba45e9f8ef3d4282696cdde7580f45c7c6cd92deee12bb10 \
  --reading-scopes "$NF_ROOT/novels/yu-xian-zhi-wai/corpus/canary-reading-scopes.json" \
  --intended-use ABSTRACT_GENERATION --target-book-id first-novel-pilot-a \
  --max-calls 20 --max-tokens 500000
```

Source授权生效后，才以同参数执行`corpus analyze --run-key first-novel-source-canary-v1 --limit 1 --authorization-ref "$CONFIRMED_REF"`，沿`corpus run --max-stages 1`、status/results逐步推进，复用原job、Effect、receipt及D0 extraction Operation。液压小样只能解释核实过的具体设备，不是排涝、调度或仓储普遍依据。本轮情节不依赖技术，无发现或待审时，原创依明确`DENY_ALL`策略继续，知识链保持未证明。

Candidate逐项提供源定位、机制、条件、例外、失效和拟用位置，正式批准绑定有权限审核者及确切版本。要消费获批Card，另走现有书级政策和合法未来规划变更，不能改已运行的freeze。模型建议不等于独立人工批准。

## 原生设计、正文和读稿检查点

相应授权生效后，上述runner加`--initialize --execute --authorization-ref "$CONFIRMED_REF"`并使用新evidence目录。路由保持已确认账户、模型与计量方式。`REVIEW_PLAN`在Formation候选审批处等待实际决定；查询原生候选后按允许的审批策略处理，不能伪称独立人工批准。恢复保留run key，传`--resume-formation-run-id "$FORMATION_RUN_ID"`。

官方驱动在真实三章组结束后暂停于3、6、9、12。先读精确接纳稿和关联前文，填写正文位置、严重程度、修复目标与保留要求，再登记及决定：

```bash
"$NF" --module scripts.creation_checkpoint_review preview \
  --project-id first-novel-pilot-20260912 --book-run-id "$BOOK_RUN_ID" --output "$READING_DIR"
"$NF" --module scripts.creation_checkpoint_review register \
  --project-id first-novel-pilot-20260912 --book-run-id "$BOOK_RUN_ID" \
  --review-file "$COMPLETED_REVIEW_FILE" --idempotency-key "$REVIEW_KEY"
"$NF" --module scripts.creation_checkpoint_review decide \
  --project-id first-novel-pilot-20260912 --book-run-id "$BOOK_RUN_ID" \
  --review-asset-version-id "$REVIEW_VERSION" --decision APPROVE \
  --reason "$REVIEW_REASON" --idempotency-key "$DECISION_KEY"
```

问题项使用`issue_id`、`chapter_number`、`status`、`severity`（如`major`）、`diagnosis`、`repair_target`、精确`location`、`preservation_requirements`和`acceptance_criteria`。标记`RESOLVED`还需`resolution_evidence`列表：每项绑定复核段落的`chapter_number`、`candidate_asset_version_id`、`text_hash`、`location`、`reason`与`preservation_check`。不能只填“已解决”。

未读模板不能批准。模型读稿标`AI_EDITORIAL_REVIEW`，人工独立评价另留证据。未解决问题继续携带；新稿针对具体问题复核，不能漏报关闭。拒绝用`REJECT`，已接纳正文问题走合法更正/未来重规划，不编辑导出稿冒充数据库同步。

第三章后，根据实际证据和已激活未来计划，经原生PlanChange提出、审阅、激活合法变化；无触发则说明并暂停。继续runner同时传`--plan-change-proposal-id "$PLAN_CHANGE_ID"`、`--resume-after-checkpoint 3`和`--checkpoint-review-decision-id "$DECISION_VERSION"`。第六、九章重复读稿并使用对应游标/新决定；六章不合格不能扩七章。不能用旧决定覆盖后来的人工暂停。

读稿检查点由官方creation driver执行，不是所有独立AUTO Book操作的全局审批门；操作沿此入口。阶段预算和章节权限在原生Provider准入强制。十二章结束后只登记终段读稿并保持停止，不放行十三章；180章Book未完成。

## 阅读版、追溯与恢复

runner导出`accepted-manuscript.md`、`accepted-manuscript.json`与`reading/chapter-NNN.md`，按真实游标、章组、`COMMITTED`血缘计汉字。候选、诊断、修订、择优、Canon/StoryState、请求与未完成问题留在原工作空间导出，不混入阅读版。`creation_checkpoint_review preview`也可无Provider导出已接纳范围。

失败先查`creation-run.json`、events与原operation/effect/receipt。未知Provider结果不得盲重发；新run key/evidence-dir不重置账本。修复后按影响维护合法代码/输入版本关系，保留原Formation/Book/Effect。改旧freeze、重建项目都不是恢复。

本包不使用两组六章`blind`接口判断完成。真实十二章可另交独立评审，覆盖知识准确性（未采用时不适用）、自然融入、因果、人物、节奏、声音、追读意愿；收到反馈前`NOT_REVIEWED`。作者指导、知识使用和模型审阅分别留痕，不推断知识因果收益。
