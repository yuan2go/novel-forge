from __future__ import annotations

import unittest
import tempfile
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
from novel_forge.modules.chapter_authority.model_effects import (
    ExternalEffectChapterModelPort,
    ModelProviderResult,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterNode,
    SingleChapterRequest,
)
from novel_forge.modules.chapter_quality_authority import (
    QUALITY_DIMENSIONS,
    QUALITY_GROUPS,
)
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution import (
    AuthorityExecutionRecoveryStore,
    ExecutionOutcome,
)
from novel_forge.modules.mkaos_authority import MkaosAuthorityQuery
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
    transaction,
)


class _ModelAdapter:
    provider = "fixture_model_effect_provider"
    reconciliation_mode = "unsupported"
    capability_profile = {
        "provider": provider,
        "control_level": "FIXTURE_CONTROLLED",
        "supports_request_timeout": True,
        "supports_provider_idempotency": True,
        "supports_query": False,
        "supports_cancel": False,
        "supports_callback": False,
        "supports_usage_receipt": True,
        "supports_cost_receipt": True,
        "reconciliation_mode": "unsupported",
        "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def __init__(self, *, fail_after_send: bool = False) -> None:
        self.fail_after_send = fail_after_send
        self.calls = 0

    def execute(self, *, stable_idempotency_key, capability, request_payload):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail_after_send:
            raise ExternalEffectAdapterError("connection lost", request_sent=True)
        if capability == "model.draft":
            output = {"text": "The promise is public, but its cost remains abstract."}
        elif capability == "model.retrieval_query_expansion":
            output = {
                "contract_version": "retrieval-expansion-plan-v1",
                "queries": [
                    {
                        "query_id": "query:origin",
                        "text": "bridge oath origin",
                        "reason": "recover required causal provenance",
                        "targets": ["fact:fact:origin"],
                        "selectors": {"entity_ids": ["entity:key"]},
                        "temporal_range": {
                            "from_chapter": 1,
                            "to_chapter": 40,
                        },
                    }
                ],
            }
        elif capability == "model.review":
            output = {
                "decision": "NEEDS_REVISION",
                "score": 70,
                "issues": [
                    {
                        "code": "COST_NOT_CONCRETE",
                        "severity": "blocking",
                        "message": "The cost must be visible.",
                    }
                ],
            }
        else:
            output = {
                "text": "The protagonist surrenders the only safe route home before every witness.",
                "resolved_issue_codes": ["COST_NOT_CONCRETE"],
            }
        result = ModelProviderResult(
            output=output,
            provider_id=self.provider,
            model_id="fixture-model-v1",
            prompt_version="draft-prompt-v1",
            skill_version="prose-generation-v1",
            input_tokens=120,
            output_tokens=40,
            cost_amount="0.0042",
            currency="USD",
            real_model_call=True,
            usage_evidence={
                "availability": "AVAILABLE",
                "measurement": "MEASURED",
                "input_tokens": 120,
                "output_tokens": 40,
                "total_tokens": 160,
            },
            cost_evidence={
                "availability": "AVAILABLE",
                "measurement": "MEASURED",
                "source": "provider_receipt",
                "amount": "0.0042",
                "currency": "USD",
                "estimated": False,
                "provider_billed": True,
            },
        )
        return ProviderResult(
            outcome="success",
            provider_correlation_id=f"fixture:{stable_idempotency_key}",
            evidence=result.to_evidence(),
        )

    def query(self, *, stable_idempotency_key, capability, request_payload):  # type: ignore[no-untyped-def]
        return ProviderResult("ambiguous", "", {"provider_state": "unknown"})


class _RetryableMeasuredAdapter(_ModelAdapter):
    def execute(self, *, stable_idempotency_key, capability, request_payload):  # type: ignore[no-untyped-def]
        self.calls += 1
        usage = {
            "availability": "AVAILABLE",
            "measurement": "MEASURED",
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
        }
        cost = {
            "availability": "AVAILABLE",
            "measurement": "ESTIMATED",
            "amount": "0.0042",
            "currency": "USD",
            "estimated": True,
            "provider_billed": False,
            "pricing_ref": "pricing:test:v1",
            "pricing_snapshot_hash": "sha256:pricing",
            "calculation_basis": {"formula": "test"},
            "model": "fixture-model-v1",
        }
        return ProviderResult(
            outcome="retryable_failure",
            provider_correlation_id=f"fixture:{stable_idempotency_key}",
            evidence={
                "provider_id": self.provider,
                "model_id": "fixture-model-v1",
                "prompt_version": "draft-prompt-v1",
                "skill_version": "prose-generation-v1",
                "real_model_call": True,
                "production_execution": {
                    "process_evidence": {
                        "failure_code": "OUTPUT_SEMANTIC_FAILURE",
                        "failure_message": "invalid stage semantics",
                        "usage": usage,
                        "cost": cost,
                    }
                },
            },
        )


class _RetryOnceMeasuredAdapter(_RetryableMeasuredAdapter):
    def execute(self, *, stable_idempotency_key, capability, request_payload):  # type: ignore[no-untyped-def]
        if self.calls == 0:
            return super().execute(
                stable_idempotency_key=stable_idempotency_key,
                capability=capability,
                request_payload=request_payload,
            )
        return _ModelAdapter.execute(
            self,
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
        )


class _AdmissionRejectingBinder:
    def freeze_before_external_effect(self, **_kwargs: object) -> None:
        raise KernelError(
            "PROVIDER_TOKEN_ADMISSION_REJECTED",
            "PROVIDER_CONTEXT_LIMIT_EXCEEDED",
        )


class _GatewayAdmissionAdapter(_ModelAdapter):
    production_execution_gateway_backed = True

    def provider_id_for_stage(self, _stage: str) -> str:
        return "openai"


class ChapterModelEffectsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def _request(self) -> ChapterHandlerRequest:
        project_id = identifier("model-project")
        operation_id = identifier("model-operation")
        definition_name = identifier("model-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
            )
        return ChapterHandlerRequest(
            operation_id=operation_id,
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            command={"chapter": 1, "context_token_budget": 200},
            inputs=(),
        )

    def _release_evidence(
        self, project_id: str, *, with_mkaos: bool = False, scope_preseeded: bool = False, workspace_id: str = "", extra_context_candidates: tuple[dict[str, object], ...] = ()
    ) -> tuple[dict[str, object], ...]:
        workspace_id = workspace_id or f"workspace:{project_id}"
        if with_mkaos and not scope_preseeded:
            seed_authority_project_book(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=f"book:{project_id}",
            )
        candidates: list[dict[str, object]] = [
            {
                "asset_version_id": f"{project_id}:chapter-plan-v1",
                "asset_type": "chapter_plan",
                "project_id": project_id,
                "safe_summary": "Complete ChapterPlan.",
                "structured_facts": [],
                "estimated_tokens": 120,
                "narrative_function": "chapter_plan",
                "content": {
                    "project_id": project_id,
                    "chapter": 1,
                    "title": "A Visible Cost",
                    "premise": "A public promise becomes irreversible.",
                    "chapter_objective": "Make the public promise costly.",
                    "scene_sequence": [{"scene_id": "s1", "goal": "choose the cost"}],
                    "required_arc_contributions": [
                        {
                            "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1",
                            "contribution": "ADVANCE",
                        }
                    ],
                    "constraint_envelope": {
                        "arc_working_set": {
                            "selected_contributions": [
                                {
                                    "arc_plan_version_id": (
                                        f"{project_id}:fixture-arc-plan-v1"
                                    ),
                                    "role": "PRIMARY",
                                    "action": "ADVANCE",
                                }
                            ]
                        }
                    },
                    "scene_plan": [
                        {
                            "scene_id": "s1",
                            "goal": "choose the cost",
                            "conflict": "safety requires breaking the promise",
                            "arc_progress": [f"{project_id}:fixture-arc-plan-v1"],
                            "beats": ["pressure", "choice", "visible cost"],
                        }
                    ],
                    "chapter_hook": "A new obligation arrives.",
                },
            },
            {
                "asset_version_id": f"{project_id}:quality-rubric-v1",
                "asset_type": "quality_rubric",
                "project_id": project_id,
                "safe_summary": "Versioned chapter quality thresholds.",
                "structured_facts": [
                    {"key": "thresholds", "value": {"readability": 70, "sentence_length_unit": "WHITESPACE_WORDS"}}
                ],
                "estimated_tokens": 20,
                "narrative_function": "quality_policy",
            },
            {
                "asset_version_id": f"{project_id}:platform-profile-v1",
                "asset_type": "platform_profile",
                "project_id": project_id,
                "safe_summary": "Versioned internal platform policy.",
                "structured_facts": [
                    {
                        "key": "platform_rules",
                        "value": {
                            "chapter_length": {"minimum": 10, "maximum": 10000},
                            "format": {"paragraph_max": 500},
                            "sensitive_content": [],
                            "ai_content": {"mode": "internal"},
                            "opening": ["visible conflict"],
                            "rhythm": ["payoff"],
                            "publish_metadata": {"title_required": True},
                        },
                    }
                ],
                "estimated_tokens": 30,
                "narrative_function": "platform_policy",
            },
            {
                "asset_version_id": f"{project_id}:checklist-v1",
                "asset_type": "operator_checklist",
                "project_id": project_id,
                "safe_summary": "Release checklist completed.",
                "structured_facts": [
                    {"key": "completed", "value": True},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-checklist-v1",
                    },
                ],
                "estimated_tokens": 8,
                "narrative_function": "release_evidence",
            },
            {
                "asset_version_id": f"{project_id}:approval-v1",
                "asset_type": "operator_approval",
                "project_id": project_id,
                "safe_summary": "Fixture release approval.",
                "structured_facts": [
                    {"key": "approved", "value": True},
                    {"key": "decision", "value": "APPROVED"},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-approval-v1",
                    },
                    {"key": "fixture_protocol_only", "value": True},
                    {
                        "key": "waiver_reason",
                        "value": "Deterministic integration fixture release only.",
                    },
                    {
                        "key": "waived_dimensions",
                        "value": list(QUALITY_DIMENSIONS),
                    },
                    {
                        "key": "scope",
                        "value": {
                            "project_id": project_id,
                            "scope_type": "PROJECT_FIXTURE",
                            "release_readiness": "INTERNAL_REVIEW_RELEASE",
                        },
                    },
                    {"key": "expiry", "value": "2099-01-01T00:00:00Z"},
                ],
                "estimated_tokens": 8,
                "narrative_function": "release_evidence",
            },
        ]
        candidates.extend(
            {
                "asset_version_id": f"{project_id}:{group}-quality-report-v1",
                "asset_type": f"{group}_quality_report",
                "project_id": project_id,
                "safe_summary": "Approved fixture-only quality evidence.",
                "structured_facts": [
                    {
                        "key": "dimension_evidence",
                        "value": [
                            {
                                "dimension": dimension,
                                "gate_status": "WAIVED_BY_APPROVAL",
                                "calibration_status": "HUMAN_CALIBRATED",
                                "human_verified": True,
                                "fixture_protocol_only": True,
                            }
                            for dimension in dimensions
                        ],
                    }
                ],
                "estimated_tokens": 40,
                "narrative_function": "quality_evidence",
            }
            for group, dimensions in QUALITY_GROUPS.items()
        )
        if with_mkaos:
            candidates.append(
                {
                    "asset_version_id": f"{project_id}:knowledge-pack-v1",
                    "asset_type": "knowledge_pack",
                    "project_id": project_id,
                    "provenance": {
                        "authority": "MKAOS",
                        "knowledge_card_asset_version_ids": [f"{project_id}:knowledge-card:v1"],
                        "knowledge_card_usages": [{
                            "knowledge_card_asset_version_id": f"{project_id}:knowledge-card:v1",
                            "usage_role": "CONSTRAINT",
                        }],
                    },
                    "safe_summary": "Use visible irreversible costs for public promises.",
                    "structured_facts": [
                        {
                            "key": "craft_constraint",
                            "value": "Make the consequence observable in-scene.",
                        }
                    ],
                    "estimated_tokens": 24,
                    "narrative_function": "craft_constraint",
                    "content": {
                        "contract_version": "mkaos-knowledge-pack-v1",
                        "book_id": f"book:{project_id}",
                        "safe_summary": (
                            "Use visible irreversible costs for public promises."
                        ),
                        "structured_facts": [
                            {
                                "key": "craft_constraint",
                                "value": "Make the consequence observable in-scene.",
                            }
                        ],
                    },
                }
            )
        candidates.extend(dict(item) for item in extra_context_candidates)
        with transaction() as connection, connection.cursor() as cursor:
            for candidate in candidates:
                content = dict(
                    candidate.get("content")
                    or {
                        "safe_summary": candidate["safe_summary"],
                        "structured_facts": candidate["structured_facts"],
                    }
                )
                content_hash = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            content, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
                candidate["content_hash"] = content_hash
                asset_id = f"{candidate['asset_version_id']}:asset"
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, candidate["asset_type"]],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                    """,
                    [
                        candidate["asset_version_id"],
                        asset_id,
                        json.dumps(content),
                        content_hash,
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_qualification (
                        qualification_id, asset_version_id, policy_version, decision, evidence
                    ) VALUES (%s, %s, 'model-fixture-release-v1', 'ELIGIBLE', '{}'::jsonb)
                    """,
                    [
                        f"{candidate['asset_version_id']}:qualification",
                        candidate["asset_version_id"],
                    ],
                )
            if with_mkaos:
                definition_name = identifier("mkaos-pack-definition")
                operation_id = identifier("mkaos-pack-operation")
                insert_definition(cursor, definition_name)
                insert_operation(
                    cursor,
                    operation_id=operation_id,
                    definition_name=definition_name,
                    project_id=project_id,
                    status="SUCCEEDED",
                )
                card_asset_id = f"{project_id}:knowledge-card"
                card_version_id = f"{card_asset_id}:v1"
                card_content = {
                    "safe_summary": "Public promises require an observable cost.",
                    "structured_facts": [
                        {
                            "key": "craft_constraint",
                            "value": "Make the cost irreversible and visible.",
                        }
                    ],
                }
                card_hash = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            card_content, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
                cursor.execute(
                    "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s,%s,'knowledge_card')",
                    [card_asset_id, project_id],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                      asset_version_id, asset_id, version_number, lifecycle,
                      eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'integration-fixture.v1')
                    """,
                    [
                        card_version_id,
                        card_asset_id,
                        json.dumps(card_content),
                        card_hash,
                    ],
                )
                pack_version_id = f"{project_id}:knowledge-pack-v1"
                pack_asset_id = f"{pack_version_id}:asset"
                cursor.execute(
                    """
                    INSERT INTO authority_mkaos_knowledge_pack(
                      knowledge_pack_id, project_id, workspace_id,
                      asset_version_id, target_asset_version_id,
                      created_by_operation_id, selector_policy_version,
                      selector_policy_hash, selection_hash, item_count, status
                    ) VALUES (%s,%s,%s,%s,%s,%s,'integration-selector-v1',%s,%s,1,'ACTIVE')
                    """,
                    [
                        pack_asset_id,
                        project_id,
                        workspace_id,
                        pack_version_id,
                        f"{project_id}:chapter-plan-v1",
                        operation_id,
                        "sha256:" + hashlib.sha256(b"selector").hexdigest(),
                        "sha256:" + hashlib.sha256(b"selection").hexdigest(),
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_mkaos_knowledge_pack_item(
                      knowledge_pack_id, knowledge_pack_asset_version_id,
                      knowledge_card_asset_version_id, ordinal, usage_role,
                      frozen_weight, created_by_operation_id
                    ) VALUES (%s,%s,%s,0,'CONSTRAINT',1.0,%s)
                    """,
                    [pack_asset_id, pack_version_id, card_version_id, operation_id],
                )
        return tuple(candidates)

    def _seed_intrinsic_semantic_commit_policy(self, project_id: str) -> None:
        """Reproduce the policy identity frozen by planning semantic review."""

        contract = {
            "policy_id": "commit:quality-intrinsic-judge:v1",
            "policy_version": "v1",
            "candidate_asset_type": "narrative_semantic_evaluation_candidate",
            "requires_validation_manifest": True,
            "requires_approval": True,
            "activation_mode": "DOMAIN_AUTHORITY_ONLY",
        }
        content = {"contract": contract}
        content_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        asset_id = f"{project_id}:intrinsic-semantic-commit-policy"
        asset_version_id = f"{asset_id}:v1"
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO authority_asset(asset_id, project_id, asset_type) "
                "VALUES (%s, %s, 'execution_commit_policy')",
                [asset_id, project_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                  asset_version_id, asset_id, version_number, lifecycle,
                  eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s,
                          'production-execution-contract.v1')
                """,
                [asset_version_id, asset_id, json.dumps(content), content_hash],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_locator(
                  project_id, logical_ref, category, asset_id,
                  current_asset_version_id
                ) VALUES (%s, 'commit:quality-intrinsic-judge:v1',
                          'production_execution_contracts', %s, %s)
                """,
                [project_id, asset_id, asset_version_id],
            )

    def test_success_records_effect_receipt_model_call_and_cost_once(self) -> None:
        request = self._request()
        adapter = _ModelAdapter()
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id="model-worker",
            max_cost_per_call="0.01",
        )

        first = port.invoke(request, stage="draft", payload={"prompt": "write"})
        replay = port.invoke(request, stage="draft", payload={"prompt": "write"})

        self.assertEqual(first.output, replay.output)
        self.assertEqual(adapter.calls, 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_external_effect WHERE operation_id = %s",
                [request.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "SUCCEEDED")
            cursor.execute(
                """
                SELECT asset.asset_type, COUNT(*)
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                WHERE binding.operation_id = %s
                GROUP BY asset.asset_type
                """,
                [request.operation_id],
            )
            self.assertEqual(
                dict(cursor.fetchall()), {"cost_ledger": 1, "model_call_log": 1}
            )

    def test_provider_admission_rejection_creates_no_external_effect(self) -> None:
        request = self._request()
        adapter = _GatewayAdmissionAdapter()
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id="admission-worker",
            capability_binder=_AdmissionRejectingBinder(),
        )

        with self.assertRaisesRegex(
            KernelError, "PROVIDER_CONTEXT_LIMIT_EXCEEDED"
        ):
            port.invoke(request, stage="draft", payload={"prompt": "write"})

        self.assertEqual(adapter.calls, 0)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_external_effect "
                "WHERE operation_id=%s",
                [request.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_query_expansion_effect_is_typed_durable_and_replayed_once(self) -> None:
        request = replace(
            self._request(),
            command={
                "chapter": 41,
                "context_token_budget": 200,
                "_effect_instance": "retrieval-expansion-round-1",
            },
        )
        adapter = _ModelAdapter()
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id="retrieval-expansion-worker",
            max_cost_per_call="0.01",
        )
        payload = {
            "round_number": 1,
            "accepted_boundary": {"accepted_through_chapter": 40},
            "coverage": {"missing": {"fact_ids": ["fact:origin"]}},
            "allowed_retrieval_dimensions": ["entity_ids"],
        }

        first = port.invoke(
            request,
            stage="retrieval_query_expansion",
            payload=payload,
        )
        replay = port.invoke(
            request,
            stage="retrieval_query_expansion",
            payload=payload,
        )

        self.assertEqual(first.output, replay.output)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(first.output["queries"][0]["targets"], ["fact:fact:origin"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT capability, status, COUNT(*) OVER ()
                FROM authority_external_effect
                WHERE operation_id=%s
                """,
                [request.operation_id],
            )
            capability, status, effect_count = cursor.fetchone()
        self.assertEqual(capability, "model.retrieval_query_expansion")
        self.assertEqual(status, "SUCCEEDED")
        self.assertEqual(effect_count, 1)

    def test_query_expansion_response_loss_is_not_blindly_resent(self) -> None:
        request = replace(
            self._request(),
            command={
                "chapter": 41,
                "context_token_budget": 200,
                "_effect_instance": "retrieval-expansion-round-1",
            },
        )
        adapter = _ModelAdapter(fail_after_send=True)
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id="retrieval-expansion-loss-worker",
        )
        payload = {
            "round_number": 1,
            "accepted_boundary": {"accepted_through_chapter": 40},
            "coverage": {"missing": {"fact_ids": ["fact:origin"]}},
            "allowed_retrieval_dimensions": ["entity_ids"],
        }

        with self.assertRaisesRegex(KernelError, "EFFECT_EXTERNAL_STATE_UNKNOWN"):
            port.invoke(
                request,
                stage="retrieval_query_expansion",
                payload=payload,
            )
        with self.assertRaises(KernelError):
            port.invoke(
                request,
                stage="retrieval_query_expansion",
                payload=payload,
            )

        self.assertEqual(adapter.calls, 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT capability, status, COUNT(*) OVER ()
                FROM authority_external_effect
                WHERE operation_id=%s
                """,
                [request.operation_id],
            )
            capability, status, effect_count = cursor.fetchone()
        self.assertEqual(capability, "model.retrieval_query_expansion")
        self.assertEqual(status, "UNKNOWN")
        self.assertEqual(effect_count, 1)

    def test_model_effect_accepts_only_lower_internal_reservation_limits(self) -> None:
        request = replace(
            self._request(), command={"chapter": 1, "context_token_budget": 200}
        )
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=_ModelAdapter(),
            worker_id="bounded-model-worker",
            max_cost_per_call="0.01",
        )

        port.invoke(
            request,
            stage="draft",
            payload={"prompt": "write"},
            reservation_amount="0.005",
            reservation_tokens=180,
        )

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT reserved_amount, estimated_tokens
                FROM authority_budget_reservation
                WHERE operation_id=%s
                """,
                [request.operation_id],
            )
            amount, tokens = cursor.fetchone()
        self.assertEqual(str(amount), "0.00500000")
        self.assertEqual(tokens, 180)

        invalid_request = self._request()
        with self.assertRaises(KernelError) as raised:
            port.invoke(
                invalid_request,
                stage="draft",
                payload={"prompt": "write"},
                reservation_amount="0.02",
            )
        self.assertEqual(
            raised.exception.code,
            "MODEL_EFFECT_RESERVATION_OVERRIDE_INVALID",
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_external_effect WHERE operation_id=%s",
                [invalid_request.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_effect_timeout_uses_frozen_operation_policy_not_worker_lease(self) -> None:
        request = self._request()
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_operation
                SET definition_snapshot = jsonb_build_object(
                    'timeout_policy',
                    jsonb_build_object('operation_timeout_seconds', 600)
                )
                WHERE operation_id=%s AND project_id=%s
                """,
                [request.operation_id, request.project_id],
            )
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=_ModelAdapter(),
            worker_id="model-timeout-policy-worker",
            lease_seconds=7,
            max_cost_per_call="0.01",
        )

        port.invoke(request, stage="draft", payload={"prompt": "write"})

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT request_timeout_seconds
                FROM authority_external_effect
                WHERE operation_id=%s
                """,
                [request.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], 600)

    def test_retryable_model_failure_records_usage_cost_and_no_candidate(self) -> None:
        request = self._request()
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=_RetryableMeasuredAdapter(),
            worker_id="model-worker",
            max_cost_per_call="0.01",
        )

        with self.assertRaisesRegex(
            KernelError,
            "MODEL_EFFECT_RETRYABLE_OUTPUT_SEMANTIC_FAILURE",
        ):
            port.invoke(request, stage="draft", payload={"prompt": "write"})

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT asset.asset_type, version.content
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset ON asset.asset_id=binding.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s
                  AND asset.asset_type IN ('model_call_log', 'cost_ledger')
                ORDER BY asset.asset_type
                """,
                [request.operation_id],
            )
            evidence = {str(row[0]): dict(row[1]) for row in cursor.fetchall()}
            self.assertFalse(evidence["model_call_log"]["accepted_candidate"])
            self.assertEqual(
                evidence["model_call_log"]["failure_code"],
                "OUTPUT_SEMANTIC_FAILURE",
            )
            self.assertFalse(evidence["cost_ledger"]["accepted_candidate"])
            self.assertEqual(evidence["cost_ledger"]["total_tokens"], 160)
            self.assertTrue(evidence["cost_ledger"]["estimated"])
            self.assertFalse(evidence["cost_ledger"]["provider_billed"])
            cursor.execute(
                """
                SELECT status, actual_tokens, settled_amount
                FROM authority_budget_reservation
                WHERE operation_id=%s
                """,
                [request.operation_id],
            )
            status, actual_tokens, settled_amount = cursor.fetchone()
            self.assertEqual(status, "SETTLED")
            self.assertEqual(actual_tokens, 160)
            self.assertEqual(str(settled_amount), "0.00420000")

    def test_measured_retry_uses_frozen_operation_envelope_and_settles_both_calls(
        self,
    ) -> None:
        base = self._request()
        adapter = _RetryOnceMeasuredAdapter()
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id="model-retry-budget-worker",
            max_cost_per_call="0.01",
            budget_caps={"operation_total": "0.02"},
        )

        with self.assertRaisesRegex(
            KernelError,
            "MODEL_EFFECT_RETRYABLE_OUTPUT_SEMANTIC_FAILURE",
        ):
            port.invoke(
                replace(base, attempt_id="attempt:1"),
                stage="draft",
                payload={"prompt": "write"},
            )
        result = port.invoke(
            replace(base, attempt_id="attempt:2"),
            stage="draft",
            payload={"prompt": "write"},
        )

        self.assertEqual(adapter.calls, 2)
        self.assertIn("promise is public", result.output["text"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*), BOOL_AND(status='SETTLED'),
                       SUM(settled_amount), SUM(actual_tokens)
                FROM authority_budget_reservation
                WHERE operation_id=%s
                """,
                [base.operation_id],
            )
            count, all_settled, amount, tokens = cursor.fetchone()
        self.assertEqual(count, 2)
        self.assertTrue(all_settled)
        self.assertEqual(str(amount), "0.00840000")
        self.assertEqual(tokens, 320)

    def test_exception_after_send_is_unknown_and_not_blindly_retried(self) -> None:
        request = self._request()
        adapter = _ModelAdapter(fail_after_send=True)
        port = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id="model-worker",
        )

        with self.assertRaisesRegex(KernelError, "EFFECT_EXTERNAL_STATE_UNKNOWN"):
            port.invoke(request, stage="draft", payload={"prompt": "write"})
        with self.assertRaises(KernelError):
            port.invoke(request, stage="draft", payload={"prompt": "write"})

        self.assertEqual(adapter.calls, 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_external_effect WHERE operation_id = %s",
                [request.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "UNKNOWN")

    def test_context_selection_is_not_consumption_before_provider_execution(
        self,
    ) -> None:
        project_id = identifier("mkaos-selection-only-project")
        worker_id = "mkaos-selection-worker"
        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(
                root=Path(directory), database_url=DATABASE_URL
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                    Path(directory) / "objects"
                ),
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
            }
            execution = build_production_execution_composition(settings, env=env)
            application = build_chapter_authority_application(
                settings, execution=execution, env=env
            )
            principal = Principal(
                principal_id=worker_id,
                principal_type=PrincipalType.WORKER,
                permissions=frozenset({"chapter.authority.execute"}),
                project_scope=frozenset({project_id}),
                authentication_source="integration-test",
            )
            admission = application.admit(
                SingleChapterRequest(
                    project_id=project_id,
                    workspace_id=f"workspace:{project_id}",
                    actor_id=worker_id,
                    chapter=1,
                    title="Selection Is Not Consumption",
                    context_token_budget=64_000,
                    premise="A selected rule has not yet reached a provider.",
                    trace_id=identifier("selection-trace"),
                    correlation_id=identifier("selection-correlation"),
                    application_build_id="mkaos-selection-test",
                    commit_sha="e" * 40,
                    context_candidates=self._release_evidence(
                        project_id, with_mkaos=True
                    ),
                ),
                principal=principal,
            )
            scheduler = application.scheduler(principal=principal)
            context_materialized = False
            for _ in range(12):
                tick = scheduler.tick(
                    project_id=project_id,
                    root_operation_id=admission.root_operation_id,
                )
                if tick.node == "context" and tick.operation_status == "SUCCEEDED":
                    context_materialized = True
                    break
            self.assertTrue(context_materialized)

        query = MkaosAuthorityQuery(DATABASE_URL)
        self.assertEqual(len(query.list_runtime_selections(project_id=project_id)), 1)
        self.assertEqual(query.list_runtime_usage(project_id=project_id), [])

    def test_canonical_chapter_outcome_obeys_frozen_router_with_fixture_evidence(self) -> None:
        from datetime import datetime, timezone
        from unittest.mock import patch

        from novel_forge.modules.production_execution.cost_routing import (
            BenchmarkObservation, ModelCandidate, PricingSnapshot,
        )
        from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
        from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness

        harness = CapabilityPackPostgresHarness("router-chapter-fixture", release_sha="e" * 40)
        approved = harness.register_compile_approve(
            "1.0.0", generation=1,
            approval_scope=harness.approval_scope(
                environments=("test",), runtime_profiles=("test",)
            ), target_runtime_profile="test",
        )
        harness.register_agents(approved.compiled)
        harness.activate(
            harness.deploy(approved, environment="test", runtime_profile="test"),
            environment="test",
        )
        candidate = ModelCandidate(
            candidate_id="fixture:chapter-router-selected", provider="scripted_provider_v2",
            model="scripted-router-selected", reasoning="high", tier="low",
            capabilities=("structured_output", "text"), context_limit=2_000_000,
            output_limit=100_000, capability_version="fixture-router.v1",
            pricing=PricingSnapshot(
                version="fixture-zero-cost.v1", effective_from="2000-01-01T00:00:00+00:00",
                effective_until="9999-01-01T00:00:00+00:00", input_miss_per_million="0",
                input_hit_per_million="0", output_per_million="0", source="fixture:zero-cost",
            ),
        )
        router = ProductionProviderRouter(
            DATABASE_URL, candidates=(candidate,), task_money_limit="1",
            task_token_limit=2_000_000,
        )
        # Synthetic inputs exercise admission only; they are never stored as measured benchmarks.
        observations = [BenchmarkObservation(
            evidence_ref=f"fixture:synthetic-routing-input:{index}",
            occurred_at=datetime.now(timezone.utc).isoformat(), quality_score=1.0,
            accepted=True, schema_success=True, canon_conflict=False, retried=False,
            repaired=False, escalated=False, latency_seconds=1, input_tokens=10,
            output_tokens=10, cache_hit_tokens=0, actual_cost="0",
        ) for index in range(200)]
        project_id = harness.project_id
        worker_id = "chapter-router-fixture-worker"
        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(root=Path(directory), database_url=DATABASE_URL)
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": harness.pack_id,
                "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(Path(directory) / "objects"),
                "NOVEL_FORGE_ENABLE_SYNCHRONOUS_AUTHORITY_FIXTURE": "true",
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
            }
            execution = build_production_execution_composition(settings, env=env)
            execution.gateway.provider_router = router
            application = build_chapter_authority_application(settings, execution=execution, env=env)
            self.assertIs(application._model_port.capability_binder.provider_router, router)
            self._seed_intrinsic_semantic_commit_policy(project_id)
            request = SingleChapterRequest(
                project_id=project_id, workspace_id=harness.workspace_id, actor_id=worker_id,
                chapter=1, title="A Frozen Fixture Route", premise="A public choice costs a safe route home.",
                trace_id=identifier("router-trace"), correlation_id=identifier("router-correlation"),
                application_build_id="chapter-router-fixture-test", commit_sha="e" * 40,
                context_candidates=self._release_evidence(
                    project_id, scope_preseeded=True, workspace_id=harness.workspace_id,
                ),
            )
            def synthetic_evidence(**scope):
                from novel_forge.modules.production_execution.cost_routing import REFERENCE_TASKS, task_policy
                if task_policy(scope["task_type"]).quality_metric == "GENERATOR_SCORE":
                    return [replace(
                        row,
                        evidence_ref=f"fixture:generator-routing:{tokens}:{index}",
                        quality_score=None, accepted=None, domain_gate_accepted=None,
                        evidence_class="BENCHMARK_CHALLENGER", production_eligible=False,
                        experiment_partition="CALIBRATION",
                        producer_contract_hash=scope["producer_contract_hash"],
                        sample_identity=f"fixture:generator:{tokens}:{index}",
                        independence_group=f"fixture:input:{tokens}:{index}",
                        generator_quality_score=.99,
                        generator_protocol_hash="sha256:" + "1" * 64,
                        generator_risk=task_policy(scope["task_type"]).risk,
                        generator_context_tokens=tokens,
                        outcome_refs=(f"fixture:synthetic-label:{tokens}:{index}",),
                    ) for tokens in (1000, 10000, 40000, 150000, 600000)
                        for index, row in enumerate(observations[:80])]
                if scope["task_type"] not in REFERENCE_TASKS:
                    return observations
                return [replace(row, evidence_ref=row.evidence_ref + ":" + str(tokens), quality_score=None, accepted=None,
                    evidence_class="REFERENCE_EVALUATION", production_eligible=False, input_tokens=tokens,
                    reference_agreed=True, reference_context_tokens=tokens, reference_label_classes=("PASS" if i % 2 else "FAIL",),
                    reference_protocol_hash="sha256:" + "1" * 64, reference_risk=task_policy(scope["task_type"]).risk,
                    sample_identity=row.evidence_ref + ":" + str(tokens))
                    for tokens in (1000, 10000, 40000, 150000, 600000) for i, row in enumerate(observations[:80])]

            with patch.object(router.registry, "observations", side_effect=synthetic_evidence) as measured_inputs:
                result = application.run(request)
                self.assertEqual((result.root_status, result.saga_status), ("SUCCEEDED", "SUCCEEDED"))
                measured_inputs.assert_called()

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT external_effect_id, model_id, request_payload
                   FROM authority_external_effect
                   WHERE project_id=%s AND capability='model.draft' AND status='SUCCEEDED'""",
                [project_id],
            )
            effects = cursor.fetchall()
            self.assertEqual(len(effects), 1)
            effect_id, selected_model, payload = effects[0]
            self.assertEqual(selected_model, candidate.model)
            decision = payload["_production_execution"]["capability_runtime"]["routing_decision"]
            self.assertEqual(decision["status"], "SELECTED")
            self.assertEqual(decision["selected"]["candidate"]["candidate_id"], candidate.candidate_id)
            document = router.registry.query.require(
                project_id=project_id, asset_version_id=decision["asset_version_id"],
            )
            self.assertEqual(document.content, {key: value for key, value in decision.items() if key != "asset_version_id"})
            cursor.execute(
                """SELECT status, provider, settled_amount FROM authority_budget_reservation
                   WHERE project_id=%s AND external_effect_id=%s""", [project_id, effect_id],
            )
            reservations = cursor.fetchall()
            self.assertEqual(len(reservations), 1)
            self.assertEqual(reservations[0][:2], ("SETTLED", candidate.provider))
            self.assertEqual(reservations[0][2], 0)
            cursor.execute(
                """SELECT version.content FROM authority_asset asset
                   JOIN authority_asset_version version ON version.asset_id=asset.asset_id
                   WHERE asset.project_id=%s AND asset.asset_type='model_call_log'
                     AND version.content->>'external_effect_id'=%s""", [project_id, effect_id],
            )
            logs = cursor.fetchall()
            self.assertEqual(len(logs), 1)
            evidence = logs[0][0]["provider_evidence"]
            self.assertEqual(evidence["model_id"], candidate.model)
            self.assertFalse(evidence["real_model_call"])
            recorded_execution = evidence["production_execution"]
            self.assertEqual(recorded_execution["route_snapshot"]["model_id"], candidate.model)
            self.assertEqual(recorded_execution["execution_result"]["outcome"], "SUCCEEDED")
            self.assertEqual(recorded_execution["execution_handle"]["transport"], "SCRIPTED_FIXTURE")
            self.assertEqual(recorded_execution["execution_handle"]["backend_id"], "scripted-fixture")
            cursor.execute(
                """SELECT effect.capability, effect.status, effect.model_id, budget.status
                   FROM authority_external_effect effect
                   JOIN authority_budget_reservation budget
                     ON budget.external_effect_id=effect.external_effect_id
                   WHERE effect.project_id=%s AND effect.provider='production_execution_gateway'""",
                [project_id],
            )
            calls = cursor.fetchall()
            self.assertEqual(len(calls), 12)
            self.assertIn("model.quality_longform", {row[0] for row in calls})
            self.assertTrue(all(row[1:] == ("SUCCEEDED", candidate.model, "SETTLED") for row in calls))
            cursor.execute(
                """SELECT asset.asset_type, version.asset_version_id, version.content
                   FROM authority_asset asset
                   JOIN authority_asset_version version ON version.asset_id=asset.asset_id
                   WHERE asset.project_id=%s AND asset.asset_type IN (
                     'quality_score_report','final_release_gate_report','narrative_runtime_measurement',
                     'execution_commit_manifest','model_call_log')""", [project_id],
            )
            artifacts = cursor.fetchall()
            reports = {kind: (ref, value) for kind, ref, value in artifacts}
            quality_ref, quality = reports["quality_score_report"]
            self.assertTrue(quality["fixture"])
            self.assertEqual(quality["gate"], "PASSED_WITH_UNCALIBRATED")
            final_gate = reports["final_release_gate_report"][1]
            self.assertEqual(final_gate["gate"], "PASSED")
            self.assertEqual(final_gate["accepted_asset_version_ids"]["quality"], quality_ref)
            self.assertEqual(final_gate["release_status"], "INTERNAL_RELEASE_FINALIZED")
            self.assertFalse(final_gate["external_publish_permitted"])
            commits = [value for kind, _, value in artifacts if kind == "execution_commit_manifest"]
            self.assertEqual(len(commits), 12)
            self.assertTrue(all(value["validation_manifest_ref"] for value in commits))
            model_logs = [value for kind, _, value in artifacts if kind == "model_call_log"]
            self.assertEqual(len(model_logs), 12)
            self.assertTrue(all(not value["provider_evidence"]["real_model_call"] for value in model_logs))
            measurement = reports["narrative_runtime_measurement"][1]
            self.assertEqual(measurement["proof_status"], "MEASURED_NOT_QUALIFIED")
            self.assertEqual(measurement["metrics"]["provider_call_count"], 12)
            self.assertEqual(set(measurement["evidence"]["provider_external_effect_ids"]), {
                value["external_effect_id"] for value in model_logs
            })
        self.assertEqual(router.registry.observations(
            project_id=project_id, task_type="draft", candidate=candidate,
        ), [])

    def test_context_semantic_subeffects_use_frozen_pack_and_durable_kernel_replay(self, *, routed=False) -> None:
        from unittest.mock import patch

        from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
        from novel_forge.modules.chapter_authority.handlers import _ContextHandler
        from novel_forge.modules.context_builder.domain import replay_context_bundle
        from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness

        harness = CapabilityPackPostgresHarness("context-semantic-subeffects", release_sha="e" * 40)
        approved = harness.register_compile_approve(
            "1.0.0", generation=1,
            approval_scope=harness.approval_scope(environments=("test",), runtime_profiles=("test",)),
            target_runtime_profile="test",
        )
        harness.register_agents(approved.compiled)
        harness.activate(harness.deploy(approved, environment="test", runtime_profile="test"), environment="test")
        project_id = harness.project_id
        semantic_dispatches = []
        semantic_results = []
        original_context_execute = _ContextHandler.execute

        def fixture(stage, inputs):
            if stage in {"context_compress", "context_fidelity"}:
                semantic_dispatches.append(stage)
            output = default_chapter_fixture_response(stage, inputs)
            if stage in {"review", "rereview"}:
                text = inputs["draft" if stage == "review" else "revision"]["text"]
                quote = text if stage == "review" else "The protagonist gives up the only safe route home before the witnesses leave."
                start = text.index(quote)
                output["knowledge_checks"] = [{
                    "knowledge_card_asset_version_id": item["knowledge_card_asset_version_id"],
                    "status": "MISAPPLIED" if stage == "review" else "VERIFIED_IN_PROSE",
                    "reason": "Fixture checks the witnessed loss of the safe route.",
                    "evidence": {"start": start, "end": start + len(quote), "quote": quote},
                    "conditions_checked": ["Public choice costs a concrete safe option."],
                    "exceptions_checked": [],
                    "issue_codes": ["COST_NOT_CONCRETE"] if stage == "review" else [],
                } for item in inputs.get("knowledge_review_targets", [])]
            return output

        def execute_with_semantic_subeffects(handler, request):
            plan = request.require_input("chapter_plan")
            memo = request.require_input("chapter_memo")
            task = {
                "contract_version": "task-context-compression.v1",
                "policy_version": "task-scoped-context.v1",
                "accepted_boundary": dict(memo.content["accepted_boundary"]),
                "memo_fingerprint": memo.content["memo_fingerprint"],
                "task": {"chapter": 1, "goal": plan.content["chapter_objective"]},
                "target_tokens": 6000,
                "required_unit_ids": ["unit:objective"],
                "units": [{"unit_id": "unit:objective", "text": plan.content["chapter_objective"], "required": True, "kind": "task_fact"}],
                "source_binding": {"asset_version_id": plan.asset_version_id, "content_hash": plan.content_hash},
                "chunk_index": 0,
            }
            for stage in ("context_compress", "context_fidelity"):
                stage_task = dict(task)
                if stage == "context_fidelity":
                    stage_task["selected_unit_ids"] = ["unit:objective"]
                instance = hashlib.sha256(json.dumps({"stage": stage, "task": stage_task}, sort_keys=True).encode()).hexdigest()
                frozen_request = replace(request, command={**request.command, "_effect_instance": instance, "_context_compression_task": stage_task})
                payload = {"chapter_plan": plan.content, "context_compression_task": stage_task}
                first = handler.provider.invoke(frozen_request, stage=stage, payload=payload)
                recovered = handler.provider.invoke(frozen_request, stage=stage, payload=payload)
                self.assertEqual(first.output, recovered.output)
                self.assertEqual(first.execution_evidence["execution_request"]["external_effect_id"], recovered.execution_evidence["execution_request"]["external_effect_id"])
                self.assertEqual(first.execution_evidence["route_snapshot"]["reasoning_effort"], "high")
                adapter_routes = handler.provider.adapter.routes
                binder_routes = handler.provider.capability_binder.routes
                original_adapter_route, original_binder_route = adapter_routes[stage], binder_routes[stage]
                try:
                    for output_limit in (128, 0):
                        adapter_routes[stage] = replace(original_adapter_route, model_output_limit=output_limit)
                        binder_routes[stage] = replace(original_binder_route, model_output_limit=output_limit)
                        with patch("novel_forge.modules.chapter_authority.context_compression_provider.task_provider_output_reserve", side_effect=AssertionError("successful frozen effects must not recompute current capacity")):
                            capacity_recovered = handler.provider.invoke(frozen_request, stage=stage, payload=payload)
                        self.assertEqual(capacity_recovered.output, first.output)
                        self.assertEqual(capacity_recovered.execution_evidence, first.execution_evidence)
                finally:
                    adapter_routes[stage], binder_routes[stage] = original_adapter_route, original_binder_route
                semantic_results.append(first)
                with self.assertRaises(KernelError) as fence_error:
                    handler.provider.invoke(replace(frozen_request, fencing_token=0), stage=stage, payload=payload)
                self.assertEqual(fence_error.exception.code, "MODEL_EFFECT_EXECUTION_IDENTITY_INVALID")
                changed = {**payload, "context_compression_task": {**stage_task, "units": [{**stage_task["units"][0], "text": "A different source version must not reuse this effect."}]}}
                with self.assertRaises(KernelError) as drift_error:
                    handler.provider.invoke(frozen_request, stage=stage, payload=changed)
                self.assertEqual(drift_error.exception.code, "MODEL_EFFECT_INTENT_DRIFT")
                with self.assertRaises(KernelError) as source_drift:
                    handler.provider.invoke(replace(frozen_request, inputs=tuple(
                        replace(item, content_hash="changed-source-version-hash") if item.asset_version_id == plan.asset_version_id else item
                        for item in frozen_request.inputs
                    )), stage=stage, payload=payload)
                self.assertEqual(source_drift.exception.code, "CONTEXT_COMPRESSION_SOURCE_DRIFT")
            return original_context_execute(handler, request)

        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(root=Path(directory), database_url=DATABASE_URL)
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": harness.pack_id,
                "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(Path(directory) / "objects"),
                "NOVEL_FORGE_ENABLE_SYNCHRONOUS_AUTHORITY_FIXTURE": "true",
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
                "NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT": "262144",
            }
            execution = build_production_execution_composition(settings, env=env, chapter_fixture_factory=fixture)
            if routed:
                from tests.integration.quality_context_routed_support import attach_mock_qualified_router

                attach_mock_qualified_router(execution, DATABASE_URL)
            application = build_chapter_authority_application(settings, execution=execution, env=env)
            history = {
                "asset_version_id": f"{project_id}:episodic-context-source-v1",
                "asset_type": "chapter_episodic_summary", "project_id": project_id,
                "safe_summary": "\n\n".join(
                    f"Scene {index}: " + "The market crowd debates which route may remain open after the public oath; distant vendors argue over coins and weather. " * 3
                    for index in range(120)
                ),
                "structured_facts": [{"key": "witnessed_promise", "value": "The public promise requires an observable irreversible cost.", "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1"}],
                "estimated_tokens": 20_000, "narrative_function": "related_episodic_history",
                "context_class": "RETRIEVABLE", "compression_method": "none",
                "source_use_mode": "generation", "allowed_use": "generation",
                "retrieval_reasons": ["task_related_episodic_history"],
            }
            from tests.integration.quality_context_state_fixture import current_state_inputs

            compiled_style_inputs = current_state_inputs(project_id, ())
            candidates = self._release_evidence(
                project_id, with_mkaos=True, scope_preseeded=True, workspace_id=harness.workspace_id,
                extra_context_candidates=(history,
                    *compiled_style_inputs, *(
                    {"asset_version_id": f"{project_id}:{kind}:genesis", "asset_type": kind,
                     "project_id": project_id, "safe_summary": "Explicit fixture genesis boundary",
                     "structured_facts": [], "estimated_tokens": 20, "narrative_function": "accepted_boundary"}
                    for kind in ("story_state_snapshot", "canon_snapshot")
                )),
            )
            self._seed_intrinsic_semantic_commit_policy(project_id)
            with patch.object(_ContextHandler, "execute", execute_with_semantic_subeffects):
                with self.assertRaises(KernelError) as unresolved:
                    application.run(SingleChapterRequest(
                    project_id=project_id, workspace_id=harness.workspace_id, actor_id="context-semantic-worker",
                    chapter=1, title="An Extracted Promise", premise="A public promise becomes irreversible.",
                    trace_id=identifier("trace"), correlation_id=identifier("correlation"),
                    application_build_id="context-semantic-test", commit_sha="e" * 40,
                    context_candidates=candidates, context_token_budget=32_768,
                    context_version_refs={"story_state_snapshot_version": f"{project_id}:story_state_snapshot:genesis",
                                          "canon_snapshot_version": f"{project_id}:canon_snapshot:genesis"},
                    preparation_report={"stage_context_profile_versions": {"draft": "draft-context-profile-v4"}},
                    ))
                self.assertEqual(unresolved.exception.code, "CHAPTER_QUALITY_GATE_BLOCKED")
        self.assertEqual(semantic_dispatches, ["context_compress", "context_fidelity"] * 2)
        self.assertEqual(len(semantic_results), 2)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT version.content
                FROM authority_operation_output_asset AS output
                JOIN authority_asset_version AS version ON version.asset_version_id = output.asset_version_id
                JOIN authority_operation AS operation ON operation.operation_id = output.operation_id
                WHERE operation.project_id = %s AND output.output_key = 'chapter.context'
            """, [project_id])
            context = cursor.fetchone()[0]
            self.assertEqual(replay_context_bundle(context)["status"], "MATCH")
            task_receipt = context["task_context_receipt"]
            self.assertGreater(task_receipt["before_estimated_tokens"], context["token_budget"])
            self.assertLessEqual(task_receipt["after_estimated_tokens"], context["token_budget"])
            self.assertEqual(len(task_receipt["compression_trace"]), 1)
            self.assertEqual(task_receipt["compression_trace"][0]["source_asset_version_id"], history["asset_version_id"])
            self.assertTrue(task_receipt["compression_trace"][0]["model_execution_evidence"])
            cursor.execute("SELECT content, content_hash FROM authority_asset_version WHERE asset_version_id = %s", [history["asset_version_id"]])
            original_source, source_hash = cursor.fetchone()
            self.assertEqual(original_source["safe_summary"], history["safe_summary"])
            self.assertEqual(task_receipt["compression_trace"][0]["source_content_hash"], source_hash)
            projected_history = next(item for item in context["stage_context_view"]["segments"] if item["asset_version_id"] == history["asset_version_id"])
            self.assertEqual(projected_history["structured_facts"], history["structured_facts"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT effect.capability, effect.status, effect.request_payload,
                       reservation.estimated_tokens
                FROM authority_external_effect AS effect
                JOIN authority_budget_reservation AS reservation
                  ON reservation.external_effect_id = effect.external_effect_id
                WHERE effect.project_id = %s
                  AND effect.capability IN ('model.context_compress', 'model.context_fidelity')
                ORDER BY effect.capability
            """, [project_id])
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 4)
            for capability, status, frozen, reserved in rows:
                self.assertEqual(status, "SUCCEEDED")
                runtime = frozen["_production_execution"]["capability_runtime"]
                self.assertTrue(runtime["materialization_hash"])
                self.assertEqual(runtime["provider_admission"]["total_reserved"], reserved)
                self.assertLess(reserved, 512_000)
                self.assertGreater(reserved, frozen["max_output_tokens"])
                self.assertLessEqual(frozen["max_output_tokens"], 4096 if capability.endswith("compress") else 2048)
                self.assertEqual(runtime["pack_ref"], f"{harness.pack_id}@1.0.0")
                if routed:
                    self.assertEqual(runtime["routing_decision"]["status"], "SELECTED")
                    self.assertEqual(runtime["routing_decision"]["policy"]["quality_metric"], "DOMAIN_GATE_ACCEPTANCE")
            from novel_forge.modules.authority_handler_runtime.context_feedback import context_gate_outcomes

            cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE project_id=%s AND capability IN ('model.context_compress','model.context_fidelity')", [project_id])
            self.assertEqual(context_gate_outcomes(cursor, project_id=project_id, effect_ids=[row[0] for row in cursor.fetchall()]), {})
            cursor.execute("SELECT count(*) FROM authority_operation WHERE project_id=%s AND definition_name IN ('chapter.draft.generate','chapter.review.evaluate') AND status='SUCCEEDED'", [project_id])
            self.assertEqual(cursor.fetchone()[0], 2)
            cursor.execute("SELECT content->'blocking_dimensions' FROM authority_asset_version JOIN authority_asset USING(asset_id) WHERE project_id=%s AND asset_type='quality_score_report'", [project_id])
            self.assertTrue(cursor.fetchone()[0])

    def test_full_chapter_slice_uses_unified_execution_gateway_and_commit_manifests(
        self,
    ) -> None:
        self._assert_full_chapter_slice_uses_unified_execution_gateway(task_scoped=False)

    def test_task_scoped_fast_path_freezes_replayable_context_without_semantic_io(self) -> None:
        self._assert_full_chapter_slice_uses_unified_execution_gateway(task_scoped=True)

    def _assert_full_chapter_slice_uses_unified_execution_gateway(self, *, task_scoped: bool) -> None:
        from tests.integration.capability_pack_postgres_support import CapabilityPackPostgresHarness
        from novel_forge.modules.context_builder.domain import replay_context_bundle

        harness = CapabilityPackPostgresHarness("gateway-model-slice", release_sha="e" * 40)
        approved = harness.register_compile_approve(
            "1.0.0", generation=1,
            approval_scope=harness.approval_scope(
                environments=("test",), runtime_profiles=("test",)
            ), target_runtime_profile="test",
        )
        harness.register_agents(approved.compiled)
        harness.activate(
            harness.deploy(approved, environment="test", runtime_profile="test"),
            environment="test",
        )
        project_id = harness.project_id
        recovery_execution_id = ""

        def pack_review_fixture(stage, inputs):
            from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response

            output = default_chapter_fixture_response(stage, inputs)
            if stage not in {"review", "rereview"}:
                return output
            text = inputs["draft" if stage == "review" else "revision"]["text"]
            quote = text if stage == "review" else "The protagonist gives up the only safe route home before the witnesses leave."
            start = text.index(quote)
            output["knowledge_checks"] = [{
                "knowledge_card_asset_version_id": item["knowledge_card_asset_version_id"],
                "status": "MISAPPLIED" if stage == "review" else "VERIFIED_IN_PROSE",
                "reason": "Fixture checks whether the public choice names an actual lost option.",
                "evidence": {"start": start, "end": start + len(quote), "quote": quote},
                "conditions_checked": ["Public choice costs a concrete safe option."],
                "exceptions_checked": [],
                "issue_codes": ["COST_NOT_CONCRETE"] if stage == "review" else [],
            } for item in inputs.get("knowledge_review_targets", [])]
            return output
        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(
                root=Path(directory), database_url=DATABASE_URL
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": harness.pack_id,
                "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                    Path(directory) / "objects"
                ),
                "NOVEL_FORGE_ENABLE_SYNCHRONOUS_AUTHORITY_FIXTURE": "true",
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
                "NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT": "262144",
            }
            execution = build_production_execution_composition(settings, env=env, chapter_fixture_factory=pack_review_fixture)
            application = build_chapter_authority_application(
                settings, execution=execution, env=env
            )
            context_candidates = self._release_evidence(project_id, with_mkaos=True, scope_preseeded=True, workspace_id=harness.workspace_id)
            self._seed_intrinsic_semantic_commit_policy(project_id)
            chapter_request = SingleChapterRequest(
                project_id=project_id,
                workspace_id=harness.workspace_id,
                actor_id="chapter-gateway-worker",
                chapter=1,
                title="A Visible Gateway Cost",
                premise="A gateway-bound public promise becomes irreversible.",
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                application_build_id="chapter-gateway-test",
                commit_sha="e" * 40,
                context_candidates=context_candidates,
                context_token_budget=64_000,
                **({"preparation_report": {"stage_context_profile_versions": {"draft": "draft-context-profile-v4"}}}
                   if task_scoped else {}),
            )
            result = application.run(chapter_request)

            self.assertEqual(result.root_status, "SUCCEEDED")
            self.assertEqual(result.saga_status, "SUCCEEDED")
            self.assertTrue(execution.gateway.production_execution_gateway_backed)
            export_version = result.outputs[ChapterNode.EXPORT].asset_version_id
            exported = (
                Path(directory) / "objects"
                / f"chapters/{project_id}/1/versions/{export_version}/chapter.txt"
            )
            self.assertIn("only safe route home", exported.read_text())

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT version.content
                FROM authority_operation_output_asset AS output
                JOIN authority_asset_version AS version ON version.asset_version_id = output.asset_version_id
                JOIN authority_operation AS operation ON operation.operation_id = output.operation_id
                WHERE operation.project_id = %s AND output.output_key = 'chapter.context'
            """, [project_id])
            context = cursor.fetchone()[0]
            self.assertEqual(replay_context_bundle(context)["status"], "MATCH")
            if task_scoped:
                self.assertTrue(context["task_context_receipt"]["fast_path"])
                self.assertEqual(context["task_context_receipt"]["compression_trace"], [])
            cursor.execute(
                """
                SELECT capability, status, COUNT(*)
                FROM authority_external_effect
                WHERE project_id = %s AND provider = 'production_execution_gateway'
                GROUP BY capability, status
                ORDER BY capability
                """,
                [project_id],
            )
            rows = cursor.fetchall()
            self.assertEqual(sum(int(row[2]) for row in rows), 12)
            self.assertTrue(all(row[1] == "SUCCEEDED" for row in rows))
            self.assertIn(("model.rereview", "SUCCEEDED", 1), rows)
            self.assertIn(("model.memo", "SUCCEEDED", 1), rows)
            self.assertIn(("model.canon_support", "SUCCEEDED", 1), rows)
            cursor.execute(
                """
                SELECT asset.asset_type, COUNT(DISTINCT version.asset_version_id)
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version ON version.asset_id = asset.asset_id
                WHERE asset.project_id = %s
                  AND asset.asset_type IN (
                    'route_snapshot', 'input_manifest', 'execution_commit_manifest',
                    'prompt_bundle', 'skill_bundle',
                    'execution_context_policy', 'execution_source_policy',
                    'execution_validation_policy', 'execution_commit_policy'
                  )
                  AND version.lifecycle = 'ACTIVE'
                GROUP BY asset.asset_type
                """,
                [project_id],
            )
            counts = dict(cursor.fetchall())
            self.assertEqual(counts["route_snapshot"], 12)
            self.assertEqual(counts["input_manifest"], 12)
            self.assertEqual(counts["execution_commit_manifest"], 12)
            self.assertEqual(counts["prompt_bundle"], 12)
            self.assertEqual(counts["skill_bundle"], 12)
            self.assertEqual(counts["execution_context_policy"], 12)
            self.assertEqual(counts["execution_source_policy"], 8)
            self.assertEqual(counts["execution_validation_policy"], 12)
            # Twelve stage-local immutable snapshots coexist with the governing
            # policy already frozen by planning semantic evaluation.
            self.assertEqual(counts["execution_commit_policy"], 13)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_asset_locator
                WHERE project_id = %s
                  AND logical_ref LIKE 'production_execution/commit_policies/%%'
                """,
                [project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 12)
            cursor.execute(
                """
                SELECT version.content -> 'contract' ->> 'candidate_asset_type'
                FROM authority_asset_locator AS locator
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = locator.current_asset_version_id
                WHERE locator.project_id = %s
                  AND locator.logical_ref = 'commit:quality-intrinsic-judge:v1'
                """,
                [project_id],
            )
            self.assertEqual(
                cursor.fetchone()[0],
                "narrative_semantic_evaluation_candidate",
            )
            cursor.execute(
                """
                SELECT BOOL_AND(
                    version.content ->> 'validation_manifest_ref'
                    LIKE 'authority-asset-version:%%'
                )
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id = asset.asset_id
                WHERE asset.project_id = %s
                  AND asset.asset_type = 'execution_commit_manifest'
                  AND version.lifecycle = 'ACTIVE'
                """,
                [project_id],
            )
            self.assertTrue(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT COUNT(DISTINCT attempt.attempt_id),
                       COUNT(DISTINCT lease.lease_id),
                       COUNT(DISTINCT effect.external_effect_id),
                       COUNT(DISTINCT budget.reservation_id),
                       COUNT(DISTINCT receipt.external_receipt_id)
                FROM authority_external_effect AS effect
                JOIN authority_operation AS operation
                  ON operation.operation_id = effect.operation_id
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id = operation.operation_id
                JOIN authority_lease_acquisition AS lease
                  ON lease.attempt_id = attempt.attempt_id
                JOIN authority_budget_reservation AS budget
                  ON budget.external_effect_id = effect.external_effect_id
                JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id = effect.external_effect_id
                JOIN authority_external_receipt AS receipt
                  ON receipt.dispatch_id = dispatch.dispatch_id
                WHERE effect.project_id = %s
                  AND effect.provider = 'production_execution_gateway'
                """,
                [project_id],
            )
            self.assertEqual(cursor.fetchone(), (12, 12, 12, 12, 12))
            cursor.execute(
                """
                SELECT asset.asset_type, COUNT(DISTINCT version.asset_version_id)
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = binding.asset_version_id
                WHERE operation.root_operation_id = %s
                  AND asset.asset_type IN ('model_call_log', 'cost_ledger')
                GROUP BY asset.asset_type
                """,
                [result.root_operation_id],
            )
            self.assertEqual(
                dict(cursor.fetchall()),
                {"cost_ledger": 12, "model_call_log": 12},
            )
            cursor.execute(
                """
                SELECT version.content
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset ON asset.asset_id=binding.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=binding.operation_id
                WHERE operation.root_operation_id=%s
                  AND asset.asset_type='narrative_runtime_measurement'
                """,
                [result.root_operation_id],
            )
            measurement = dict(cursor.fetchone()[0])
            self.assertEqual(
                measurement["observations"]["provider_usage"]["status"],
                "MEASURED",
            )
            self.assertEqual(
                measurement["observations"]["provider_trace"]["status"],
                "MEASURED",
            )
            self.assertEqual(
                measurement["observations"]["provider_usage_receipt"]["status"],
                "MEASURED",
            )
            self.assertEqual(
                measurement["observations"]["provider_cost_receipt"]["status"],
                "MEASURED",
            )
            self.assertEqual(
                measurement["observations"]["provider_tokens"]["status"],
                "MEASURED",
            )
            self.assertEqual(
                measurement["observations"]["provider_cost"]["status"],
                "MEASURED",
            )
            self.assertEqual(measurement["metrics"]["provider_call_count"], 12)
            self.assertEqual(measurement["metrics"]["provider_token_count"], 0)
            self.assertEqual(measurement["metrics"]["provider_cost"], 0.0)
            self.assertEqual(measurement["metrics"]["provider_trace_missing_count"], 0)
            self.assertEqual(
                measurement["observations"]["planning"]["status"], "MEASURED"
            )
            self.assertEqual(measurement["metrics"]["planning_drift_count"], 0)
            self.assertEqual(
                measurement["observations"]["mkaos_consumption"]["status"],
                "MEASURED",
            )
            self.assertEqual(measurement["metrics"]["mkaos_consumption_count"], 1)
            cursor.execute(
                """
                SELECT COUNT(*),
                       BOOL_AND(
                         (version.content -> 'record' -> 'result' ->> 'normalized_output_ref') <> ''
                         AND (version.content -> 'record' -> 'result' ->> 'validation_report_ref') <> ''
                         AND (version.content -> 'record' -> 'result' ->> 'usage_receipt_ref') <> ''
                         AND (version.content -> 'record' -> 'result' ->> 'cost_receipt_ref') <> ''
                       )
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id = asset.asset_id
                WHERE asset.project_id = %s
                  AND asset.asset_type = 'execution_recovery_session'
                  AND version.lifecycle = 'ACTIVE'
                """,
                [project_id],
            )
            self.assertEqual(cursor.fetchone(), (12, True))
            cursor.execute(
                """
                SELECT version.content ->> 'execution_id'
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id = asset.asset_id
                WHERE asset.project_id = %s
                  AND asset.asset_type = 'execution_recovery_session'
                  AND version.lifecycle = 'ACTIVE'
                ORDER BY version.created_at
                LIMIT 1
                """,
                [project_id],
            )
            recovery_execution_id = str(cursor.fetchone()[0])

        selections = MkaosAuthorityQuery(DATABASE_URL).list_runtime_selections(
            project_id=project_id
        )
        usage = MkaosAuthorityQuery(DATABASE_URL).list_runtime_usage(
            project_id=project_id
        )
        self.assertEqual(len(selections), 1)
        self.assertEqual(len(usage), 11)
        self.assertTrue(all(item["delivery_evidence_class"] == "FIXTURE_PROTOCOL_RECEIPT"
                            and item["real_model_call"] is False
                            and item["capability_materialization_asset_version_id"]
                            and item["provider_context_view_hash"] for item in usage))
        self.assertEqual(MkaosAuthorityQuery(DATABASE_URL).list_runtime_usage(
            project_id=project_id, knowledge_card_asset_version_id="unrelated-card", limit=1,
        ), [])
        self.assertEqual(MkaosAuthorityQuery(DATABASE_URL).list_runtime_usage(
            project_id=project_id, book_id="another-book", limit=1,
        ), [])
        query = MkaosAuthorityQuery(DATABASE_URL)
        first = usage[0]
        self.assertEqual(query.list_runtime_usage(
            project_id=project_id,
            knowledge_card_asset_version_id=first["knowledge_card_asset_version_id"],
            target_capability_id=first["target_capability_id"],
            result_asset_version_id=first["result_asset_version_id"],
            limit=1,
        ), [first])
        self.assertEqual(query.list_runtime_usage(
            project_id=project_id, target_capability_id="unrelated-capability",
        ), [])
        self.assertEqual(query.list_runtime_selections(
            project_id=project_id,
            knowledge_card_asset_version_id=first["knowledge_card_asset_version_id"],
            target_capability_id=first["target_capability_id"],
            limit=1,
        ), selections)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT a.asset_type, v.content #>> '{knowledge_checks,0,usage_role}',
                          v.content #>> '{knowledge_checks,0,status}'
                FROM authority_asset a JOIN authority_asset_version v ON v.asset_id=a.asset_id
                WHERE a.project_id=%s AND a.asset_type IN ('review_report','re_review_report')""",
                [project_id],
            )
            self.assertEqual(set(cursor.fetchall()), {
                ("review_report", "CONSTRAINT", "MISAPPLIED"),
                ("re_review_report", "CONSTRAINT", "VERIFIED_IN_PROSE"),
            })
        self.assertTrue(all(item["capability_id"] != "model.memo" for item in usage))
        self.assertTrue(all(item["attempt_id"] for item in usage))
        self.assertTrue(all(item["external_effect_id"] for item in usage))
        self.assertTrue(
            all(item["capability_id"].startswith("model.") for item in usage)
        )
        self.assertTrue(all("capability_pack_snapshot_id" in item for item in usage))
        self.assertTrue(all(item["result_asset_version_id"] for item in usage))
        self.assertEqual(
            len(usage),
            len(
                {
                    (
                        item["external_effect_id"],
                        item["knowledge_card_asset_version_id"],
                        item["result_asset_version_id"],
                    )
                    for item in usage
                }
            ),
        )
        self.assertEqual(
            MkaosAuthorityQuery(DATABASE_URL).list_runtime_usage(project_id=project_id),
            usage,
        )

        recovered = AuthorityExecutionRecoveryStore(
            DATABASE_URL,
            project_id=project_id,
        ).load_session(recovery_execution_id)
        self.assertEqual(recovered.result.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertEqual(recovered.request.project_id, project_id)


if __name__ == "__main__":
    unittest.main()
