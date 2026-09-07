from __future__ import annotations

from collections.abc import Iterator
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb
import pytest

import novel_forge.api.authority_dependencies as authority_dependencies
from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
    build_story_planning_generation_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.authoring import PostgresAuthoringQuery
from novel_forge.modules.book_authority import (
    ResolveBookProductionInputCommand,
    StartBookProductionCommand,
)
from novel_forge.modules.book_production import SupervisorAction
from novel_forge.modules.chapter_authority import ChapterNode
from novel_forge.modules.chapter_authority.execution_artifacts import (
    validate_chapter_execution_intent,
    validate_chapter_memo,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    default_chapter_fixture_response,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority import MkaosAuthorityQuery
from novel_forge.modules.narrative_state.contracts import NarrativeStateKind
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationStatus,
    StoryPlanningGenerationCommand,
    canonical_hash,
)
from novel_forge.modules.story_planning_runtime.execution import (
    planning_fixture_response,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, run_migrations
from novel_forge.workers.book_authority import (
    execute_book_coordination_claim,
    schedule_book_coordination_jobs,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    insert_definition,
    insert_operation,
    transaction,
)
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)
from tests.integration.migration_window_postgres_support import (
    PRE_WORKFLOW_MIGRATION_ID,
    WORKFLOW_MIGRATION_ID,
    assert_database_at_migration,
    disposable_database_at_migration,
)
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA,
    _activate_planning_pack,
    _principal,
    _seed_inputs,
)
import tests.integration.test_postgresql_only_chapter_slice as chapter_slice_fixture
import tests.integration.authority_postgres_support as authority_postgres_support
import tests.integration.capability_pack_postgres_support as capability_pack_support
import tests.integration.test_core_functional_loops_postgres as core_functional_fixture


@pytest.fixture()
def pre_workflow_migration_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    base_database_url = DATABASE_URL
    with disposable_database_at_migration(
        base_database_url,
        prefix="nf_narrative_0103",
        target_migration_id=PRE_WORKFLOW_MIGRATION_ID,
    ) as database_url:
        monkeypatch.setattr(
            authority_postgres_support,
            "DATABASE_URL",
            database_url,
        )
        monkeypatch.setattr(
            capability_pack_support,
            "DATABASE_URL",
            database_url,
        )
        monkeypatch.setattr(
            capability_pack_support,
            "ensure_migrated",
            lambda: assert_database_at_migration(
                database_url,
                target_migration_id=PRE_WORKFLOW_MIGRATION_ID,
            ),
        )
        monkeypatch.setattr(
            core_functional_fixture,
            "DATABASE_URL",
            database_url,
        )
        monkeypatch.setitem(globals(), "DATABASE_URL", database_url)
        yield database_url


def _activate(
    *,
    planning: Any,
    principal: Principal,
    project_id: str,
    workspace_id: str,
    book_id: str,
    generic: Mapping[str, str],
    generator: str,
    logical_key: str,
    generated: Mapping[str, str],
    parent_version_id: str = "",
    related_arc_plan_version_ids: tuple[str, ...] = (),
) -> str:
    inputs = {
        role: (
            generated["book"]
            if role == "book_plan"
            else generated["volume"]
            if role == "volume_plan"
            else generated["arc_truth"]
            if role == "arc_plans"
            else generic[role]
        )
        for role in GENERATOR_INPUT_ROLES[generator]
    }
    command = StoryPlanningGenerationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        generator_operation_name=generator,
        logical_key=logical_key,
        input_versions=inputs,
        parent_version_id=parent_version_id,
        related_arc_plan_version_ids=related_arc_plan_version_ids,
        idempotency_key=f"{project_id}:qualification:{generator}:{logical_key}",
        trace_id=f"trace:{project_id}:{generator}:{logical_key}",
        correlation_id=f"correlation:{project_id}",
    )
    result = planning.generate(command, principal=principal)
    assert result.status is PlanningGenerationStatus.APPROVAL_PENDING
    planning.approve_candidate(
        result.candidate_asset_version_id,
        principal=principal,
        idempotency_key=f"{command.idempotency_key}:approve",
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
    )
    planning.activate_candidate(
        result.candidate_asset_version_id,
        principal=principal,
        idempotency_key=f"{command.idempotency_key}:activate",
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
    )
    return result.candidate_asset_version_id


def _qualification_planning_response(
    stage: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    if stage == "world_candidates.generate":
        return {"disposition": "NO_OP", "reason": "This transport tests existing accepted orchestration without a new world intervention.", "candidates": []}
    if stage == "world_candidates.evaluate":
        return {"evaluations": []}
    payload = planning_fixture_response(stage, inputs)
    command = dict(inputs.get("planning_command") or {})
    logical_key = str(command.get("logical_key") or "")
    if stage == "arc_plan.generate":
        if logical_key == "arc:truth":
            payload["closure_conditions"] = [
                "the truth is acknowledged",
                "the public cost is accepted",
            ]
            payload["target_progress_units"] = 2
            payload["target_window"] = {"from_chapter": 1, "to_chapter": 2}
        elif logical_key == "arc:obligation":
            payload["closure_conditions"] = ["the overdue promise is settled"]
            payload["target_progress_units"] = 1
            payload["target_window"] = {"from_chapter": 1, "to_chapter": 3}
        elif logical_key == "arc:countermove":
            payload["closure_conditions"] = ["the enabled countermove lands"]
            payload["target_progress_units"] = 1
            payload["target_window"] = {"from_chapter": 2, "to_chapter": 3}
    elif stage == "chapter_group_plan.generate":
        versions = dict(command.get("input_versions") or {})
        arc_truth = str(versions["arc_plans"])
        related = tuple(str(item) for item in command["related_arc_plan_version_ids"])
        if not related:
            raise AssertionError("qualification ChapterGroup requires a related Arc")
        cadence = (
            [
                {"arc_plan_version_id": related[1], "action": "ADVANCE"},
                {"arc_plan_version_id": arc_truth, "action": "TOUCH"},
                {"arc_plan_version_id": related[0], "action": "DORMANT"},
            ]
            if len(related) == 2
            else [
                {"arc_plan_version_id": related[0], "action": "ADVANCE"},
                {"arc_plan_version_id": arc_truth, "action": "TOUCH"},
            ]
        )
        for row in payload["chapter_function_matrix"]:
            row["narrative_density"] = "MEDIUM"
            row["arc_cadence"] = cadence
    elif stage == "chapter_plan.generate":
        # The Group row owns the density ceiling.  The Chapter candidate may
        # refine Arc contributions through the governed Working Set, but must
        # preserve the static row's exact structural fields for admission.
        payload["narrative_density"] = "MEDIUM"
    return payload


def _qualification_chapter_response(
    stage: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    payload = default_chapter_fixture_response(stage, inputs)
    if stage == "revision" and int(dict(inputs.get("draft") or {}).get("chapter") or 0) == 2:
        payoff_text = "By refusing the safe escape before the witnesses, the protagonist kept yesterday's public promise."
        scenes = payload.get("scene_artifacts") or []
        if scenes:
            scenes[-1]["text"] += " " + payoff_text
            payload["text"] = "\n\n".join(scene["text"] for scene in scenes)
        else:
            payload["text"] += " " + payoff_text
    if stage != "canon_extraction":
        return payload
    expectations = dict(inputs.get("execution_expectations") or {})
    revision = dict(inputs.get("revision") or {})
    chapter_number = int(revision.get("chapter") or 0)
    truth = next(
        (
            dict(item)
            for item in expectations.get("frozen_arc_plans") or ()
            if isinstance(item, Mapping) and item.get("logical_key") == "arc:truth"
        ),
        None,
    )
    obligation = next(
        (
            dict(item)
            for item in expectations.get("frozen_arc_plans") or ()
            if isinstance(item, Mapping) and item.get("logical_key") == "arc:obligation"
        ),
        None,
    )
    if truth is None or chapter_number not in {1, 2}:
        return payload
    criteria = [
        str(item["criterion_id"]) for item in truth.get("completion_criteria") or ()
    ]
    payload["arc_evidence"] = [
        {
            "arc_plan_version_id": str(truth["arc_plan_version_id"]),
            "observation_status": "OBSERVED",
            "contribution_kind": "PRIMARY",
            "progress_units": 1,
            "effect_dimensions": ["PLOT", "CHARACTER", "RELATIONSHIP"],
            "milestone_ids": [f"truth:chapter:{chapter_number}"],
            "actual_consequences": [
                f"observed costly choice at chapter {chapter_number}"
            ],
            "obligation_ids": [],
            "resolution_evidence": [f"chapter:{chapter_number}:scene:1"],
            "completion_criterion_ids": [criteria[chapter_number - 1]],
            "phase_to": "CRISIS" if chapter_number == 1 else "PAYOFF",
        }
    ]
    if chapter_number == 2 and obligation is not None:
        obligation_criteria = [
            str(item["criterion_id"])
            for item in obligation.get("completion_criteria") or ()
        ]
        payload["arc_evidence"].append(
            {
                "arc_plan_version_id": str(obligation["arc_plan_version_id"]),
                "observation_status": "OBSERVED",
                "contribution_kind": "SECONDARY",
                "progress_units": 1,
                "effect_dimensions": ["PLOT", "READER_EXPERIENCE"],
                "milestone_ids": ["promise:late:paid"],
                "actual_consequences": [
                    "the overdue public promise is settled by the same witnessed choice"
                ],
                "obligation_ids": ["promise:late"],
                "resolution_evidence": ["chapter:2:scene:1"],
                "completion_criterion_ids": obligation_criteria,
                "phase_to": "PAYOFF",
            }
        )
        payload["obligation_changes"] = [
            {
                "obligation_id": "promise:late",
                "obligation_type": "PROMISE",
                "from_status": "OPEN",
                "status": "FULFILLED",
                "priority": "HIGH",
                "target_window": {
                    "status": "SCHEDULED",
                    "from_chapter": 1,
                    "to_chapter": 1,
                },
                "payoff_evidence": {
                    "asset_version_id": "$FINAL_CANDIDATE",
                    "event_id": "$CURRENT_CLAIM",
                },
                "linked_arc_ids": [str(obligation["arc_plan_version_id"])],
                "summary": "The promise is visibly fulfilled by the witnessed choice.",
                "evidence_start": 0,
                "evidence_end": max(1, len(str(revision.get("text") or ""))),
                "confidence": 0.99,
                "impact_type": "narrative_obligation_payoff",
            }
        ]
    for observation in payload["arc_evidence"]:
        observation["evidence_start"] = 0
        observation["evidence_end"] = len(str(revision["text"]))
    from tests.integration.narrative_reality_vertical_support import scripted_claim_evidence
    return scripted_claim_evidence(stage, inputs, payload)


def _replace_production_profile(*, project_id: str, version_id: str) -> str:
    replacement = f"{version_id.rsplit(':', 1)[0]}:v2"
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT asset_id, content FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [version_id],
        )
        asset_id, raw_content = cursor.fetchone()
        content = dict(raw_content)
        content.update(
            {
                "genre_tags": ["institutional mystery"],
                "conflict_tags": ["cost of truth"],
                "reader_effect_tags": ["tension", "earned relief"],
                "theme_tags": ["accountability"],
                "narrative_load_policy": {
                    "policy_id": "qualification-bounded-bandwidth",
                    "policy_version": 1,
                    "limits": {"max_active_arcs": 2},
                },
            }
        )
        cursor.execute(
            """
            UPDATE authority_asset_version SET lifecycle='SUPERSEDED'
            WHERE asset_version_id=%s
            """,
            [version_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,
                eligibility,governance,content,content_hash,schema_version
            ) VALUES (%s,%s,2,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'production_profile.v2')
            """,
            [replacement, asset_id, Jsonb(content), canonical_hash(content)],
        )
    return replacement


def _seed_initial_narrative_pair(
    *, project_id: str, book_id: str, obligation_arc_version_id: str
) -> tuple[str, str]:
    current = {kind.value: [] for kind in NarrativeStateKind}
    current[NarrativeStateKind.NARRATIVE_OBLIGATION.value] = [
        {
            "entity_key": "obligation_id=promise:late",
            "state": {
                "obligation_id": "promise:late",
                "obligation_type": "PROMISE",
                "status": "OPEN",
                "priority": "HIGH",
                "opened_chapter": 0,
                "linked_arc_ids": [obligation_arc_version_id],
                "target_window": {
                    "status": "SCHEDULED",
                    "from_chapter": 1,
                    "to_chapter": 1,
                },
                "stale_after_chapters": 1,
            },
        }
    ]
    campaign_identity = canonical_hash(
        {"qualification_contract": "narrative-orchestration-current"}
    )
    story: dict[str, Any] = {
        "type": "StoryStateSnapshot",
        "contract_version": "story-state-snapshot-v2",
        "layer": "CURRENT_STATE",
        "project_id": project_id,
        "book_id": book_id,
        "scope": {"project_id": project_id, "book_id": book_id},
        "accepted_through_chapter": 0,
        "chapter": 0,
        "chapter_number": 0,
        "state_version": 0,
        "based_on_chapter_outcome_asset_version_id": "",
        "based_on_chapter_outcome_id": "",
        "previous_story_state_asset_version_id": "",
        "current_state": current,
        "reducer_applications": [],
        "accepted_state_only": True,
        "replayable_from": (
            "FROZEN_BOOK_PRODUCTION_INPUT_PLUS_COMMITTED_BOOK_CHAPTER_ACCEPTANCE"
        ),
        "initial_state_boundary": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
        "campaign_contract_identity": campaign_identity,
        "evidence_level": "CONTROLLED_QUALIFICATION_BOOTSTRAP",
        "runtime_result": False,
    }
    story["state_hash"] = canonical_hash(story)
    canon: dict[str, Any] = {
        "type": "CanonSnapshot",
        "contract_version": "canon-snapshot-v2",
        "layer": "TRUTH",
        "authority": {
            "status": "FROZEN_BOOK_PRODUCTION_INPUT",
            "required_boundary": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
        },
        "project_id": project_id,
        "book_id": book_id,
        "scope": {"project_id": project_id, "book_id": book_id},
        "accepted_through_chapter": 0,
        "chapter": 0,
        "chapter_number": 0,
        "current_facts": [],
        "based_on_chapter_outcome_asset_version_id": "",
        "previous_canon_asset_version_id": "",
        "story_state_hash": story["state_hash"],
        "accepted_state_only": True,
        "rebuildable_from": (
            "FROZEN_BOOK_PRODUCTION_INPUT_PLUS_COMMITTED_BOOK_CHAPTER_ACCEPTANCE"
        ),
        "initial_state_boundary": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
        "campaign_contract_identity": campaign_identity,
        "evidence_level": "CONTROLLED_QUALIFICATION_BOOTSTRAP",
        "runtime_result": False,
    }
    canon["canon_hash"] = canonical_hash(canon)
    story_version = f"fixture:{project_id}:initial-story-state:v1"
    canon_version = f"fixture:{project_id}:initial-canon:v1"
    with transaction() as connection, connection.cursor() as cursor:
        for asset_id, version_id, asset_type, schema, content in (
            (
                f"fixture:{project_id}:initial-story-state",
                story_version,
                "story_state_snapshot",
                "story_state_snapshot.v2",
                story,
            ),
            (
                f"fixture:{project_id}:initial-canon",
                canon_version,
                "canon_snapshot",
                "canon_snapshot.v2",
                canon,
            ),
        ):
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [version_id, asset_id, Jsonb(content), canonical_hash(content), schema],
            )
    return story_version, canon_version


def _seed_book_authority_inputs(
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    book_design_version: str,
) -> int:
    book_record_version = f"fixture:{project_id}:book-record:v1"
    with transaction() as connection, connection.cursor() as cursor:
        for asset_type in ("reader_segment_profile", "reader_contract"):
            asset_id = f"fixture:{project_id}:{asset_type}"
            version_id = f"{asset_id}:v1"
            content = {"book_id": book_id, "role": asset_type}
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    canonical_hash(content),
                    f"{asset_type}.v1",
                ],
            )
        book_record_id = f"fixture:{project_id}:book-record"
        book_record = {"book_id": book_id, "record": "authority"}
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'book_record')",
            [book_record_id, project_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,
                eligibility,governance,content,content_hash,schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'book-record.v1')
            """,
            [
                book_record_version,
                book_record_id,
                Jsonb(book_record),
                canonical_hash(book_record),
            ],
        )
        cursor.execute(
            """
            UPDATE authority_book
            SET current_book_asset_version_id=%s,
                current_book_design_asset_version_id=%s,
                production_profile=%s,status='DESIGN_ACTIVE',version=version+1
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
            RETURNING version
            """,
            [
                book_record_version,
                book_design_version,
                Jsonb({"profile_id": "narrative-orchestration-qualification"}),
                project_id,
                workspace_id,
                book_id,
            ],
        )
        return int(cursor.fetchone()[0])


def _seed_prequalified_narrative_card(
    *,
    project_id: str,
    workspace_id: str,
    semantic_family: str = "SCENE_INTERACTION",
    repetition_key: str = "witnessed-choice-multifunction",
    suffix: str = "primary",
) -> str:
    """Freeze an upstream-governed Card as a qualification input snapshot.

    This fixture proves selection/consumption contracts only.  It is not
    evidence that deterministic execution produced a non-fixture Card.
    """

    definition_name = f"qualification.mkaos.prequalified-card.{project_id}.{suffix}"
    operation_id = f"operation:{project_id}:prequalified-card:{suffix}"
    candidate_id = f"fixture:{project_id}:knowledge-candidate:{suffix}:v1"
    decision_id = f"fixture:{project_id}:governance-decision:{suffix}:v1"
    card_id = f"fixture:{project_id}:knowledge-card:{suffix}"
    card_version = f"{card_id}:v1"
    abstract = {
        "concept_name": "One witnessed choice carries several consequences",
        "discipline": "narrative_design",
        "abstract_principle": (
            "A single causal choice can advance conflict, relationship, and reader tension."
        ),
        "constraints": ["Every carried function must change the same causal event."],
        "conflict_generators": ["Truth creates a public cost."],
        "review_checks": ["Reject separate exposition-only scenes."],
        "copyright_boundaries": ["Mechanism only; no source sequence or expression."],
        "knowledge_kind": "NARRATIVE_INTELLIGENCE",
        "semantic_family": semantic_family,
        "mechanism": "Bind disclosure and relationship cost to one witnessed choice.",
        "applicability": ["A chapter must advance multiple active Arcs naturally."],
        "failure_conditions": [
            "The functions can be removed without changing causality."
        ],
        "selection_tags": {
            "genre": ["institutional mystery"],
            "conflict": ["cost of truth"],
            "reader_effect": ["tension"],
            "theme": ["accountability"],
        },
        "repetition_key": repetition_key,
        "originality_boundary": {
            "source_specific_sequence_reusable": False,
            "named_entity_substitution_allowed": False,
            "expression_reuse_allowed": False,
        },
    }
    content = {
        "type": "KnowledgeCard",
        "abstract_content": abstract,
        "lineage": {
            "candidate_asset_version_id": candidate_id,
            "governance_decision_asset_version_id": decision_id,
            "qualification_fixture_boundary": "UPSTREAM_SNAPSHOT_ONLY",
        },
        "source_policy": {
            "knowledge_card_context_eligible": True,
            "raw_source_expression_included": False,
            "source_chunks_direct_context_eligible": False,
            "fixture_protocol_only": False,
        },
    }
    digest = canonical_hash(content)
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=project_id,
            status="SUCCEEDED",
        )
        for asset_id, version_id, asset_type, value in (
            (
                candidate_id.rsplit(":", 1)[0],
                candidate_id,
                "knowledge_card_candidate",
                {"qualification_fixture_boundary": "UPSTREAM_SNAPSHOT_ONLY"},
            ),
            (
                decision_id.rsplit(":", 1)[0],
                decision_id,
                "mkaos_governance_decision",
                {"decision": "APPROVE", "qualification_fixture_boundary": True},
            ),
            (card_id, card_version, "knowledge_card", content),
        ):
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(value),
                    canonical_hash(value),
                    f"{asset_type}.v1",
                ],
            )
        cursor.execute(
            """
            INSERT INTO authority_mkaos_knowledge_card(
                knowledge_card_id,project_id,workspace_id,asset_version_id,
                candidate_asset_version_id,governance_decision_asset_version_id,
                created_by_operation_id,content_hash,status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE')
            """,
            [
                card_id,
                project_id,
                workspace_id,
                card_version,
                candidate_id,
                decision_id,
                operation_id,
                digest,
            ],
        )
    return card_version


@pytest.mark.parametrize("revoke_before_retry", [False, True])
def test_planning_retry_freezes_narrative_intelligence_and_honors_revocation(
    revoke_before_retry: bool,
) -> None:
    harness = CapabilityPackPostgresHarness(
        f"narrative-intelligence-retry-{int(revoke_before_retry)}"
    )
    _activate_planning_pack(harness)
    project_id = harness.project_id
    book_id = harness.book_ids[0]
    generic = _seed_inputs(project_id, book_id)
    principal = _principal(project_id)
    first_card = _seed_prequalified_narrative_card(
        project_id=project_id,
        workspace_id=harness.workspace_id,
        semantic_family="NARRATIVE_MECHANISM",
        repetition_key="retry-frozen-mechanism-v1",
        suffix="retry-first",
    )
    injected = {"done": False}

    def fail_once(checkpoint: str) -> None:
        if (
            checkpoint == "after_measured_usage_before_candidate_acceptance"
            and not injected["done"]
        ):
            injected["done"] = True
            raise KernelError(
                "NARRATIVE_INTELLIGENCE_RETRY_PROBE",
                "controlled failure after the frozen Planning Context was consumed",
            )

    with tempfile.TemporaryDirectory(prefix="narrative-intelligence-retry-") as root:
        settings = IndustrialSettings(
            root=Path(__file__).resolve().parents[2],
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "narrative-intelligence-retry",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        execution = build_production_execution_composition(settings, env=env, planning_fixture_factory=_qualification_planning_response)
        planning = build_story_planning_generation_application(
            settings,
            execution=execution,
            env=env,
            post_provider_fault_injector=fail_once,
        )
        command = StoryPlanningGenerationCommand(
            project_id=project_id,
            workspace_id=harness.workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name="book_plan.generate",
            logical_key=f"{book_id}:narrative-intelligence-retry",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            idempotency_key=f"{project_id}:narrative-intelligence-retry",
            trace_id=f"trace:{project_id}:narrative-intelligence-retry",
            correlation_id=f"correlation:{project_id}",
        )
        with pytest.raises(KernelError, match="NARRATIVE_INTELLIGENCE_RETRY_PROBE"):
            planning.generate(command, principal=principal)

        query = MkaosAuthorityQuery(DATABASE_URL)
        first_card_record = next(
            card
            for card in query.list_cards(project_id=project_id, limit=10)
            if card["asset_version_id"] == first_card
        )
        first_card_content_hash = str(first_card_record["content_hash"])
        frozen_usage = query.list_planning_usage(project_id=project_id, book_id=book_id)
        assert len(frozen_usage) == 1
        assert frozen_usage[0]["knowledge_card_asset_version_id"] == first_card
        assert frozen_usage[0]["consumption_status"] == "CONTEXT_FROZEN"

        second_card = _seed_prequalified_narrative_card(
            project_id=project_id,
            workspace_id=harness.workspace_id,
            semantic_family="NARRATIVE_MECHANISM",
            repetition_key="retry-new-mechanism-v2",
            suffix="retry-second",
        )
        if revoke_before_retry:
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_mkaos_knowledge_card SET status='REVOKED'
                    WHERE project_id=%s AND asset_version_id=%s
                    """,
                    [project_id, first_card],
                )
            with pytest.raises(
                KernelError, match="PLANNING_NARRATIVE_INTELLIGENCE_DRIFT"
            ):
                planning.generate(command, principal=principal)
            with pytest.raises(
                KernelError, match="PLANNING_NARRATIVE_INTELLIGENCE_DRIFT"
            ):
                query.require_planning_card_current(
                    project_id=project_id,
                    asset_version_id=first_card,
                    content_hash=first_card_content_hash,
                )
        else:
            result = planning.generate(command, principal=principal)
            assert result.status is PlanningGenerationStatus.APPROVAL_PENDING
            materialized_usage = query.list_planning_usage(
                project_id=project_id, book_id=book_id
            )
            assert len(materialized_usage) == 1
            assert materialized_usage[0]["knowledge_card_asset_version_id"] == (
                first_card
            )
            assert materialized_usage[0]["knowledge_card_asset_version_id"] != (
                second_card
            )
            assert materialized_usage[0]["consumption_status"] == (
                "FIXTURE_PROTOCOL_USED"
            )
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT COUNT(*), COUNT(DISTINCT version.content_hash)
                    FROM authority_operation_output_asset AS output
                    JOIN authority_asset_version AS version
                      ON version.asset_version_id=output.asset_version_id
                    WHERE output.operation_id=%s
                      AND output.output_key='planning.context_bundle'
                    """,
                    [result.generation_operation_id],
                )
                assert uow.cursor.fetchone() == (1, 1)
        execution.close()


def test_accepted_reality_closes_three_chapter_orchestration_loop(
    monkeypatch: pytest.MonkeyPatch,
    pre_workflow_migration_database: str,
) -> None:
    monkeypatch.setattr(
        authority_dependencies,
        "planning_fixture_response",
        _qualification_planning_response,
    )
    monkeypatch.setattr(
        authority_dependencies,
        "default_chapter_fixture_response",
        _qualification_chapter_response,
    )
    harness = CapabilityPackPostgresHarness("narrative-orchestration-qualification")
    _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    from tests.integration.narrative_reality_vertical_support import compiled_world_fixture
    approved_world = compiled_world_fixture()
    for rule in approved_world["rules"]:
        rule.update(enforcement="SOFT_CAUSAL", predicate=None)
    generic = _seed_inputs(project_id, book_id, target_chapter_count=3, world_foundation=approved_world)
    generic["production_profile"] = _replace_production_profile(
        project_id=project_id,
        version_id=generic["production_profile"],
    )
    chapter_slice_fixture.PostgreSQLOnlyChapterSliceTests.release_evidence(project_id)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE authority_asset_version SET lifecycle='SUPERSEDED'
            WHERE asset_version_id=%s
            """,
            [f"{project_id}:platform-profile-v1"],
        )
        approval_id = f"fixture:{project_id}:approval-decision"
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'approval_decision')",
            [approval_id, project_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,
                eligibility,governance,content,content_hash,schema_version
            )
            SELECT %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',content,content_hash,
                   'integration_fixture.v1'
            FROM authority_asset_version WHERE asset_version_id=%s
            """,
            [f"{approval_id}:v1", approval_id, f"{project_id}:approval-v1"],
        )
    principal = _principal(project_id)
    worker_principal = Principal(
        principal_id=f"narrative-qualification-worker:{project_id}",
        principal_type=PrincipalType.WORKER,
        permissions=principal.permissions,
        project_scope=principal.project_scope,
        authentication_source="narrative-orchestration-qualification",
    )
    with tempfile.TemporaryDirectory(prefix="narrative-orchestration-") as root:
        settings = IndustrialSettings(
            root=Path(__file__).resolve().parents[2],
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "narrative-qualification-fixture",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_AUTHORITY_WORKER_ID": "narrative-qualification-worker",
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        execution = build_production_execution_composition(settings, env=env, planning_fixture_factory=_qualification_planning_response)
        chapter = build_chapter_authority_application(
            settings, execution=execution, env=env
        )
        composition = build_book_production_composition(
            settings,
            principal=principal,
            execution=execution,
            env=env,
            chapter_application=chapter,
        )
        planning = composition.planning
        activated: dict[str, str] = {}
        activated["book"] = _activate(
            planning=planning,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            generic=generic,
            generator="book_plan.generate",
            logical_key="book:main",
            generated=activated,
        )
        activated["volume"] = _activate(
            planning=planning,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            generic=generic,
            generator="volume_plan.generate",
            logical_key="volume:1",
            generated=activated,
            parent_version_id=activated["book"],
        )
        activated["arc_truth"] = _activate(
            planning=planning,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            generic=generic,
            generator="arc_plan.generate",
            logical_key="arc:truth",
            generated=activated,
        )
        activated["arc_obligation"] = _activate(
            planning=planning,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            generic=generic,
            generator="arc_plan.generate",
            logical_key="arc:obligation",
            generated=activated,
        )
        activated["arc_countermove"] = _activate(
            planning=planning,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            generic=generic,
            generator="arc_plan.generate",
            logical_key="arc:countermove",
            generated=activated,
            related_arc_plan_version_ids=(activated["arc_truth"],),
        )
        activated["group"] = _activate(
            planning=planning,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            generic=generic,
            generator="chapter_group_plan.generate",
            logical_key="chapter-group:1-3",
            generated=activated,
            parent_version_id=activated["volume"],
            related_arc_plan_version_ids=(
                activated["arc_obligation"],
                activated["arc_countermove"],
            ),
        )
        narrative_card_version = _seed_prequalified_narrative_card(
            project_id=project_id, workspace_id=workspace_id
        )
        initial_story, initial_canon = _seed_initial_narrative_pair(
            project_id=project_id,
            book_id=book_id,
            obligation_arc_version_id=activated["arc_obligation"],
        )
        expected_book_version = _seed_book_authority_inputs(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            book_design_version=generic["book_design"],
        )
        snapshot = composition.input_resolver.resolve(
            ResolveBookProductionInputCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                production_profile=generic["production_profile"],
                expected_book_version=expected_book_version,
                actor_id=principal.principal_id,
                idempotency_key=f"{project_id}:resolve-qualification-input",
                trace_id=f"trace:{project_id}:resolve-qualification-input",
                correlation_id=f"correlation:{project_id}",
                role_asset_version_overrides=(
                    ("platform_profile_version", generic["platform_profile"]),
                    ("initial_story_state_version", initial_story),
                    ("initial_canon_snapshot_version", initial_canon),
                ),
            ),
            principal=principal,
        )
        assert set(snapshot.arc_portfolio_plan_versions) == {
            activated["arc_truth"],
            activated["arc_obligation"],
            activated["arc_countermove"],
        }
        assert_database_at_migration(
            pre_workflow_migration_database,
            target_migration_id=PRE_WORKFLOW_MIGRATION_ID,
        )
        migration_status = run_migrations(pre_workflow_migration_database)
        assert migration_status["ok"] is True
        assert migration_status["current"] == LATEST_MIGRATION_ID
        assert WORKFLOW_MIGRATION_ID in {
            item["migration_id"] for item in migration_status["applied"]
        }
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT project_id,workspace_id,book_id,snapshot_hash,
                       source_migration_id
                FROM authority_book_opening_legacy_snapshot_entitlement
                WHERE snapshot_id=%s
                """,
                [snapshot.snapshot_id],
            )
            assert uow.cursor.fetchone() == (
                project_id,
                workspace_id,
                book_id,
                snapshot.snapshot_hash,
                WORKFLOW_MIGRATION_ID,
            )
        admission = composition.authority.start(
            StartBookProductionCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                trace_id=f"trace:{project_id}:book-start",
                correlation_id=f"correlation:{project_id}",
                stable_idempotency_key=f"{project_id}:book-start",
                book_design_version=snapshot.book_design_version,
                book_plan_version=snapshot.book_plan_version,
                production_profile_version=snapshot.production_profile_version,
                longform_context_versions={
                    "volume_plan_version": snapshot.current_volume_plan_version,
                    "arc_plan_versions": list(
                        snapshot.current_relevant_arc_plan_versions
                    ),
                    "character_state_version": snapshot.character_state_version,
                    "foreshadowing_state_version": (
                        snapshot.foreshadowing_state_version
                    ),
                    "quality_trend_version": snapshot.quality_trend_version,
                    "reward_ledger_version": snapshot.reward_ledger_version,
                    "promise_ledger_version": snapshot.promise_ledger_version,
                    "reader_segment_version": snapshot.reader_segment_version,
                    "reader_contract_version": snapshot.reader_contract_version,
                    "platform_profile_version": snapshot.platform_profile_version,
                },
                target_chapter_count=3,
                input_mode="RESOLVED_AUTHORITY_INPUT",
                input_snapshot_id=snapshot.snapshot_id,
            ),
            principal=principal,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
                [activated["group"]],
            )
            group = dict(uow.cursor.fetchone()[0])
        schedule_rows = {
            int(row["chapter_number"]): dict(row)
            for row in group["chapter_function_matrix"]
        }
        working_sets = {
            1: composition.query.require_arc_working_set(
                book_run_id=admission.book_run_id,
                snapshot_id=snapshot.snapshot_id,
                chapter_number=1,
                schedule_row=schedule_rows[1],
            )
        }
        selected_one = {
            item["arc_plan_version_id"]
            for item in working_sets[1]["selected_contributions"]
        }
        assert working_sets[1]["accepted_reality"]["accepted_through_chapter"] == 0
        assert working_sets[1]["capacity"]["maximum_active_arcs"] == 2
        assert selected_one == {
            activated["arc_truth"],
            activated["arc_obligation"],
        }
        assert working_sets[1]["schedule_correction"] == {
            "status": "CORRECTED_FROM_GROUP_CADENCE",
            "added_arc_plan_version_ids": [activated["arc_obligation"]],
            "removed_arc_plan_version_ids": [activated["arc_countermove"]],
        }

        runtime_jobs = RuntimeJobAuthority(DATABASE_URL)

        def worker_tick() -> dict[str, Any]:
            schedule_book_coordination_jobs(
                composition.query,
                runtime_jobs,
                limit=1,
                book_run_id=admission.book_run_id,
            )
            claim = runtime_jobs.claim(
                runtime_group="book",
                worker_id="narrative-qualification-book-worker",
                lease_seconds=30,
                job_kinds=("BOOK_COORDINATION_TICK",),
                subject_kind="BOOK_RUN",
                subject_id=admission.book_run_id,
            )
            assert claim is not None
            return execute_book_coordination_claim(runtime_jobs, composition, claim)

        def run_chapter(root_operation_id: str) -> None:
            scheduler = chapter.scheduler(principal=worker_principal)
            for _ in range(len(ChapterNode) * 2 + 4):
                tick = scheduler.tick(
                    project_id=project_id,
                    root_operation_id=root_operation_id,
                )
                if tick.saga_status == "SUCCEEDED":
                    return
            raise AssertionError("Chapter Authority did not complete")

        def advance_through(target_chapter: int) -> list[str]:
            actions: list[str] = []
            for _ in range(96):
                tick = worker_tick()
                action = str(tick["action"])
                actions.append(action)
                if action == SupervisorAction.DISPATCH_CHAPTER.value:
                    run_chapter(str(tick["operation_id"]))
                if (
                    int(
                        composition.authority.require(admission.book_run_id)[
                            "accepted_through_chapter"
                        ]
                    )
                    >= target_chapter
                ):
                    return actions
            raise AssertionError(f"Book did not accept Chapter {target_chapter}")

        chapter_one_actions = advance_through(1)
        assert SupervisorAction.DISPATCH_CHAPTER.value in chapter_one_actions
        assert SupervisorAction.ACCEPT_CHAPTER.value in chapter_one_actions
        working_sets[2] = composition.query.require_arc_working_set(
            book_run_id=admission.book_run_id,
            snapshot_id=snapshot.snapshot_id,
            chapter_number=2,
            schedule_row=schedule_rows[2],
        )
        by_two = {
            item["arc_plan_version_id"]: item for item in working_sets[2]["candidates"]
        }
        assert by_two[activated["arc_truth"]]["current_phase"] == "CRISIS"
        assert by_two[activated["arc_truth"]]["cumulative_progress_units"] == 1
        assert by_two[activated["arc_countermove"]]["eligible"] is False
        assert by_two[activated["arc_countermove"]]["dependency_blockers"] == [
            activated["arc_truth"]
        ]
        assert by_two[activated["arc_obligation"]]["obligation_debt"][
            "overdue_ids"
        ] == ["promise:late"]
        assert {
            item["arc_plan_version_id"]
            for item in working_sets[2]["selected_contributions"]
        } == {activated["arc_truth"], activated["arc_obligation"]}
        assert (
            composition.query.require_arc_working_set(
                book_run_id=admission.book_run_id,
                snapshot_id=snapshot.snapshot_id,
                chapter_number=2,
                schedule_row=schedule_rows[2],
            )
            == working_sets[2]
        )

        advance_through(2)
        working_sets[3] = composition.query.require_arc_working_set(
            book_run_id=admission.book_run_id,
            snapshot_id=snapshot.snapshot_id,
            chapter_number=3,
            schedule_row=schedule_rows[3],
        )
        by_three = {
            item["arc_plan_version_id"]: item for item in working_sets[3]["candidates"]
        }
        assert by_three[activated["arc_truth"]]["lifecycle_status"] == "COMPLETED"
        assert by_three[activated["arc_truth"]]["eligible"] is False
        assert by_three[activated["arc_obligation"]]["lifecycle_status"] == (
            "COMPLETED"
        )
        assert by_three[activated["arc_obligation"]]["eligible"] is False
        assert by_three[activated["arc_countermove"]]["dependency_blockers"] == []
        assert {
            item["arc_plan_version_id"]
            for item in working_sets[3]["selected_contributions"]
        } == {activated["arc_countermove"]}

        chapter_three_preparation_actions: list[str] = []
        for _ in range(24):
            preparation_tick = worker_tick()
            preparation_action = str(preparation_tick["action"])
            chapter_three_preparation_actions.append(preparation_action)
            if preparation_action == SupervisorAction.FREEZE_CHAPTER_PLAN.value:
                break
        assert SupervisorAction.FREEZE_CHAPTER_PLAN.value in (
            chapter_three_preparation_actions
        )
        pre_dispatch_book = composition.authority.require(admission.book_run_id)
        chapter_three_active_plan = composition.query.active_plan_covering_chapter(
            project_id=project_id,
            book_id=book_id,
            contract_type="CHAPTER",
            chapter_number=3,
        )
        assert chapter_three_active_plan is not None
        chapter_three_plan_version = str(chapter_three_active_plan["asset_version_id"])
        chapter_three_active_group = composition.query.active_plan_covering_chapter(
            project_id=project_id,
            book_id=book_id,
            contract_type="CHAPTER_GROUP",
            chapter_number=3,
        )
        assert chapter_three_active_group is not None
        chapter_three_group_version = str(
            chapter_three_active_group["asset_version_id"]
        )
        assert chapter_three_group_version != activated["group"]
        valid_three_admission = composition.query.require_chapter_production_admission(
            book_run_id=admission.book_run_id,
            snapshot_id=snapshot.snapshot_id,
            chapter_group_plan_version_id=chapter_three_group_version,
            chapter_plan_version_id=chapter_three_plan_version,
            chapter_number=3,
            accepted_through_chapter=2,
            active_story_state_version_id=str(
                pre_dispatch_book["active_story_state_version_id"]
            ),
            active_canon_snapshot_version_id=str(
                pre_dispatch_book["active_canon_snapshot_version_id"]
            ),
        )
        chapter_three_frozen_working_set = dict(
            chapter_three_active_plan["content"]["constraint_envelope"][
                "arc_working_set"
            ]
        )
        assert (
            valid_three_admission["arc_working_set_digest"]
            == chapter_three_frozen_working_set["working_set_digest"]
        )
        assert {
            item["arc_plan_version_id"]
            for item in chapter_three_frozen_working_set["selected_contributions"]
        } == {
            item["arc_plan_version_id"]
            for item in working_sets[3]["selected_contributions"]
        }
        with pytest.raises(CheckViolation, match="content is immutable"):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT content FROM authority_asset_version
                    WHERE asset_version_id=%s
                    """,
                    [chapter_three_plan_version],
                )
                original_plan_content = dict(cursor.fetchone()[0])
                tampered_plan_content = json.loads(json.dumps(original_plan_content))
                tampered_plan_content["constraint_envelope"]["arc_working_set"][
                    "working_set_digest"
                ] = "sha256:tampered-working-set"
                cursor.execute(
                    """
                    UPDATE authority_asset_version SET content=%s
                    WHERE asset_version_id=%s
                    """,
                    [Jsonb(tampered_plan_content), chapter_three_plan_version],
                )
        advance_through(3)

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT chapter_number, arc_state, obligation_state, status
                FROM authority_book_narrative_projection_set
                WHERE book_run_id=%s ORDER BY chapter_number
                """,
                [admission.book_run_id],
            )
            projections = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT acceptance.chapter_number, request.command_payload,
                       acceptance.chapter_outcome_asset_version_id,
                       request.chapter_root_operation_id
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_chapter_request AS request
                  ON request.chapter_request_id=acceptance.chapter_request_id
                WHERE acceptance.book_run_id=%s ORDER BY acceptance.chapter_number
                """,
                [admission.book_run_id],
            )
            accepted_requests = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT context_version.content, candidate_version.content,
                       binding.binding_id, effect.request_payload,
                       effect.status, receipt.external_receipt_id
                FROM authority_operation_output_asset AS context_output
                JOIN authority_asset_version AS context_version
                  ON context_version.asset_version_id=context_output.asset_version_id
                LEFT JOIN authority_operation_output_asset AS candidate_output
                  ON candidate_output.operation_id=context_output.operation_id
                 AND candidate_output.output_key='story_planning.candidate'
                LEFT JOIN authority_asset_version AS candidate_version
                  ON candidate_version.asset_version_id=candidate_output.asset_version_id
                LEFT JOIN story_plan_binding AS binding
                  ON binding.asset_version_id=candidate_output.asset_version_id
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=context_output.operation_id
                 AND effect.effect_type='model.invoke'
                LEFT JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                LEFT JOIN authority_external_receipt AS receipt
                  ON receipt.dispatch_id=dispatch.dispatch_id
                WHERE context_output.output_key='planning.context_bundle'
                  AND context_version.content->>'book_id'=%s
                  AND context_version.content->'narrative_intelligence'->'selected' @>
                      %s::jsonb
                """,
                [
                    book_id,
                    Jsonb(
                        [{"knowledge_card_asset_version_id": (narrative_card_version)}]
                    ),
                ],
            )
            intelligence_usage = uow.cursor.fetchall()
            chapter_roots = [str(row[3]) for row in accepted_requests]
            uow.cursor.execute(
                """
                SELECT operation.root_operation_id, output.output_key,
                       version.asset_version_id, version.content_hash,
                       version.content
                FROM authority_operation_output_asset AS output
                JOIN authority_operation AS operation
                  ON operation.operation_id=output.operation_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                WHERE operation.root_operation_id=ANY(%s)
                  AND output.role='primary'
                  AND output.output_key IN (
                      'chapter.plan', 'chapter.execution_intent',
                      'chapter.memo', 'chapter.retrieval', 'chapter.context',
                      'chapter.best_candidate', 'chapter.canon'
                  )
                ORDER BY operation.created_at, output.created_at
                """,
                [chapter_roots],
            )
            artifact_rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM story_plan_binding
                WHERE asset_version_id=ANY(%s)
                """,
                [
                    [
                        str(row[2])
                        for row in artifact_rows
                        if str(row[1])
                        in {
                            "chapter.execution_intent",
                            "chapter.memo",
                        }
                    ]
                ],
            )
            execution_artifact_plan_binding_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT context_bundle_asset_version_id, selected_asset_version_id,
                       consumer_definition_name, consumer_status
                FROM authority_context_runtime_usage_projection
                WHERE project_id=%s AND book_id=%s
                """,
                [project_id, book_id],
            )
            context_runtime_usage = uow.cursor.fetchall()
        assert [int(row[0]) for row in projections] == [1, 2, 3]
        assert all(str(row[3]) == "COMPLETE" for row in projections)
        chapter_two_truth = next(
            item
            for item in projections[1][1]
            if item["arc_plan_version_id"] == activated["arc_truth"]
        )
        assert chapter_two_truth["cumulative_progress_units"] == 2
        assert chapter_two_truth["lifecycle_status"] == "COMPLETED"
        assert len(chapter_two_truth["satisfied_completion_criterion_ids"]) == 2
        chapter_one_obligation = next(
            item
            for item in projections[0][2]
            if item["state"]["obligation_id"] == "promise:late"
        )
        assert chapter_one_obligation["state"]["accepted_evaluation"]["due"] is True
        assert len(accepted_requests) == 3
        accepted_by_root = {
            str(root_operation_id): (int(chapter_number), dict(command_payload))
            for (
                chapter_number,
                command_payload,
                _outcome_version,
                root_operation_id,
            ) in accepted_requests
        }
        artifacts_by_chapter: dict[int, dict[str, tuple[str, str, dict[str, Any]]]] = {}
        for (
            root_operation_id,
            output_key,
            version_id,
            content_hash,
            content,
        ) in artifact_rows:
            chapter_number, _command_payload = accepted_by_root[str(root_operation_id)]
            artifacts_by_chapter.setdefault(chapter_number, {})[str(output_key)] = (
                str(version_id),
                str(content_hash),
                dict(content),
            )
        assert set(artifacts_by_chapter) == {1, 2, 3}
        chapter_two_payoff = next(
            item["state"]["payoff_evidence"] for item in projections[1][2]
            if item["state"]["obligation_id"] == "promise:late"
        )
        assert chapter_two_payoff["asset_version_id"] == artifacts_by_chapter[2]["chapter.best_candidate"][0]
        assert chapter_two_payoff["event_id"] == (
            f"{artifacts_by_chapter[2]['chapter.canon'][0]}#{NarrativeStateKind.NARRATIVE_OBLIGATION.value}:0"
        )
        assert chapter_two_payoff["evidence_mode"] == "ACCEPTED_DRAFT_CANON_LINEAGE"
        assert chapter_two_payoff["grounded_claim_id"].startswith("sha256:")
        assert execution_artifact_plan_binding_count == 0
        for (
            chapter_number,
            command_payload,
            _outcome_version,
            _root_operation_id,
        ) in accepted_requests:
            preparation = dict(command_payload["preparation_report"])
            chapter_admission = dict(preparation["chapter_production_admission"])
            assert chapter_admission["admission"] == "CHAPTER_PRODUCTION_ADMITTED"
            plan_version, plan_hash, plan = artifacts_by_chapter[int(chapter_number)][
                "chapter.plan"
            ]
            frozen_working_set = dict(plan["constraint_envelope"]["arc_working_set"])
            expected = frozen_working_set["working_set_digest"]
            assert chapter_admission["arc_working_set_digest"] == expected
            assert {
                str(item["arc_plan_version_id"])
                for item in frozen_working_set["selected_contributions"]
            } == {
                str(item["arc_plan_version_id"])
                for item in working_sets[int(chapter_number)]["selected_contributions"]
            }
            intent_version, _intent_hash, intent = artifacts_by_chapter[
                int(chapter_number)
            ]["chapter.execution_intent"]
            _memo_version, _memo_hash, memo = artifacts_by_chapter[int(chapter_number)][
                "chapter.memo"
            ]
            _retrieval_version, _retrieval_hash, retrieval = artifacts_by_chapter[
                int(chapter_number)
            ]["chapter.retrieval"]
            _context_version, _context_hash, context = artifacts_by_chapter[
                int(chapter_number)
            ]["chapter.context"]
            validate_chapter_execution_intent(
                intent,
                expected_plan_asset_version_id=plan_version,
                expected_plan_content_hash=plan_hash,
            )
            validate_chapter_memo(
                memo,
                intent=intent,
                intent_asset_version_id=intent_version,
            )
            refs = dict(command_payload["context_version_refs"])
            boundary = dict(intent["accepted_boundary"])
            assert boundary["accepted_through_chapter"] == int(chapter_number) - 1
            assert (
                boundary["story_state_asset_version_id"]
                == refs["story_state_snapshot_version"]
            )
            assert (
                boundary["canon_snapshot_asset_version_id"]
                == refs["canon_snapshot_version"]
            )
            mission = dict(intent["chapter_mission"])
            assert plan["chapter_contract_schema_version"] == "chapter-mission-scene.v2"
            assert intent["contract_version"] == "chapter-execution-intent-v3"
            assert "required_beats" not in mission
            assert intent["required_beats"]
            assert set(mission["trajectory_refs"]) == {
                str(ref) for scene in intent["scene_plans"] for ref in scene["trajectory_refs"]
            }
            assert set(mission["obligation_refs"]) == {
                str(ref) for scene in intent["scene_plans"] for ref in scene["obligation_refs"]
            }
            assert {str(event["event_id"]) for event in mission["narrative_realization"]["events"]} == {
                str(ref) for scene in intent["scene_plans"] for ref in scene["realization_event_ids"]
            }
            assert {
                "why_this_chapter_exists",
                "entry_state",
                "required_outcomes",
                "trajectory_refs",
                "obligation_refs",
                "arc_contributions",
                "forbidden_changes",
                "knowledge_and_disclosure_boundaries",
                "reader_effect",
                "hook_intent",
                "unresolved_obligation_intent",
                "expected_exit_state",
                "narrative_composition",
                "arc_working_set",
                "mission_fingerprint",
            }.issubset(mission)
            expected_arc_ids = {
                str(item["arc_plan_version_id"])
                for item in frozen_working_set["selected_contributions"]
            }
            assert {
                str(item["arc_plan_version_id"])
                for item in mission["arc_contributions"]
            } == expected_arc_ids
            composition_contract = dict(mission["narrative_composition"])
            assert composition_contract["composition_rule"] == (
                "CAUSAL_MULTI_FUNCTION_EVENTS"
            )
            if len(expected_arc_ids) > 1:
                assert int(composition_contract["multi_arc_event_count"]) >= 1
                assert any(
                    set(event["arc_contributions"]) == expected_arc_ids
                    and len(set(event["narrative_functions"])) >= 3
                    for event in composition_contract["events"]
                )
            context_expectations = dict(context["chapter_execution_expectations"])
            assert (
                context_expectations["mission_fingerprint"]
                == mission["mission_fingerprint"]
            )
            assert context_expectations["entry_state"] == mission["entry_state"]
            assert context_expectations["required_beats"] == intent["required_beats"]
            assert (
                context_expectations["required_arc_contributions"]
                == mission["arc_contributions"]
            )
            assert (
                context_expectations["narrative_composition"]
                == mission["narrative_composition"]
            )
            assert (
                context["chapter_execution"]["source_chapter_plan_asset_version_id"]
                == plan_version
            )
            assert (
                context["chapter_execution"]["intent_fingerprint"]
                == intent["intent_fingerprint"]
            )
            assert (
                context["chapter_execution"]["memo_fingerprint"]
                == memo["memo_fingerprint"]
            )
            assert retrieval["contract_version"] == "chapter-retrieval-result-v5"
            assert retrieval["ranking"]["lexical_signal"] == (
                "PostgreSQL Full-Text Search / ts_rank"
            )
            assert retrieval["ranking"]["semantic_candidate_expansion"] is False
            assert context["context_contract_version"] == "authority-context-bundle-v8"
            manifest = dict(context["context_manifest"])
            assert manifest["contract_version"] == "narrative-context-manifest-v4"
            assert manifest["effective_policy"]["compiler_version"] == (
                "effective-context-policy-compiler-v1"
            )
            assert manifest["token_accounting_contract"]["precision"] == (
                "ESTIMATE_ONLY"
            )
            assert manifest["token_budget"]["protected"] > 0
            assert (
                manifest["token_budget"]["estimated_used"]
                <= (manifest["token_budget"]["maximum"])
            )
            assert all(
                item["context_class"]
                in {"PROTECTED", "RETRIEVABLE", "COMPRESSIBLE", "EPHEMERAL"}
                for item in manifest["selected_inputs"]
            )
            assert all(item["provenance"] for item in manifest["compressible_context"])
        assert len(intelligence_usage) == 3
        assert sum(bool(row[2]) for row in intelligence_usage) == 1
        for usage in intelligence_usage:
            intelligence_context = dict(usage[0])
            intelligence_candidate = dict(usage[1])
            assert (
                intelligence_context["narrative_intelligence"]["authority_boundary"][
                    "semantic_role"
                ]
                == "POSSIBILITY_ONLY"
            )
            assert (
                intelligence_candidate["execution_evidence"]["fixture_protocol_only"]
                is True
            )
            provider_task_view = dict(usage[3])
            assert (
                provider_task_view["input"]["narrative_intelligence"]["selected"][0][
                    "knowledge_card_asset_version_id"
                ]
                == narrative_card_version
            )
            assert str(usage[4]) == "SUCCEEDED"
            assert usage[5]
        traced_usage = MkaosAuthorityQuery(DATABASE_URL).list_planning_usage(
            project_id=project_id, book_id=book_id
        )
        matching_usage = [
            item
            for item in traced_usage
            if item["knowledge_card_asset_version_id"] == narrative_card_version
        ]
        assert len(matching_usage) == 3
        assert {item["consumption_status"] for item in matching_usage} == {
            "FIXTURE_PROTOCOL_USED"
        }
        bound_usage = [item for item in matching_usage if item["plan_binding_id"]]
        assert len(bound_usage) == 1
        assert bound_usage[0]["plan_execution_scope"] == "FROZEN"
        assert bound_usage[0]["plan_freshness"] == "CURRENT"
        assert context_runtime_usage
        assert all(str(row[3]) == "SUCCEEDED" for row in context_runtime_usage)
        assert any(
            str(row[2]) == "chapter.draft.generate" for row in context_runtime_usage
        )

        # Proof A: committed evidence creates rebuildable writer projections,
        # the lexical-first RetrievalResult consumes the accepted boundary, and
        # the governed v7 Context Manifest is the immutable Provider input.
        authoring = PostgresAuthoringQuery(DATABASE_URL)
        recent_trail = authoring.recent_trail(
            project_id=project_id,
            book_id=book_id,
            through_chapter=3,
        )
        hook_debt = authoring.hook_debt(
            project_id=project_id,
            book_id=book_id,
            through_chapter=3,
        )
        assert [entry["chapter_number"] for entry in recent_trail["entries"]] == [
            1,
            2,
            3,
        ]
        assert recent_trail["authority"] == "NONE_REBUILDABLE_PROJECTION"
        assert hook_debt["authority"] == "NONE_PROJECTION_ONLY"
        assert hook_debt["source_authority"] == ("ACCEPTED_NARRATIVE_OBLIGATION_STATE")
        assert hook_debt["items"][0]["obligation_id"] == "promise:late"
        assert hook_debt["items"][0]["status"] == "FULFILLED"
        chapter_two_retrieval = artifacts_by_chapter[2]["chapter.retrieval"][2]
        selected_projection_kinds = {
            str(dict(item.get("metadata") or {}).get("projection_kind") or "")
            for item in chapter_two_retrieval["selected_documents"]
        }
        assert "accepted_scene_episodic_history" in selected_projection_kinds
        assert "accepted_obligation_state" in selected_projection_kinds

        # Proof B: the Workspace is a read model over the same Chapter run and
        # immutable AssetVersions, including accepted state and future impact.
        chapter_two_root = str(accepted_requests[1][3])
        workspace = authoring.chapter_transaction_workspace(
            project_id=project_id,
            root_operation_id=chapter_two_root,
        )
        assert workspace["authority"] == "NONE_READ_MODEL"
        assert workspace["activation_permissions"] == []
        assert workspace["immutable_asset_references_only"] is True
        assert workspace["artifacts"]["plan"]
        assert workspace["artifacts"]["intent"]
        assert workspace["artifacts"]["memo"]
        assert workspace["artifacts"]["context"]
        assert workspace["artifacts"]["draft_candidates"]
        assert workspace["artifacts"]["reviews"]
        assert workspace["artifacts"]["candidate_comparison"]
        assert workspace["artifacts"]["quality"]
        assert workspace["canon_state_change"]["acceptance"]["status"] == ("COMMITTED")
        assert workspace["hook_debt"]["source_authority"] == (
            "ACCEPTED_NARRATIVE_OBLIGATION_STATE"
        )
        assert workspace["stale_future_impact"]
        execution.close()
