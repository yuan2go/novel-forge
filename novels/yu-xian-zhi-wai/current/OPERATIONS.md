# 当前操作与恢复

从仓库根目录执行；私有连接与账户配置放在仓库外。将 `NF_ROOT`、`RUN_ROOT`、`EVIDENCE_ROOT` 和 `NF` 配成实际位置，`NF` 可指向加载私有环境后执行原生 CLI 的本机包装器。不要使用素材业务库运行 pytest，也不要覆盖历史冻结、备份或旧配置。

```bash
NF_ROOT="${NF_ROOT:-$PWD}"
export PYTHONPATH="$NF_ROOT/src:$NF_ROOT"
NF="${NF:-$NF_ROOT/.venv/bin/novel-forge}"
PYTHON="$NF_ROOT/.venv/bin/python"
INPUTS="$NF_ROOT/config/production/first-novel-creative-execution"
```

当前配置是新的共同中性输入；历史 `first-novel-pilot` 和归档冻结不变。`experiment.json` 的 480 次 / 1200 万 Token 是机会分配建议，**不是授权**。金额和不可观测开销未知，不能据此预测费用。各阶段分别确认；没有授权时只执行查询、输入冻结和预览。

新 Formation 使用原生 `REVIEW_PLAN`，在候选审批处等待实际决定；不复用历史 `AUTO` 配置作为本轮自动批准授权。恢复使用原 `--resume-formation-run-id`，保留候选与审批记录。

## 查询已有素材

```bash
"$NF" corpus jobs --project-id first-novel-pilot-20260912 --limit 10
"$NF" corpus inspect --project-id first-novel-pilot-20260912 \
  --processing-id corpus-processing:c4991a1a3a6e8f8259f9b585a5e745605ad13980bc34f689b2ea00d38b90d512
"$NF" authority-creative-budget query --project-id first-novel-pilot-20260912
```

最后一个查询在尚未登记阶段授权时返回 `CREATIVE_BUDGET_AUTHORIZATION_REQUIRED`，不返回虚假的零余额。既有素材目录、失败和精选版本见[历史目录](../corpus/index.html)。无需重新获取或重新入库。

## 第一阶段：Source 小样

待明确确认：Codex CLI / gpt-6-astra / xhigh、实际账户引用、本项目与 `hydraulics-12` 范围、`ACCOUNT_ENTITLEMENT`、总计最多 10 次 / 250000 可观测 Token（含审阅、有限修复、D0与恢复）、并发 1；金额及不可观测 CLI 开销未知，不改用付费 API。该范围不包含知识正式批准、设计、正文或 B 组。

确认后，在同一真实账户配置下由具有权限的操作者登记阶段策略，`policy.authorization` 绑定实际授权引用、证据字节哈希、项目和 Book。Source 授权累计上限为已确认小样额度，CREATION/REPAIR 均为零。授权文件由实际确认产生，此目录不附伪造授权。

```bash
"$NF" authority-creative-budget configure --project-id first-novel-pilot-20260912 \
  --workspace-id first-novel-pilot-workspace --policy-file "$CONFIRMED_POLICY_FILE" \
  --authorization-evidence-file "$CONFIRMED_EVIDENCE_FILE" --idempotency-key "$GRANT_KEY"
"$NF" corpus analyze --project-id first-novel-pilot-20260912 \
  --revision-id corpus-curated-revision:d7202836d9753903ba45e9f8ef3d4282696cdde7580f45c7c6cd92deee12bb10 \
  --reading-scopes "$NF_ROOT/novels/yu-xian-zhi-wai/corpus/canary-reading-scopes.json" \
  --intended-use ABSTRACT_GENERATION --target-book-id first-novel-pilot-a \
  --run-key first-novel-source-canary-v1 --limit 1 --max-calls 10 --max-tokens 250000 \
  --authorization-ref "$CONFIRMED_REF"
```

先用原 `reading-preview` 核对实际读取，再沿 `corpus run --max-stages 1`、`corpus status/results` 分阶段执行，D0 复用原 Source extraction Operation。详细参数以原生 `corpus --help` 和[运行手册](../../../docs/runtime-operations.md)为准。未知结果核对原 Effect/receipt；恢复保留原 job、project、Book 和 run key。暂停、恢复不释放未知预留；新 evidence-dir 不重置账本。

Candidate 逐项导出原文定位、结论、条件、例外与拟用位置，由有权限审核者决定确切版本。已有 MKAOS 批准 API 的 202 只是受理，须待原 worker 完成并查询正式 Card。模型建议不是独立人工批准。

## 冻结、原生设计和首章

获得确切批准版本后才创建 A 的白名单。使用新的、尚不存在的目录；不要把旧 freeze 目录当新的 input-dir。

```bash
"$PYTHON" -m scripts.prepare_knowledge_closure prepare --input-dir "$INPUTS" \
  --approved-card-versions "$APPROVED_VERSIONS_FILE" --target-book-id first-novel-pilot-a \
  --output "$FROZEN_A"
"$PYTHON" -m scripts.prepare_knowledge_closure verify "$FROZEN_A"
```

保存最终 `freeze.json` 字节 SHA256 为外部校验值 `FREEZE_MANIFEST_HASH_A`。`verify` 不改文件；输入变化必须新版本目录。恢复沿用同一冻结目录和外部校验值。

```bash
"$PYTHON" -m scripts.run_creation_synthesis \
  --brief "$FROZEN_A/brief.json" --policy "$FROZEN_A/creation.json" \
  --formation-policy "$FROZEN_A/formation.json" --knowledge-policy "$FROZEN_A/allow-only.json" \
  --comparison-budget "$FROZEN_A/experiment.json" --freeze-dir "$FROZEN_A" \
  --freeze-manifest-hash "$FREEZE_MANIFEST_HASH_A" \
  --project-id first-novel-pilot-20260912 --book-id first-novel-pilot-a \
  --workspace-id first-novel-pilot-workspace --root "$RUN_ROOT/a" --run-key first-novel-a-v1 \
  --expected-sha "$VERIFIED_SHA" --evidence-dir "$EVIDENCE_ROOT/a-preview-v1"
```

上面仅预览。原生 Formation/Opening/正文阶段须另获额度后添加 `--initialize --execute --authorization-ref "$CONFIRMED_REF"`，并使用新的 evidence-dir。先完成一条知识进入规划、最终请求与接纳正文的追溯再扩大调用。若只批准分阶段的 A 首章机会，允许本组工作，但 A/B 比较保持未成立；不能事后追加额度就追认先前机会公平。

B 独立冻结同一中性 brief 与比较计划，使用 `deny-all.json`，独立 project/Book/workspace/run-key/runtime-root；不得复制 A 的设计和缓存。Source 剩余额度不能转为任一组正文或修复额度。授权升级沿原生策略追加版本和累计上限，历史 Effect 仍保留原授权，账本不清零。

登记 B 的预算前，若该项目尚不存在，先通过已有 `POST /product/projects` 创建空的 B 项目与工作区，不能克隆 A。该步骤不调用模型：

```bash
curl --fail-with-body -H 'Content-Type: application/json' \
  --data '{"project_id":"first-novel-control-20260912","workspace_id":"first-novel-control-workspace","title":"雨线之外 B","idempotency_key":"first-novel-control-project-v1"}' \
  "$API_ROOT/product/projects"
```

仅获准设计或首章时，以既有 Supervisor 的单步推进和暂停操作守住已授权范围，达到边界立即暂停；不要直接启动六章连续驱动。部分创作额度允许启动，实际预留仍受阶段上限限制；这不构成完整 A/B 机会公平证明。

第三章后先检查本组实际接纳证据，再通过既有 PlanChange 的提出、审批和激活入口修改第四至六章。无证据触发时保持暂停，不伪造旧计划或事件。恢复传入原生 `--plan-change-proposal-id`；第六章完成真实章组后暂停，目标 180 章的 Book 不结束。

## 导出与评审

runner 保存原稿、审稿、修订、选择、接纳、状态、实际请求和预算用量。任一卡使用 `authority-knowledge-trace` 反查。两组都接纳六章且完整导出后，才执行：

```bash
"$PYTHON" -m scripts.prepare_knowledge_closure blind "$A_EXPORT" "$B_EXPORT" --output "$BLIND_OUTPUT"
```

预算比较输出显式分类差异与实际累计用量；未知重要差异或未测使用阻止公平结论。盲评由独立评审填写七维表，当前为 `NOT_REVIEWED`；没有真实正文时不评价文学质量。
