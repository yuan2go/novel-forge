# Novel OS Capability Pack 系统设计文档

> 文档类型：系统设计 / Architecture and Protocol Design  
> 更新日期：2026-08-05  
> 目标分支：`feat/v7-content-intelligence-and-longform-proof`  
> 本轮静态审计基线 HEAD：`f8bb9f252ef701ede19a9a1838d4deaf513ff6fc`  
> 仓库既有实现证据基线：`8d0c49973ad3f58ca325e3d39941fd89cb5d5f5e`  
> 测试状态：`NOT_EXECUTED`；本轮未在本地执行测试，GitHub HEAD 无 Actions 状态和 workflow run 记录  
> 文档状态：`PROPOSED SYSTEM DESIGN`  

## 1. 文档目的

本文基于当前 Novel Forge 代码，设计 Capability Pack 的系统协议、组件边界、运行时集成、持久化模型、验证规则和分阶段实施方案。

本文不把 Capability Pack 设计为新的执行平台。其核心定位是：

```text
业务能力声明标准
→ 静态校验
→ 版本解析
→ 编译为现有执行合同
→ 绑定现有 Authority Operation
→ 使用现有 Saga / Attempt / ExternalEffect 执行
→ 使用现有 AssetVersion / Event / Audit 保存证据
```

系统必须继续遵守当前架构原则：

1. PostgreSQL Authority 是生产唯一权威；
2. Authority Attempt 是唯一执行尝试权威；
3. Transaction Command、Durable Job、Saga、External Effect 必须按执行语义分类；
4. Production Execution Plane 负责受控执行，不拥有领域语义；
5. Context Builder 应按当前文档术语收敛为 Context Compiler；
6. Book Production Coordinator 只协调，不拥有创作领域状态；
7. Fixture、Schema、文档和 UI 不等于生产证明。

---

## 2. 当前代码事实

### 2.1 主入口与运行边界

| 代码位置 | 当前事实 | Capability Pack 复用点 |
|---|---|---|
| `src/novel_forge/cli/__init__.py` | 在 Legacy 与 PostgreSQL Authority CLI 间 fail-closed 选择；production 禁止 Legacy command surface | 后续增加 Pack register / validate / inspect 命令时必须走 Authority CLI |
| `src/novel_forge/infrastructure/settings.py` | production 强制 PostgreSQL，禁止 Legacy write、dual write 和 silent fallback | Pack compatibility 和 release channel 必须复用环境治理 |
| `src/novel_forge/workers/runtime_groups.py` | Authority、Execution、Integration、Maintenance worker group 按执行特性划分 | Pack 不按每个业务域新建 worker；运行任务应路由到现有 group |
| `architecture/manifests/module-manifest.yaml` | 当前正式模块包括 command-kernel、project/task/source/mkaos/chapter/book/book-design、provider-control、runtime-job 等 | Capability Pack 新模块应纳入 architecture manifest 和 fitness checks |

### 2.2 Production Execution Plane 基础

| 代码位置 | 已有合同 |
|---|---|
| `modules/production_execution/capabilities.py` | `CapabilityId`、`ExecutionDomain`、`RiskClass`、`CapabilityDefinition` |
| `modules/production_execution/capability_registry.py` | fail-closed Capability Registry、环境和 backend compatibility 校验 |
| `modules/production_execution/bundles.py` | `PromptBundle`、`SkillBundle`、hash、no-inline-secret 校验 |
| `modules/production_execution/policies.py` | Context、Source、Validation、Commit 等策略合同 |
| `modules/production_execution/contracts.py` | ExecutionRequest、InputManifest、RouteSnapshot、ModelProfile、FallbackPolicy、ValidationManifest、CommitManifest 等 |
| `modules/production_execution/gateway.py` | Admission、Backend Registry、ProductionExecutionGateway |

当前 `CapabilityDefinition` 已经包含：

- input / output schema ref；
- allowed runtime classes；
- allowed backend ids；
- prompt / skill bundle type；
- timeout / budget / permission / source / validation / commit policy ref；
- provider idempotency；
- query / cancel / callback；
- fixture / production allowed；
- risk class。

结论：`CapabilityDefinition` 是 Pack 的底层执行能力定义，但不是 Pack 本身。Pack 必须引用一个或多个 CapabilityDefinition，而不是替换它。

### 2.3 Chapter Authority 基础

`src/novel_forge/modules/chapter_authority/contracts.py` 定义当前 18 个节点：

```text
PLAN
CONTEXT
DRAFT
REVIEW
REVISION
REREVIEW
CANON_EXTRACTION
CANON_PROPOSAL
CANON
QUALITY_STRUCTURAL
QUALITY_COMMERCIAL
QUALITY_SOURCE_ORIGINALITY
QUALITY_LONGFORM
QUALITY_PLATFORM
QUALITY
PUBLISH_GATE
EXPORT
FINAL_RELEASE_GATE
```

每个节点绑定：

- definition name；
- asset type；
- output key；
- completion topic；
- handler key。

`orchestrator.py` 已通过 Command Kernel 建立：

```text
root Operation
→ Saga
→ child Operation
→ dependency
→ Attempt
→ Lease / Fence
→ Handler execution
→ completion contract
→ evidence manifest
```

`handlers.py` 已实现：

- frozen ChapterPlan 身份校验；
- Context manifest / frozen input / segment 一致性；
- Draft / Review / Revision / Re-review 模型调用；
- Canon Extraction / Proposal / Decision / Patch；
- 五组 Quality fan-out；
- Quality Aggregate fan-in；
- Publish / Export / Final Release Gate；
- execution commit evidence。

结论：Chapter Authority 是首个 Capability Pack 的最佳接入点，但 P0 不应把硬编码节点改成动态 Workflow。

### 2.4 Chapter Execution Contract Binder

`src/novel_forge/modules/chapter_authority/execution_gateway.py` 的 `PostgresChapterExecutionContractBinder` 已在每个 Attempt 中生成并冻结：

```text
ContextPolicy
SourcePolicy
ValidationPolicy
CommitPolicy
SkillBundle
PromptBundle
ModelProfile
FallbackPolicy
RoutePolicy
InputManifest
RouteSnapshot
ExecutionRequest
```

这些合同以 Authority AssetVersion 保存，并通过 operation、attempt、fencing token、project、workspace、book、chapter、input artifact、budget reservation 等身份绑定。

这是 Capability Pack Runtime Compiler 的直接复用目标。

### 2.5 Command Kernel 与执行语义

`modules/command_kernel/service.py` 已实现：

- Command identity 校验；
- Operation Definition 注册和查找；
- handler availability；
- permissions；
- actor identity；
- idempotency scope / request digest；
- frozen input asset snapshot；
- approval policy；
- definition / policy / completion snapshot；
- event / audit / outbox evidence。

`execute_transaction_command` 已定义原子 Transaction Command：

```text
admission
+ domain mutation
+ AssetVersion
+ completion evidence
+ audit / outbox
+ Operation success
= one PostgreSQL transaction
```

`attempt_runtime.py` 已实现 Durable Job / Saga 节点所需的 Attempt、Lease、Fence、Heartbeat、Checkpoint、Retry、Dead Letter、Result 和 Timeout。

结论：Pack 注册、验证、激活、停用等短事务应使用 Transaction Command；Pack 驱动的模型执行继续使用现有 Saga / Durable Job / External Effect。

### 2.6 MKAOS、Book 和 Reader 基础

- `mkaos_authority` 已有 Candidate → Governance Decision → KnowledgeCard → KnowledgePack；
- `book_design_authority` 已有 Book create、BookDesign propose / decide / activate；
- `book_authority` 已有 Book Root、Chapter child delegation、acceptance、cursor、pause / cancel 和 follow-up；
- Story Design / Hierarchical Planning 迁移已有 Generator Definition、Version State、Plan Binding、Hierarchy、Planning Horizon、Production Cursor；
- Reader Calibration 迁移已有 Human Preference、Reader Exposure、Outcome Event、Calibration Profile / Run / Metric / Validity。

结论：这些领域可以成为后续 Pack，但 P0 只实现协议层，不为每个领域分别开发 Pack Runtime。

---

## 3. 架构决策

### ADR-CP-001：Capability Pack 位于 Agent OS 业务能力层

Capability Pack 是业务能力声明，不属于 MKAOS、Prompt 或 Provider 子系统。

```text
Agent OS / Capability Pack Layer
→ Production Execution Capability Layer
→ Command Kernel / Runtime Layer
→ PostgreSQL Authority / Object Store
```

### ADR-CP-002：Pack 不拥有运行状态

Pack 不新增独立状态机。

```text
Pack Manifest
= immutable definition

Pack Version Binding
= resolution evidence

Operation / Saga / Attempt
= runtime state authority
```

未来的 `capability_pack_run` 如存在，只能是查询投影或聚合索引，不得成为状态权威。

### ADR-CP-003：Pack Manifest 是 Authority AssetVersion

从 P1 开始，Pack Manifest 应保存为：

```text
asset_type = capability_pack_manifest
schema_version = capability-pack-manifest.v1
lifecycle = CANDIDATE / ACTIVE / SUPERSEDED / REVOKED
```

Pack 表保存可查询业务索引，完整 manifest 和 hash 由 AssetVersion 承载。

### ADR-CP-004：Pack 编译到现有 PEP 合同

Pack Compiler 不执行模型。它只解析和生成：

- Capability references；
- PromptBundle；
- SkillBundle；
- ContextPolicy；
- SourcePolicy；
- ValidationPolicy；
- CommitPolicy；
- Tool / Permission Policy refs；
- Workflow / Operation Definition binding；
- Evaluation binding。

### ADR-CP-005：P0 使用 JSON 和标准库

P0 不新增 PyYAML 或 JSON Schema 第三方库。协议文件优先 JSON，使用标准库和显式 Python 校验。

### ADR-CP-006：P0 只校验已注册 Operation 和 Capability 的引用

不允许 Pack 在运行时创建任意 Python handler 或执行任意 import path。早期 Pack Workflow 只能引用：

- 已注册 CapabilityId；
- 已知 Operation Definition；
- 已知 handler key；
- 已知 Asset Type 和 policy ref。

---

## 4. 目标架构

```text
config/capability_packs/*.json
          │
          ▼
CapabilityPackLoader
          │
          ▼
CapabilityPackManifest
          │
          ├── CapabilityPackValidator
          │       ├── CapabilityRegistry
          │       ├── Workflow DAG Validator
          │       ├── Context / Source Validator
          │       ├── Tool Permission Validator
          │       └── Evaluation / Runtime Validator
          │
          ├── CapabilityPackVersionResolver        [P1/P2]
          │
          └── CapabilityPackCompiler               [P2]
                  ├── PromptBundle
                  ├── SkillBundle
                  ├── ContextPolicy / SourcePolicy
                  ├── ValidationPolicy / CommitPolicy
                  ├── Operation Definition bindings
                  └── PackExecutionBinding
                              │
                              ▼
                    Existing Authority Application
                              │
                              ▼
           Command / Transaction / Job / Saga / Effect
                              │
                              ▼
               Authority AssetVersion / Audit / Query
```

---

## 5. 模块设计

### 5.1 P0 模块结构

```text
src/novel_forge/modules/capability_packs/
├── __init__.py
├── schema.py
├── loader.py
├── validator.py
└── errors.py

config/capability_packs/
└── chapter_generation_pack.json

tests/unit/
└── test_capability_pack_validator.py
```

### 5.2 `schema.py`

职责：

- 定义强类型 dataclass / StrEnum；
- 从 Mapping 解析；
- canonical serialization；
- manifest hash；
- 不执行跨模块运行时查询。

建议核心类型：

```text
CapabilityPackManifest
PackIdentity
PackCompatibility
RoleDefinition
SkillBinding
BoundSkill
PromptBinding
WorkflowTemplate
WorkflowNode
RetryPolicy
ApprovalBinding
ContextSources
ContextFreshnessPolicy
ToolPermissions
ToolBinding
PackAssets
RuleBinding
TemplateBinding
EvaluationDefinition
EvaluationGate
EvaluationMetric
RuntimeContract
GovernanceDefinition
AuditDefinition
ValidationReport
```

### 5.3 `loader.py`

职责：

1. 接收 `str | Path`；
2. 限制 UTF-8 JSON；
3. 限制文件大小，例如 1 MiB；
4. 拒绝根对象不是 JSON object；
5. 调用 `CapabilityPackManifest.from_dict`；
6. 不读取网络；
7. 不展开任意 `$ref`；
8. 不读取 secret 或环境变量。

建议接口：

```python
load_capability_pack(path: str | Path) -> CapabilityPackManifest
load_capability_pack_payload(payload: Mapping[str, Any]) -> CapabilityPackManifest
```

### 5.4 `validator.py`

职责：

- 对 manifest 做跨字段、跨引用校验；
- 调用现有 `default_capability_registry()`；
- 输出结构化报告，不以裸 `ValueError` 作为产品结果；
- 对程序错误和用户配置错误进行区分。

建议接口：

```python
validate_capability_pack(
    manifest: CapabilityPackManifest,
    *,
    capability_registry: CapabilityRegistry | None = None,
) -> CapabilityPackValidationReport
```

### 5.5 `errors.py`

建议错误对象：

```python
@dataclass(frozen=True, slots=True)
class CapabilityPackValidationIssue:
    code: str
    path: str
    message: str
    severity: str
```

核心错误码：

| 错误码 | 含义 |
|---|---|
| `CAPABILITY_PACK_SCHEMA_VERSION_UNSUPPORTED` | 协议版本不支持 |
| `CAPABILITY_PACK_IDENTITY_INVALID` | pack_id / version / status / lifecycle 非法 |
| `CAPABILITY_PACK_CAPABILITY_UNKNOWN` | CapabilityId 未注册 |
| `CAPABILITY_PACK_HASH_INVALID` | hash 非 SHA-256 |
| `CAPABILITY_PACK_SKILL_DUPLICATE` | Skill 重复 |
| `CAPABILITY_PACK_SKILL_DEPENDENCY_UNKNOWN` | Skill 依赖不存在 |
| `CAPABILITY_PACK_WORKFLOW_NODE_DUPLICATE` | Workflow 节点重复 |
| `CAPABILITY_PACK_WORKFLOW_DEPENDENCY_UNKNOWN` | 节点依赖不存在 |
| `CAPABILITY_PACK_WORKFLOW_CYCLE` | Workflow 有环 |
| `CAPABILITY_PACK_TOOL_DEFAULT_ALLOW_FORBIDDEN` | 工具策略不是 default deny |
| `CAPABILITY_PACK_HIGH_RISK_TOOL_AUDIT_REQUIRED` | 高风险工具未要求审计 |
| `CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN` | 生产 Pack 允许原始来源进入 Context |
| `CAPABILITY_PACK_EVALUATION_CAPABILITY_UNKNOWN` | Judge capability 未注册 |
| `CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED` | 生产 Pack 未绑定 Authority Operation / Attempt Fence |
| `CAPABILITY_PACK_EXTENSION_INVALID` | ext 不是对象或包含保留字段 |

---

## 6. 标准协议

### 6.1 协议版本

```text
schema_version = novelos.capability_pack.v1
```

Pack 自身使用 SemVer：

```text
identity.version = MAJOR.MINOR.PATCH
```

资产 Schema 独立版本化，不与 Pack version 混用。

### 6.2 顶层结构

```yaml
schema_version: novelos.capability_pack.v1
identity: {}
compatibility: {}
role: {}
skill_binding: {}
prompt_binding: {}
workflow_template: {}
context_sources: {}
tool_permissions: {}
assets: {}
evaluation: {}
runtime_contract: {}
governance: {}
audit: {}
ext: {}
```

### 6.3 Identity

必填字段：

```yaml
identity:
  pack_id: chapter_generation_pack
  name: Chapter Generation Pack
  domain: prose
  capability_type: production_workflow
  version: 1.0.0
  owner: novel-os-core
  status: CANDIDATE
  lifecycle: VALIDATION
  description: Governed chapter production capability.
```

约束：

- `pack_id`：`^[a-z][a-z0-9_.-]*$`；
- `version`：基础 SemVer；
- `status`：`DRAFT | CANDIDATE | ACTIVE | DEPRECATED | RETIRED | DISABLED`；
- `lifecycle`：`DESIGN | VALIDATION | PRODUCTION | MAINTENANCE | RETIRED`。

### 6.4 Compatibility

```yaml
compatibility:
  novel_forge_min_version: 6.0.0
  novel_forge_max_version: null
  protocol_min_version: novelos.capability_pack.v1
  protocol_max_version: null
  required_capabilities:
    - prose.chapter.draft
    - review.chapter.evaluate
  required_schema_versions:
    - chapter-plan-authority.v1
  incompatible_packs: []
  compatible_runtime_profiles:
    - development
    - validation
    - validation
    - production
```

P0 必须校验 `required_capabilities`；Novel Forge version range 和 schema availability 可在 P1 完整实现。

### 6.5 Role Definition

```yaml
role:
  role_type: WORKER
  role_name: chapter_authority_worker
  responsibilities: []
  boundaries: []
  forbidden_actions: []
  upstream_packs: []
  downstream_packs: []
  authority_level: DOMAIN_AUTHORITY
```

`role_type`：`AGENT | WORKER | REVIEWER | JUDGE | AUTHORITY | COORDINATOR`。

### 6.6 Skill Binding

```yaml
skill_binding:
  mode: STATIC
  skills:
    - skill_ref: chapter-draft-skill
      version: chapter-draft-skill-v1
      content_hash: sha256:...
      required: true
      input_contract_ref: schema:execution-input:prose-chapter-draft:v1
      output_contract_ref: schema:execution-output:prose-chapter-draft:v1
      preconditions: []
      postconditions: []
      depends_on: []
      max_invocations_per_run: 1
      drift_policy: FAIL_CLOSED
  anti_drift:
    duplicate_skill_refs_forbidden: true
    unbound_skill_forbidden: true
    dynamic_selection_requires_policy: true
```

P0 规则：

- Skill ref 唯一；
- hash 有效；
- dependency 存在；
- invocation > 0；
- `DYNAMIC_ALLOWED` 必须存在显式 selection policy ref，否则失败。

### 6.7 Prompt Binding

```yaml
prompt_binding:
  prompt_bundle_type: DOMAIN_PROMPT_BUNDLE
  system_instruction_hash: sha256:...
  template_hash: sha256:...
  compiler_version: chapter-prompt-compiler:v1
  input_schema_ref: schema:execution-input:prose-chapter-draft:v1
  output_schema_ref: schema:execution-output:prose-chapter-draft:v1
```

P0 不保存 Prompt 内容，只保存 identity、version 或 hash。

### 6.8 Workflow Template

```yaml
workflow_template:
  workflow_id: chapter_authority_slice
  workflow_version: 1.0.0
  execution_mode: SAGA
  idempotency_scope: project:chapter-slice
  nodes:
    - node_id: draft
      operation_name: chapter.draft.generate
      operation_definition_ref: chapter.draft.generate@1
      handler_key: novel_forge.chapter_authority.draft
      stage: draft
      capability_id: prose.chapter.draft
      input_asset_types: [chapter_plan, context_bundle]
      output_asset_types: [draft_chapter]
      depends_on: [context]
      retry_policy:
        max_attempts: 2
        retryable_errors: [PROVIDER_TIMEOUT]
        dead_letter_on_exhausted: true
      timeout_policy_ref: timeout:prose-chapter-draft:v1
      approval:
        required: false
        policy_ref: provider-route-policy-v1
      compensation:
        supported: true
        policy_ref: append-only-supersede-v1
  completion:
    required_terminal_nodes: [final_release_gate]
    required_evidence: [trace, audit, final_release_gate_report]
    required_output_asset_types: [release_package, final_release_gate_report]
```

P0 校验：

- node_id 唯一；
- capability 已注册；
- dependency 存在；
- DAG 无环；
- completion terminal node 存在；
- max_attempts > 0；
- 生产 Pack 不允许未声明 handler / operation ref。

P2 编译时，Pack node 不直接替换 `ChapterNode`，而是验证它与现有 Chapter Operation Definition 的映射一致。

### 6.9 Context Sources

```yaml
context_sources:
  policy_id: context-policy:chapter-generation-pack:v1
  max_tokens: 6000
  source_isolation: ABSTRACT_ASSETS_ONLY
  allowed_asset_types: []
  forbidden_asset_types:
    - raw_source_document
    - raw_source_chunk
  required_version_refs: []
  priority: []
  freshness:
    reject_stale: true
    reject_cross_project: true
    reject_unqualified: true
  longform_bindings:
    book: required
    volume: optional
    arc: optional
    chapter_group: required
    chapter: required
    canon: required
    story_bible: required
    reader_feedback: optional
```

P0 生产校验：

- max_tokens > 0；
- allowed / forbidden 不得交叉；
- production lifecycle 禁止 `RAW_ALLOWED_WITH_APPROVAL`；
- generation pack 必须禁止 raw source document / chunk；
- cross-project rejection 必须为 true。

P2 映射到现有 `ContextPolicy`、`SourcePolicy` 和 `InputManifest`。

### 6.10 Tool Permissions

```yaml
tool_permissions:
  policy_id: tools:chapter-generation-pack:v1
  default: DENY
  tools:
    - tool_ref: model.provider.invoke
      permission: EXECUTE
      allowed_operations: [draft]
      risk_class: HIGH
      approval_required: false
      audit_required: true
      budget_policy_ref: budget:chapter-generation-pack:v1
  database:
    read_allowed: true
    write_allowed: true
    allowed_tables: []
    forbidden_tables: []
  files:
    read_allowed: false
    write_allowed: false
    allowed_roots: []
  external_models:
    allowed: true
    route_policy_ref: chapter.stage.route.policy
  retrieval:
    allowed: true
    source_policy_ref: source:chapter-generation-pack:v1
```

P0 校验：

- `default == DENY`；
- HIGH / CRITICAL 必须 audit；
- CRITICAL 默认要求 approval，除非协议未来定义特定 Authority exemption；
- 不允许 inline credential；
- production file roots 不允许相对路径和 `..`。

### 6.11 Assets

```yaml
assets:
  knowledge:
    required_packs: []
    allowed_usage_roles: [PRINCIPLE, CONSTRAINT, CHECK, REFERENCE]
  rules:
    - rule_ref: source-isolation-no-raw-expression
      version: v1
      severity: BLOCKING
      hard_constraint: true
  templates: []
  source_policy:
    allowed_eligibility: [PRODUCTION_ELIGIBLE, NOT_SOURCE_DERIVED]
    raw_source_expression_allowed: false
    requires_lineage: true
```

P2 中 `knowledge.required_packs` 解析为 MKAOS Authority KnowledgePack AssetVersion，不解析目录或 latest-by-filename。

### 6.12 Evaluation

```yaml
evaluation:
  evaluation_id: chapter-generation-evaluation-v1
  required_gates:
    - gate_id: quality_aggregate
      judge_capability_id: quality.intrinsic.judge
      blocking: true
      threshold: 80
      required_evidence: [quality_score_report]
  metrics:
    - metric_id: originality
      type: ORIGINALITY
      target: pass
      aggregation: RULE
  failure_policy:
    acceptable_failures: []
    retryable_failures: [PROVIDER_TIMEOUT]
    terminal_failures: [CONTEXT_MANIFEST_CONSISTENCY_FAILED]
```

P0 校验 Judge capability；P2/P3 映射到 Chapter Quality、Reader Outcome、Evaluation Lab 和 Pack Evaluation Report。

### 6.13 Runtime Contract

```yaml
runtime_contract:
  input_protocol_ref: chapter-generation-input.v1
  output_protocol_ref: chapter-generation-output.v1
  error_protocol_ref: authority-error.v1
  state_protocol_ref: operation-saga-attempt-state.v1
  event_protocol_ref: authority-event.v1
  audit_protocol_ref: authority-audit.v1
  rollback_protocol_ref: append-only-supersede.v1
  commit_policy_ref: commit:chapter-generation-pack:v1
  validation_policy_ref: validation:chapter-generation-pack:v1
  execution:
    binds_authority_operation: true
    binds_attempt_fence: true
    external_effects_allowed: true
    synchronous_fixture_allowed: false
```

P0 对 `lifecycle=PRODUCTION` 或 `release_channel=PRODUCTION` 强制：

- `binds_authority_operation == true`；
- 模型、Agent、Durable Job 或 Saga 型 Pack 的 `binds_attempt_fence == true`；
- fixture 不允许作为生产证明。

Transaction Command 型 Authority Pack 可以在未来通过 execution classification 明确 `attempt_not_applicable=true`，但 P0 示例不处理该豁免。

### 6.14 Governance / Audit

```yaml
governance:
  release_channel: VALIDATION
  approval_policy_ref: domain-decision-record
  versioning:
    compatibility: BACKWARD_COMPATIBLE
    migration_required: false
    migration_policy_ref: null
  rollout:
    mode: OFF
    canary_percent: 0
  rollback:
    allowed: true
    policy_ref: append-only-supersede:v1
  cost_tracking:
    required: true
    budget_policy_ref: budget:chapter-generation-pack:v1
  quality_tracking:
    required: true
    report_refs: [quality_score_report]
  deprecation:
    replacement_pack_id: null
    retirement_deadline: null

audit:
  audit_level: FULL
  record_operation_snapshot: true
  record_pack_manifest_hash: true
  record_input_manifest: true
  record_route_snapshot: true
  record_tool_calls: true
  record_cost_receipts: true
  record_evaluation_results: true
```

---

## 7. Manifest Hash 与不可变性

Manifest hash 必须使用 canonical JSON：

```python
json.dumps(
    manifest.to_dict(),
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

然后计算 SHA-256，并统一输出：

```text
sha256:<64 lowercase hex>
```

以下字段不得纳入可变运行结果：

- current timestamp；
- generated UUID；
- environment secret；
- local absolute workspace path；
- latest alias resolution result。

Pack Version 一旦进入 `ACTIVE`，相同 `pack_id + version` 的 manifest hash 不得变化。变化必须发布新版本。

---

## 8. 静态校验流程

```text
Load JSON
→ Parse strongly typed schema
→ Validate top-level required fields
→ Validate identity and versions
→ Resolve CapabilityIds
→ Validate Skill graph
→ Validate Workflow graph
→ Validate Context and Source isolation
→ Validate Tool permissions
→ Validate Evaluation capabilities
→ Validate Runtime Authority binding
→ Compute manifest hash
→ Return structured report
```

Validator 不进行：

- Provider 网络调用；
- 数据库写入；
- 文件自动修复；
- Skill 内容执行；
- Prompt 编译；
- Workflow 执行。

---

## 9. P1 Registry 与持久化设计

### 9.1 可复用现有表

| 现有对象 | 用途 |
|---|---|
| `authority_asset` | Pack manifest 的稳定 Asset identity |
| `authority_asset_version` | 不可变 Pack version manifest |
| `authority_asset_qualification` | 静态验证、集成验证和发布资格 |
| `authority_operation_definition` | register / activate / deprecate / disable 命令定义 |
| `authority_operation` | Pack 治理命令和快照 |
| `authority_asset_evidence` | Validation / compilation / rollout evidence |
| state event / audit / outbox | Pack 治理事件 |

### 9.2 最小新增表

```sql
CREATE TABLE authority_capability_pack (
    pack_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    capability_type TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN (
        'DRAFT', 'CANDIDATE', 'ACTIVE',
        'DEPRECATED', 'RETIRED', 'DISABLED'
    ))
);

CREATE TABLE authority_capability_pack_version (
    pack_version_id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES authority_capability_pack(pack_id),
    version TEXT NOT NULL,
    manifest_asset_version_id TEXT NOT NULL UNIQUE
        REFERENCES authority_asset_version(asset_version_id),
    manifest_hash TEXT NOT NULL,
    protocol_version TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    release_channel TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    created_by_operation_id TEXT NOT NULL
        REFERENCES authority_operation(operation_id),
    activated_by_operation_id TEXT
        REFERENCES authority_operation(operation_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(pack_id, version),
    CHECK (manifest_hash LIKE 'sha256:%')
);
```

### 9.3 P2 Operation Binding

建议新增事实绑定表，而不是 `pack_run` 状态表：

```sql
CREATE TABLE authority_operation_capability_pack_binding (
    operation_id TEXT PRIMARY KEY
        REFERENCES authority_operation(operation_id),
    project_id TEXT NOT NULL REFERENCES authority_project(project_id),
    pack_version_id TEXT NOT NULL
        REFERENCES authority_capability_pack_version(pack_version_id),
    manifest_asset_version_id TEXT NOT NULL
        REFERENCES authority_asset_version(asset_version_id),
    manifest_hash TEXT NOT NULL,
    resolution_source TEXT NOT NULL,
    resolution_scope JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (manifest_hash LIKE 'sha256:%')
);
```

它只记录运行绑定，不拥有 Operation 状态。

### 9.4 不应立即新增的表

P1/P2 不新增：

- `capability_pack_runs`；
- `capability_pack_attempts`；
- `capability_pack_audit_logs`；
- `capability_pack_external_effects`。

这些数据已有 Authority 权威，重复表会导致双写和状态冲突。

---

## 10. Pack Registry 命令语义

建议 Operation：

| Operation | 执行分类 | 说明 |
|---|---|---|
| `capability_pack.register` | Transaction Command | 创建 Pack identity 和 candidate manifest version |
| `capability_pack.validate` | Durable Job 或 Transaction Command | P0 静态验证可事务执行；复杂集成验证可 Durable Job |
| `capability_pack.activate` | Transaction Command | 激活已通过资格的版本 |
| `capability_pack.deprecate` | Transaction Command | 标记 deprecated，不影响历史绑定 |
| `capability_pack.disable` | Transaction Command | 紧急禁止新解析 |
| `capability_pack.supersede` | Transaction Command | 建立 successor 关系 |
| `capability_pack.migrate_binding` | Saga / Durable Job | 批量迁移项目或书籍绑定，P4 实现 |

注册和激活必须复用 `execute_transaction_command`，确保：

```text
Operation admission
+ Pack row
+ AssetVersion
+ qualification / decision
+ audit / outbox
+ Operation success
= atomic commit
```

---

## 11. Pack Version Resolver

### 11.1 解析优先级

```text
explicit operation request
> workflow binding
> book binding
> project binding
> environment default
> global active default
```

### 11.2 解析输入

```text
pack_id
project_id
workspace_id
book_id optional
environment
release_channel
required_capabilities
runtime_profile
```

### 11.3 解析输出

```json
{
  "pack_version_id": "...",
  "pack_id": "chapter_generation_pack",
  "version": "1.0.0",
  "manifest_asset_version_id": "...",
  "manifest_hash": "sha256:...",
  "resolution_source": "book_binding",
  "release_channel": "CANARY"
}
```

解析结果必须在 Command Admission 前或 Admission 事务内冻结，不允许在同一 Operation 的后续 Attempt 中重新选择版本。

---

## 12. Pack Compiler

P2 新增 `CapabilityPackCompiler`，输入是已验证且已解析的 Pack Version。

### 12.1 编译结果

```text
CompiledCapabilityPack
├── manifest identity
├── capability definitions
├── skill bundles
├── prompt bundles
├── context/source policies
├── tool/permission policy refs
├── validation/commit policies
├── workflow bindings
└── evaluation bindings
```

### 12.2 与 Chapter Route 集成

当前 `authority_dependencies.py` 从环境变量生成：

- provider；
- model；
- prompt_version；
- skill_version；
- instruction/template/skill hash；
- route policy；
- fallback policy。

P2 应采用兼容式接入：

```text
Pack declares allowed and required contract
+ environment supplies deployment-specific provider credentials and host identity
→ compiler validates both sides
→ build ChapterExecutionRoute
```

Pack 不应包含：

- API key；
- auth token；
- runtime host secret；
- provider account credential。

Pack 可以包含：

- allowed provider class；
- model profile ref；
- reasoning policy；
- timeout / budget / fallback policy ref；
- prompt / skill identity和 hash。

### 12.3 Runtime Evidence

`PostgresChapterExecutionContractBinder` 在生成 SkillBundle、PromptBundle、InputManifest、RouteSnapshot 时应增加或关联：

```text
pack_id
pack_version
pack_manifest_hash
pack_manifest_asset_version_id
pack_resolution_source
```

优先通过独立 Pack binding evidence 或 contract ref 关联，避免破坏已有合同兼容性。

---

## 13. 各领域接入设计

### 13.1 Chapter Generation Pack

复用：

- ChapterNode；
- Chapter Operation Definitions；
- Chapter Handler Registry；
- Chapter Saga；
- PEP Chapter Contract Binder；
- Quality Aggregate；
- Final Release Gate。

新增：

- Pack manifest；
- Pack validator；
- Pack version binding；
- Pack audit query。

不新增：

- 第二套 Chapter Workflow；
- 第二套 Attempt；
- 动态 Python Handler。

### 13.2 Book Design Authority Pack

应映射到现有：

```text
book.create
book_design.propose
book_design.decide
book_design.activate
```

Pack 可描述角色和流程，但 Authority decision 仍由 BookDesign Authority 提交。Generator Pack 和 Authority Pack 建议分开，避免“生成即激活”。

### 13.3 MKAOS Knowledge Assets

Pack 的 `assets.knowledge.required_packs` 必须解析到：

- `authority_mkaos_knowledge_pack.asset_version_id`；
- frozen item list；
- selector policy version / hash；
- selection hash。

不得在执行中通过目录扫描或“最新文件”重新构建知识选择。

### 13.4 Longform Review Pack

未来映射到：

- `LONGFORM_RECAP_ANALYZE`；
- `LONGFORM_PLAN_VS_ACTUAL_JUDGE`；
- `LONGFORM_ARC_CLOSURE_JUDGE`；
- `LONGFORM_PLAN_CHANGE_GENERATE`；
- Book Follow-up Authority；
- Plan Change Authority。

输出必须是候选、Issue、Impact Report 或 Plan Change Proposal，不能直接修改 active plan / canon。

### 13.5 Reader Outcome Judge Pack

映射到：

- `QUALITY_READER_OUTCOME_JUDGE`；
- reader exposure / outcome；
- calibration profile / run / validity；
- human preference golden set。

Pack Validator / Resolver 必须根据 calibration status 限制运行模式：

```text
INSUFFICIENT_DATA → SHADOW
VALID → ADVISORY or bounded production
DRIFTED / INVALID → SHADOW or DISABLED
```

该规则在 P3/P4 实现。

---

## 14. 安全设计

### 14.1 Secret Boundary

Manifest 和 Compiled Pack 禁止包含：

- API key；
- password；
- bearer token；
- cookie；
- private key；
- connection string credential。

复用 `production_execution.security.assert_no_inline_secrets` 的检测方式。

### 14.2 Tool Boundary

Pack 声明工具权限，最终执行仍必须通过：

- Admission permission；
- qualified backend；
- ExternalEffect；
- budget reservation；
- audit / receipt；
- cancellation / reconciliation。

### 14.3 Source Boundary

生产生成 Pack 必须：

- `raw_source_expression_allowed=false`；
- `requires_lineage=true`；
- allowed eligibility 只包括受治理状态；
- Context Compiler 验证 manifest / frozen input / segment 一致；
- cross-project 失败关闭。

### 14.4 Extension Boundary

`ext` 只允许对象，并要求命名空间：

```text
ext.ui
ext.enterprise
ext.experiments
ext.vendor.<vendor_name>
```

扩展字段不得覆盖核心字段语义。核心 Validator 可以忽略未知命名空间，但必须保留 canonical serialization。

---

## 15. 可观测性与审计

### 15.1 Pack 级证据

每次运行至少应关联：

- Pack identity / version / hash；
- resolution source；
- Operation / Saga / Attempt；
- PromptBundle / SkillBundle；
- InputManifest / RouteSnapshot；
- tool calls / ExternalEffects；
- cost / usage receipt；
- evaluation results；
- commit / rollback ref。

### 15.2 Pack Audit Query

未来查询接口：

```text
GET /authority/capability-packs
GET /authority/capability-packs/{pack_id}/versions
GET /authority/capability-packs/{pack_id}/versions/{version}
GET /authority/operations/{operation_id}/capability-pack
GET /authority/capability-packs/{pack_id}/metrics
```

API 不是 P0 范围。

### 15.3 指标

- validation failure count by code；
- active version count；
- operation count by pack version；
- quality / cost / retry / failure distribution；
- deprecated version usage；
- resolver conflict；
- missing audit evidence；
- raw source and cross-project rejection。

---

## 16. 版本、灰度与迁移

### 16.1 版本兼容

| 变化 | 版本级别 |
|---|---|
| 描述、标签、非行为元数据 | Patch |
| 新增可选 Skill / Context / 非阻塞 Gate | Minor |
| 修改必填输入、输出 Schema、Workflow、权限、阻塞 Gate | Major |

### 16.2 灰度

P3 支持：

```text
OFF
SHADOW
CANARY
FULL
```

Canary 解析必须稳定，建议基于：

```text
hash(project_id + book_id + pack_id + rollout_version) % 100
```

不得根据进程随机数选择。

### 16.3 回滚

回滚不修改历史 Operation：

1. 停止新解析到问题版本；
2. 激活前一稳定版本；
3. 记录 supersession / rollback decision；
4. 已运行 Operation 保留原 Pack binding；
5. 需要重做的业务资产通过新 Operation 生成新版本。

### 16.4 迁移

Major migration 应输出：

- affected bindings；
- compatibility report；
- required asset revalidation；
- workflow change；
- operator approval；
- rollback plan；
- migration result evidence。

---

## 17. 测试设计

### 17.1 P0 Unit Tests

必须包含：

1. valid chapter generation pack；
2. unsupported schema version；
3. invalid pack id；
4. invalid semver；
5. unknown capability；
6. invalid hash；
7. duplicate skill；
8. unknown skill dependency；
9. duplicate workflow node；
10. unknown workflow dependency；
11. workflow cycle；
12. unknown terminal node；
13. tool policy not default deny；
14. high-risk tool without audit；
15. production raw source context；
16. allowed/forbidden asset overlap；
17. unknown judge capability；
18. runtime without Authority binding；
19. deterministic manifest hash；
20. loader rejects non-object / oversized / invalid JSON。

### 17.2 P1 PostgreSQL Tests

- register atomicity；
- same digest replay；
- different digest conflict；
- manifest hash immutable；
- activate only validated version；
- one active default per scope；
- disable prevents resolver selection；
- response loss after commit replay。

### 17.3 P2 Integration Tests

- Chapter root Operation freezes Pack binding；
- worker restart reuses same Pack version；
- route / prompt / skill / input contract references match Pack；
- Pack version change does not affect in-flight Operation；
- invalid Pack fails before Provider request；
- fixture is prohibited in controlled environment。

### 17.4 P3/P4 Acceptance

- Canary deterministic resolution；
- rollback；
- longform Pack sequence；
- Reader Judge calibration mode；
- 10 / 30 / 100 / 300 chapter staged proof；
- multi-book isolation；
- production SLO / security / PITR evidence。

---

## 18. 实施路线图

### P0：协议与静态校验

修改：

```text
src/novel_forge/modules/capability_packs/*
config/capability_packs/chapter_generation_pack.json
tests/unit/test_capability_pack_validator.py
```

不修改：

- migrations；
- Chapter Authority；
- ProductionExecutionGateway；
- CLI / API；
- Web。

### P1：Registry

新增：

- Pack Authority Transaction Commands；
- Pack / PackVersion 表；
- Manifest AssetVersion；
- Query service；
- PostgreSQL tests。

### P2：Chapter Runtime Binding

新增：

- Resolver；
- Compiler；
- Operation binding；
- execution contract references；
- integration tests。

### P3：Evaluation / Audit / Governance

新增：

- Pack evaluation report；
- audit query；
- activation / supersession；
- canary / rollback。

### P4：Composite Packs 和规模验证

新增：

- Pack dependency graph；
- Book / Longform / Reader Pack；
- 多项目、多书、多模型；
- enterprise extension。

---

## 19. P0 验收 Gate

```text
protocol_schema_defined=true
loader_fail_closed=true
validator_structured_report=true
capability_registry_reused=true
workflow_dag_validation=true
context_source_isolation_validation=true
tool_default_deny_validation=true
evaluation_capability_validation=true
authority_binding_validation=true
chapter_generation_pack_fixture_valid=true
unit_tests_passed=true
compileall_passed=true
runtime_behavior_unchanged=true
database_migration_added=false
```

只有全部为 true，P0 才可完成。

---

## 20. 结论

Capability Pack 可以被当前架构承载，且不需要新建平行平台。

最重要的系统决策是：

```text
Capability Pack
= business definition and governance source

Production Execution Plane
= execution contract and backend boundary

Command Kernel / Operation / Saga / Attempt
= runtime state and recovery authority

Authority AssetVersion
= immutable definition and evidence

MKAOS KnowledgePack
= knowledge dependency
```

P0 应保持极小：只完成协议、Loader、Validator、示例和 Unit Tests。其价值不是立即动态编排全部 Novel OS，而是为后续 Registry、Runtime Binding、Audit、Canary 和多 Pack 组合建立一个不会破坏现有 Authority 架构的稳定标准。