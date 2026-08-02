# AC-00 仓库与 HEAD 完整性

状态：`PLANNED`  
阶段：Phase 0 / Trusted Baseline  
前置依赖：无  
阻塞范围：AC-01 至 AC-19 的实现与验收

## 1. ADR

### 背景

2026-08-01 远程审计发现，Authority API、migration registry、console scripts 和测试清单引用了部分在同一审计 HEAD 下无法通过内容接口解析的模块、迁移和测试文件。由于未获得完整本地 checkout，也未在同一 SHA 上运行构建和测试，当前必须把仓库完整性视为未验证。

### 决策

任何 Architecture Closure 开发必须从一个“可完整 checkout、可导入、可迁移、可启动、可测试”的唯一 SHA 开始。CI 必须验证引用清单与实际文件一致，不允许通过历史测试结果、工作树未提交文件或不同 SHA 拼接当前基线。

### 替代方案及拒绝理由

- 继续功能开发后再统一修复：会扩大悬空 import、migration 和 worker surface。
- 只运行 `make test`：测试发现机制可能漏掉不存在的显式测试模式，且不能验证部署入口。
- 只依赖 GitHub 代码搜索：不能替代真实 checkout、Python import 和 migration execution。

### 后果

AC-00 完成前，其他工作包可以继续设计，但不得宣称实现、迁移或当前 SHA 验证完成。

## 2. 实施范围

### 2.1 建立完整性清单

新增机器可读清单：

```text
architecture/manifests/python-modules.yaml
architecture/manifests/api-entrypoints.yaml
architecture/manifests/workers.yaml
architecture/manifests/migrations.yaml
architecture/manifests/tests.yaml
architecture/manifests/console-scripts.yaml
architecture/manifests/deployment-units.yaml
```

每项至少包含：`name`、`path`、`import_path`、`entrypoint`、`authority_mode`、`required_env`、`tests`、`deployment_unit`、`owner`。

### 2.2 静态引用核验

扫描：

- `pyproject.toml` console scripts；
- `src/novel_forge/api/*.py` router/import；
- `src/novel_forge/storage/migrations/versions/__init__.py`；
- `Makefile` 目标；
- `.github/workflows/*.yml` 测试路径；
- `docker-compose.yml` 和 `Dockerfile` command；
- `scripts/run_*tests.py` 显式测试模式；
- Worker module 与部署单元映射。

### 2.3 同一 SHA 验证

所有验证输出必须记录：

```text
repository
branch
commit_sha
working_tree_clean
python_version
node_version
postgres_version
container_image_digest
started_at
completed_at
```

执行顺序：import → compile → migration chain → unit → PostgreSQL integration → API boot → workers boot → web build → compose smoke。

### 2.4 防止空测试通过

显式测试 runner 必须声明 expected test count 或 minimum count。发现 0 个测试时必须失败，不能把“pytest/unittest 返回成功但未收集目标测试”当作通过。

## 3. 代码位置

### 当前重点核验

- `pyproject.toml`
- `Makefile`
- `Dockerfile`
- `docker-compose.yml`
- `.github/workflows/core-os-ci.yml`
- `src/novel_forge/api/app.py`
- `src/novel_forge/api/authority_app.py`
- `src/novel_forge/api/legacy_app.py`
- `src/novel_forge/api/authority_dependencies.py`
- `src/novel_forge/cli/__init__.py`
- `src/novel_forge/workers/`
- `src/novel_forge/storage/migrations/versions/`
- `scripts/run_authority_postgres_tests.py`
- `tests/unit/`、`tests/integration/`、`tests/acceptance/`

### 目标新增

- `scripts/architecture/check_repository_integrity.py`
- `scripts/architecture/check_manifest_references.py`
- `scripts/architecture/check_test_collection.py`
- `scripts/architecture/check_entrypoint_boot.py`
- `tests/architecture/test_repository_manifest.py`
- `tests/architecture/test_migration_registry_integrity.py`
- `tests/architecture/test_console_script_integrity.py`

### 禁止位置

不得在业务模块中加入临时 `try/except ImportError` 来掩盖缺失文件；不得以运行时动态 import 代替清单修复。

## 4. 迁移脚本设计

本工作包原则上不新增业务表。若需要保存构建证明，可新增独立的 build evidence migration，但应优先使用 CI artifact 和 release manifest，避免把 CI 日志写入业务数据库。

需要新增的非 SQL 脚本：

```text
scripts/architecture/build_head_manifest.py
scripts/architecture/verify_head_manifest.py
scripts/architecture/verify_current_sha.sh
```

`build_head_manifest.py` 生成文件路径、blob hash、migration chain、entrypoint 和 test inventory。`verify_head_manifest.py` 对当前 checkout 复核。脚本必须 fail closed。

## 5. 实施计划

1. 导出当前 branch 完整文件树和 import graph。
2. 修复悬空 import、未提交文件、错误 migration registry 和错误 console script。
3. 为每个 worker 建立 manifest 与最小 boot test。
4. 为显式测试 runner 增加 collection count 断言。
5. 在 CI 增加 `repository-integrity` 独立 job，并作为其他 Authority jobs 的前置依赖。
6. 生成当前 SHA 验证报告，更新 `docs/project-current-state.md`。

## 6. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Manifest unit | 清单解析与重复 key | 无重复、无缺失字段 |
| Import architecture | 遍历所有声明模块 | 全部可 import |
| Migration registry | registry 与文件树对比 | 无悬空、无遗漏、唯一 head |
| Console script | 加载所有 entrypoint | callable 存在且签名有效 |
| Test collection | 每个显式 pattern | 收集数达到声明下限 |
| API boot | Legacy 与 Authority 配置 | 预期模式启动；错误模式 fail closed |
| Worker boot | 每个 worker | 完成依赖装配并进入健康状态 |
| Web build | 当前 lockfile | build/type/lint 通过 |
| Compose smoke | Authority-only 配置 | 无 Legacy workspace 也可启动 |
| Negative | 删除清单中的文件 | CI 必须失败 |

## 7. Acceptance Gate

必须全部满足：

```text
head_integrity_verified=true
current_head_checkout_verified=true
current_head_import_verified=true
current_head_test_collection_verified=true
current_head_migration_chain_verified=true
current_head_api_boot_verified=true
current_head_worker_boot_verified=true
current_head_web_build_verified=true
```

Gate 证据必须包含唯一 commit SHA、CI run、命令清单和测试数量。任何一项使用历史 SHA 或未提交工作树均视为未通过。

## 8. 风险与控制

- 私有仓库连接器索引不一致：以本地 git tree、GitHub tree API 和 CI checkout 三方交叉验证。
- 测试数量频繁变化：清单记录最低数量与关键测试名称，不仅记录总数。
- 动态插件无法静态发现：插件必须注册 manifest，禁止隐式目录扫描成为生产依赖。
- 修复过程中混入功能变更：AC-00 PR 只允许完整性、入口和测试发现修复。