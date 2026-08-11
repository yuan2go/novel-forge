"""Heterogeneous-corpus routing layered on the canonical Source Import runtime."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_import_repositories import SourceImportRepository

from .analysis_profiles import analysis_profile
from .application import SourceImportApplication as _BaseSourceImportApplication
from .content_profile import classify_source_content


class SourceImportApplication(_BaseSourceImportApplication):
    """Adds AUTO file-level profiling without creating a second import path."""

    def _admit_deconstruction_children(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        transform: dict[str, Any],
    ) -> None:
        requested_profile = str(job["analysis_profile"]).strip().lower()
        if requested_profile != "auto":
            super()._admit_deconstruction_children(worker, job, transform)
            return

        paths, normalized_text = self._profile_input(
            project_id=worker.project_id,
            source_transform_id=str(transform["source_transform_id"]),
        )
        profile = classify_source_content(
            paths=paths,
            text=normalized_text,
            requested_profile="auto",
        )
        transform["source_profile"] = profile.to_dict()
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
            }
            return

        routed_job = {**job, "analysis_profile": profile.selected_analysis_profile}
        super()._admit_deconstruction_children(worker, routed_job, transform)

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
        result = super()._execute_file(worker)
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
                    },
                )
            uow.commit()
        return result

    def _profile_input(
        self, *, project_id: str, source_transform_id: str
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
                WHERE file.project_id=%s AND file.source_transform_id=%s
                  AND file.diff_state <> 'REMOVED'
                ORDER BY file.path
                """,
                [project_id, source_transform_id],
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
