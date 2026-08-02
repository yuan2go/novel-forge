# AC-13 Quality、Eval 与 Release Gate

状态：`PLANNED`  
阶段：Phase 3 / Intelligence and Decision Closure  
前置依赖：AC-06、AC-08、AC-09、AC-12

## 1. ADR

### 背景

当前系统已有五组 Chapter Quality、Quality Aggregate、Quality Eval 2.0、Eval Center、Provider Judge、Reader Outcome、ReviewIssue、Publish Gate 和 Final Release Gate。若这些证据使用不同评分、校准、阻塞和目标绑定方式，系统会把 Fixture score、未校准模型判断和真实读者反馈混为一体。

### 决策

所有质量判断统一为版本化 QualityEvidence，并明确：目标 AssetVersion、JudgeProfile、EvaluationFamily、InputManifest、ContextManifest、RouteSnapshot、Raw Output、Normalized Result、Calibration Status、Evidence Span、Issue、Blocking Level 和 Confidence Semantics。

质量结果必须区分：

- deterministic rule；
- heuristic；
- model judge；
- pairwise preference；
- human review；
- reader simulation；
- platform behavior；
- mutation/OOD test。

未校准结果不得声称概率，只能使用 Raw Score、Ordinal Band、Pairwise Preference 或 Uncalibrated Ranking。

Final Release 必须通过统一 Gate Aggregate，任何单独模块不得自行声明 production-ready。

## 2. Gate 模型

统一状态：

```text
PASSED
BLOCKED
WARNING
NOT_EVALUATED
STALE
```

Gate 至少聚合：Canon、Continuity、Quality、Originality、Source、Platform、Cost、Approval、Export Verification。Gate policy 本身必须版本化，并绑定目标版本和 effective environment。

Reader Outcome 在校准完成前保持 Shadow/Advisory，不得直接阻断发布，除非独立 Authority Policy 明确批准。

## 3. 实施范围

- 建立 JudgeProfile、EvaluationSuite、GoldenSet、HumanAnnotation、CalibrationReport；
- 统一 Chapter 五组质量、Aggregate 和其他 Quality Eval 输出；
- 将 ReviewIssue、RevisionTask 和 GateDecision 建立可追踪链；
- 建立 stale evidence 检测：目标资产或依赖变化后旧证据失效；
- 建立 pairwise、mutation、OOD 和 disagreement evidence；
- Gate Aggregate fail closed：缺少 required evidence 即 BLOCKED/NOT_EVALUATED；
- 发布和 Book completion 使用同一证据框架但不同 policy。

## 4. 代码位置

### 当前重点

- `src/novel_forge/modules/quality_eval/`
- `src/novel_forge/modules/evaluation_center/`
- `src/novel_forge/modules/chapter_authority/handlers.py`
- `src/novel_forge/modules/book_followup_authority/`
- `src/novel_forge/modules/review_issue/`
- `src/novel_forge/modules/content_quality_loop/`
- `src/novel_forge/modules/publishing/`
- `src/novel_forge/modules/long_chain_proof/`

### 目标收敛

- `src/novel_forge/modules/quality_authority/contracts.py`
- `.../judge_profiles.py`
- `.../evidence.py`
- `.../calibration.py`
- `.../issues.py`
- `.../gates.py`
- `.../aggregation.py`
- `.../staleness.py`
- `tests/integration/test_quality_authority_postgres.py`

若现有 Quality Eval 2.0 已承担这些能力，应作为唯一实现扩展。

### 禁止位置

- Judge 直接修改 Draft；
- 未绑定 AssetVersion 的分数；
- 将 Fixture provider 标记 external proof；
- 未校准分数转成概率；
- Gate 只检查报告文件是否存在；
- 发布路径绕过 required gate。

## 5. 迁移脚本设计

数据库需支持 Judge profiles/versions、Evaluation runs/evidence、golden sets、annotations、calibration reports、issues、gate policies/results 和 staleness links。

脚本：

```text
scripts/migrations/inventory_quality_reports.py
scripts/migrations/import_quality_evidence.py
scripts/migrations/link_quality_targets_and_inputs.py
scripts/migrations/classify_calibration_status.py
scripts/migrations/rebuild_gate_results.py
scripts/migrations/quarantine_unbound_scores.py
```

无法绑定目标版本、Judge profile 或输入证据的旧评分只能作为 historical/unverifiable，不进入正式 Gate。

## 6. 实施计划

1. 固定 QualityEvidence 和 GateResult contract。
2. 统一五组 Chapter quality 与 Eval Center 输出。
3. 建立 JudgeProfile、Suite、GoldenSet 和 Calibration lifecycle。
4. 将 ReviewIssue/RevisionTask/Revision evidence 串联。
5. 建立 stale detection 和 required evidence policy。
6. 将 Publish/Final Release/Book Completion 接入 Gate Aggregate。
7. 完成真实 Provider Judge + human/golden calibration pilot。
8. 建立 L10/L30 质量趋势和回归检测。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Target binding | score 无 target version | 拒绝 |
| Calibration semantics | uncalibrated 输出概率 | contract 拒绝 |
| Staleness | Draft 新版本产生 | 旧 evidence 不再满足 Gate |
| Missing evidence | required Judge 未运行 | BLOCKED/NOT_EVALUATED |
| Disagreement | 多 Judge 冲突 | 保存 disagreement，不静默平均 |
| Revision loop | blocking issue 修复 | 新 evidence 绑定新版本 |
| Fixture classification | scripted provider | external_proof=false |
| Publish bypass | 直接调用 submit | 发布 Authority 拒绝 |
| Golden calibration | human labels 与 judge | 输出 calibration report |
| Long chain | 10/30 章趋势 | 可检测持续下降和漂移 |

## 8. Acceptance Gate

```text
quality_evidence_contract_unified=true
judge_profiles_versioned=true
uncalibrated_probability_claims_blocked=true
quality_evidence_staleness_verified=true
review_revision_evidence_chain_complete=true
release_gate_aggregate_fail_closed=true
real_provider_judge_pilot_proven=true
human_golden_calibration_foundation_verified=true
```

## 9. 风险

- 指标过多导致优化目标冲突：Gate policy 明确 required/advisory，保留 disagreement。
- Judge 自洽但与读者无关：逐步引入 human、pairwise、platform behavior 校准。
- 质量循环无限修订：设置 revision budget、stop policy 和 human escalation。
- Gate 阻塞开发：development policy 可 warning，但 production policy 不得静默降级。