"""Resolve one immutable, compatible Book Production input snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.story_design_authority import (
    GENERATOR_CATALOG,
    NarrativeDesignLayer,
    required_qualification_profiles,
)
from novel_forge.modules.story_planning_runtime import (
    STORY_PLANNING_OPERATION_DEFINITION_REF,
    canonical_hash,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


BOOK_INPUT_RESOLVE_DEFINITION = "book.production_input.resolve"
BOOK_INPUT_RESOLVE_VERSION = "1.3.0"
BOOK_INPUT_RESOLVE_HANDLER = "novel_forge.book_authority.production_input.resolve"


_ACTIVE_ROLE_TYPES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "production_profile_version": ("production_profile",),
        "reader_segment_version": ("reader_segment_profile", "reader_segment"),
        "reader_contract_version": ("reader_contract",),
        "platform_profile_version": ("platform_profile",),
        "character_state_version": ("character_state_snapshot", "character_state"),
        "foreshadowing_state_version": ("foreshadow_snapshot", "foreshadowing_state"),
        "quality_trend_version": ("quality_trend",),
        "reward_ledger_version": ("reward_ledger_snapshot", "reward_ledger"),
        "promise_ledger_version": (
            "promise_ledger_snapshot",
            "reader_promise_ledger",
            "promise_ledger",
        ),
    }
)

_OPTIONAL_INITIAL_STATE_ROLE_TYPES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "initial_story_state_version": ("story_state_snapshot",),
        "initial_canon_snapshot_version": ("canon_snapshot",),
    }
)


@dataclass(frozen=True, slots=True)
class ResolveBookProductionInputCommand:
    project_id: str
    workspace_id: str
    book_id: str
    production_profile: str
    expected_book_version: int
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    narrative_chapter_cursor: int = 1
    role_asset_version_overrides: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        values = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.production_profile,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if (
            any(not value.strip() for value in values)
            or self.expected_book_version <= 0
            or self.narrative_chapter_cursor <= 0
        ):
            raise ValueError("Book Production input resolution command is incomplete")
        override_roles = [
            role for role, _version_id in self.role_asset_version_overrides
        ]
        initial_roles = set(override_roles) & set(_OPTIONAL_INITIAL_STATE_ROLE_TYPES)
        if (
            len(override_roles) != len(set(override_roles))
            or any(
                role not in {*_ACTIVE_ROLE_TYPES, *_OPTIONAL_INITIAL_STATE_ROLE_TYPES}
                for role in override_roles
            )
            or any(
                not role.strip() or not version_id.strip()
                for role, version_id in self.role_asset_version_overrides
            )
            or (
                initial_roles
                and initial_roles != set(_OPTIONAL_INITIAL_STATE_ROLE_TYPES)
            )
        ):
            raise ValueError("Book Production role overrides are invalid")


@dataclass(frozen=True, slots=True)
class BookProductionInputSnapshot:
    snapshot_id: str
    project_id: str
    workspace_id: str
    book_id: str
    expected_book_version: int
    narrative_chapter_cursor: int
    book_record_version: str
    book_design_version: str
    book_plan_version: str
    current_volume_plan_version: str
    volume_portfolio_plan_versions: tuple[str, ...]
    arc_portfolio_plan_versions: tuple[str, ...]
    current_relevant_arc_plan_versions: tuple[str, ...]
    active_arc_plan_versions: tuple[str, ...]
    current_chapter_group_plan_version: str
    production_profile_version: str
    reader_segment_version: str
    reader_contract_version: str
    platform_profile_version: str
    character_state_version: str
    foreshadowing_state_version: str
    quality_trend_version: str
    reward_ledger_version: str
    promise_ledger_version: str
    initial_story_state_version: str
    initial_canon_snapshot_version: str
    design_admission_status: str
    design_qualification: dict[str, Any]
    design_qualification_hash: str
    capability_pack_deployment_refs: tuple[str, ...]
    release_sha: str
    snapshot_hash: str
    resolved_by_operation_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _select_current_volume_from_portfolio(
    volumes: list[dict[str, Any]], *, chapter_cursor: int
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    previous_end = 0
    for volume in volumes:
        chapter_range = volume["content"].get("chapter_range")
        if (
            not isinstance(chapter_range, list)
            or len(chapter_range) != 2
            or any(
                not isinstance(item, int) or isinstance(item, bool)
                for item in chapter_range
            )
        ):
            raise KernelError(
                "BOOK_PRODUCTION_VOLUME_RANGE_INVALID",
                "every Volume Portfolio member requires an integer chapter range",
            )
        start, end = chapter_range
        if start != previous_end + 1 or end < start:
            raise KernelError(
                "BOOK_PRODUCTION_VOLUME_PORTFOLIO_OVERLAP",
                "Volume Portfolio ranges must be ordered, contiguous, and start at chapter 1",
            )
        previous_end = end
        if start <= chapter_cursor <= end:
            matches.append(volume)
    if len(matches) != 1:
        raise KernelError(
            "BOOK_PRODUCTION_CURRENT_VOLUME_AMBIGUOUS",
            "accepted chapter cursor must resolve exactly one current VolumePlan",
        )
    return matches[0]


def project_current_plan_cursor(
    *,
    volumes: list[dict[str, Any]],
    arcs: list[dict[str, Any]],
    chapter_cursor: int,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Derive the current Volume and complete relevant Arc set from one portfolio."""

    current = _select_current_volume_from_portfolio(
        volumes, chapter_cursor=chapter_cursor
    )
    volume_ids = [str(item["asset_version_id"]) for item in volumes]
    for arc in arcs:
        scope = [str(item) for item in arc["content"].get("cross_volume_scope") or ()]
        if (
            not scope
            or len(scope) != len(set(scope))
            or not set(scope).issubset(volume_ids)
            or scope != [item for item in volume_ids if item in set(scope)]
        ):
            raise KernelError(
                "BOOK_PRODUCTION_ARC_VOLUME_INVALID",
                "Canonical Arc scope must be a non-empty ordered subset of the Volume Portfolio",
            )
    current_id = str(current["asset_version_id"])
    relevant = tuple(
        str(arc["asset_version_id"])
        for arc in arcs
        if current_id
        in {str(item) for item in arc["content"].get("cross_volume_scope") or ()}
    )
    if not relevant:
        raise KernelError(
            "BOOK_PRODUCTION_CURRENT_ARC_MISSING",
            "current Volume has no narratively relevant Canonical Arc",
        )
    return current, relevant


class BookProductionInputResolver:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        allow_scripted_qualification_fixture: bool = False,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Book input resolver requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.allow_scripted_qualification_fixture = allow_scripted_qualification_fixture

    def resolve(
        self,
        command: ResolveBookProductionInputCommand,
        *,
        principal: Principal,
    ) -> BookProductionInputSnapshot:
        principal.require("book.authority.execute", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError(
                "Book input resolver actor must be the trusted Principal"
            )
        self._register_definition()
        with AuthorityUnitOfWork(self.database_url) as uow:
            preview = self._resolve_in_cursor(uow.cursor, command)
        input_ids = self._snapshot_asset_ids(preview)
        input_assets = self._input_assets(command.project_id, input_ids)
        result = execute_transaction_command(
            self.database_url,
            {
                "definition_name": BOOK_INPUT_RESOLVE_DEFINITION,
                "definition_version": BOOK_INPUT_RESOLVE_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "book_id": command.book_id,
                "actor_id": command.actor_id,
                "idempotency_scope": "book:production-input-resolve",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "book_id": command.book_id,
                    "production_profile": command.production_profile,
                    "expected_book_version": command.expected_book_version,
                    "narrative_chapter_cursor": command.narrative_chapter_cursor,
                    "expected_snapshot_hash": preview["snapshot_hash"],
                    "role_asset_version_overrides": [
                        list(item) for item in command.role_asset_version_overrides
                    ],
                },
                "input_assets": list(input_assets),
            },
            context=AdmissionContext(
                actor_id=command.actor_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({BOOK_INPUT_RESOLVE_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=self._execute_transaction,
        )
        return self.require(str(result["snapshot_id"]))

    def require(self, snapshot_id: str) -> BookProductionInputSnapshot:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT snapshot_id, project_id, workspace_id, book_id,
                       expected_book_version, narrative_chapter_cursor,
                       book_record_version,
                       book_design_version, book_plan_version,
                       current_volume_plan_version,
                       volume_portfolio_plan_versions,
                       arc_portfolio_plan_versions,
                       current_relevant_arc_plan_versions,
                       active_arc_plan_versions,
                       COALESCE(current_chapter_group_plan_version, ''),
                       production_profile_version, reader_segment_version,
                       reader_contract_version, platform_profile_version,
                       character_state_version, foreshadowing_state_version,
                       quality_trend_version, reward_ledger_version,
                       promise_ledger_version,
                       COALESCE(initial_story_state_version, ''),
                       COALESCE(initial_canon_snapshot_version, ''),
                       design_admission_status, design_qualification,
                       design_qualification_hash,
                       capability_pack_deployment_refs,
                       release_sha, snapshot_hash, resolved_by_operation_id
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s
                """,
                [snapshot_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_PRODUCTION_INPUT_SNAPSHOT_NOT_FOUND",
                "Book Production input snapshot does not exist",
            )
        names = [item.name for item in fields(BookProductionInputSnapshot)]
        if len(row) != len(names):
            raise KernelError(
                "BOOK_PRODUCTION_INPUT_SNAPSHOT_SHAPE_INVALID",
                "persisted Book Production input shape differs from its typed contract",
            )
        values = dict(zip(names, row, strict=True))
        for name in (
            "volume_portfolio_plan_versions",
            "arc_portfolio_plan_versions",
            "current_relevant_arc_plan_versions",
            "active_arc_plan_versions",
            "capability_pack_deployment_refs",
        ):
            values[name] = tuple(str(item) for item in values[name])
        return BookProductionInputSnapshot(**values)

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT project_id, workspace_id, command_payload->>'book_id', actor_id,
                   trace_id, correlation_id, command_payload
            FROM authority_operation WHERE operation_id=%s
            """,
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "OPERATION_NOT_FOUND", "Book input Operation does not exist"
            )
        payload = dict(row[6])
        command = ResolveBookProductionInputCommand(
            project_id=str(row[0]),
            workspace_id=str(row[1]),
            book_id=str(row[2]),
            actor_id=str(row[3]),
            trace_id=str(row[4]),
            correlation_id=str(row[5]),
            production_profile=str(payload["production_profile"]),
            expected_book_version=int(payload["expected_book_version"]),
            narrative_chapter_cursor=int(payload["narrative_chapter_cursor"]),
            idempotency_key=str(payload.get("idempotency_key") or operation_id),
            role_asset_version_overrides=tuple(
                (str(item[0]), str(item[1]))
                for item in payload.get("role_asset_version_overrides") or ()
            ),
        )
        resolved = self._resolve_in_cursor(uow.cursor, command)
        if resolved["snapshot_hash"] != str(payload["expected_snapshot_hash"]):
            raise KernelError(
                "BOOK_PRODUCTION_INPUT_CHANGED_DURING_RESOLUTION",
                "active Book inputs changed before the snapshot transaction committed",
            )
        checkpoint("after_domain_validation")
        snapshot_id = resolved["snapshot_id"]
        uow.cursor.execute(
            """
            INSERT INTO authority_book_production_input_snapshot(
                snapshot_id, project_id, workspace_id, book_id,
                expected_book_version, narrative_chapter_cursor,
                book_record_version,
                book_design_version, book_plan_version,
                current_volume_plan_version, volume_portfolio_plan_versions,
                arc_portfolio_plan_versions,
                current_relevant_arc_plan_versions,
                active_arc_plan_versions,
                current_chapter_group_plan_version,
                production_profile_version, reader_segment_version,
                reader_contract_version, platform_profile_version,
                character_state_version, foreshadowing_state_version,
                quality_trend_version, reward_ledger_version,
                promise_ledger_version, initial_story_state_version,
                initial_canon_snapshot_version, design_admission_status,
                design_qualification, design_qualification_hash,
                capability_pack_deployment_refs,
                release_sha, snapshot_hash, resolved_by_operation_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                NULLIF(%s, ''), %s, %s, %s, %s, %s, %s, %s, %s, %s,
                NULLIF(%s, ''),
                NULLIF(%s, ''), %s, %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (snapshot_hash) DO NOTHING
            """,
            [
                snapshot_id,
                resolved["project_id"],
                resolved["workspace_id"],
                resolved["book_id"],
                resolved["expected_book_version"],
                resolved["narrative_chapter_cursor"],
                resolved["book_record_version"],
                resolved["book_design_version"],
                resolved["book_plan_version"],
                resolved["current_volume_plan_version"],
                Jsonb(resolved["volume_portfolio_plan_versions"]),
                Jsonb(resolved["arc_portfolio_plan_versions"]),
                Jsonb(resolved["current_relevant_arc_plan_versions"]),
                Jsonb(resolved["active_arc_plan_versions"]),
                resolved["current_chapter_group_plan_version"],
                resolved["production_profile_version"],
                resolved["reader_segment_version"],
                resolved["reader_contract_version"],
                resolved["platform_profile_version"],
                resolved["character_state_version"],
                resolved["foreshadowing_state_version"],
                resolved["quality_trend_version"],
                resolved["reward_ledger_version"],
                resolved["promise_ledger_version"],
                resolved["initial_story_state_version"],
                resolved["initial_canon_snapshot_version"],
                resolved["design_admission_status"],
                Jsonb(resolved["design_qualification"]),
                resolved["design_qualification_hash"],
                Jsonb(resolved["capability_pack_deployment_refs"]),
                resolved["release_sha"],
                resolved["snapshot_hash"],
                operation_id,
            ],
        )
        checkpoint("after_business_projection_update")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_production_input_snapshot",
                "aggregate_id": snapshot_id,
                "operation_id": operation_id,
                "project_id": command.project_id,
                "event_type": "book.production_input.resolved",
                "correlation_id": command.correlation_id,
                "causation_id": operation_id,
                "payload": {
                    "operation_id": operation_id,
                    "snapshot_id": snapshot_id,
                    "snapshot_hash": resolved["snapshot_hash"],
                    "book_id": command.book_id,
                    "narrative_chapter_cursor": command.narrative_chapter_cursor,
                    "design_admission_status": resolved["design_admission_status"],
                    "design_qualification_hash": resolved["design_qualification_hash"],
                },
            }
        )
        checkpoint("after_outbox_insert")
        return {"snapshot_id": snapshot_id, "snapshot_hash": resolved["snapshot_hash"]}

    def _resolve_in_cursor(
        self, cursor: Any, command: ResolveBookProductionInputCommand
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT current_book_asset_version_id,
                   current_book_design_asset_version_id,
                   version, production_profile, release_identity, status
            FROM authority_book
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
            """,
            [command.project_id, command.workspace_id, command.book_id],
        )
        book = cursor.fetchone()
        if book is None:
            raise KernelError(
                "BOOK_PRODUCTION_SCOPE_INVALID",
                "Book belongs to another Project or Workspace",
            )
        if int(book[2]) != command.expected_book_version:
            raise KernelError(
                "BOOK_PRODUCTION_VERSION_CONFLICT",
                "expected Book version is stale",
            )
        if str(book[5]) != "DESIGN_ACTIVE" or not book[1]:
            raise KernelError(
                "BOOK_DESIGN_ACTIVE_REQUIRED",
                "Book Production requires an Active Book Design",
            )
        self._require_authoritative_chapter_cursor(cursor, command)
        plans = self._active_plans(cursor, command)
        roles = {
            role: self._active_role_asset(
                cursor,
                command=command,
                role=role,
                asset_types=asset_types,
                requested_profile=(
                    command.production_profile
                    if role == "production_profile_version"
                    else ""
                ),
            )
            for role, asset_types in _ACTIVE_ROLE_TYPES.items()
        }
        overrides = dict(command.role_asset_version_overrides)
        initial_roles = {
            role: self._active_role_asset(
                cursor,
                command=command,
                role=role,
                asset_types=asset_types,
                requested_profile="",
            )
            for role, asset_types in _OPTIONAL_INITIAL_STATE_ROLE_TYPES.items()
            if role in overrides
        }
        self._validate_initial_narrative_state_pair(
            project_id=command.project_id,
            book_id=command.book_id,
            initial_roles=initial_roles,
        )
        current_volume = self._select_current_volume(
            plans["VOLUME"], chapter_cursor=command.narrative_chapter_cursor
        )
        self._validate_plan_hierarchy(plans, current_volume=current_volume)
        current_relevant_arcs = self._select_current_relevant_arcs(
            plans["ARC"], current_volume=current_volume
        )
        book_design = self._asset_content(cursor, str(book[1]), command.project_id)
        book_plan = plans["BOOK"][0]
        self._validate_design_plan_compatibility(
            book_design=book_design,
            book_plan=book_plan["content"],
            volume_portfolio=plans["VOLUME"],
            production_profile=roles["production_profile_version"]["content"],
        )
        design_qualification = self._longform_design_qualification(
            cursor,
            command=command,
            book_design_version=str(book[1]),
            plans=plans,
        )
        deployments = self._planning_deployments(cursor, command)
        value: dict[str, Any] = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "expected_book_version": command.expected_book_version,
            "narrative_chapter_cursor": command.narrative_chapter_cursor,
            "book_record_version": str(book[0]),
            "book_design_version": str(book[1]),
            "book_plan_version": book_plan["asset_version_id"],
            "current_volume_plan_version": current_volume["asset_version_id"],
            "volume_portfolio_plan_versions": [
                item["asset_version_id"] for item in plans["VOLUME"]
            ],
            "arc_portfolio_plan_versions": [
                item["asset_version_id"] for item in plans["ARC"]
            ],
            "current_relevant_arc_plan_versions": list(current_relevant_arcs),
            "active_arc_plan_versions": list(current_relevant_arcs),
            "current_chapter_group_plan_version": (
                plans["CHAPTER_GROUP"][0]["asset_version_id"]
                if plans["CHAPTER_GROUP"]
                else ""
            ),
            **{role: item["asset_version_id"] for role, item in roles.items()},
            **{
                role: (
                    initial_roles[role]["asset_version_id"]
                    if role in initial_roles
                    else ""
                )
                for role in _OPTIONAL_INITIAL_STATE_ROLE_TYPES
            },
            "capability_pack_deployment_refs": deployments,
            "design_admission_status": "LONGFORM_DESIGN_QUALIFIED",
            "design_qualification": design_qualification,
            "design_qualification_hash": canonical_hash(design_qualification),
            "release_sha": self.commit_sha,
        }
        value["snapshot_hash"] = canonical_hash(value)
        value["snapshot_id"] = value["snapshot_hash"]
        return value

    @staticmethod
    def _require_authoritative_chapter_cursor(
        cursor: Any, command: ResolveBookProductionInputCommand
    ) -> None:
        cursor.execute(
            """
            SELECT book_run_id, accepted_through_chapter
            FROM authority_book_production
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
              AND state NOT IN ('COMPLETED', 'ABORTED')
            ORDER BY created_at DESC
            FOR SHARE
            """,
            [command.project_id, command.workspace_id, command.book_id],
        )
        rows = cursor.fetchall()
        if len(rows) > 1:
            raise KernelError(
                "BOOK_PRODUCTION_CHAPTER_CURSOR_AMBIGUOUS",
                "multiple non-terminal Book runs cannot own one Narrative cursor",
            )
        expected = 1 if not rows else max(1, int(rows[0][1]) + 1)
        if command.narrative_chapter_cursor != expected:
            raise KernelError(
                "BOOK_PRODUCTION_CHAPTER_CURSOR_CONFLICT",
                "Narrative chapter cursor differs from accepted Book Authority history",
            )

    def _longform_design_qualification(
        self,
        cursor: Any,
        *,
        command: ResolveBookProductionInputCommand,
        book_design_version: str,
        plans: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        expected: list[tuple[str, str, Any]] = []
        stage_assets = (
            ("book_design.propose", (book_design_version,)),
            ("book_plan.generate", (plans["BOOK"][0]["asset_version_id"],)),
            (
                "volume_plan.generate",
                tuple(item["asset_version_id"] for item in plans["VOLUME"]),
            ),
            (
                "arc_plan.generate",
                tuple(item["asset_version_id"] for item in plans["ARC"]),
            ),
        )
        for stage, asset_version_ids in stage_assets:
            for asset_version_id in asset_version_ids:
                expected.extend(
                    (asset_version_id, profile.layer.value, profile)
                    for profile in required_qualification_profiles(stage)
                )
        version_ids = sorted({item[0] for item in expected})
        cursor.execute(
            """
            SELECT qualification.asset_version_id,
                   qualification.design_layer,
                   qualification.profile_id,
                   qualification.profile_version,
                   qualification.profile_hash,
                   qualification.qualification_hash,
                   qualification.evaluation_hash,
                   qualification.evaluator_execution_class,
                   qualification.source_operation_id
            FROM authority_narrative_design_qualification AS qualification
            JOIN authority_operation AS operation
              ON operation.operation_id=qualification.source_operation_id
            WHERE qualification.project_id=%s
              AND qualification.book_id=%s
              AND qualification.asset_version_id=ANY(%s)
              AND qualification.qualification_status='PASS'
              AND qualification.trust_boundary='INDEPENDENT'
              AND (
                    qualification.evaluator_execution_class='MODEL_PROVIDER'
                    OR (
                        %s
                        AND qualification.evaluator_execution_class='SCRIPTED_FIXTURE'
                    )
                  )
              AND (
                    qualification.evaluator_execution_class<>'MODEL_PROVIDER'
                    OR (
                        qualification.provider_model_call_asset_version_id IS NOT NULL
                        AND qualification.provider_model_call_content_hash IS NOT NULL
                        AND qualification.provider_evidence_hash IS NOT NULL
                        AND qualification.provider_result_hash IS NOT NULL
                        AND qualification.provider_route_snapshot_id IS NOT NULL
                    )
                  )
              AND operation.status IN ('WAITING_GATE', 'SUCCEEDED')
            ORDER BY qualification.asset_version_id,
                     qualification.design_layer,
                     qualification.created_at
            """,
            [
                command.project_id,
                command.book_id,
                version_ids,
                self.allow_scripted_qualification_fixture,
            ],
        )
        rows = cursor.fetchall()
        by_identity: dict[tuple[str, str], list[Any]] = {}
        for row in rows:
            by_identity.setdefault((str(row[0]), str(row[1])), []).append(row)
        receipts: list[dict[str, Any]] = []
        for asset_version_id, layer, profile in expected:
            matches = by_identity.get((asset_version_id, layer), [])
            if len(matches) != 1:
                raise KernelError(
                    "LONGFORM_DESIGN_QUALIFICATION_INCOMPLETE",
                    f"{layer} requires one current qualification receipt",
                )
            row = matches[0]
            if tuple(str(item) for item in row[2:5]) != (
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
            ):
                raise KernelError(
                    "LONGFORM_DESIGN_QUALIFICATION_STALE",
                    f"{layer} qualification differs from current policy",
                )
            receipts.append(
                {
                    "asset_version_id": asset_version_id,
                    "design_layer": layer,
                    "profile_id": str(row[2]),
                    "profile_version": str(row[3]),
                    "profile_hash": str(row[4]),
                    "qualification_hash": str(row[5]),
                    "evaluation_hash": str(row[6]),
                    "evaluator_execution_class": str(row[7]),
                    "source_operation_id": str(row[8]),
                }
            )
        required_layers = {
            NarrativeDesignLayer.STORY_INTENT.value,
            NarrativeDesignLayer.STORY_FOUNDATION.value,
            NarrativeDesignLayer.BOOK_ARCHITECTURE.value,
            NarrativeDesignLayer.VOLUME_ARCHITECTURE.value,
            NarrativeDesignLayer.NARRATIVE_ARC_GRAPH.value,
            NarrativeDesignLayer.CHARACTER_DEVELOPMENT.value,
            NarrativeDesignLayer.DISCLOSURE_OBLIGATION.value,
        }
        if {item["design_layer"] for item in receipts} != required_layers:
            raise KernelError(
                "LONGFORM_DESIGN_QUALIFICATION_INCOMPLETE",
                "global long-form design layers are incomplete",
            )
        return {
            "schema_version": "longform-design-qualification.v1",
            "admission": "LONGFORM_DESIGN_QUALIFIED",
            "project_id": command.project_id,
            "book_id": command.book_id,
            "book_version": command.expected_book_version,
            "required_layers": sorted(required_layers),
            "receipts": sorted(
                receipts,
                key=lambda item: (
                    item["design_layer"],
                    item["asset_version_id"],
                ),
            ),
        }

    @staticmethod
    def _validate_initial_narrative_state_pair(
        *,
        project_id: str,
        book_id: str,
        initial_roles: Mapping[str, dict[str, Any]],
    ) -> None:
        if not initial_roles:
            return
        if set(initial_roles) != set(_OPTIONAL_INITIAL_STATE_ROLE_TYPES):
            raise KernelError(
                "BOOK_INITIAL_NARRATIVE_STATE_INCOMPLETE",
                "initial Story State and Canon must be resolved together",
            )
        story = dict(initial_roles["initial_story_state_version"]["content"])
        canon = dict(initial_roles["initial_canon_snapshot_version"]["content"])
        if (
            story.get("contract_version") != "story-state-snapshot-v2"
            or canon.get("contract_version") != "canon-snapshot-v2"
            or story.get("project_id") != project_id
            or canon.get("project_id") != project_id
            or story.get("book_id") != book_id
            or canon.get("book_id") != book_id
            or int(story.get("accepted_through_chapter", -1)) != 0
            or int(canon.get("accepted_through_chapter", -1)) != 0
            or story.get("initial_state_boundary") != "BOOK_PRODUCTION_INPUT_SNAPSHOT"
            or canon.get("initial_state_boundary") != "BOOK_PRODUCTION_INPUT_SNAPSHOT"
            or not str(story.get("campaign_contract_identity") or "").startswith(
                "sha256:"
            )
            or story.get("campaign_contract_identity")
            != canon.get("campaign_contract_identity")
            or canon.get("story_state_hash") != story.get("state_hash")
            or story.get("state_hash")
            != canonical_hash(
                {key: value for key, value in story.items() if key != "state_hash"}
            )
            or canon.get("canon_hash")
            != canonical_hash(
                {key: value for key, value in canon.items() if key != "canon_hash"}
            )
        ):
            raise KernelError(
                "BOOK_INITIAL_NARRATIVE_STATE_INVALID",
                "initial Story State and Canon must be scoped, integrity-bound v2 inputs",
            )

    @staticmethod
    def _active_plans(
        cursor: Any, command: ResolveBookProductionInputCommand
    ) -> dict[str, list[dict[str, Any]]]:
        cursor.execute(
            """
            SELECT binding.contract_type, binding.asset_version_id,
                   COALESCE(binding.parent_version_id, ''), binding.logical_key,
                   version.content, version.content_hash, binding.freshness,
                   binding.execution_scope
            FROM active_story_plan_version AS active
            JOIN story_plan_binding AS binding ON binding.binding_id=active.binding_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=binding.asset_version_id
            WHERE active.project_id=%s AND active.book_id=%s
            ORDER BY binding.contract_type,
                     CASE
                       WHEN binding.contract_type='VOLUME'
                       THEN (version.content->'chapter_range'->>0)::INTEGER
                       ELSE 0
                     END,
                     active.activated_at ASC,
                     binding.logical_key
            """,
            [command.project_id, command.book_id],
        )
        result = {
            name: [] for name in ("BOOK", "VOLUME", "ARC", "CHAPTER_GROUP", "CHAPTER")
        }
        for row in cursor.fetchall():
            if str(row[6]) != "CURRENT":
                raise KernelError(
                    "BOOK_PRODUCTION_PLAN_STALE",
                    "Book Production cannot bind an Impacted or Stale plan",
                )
            result[str(row[0])].append(
                {
                    "asset_version_id": str(row[1]),
                    "parent_version_id": str(row[2]),
                    "logical_key": str(row[3]),
                    "content": dict(row[4]),
                    "content_hash": str(row[5]),
                    "execution_scope": str(row[7]),
                }
            )
        if len(result["BOOK"]) != 1 or not result["VOLUME"] or not result["ARC"]:
            raise KernelError(
                "BOOK_PRODUCTION_PLAN_SET_INCOMPLETE",
                "Book Production requires one BookPlan, a Volume Portfolio, and active ArcPlans",
            )
        if len(result["CHAPTER_GROUP"]) > 1:
            raise KernelError(
                "BOOK_PRODUCTION_GROUP_AMBIGUOUS",
                "Book Production has multiple active ChapterGroupPlans",
            )
        return result

    @staticmethod
    def _select_current_volume(
        volumes: list[dict[str, Any]], *, chapter_cursor: int
    ) -> dict[str, Any]:
        return _select_current_volume_from_portfolio(
            volumes, chapter_cursor=chapter_cursor
        )

    @staticmethod
    def _validate_plan_hierarchy(
        plans: dict[str, list[dict[str, Any]]],
        *,
        current_volume: dict[str, Any],
    ) -> None:
        book = plans["BOOK"][0]["asset_version_id"]
        if any(volume["parent_version_id"] != book for volume in plans["VOLUME"]):
            raise KernelError(
                "BOOK_PRODUCTION_PLAN_PARENT_INVALID",
                "every Volume Portfolio member must be a child of the active BookPlan",
            )
        if plans["CHAPTER_GROUP"] and (
            plans["CHAPTER_GROUP"][0]["parent_version_id"]
            != current_volume["asset_version_id"]
        ):
            raise KernelError(
                "BOOK_PRODUCTION_PLAN_PARENT_INVALID",
                "current ChapterGroupPlan is not a child of the current VolumePlan",
            )
        for arc in plans["ARC"]:
            spans = [
                str(item) for item in arc["content"].get("cross_volume_scope") or ()
            ]
            portfolio_order = [item["asset_version_id"] for item in plans["VOLUME"]]
            portfolio = set(portfolio_order)
            if (
                not spans
                or len(spans) != len(set(spans))
                or not set(spans).issubset(portfolio)
                or spans != [item for item in portfolio_order if item in set(spans)]
            ):
                raise KernelError(
                    "BOOK_PRODUCTION_ARC_VOLUME_INVALID",
                    "Canonical Arc scope must be a non-empty ordered subset of the Volume Portfolio",
                )

    @staticmethod
    def _select_current_relevant_arcs(
        arcs: list[dict[str, Any]],
        *,
        current_volume: dict[str, Any],
    ) -> tuple[str, ...]:
        current_id = str(current_volume["asset_version_id"])
        relevant = tuple(
            str(arc["asset_version_id"])
            for arc in arcs
            if current_id
            in {str(item) for item in arc["content"].get("cross_volume_scope") or ()}
        )
        if not relevant:
            raise KernelError(
                "BOOK_PRODUCTION_CURRENT_ARC_MISSING",
                "current Volume has no narratively relevant Canonical Arc",
            )
        return relevant

    @staticmethod
    def _validate_design_plan_compatibility(
        *,
        book_design: dict[str, Any],
        book_plan: dict[str, Any],
        volume_portfolio: list[dict[str, Any]],
        production_profile: dict[str, Any],
    ) -> None:
        design_ending = book_design.get("ending_contract") or book_design.get(
            "ending_intent"
        )
        plan_ending = book_plan.get("ending_contract")
        if (
            design_ending
            and plan_ending
            and canonical_hash(design_ending) != canonical_hash(plan_ending)
        ):
            raise KernelError(
                "BOOK_DESIGN_ENDING_PLAN_CONFLICT",
                "BookDesign and BookPlan Ending Contract differ",
            )
        planned = int(
            (book_plan.get("length_strategy") or {}).get("target_chapters") or 0
        )
        profiled = int(production_profile.get("target_chapter_count") or planned or 0)
        if planned <= 0 or profiled <= 0 or planned != profiled:
            raise KernelError(
                "BOOK_PRODUCTION_CHAPTER_RANGE_CONFLICT",
                "Production Profile target chapters differ from the active BookPlan",
            )
        portfolio_end = int(volume_portfolio[-1]["content"]["chapter_range"][1])
        volume_skeleton = list(book_plan.get("volume_skeleton") or ())
        if portfolio_end != planned or (
            volume_skeleton and len(volume_skeleton) != len(volume_portfolio)
        ):
            raise KernelError(
                "BOOK_PRODUCTION_VOLUME_PORTFOLIO_INCOMPLETE",
                "qualified Volume Portfolio must cover the BookPlan target and volume skeleton exactly",
            )

    @staticmethod
    def _asset_content(cursor: Any, version_id: str, project_id: str) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT version.content
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE version.asset_version_id=%s AND asset.project_id=%s
            """,
            [version_id, project_id],
        )
        row = cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_INPUT_ASSET_INVALID", "Book input asset is outside Project scope"
            )
        return dict(row[0])

    @staticmethod
    def _active_role_asset(
        cursor: Any,
        *,
        command: ResolveBookProductionInputCommand,
        role: str,
        asset_types: tuple[str, ...],
        requested_profile: str,
    ) -> dict[str, Any]:
        override_version = dict(command.role_asset_version_overrides).get(role, "")
        if override_version:
            cursor.execute(
                """
                SELECT version.asset_version_id, asset.asset_id,
                       version.content_hash, version.content
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id=asset.asset_id
                WHERE asset.project_id=%s AND asset.asset_type=ANY(%s)
                  AND version.asset_version_id=%s
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                  AND (COALESCE(version.content->>'book_id', '') IN ('', %s))
                """,
                [
                    command.project_id,
                    list(asset_types),
                    override_version,
                    command.book_id,
                ],
            )
        else:
            cursor.execute(
                """
                SELECT version.asset_version_id, asset.asset_id,
                       version.content_hash, version.content
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id=asset.asset_id
                WHERE asset.project_id=%s AND asset.asset_type=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                  AND (COALESCE(version.content->>'book_id', '') IN ('', %s))
                ORDER BY version.created_at DESC, version.version_number DESC
                """,
                [command.project_id, list(asset_types), command.book_id],
            )
        rows = cursor.fetchall()
        if requested_profile:
            rows = [
                row
                for row in rows
                if requested_profile
                in {
                    str(row[0]),
                    str(row[1]),
                    str(dict(row[3]).get("profile_id") or ""),
                    str(dict(row[3]).get("name") or ""),
                }
            ]
        asset_ids = {str(row[1]) for row in rows}
        if len(rows) != 1 or len(asset_ids) != 1:
            raise KernelError(
                "BOOK_PRODUCTION_ACTIVE_INPUT_AMBIGUOUS",
                f"Authority role {role} resolved {len(rows)} active versions",
            )
        row = rows[0]
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[2]),
            "content": dict(row[3]),
        }

    @staticmethod
    def _planning_deployments(
        cursor: Any, command: ResolveBookProductionInputCommand
    ) -> list[str]:
        cursor.execute(
            """
            SELECT deployment.deployment_id, binding.node_bindings
            FROM authority_capability_pack_activation AS activation
            JOIN authority_capability_pack_deployment AS deployment
              ON deployment.deployment_id=activation.active_deployment_id
            JOIN authority_capability_pack_binding_set AS binding
              ON binding.binding_set_id=deployment.binding_set_id
            WHERE deployment.deployment_status='ACTIVE'
              AND (
                activation.target_scope_type='SYSTEM'
                OR (activation.project_id=%s AND activation.target_scope_type='PROJECT')
                OR (activation.project_id=%s AND activation.workspace_id=%s
                    AND activation.target_scope_type='WORKSPACE')
                OR (activation.project_id=%s AND activation.workspace_id=%s
                    AND activation.book_id=%s AND activation.target_scope_type='BOOK')
              )
            """,
            [
                command.project_id,
                command.project_id,
                command.workspace_id,
                command.project_id,
                command.workspace_id,
                command.book_id,
            ],
        )
        rows = cursor.fetchall()
        expected = {
            name: GENERATOR_CATALOG[name].capability
            for name in (
                "book_plan.generate",
                "volume_plan.generate",
                "arc_plan.generate",
                "chapter_group_plan.generate",
                "chapter_plan.generate",
            )
        }
        compatible_nodes: set[str] = set()
        for _, bindings in rows:
            for item in list(bindings):
                node_id = str(item.get("workflow_node_id") or "")
                if node_id not in expected:
                    continue
                if (
                    str(item.get("execution_capability_id") or "") != expected[node_id]
                    or str(item.get("operation_definition_ref") or "")
                    != STORY_PLANNING_OPERATION_DEFINITION_REF
                    or str(item.get("commit_authority") or "")
                    != "STORY_DESIGN_AUTHORITY"
                    or not str(item.get("agent_definition_ref") or "")
                ):
                    raise KernelError(
                        "BOOK_PRODUCTION_CAPABILITY_PACK_INCOMPATIBLE",
                        f"Planning Pack node {node_id} is not runtime compatible",
                    )
                compatible_nodes.add(node_id)
        if not rows or compatible_nodes != set(expected):
            raise KernelError(
                "BOOK_PRODUCTION_CAPABILITY_PACK_INCOMPATIBLE",
                "active Capability Pack deployments do not cover all Planning Generators",
            )
        return sorted(str(row[0]) for row in rows)

    @staticmethod
    def _snapshot_asset_ids(snapshot: dict[str, Any]) -> tuple[str, ...]:
        scalar = (
            "book_record_version",
            "book_design_version",
            "book_plan_version",
            "current_volume_plan_version",
            "current_chapter_group_plan_version",
            *_ACTIVE_ROLE_TYPES.keys(),
            *_OPTIONAL_INITIAL_STATE_ROLE_TYPES.keys(),
        )
        values = [str(snapshot[key]) for key in scalar if snapshot.get(key)]
        values.extend(str(item) for item in snapshot["volume_portfolio_plan_versions"])
        values.extend(str(item) for item in snapshot["arc_portfolio_plan_versions"])
        return tuple(dict.fromkeys(values))

    def _input_assets(
        self, project_id: str, version_ids: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s)
                """,
                [project_id, list(version_ids)],
            )
            rows = uow.cursor.fetchall()
        found = {str(row[0]): str(row[1]) for row in rows}
        if set(found) != set(version_ids):
            raise KernelError(
                "BOOK_PRODUCTION_INPUT_ASSET_MISSING",
                "resolved Book Production input is missing from Authority storage",
            )
        return tuple(
            {"asset_version_id": version_id, "content_hash": found[version_id]}
            for version_id in version_ids
        )

    def _register_definition(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                book_production_input_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()


def book_production_input_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": [
            "project_id",
            "workspace_id",
            "book_id",
            "production_profile",
            "expected_book_version",
            "narrative_chapter_cursor",
            "expected_snapshot_hash",
            "role_asset_version_overrides",
        ],
        "properties": {
            "project_id": {"type": "string"},
            "workspace_id": {"type": "string"},
            "book_id": {"type": "string"},
            "production_profile": {"type": "string"},
            "expected_book_version": {"type": "integer"},
            "narrative_chapter_cursor": {"type": "integer"},
            "expected_snapshot_hash": {"type": "string"},
            "role_asset_version_overrides": {"type": "array"},
        },
        "additionalProperties": False,
    }
    return {
        "name": BOOK_INPUT_RESOLVE_DEFINITION,
        "definition_version": BOOK_INPUT_RESOLVE_VERSION,
        "family": "book_authority",
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": "book-production-input-resolve-command-v3",
        "result_schema_version": "book-production-input-snapshot-v3",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {"type": "BookProductionInputSnapshot"},
        "handler_key": BOOK_INPUT_RESOLVE_HANDLER,
        "handler_contract_version": "book-production-input-resolver-v3",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "authority_resolution_required": True,
            "caller_json_versions_forbidden": True,
            "stale_plan_fail_closed": True,
            "snapshot_immutable": True,
            "longform_design_qualification_required": True,
        },
        "idempotency_scope": "book:production-input-resolve",
        "concurrency_key_template": "book:{book_id}:production-input",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {"supported": False, "reason": "immutable snapshot"},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["book_authority", "book_production_supervisor"],
        "migration_owner": "book-authority",
        "completion_contract": {
            "version": "book-production-input-resolve-completion-v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["book.production_input.resolved"],
        },
    }


__all__ = [
    "BOOK_INPUT_RESOLVE_DEFINITION",
    "BookProductionInputResolver",
    "BookProductionInputSnapshot",
    "ResolveBookProductionInputCommand",
    "book_production_input_definition",
]
