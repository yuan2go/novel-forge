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
        generation_failures: tuple[dict[str, str], ...] = (),
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
        self.generation_failures = generation_failures


class FormationGeneration:
    def __init__(
        self, planning: StoryPlanningGenerationApplication, *, book_design: Any = None
    ) -> None:
        self.book_design = book_design
        self.planning = planning
        self.database_url = planning.database_url
        self.query = AuthorityAssetQuery(self.database_url)

    def _require_creation_live(self, formation_run_id: str) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            if StoryFormationRepository(uow.cursor).cancellation(formation_run_id):
                raise KernelError("CREATION_CANCELLED", "No new generation after creation cancellation")

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
        author_selected = (frozen.generation_policy or {}).get("author_creative_foundation")
        if author_selected and role is FoundationRole.CREATIVE_FOUNDATION:
            with AuthorityUnitOfWork(self.database_url) as uow:
                return StoryFormationRepository(uow.cursor).authored_creative_layer(
                    project_id=run["project_id"], book_id=run["book_id"], asset_version_id=author_selected["asset_version_id"],
                    content_hash=author_selected["content_hash"])
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
        candidate_keys = {}
        generation_failures = []
        with AuthorityUnitOfWork(self.database_url) as uow:
            saved_failures = StoryFormationRepository(uow.cursor).approval_wait(run["formation_run_id"], stage).get("generation_failures", [])
        for ordinal in range(count):
            key = f"{run['formation_run_id']}:{role.value}:{ordinal}"
            retained_failure = None
            for failure in saved_failures:
                with AuthorityUnitOfWork(self.database_url) as uow:
                    if failure.get("asset_version_id"):
                        uow.cursor.execute("SELECT content->>'logical_key' FROM authority_asset_version WHERE asset_version_id=%s AND content_hash=%s", [failure["asset_version_id"],failure["content_hash"]])
                    else:
                        uow.cursor.execute("""SELECT generation.logical_key FROM authority_external_effect effect
                            JOIN authority_story_planning_generation generation ON generation.operation_id=effect.operation_id
                            WHERE effect.external_effect_id=%s AND effect.request_hash=%s AND effect.status='FAILED_FINAL'""", [failure["external_effect_id"],failure["request_hash"]])
                    failed_source = uow.cursor.fetchone()
                if failed_source and failed_source[0] == key:
                    retained_failure = failure
                    break
            if retained_failure:
                generation_failures.append(retained_failure)
                continue
            try:
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
                    execution_probe=lambda: self._require_creation_live(run["formation_run_id"]),
                    principal=principal,
                )
            except KernelError as error:
                if (role is not FoundationRole.CREATIVE_FOUNDATION or policy.get("creative_selection") != "AUTHOR_COMPARISON"
                        or error.code not in {"PLANNING_RESULT_REPAIR_BOUND_EXCEEDED", "PLANNING_REPAIR_BOUND_EXCEEDED", "MODEL_EFFECT_FINAL_PLANNING"}):
                    raise
                with AuthorityUnitOfWork(self.database_url) as uow:
                    uow.cursor.execute("""SELECT version.asset_version_id,version.content_hash FROM authority_asset_version version
                        JOIN authority_asset asset USING(asset_id) WHERE asset.project_id=%s
                        AND asset.asset_type='planning_generation_result_failure' AND version.content->>'book_id'=%s
                        AND version.content->>'logical_key'=%s ORDER BY version.created_at DESC LIMIT 1""", [run["project_id"],run["book_id"],key])
                    retained = uow.cursor.fetchone()
                if retained:
                    generation_failures.append({"asset_version_id": retained[0], "content_hash": retained[1], "reason_code": error.code})
                else:
                    with AuthorityUnitOfWork(self.database_url) as uow:
                        uow.cursor.execute("""SELECT effect.external_effect_id,effect.request_hash FROM authority_external_effect effect
                            JOIN authority_story_planning_generation generation ON generation.operation_id=effect.operation_id
                            WHERE generation.project_id=%s AND generation.book_id=%s AND generation.logical_key=%s
                              AND effect.status='FAILED_FINAL' ORDER BY effect.created_at DESC LIMIT 1""", [run["project_id"],run["book_id"],key])
                        terminal = uow.cursor.fetchone()
                    if not terminal:
                        raise
                    generation_failures.append({"external_effect_id": terminal[0], "request_hash": terminal[1], "reason_code": error.code})
                continue
            candidate_id = result.candidate_asset_version_id
            state = self.planning.story_design.require(
                project_id=run["project_id"], asset_version_id=candidate_id
            )
            from novel_forge.modules.story_design_authority.author_supervision import (
                supervised_state,
            )
            from novel_forge.modules.story_design_authority.creative_validation import validation_state
            if state["qualification"] != "QUALIFIED" and not supervised_state(state) and not validation_state(state):
                raise KernelError(
                    "STORY_FORMATION_GENERATION_BLOCKED",
                    f"{role.value} candidate {candidate_id} remains {state['qualification']}; no Foundation activation",
                )
            candidates.append(candidate_id)
            candidate_keys[candidate_id] = key
        with AuthorityUnitOfWork(self.database_url) as uow:
            selection = StoryFormationRepository(uow.cursor).author_selection(
                run["formation_run_id"], stage
            )
        if not candidates:
            raise KernelError("STORY_FORMATION_NO_ADMITTED_ALTERNATIVE", "All directions failed; original diagnostics remain retained")
        if (role is FoundationRole.CREATIVE_FOUNDATION
                and policy.get("creative_selection") == "AUTHOR_COMPARISON"
                and selection.get("decision") != "APPROVE"):
            proposed = self.query.require(project_id=run["project_id"], asset_version_id=candidates[0])
            raise FormationApprovalRequired(
                stage=stage, authority="STORY_PLANNING_AUTHORITY",
                candidate_asset_version_id=proposed.asset_version_id,
                candidate_content_hash=proposed.content_hash,
                candidate_asset_version_ids=tuple(candidates),
                generation_failures=tuple(generation_failures),
            )
        self._require_creation_live(run["formation_run_id"])
        selected = str(selection.get("candidate_asset_version_id") or candidates[0])
        if selected not in candidates or selection.get("decision") in {"REJECT", "REQUEST_CHANGES"}:
            raise KernelError("STORY_FORMATION_AUTHOR_SELECTION_DRIFT", "Frozen author selection cannot be consumed")
        key = candidate_keys[selected]
        state = self.planning.story_design.require(
            project_id=run["project_id"], asset_version_id=selected
        )
        candidate = self.query.require(
            project_id=run["project_id"], asset_version_id=selected
        )
        if selection and selection.get("candidate_content_hash") != candidate.content_hash:
            raise KernelError("STORY_FORMATION_AUTHOR_SELECTION_DRIFT", "Selected candidate hash changed")
        if state["approval"] != "APPROVED":
            if policy["approval_mode"] != "AUTO" or supervised_state(state):
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
        if policy["approval_mode"] == "AUTO" and not supervised_state(state):
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
                formation_run_id=run["formation_run_id"],
                project_id=run["project_id"],
                book_id=run["book_id"],
                candidate_id=selected,
                candidates=tuple(candidates),
                reasons=(
                    ("AUTHOR_SUPERVISED_SELECTION" if supervised_state(state) else "AUTHOR_SELECTED_QUALIFIED_BRANCH", str(selection["reason"]))
                    if selection else (
                        "FIRST_TEMPLATE_VALIDATED_BRANCH" if validation_state(state) else "FIRST_INDEPENDENTLY_QUALIFIED_BRANCH",
                        "Frozen brief and parent constraints passed; literary qualification NOT_RUN" if validation_state(state) else "Frozen brief and parent constraints passed; alternatives retain their independent evaluations",
                    )
                ),
            )

    def prepare_design(
        self, run: dict[str, Any], frozen: StoryFormationInput, *, principal: Principal
    ) -> dict[str, str]:
        from novel_forge.storage.foundation_repositories import (
            require_current_foundation_set,
        )

        from .application import BookDesignAuthorityCommand
        from .domain import (
            FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
            LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
            WORK_BOOK_DESIGN_SCHEMA_VERSION,
        )

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
        work_requirements = all(
            value.get("constraint_envelope", {}).get("contract_version")
            in {"foundation-generation.v2", "foundation-generation.v3"}
            for value in content.values()
        )
        if not invariants and not work_requirements:
            raise KernelError(
                "STORY_FORMATION_CONSTRAINTS_REQUIRED",
                "Generated foundations lack operational constraints",
            )
        payload = {
            "schema_version": (WORK_BOOK_DESIGN_SCHEMA_VERSION if all(value.get("constraint_envelope", {}).get("contract_version") == "foundation-generation.v3" for value in content.values()) else LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION)
            if work_requirements
            else FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
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
                    + (
                        "; " + ending["protagonist_cost"]
                        if ending["protagonist_cost"] is not None
                        else ""
                    ),
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
        from .author_supervision import proposed_supervision

        with AuthorityUnitOfWork(self.database_url) as uow:
            supervision = proposed_supervision(uow.cursor, project_id=run["project_id"], book_id=run["book_id"], asset_version_id=candidate.asset_version_id)
        if policy["approval_mode"] != "AUTO" or supervision:
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
                        "reason": "Frozen AUTO Formation policy; exact admitted Foundation synthesis",
                    },
                ),
                (
                    "book_design.activate",
                    "book_design.candidate.activate",
                    {
                        "reason": "Activate exact admitted Foundation synthesis"
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
