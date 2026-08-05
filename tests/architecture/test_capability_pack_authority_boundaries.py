from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_capability_pack_authority_does_not_create_second_runtime_tables() -> None:
    migration = (
        ROOT
        / "src/novel_forge/storage/migrations/versions/"
        "v20260805_0071_capability_pack_authority.py"
    ).read_text(encoding="utf-8")
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
