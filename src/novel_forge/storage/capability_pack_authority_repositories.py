from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.capability_pack_authority.domain import (
    ApprovalDecision,
    CapabilityPackExecutionSnapshot,
    CapabilityPackScope,
    DeploymentStatus,
    RolloutStatus,
    ScopeType,
    canonical_hash,
    stable_rollout_bucket,
)
from novel_forge.modules.capability_pack_authority.policy import (
    CapabilityPackApprovalScope,
)
from novel_forge.modules.capability_packs.artifacts import is_floating_version
from novel_forge.modules.command_kernel.errors import KernelError


class CapabilityPackAuthorityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def lock_pack_authority(self, pack_id: str) -> None:

        self.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"novel-forge:capability-pack:{pack_id}"],
        )

    def register_version(
        self,
        *,
        project_id: str,
        manifest: Mapping[str, Any],
        manifest_hash: str,
        artifact_catalog: Mapping[str, Any],
        artifact_catalog_hash: str,
        release_channel: str,
        owner_scope_type: str,
        owner_project_id: str,
        dependencies: Sequence[Mapping[str, Any]],
        registered_by: str,
        operation_id: str,
        checkpoint: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        identity = dict(manifest.get("identity") or {})
        pack_id = str(identity.get("pack_id") or "")
        pack_version = str(identity.get("version") or "")
        if not pack_id or not pack_version:
            raise KernelError(
                "CAPABILITY_PACK_IDENTITY_REQUIRED",
                "Capability Pack manifest requires exact pack_id and version",
            )
        owner_scope_type = str(owner_scope_type).upper()
        if owner_scope_type not in {ScopeType.SYSTEM.value, ScopeType.PROJECT.value}:
            raise KernelError(
                "CAPABILITY_PACK_OWNER_SCOPE_INVALID",
                "Pack owner scope must be SYSTEM or PROJECT",
            )
        if (owner_scope_type == ScopeType.SYSTEM.value and owner_project_id) or (
            owner_scope_type == ScopeType.PROJECT.value
            and owner_project_id != project_id
        ):
            raise KernelError(
                "CAPABILITY_PACK_OWNER_SCOPE_INVALID",
                "SYSTEM owner has no owner Project; PROJECT owner must be the command Project",
            )
        normalized_dependencies = self._normalize_dependencies(
            manifest=manifest,
            dependencies=dependencies,
        )
        existing = self.require_version(
            pack_id,
            pack_version,
            project_id=project_id,
            for_update=True,
            required=False,
        )
        if existing is not None:
            if (
                existing["manifest_hash"] != manifest_hash
                or existing["artifact_catalog_hash"] != artifact_catalog_hash
            ):
                raise KernelError(
                    "CAPABILITY_PACK_VERSION_CONFLICT",
                    "Pack version is already bound to different immutable content",
                )
            if (
                existing["owner_scope_type"] != owner_scope_type
                or existing["owner_project_id"] != owner_project_id
                or self.dependencies_for_version(pack_id, pack_version)
                != normalized_dependencies
            ):
                raise KernelError(
                    "CAPABILITY_PACK_VERSION_CONFLICT",
                    "Pack version ownership or exact dependencies changed",
                )
            return {**existing, "replayed": True}

        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack(
                pack_id, name, domain, capability_type, owner, description,
                created_by_operation_id, owner_scope_type, owner_project_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, ''))
            ON CONFLICT(pack_id) DO NOTHING
            """,
            [
                pack_id,
                str(identity.get("name") or pack_id),
                str(identity.get("domain") or ""),
                str(identity.get("capability_type") or ""),
                str(identity.get("owner") or ""),
                str(identity.get("description") or ""),
                operation_id,
                owner_scope_type,
                owner_project_id,
            ],
        )
        self.cursor.execute(
            """
            SELECT name, domain, capability_type, owner,
                   owner_scope_type, COALESCE(owner_project_id, '')
            FROM authority_capability_pack WHERE pack_id=%s FOR SHARE
            """,
            [pack_id],
        )
        row = self.cursor.fetchone()
        expected = (
            str(identity.get("name") or pack_id),
            str(identity.get("domain") or ""),
            str(identity.get("capability_type") or ""),
            str(identity.get("owner") or ""),
            owner_scope_type,
            owner_project_id,
        )
        if row != expected:
            raise KernelError(
                "CAPABILITY_PACK_IDENTITY_CONFLICT",
                "stable Pack identity is already bound to different metadata",
            )

        manifest_asset_version_id = self._store_asset_version(
            project_id=project_id,
            asset_id=f"capability-pack-manifest:{pack_id}",
            asset_type="capability_pack_manifest",
            content=manifest,
            content_hash=manifest_hash,
            schema_version=str(manifest.get("schema_version") or ""),
        )
        catalog_asset_version_id = self._store_asset_version(
            project_id=project_id,
            asset_id=f"capability-pack-artifact-catalog:{pack_id}",
            asset_type="capability_pack_artifact_catalog",
            content=artifact_catalog,
            content_hash=artifact_catalog_hash,
            schema_version=str(
                artifact_catalog.get("schema_version")
                or "novelos.capability_pack.artifact_catalog.v1"
            ),
        )
        if checkpoint is not None:
            checkpoint("after_manifest_asset")
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_version(
                pack_id, pack_version, manifest_asset_version_id,
                artifact_catalog_asset_version_id, manifest_hash,
                artifact_catalog_hash, protocol_version, lifecycle,
                release_channel, registered_by, registered_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                pack_id,
                pack_version,
                manifest_asset_version_id,
                catalog_asset_version_id,
                manifest_hash,
                artifact_catalog_hash,
                str(manifest.get("schema_version") or ""),
                str(identity.get("lifecycle") or "VALIDATION"),
                release_channel,
                registered_by,
                operation_id,
            ],
        )
        for dependency in normalized_dependencies:
            self.cursor.execute(
                """
                INSERT INTO authority_capability_pack_dependency(
                    pack_id, pack_version, dependency_pack_id,
                    dependency_pack_version, dependency_manifest_hash,
                    dependency_type, created_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    pack_id,
                    pack_version,
                    dependency["pack_id"],
                    dependency["version"],
                    dependency["manifest_hash"],
                    dependency["dependency_type"],
                    operation_id,
                ],
            )
        result = self.require_version(pack_id, pack_version, project_id=project_id)
        assert result is not None
        return {**result, "replayed": False}

    def require_version(
        self,
        pack_id: str,
        pack_version: str,
        *,
        project_id: str = "",
        for_update: bool = False,
        required: bool = True,
    ) -> dict[str, Any] | None:
        lock = " FOR UPDATE" if for_update else ""
        self.cursor.execute(
            f"""
            SELECT version.pack_id, version.pack_version,
                   version.manifest_asset_version_id,
                   version.artifact_catalog_asset_version_id,
                   version.manifest_hash, version.artifact_catalog_hash,
                   version.protocol_version, version.lifecycle,
                   version.release_channel, version.registered_by,
                   manifest.content, catalog.content,
                   pack.owner_scope_type,
                   COALESCE(pack.owner_project_id, ''),
                   manifest_owner.project_id
            FROM authority_capability_pack_version AS version
            JOIN authority_capability_pack AS pack
              ON pack.pack_id=version.pack_id
            JOIN authority_asset_version AS manifest
              ON manifest.asset_version_id=version.manifest_asset_version_id
            JOIN authority_asset AS manifest_owner
              ON manifest_owner.asset_id=manifest.asset_id
            JOIN authority_asset_version AS catalog
              ON catalog.asset_version_id=version.artifact_catalog_asset_version_id
            WHERE version.pack_id=%s AND version.pack_version=%s{lock}
            """,
            [pack_id, pack_version],
        )
        row = self.cursor.fetchone()
        if row is None:
            if required:
                raise KernelError(
                    "CAPABILITY_PACK_VERSION_NOT_FOUND",
                    f"Capability Pack version does not exist: {pack_id}@{pack_version}",
                )
            return None
        fields = (
            "pack_id",
            "pack_version",
            "manifest_asset_version_id",
            "artifact_catalog_asset_version_id",
            "manifest_hash",
            "artifact_catalog_hash",
            "protocol_version",
            "lifecycle",
            "release_channel",
            "registered_by",
            "manifest",
            "artifact_catalog",
            "owner_scope_type",
            "owner_project_id",
            "authority_storage_project_id",
        )
        result = dict(zip(fields, row, strict=True))
        if project_id:
            if result["owner_scope_type"] == ScopeType.PROJECT.value:
                if result["owner_project_id"] != project_id:
                    raise KernelError(
                        "CAPABILITY_PACK_PROJECT_SCOPE_MISMATCH",
                        "Project-owned Pack is outside the authorized project",
                    )
            elif result["authority_storage_project_id"] != project_id:
                raise KernelError(
                    "CAPABILITY_PACK_SYSTEM_AUTHORITY_PROJECT_REQUIRED",
                    "SYSTEM Pack mutation requires its explicit Authority Project",
                )
        return result

    def dependencies_for_version(
        self, pack_id: str, pack_version: str
    ) -> tuple[dict[str, str], ...]:
        self.cursor.execute(
            """
            SELECT dependency_pack_id, dependency_pack_version,
                   dependency_manifest_hash, dependency_type
            FROM authority_capability_pack_dependency
            WHERE pack_id=%s AND pack_version=%s
            ORDER BY dependency_pack_id
            """,
            [pack_id, pack_version],
        )
        return tuple(
            {
                "pack_id": str(row[0]),
                "version": str(row[1]),
                "manifest_hash": str(row[2]),
                "dependency_type": str(row[3]),
            }
            for row in self.cursor.fetchall()
        )

    def blocked_dependencies(self, pack_id: str, pack_version: str) -> tuple[str, ...]:

        blocked: list[str] = []
        for dependency in self.dependencies_for_version(pack_id, pack_version):
            dependency_id = dependency["pack_id"]
            dependency_version = dependency["version"]
            version = self.require_version(dependency_id, dependency_version)
            deprecation = self.latest_deprecation(dependency_id, dependency_version)
            self.cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM authority_capability_pack_compilation AS compilation
                    WHERE compilation.pack_id=%s
                      AND compilation.pack_version=%s
                      AND (
                        compilation.compilation_status='REVOKED'
                        OR (
                            SELECT approval.decision
                            FROM authority_capability_pack_approval AS approval
                            WHERE approval.compilation_id=compilation.compilation_id
                            ORDER BY approval.decided_at DESC,
                                     approval.approval_id DESC
                            LIMIT 1
                        )='REVOKED'
                      )
                )
                """,
                [dependency_id, dependency_version],
            )
            revoked = bool(self.cursor.fetchone()[0])
            if (
                version["manifest_hash"] != dependency["manifest_hash"]
                or bool(deprecation and deprecation["retired"])
                or revoked
            ):
                blocked.append(f"{dependency_id}@{dependency_version}")
        return tuple(sorted(blocked))

    def exact_dependency_catalog(
        self, *, pack_id: str, pack_version: str, project_id: str
    ) -> tuple[dict[str, Any], ...]:
        root = self.require_version(pack_id, pack_version, project_id=project_id)
        assert root is not None
        result: dict[tuple[str, str], dict[str, Any]] = {}

        def visit(version: Mapping[str, Any]) -> None:
            identity = (str(version["pack_id"]), str(version["pack_version"]))
            if identity in result:
                return
            dependencies = self.dependencies_for_version(*identity)
            result[identity] = {
                "manifest": dict(version["manifest"]),
                "dependencies": dependencies,
            }
            for dependency in dependencies:
                child = self.require_version(
                    dependency["pack_id"], dependency["version"]
                )
                assert child is not None
                if child["manifest_hash"] != dependency["manifest_hash"]:
                    raise KernelError(
                        "CAPABILITY_PACK_DEPENDENCY_HASH_DRIFT",
                        "registered dependency differs from its exact Manifest hash",
                    )
                visit(child)

        visit(root)
        return tuple(result[key] for key in sorted(result))

    def list_versions(
        self, *, project_id: str, pack_id: str = ""
    ) -> list[dict[str, Any]]:
        parameters: list[str] = [project_id]
        clauses = ["asset.project_id=%s"]
        if pack_id:
            clauses.append("version.pack_id=%s")
            parameters.append(pack_id)
        where = "WHERE " + " AND ".join(clauses)
        self.cursor.execute(
            f"""
            SELECT version.pack_id, version.pack_version, version.manifest_hash,
                   version.protocol_version, version.lifecycle,
                   version.release_channel, version.registered_by,
                   version.registered_at
            FROM authority_capability_pack_version AS version
            JOIN authority_asset_version AS asset_version
              ON asset_version.asset_version_id=version.manifest_asset_version_id
            JOIN authority_asset AS asset ON asset.asset_id=asset_version.asset_id
            {where}
            ORDER BY version.pack_id, version.registered_at DESC
            """,
            parameters,
        )
        fields = (
            "pack_id",
            "pack_version",
            "manifest_hash",
            "protocol_version",
            "lifecycle",
            "release_channel",
            "registered_by",
            "registered_at",
        )
        return [dict(zip(fields, row, strict=True)) for row in self.cursor.fetchall()]

    def all_manifest_payloads(self, *, project_id: str) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT manifest.content
            FROM authority_capability_pack_version AS version
            JOIN authority_asset_version AS manifest
              ON manifest.asset_version_id=version.manifest_asset_version_id
            JOIN authority_asset AS asset ON asset.asset_id=manifest.asset_id
            WHERE asset.project_id=%s
            ORDER BY version.pack_id, version.pack_version
            """,
            [project_id],
        )
        return [dict(row[0]) for row in self.cursor.fetchall()]

    def record_validation(
        self,
        *,
        pack_id: str,
        pack_version: str,
        manifest_hash: str,
        validator_version: str,
        valid: bool,
        report: Mapping[str, Any],
        validated_by: str,
        operation_id: str,
    ) -> dict[str, Any]:
        report_hash = canonical_hash(report)
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_validation(
                validation_id, pack_id, pack_version, manifest_hash,
                validator_version, decision, report, report_hash,
                validated_by, validated_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(pack_id, pack_version, manifest_hash, report_hash)
            DO NOTHING
            """,
            [
                str(uuid4()),
                pack_id,
                pack_version,
                manifest_hash,
                validator_version,
                "VALID" if valid else "INVALID",
                Jsonb(dict(report)),
                report_hash,
                validated_by,
                operation_id,
            ],
        )
        return {
            "pack_id": pack_id,
            "pack_version": pack_version,
            "manifest_hash": manifest_hash,
            "validation_status": "VALID" if valid else "INVALID",
            "report_hash": report_hash,
        }

    def store_compilation(
        self,
        *,
        project_id: str,
        compilation_id: str,
        compiled: Mapping[str, Any],
        compiler_version: str,
        compiled_by: str,
        operation_id: str,
        checkpoint: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        existing = self.compilation_by_hash(
            str(compiled["compilation_hash"]), project_id=project_id
        )
        if existing is not None:
            if (
                existing["pack_id"] != str(compiled["pack_id"])
                or existing["pack_version"] != str(compiled["pack_version"])
                or existing["manifest_hash"] != str(compiled["manifest_hash"])
            ):
                raise KernelError(
                    "CAPABILITY_PACK_COMPILATION_CONFLICT",
                    "Compilation hash is bound to a different Pack identity",
                )
            return {**existing, "replayed": True}
        compiled_asset_version_id = self._store_asset_version(
            project_id=project_id,
            asset_id=(
                f"capability-pack-compilation:{compiled['pack_id']}:"
                f"{compiled['pack_version']}"
            ),
            asset_type="compiled_capability_pack",
            content=compiled,
            content_hash=str(compiled["compilation_hash"]),
            schema_version=str(compiled["schema_version"]),
        )
        if checkpoint is not None:
            checkpoint("after_compilation_asset")
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_compilation(
                compilation_id, pack_id, pack_version, manifest_hash,
                compiled_asset_version_id, compilation_hash,
                catalog_snapshot_hash, compiler_version, release_sha,
                novel_forge_version, runtime_profile, release_channel,
                compiled_by, compiled_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                compilation_id,
                str(compiled["pack_id"]),
                str(compiled["pack_version"]),
                str(compiled["manifest_hash"]),
                compiled_asset_version_id,
                str(compiled["compilation_hash"]),
                str(compiled["catalog_snapshot_hash"]),
                compiler_version,
                str(compiled["release_sha"]),
                str(compiled["novel_forge_version"]),
                str(compiled["target_runtime_profile"]),
                str(compiled["release_channel"]),
                compiled_by,
                operation_id,
            ],
        )
        result = self.require_compilation(compilation_id, project_id=project_id)
        return {**result, "replayed": False}

    def require_compilation(
        self,
        compilation_id: str,
        *,
        project_id: str = "",
        for_update: bool = False,
    ) -> dict[str, Any]:
        lock = " FOR UPDATE" if for_update else ""
        self.cursor.execute(
            f"""
            SELECT compilation.compilation_id, compilation.pack_id,
                   compilation.pack_version, compilation.manifest_hash,
                   compilation.compiled_asset_version_id,
                   compilation.compilation_hash,
                   compilation.catalog_snapshot_hash,
                   compilation.compiler_version, compilation.release_sha,
                   compilation.novel_forge_version,
                   compilation.runtime_profile,
                   compilation.release_channel,
                   compilation.compilation_status,
                   compilation.compiled_by,
                   version.content
            FROM authority_capability_pack_compilation AS compilation
            JOIN authority_asset_version AS version
              ON version.asset_version_id=compilation.compiled_asset_version_id
            WHERE compilation.compilation_id=%s{lock}
            """,
            [compilation_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CAPABILITY_PACK_COMPILATION_NOT_FOUND",
                f"trusted Compilation does not exist: {compilation_id}",
            )
        fields = (
            "compilation_id",
            "pack_id",
            "pack_version",
            "manifest_hash",
            "compiled_asset_version_id",
            "compilation_hash",
            "catalog_snapshot_hash",
            "compiler_version",
            "release_sha",
            "novel_forge_version",
            "runtime_profile",
            "release_channel",
            "compilation_status",
            "compiled_by",
            "compiled",
        )
        result = dict(zip(fields, row, strict=True))
        if project_id:
            self._require_asset_project(
                str(result["compiled_asset_version_id"]), project_id
            )
        return result

    def compilation_by_hash(
        self, compilation_hash: str, *, project_id: str = ""
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT compilation_id
            FROM authority_capability_pack_compilation
            WHERE compilation_hash=%s
            """,
            [compilation_hash],
        )
        row = self.cursor.fetchone()
        return (
            self.require_compilation(str(row[0]), project_id=project_id)
            if row
            else None
        )

    def record_approval(
        self,
        *,
        project_id: str,
        compilation_id: str,
        compilation_hash: str,
        decision: ApprovalDecision,
        approval_policy_ref: str,
        approval_scope: CapabilityPackApprovalScope,
        reason: str,
        evidence_refs: Sequence[str],
        limitations: Sequence[Mapping[str, Any]],
        expires_at: datetime | None,
        decided_by: str,
        operation_id: str,
        enforce_duties_separation: bool,
    ) -> dict[str, Any]:
        compilation = self.require_compilation(
            compilation_id, project_id=project_id, for_update=True
        )
        if compilation["compilation_hash"] != compilation_hash:
            raise KernelError(
                "CAPABILITY_PACK_APPROVAL_HASH_DRIFT",
                "approval does not bind the trusted Compilation hash",
            )
        if enforce_duties_separation and compilation["compiled_by"] == decided_by:
            raise KernelError(
                "CAPABILITY_PACK_DUTIES_SEPARATION_REQUIRED",
                "compiler principal cannot approve this Compilation",
            )
        approval_id = str(uuid4())
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_approval(
                approval_id, compilation_id, compilation_hash, decision,
                approval_policy_ref, approval_scope, reason, evidence_refs,
                limitations, expires_at, decided_by, decided_by_operation_id,
                approval_scope_v1, structured_limitations
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s)
            """,
            [
                approval_id,
                compilation_id,
                compilation_hash,
                ApprovalDecision(decision).value,
                approval_policy_ref,
                Jsonb(approval_scope.to_dict()),
                reason,
                Jsonb(list(evidence_refs)),
                Jsonb([dict(item) for item in limitations]),
                expires_at,
                decided_by,
                operation_id,
                Jsonb(approval_scope.to_dict()),
                Jsonb([dict(item) for item in limitations]),
            ],
        )
        return {
            "approval_id": approval_id,
            "compilation_id": compilation_id,
            "compilation_hash": compilation_hash,
            "decision": ApprovalDecision(decision).value,
        }

    def require_admitted_compilation(self, compilation_id: str, *, project_id: str, environment: str, book_id: str) -> dict[str, Any]:
        from novel_forge.modules.capability_pack_authority.validation_admission import require_validation_admission
        compilation = self.require_compilation(compilation_id, project_id=project_id, for_update=True)
        admitted = require_validation_admission(self, compilation, environment=environment, book_id=book_id)
        return admitted if admitted is not None else self.require_approved_compilation(compilation_id, project_id=project_id)

    def require_approved_compilation(
        self, compilation_id: str, *, project_id: str = ""
    ) -> dict[str, Any]:
        compilation = self.require_compilation(
            compilation_id, project_id=project_id, for_update=True
        )
        self.cursor.execute(
            """
            SELECT approval_id, compilation_hash, decision, expires_at,
                   approval_policy_ref, approval_scope_v1,
                   structured_limitations
            FROM authority_capability_pack_approval
            WHERE compilation_id=%s
            ORDER BY decided_at DESC, approval_id DESC
            LIMIT 1
            """,
            [compilation_id],
        )
        row = self.cursor.fetchone()
        expired = (
            row is not None
            and row[3] is not None
            and row[3] <= datetime.now(timezone.utc)
        )
        if (
            row is None
            or str(row[1]) != compilation["compilation_hash"]
            or str(row[2]) != ApprovalDecision.APPROVED.value
            or expired
        ):
            raise KernelError(
                "CAPABILITY_PACK_COMPILATION_NOT_APPROVED",
                "trusted Compilation has no current exact APPROVED decision",
            )
        return {
            **compilation,
            "approval_id": str(row[0]),
            "approval_policy_ref": str(row[4]),
            "approval_scope": dict(row[5] or {}),
            "structured_limitations": tuple(dict(item) for item in row[6] or ()),
        }

    def store_binding_set(
        self,
        *,
        binding_set_id: str,
        compilation_id: str,
        binding_set_hash: str,
        workflow_definition_ref: str,
        node_bindings: Sequence[Mapping[str, Any]],
        artifact_bindings: Mapping[str, Any],
        policy_bindings: Mapping[str, Any],
        operation_id: str,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_binding_set(
                binding_set_id, compilation_id, binding_set_hash,
                workflow_definition_ref, node_bindings, artifact_bindings,
                policy_bindings, created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(compilation_id) DO NOTHING
            """,
            [
                binding_set_id,
                compilation_id,
                binding_set_hash,
                workflow_definition_ref,
                Jsonb([dict(item) for item in node_bindings]),
                Jsonb(dict(artifact_bindings)),
                Jsonb(dict(policy_bindings)),
                operation_id,
            ],
        )
        existing = self.binding_set_for_compilation(compilation_id)
        if existing["binding_set_hash"] != binding_set_hash:
            raise KernelError(
                "CAPABILITY_PACK_BINDING_SET_CONFLICT",
                "Compilation is already bound to a different Binding Set",
            )
        return existing

    def binding_set_for_compilation(self, compilation_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT binding_set_id, compilation_id, binding_set_hash,
                   workflow_definition_ref, node_bindings,
                   artifact_bindings, policy_bindings
            FROM authority_capability_pack_binding_set
            WHERE compilation_id=%s
            """,
            [compilation_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CAPABILITY_PACK_BINDING_SET_NOT_FOUND",
                "trusted Compilation has no complete Binding Set",
            )
        fields = (
            "binding_set_id",
            "compilation_id",
            "binding_set_hash",
            "workflow_definition_ref",
            "node_bindings",
            "artifact_bindings",
            "policy_bindings",
        )
        return dict(zip(fields, row, strict=True))

    def create_deployment(
        self,
        *,
        deployment_id: str,
        compilation: Mapping[str, Any],
        binding_set: Mapping[str, Any],
        scope: CapabilityPackScope,
        owner_project_id: str,
        environment: str,
        rollout_policy_ref: str,
        operation_id: str,
    ) -> dict[str, Any]:
        self._validate_scope_exists(scope)
        CapabilityPackApprovalScope.from_payload(
            dict(compilation.get("admission_scope") or compilation["approval_scope"])
        ).require_admission(
            scope=scope,
            environment=environment,
            runtime_profile=str(compilation["runtime_profile"]),
            release_channel=str(compilation["release_channel"]),
            workflow_definition_ref=str(binding_set["workflow_definition_ref"]),
            limitations=tuple(compilation.get("structured_limitations") or ()),
        )
        deprecation = self.latest_deprecation(
            str(compilation["pack_id"]), str(compilation["pack_version"])
        )
        if deprecation is not None and bool(deprecation["retired"]):
            raise KernelError(
                "CAPABILITY_PACK_VERSION_RETIRED",
                "retired Pack Version cannot create a new Deployment",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_deployment(
                deployment_id, pack_id, pack_version, compilation_id,
                binding_set_id, target_scope_type, scope_key, project_id,
                workspace_id, book_id, environment,
                workflow_definition_ref, rollout_policy_ref,
                created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NULLIF(%s, ''),
                      NULLIF(%s, ''), NULLIF(%s, ''), %s, %s, %s, %s)
            """,
            [
                deployment_id,
                str(compilation["pack_id"]),
                str(compilation["pack_version"]),
                str(compilation["compilation_id"]),
                str(binding_set["binding_set_id"]),
                scope.scope_type.value,
                scope.scope_key,
                scope.project_id,
                scope.workspace_id,
                scope.book_id,
                environment,
                str(binding_set["workflow_definition_ref"]),
                rollout_policy_ref,
                operation_id,
            ],
        )
        return self.require_deployment(deployment_id, project_id=owner_project_id)

    def require_deployment(
        self,
        deployment_id: str,
        *,
        project_id: str = "",
        for_update: bool = False,
    ) -> dict[str, Any]:
        lock = " FOR UPDATE" if for_update else ""
        self.cursor.execute(
            f"""
            SELECT deployment.deployment_id, deployment.pack_id,
                   deployment.pack_version, deployment.compilation_id,
                   deployment.binding_set_id, deployment.target_scope_type,
                   deployment.scope_key, COALESCE(deployment.project_id, ''),
                   COALESCE(deployment.workspace_id, ''),
                   COALESCE(deployment.book_id, ''), deployment.environment,
                   deployment.workflow_definition_ref,
                   deployment.deployment_status,
                   deployment.rollout_policy_ref,
                   compilation.compilation_hash, compilation.manifest_hash,
                   compilation.catalog_snapshot_hash, compilation.release_sha,
                   compilation.runtime_profile, compilation.release_channel,
                   binding_set.binding_set_hash,
                   binding_set.node_bindings,
                   binding_set.artifact_bindings,
                   binding_set.policy_bindings
            FROM authority_capability_pack_deployment AS deployment
            JOIN authority_capability_pack_compilation AS compilation
              ON compilation.compilation_id=deployment.compilation_id
            JOIN authority_capability_pack_binding_set AS binding_set
              ON binding_set.binding_set_id=deployment.binding_set_id
            WHERE deployment.deployment_id=%s{lock}
            """,
            [deployment_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CAPABILITY_PACK_DEPLOYMENT_NOT_FOUND",
                f"Pack Deployment does not exist: {deployment_id}",
            )
        fields = (
            "deployment_id",
            "pack_id",
            "pack_version",
            "compilation_id",
            "binding_set_id",
            "target_scope_type",
            "scope_key",
            "project_id",
            "workspace_id",
            "book_id",
            "environment",
            "workflow_definition_ref",
            "deployment_status",
            "rollout_policy_ref",
            "compilation_hash",
            "manifest_hash",
            "catalog_snapshot_hash",
            "release_sha",
            "runtime_profile",
            "release_channel",
            "binding_set_hash",
            "node_bindings",
            "artifact_bindings",
            "policy_bindings",
        )
        result = dict(zip(fields, row, strict=True))
        if project_id:
            self.require_compilation(
                str(result["compilation_id"]), project_id=project_id
            )
        return result

    def activate_deployment_cas(
        self,
        *,
        project_id: str,
        deployment_id: str,
        expected_activation_version: int,
        reason: str,
        activated_by: str,
        operation_id: str,
    ) -> dict[str, Any]:
        deployment = self.require_deployment(
            deployment_id, project_id=project_id, for_update=True
        )
        self._require_deployment_admissible(deployment)
        activation_key = canonical_hash(
            {
                "scope_key": deployment["scope_key"],
                "environment": deployment["environment"],
                "workflow_definition_ref": deployment["workflow_definition_ref"],
                "pack_id": deployment["pack_id"],
            }
        )
        if expected_activation_version == 0:
            self.cursor.execute(
                """
                INSERT INTO authority_capability_pack_activation(
                    activation_key, scope_key, target_scope_type, project_id,
                    workspace_id, book_id, environment,
                    workflow_definition_ref, pack_id, active_deployment_id,
                    activation_version, reason, activated_by,
                    activated_by_operation_id
                ) VALUES (%s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''),
                          NULLIF(%s, ''), %s, %s, %s, %s, 1, %s, %s, %s)
                ON CONFLICT(activation_key) DO NOTHING
                """,
                [
                    activation_key,
                    deployment["scope_key"],
                    deployment["target_scope_type"],
                    deployment["project_id"],
                    deployment["workspace_id"],
                    deployment["book_id"],
                    deployment["environment"],
                    deployment["workflow_definition_ref"],
                    deployment["pack_id"],
                    deployment_id,
                    reason,
                    activated_by,
                    operation_id,
                ],
            )
        elif expected_activation_version > 0:
            self.cursor.execute(
                """
                UPDATE authority_capability_pack_activation
                SET active_deployment_id=%s,
                    activation_version=activation_version + 1,
                    reason=%s, activated_by=%s,
                    activated_by_operation_id=%s,
                    activated_at=NOW(), updated_at=NOW()
                WHERE activation_key=%s AND activation_version=%s
                """,
                [
                    deployment_id,
                    reason,
                    activated_by,
                    operation_id,
                    activation_key,
                    expected_activation_version,
                ],
            )
        else:
            raise KernelError(
                "CAPABILITY_PACK_ACTIVATION_VERSION_INVALID",
                "expected activation version cannot be negative",
            )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CAPABILITY_PACK_ACTIVATION_CONFLICT",
                "Pack activation changed concurrently",
            )
        self.cursor.execute(
            """
            UPDATE authority_capability_pack_deployment
            SET deployment_status=CASE
                    WHEN deployment_id=%s THEN 'ACTIVE'
                    WHEN deployment_status='ACTIVE' THEN 'CANDIDATE'
                    ELSE deployment_status
                END,
                updated_at=NOW()
            WHERE scope_key=%s AND environment=%s
              AND workflow_definition_ref=%s AND pack_id=%s
              AND deployment_status <> 'RETIRED'
            """,
            [
                deployment_id,
                deployment["scope_key"],
                deployment["environment"],
                deployment["workflow_definition_ref"],
                deployment["pack_id"],
            ],
        )
        return self.activation_by_key(activation_key)

    def activation_by_key(self, activation_key: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT activation_key, scope_key, target_scope_type,
                   COALESCE(project_id, ''), COALESCE(workspace_id, ''),
                   COALESCE(book_id, ''), environment,
                   workflow_definition_ref, pack_id, active_deployment_id,
                   activation_version, reason, activated_by
            FROM authority_capability_pack_activation
            WHERE activation_key=%s
            """,
            [activation_key],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CAPABILITY_PACK_ACTIVATION_NOT_FOUND",
                "Pack activation pointer does not exist",
            )
        fields = (
            "activation_key",
            "scope_key",
            "target_scope_type",
            "project_id",
            "workspace_id",
            "book_id",
            "environment",
            "workflow_definition_ref",
            "pack_id",
            "active_deployment_id",
            "activation_version",
            "reason",
            "activated_by",
        )
        return dict(zip(fields, row, strict=True))

    def disable_deployment(
        self, deployment_id: str, *, project_id: str
    ) -> dict[str, Any]:
        deployment = self.require_deployment(
            deployment_id, project_id=project_id, for_update=True
        )
        if deployment["deployment_status"] == DeploymentStatus.RETIRED.value:
            raise KernelError(
                "CAPABILITY_PACK_DEPLOYMENT_RETIRED",
                "retired Deployment cannot change status",
            )
        self.cursor.execute(
            """
            UPDATE authority_capability_pack_deployment
            SET deployment_status='DISABLED', updated_at=NOW()
            WHERE deployment_id=%s
            """,
            [deployment_id],
        )
        return self.require_deployment(deployment_id, project_id=project_id)

    def start_rollout(
        self,
        *,
        project_id: str,
        rollout_id: str,
        baseline_deployment_id: str,
        candidate_deployment_id: str,
        mode: RolloutStatus,
        percentage: float,
        assignment_key_policy: str,
        operation_id: str,
    ) -> dict[str, Any]:
        baseline = self.require_deployment(
            baseline_deployment_id, project_id=project_id, for_update=True
        )
        candidate = self.require_deployment(
            candidate_deployment_id, project_id=project_id, for_update=True
        )
        self._require_deployment_admissible(candidate)
        identity_fields = (
            "scope_key",
            "environment",
            "workflow_definition_ref",
            "pack_id",
        )
        if any(baseline[key] != candidate[key] for key in identity_fields):
            raise KernelError(
                "CAPABILITY_PACK_ROLLOUT_SCOPE_CONFLICT",
                "baseline and candidate must share exact scope, workflow, and Pack family",
            )
        normalized = RolloutStatus(mode)
        if normalized not in {
            RolloutStatus.OFF,
            RolloutStatus.CANARY,
            RolloutStatus.PERCENTAGE,
            RolloutStatus.FULL,
        }:
            raise KernelError(
                "CAPABILITY_PACK_ROLLOUT_MODE_INVALID",
                "rollout start requires OFF, CANARY, PERCENTAGE, or FULL",
            )
        approval = self.latest_approval(str(candidate["compilation_id"]))
        assert approval is not None
        CapabilityPackApprovalScope.from_payload(
            dict(approval["approval_scope"])
        ).require_rollout(
            mode=normalized,
            percentage=percentage,
            limitations=tuple(approval.get("structured_limitations") or ()),
        )
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_rollout(
                rollout_id, baseline_deployment_id, candidate_deployment_id,
                mode, percentage, assignment_key_policy, status,
                started_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                rollout_id,
                baseline_deployment_id,
                candidate_deployment_id,
                normalized.value,
                percentage,
                assignment_key_policy,
                normalized.value,
                operation_id,
            ],
        )
        return self.require_rollout(rollout_id, project_id=project_id)

    def update_rollout_status(
        self, rollout_id: str, status: RolloutStatus, *, project_id: str
    ) -> dict[str, Any]:
        self.require_rollout(rollout_id, project_id=project_id)
        normalized = RolloutStatus(status)
        timestamps = {
            RolloutStatus.PAUSED: "paused_at=NOW(),",
            RolloutStatus.COMPLETED: "completed_at=NOW(),",
        }
        marker = timestamps.get(normalized, "")
        self.cursor.execute(
            f"""
            UPDATE authority_capability_pack_rollout
            SET status=%s, {marker} updated_at=NOW()
            WHERE rollout_id=%s
              AND status NOT IN ('COMPLETED', 'ROLLED_BACK')
            """,
            [normalized.value, rollout_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CAPABILITY_PACK_ROLLOUT_TRANSITION_CONFLICT",
                "rollout is terminal or does not exist",
            )
        return self.require_rollout(rollout_id, project_id=project_id)

    def complete_rollout(
        self,
        rollout_id: str,
        *,
        project_id: str,
        expected_activation_version: int,
        reason: str,
        activated_by: str,
        operation_id: str,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SET CONSTRAINTS
                authority_capability_pack_activation_fact_guard,
                authority_capability_pack_rollout_fact_guard
            DEFERRED
            """
        )
        rollout = self.require_rollout(
            rollout_id, project_id=project_id, for_update=True
        )
        if rollout["status"] in {
            RolloutStatus.COMPLETED.value,
            RolloutStatus.ROLLED_BACK.value,
        }:
            raise KernelError(
                "CAPABILITY_PACK_ROLLOUT_TRANSITION_CONFLICT",
                "rollout is already terminal",
            )
        baseline = self.require_deployment(
            str(rollout["baseline_deployment_id"]),
            project_id=project_id,
            for_update=True,
        )
        candidate = self.require_deployment(
            str(rollout["candidate_deployment_id"]),
            project_id=project_id,
            for_update=True,
        )
        activation_key = canonical_hash(
            {
                "scope_key": baseline["scope_key"],
                "environment": baseline["environment"],
                "workflow_definition_ref": baseline["workflow_definition_ref"],
                "pack_id": baseline["pack_id"],
            }
        )
        self.cursor.execute(
            """
            SELECT active_deployment_id, activation_version
            FROM authority_capability_pack_activation
            WHERE activation_key=%s FOR UPDATE
            """,
            [activation_key],
        )
        activation_row = self.cursor.fetchone()
        if activation_row != (
            baseline["deployment_id"],
            expected_activation_version,
        ):
            raise KernelError(
                "CAPABILITY_PACK_ACTIVATION_CONFLICT",
                "rollout baseline Activation changed; qualification must be re-evaluated",
            )
        self._require_deployment_admissible(candidate)
        approval = self.latest_approval(str(candidate["compilation_id"]))
        assert approval is not None
        CapabilityPackApprovalScope.from_payload(
            dict(approval["approval_scope"])
        ).require_rollout(
            mode=RolloutStatus.FULL,
            percentage=100,
            limitations=tuple(approval.get("structured_limitations") or ()),
        )
        activation = self.activate_deployment_cas(
            project_id=project_id,
            deployment_id=str(candidate["deployment_id"]),
            expected_activation_version=expected_activation_version,
            reason=reason,
            activated_by=activated_by,
            operation_id=operation_id,
        )
        self.cursor.execute(
            """
            UPDATE authority_capability_pack_rollout
            SET status='COMPLETED', completed_at=NOW(), updated_at=NOW()
            WHERE rollout_id=%s
              AND status NOT IN ('COMPLETED', 'ROLLED_BACK')
            """,
            [rollout_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "CAPABILITY_PACK_ROLLOUT_TRANSITION_CONFLICT",
                "rollout changed concurrently",
            )
        result = self.require_rollout(rollout_id, project_id=project_id)
        return {
            **result,
            "active_deployment_id": activation["active_deployment_id"],
            "activation_version": activation["activation_version"],
        }

    def mark_rollouts_rolled_back(
        self, baseline_deployment_id: str, *, project_id: str
    ) -> None:
        self.require_deployment(
            baseline_deployment_id, project_id=project_id, for_update=True
        )
        self.cursor.execute(
            """
            UPDATE authority_capability_pack_rollout
            SET status='ROLLED_BACK', completed_at=COALESCE(completed_at, NOW()),
                updated_at=NOW()
            WHERE baseline_deployment_id=%s
              AND status IN (
                  'OFF', 'CANARY', 'PERCENTAGE', 'FULL', 'PAUSED', 'COMPLETED'
              )
            """,
            [baseline_deployment_id],
        )

    def require_rollout(
        self,
        rollout_id: str,
        *,
        project_id: str = "",
        for_update: bool = False,
    ) -> dict[str, Any]:
        lock = " FOR UPDATE" if for_update else ""
        self.cursor.execute(
            f"""
            SELECT rollout_id, baseline_deployment_id, candidate_deployment_id,
                   mode, percentage, assignment_key_policy, status,
                   started_at, paused_at, completed_at
            FROM authority_capability_pack_rollout WHERE rollout_id=%s{lock}
            """,
            [rollout_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CAPABILITY_PACK_ROLLOUT_NOT_FOUND",
                f"Pack rollout does not exist: {rollout_id}",
            )
        fields = (
            "rollout_id",
            "baseline_deployment_id",
            "candidate_deployment_id",
            "mode",
            "percentage",
            "assignment_key_policy",
            "status",
            "started_at",
            "paused_at",
            "completed_at",
        )
        result = dict(zip(fields, row, strict=True))
        if project_id:
            self.require_deployment(
                str(result["baseline_deployment_id"]), project_id=project_id
            )
        return result

    def active_rollout_for_baseline(
        self, baseline_deployment_id: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT rollout_id
            FROM authority_capability_pack_rollout
            WHERE baseline_deployment_id=%s
              AND status IN (
                  'CANARY', 'PERCENTAGE', 'FULL', 'PAUSED'
              )
            ORDER BY started_at DESC LIMIT 2
            """,
            [baseline_deployment_id],
        )
        rows = self.cursor.fetchall()
        if len(rows) > 1:
            raise KernelError(
                "CAPABILITY_PACK_ROLLOUT_AMBIGUOUS",
                "multiple active rollouts target the same baseline",
            )
        return self.require_rollout(str(rows[0][0])) if rows else None

    def assign_rollout_subject(
        self, rollout: Mapping[str, Any], subject_key: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT assignment_id, bucket, selected_deployment_id, assignment_hash
            FROM authority_capability_pack_assignment
            WHERE rollout_id=%s AND subject_key=%s
            """,
            [rollout["rollout_id"], subject_key],
        )
        row = self.cursor.fetchone()
        if row:
            return {
                "assignment_id": str(row[0]),
                "bucket": int(row[1]),
                "selected_deployment_id": str(row[2]),
                "assignment_hash": str(row[3]),
            }
        bucket = stable_rollout_bucket(str(rollout["rollout_id"]), subject_key)
        percentage = float(rollout["percentage"])
        select_candidate = str(rollout["status"]) not in {"PAUSED", "OFF"} and (
            str(rollout["status"]) in {"FULL", "COMPLETED"}
            or bucket < round(percentage * 100)
        )
        selected = str(
            rollout[
                "candidate_deployment_id"
                if select_candidate
                else "baseline_deployment_id"
            ]
        )
        payload = {
            "rollout_id": str(rollout["rollout_id"]),
            "subject_key": subject_key,
            "bucket": bucket,
            "selected_deployment_id": selected,
        }
        assignment_id = canonical_hash(payload)
        assignment_hash = canonical_hash({**payload, "assignment_id": assignment_id})
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_assignment(
                assignment_id, rollout_id, subject_key, bucket,
                selected_deployment_id, assignment_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT(rollout_id, subject_key) DO NOTHING
            """,
            [
                assignment_id,
                rollout["rollout_id"],
                subject_key,
                bucket,
                selected,
                assignment_hash,
            ],
        )
        return self.assign_rollout_subject(rollout, subject_key)

    def record_deprecation(
        self,
        *,
        pack_id: str,
        pack_version: str,
        replacement_pack_ref: str,
        reason: str,
        retirement_deadline: datetime | None,
        migration_required: bool,
        migration_policy_ref: str,
        retired: bool,
        operation_id: str,
    ) -> dict[str, Any]:
        deprecation_id = str(uuid4())
        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack_deprecation(
                deprecation_id, pack_id, pack_version, replacement_pack_ref,
                deprecation_reason, retirement_deadline, migration_required,
                migration_policy_ref, retired, created_by_operation_id
            ) VALUES (%s, %s, %s, NULLIF(%s, ''), %s, %s, %s,
                      NULLIF(%s, ''), %s, %s)
            """,
            [
                deprecation_id,
                pack_id,
                pack_version,
                replacement_pack_ref,
                reason,
                retirement_deadline,
                migration_required,
                migration_policy_ref,
                retired,
                operation_id,
            ],
        )
        if retired:
            self.cursor.execute(
                """
                UPDATE authority_capability_pack_deployment
                SET deployment_status='RETIRED', updated_at=NOW()
                WHERE pack_id=%s AND pack_version=%s
                  AND deployment_status <> 'ACTIVE'
                """,
                [pack_id, pack_version],
            )
        return {
            "deprecation_id": deprecation_id,
            "pack_id": pack_id,
            "pack_version": pack_version,
            "retired": retired,
        }

    def mark_compilation_revoked(self, compilation_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_capability_pack_deployment
            SET deployment_status='ROLLBACK_REQUIRED', updated_at=NOW()
            WHERE compilation_id=%s
              AND deployment_status NOT IN ('DISABLED', 'RETIRED')
            """,
            [compilation_id],
        )

    def resolve_activation_candidates(
        self,
        *,
        scope_keys: Sequence[str],
        environment: str,
        workflow_definition_ref: str,
        pack_id: str,
    ) -> list[dict[str, Any]]:
        if not scope_keys:
            return []
        placeholders = ", ".join("%s" for _ in scope_keys)
        self.cursor.execute(
            f"""
            SELECT activation.activation_key, activation.scope_key,
                   activation.target_scope_type,
                   activation.active_deployment_id,
                   activation.activation_version
            FROM authority_capability_pack_activation AS activation
            JOIN authority_capability_pack_deployment AS deployment
              ON deployment.deployment_id=activation.active_deployment_id
            WHERE activation.scope_key IN ({placeholders})
              AND activation.environment=%s
              AND activation.workflow_definition_ref=%s
              AND activation.pack_id=%s
              AND deployment.deployment_status='ACTIVE'
            """,
            [*scope_keys, environment, workflow_definition_ref, pack_id],
        )
        fields = (
            "activation_key",
            "scope_key",
            "target_scope_type",
            "active_deployment_id",
            "activation_version",
        )
        return [dict(zip(fields, row, strict=True)) for row in self.cursor.fetchall()]

    def validate_resolution_scope(
        self, *, project_id: str, workspace_id: str, book_id: str
    ) -> None:
        self.cursor.execute(
            "SELECT 1 FROM authority_project WHERE project_id=%s",
            [project_id],
        )
        if self.cursor.fetchone() is None:
            raise KernelError(
                "CAPABILITY_PACK_SCOPE_NOT_FOUND",
                "runtime Project does not exist",
            )
        if workspace_id:
            self.cursor.execute(
                """
                SELECT 1 FROM authority_workspace
                WHERE project_id=%s AND workspace_id=%s
                """,
                [project_id, workspace_id],
            )
            if self.cursor.fetchone() is None:
                raise KernelError(
                    "CAPABILITY_PACK_SCOPE_CONFLICT",
                    "runtime Workspace does not belong to Project",
                )
        if book_id:
            self.cursor.execute(
                """
                SELECT 1 FROM authority_book
                WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                """,
                [project_id, workspace_id, book_id],
            )
            if self.cursor.fetchone() is None:
                raise KernelError(
                    "CAPABILITY_PACK_SCOPE_CONFLICT",
                    "runtime Book does not belong to Workspace and Project",
                )

    def find_attempt_snapshot(self, attempt_id: str) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT snapshot_id, operation_id, attempt_id,
                   execution_fencing_token, snapshot_creation_fencing_token,
                   snapshot_payload, snapshot_hash, trace_id, span_id,
                   created_by_worker_id, created_at
            FROM authority_attempt_capability_pack_snapshot
            WHERE attempt_id=%s
            """,
            [attempt_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        snapshot = CapabilityPackExecutionSnapshot(**dict(row[5]))
        if str(row[6]) != snapshot.snapshot_hash:
            raise KernelError(
                "CAPABILITY_PACK_ATTEMPT_SNAPSHOT_HASH_DRIFT",
                "stored Attempt Capability Snapshot differs from its immutable hash",
            )
        return {
            "snapshot_id": str(row[0]),
            "operation_id": str(row[1]),
            "attempt_id": str(row[2]),
            "execution_fencing_token": int(row[3]),
            "snapshot_creation_fencing_token": int(row[4]),
            "snapshot": snapshot,
            "snapshot_hash": str(row[6]),
            "trace_id": str(row[7]),
            "span_id": str(row[8]),
            "created_by_worker_id": str(row[9]),
            "created_at": row[10],
        }

    def find_latest_operation_attempt_snapshot(
        self,
        operation_id: str,
        *,
        excluding_attempt_id: str,
    ) -> dict[str, Any] | None:

        self.cursor.execute(
            """
            SELECT snapshot.attempt_id
            FROM authority_attempt_capability_pack_snapshot AS snapshot
            JOIN authority_attempt AS attempt
              ON attempt.attempt_id=snapshot.attempt_id
            JOIN authority_attempt AS current_attempt
              ON current_attempt.attempt_id=%s
             AND current_attempt.operation_id=snapshot.operation_id
            WHERE snapshot.operation_id=%s
              AND snapshot.attempt_id<>current_attempt.attempt_id
              AND attempt.attempt_number<current_attempt.attempt_number
            ORDER BY attempt.attempt_number DESC, snapshot.created_at DESC
            LIMIT 1
            """,
            [excluding_attempt_id, operation_id],
        )
        row = self.cursor.fetchone()
        return None if row is None else self.find_attempt_snapshot(str(row[0]))

    def store_attempt_snapshot(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        execution_fencing_token: int,
        snapshot_creation_fencing_token: int,
        worker_id: str,
        snapshot: CapabilityPackExecutionSnapshot,
        reused_from_snapshot_id: str = "",
        reused_from_attempt_id: str = "",
    ) -> dict[str, Any]:
        existing = self.find_attempt_snapshot(attempt_id)
        if existing is not None:
            if existing["operation_id"] != operation_id:
                raise KernelError(
                    "CAPABILITY_PACK_ATTEMPT_SNAPSHOT_CONFLICT",
                    "Attempt is already bound to another Pack snapshot operation",
                )
            return existing
        snapshot_id = canonical_hash(
            {
                "type": "CapabilityPackAttemptSnapshot.v1",
                "operation_id": operation_id,
                "attempt_id": attempt_id,
            }
        )
        assignment_id = (
            snapshot.assignment_ref
            if snapshot.rollout_id and snapshot.assignment_ref.startswith("sha256:")
            else None
        )
        self.cursor.execute(
            """
            SELECT project_id, trace_id, span_id, correlation_id, causation_id
            FROM authority_operation WHERE operation_id=%s
            """,
            [operation_id],
        )
        operation = self.cursor.fetchone()
        if operation is None:
            raise KernelError(
                "CAPABILITY_PACK_ATTEMPT_OPERATION_INVALID",
                "Pack Snapshot operation does not exist",
            )
        project_id, trace_id, span_id, correlation_id, causation_id = operation
        self.cursor.execute(
            """
            INSERT INTO authority_attempt_capability_pack_snapshot(
                snapshot_id, operation_id, attempt_id,
                execution_fencing_token, snapshot_creation_fencing_token,
                deployment_id,
                activation_version, pack_id, pack_version, manifest_hash,
                compilation_id, compilation_hash, catalog_snapshot_hash,
                binding_set_id, binding_set_hash, selected_scope_type,
                rollout_id, assignment_id, assignment_ref,
                workflow_node_id, operation_definition_ref,
                agent_definition_ref, release_sha, snapshot_payload,
                snapshot_hash, trace_id, span_id, created_by_worker_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, NULLIF(%s, ''), %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT(attempt_id) DO NOTHING
            """,
            [
                snapshot_id,
                operation_id,
                attempt_id,
                execution_fencing_token,
                snapshot_creation_fencing_token,
                snapshot.deployment_id,
                snapshot.activation_version,
                snapshot.pack_id,
                snapshot.pack_version,
                snapshot.manifest_hash,
                snapshot.compilation_id,
                snapshot.compilation_hash,
                snapshot.catalog_snapshot_hash,
                snapshot.binding_set_id,
                snapshot.binding_set_hash,
                snapshot.selected_scope_type.value,
                snapshot.rollout_id,
                assignment_id,
                snapshot.assignment_ref,
                snapshot.workflow_node_id,
                snapshot.operation_definition_ref,
                snapshot.agent_definition_ref,
                snapshot.release_sha,
                Jsonb(snapshot.to_dict()),
                snapshot.snapshot_hash,
                trace_id,
                span_id,
                worker_id,
            ],
        )
        inserted = self.cursor.rowcount == 1
        if inserted:
            event_id = str(uuid4())
            topic = "authority.capability_pack.attempt_snapshot.frozen"
            evidence = {
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "snapshot_id": snapshot_id,
                "snapshot_hash": snapshot.snapshot_hash,
                "execution_fencing_token": execution_fencing_token,
                "snapshot_creation_fencing_token": (snapshot_creation_fencing_token),
                "trace_id": str(trace_id),
                "span_id": str(span_id),
                "resolution_mode": (
                    "REUSED_OPERATION_RETRY_SNAPSHOT"
                    if reused_from_snapshot_id
                    else "RESOLVED_ACTIVE_DEPLOYMENT"
                ),
                "reused_from_snapshot_id": reused_from_snapshot_id,
                "reused_from_attempt_id": reused_from_attempt_id,
            }
            self.cursor.execute(
                """
                INSERT INTO state_event(
                    event_id, aggregate_type, aggregate_id, project_id,
                    event_type, event_version, sequence_number,
                    correlation_id, causation_id, payload
                ) VALUES (
                    %s, 'capability_pack_attempt_snapshot', %s, %s,
                    %s, 1, 1, %s, %s, %s
                )
                """,
                [
                    event_id,
                    snapshot_id,
                    project_id,
                    topic,
                    correlation_id,
                    causation_id,
                    Jsonb(evidence),
                ],
            )
            self.cursor.execute(
                """
                INSERT INTO audit_log(
                    audit_id, project_id, operation_id, action, payload
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                [str(uuid4()), project_id, operation_id, topic, Jsonb(evidence)],
            )
            self.cursor.execute(
                """
                INSERT INTO outbox_event(
                    outbox_id, event_id, project_id, topic, status, payload
                ) VALUES (%s, %s, %s, %s, 'PENDING', %s)
                """,
                [str(uuid4()), event_id, project_id, topic, Jsonb(evidence)],
            )
        stored = self.find_attempt_snapshot(attempt_id)
        if stored is None or stored["snapshot_hash"] != snapshot.snapshot_hash:
            raise KernelError(
                "CAPABILITY_PACK_ATTEMPT_SNAPSHOT_CONFLICT",
                "Attempt is already bound to different immutable Pack content",
            )
        return stored

    def latest_deprecation(
        self, pack_id: str, pack_version: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT replacement_pack_ref, deprecation_reason,
                   retirement_deadline, migration_required,
                   migration_policy_ref, retired, created_at
            FROM authority_capability_pack_deprecation
            WHERE pack_id=%s AND pack_version=%s
            ORDER BY created_at DESC, deprecation_id DESC LIMIT 1
            """,
            [pack_id, pack_version],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        fields = (
            "replacement_pack_ref",
            "deprecation_reason",
            "retirement_deadline",
            "migration_required",
            "migration_policy_ref",
            "retired",
            "created_at",
        )
        return dict(zip(fields, row, strict=True))

    def latest_approval(self, compilation_id: str) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT approval_id, compilation_hash, decision,
                   approval_policy_ref, approval_scope_v1, expires_at,
                   decided_by, decided_at, structured_limitations
            FROM authority_capability_pack_approval
            WHERE compilation_id=%s
            ORDER BY decided_at DESC, approval_id DESC LIMIT 1
            """,
            [compilation_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        fields = (
            "approval_id",
            "compilation_hash",
            "decision",
            "approval_policy_ref",
            "approval_scope",
            "expires_at",
            "decided_by",
            "decided_at",
            "structured_limitations",
        )
        return dict(zip(fields, row, strict=True))

    def _store_asset_version(
        self,
        *,
        project_id: str,
        asset_id: str,
        asset_type: str,
        content: Mapping[str, Any],
        content_hash: str,
        schema_version: str,
    ) -> str:
        self.cursor.execute(
            """
            INSERT INTO authority_asset(asset_id, project_id, asset_type)
            VALUES (%s, %s, %s) ON CONFLICT(asset_id) DO NOTHING
            """,
            [asset_id, project_id, asset_type],
        )
        self.cursor.execute(
            """
            SELECT project_id, asset_type
            FROM authority_asset WHERE asset_id=%s FOR UPDATE
            """,
            [asset_id],
        )
        if self.cursor.fetchone() != (project_id, asset_type):
            raise KernelError(
                "CAPABILITY_PACK_ASSET_SCOPE_CONFLICT",
                "Capability Pack Asset identity belongs to another scope or type",
            )
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1
            FROM authority_asset_version WHERE asset_id=%s
            """,
            [asset_id],
        )
        version_number = int(self.cursor.fetchone()[0])
        asset_version_id = str(uuid4())
        self.cursor.execute(
            """
            UPDATE authority_asset_version
            SET lifecycle='SUPERSEDED'
            WHERE asset_id=%s AND lifecycle='ACTIVE'
            """,
            [asset_id],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id, asset_id, version_number, lifecycle,
                eligibility, governance, content, content_hash, schema_version
            ) VALUES (%s, %s, %s, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, %s)
            """,
            [
                asset_version_id,
                asset_id,
                version_number,
                Jsonb(dict(content)),
                content_hash,
                schema_version,
            ],
        )
        return asset_version_id

    def _normalize_dependencies(
        self,
        *,
        manifest: Mapping[str, Any],
        dependencies: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, str], ...]:
        declared = {
            str(value)
            for value in (manifest.get("role") or {}).get("upstream_packs") or ()
        }
        normalized: dict[str, dict[str, str]] = {}
        for raw in dependencies:
            if set(raw) != {
                "pack_id",
                "version",
                "manifest_hash",
                "dependency_type",
            }:
                raise KernelError(
                    "CAPABILITY_PACK_DEPENDENCY_PROTOCOL_INVALID",
                    "dependency declaration must use the closed exact protocol",
                )
            dependency = {
                "pack_id": str(raw.get("pack_id") or ""),
                "version": str(raw.get("version") or ""),
                "manifest_hash": str(raw.get("manifest_hash") or ""),
                "dependency_type": str(raw.get("dependency_type") or ""),
            }
            if (
                not dependency["pack_id"]
                or is_floating_version(dependency["version"])
                or re.fullmatch(
                    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)",
                    dependency["version"],
                )
                is None
                or dependency["dependency_type"] not in {"REQUIRED", "OPTIONAL"}
            ):
                raise KernelError(
                    "CAPABILITY_PACK_DEPENDENCY_VERSION_INVALID",
                    "Pack dependency requires an exact SemVer and governed type",
                )
            if dependency["pack_id"] in normalized:
                raise KernelError(
                    "CAPABILITY_PACK_DEPENDENCY_DUPLICATE",
                    "one Pack dependency id cannot resolve to multiple versions",
                )
            target = self.require_version(dependency["pack_id"], dependency["version"])
            assert target is not None
            if target["manifest_hash"] != dependency["manifest_hash"]:
                raise KernelError(
                    "CAPABILITY_PACK_DEPENDENCY_HASH_DRIFT",
                    "dependency declaration does not bind the exact Manifest hash",
                )
            normalized[dependency["pack_id"]] = dependency
        if declared != set(normalized):
            raise KernelError(
                "CAPABILITY_PACK_DEPENDENCY_DECLARATION_MISMATCH",
                "Manifest upstream_packs require exact registered dependencies",
            )
        incompatible = {
            str(value)
            for value in (manifest.get("compatibility") or {}).get("incompatible_packs")
            or ()
        }
        if incompatible & set(normalized):
            raise KernelError(
                "CAPABILITY_PACK_DEPENDENCY_INCOMPATIBLE",
                "Manifest dependency is explicitly incompatible",
            )
        return tuple(normalized[key] for key in sorted(normalized))

    def _require_asset_project(self, asset_version_id: str, project_id: str) -> None:
        self.cursor.execute(
            """
            SELECT asset.project_id
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE version.asset_version_id=%s
            """,
            [asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None or str(row[0]) != project_id:
            raise KernelError(
                "CAPABILITY_PACK_PROJECT_SCOPE_MISMATCH",
                "Capability Pack object is outside the authorized project",
            )

    def _validate_scope_exists(self, scope: CapabilityPackScope) -> None:
        if scope.scope_type is ScopeType.SYSTEM:
            return
        self.cursor.execute(
            "SELECT project_id FROM authority_project WHERE project_id=%s FOR SHARE",
            [scope.project_id],
        )
        if self.cursor.fetchone() is None:
            raise KernelError(
                "CAPABILITY_PACK_SCOPE_NOT_FOUND", "target Project does not exist"
            )
        if scope.scope_type in {ScopeType.WORKSPACE, ScopeType.BOOK}:
            self.cursor.execute(
                """
                SELECT project_id FROM authority_workspace
                WHERE project_id=%s AND workspace_id=%s FOR SHARE
                """,
                [scope.project_id, scope.workspace_id],
            )
            if self.cursor.fetchone() is None:
                raise KernelError(
                    "CAPABILITY_PACK_SCOPE_CONFLICT",
                    "target Workspace does not belong to Project",
                )
        if scope.scope_type is ScopeType.BOOK:
            self.cursor.execute(
                """
                SELECT project_id FROM authority_book
                WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                FOR SHARE
                """,
                [scope.project_id, scope.workspace_id, scope.book_id],
            )
            if self.cursor.fetchone() is None:
                raise KernelError(
                    "CAPABILITY_PACK_SCOPE_CONFLICT",
                    "target Book does not belong to Workspace and Project",
                )

    def _require_deployment_admissible(self, deployment: Mapping[str, Any]) -> None:
        if deployment["deployment_status"] in {
            DeploymentStatus.DISABLED.value,
            DeploymentStatus.RETIRED.value,
            DeploymentStatus.ROLLBACK_REQUIRED.value,
        }:
            raise KernelError(
                "CAPABILITY_PACK_DEPLOYMENT_BLOCKED",
                "disabled, retired, or rollback-required Deployment cannot activate",
            )
        from novel_forge.modules.capability_pack_authority.validation_admission import require_validation_admission
        compilation = self.require_compilation(str(deployment["compilation_id"]))
        admitted = require_validation_admission(self, compilation, environment=str(deployment["environment"]), book_id=str(deployment.get("book_id") or ""))
        if admitted is not None:
            CapabilityPackApprovalScope.from_payload(admitted["admission_scope"]).require_admission(
                scope=CapabilityPackScope(ScopeType(str(deployment["target_scope_type"])),
                    project_id=str(deployment.get("project_id") or ""), workspace_id=str(deployment.get("workspace_id") or ""), book_id=str(deployment.get("book_id") or "")),
                environment=str(deployment["environment"]), runtime_profile=str(deployment["runtime_profile"]),
                release_channel=str(deployment["release_channel"]), workflow_definition_ref=str(deployment["workflow_definition_ref"]))
            deprecation = self.latest_deprecation(str(deployment["pack_id"]), str(deployment["pack_version"]))
            if deprecation and deprecation["retired"]:
                raise KernelError("CAPABILITY_PACK_VERSION_RETIRED", "retired validation Pack cannot activate")
            return
        approval = self.latest_approval(str(deployment["compilation_id"]))
        if approval is None or approval["decision"] != ApprovalDecision.APPROVED.value:
            raise KernelError(
                "CAPABILITY_PACK_COMPILATION_NOT_APPROVED",
                "Deployment Compilation is not currently approved",
            )
        if approval["compilation_hash"] != deployment["compilation_hash"]:
            raise KernelError(
                "CAPABILITY_PACK_APPROVAL_HASH_DRIFT",
                "Deployment differs from approval Compilation hash",
            )
        if approval["expires_at"] and approval["expires_at"] <= datetime.now(
            timezone.utc
        ):
            raise KernelError(
                "CAPABILITY_PACK_APPROVAL_EXPIRED",
                "Deployment approval has expired",
            )
        CapabilityPackApprovalScope.from_payload(
            dict(approval["approval_scope"])
        ).require_admission(
            scope=CapabilityPackScope(
                ScopeType(str(deployment["target_scope_type"])),
                project_id=str(deployment.get("project_id") or ""),
                workspace_id=str(deployment.get("workspace_id") or ""),
                book_id=str(deployment.get("book_id") or ""),
            ),
            environment=str(deployment["environment"]),
            runtime_profile=str(deployment["runtime_profile"]),
            release_channel=str(deployment["release_channel"]),
            workflow_definition_ref=str(deployment["workflow_definition_ref"]),
            limitations=tuple(approval.get("structured_limitations") or ()),
        )
        deprecation = self.latest_deprecation(
            str(deployment["pack_id"]), str(deployment["pack_version"])
        )
        if deprecation and deprecation["retired"]:
            raise KernelError(
                "CAPABILITY_PACK_VERSION_RETIRED",
                "retired Pack Version cannot activate",
            )


__all__ = ["CapabilityPackAuthorityRepository"]
