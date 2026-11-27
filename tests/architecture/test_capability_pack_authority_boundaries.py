from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_capability_pack_authority_does_not_create_second_runtime_tables() -> None:
    migration_root = ROOT / "src/novel_forge/storage/migrations/versions"
    migration = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            migration_root / "v20260805_0071_capability_pack_authority.py",
            migration_root
            / "v20260806_0072_capability_pack_integrity_hardening.py",
        )
    )
    forbidden = (
        "authority_capability_pack_run",
        "authority_capability_pack_attempt",
        "authority_capability_pack_lease",
        "authority_capability_pack_fence",
        "authority_capability_pack_worker",
        "authority_capability_pack_external_effect",
    )
    for table in forbidden:
        assert f"CREATE TABLE {table}" not in migration


def test_controlled_runtime_rejects_inline_pack_binding_authority() -> None:
    application = (
        ROOT / "src/novel_forge/modules/agent_runtime/application.py"
    ).read_text(encoding="utf-8")
    assert "CAPABILITY_PACK_DEPLOYMENT_REQUIRED" in application
    assert "CAPABILITY_PACK_LEGACY_MODE_REQUIRED" in application
    assert "DEVELOPMENT_FIXTURE" in application


def test_production_pack_authority_has_no_local_storage_import() -> None:
    roots = (
        ROOT / "src/novel_forge/modules/capability_pack_authority",
        ROOT / "src/novel_forge/api/routers/capability_pack_authority.py",
        ROOT / "src/novel_forge/storage/capability_pack_authority_repositories.py",
    )
    for root in roots:
        paths = root.rglob("*.py") if root.is_dir() else (root,)
        for path in paths:
            assert "novel_forge.storage.local" not in path.read_text(encoding="utf-8")


def test_attempt_pack_snapshot_has_one_resolution_and_shared_consumers() -> None:
    migration = (
        ROOT
        / "src/novel_forge/storage/migrations/versions/"
        "v20260806_0072_capability_pack_integrity_hardening.py"
    ).read_text(encoding="utf-8")
    runtime = (
        ROOT / "src/novel_forge/modules/capability_pack_authority/runtime.py"
    ).read_text(encoding="utf-8")
    gateway = (
        ROOT / "src/novel_forge/modules/chapter_authority/execution_gateway.py"
    ).read_text(encoding="utf-8")
    binding = (
        ROOT / "src/novel_forge/modules/agent_runtime/chapter_binding.py"
    ).read_text(encoding="utf-8")
    assert "attempt_id TEXT NOT NULL UNIQUE" in migration
    assert "resolution_count SMALLINT NOT NULL DEFAULT 1" in migration
    assert "CHECK (resolution_count=1)" in migration
    assert "snapshot_creation_fencing_token BIGINT NOT NULL" in migration
    assert "trace_id TEXT NOT NULL" in migration
    assert "span_id TEXT NOT NULL" in migration
    assert gateway.count("freeze_attempt_snapshot(") == 1
    assert "resolve_active_deployment(" not in gateway
    assert "resolve_active_deployment(" not in binding
    assert "execution_binding.capability_pack_attempt_snapshot" in binding
    freeze_method = runtime[
        runtime.index("def freeze_attempt_snapshot(") : runtime.index(
            "def validate_runtime_admission("
        )
    ]
    assert freeze_method.index("find_attempt_snapshot(") < freeze_method.index(
        "resolve_in_uow("
    )


def test_rollout_approval_dependency_and_ownership_fitness_rules_are_closed() -> None:
    runtime = (
        ROOT / "src/novel_forge/modules/capability_pack_authority/runtime.py"
    ).read_text(encoding="utf-8")
    application = (
        ROOT / "src/novel_forge/modules/capability_pack_authority/application.py"
    ).read_text(encoding="utf-8")
    repository = (
        ROOT / "src/novel_forge/storage/capability_pack_authority_repositories.py"
    ).read_text(encoding="utf-8")
    policy = (
        ROOT / "src/novel_forge/modules/capability_pack_authority/policy.py"
    ).read_text(encoding="utf-8")
    migration_71 = (
        ROOT
        / "src/novel_forge/storage/migrations/versions/"
        "v20260805_0071_capability_pack_authority.py"
    ).read_text(encoding="utf-8")
    migration = (
        ROOT
        / "src/novel_forge/storage/migrations/versions/"
        "v20260806_0072_capability_pack_integrity_hardening.py"
    ).read_text(encoding="utf-8")
    query = (
        ROOT / "src/novel_forge/modules/capability_pack_authority/query.py"
    ).read_text(encoding="utf-8")
    assert "RolloutStatus.COMPLETED" not in runtime
    assert "complete_rollout(" in application and "activate_deployment_cas(" in repository
    assert "CapabilityPackApprovalScope.from_payload" in application
    authorization = (
        ROOT / "src/novel_forge/modules/capability_pack_authority/validation_admission.py"
    ).read_text(encoding="utf-8")
    assert "require_deployment_authorization(" in runtime
    assert "CapabilityPackApprovalScope.from_payload" in authorization
    assert "authority_agent_runtime_pack_integrity_fact_guard" in migration
    assert '"authority_capability_pack_assignment",' in migration_71
    assert "owner_scope_type" in migration and "owner_project_id" in migration
    assert "authority_capability_pack_dependency" in migration
    assert "is_floating_version" in repository
    assert "blocked_dependencies(" in repository
    assert "CAPABILITY_PACK_DEPENDENCY_ADMISSION_BLOCKED" in runtime
    assert "authority.capability_pack.attempt_snapshot.frozen" in repository
    assert "_SCOPE_KEYS" in policy
    assert '"real_provider_proven"' not in query
    assert '"provider_vertical_qualification_status"' in query
