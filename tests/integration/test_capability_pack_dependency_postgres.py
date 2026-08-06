from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest

from novel_forge.modules.capability_pack_authority.query import (
    CapabilityPackAuthorityQuery,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import connect
from tests.integration.capability_pack_postgres_support import (
    DATABASE_URL,
    RELEASE_SHA,
    CapabilityPackPostgresHarness,
)


def _register_dependency(
    harness: CapabilityPackPostgresHarness,
    *,
    pack_id: str,
    version: str = "1.0.0",
    approve: bool = False,
) -> dict[str, str]:
    manifest, catalog = harness.build_version_payload(version, generation=1)
    manifest["identity"]["pack_id"] = pack_id
    manifest["identity"]["name"] = f"Dependency {pack_id}"
    result = harness.execute(
        "capability_pack.manifest.register",
        principal=harness.compiler,
        pack_id=pack_id,
        pack_version=version,
        payload={
            "manifest": manifest,
            "artifact_catalog": catalog,
            "release_channel": "VALIDATION",
            "owner_scope_type": "PROJECT",
            "owner_project_id": harness.project_id,
            "dependencies": [],
        },
    )
    dependency = {
        "pack_id": pack_id,
        "version": version,
        "manifest_hash": str(result["manifest_hash"]),
        "dependency_type": "REQUIRED",
    }
    if approve:
        compilation_id = f"dependency-compilation:{uuid4()}"
        compilation = harness.execute(
            "capability_pack.compile",
            principal=harness.compiler,
            pack_id=pack_id,
            pack_version=version,
            compilation_id=compilation_id,
            payload={
                "target_runtime_profile": "development",
                "novel_forge_version": "6.0.0",
                "release_sha": RELEASE_SHA,
                "release_channel": "VALIDATION",
            },
        )
        harness.execute(
            "capability_pack.approval.decide",
            principal=harness.approver,
            pack_id=pack_id,
            pack_version=version,
            compilation_id=compilation_id,
            payload={
                "compilation_hash": compilation["compilation_hash"],
                "decision": "APPROVED",
                "approval_policy_ref": "capability-pack-approval-scope:v1",
                "scope": harness.approval_scope(),
                "reason": "dependency approval fixture",
                "evidence_refs": ["test:dependency-revocation"],
                "enforce_duties_separation": True,
            },
        )
        dependency["compilation_id"] = compilation_id
    return dependency


def test_exact_dependency_registration_and_compilation_freeze() -> None:
    harness = CapabilityPackPostgresHarness("pack-dependency")
    dependency = _register_dependency(
        harness, pack_id=f"dependency-{uuid4().hex}"
    )
    root = harness.register_compile_approve(
        "1.0.0", generation=1, dependencies=(dependency,)
    )
    snapshot = dict(root.compiled["version_resolution_snapshot"])
    dependency_ref = f"{dependency['pack_id']}@{dependency['version']}"
    root_ref = f"{harness.pack_id}@1.0.0"
    assert snapshot["dependency_order"] == [dependency_ref, root_ref]
    assert snapshot["dependency_edges"] == [[root_ref, dependency_ref]]
    assert [dependency_ref, dependency["manifest_hash"]] in snapshot[
        "manifest_hashes"
    ]
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT dependency_pack_id, dependency_pack_version,
                   dependency_manifest_hash, dependency_type
            FROM authority_capability_pack_dependency
            WHERE pack_id=%s AND pack_version='1.0.0'
            """,
            [harness.pack_id],
        )
        assert cursor.fetchone() == (
            dependency["pack_id"],
            dependency["version"],
            dependency["manifest_hash"],
            "REQUIRED",
        )

    deployment = harness.deploy(root)
    harness.activate(deployment)
    harness.execute(
        "capability_pack.retire",
        principal=harness.compiler,
        pack_id=dependency["pack_id"],
        pack_version=dependency["version"],
        payload={
            "environment": "development",
            "reason": "dependency retirement fixture",
            "migration_required": True,
            "migration_policy_ref": "migration:dependency:v1",
        },
    )
    drift = CapabilityPackAuthorityQuery(
        DATABASE_URL, current_release_sha=RELEASE_SHA
    ).drift_report(deployment.deployment_id, project_id=harness.project_id)
    assert drift["classification"] == "NEW_ADMISSION_BLOCKED"
    assert drift["dependency_admission_status"] == "NEW_ADMISSION_BLOCKED"
    assert drift["dependency_drift"] == [dependency_ref]
    with pytest.raises(KernelError) as blocked_runtime:
        CapabilityPackRuntimeResolver(DATABASE_URL).resolve_active_deployment(
            harness.resolution_request()
        )
    assert (
        blocked_runtime.value.code
        == "CAPABILITY_PACK_DEPENDENCY_ADMISSION_BLOCKED"
    )


def test_dependency_revocation_blocks_drift_and_new_runtime_admission() -> None:
    harness = CapabilityPackPostgresHarness("pack-dependency-revoked")
    dependency = _register_dependency(
        harness,
        pack_id=f"dependency-{uuid4().hex}",
        approve=True,
    )
    dependency_compilation_id = dependency.pop("compilation_id")
    root = harness.register_compile_approve(
        "1.0.0", generation=1, dependencies=(dependency,)
    )
    deployment = harness.deploy(root)
    harness.activate(deployment)
    harness.execute(
        "capability_pack.revoke",
        principal=harness.approver,
        pack_id=dependency["pack_id"],
        pack_version=dependency["version"],
        compilation_id=dependency_compilation_id,
        payload={"reason": "dependency revocation fixture"},
    )
    dependency_ref = f"{dependency['pack_id']}@{dependency['version']}"
    drift = CapabilityPackAuthorityQuery(
        DATABASE_URL, current_release_sha=RELEASE_SHA
    ).drift_report(deployment.deployment_id, project_id=harness.project_id)
    assert drift["classification"] == "NEW_ADMISSION_BLOCKED"
    assert drift["dependency_drift"] == [dependency_ref]
    with pytest.raises(KernelError) as blocked_runtime:
        CapabilityPackRuntimeResolver(DATABASE_URL).resolve_active_deployment(
            harness.resolution_request()
        )
    assert (
        blocked_runtime.value.code
        == "CAPABILITY_PACK_DEPENDENCY_ADMISSION_BLOCKED"
    )


def test_dependency_protocol_rejects_floating_duplicate_unregistered_and_incompatible() -> None:
    harness = CapabilityPackPostgresHarness("pack-dependency-invalid")
    dependency = _register_dependency(
        harness, pack_id=f"dependency-{uuid4().hex}"
    )
    manifest, catalog = harness.build_version_payload(
        "1.0.0", generation=1, dependencies=(dependency,)
    )

    floating = {**dependency, "version": "latest"}
    with pytest.raises(KernelError) as floating_error:
        harness.execute(
            "capability_pack.manifest.register",
            principal=harness.compiler,
            pack_version="1.0.0",
            payload={
                "manifest": manifest,
                "artifact_catalog": catalog,
                "release_channel": "VALIDATION",
                "dependencies": [floating],
            },
        )
    assert floating_error.value.code == "CAPABILITY_PACK_DEPENDENCY_VERSION_INVALID"

    duplicate = {**dependency, "version": "2.0.0"}
    with pytest.raises(KernelError) as duplicate_error:
        harness.execute(
            "capability_pack.manifest.register",
            principal=harness.compiler,
            pack_version="1.0.0",
            payload={
                "manifest": manifest,
                "artifact_catalog": catalog,
                "release_channel": "VALIDATION",
                "dependencies": [dependency, duplicate],
            },
        )
    assert duplicate_error.value.code == "CAPABILITY_PACK_DEPENDENCY_DUPLICATE"

    missing = {
        "pack_id": f"missing-{uuid4().hex}",
        "version": "1.0.0",
        "manifest_hash": "sha256:" + "a" * 64,
        "dependency_type": "REQUIRED",
    }
    missing_manifest = deepcopy(manifest)
    missing_manifest["role"]["upstream_packs"] = [missing["pack_id"]]
    with pytest.raises(KernelError) as missing_error:
        harness.execute(
            "capability_pack.manifest.register",
            principal=harness.compiler,
            pack_version="1.0.0",
            payload={
                "manifest": missing_manifest,
                "artifact_catalog": catalog,
                "release_channel": "VALIDATION",
                "dependencies": [missing],
            },
        )
    assert missing_error.value.code == "CAPABILITY_PACK_VERSION_NOT_FOUND"

    incompatible_manifest = deepcopy(manifest)
    incompatible_manifest["compatibility"]["incompatible_packs"] = [
        dependency["pack_id"]
    ]
    with pytest.raises(KernelError) as incompatible_error:
        harness.execute(
            "capability_pack.manifest.register",
            principal=harness.compiler,
            pack_version="1.0.0",
            payload={
                "manifest": incompatible_manifest,
                "artifact_catalog": catalog,
                "release_channel": "VALIDATION",
                "dependencies": [dependency],
            },
        )
    assert incompatible_error.value.code == "CAPABILITY_PACK_DEPENDENCY_INCOMPATIBLE"


def test_dependency_database_rejects_cycles_and_cross_project_namespace() -> None:
    harness = CapabilityPackPostgresHarness("pack-dependency-cycle")
    dependency = _register_dependency(
        harness, pack_id=f"dependency-{uuid4().hex}"
    )
    root = harness.register_compile_approve(
        "1.0.0", generation=1, dependencies=(dependency,)
    )
    with connect() as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg.IntegrityError):
            cursor.execute(
                """
                INSERT INTO authority_capability_pack_dependency(
                    pack_id, pack_version, dependency_pack_id,
                    dependency_pack_version, dependency_manifest_hash,
                    dependency_type, created_by_operation_id
                )
                SELECT %s, '1.0.0', %s, '1.0.0', %s, 'REQUIRED',
                       registered_by_operation_id
                FROM authority_capability_pack_version
                WHERE pack_id=%s AND pack_version='1.0.0'
                """,
                [
                    dependency["pack_id"],
                    harness.pack_id,
                    root.manifest_hash,
                    dependency["pack_id"],
                ],
            )
            connection.commit()
        connection.rollback()

    other = CapabilityPackPostgresHarness("pack-dependency-other-project")
    other_dependency = _register_dependency(
        other, pack_id=f"dependency-{uuid4().hex}"
    )
    manifest, catalog = harness.build_version_payload(
        "2.0.0", generation=2, dependencies=(other_dependency,)
    )
    with pytest.raises(psycopg.IntegrityError):
        harness.execute(
            "capability_pack.manifest.register",
            principal=harness.compiler,
            pack_version="2.0.0",
            payload={
                "manifest": manifest,
                "artifact_catalog": catalog,
                "release_channel": "VALIDATION",
                "dependencies": [other_dependency],
            },
        )
