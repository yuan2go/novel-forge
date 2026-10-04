from __future__ import annotations

from novel_forge.modules.story_design_authority.qualification import (
    uses_work_requirements,
)

from decimal import Decimal, InvalidOperation
from typing import Any

from novel_forge.modules.story_design_authority.qualification import (
    required_qualification_profiles,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.application import (
    PostgresHierarchicalPlanningAuthority,
)
from novel_forge.modules.hierarchical_planning.chapter_contracts import (
    require_chapter_contracts,
)
from novel_forge.storage.foundation_repositories import require_current_foundation_set
from novel_forge.storage.narrative_realization_repositories import (
    NarrativeRealizationRepository,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .narrative_qualification import NarrativeReceipt, narrative_digest


_LAYER_MAP = {
    "STORY_INTENT": "INTENT",
    "STORY_FOUNDATION": "FOUNDATION",
    "BOOK_ARCHITECTURE": "BOOK_ARCHITECTURE",
    "CHARACTER_DEVELOPMENT": "BOOK_ARCHITECTURE",
    "DISCLOSURE_OBLIGATION": "BOOK_ARCHITECTURE",
    "NARRATIVE_ARC_GRAPH": "TRAJECTORY_PORTFOLIO",
    "CHAPTER_EXECUTION_PLAN": "CHAPTER_MISSION",
    "CHAPTER_MISSION": "CHAPTER_MISSION",
    "SCENE_ARCHITECTURE": "SCENE_ARCHITECTURE",
}


def _verified_provider_receipt(
    cursor: Any, *, project_id: str, row: tuple[Any, ...]
) -> bool:
    log = dict(row[20] or {})
    evidence = dict(log.get("provider_evidence") or {})
    production = dict(evidence.get("production_execution") or {})
    route = dict(production.get("route_snapshot") or {})
    handle = dict(production.get("execution_handle") or {})
    if (
        not row[18]
        or row[18] != row[19]
        or row[19] != narrative_digest(log)
        or evidence.get("real_model_call") is not True
        or evidence.get("fixture") is True
        or row[21] != narrative_digest(evidence)
        or row[22] != narrative_digest(evidence.get("result"))
        or row[23] != route.get("route_snapshot_id")
        or handle.get("transport")
        not in {"REMOTE_PROVIDER_API", "LOCAL_CLI_REMOTE_INFERENCE"}
        or log.get("operation_id") != row[5]
    ):
        return False
    cursor.execute(
        """
        SELECT effect.request_hash,effect.request_payload,effect.provider,
               dispatch.payload_hash,dispatch.receipt_id,dispatch.provider,
               receipt.receipt_id,receipt.payload_hash,receipt.payload,receipt.provider,
               budget.status,budget.settled_amount,budget.actual_tokens,
               attempt.attempt_id
        FROM authority_external_effect effect
        JOIN authority_external_effect_dispatch dispatch ON dispatch.external_effect_id=effect.external_effect_id AND dispatch.status='SUCCEEDED'
        JOIN authority_external_receipt receipt ON receipt.dispatch_id=dispatch.dispatch_id AND receipt.status='VERIFIED'
        JOIN authority_budget_reservation budget ON budget.external_effect_id=effect.external_effect_id AND budget.operation_id=effect.operation_id
        JOIN authority_attempt attempt ON attempt.operation_id=effect.operation_id AND attempt.status='SUCCEEDED'
        WHERE effect.external_effect_id=%s AND effect.operation_id=%s AND effect.project_id=%s AND effect.status='SUCCEEDED'
        """,
        [str(log.get("external_effect_id") or ""), str(row[5]), project_id],
    )
    durable = cursor.fetchall()
    if len(durable) != 1:
        return False
    values = durable[0]
    request = dict(values[1] or {})
    receipt = dict(values[8] or {})
    try:
        settled = Decimal(str(values[11])) == Decimal(
            str(dict(evidence.get("cost") or {}).get("amount"))
        )
    except (InvalidOperation, ValueError):
        return False
    return bool(
        values[0] == values[3] == narrative_digest(request)
        and values[7] == narrative_digest(receipt)
        and values[4] == values[6]
        and bool(values[6])
        and values[2] == values[5] == values[9] == evidence.get("provider_id")
        and receipt.get("outcome") == "success"
        and receipt.get("evidence") == evidence
        and values[10] == "SETTLED"
        and settled
        and values[12] == dict(evidence.get("usage") or {}).get("total_tokens")
        and values[13] == log.get("attempt_id")
        and dict(request.get("_production_execution") or {}).get("operation_id")
        == row[5]
        and dict(request.get("_production_execution") or {}).get("attempt_id")
        == values[13]
    )


def _native_gate(
    cursor: Any,
    *,
    project_id: str,
    book_id: str,
    layer: str,
    asset_version_id: str,
    content: dict[str, Any],
) -> tuple[str, str]:
    try:
        if layer == "FOUNDATION":
            foundation = require_current_foundation_set(
                cursor, project_id=project_id, book_id=book_id, require_ready=True
            )
            if asset_version_id not in {
                binding.asset_version_id for binding in foundation.by_role.values()
            }:
                return "NOT_PROVEN", "SEMANTIC_ASSET_NOT_IN_READY_FOUNDATION_SET"
        if layer in {"BOOK_ARCHITECTURE", "CHAPTER_MISSION", "SCENE_ARCHITECTURE"}:
            cursor.execute(
                """SELECT 1 FROM story_plan_binding binding
                   JOIN active_story_plan_version active ON active.binding_id=binding.binding_id
                   WHERE binding.project_id=%s AND binding.book_id=%s
                     AND binding.asset_version_id=%s AND binding.freshness='CURRENT'""",
                [project_id, book_id, asset_version_id],
            )
            if cursor.fetchone() is None:
                return "NOT_PROVEN", "CURRENT_TYPED_PLANNING_BINDING_MISSING"
            if layer == "BOOK_ARCHITECTURE":
                PostgresHierarchicalPlanningAuthority._require_qualified_foundation_for_book_plan(
                    cursor,
                    project_id=project_id,
                    book_id=book_id,
                    content=content,
                )
            else:
                require_chapter_contracts(content)
                realization = NarrativeRealizationRepository(
                    cursor
                ).require_current_for_chapter(
                    project_id=project_id,
                    book_id=book_id,
                    chapter_group_plan_version_id=str(
                        content.get("parent_version_id") or ""
                    ),
                    chapter_number=int(content["chapter_number"]),
                )
                if content.get("narrative_realization_slice") != realization:
                    return "NOT_PROVEN", "FROZEN_REALIZATION_IDENTITY_DRIFT"
    except KernelError as error:
        return "NOT_PROVEN", error.code
    return "PASS", ""


def load_native_narrative_receipts(
    database_url: str, *, project_id: str, book_id: str
) -> tuple[NarrativeReceipt, ...]:
    if not database_url or not project_id or not book_id:
        raise ValueError("native narrative evidence requires PostgreSQL and Book scope")
    receipts: list[NarrativeReceipt] = []
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        uow.cursor.execute(
            "SELECT 1 FROM authority_book WHERE project_id=%s AND book_id=%s",
            [project_id, book_id],
        )
        if uow.cursor.fetchone() is None:
            raise ValueError("native narrative evidence Book does not exist in Project")
        uow.cursor.execute(
            """
            SELECT q.qualification_id,q.design_layer,s.generator_operation_name,
                   q.asset_version_id,q.candidate_content_hash,
                   q.evaluation_operation_id,q.evaluator_execution_class,
                   q.qualification_status,q.profile_id,q.profile_hash,
                   generation.definition_snapshot,evaluation.definition_snapshot,
                   s.lifecycle,active.asset_version_id,v.content_hash,
                   generation.status,evaluation.status,q.trust_boundary,
                   q.provider_model_call_content_hash,model.content_hash,
                   model.content,q.provider_evidence_hash,q.provider_result_hash,
                   q.provider_route_snapshot_id,v.eligibility,v.governance,v.content
            FROM authority_narrative_design_qualification q
            JOIN authority_story_design_version_state s
              ON s.asset_version_id=q.asset_version_id AND s.project_id=q.project_id
            JOIN authority_asset_version v ON v.asset_version_id=q.asset_version_id
            JOIN authority_asset a ON a.asset_id=v.asset_id AND a.project_id=q.project_id
            JOIN authority_operation generation ON generation.operation_id=q.generation_operation_id
              AND generation.project_id=q.project_id
            JOIN authority_operation evaluation ON evaluation.operation_id=q.evaluation_operation_id
              AND evaluation.project_id=q.project_id
            LEFT JOIN authority_story_design_active_version active
              ON active.asset_version_id=q.asset_version_id AND active.project_id=q.project_id
            LEFT JOIN authority_asset_version model ON model.asset_version_id=q.provider_model_call_asset_version_id
            WHERE q.project_id=%s AND q.book_id=%s
            ORDER BY q.qualification_id
            """,
            [project_id, book_id],
        )
        design_rows = uow.cursor.fetchall()
        profiles_by_asset: dict[str, set[tuple[str, str]]] = {}
        for row in design_rows:
            profiles_by_asset.setdefault(str(row[3]), set()).add(
                (str(row[8]), str(row[9]))
            )
        for row in design_rows:
            layer = _LAYER_MAP.get(str(row[1]))
            if layer is None:
                continue
            generator = str(row[2])
            if generator == "character.cast.generate":
                layer = "FOUNDATION"
            profiles = required_qualification_profiles(
                generator, work_requirements=uses_work_requirements(row[26])
            )
            expected_profiles = {
                (profile.profile_id, profile.profile_hash) for profile in profiles
            }
            profile_current = (
                str(row[8]),
                str(row[9]),
            ) in expected_profiles and expected_profiles <= profiles_by_asset[
                str(row[3])
            ]
            real_provider = str(
                row[6]
            ) == "MODEL_PROVIDER" and _verified_provider_receipt(
                uow.cursor, project_id=project_id, row=tuple(row)
            )
            source_class = (
                "REAL_PROVIDER_SEMANTIC"
                if real_provider
                else "MODEL_PROVIDER_UNVERIFIED"
                if str(row[6]) == "MODEL_PROVIDER"
                else str(row[6])
            )
            gate_status, gate_reason = _native_gate(
                uow.cursor,
                project_id=project_id,
                book_id=book_id,
                layer=layer,
                asset_version_id=str(row[3]),
                content=dict(row[26]),
            )
            receipts.append(
                NarrativeReceipt(
                    receipt_id=str(row[0]),
                    source_table="authority_narrative_design_qualification",
                    layer=layer,
                    generator=generator,
                    asset_version_id=str(row[3]),
                    content_hash=str(row[4]),
                    operation_id=str(row[5]),
                    implementation_sha=str(dict(row[11]).get("commit_sha") or ""),
                    generation_sha=str(dict(row[10]).get("commit_sha") or ""),
                    source_class=source_class,
                    status=str(row[7]),
                    current=str(row[12]) == "ACTIVE" and row[13] == row[3],
                    native_lineage_valid=(
                        row[4] == row[14]
                        and str(row[15]) in {"SUCCEEDED", "WAITING_GATE"}
                        and str(row[16]) == "SUCCEEDED"
                        and str(row[17]) == "INDEPENDENT"
                        and str(row[24]) == "ELIGIBLE"
                        and str(row[25]) == "CLEAR"
                    ),
                    profile_current=profile_current,
                    gate_status=gate_status,
                    gate_reason=gate_reason,
                )
            )
        uow.cursor.execute(
            """
            SELECT accepted.acceptance_id,accepted.chapter_number,
                   accepted.chapter_outcome_asset_version_id,outcome.content_hash,
                   accepted.acceptance_operation_id,operation.definition_snapshot,
                   accepted.status,operation.status,outcome.content,
                   accepted.story_state_asset_version_id,accepted.canon_snapshot_asset_version_id,
                   story.content_hash,canon.content_hash
            FROM authority_book_chapter_acceptance accepted
            JOIN authority_book_production production ON production.book_run_id=accepted.book_run_id
              AND production.project_id=accepted.project_id
            JOIN authority_operation operation ON operation.operation_id=accepted.acceptance_operation_id
              AND operation.project_id=accepted.project_id
            JOIN authority_asset_version outcome ON outcome.asset_version_id=accepted.chapter_outcome_asset_version_id
            JOIN authority_asset outcome_asset ON outcome_asset.asset_id=outcome.asset_id AND outcome_asset.project_id=accepted.project_id
            JOIN authority_asset_version story ON story.asset_version_id=accepted.story_state_asset_version_id
            JOIN authority_asset_version canon ON canon.asset_version_id=accepted.canon_snapshot_asset_version_id
            WHERE accepted.project_id=%s AND production.book_id=%s
            ORDER BY accepted.chapter_number,accepted.acceptance_id
            """,
            [project_id, book_id],
        )
        for row in uow.cursor.fetchall():
            outcome = dict(row[8])
            commit_sha = str(dict(row[5]).get("commit_sha") or "")
            for layer in ("PROSE", "ACCEPTANCE"):
                receipts.append(
                    NarrativeReceipt(
                        receipt_id=f"{row[0]}:{layer}",
                        source_table="authority_book_chapter_acceptance",
                        layer=layer,
                        generator="book.chapter.accept",
                        asset_version_id=str(row[2]),
                        content_hash=str(row[3]),
                        operation_id=str(row[4]),
                        implementation_sha=commit_sha,
                        generation_sha=commit_sha,
                        source_class="ACCEPTED_ACTUAL_CONTRACT",
                        status="PASS" if str(row[6]) == "COMMITTED" else "FAIL",
                        current=True,
                        native_lineage_valid=str(row[7]) == "SUCCEEDED"
                        and all(row[index] for index in (9, 10, 11, 12)),
                        profile_current=outcome.get("contract_version")
                        in {"chapter-outcome-v3", "chapter-outcome-v4"},
                        chapter_number=int(row[1]),
                    )
                )
    return tuple(sorted(receipts, key=lambda item: item.receipt_id))
