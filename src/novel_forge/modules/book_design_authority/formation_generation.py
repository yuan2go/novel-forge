from __future__ import annotations

from typing import Any

from novel_forge.modules.authority_security import Principal
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

from .formation_domain import FormationLayerInput, StoryFormationInput
from .foundation import FoundationRole


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
        # CONSTRAINT: Selection is the first independently qualified branch, not literary ranking.
        # INVARIANT: Unselected alternatives remain qualified candidates, never active Foundations.
        selected = candidates[0]
        key = f"{run['formation_run_id']}:{role.value}:0"
        state = self.planning.story_design.require(
            project_id=run["project_id"], asset_version_id=selected
        )
        if state["approval"] != "APPROVED":
            if policy["approval_mode"] != "AUTO":
                raise KernelError(
                    "STORY_FORMATION_APPROVAL_REQUIRED",
                    f"Review and approve selected candidate {selected}, then resume the same frozen Formation",
                )
            self.planning.approve_candidate(
                selected,
                principal=principal,
                idempotency_key=f"{key}:approve",
                trace_id=f"trace:{run['formation_run_id']}",
                correlation_id=run["root_operation_id"],
            )
        self.planning.activate_candidate(
            selected,
            principal=principal,
            idempotency_key=f"{key}:activate",
            trace_id=f"trace:{run['formation_run_id']}",
            correlation_id=run["root_operation_id"],
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
                raise KernelError(
                    "STORY_FORMATION_APPROVAL_REQUIRED",
                    f"Review and activate BookDesign {candidate.asset_version_id}, then resume Formation",
                )
        else:
            for action, decision in (
                (
                    "book_design.decide",
                    {
                        "decision": "APPROVE",
                        "reason": "Frozen AUTO Formation policy; independently evaluated Foundation synthesis",
                    },
                ),
                (
                    "book_design.activate",
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
                        payload=decision,
                        target_asset_version_id=candidate.asset_version_id,
                    ),
                    principal=principal,
                )
        return {
            "asset_version_id": candidate.asset_version_id,
            "content_hash": candidate.content_hash,
        }
