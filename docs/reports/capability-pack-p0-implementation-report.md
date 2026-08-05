# Novel OS Capability Pack P0 实现报告

## 1. 实现身份

- 日期：2026-08-05
- 分支：`feat/v7-content-intelligence-and-longform-proof`
- 实现前 HEAD：`ee43c1f08de2b828a1e555cf52ada01a4803393b`
- 协议实现 HEAD：`f31cf254c0e7712692fa6975587eb952dd10cc09`
- 协议版本：`novelos.capability_pack.v1`
- 数据库迁移：未新增、未修改

本报告记录静态协议边界的实现证据。Capability Pack 未接入生产运行时，也未改变 Chapter Authority、ProductionExecutionGateway、Operation、Saga 或 Attempt 的行为。

## 2. 变更文件

- `src/novel_forge/modules/capability_packs/__init__.py`
- `src/novel_forge/modules/capability_packs/errors.py`
- `src/novel_forge/modules/capability_packs/schema.py`
- `src/novel_forge/modules/capability_packs/loader.py`
- `src/novel_forge/modules/capability_packs/validator.py`
- `config/capability_packs/chapter_generation_pack.json`
- `tests/unit/test_capability_pack_validator.py`
- `architecture/manifests/module-manifest.yaml`
- `docs/reports/capability-pack-p0-implementation-report.md`

## 3. 协议字段

实现了固定顶层合同：`schema_version`、`identity`、`compatibility`、`role`、`skill_binding`、`prompt_binding`、`workflow_template`、`context_sources`、`tool_permissions`、`assets`、`evaluation`、`runtime_contract`、`governance`、`audit`、`ext`。

协议对象使用 frozen/slots dataclass，嵌套 JSON 在加载后递归冻结；`to_dict()` 返回新的普通 JSON 对象。Manifest identity 使用 UTF-8 canonical JSON：`ensure_ascii=False`、`sort_keys=True`、`separators=(",", ":")`，输出 `sha256:<64 lowercase hex>`。有效示例的 hash 为：

`sha256:400519b51c1f9f01760c36b381365dca60284f8a619b77b50c1b5f50004b0018`

有效 Manifest 会拒绝运行/机器相关身份输入，包括时间字段、run/result 字段、生成 UUID、本机用户/临时目录绝对路径；inline secret 检测直接复用 `production_execution.security.assert_no_inline_secrets`。

Loader 仅接受 UTF-8 JSON object，不读取环境变量、不访问网络、不展开 `$ref`、不修复或强制转换 Python 输入。文件读取本身限制为 1 MiB + 1 byte，避免 stat/read 竞态绕过大小上限。

## 4. Validator 规则

- Identity：pack id、SemVer、状态、生命周期、P0 capability type catalog。
- Compatibility：`required_capabilities` 通过 `default_capability_registry().resolve(...)` 解析。
- Role：角色枚举、名称与 Authority level。
- Skill：唯一 ref、SHA-256、正数调用上限、依赖存在、静态/动态策略、禁止未绑定 Skill。
- Prompt：只接受引用、版本与 hash，不存 Prompt 正文。
- Workflow：18 节点静态 Operation contract、唯一节点、依赖存在、确定性 Kahn DAG 检测、terminal node、重试和类型合同。
- Context：正 token budget、allowed/forbidden 不交叉、cross-project fail closed、generation/raw-source 禁止与 source isolation。
- Tools：默认 DENY、严格权限/风险枚举、HIGH/CRITICAL audit、CRITICAL approval、路径穿越/生产相对路径拒绝、inline secret 拒绝。
- Assets：生成 Pack 禁止 raw source expression，并要求 lineage。
- Evaluation：Gate 类型/evidence 和 Judge Capability Registry 解析。
- Runtime：生成/生产 Pack 必须绑定 Authority Operation 与 Attempt Fence，且禁止 synchronous fixture。
- Governance/Audit/Extension：release channel、审计布尔合同、四个命名空间和禁止覆盖核心字段。
- 错误聚合：内容错误返回 frozen `CapabilityPackValidationReport`，尽可能一次收集多个错误；Loader 边界返回带结构化 issue 的 `CapabilityPackLoadError`。

## 5. 错误码

实现包含任务要求的全部最低错误码，并补充更细的 fail-closed 分类：

- `CAPABILITY_PACK_SCHEMA_VERSION_UNSUPPORTED`
- `CAPABILITY_PACK_IDENTITY_INVALID`
- `CAPABILITY_PACK_CAPABILITY_UNKNOWN`
- `CAPABILITY_PACK_HASH_INVALID`
- `CAPABILITY_PACK_SKILL_DUPLICATE`
- `CAPABILITY_PACK_SKILL_DEPENDENCY_UNKNOWN`
- `CAPABILITY_PACK_WORKFLOW_NODE_DUPLICATE`
- `CAPABILITY_PACK_WORKFLOW_DEPENDENCY_UNKNOWN`
- `CAPABILITY_PACK_WORKFLOW_CYCLE`
- `CAPABILITY_PACK_TOOL_DEFAULT_ALLOW_FORBIDDEN`
- `CAPABILITY_PACK_HIGH_RISK_TOOL_AUDIT_REQUIRED`
- `CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN`
- `CAPABILITY_PACK_EVALUATION_CAPABILITY_UNKNOWN`
- `CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED`
- `CAPABILITY_PACK_EXTENSION_INVALID`
- `CAPABILITY_PACK_JSON_INVALID`
- `CAPABILITY_PACK_FILE_TOO_LARGE`
- `CAPABILITY_PACK_PROTOCOL_INVALID`
- `CAPABILITY_PACK_REQUIRED_FIELD_MISSING`
- `CAPABILITY_PACK_ROLE_INVALID`
- `CAPABILITY_PACK_SKILL_POLICY_INVALID`
- `CAPABILITY_PACK_WORKFLOW_BINDING_UNKNOWN`
- `CAPABILITY_PACK_WORKFLOW_BINDING_INVALID`
- `CAPABILITY_PACK_WORKFLOW_RETRY_INVALID`
- `CAPABILITY_PACK_WORKFLOW_TERMINAL_UNKNOWN`
- `CAPABILITY_PACK_CONTEXT_POLICY_INVALID`
- `CAPABILITY_PACK_CONTEXT_ASSET_OVERLAP`
- `CAPABILITY_PACK_TOOL_POLICY_INVALID`
- `CAPABILITY_PACK_CRITICAL_TOOL_APPROVAL_REQUIRED`
- `CAPABILITY_PACK_FILE_ROOT_INVALID`
- `CAPABILITY_PACK_INLINE_SECRET_FORBIDDEN`
- `CAPABILITY_PACK_SOURCE_LINEAGE_REQUIRED`
- `CAPABILITY_PACK_EVALUATION_INVALID`
- `CAPABILITY_PACK_GOVERNANCE_INVALID`
- `CAPABILITY_PACK_AUDIT_INVALID`
- `CAPABILITY_PACK_MANIFEST_IDENTITY_VOLATILE`

## 6. `chapter_generation_pack` 示例

示例为 `CANDIDATE` / `VALIDATION` / release channel `VALIDATION`。它按当前 `ChapterNode` 顺序映射 18 节点，并绑定当前 operation name、definition version、handler key、stage、output asset type和 Scheduler 直接依赖图。全部 Capability ID 来自现有 Registry；验证结果为 11 个唯一已解析 Capability、0 error、0 warning。

示例明确禁止 `raw_source_document` 和 `raw_source_chunk`，工具默认 DENY，HIGH 模型工具要求审计；Runtime 声明 Authority Operation 与 Attempt Fence 绑定并禁止同步 fixture。示例不包含 Secret、本机路径或 Provider credential。

## 7. 测试与真实结果

| 命令 | 结果 | 证据 |
|---|---|---|
| `PYTHONPATH=src python3 -m unittest tests.unit.test_capability_pack_validator` | PASS，49 passed，0 failed，0 skipped，0.292s | Loader、协议、结构化报告、DAG、Registry、安全边界、18 节点 fixture |
| `PYTHONPATH=src python3 -m compileall -q src tests` | PASS，无输出 | Python 语法/字节码编译 |
| `make architecture-manifests-check` | PASS | 19 modules、67 migrations、11 workers、4 test collections、10 console scripts |
| `make architecture-fitness-check` | PASS，`violations=[]` | 架构依赖与 subordinate manifests |
| `make head-integrity-check` | PASS | 717 Python files，缺失/错误 import、export、registry target 均为 0 |
| `git diff --cached --check` | PASS | 暂存实现无 whitespace error |

测试未调用真实 Provider，也未要求 Provider credential。

## 8. 未执行或阻塞项

- 真实 Provider 测试：`NOT_EXECUTED`，明确超出 P0 范围。
- Runtime/Compose/数据库集成测试：`NOT_EXECUTED`，本轮没有 Runtime 或数据库集成。
- `ruff` 定点检查：`NOT_EXECUTED`，当前 `.venv` 未提供 ruff executable；指定 unittest、compileall 与三项架构门禁均已实际执行。
- 阻塞项：无。

## 9. 与设计文档和当前实现的差异

- 设计文档描述长期 Capability Pack Platform；本轮只实现 P0 Loader + static Validator，不实现 Registry、Resolver、Compiler、Runtime Binding、Canary 或 Migration。
- 当前 P0 capability type catalog 只开放设计示例实际使用的 `production_workflow`；未知类型既报错，又保守应用 generation 安全门禁，避免通过自由文本绕过 source/runtime policy。
- 当前 P0 Operation binding catalog 仅以公开 Chapter contract 固定 18 个 model-effect definitions。未来非 Chapter Pack 需要通用、受治理的 Operation Definition/handler catalog，不能复用本轮静态表冒充 Registry。
- Fixture 的依赖采用当前 `chapter_authority.scheduler` 的直接 admission dependencies，而不是把全部传递依赖重复写入 Manifest。
- 当前 Capability Registry 未为所有确定性协调节点提供一一对应的专用 Capability ID；这些节点使用现有真实且语义最接近的已注册 Capability，并由独立 Operation/handler 静态绑定防止身份漂移。没有因此改变 Runtime route。

## 10. 明确未做事项

- 未新增数据库表或迁移。
- 未接入 Chapter Authority 或 ProductionExecutionGateway Runtime。
- 未改变 18 节点顺序、Operation、Saga、Attempt、Fence 或 fail-closed 行为。
- 未新增 CLI、API、Web、第三方依赖或 Provider。
- 未实现 Pack Registry、Version Resolver、Compiler、Runtime Binding、Canary、Migration、Pack Run 或 Pack Attempt。
- 未宣称真实 Provider、长篇、多书或生产证明。

## 11. P1 建议（未实施）

1. 定义受治理的 Capability Type catalog 与每类安全 policy class。
2. 建立通用 Operation Definition/handler 只读目录，替代 P0 Chapter-only 静态绑定表。
3. 在保持现有 Authority 为唯一运行权威的前提下设计 Registry、Version Resolver 和 Compiler。
4. 增加签名、发布通道、兼容性解析、drift/revalidation 和 immutable version 治理。
5. 在独立 P1 任务中设计 Runtime Binding 与审计快照，不创建第二套 Operation/Attempt 状态机。

## 12. 证据状态与验收

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

static_validation_proven=true
fixture_manifest_validated=true
runtime_integrated=false
database_registry_implemented=false
real_provider_proven=false
longform_proven=false
multi_book_proven=false
production_verified=false
```

结论：Capability Pack P0 协议与静态校验最小闭环满足本轮验收；证据边界仍严格停留在静态协议、fixture 与单元测试层。
