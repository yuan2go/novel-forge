from __future__ import annotations

import psycopg
import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import (
    connect,
    seed_authority_project_book,
)
from tests.integration.capability_pack_postgres_support import (
    DATABASE_URL,
    PACK_PERMISSIONS,
    RELEASE_SHA,
    CapabilityPackPostgresHarness,
)


def test_postgres_scope_precedence_is_book_workspace_project_system() -> None:
    harness = CapabilityPackPostgresHarness("pack-scope")
    global_admin = Principal(
        principal_id=f"global-admin:{harness.project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset(PACK_PERMISSIONS),
        project_scope=frozenset({harness.project_id, "*"}),
        authentication_source="integration-fixture",
    )
    versions = []
    deployments = []
    for generation, scope_type in enumerate(
        ("SYSTEM", "PROJECT", "WORKSPACE", "BOOK"), start=1
    ):
        version = harness.register_compile_approve(
            f"1.{generation - 1}.0",
            generation=generation,
            owner_scope_type="SYSTEM",
        )
        deployment = harness.deploy(
            version,
            principal=global_admin if scope_type == "SYSTEM" else harness.compiler,
            scope_type=scope_type,
        )
        activation = harness.activate(
            deployment,
            principal=global_admin if scope_type == "SYSTEM" else harness.compiler,
        )
        assert activation["activation_version"] == 1
        versions.append(version)
        deployments.append(deployment)

    resolver = CapabilityPackRuntimeResolver(DATABASE_URL)
    expected = (
        ("BOOK", deployments[3]),
        ("WORKSPACE", deployments[2]),
        ("PROJECT", deployments[1]),
        ("SYSTEM", deployments[0]),
    )
    for scope_type, deployment in expected:
        snapshot = resolver.resolve_active_deployment(harness.resolution_request())
        assert snapshot.selected_scope_type.value == scope_type
        assert snapshot.deployment_id == deployment.deployment_id
        assert snapshot.binding_set_hash == deployment.binding_set_hash
        harness.execute(
            "capability_pack.deployment.disable",
            principal=(global_admin if scope_type == "SYSTEM" else harness.compiler),
            pack_version=deployment.pack.pack_version,
            deployment_id=deployment.deployment_id,
            payload={"environment": "development", "reason": "precedence proof"},
        )
    with pytest.raises(KernelError) as missing:
        resolver.resolve_active_deployment(harness.resolution_request())
    assert missing.value.code == "CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED"


def test_scope_membership_and_project_owned_system_leakage_fail_closed() -> None:
    harness = CapabilityPackPostgresHarness("pack-scope-guard")
    version = harness.register_compile_approve("1.0.0", generation=1)
    other_project = f"other-{harness.project_id}"
    other_workspace = f"other-{harness.workspace_id}"
    other_book = f"other-{harness.book_ids[0]}"
    seed_authority_project_book(
        project_id=other_project,
        workspace_id=other_workspace,
        book_id=other_book,
    )
    resolver = CapabilityPackRuntimeResolver(DATABASE_URL)
    with pytest.raises(KernelError) as wrong_membership:
        resolver.resolve_active_deployment(
            CapabilityPackResolutionRequest(
                project_id=harness.project_id,
                workspace_id=other_workspace,
                book_id=other_book,
                workflow_definition_ref="chapter_authority_slice@2.3.0",
                workflow_node_id="draft",
                environment="development",
                runtime_profile="development",
                release_channel="VALIDATION",
                release_sha=RELEASE_SHA,
                operation_definition_ref="chapter.draft.generate@2.3.0",
                pack_id=harness.pack_id,
            )
        )
    assert wrong_membership.value.code == "CAPABILITY_PACK_SCOPE_CONFLICT"
    with pytest.raises(ValueError, match="requires workspace_id"):
        CapabilityPackResolutionRequest(
            project_id=harness.project_id,
            workspace_id="",
            book_id=harness.book_ids[0],
            workflow_definition_ref="chapter_authority_slice@2.3.0",
            workflow_node_id="draft",
            environment="development",
            runtime_profile="development",
            release_channel="VALIDATION",
            release_sha=RELEASE_SHA,
            operation_definition_ref="chapter.draft.generate@2.3.0",
            pack_id=harness.pack_id,
        )

    global_admin = Principal(
        principal_id=f"global-admin:{harness.project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset(PACK_PERMISSIONS),
        project_scope=frozenset({harness.project_id, "*"}),
        authentication_source="integration-fixture",
    )
    with pytest.raises(Exception) as project_pack_system_deployment:
        harness.deploy(version, principal=global_admin, scope_type="SYSTEM")
    assert "Deployment does not belong" in str(project_pack_system_deployment.value)


def test_postgres_rejects_same_scope_activation_ambiguity() -> None:
    harness = CapabilityPackPostgresHarness("pack-scope-ambiguity")
    version = harness.register_compile_approve("1.0.0", generation=1)
    deployment = harness.deploy(version)
    harness.activate(deployment)
    with connect() as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg.IntegrityError):
            cursor.execute(
                """
                INSERT INTO authority_capability_pack_activation(
                    activation_key, scope_key, target_scope_type, project_id,
                    workspace_id, book_id, environment,
                    workflow_definition_ref, pack_id, active_deployment_id,
                    activation_version, reason, activated_by,
                    activated_by_operation_id
                )
                SELECT activation_key, scope_key, target_scope_type, project_id,
                       workspace_id, book_id, environment,
                       workflow_definition_ref, pack_id, active_deployment_id,
                       activation_version, 'ambiguous duplicate',
                       'sql-attacker', activated_by_operation_id
                FROM authority_capability_pack_activation
                WHERE pack_id=%s
                """,
                [harness.pack_id],
            )
            connection.commit()
        connection.rollback()
