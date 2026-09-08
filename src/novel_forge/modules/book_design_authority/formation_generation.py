from __future__ import annotations

from typing import Any

from novel_forge.modules.authority_security import (
    Principal,
    build_manual_formation_continuation_evidence,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.application import (
    StoryPlanningGenerationApplication,
)
from novel_forge.modules.story_planning_runtime.domain import (
    StoryPlanningGenerationCommand,
)
from novel_forge.modules.story_planning_runtime.foundation_generation import (
    FOUNDATION_GENERATORS,
)
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.story_formation_repositories import StoryFormationRepository

from .formation_domain import (
    FormationLayerInput,
    StoryFormationInput,
    build_formation_auto_decision_evidence,
)
from .foundation import FoundationRole


class FormationApprovalRequired(KernelError):
    def __init__(
        self,
        *,
        stage: str,
        authority: str,
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        candidate_asset_version_ids: tuple[str, ...],
    ) -> None:
        super().__init__(
            "STORY_FORMATION_APPROVAL_REQUIRED",
            "Review and approve the exact frozen Formation candidate, then resume",
        )
        self.stage = stage
        self.authority = authority
        self.candidate_asset_version_id = candidate_asset_version_id
        self.candidate_content_hash = candidate_content_hash
        self.candidate_asset_version_ids = candidate_asset_version_ids


class FormationGeneration:
    def __init__(
        self, planning: StoryPlanningGenerationApplication, *, book_design: Any = None
    ) -> None:
        self.book_design = book_design
        self.planning = planning
        self.database_url = planning.database_url
        self.query = AuthorityAssetQuery(self.database_url)

    def prepare_layer(
        self, run: dict[str, Any], frozen: StoryFormationInput, *, principal: Principal
    ) -> FormationLayerInput | None:
        stage = str(run["current_stage"])
        if stage in {"BOOK_DESIGN", "COMPLETE", "CREATIVE_FOUNDATION"}:
            return None
        role = (
            FoundationRole.CREATIVE_FOUNDATION
            if stage == "CREATIVE_SEARCH"
            else FoundationRole(stage)
        )
        generator = next(
            name for name, item in FOUNDATION_GENERATORS.items() if item is role
        )
        brief = self.query.require(
            project_id=run["project_id"],
            asset_version_id=frozen.creative_brief_asset_version_id,
        )
        if (
            brief.asset_type != "creative_brief"
            or brief.content_hash != frozen.creative_brief_content_hash
        ):
            raise KernelError(
                "STORY_FORMATION_BRIEF_DRIFT",
                "Formation must consume its exact author brief",
            )
        inputs = {"creative_brief": brief.asset_version_id}
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = StoryFormationRepository(uow.cursor)
            for parent in role.required_parents:
                inputs[parent.value.lower()] = repository.stage_input(
                    run["formation_run_id"], parent
                ).asset_version_id
        policy = dict(frozen.generation_policy or {})
        count = (
            policy["creative_candidates"]
            if role is FoundationRole.CREATIVE_FOUNDATION
            else 1
        )
        candidates = []
        for ordinal in range(count):
            key = f"{run['formation_run_id']}:{role.value}:{ordinal}"
            result = self.planning.generate(
                StoryPlanningGenerationCommand(
                    project_id=run["project_id"],
                    workspace_id=run["workspace_id"],
                    book_id=run["book_id"],
                    actor_id=principal.principal_id,
                    generator_operation_name=generator,
                    logical_key=key,
                    input_versions=inputs,
                    idempotency_key=f"{key}:generate",
                    trace_id=f"trace:{run['formation_run_id']}",
                    correlation_id=run["root_operation_id"],
                ),
                principal=principal,
            )
            candidate_id = result.candidate_asset_version_id
            state = self.planning.story_design.require(
                project_id=run["project_id"], asset_version_id=candidate_id
            )
            if state["qualification"] != "QUALIFIED":
                raise KernelError(
                    "STORY_FORMATION_GENERATION_BLOCKED",
                    f"{role.value} candidate {candidate_id} remains {state['qualification']}; no Foundation activation",
                )
            candidates.append(candidate_id)
        selected = candidates[0]
        key = f"{run['formation_run_id']}:{role.value}:0"
        state = self.planning.story_design.require(
            project_id=run["project_id"], asset_version_id=selected
        )
        candidate = self.query.require(
            project_id=run["project_id"], asset_version_id=selected
        )
        if state["approval"] != "APPROVED":
            if policy["approval_mode"] != "AUTO":
                raise FormationApprovalRequired(
                    stage=str(run["current_stage"]),
                    authority="STORY_PLANNING_AUTHORITY",
                    candidate_asset_version_id=selected,
                    candidate_content_hash=candidate.content_hash,
                    candidate_asset_version_ids=tuple(candidates),
                )
            approval_evidence = build_formation_auto_decision_evidence(
                frozen=frozen,
                action="story_planning.candidate.approve",
                candidate_asset_version_id=selected,
                candidate_content_hash=candidate.content_hash,
                executed_by_principal_id=principal.principal_id,
            )
            self.planning.approve_candidate(
                selected,
                principal=principal,
                idempotency_key=f"{key}:approve",
                trace_id=f"trace:{run['formation_run_id']}",
                correlation_id=run["root_operation_id"],
                decision_evidence=approval_evidence,
            )
        if policy["approval_mode"] == "AUTO":
            activation_evidence = build_formation_auto_decision_evidence(
                frozen=frozen,
                action="story_planning.candidate.activate",
                candidate_asset_version_id=selected,
                candidate_content_hash=candidate.content_hash,
                executed_by_principal_id=principal.principal_id,
            )
        else:
            activation_evidence = self._manual_activation_evidence(
                run=run,
                frozen=frozen,
                state=state,
                candidate_asset_version_id=selected,
                candidate_content_hash=candidate.content_hash,
                principal=principal,
            )
        self.planning.activate_candidate(
            selected,
            principal=principal,
            idempotency_key=f"{key}:activate",
            trace_id=f"trace:{run['formation_run_id']}",
            correlation_id=run["root_operation_id"],
            decision_evidence=activation_evidence,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            return StoryFormationRepository(uow.cursor).generated_layer(
                project_id=run["project_id"],
                book_id=run["book_id"],
                candidate_id=selected,
                candidates=tuple(candidates),
                reasons=(
                    "FIRST_INDEPENDENTLY_QUALIFIED_BRANCH",
                    "Frozen brief and parent constraints passed; alternatives retain their independent evaluations",
                ),
            )

    def prepare_design(
        self, run: dict[str, Any], frozen: StoryFormationInput, *, principal: Principal
    ) -> dict[str, str]:
        from novel_forge.storage.foundation_repositories import (
            require_current_foundation_set,
        )
        from .application import BookDesignAuthorityCommand
        from .domain import FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION

        if self.book_design is None:
            raise KernelError(
                "STORY_FORMATION_DESIGN_NOT_CONFIGURED",
                "Formation requires the existing Book Design Authority",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            foundation = require_current_foundation_set(
                uow.cursor, project_id=run["project_id"], book_id=run["book_id"]
            )
            repository = StoryFormationRepository(uow.cursor)
            layers = {
                role: repository.stage_input(run["formation_run_id"], role)
                for role in FoundationRole
            }
        content = {
            role: self.query.require(
                project_id=run["project_id"], asset_version_id=layer.asset_version_id
            ).content["candidate_payload"]
            for role, layer in layers.items()
        }
        creative = content[FoundationRole.CREATIVE_FOUNDATION]
        theme = content[FoundationRole.THEME_CONTRACT]
        ending = content[FoundationRole.ENDING_INTENT]
        promise = content[FoundationRole.READER_PROMISE]
        policy = dict(frozen.generation_policy or {})
        invariants = list(
            dict.fromkeys(
                item for value in content.values() for item in value["constraints"]
            )
        )
        if not invariants:
            raise KernelError(
                "STORY_FORMATION_CONSTRAINTS_REQUIRED",
                "Generated foundations lack operational constraints",
            )
        payload = {
            "schema_version": FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
            "title": policy["title"],
            "target_chapters": policy["target_chapters"],
            "foundation_set": foundation.to_dict(),
            "book_invariants": invariants,
            "cross_layer_synthesis": [
                {
                    "synthesis_id": "conflict-and-theme",
                    "source_roles": ["CREATIVE_FOUNDATION", "THEME_CONTRACT"],
                    "narrative_function": creative["narrative_engine"],
                    "constraint": theme["thematic_question"],
                    "downstream_scope": "BOOK",
                },
                {
                    "synthesis_id": "promise-and-ending",
                    "source_roles": ["READER_PROMISE", "ENDING_INTENT"],
                    "narrative_function": promise["reader_promise"],
                    "constraint": ending["ending_direction"]
                    + "; "
                    + ending["protagonist_cost"],
                    "downstream_scope": "BOOK",
                },
            ],
            "narrative_dna": {
                "core_question": theme["thematic_question"],
                "recurring_choice": creative["core_conflict"],
                "cost_logic": ending["protagonist_cost"],
                "distinctive_mechanism": creative["differentiation"],
                "emotional_contract": creative["emotional_contract"],
            },
        }
        common = dict(
            project_id=run["project_id"],
            workspace_id=run["workspace_id"],
            book_id=run["book_id"],
            actor_id=principal.principal_id,
            service_identity="story-formation",
            expected_book_version=int(run["expected_book_version"]),
            trace_id=f"trace:{run['formation_run_id']}",
            correlation_id=run["root_operation_id"],
        )
        key = f"{run['formation_run_id']}:book-design"
        proposed = self.book_design.execute(
            BookDesignAuthorityCommand(
                **common,
                definition_name="book_design.propose",
                idempotency_key=f"{key}:propose",
                payload=payload,
            ),
            principal=principal,
        )
        candidate = self.query.require(
            project_id=run["project_id"], asset_version_id=proposed["asset_version_id"]
        )
        if policy["approval_mode"] != "AUTO":
            from .query import BookDesignAuthorityQuery

            book = BookDesignAuthorityQuery(self.database_url).require_book(
                project_id=run["project_id"], book_id=run["book_id"]
            )
            if book["active_book_design_version_id"] != candidate.asset_version_id:
                raise FormationApprovalRequired(
                    stage=str(run["current_stage"]),
                    authority="BOOK_DESIGN_AUTHORITY",
                    candidate_asset_version_id=candidate.asset_version_id,
                    candidate_content_hash=candidate.content_hash,
                    candidate_asset_version_ids=(candidate.asset_version_id,),
                )
        else:
            for action, auto_action, decision in (
                (
                    "book_design.decide",
                    "book_design.candidate.decide",
                    {
                        "decision": "APPROVE",
                        "reason": "Frozen AUTO Formation policy; independently evaluated Foundation synthesis",
                    },
                ),
                (
                    "book_design.activate",
                    "book_design.candidate.activate",
                    {
                        "reason": "Activate exact independently evaluated Foundation synthesis"
                    },
                ),
            ):
                self.book_design.execute(
                    BookDesignAuthorityCommand(
                        **common,
                        definition_name=action,
                        idempotency_key=f"{key}:{action}",
                        payload={
                            **decision,
                            "formation_auto_decision": (
                                build_formation_auto_decision_evidence(
                                    frozen=frozen,
                                    action=auto_action,
                                    candidate_asset_version_id=(
                                        candidate.asset_version_id
                                    ),
                                    candidate_content_hash=candidate.content_hash,
                                    executed_by_principal_id=(
                                        principal.principal_id
                                    ),
                                )
                            ),
                        },
                        target_asset_version_id=candidate.asset_version_id,
                    ),
                    principal=principal,
                )
        return {
            "asset_version_id": candidate.asset_version_id,
            "content_hash": candidate.content_hash,
        }

    def _manual_activation_evidence(
        self,
        *,
        run: dict[str, Any],
        frozen: StoryFormationInput,
        state: dict[str, Any],
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        principal: Principal,
    ) -> dict[str, Any]:
        approval_operation_id = str(state.get("updated_by_operation_id") or "")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT actor_id FROM authority_operation WHERE operation_id=%s",
                [approval_operation_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "STORY_FORMATION_APPROVAL_EVIDENCE_MISSING",
                "approved candidate has no authoritative approval Operation",
            )
        return build_manual_formation_continuation_evidence(
            formation_run_id=str(run["formation_run_id"]),
            formation_input_digest=frozen.digest,
            project_id=str(run["project_id"]),
            workspace_id=str(run["workspace_id"]),
            book_id=str(run["book_id"]),
            action="story_planning.candidate.activate",
            candidate_asset_version_id=candidate_asset_version_id,
            candidate_content_hash=candidate_content_hash,
            approved_by_principal_id=str(row[0]),
            approval_operation_id=approval_operation_id,
            executed_by_principal_id=principal.principal_id,
        )


__all__ = ["FormationApprovalRequired", "FormationGeneration"]
