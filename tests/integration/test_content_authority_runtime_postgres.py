from __future__ import annotations

import hashlib
import json
import unittest

from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS
from novel_forge.modules.content_authority import CONTENT_CODECS
from novel_forge.modules.content_authority.application import (
    ContentAuthorityApplication,
    ContentOperationRequest,
)
from novel_forge.modules.reader_calibration import BLIND_EVALUATION_DIMENSIONS
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)


class ContentAuthorityRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("content-project")
        self.counter = 0
        self.app = ContentAuthorityApplication(
            DATABASE_URL,
            application_build_id="content-authority-integration",
            commit_sha="d" * 40,
            integration_proven=CONTENT_CODECS,
        )

    def seed(self, asset_type: str, content: dict, label: str):
        asset_version_id = f"{self.project_id}:{label}:v1"
        asset_id = f"{self.project_id}:{label}"
        content_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                [asset_id, self.project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version (
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                """,
                [asset_version_id, asset_id, json.dumps(content), content_hash],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification (
                    qualification_id, asset_version_id, policy_version, decision, evidence
                ) VALUES (%s, %s, 'content-fixture-v1', 'ELIGIBLE', '{}'::jsonb)
                """,
                [f"{asset_version_id}:qualification", asset_version_id],
            )
            uow.commit()
        return {"asset_version_id": asset_version_id, "content_hash": content_hash}

    def run_op(self, name: str, inputs=(), payload=None, approval=None):
        self.counter += 1
        result = self.app.execute(
            ContentOperationRequest(
                definition_name=name,
                project_id=self.project_id,
                workspace_id=f"workspace:{self.project_id}",
                actor_id="content-operator",
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
                idempotency_key=f"{self.project_id}:{name}:{self.counter}",
                payload=payload or {},
                input_assets=tuple(inputs),
                approval=approval,
            )
        )
        return {
            "asset_version_id": result.asset_version_id,
            "content_hash": result.content_hash,
        }

    def read_content(self, asset_version_id: str) -> dict:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        self.assertIsNotNone(row)
        return dict(row[0])

    def test_unrelated_historical_definition_drift_does_not_block_brief(self) -> None:
        from copy import deepcopy
        from unittest.mock import patch
        from novel_forge.modules.content_authority.definitions import content_operation_definitions
        from novel_forge.storage.authority_repositories import definition_hash

        definitions = content_operation_definitions(application_build_id="test", commit_sha="d" * 40)
        historical = deepcopy(definitions[0])
        historical["name"] = identifier("unrelated-historical-content")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(historical)
            uow.commit()
        drifted = deepcopy(historical)
        drifted["policy"] = {**drifted["policy"], "unrelated_changed_contract": True}
        brief = {"creative_brief_contract_version": "creative-brief-v2",
                 "idea": "A witness must choose whether to reveal a costly truth.",
                 "genre": "fantasy", "audience": "adult",
                 "constraints": ["Original characters"], "source_boundaries": ["No source text"]}
        with patch("novel_forge.modules.content_authority.application.content_operation_definitions",
                   return_value=(*definitions, drifted)):
            result = self.run_op("creative.brief.create", payload={"brief": brief})
        self.assertEqual(self.read_content(result["asset_version_id"])["idea"], brief["idea"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT definition_hash FROM authority_operation_definition WHERE name=%s AND definition_version=%s",
                               [historical["name"], historical["definition_version"]])
            self.assertEqual(uow.cursor.fetchone()[0], definition_hash(historical))

    def test_all_registered_codecs_execute_through_postgresql_authority(self) -> None:
        brief_payload = {
            "target_genre": "fantasy",
            "subgenre": "mystery",
            "target_platform": "serial",
            "target_audience": "adult",
            "reading_promise": "costly public choices",
            "core_fantasy": "truth changes power",
            "core_conflict": "truth versus safety",
            "protagonist_mechanism": "auditable memory",
            "antagonist_mechanism": "institutional erasure",
            "world_novelty": "records alter reality",
            "emotional_engine": "loyalty under evidence",
            "pleasure_engine": "clever reversals",
            "suspense_engine": "missing records",
            "theme_question": "When safety requires betrayal, is loyalty still worth its cost?",
            "serialization_strategy": "case arcs",
            "prohibited_elements": ["copying"],
            "source_boundaries": ["abstract_only"],
            "quality_targets": {"review": 80},
        }
        brief = self.run_op("creative.brief.create", payload={"brief": brief_payload})
        fingerprint = {
            "protagonist_advantage_mechanism": "auditable memory",
            "conflict_loop": "record versus erasure",
            "growth_loop": "trust through costly proof",
            "reward_loop": "restore a hidden fact",
            "information_asymmetry": "institutions know deletions",
            "world_constraint": "records require sacrifice",
            "relationship_engine": "mutual audit",
            "antagonist_response_pattern": "rewrite procedure",
            "chapter_payoff_pattern": "public proof with private cost",
        }
        scores = {
            "novelty": 0.8,
            "genre_fit": 0.8,
            "platform_fit": 0.8,
            "conflict_sustainability": 0.8,
            "longform_capacity": 0.8,
            "protagonist_agency": 0.8,
            "antagonist_pressure": 0.8,
            "pleasure_potential": 0.8,
            "suspense_potential": 0.8,
            "theme_potential": 0.8,
            "serialization_potential": 0.8,
            "similarity_risk": 0.1,
            "production_difficulty": 0.2,
        }
        generation_receipt = self.seed(
            "creative_candidate_generation_receipt",
            {
                "provider": "scripted_creative_fixture",
                "model": "fixture",
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
                "candidates": [
                    {
                        "candidate_id": f"generated-{index}",
                        "fingerprint": {
                            **fingerprint,
                            "conflict_loop": f"mechanism-conflict-{index}",
                        },
                    }
                    for index in range(3)
                ],
            },
            "creative-generation-receipt",
        )
        self.run_op("creative.candidates.generate", [brief, generation_receipt])
        candidate1 = self.seed(
            "creative_candidate",
            {
                "project_id": self.project_id,
                "candidate_id": "c1",
                "fingerprint": fingerprint,
                "scores": scores,
                "known_risks": [],
            },
            "candidate-1",
        )
        candidate2 = self.seed(
            "creative_candidate",
            {
                "project_id": self.project_id,
                "candidate_id": "c2",
                "fingerprint": {
                    **fingerprint,
                    "conflict_loop": "witness versus archive",
                },
                "scores": scores,
                "known_risks": [],
            },
            "candidate-2",
        )
        evaluation1 = self.run_op("creative.candidates.evaluate", [brief, candidate1])
        evaluation2 = self.run_op("creative.candidates.evaluate", [brief, candidate2])
        self.run_op(
            "creative.candidates.cluster",
            [evaluation1, evaluation2],
            {"threshold": 0.7},
        )
        self.run_op(
            "creative.project.approve",
            [brief, evaluation1, evaluation2],
            approval={"status": "APPROVED", "project_id": self.project_id},
        )

        rules = [
            {
                "rule_key": "memory_cost",
                "rule": "restoring a record costs a memory",
                "scope": "archive",
                "cost": "one personal memory",
                "exception": "none",
                "observable_consequence": "name loss",
                "narrative_function": "force costly proof",
                "conflict_potential": "high",
                "failure_mode": "identity erosion",
                "canon_policy": "append_only",
            }
        ]
        world = self.run_op(
            "production.world.generate",
            [brief],
            {
                "rules": rules,
                "entities": {
                    "world_premise": [{"name": "Archive City"}],
                    "factions": [],
                    "institutions": [],
                    "locations": [],
                    "resources": [],
                    "systems": [],
                    "economy": [],
                    "social_hierarchy": [],
                    "information_boundaries": [],
                    "historical_events": [],
                    "conflict_sources": [],
                    "daily_life_impacts": [],
                },
            },
        )
        self.run_op("world.validate", [world])
        consequence_receipt = self.seed(
            "world_consequence_provider_receipt",
            {
                "provider_id": "scripted-world-fixture",
                "model_id": "fixture",
                "prompt_version": "world-consequence-fixture-v1",
                "real_model_call": False,
                "consequences": [
                    {
                        "consequence_id": "consequence:memory-tax",
                        "rule_id": "memory_cost",
                        "direct_consequence": "Restoration becomes rationed.",
                        "affected_groups": ["clerks"],
                    }
                ],
            },
            "world-consequence-receipt",
        )
        world_consequence = self.run_op(
            "world.consequence.materialize_candidate",
            [world, consequence_receipt],
        )
        consequence_content = self.read_content(world_consequence["asset_version_id"])
        self.assertEqual(consequence_content["status"], "CANDIDATE")
        self.assertFalse(consequence_content["accepted_canon"])
        self.assertEqual(
            consequence_content["activation_requirement"],
            "STORY_DESIGN_AUTHORITY_DECISION",
        )
        self.assertEqual(
            consequence_content["affected_group_node_ids"],
            ["affected_group:clerks"],
        )
        consequence_node_ids = {
            item["node_id"] for item in consequence_content["nodes"]
        }
        self.assertTrue(
            all(
                edge["source_id"] in consequence_node_ids
                and edge["target_id"] in consequence_node_ids
                for edge in consequence_content["edges"]
            )
        )
        theme_question = self.run_op(
            "theme.question.create",
            payload={"question": brief_payload["theme_question"]},
        )
        character_fields = {
            "project_id": self.project_id,
            "desire": "restore truth",
            "need": "trust others",
            "fear": "self-erasure",
            "wound": "a deleted family",
            "false_belief": "proof is enough",
            "value_hierarchy": ["truth", "loyalty"],
            "moral_boundary": "never erase another",
            "capability": "audit records",
            "capability_cost": "memory loss",
            "weakness": "solitary",
            "agency": "chooses cases",
            "voice": "precise",
            "public_identity": "clerk",
            "private_identity": "survivor",
            "secret": "altered record",
            "relationship_goals": ["earn trust"],
            "conflict_style": "document first",
            "growth_arc": "proof to solidarity",
            "failure_arc": "becomes eraser",
            "reader_charm_mechanism": "pays costs first",
        }
        character1 = self.run_op(
            "production.character.generate",
            [brief, world, theme_question],
            {"profile": {**character_fields, "character_id": "hero"}},
        )
        character2 = self.run_op(
            "production.character.generate",
            [brief, world, theme_question],
            {
                "profile": {
                    **character_fields,
                    "character_id": "ally",
                    "public_identity": "witness",
                }
            },
        )
        self.run_op(
            "character.relationships.generate",
            [character1, character2],
            {
                "state": {
                    "relationship_edge": "allies",
                    "power_relation": "balanced",
                    "trust_state": "fragile",
                    "debt": "shared proof",
                    "dependency": "mutual witness",
                    "hidden_conflict": "different costs",
                    "relationship_arc": "audit to trust",
                }
            },
        )
        value_conflict = self.seed(
            "value_conflict",
            {
                "conflicting_values": ["safety", "loyalty"],
                "character_initial_position": "safety first",
                "pressure_event": "ally accused",
                "choice": "testify",
                "immediate_cost": "job loss",
                "longterm_cost": "exile",
                "relationship_consequence": "trust gained",
                "world_consequence": "record reopened",
                "belief_change": "loyalty needs action",
                "unresolved_tension": "family risk",
            },
            "value-conflict",
        )
        self.run_op("theme.arc.build", [theme_question, value_conflict])
        draft = self.seed(
            "draft_version", {"text": "The clerk chooses and pays."}, "draft"
        )
        anti_evidence = self.seed(
            "anti_preaching_evidence", {"passages": []}, "anti-evidence"
        )
        self.run_op("theme.anti_preaching.evaluate", [draft, anti_evidence])

        ending_intent = self.seed(
            "ending_intent", {"intent": "costly truth"}, "ending-intent"
        )
        closure = self.run_op(
            "ending.closure.plan",
            [ending_intent],
            {
                "plan": {
                    "main_problem_resolution": "restore the archive",
                    "protagonist_final_choice": "publish the record",
                    "protagonist_cost": "loses the final family memory",
                    "antagonist_end": "authority removed by evidence",
                    "relationship_closures": ["mutual trust"],
                    "reader_promises": ["truth revealed"],
                    "foreshadow_payoffs": ["missing name"],
                    "open_questions": ["who rebuilds"],
                    "theme_reanswer": "loyalty is chosen through cost",
                    "world_state_change": "public archive",
                    "aftertaste": "hope with loss",
                    "epilogue_policy": "one quiet scene",
                }
            },
        )
        promise = self.seed("promise", {"promise": "truth revealed"}, "promise")
        payoff = self.run_op(
            "ending.payoff_matrix.build",
            [promise],
            {
                "items": [
                    {
                        "type": "promise",
                        "status": "PAID",
                        "asset_version_id": promise["asset_version_id"],
                    }
                ]
            },
        )
        ending_evidence = self.seed("ending_evidence", {}, "ending-evidence")
        self.run_op("ending.quality.evaluate", [closure, payoff, ending_evidence])

        character_state = self.seed(
            "character_state", {"long_term_goal": "restore truth"}, "character-state"
        )
        behavior = self.seed(
            "character_behavior",
            {"implied_goal": "restore truth", "change_evidence": []},
            "behavior",
        )
        motivation = self.run_op(
            "longform.motivation.evaluate", [character_state, behavior]
        )
        entity1 = self.seed(
            "entity_identity",
            {
                "project_id": self.project_id,
                "entity_id": "hero",
                "name": "Arin",
                "aliases": ["Clerk"],
                "entity_type": "character",
            },
            "entity-1",
        )
        entity2 = self.seed(
            "entity_identity",
            {
                "project_id": self.project_id,
                "entity_id": "masked",
                "name": "Clerk",
                "aliases": [],
                "entity_type": "character",
            },
            "entity-2",
        )
        self.run_op("longform.entity_merge.propose", [entity1, entity2])
        foreshadow_state = self.seed(
            "foreshadow_state", {"thread": "missing name"}, "foreshadow"
        )
        foreshadow_evidence = self.seed(
            "foreshadow_payoff_evidence",
            {
                "scores": {
                    "setup_clarity": 0.8,
                    "reader_memory": 0.8,
                    "timing": 0.8,
                    "causal_relevance": 0.8,
                    "surprise": 0.8,
                    "fairness": 0.8,
                    "emotional_payoff": 0.8,
                    "plot_consequence": 0.8,
                    "character_consequence": 0.8,
                    "theme_relevance": 0.8,
                }
            },
            "foreshadow-evidence",
        )
        foreshadow_report = self.run_op(
            "longform.foreshadow_payoff.evaluate",
            [foreshadow_state, foreshadow_evidence],
        )
        world_rule = self.seed(
            "world_rule",
            {
                "rule_key": "memory_cost",
                "scope": "archive",
                "definition": "restoration costs memory",
            },
            "world-rule",
        )
        world_event = self.seed(
            "world_event", {"unpaid_exception": False}, "world-event"
        )
        world_report = self.run_op(
            "longform.world_rule.evaluate", [world_rule, world_event]
        )
        power1 = self.seed(
            "power_state", {"power_tier": 1, "cost": "memory"}, "power-1"
        )
        power2 = self.seed(
            "power_state",
            {
                "power_tier": 2,
                "cost": "memory",
                "change_reasons": ["training"],
                "scale_growth": 2,
            },
            "power-2",
        )
        power_report = self.run_op("longform.power.evaluate", [power1, power2])
        patterns = [
            self.seed(
                "narrative_pattern_fingerprint",
                {
                    "conflict_trigger": "missing record",
                    "antagonist_entry": "procedure",
                    "resolution": f"proof-{index}",
                    "reward": "truth",
                    "misunderstanding": "",
                    "humiliation": "",
                    "chapter_ending": "new cost",
                    "revelation": "record",
                    "character_reaction": "choice",
                },
                f"pattern-{index}",
            )
            for index in range(3)
        ]
        pattern_report = self.run_op(
            "longform.pattern.evaluate", patterns, {"threshold": 3}
        )
        debt_asset = self.seed(
            "narrative_debt",
            {"type": "main_plot", "opened_chapter": 1, "payoff_window_end": 4},
            "debt",
        )
        debt_report = self.run_op(
            "longform.narrative_debt.evaluate", [debt_asset], {"current_chapter": 5}
        )
        recap_inputs = [
            motivation,
            self.seed(
                "relationship_report",
                {"movement": "trust grows"},
                "relationship-report",
            ),
            self.seed("canon_conflict_report", {"issues": []}, "canon-report"),
            world_report,
            power_report,
            foreshadow_report,
            debt_report,
            self.seed("reward_cadence_report", {"cadence": "steady"}, "reward-report"),
            self.seed(
                "antagonist_pressure_report",
                {"pressure": "rising"},
                "antagonist-report",
            ),
            pattern_report,
            self.seed(
                "theme_movement_report",
                {"movement": "choice gains cost"},
                "theme-report",
            ),
            self.seed("quality_score_report", {"trend": "improving"}, "quality-report"),
        ]
        self.run_op(
            "longform.recap.enhance",
            recap_inputs,
            {
                "reports": {
                    "main_plot_progress": "archive reopened",
                    "constraints": ["preserve memory cost"],
                }
            },
        )

        source_document = self.seed(
            "source_document",
            {"title": "Policy record", "rights_authorization": "owned"},
            "fact-source",
        )
        fact_claim = self.run_op(
            "fact.claim.register",
            [source_document],
            {
                "claim": {
                    "claim_id": "claim:policy",
                    "statement": "The archive policy is in force.",
                    "domain": "law",
                    "retrieved_at": "2026-08-01T00:00:00Z",
                    "temporal_valid_to": "2026-12-31T00:00:00Z",
                    "source_quality": 0.9,
                    "confidence": 0.8,
                    "fictionalization_allowed": False,
                }
            },
        )
        knowledge_card = self.seed(
            "knowledge_card",
            {
                "project_id": self.project_id,
                "lineage": {
                    "candidate_asset_version_id": "candidate:policy:v1",
                    "source_chunk_asset_version_ids": ["source-chunk:policy:v1"],
                },
            },
            "fact-knowledge-card",
        )
        fact_verification = self.run_op(
            "fact.verify",
            [fact_claim, knowledge_card],
            {
                "as_of": "2026-08-01T00:00:00Z",
                "evidence_decisions": [
                    {
                        "knowledge_card_asset_version_id": knowledge_card[
                            "asset_version_id"
                        ],
                        "stance": "SUPPORTS",
                        "source_quality": 0.9,
                        "confidence": 0.8,
                    }
                ],
            },
        )
        verification_content = self.read_content(fact_verification["asset_version_id"])
        self.assertEqual(verification_content["status"], "VERIFIED")
        self.assertEqual(verification_content["gate_result"], "PASSED")
        self.assertEqual(
            verification_content["claim_asset_version_id"],
            fact_claim["asset_version_id"],
        )
        self.assertTrue(verification_content["evidence_refs"])

        quality_subject = self.seed(
            "draft_version",
            {"text": "A bounded subjective quality calibration subject."},
            "quality-v2-subject",
        )
        judge_provider_result = self.seed(
            "quality_provider_result",
            {
                "status": "PASSED",
                "score": 82,
                "fixture_protocol_only": True,
                "real_model_call": False,
            },
            "quality-v2-provider-result",
        )
        quality_profile_v2 = self.run_op(
            "quality.profile.v2.create",
            payload={
                "profile": {
                    "profile_version_id": "quality-profile:readability:v2",
                    "profile_id": "quality-profile:readability",
                    "version": 2,
                    "dimension": "readability",
                    "threshold_policy_version_id": "threshold-policy:v2",
                    "thresholds": {
                        "minimum_sample_count": 1,
                        "minimum_status_accuracy": 1.0,
                        "maximum_false_pass_count": 0,
                    },
                    "judge_profile_ref": "quality-judge:readability",
                    "judge_profile_hash": "sha256:" + "a" * 64,
                    "judge_provider_id": "fixture-judge-provider",
                    "judge_model_id": "fixture-judge-model",
                    "status": "CANDIDATE",
                }
            },
        )
        judge_v2 = self.run_op(
            "quality.judge_evaluation.record",
            [quality_subject, judge_provider_result],
            {
                "evaluation": {
                    "evaluation_id": "judge-evaluation:readability:1",
                    "subject_asset_version_id": quality_subject["asset_version_id"],
                    "dimension": "readability",
                    "status": "PASSED",
                    "score": 82,
                    "confidence": 0.9,
                    "evaluator_id": "quality-judge:readability",
                    "provider_id": "fixture-judge-provider",
                    "model_id": "fixture-judge-model",
                    "generator_provider_id": "fixture-generator-provider",
                    "generator_model_id": "fixture-generator-model",
                    "reviewer_provider_id": "fixture-reviewer-provider",
                    "reviewer_model_id": "fixture-reviewer-model",
                    "prompt_version": "quality-prompt:v2",
                    "prompt_hash": "sha256:" + "b" * 64,
                    "provider_result_asset_version_id": judge_provider_result[
                        "asset_version_id"
                    ],
                }
            },
        )
        human_v2 = []
        for ordinal in (1, 2):
            human_v2.append(
                self.run_op(
                    "quality.human_evaluation.record",
                    [quality_subject],
                    {
                        "evaluation": {
                            "evaluation_id": f"human-evaluation:readability:{ordinal}",
                            "subject_asset_version_id": quality_subject[
                                "asset_version_id"
                            ],
                            "dimension": "readability",
                            "status": "PASSED",
                            "score": 82 + ordinal - 1,
                            "evaluator_id": f"human-evaluator:{ordinal}",
                            "evaluator_group": "blind-literary-panel",
                            "evaluator_identity_class": (
                                "PROFESSIONAL_EDITOR"
                                if ordinal == 1
                                else "EXPERIENCED_READER"
                            ),
                            "protocol_version": "human-blind-comparison-v1",
                            "evaluation_version": "editorial-pairwise-v1",
                            "scope_type": "CHAPTER",
                            "chapter_start": 1,
                            "chapter_end": 1,
                            "confidence": 0.8,
                            "evidence": [{"reason": "clear causal prose"}],
                            "blind": True,
                        }
                    },
                )
            )
        adjudication_v2 = self.run_op(
            "quality.adjudication.record",
            [quality_subject, *human_v2],
            {
                "adjudication": {
                    "adjudication_id": "adjudication:readability:1",
                    "subject_asset_version_id": quality_subject["asset_version_id"],
                    "dimension": "readability",
                    "status": "PASSED",
                    "score_range": [80, 85],
                    "source_human_evaluation_asset_version_ids": [
                        item["asset_version_id"] for item in human_v2
                    ],
                    "adjudicator_id": "adjudicator:readability",
                    "adjudicator_identity_class": "PROFESSIONAL_EDITOR",
                    "protocol_version": "human-blind-comparison-v1",
                    "evaluation_version": "editorial-pairwise-v1",
                    "scope_type": "CHAPTER",
                    "chapter_start": 1,
                    "chapter_end": 1,
                    "rationale": "two blind evaluations converge",
                }
            },
        )
        blind_pair_human = self.run_op(
            "quality.blind_pair_preference.record",
            [quality_subject, draft],
            {
                "preference": {
                    "preference_id": "blind-preference:1",
                    "pair_id": "pair:quality-v2:human",
                    "subject_id": "quality-subject:chapter:1",
                    "candidate_a_asset_version_id": draft["asset_version_id"],
                    "candidate_b_asset_version_id": quality_subject["asset_version_id"],
                    "choice": "B",
                    "evaluator_id": "human-evaluator:3",
                    "evaluator_role": "HUMAN",
                    "evaluator_identity_class": "EXPERIENCED_READER",
                    "protocol_version": "human-blind-comparison-v1",
                    "evaluation_version": "editorial-pairwise-v1",
                    "scope_type": "CHAPTER",
                    "chapter_start": 1,
                    "chapter_end": 1,
                    "presentation_order": "BA",
                    "dimension_scores": {
                        dimension: {"a": 3, "b": 4}
                        for dimension in BLIND_EVALUATION_DIMENSIONS
                    },
                    "confidence": 0.8,
                    "rationale": "the causal chain is clearer",
                }
            },
        )
        blind_pair_judge = self.run_op(
            "quality.blind_pair_preference.record",
            [quality_subject, draft],
            {
                "preference": {
                    "preference_id": "blind-preference:judge:1",
                    "pair_id": "pair:quality-v2:judge",
                    "subject_id": "quality-subject:chapter:1",
                    "candidate_a_asset_version_id": quality_subject["asset_version_id"],
                    "candidate_b_asset_version_id": draft["asset_version_id"],
                    "choice": "A",
                    "evaluator_id": "quality-judge:readability",
                    "evaluator_role": "AUTOMATED_JUDGE",
                    "evaluator_identity_class": "MODEL_JUDGE",
                    "protocol_version": "human-blind-comparison-v1",
                    "evaluation_version": "editorial-pairwise-v1",
                    "scope_type": "CHAPTER",
                    "chapter_start": 1,
                    "chapter_end": 1,
                    "presentation_order": "AB",
                    "dimension_scores": {
                        dimension: {"a": 4, "b": 3}
                        for dimension in BLIND_EVALUATION_DIMENSIONS
                    },
                    "confidence": 0.75,
                    "rationale": "the causal chain is clearer",
                }
            },
        )
        reader_outcome = self.run_op(
            "quality.reader_outcome_evidence.record",
            [quality_subject],
            {
                "evidence": {
                    "evidence_id": "reader-outcome:quality-v2:1",
                    "subject_asset_version_id": quality_subject["asset_version_id"],
                    "metric_type": "chapter_completion",
                    "exposure_count": 10,
                    "outcome_count": 8,
                    "reader_segment": "fixture-segment",
                    "platform": "fixture-platform",
                }
            },
        )
        calibration_v2 = self.run_op(
            "quality.calibration.v2.run",
            [
                quality_profile_v2,
                judge_v2,
                *human_v2,
                adjudication_v2,
                blind_pair_human,
                blind_pair_judge,
                reader_outcome,
            ],
            {
                "run_id": "calibration-run-v2",
                "protocol_version": "human-blind-comparison-v1",
                "evaluation_version": "editorial-pairwise-v1",
                "evidence_scope": "BOUNDED_EVIDENCE",
                "fixture_protocol_only": True,
            },
        )
        calibration_v2_content = self.read_content(calibration_v2["asset_version_id"])
        self.assertEqual(calibration_v2_content["calibration_status"], "UNCALIBRATED")
        self.assertEqual(calibration_v2_content["evidence_status"], "BOUNDED_EVIDENCE")
        self.assertFalse(calibration_v2_content["activation_allowed"])
        self.assertFalse(calibration_v2_content["production_verified"])
        self.assertEqual(
            calibration_v2_content["independence_status"],
            "CROSS_PROVIDER_DISTINCT_MODEL",
        )
        self.assertEqual(
            calibration_v2_content["diagnostics"]["pairwise_agreement"][
                "agreement_rate"
            ],
            1.0,
        )
        self.assertEqual(
            calibration_v2_content["diagnostics"]["subjective_reference_source"],
            "ADJUDICATED_SUBJECTIVE_EVIDENCE",
        )
        self.assertFalse(
            calibration_v2_content["diagnostics"][
                "single_human_evaluation_is_ground_truth"
            ]
        )
        absence_evidence = self.seed(
            "state_absence_evidence",
            {
                "state_kind": "relationship_state_snapshot",
                "previous_chapter": 1,
                "state_exists": False,
                "canon_reduction_status": "SUCCEEDED",
                "previous_final_release_gate_id": "release-gate:chapter-1",
                "fixture_protocol_only": True,
            },
            "relationship-state-absence",
        )
        self.run_op(
            "chapter.state.initialize_empty",
            [absence_evidence],
            {
                "state_kind": "relationship_state_snapshot",
                "previous_chapter": 1,
                "reason": "chapter one completed without relationship state entries",
            },
        )
        authored_inputs = {
            "chapter.plan.author": {
                "type": "chapter_plan",
                "chapter": 1,
                "title": "The Cost of Memory",
                "premise": "A clerk must expose a falsified public record.",
                "chapter_objective": "Make the clerk choose proof over safety.",
                "scene_sequence": [{"scene_id": "s1", "goal": "find proof"}],
                "chapter_hook": "The erased witness returns.",
            },
            "chapter.style_policy.author": {
                "type": "style_policy",
                "profile_id": "style:proof",
                "constraints": ["close third person"],
            },
            "chapter.quality_rubric.author": {
                "type": "quality_rubric",
                "profile_id": "quality:proof",
                "dimensions": ["continuity"],
            },
            "chapter.platform_profile.author": {
                "type": "platform_profile",
                "profile_id": "platform:proof",
                "constraints": ["strong hook"],
            },
            "chapter.operator_checklist.author": {
                "type": "operator_checklist",
                "chapter": 1,
                "completed": True,
                "contract_version": "internal-release-checklist-v1",
            },
            "chapter.fixture_waiver_approval.author": {
                "type": "operator_approval",
                "book_id": f"book:{self.project_id}",
                "decision": "APPROVED",
                "contract_version": "fixture-waiver-approval-v1",
                "fixture_protocol_only": True,
                "production_verified": False,
                "human_preference_evidence": False,
                "waiver_reason": "Exercise fixture-only Quality gate wiring.",
                "waived_dimensions": list(QUALITY_DIMENSIONS),
                "scope": {
                    "project_id": self.project_id,
                    "scope_type": "PROJECT_FIXTURE",
                    "release_readiness": "INTERNAL_REVIEW_RELEASE",
                },
                "expiry": "2099-12-31T23:59:59Z",
            },
        }
        for name, content in authored_inputs.items():
            self.run_op(
                name,
                payload={
                    "content": {
                        **content,
                        "safe_summary": f"Safe {content['type']} production input.",
                        "structured_facts": [
                            {"kind": content["type"], "value": "proof"}
                        ],
                    }
                },
            )

        def author_foundation(
            name: str,
            generator: str,
            logical_role: str,
            candidate_payload: dict,
            parents: dict[str, dict] | None = None,
        ) -> dict:
            frozen_parents = parents or {}
            return self.run_op(
                name,
                list(frozen_parents.values()),
                {
                    "content": {
                        "schema_version": "story_design.authority.v1",
                        "project_id": self.project_id,
                        "generator_operation_name": generator,
                        "planning_scope": "NOT_APPLICABLE",
                        "logical_key": (
                            f"foundation:{logical_role}:content-runtime-v1"
                        ),
                        "operator_authored": True,
                        "provider_generated": False,
                        "candidate_payload": {
                            **candidate_payload,
                            **(
                                {
                                    "foundation_parent_bindings": {
                                        role: {
                                            "asset_version_id": item[
                                                "asset_version_id"
                                            ],
                                            "content_hash": item["content_hash"],
                                        }
                                        for role, item in frozen_parents.items()
                                    }
                                }
                                if frozen_parents
                                else {}
                            ),
                        },
                    }
                },
            )

        creative = author_foundation(
            "story_design.creative_foundation.author",
            "creative.candidates.generate",
            "creative",
            {
                "objective": "Establish a costly public-truth mystery engine.",
                "narrative_intent_source": "goal: Public evidence forces a costly choice\nmust_have: Earned discovery\nmust_not: Uncaused resurrection\ntone: restrained\nallowed_deviation: Scene order only",
                "target_reader": "adult speculative mystery readers",
                "why_worth_writing": "Public truth creates responsibility.",
                "genre": "speculative mystery",
                "subgenre": "institutional mystery",
                "core_desire": "restore erased belonging",
                "core_fear": "truth will expose protected people",
                "core_conflict": "witnesses challenge a self-editing archive",
                "narrative_engine": "each anomaly forces disclosure or concealment",
                "differentiation": "geography changes through accountable choices",
                "emotional_contract": "wonder becomes costly shared responsibility",
                "serialization_potential": "each district exposes a distinct bargain",
            },
        )
        compiled_creative = self.read_content(creative["asset_version_id"])["candidate_payload"]
        self.assertNotIn("narrative_intent_source", compiled_creative)
        self.assertEqual(compiled_creative["narrative_intent"]["must_not"], ["Uncaused resurrection"])
        self.assertEqual(compiled_creative["intent_compiler_version"], "labeled-narrative-intent.v1")
        creative_parent = {"CREATIVE_FOUNDATION": creative}
        theme = author_foundation(
            "story_design.theme_contract.author",
            "theme.candidates.generate",
            "theme",
            {
                "objective": "Bind truth to humane public choice.",
                "thematic_question": "Can public truth remain humane under pressure?",
                "genre": "speculative mystery",
            },
            creative_parent,
        )
        ending = author_foundation(
            "story_design.ending_intent.author",
            "ending.intent.generate",
            "ending",
            {
                "objective": "Make collective custody an earned ending direction.",
                "ending_direction": "collective custody replaces solitary control",
                "protagonist_cost": "Mara surrenders exclusive certainty",
                "genre": "speculative mystery",
            },
            creative_parent,
        )
        promise = author_foundation(
            "story_design.reader_promise.author",
            "reader.promise.generate",
            "reader-promise",
            {
                "objective": "Promise discovery through costly public choices.",
                "reader_promise": "Every discovery forces a costly public choice",
                "genre": "speculative mystery",
            },
            creative_parent,
        )
        creative_contracts = {
            "CREATIVE_FOUNDATION": creative,
            "THEME_CONTRACT": theme,
            "ENDING_INTENT": ending,
            "READER_PROMISE": promise,
        }
        world = author_foundation(
            "story_design.world_bible.author",
            "world.design.generate",
            "world",
            {
                "objective": "Turn witnessed truth into bounded world causality.",
                "rules": [
                    {
                        "rule": "A witnessed place resists erasure for seven days",
                        "cost": "the witness becomes publicly exposed",
                        "exception": "a witness may formally recant",
                        "consequence": "access remains open while testimony stands",
                        "narrative_function": "turn knowledge into costly agency",
                    }
                ],
            },
            creative_contracts,
        )
        author_foundation(
            "story_design.character_cast.author",
            "character.cast.generate",
            "characters",
            {
                "objective": "Give the witness mystery an agentic cast.",
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
                        "agency": "chooses when evidence becomes public",
                        "capability": "reads archival topology",
                        "weakness": "withholds uncertainty",
                        "voice": "precise until emotionally cornered",
                        "secret": "her first map caused harm",
                        "relationship_function": "learn accountable trust",
                        "arc_direction": "certainty becomes shared responsibility",
                    }
                ],
            },
            {**creative_contracts, "WORLD_BIBLE": world},
        )
        self.run_op(
            "story_design.review.author",
            [creative],
            {
                "candidate_asset_version_id": creative["asset_version_id"],
                "candidate_content_hash": creative["content_hash"],
                "evaluation": {
                    "schema_version": "progressive-narrative-qualification.v1",
                    "evaluations": [],
                    "fixture_protocol_only": True,
                },
                "review_rationale": (
                    "Independent fixture operator binds review evidence to the exact "
                    "candidate; this is not human preference or Provider evidence."
                ),
            },
        )

        book_id = f"book:{self.project_id}"
        bootstrap_inputs = {
            "book.production_profile.author": {
                "type": "production_profile",
                "profile_id": "bounded-quality-v1",
                "target_chapter_count": 8,
                "language_contract": {
                    "language": "zh-CN",
                    "script": "Hans",
                },
                "authority_boundary": "FUTURE_INTENT",
            },
            "book.previous_volume_outcome.author": {
                "type": "previous_volume_outcome",
                "contract_version": "v1",
                "status": "NO_PREVIOUS_VOLUME",
                "authority_boundary": "PRE_CHAPTER_0",
            },
            "book.previous_chapter_group_outcome.author": {
                "type": "previous_chapter_group_outcome",
                "contract_version": "v1",
                "status": "NO_PREVIOUS_CHAPTER_GROUP",
                "actual_outcomes": [],
                "authority_boundary": "PRE_CHAPTER_0",
            },
            "book.previous_chapter_outcome.author": {
                "type": "previous_chapter_outcome",
                "contract_version": "v1",
                "status": "NO_PREVIOUS_CHAPTER",
                "actual_outcomes": [],
                "authority_boundary": "PRE_CHAPTER_0",
            },
            "book.arc_portfolio.author": {
                "type": "arc_portfolio",
                "portfolio_id": "arc-portfolio:bounded",
                "contract_version": "v1",
                "authority_boundary": "FUTURE_INTENT",
            },
            "book.ending_reachability.author": {
                "type": "ending_reachability",
                "contract_version": "v1",
                "status": "PLANNED_NOT_ACTUAL",
                "authority_boundary": "ADVISORY",
            },
            "book.character_arc_portfolio.author": {
                "type": "character_arc_portfolio",
                "portfolio_id": "character-arc-portfolio:bounded",
                "contract_version": "v1",
                "authority_boundary": "FUTURE_INTENT",
            },
            "book.conflict_state.author": {
                "type": "conflict_state",
                "contract_version": "v1",
                "active_conflicts": [],
                "authority_boundary": "PRE_CHAPTER_0",
            },
            "book.foreshadowing_ledger.author": {
                "type": "foreshadowing_ledger",
                "contract_version": "v1",
                "entries": [],
                "authority_boundary": "PRE_CHAPTER_0",
            },
            "book.reader_segment.author": {
                "type": "reader_segment_profile",
                "profile_id": "reader:bounded",
                "profile_version": "reader-outcome-v3",
                "authority_boundary": "ADVISORY",
            },
            "book.reader_contract.author": {
                "type": "reader_contract",
                "profile_id": "reader:bounded",
                "profile_version": "reader-outcome-v3",
                "authority_boundary": "ADVISORY",
            },
            "book.reader_state.author": {
                "type": "reader_state",
                "contract_version": "reader-state-genesis-v1",
                "profile_version": "reader-outcome-v3",
                "status": "NOT_OBSERVED",
                "accepted_through_chapter": 0,
                "observations": [],
                "evidence_class": "READER_PROXY_ADVISORY",
                "authority_boundary": "ADVISORY",
            },
            "book.character_state.author": {
                "type": "character_state_snapshot",
                "contract_version": "v1",
                "entries": [],
                "authority_boundary": "PRE_CHAPTER_0",
            },
            "book.foreshadowing_state.author": {
                "type": "foreshadow_snapshot",
                "contract_version": "v1",
                "entries": [],
                "authority_boundary": "PRE_CHAPTER_0",
            },
            "book.quality_trend.author": {
                "type": "quality_trend",
                "contract_version": "v1",
                "status": "NO_ACCEPTED_CHAPTERS",
                "authority_boundary": "ADVISORY",
            },
            "book.reward_ledger.author": {
                "type": "reward_ledger_snapshot",
                "contract_version": "v1",
                "entries": [],
                "authority_boundary": "PRE_CHAPTER_0",
            },
            "book.promise_ledger.author": {
                "type": "promise_ledger_snapshot",
                "contract_version": "v1",
                "entries": [],
                "authority_boundary": "PRE_CHAPTER_0",
            },
        }
        for name, content in bootstrap_inputs.items():
            self.run_op(
                name,
                payload={
                    "content": {
                        **content,
                        "book_id": book_id,
                        "safe_summary": f"Bounded {content['type']} bootstrap.",
                        "structured_facts": [
                            {
                                "key": "authority_boundary",
                                "value": content["authority_boundary"],
                            }
                        ],
                    }
                },
            )
        style_creative = self.seed(
            "creative_foundation",
            {
                "book_id": book_id,
                "style_profile": {
                    "narrator": "Limited third person; show the price of each choice.",
                    "pov": {"mara": "Distinguish observation from suspicion."},
                    "genre_conventions": "Pay off clues through public evidence.",
                    "constraints": ["Do not narrate unobserved secrets as Mara's knowledge."],
                },
            },
            "style-creative",
        )
        style_cast = self.seed(
            "character_cast",
            {"characters": [{"character_id": "mara", "voice_anchors": ["Asks who witnessed a claim."]}]},
            "style-cast",
        )
        style_design = self.seed(
            "book_design",
            {"foundation_set": {"bindings": [
                {"role": "CREATIVE_FOUNDATION", **style_creative},
                {"role": "CHARACTER_CAST", **style_cast},
            ]}},
            "style-design",
        )
        compiled_style = self.run_op(
            "chapter.style_policy.compile", [style_design, style_creative, style_cast]
        )
        style = self.read_content(compiled_style["asset_version_id"])
        self.assertEqual(style["source_bindings"], [style_design, style_creative, style_cast])
        self.assertEqual(style["book_id"], book_id)
        self.assertFalse(style["narrative_truth_mutation_allowed"])
        campaign_identity = (
            "sha256:"
            + hashlib.sha256(
                f"{self.project_id}\x00{book_id}\x00bounded-quality-v1".encode()
            ).hexdigest()
        )
        initial_story_state = self.run_op(
            "book.initial_story_state.author",
            payload={
                "book_id": book_id,
                "campaign_contract_identity": campaign_identity,
            },
        )
        self.run_op(
            "book.initial_canon.author",
            [initial_story_state],
            {
                "book_id": book_id,
                "campaign_contract_identity": campaign_identity,
            },
        )
        directive = "Change the future rescue route while retaining accepted history and water cost."
        proposed_change = self.run_op(
            "planning.change_request.author",
            payload={"content": {
                "book_id": book_id,
                "target_plan_version_id": f"{self.project_id}:future-group:v1",
                "accepted_through_chapter": 3,
                "affected_scope": "CHAPTER_GROUP",
                "directive": directive,
                "preserved_invariants": ["Accepted chapters 1–3 and the water cost"],
                "safe_summary": directive,
                "structured_facts": [],
            }},
        )
        change = self.read_content(proposed_change["asset_version_id"])
        self.assertEqual(change["book_id"], book_id)
        self.assertEqual(change["accepted_through_chapter"], 3)
        self.assertEqual(change["directive"], directive)
        self.assertEqual(change["authority_boundary"], "FUTURE_PLAN_PROPOSAL_ONLY")
        self.assertFalse(change["direct_plan_mutation_allowed"])
        self.assertFalse(change["canon_mutation_allowed"])

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT definition_name, status FROM authority_operation WHERE project_id = %s",
                [self.project_id],
            )
            operations = uow.cursor.fetchall()
            uow.cursor.execute(
                "SELECT COUNT(*) FROM audit_log WHERE project_id = %s AND action LIKE 'content.%%.materialized'",
                [self.project_id],
            )
            audits = uow.cursor.fetchone()[0]
            uow.cursor.execute(
                "SELECT COUNT(*) FROM outbox_event WHERE project_id = %s AND topic LIKE 'content.%%.materialized'",
                [self.project_id],
            )
            outbox = uow.cursor.fetchone()[0]
        self.assertEqual({name for name, _ in operations}, set(CONTENT_CODECS))
        self.assertEqual(
            {name: status for name, status in operations if status != "SUCCEEDED"},
            {},
        )
        succeeded = sum(status == "SUCCEEDED" for _, status in operations)
        self.assertEqual(audits, succeeded)
        self.assertEqual(outbox, succeeded)


if __name__ == "__main__":
    unittest.main()
