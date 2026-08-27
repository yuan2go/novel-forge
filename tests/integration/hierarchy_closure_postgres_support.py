"""Canonical PostgreSQL fixture support for hierarchy-closure qualification.

The default preparation path materializes prequalified StoryDesign evidence to
keep unrelated integration tests bounded, then exercises the real durable
Formation coordinator and BookDesign Authority.  The qualification test sets
``full_story_design_lifecycle`` to prove every StoryDesign transition as well.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority import (
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
    BookDesignAuthorityQuery,
    BookDesignSemanticEvaluationCommand,
    FormationLayerInput,
    FoundationRole,
    StartStoryFormationCommand,
    StoryFormationApplication,
    StoryFormationInput,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.story_design_authority import (
    DesignTransition,
    GENERATOR_CATALOG,
    GENERATOR_DESIGN_SCOPE,
    GENERATOR_DEFINITIONS,
    PlanningScope,
    PostgresStoryDesignAssetAuthority,
    StoryDesignTransitionCommand,
    scripted_qualification,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_story_formation_claim
from tests.integration.authority_postgres_support import (
    insert_definition,
    insert_operation,
    transaction,
)


_GENERATOR_BY_ROLE = {
    FoundationRole.CREATIVE_FOUNDATION: "creative.candidates.generate",
    FoundationRole.THEME_CONTRACT: "theme.candidates.generate",
    FoundationRole.ENDING_INTENT: "ending.intent.generate",
    FoundationRole.READER_PROMISE: "reader.promise.generate",
    FoundationRole.WORLD_BIBLE: "world.design.generate",
    FoundationRole.CHARACTER_CAST: "character.cast.generate",
}


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _payload(
    role: FoundationRole,
    *,
    parent_candidates: dict[FoundationRole, dict[str, str]],
    alternate: bool = False,
) -> dict[str, Any]:
    suffix = " through contested testimony" if alternate else ""
    common = {
        "objective": f"Establish {role.value.lower()} for a causal serial novel",
    }
    if role.required_parents:
        common["foundation_parent_bindings"] = {
            parent.value: {
                "asset_version_id": parent_candidates[parent]["asset_version_id"],
                "content_hash": parent_candidates[parent]["content_hash"],
            }
            for parent in role.required_parents
        }
    if role is FoundationRole.CREATIVE_FOUNDATION:
        return {
            **common,
            "target_reader": "adult speculative mystery readers",
            "why_worth_writing": "public truth creates personal responsibility",
            "genre": "speculative mystery",
            "subgenre": "institutional mystery",
            "core_desire": "restore erased belonging",
            "core_fear": "truth will expose the people it should protect",
            "core_conflict": "witnesses challenge a self-editing archive" + suffix,
            "narrative_engine": "each anomaly forces disclosure or concealment",
            "differentiation": "geography changes through accountable choices",
            "emotional_contract": "wonder becomes costly shared responsibility",
            "serialization_potential": "each district exposes a distinct bargain",
        }
    if role is FoundationRole.THEME_CONTRACT:
        return {
            **common,
            "thematic_question": "Can public truth remain humane under pressure?",
            "genre": "speculative mystery",
        }
    if role is FoundationRole.ENDING_INTENT:
        return {
            **common,
            "ending_direction": "collective custody replaces solitary control",
            "protagonist_cost": "Mara surrenders exclusive certainty",
            "genre": "speculative mystery",
        }
    if role is FoundationRole.READER_PROMISE:
        return {
            **common,
            "reader_promise": "Every discovery forces a costly public choice",
            "genre": "speculative mystery",
        }
    if role is FoundationRole.WORLD_BIBLE:
        return {
            **common,
            "rules": [
                {
                    "rule": "A witnessed place resists erasure for seven days",
                    "cost": "the witness becomes publicly exposed",
                    "exception": "a witness may formally recant",
                    "consequence": "access remains open while testimony stands",
                    "narrative_function": "turn knowledge into costly agency",
                }
            ],
        }
    return {
        **common,
        "characters": [
            {
                "character_id": "mara",
                "desire": "restore the erased district",
                "need": "share uncertain evidence",
                "fear": "causing another erasure",
                "wound": "a failed solitary proof",
                "false_belief": "only certainty protects people",
                "values": ["truth", "care"],
                "moral_boundary": "never fabricate a witness",
                "agency": "chooses when and how evidence becomes public",
                "capability": "reads archival topology",
                "weakness": "withholds uncertainty",
                "voice": "precise until emotionally cornered",
                "secret": "her first map caused harm",
                "relationship_function": "learn accountable trust",
                "arc_direction": "certainty becomes collective responsibility",
            }
        ],
    }


def _candidate_content(
    *,
    project_id: str,
    generator: str,
    logical_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "story_design.authority.v1",
        "project_id": project_id,
        "generator_operation_name": generator,
        "planning_scope": PlanningScope.NOT_APPLICABLE.value,
        "logical_key": logical_key,
        "candidate_payload": payload,
    }


def _seed_candidate_and_evaluation(
    *,
    project_id: str,
    role: FoundationRole,
    label: str,
    alternate: bool,
    parent_candidates: dict[FoundationRole, dict[str, str]],
) -> dict[str, str]:
    generator = _GENERATOR_BY_ROLE[role]
    logical_key = f"foundation:{role.value.lower()}:{label}"
    content = _candidate_content(
        project_id=project_id,
        generator=generator,
        logical_key=logical_key,
        payload=_payload(
            role,
            parent_candidates=parent_candidates,
            alternate=alternate,
        ),
    )
    content_hash = _hash(content)
    asset_id = f"fixture:{project_id}:foundation:{role.value.lower()}:{label}"
    asset_version_id = f"{asset_id}:v1"
    generation_definition = f"fixture.foundation.generate.{uuid4()}"
    generation_operation_id = f"operation:foundation-generate:{uuid4()}"
    evaluation_definition = f"fixture.foundation.evaluate.{uuid4()}"
    evaluation_operation_id = f"operation:foundation-evaluate:{uuid4()}"
    evaluation = {
        "schema_version": "narrative-design-evaluation.v1",
        "project_id": project_id,
        "candidate_asset_version_id": asset_version_id,
        "candidate_content_hash": content_hash,
        "generation_operation_id": generation_operation_id,
        "evaluation_operation_id": evaluation_operation_id,
        "evaluation_attempt_id": f"fixture-evaluation-attempt:{uuid4()}",
        "evaluator_execution_class": "SCRIPTED_FIXTURE",
        "evaluation": {"coherence": "PASS", "fixture_protocol_only": True},
        "qualification": {
            "status": "PASS",
            "fixture_protocol_only": True,
            "real_provider_proven": False,
            "production_verified": False,
        },
        "evaluation_evidence_hash": _hash(
            {"candidate": asset_version_id, "evaluation": evaluation_operation_id}
        ),
        "provider_evidence_asset_version_ids": [],
        "provider_evidence": [],
    }
    qualification_hash = _hash(evaluation)
    qualification_asset_id = f"{asset_id}:qualification"
    qualification_version_id = f"{qualification_asset_id}:v1"
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, generation_definition)
        insert_operation(
            cursor,
            operation_id=generation_operation_id,
            definition_name=generation_definition,
            project_id=project_id,
            status="SUCCEEDED",
        )
        cursor.execute(
            """
            UPDATE authority_operation
            SET input_asset_snapshot=%s
            WHERE operation_id=%s
            """,
            [
                Jsonb(
                    [
                        {
                            "asset_version_id": parent_candidates[parent][
                                "asset_version_id"
                            ],
                            "content_hash": parent_candidates[parent]["content_hash"],
                            "project_id": project_id,
                        }
                        for parent in role.required_parents
                    ]
                ),
                generation_operation_id,
            ],
        )
        insert_definition(cursor, evaluation_definition)
        insert_operation(
            cursor,
            operation_id=evaluation_operation_id,
            definition_name=evaluation_definition,
            project_id=project_id,
            status="SUCCEEDED",
        )
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
            [asset_id, project_id, role.value.lower()],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,eligibility,
                governance,content,content_hash,schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
            """,
            [
                asset_version_id,
                asset_id,
                Jsonb(content),
                content_hash,
                f"{role.value.lower().replace('_', '-')}.v1",
            ],
        )
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'narrative_design_evaluation')",
            [qualification_asset_id, project_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,eligibility,
                governance,content,content_hash,schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,
                      'narrative-design-evaluation.v1')
            """,
            [
                qualification_version_id,
                qualification_asset_id,
                Jsonb(evaluation),
                qualification_hash,
            ],
        )
        cursor.execute(
            """
            INSERT INTO authority_operation_output_asset(
                operation_id,asset_id,asset_version_id,output_key,role,content_hash
            ) VALUES (%s,%s,%s,'story_design.semantic_evaluation',
                      'qualification_evidence',%s)
            """,
            [
                evaluation_operation_id,
                qualification_asset_id,
                qualification_version_id,
                qualification_hash,
            ],
        )
    return {
        "role": role.value,
        "logical_key": logical_key,
        "generator": generator,
        "asset_version_id": asset_version_id,
        "content_hash": content_hash,
        "schema_version": f"{role.value.lower().replace('_', '-')}.v1",
        "generation_operation_id": generation_operation_id,
        "qualification_evidence_asset_version_id": qualification_version_id,
        "qualification_hash": qualification_hash,
        "evaluation_operation_id": evaluation_operation_id,
    }


def _activate_story_design(
    *,
    database_url: str,
    project_id: str,
    workspace_id: str,
    candidate: dict[str, str],
    principal: Principal,
    full_lifecycle: bool,
    activate: bool,
    release_sha: str,
) -> str:
    generator = candidate["generator"]
    evidence = {
        "production_execution_gateway_backed": True,
        "operation_id": candidate["generation_operation_id"],
        "attempt_id": f"fixture-generation-attempt:{uuid4()}",
        "route_snapshot_id": "fixture-route-snapshot",
        "input_manifest_ref": "fixture-input-manifest",
        "validation_manifest_ref": "fixture-validation-manifest",
        "usage_receipt_ref": "fixture-usage-receipt",
        "cost_receipt_ref": "fixture-cost-receipt",
        "fixture_protocol_only": True,
        "real_provider_proven": False,
        "production_verified": False,
    }
    if full_lifecycle:
        authority = PostgresStoryDesignAssetAuthority(
            database_url,
            application_build_id="hierarchy-closure-qualification",
            commit_sha=release_sha,
        )
        state: dict[str, Any] = {"version": 0}
        transitions = [
            DesignTransition.ENROLL,
            DesignTransition.MATERIALIZE,
            DesignTransition.STRUCTURAL_VALIDATE,
            DesignTransition.SEMANTIC_VALIDATE,
            DesignTransition.QUALIFY,
        ]
        if activate:
            transitions.extend(
                [
                    DesignTransition.SUBMIT_APPROVAL,
                    DesignTransition.APPROVE,
                    DesignTransition.ACTIVATE,
                ]
            )
        for transition in transitions:
            transition_evidence = (
                evidence if transition is DesignTransition.ENROLL else {"passed": True}
            )
            state = authority.transition(
                StoryDesignTransitionCommand(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    actor_id=principal.principal_id,
                    trace_id=f"trace:{project_id}:story-design",
                    correlation_id=f"correlation:{project_id}:formation",
                    idempotency_key=(
                        f"{candidate['asset_version_id']}:{transition.value}"
                    ),
                    asset_version_id=candidate["asset_version_id"],
                    content_hash=candidate["content_hash"],
                    logical_key=candidate["logical_key"],
                    generator_operation_name=generator,
                    transition=transition,
                    planning_scope=PlanningScope.NOT_APPLICABLE,
                    expected_version=int(state["version"]),
                    evidence=transition_evidence,
                ),
                principal=principal,
            )
        return str(state["updated_by_operation_id"])

    with AuthorityUnitOfWork(database_url) as uow:
        for definition in GENERATOR_DEFINITIONS:
            uow.repositories.story_design.register_generator(asdict(definition))
        activation_definition = f"fixture.foundation.activate.{uuid4()}"
        activation_operation_id = f"operation:foundation-activate:{uuid4()}"
        insert_definition(uow.cursor, activation_definition)
        insert_operation(
            uow.cursor,
            operation_id=activation_operation_id,
            definition_name=activation_definition,
            project_id=project_id,
            status="SUCCEEDED",
        )
        lifecycle = "ACTIVE" if activate else "MATERIALIZED"
        approval = "APPROVED" if activate else "NOT_REQUESTED"
        uow.cursor.execute(
            """
            INSERT INTO authority_story_design_version_state(
                project_id,asset_version_id,logical_key,generator_operation_name,
                generator_definition_version,candidate_type,lifecycle,
                qualification,approval,freshness,planning_scope,design_scope,
                source_kind,execution_evidence,created_by_operation_id,
                updated_by_operation_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,'QUALIFIED',%s,'CURRENT',
                      'NOT_APPLICABLE',%s,'GENERATED',%s,%s,%s)
            """,
            [
                project_id,
                candidate["asset_version_id"],
                candidate["logical_key"],
                generator,
                GENERATOR_CATALOG[generator].definition_version,
                GENERATOR_CATALOG[generator].output_candidate_type,
                lifecycle,
                approval,
                GENERATOR_DESIGN_SCOPE[generator].value,
                Jsonb(evidence),
                activation_operation_id,
                activation_operation_id,
            ],
        )
        if activate:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_design_active_version(
                    project_id,logical_key,asset_version_id,
                    activated_by_operation_id
                ) VALUES (%s,%s,%s,%s)
                """,
                [
                    project_id,
                    candidate["logical_key"],
                    candidate["asset_version_id"],
                    activation_operation_id,
                ],
            )
        uow.commit()
    return activation_operation_id


def _book_design_payload(foundation: Any, *, target_chapters: int) -> dict[str, Any]:
    return {
        "schema_version": FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
        "title": "The Glass Harbor",
        "target_chapters": target_chapters,
        "foundation_set": foundation.to_dict(),
        "book_invariants": [
            "Accepted truth changes only through Chapter acceptance",
            "Every discovery forces a cost-bearing character choice",
        ],
        "cross_layer_synthesis": [
            {
                "synthesis_id": "witness-choice",
                "source_roles": [
                    "CREATIVE_FOUNDATION",
                    "THEME_CONTRACT",
                    "WORLD_BIBLE",
                    "CHARACTER_CAST",
                ],
                "narrative_function": "convert discovery into accountable agency",
                "constraint": "no discovery resolves without a character choice",
                "downstream_scope": "BOOK",
            }
        ],
        "narrative_dna": {
            "core_question": "Who owns truth?",
            "recurring_choice": "Certainty or accountable disclosure",
            "cost_logic": "Every fact exposes a witness",
            "distinctive_mechanism": "Maps change physical access",
            "emotional_contract": "Discovery brings hope and public cost",
        },
    }


def seed_ready_story_foundation(
    database_url: str,
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    principal: Principal,
    target_chapters: int,
    release_sha: str,
    full_story_design_lifecycle: bool = False,
    exercise_formation_recovery: bool = False,
) -> dict[str, Any]:
    """Build the exact Foundation set and BookDesign v5 through real runtime gates."""

    selected: dict[FoundationRole, dict[str, str]] = {}
    alternates: dict[FoundationRole, tuple[str, ...]] = {}
    for role in FoundationRole:
        candidate = _seed_candidate_and_evaluation(
            project_id=project_id,
            role=role,
            label="selected",
            alternate=False,
            parent_candidates=selected,
        )
        candidate["activation_operation_id"] = _activate_story_design(
            database_url=database_url,
            project_id=project_id,
            workspace_id=workspace_id,
            candidate=candidate,
            principal=principal,
            full_lifecycle=full_story_design_lifecycle,
            activate=True,
            release_sha=release_sha,
        )
        selected[role] = candidate
        alternates[role] = (candidate["asset_version_id"],)
    alternate = _seed_candidate_and_evaluation(
        project_id=project_id,
        role=FoundationRole.CREATIVE_FOUNDATION,
        label="alternate",
        alternate=True,
        parent_candidates=selected,
    )
    _activate_story_design(
        database_url=database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        candidate=alternate,
        principal=principal,
        full_lifecycle=full_story_design_lifecycle,
        activate=False,
        release_sha=release_sha,
    )
    alternates[FoundationRole.CREATIVE_FOUNDATION] = (
        selected[FoundationRole.CREATIVE_FOUNDATION]["asset_version_id"],
        alternate["asset_version_id"],
    )
    layers = tuple(
        FormationLayerInput(
            role=role,
            asset_version_id=item["asset_version_id"],
            content_hash=item["content_hash"],
            schema_version=item["schema_version"],
            generation_operation_id=item["generation_operation_id"],
            qualification_evidence_asset_version_id=(
                item["qualification_evidence_asset_version_id"]
            ),
            qualification_hash=item["qualification_hash"],
            activation_operation_id=item["activation_operation_id"],
            candidate_asset_version_ids=alternates[role],
            selection_reason=("best causal coherence under frozen comparison",),
        )
        for role, item in selected.items()
    )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT version FROM authority_book WHERE project_id=%s AND book_id=%s",
            [project_id, book_id],
        )
        expected_book_version = int(uow.cursor.fetchone()[0])
    formation = StoryFormationApplication(
        database_url,
        application_build_id="hierarchy-closure-qualification",
        commit_sha=release_sha,
    )
    start_command = StartStoryFormationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        expected_book_version=expected_book_version,
        stable_idempotency_key=f"formation:{project_id}:{book_id}",
        trace_id=f"trace:{project_id}:formation",
        correlation_id=f"correlation:{project_id}:formation",
        frozen_input=StoryFormationInput(layers=layers),
    )
    admitted = formation.admit(start_command, principal=principal)
    runtime_jobs = RuntimeJobAuthority(database_url)
    recovery_attempted = False
    if exercise_formation_recovery:
        claim = runtime_jobs.claim(
            runtime_group="story_formation",
            worker_id="hierarchy-closure-crashing-worker",
            lease_seconds=30,
            job_kinds=("STORY_FORMATION_ADVANCE",),
            project_id=project_id,
        )
        assert claim is not None

        def fail_after_projection(point: str) -> None:
            if point == "after_business_projection_update":
                raise RuntimeError("injected formation crash after projection")

        crashing = StoryFormationApplication(
            database_url,
            application_build_id="hierarchy-closure-qualification",
            commit_sha=release_sha,
            fault_injector=fail_after_projection,
        )
        try:
            execute_story_formation_claim(
                runtime_jobs, crashing, principal, claim, lease_seconds=30
            )
        except RuntimeError as error:
            assert str(error) == "injected formation crash after projection"
        else:
            raise AssertionError("Formation fault injection did not fail closed")
        failed = crashing.require(admitted.formation_run_id)
        assert failed["lifecycle"] == "FAILED"
        assert failed["current_stage"] == "CREATIVE_SEARCH"
        formation = StoryFormationApplication(
            database_url,
            application_build_id="hierarchy-closure-qualification",
            commit_sha=release_sha,
        )
        resumed = formation.resume(
            admitted.formation_run_id,
            expected_version=int(failed["version"]),
            principal=principal,
        )
        assert resumed["lifecycle"] == "RUNNING"
        retry_claim = runtime_jobs.claim(
            runtime_group="story_formation",
            worker_id="hierarchy-closure-recovery-worker",
            lease_seconds=30,
            job_kinds=("STORY_FORMATION_ADVANCE",),
            project_id=project_id,
        )
        assert retry_claim is not None
        assert retry_claim.runtime_job_id != claim.runtime_job_id
        assert retry_claim.attempt_number == 1
        recovered = execute_story_formation_claim(
            runtime_jobs, formation, principal, retry_claim, lease_seconds=30
        )
        assert recovered["current_stage"] == "CREATIVE_FOUNDATION"
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute(
                "SELECT status FROM authority_runtime_job WHERE runtime_job_id=%s",
                [claim.runtime_job_id],
            )
            assert uow.cursor.fetchone() == ("CANCELLED",)
        recovery_attempted = True
        formation.schedule_candidates(limit=1)
    for _ in range(10):
        run = formation.require(admitted.formation_run_id)
        if run["lifecycle"] == "WAITING_APPROVAL":
            break
        claim = runtime_jobs.claim(
            runtime_group="story_formation",
            worker_id="hierarchy-closure-formation-worker",
            lease_seconds=30,
            job_kinds=("STORY_FORMATION_ADVANCE",),
            project_id=project_id,
        )
        if claim is None:
            formation.schedule_candidates(limit=1)
            claim = runtime_jobs.claim(
                runtime_group="story_formation",
                worker_id="hierarchy-closure-formation-worker",
                lease_seconds=30,
                job_kinds=("STORY_FORMATION_ADVANCE",),
                project_id=project_id,
            )
        assert claim is not None
        execute_story_formation_claim(
            runtime_jobs, formation, principal, claim, lease_seconds=30
        )
        formation.schedule_candidates(limit=1)
    waiting = formation.require(admitted.formation_run_id)
    assert waiting["lifecycle"] == "WAITING_APPROVAL"

    from novel_forge.storage.foundation_repositories import (
        require_current_foundation_set,
    )

    with AuthorityUnitOfWork(database_url) as uow:
        foundation = require_current_foundation_set(
            uow.cursor, project_id=project_id, book_id=book_id
        )
    design = BookDesignAuthorityApplication(
        database_url,
        application_build_id="hierarchy-closure-qualification",
        commit_sha=release_sha,
        allow_scripted_evaluation_fixture=True,
    )
    query = BookDesignAuthorityQuery(database_url)
    book = query.require_book(project_id=project_id, book_id=book_id)
    design_principal = Principal(
        principal_id=principal.principal_id,
        principal_type=principal.principal_type,
        permissions=principal.permissions
        | frozenset(
            {"book_design.authority.execute", "book_design.authority.query"}
        ),
        project_scope=principal.project_scope,
        authentication_source=principal.authentication_source,
    )
    evaluator = Principal(
        principal_id=f"hierarchy-evaluator:{project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"narrative_design.evaluate"}),
        project_scope=frozenset({project_id}),
        authentication_source="controlled-integration-fixture",
    )
    proposed = design.execute(
        BookDesignAuthorityCommand(
            definition_name="book_design.propose",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=design_principal.principal_id,
            service_identity="hierarchy-closure-fixture",
            idempotency_key=f"{book_id}:book-design-v5:propose",
            trace_id=f"trace:{project_id}:book-design-v5",
            correlation_id=f"correlation:{project_id}:formation",
            payload=_book_design_payload(
                foundation, target_chapters=target_chapters
            ),
            expected_book_version=int(book["version"]),
            expected_current_design_asset_version_id=str(
                book["active_book_design_version_id"]
            ),
        ),
        principal=design_principal,
    )
    design.evaluate_semantics(
        BookDesignSemanticEvaluationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=evaluator.principal_id,
            candidate_asset_version_id=str(proposed["asset_version_id"]),
            generation_operation_id=str(proposed["operation_id"]),
            generator_operation_name="book_design.propose",
            candidate_content_hash=str(proposed["content_hash"]),
            evaluator_execution_class="SCRIPTED_FIXTURE",
            evaluation=scripted_qualification("book_design.propose"),
            idempotency_key=f"{book_id}:book-design-v5:evaluate",
            trace_id=f"trace:{project_id}:book-design-v5:evaluate",
            correlation_id=f"correlation:{project_id}:formation",
        ),
        principal=evaluator,
    )
    for operation, payload in (
        (
            "book_design.decide",
            {"decision": "APPROVE", "reason": "qualified Foundation synthesis"},
        ),
        ("book_design.activate", {"reason": "activate exact Foundation synthesis"}),
    ):
        design.execute(
            BookDesignAuthorityCommand(
                definition_name=operation,
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=design_principal.principal_id,
                service_identity="hierarchy-closure-fixture",
                idempotency_key=f"{book_id}:book-design-v5:{operation}",
                trace_id=f"trace:{project_id}:book-design-v5",
                correlation_id=f"correlation:{project_id}:formation",
                payload=payload,
                expected_book_version=int(book["version"]),
                expected_current_design_asset_version_id=str(
                    book["active_book_design_version_id"]
                ),
                target_asset_version_id=str(proposed["asset_version_id"]),
            ),
            principal=design_principal,
        )
    ready = formation.approve_book_design(
        admitted.formation_run_id,
        expected_version=int(waiting["version"]),
        asset_version_id=str(proposed["asset_version_id"]),
        content_hash=str(proposed["content_hash"]),
        principal=principal,
    )
    assert ready["lifecycle"] == "READY"
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_runtime_job
            WHERE runtime_group='story_formation'
              AND subject_id=%s
            """,
            [admitted.formation_run_id],
        )
        job_count_before_replay = int(uow.cursor.fetchone()[0])
    replayed_admission = formation.admit(start_command, principal=principal)
    assert replayed_admission.replayed is True
    assert replayed_admission.formation_run_id == admitted.formation_run_id
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_runtime_job
            WHERE runtime_group='story_formation'
              AND subject_id=%s
            """,
            [admitted.formation_run_id],
        )
        assert int(uow.cursor.fetchone()[0]) == job_count_before_replay
    final_book = query.require_book(project_id=project_id, book_id=book_id)
    role_assets = {
        {
            FoundationRole.CREATIVE_FOUNDATION: "creative_foundation",
            FoundationRole.THEME_CONTRACT: "theme_contract",
            FoundationRole.ENDING_INTENT: "ending_intent",
            FoundationRole.READER_PROMISE: "reader_promise",
            FoundationRole.WORLD_BIBLE: "world_bible",
            FoundationRole.CHARACTER_CAST: "character_cast",
        }[role]: item["asset_version_id"]
        for role, item in selected.items()
    }
    return {
        "formation_run_id": admitted.formation_run_id,
        "formation_root_operation_id": admitted.root_operation_id,
        "foundation": foundation,
        "foundation_set_digest": foundation.set_digest,
        "book_design_asset_version_id": str(proposed["asset_version_id"]),
        "book_design_content_hash": str(proposed["content_hash"]),
        "book_version": int(final_book["version"]),
        "formation_replayed": replayed_admission.replayed,
        "formation_recovery_exercised": recovery_attempted,
        "asset_versions": {**role_assets, "book_design": str(proposed["asset_version_id"])},
    }


__all__ = ["seed_ready_story_foundation"]
