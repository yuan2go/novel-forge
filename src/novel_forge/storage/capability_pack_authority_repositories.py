"""PostgreSQL repositories for Capability Pack Authority configuration facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.capability_pack_authority.domain import (
    ApprovalDecision,
    CapabilityPackScope,
    DeploymentStatus,
    RolloutStatus,
    ScopeType,
    canonical_hash,
    stable_rollout_bucket,
)
from novel_forge.modules.command_kernel.errors import KernelError


class CapabilityPackAuthorityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def register_version(
        self,
        *,
        project_id: str,
        manifest: Mapping[str, Any],
        manifest_hash: str,
        artifact_catalog: Mapping[str, Any],
        artifact_catalog_hash: str,
        release_channel: str,
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
            return {**existing, "replayed": True}

        self.cursor.execute(
            """
            INSERT INTO authority_capability_pack(
                pack_id, name, domain, capability_type, owner, description,
                created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
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
            ],
        )
        self.cursor.execute(
            """
            SELECT name, domain, capability_type, owner
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
        result = self.require_version(
            pack_id, pack_version, project_id=project_id
        )
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
                   manifest.content, catalog.content
            FROM authority_capability_pack_version AS version
            JOIN authority_asset_version AS manifest
              ON manifest.asset_version_id=version.manifest_asset_version_id
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
        )
        result = dict(zip(fields, row, strict=True))
        if project_id:
            self._require_asset_project(
                str(result["manifest_asset_version_id"]), project_id
            )
        return result

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
        approval_scope: Mapping[str, Any],
        reason: str,
        evidence_refs: Sequence[str],
        limitations: Sequence[str],
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
                limitations, expires_at, decided_by, decided_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                approval_id,
                compilation_id,
                compilation_hash,
                ApprovalDecision(decision).value,
                approval_policy_ref,
                Jsonb(dict(approval_scope)),
                reason,
                Jsonb(list(evidence_refs)),
                Jsonb(list(limitations)),
                expires_at,
                decided_by,
                operation_id,
            ],
        )
        return {
            "approval_id": approval_id,
            "compilation_id": compilation_id,
            "compilation_hash": compilation_hash,
            "decision": ApprovalDecision(decision).value,
        }

    def require_approved_compilation(
        self, compilation_id: str, *, project_id: str = ""
    ) -> dict[str, Any]:
        compilation = self.require_compilation(
            compilation_id, project_id=project_id, for_update=True
        )
        self.cursor.execute(
            """
            SELECT approval_id, compilation_hash, decision, expires_at,
                   approval_policy_ref, approval_scope
            FROM authority_capability_pack_approval
            WHERE compilation_id=%s
            ORDER BY decided_at DESC, approval_id DESC
            LIMIT 1
            """,
            [compilation_id],
        )
        row = self.cursor.fetchone()
        expired = row is not None and row[3] is not None and row[3] <= datetime.now(
            timezone.utc
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
        return self.require_deployment(
            deployment_id, project_id=owner_project_id
        )

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
        self, rollout_id: str, *, project_id: str = ""
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT rollout_id, baseline_deployment_id, candidate_deployment_id,
                   mode, percentage, assignment_key_policy, status,
                   started_at, paused_at, completed_at
            FROM authority_capability_pack_rollout WHERE rollout_id=%s
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

    def active_rollout_for_baseline(self, baseline_deployment_id: str) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT rollout_id
            FROM authority_capability_pack_rollout
            WHERE baseline_deployment_id=%s
              AND status IN (
                  'CANARY', 'PERCENTAGE', 'FULL', 'PAUSED', 'COMPLETED'
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
            WHERE activation.scope_key IN ({placeholders})
              AND activation.environment=%s
              AND activation.workflow_definition_ref=%s
              AND activation.pack_id=%s
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

    def latest_deprecation(self, pack_id: str, pack_version: str) -> dict[str, Any] | None:
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
                   approval_policy_ref, approval_scope, expires_at,
                   decided_by, decided_at
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

    def _require_asset_project(
        self, asset_version_id: str, project_id: str
    ) -> None:
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
        deprecation = self.latest_deprecation(
            str(deployment["pack_id"]), str(deployment["pack_version"])
        )
        if deprecation and deprecation["retired"]:
            raise KernelError(
                "CAPABILITY_PACK_VERSION_RETIRED",
                "retired Pack Version cannot activate",
            )


__all__ = ["CapabilityPackAuthorityRepository"]
