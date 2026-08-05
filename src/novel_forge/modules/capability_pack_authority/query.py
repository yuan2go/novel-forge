"""Strong PostgreSQL query projections for Capability Pack Authority."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import DriftClassification, canonical_hash


def classify_deployment_drift(
    *,
    deployment_status: str,
    approval_current: bool,
    retired: bool,
    definition_drift: bool,
    agent_drift: bool,
    approval_revoked: bool = False,
) -> DriftClassification:
    if approval_revoked or retired or deployment_status == "RETIRED":
        return DriftClassification.REVOKED
    if deployment_status == "ROLLBACK_REQUIRED":
        return DriftClassification.ROLLBACK_RECOMMENDED
    if not approval_current or definition_drift or agent_drift:
        return DriftClassification.NEW_ADMISSION_BLOCKED
    if deployment_status not in {"ACTIVE", "CANDIDATE"}:
        return DriftClassification.HISTORICAL_ONLY
    return DriftClassification.CLEAN


class CapabilityPackAuthorityQuery:
    def __init__(
        self,
        database_url: str,
        *,
        current_release_sha: str = "",
        current_runtime_profile: str = "",
        current_release_channel: str = "",
    ) -> None:
        if not database_url:
            raise ValueError("Capability Pack Authority query requires PostgreSQL")
        self.database_url = database_url
        self.current_release_sha = current_release_sha
        self.current_runtime_profile = current_runtime_profile
        self.current_release_channel = current_release_channel

    def list_versions(
        self, *, project_id: str, pack_id: str = ""
    ) -> list[dict[str, Any]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return _json_safe(
                uow.repositories.capability_packs.list_versions(
                    project_id=project_id, pack_id=pack_id
                )
            )

    def version_detail(
        self, *, project_id: str, pack_id: str, pack_version: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            version = uow.repositories.capability_packs.require_version(
                pack_id, pack_version, project_id=project_id
            )
            uow.cursor.execute(
                """
                SELECT compilation.compilation_id
                FROM authority_capability_pack_compilation AS compilation
                JOIN authority_asset_version AS asset_version
                  ON asset_version.asset_version_id=
                     compilation.compiled_asset_version_id
                JOIN authority_asset AS asset
                  ON asset.asset_id=asset_version.asset_id
                WHERE compilation.pack_id=%s AND compilation.pack_version=%s
                  AND asset.project_id=%s
                ORDER BY compilation.created_at DESC,
                         compilation.compilation_id DESC
                """,
                [pack_id, pack_version, project_id],
            )
            compilations = [
                uow.repositories.capability_packs.require_compilation(
                    str(row[0]), project_id=project_id
                )
                for row in uow.cursor.fetchall()
            ]
            for compilation in compilations:
                compilation["approval"] = (
                    uow.repositories.capability_packs.latest_approval(
                        str(compilation["compilation_id"])
                    )
                )
            return _json_safe(
                {
                    **version,
                    "compilations": compilations,
                    "deprecation": uow.repositories.capability_packs.latest_deprecation(
                        pack_id, pack_version
                    ),
                }
            )

    def list_deployments(
        self,
        *,
        pack_id: str = "",
        project_id: str = "",
        environment: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not project_id:
            raise ValueError("Capability Pack deployment query requires project_id")
        clauses: list[str] = ["owner.project_id=%s"]
        parameters: list[Any] = [project_id]
        for column, value in (
            ("deployment.pack_id", pack_id),
            ("deployment.environment", environment),
        ):
            if value:
                clauses.append(f"{column}=%s")
                parameters.append(value)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(int(limit), 500)))
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT deployment_id, pack_id, pack_version, compilation_id,
                       binding_set_id, target_scope_type, scope_key,
                       COALESCE(project_id, ''), COALESCE(workspace_id, ''),
                       COALESCE(book_id, ''), environment,
                       workflow_definition_ref, deployment_status,
                       rollout_policy_ref, created_at, updated_at
                FROM authority_capability_pack_deployment AS deployment
                JOIN authority_capability_pack_compilation AS compilation
                  ON compilation.compilation_id=deployment.compilation_id
                JOIN authority_asset_version AS compiled_asset_version
                  ON compiled_asset_version.asset_version_id=
                     compilation.compiled_asset_version_id
                JOIN authority_asset AS owner
                  ON owner.asset_id=compiled_asset_version.asset_id
                {where}
                ORDER BY created_at DESC, deployment_id DESC
                LIMIT %s
                """,
                parameters,
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
                "created_at",
                "updated_at",
            )
            return _json_safe(
                [dict(zip(fields, row, strict=True)) for row in uow.cursor.fetchall()]
            )

    def deployment_detail(
        self, deployment_id: str, *, project_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            deployment = uow.repositories.capability_packs.require_deployment(
                deployment_id, project_id=project_id
            )
            uow.cursor.execute(
                """
                SELECT activation_key, activation_version, reason, activated_by,
                       activated_at
                FROM authority_capability_pack_activation
                WHERE active_deployment_id=%s
                ORDER BY updated_at DESC
                """,
                [deployment_id],
            )
            fields = (
                "activation_key",
                "activation_version",
                "reason",
                "activated_by",
                "activated_at",
            )
            activations = [
                dict(zip(fields, row, strict=True)) for row in uow.cursor.fetchall()
            ]
            return _json_safe({**deployment, "activations": activations})

    def rollout_detail(
        self, rollout_id: str, *, project_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            result = uow.repositories.capability_packs.require_rollout(
                rollout_id, project_id=project_id
            )
            uow.cursor.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (
                           WHERE selected_deployment_id=%s
                       )
                FROM authority_capability_pack_assignment
                WHERE rollout_id=%s
                """,
                [result["candidate_deployment_id"], rollout_id],
            )
            assignment = uow.cursor.fetchone()
            result["assignment_count"] = int(assignment[0])
            result["candidate_assignment_count"] = int(assignment[1])
            return _json_safe(result)

    def drift_report(
        self, deployment_id: str, *, project_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = uow.repositories.capability_packs
            deployment = repository.require_deployment(
                deployment_id, project_id=project_id
            )
            version = repository.require_version(
                str(deployment["pack_id"]),
                str(deployment["pack_version"]),
                project_id=project_id,
            )
            compilation = repository.require_compilation(
                str(deployment["compilation_id"]), project_id=project_id
            )
            approval = repository.latest_approval(str(deployment["compilation_id"]))
            approval_current = bool(
                approval
                and approval["decision"] == "APPROVED"
                and approval["compilation_hash"] == deployment["compilation_hash"]
                and (
                    approval["expires_at"] is None
                    or approval["expires_at"] > datetime.now(timezone.utc)
                )
            )
            approval_revoked = bool(
                approval and approval["decision"] == "REVOKED"
            )
            deprecation = repository.latest_deprecation(
                str(deployment["pack_id"]), str(deployment["pack_version"])
            )
            definition_drift: list[str] = []
            agent_drift: list[str] = []
            capability_drift: list[str] = []
            artifact_drift: list[str] = []
            resolved_artifacts = [
                dict(item)
                for item in deployment["artifact_bindings"].get(
                    "resolved_artifacts", ()
                )
            ]
            artifact_identities = {
                (
                    f"{item.get('ref')}@{item.get('version')}",
                    str(item.get("content_hash") or ""),
                )
                for item in resolved_artifacts
            }
            for node in deployment["node_bindings"]:
                operation_ref = str(node["operation_definition_ref"])
                name, separator, operation_version = operation_ref.rpartition("@")
                definition = (
                    uow.repositories.definitions.get(name, operation_version)
                    if separator
                    else None
                )
                if (
                    definition is None
                    or not definition.get("enabled")
                    or str(definition.get("definition_hash"))
                    != str(node["operation_definition_hash"])
                ):
                    definition_drift.append(operation_ref)
                agent_ref = str(node.get("agent_definition_ref") or "")
                if agent_ref:
                    agent_id, _, raw_version = agent_ref.rpartition("@")
                    try:
                        agent = uow.repositories.agent_runtime.resolve_active_definition(
                            agent_id
                        )
                    except KernelError:
                        agent_drift.append(agent_ref)
                    else:
                        if (
                            str(agent.get("definition_version")) != raw_version
                            or str(agent.get("definition_hash"))
                            != str(node["agent_definition_hash"])
                        ):
                            agent_drift.append(agent_ref)
                        capabilities = [
                            item
                            for item in agent.get("capabilities") or ()
                            if (
                                f"{item.get('capability_id')}@"
                                f"{item.get('capability_version')}"
                            )
                            == str(node.get("capability_ref") or "")
                            and str(item.get("capability_hash") or "")
                            == str(node.get("capability_hash") or "")
                            and str(item.get("execution_capability_hash") or "")
                            == str(
                                node.get("execution_capability_hash") or ""
                            )
                        ]
                        if len(capabilities) != 1:
                            capability_drift.append(
                                str(node.get("capability_ref") or agent_ref)
                            )
                if not agent_ref:
                    continue
                for ref_key, hash_key in (
                    ("prompt_system_instruction_ref", "prompt_system_instruction_hash"),
                    ("prompt_template_ref", "prompt_template_hash"),
                    ("skill_bundle_ref", "skill_bundle_hash"),
                ):
                    identity = (
                        str(node.get(ref_key) or ""),
                        str(node.get(hash_key) or ""),
                    )
                    if identity not in artifact_identities:
                        artifact_drift.append(identity[0] or ref_key)
                for payload_key, hash_key, label in (
                    ("tool_policy_payload", "tool_policy_hash", "tool"),
                    ("context_policy_payload", "context_policy_hash", "context"),
                    (
                        "evaluation_policy_payload",
                        "evaluation_policy_hash",
                        "evaluation",
                    ),
                ):
                    if canonical_hash(dict(node.get(payload_key) or {})) != str(
                        node.get(hash_key) or ""
                    ):
                        artifact_drift.append(label)
            release_drift = bool(
                self.current_release_sha
                and deployment["release_sha"] != self.current_release_sha
            )
            runtime_profile_drift = bool(
                self.current_runtime_profile
                and deployment["runtime_profile"] != self.current_runtime_profile
            )
            release_channel_drift = bool(
                self.current_release_channel
                and deployment["release_channel"] != self.current_release_channel
            )
            identity_drift = any(
                (
                    version["manifest_hash"] != deployment["manifest_hash"],
                    compilation["compilation_hash"]
                    != deployment["compilation_hash"],
                    compilation["catalog_snapshot_hash"]
                    != deployment["catalog_snapshot_hash"],
                )
            )
            expected_binding_hash = canonical_hash(
                {
                    "schema_version": "novelos.capability_pack.binding_set.v1",
                    "pack_id": deployment["pack_id"],
                    "pack_version": deployment["pack_version"],
                    "compilation_hash": deployment["compilation_hash"],
                    "workflow_definition_ref": deployment[
                        "workflow_definition_ref"
                    ],
                    "node_bindings": deployment["node_bindings"],
                    "artifact_bindings": deployment["artifact_bindings"],
                    "policy_bindings": deployment["policy_bindings"],
                }
            )
            binding_set_drift = (
                expected_binding_hash != deployment["binding_set_hash"]
            )
            deadline_elapsed = bool(
                deprecation
                and deprecation["retirement_deadline"] is not None
                and deprecation["retirement_deadline"]
                <= datetime.now(timezone.utc)
            )
            configuration_drift = any(
                (
                    identity_drift,
                    binding_set_drift,
                    bool(artifact_drift),
                    bool(capability_drift),
                    release_drift,
                    runtime_profile_drift,
                    release_channel_drift,
                    deadline_elapsed,
                )
            )
            classification = classify_deployment_drift(
                deployment_status=str(deployment["deployment_status"]),
                approval_current=approval_current,
                retired=bool(deprecation and deprecation["retired"]),
                definition_drift=bool(definition_drift) or configuration_drift,
                agent_drift=bool(agent_drift),
                approval_revoked=approval_revoked,
            )
            return _json_safe(
                {
                    "deployment_id": deployment_id,
                    "classification": classification.value,
                    "new_admission_allowed": classification
                    is DriftClassification.CLEAN,
                    "approval_current": approval_current,
                    "definition_drift": definition_drift,
                    "agent_definition_drift": agent_drift,
                    "capability_drift": capability_drift,
                    "artifact_or_policy_drift": artifact_drift,
                    "manifest_compilation_catalog_drift": identity_drift,
                    "binding_set_hash_drift": binding_set_drift,
                    "running_release_differs": release_drift,
                    "runtime_profile_differs": runtime_profile_drift,
                    "release_channel_differs": release_channel_drift,
                    "deprecation_deadline_elapsed": deadline_elapsed,
                    "historical_runtime_bindings_remain_valid": True,
                    "deprecation": deprecation,
                }
            )

    def usage_metrics(
        self,
        deployment_id: str,
        *,
        project_id: str,
        workspace_id: str = "",
        book_id: str = "",
        workflow_node_id: str = "",
        agent_id: str = "",
        provider_id: str = "",
        model_id: str = "",
        started_after: datetime | None = None,
        started_before: datetime | None = None,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            deployment = uow.repositories.capability_packs.require_deployment(
                deployment_id, project_id=project_id
            )
            clauses = [
                "binding.capability_pack_deployment_id=%s",
                "binding.project_id=%s",
            ]
            parameters: list[Any] = [deployment_id, project_id]
            for column, value in (
                ("binding.workspace_id", workspace_id),
                ("binding.book_id", book_id),
                ("binding.workflow_node_id", workflow_node_id),
                ("binding.agent_id", agent_id),
            ):
                if value:
                    clauses.append(f"{column}=%s")
                    parameters.append(value)
            for column, value, operator in (
                ("operation.created_at", started_after, ">="),
                ("operation.created_at", started_before, "<"),
            ):
                if value is not None:
                    clauses.append(f"{column}{operator}%s")
                    parameters.append(value)
            if provider_id:
                clauses.append(
                    """
                    EXISTS (
                        SELECT 1 FROM authority_external_effect AS provider_effect
                        WHERE provider_effect.operation_id=operation.operation_id
                          AND provider_effect.provider=%s
                    )
                    """
                )
                parameters.append(provider_id)
            if model_id:
                clauses.append(
                    """
                    EXISTS (
                        SELECT 1 FROM authority_external_effect AS model_effect
                        WHERE model_effect.operation_id=operation.operation_id
                          AND model_effect.model_id=%s
                    )
                    """
                )
                parameters.append(model_id)
            uow.cursor.execute(
                f"""
                WITH bound AS (
                    SELECT DISTINCT binding.binding_id, binding.operation_id,
                           operation.root_operation_id, operation.status,
                           operation.created_at, operation.updated_at
                    FROM authority_agent_runtime_binding AS binding
                    JOIN authority_operation AS operation
                      ON operation.operation_id=binding.operation_id
                    WHERE {' AND '.join(clauses)}
                ), related AS (
                    SELECT DISTINCT operation.*
                    FROM authority_operation AS operation
                    JOIN bound ON bound.root_operation_id=operation.root_operation_id
                ), output_evidence AS (
                    SELECT DISTINCT output.asset_version_id, asset.asset_type,
                           asset_version.content
                    FROM authority_operation_output_asset AS output
                    JOIN related ON related.operation_id=output.operation_id
                    JOIN authority_asset_version AS asset_version
                      ON asset_version.asset_version_id=output.asset_version_id
                    JOIN authority_asset AS asset
                      ON asset.asset_id=asset_version.asset_id
                )
                SELECT
                    (SELECT COUNT(*) FROM bound),
                    (SELECT COUNT(DISTINCT operation_id) FROM bound),
                    (SELECT COUNT(*) FROM bound WHERE status='SUCCEEDED'),
                    (SELECT COUNT(*) FROM bound WHERE status IN (
                        'FAILED_FINAL', 'DEAD_LETTER'
                    )),
                    (SELECT COUNT(*) FROM bound WHERE status='CANCELLED'),
                    (SELECT COUNT(*) FROM bound
                     WHERE status='RECONCILIATION_REQUIRED'),
                    (SELECT GREATEST(
                        COUNT(*) - COUNT(DISTINCT attempt.operation_id), 0
                     ) FROM authority_attempt AS attempt
                     JOIN bound ON bound.operation_id=attempt.operation_id),
                    (SELECT COUNT(*)
                     FROM authority_agent_collaboration_commit AS commit
                     JOIN bound ON bound.operation_id=commit.operation_id),
                    (SELECT COUNT(*) FROM authority_external_effect AS effect
                     JOIN bound ON bound.operation_id=effect.operation_id),
                    (SELECT COUNT(*) FROM authority_external_effect AS effect
                     JOIN bound ON bound.operation_id=effect.operation_id
                     WHERE effect.provider_control_level='FIXTURE_CONTROLLED'),
                    (SELECT COUNT(*) FROM authority_external_effect AS effect
                     JOIN bound ON bound.operation_id=effect.operation_id
                     WHERE effect.provider_control_level='V2_CONTROLLED'
                       AND effect.provider_request_id<>''
                       AND effect.status='SUCCEEDED'
                       AND effect.provider_capability_profile
                           ->>'real_provider_validation_eligible'='true'
                       AND EXISTS (
                           SELECT 1
                           FROM authority_external_effect_dispatch AS dispatch
                           JOIN authority_external_receipt AS receipt
                             ON receipt.dispatch_id=dispatch.dispatch_id
                           WHERE dispatch.external_effect_id=
                                 effect.external_effect_id
                       )),
                    (SELECT COALESCE(SUM(reservation.actual_tokens), 0)
                     FROM authority_budget_reservation AS reservation
                     JOIN bound ON bound.operation_id=reservation.operation_id),
                    (SELECT COALESCE(SUM(cost.amount), 0)
                     FROM authority_operation_cost_evidence AS cost
                     JOIN bound ON bound.operation_id=cost.operation_id),
                    (SELECT COUNT(*) FROM authority_operation_cost_evidence AS cost
                     JOIN bound ON bound.operation_id=cost.operation_id),
                    (SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (
                        updated_at-created_at
                    )) * 1000), 0) FROM bound),
                    (SELECT COUNT(*) FROM output_evidence
                     WHERE asset_type='quality_score_report'),
                    (SELECT COUNT(*) FROM output_evidence
                     WHERE asset_type='quality_score_report'
                       AND content->>'gate' IN (
                           'PASSED', 'PASSED_WITH_UNCALIBRATED'
                       )),
                    (SELECT COUNT(*) FROM output_evidence
                     WHERE asset_type='publish_gate_report'),
                    (SELECT COUNT(*) FROM output_evidence
                     WHERE asset_type='publish_gate_report'
                       AND content->>'gate'='PASSED'),
                    (SELECT COUNT(DISTINCT outcome.outcome_event_id)
                     FROM reader_outcome_event AS outcome
                     JOIN reader_exposure AS exposure
                       ON exposure.exposure_id=outcome.exposure_id
                     JOIN authority_operation_output_asset AS chapter_output
                       ON chapter_output.asset_version_id=
                          exposure.chapter_asset_version_id
                     JOIN related
                       ON related.operation_id=chapter_output.operation_id)
                """,
                parameters,
            )
            row = uow.cursor.fetchone()
            quality_rate = _rate(int(row[16]), int(row[15]))
            publish_rate = _rate(int(row[18]), int(row[17]))
            return _json_safe(
                {
                    "deployment_id": deployment_id,
                    "pack_id": deployment["pack_id"],
                    "pack_version": deployment["pack_version"],
                    "compilation_hash": deployment["compilation_hash"],
                    "binding_set_hash": deployment["binding_set_hash"],
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "book_id": book_id,
                    "workflow_node_id": workflow_node_id,
                    "agent_id": agent_id,
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "started_after": started_after,
                    "started_before": started_before,
                    "runtime_binding_count": int(row[0]),
                    "run_count": int(row[1]),
                    "success_count": int(row[2]),
                    "failure_count": int(row[3]),
                    "cancellation_count": int(row[4]),
                    "reconciliation_count": int(row[5]),
                    "retry_count": int(row[6]),
                    "domain_commit_count": int(row[7]),
                    "provider_call_count": int(row[8]),
                    "fixture_provider_call_count": int(row[9]),
                    "real_provider_call_count": int(row[10]),
                    "token_usage": int(row[11]),
                    "cost_amount": row[12],
                    "cost_evidence_count": int(row[13]),
                    "average_latency_ms": row[14],
                    "quality_gate_count": int(row[15]),
                    "quality_gate_pass_count": int(row[16]),
                    "quality_gate_pass_rate": quality_rate,
                    "publish_gate_count": int(row[17]),
                    "publish_gate_pass_count": int(row[18]),
                    "publish_gate_pass_rate": publish_rate,
                    "reader_outcome_sample_count": int(row[19]),
                    "real_provider_proven": int(row[10]) > 0,
                    "production_verified": False,
                    "currency_note": "inspect per-operation evidence for mixed currencies",
                }
            )

    def usage_metrics_by_dimensions(
        self,
        *,
        project_id: str,
        pack_id: str = "",
        pack_version: str = "",
        compilation_hash: str = "",
        deployment_id: str = "",
        binding_set_hash: str = "",
        workspace_id: str = "",
        book_id: str = "",
        workflow_node_id: str = "",
        agent_id: str = "",
        provider_id: str = "",
        model_id: str = "",
        started_after: datetime | None = None,
        started_before: datetime | None = None,
    ) -> dict[str, Any]:
        clauses = ["owner.project_id=%s"]
        parameters: list[Any] = [project_id]
        for column, value in (
            ("deployment.pack_id", pack_id),
            ("deployment.pack_version", pack_version),
            ("compilation.compilation_hash", compilation_hash),
            ("deployment.deployment_id", deployment_id),
            ("binding_set.binding_set_hash", binding_set_hash),
        ):
            if value:
                clauses.append(f"{column}=%s")
                parameters.append(value)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT deployment.deployment_id
                FROM authority_capability_pack_deployment AS deployment
                JOIN authority_capability_pack_compilation AS compilation
                  ON compilation.compilation_id=deployment.compilation_id
                JOIN authority_capability_pack_binding_set AS binding_set
                  ON binding_set.binding_set_id=deployment.binding_set_id
                JOIN authority_asset_version AS compiled_asset_version
                  ON compiled_asset_version.asset_version_id=
                     compilation.compiled_asset_version_id
                JOIN authority_asset AS owner
                  ON owner.asset_id=compiled_asset_version.asset_id
                WHERE {' AND '.join(clauses)}
                ORDER BY deployment.deployment_id
                """,
                parameters,
            )
            deployment_ids = [str(row[0]) for row in uow.cursor.fetchall()]
        records = [
            self.usage_metrics(
                item,
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                workflow_node_id=workflow_node_id,
                agent_id=agent_id,
                provider_id=provider_id,
                model_id=model_id,
                started_after=started_after,
                started_before=started_before,
            )
            for item in deployment_ids
        ]
        count_keys = (
            "runtime_binding_count",
            "run_count",
            "success_count",
            "failure_count",
            "cancellation_count",
            "reconciliation_count",
            "retry_count",
            "domain_commit_count",
            "provider_call_count",
            "fixture_provider_call_count",
            "real_provider_call_count",
            "token_usage",
            "cost_evidence_count",
            "quality_gate_count",
            "quality_gate_pass_count",
            "publish_gate_count",
            "publish_gate_pass_count",
            "reader_outcome_sample_count",
        )
        aggregate: dict[str, Any] = {
            key: sum(int(record[key]) for record in records) for key in count_keys
        }
        aggregate["cost_amount"] = sum(
            (Decimal(str(record["cost_amount"])) for record in records),
            Decimal("0"),
        )
        latency_weight = sum(int(record["run_count"]) for record in records)
        aggregate["average_latency_ms"] = (
            sum(
                Decimal(str(record["average_latency_ms"]))
                * int(record["run_count"])
                for record in records
            )
            / latency_weight
            if latency_weight
            else Decimal("0")
        )
        aggregate["quality_gate_pass_rate"] = _rate(
            aggregate["quality_gate_pass_count"],
            aggregate["quality_gate_count"],
        )
        aggregate["publish_gate_pass_rate"] = _rate(
            aggregate["publish_gate_pass_count"],
            aggregate["publish_gate_count"],
        )
        aggregate["real_provider_proven"] = (
            aggregate["real_provider_call_count"] > 0
        )
        aggregate["production_verified"] = False
        return _json_safe(
            {
                "dimensions": {
                    "project_id": project_id,
                    "pack_id": pack_id,
                    "pack_version": pack_version,
                    "compilation_hash": compilation_hash,
                    "deployment_id": deployment_id,
                    "binding_set_hash": binding_set_hash,
                    "workspace_id": workspace_id,
                    "book_id": book_id,
                    "workflow_node_id": workflow_node_id,
                    "agent_id": agent_id,
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "started_after": started_after,
                    "started_before": started_before,
                },
                "deployment_count": len(records),
                "aggregate": aggregate,
                "deployment_metrics": records,
                "effectiveness_status": "INSUFFICIENT_EVIDENCE",
            }
        )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _rate(passed: int, total: int) -> float | None:
    return round(passed / total, 6) if total else None


__all__ = ["CapabilityPackAuthorityQuery", "classify_deployment_drift"]
