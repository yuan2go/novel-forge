from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
    selected_template,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def require_current_reader_template(cursor, *, project_id: str, book_id: str) -> None:
    template = selected_book_template(
        cursor, project_id=project_id, book_id=book_id, allow_literary_required=True
    )
    selected = (
        selected_template(template["policy_snapshot"]["policy"], book_id)
        if template
        else None
    )
    if not selected or selected.get("version") not in {"creative-execution-template.v11", "creative-execution-template.v12"}:
        raise KernelError(
            "READER_CURRENT_TEMPLATE_REQUIRED",
            "Current Reader requires the exact frozen coordinated Book template",
        )


def ensure_creation_reader_pack(
    settings: Any, args: Any, *, principal: Any, build_id: str, sha: str, pack_id: str
) -> dict[str, Any]:
    from novel_forge.modules.capability_packs.longform_profiles import (
        build_reader_outcome_pack_profile,
    )
    from novel_forge.modules.capability_packs.validation_deployment import (
        install_longform_validation_pack,
        register_validation_runtime_definitions,
    )

    principal.require("book.authority.execute", args.project_id)
    with AuthorityUnitOfWork(settings.database_url) as uow:
        require_current_reader_template(
            uow.cursor, project_id=args.project_id, book_id=args.book_id
        )
    hashes = register_validation_runtime_definitions(
        settings.database_url, application_build_id=build_id, commit_sha=sha
    )
    profile = build_reader_outcome_pack_profile(
        args.repository_root,
        operation_definition_hash=hashes["reader_proxy_current"],
        pack_id=pack_id,
        coordinated_contract=True,
    )
    from novel_forge.modules.capability_pack_authority.domain import canonical_hash
    from novel_forge.modules.capability_pack_authority.application import (
        _normalized_artifact_catalog,
    )

    with AuthorityUnitOfWork(settings.database_url) as uow:
        require_current_reader_template(
            uow.cursor, project_id=args.project_id, book_id=args.book_id
        )
        uow.cursor.execute(
            """SELECT activation.activation_version,deployment.deployment_id,deployment.pack_version,
            deployment.deployment_status,compilation.release_sha,version.manifest_hash,version.artifact_catalog_hash
            FROM authority_capability_pack_activation activation
            JOIN authority_capability_pack_deployment deployment ON deployment.deployment_id=activation.active_deployment_id
            JOIN authority_capability_pack_compilation compilation USING(compilation_id)
            JOIN authority_capability_pack_version version ON version.pack_id=deployment.pack_id AND version.pack_version=deployment.pack_version
            WHERE activation.project_id=%s AND activation.workspace_id=%s AND activation.book_id=%s
              AND activation.target_scope_type='BOOK' AND activation.environment=%s
              AND activation.workflow_definition_ref=%s AND activation.pack_id=%s FOR SHARE OF activation,deployment""",
            [
                args.project_id,
                args.workspace_id,
                args.book_id,
                settings.environment,
                profile.workflow_ref,
                pack_id,
            ],
        )
        active = uow.cursor.fetchone()
        if active and active[3] == "ACTIVE" and active[4] == sha:
            profile.manifest["identity"]["version"] = active[2]
            if (active[5], active[6]) != (canonical_hash(profile.manifest), canonical_hash(_normalized_artifact_catalog(profile.artifact_catalog))):
                raise KernelError("READER_CURRENT_DEPLOYMENT_DRIFT", "Current release Reader deployment differs from its frozen manifest/catalog")
            return {"pack_id": pack_id, "pack_version": active[2], "deployment_id": active[1],
                "activation_version": active[0], "replayed": True}
    version = "1.6." + str(100000 + int(sha[:8], 16))
    return install_longform_validation_pack(
        settings.database_url,
        profile=profile,
        pack_version=version,
        agent_generation=1,
        expected_activation_version=int(active[0]) if active else 0,
        project_id=args.project_id,
        workspace_id=args.workspace_id,
        book_id=args.book_id,
        application_build_id=build_id,
        commit_sha=sha,
        compiler=principal,
        approver=principal,
        agent_admin=principal,
        agent_domain="reader_outcome",
        agent_scope_type="BOOK",
        runtime_environment=settings.environment,
    )
