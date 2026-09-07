from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Callable
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.story_formation_repositories import StoryFormationRepository

from .formation_domain import (
    STORY_FORMATION_POLICY_VERSION,
    StoryFormationInput,
    FormationLayerInput,
)


STORY_FORMATION_DEFINITION_VERSION = "1.1.0"
STORY_FORMATION_HANDLER = "novel_forge.book_design.story_formation"
STORY_FORMATION_OPERATIONS = frozenset(
    {
        "story.formation.admit",
        "story.formation.advance",
        "story.formation.approve_book_design",
        "story.formation.resume",
        "story.formation.abort",
    }
)


@dataclass(frozen=True, slots=True)
class StartStoryFormationCommand:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    expected_book_version: int
    stable_idempotency_key: str
    trace_id: str
    correlation_id: str
    frozen_input: StoryFormationInput


@dataclass(frozen=True, slots=True)
class StoryFormationAdmission:
    formation_run_id: str
    root_operation_id: str
    runtime_job_id: str
    lifecycle: str
    replayed: bool


class StoryFormationApplication:

    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        fault_injector: Callable[[str], None] | None = None,
        generation: Any = None,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("Story Formation requires PostgreSQL/build identity")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector
        self.generation = generation
        self.runtime_jobs = RuntimeJobAuthority(database_url)

    def admit(
        self, command: StartStoryFormationCommand, *, principal: Principal
    ) -> StoryFormationAdmission:
        principal.require("book.authority.execute", command.project_id)
        if principal.principal_id != command.actor_id:
            raise KernelError(
                "ACTOR_IDENTITY_INVALID",
                "Story Formation actor differs from authenticated Principal",
            )
        if (
            command.expected_book_version < 0
            or any(
                not value.strip()
                for value in (
                    command.project_id,
                    command.workspace_id,
                    command.book_id,
                    command.actor_id,
                    command.stable_idempotency_key,
                    command.trace_id,
                    command.correlation_id,
                )
            )
        ):
            raise ValueError("Story Formation command is incomplete")
        identity = "\x00".join(
            (
                command.project_id,
                command.book_id,
                command.stable_idempotency_key,
            )
        ).encode("utf-8")
        formation_run_id = "story-formation:" + hashlib.sha256(identity).hexdigest()
        self._register_definitions()
        executed = execute_transaction_command(
            self.database_url,
            {
                "definition_name": "story.formation.admit",
                "definition_version": STORY_FORMATION_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "book_id": command.book_id,
                "actor_id": command.actor_id,
                "idempotency_scope": "book:story-formation",
                "idempotency_key": command.stable_idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "book_id": command.book_id,
                    "formation_run_id": formation_run_id,
                    "expected_book_version": command.expected_book_version,
                    "stable_idempotency_key": command.stable_idempotency_key,
                    "frozen_input": command.frozen_input.to_dict(),
                    "frozen_input_digest": command.frozen_input.digest,
                },
                "input_assets": list(
                    self._input_assets(command.project_id, command.frozen_input)
                ),
            },
            context=self._context(command.actor_id),
            handler=self._execute_transaction,
            fault_injector=self.fault_injector,
        )
        run = self.require(formation_run_id)
        job = (
            self._schedule(run)
            if run["lifecycle"] in {"ADMITTED", "RUNNING"}
            else self._latest_job(formation_run_id)
        )
        return StoryFormationAdmission(
            formation_run_id=formation_run_id,
            root_operation_id=str(executed["operation_id"]),
            runtime_job_id=str(job["runtime_job_id"]),
            lifecycle=str(run["lifecycle"]),
            replayed=bool(executed["replayed"]),
        )

    def advance(self, formation_run_id: str, *, principal: Principal) -> dict[str, Any]:
        run = self.require(formation_run_id)
        return self.advance_expected(
            formation_run_id,
            expected_stage=str(run["current_stage"]),
            expected_version=int(run["version"]),
            principal=principal,
        )

    def advance_expected(
        self,
        formation_run_id: str,
        *,
        expected_stage: str,
        expected_version: int,
        principal: Principal,
    ) -> dict[str, Any]:

        run = self.require(formation_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        if run["lifecycle"] in {"READY", "ABORTED"} and (
            str(run["current_stage"]) == expected_stage
            and int(run["version"]) == expected_version
        ):
            return run
        if not expected_stage.strip() or expected_version < 0:
            raise KernelError(
                "STORY_FORMATION_JOB_INVALID",
                "Formation RuntimeJob has no frozen stage/version",
            )
        frozen = self._frozen_input(formation_run_id)
        generated_layer = None
        generated_design = None
        if frozen.creative_brief_asset_version_id:
            if self.generation is None:
                raise KernelError("STORY_FORMATION_GENERATION_NOT_CONFIGURED", "Formation brief generation is not wired")
            if expected_stage == "BOOK_DESIGN":
                generated_design = self.generation.prepare_design(run, frozen, principal=principal)
            else:
                generated_layer = self.generation.prepare_layer(run, frozen, principal=principal)
        executed = self._control(
            run=run,
            principal=principal,
            definition_name="story.formation.advance",
            idempotency_key=(
                f"{formation_run_id}:advance:{expected_stage}:{expected_version}"
            ),
            payload={
                "stage": expected_stage,
                "expected_version": expected_version,
                **({"generated_layer": generated_layer.to_dict()} if generated_layer else {}),
                **({"generated_book_design": generated_design} if generated_design else {}),
            },
            frozen_input=frozen,
            additional_input_assets=(
                ({"asset_version_id": generated_layer.asset_version_id, "content_hash": generated_layer.content_hash},
                 {"asset_version_id": generated_layer.qualification_evidence_asset_version_id, "content_hash": generated_layer.qualification_hash})
                if generated_layer else (generated_design,) if generated_design else ()
            ),
        )
        return {
            **self.require(formation_run_id),
            "operation_id": executed["operation_id"],
            "replayed": bool(executed["replayed"]),
        }

    def resume(
        self,
        formation_run_id: str,
        *,
        expected_version: int,
        principal: Principal,
    ) -> dict[str, Any]:
        run = self.require(formation_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        frozen = self._frozen_input(formation_run_id)
        executed = self._control(
            run=run,
            principal=principal,
            definition_name="story.formation.resume",
            idempotency_key=f"{formation_run_id}:resume:{expected_version}",
            payload={"expected_version": expected_version},
            frozen_input=frozen,
        )
        resumed = self.require(formation_run_id)
        self.runtime_jobs.cancel_pending_for_subject(
            job_kind="STORY_FORMATION_ADVANCE",
            runtime_group="story_formation",
            subject_kind="STORY_FORMATION_RUN",
            subject_id=formation_run_id,
            project_id=str(resumed["project_id"]),
            reason=f"Formation resumed at version {resumed['version']}",
        )
        self._schedule(resumed)
        return {**resumed, "operation_id": executed["operation_id"]}

    def approve_book_design(
        self,
        formation_run_id: str,
        *,
        expected_version: int,
        asset_version_id: str,
        content_hash: str,
        principal: Principal,
    ) -> dict[str, Any]:
        run = self.require(formation_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        if (
            not asset_version_id.strip()
            or len(content_hash) != 71
            or not content_hash.startswith("sha256:")
        ):
            raise ValueError("BookDesign approval requires an exact AssetVersion/hash")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND asset.asset_type='book_design'
                  AND version.asset_version_id=%s
                """,
                [str(run["project_id"]), asset_version_id],
            )
            asset = uow.cursor.fetchone()
        if asset is None or str(asset[0]) != content_hash:
            raise KernelError(
                "STORY_FORMATION_BOOK_DESIGN_INPUT_DRIFT",
                "BookDesign approval target is missing or hash-mismatched",
            )
        frozen = self._frozen_input(formation_run_id)
        executed = self._control(
            run=run,
            principal=principal,
            definition_name="story.formation.approve_book_design",
            idempotency_key=(
                f"{formation_run_id}:approve-book-design:{expected_version}:"
                f"{asset_version_id}"
            ),
            payload={
                "expected_version": expected_version,
                "book_design_asset_version_id": asset_version_id,
                "book_design_content_hash": content_hash,
            },
            frozen_input=frozen,
            additional_input_assets=(
                {
                    "asset_version_id": asset_version_id,
                    "content_hash": content_hash,
                },
            ),
        )
        return {
            **self.require(formation_run_id),
            "operation_id": executed["operation_id"],
            "replayed": executed["replayed"],
        }

    def abort(
        self,
        formation_run_id: str,
        *,
        expected_version: int,
        principal: Principal,
    ) -> dict[str, Any]:
        run = self.require(formation_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        frozen = self._frozen_input(formation_run_id)
        self._control(
            run=run,
            principal=principal,
            definition_name="story.formation.abort",
            idempotency_key=f"{formation_run_id}:abort:{expected_version}",
            payload={"expected_version": expected_version},
            frozen_input=frozen,
        )
        return self.require(formation_run_id)

    def require(self, formation_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return StoryFormationRepository(uow.cursor).require(formation_run_id)

    def record_failure(
        self,
        formation_run_id: str,
        *,
        error: dict[str, Any],
        runtime_attempt_id: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            StoryFormationRepository(uow.cursor).fail(
                formation_run_id,
                error=error,
                operation_id=runtime_attempt_id,
            )
            uow.commit()

    def schedule_candidates(self, *, limit: int, project_id: str = "", formation_run_id: str = "") -> tuple[dict[str, Any], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT formation_run_id, project_id, lifecycle, current_stage,
                       version, frozen_input_digest
                FROM authority_story_formation_run AS run
                WHERE lifecycle IN ('ADMITTED','RUNNING')
                  AND (%s='' OR project_id=%s)
                  AND (%s='' OR formation_run_id=%s)
                  AND NOT EXISTS (
                    SELECT 1 FROM authority_runtime_job AS job
                    WHERE job.runtime_group='story_formation'
                      AND job.job_kind='STORY_FORMATION_ADVANCE'
                      AND job.subject_id=run.formation_run_id
                      AND job.status IN ('PENDING','LEASED','RUNNING','RETRY_WAIT')
                  )
                ORDER BY updated_at, formation_run_id
                LIMIT %s
                """,
                [project_id, project_id, formation_run_id, formation_run_id, limit],
            )
            rows = uow.cursor.fetchall()
        return tuple(
            self._schedule(
                {
                    "formation_run_id": str(row[0]),
                    "project_id": str(row[1]),
                    "lifecycle": str(row[2]),
                    "current_stage": str(row[3]),
                    "version": int(row[4]),
                    "frozen_input_digest": str(row[5]),
                }
            )
            for row in rows
        )

    def _control(
        self,
        *,
        run: dict[str, Any],
        principal: Principal,
        definition_name: str,
        idempotency_key: str,
        payload: dict[str, Any],
        frozen_input: StoryFormationInput,
        additional_input_assets: tuple[dict[str, str], ...] = (),
    ) -> dict[str, Any]:
        self._register_definitions()
        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": STORY_FORMATION_DEFINITION_VERSION,
                "project_id": str(run["project_id"]),
                "workspace_id": str(run["workspace_id"]),
                "book_id": str(run["book_id"]),
                "actor_id": principal.principal_id,
                "idempotency_scope": "book:story-formation",
                "idempotency_key": idempotency_key,
                "trace_id": f"trace:{run['formation_run_id']}",
                "span_id": str(uuid4()),
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "causation_operation_id": str(run["root_operation_id"]),
                "input": {
                    "project_id": str(run["project_id"]),
                    "workspace_id": str(run["workspace_id"]),
                    "book_id": str(run["book_id"]),
                    "formation_run_id": str(run["formation_run_id"]),
                    **payload,
                },
                "input_assets": [
                    *self._input_assets(str(run["project_id"]), frozen_input),
                    *additional_input_assets,
                ],
            },
            context=self._context(principal.principal_id),
            handler=self._execute_transaction,
            fault_injector=self.fault_injector,
        )

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT definition_name, project_id, workspace_id,
                   command_payload, trace_id, correlation_id
            FROM authority_operation WHERE operation_id=%s
            """,
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "Formation Operation is missing")
        definition_name = str(row[0])
        payload = dict(row[3])
        repository = StoryFormationRepository(uow.cursor)
        formation_run_id = str(payload["formation_run_id"])
        checkpoint("after_domain_validation")
        if definition_name == "story.formation.admit":
            result = repository.create(
                formation_run_id=formation_run_id,
                project_id=str(row[1]),
                workspace_id=str(row[2]),
                book_id=str(payload["book_id"]),
                root_operation_id=operation_id,
                stable_idempotency_key=str(payload["stable_idempotency_key"]),
                expected_book_version=int(payload["expected_book_version"]),
                formation_policy_version=STORY_FORMATION_POLICY_VERSION,
                frozen_input=StoryFormationInput.from_mapping(
                    dict(payload["frozen_input"])
                ),
            )
        elif definition_name == "story.formation.advance":
            result = repository.advance_one(
                formation_run_id,
                operation_id,
                expected_stage=str(payload["stage"]),
                expected_version=int(payload["expected_version"]),
                generated_layer=FormationLayerInput.from_mapping(payload["generated_layer"]) if payload.get("generated_layer") else None,
                generated_book_design=payload.get("generated_book_design"),
            )
        elif definition_name == "story.formation.resume":
            result = repository.resume(
                formation_run_id, int(payload["expected_version"])
            )
        elif definition_name == "story.formation.approve_book_design":
            result = repository.bind_book_design(
                formation_run_id,
                expected_version=int(payload["expected_version"]),
                asset_version_id=str(payload["book_design_asset_version_id"]),
                content_hash=str(payload["book_design_content_hash"]),
                operation_id=operation_id,
            )
        else:
            result = repository.abort(
                formation_run_id, int(payload["expected_version"])
            )
        checkpoint("after_business_projection_update")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "story_formation",
                "aggregate_id": formation_run_id,
                "operation_id": operation_id,
                "project_id": str(row[1]),
                "event_type": "story.formation.transitioned",
                "correlation_id": str(row[5]),
                "causation_id": str(payload.get("causation_id") or ""),
                "payload": {
                    "formation_run_id": formation_run_id,
                    "lifecycle": result["lifecycle"],
                    "current_stage": result["current_stage"],
                    "version": result["version"],
                    "operation_id": operation_id,
                },
            }
        )
        checkpoint("after_outbox_insert")
        return {
            "formation_run_id": formation_run_id,
            "lifecycle": str(result["lifecycle"]),
            "current_stage": str(result["current_stage"]),
            "version": int(result["version"]),
        }

    def _schedule(self, run: dict[str, Any]) -> dict[str, Any]:
        return self.runtime_jobs.schedule(
            RuntimeJobSpec(
                job_kind="STORY_FORMATION_ADVANCE",
                runtime_group="story_formation",
                subject_kind="STORY_FORMATION_RUN",
                subject_id=str(run["formation_run_id"]),
                project_id=str(run["project_id"]),
                dedupe_key=(
                    f"{run['formation_run_id']}:{run['current_stage']}:{run['version']}"
                ),
                input_snapshot={
                    "formation_run_id": str(run["formation_run_id"]),
                    "observed_stage": str(run["current_stage"]),
                    "observed_version": int(run["version"]),
                    "frozen_input_digest": str(run["frozen_input_digest"]),
                },
                max_attempts=5,
            )
        )

    def _latest_job(self, formation_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT runtime_job_id, status, current_attempt_id
                FROM authority_runtime_job
                WHERE runtime_group='story_formation'
                  AND job_kind='STORY_FORMATION_ADVANCE'
                  AND subject_kind='STORY_FORMATION_RUN'
                  AND subject_id=%s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [formation_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "STORY_FORMATION_JOB_MISSING",
                "Formation replay has no durable RuntimeJob lineage",
            )
        return {
            "runtime_job_id": str(row[0]),
            "status": str(row[1]),
            "current_attempt_id": str(row[2] or ""),
        }

    def _frozen_input(self, formation_run_id: str) -> StoryFormationInput:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT frozen_stage_inputs, frozen_input_digest
                FROM authority_story_formation_run
                WHERE formation_run_id=%s
                """,
                [formation_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("STORY_FORMATION_NOT_FOUND", "Formation run is missing")
        frozen = StoryFormationInput.from_mapping(dict(row[0]))
        if frozen.digest != str(row[1]):
            raise KernelError(
                "STORY_FORMATION_FROZEN_INPUT_DRIFT",
                "Formation frozen input digest drifted",
            )
        return frozen

    def _input_assets(
        self, project_id: str, frozen: StoryFormationInput
    ) -> tuple[dict[str, str], ...]:
        requested = {
            *(item.asset_version_id for item in frozen.layers),
            *(item.qualification_evidence_asset_version_id for item in frozen.layers),
            *(
                candidate
                for item in frozen.layers
                for candidate in item.candidate_asset_version_ids
            ),
        }
        if frozen.book_design_asset_version_id:
            requested.add(frozen.book_design_asset_version_id)
        if frozen.creative_brief_asset_version_id:
            requested.add(frozen.creative_brief_asset_version_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s)
                """,
                [project_id, list(requested)],
            )
            found = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        if frozen.creative_brief_asset_version_id and found.get(frozen.creative_brief_asset_version_id) != frozen.creative_brief_content_hash:
            raise KernelError("STORY_FORMATION_BRIEF_DRIFT", "Formation author brief content hash differs")
        if set(found) != requested:
            raise KernelError(
                "STORY_FORMATION_INPUT_ASSET_MISSING",
                "Formation frozen input assets are missing or outside Project scope",
            )
        return tuple(
            {"asset_version_id": item, "content_hash": found[item]}
            for item in sorted(requested)
        )

    def _context(self, actor_id: str) -> AdmissionContext:
        return AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset({"book.authority.execute"}),
            available_handlers=frozenset({STORY_FORMATION_HANDLER}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for name in sorted(STORY_FORMATION_OPERATIONS):
                uow.repositories.definitions.register(
                    _definition(
                        name,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                )
            uow.commit()


def _definition(
    name: str, *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["project_id", "formation_run_id"],
        "properties": {
            "project_id": {"type": "string"},
            "formation_run_id": {"type": "string"},
        },
    }
    return {
        "name": name,
        "definition_version": STORY_FORMATION_DEFINITION_VERSION,
        "family": "book_design_authority",
        "enabled": True,
        "definition_status": "implemented",
        "command_schema_version": "story-formation-command.v1",
        "result_schema_version": "story-formation-result.v1",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {"type": "StoryFormationTransition"},
        "handler_key": STORY_FORMATION_HANDLER,
        "handler_contract_version": "story-formation-handler.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "coordinator_only": True,
            "provider_calls_in_http_forbidden": True,
            "frozen_inputs_required": True,
        },
        "idempotency_scope": "book:story-formation",
        "concurrency_key_template": "book:{book_id}:story-formation",
        "retry_policy": {"max_attempts": 3},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "reject_if_committing"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable Authority inputs and append-only lineage",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["story_formation_run"],
        "migration_owner": "book-design-authority",
        "completion_contract": {
            "version": "story-formation-completion.v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["story.formation.transitioned"],
        },
    }


__all__ = [
    "StartStoryFormationCommand",
    "StoryFormationAdmission",
    "StoryFormationApplication",
]
