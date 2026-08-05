# Codex 执行提示：Capability Pack P0 协议与静态校验

将下面内容完整交给 Codex 执行。

---

你正在开发仓库：

```text
https://github.com/yuan2go/novel-forge
```

目标分支：

```text
feat/v7-content-intelligence-and-longform-proof
```

## 一、任务定位

请基于当前分支最新代码，实现 Novel OS Capability Pack 的 **P0 最小闭环：协议定义、JSON Loader、静态 Validator、章节生成示例 Pack 和单元测试**。

本轮不是开发完整 Capability Pack 平台，不接入生产运行时，不新增数据库表，不重构现有 Chapter Authority。

Capability Pack 的定位是：

```text
Role Definition
+ Skill Binding
+ Prompt Binding
+ Workflow Template
+ Context Sources
+ Tool Permissions
+ Knowledge / Rule / Template Assets
+ Evaluation Rules
+ Runtime Contract
+ Governance / Audit
```

它不是 Prompt 模板，不是 Skill 改名，也不是新的 Operation / Saga / Attempt 状态机。

请自行完整执行，不要在中途要求用户确认。遇到实现细节歧义时，以当前代码、现有架构原则和最小变更为准。

## 二、开始前必须完成的工作

1. 确认当前 Git 分支和 HEAD；
2. 检查工作区是否存在未提交修改，不覆盖与本任务无关的改动；
3. 阅读当前文档入口和本次设计：
   - `docs/README.md`
   - `docs/product/capability-pack-product-design.md`
   - `docs/architecture/capability-pack-system-design.md`
4. 阅读并理解以下代码：
   - `src/novel_forge/modules/production_execution/capabilities.py`
   - `src/novel_forge/modules/production_execution/capability_registry.py`
   - `src/novel_forge/modules/production_execution/bundles.py`
   - `src/novel_forge/modules/production_execution/policies.py`
   - `src/novel_forge/modules/production_execution/contracts.py`
   - `src/novel_forge/modules/chapter_authority/contracts.py`
   - `src/novel_forge/modules/chapter_authority/orchestrator.py`
   - `src/novel_forge/modules/chapter_authority/handlers.py`
   - `src/novel_forge/modules/chapter_authority/execution_gateway.py`
   - `src/novel_forge/api/authority_dependencies.py`
   - `src/novel_forge/modules/command_kernel/service.py`
   - `src/novel_forge/modules/command_kernel/attempt_runtime.py`
   - `architecture/manifests/module-manifest.yaml`
   - `scripts/check_module_manifest.py`
   - `scripts/check_architecture_fitness.py`
5. 阅读当前测试风格：
   - `tests/unit/`
   - `tests/integration/test_novel_os_acceptance.py`
   - `tests/integration/test_novel_os_long_chain_smoke.py`

不要根据旧文档或目录名称推断实现。代码与文档冲突时，以当前代码为准，并在报告中记录差异。

## 三、开发目标

新增一个纯标准库、fail-closed 的 Capability Pack P0 模块，建议结构：

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

如果当前仓库命名、模块组织或测试约定要求不同路径，可以做小幅调整，但必须说明原因。

## 四、严格修改边界

### 允许修改

1. 新增 `capability_packs` 模块；
2. 新增示例 JSON Pack；
3. 新增单元测试；
4. 在确有需要时更新：
   - `architecture/manifests/module-manifest.yaml`
   - 与新模块直接相关的 `__init__.py`
5. 新增实现报告：
   - `docs/reports/capability-pack-p0-implementation-report.md`

### 禁止修改

1. 不新增或修改数据库迁移；
2. 不新增 PostgreSQL 表；
3. 不修改 `ChapterNode` 和 18 节点执行顺序；
4. 不修改 `ChapterAuthorityApplication` 的运行行为；
5. 不修改 `ProductionExecutionGateway` 的执行行为；
6. 不新增 CLI、API 或 Web 页面；
7. 不接入真实 Provider；
8. 不新增第三方依赖；
9. 不实现 Pack Registry、Resolver、Compiler、Runtime Binding、Canary 或 Migration；
10. 不创建 `capability_pack_run`、Pack Attempt 或第二套审计状态；
11. 不弱化现有 Source Isolation、Permission、Budget、Attempt Fence 或 fail-closed 行为；
12. 不进行与本任务无关的重构、格式化或文档清理。

## 五、协议版本与核心模型

协议版本固定为：

```text
novelos.capability_pack.v1
```

请使用标准库 dataclass、StrEnum 或当前工程兼容的等价强类型结构。

顶层对象必须包含：

```text
schema_version
identity
compatibility
role
skill_binding
prompt_binding
workflow_template
context_sources
tool_permissions
assets
evaluation
runtime_contract
governance
audit
ext
```

### 5.1 Identity

必填：

```text
pack_id
name
domain
capability_type
version
owner
status
lifecycle
description
```

约束：

- `pack_id`：`^[a-z][a-z0-9_.-]*$`；
- `version`：基础 SemVer `MAJOR.MINOR.PATCH`；
- `status`：`DRAFT | CANDIDATE | ACTIVE | DEPRECATED | RETIRED | DISABLED`；
- `lifecycle`：`DESIGN | VALIDATION | PRODUCTION | MAINTENANCE | RETIRED`。

### 5.2 Compatibility

至少包括：

```text
novel_forge_min_version
novel_forge_max_version
protocol_min_version
protocol_max_version
required_capabilities
required_schema_versions
incompatible_packs
compatible_runtime_profiles
```

P0 必须真实校验 `required_capabilities`，通过现有 `default_capability_registry().resolve()` 完成。

### 5.3 Role

至少包括：

```text
role_type
role_name
responsibilities
boundaries
forbidden_actions
upstream_packs
downstream_packs
authority_level
```

`role_type`：

```text
AGENT | WORKER | REVIEWER | JUDGE | AUTHORITY | COORDINATOR
```

### 5.4 Skill Binding

每个 Skill 至少包括：

```text
skill_ref
version
content_hash
required
input_contract_ref
output_contract_ref
preconditions
postconditions
depends_on
max_invocations_per_run
drift_policy
```

同时包括：

```text
mode
anti_drift
```

要求：

- Skill ref 不得重复；
- dependency 必须存在；
- hash 必须是 SHA-256；
- `max_invocations_per_run > 0`；
- 动态选择必须有显式策略，否则 fail closed。

### 5.5 Prompt Binding

至少包括：

```text
prompt_bundle_type
system_instruction_hash
template_hash
compiler_version
input_schema_ref
output_schema_ref
```

P0 只保存 hash 和引用，不读取或保存 Prompt 正文。

### 5.6 Workflow Template

至少包括：

```text
workflow_id
workflow_version
execution_mode
idempotency_scope
nodes
completion
```

每个节点至少包括：

```text
node_id
operation_name
operation_definition_ref
handler_key
stage
capability_id
input_asset_types
output_asset_types
depends_on
retry_policy
timeout_policy_ref
approval
compensation
```

要求：

- node_id 唯一；
- capability 必须存在；
- depends_on 必须指向已存在节点；
- Workflow 必须是 DAG；
- completion terminal node 必须存在；
- `max_attempts > 0`。

请实现确定性的 DAG cycle detection，不要依赖第三方图包。

### 5.7 Context Sources

至少包括：

```text
policy_id
max_tokens
source_isolation
allowed_asset_types
forbidden_asset_types
required_version_refs
priority
freshness
longform_bindings
```

要求：

- `max_tokens > 0`；
- allowed / forbidden 不得交叉；
- `reject_cross_project` 必须为 true；
- `lifecycle=PRODUCTION` 时禁止 `RAW_ALLOWED_WITH_APPROVAL`；
- `chapter_generation_pack` 必须禁止：
  - `raw_source_document`
  - `raw_source_chunk`

### 5.8 Tool Permissions

至少包括：

```text
policy_id
default
tools
database
files
external_models
retrieval
```

每个工具至少包括：

```text
tool_ref
permission
allowed_operations
risk_class
approval_required
audit_required
budget_policy_ref
```

要求：

- `default` 必须为 `DENY`；
- HIGH / CRITICAL 风险必须 `audit_required=true`；
- P0 对 CRITICAL 风险要求 `approval_required=true`；
- 不允许 inline secret；
- 不允许含 `..` 的文件 root；
- 生产 Pack 不允许相对文件 root。

优先复用或参考 `production_execution.security.assert_no_inline_secrets`，不要复制出语义不一致的 Secret 规则。

### 5.9 Assets

至少包括：

```text
knowledge
rules
templates
source_policy
```

`source_policy` 至少包括：

```text
allowed_eligibility
raw_source_expression_allowed
requires_lineage
```

生产生成 Pack 必须：

```text
raw_source_expression_allowed=false
requires_lineage=true
```

### 5.10 Evaluation

至少包括：

```text
evaluation_id
required_gates
metrics
failure_policy
```

每个 Gate 至少包括：

```text
gate_id
judge_capability_id
blocking
threshold
required_evidence
```

Judge capability 必须能被现有 Capability Registry 解析。

### 5.11 Runtime Contract

至少包括：

```text
input_protocol_ref
output_protocol_ref
error_protocol_ref
state_protocol_ref
event_protocol_ref
audit_protocol_ref
rollback_protocol_ref
commit_policy_ref
validation_policy_ref
execution
```

`execution` 至少包括：

```text
binds_authority_operation
binds_attempt_fence
external_effects_allowed
synchronous_fixture_allowed
```

对 `lifecycle=PRODUCTION`：

- `binds_authority_operation` 必须为 true；
- 本轮生成/模型型 Pack 的 `binds_attempt_fence` 必须为 true；
- `synchronous_fixture_allowed` 必须为 false。

### 5.12 Governance / Audit

Governance 至少包括：

```text
release_channel
approval_policy_ref
versioning
rollout
rollback
cost_tracking
quality_tracking
deprecation
```

Audit 至少包括：

```text
audit_level
record_operation_snapshot
record_pack_manifest_hash
record_input_manifest
record_route_snapshot
record_tool_calls
record_cost_receipts
record_evaluation_results
```

### 5.13 Extensions

`ext` 必须是对象。

只允许命名空间式扩展，例如：

```text
ext.ui
ext.enterprise
ext.experiments
ext.vendor
```

扩展不得覆盖核心字段。

## 六、Manifest Hash

使用 canonical JSON：

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

计算 SHA-256，统一输出：

```text
sha256:<64 lowercase hex>
```

相同内容必须稳定生成相同 hash。

禁止将以下内容加入 manifest identity hash：

- 当前时间；
- 随机 UUID；
- 环境 secret；
- 本地绝对路径；
- 运行结果。

## 七、Loader 要求

建议接口：

```python
load_capability_pack(path: str | Path) -> CapabilityPackManifest
load_capability_pack_payload(payload: Mapping[str, Any]) -> CapabilityPackManifest
```

Loader 必须：

1. 只读取 UTF-8 JSON；
2. 限制文件大小，建议 1 MiB；
3. 拒绝非 object 根节点；
4. 拒绝无效 JSON；
5. 不访问网络；
6. 不读取环境变量；
7. 不展开任意外部 `$ref`；
8. 不自动修复输入。

## 八、Validator Report

Validator 不应只抛普通 `ValueError`。用户配置错误必须进入结构化结果。

建议：

```python
@dataclass(frozen=True, slots=True)
class CapabilityPackValidationIssue:
    code: str
    path: str
    message: str
    severity: str

@dataclass(frozen=True, slots=True)
class CapabilityPackValidationReport:
    ok: bool
    pack_id: str
    version: str
    manifest_hash: str
    errors: tuple[CapabilityPackValidationIssue, ...]
    warnings: tuple[CapabilityPackValidationIssue, ...]
    resolved_capabilities: tuple[str, ...]
```

最低错误码：

```text
CAPABILITY_PACK_SCHEMA_VERSION_UNSUPPORTED
CAPABILITY_PACK_IDENTITY_INVALID
CAPABILITY_PACK_CAPABILITY_UNKNOWN
CAPABILITY_PACK_HASH_INVALID
CAPABILITY_PACK_SKILL_DUPLICATE
CAPABILITY_PACK_SKILL_DEPENDENCY_UNKNOWN
CAPABILITY_PACK_WORKFLOW_NODE_DUPLICATE
CAPABILITY_PACK_WORKFLOW_DEPENDENCY_UNKNOWN
CAPABILITY_PACK_WORKFLOW_CYCLE
CAPABILITY_PACK_TOOL_DEFAULT_ALLOW_FORBIDDEN
CAPABILITY_PACK_HIGH_RISK_TOOL_AUDIT_REQUIRED
CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN
CAPABILITY_PACK_EVALUATION_CAPABILITY_UNKNOWN
CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED
CAPABILITY_PACK_EXTENSION_INVALID
CAPABILITY_PACK_JSON_INVALID
CAPABILITY_PACK_FILE_TOO_LARGE
```

程序错误可以抛异常；Pack 内容错误应尽可能收集多个 issue 后一次返回。

## 九、示例 Pack

新增：

```text
config/capability_packs/chapter_generation_pack.json
```

要求：

1. `schema_version=novelos.capability_pack.v1`；
2. status 使用 `CANDIDATE`；
3. lifecycle 使用 `VALIDATION`；
4. release channel 使用 `VALIDATION`；
5. 映射当前 Chapter Authority 18 节点，或在不重复大量内容的情况下完整覆盖节点引用；
6. capability_id 必须使用当前 `CapabilityId` 中真实存在的值；
7. raw source document / chunk 必须禁止；
8. Tool 默认 DENY；
9. HIGH 风险模型工具必须审计；
10. Runtime 必须绑定 Authority Operation / Attempt Fence；
11. 所有 hash 为有效 SHA-256；
12. 示例不得包含 secret、绝对路径或真实 Provider credential。

不要为了让示例通过而放宽 Validator。

## 十、测试要求

至少实现以下测试，名称可按当前风格调整，但覆盖不得减少：

```text
test_valid_chapter_generation_pack_passes
test_unsupported_schema_version_fails
test_invalid_pack_id_fails
test_invalid_semver_fails
test_unknown_capability_fails
test_invalid_hash_fails
test_duplicate_skill_fails
test_unknown_skill_dependency_fails
test_duplicate_workflow_node_fails
test_workflow_unknown_dependency_fails
test_workflow_cycle_fails
test_unknown_completion_terminal_node_fails
test_non_default_deny_tool_policy_fails
test_high_risk_tool_without_audit_fails
test_critical_tool_without_approval_fails
test_production_pack_with_raw_source_context_fails
test_allowed_and_forbidden_asset_overlap_fails
test_unknown_judge_capability_fails
test_runtime_contract_without_authority_binding_fails
test_manifest_hash_is_deterministic
test_loader_rejects_invalid_json
test_loader_rejects_non_object_root
test_loader_rejects_oversized_file
```

测试必须使用 `unittest`，遵循仓库 stdlib-first 约定。

## 十一、需要执行的验证

至少执行：

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_capability_pack_validator
PYTHONPATH=src python3 -m compileall -q src tests
```

然后根据当前仓库条件执行：

```bash
make architecture-manifests-check
make architecture-fitness-check
make head-integrity-check
```

如完整命令因环境前置条件无法执行，必须记录：

```text
NOT_EXECUTED
```

或：

```text
BLOCKED_PRECONDITION
```

并写明具体原因。不得伪造通过结果。

不要运行需要真实 Provider credential 的测试。

## 十二、实现质量要求

1. 代码必须有类型注解；
2. dataclass 尽量 `frozen=True, slots=True`，与当前工程风格一致；
3. 所有输入解析 fail closed；
4. 不接受隐式 bool、数字或字符串强制转换造成的歧义；
5. 不在 Validator 中使用全局可变状态；
6. 不读取网络或环境 secret；
7. 保持 canonical serialization 稳定；
8. 避免一个超大 `validator.py`，但也不要过度拆分；
9. 不加入与 P0 无关的抽象层、Repository、Service、Factory 或 Plugin Framework；
10. 不以 TODO、空方法或伪实现满足验收。

## 十三、完成报告

新增：

```text
docs/reports/capability-pack-p0-implementation-report.md
```

报告必须包括：

1. 日期、分支、实现前 HEAD、实现后 HEAD；
2. 变更文件清单；
3. 实现的协议字段；
4. Validator 规则；
5. 错误码清单；
6. 示例 Pack 摘要；
7. 测试命令和逐项结果；
8. 未执行或阻塞的测试；
9. 与产品设计或系统设计的偏差；
10. 明确未做事项；
11. P1 建议，但不要实现 P1；
12. 证据等级：

```text
protocol_schema_defined
static_validation_proven
fixture_manifest_validated
runtime_integrated=false
database_registry_implemented=false
real_provider_proven=false
longform_proven=false
multi_book_proven=false
production_verified=false
```

## 十四、最终验收标准

只有同时满足以下条件才算完成：

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

如果某项未满足，不要宣称完成。输出实际状态、阻塞原因和最小修复建议。

## 十五、最终回复格式

完成后按以下结构回复：

```text
1. 总体结论
2. 当前 HEAD 和变更范围
3. 新增/修改文件
4. 协议实现摘要
5. Validator 规则与错误码
6. 示例 Pack
7. 测试命令与真实结果
8. 未执行/阻塞项
9. 未做事项
10. P1 建议
11. 实现报告路径
```

不要只回复“已完成”。所有结论必须绑定代码、测试和文件路径。