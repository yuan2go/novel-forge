
import pytest
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_authority import (
    SourceAuthorityApplication,
    SourceAuthorityScheduler,
)
from novel_forge.modules.source_authority.public_catalog import CatalogCapture
from novel_forge.modules.source_authority.public_catalog_adapter import (
    PublicCatalogAdapter,
)
from novel_forge.modules.source_authority.public_catalog_application import (
    CatalogCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    identifier,
    transaction,
)
from tests.unit.test_public_catalog import Transport, URL


def setup_scope():
    project, workspace = identifier("catalog"), identifier("workspace")
    principal = Principal(
        principal_id="catalog-operator",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"source.authority.execute", "source.authority.query"}),
        project_scope=frozenset({project}),
        authentication_source="integration-test",
    )
    ProjectAuthorityApplication(
        DATABASE_URL, application_build_id="catalog-check", commit_sha="e" * 40
    ).execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=project,
            workspace_id=workspace,
            actor_id=principal.principal_id,
            idempotency_key="create:" + project,
            trace_id="trace:" + project,
            correlation_id=project,
            payload={"title": "Synthetic catalog test"},
        )
    )
    app = SourceAuthorityApplication(
        DATABASE_URL, application_build_id="catalog-check", commit_sha="e" * 40
    )
    return project, workspace, principal, app


def test_native_snapshot_replay_scope_and_failure_receipts(tmp_path):
    project, workspace, principal, app = setup_scope()
    transport = Transport()
    app.public_catalog._adapter = PublicCatalogAdapter(tmp_path, transport=transport)
    command = CatalogCommand(
        project_id=project,
        workspace_id=workspace,
        idempotency_key="synthetic-capture",
        actor_id=principal.principal_id,
        capture=CatalogCapture(platform="qidian", url=URL),
        trace_id="trace:catalog",
        correlation_id="catalog",
    )
    admitted = app.admit_catalog(command, principal=principal)
    scheduler = SourceAuthorityScheduler(app)
    result = scheduler.run_or_recover(
        operation_id=admitted["operation_id"], project_id=project
    )
    assert result["status"] == "SUCCEEDED"
    assert result["snapshot"]["records"][0]["metric_value"] is None
    assert result["snapshot"]["generation_context_allowed"] is False
    assert scheduler.run_or_recover(
        operation_id=admitted["operation_id"], project_id=project
    )["replayed"]
    assert app.admit_catalog(command, principal=principal)["replayed"]
    assert transport.calls == 1
    page = app.public_catalog.works(
        project_id=project, snapshot_id=result["asset_version_id"], category="仙侠"
    )
    assert len(page["items"]) == 1
    with pytest.raises(KernelError, match="SNAPSHOT_NOT_FOUND"):
        app.public_catalog.works(
            project_id="another-project", snapshot_id=result["asset_version_id"]
        )
    with transaction() as connection:
        rows = connection.execute(
            "SELECT status,count(*) FROM authority_external_effect WHERE operation_id=%s GROUP BY status",
            [admitted["operation_id"]],
        ).fetchall()
        assert rows == [("SUCCEEDED", 1)]
        outputs = connection.execute(
            "SELECT count(*) FROM authority_operation_output_asset WHERE operation_id=%s",
            [admitted["operation_id"]],
        ).fetchone()[0]
        assert outputs == 1


def test_native_http_challenge_is_failed_task_not_empty_success(tmp_path):
    project, workspace, principal, app = setup_scope()
    transport = Transport(status=202, body=b'<script src="/probe.js"></script>')
    app.public_catalog._adapter = PublicCatalogAdapter(tmp_path, transport=transport)
    admitted = app.admit_catalog(
        CatalogCommand(
            project_id=project,
            workspace_id=workspace,
            idempotency_key="blocked-capture",
            actor_id=principal.principal_id,
            capture=CatalogCapture(platform="qidian", url=URL),
            trace_id="trace:blocked",
            correlation_id="blocked",
        ),
        principal=principal,
    )
    with pytest.raises(KernelError, match="CAPTURE_FAILED_FINAL"):
        SourceAuthorityScheduler(app).run_or_recover(
            operation_id=admitted["operation_id"], project_id=project
        )
    result = app.public_catalog.result(admitted["operation_id"], project, replayed=True)
    assert result["status"] == "FAILED_FINAL"
    assert result["snapshot"] is None
    assert transport.calls == 1
