"""Heterogeneous-corpus routing layered on the canonical Source Import runtime."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.deconstruction import ObservationScope, stable_hash
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocument,
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_import_repositories import SourceImportRepository
from novel_forge.storage.source_intelligence_repositories import SourceIntelligenceRepository

from .analysis_profiles import analysis_profile, plan_analysis_tasks
from .application import SourceImportApplication as _BaseSourceImportApplication
from .content_profile import SourceContentProfile, classify_source_content
from .definitions import (
    SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
    SOURCE_IMPORT_FILE_OPERATION,
)


class SourceImportApplication(_BaseSourceImportApplication):
    """Adds AUTO file-level profiling without creating a second import path."""

    def _admit_file_children(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        discovery_result: dict[str, Any],
    ) -> None:
        super()._admit_file_children(worker, job, discovery_result)
        if bool(discovery_result.get("snapshot_reused")):
            return
        snapshot_id = str(discovery_result["repository_snapshot_asset_version_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            current_job = repository.job_for_update(
                project_id=worker.project_id,
                import_job_id=str(job["import_job_id"]),
            )
            # A predecessor under the exact same import policy already owns the
            # unchanged rows' analysis. Cross-policy content reuse has no such
            # predecessor and must enter profiling/analysis without re-fetching.
            if current_job["previous_snapshot_asset_version_id"]:
                return
            rows = repository.snapshot_files(
                project_id=worker.project_id,
                snapshot_asset_version_id=snapshot_id,
            )
            transform_ids = sorted(
                {
                    str(row["source_transform_id"])
                    for row in rows
                    if row["status"] == "REUSED" and row.get("source_transform_id")
                }
            )
            if not transform_ids:
                return
            uow.cursor.execute(
                """
                SELECT transform.source_transform_id,
                       transform.source_document_id,
                       transform.asset_version_id,
                       transform.source_asset_version_id,
                       transform.status
                FROM authority_source_transform AS transform
                WHERE transform.project_id=%s
                  AND transform.source_transform_id=ANY(%s)
                ORDER BY transform.source_transform_id
                """,
                [worker.project_id, transform_ids],
            )
            transforms = {
                str(row[0]): {
                    "source_transform_id": str(row[0]),
                    "source_document_id": str(row[1]),
                    "source_transform_asset_version_id": str(row[2]),
                    "source_asset_version_id": str(row[3]),
                    "status": str(row[4]),
                }
                for row in uow.cursor.fetchall()
            }
        if set(transforms) != set(transform_ids) or any(
            item["status"] != "ACTIVE" for item in transforms.values()
        ):
            raise KernelError(
                "SOURCE_IMPORT_REUSED_TRANSFORM_INVALID",
                "reused Source content does not resolve to an active SourceTransform",
            )
        for transform_id in transform_ids:
            transform = transforms[transform_id]
            child = self._admit_child(
                definition_name=SOURCE_IMPORT_FILE_OPERATION,
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                actor_id=self.worker_id,
                idempotency_key=(
                    f"source.import.reused-analysis:{job['import_job_id']}:"
                    f"{transform_id}:{job['analysis_profile']}"
                ),
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=snapshot_id,
                parent_operation_id=worker.causation_id,
                payload={
                    "import_job_id": job["import_job_id"],
                    "repository_snapshot_asset_version_id": snapshot_id,
                    "reuse_existing_transform": True,
                    **transform,
                },
                input_assets=(
                    {
                        "asset_version_id": snapshot_id,
                        "role": "repository_snapshot",
                    },
                    {
                        "asset_version_id": transform[
                            "source_transform_asset_version_id"
                        ],
                        "role": "source_transform",
                    },
                ),
                ready=False,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                SourceImportRepository(uow.cursor).register_work(
                    {
                        "work_id": str(uuid4()),
                        "import_job_id": job["import_job_id"],
                        "project_id": worker.project_id,
                        "work_kind": "FILE",
                        "stable_key": f"reuse-analysis:{transform_id}",
                        "source_path": "",
                        "target_asset_version_id": transform[
                            "source_transform_asset_version_id"
                        ],
                        "operation_id": child,
                        "status": "PLANNED",
                        "result": {},
                        "failure": {},
                    }
                )
                uow.commit()
            self._ready_child(
                operation_id=child,
                project_id=worker.project_id,
                actor_id=self.worker_id,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=snapshot_id,
                reason="reused SourceTransform profiling and analysis ready",
            )

    def _admit_deconstruction_children(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        transform: dict[str, Any],
    ) -> None:
        requested_profile = str(job["analysis_profile"]).strip().lower()
        if requested_profile != "auto":
            self._admit_profiled_deconstruction_children(
                worker,
                job,
                transform,
                profile_asset_version_id="",
            )
            return

        snapshot_id = str(job["repository_snapshot_asset_version_id"])
        paths, normalized_text = self._profile_input(
            project_id=worker.project_id,
            repository_snapshot_asset_version_id=snapshot_id,
            source_transform_id=str(transform["source_transform_id"]),
        )
        profile = classify_source_content(
            paths=paths,
            text=normalized_text,
            requested_profile="auto",
        )
        profile_document = self._materialize_source_profile(
            worker,
            transform,
            profile,
            repository_snapshot_asset_version_id=snapshot_id,
        )
        transform["source_profile"] = profile.to_dict()
        transform["source_profile_asset_version_id"] = profile_document.asset_version_id
        transform["resolved_analysis_profile"] = profile.selected_analysis_profile
        if profile.manual_review_required or profile.selected_analysis_profile == "unknown":
            transform["analysis_blocked"] = {
                "code": "SOURCE_PROFILE_REVIEW_REQUIRED",
                "message": (
                    "AUTO source profiling could not select a sufficiently reliable "
                    "analysis methodology; re-import the same frozen repository snapshot "
                    "with an explicit analysis_profile after review"
                ),
                "confidence": profile.confidence,
                "source_profile_asset_version_id": profile_document.asset_version_id,
            }
            return

        routed_job = {**job, "analysis_profile": profile.selected_analysis_profile}
        self._admit_profiled_deconstruction_children(
            worker,
            routed_job,
            transform,
            profile_asset_version_id=profile_document.asset_version_id,
        )

    def _admit_profiled_deconstruction_children(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        transform: dict[str, Any],
        *,
        profile_asset_version_id: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset_version_id, chunk_index, byte_size, content_hash
                FROM authority_source_chunk
                WHERE project_id=%s AND source_transform_id=%s
                ORDER BY chunk_index
                """,
                [worker.project_id, transform["source_transform_id"]],
            )
            chunks = [
                {
                    "asset_version_id": row[0],
                    "chunk_index": row[1],
                    "byte_size": row[2],
                    "content_hash": row[3],
                }
                for row in uow.cursor.fetchall()
            ]
        tasks = plan_analysis_tasks(
            profile_id=str(job["analysis_profile"]),
            source_document_id=str(transform["source_document_id"]),
            chunks=chunks,
        )
        for task in tasks:
            scope = ObservationScope(
                scale=task.scale,
                range_start=task.range_start,
                range_end=task.range_end,
                source_document_ids=(str(transform["source_document_id"]),),
                label=task.label,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                current = SourceIntelligenceRepository(uow.cursor).current_observation(
                    project_id=worker.project_id,
                    scope_hash=scope.fingerprint,
                    analyzer_id=task.analyzer.analyzer_id,
                )
            if (
                current is not None
                and str(current["analyzer_contract_hash"]) == task.analyzer.fingerprint
            ):
                continue
            input_assets = [
                {
                    "asset_version_id": chunk_id,
                    "role": "source_chunk_evidence",
                }
                for chunk_id in task.source_chunk_asset_version_ids
            ]
            if profile_asset_version_id:
                input_assets.append(
                    {
                        "asset_version_id": profile_asset_version_id,
                        "role": "source_content_profile",
                    }
                )
            child = self._admit_child(
                definition_name=SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                actor_id=self.worker_id,
                idempotency_key=f"source.import.analysis:{task.stable_key}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=str(transform["source_transform_asset_version_id"]),
                parent_operation_id=worker.causation_id,
                payload={
                    "import_job_id": job["import_job_id"],
                    "source_document_id": transform["source_document_id"],
                    "source_transform_id": transform["source_transform_id"],
                    "source_transform_asset_version_id": transform[
                        "source_transform_asset_version_id"
                    ],
                    "source_profile_asset_version_id": profile_asset_version_id,
                    "resolved_analysis_profile": str(job["analysis_profile"]),
                    "analysis_task": task.to_dict(),
                },
                input_assets=tuple(input_assets),
                ready=False,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                SourceImportRepository(uow.cursor).register_work(
                    {
                        "work_id": str(uuid4()),
                        "import_job_id": job["import_job_id"],
                        "project_id": worker.project_id,
                        "work_kind": "DECONSTRUCTION",
                        "stable_key": task.stable_key,
                        "source_path": "",
                        "target_asset_version_id": transform[
                            "source_transform_asset_version_id"
                        ],
                        "operation_id": child,
                        "status": "PLANNED",
                        "result": {},
                        "failure": {},
                    }
                )
                uow.commit()
            self._ready_child(
                operation_id=child,
                project_id=worker.project_id,
                actor_id=self.worker_id,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=str(transform["source_transform_asset_version_id"]),
                reason="profile-routed Source deconstruction execution ready",
            )

    def _admit_mkaos_child(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        observation: dict[str, Any],
    ) -> None:
        if str(job["analysis_profile"]).strip().lower() != "auto":
            super()._admit_mkaos_child(worker, job, observation)
            return
        analyzer_id = str(observation.get("analyzer_id") or "")
        parts = analyzer_id.split(".")
        if len(parts) < 3 or parts[0] != "novel-forge":
            raise KernelError(
                "SOURCE_PROFILE_ANALYZER_IDENTITY_INVALID",
                "AUTO-routed Observation does not carry a profile-bound analyzer identity",
            )
        profile_id = parts[1]
        profile = analysis_profile(profile_id)
        if profile.profile_id == "auto":
            raise KernelError(
                "SOURCE_PROFILE_NOT_RESOLVED",
                "AUTO profile reached MKAOS without a resolved Source methodology",
            )
        observation["resolved_analysis_profile"] = profile.profile_id
        routed_job = {**job, "analysis_profile": profile.profile_id}
        super()._admit_mkaos_child(worker, routed_job, observation)

    def _execute_file(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            payload = dict(operation["command_payload"])["payload"]
        result = (
            self._execute_reused_transform_analysis(worker, dict(payload))
            if bool(payload.get("reuse_existing_transform"))
            else super()._execute_file(worker)
        )
        if not result.get("analysis_blocked"):
            return result
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            all_work = repository.list_work(
                project_id=worker.project_id,
                import_job_id=str(work["import_job_id"]),
            )
            unfinished = any(
                str(item["status"]) in {"PLANNED", "RUNNING", "FAILED_RETRYABLE"}
                for item in all_work
                if str(item["operation_id"]) != worker.causation_id
            )
            job = repository.job_for_update(
                project_id=worker.project_id,
                import_job_id=str(work["import_job_id"]),
            )
            if (
                not unfinished
                and job["status"] in {"PROCESSING", "PARTIALLY_COMPLETED"}
            ):
                repository.transition_job(
                    project_id=worker.project_id,
                    import_job_id=str(work["import_job_id"]),
                    expected=(str(job["status"]),),
                    target="AWAITING_GOVERNANCE",
                    failure={
                        "code": "SOURCE_PROFILE_REVIEW_REQUIRED",
                        "operation_id": worker.causation_id,
                        "source_profile": dict(result["source_profile"]),
                        "source_profile_asset_version_id": str(
                            result["source_profile_asset_version_id"]
                        ),
                    },
                )
            uow.commit()
        return result

    def _execute_reused_transform_analysis(
        self, worker: WorkerLeaseCommand, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            if work["status"] in {"SUCCEEDED", "REUSED"}:
                return dict(work["result"])
            job = repository.job_for_update(
                project_id=worker.project_id,
                import_job_id=str(work["import_job_id"]),
            )
            uow.cursor.execute(
                """
                SELECT transform.source_document_id, transform.asset_version_id,
                       transform.source_asset_version_id, transform.status
                FROM authority_source_transform AS transform
                WHERE transform.project_id=%s AND transform.source_transform_id=%s
                FOR SHARE OF transform
                """,
                [worker.project_id, str(payload["source_transform_id"])],
            )
            row = uow.cursor.fetchone()
            if row is None or str(row[3]) != "ACTIVE":
                raise KernelError(
                    "SOURCE_IMPORT_REUSED_TRANSFORM_INVALID",
                    "reused SourceTransform became unavailable before analysis",
                )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"),
                status="RUNNING",
            )
            uow.commit()
        result = {
            "source_document_id": str(row[0]),
            "source_transform_id": str(payload["source_transform_id"]),
            "source_transform_asset_version_id": str(row[1]),
            "source_asset_version_id": str(row[2]),
            "reused_source_transform": True,
            "provider_tokens": 0,
        }
        self._admit_deconstruction_children(worker, job, result)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status="SUCCEEDED",
                result=result,
            )
            if not result.get("analysis_blocked"):
                self._refresh_job(
                    repository, str(job["import_job_id"]), worker.project_id
                )
            uow.commit()
        return result

    def _materialize_source_profile(
        self,
        worker: WorkerLeaseCommand,
        transform: dict[str, Any],
        profile: SourceContentProfile,
        *,
        repository_snapshot_asset_version_id: str,
    ) -> AuthorityAssetDocument:
        content = {
            "schema_version": "source-content-profile.v1",
            "project_id": worker.project_id,
            "repository_snapshot_asset_version_id": (
                repository_snapshot_asset_version_id
            ),
            "source_document_id": str(transform["source_document_id"]),
            "source_transform_id": str(transform["source_transform_id"]),
            "source_transform_asset_version_id": str(
                transform["source_transform_asset_version_id"]
            ),
            "classification": profile.to_dict(),
            "source_policy": {
                "raw_source_text_included": False,
                "generation_context_allowed": False,
                "routing_evidence_only": True,
            },
            "lineage": {"created_by_operation_id": worker.causation_id},
        }
        digest = stable_hash(content).removeprefix("sha256:")
        logical_ref = f"source-intelligence/profiles/{digest}.json"
        query = AuthorityAssetQuery(self.database_url)
        try:
            existing = query.require(project_id=worker.project_id, logical_ref=logical_ref)
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            existing = None
        if existing is not None:
            if existing.asset_type != "source_content_profile" or existing.content != content:
                raise KernelError(
                    "SOURCE_PROFILE_REPLAY_CONFLICT",
                    "Source profile identity is already bound to different content",
                )
            return existing
        return AuthorityAssetWriter(self.database_url).materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=f"source-content-profile:{worker.project_id}:{digest}",
                asset_type="source_content_profile",
                schema_version="source-content-profile.v1",
                logical_ref=logical_ref,
                category="source-intelligence",
                output_key="source.import.content_profile",
                role="routing_evidence",
                content=content,
                qualification_policy="source-content-profile-v1",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=str(transform["source_transform_asset_version_id"]),
                eligibility="INELIGIBLE",
                governance="CLEAR",
            )
        )

    def _profile_input(
        self,
        *,
        project_id: str,
        repository_snapshot_asset_version_id: str,
        source_transform_id: str,
    ) -> tuple[tuple[str, ...], str]:
        if self.object_store_reader is None:
            raise KernelError(
                "SOURCE_IMPORT_OBJECT_READER_REQUIRED",
                "AUTO Source profiling requires the governed normalized object",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT file.path, transform.normalized_blob_id,
                       blob.actual_object_key, blob.actual_hash,
                       blob.actual_size, blob.status
                FROM authority_source_repository_file AS file
                JOIN authority_source_transform AS transform
                  ON transform.project_id=file.project_id
                 AND transform.source_transform_id=file.source_transform_id
                JOIN authority_blob AS blob
                  ON blob.blob_id=transform.normalized_blob_id
                WHERE file.project_id=%s
                  AND file.repository_snapshot_asset_version_id=%s
                  AND file.source_transform_id=%s
                  AND file.diff_state <> 'REMOVED'
                ORDER BY file.path
                """,
                [
                    project_id,
                    repository_snapshot_asset_version_id,
                    source_transform_id,
                ],
            )
            rows = uow.cursor.fetchall()
        if not rows:
            raise KernelError(
                "SOURCE_PROFILE_INPUT_MISSING",
                "Source profile cannot resolve its repository file and normalized Blob",
            )
        blob_identities = {
            (str(row[1]), str(row[2]), str(row[3]), int(row[4]), str(row[5]))
            for row in rows
        }
        if len(blob_identities) != 1:
            raise KernelError(
                "SOURCE_PROFILE_INPUT_CONFLICT",
                "one SourceTransform resolved to inconsistent normalized Blob identities",
            )
        _blob_id, object_key, content_hash, byte_size, status = next(
            iter(blob_identities)
        )
        if status != "AVAILABLE":
            raise KernelError(
                "SOURCE_PROFILE_BLOB_UNAVAILABLE",
                "normalized Source Blob is not AVAILABLE for profiling",
            )
        content = self.object_store_reader.read(
            object_key=object_key,
            expected_hash=content_hash,
            expected_size=byte_size,
        )
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise KernelError(
                "SOURCE_PROFILE_NORMALIZED_ENCODING_INVALID",
                "normalized Source content is not valid UTF-8",
            ) from exc
        return tuple(str(row[0]) for row in rows), text


__all__ = ["SourceImportApplication"]
