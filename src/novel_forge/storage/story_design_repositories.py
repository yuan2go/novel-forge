"""Transactional repository for semantic Story Design asset authority."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.book_opening_plan_fence import (
    lock_and_assert_book_opening_plan_mutation,
)


class StoryDesignRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def register_generator(self, definition: dict[str, Any]) -> None:
        encoded = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
        definition_hash = "sha256:" + hashlib.sha256(encoded).hexdigest()
        self.cursor.execute(
            """
            INSERT INTO authority_story_design_generator_definition(
                operation_name, definition_version, capability,
                output_candidate_type, definition, definition_hash, status
            ) VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE')
            ON CONFLICT (operation_name, definition_version) DO UPDATE
            SET status='ACTIVE'
            WHERE authority_story_design_generator_definition.definition_hash=
                  EXCLUDED.definition_hash
            """,
            [
                definition["operation_name"],
                definition["definition_version"],
                definition["capability"],
                definition["output_candidate_type"],
                Jsonb(definition),
                definition_hash,
            ],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "GENERATOR_DEFINITION_CONFLICT",
                "GeneratorDefinition version is already bound to other semantics",
            )

    def apply_transition(
        self,
        *,
        operation_id: str,
        project_id: str,
        asset_version_id: str,
        logical_key: str,
        generator_operation_name: str,
        generator_definition_version: str,
        candidate_type: str,
        planning_scope: str,
        design_scope: str,
        transition: str,
        expected_version: int,
        source_kind: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT transition_operation_id
            FROM authority_story_design_transition
            WHERE transition_operation_id=%s
            """,
            [operation_id],
        )
        if self.cursor.fetchone() is not None:
            return self.require(project_id, asset_version_id)
        if transition == "ACTIVATE":
            self.cursor.execute(
                """
                SELECT generation.operation_id,generation.book_id,
                       generation.logical_key,
                       generation.generator_operation_name
                FROM authority_story_planning_candidate AS candidate
                JOIN authority_story_planning_generation AS generation
                  ON generation.generation_id=candidate.generation_id
                 AND generation.project_id=candidate.project_id
                 AND generation.book_id=candidate.book_id
                WHERE candidate.project_id=%s
                  AND candidate.candidate_asset_version_id=%s
                """,
                [project_id, asset_version_id],
            )
            planning_generation = self.cursor.fetchone()
            if planning_generation is not None:
                if (
                    str(planning_generation[2]) != logical_key
                    or str(planning_generation[3]) != generator_operation_name
                ):
                    raise KernelError(
                        "BOOK_OPENING_PLAN_MUTATION_NOT_AUTHORIZED",
                        "Story Design activation differs from PlanningGeneration lineage",
                    )
                lock_and_assert_book_opening_plan_mutation(
                    self.cursor,
                    project_id=project_id,
                    book_id=str(planning_generation[1]),
                    generation_operation_id=str(planning_generation[0]),
                    candidate_asset_version_id=asset_version_id,
                )
            elif generator_operation_name in {
                "book_plan.generate",
                "volume_plan.generate",
                "arc_plan.generate",
                "chapter_group_plan.generate",
                "chapter_plan.generate",
            }:
                raise KernelError(
                    "STORY_DESIGN_PLANNING_GENERATION_REQUIRED",
                    "Planning-scope Story Design activation requires exact Generation lineage",
                )
        self.cursor.execute(
            """
            SELECT lifecycle, qualification, approval, freshness,
                   semantic_repair_count, structural_regeneration_count,
                   version, logical_key, source_kind
            FROM authority_story_design_version_state
            WHERE project_id=%s AND asset_version_id=%s
            FOR UPDATE
            """,
            [project_id, asset_version_id],
        )
        row = self.cursor.fetchone()
        if transition == "ENROLL":
            if row is None:
                self._validate_enrollment(source_kind, evidence)
                self.cursor.execute(
                    """
                    INSERT INTO authority_story_design_version_state(
                        project_id, asset_version_id, logical_key,
                        generator_operation_name,
                        generator_definition_version, candidate_type,
                        lifecycle, qualification, approval, freshness,
                        planning_scope, design_scope, source_kind, execution_evidence,
                        created_by_operation_id, updated_by_operation_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        'CANDIDATE', 'PENDING', 'NOT_REQUESTED', 'CURRENT',
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    [
                        project_id,
                        asset_version_id,
                        logical_key,
                        generator_operation_name,
                        generator_definition_version,
                        candidate_type,
                        planning_scope,
                        design_scope,
                        source_kind,
                        Jsonb(evidence),
                        operation_id,
                        operation_id,
                    ],
                )
                from_version = to_version = 0
            else:
                if str(row[7]) != logical_key:
                    raise KernelError(
                        "STORY_DESIGN_LOGICAL_KEY_CONFLICT",
                        "candidate is already enrolled under another logical key",
                    )
                from_version = to_version = int(row[6])
        else:
            if row is None:
                raise KernelError(
                    "STORY_DESIGN_CANDIDATE_NOT_FOUND",
                    "Story Design candidate is not enrolled",
                )
            if int(row[6]) != expected_version:
                raise KernelError(
                    "STORY_DESIGN_VERSION_CONFLICT",
                    "Story Design transition expected another aggregate version",
                )
            lifecycle, qualification, approval, freshness = map(str, row[:4])
            semantic_repairs = int(row[4])
            structural_regenerations = int(row[5])
            (
                lifecycle,
                qualification,
                approval,
                freshness,
                semantic_repairs,
                structural_regenerations,
            ) = self._next_state(
                generator_operation_name=generator_operation_name,
                generator_definition_version=generator_definition_version,
                source_kind=str(row[8]),
                transition=transition,
                lifecycle=lifecycle,
                qualification=qualification,
                approval=approval,
                freshness=freshness,
                semantic_repairs=semantic_repairs,
                structural_regenerations=structural_regenerations,
                evidence=evidence,
            )
            from_version = int(row[6])
            to_version = from_version + 1
            if transition == "ACTIVATE":
                self._activate(
                    project_id=project_id,
                    logical_key=logical_key,
                    asset_version_id=asset_version_id,
                    operation_id=operation_id,
                )
            self.cursor.execute(
                """
                UPDATE authority_story_design_version_state
                SET lifecycle=%s, qualification=%s, approval=%s,
                    freshness=%s, semantic_repair_count=%s,
                    structural_regeneration_count=%s,
                    updated_by_operation_id=%s, version=%s, updated_at=NOW()
                WHERE project_id=%s AND asset_version_id=%s AND version=%s
                """,
                [
                    lifecycle,
                    qualification,
                    approval,
                    freshness,
                    semantic_repairs,
                    structural_regenerations,
                    operation_id,
                    to_version,
                    project_id,
                    asset_version_id,
                    from_version,
                ],
            )
            if self.cursor.rowcount != 1:
                raise KernelError(
                    "STORY_DESIGN_VERSION_CONFLICT",
                    "concurrent Story Design transition won",
                )
        self.cursor.execute(
            """
            INSERT INTO authority_story_design_transition(
                transition_operation_id, project_id, asset_version_id,
                transition_type, from_version, to_version, evidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                operation_id,
                project_id,
                asset_version_id,
                transition,
                from_version,
                to_version,
                Jsonb(evidence),
            ],
        )
        event_id = str(uuid4())
        self._record_event(
            operation_id=operation_id,
            project_id=project_id,
            asset_version_id=asset_version_id,
            transition=transition,
            version=to_version,
            event_id=event_id,
        )
        return self.require(project_id, asset_version_id)

    def require(self, project_id: str, asset_version_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT project_id, asset_version_id, logical_key,
                   generator_operation_name, generator_definition_version,
                   candidate_type, lifecycle, qualification, approval,
                   freshness, planning_scope, design_scope, source_kind,
                   execution_evidence, semantic_repair_count,
                   structural_regeneration_count, created_by_operation_id,
                   updated_by_operation_id, version
            FROM authority_story_design_version_state
            WHERE project_id=%s AND asset_version_id=%s
            """,
            [project_id, asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "STORY_DESIGN_CANDIDATE_NOT_FOUND",
                "Story Design candidate does not exist",
            )
        fields = (
            "project_id",
            "asset_version_id",
            "logical_key",
            "generator_operation_name",
            "generator_definition_version",
            "candidate_type",
            "lifecycle",
            "qualification",
            "approval",
            "freshness",
            "planning_scope",
            "design_scope",
            "source_kind",
            "execution_evidence",
            "semantic_repair_count",
            "structural_regeneration_count",
            "created_by_operation_id",
            "updated_by_operation_id",
            "version",
        )
        return dict(zip(fields, row, strict=True))

    @staticmethod
    def _validate_enrollment(source_kind: str, evidence: dict[str, Any]) -> None:
        if source_kind == "GENERATED":
            required = (
                "operation_id",
                "attempt_id",
                "route_snapshot_id",
                "input_manifest_ref",
                "validation_manifest_ref",
                "usage_receipt_ref",
                "cost_receipt_ref",
            )
            if not evidence.get("production_execution_gateway_backed") or any(
                not evidence.get(key) for key in required
            ):
                raise KernelError(
                    "STORY_DESIGN_PEP_EVIDENCE_REQUIRED",
                    "generated candidates require complete PEP evidence",
                )
        elif source_kind == "LEGACY_IMPORT":
            if not evidence.get("legacy_import_operation_id"):
                raise KernelError(
                    "STORY_DESIGN_LEGACY_IMPORT_OPERATION_REQUIRED",
                    "legacy imports require an Authority Operation reference",
                )
        elif source_kind == "OPERATOR_AUTHORED":
            operation_id = str(evidence.get("operation_id") or "")
            if (
                not operation_id
                or operation_id != str(evidence.get("authoring_operation_id") or "")
                or evidence.get("operator_authored") is not True
                or evidence.get("provider_generated") is not False
            ):
                raise KernelError(
                    "STORY_DESIGN_OPERATOR_AUTHORING_EVIDENCE_REQUIRED",
                    "operator-authored candidates require exact non-Provider Authority lineage",
                )
        else:
            raise KernelError(
                "STORY_DESIGN_SOURCE_KIND_INVALID",
                "Story Design source kind is unsupported",
            )

    def _next_state(
        self,
        *,
        generator_operation_name: str,
        generator_definition_version: str,
        source_kind: str,
        transition: str,
        lifecycle: str,
        qualification: str,
        approval: str,
        freshness: str,
        semantic_repairs: int,
        structural_regenerations: int,
        evidence: dict[str, Any],
    ) -> tuple[str, str, str, str, int, int]:
        if transition == "MATERIALIZE" and lifecycle == "CANDIDATE":
            lifecycle = "MATERIALIZED"
        elif transition == "STRUCTURAL_VALIDATE" and lifecycle == "MATERIALIZED":
            if source_kind == "LEGACY_IMPORT":
                self._require_validator_receipt(evidence, "STRUCTURAL")
            if evidence.get("passed") is False:
                structural_regenerations += 1
                maximum = self._repair_bound(
                    generator_operation_name,
                    generator_definition_version,
                    "maximum_structural_regenerations",
                )
                if structural_regenerations > maximum:
                    qualification, lifecycle = "FAILED", "REJECTED"
            else:
                qualification = "STRUCTURALLY_VALID"
        elif (
            transition == "SEMANTIC_VALIDATE" and qualification == "STRUCTURALLY_VALID"
        ):
            if source_kind == "LEGACY_IMPORT":
                self._require_validator_receipt(evidence, "SEMANTIC")
            if evidence.get("passed") is False:
                semantic_repairs += 1
                maximum = self._repair_bound(
                    generator_operation_name,
                    generator_definition_version,
                    "maximum_semantic_repairs",
                )
                if semantic_repairs > maximum:
                    qualification, lifecycle = "FAILED", "REJECTED"
            else:
                qualification = "SEMANTICALLY_VALID"
        elif transition == "QUALIFY" and qualification == "SEMANTICALLY_VALID":
            if source_kind == "LEGACY_IMPORT":
                receipt = evidence.get("qualification_receipt")
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("status") != "PASS"
                    or not str(receipt.get("result_hash") or "").startswith("sha256:")
                    or not receipt.get("migration_validation_id")
                ):
                    raise KernelError(
                        "STORY_DESIGN_QUALIFICATION_RECEIPT_REQUIRED",
                        "Legacy Story Design qualification requires bound validation",
                    )
            qualification = "QUALIFIED"
        elif transition == "SUBMIT_APPROVAL" and qualification == "QUALIFIED":
            approval = "PENDING"
        elif transition == "APPROVE" and approval == "PENDING":
            approval = "APPROVED"
        elif (
            transition == "ACTIVATE"
            and qualification == "QUALIFIED"
            and approval == "APPROVED"
            and freshness == "CURRENT"
        ):
            lifecycle = "ACTIVE"
        elif transition == "REJECT" and lifecycle not in {
            "ACTIVE",
            "SUPERSEDED",
        }:
            lifecycle, approval = "REJECTED", "REJECTED"
        else:
            raise KernelError(
                "STORY_DESIGN_TRANSITION_INVALID",
                f"{transition} is invalid from {lifecycle}/"
                f"{qualification}/{approval}/{freshness}",
            )
        return (
            lifecycle,
            qualification,
            approval,
            freshness,
            semantic_repairs,
            structural_regenerations,
        )

    @staticmethod
    def _require_validator_receipt(
        evidence: dict[str, Any], validation_kind: str
    ) -> None:
        receipt = evidence.get("validator_receipt")
        if (
            not isinstance(receipt, dict)
            or receipt.get("validation_kind") != validation_kind
            or receipt.get("status") != "PASS"
            or not receipt.get("validator_name")
            or not receipt.get("validator_version")
            or not str(receipt.get("result_hash") or "").startswith("sha256:")
        ):
            raise KernelError(
                "STORY_DESIGN_VALIDATOR_RECEIPT_REQUIRED",
                f"Legacy Story Design {validation_kind} validation requires a receipt",
            )

    def _repair_bound(
        self, operation_name: str, definition_version: str, field: str
    ) -> int:
        self.cursor.execute(
            """
            SELECT (definition->>%s)::int
            FROM authority_story_design_generator_definition
            WHERE operation_name=%s AND definition_version=%s
            """,
            [field, operation_name, definition_version],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "GENERATOR_DEFINITION_NOT_FOUND",
                "GeneratorDefinition is not registered",
            )
        return int(row[0])

    def _activate(
        self,
        *,
        project_id: str,
        logical_key: str,
        asset_version_id: str,
        operation_id: str,
    ) -> None:
        self.cursor.execute(
            """
            SELECT asset_version_id
            FROM authority_story_design_active_version
            WHERE project_id=%s AND logical_key=%s
            FOR UPDATE
            """,
            [project_id, logical_key],
        )
        previous = self.cursor.fetchone()
        if previous is not None and str(previous[0]) != asset_version_id:
            self.cursor.execute(
                """
                UPDATE authority_story_design_version_state
                SET lifecycle='SUPERSEDED', version=version+1,
                    updated_by_operation_id=%s, updated_at=NOW()
                WHERE project_id=%s AND asset_version_id=%s
                  AND lifecycle='ACTIVE'
                """,
                [operation_id, project_id, str(previous[0])],
            )
        self.cursor.execute(
            """
            INSERT INTO authority_story_design_active_version(
                project_id, logical_key, asset_version_id,
                activated_by_operation_id
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (project_id, logical_key) DO UPDATE
            SET asset_version_id=EXCLUDED.asset_version_id,
                activated_by_operation_id=EXCLUDED.activated_by_operation_id,
                activated_at=NOW()
            """,
            [project_id, logical_key, asset_version_id, operation_id],
        )

    def _record_event(
        self,
        *,
        operation_id: str,
        project_id: str,
        asset_version_id: str,
        transition: str,
        version: int,
        event_id: str,
    ) -> None:
        self.cursor.execute(
            """
            SELECT trace_id, correlation_id
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [operation_id],
        )
        trace_id, correlation_id = self.cursor.fetchone()
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM state_event
            WHERE aggregate_type='story_design_asset'
              AND aggregate_id=%s
            """,
            [asset_version_id],
        )
        sequence = int(self.cursor.fetchone()[0])
        payload = Jsonb(
            {
                "asset_version_id": asset_version_id,
                "transition": transition,
                "version": version,
                "trace_id": trace_id,
            }
        )
        self.cursor.execute(
            """
            INSERT INTO state_event(
                event_id, aggregate_type, aggregate_id, project_id,
                event_type, event_version, sequence_number,
                correlation_id, causation_id, payload
            ) VALUES (
                %s, 'story_design_asset', %s, %s,
                'story_design.transitioned', 1, %s, %s, %s, %s
            )
            """,
            [
                event_id,
                asset_version_id,
                project_id,
                sequence,
                correlation_id,
                operation_id,
                payload,
            ],
        )
        self.cursor.execute(
            """
            INSERT INTO audit_log(
                audit_id, project_id, operation_id, action, payload
            ) VALUES (%s, %s, %s, 'story_design.transitioned', %s)
            """,
            [str(uuid4()), project_id, operation_id, payload],
        )
        self.cursor.execute(
            """
            INSERT INTO outbox_event(
                outbox_id, event_id, project_id, topic, status, payload
            ) VALUES (
                %s, %s, %s, 'story_design.transitioned', 'PENDING', %s
            )
            """,
            [str(uuid4()), event_id, project_id, payload],
        )


__all__ = ["StoryDesignRepository"]
