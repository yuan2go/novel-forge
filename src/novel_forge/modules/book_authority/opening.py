"""Book opening coordinator over existing design, planning, and input Authorities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_design_authority import (
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignPayload,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    NarrativeSearchRequest,
    PostgresNarrativeSearchApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.foundation_repositories import (
    require_current_foundation_set,
)

from .input_resolver import (
    BookProductionInputResolver,
    BookProductionInputSnapshot,
    ResolveBookProductionInputCommand,
)


_RESOLVER_ROLE_BY_PLANNING_ROLE = {
    "production_profile": "production_profile_version",
    "reader_segment": "reader_segment_version",
    "reader_contract": "reader_contract_version",
    "platform_profile": "platform_profile_version",
    "character_state": "character_state_version",
    "foreshadowing_state": "foreshadowing_state_version",
    "quality_trend": "quality_trend_version",
    "reward_ledger": "reward_ledger_version",
    "promise_ledger": "promise_ledger_version",
}
_OPENING_INPUT_ROLES = frozenset(
    role
    for generator in (
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
    )
    for role in GENERATOR_INPUT_ROLES[generator]
    if role not in {"book_plan", "volume_plan"}
)
BOOK_OPENING_DEFINITION_VERSION = "1.0.0"
BOOK_OPENING_HANDLER = "novel_forge.book_authority.opening"
BOOK_OPENING_OPERATIONS = frozenset(
    {"book.opening.admit", "book.opening.complete", "book.opening.resume", "book.opening.abort"}
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class OpenBookProductionRequest:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    expected_book_version: int
    production_profile: str
    planning_input_versions: Mapping[str, str]
    arc_logical_keys: tuple[str, ...]
    idempotency_key: str
    trace_id: str
    correlation_id: str
    initial_story_state_version: str = ""
    initial_canon_snapshot_version: str = ""

    def __post_init__(self) -> None:
        identities = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.actor_id,
            self.production_profile,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if (
            any(not item.strip() for item in identities)
            or self.expected_book_version <= 0
        ):
            raise ValueError("Book opening request is incomplete")
        if not self.arc_logical_keys or len(set(self.arc_logical_keys)) != len(
            self.arc_logical_keys
        ):
            raise ValueError("Book opening requires a non-empty unique Arc portfolio")
        if (
            not self.initial_story_state_version
            or not self.initial_canon_snapshot_version
        ):
            raise ValueError(
                "Book opening requires the initial accepted Story State and Canon boundary"
            )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["planning_input_versions"] = dict(self.planning_input_versions)
        value["arc_logical_keys"] = list(self.arc_logical_keys)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OpenBookProductionRequest":
        expected = {
            "project_id",
            "workspace_id",
            "book_id",
            "actor_id",
            "expected_book_version",
            "production_profile",
            "planning_input_versions",
            "arc_logical_keys",
            "idempotency_key",
            "trace_id",
            "correlation_id",
            "initial_story_state_version",
            "initial_canon_snapshot_version",
        }
        if set(value) != expected or not isinstance(
            value.get("planning_input_versions"), Mapping
        ) or not isinstance(value.get("arc_logical_keys"), list):
            raise KernelError(
                "BOOK_OPENING_REQUEST_INVALID",
                "frozen Book opening request fields must match exactly",
            )
        return cls(
            project_id=str(value["project_id"]),
            workspace_id=str(value["workspace_id"]),
            book_id=str(value["book_id"]),
            actor_id=str(value["actor_id"]),
            expected_book_version=int(value["expected_book_version"]),
            production_profile=str(value["production_profile"]),
            planning_input_versions={
                str(role): str(version)
                for role, version in value["planning_input_versions"].items()
            },
            arc_logical_keys=tuple(str(item) for item in value["arc_logical_keys"]),
            idempotency_key=str(value["idempotency_key"]),
            trace_id=str(value["trace_id"]),
            correlation_id=str(value["correlation_id"]),
            initial_story_state_version=str(value["initial_story_state_version"]),
            initial_canon_snapshot_version=str(value["initial_canon_snapshot_version"]),
        )


@dataclass(frozen=True, slots=True)
class BookOpeningAdmission:
    opening_run_id: str
    root_operation_id: str
    runtime_job_id: str
    lifecycle: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class BookOpeningResult:
    book_design_version: str
    book_plan_version: str
    volume_plan_version: str
    arc_plan_versions: tuple[str, ...]
    input_snapshot: BookProductionInputSnapshot
    search_ids: tuple[str, ...]


class PostgresBookOpeningApplication:
    """Coordinates existing Authorities; it owns no new truth or execution state."""

    def __init__(
        self,
        database_url: str,
        *,
        narrative_search: PostgresNarrativeSearchApplication,
        input_resolver: BookProductionInputResolver,
        application_build_id: str,
        commit_sha: str,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("Book opening requires PostgreSQL/build identity")
        self.database_url = database_url
        self.narrative_search = narrative_search
        self.input_resolver = input_resolver
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.runtime_jobs = RuntimeJobAuthority(database_url)

    def admit(
        self, request: OpenBookProductionRequest, *, principal: Principal
    ) -> BookOpeningAdmission:
        """Freeze a durable opening run without owning Provider execution."""

        principal.require("book.authority.execute", request.project_id)
        principal.require("story_planning.authority.execute", request.project_id)
        if principal.principal_id != request.actor_id:
            raise KernelError(
                "ACTOR_IDENTITY_INVALID",
                "Book opening actor differs from authenticated Principal",
            )
        self._require_qualified_foundation(request)
        self._register_definitions()
        identity = "\x00".join(
            (request.project_id, request.book_id, request.idempotency_key)
        ).encode("utf-8")
        opening_run_id = "book-opening:" + hashlib.sha256(identity).hexdigest()
        frozen_request = request.to_dict()
        executed = execute_transaction_command(
            self.database_url,
            {
                "definition_name": "book.opening.admit",
                "definition_version": BOOK_OPENING_DEFINITION_VERSION,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "book_id": request.book_id,
                "actor_id": request.actor_id,
                "idempotency_scope": "book:opening",
                "idempotency_key": request.idempotency_key,
                "trace_id": request.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": request.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": request.project_id,
                    "book_id": request.book_id,
                    "opening_run_id": opening_run_id,
                    "frozen_request": frozen_request,
                    "frozen_request_digest": _canonical_hash(frozen_request),
                },
                "input_assets": self._opening_input_assets(request),
            },
            context=self._context(request.actor_id),
            handler=self._execute_transaction,
        )
        run = self.require(opening_run_id)
        job = (
            self._schedule(run)
            if run["lifecycle"] in {"ADMITTED", "RUNNING"}
            else self._latest_job(opening_run_id)
        )
        return BookOpeningAdmission(
            opening_run_id=opening_run_id,
            root_operation_id=str(executed["operation_id"]),
            runtime_job_id=str(job["runtime_job_id"]),
            lifecycle=str(run["lifecycle"]),
            replayed=bool(executed["replayed"]),
        )

    def require(self, opening_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT opening_run_id,project_id,workspace_id,book_id,
                       root_operation_id,lifecycle,frozen_request_digest,
                       version,result,failure,recovery_instruction
                FROM authority_book_opening_run
                WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_OPENING_NOT_FOUND", "Book opening run is missing")
        return dict(
            zip(
                (
                    "opening_run_id",
                    "project_id",
                    "workspace_id",
                    "book_id",
                    "root_operation_id",
                    "lifecycle",
                    "frozen_request_digest",
                    "version",
                    "result",
                    "failure",
                    "recovery_instruction",
                ),
                row,
                strict=True,
            )
        )

    def execute_run(
        self, opening_run_id: str, *, expected_version: int, principal: Principal
    ) -> dict[str, Any]:
        run = self.require(opening_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        if str(run["lifecycle"]) == "COMPLETE":
            return dict(run["result"])
        if str(run["lifecycle"]) not in {"ADMITTED", "RUNNING"} or int(
            run["version"]
        ) != expected_version:
            raise KernelError(
                "BOOK_OPENING_JOB_STALE",
                "Book opening RuntimeJob differs from its frozen run version",
            )
        request = self._frozen_request(opening_run_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='RUNNING',updated_at=NOW()
                WHERE opening_run_id=%s AND version=%s
                  AND lifecycle IN ('ADMITTED','RUNNING')
                """,
                [opening_run_id, expected_version],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_JOB_STALE",
                    "Book opening changed before worker execution",
                )
            uow.commit()
        opened = self._open_frozen(request, principal=principal)
        result = {
            "book_design_version": opened.book_design_version,
            "book_plan_version": opened.book_plan_version,
            "volume_plan_version": opened.volume_plan_version,
            "arc_plan_versions": list(opened.arc_plan_versions),
            "input_snapshot_id": opened.input_snapshot.snapshot_id,
            "search_ids": list(opened.search_ids),
        }
        self._control(
            run=run,
            principal=principal,
            definition_name="book.opening.complete",
            idempotency_key=f"{opening_run_id}:complete:{_canonical_hash(result)}",
            payload={"expected_version": expected_version, "result": result},
        )
        return result

    def record_failure(
        self, opening_run_id: str, *, expected_version: int, error: dict[str, Any]
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='FAILED',failure=%s,recovery_instruction=%s,
                    version=version+1,updated_at=NOW()
                WHERE opening_run_id=%s AND version=%s
                  AND lifecycle IN ('ADMITTED','RUNNING')
                """,
                [
                    Jsonb(error),
                    Jsonb(
                        {
                            "action": "RESUME_WITH_SAME_FROZEN_REQUEST",
                            "opening_run_id": opening_run_id,
                        }
                    ),
                    opening_run_id,
                    expected_version,
                ],
            )
            uow.commit()

    def resume(
        self, opening_run_id: str, *, expected_version: int, principal: Principal
    ) -> dict[str, Any]:
        run = self.require(opening_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        self._control(
            run=run,
            principal=principal,
            definition_name="book.opening.resume",
            idempotency_key=f"{opening_run_id}:resume:{expected_version}",
            payload={"expected_version": expected_version},
        )
        resumed = self.require(opening_run_id)
        self.runtime_jobs.cancel_pending_for_subject(
            job_kind="BOOK_OPENING_EXECUTE",
            runtime_group="book_opening",
            subject_kind="BOOK_OPENING_RUN",
            subject_id=opening_run_id,
            project_id=str(resumed["project_id"]),
            reason=f"Book opening resumed at version {resumed['version']}",
        )
        job = self._schedule(resumed)
        return {**resumed, "runtime_job_id": str(job["runtime_job_id"])}

    def abort(
        self, opening_run_id: str, *, expected_version: int, principal: Principal
    ) -> dict[str, Any]:
        run = self.require(opening_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        self._control(
            run=run,
            principal=principal,
            definition_name="book.opening.abort",
            idempotency_key=f"{opening_run_id}:abort:{expected_version}",
            payload={"expected_version": expected_version},
        )
        self.runtime_jobs.cancel_pending_for_subject(
            job_kind="BOOK_OPENING_EXECUTE",
            runtime_group="book_opening",
            subject_kind="BOOK_OPENING_RUN",
            subject_id=opening_run_id,
            project_id=str(run["project_id"]),
            reason="Book opening aborted by Authority command",
        )
        return self.require(opening_run_id)

    def _open_frozen(
        self, request: OpenBookProductionRequest, *, principal: Principal
    ) -> BookOpeningResult:
        principal.require("book.authority.execute", request.project_id)
        principal.require("story_planning.authority.execute", request.project_id)
        design_version = self._require_qualified_foundation(request)
        generic = dict(request.planning_input_versions)
        if (
            set(generic) != _OPENING_INPUT_ROLES
            or generic.get("book_design") != design_version
        ):
            raise KernelError(
                "BOOK_OPENING_INPUTS_INVALID",
                "opening inputs must exactly match the Book planning Authority roles and active Foundation",
            )
        accepted_state = request.initial_story_state_version
        search_ids: list[str] = []
        book_search = self._search(
            request=request,
            principal=principal,
            generator="book_plan.generate",
            logical_key="book:main",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            parent_version_id="",
            accepted_state=accepted_state,
            horizon={"level": "BOOK", "stability": "HIGH", "reach": "DISTANT"},
            transformation={
                "foundation_version": design_version,
                "goal": "establish a sustainable Book narrative architecture",
            },
        )
        search_ids.append(book_search.search_id)
        book_plan = book_search.selected_generation.candidate_asset_version_id
        volume_inputs = self._stage_inputs(
            generic, "volume_plan.generate", book_plan=book_plan
        )
        volume_search = self._search(
            request=request,
            principal=principal,
            generator="volume_plan.generate",
            logical_key="volume:1",
            input_versions=volume_inputs,
            parent_version_id=book_plan,
            accepted_state=accepted_state,
            horizon={"level": "VOLUME", "stability": "MEDIUM_HIGH", "ordinal": 1},
            transformation={
                "goal": "create the first irreversible stage transformation"
            },
        )
        search_ids.append(volume_search.search_id)
        volume_plan = volume_search.selected_generation.candidate_asset_version_id
        arc_versions: list[str] = []
        for arc_key in request.arc_logical_keys:
            arc_inputs = self._stage_inputs(
                generic,
                "arc_plan.generate",
                book_plan=book_plan,
                volume_plan=volume_plan,
            )
            arc_search = self._search(
                request=request,
                principal=principal,
                generator="arc_plan.generate",
                logical_key=arc_key,
                input_versions=arc_inputs,
                parent_version_id="",
                accepted_state=accepted_state,
                horizon={"level": "ARC", "stability": "MEDIUM", "volume": 1},
                transformation={
                    "goal": "produce a causal transformation with closure criteria",
                    "arc_key": arc_key,
                },
            )
            search_ids.append(arc_search.search_id)
            arc_versions.append(
                arc_search.selected_generation.candidate_asset_version_id
            )
        overrides = tuple(
            (
                _RESOLVER_ROLE_BY_PLANNING_ROLE[role],
                version_id,
            )
            for role, version_id in generic.items()
            if role in _RESOLVER_ROLE_BY_PLANNING_ROLE
        )
        overrides += (
            ("initial_story_state_version", request.initial_story_state_version),
            ("initial_canon_snapshot_version", request.initial_canon_snapshot_version),
        )
        snapshot = self.input_resolver.resolve(
            ResolveBookProductionInputCommand(
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=request.book_id,
                production_profile=request.production_profile,
                expected_book_version=request.expected_book_version,
                actor_id=request.actor_id,
                idempotency_key=f"{request.idempotency_key}:production-input",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                role_asset_version_overrides=overrides,
            ),
            principal=principal,
        )
        return BookOpeningResult(
            book_design_version=design_version,
            book_plan_version=book_plan,
            volume_plan_version=volume_plan,
            arc_plan_versions=tuple(arc_versions),
            input_snapshot=snapshot,
            search_ids=tuple(search_ids),
        )

    def _control(
        self,
        *,
        run: dict[str, Any],
        principal: Principal,
        definition_name: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._register_definitions()
        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": BOOK_OPENING_DEFINITION_VERSION,
                "project_id": str(run["project_id"]),
                "workspace_id": str(run["workspace_id"]),
                "book_id": str(run["book_id"]),
                "actor_id": principal.principal_id,
                "idempotency_scope": "book:opening",
                "idempotency_key": idempotency_key,
                "trace_id": f"trace:{run['opening_run_id']}",
                "span_id": str(uuid4()),
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "causation_operation_id": str(run["root_operation_id"]),
                "input": {
                    "project_id": str(run["project_id"]),
                    "book_id": str(run["book_id"]),
                    "opening_run_id": str(run["opening_run_id"]),
                    **payload,
                },
                "input_assets": self._opening_input_assets(
                    self._frozen_request(str(run["opening_run_id"]))
                ),
            },
            context=self._context(principal.principal_id),
            handler=self._execute_transaction,
        )

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT definition_name,project_id,workspace_id,command_payload
            FROM authority_operation WHERE operation_id=%s
            """,
            [operation_id],
        )
        operation = uow.cursor.fetchone()
        if operation is None:
            raise KernelError("OPERATION_NOT_FOUND", "Book opening Operation is missing")
        definition_name = str(operation[0])
        payload = dict(operation[3])
        opening_run_id = str(payload["opening_run_id"])
        checkpoint("after_domain_validation")
        if definition_name == "book.opening.admit":
            frozen_request = dict(payload["frozen_request"])
            digest = _canonical_hash(frozen_request)
            if digest != str(payload["frozen_request_digest"]):
                raise KernelError(
                    "BOOK_OPENING_FROZEN_REQUEST_DRIFT",
                    "Book opening request differs from its digest",
                )
            OpenBookProductionRequest.from_mapping(frozen_request)
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_run(
                    opening_run_id,project_id,workspace_id,book_id,
                    root_operation_id,stable_idempotency_key,lifecycle,
                    frozen_request,frozen_request_digest
                ) VALUES (%s,%s,%s,%s,%s,%s,'ADMITTED',%s,%s)
                ON CONFLICT (opening_run_id) DO NOTHING
                """,
                [
                    opening_run_id,
                    str(operation[1]),
                    str(operation[2]),
                    str(payload["book_id"]),
                    operation_id,
                    str(frozen_request["idempotency_key"]),
                    Jsonb(frozen_request),
                    digest,
                ],
            )
            if uow.cursor.rowcount == 0:
                uow.cursor.execute(
                    """
                    SELECT root_operation_id,frozen_request_digest
                    FROM authority_book_opening_run WHERE opening_run_id=%s
                    """,
                    [opening_run_id],
                )
                existing = uow.cursor.fetchone()
                if existing is None or tuple(str(item) for item in existing) != (
                    operation_id,
                    digest,
                ):
                    raise KernelError(
                        "BOOK_OPENING_IDEMPOTENCY_CONFLICT",
                        "Book opening identity binds different frozen evidence",
                    )
        elif definition_name == "book.opening.complete":
            result = payload.get("result")
            if not isinstance(result, dict):
                raise KernelError(
                    "BOOK_OPENING_RESULT_INVALID", "Book opening result is not typed"
                )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='COMPLETE',result=%s,failure='{}'::jsonb,
                    recovery_instruction='{}'::jsonb,version=version+1,
                    updated_at=NOW()
                WHERE opening_run_id=%s AND version=%s AND lifecycle='RUNNING'
                """,
                [
                    Jsonb(result),
                    opening_run_id,
                    int(payload["expected_version"]),
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_COMMIT_CONFLICT",
                    "Book opening completion changed concurrently",
                )
        elif definition_name == "book.opening.resume":
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='ADMITTED',failure='{}'::jsonb,
                    recovery_instruction='{}'::jsonb,version=version+1,
                    updated_at=NOW()
                WHERE opening_run_id=%s AND version=%s AND lifecycle='FAILED'
                """,
                [opening_run_id, int(payload["expected_version"])],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_RESUME_CONFLICT",
                    "Book opening is not failed at the expected version",
                )
        else:
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='ABORTED',version=version+1,updated_at=NOW()
                WHERE opening_run_id=%s AND version=%s
                  AND lifecycle IN ('ADMITTED','FAILED')
                """,
                [opening_run_id, int(payload["expected_version"])],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_ABORT_CONFLICT",
                    "Book opening cannot abort at the expected version",
                )
        checkpoint("after_business_projection_update")
        run = self._require_in_uow(uow, opening_run_id)
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_opening",
                "aggregate_id": opening_run_id,
                "operation_id": operation_id,
                "project_id": str(operation[1]),
                "event_type": "book.opening.transitioned",
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "payload": {
                    "operation_id": operation_id,
                    "opening_run_id": opening_run_id,
                    "lifecycle": str(run["lifecycle"]),
                    "version": int(run["version"]),
                },
            }
        )
        checkpoint("after_outbox_insert")
        return {
            "opening_run_id": opening_run_id,
            "lifecycle": str(run["lifecycle"]),
            "version": int(run["version"]),
        }

    @staticmethod
    def _require_in_uow(
        uow: AuthorityUnitOfWork, opening_run_id: str
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT opening_run_id,root_operation_id,lifecycle,version
            FROM authority_book_opening_run WHERE opening_run_id=%s
            """,
            [opening_run_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_OPENING_NOT_FOUND", "Book opening run is missing")
        return dict(
            zip(
                ("opening_run_id", "root_operation_id", "lifecycle", "version"),
                row,
                strict=True,
            )
        )

    def _frozen_request(self, opening_run_id: str) -> OpenBookProductionRequest:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT frozen_request,frozen_request_digest
                FROM authority_book_opening_run WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None or not isinstance(row[0], dict) or _canonical_hash(
            dict(row[0])
        ) != str(row[1]):
            raise KernelError(
                "BOOK_OPENING_FROZEN_REQUEST_DRIFT",
                "Book opening frozen request is missing or digest-mismatched",
            )
        return OpenBookProductionRequest.from_mapping(dict(row[0]))

    def _opening_input_assets(
        self, request: OpenBookProductionRequest
    ) -> list[dict[str, str]]:
        requested = {
            *request.planning_input_versions.values(),
            request.initial_story_state_version,
            request.initial_canon_snapshot_version,
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id,version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s)
                """,
                [request.project_id, list(requested)],
            )
            found = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        if set(found) != requested:
            raise KernelError(
                "BOOK_OPENING_INPUT_ASSET_MISSING",
                "Book opening frozen inputs are missing or outside Project scope",
            )
        return [
            {"asset_version_id": item, "content_hash": found[item]}
            for item in sorted(requested)
        ]

    def _schedule(self, run: dict[str, Any]) -> dict[str, Any]:
        return self.runtime_jobs.schedule(
            RuntimeJobSpec(
                job_kind="BOOK_OPENING_EXECUTE",
                runtime_group="book_opening",
                subject_kind="BOOK_OPENING_RUN",
                subject_id=str(run["opening_run_id"]),
                project_id=str(run["project_id"]),
                dedupe_key=f"{run['opening_run_id']}:{run['version']}",
                input_snapshot={
                    "opening_run_id": str(run["opening_run_id"]),
                    "observed_version": int(run["version"]),
                    "frozen_request_digest": str(run["frozen_request_digest"]),
                },
                max_attempts=5,
            )
        )

    def _latest_job(self, opening_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT runtime_job_id,status
                FROM authority_runtime_job
                WHERE job_kind='BOOK_OPENING_EXECUTE'
                  AND subject_kind='BOOK_OPENING_RUN' AND subject_id=%s
                ORDER BY created_at DESC LIMIT 1
                """,
                [opening_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_OPENING_JOB_MISSING",
                "Book opening replay has no durable RuntimeJob lineage",
            )
        return {"runtime_job_id": str(row[0]), "status": str(row[1])}

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for name in sorted(BOOK_OPENING_OPERATIONS):
                uow.repositories.definitions.register(
                    _opening_definition(
                        name,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                )
            uow.commit()

    def _context(self, actor_id: str) -> AdmissionContext:
        return AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset(
                {"book.authority.execute", "story_planning.authority.execute"}
            ),
            available_handlers=frozenset({BOOK_OPENING_HANDLER}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )

    def _search(
        self,
        *,
        request: OpenBookProductionRequest,
        principal: Principal,
        generator: str,
        logical_key: str,
        input_versions: Mapping[str, str],
        parent_version_id: str,
        accepted_state: str,
        horizon: Mapping[str, object],
        transformation: Mapping[str, object],
    ):
        generation = StoryPlanningGenerationCommand(
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            book_id=request.book_id,
            actor_id=request.actor_id,
            generator_operation_name=generator,
            logical_key=logical_key,
            input_versions=input_versions,
            parent_version_id=parent_version_id,
            idempotency_key=f"{request.idempotency_key}:{generator}:{logical_key}",
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        return self.narrative_search.explore(
            NarrativeSearchRequest(
                generation=generation,
                planning_horizon=horizon,
                desired_transformation=transformation,
                hard_constraints=(
                    "preserve the approved Creative Foundation",
                    "protect reader promise and ending direction",
                    "do not convert future intent into accepted reality",
                ),
                accepted_through_chapter=0,
                parent_state_asset_version_id=accepted_state,
            ),
            principal=principal,
            activate_selected=True,
        )

    @staticmethod
    def _stage_inputs(
        generic: Mapping[str, str],
        generator: str,
        *,
        book_plan: str,
        volume_plan: str = "",
    ) -> dict[str, str]:
        values = dict(generic)
        values["book_plan"] = book_plan
        if volume_plan:
            values["volume_plan"] = volume_plan
        return {role: values[role] for role in GENERATOR_INPUT_ROLES[generator]}

    def _require_qualified_foundation(self, request: OpenBookProductionRequest) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.current_book_design_asset_version_id,
                       version.schema_version, version.lifecycle,
                       version.eligibility, version.governance,
                       version.content_hash, version.content
                FROM authority_book AS book
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=book.current_book_design_asset_version_id
                WHERE book.project_id=%s AND book.workspace_id=%s AND book.book_id=%s
                  AND book.version=%s AND book.status='DESIGN_ACTIVE'
                """,
                [
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                    request.expected_book_version,
                ],
            )
            row = uow.cursor.fetchone()
            if row is None or tuple(str(item) for item in row[1:5]) != (
                FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                "ACTIVE",
                "ELIGIBLE",
                "CLEAR",
            ):
                raise KernelError(
                    "BOOK_OPENING_FOUNDATION_REQUIRED",
                    "Book opening requires the exact active and qualified Foundation synthesis",
                )
            foundation = require_current_foundation_set(
                uow.cursor,
                project_id=request.project_id,
                book_id=request.book_id,
                require_ready=True,
            )
            design = BookDesignPayload.from_mapping(dict(row[6]))
            if design.foundation_set != foundation:
                raise KernelError(
                    "BOOK_OPENING_FOUNDATION_DRIFT",
                    "BookDesign does not bind the current qualified Foundation Set",
                )
            uow.cursor.execute(
                """
                SELECT formation_run_id
                FROM authority_story_formation_run
                WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                  AND lifecycle='READY' AND current_stage='COMPLETE'
                  AND foundation_set_digest=%s
                  AND book_design_asset_version_id=%s
                  AND book_design_content_hash=%s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                [
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                    foundation.set_digest,
                    str(row[0]),
                    str(row[5]),
                ],
            )
            formation = uow.cursor.fetchone()
        if formation is None:
            raise KernelError(
                "BOOK_OPENING_FORMATION_NOT_READY",
                "Book opening requires a READY durable Story Formation bound to the active synthesis",
            )
        return str(row[0])


def _opening_definition(
    name: str, *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["project_id", "book_id", "opening_run_id"],
        "properties": {
            "project_id": {"type": "string"},
            "book_id": {"type": "string"},
            "opening_run_id": {"type": "string"},
        },
    }
    return {
        "name": name,
        "definition_version": BOOK_OPENING_DEFINITION_VERSION,
        "family": "book_authority",
        "enabled": True,
        "definition_status": "implemented",
        "command_schema_version": "book-opening-command.v1",
        "result_schema_version": "book-opening-result.v1",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {"type": "BookOpeningTransition"},
        "handler_key": BOOK_OPENING_HANDLER,
        "handler_contract_version": "book-opening-handler.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "worker_owned_provider_chain": True,
            "frozen_inputs_required": True,
        },
        "idempotency_scope": "book:opening",
        "concurrency_key_template": "book:{book_id}:opening",
        "retry_policy": {"max_attempts": 5},
        "timeout_policy": {"operation_timeout_seconds": 300},
        "cancellation_policy": {"mode": "reject_if_committing"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable selected search and Plan activation lineage",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["book_opening_run"],
        "migration_owner": "book-authority",
        "completion_contract": {
            "version": "book-opening-completion.v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["book.opening.transitioned"],
        },
    }


__all__ = [
    "BookOpeningAdmission",
    "BookOpeningResult",
    "OpenBookProductionRequest",
    "PostgresBookOpeningApplication",
]
