"""Command/Attempt-backed semantic lifecycle for Story Design assets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command,
)
from novel_forge.modules.content_authority.scheduler import (
    ContentAuthorityScheduler,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import (
    DesignTransition,
    GENERATOR_CATALOG,
    GENERATOR_DESIGN_SCOPE,
    GENERATOR_DEFINITIONS,
    PlanningScope,
)
from .qualification import required_qualification_profiles
from .validators import validate_story_design_candidate


STORY_DESIGN_TRANSITION_DEFINITION = "story_design.lifecycle.transition"
STORY_DESIGN_TRANSITION_VERSION = "1.1.0"
STORY_DESIGN_TRANSITION_HANDLER = (
    "novel_forge.story_design_authority.lifecycle_transition"
)

_OPERATOR_AUTHOR_OPERATION_BY_GENERATOR = {
    "creative.candidates.generate": (
        "story_design.creative_foundation.author",
        "creative_foundation",
    ),
    "theme.candidates.generate": (
        "story_design.theme_contract.author",
        "theme_contract",
    ),
    "ending.intent.generate": (
        "story_design.ending_intent.author",
        "ending_intent",
    ),
    "reader.promise.generate": (
        "story_design.reader_promise.author",
        "reader_promise",
    ),
    "world.design.generate": (
        "story_design.world_bible.author",
        "world_bible",
    ),
    "character.cast.generate": (
        "story_design.character_cast.author",
        "character_cast",
    ),
}


@dataclass(frozen=True, slots=True)
class StoryDesignTransitionCommand:
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    asset_version_id: str
    content_hash: str
    logical_key: str
    generator_operation_name: str
    transition: DesignTransition
    planning_scope: PlanningScope
    expected_version: int
    source_kind: str = "GENERATED"
    evidence: dict[str, Any] | None = None


class _TransitionHandler:
    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "STORY_DESIGN_TRANSITION_INPUT_INVALID",
                "transition payload must be an object",
            )
        target = request.inputs
        if len(target) != 1:
            raise KernelError(
                "STORY_DESIGN_TRANSITION_INPUT_INVALID",
                "transition requires exactly one frozen target AssetVersion",
            )
        if target[0].asset_version_id != payload.get("asset_version_id"):
            raise KernelError(
                "STORY_DESIGN_TRANSITION_INPUT_MISMATCH",
                "transition target differs from the frozen AssetVersion",
            )
        transition = DesignTransition(str(payload.get("transition") or ""))
        generator = GENERATOR_CATALOG.get(
            str(payload.get("generator_operation_name") or "")
        )
        if generator is None:
            raise KernelError(
                "GENERATOR_DEFINITION_NOT_FOUND",
                "Story Design GeneratorDefinition is not registered",
            )
        return AuthorityHandlerOutput(
            asset_type="story_design_transition_receipt",
            output_key="story_design.transition.receipt",
            role="transition_evidence",
            content={
                "type": "StoryDesignTransitionReceipt",
                "contract_version": "story-design-transition-receipt-v1",
                "project_id": request.project_id,
                "asset_version_id": target[0].asset_version_id,
                "target_content_hash": target[0].content_hash,
                "logical_key": str(payload["logical_key"]),
                "generator_operation_name": generator.operation_name,
                "generator_definition_version": generator.definition_version,
                "candidate_type": generator.output_candidate_type,
                "transition": transition.value,
                "expected_version": int(payload["expected_version"]),
                "planning_scope": PlanningScope(str(payload["planning_scope"])).value,
                "design_scope": GENERATOR_DESIGN_SCOPE[generator.operation_name].value,
                "source_kind": str(payload["source_kind"]),
                "evidence": dict(payload.get("evidence") or {}),
            },
            qualification_policy="story-design-transition-v1",
            reference_asset_version_ids=(target[0].asset_version_id,),
            evidence={"deterministic": True, "model_calls": 0},
        )


class _Registry:
    def __init__(self) -> None:
        self.item = AuthorityHandlerRegistration(
            definition_name=STORY_DESIGN_TRANSITION_DEFINITION,
            definition_version=STORY_DESIGN_TRANSITION_VERSION,
            handler_key=STORY_DESIGN_TRANSITION_HANDLER,
            handler_contract_version="story-design-transition-handler-v1",
            output_asset_type="story_design_transition_receipt",
            output_key="story_design.transition.receipt",
            role="transition_evidence",
            completion_topic="story_design.transition.materialized",
            handler=_TransitionHandler(),
        )

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset({STORY_DESIGN_TRANSITION_HANDLER})

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        if (
            definition_name != STORY_DESIGN_TRANSITION_DEFINITION
            or definition_version != STORY_DESIGN_TRANSITION_VERSION
        ):
            raise KeyError((definition_name, definition_version))
        return self.item


class PostgresStoryDesignAssetAuthority:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "story-design-authority-worker",
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Story Design Authority requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.registry = _Registry()

    def transition(
        self,
        command: StoryDesignTransitionCommand,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        prepared = self.prepare_transition(command, principal=principal)
        generator = GENERATOR_CATALOG[command.generator_operation_name]
        with AuthorityUnitOfWork(self.database_url) as uow:
            result = uow.repositories.story_design.apply_transition(
                operation_id=str(prepared["operation_id"]),
                project_id=command.project_id,
                asset_version_id=command.asset_version_id,
                logical_key=command.logical_key,
                generator_operation_name=generator.operation_name,
                generator_definition_version=generator.definition_version,
                candidate_type=generator.output_candidate_type,
                planning_scope=command.planning_scope.value,
                design_scope=GENERATOR_DESIGN_SCOPE[generator.operation_name].value,
                transition=command.transition.value,
                expected_version=command.expected_version,
                source_kind=command.source_kind,
                evidence=dict(command.evidence or {}),
            )
            uow.commit()
        return result

    def prepare_transition(
        self,
        command: StoryDesignTransitionCommand,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        """Persist immutable transition execution evidence without projecting state.

        Planning activation uses this preparation seam before a separate atomic
        coordinator commits the Story Design projection and typed Planning
        binding in one PostgreSQL transaction. Other lifecycle transitions keep
        using :meth:`transition`, which projects immediately after preparation.
        """

        principal.require("story_design.authority.execute", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError(
                "Story Design transition actor must be the trusted Principal"
            )
        generator = GENERATOR_CATALOG.get(command.generator_operation_name)
        if generator is None:
            raise KernelError(
                "GENERATOR_DEFINITION_NOT_FOUND",
                "unknown Story Design GeneratorDefinition",
            )
        current_state: dict[str, Any] | None = None
        if command.transition is not DesignTransition.ENROLL:
            current_state = self.require(
                project_id=command.project_id,
                asset_version_id=command.asset_version_id,
            )
        if (
            command.transition is DesignTransition.ENROLL
            and command.source_kind == "OPERATOR_AUTHORED"
        ):
            self._require_operator_authored_candidate(command)
        if (
            command.transition is DesignTransition.SEMANTIC_VALIDATE
            and current_state is not None
            and str(current_state["source_kind"]) == "OPERATOR_AUTHORED"
        ):
            self._require_operator_semantic_evaluation(command, current_state)
        self._register_contracts()
        payload = {
            "asset_version_id": command.asset_version_id,
            "logical_key": command.logical_key,
            "generator_operation_name": generator.operation_name,
            "generator_definition_version": generator.definition_version,
            "candidate_type": generator.output_candidate_type,
            "transition": command.transition.value,
            "expected_version": command.expected_version,
            "planning_scope": command.planning_scope.value,
            "design_scope": GENERATOR_DESIGN_SCOPE[generator.operation_name].value,
            "source_kind": command.source_kind,
            "evidence": dict(command.evidence or {}),
        }
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": STORY_DESIGN_TRANSITION_DEFINITION,
                "definition_version": STORY_DESIGN_TRANSITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:story-design-transition",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": command.project_id,
                    "input_asset_version_ids": [command.asset_version_id],
                    "payload": payload,
                },
                "input_assets": [
                    {
                        "asset_version_id": command.asset_version_id,
                        "content_hash": command.content_hash,
                    }
                ],
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"story_design.authority.execute"}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, command.project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=principal.principal_id,
                    reason="Story Design transition input frozen",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id="",
                ),
            )
            start_saga(
                self.database_url,
                GraphCommandContext(
                    command.project_id,
                    principal.principal_id,
                    command.trace_id,
                    command.correlation_id,
                ),
                root_operation_id=operation_id,
            )
        ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            worker_id=self.worker_id,
        ).run_or_recover(
            operation_id=operation_id,
            project_id=command.project_id,
        )
        return {
            "operation_id": operation_id,
            "replayed": bool(admitted["replayed"]),
        }

    def require(self, *, project_id: str, asset_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.story_design.require(project_id, asset_version_id)

    def _require_operator_authored_candidate(
        self, command: StoryDesignTransitionCommand
    ) -> None:
        expected_authoring = _OPERATOR_AUTHOR_OPERATION_BY_GENERATOR.get(
            command.generator_operation_name
        )
        if expected_authoring is None:
            raise KernelError(
                "STORY_DESIGN_OPERATOR_AUTHORING_LINEAGE_INVALID",
                "generator has no governed operator-authoring operation",
            )
        operation_id = str((command.evidence or {}).get("authoring_operation_id") or "")
        if operation_id != str((command.evidence or {}).get("operation_id") or ""):
            raise KernelError(
                "STORY_DESIGN_OPERATOR_AUTHORING_LINEAGE_INVALID",
                "operator-authored candidate has inconsistent Operation lineage",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, operation.definition_name,
                       output.content_hash, asset.asset_type, version.content
                FROM authority_operation AS operation
                JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                 AND output.asset_version_id=%s
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE operation.operation_id=%s AND operation.project_id=%s
                  AND asset.project_id=operation.project_id
                """,
                [command.asset_version_id, operation_id, command.project_id],
            )
            row = uow.cursor.fetchone()
        if (
            row is None
            or str(row[0]) != "SUCCEEDED"
            or str(row[1]) != expected_authoring[0]
            or str(row[2]) != command.content_hash
            or str(row[3]) != expected_authoring[1]
        ):
            raise KernelError(
                "STORY_DESIGN_OPERATOR_AUTHORING_LINEAGE_INVALID",
                "operator-authored candidate is not an exact successful Content Authority output",
            )
        validate_story_design_candidate(
            content=dict(row[4]),
            project_id=command.project_id,
            generator_operation_name=command.generator_operation_name,
            planning_scope=command.planning_scope,
            logical_key=command.logical_key,
        )

    def _require_operator_semantic_evaluation(
        self,
        command: StoryDesignTransitionCommand,
        state: dict[str, Any],
    ) -> None:
        evidence = dict(command.evidence or {})
        evaluation_asset_version_id = str(
            evidence.get("evaluation_asset_version_id") or ""
        )
        qualification_hash = str(evidence.get("qualification_hash") or "")
        expected_profiles = required_qualification_profiles(
            command.generator_operation_name
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT qualification.design_layer, qualification.profile_id,
                       qualification.qualification_status,
                       qualification.qualification_hash,
                       qualification.evaluator_execution_class,
                       qualification.generation_operation_id,
                       qualification.evaluation_asset_version_id,
                       qualification.candidate_content_hash,
                       generation.actor_id, evaluation.actor_id,
                       evaluation.status
                FROM authority_narrative_design_qualification AS qualification
                JOIN authority_operation AS generation
                  ON generation.operation_id=qualification.generation_operation_id
                JOIN authority_operation AS evaluation
                  ON evaluation.operation_id=qualification.evaluation_operation_id
                WHERE qualification.project_id=%s
                  AND qualification.asset_version_id=%s
                ORDER BY qualification.design_layer, qualification.profile_id
                """,
                [command.project_id, command.asset_version_id],
            )
            rows = uow.cursor.fetchall()
        expected = {
            (profile.layer.value, profile.profile_id) for profile in expected_profiles
        }
        observed = {(str(row[0]), str(row[1])) for row in rows}
        authoring_operation_id = str(
            dict(state.get("execution_evidence") or {}).get("operation_id") or ""
        )
        if (
            not evaluation_asset_version_id
            or not qualification_hash.startswith("sha256:")
            or observed != expected
            or any(
                str(row[2]) != "PASS"
                or str(row[3]) != qualification_hash
                or str(row[4]) != "OPERATOR_REVIEW"
                or str(row[5]) != authoring_operation_id
                or str(row[6]) != evaluation_asset_version_id
                or str(row[7]) != command.content_hash
                or str(row[8]) == str(row[9])
                or str(row[10]) != "SUCCEEDED"
                for row in rows
            )
        ):
            raise KernelError(
                "STORY_DESIGN_OPERATOR_EVALUATION_REQUIRED",
                "operator-authored candidate requires an exact independent passing Narrative Evaluation",
            )

    def _register_contracts(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                _transition_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            for definition in GENERATOR_DEFINITIONS:
                uow.repositories.story_design.register_generator(asdict(definition))
            uow.commit()


def _transition_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["project_id", "input_asset_version_ids", "payload"],
        "properties": {
            "project_id": {"type": "string"},
            "input_asset_version_ids": {"type": "array"},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    return {
        "name": STORY_DESIGN_TRANSITION_DEFINITION,
        "definition_version": STORY_DESIGN_TRANSITION_VERSION,
        "family": "story_design_authority",
        "enabled": True,
        "definition_status": "integration_proven",
        "command_schema_version": "story-design-transition-command-v1",
        "result_schema_version": "story-design-transition-result-v1",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {
            "asset_type": "story_design_transition_receipt",
            "output_key": "story_design.transition.receipt",
        },
        "handler_key": STORY_DESIGN_TRANSITION_HANDLER,
        "handler_contract_version": "story-design-transition-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["story_design.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "target_asset_mutation": False,
            "semantic_activation_separate": True,
            "frozen_inputs_required": True,
            "story_design_candidate_asset_input_allowed": True,
        },
        "idempotency_scope": "project:story-design-transition",
        "concurrency_key_template": ("project:{project_id}:story-design-transition"),
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only transition receipts",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["story_design_active_version"],
        "migration_owner": "story-design-authority",
        "completion_contract": {
            "version": "story-design-transition-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": "story_design_transition_receipt",
                    "output_key": "story_design.transition.receipt",
                    "role": "transition_evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["story_design.transition.materialized"],
        },
    }


__all__ = [
    "PostgresStoryDesignAssetAuthority",
    "StoryDesignTransitionCommand",
]
