from __future__ import annotations

import hashlib
import json
import unittest

from novel_forge.modules.content_authority import CONTENT_CODECS
from novel_forge.modules.content_authority.application import (
    ContentAuthorityApplication,
    ContentOperationRequest,
)
from novel_forge.modules.command_kernel.errors import KernelError
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

        calibration_profile = self.seed(
            "quality_calibration_profile",
            {
                "profile_id": "readability-golden-v1",
                "dimension": "readability",
                "dataset_version": "golden-v1",
                "threshold_policy_version_id": "quality-policy-v1",
                "status": "UNCALIBRATED",
                "revoked": False,
                "stale": False,
            },
            "calibration-profile",
        )
        golden_samples = []
        provider_decisions = []
        for index in range(5):
            target = self.seed(
                "draft_version",
                {"text": f"Deterministic golden sample {index}."},
                f"golden-target-{index}",
            )
            sample_id = f"sample-{index}"
            golden = self.run_op(
                "quality.golden_sample.create",
                [target],
                {
                    "sample": {
                        "sample_id": sample_id,
                        "dimension": "readability",
                        "input_asset_version_ids": [target["asset_version_id"]],
                        "expected_status": "PASSED",
                        "expected_score_range": [75, 90],
                        "human_evidence": [{"span": [0, 10]}],
                        "annotator": "fixture-adjudicator",
                        "adjudication_status": "ADJUDICATED",
                        "dataset_version": "golden-v1",
                    }
                },
            )
            golden_samples.append(golden)
            provider_decisions.append(
                self.seed(
                    "quality_provider_decision",
                    {
                        "sample_id": sample_id,
                        "dimension": "readability",
                        "status": "PASSED",
                        "score": 82,
                        "confidence": 0.9,
                        "fixture_protocol_only": True,
                        "real_model_call": False,
                        "production_verified": False,
                    },
                    f"provider-decision-{index}",
                )
            )
        self.run_op(
            "quality.human_decision.record",
            [golden_samples[0]],
            {
                "decision": {
                    "sample_id": "sample-0",
                    "dimension": "readability",
                    "status": "PASSED",
                    "score": 82,
                    "evidence": [{"span": [0, 10]}],
                    "annotator": "fixture-human",
                }
            },
        )
        calibration_report = self.run_op(
            "quality.calibration.run",
            [calibration_profile, *golden_samples, *provider_decisions],
            {
                "run_id": "calibration-run-v1",
                "fixture_protocol_only": True,
                "policy": {
                    "policy_version": "fixture-calibration-policy-v1",
                    "minimum_sample_count": 5,
                    "minimum_coverage": 1.0,
                    "minimum_status_accuracy": 1.0,
                    "minimum_score_in_range_rate": 1.0,
                    "minimum_per_status_precision": 1.0,
                    "minimum_per_status_recall": 1.0,
                    "minimum_inter_annotator_agreement": 1.0,
                    "maximum_unresolved_adjudication": 0,
                    "confidence_interval_policy": "deterministic-fixture-exact",
                },
            },
        )
        with self.assertRaisesRegex(KernelError, "QUALITY_FIXTURE_PROMOTION_FORBIDDEN"):
            self.run_op(
                "quality.calibration.profile.promote",
                [calibration_profile, calibration_report],
            )
        self.run_op(
            "quality.calibration.profile.revoke",
            [calibration_profile],
            {"reason": "fixture lifecycle proof"},
        )
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
                    "judge_profile_ref": "judge-profile:readability:v2",
                    "judge_profile_hash": "sha256:" + "a" * 64,
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
                    "model_id": "fixture-model",
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
                    "rationale": "two blind evaluations converge",
                }
            },
        )
        blind_pair = self.run_op(
            "quality.blind_pair_preference.record",
            [quality_subject, draft],
            {
                "preference": {
                    "preference_id": "blind-preference:1",
                    "pair_id": "pair:quality-v2:1",
                    "candidate_a_asset_version_id": quality_subject["asset_version_id"],
                    "candidate_b_asset_version_id": draft["asset_version_id"],
                    "preferred_asset_version_id": quality_subject["asset_version_id"],
                    "evaluator_id": "human-evaluator:3",
                    "presentation_order": "BA",
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
                blind_pair,
                reader_outcome,
            ],
            {"run_id": "calibration-run-v2", "fixture_protocol_only": True},
        )
        calibration_v2_content = self.read_content(calibration_v2["asset_version_id"])
        self.assertEqual(calibration_v2_content["calibration_status"], "UNCALIBRATED")
        self.assertFalse(calibration_v2_content["activation_allowed"])
        self.assertFalse(calibration_v2_content["production_verified"])
        self.assertEqual(
            calibration_v2_content["diagnostics"]["subjective_reference_source"],
            "ADJUDICATED_EVALUATION",
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
            {"quality.calibration.profile.promote": "FAILED_FINAL"},
        )
        succeeded = sum(status == "SUCCEEDED" for _, status in operations)
        self.assertEqual(audits, succeeded)
        self.assertEqual(outbox, succeeded)


if __name__ == "__main__":
    unittest.main()
