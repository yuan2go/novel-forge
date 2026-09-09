from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import admit_command_in_uow
from novel_forge.modules.source_authority import SourceAuthorityScheduler
from novel_forge.modules.source_authority.application import (
    RegisterSourceDocumentCommand,
    CommitSourceTransformCommand,
)
from novel_forge.modules.source_authority.corpus import (
    CorpusUse,
    RightsDeclaration,
    corpus_hash,
    corpus_identity,
    validate_corpus_action,
)
from novel_forge.modules.source_authority.corpus_application import CorpusCommand
from novel_forge.modules.source_authority.domain import SourceChunkCandidate
from novel_forge.modules.source_import.definitions import (
    SOURCE_IMPORT_DEFINITION_VERSION,
)
from novel_forge.modules.source_import.domain import SourceImportPolicy
from novel_forge.modules.source_import.profiling import SourceIntelligencePolicy
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_import_repositories import SourceImportRepository

from .contracts import IngestionManifest
from .mapping import parsed_source_work
from .parsers import compile_work_index

ACQUIRE_OPERATION = "source.import.corpus.acquire"
WORK_OPERATION = "source.import.corpus.work"


class CorpusIngestionRuntime:
    def __init__(self, application: Any) -> None:
        self.app = application

    def create(
        self,
        *,
        project_id: str,
        workspace_id: str,
        manifest: IngestionManifest,
        mode: str,
        run_key: str,
        actor_id: str,
        principal: Any,
        intelligence_policy: SourceIntelligencePolicy | None = None,
    ) -> dict[str, Any]:
        principal.require("source.authority.execute", project_id)
        if (
            mode not in {"IMPORT", "PREVIEW"}
            or not run_key.strip()
            or len(run_key) > 200
        ):
            raise ValueError("mode or run key is invalid")
        actor_id = principal.principal_id
        source_identity = corpus_identity(
            "source", project_id, manifest.source.kind, manifest.source.location
        )
        declaration = RightsDeclaration.model_validate(
            {
                **manifest.rights,
                "action": "declare_rights",
                "source_id": manifest.source_id or source_identity,
            }
        )
        self.app._register_definitions()
        policy = SourceImportPolicy(max_chunk_bytes=manifest.budget.max_chunk_bytes)
        intelligence = intelligence_policy or SourceIntelligencePolicy()
        requested_manifest = manifest.model_dump(mode="json")
        with AuthorityUnitOfWork(self.app.database_url, coordinate_nested=True) as uow:
            repository = SourceImportRepository(uow.cursor)
            repository.require_scope(project_id=project_id, workspace_id=workspace_id)
            previous = repository.corpus_frozen_request(
                project_id, f"corpus-ingestion:{project_id}:{mode}:{run_key}"
            )
            if previous:
                if previous["requested_manifest"] != requested_manifest or corpus_hash(
                    previous["intelligence_policy"]
                ) != corpus_hash(asdict(intelligence)):
                    raise KernelError(
                        "IDEMPOTENCY_PAYLOAD_CONFLICT",
                        "run key already binds different immutable inputs",
                    )
                manifest = IngestionManifest.model_validate(previous["manifest"])
            corpus = SourceAuthorityRepository(uow.cursor)
            corpus.corpus_authorization_lock(project_id)
            source_id = manifest.source_id or source_identity
            if (
                not previous
                and corpus.corpus_existing("source", project_id, source_id)
                and manifest.previous_snapshot_id is None
            ):
                source = corpus.corpus_source_lock(project_id, source_id)
                if (
                    source["workspace_id"] != workspace_id
                    or source["purpose"] != manifest.purpose.value
                    or source["retired"]
                ):
                    raise KernelError(
                        "CORPUS_IMPORT_SOURCE_SCOPE",
                        "current source is not active in this purpose/workspace",
                    )
                current_rights = corpus.corpus_latest("rights", project_id, source_id)
                if current_rights and not manifest.rights_id:
                    frozen_rights = corpus.corpus_record(
                        "rights", project_id, current_rights
                    )
                    if frozen_rights["declaration"] != declaration.model_dump(
                        mode="json"
                    ):
                        raise KernelError(
                            "CORPUS_ACQUISITION_RIGHTS_STALE",
                            "declare a new rights revision explicitly before importing",
                        )
                manifest = manifest.model_copy(
                    update={
                        "source_id": source_id,
                        "rights_id": manifest.rights_id or current_rights,
                        "previous_snapshot_id": corpus.corpus_latest(
                            "snapshot", project_id, source_id
                        ),
                    }
                )
            payload = {
                "manifest": manifest.model_dump(mode="json"),
                "requested_manifest": requested_manifest,
                "mode": mode,
                "intelligence_policy": asdict(intelligence),
            }
            admitted = admit_command_in_uow(
                uow,
                {
                    "definition_name": ACQUIRE_OPERATION,
                    "definition_version": SOURCE_IMPORT_DEFINITION_VERSION,
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "actor_id": actor_id,
                    "idempotency_scope": "project:source-import",
                    "idempotency_key": f"corpus-ingestion:{project_id}:{mode}:{run_key}",
                    "trace_id": f"corpus:{run_key}",
                    "span_id": str(uuid4()),
                    "correlation_id": f"corpus:{run_key}",
                    "causation_id": run_key,
                    "input_assets": [],
                    "input": {
                        "project_id": project_id,
                        "workspace_id": workspace_id,
                        "payload": payload,
                    },
                },
                context=self.app._admission_context(actor_id),
            )
            operation_id = str(admitted["operation_id"])
            job_id = f"source-import:{operation_id}"
            created = repository.register_job(
                {
                    "import_job_id": job_id,
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "source_type": "corpus_content",
                    "source_locator": {"manifest": manifest.model_dump(mode="json")},
                    "requested_ref": manifest.identity,
                    "import_policy": asdict(policy),
                    "import_policy_hash": policy.policy_hash,
                    "intelligence_policy": asdict(intelligence),
                    "intelligence_policy_hash": intelligence.policy_hash,
                    "analysis_override": {},
                    "mode": mode,
                    "status": "ADMITTED",
                    "discovery_operation_id": operation_id,
                    "counters": {},
                    "failure": {},
                }
            )
            if created:
                repository.register_work(
                    {
                        "work_id": str(uuid4()),
                        "import_job_id": job_id,
                        "project_id": project_id,
                        "work_kind": "DISCOVERY",
                        "stable_key": "corpus-acquisition",
                        "source_path": "",
                        "target_asset_version_id": None,
                        "operation_id": operation_id,
                        "status": "PLANNED",
                        "result": {},
                        "failure": {},
                    }
                )
            uow.commit()
        self.app._ready_child(
            operation_id=operation_id,
            project_id=project_id,
            actor_id=actor_id,
            trace_id=f"corpus:{run_key}",
            correlation_id=f"corpus:{run_key}",
            causation_id=run_key,
            reason="frozen Corpus ingestion ready",
        )
        return {
            "import_job_id": job_id,
            "operation_id": operation_id,
            "manifest_hash": manifest.identity,
            "replayed": admitted.get("replayed", False),
            "mode": mode,
        }

    def _load(
        self, worker: Any
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        with AuthorityUnitOfWork(self.app.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            job = repository.job_for_update(
                project_id=worker.project_id, import_job_id=work["import_job_id"]
            )
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            if job["status"] in {"CANCELLED", "PAUSED"}:
                raise KernelError(
                    "CORPUS_IMPORT_CANCELLED",
                    "cancelled or paused import cannot start another stage",
                )
            if work["status"] not in {"SUCCEEDED", "REUSED"}:
                repository.update_work(
                    project_id=worker.project_id,
                    operation_id=worker.causation_id,
                    expected=("PLANNED", "QUEUED", "RUNNING", "FAILED_RETRYABLE"),
                    status="RUNNING",
                )
            if job["status"] == "ADMITTED":
                repository.transition_job(
                    project_id=worker.project_id,
                    import_job_id=job["import_job_id"],
                    expected=("ADMITTED",),
                    target="PROCESSING",
                )
            uow.commit()
        return work, job, dict(operation["command_payload"]["payload"])

    def _corpus(
        self, worker: Any, job: dict[str, Any], action: dict[str, Any]
    ) -> dict[str, Any]:
        command = CorpusCommand(
            project_id=worker.project_id,
            workspace_id=job["workspace_id"],
            actor_id=self.app.worker_id,
            idempotency_key=corpus_hash(action),
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            action=validate_corpus_action(action),
        )
        admitted = self.app.source_authority.admit_corpus(command, parent_worker=worker)
        result = SourceAuthorityScheduler(
            self.app.source_authority, worker_id=f"{self.app.worker_id}:corpus"
        ).run_or_recover(
            operation_id=admitted["operation_id"], project_id=worker.project_id
        )
        return result

    def _content(
        self,
        worker: Any,
        snapshot_id: str,
        edition_id: str | None,
        effect_id: str,
        blob_id: str,
        role: str,
        path: str,
        pointer: dict[str, Any],
        locator: dict[str, Any],
    ) -> None:
        with AuthorityUnitOfWork(self.app.database_url) as uow:
            require_current_fence(uow, worker)
            SourceAuthorityRepository(uow.cursor).corpus_bind_content(
                {
                    "project_id": worker.project_id,
                    "snapshot_id": snapshot_id,
                    "edition_id": edition_id,
                    "blob_id": blob_id,
                    "role": role,
                    "path": path,
                    "content_hash": pointer["checksum"],
                    "byte_size": pointer["size_bytes"],
                    "locator": locator,
                    "acquisition_effect_id": effect_id,
                    "created_by_operation_id": worker.causation_id,
                }
            )
            uow.commit()

    def _authorize_acquisition(
        self, worker: Any, manifest: IngestionManifest, workspace_id: str
    ) -> None:
        source_id = manifest.source_id or corpus_identity(
            "source", worker.project_id, manifest.source.kind, manifest.source.location
        )
        declaration = RightsDeclaration.model_validate(
            {**manifest.rights, "action": "declare_rights", "source_id": source_id}
        )
        with AuthorityUnitOfWork(self.app.database_url) as uow:
            require_current_fence(uow, worker)
            SourceAuthorityRepository(uow.cursor).require_corpus_acquisition(
                worker.project_id,
                source_id=source_id,
                workspace_id=workspace_id,
                source_kind=manifest.source.kind,
                location=manifest.source.location,
                rights_id=manifest.rights_id,
                declaration=declaration,
                purpose=manifest.purpose,
            )

    def acquire(self, worker: Any) -> dict[str, Any]:
        work, job, payload = self._load(worker)
        if work["status"] in {"SUCCEEDED", "REUSED"}:
            return work["result"]
        manifest = IngestionManifest.model_validate(payload["manifest"])
        if self.app.corpus_adapter is None:
            raise KernelError(
                "CORPUS_ACQUISITION_RUNTIME_REQUIRED",
                "Corpus worker requires its governed acquisition cache and allowed source roots",
            )
        receipt = self.app._execute_external_effect(
            worker=worker,
            effect_type="corpus.acquire",
            capability="source.remote.fetch",
            stable_key=f"corpus-acquire:{worker.causation_id}",
            request_payload={
                "manifest": manifest.model_dump(mode="json"),
                "mode": job["mode"],
            },
            adapter=self.app.corpus_adapter,
            max_attempts=1,
            timeout_seconds=manifest.budget.timeout_seconds,
            pre_send_assertion=(
                lambda: self._authorize_acquisition(
                    worker, manifest, job["workspace_id"]
                )
            )
            if job["mode"] == "IMPORT"
            else None,
        )
        with AuthorityUnitOfWork(self.app.database_url) as uow:
            uow.cursor.execute(
                "SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s AND capability='source.remote.fetch' AND status='SUCCEEDED'",
                [worker.causation_id],
            )
            effect_id = str(uow.cursor.fetchone()[0])
        if job["mode"] == "PREVIEW":
            return self._finish(
                worker,
                job,
                {
                    "stage": "PREVIEW",
                    "receipt": receipt,
                    "content_imported": False,
                    "analysis_called": False,
                },
            )
        if (
            not receipt["content_verified"]
            or receipt["manifest_hash"] != manifest.identity
        ):
            raise KernelError(
                "CORPUS_ACQUISITION_UNVERIFIED", "receipt differs from frozen Manifest"
            )
        if manifest.source_id:
            source_id, rights_id = manifest.source_id, manifest.rights_id
        else:
            source_id = self._corpus(
                worker,
                job,
                {
                    "action": "register_source",
                    "source_kind": manifest.source.kind,
                    "external_identity": manifest.source.location,
                    "purpose": manifest.purpose.value,
                },
            )["source_id"]
            rights_id = self._corpus(
                worker,
                job,
                {**manifest.rights, "action": "declare_rights", "source_id": source_id},
            )["rights_id"]
        source_metadata = manifest.source.model_dump(mode="json")
        if manifest.source.kind == "GITHUB":
            source_metadata.update(
                repository=manifest.source.location, commit=manifest.source.revision
            )
        snapshot = self._corpus(
            worker,
            job,
            {
                "action": "freeze_snapshot",
                "source_id": source_id,
                "rights_id": rights_id,
                "previous_snapshot_id": manifest.previous_snapshot_id,
                "manifest": {
                    "origin_uri": manifest.source.location,
                    "external_version": manifest.source.revision
                    or receipt["acquisition_identity"],
                    "format": manifest.parser.format,
                    "checksum": receipt["acquisition_identity"],
                    "adapter_profile": manifest.source.kind,
                    "adapter_contract_version": manifest.adapter_version,
                    "metadata": {
                        "source": source_metadata,
                        "parser": manifest.parser.model_dump(mode="json"),
                        "ingestion_manifest_hash": manifest.identity,
                    },
                },
                "acquisition": {
                    "locator": manifest.source.location,
                    "acquired_at": receipt["acquired_at"],
                    "receipt_ref": effect_id,
                    "checksum": receipt["acquisition_identity"],
                },
            },
        )
        snapshot_id = snapshot["snapshot_id"]
        with AuthorityUnitOfWork(self.app.database_url) as uow:
            require_current_fence(uow, worker)
            uow.cursor.execute(
                "UPDATE authority_source_import_job SET corpus_snapshot_id=%s WHERE import_job_id=%s AND (corpus_snapshot_id IS NULL OR corpus_snapshot_id=%s)",
                [snapshot_id, job["import_job_id"], snapshot_id],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "CORPUS_IMPORT_SNAPSHOT_CONFLICT",
                    "job already binds another acquisition",
                )
            uow.commit()
        files = self.app.corpus_adapter.parse_files(receipt, manifest)
        for item in receipt["files"] + [f for f in files if f.get("container_path")]:
            blob = self.app._put_blob(
                worker,
                content=Path(item["cache_path"]),
                content_hash=item["checksum"],
                media_type="application/octet-stream",
                purpose="corpus-acquisition",
            )
            item["blob_id"] = blob
            locator = {
                key: value
                for key, value in item.items()
                if key not in {"cache_path", "parser"}
            }
            self._content(
                worker,
                snapshot_id,
                None,
                effect_id,
                blob,
                "ACQUISITION",
                (item.get("container_path", "") + "!" + item["path"]),
                item,
                locator,
            )
        raw_lookup = {
            (item.get("container_path"), item["path"]): item
            for item in files + receipt["files"]
            if "blob_id" in item
        }
        for item in files:
            if "blob_id" not in item:
                item["blob_id"] = raw_lookup[
                    (item.get("container_path"), item["path"])
                ]["blob_id"]
        root = (
            self.app.corpus_adapter.root
            / "parsing"
            / hashlib.sha256(worker.causation_id.encode()).hexdigest()
        )
        parsed = compile_work_index(files, manifest.parser, manifest.budget, root)
        child_operations = []
        for pointer in parsed["works"]:
            self._corpus(
                worker,
                job,
                {
                    "action": "import_batch",
                    "snapshot_id": snapshot_id,
                    "batch_key": corpus_hash(
                        {
                            "parser": manifest.parser.model_dump(mode="json"),
                            "work": pointer["work_id"],
                            "edition": pointer["edition_id"],
                        }
                    ),
                    "entries": [
                        {
                            "external_work_id": pointer["work_id"],
                            "external_edition_id": pointer["edition_id"],
                            "title": pointer["title"],
                            "checksum": pointer["checksum"],
                            "locator": manifest.source.location,
                            "metadata": {
                                "completeness": pointer["completeness"],
                                "unit_count": pointer["unit_count"],
                                "parser": manifest.parser.version,
                            },
                        }
                    ],
                },
            )
            edition_id = corpus_identity(
                "edition",
                snapshot_id,
                corpus_identity("book", source_id, pointer["work_id"]),
                pointer["edition_id"],
            )
            with AuthorityUnitOfWork(self.app.database_url) as uow:
                permission = SourceAuthorityRepository(uow.cursor).corpus_edition_uses(
                    worker.project_id,
                    (edition_id,),
                    CorpusUse.LOCAL_PROCESSING,
                    require_bridge=False,
                )[edition_id]
            if permission["decision"] != "ALLOW":
                child_operations.append(
                    {
                        "edition_id": edition_id,
                        "status": "BLOCKED",
                        "reasons": permission["reasons"],
                    }
                )
                continue
            blob_id = self.app._put_blob(
                worker,
                content=Path(pointer["cache_path"]),
                content_hash=pointer["checksum"],
                media_type="application/json",
                purpose="corpus-parsed-work",
            )
            self._content(
                worker,
                snapshot_id,
                edition_id,
                effect_id,
                blob_id,
                "PARSED_WORK",
                edition_id,
                pointer,
                {
                    "external_work_id": pointer["work_id"],
                    "parser_version": parsed["parser_version"],
                },
            )
            child_payload = {
                "manifest": manifest.model_dump(mode="json"),
                "snapshot_id": snapshot_id,
                "edition_id": edition_id,
                "rights_id": rights_id,
                "acquisition_effect_id": effect_id,
                "parsed_blob_id": blob_id,
                "parsed_hash": pointer["checksum"],
                "parsed_size": pointer["size_bytes"],
            }
            child = self.app._admit_child(
                definition_name=WORK_OPERATION,
                project_id=worker.project_id,
                workspace_id=job["workspace_id"],
                actor_id=self.app.worker_id,
                idempotency_key=f"corpus-work:{edition_id}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=worker.causation_id,
                parent_operation_id=worker.causation_id,
                payload=child_payload,
                input_assets=(),
                ready=False,
            )
            with AuthorityUnitOfWork(self.app.database_url) as uow:
                require_current_fence(uow, worker)
                SourceImportRepository(uow.cursor).register_work(
                    {
                        "work_id": str(uuid4()),
                        "import_job_id": job["import_job_id"],
                        "project_id": worker.project_id,
                        "work_kind": "WORK",
                        "stable_key": edition_id,
                        "source_path": pointer["work_id"],
                        "target_asset_version_id": None,
                        "operation_id": child,
                        "status": "PLANNED",
                        "result": {},
                        "failure": {},
                    }
                )
                uow.commit()
            self.app._ready_child(
                operation_id=child,
                project_id=worker.project_id,
                actor_id=self.app.worker_id,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=worker.causation_id,
                reason="verified Corpus Edition ready for Source mapping",
            )
            child_operations.append(
                {"edition_id": edition_id, "operation_id": child, "status": "READY"}
            )
        return self._finish(
            worker,
            job,
            {
                "stage": "ACQUIRED",
                "source_id": source_id,
                "snapshot_id": snapshot_id,
                "rights_id": rights_id,
                "acquisition_effect_id": effect_id,
                "actual_bytes": receipt["actual_bytes"],
                "verified_files": len(receipt["files"]),
                "parsed_records": parsed["records"],
                "work_count": parsed["work_count"],
                "children": child_operations,
                "analysis_called": False,
            },
        )

    def _finish(
        self, worker: Any, job: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.app.database_url) as uow:
            require_current_fence(uow, worker)
            SourceImportRepository(uow.cursor).update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING", "PLANNED", "QUEUED"),
                status="SUCCEEDED",
                result=result,
            )
            self.app._record_event(
                uow,
                worker,
                aggregate_type="authority_source_import_job",
                aggregate_id=job["import_job_id"],
                event_type="authority.source.corpus.ingestion.stage_completed",
                payload=result,
            )
            repository = SourceImportRepository(uow.cursor)
            if result.get("stage") == "PREVIEW":
                repository.transition_job(
                    project_id=worker.project_id,
                    import_job_id=job["import_job_id"],
                    expected=("PROCESSING", "PAUSED"),
                    target="PREVIEWED",
                )
            else:
                self.app._refresh_job(
                    repository, job["import_job_id"], worker.project_id
                )
            uow.commit()
        return result

    def process_work(self, worker: Any) -> dict[str, Any]:
        work, job, payload = self._load(worker)
        if work["status"] in {"SUCCEEDED", "REUSED"}:
            return work["result"]
        if payload.get("reprocess"):
            from .reprocessing import prepare_reprocessing

            payload = prepare_reprocessing(self, worker, payload)
            if payload.get("reuse_result"):
                return self._finish(worker, job, payload["reuse_result"])
        manifest = IngestionManifest.model_validate(payload["manifest"])
        processing_key = corpus_identity(
            "processing", payload["edition_id"], payload["parsed_hash"]
        )
        edition_id, snapshot_id, effect_id = (
            payload["edition_id"],
            payload["snapshot_id"],
            payload["acquisition_effect_id"],
        )
        binding_key = processing_key if manifest.parser.normalization else edition_id
        with AuthorityUnitOfWork(self.app.database_url) as uow:
            permission = SourceAuthorityRepository(
                uow.cursor
            ).require_corpus_edition_use(
                worker.project_id,
                edition_id,
                CorpusUse.LOCAL_PROCESSING,
                require_bridge=False,
            )
            blob = uow.repositories.asset_blobs.blob_for_update(
                payload["parsed_blob_id"]
            )
        if int(blob["actual_size"]) > manifest.budget.memory_bytes // 4:
            raise KernelError(
                "CORPUS_WORK_SIZE_LIMIT", "parsed work exceeds frozen memory allowance"
            )
        document = json.loads(
            self.app.object_store_reader.read(
                object_key=blob["actual_object_key"],
                expected_hash=payload["parsed_hash"],
                expected_size=payload["parsed_size"],
            )
        )
        parsed = parsed_source_work(
            document,
            edition_id=edition_id,
            snapshot_id=snapshot_id,
            max_chunk_bytes=manifest.budget.max_chunk_bytes,
        )
        raw = json.dumps(
            {
                "schema_version": "corpus-source-bundle.v1",
                "edition_id": edition_id,
                "snapshot_id": snapshot_id,
                "acquisition_effect_id": effect_id,
                "parsed_blob_id": payload["parsed_blob_id"],
                "parsed_hash": payload["parsed_hash"],
                "parser_hash": document["parser_hash"],
                "units": [u.manifest_entry() for u in parsed.units],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        raw_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        raw_blob = self.app._put_blob(
            worker,
            content=raw,
            content_hash=raw_hash,
            media_type="application/json",
            purpose="corpus-source-bundle",
        )
        self._content(
            worker,
            snapshot_id,
            edition_id,
            effect_id,
            raw_blob,
            "RAW_BUNDLE",
            edition_id,
            {"checksum": raw_hash, "size_bytes": len(raw)},
            {
                "parsed_blob_id": payload["parsed_blob_id"],
                "offset_semantics": "DERIVED_UNICODE_AND_UTF8",
            },
        )
        declaration = RightsDeclaration.model_validate(permission["declaration"])
        source = self.app.source_authority.execute(
            RegisterSourceDocumentCommand(
                project_id=worker.project_id,
                workspace_id=job["workspace_id"],
                blob_id=raw_blob,
                title=document["title"],
                source_kind="corpus_work_bundle",
                source_uri=f"corpus:{edition_id}",
                rights_authorization="unknown",
                license_name=declaration.dataset_license,
                copyright_boundary="Corpus rights and per-use admission required; no raw generation",
                actor_id=self.app.worker_id,
                idempotency_key=f"corpus-source:{binding_key}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                corpus_edition_id=edition_id,
            )
        )
        normalized_blob = self.app._put_blob(
            worker,
            content=parsed.normalized.text.encode(),
            content_hash=parsed.normalized.content_hash,
            media_type="text/plain",
            purpose="corpus-normalized-"
            + hashlib.sha256(binding_key.encode()).hexdigest(),
        )
        self._content(
            worker,
            snapshot_id,
            edition_id,
            effect_id,
            normalized_blob,
            "NORMALIZED",
            edition_id,
            {
                "checksum": parsed.normalized.content_hash,
                "size_bytes": parsed.normalized.byte_size,
            },
            {"raw_blob_id": raw_blob, "parser_hash": document["parser_hash"]},
        )
        candidates = []
        for chunk in parsed.chunks:
            chunk_blob = self.app._put_blob(
                worker,
                content=chunk.content,
                content_hash=chunk.content_hash,
                media_type="text/plain",
                purpose="corpus-chunk-"
                + hashlib.sha256(binding_key.encode()).hexdigest()
                + f"-{chunk.chunk_index}",
            )
            self._content(
                worker,
                snapshot_id,
                edition_id,
                effect_id,
                chunk_blob,
                "CHUNK",
                f"{edition_id}:{chunk.chunk_index}",
                {"checksum": chunk.content_hash, "size_bytes": chunk.byte_size},
                {
                    "normalized_byte_start": chunk.normalized_byte_start,
                    "normalized_byte_end": chunk.normalized_byte_end,
                },
            )
            candidates.append(
                SourceChunkCandidate(
                    chunk_index=chunk.chunk_index,
                    blob_id=chunk_blob,
                    content_hash=chunk.content_hash,
                    byte_size=chunk.byte_size,
                    character_count=chunk.character_count,
                    token_count=chunk.token_count,
                    source_byte_start=chunk.normalized_byte_start,
                    source_byte_end=chunk.normalized_byte_end,
                )
            )
        policy = SourceImportPolicy(**job["import_policy"])
        transform = self.app.source_authority.execute_transform(
            CommitSourceTransformCommand(
                project_id=worker.project_id,
                workspace_id=job["workspace_id"],
                source_document_id=source["source_document_id"],
                normalization_version=parsed.normalized.normalization_version,
                chunking_version=policy.chunking_version,
                chunking_policy_hash=policy.chunking_policy_hash,
                chunks=tuple(candidates),
                actor_id=self.app.worker_id,
                idempotency_key=f"corpus-transform:{binding_key}:{policy.chunking_policy_hash}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                normalized_blob_id=normalized_blob,
                normalized_content_hash=parsed.normalized.content_hash,
                normalized_byte_size=parsed.normalized.byte_size,
            )
        )
        from .similarity import fingerprint
        from .integrity import assess_integrity
        from .contracts import NormalizationProfile

        assessment = document.get("integrity")
        if assessment is None:
            assessment = assess_integrity(
                document["units"],
                manifest.parser.model_copy(
                    update={
                        "normalization": NormalizationProfile(
                            segmentation="EXPLICIT", min_body_chars=1
                        )
                    }
                ),
            )
            assessment["coverage"] = document["completeness"]
            assessment["structure_usable"] = (
                document["completeness"] != "REVIEW_REQUIRED"
            )
            assessment["evidence_ceiling"] = "FROZEN_V1_STRUCTURE_CONTRACT"
        signature = fingerprint(
            r["text"] for r in document["units"] if not r.get("excluded_from_analysis")
        )
        metadata = assessment.get("metadata", {})
        if metadata.get("title") and metadata.get("author"):
            signature["buckets"].append(
                "title-author:"
                + corpus_hash(
                    {"title": metadata["title"], "author": metadata["author"]}
                )
            )
        signature["buckets"].extend(
            "external:" + corpus_hash(value)
            for value in metadata.get("external_work_ids", [])
        )
        with AuthorityUnitOfWork(self.app.database_url, coordinate_nested=True) as uow:
            require_current_fence(uow, worker)
            materialized = self.app._materialize_source_work(
                worker=worker,
                job=job,
                snapshot={
                    "corpus_edition_id": edition_id,
                    "repository_identity": f"corpus:{permission['source_id']}",
                    "repository_url": manifest.source.location,
                },
                parsed=parsed,
                source_result=source,
                transform=transform,
                raw_blob_id=raw_blob,
                raw_bundle_hash=raw_hash,
                raw_bundle_size=len(raw),
                normalized_blob_id=normalized_blob,
            )
            repository = SourceAuthorityRepository(uow.cursor)
            repository.require_corpus_edition_use(
                worker.project_id,
                edition_id,
                CorpusUse.LOCAL_PROCESSING,
                require_bridge=False,
            )
            repository.corpus_bind_bridge(
                {
                    "project_id": worker.project_id,
                    "edition_id": edition_id,
                    "source_document_id": source["source_document_id"],
                    "source_transform_id": transform["source_transform_id"],
                    "source_work_asset_version_id": materialized[
                        "source_work_asset_version_id"
                    ],
                    "rights_id": payload["rights_id"],
                    "parser_hash": document["parser_hash"],
                    "normalized_hash": parsed.normalized.content_hash,
                    "policy_version": "corpus-use-policy.v1",
                    "evidence": {
                        "completeness": document["completeness"],
                        "parsed_blob_id": payload["parsed_blob_id"],
                        "acquisition_effect_id": effect_id,
                        "manifest_hash": manifest.identity,
                        "scope": "CONTENT_AND_LINEAGE_ONLY",
                        "knowledge_approved": False,
                    },
                    "created_by_operation_id": worker.causation_id,
                }
            )
            repository.corpus_insert_processing(
                {
                    "processing_id": processing_key,
                    "project_id": worker.project_id,
                    "edition_id": edition_id,
                    "parent_id": document.get("processing_parent"),
                    "source_work_asset_version_id": materialized[
                        "source_work_asset_version_id"
                    ],
                    "source_document_id": source["source_document_id"],
                    "parsed_blob_id": payload["parsed_blob_id"],
                    "input_hash": payload["parsed_hash"],
                    "parser_hash": document["parser_hash"],
                    "normalized_hash": parsed.normalized.content_hash,
                    "profile": manifest.parser.model_dump(mode="json"),
                    "assessment": assessment,
                    "fingerprint": signature,
                    "buckets": signature["buckets"],
                    "created_by_operation_id": worker.causation_id,
                }
            )
            result = {
                **materialized,
                "stage": "CONTENT_IMPORTED",
                "processing_id": processing_key,
                "structure_usable": assessment["structure_usable"],
                "edition_id": edition_id,
                "snapshot_id": snapshot_id,
                "source_document_id": source["source_document_id"],
                "source_asset_version_id": source["asset_version_id"],
                "source_transform_id": transform["source_transform_id"],
                "source_transform_asset_version_id": transform["asset_version_id"],
                "chunk_count": transform["chunk_count"],
                "unit_count": len(parsed.units),
                "completeness": document["completeness"],
                "normalized_hash": parsed.normalized.content_hash,
                "analysis_scheduled": False,
                "knowledge_approved": False,
                "provider_model_calls": 0,
            }
            if manifest.analyze:
                SourceAuthorityRepository(uow.cursor).require_corpus_documents(
                    worker.project_id,
                    (source["source_document_id"],),
                    CorpusUse.SOURCE_ANALYSIS,
                )
                self.app._admit_profiling_child(worker, job, result, source_paths=())
                result["analysis_scheduled"] = True
            finished = self._finish(worker, job, result)
            uow.commit()
            return finished
