from __future__ import annotations

import unittest
from dataclasses import replace

from novel_forge.modules.authority_security import (
    PrincipalType,
    TrustedPrincipalResolver,
)
from novel_forge.modules.production_preparation.contracts import (
    ProductionPreparationRequest,
    ResolvedProductionAsset,
)
from novel_forge.modules.production_preparation.service import (
    ProductionPreparationService,
)
from novel_forge.modules.production_preparation.policies import STAGE_PROFILES
from novel_forge.modules.chapter_authority.domain_handlers import build_context_bundle
from novel_forge.modules.mkaos_authority.domain import (
    resolve_book_knowledge_access_policy,
)


class _Resolver:
    def __init__(self, assets: dict[str, ResolvedProductionAsset]) -> None:
        self.assets = assets

    def resolve_latest(self, *, project_id: str, asset_type: str):
        asset = self.assets.get(asset_type)
        if asset is not None and asset.project_id != project_id:
            return None
        return asset

    def resolve_all(self, *, project_id: str, asset_type: str, limit: int = 200):
        del limit
        asset = self.resolve_latest(project_id=project_id, asset_type=asset_type)
        return () if asset is None else (asset,)

    def resolve_override(self, *, project_id: str, asset_version_id: str):
        for asset in self.assets.values():
            if asset.asset_version_id == asset_version_id:
                if asset.project_id != project_id:
                    raise ValueError("cross-project override")
                return asset
        raise ValueError("missing override")


class _MultiResolver(_Resolver):
    def __init__(self, assets: dict[str, list[ResolvedProductionAsset]]) -> None:
        self.collections = assets
        super().__init__({key: values[0] for key, values in assets.items() if values})

    def resolve_all(self, *, project_id: str, asset_type: str, limit: int = 200):
        return tuple(
            item
            for item in self.collections.get(asset_type, [])[:limit]
            if item.project_id == project_id
        )

    def resolve_override(self, *, project_id: str, asset_version_id: str):
        for values in self.collections.values():
            for asset in values:
                if asset.asset_version_id == asset_version_id:
                    if asset.project_id != project_id:
                        raise ValueError("cross-project override")
                    return asset
        raise ValueError("missing override")


def _asset(
    asset_type: str, *, project_id: str = "project-1"
) -> ResolvedProductionAsset:
    content = {
        "type": asset_type,
        "chapter": 1,
        "safe_summary": f"Safe {asset_type} summary.",
        "structured_facts": [],
    }
    if asset_type == "operator_checklist":
        content["structured_facts"] = [{"key": "completed", "value": True}]
    if asset_type == "operator_approval":
        content["structured_facts"] = [{"key": "approved", "value": True}]
    if asset_type == "chapter_plan":
        content.update(
            {
                "title": "Qualified plan",
                "premise": "A costly choice advances the promise.",
                "chapter_objective": "Force a consequential choice.",
                "scene_sequence": [{"scene_id": "scene-1", "goal": "choose"}],
                "chapter_hook": "The cost creates a new obligation.",
                "conflict_chain": [{"pressure": "public consequence"}],
                "reader_promise_actions": [
                    {"promise_id": "promise-1", "action": "progress"}
                ],
                "protagonist_charm_mechanism": "accepts a cost for another person",
                "information_reveals": [{"fact": "the promise has a hidden price"}],
                "next_chapter_bridge": "The obligation becomes the next conflict.",
                "emotional_curve": ["resolve", "doubt", "cost"],
                "suspense_curve": ["question", "pressure", "new question"],
                "antagonist_pressure": {"mechanism": "tightens the deadline"},
            }
        )
    if asset_type == "story_state_snapshot":
        content.update(
            {
                "contract_version": "story-state-snapshot-v2",
                "book_id": "book-1",
                "accepted_through_chapter": 1,
                "_authority_acceptance_bound": True,
                "current_state": {
                    "character_state": [
                        {
                            "entity_key": "character_id=hero",
                            "entity_version": 1,
                            "state": {"character_id": "hero", "location": "Hangzhou"},
                            "source_event_id": "narrative-event:hero",
                            "source_chapter": 1,
                            "effective_from_chapter": 1,
                            "confidence": 1.0,
                            "coverage": "EXPLICIT",
                            "evidence": {},
                        }
                    ]
                },
            }
        )
    if asset_type == "canon_snapshot":
        content.update(
            {
                "contract_version": "canon-snapshot-v2",
                "book_id": "book-1",
                "accepted_through_chapter": 1,
                "_authority_acceptance_bound": True,
                "current_facts": [],
            }
        )
    return ResolvedProductionAsset(
        project_id=project_id,
        asset_id=f"asset:{asset_type}",
        asset_version_id=f"version:{asset_type}",
        asset_type=asset_type,
        content_hash=f"sha256:{asset_type}",
        content=content,
        qualification="ELIGIBLE",
        selected_reason="latest eligible authority version",
    )


class ProductionPreparationTests(unittest.TestCase):
    def test_foreign_fallbacks_are_skipped_but_explicit_scope_and_context_conflicts_fail_closed(self) -> None:
        from novel_forge.modules.command_kernel.errors import KernelError

        request = ProductionPreparationRequest(project_id="project-1", workspace_id="workspace-1",
            book_id="book-1", chapter=1, idempotency_key="book-scoped")
        assets = {kind: [_asset(kind)] for kind in (
            "chapter_plan", "style_policy", "quality_rubric", "platform_profile")}
        own = assets["style_policy"][0]
        foreign_scopes = (
            {"book_id": "book-2"}, {"scope": {"book_id": "book-2"}},
            {"creative_input_selection": {"book_id": "book-2"}},
            {"book_id": "book-1", "scope": {"book_id": "book-2"}},
        )
        for content in foreign_scopes:
            with self.subTest(content=content):
                foreign = replace(own, asset_version_id="foreign:v1", content={**own.content, **content})
                assets["style_policy"] = [foreign, own]
                service = ProductionPreparationService(_MultiResolver(assets))
                prepared = service.prepare(request)
                self.assertEqual(prepared.report.decision, "READY")
                ids = {item["asset_version_id"] for item in prepared.command.context_candidates}
                self.assertIn(own.asset_version_id, ids)
                self.assertNotIn(foreign.asset_version_id, ids)
                self.assertTrue(any(item["asset_version_id"] == foreign.asset_version_id
                    for item in prepared.report.production_input_manifest["rejected_asset_versions"]))
                with self.assertRaisesRegex(KernelError, "PREPARATION_(CROSS_BOOK_INPUT|BOOK_SCOPE_CONFLICT)"):
                    service.prepare(replace(request, explicit_asset_version_overrides={"style_policy": "foreign:v1"}))
                with self.assertRaisesRegex(KernelError, "PREPARATION_(CROSS_BOOK_INPUT|BOOK_SCOPE_CONFLICT)"):
                    service._context_candidate(foreign, evidence_only_types=(), task_narrative_projection={},
                        chapter=1, book_id="book-1", accepted_boundary={})
        foreign = replace(own, asset_version_id="owned-foreign:v1", book_scope_ids=("book-2",))
        assets["style_policy"] = [foreign, own]
        prepared = ProductionPreparationService(_MultiResolver(assets)).prepare(request)
        self.assertEqual(prepared.report.decision, "READY")
        self.assertNotIn(foreign.asset_version_id, {item["asset_version_id"] for item in prepared.command.context_candidates})
        for invalid in (0, False, []):
            assets["style_policy"] = [replace(own, content={**own.content, "book_id": invalid})]
            with self.assertRaisesRegex(KernelError, "PREPARATION_BOOK_SCOPE_INVALID"):
                ProductionPreparationService(_MultiResolver(assets)).prepare(replace(request,
                    explicit_asset_version_overrides={"style_policy": own.asset_version_id}))

    def test_optional_candidate_unavailability_does_not_bypass_adopted_or_explicit_bindings(self) -> None:
        from novel_forge.modules.command_kernel.errors import KernelError

        for unavailable in ("PREPARATION_OVERRIDE_NOT_FOUND", "PREPARATION_OVERRIDE_NOT_ELIGIBLE"):
            with self.subTest(unavailable=unavailable):
                assets = {kind: [_asset(kind)] for kind in ("chapter_plan", "style_policy", "quality_rubric", "platform_profile")}
                class UnavailableResolver(_MultiResolver):
                    def resolve_override(self, *, project_id, asset_version_id):
                        if asset_version_id == "optional:v1":
                            raise KernelError(unavailable, "Optional Card is unavailable")
                        return super().resolve_override(project_id=project_id, asset_version_id=asset_version_id)
                profile = {"knowledge_access_policy": {"mode": "ALLOW_ONLY",
                    "allowed_knowledge_card_asset_version_ids": ["optional:v1"],
                    "usage_scope": "EXPERIMENTAL_VALIDATION", "experimental_policy_version": "experiment.v1",
                    "craft_candidate_review_version": "explicit-allowlist-craft-review.v1"}}
                access = resolve_book_knowledge_access_policy(production_profile=profile, project_id="project-1", book_id="book-1")
                plan = assets["chapter_plan"][0]
                assets["chapter_plan"] = [replace(plan, content={**plan.content, "knowledge_translations": []})]
                request = ProductionPreparationRequest(project_id="project-1", workspace_id="workspace-1", book_id="book-1",
                    chapter=1, idempotency_key="optional-review", knowledge_access_policy=access)
                service = ProductionPreparationService(UnavailableResolver(assets))
                ready = service.prepare(request)
                self.assertEqual(ready.report.decision, "READY")
                self.assertTrue(any(item["code"] == unavailable for item in ready.report.production_input_manifest["rejected_asset_versions"]))
                available = replace(_asset("knowledge_card"), asset_version_id="optional:v1", content={
                    "abstract_content": {"mechanism": "A reaction follows the person's available information."},
                    "source_policy": {"approval_class": "EXPERIMENTAL_VALIDATION", "experimental_context_eligible": True,
                        "approval_policy_version": "experiment.v1"}})
                assets["knowledge_card"] = [available]
                assets["chapter_plan"] = [plan]
                without_translation = ProductionPreparationService(_MultiResolver(assets)).prepare(request)
                self.assertEqual(without_translation.report.decision, "READY")
                self.assertFalse(any(item["asset_type"] == "knowledge_card" for item in without_translation.command.context_candidates))
                self.assertTrue(any(item["code"] == "KNOWLEDGE_NOT_ADOPTED_BY_CHAPTER_PLAN" for item in without_translation.report.production_input_manifest["rejected_asset_versions"]))
                assets.pop("knowledge_card")
                assets["chapter_plan"] = [replace(plan, content={**plan.content, "knowledge_translations": [{
                    "knowledge_card_asset_version_id": "optional:v1", "content_hash": "sha256:original",
                    "decision": "ADAPT", "usage_role": "MECHANISM"}]})]
                blocked = service.prepare(request)
                self.assertEqual(blocked.report.decision, "BLOCKED")
                self.assertEqual(blocked.report.blocked_assets[0]["code"], unavailable)
                with self.assertRaisesRegex(KernelError, unavailable):
                    service.prepare(replace(request, explicit_asset_version_overrides={"knowledge_card": "optional:v1"}))
                profile["knowledge_access_policy"].pop("craft_candidate_review_version")
                legacy = resolve_book_knowledge_access_policy(production_profile=profile, project_id="project-1", book_id="book-1")
                with self.assertRaisesRegex(KernelError, unavailable):
                    service.prepare(replace(request, knowledge_access_policy=legacy))

    def test_operational_text_in_knowledge_constraints_never_becomes_context(self) -> None:
        from novel_forge.modules.command_kernel.errors import KernelError
        card = replace(_asset("knowledge_card"), content={"abstract_content": {
            "knowledge_kind": "NARRATIVE_INTELLIGENCE", "mechanism": "Practice changes later options.",
            "constraints": ["project_id=research; observation_hash=sha256:fixture"],
        }})
        with self.assertRaisesRegex(KernelError, "OPERATIONAL_LEAK"):
            ProductionPreparationService._context_candidate(card, evidence_only_types=(),
                task_narrative_projection={}, chapter=1, book_id="book-1", accepted_boundary={})

    def test_reading_checklist_cannot_replace_chapter_governance_or_enter_explicitly(self) -> None:
        assets = {kind: [_asset(kind)] for kind in (
            "chapter_plan", "style_policy", "quality_rubric", "platform_profile",
        )}
        chapter_checklist = _asset("operator_checklist")
        reading = replace(chapter_checklist, asset_id="reading", asset_version_id="reading:v1", content={
            **chapter_checklist.content, "contract_version": "author-reading-review.v1",
            "allowed_use": "evidence_only", "safe_summary": "Operator-only reading evidence",
        })
        assets["operator_checklist"] = [reading, chapter_checklist]
        service = ProductionPreparationService(_MultiResolver(assets))
        request = ProductionPreparationRequest(
            project_id="project-1", workspace_id="workspace-1", book_id="book-1", chapter=1,
            idempotency_key="reading-purpose", capability_required_asset_types=("operator_checklist",),
        )
        result = service.prepare(request)
        self.assertEqual(result.report.decision, "READY")
        selected = [item for item in result.command.context_candidates if item["asset_type"] == "operator_checklist"]
        self.assertEqual([item["asset_version_id"] for item in selected], [chapter_checklist.asset_version_id])
        rejected = service.prepare(replace(request, explicit_asset_version_overrides={"operator_checklist": reading.asset_version_id}))
        self.assertEqual(rejected.report.decision, "BLOCKED")
        self.assertEqual(rejected.report.blocked_assets[0]["code"], "OPERATOR_CHECKLIST_PURPOSE_MISMATCH")

    def test_preparation_revalidates_adoption_against_current_mechanism_inputs(self) -> None:
        import json

        for role, decision, reserve, expected in (
            ("MECHANISM", "ADOPT", 2, "READY"),
            ("MECHANISM", "ADOPT", 0, "BLOCKED"),
            ("CONSTRAINT", "ADOPT", 0, "BLOCKED"),
            ("MECHANISM", "ADOPT", None, "BLOCKED"),
            ("MECHANISM", "ADAPT", 0, "READY"),
            ("INSPIRATION", "ADOPT", 0, "READY"),
        ):
            with self.subTest(role=role, decision=decision, reserve=reserve):
                assets = {kind: [_asset(kind)] for kind in (
                    "chapter_plan", "style_policy", "quality_rubric", "platform_profile",
                )}
                world = replace(
                    _asset("world_bible"), asset_version_id=f"world:{reserve}",
                    content_hash=f"sha256:world:{reserve}",
                    content={} if reserve is None else {"water_reserve": reserve},
                )
                assets["world_bible"] = [world]
                card = replace(_asset("knowledge_card"), content={"abstract_content": {
                    "concept_name": "Cooling consumes the reserve", "mechanism": "Water carries away heat.",
                    "applicability_contract": {
                        "schema_version": "knowledge-applicability.v1", "usage_role": role,
                        "prerequisites": [{"condition_id": "water", "path": "/world_bible/water_reserve", "operator": "GT", "value": 0}],
                        "exceptions": [], "hard_conflicts": [],
                    },
                }})
                assets["knowledge_card"] = [card]
                plan = assets["chapter_plan"][0]
                translation = {
                    "knowledge_card_asset_version_id": card.asset_version_id,
                    "content_hash": card.content_hash, "decision": decision, "usage_role": role,
                }
                assets["chapter_plan"] = [replace(plan, content={**plan.content, "knowledge_translations": [translation]})]
                result = ProductionPreparationService(_MultiResolver(assets)).prepare(
                    ProductionPreparationRequest(project_id="project-1", workspace_id="workspace-1", book_id="book-1", chapter=1, idempotency_key=f"current:{role}:{decision}:{reserve}")
                )
                self.assertEqual(result.report.decision, expected)
                if expected == "BLOCKED":
                    self.assertIsNone(result.command)
                    issue = result.report.blocked_assets[0]
                    self.assertEqual(issue["code"], "KNOWLEDGE_TRANSLATION_ADOPTION_REQUIRES_REPLAN")
                    self.assertEqual(issue["current_applicability_assessment"]["checks"][0]["source_asset_version_id"], world.asset_version_id)
                else:
                    candidate = next(item for item in result.command.context_candidates if item["asset_type"] == "knowledge_card")
                    assessment = json.loads(candidate["safe_summary"])["applicability_assessment"]
                    self.assertEqual(assessment["checks"][0]["source_content_hash"], world.content_hash)

    def test_plan_adoption_is_required_protected_and_does_not_reselect_rejected_cards(self) -> None:
        import json

        assets = {kind: [_asset(kind)] for kind in ("chapter_plan", "style_policy", "quality_rubric", "platform_profile")}
        card = replace(_asset("knowledge_card"), content={"abstract_content": {
            "concept_name": "Costly cooling", "mechanism": "Cooling consumes the water reserve.",
            "preconditions": ["Reserve exists and is uncontaminated."], "exceptions": ["Contamination makes this mechanism unsafe."],
        }})
        extra = replace(card, asset_id="extra", asset_version_id="extra:v1")
        assets["knowledge_card"] = [extra, card]
        plan = assets["chapter_plan"][0]
        translation = {
            "knowledge_card_asset_version_id": card.asset_version_id, "content_hash": card.content_hash,
            "decision": "ADAPT", "usage_role": "MECHANISM", "rationale": "Cooling forces a costly choice.",
            "prerequisite_resolution": "Verify the water supply first.",
            "use_sites": [{"target_pointer": "/chapter_objective", "realization_excerpt": "Force a consequential choice.", "expected_application": "The water is spent.", "preservation_requirements": ["Preserve resource cost."], "verification_checks": ["Verify loss of water after cooling."]}],
        }
        assets["chapter_plan"] = [replace(plan, content={**plan.content, "knowledge_translations": [translation]})]
        request = ProductionPreparationRequest(project_id="project-1", workspace_id="workspace-1", book_id="book-1", chapter=1, idempotency_key="translated")
        result = ProductionPreparationService(_MultiResolver(assets)).prepare(request)
        self.assertEqual(result.report.decision, "READY")
        candidates = [item for item in result.command.context_candidates if item["asset_type"] == "knowledge_card"]
        self.assertEqual([item["asset_version_id"] for item in candidates], [card.asset_version_id])
        self.assertEqual(candidates[0]["context_class"], "PROTECTED")
        rendered = json.loads(candidates[0]["safe_summary"])
        self.assertEqual(rendered["translation"], translation)
        self.assertEqual(rendered["preconditions"], ["Reserve exists and is uncontaminated."])
        self.assertTrue(any(item["code"] == "KNOWLEDGE_NOT_ADOPTED_BY_CHAPTER_PLAN" for item in result.report.production_input_manifest["rejected_asset_versions"]))
        assets["chapter_plan"] = [replace(plan, content={**plan.content, "knowledge_translations": [{**translation, "content_hash": "wrong"}]})]
        drift = ProductionPreparationService(_MultiResolver(assets)).prepare(request)
        self.assertEqual(drift.report.decision, "BLOCKED")
        self.assertEqual(drift.report.blocked_assets[0]["code"], "KNOWLEDGE_TRANSLATION_VERSION_DRIFT")

    def test_book_allowlist_selects_exact_knowledge_card_versions(self) -> None:
        required = {
            kind: [_asset(kind)]
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
            )
        }
        cards = []
        for name in ("allowed", "outside"):
            base = _asset("knowledge_card")
            cards.append(
                replace(
                    base,
                    asset_id=f"asset:knowledge:{name}",
                    asset_version_id=f"knowledge-card:{name}:v1",
                    content_hash=f"sha256:knowledge:{name}",
                    content={
                        "abstract_content": {
                            "concept_name": name,
                            "mechanism": "A choice changes later options.",
                            "applicability": ["A plan needs a causal choice."],
                            "failure_conditions": ["No option changes."],
                            "constraints": ["Preserve the consequence."],
                            "conflict_generators": ["Benefits conflict."],
                            "review_checks": ["Check the later state."],
                            "semantic_family": "NARRATIVE_MECHANISM",
                            "selection_tags": {},
                            "repetition_key": name,
                        }
                    },
                )
            )
        collections = {**required, "knowledge_card": cards}
        access = resolve_book_knowledge_access_policy(
            production_profile={
                "knowledge_access_policy": {
                    "mode": "ALLOW_ONLY",
                    "allowed_knowledge_card_asset_version_ids": [
                        "knowledge-card:allowed:v1"
                    ],
                }
            },
            project_id="project-1",
            book_id="book-1",
        )

        result = ProductionPreparationService(_MultiResolver(collections)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=1,
                idempotency_key="exact-book-knowledge",
                knowledge_access_policy=access,
            )
        )

        self.assertEqual(result.report.decision, "READY")
        assert result.command is not None
        selected_cards = [
            item["asset_version_id"]
            for item in result.command.context_candidates
            if item["asset_type"] == "knowledge_card"
        ]
        self.assertEqual(selected_cards, ["knowledge-card:allowed:v1"])
        self.assertEqual(
            result.report.production_input_manifest["knowledge_access_policy"],
            access,
        )
        projected = next(
            item
            for item in result.command.context_candidates
            if item["asset_type"] == "knowledge_card"
        )
        self.assertIn("A choice changes later options", projected["safe_summary"])

    def test_canonical_chapter_freezes_protected_foundation_contracts(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "character_cast",
                "reader_promise",
            )
        }
        assets["character_cast"] = replace(
            assets["character_cast"],
            content={
                "candidate_payload": {
                    "characters": [
                        {
                            "character_id": "lin-yao",
                            "name": "林遥",
                            "aliases": ["林遥"],
                            "pronouns": ["她"],
                            "desire": "保存道路",
                            "voice": "精确克制",
                        }
                    ]
                }
            },
        )
        assets["reader_promise"] = replace(
            assets["reader_promise"],
            content={
                "candidate_payload": {
                    "reader_promise": "每章发现都造成选择、代价和反制。"
                }
            },
        )
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=1,
                idempotency_key="canonical-foundation-context",
                capability_required_asset_types=(
                    "character_cast",
                    "reader_promise",
                ),
            )
        )

        self.assertEqual(result.report.decision, "READY")
        selected = {
            item["asset_type"]: item
            for item in result.report.production_input_manifest[
                "selected_asset_versions"
            ]
        }
        self.assertEqual(
            selected["character_cast"]["content_hash"], "sha256:character_cast"
        )
        self.assertEqual(
            selected["reader_promise"]["content_hash"], "sha256:reader_promise"
        )
        self.assertEqual(
            result.command.context_version_refs["character_cast_version"],
            "version:character_cast",
        )
        self.assertEqual(
            result.command.context_version_refs["reader_promise_versions"],
            ["version:reader_promise"],
        )
        protected = {
            item["asset_type"]: item
            for item in result.command.context_candidates
            if item["asset_type"] in {"character_cast", "reader_promise"}
        }
        self.assertEqual(
            {item["context_class"] for item in protected.values()}, {"PROTECTED"}
        )

    def test_canonical_chapter_blocks_historical_unbound_character_cast(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "character_cast",
                "reader_promise",
            )
        }
        assets["character_cast"] = replace(
            assets["character_cast"],
            content={
                "candidate_payload": {
                    "characters": [
                        {
                            "character_id": "lin-yao",
                            "wound": "她曾因独断标注误导救援队",
                        }
                    ]
                }
            },
        )
        assets["reader_promise"] = replace(
            assets["reader_promise"],
            content={"candidate_payload": {"reader_promise": "有代价的发现。"}},
        )

        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=1,
                idempotency_key="historical-unbound-character",
                capability_required_asset_types=(
                    "character_cast",
                    "reader_promise",
                ),
            )
        )

        self.assertEqual(result.report.decision, "BLOCKED")
        self.assertIn(
            {
                "asset_type": "character_cast",
                "code": "CHARACTER_IDENTITY_CONTRACT_INCOMPLETE",
            },
            result.report.blocked_assets,
        )
        self.assertIsNone(result.command)

    def test_project_knowledge_pack_is_optional_unless_capability_requires_it(
        self,
    ) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
            )
        }
        service = ProductionPreparationService(_Resolver(assets))
        optional = service.prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                idempotency_key="knowledge-optional",
            )
        )
        required = service.prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                idempotency_key="knowledge-required",
                capability_required_asset_types=("knowledge_pack",),
            )
        )

        self.assertEqual(optional.report.decision, "READY")
        self.assertEqual(required.report.decision, "BLOCKED")
        self.assertIn("knowledge_pack", required.report.missing_required_asset_types)

    def test_previous_production_manifest_is_not_recursive_chapter_context(
        self,
    ) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "production_input_manifest",
            )
        }
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                idempotency_key="non-recursive-manifest",
            )
        )

        self.assertEqual(result.report.decision, "READY")
        self.assertNotIn(
            "production_input_manifest",
            {item["asset_type"] for item in result.command.context_candidates},
        )

    def test_ready_report_freezes_context_and_versions(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "world_bible",
            )
        }
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                title_override="Chapter One",
                premise_override="A costly promise.",
                idempotency_key="chapter-1",
            )
        )

        self.assertEqual(result.report.decision, "READY")
        self.assertIn("version:chapter_plan", result.report.selected_asset_version_ids)
        self.assertEqual(
            result.command.context_version_refs["chapter_plan_version"],
            "version:chapter_plan",
        )
        self.assertTrue(result.command.context_candidates)
        style_candidate = next(
            item
            for item in result.command.context_candidates
            if item["asset_type"] == "style_policy"
        )
        self.assertEqual(style_candidate["project_id"], "project-1")
        self.assertTrue(style_candidate["safe_summary"])
        self.assertIn(
            "chapter_plan",
            {item["asset_type"] for item in result.command.context_candidates},
        )
        self.assertEqual(
            result.report.production_input_manifest["platform_profile_version_id"],
            "version:platform_profile",
        )

    def test_operator_approval_is_frozen_as_evidence_only_context(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "operator_approval",
            )
        }

        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                idempotency_key="operator-approval-context",
            )
        )

        self.assertEqual(result.report.decision, "READY")
        approval = next(
            item
            for item in result.command.context_candidates
            if item["asset_type"] == "operator_approval"
        )
        self.assertEqual(approval["allowed_use"], "evidence_only")
        self.assertEqual(
            result.command.context_version_refs["operator_approval_versions"],
            "version:operator_approval",
        )

    def test_wrong_chapter_plan_is_blocked(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
            )
        }
        assets["chapter_plan"] = replace(
            assets["chapter_plan"],
            content={**assets["chapter_plan"].content, "chapter": 2},
        )
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                chapter=1,
                idempotency_key="wrong-plan",
            )
        )
        self.assertEqual(result.report.decision, "BLOCKED")
        self.assertIn(
            {"asset_type": "chapter_plan", "code": "CHAPTER_PLAN_TARGET_MISMATCH"},
            result.report.blocked_assets,
        )

    def test_second_chapter_without_canon_baseline_is_blocked_with_repair(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
            )
        }
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=2,
                idempotency_key="chapter-2",
            )
        )

        self.assertEqual(result.report.decision, "BLOCKED")
        self.assertIn("canon_snapshot", result.report.missing_required_asset_types)
        self.assertTrue(
            any("Canon" in action for action in result.report.repair_actions)
        )
        self.assertIsNone(result.command)

    def test_story_state_snapshot_is_required_for_continuing_chapter(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "canon_snapshot",
                "character_state_snapshot",
                "relationship_state_snapshot",
                "timeline_snapshot",
                "foreshadow_snapshot",
                "promise_ledger_snapshot",
                "reward_ledger_snapshot",
                "world_rule_snapshot",
                "power_state_snapshot",
            )
        }
        assets["chapter_plan"] = replace(
            assets["chapter_plan"],
            content={**assets["chapter_plan"].content, "chapter": 2},
        )

        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=2,
                idempotency_key="missing-story-state",
            )
        )

        self.assertIn(
            "story_state_snapshot", result.report.missing_required_asset_types
        )

    def test_cross_project_override_fails_closed(self) -> None:
        assets = {"chapter_plan": _asset("chapter_plan", project_id="project-2")}
        with self.assertRaisesRegex(ValueError, "cross-project"):
            ProductionPreparationService(_Resolver(assets)).prepare(
                ProductionPreparationRequest(
                    project_id="project-1",
                    workspace_id="workspace-1",
                    chapter=1,
                    explicit_asset_version_overrides={
                        "chapter_plan": "version:chapter_plan"
                    },
                    idempotency_key="chapter-1",
                )
            )

    def test_api_actor_is_not_a_trusted_principal_source(self) -> None:
        principal = TrustedPrincipalResolver(
            environment="test",
            configured_local_operator_id="trusted-local",
        ).resolve_api_principal(claimed_actor_id="attacker-supplied")

        self.assertEqual(principal.principal_id, "trusted-local")
        self.assertEqual(principal.principal_type, PrincipalType.LOCAL_OPERATOR)
        self.assertNotEqual(principal.principal_id, "attacker-supplied")
        self.assertTrue(principal.allows("chapter.authority.execute", "project-1"))
        self.assertTrue(
            principal.allows("content.operation:theme.question.create", "project-1")
        )
        self.assertTrue(
            principal.allows("story_planning.authority.execute", "project-1")
        )
        worker = TrustedPrincipalResolver(environment="test").resolve_worker_principal(
            "book-worker"
        )
        self.assertTrue(worker.allows("story_planning.authority.execute", "project-1"))
        self.assertFalse(worker.allows("story_planning.authority.approve", "project-1"))
        self.assertFalse(worker.allows("story_planning.authority.activate", "project-1"))

        formation_worker = TrustedPrincipalResolver(
            environment="test"
        ).resolve_book_formation_worker_principal("book-worker")
        self.assertEqual(formation_worker.principal_id, worker.principal_id)
        self.assertTrue(
            formation_worker.allows("story_planning.authority.approve", "project-1")
        )
        self.assertTrue(
            formation_worker.allows("story_planning.authority.activate", "project-1")
        )
        self.assertTrue(
            formation_worker.allows("story_design.authority.execute", "project-1")
        )
        self.assertFalse(formation_worker.allows("mkaos.authority.approve", "project-1"))

    def test_production_requires_configured_trusted_principal(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "trusted local operator"):
            TrustedPrincipalResolver(environment="production").resolve_api_principal()

    def test_v2_freezes_multiple_entities_inside_one_compact_story_state(self) -> None:
        required = (
            "chapter_plan",
            "style_policy",
            "quality_rubric",
            "platform_profile",
            "story_state_snapshot",
            "canon_snapshot",
        )
        collections = {kind: [_asset(kind)] for kind in required}
        collections["chapter_plan"][0] = replace(
            collections["chapter_plan"][0],
            content={**collections["chapter_plan"][0].content, "chapter": 2},
        )
        story = collections["story_state_snapshot"][0]
        entries = [
            {
                "entity_key": f"character_id=character-{index}",
                "entity_version": 1,
                "state": {"character_id": f"character-{index}", "location": "Hangzhou"},
                "source_event_id": f"narrative-event:character-{index}",
                "source_chapter": 1,
                "effective_from_chapter": 1,
                "confidence": 1.0,
                "coverage": "EXPLICIT",
                "evidence": {},
            }
            for index in (1, 2)
        ]
        collections["story_state_snapshot"][0] = replace(
            story,
            content={
                **story.content,
                "current_state": {
                    "character_state": entries,
                    "relationship_state": [],
                },
            },
        )
        result = ProductionPreparationService(_MultiResolver(collections)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=2,
                title_override="Chapter Two",
                premise_override="State carries forward.",
                idempotency_key="chapter-2-multi",
            )
        )
        self.assertEqual(result.report.decision, "READY")
        story_candidate = next(
            item
            for item in result.command.context_candidates
            if item["asset_type"] == "story_state_snapshot"
        )
        self.assertEqual(len(story_candidate["structured_facts"]), 2)
        self.assertEqual(
            {item["entity_key"] for item in story_candidate["structured_facts"]},
            {
                "character_id=character-1",
                "character_id=character-2",
            },
        )

    def test_continuing_state_and_canon_fit_frozen_draft_budget(self) -> None:
        required = (
            "chapter_plan",
            "world_bible",
            "style_policy",
            "quality_rubric",
            "platform_profile",
            "story_state_snapshot",
            "canon_snapshot",
        )
        collections = {kind: [_asset(kind)] for kind in required}
        plan = collections["chapter_plan"][0]
        collections["chapter_plan"][0] = replace(
            plan,
            content={**plan.content, "chapter": 2},
        )
        operational = {
            "approval_resolution": {"decision": "APPROVE"},
            "change_reasons": ["x" * 500],
            "model_id": "model-a",
            "provider_id": "provider-a",
            "prompt_version": "prompt-a",
            "source_revision_asset_version_id": "revision:" + "x" * 200,
        }
        story = collections["story_state_snapshot"][0]
        story_entries = [
            {
                "entity_key": f"character_id=character-{index}",
                "entity_version": 1,
                "state": {
                    "character_id": f"character-{index}",
                    "summary": "n" * 300,
                    **operational,
                },
                "source_event_id": f"narrative-event:{index}:" + "a" * 64,
                "source_chapter": 1,
                "effective_from_chapter": 1,
                "confidence": 1.0,
                "coverage": "EXPLICIT",
                "evidence": {"excerpt": "e" * 500},
                "canon_status": "APPROVED_CANON_PATCH",
            }
            for index in range(32)
        ]
        collections["story_state_snapshot"][0] = replace(
            story,
            content={
                **story.content,
                "current_state": {"character_state": story_entries},
            },
        )
        canon = collections["canon_snapshot"][0]
        collections["canon_snapshot"][0] = replace(
            canon,
            content={
                **canon.content,
                "current_facts": [
                    {
                        **story_entries[index],
                        "entity_key": f"fact_id=fact-{index}",
                        "state": {
                            "fact_id": f"fact-{index}",
                            "statement": "c" * 300,
                            **operational,
                        },
                    }
                    for index in range(15)
                ],
            },
        )

        result = ProductionPreparationService(_MultiResolver(collections)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=2,
                title_override="Chapter Two",
                premise_override="State and Canon must both continue.",
                context_token_budget=16_000,
                idempotency_key="chapter-2-budget-regression",
            )
        )
        self.assertEqual(result.report.decision, "READY")
        assert result.command is not None
        bundle = build_context_bundle(
            plan=collections["chapter_plan"][0].content,
            plan_asset_version_id=collections["chapter_plan"][0].asset_version_id,
            plan_content_hash=collections["chapter_plan"][0].content_hash,
            project_id="project-1",
            book_id="book-1",
            created_by_operation_id="operation:context-budget-regression",
            governed_candidates=[
                dict(item) for item in result.command.context_candidates
            ],
            version_refs=dict(result.command.context_version_refs),
            token_budget=16_000,
            required_asset_types=("story_state_snapshot", "canon_snapshot"),
        )
        selected_types = {
            item["asset_type"] for item in bundle["context_manifest"]["selected_inputs"]
        }
        self.assertTrue(
            {"story_state_snapshot", "canon_snapshot"}.issubset(selected_types)
        )
        self.assertLessEqual(bundle["estimated_tokens"], 16_000)

    def test_long_history_is_projected_before_context_budget_selection(self) -> None:
        required = (
            "chapter_plan",
            "style_policy",
            "quality_rubric",
            "platform_profile",
            "story_state_snapshot",
            "canon_snapshot",
        )

        def prepare(history_size: int):
            collections = {kind: [_asset(kind)] for kind in required}
            plan = collections["chapter_plan"][0]
            collections["chapter_plan"][0] = replace(
                plan,
                content={
                    **plan.content,
                    "chapter": 2,
                    "character_participation": [
                        {
                            "character_id": "hero",
                            "known_fact_ids": ["fact:target"],
                            "unknown_fact_ids": [],
                            "belief_refs": [],
                            "trajectory_refs": [],
                        }
                    ],
                },
            )
            story = collections["story_state_snapshot"][0]
            story_entries = [
                {
                    "entity_key": f"character_id={character_id}",
                    "entity_version": 1,
                    "state": {
                        "character_id": character_id,
                        "location": "Hangzhou",
                    },
                    "source_event_id": f"event:{character_id}",
                    "source_chapter": 1,
                    "effective_from_chapter": 1,
                    "confidence": 1.0,
                    "coverage": "EXPLICIT",
                    "evidence": {},
                }
                for character_id in (
                    "hero",
                    *(f"irrelevant-{index}" for index in range(history_size)),
                )
            ]
            collections["story_state_snapshot"][0] = replace(
                story,
                content={
                    **story.content,
                    "current_state": {"character_state": story_entries},
                    "estimated_tokens": 10_000_000,
                },
            )
            canon = collections["canon_snapshot"][0]
            canon_entries = [
                {
                    **story_entries[0],
                    "entity_key": f"fact_id={fact_id}",
                    "state": {"fact_id": fact_id, "statement": "bounded truth"},
                }
                for fact_id in (
                    "fact:target",
                    *(f"fact:irrelevant-{index}" for index in range(history_size)),
                )
            ]
            collections["canon_snapshot"][0] = replace(
                canon,
                content={
                    **canon.content,
                    "current_facts": canon_entries,
                    "estimated_tokens": 10_000_000,
                },
            )
            result = ProductionPreparationService(_MultiResolver(collections)).prepare(
                ProductionPreparationRequest(
                    project_id="project-1",
                    workspace_id="workspace-1",
                    book_id="book-1",
                    chapter=2,
                    title_override="Chapter Two",
                    premise_override="Only task-relevant state enters working context.",
                    context_token_budget=4_000,
                    idempotency_key=f"bounded-history-{history_size}",
                )
            )
            self.assertEqual(result.report.decision, "READY")
            assert result.command is not None
            bundle = build_context_bundle(
                plan=collections["chapter_plan"][0].content,
                plan_asset_version_id=plan.asset_version_id,
                plan_content_hash=plan.content_hash,
                project_id="project-1",
                book_id="book-1",
                created_by_operation_id=f"operation:bounded-history-{history_size}",
                governed_candidates=[
                    dict(item) for item in result.command.context_candidates
                ],
                version_refs=dict(result.command.context_version_refs),
                token_budget=4_000,
                required_asset_types=("story_state_snapshot", "canon_snapshot"),
            )
            state_candidates = {
                item["asset_type"]: item
                for item in result.command.context_candidates
                if item["asset_type"] in {"story_state_snapshot", "canon_snapshot"}
            }
            return state_candidates, bundle

        light, light_bundle = prepare(1)
        heavy, heavy_bundle = prepare(3_000)

        self.assertEqual(light, heavy)
        self.assertEqual(
            light_bundle["estimated_tokens"], heavy_bundle["estimated_tokens"]
        )
        self.assertEqual(len(heavy["story_state_snapshot"]["structured_facts"]), 1)
        self.assertEqual(len(heavy["canon_snapshot"]["structured_facts"]), 1)

    def test_current_collection_snapshot_is_not_blocked_by_historical_versions(
        self,
    ) -> None:
        state_types = ("story_state_snapshot", "canon_snapshot")
        collections = {
            kind: [_asset(kind)]
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                *state_types,
            )
        }
        collections["chapter_plan"][0] = replace(
            collections["chapter_plan"][0],
            content={**collections["chapter_plan"][0].content, "chapter": 3},
        )
        for state_type in state_types:
            current = collections[state_type][0]
            collections[state_type][0] = replace(
                current,
                asset_id=f"asset:{state_type}:chapter-2",
                asset_version_id=f"version:{state_type}:chapter-2",
                content={
                    **current.content,
                    "chapter": 2,
                    "accepted_through_chapter": 2,
                },
            )
        for state_type in state_types:
            historical = _asset(state_type)
            collections[state_type].append(
                replace(
                    historical,
                    asset_id=f"asset:{state_type}:chapter-1",
                    asset_version_id=f"version:{state_type}:chapter-1",
                    content={**historical.content, "chapter": 1},
                )
            )

        result = ProductionPreparationService(_MultiResolver(collections)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=3,
                title_override="Chapter Three",
                premise_override="Current state carries forward after replan.",
                idempotency_key="chapter-3-current-state",
            )
        )

        self.assertEqual(result.report.decision, "READY")
        self.assertEqual(result.report.blocked_assets, ())
        for state_type in state_types:
            self.assertIn(
                f"version:{state_type}:chapter-2",
                result.report.selected_asset_version_ids,
            )
            self.assertNotIn(
                f"version:{state_type}:chapter-1",
                result.report.selected_asset_version_ids,
            )

    def test_legacy_per_kind_snapshots_cannot_replace_compact_story_state(self) -> None:
        assets = {
            kind: _asset(kind)
            for kind in (
                "chapter_plan",
                "style_policy",
                "quality_rubric",
                "platform_profile",
                "canon_snapshot",
                "character_state_snapshot",
                "timeline_snapshot",
                "foreshadow_snapshot",
                "promise_ledger_snapshot",
                "reward_ledger_snapshot",
                "world_rule_snapshot",
                "power_state_snapshot",
            )
        }
        assets["chapter_plan"] = replace(
            assets["chapter_plan"],
            content={**assets["chapter_plan"].content, "chapter": 2},
        )
        result = ProductionPreparationService(_Resolver(assets)).prepare(
            ProductionPreparationRequest(
                project_id="project-1",
                workspace_id="workspace-1",
                book_id="book-1",
                chapter=2,
                idempotency_key="missing-relationship",
            )
        )
        self.assertIn(
            "story_state_snapshot", result.report.missing_required_asset_types
        )
        self.assertNotIn(
            "relationship_state_snapshot", result.report.missing_required_asset_types
        )

    def test_stage_profiles_have_distinct_allowed_and_required_contracts(self) -> None:
        draft = STAGE_PROFILES["draft"]
        review = STAGE_PROFILES["review"]
        quality = STAGE_PROFILES["quality"]

        self.assertNotIn("review_rule", draft.allowed_asset_types)
        self.assertIn("review_rule", review.allowed_asset_types)
        self.assertIn("structural_quality_report", draft.allowed_asset_types)
        self.assertIn("structural_quality_report", draft.evidence_only_types)
        self.assertIn("structural_quality_report", quality.allowed_asset_types)
        self.assertIn("draft_version", review.required_asset_types)
        self.assertIn("re_review_report", quality.required_asset_types)


if __name__ == "__main__":
    unittest.main()
