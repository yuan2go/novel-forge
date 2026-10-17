from copy import deepcopy
from tests.integration.capability_pack_postgres_support import frozen_provider_task_view
import json
import os
from pathlib import Path

import pytest

from novel_forge.modules.book_authority.production import SubmitBookChapterCommand
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.execution_gateway import (
    default_chapter_fixture_response,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_task_view,
)
from novel_forge.modules.mkaos_authority.application import (
    MkaosAuthorityApplication,
    ApproveKnowledgeCandidateCommand,
)
from novel_forge.modules.mkaos_authority.craft import (
    CRAFT_ORIGINAL_POLICY,
    core_catalog_hash,
    craft_hash,
)
from novel_forge.modules.mkaos_authority.craft_authoring import AuthorCoreCraftCommand
from novel_forge.modules.mkaos_authority.craft_selection import (
    build_craft_strategy,
    DEFAULT_CRAFT_POLICY,
    craft_candidate_assessment,
    validate_craft_policy,
)
from novel_forge.modules.production_preparation.contracts import ResolvedProductionAsset
from novel_forge.modules.production_preparation.service import (
    ProductionPreparationService,
)
from novel_forge.modules.review.craft import (
    craft_review_targets,
    PRESERVATION_DIMENSIONS,
    SIDE_EFFECTS,
)
from novel_forge.modules.review.diagnostics import prose_hash
from novel_forge.modules.review.prose_window import (
    PRESERVATION_DIMENSIONS as CROSS_DIMENSIONS,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_cross_chapter_prose_review_postgres import (
    make_book,
    ReceiptCommitLoss,
)


BROKEN = "他很有担当，特别有担当，大家都觉得他有担当。"
REPAIRED = "他把仅有的返程木牌推到证人手边，收回手时，守门人已经划掉了他的名字。"


class CraftTransport:
    mechanism_id = "choice-exposes-value"
    policy = DEFAULT_CRAFT_POLICY
    broken = BROKEN
    repaired = REPAIRED

    def __init__(self, loss):
        self.loss, self.lost = loss, False
        self.calls = []
        self.card_id = ""

    def checkpoint(self, point):
        if (
            self.loss
            and not self.lost
            and point == "after_provider_success"
            and self.calls
            and self.calls[-1][0] == "review"
        ):
            self.lost = True
            raise ReceiptCommitLoss()

    def prepare(self, project, workspace, candidates):
        app = MkaosAuthorityApplication(
            DATABASE_URL,
            application_build_id="craft-chapter-engineering",
            commit_sha="e" * 40,
        )
        authored = app.execute_core_craft(
            AuthorCoreCraftCommand(
                project,
                workspace,
                self.mechanism_id,
                core_catalog_hash(),
                "craft-operator",
                f"{project}:craft",
                f"trace:{project}",
                f"correlation:{project}",
            )
        )
        approved = app.execute_approval(
            ApproveKnowledgeCandidateCommand(
                project,
                workspace,
                authored["asset_version_id"],
                CRAFT_ORIGINAL_POLICY + ":" + core_catalog_hash(),
                "Original hypothesis approved for controlled engineering use; fixture planning is not native planning qualification.",
                "craft-operator",
                f"{project}:craft-approval",
                f"trace:{project}",
                f"correlation:{project}",
            )
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            document = uow.repositories.asset_documents.require(
                project_id=project, asset_version_id=approved["asset_version_id"]
            )
        self.card_id = document.asset_version_id
        self.card = document
        self.selection = {
            "selection_digest": craft_hash(
                {
                    "card": document.asset_version_id,
                    "hash": document.content_hash,
                    "evidence": "FIXTURE_PLANNING_LINEAGE",
                }
            ),
            "craft_policy": self.policy,
            "selected": [
                {
                    "knowledge_card_asset_version_id": document.asset_version_id,
                    "content_hash": document.content_hash,
                    "selected_content": document.content["abstract_content"],
                }
            ],
        }

        def transform(content):
            content = deepcopy(content)
            site = {
                "target_pointer": "/scene_plan/0/goal",
                "craft_role": "PRIMARY",
                "craft_sequence": 1,
                "intended_reader_effect": "看见人物为了证人放弃安全而不是听作者评价",
                "preservation_requirements": [
                    "保留公开承诺、证人、关闭退路的结果与未知事实边界"
                ],
                "verification_checks": ["既有选择具有可见的机会成本"],
                "realization_excerpt": content["scene_plan"][0]["goal"],
                "expected_application": "把既定代价落实为一次物件处置",
            }
            if self.mechanism_id == "meaningful-callback":
                site.update(intended_reader_effect="通过同一称呼的语气和承担变化看到人物关系推进",
                    preservation_requirements=["保留过桥费旧称呼、交出木牌的选择与被划掉名字的代价"],
                    verification_checks=["回调改变说话权和承担关系，不靠作者宣布好笑"],
                    expected_application="在既有选择后让旧称呼承载共同承担，幽默不冲淡代价")
            if self.mechanism_id == "exchange-response-cost":
                site.update(intended_reader_effect="看清防守救下证人与失去退路之间的动作因果",
                    preservation_requirements=["保留来刀、证人避险与木牌损坏的既定结果"],
                    verification_checks=["攻势引发针对性回应，回应具有可定位损耗"],
                    expected_application="用一次抬剑偏转写清救人与木牌损失的同一因果链")
            if self.mechanism_id == "spatial-anchor":
                site.update(intended_reader_effect="追踪双方距离、桥头出口和阻挡",
                    verification_checks=["既定通路与移动后位置可定位"],
                    expected_application="在既定行动中给出可观察的空间锚点")
            translation = {
                "knowledge_card_asset_version_id": document.asset_version_id,
                "decision": "ADAPT",
                "usage_role": "MECHANISM",
                "use_sites": [site],
                "rationale": "Original fixture binds the planned choice; not production planning qualification",
                "prerequisite_resolution": "The approved fixture scene supplies the choice, witness and existing irreversible cost",
            }
            content["knowledge_translations"] = [translation]
            content["craft_strategy"] = build_craft_strategy(content, self.selection)
            self.strategies = getattr(self, "strategies", {})
            self.strategies[int(content.get("chapter") or 1)] = content["craft_strategy"]
            if int(content.get("chapter") or 1) == 1:
                self.strategy = content["craft_strategy"]
                projection = {
                    "translation": translation,
                    "craft_uses": self.strategy["uses"],
                    "craft_strategy_digest": self.strategy["strategy_digest"],
                }
                candidate = ProductionPreparationService._context_candidate(
                    ResolvedProductionAsset(
                        project,
                        document.asset_id,
                        document.asset_version_id,
                        "knowledge_card",
                        document.content_hash,
                        document.content,
                        "ELIGIBLE",
                        "FIXTURE_PLANNING_CONTROL",
                    ),
                    evidence_only_types=(),
                    task_narrative_projection={},
                    chapter=1,
                    book_id=f"book:{project}",
                    accepted_boundary={},
                    knowledge_projection=projection,
                )
                candidates.append(candidate)
            return content

        return transform

    def check(self, draft, status):
        target = craft_review_targets(draft)[0]
        sentence = self.broken if status == "FAILED" else self.repaired
        start = draft["text"].index(sentence)
        evidence = {"start": start, "end": start + len(sentence), "quote": sentence}
        codes = ["CRAFT_CHOICE_REALIZATION"] if status == "FAILED" else []
        return {
            "use_id": target["use_id"],
            "effect_status": status,
            "evidence": evidence,
            "reason": "Original scripted contrast control; no independent reader measurement.",
            "signals_checked": [
                "Scripted selected mechanism realization matches its located control span"
            ],
            "issue_codes": codes,
            "side_effects": [
                {
                    "kind": kind,
                    "status": "PRESENT"
                    if kind == "ARTIFICIALITY" and codes
                    else "CLEAR",
                    "evidence": evidence,
                    "reason": "Scripted control contrasts repeated evaluation with a visible existing cost.",
                    "issue_codes": codes if kind == "ARTIFICIALITY" else [],
                }
                for kind in SIDE_EFFECTS
            ],
        }

    def __call__(self, stage, inputs):
        self.calls.append((stage, deepcopy(inputs)))
        if stage == "canon_extraction" and inputs.get("canon_context_projection") == "canon-source-context.v1":
            from tests.integration.synthesis_production_support import scripted_chapter_response
            result = scripted_chapter_response(stage, inputs)
        else:
            result = default_chapter_fixture_response(stage, inputs)
        if stage == "draft":
            assert inputs["realization_contract"]["craft_strategy"] == self.strategies[inputs["plan"]["chapter"]]
            result["scene_artifacts"][-1]["text"] += " " + self.broken
            result["text"] = "\n\n".join(
                item["text"] for item in result["scene_artifacts"]
            )
        elif stage == "review":
            draft = inputs["draft"]
            check = self.check(draft, "FAILED")
            result.update(
                score=65,
                craft_checks=[check],
                preservation_checks=[],
                issues=[
                    {
                        "code": "CRAFT_CHOICE_REALIZATION",
                        "severity": "minor",
                        "message": "Repeated evaluation obscures the chosen character effect",
                        "category": "CRAFT_EFFECT",
                        "judgment_kind": "SEMANTIC_CONFLICT",
                        "confidence": "HIGH",
                        "interpretation": "CONTINUITY_PROBLEM",
                        "repair": {"root_cause": "LANGUAGE", "problem_owner": "PROSE",
                            "repair_scope": "LOCAL_PROSE",
                            "revision_goal": "Realize the adopted use_site at the located span",
                            "preserve": ["Frozen scene choices, facts and all other prose"],
                            "resolution_criteria": ["The selected mechanism is visible in its frozen use_site"]},
                        "lineage_code": None,
                        "supporting_evidence": [],
                        "evidence": {
                            **check["evidence"],
                            "asset_version_id": inputs[
                                "target_candidate_asset_version_id"
                            ],
                            "text_hash": prose_hash(draft["text"]),
                        },
                        "violated_constraint": "Frozen adopted Craft use: " + craft_review_targets(draft)[0]["use_id"],
                        "revision_goal": "Replace evaluation with the already planned cost",
                        "preserve": [
                            "Planned choice, facts, POV, voice, knowledge and all other prose"
                        ],
                        "acceptance_criteria": [
                            "Existing cost appears as an action rather than repeated author evaluation"
                        ],
                    }
                ],
            )
        elif stage == "revision":
            issue = inputs["review"]["issues"][0]
            result = {
                "resolved_issue_codes": [issue["code"]],
                "edits": [
                    {
                        "quote": issue["evidence_locator"]["quote"],
                        "replacement": self.repaired,
                        "issue_codes": [issue["code"]],
                    }
                ],
            }
        elif stage == "rereview":
            check = self.check(inputs["revision"], getattr(self, "final_effect_status", "ACHIEVED"))
            evidence = check["evidence"]
            result.update(
                score=95,
                craft_checks=[check],
                issues=[],
                resolution_checks=[
                    {
                        "code": issue["code"],
                        "status": "RESOLVED",
                        "preservation": "PRESERVED",
                        "evidence": evidence,
                        "supporting_evidence": [],
                        "reason": "Scripted local edit satisfies the stated control criterion.",
                    }
                    for issue in inputs["review"]["issues"]
                ],
                preservation_checks=[
                    {
                        "dimension": dim,
                        "status": "PRESERVED",
                        "evidence": evidence,
                        "reason": "Original controlled edit preserves frozen scene commitments.",
                    }
                    for dim in CROSS_DIMENSIONS
                ],
                craft_preservation_checks=[
                    {
                        "dimension": dim,
                        "status": "PRESERVED",
                        "evidence": evidence,
                        "reason": "Original controlled edit preserves frozen scene commitments.",
                    }
                    for dim in PRESERVATION_DIMENSIONS
                ],
            )
        return result


@pytest.mark.parametrize("receipt_loss,mechanism,final_status", [(False, "choice-exposes-value", "ACHIEVED"), (True, "choice-exposes-value", "ACHIEVED"),
    (False, "meaningful-callback", "ACHIEVED"), (False, "exchange-response-cost", "ACHIEVED"),
    (False, "meaningful-callback", "UNCERTAIN")])
def test_native_craft_card_chapter_provider_targeted_repair_acceptance_and_receipt_replay(
    tmp_path, receipt_loss, mechanism, final_status
):
    transport = CraftTransport(receipt_loss)
    transport.final_effect_status = final_status
    transport.mechanism_id = mechanism
    if mechanism == "meaningful-callback":
        transport.broken = "先前证人叫他铁算盘，是讥他舍不得过桥费。如今他交出返程木牌，守门人划掉他的名字。证人很感动，两人关系更近了，这个称呼也变得好笑。"
        transport.repaired = "先前证人叫他铁算盘，是讥他舍不得过桥费。他把仅有的返程木牌推过去，守门人在名册上划掉他的名字。证人把行囊挪到他身边，又叫了一声铁算盘：回城的账先欠着，我认。"
    elif mechanism == "exchange-response-cost":
        transport.broken = "桥头来刀，他与守门人过了几招，证人躲开了，返程木牌也坏了。"
        transport.repaired = "守门人的刀越过桥柱劈向证人，他抬剑压住刀脊，给证人让出半步；刀锋顺剑滑落，削断他腰间唯一的返程木牌。"

    project, authority, chapter, principal, worker, book, candidates, plans, restart = (
        make_book(tmp_path, transport, prepare_plans=transport.prepare)
    )
    plan = plans[1]
    command = SubmitBookChapterCommand(
        book_run_id=book.book_run_id,
        chapter_number=1,
        title="Craft control",
        premise="A choice has an irreversible cost.",
        chapter_plan_asset_version_id=plan["asset_version_id"],
        chapter_plan_content_hash=plan["content_hash"],
        context_token_budget=64000,
        context_candidates=tuple(
            plan if item["asset_type"] == "chapter_plan" else item
            for item in candidates
        ),
        preparation_report={
            "stage_context_profile_versions": {"draft": "draft-context-profile-v4"},
                "stage_context_token_budgets": {
                stage: 64000
                for stage in ("memo", "draft", "review", "revision", "rereview")
            }
        },
    )
    dispatched = authority.submit_chapter(command, principal=principal)
    interrupted = None
    for _ in range(len(ChapterNode) * 3):
        try:
            tick = chapter.scheduler(principal=worker).tick(
                project_id=project,
                root_operation_id=dispatched["chapter_root_operation_id"],
            )
        except ReceiptCommitLoss:
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    "SELECT external_effect_id, request_payload, (SELECT receipt_id FROM authority_external_effect_dispatch dispatch WHERE dispatch.external_effect_id=effect.external_effect_id AND receipt_id <> '') FROM authority_external_effect effect WHERE project_id=%s AND capability='model.review' AND status='SUCCEEDED'",
                    [project],
                )
                interrupted = uow.cursor.fetchone()
                assert (
                    interrupted[1]["input"]["draft"]["realization_contract"][
                        "craft_strategy"
                    ]
                    == transport.strategy
                )
                uow.cursor.execute(
                    "UPDATE authority_lease_acquisition lease SET expires_at=acquired_at+INTERVAL '1 microsecond' FROM authority_attempt attempt JOIN authority_operation operation USING(operation_id) WHERE lease.attempt_id=attempt.attempt_id AND operation.project_id=%s AND operation.definition_name='chapter.review.evaluate' AND lease.status='HELD'",
                    [project],
                )
                uow.commit()
            chapter = restart()
            continue
        if tick.saga_status == "SUCCEEDED":
            break
    assert tick.saga_status == "SUCCEEDED"
    authority.reconcile_chapter(dispatched["chapter_request_id"])
    from novel_forge.modules.mkaos_authority.runtime_usage import list_accepted_craft_usage
    assert list_accepted_craft_usage(DATABASE_URL, project_id=project, book_id=f"book:{project}") == []
    authority.accept_chapter(dispatched["chapter_request_id"], principal=principal)
    usage = list_accepted_craft_usage(DATABASE_URL, project_id=project, book_id=f"book:{project}")
    assert len(usage) == 1 and usage[0]["effect_status"] == final_status
    assert usage[0]["evidence"]["quote"] == transport.repaired
    assert list_accepted_craft_usage(DATABASE_URL, project_id=project, book_id=f"book:{project}") == usage
    if final_status == "UNCERTAIN":
        next_selection = craft_candidate_assessment(transport.strategy["uses"][0]["mechanism"],
            context={"chapter_number": 2, "scene_goal": transport.strategy["uses"][0]["mechanism"]["narrative_problem"]},
            recent_usage=usage, policy=DEFAULT_CRAFT_POLICY)
        assert next_selection["rejection_reason"] == ""
        assert next_selection["budget_assessment"]["frequency"] == 0
        assert next_selection["budget_assessment"]["realization_cautions"] == usage
        assert "CRAFT_VARIATION_BONUS" not in next_selection["match_reasons"]
    workspace = chapter.query.require_workspace(
        project_id=project, root_operation_id=dispatched["chapter_root_operation_id"]
    )
    assert workspace["accepted_manuscript"]["status"] == "EXACT_ACCEPTANCE_BOUND"
    assert workspace["acceptance"]["accepted_through_chapter"] == 1
    accepted = next(
        asset
        for asset in workspace["artifacts"]["candidates"]
        if asset["asset_type"] == "best_draft_candidate"
    )
    assert (
        transport.repaired in accepted["content"]["text"]
        and transport.broken not in accepted["content"]["text"]
    )
    checks = workspace["craft_trace"]["effect_observations"]
    assert any(check["effect_status"] == "FAILED" for check in checks)
    assert any(
        check["effect_status"] == final_status and check["accepted_lineage"]
        for check in checks
    )
    assert all(not check["reader_effect_proven"] for check in checks)
    assert all(check["evidence_class"] == "FIXTURE_SEMANTIC_REVIEW" for check in checks)
    memo = next(
        asset
        for asset in workspace["artifacts"]["memo"]
        if asset["asset_type"] == "chapter_memo"
    )
    assert memo["content"]["craft_strategy"] == transport.strategy
    draft_inputs = next(inputs for stage, inputs in transport.calls if stage == "draft")
    assert len(draft_inputs["realization_contract"]["craft_strategy"]["uses"]) == 1
    assert (
        draft_inputs["realization_contract"]["craft_strategy"]["uses"][0][
            "knowledge_card_asset_version_id"
        ]
        == transport.card_id
    )
    assert len([1 for stage, _ in transport.calls if stage == "review"]) == 1
    assert bool(interrupted) == receipt_loss
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT external_effect_id, request_payload, (SELECT receipt_id FROM authority_external_effect_dispatch dispatch WHERE dispatch.external_effect_id=effect.external_effect_id AND receipt_id <> '') FROM authority_external_effect effect WHERE project_id=%s AND capability='model.review'",
            [project],
        )
        effect = uow.cursor.fetchone()
        if receipt_loss:
            assert effect == interrupted
        binding = effect[1]["_production_execution"]["capability_runtime"]
        assert binding["output_schema_ref"] == "schema:chapter-provider-output:review:cross-chapter-v6:narrative-craft-v2:delivered-card-scope-v1:repair-scope-v1"
        admission = uow.repositories.asset_documents.require(
            project_id=project,
            asset_version_id=binding["provider_admission_asset_version_id"],
        ).content["contract"]
        assert admission["prompt_materialization"]["provider_view"]["component_hashes"][
            "provider_task_view"
        ] == craft_hash(frozen_provider_task_view(uow, project, effect[1]))
        uow.cursor.execute(
            "SELECT capability, request_payload FROM authority_external_effect WHERE project_id=%s AND capability IN ('model.memo','model.draft','model.revision','model.rereview')",
            [project],
        )
        for capability, payload in uow.cursor.fetchall():
            stage = capability.split(".")[1]
            admitted_binding = payload["_production_execution"]["capability_runtime"]
            admitted = uow.repositories.asset_documents.require(
                project_id=project,
                asset_version_id=admitted_binding[
                    "provider_admission_asset_version_id"
                ],
            ).content["contract"]
            task_view = frozen_provider_task_view(uow, project, payload)
            assert admitted["prompt_materialization"]["provider_view"][
                "component_hashes"
            ]["provider_task_view"] == craft_hash(task_view), (
                stage, admitted_binding["output_schema_ref"]
            )
            assert transport.strategy["uses"][0]["mechanism_id"] in json.dumps(
                task_view
            )
            assert "unfinished-action-hook" not in json.dumps(task_view)
        uow.cursor.execute(
            "SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s",
            [effect[0]],
        )
        assert uow.cursor.fetchone() == (1,)
        uow.cursor.execute(
            "SELECT count(*) FROM authority_budget_reservation WHERE project_id=%s AND operation_id=(SELECT operation_id FROM authority_external_effect WHERE external_effect_id=%s) AND status='SETTLED'",
            [project, effect[0]],
        )
        assert uow.cursor.fetchone() == (1,)
    assert "SOURCE_ABSTRACTION" not in json.dumps(transport.strategy)
    if evidence_dir := os.environ.get("NOVEL_FORGE_CRAFT_TEST_EVIDENCE_DIR"):
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        Path(evidence_dir, f"craft-{mechanism}-{final_status}-receipt-loss-{receipt_loss}.json").write_text(json.dumps({
            "evidence_class": "SCRIPTED_NATIVE_POSTGRESQL_INTEGRATION",
            "actual_real_model_calls": 0, "actual_human_evaluations": 0,
            "reader_effect_proven": False, "project_id": project,
            "planned_strategy": transport.strategy, "chapter_plan": plan,
            "original_span": transport.broken, "revised_accepted_span": transport.repaired,
            "accepted_manuscript": workspace["accepted_manuscript"],
            "acceptance": workspace["acceptance"], "accepted_draft": accepted,
            "craft_trace": workspace["craft_trace"], "accepted_usage": usage,
            "replayed_review_effect_unchanged": bool(interrupted),
            "review_effect_id": effect[0], "review_receipt_id": effect[2],
            "review_dispatch_count": 1, "review_settled_reservation_count": 1,
        }, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


class JointCraftTransport(CraftTransport):
    def __call__(self, stage, inputs):
        from tests.integration.test_cross_chapter_prose_review_postgres import (
            HISTORY, BROKEN as CONTINUITY_BROKEN, REPAIRED as CONTINUITY_REPAIRED,
            ProseTransport,
        )
        if stage == "revision":
            self.calls.append((stage, deepcopy(inputs)))
            result = {"resolved_issue_codes": [], "edits": []}
            for issue in inputs["review"]["issues"]:
                replacement = (self.repaired if issue["category"] == "CRAFT_EFFECT"
                               else CONTINUITY_REPAIRED)
                result["resolved_issue_codes"].append(issue["code"])
                result["edits"].append({"quote": issue["evidence_locator"]["quote"],
                                        "replacement": replacement, "issue_codes": [issue["code"]]})
            return result
        result = super().__call__(stage, inputs)
        if stage == "draft":
            result["scene_artifacts"][-1]["text"] += " " + (HISTORY if inputs["plan"]["chapter"] == 1 else CONTINUITY_BROKEN)
            result["text"] = "\n\n".join(item["text"] for item in result["scene_artifacts"])
        if stage == "review" and inputs["cross_chapter_window"]["sources"]:
            result["issues"].extend(ProseTransport()(stage, inputs)["issues"])
        if stage == "rereview":
            for check in result["resolution_checks"]:
                prior = next(issue for issue in inputs["review"]["issues"] if issue["code"] == check["code"])
                if prior.get("supporting_evidence"):
                    check["supporting_evidence"] = prior["supporting_evidence"]
                    start = inputs["revision"]["text"].index(CONTINUITY_REPAIRED)
                    check["evidence"] = {"start": start, "end": start + len(CONTINUITY_REPAIRED), "quote": CONTINUITY_REPAIRED}
        return result


class ContinuousSpatialTransport(JointCraftTransport):
    mechanism_id = "spatial-anchor"
    policy = validate_craft_policy({"schema_version": "narrative-craft-budget.v2"})
    broken = "他冲向敌人，又退了几步，回头时出口已被挡住。"
    repaired = "他由西桥头向东踏出两步，横剑退回桥柱内侧；守门人从他右肩后堵住西岸出口。"


@pytest.mark.parametrize("continuous_spatial", [False, True])
def test_same_chapter_combines_accepted_history_and_adopted_craft_through_book_acceptance(tmp_path, continuous_spatial):
    from tests.integration.test_cross_chapter_prose_review_postgres import REPAIRED as CONTINUITY_REPAIRED

    transport = ContinuousSpatialTransport(False) if continuous_spatial else JointCraftTransport(False)
    project, authority, chapter, principal, worker, book, candidates, plans, _ = make_book(
        tmp_path, transport, prepare_plans=transport.prepare)
    for number in (1, 2):
        if number == 2 and continuous_spatial:
            from novel_forge.modules.mkaos_authority.runtime_usage import list_accepted_craft_usage
            from novel_forge.modules.mkaos_authority.domain import NarrativeIntelligenceNeed, select_narrative_intelligence

            recent = tuple(list_accepted_craft_usage(DATABASE_URL, project_id=project, book_id=f"book:{project}"))
            assert len(recent) == 1 and recent[0]["usage_basis"] == "ACCEPTED_PROSE_REVIEW"
            assert recent[0]["evidence"]["quote"] == transport.repaired
            assert recent and all(use["acceptance_id"] and use["review_content_hash"] and use["chapter"] == 1 for use in recent)
            context = {"chapter_number": 2, "scene_goal": ["交战位置与通路难以想象，连续战斗仍须交代距离和出口"]}
            mechanism = transport.card.content["abstract_content"]["craft_mechanism"]
            assert craft_candidate_assessment(mechanism, context=context, recent_usage=recent,
                policy=DEFAULT_CRAFT_POLICY)["rejection_reason"] == "CRAFT_COOLDOWN"
            selected = select_narrative_intelligence(NarrativeIntelligenceNeed(scope="SCENE", target_stage="chapter_plan.generate",
                craft_context=context, craft_policy=transport.policy, recent_craft_usage=recent),
                ({"asset_version_id": transport.card_id, "content_hash": transport.card.content_hash, "content": transport.card.content},))
            assert selected["selected"][0]["knowledge_card_asset_version_id"] == transport.card_id
            budget = selected["selected"][0]["craft_assessment"]["budget_assessment"]
            assert budget["in_cooldown"] and not budget["temporal_budget_applied"]
            assert budget["creative_benefit"] == "NOT_PROVEN"
        plan = plans[number]
        dispatched = authority.submit_chapter(SubmitBookChapterCommand(
            context_token_budget=128000, book_run_id=book.book_run_id, chapter_number=number, title="双源修订", premise="既定代价不可无因消失。",
            chapter_plan_asset_version_id=plan["asset_version_id"], chapter_plan_content_hash=plan["content_hash"],
            context_candidates=tuple(plan if item["asset_type"] == "chapter_plan" else item for item in candidates),
            preparation_report={"stage_context_profile_versions": {"draft": "draft-context-profile-v4"},
                "stage_context_token_budgets": {stage: 64000 for stage in ("memo", "draft", "review", "revision", "rereview")}},
        ), principal=principal)
        for _ in range(len(ChapterNode) * 3):
            tick = chapter.scheduler(principal=worker).tick(project_id=project, root_operation_id=dispatched["chapter_root_operation_id"])
            if tick.saga_status == "SUCCEEDED":
                break
        assert tick.saga_status == "SUCCEEDED"
        authority.reconcile_chapter(dispatched["chapter_request_id"])
        authority.accept_chapter(dispatched["chapter_request_id"], principal=principal)
    workspace = chapter.query.require_workspace(project_id=project, root_operation_id=dispatched["chapter_root_operation_id"])
    selected = next(item for item in workspace["artifacts"]["candidates"] if item["asset_type"] == "best_draft_candidate")
    assert transport.repaired in selected["content"]["text"] and CONTINUITY_REPAIRED in selected["content"]["text"]
    diagnoses = workspace["artifacts"]["diagnoses"]
    review = next(item["content"] for item in diagnoses if item["asset_type"] == "review_report")
    after = next(item["content"] for item in diagnoses if item["asset_type"] == "re_review_report")
    assert {issue["category"] for issue in review["issues"]} == {"CRAFT_EFFECT", "CAUSAL_CARRYOVER"}
    assert set(after["resolved_issue_codes"]) == {issue["code"] for issue in review["issues"]}
    assert after["cross_chapter_window"] == review["cross_chapter_window"]
    assert after["craft_checks"][0]["knowledge_card_asset_version_id"] == transport.card_id
    assert workspace["acceptance"]["accepted_through_chapter"] == 2
    if continuous_spatial:
        assert all(strategy["policy"] == transport.policy for strategy in transport.strategies.values())
        assert all(inputs["realization_contract"]["craft_strategy"]["policy"] == transport.policy for stage, inputs in transport.calls if stage == "draft")
        assert all(inputs["draft"]["realization_contract"]["craft_strategy"]["policy"] == transport.policy for stage, inputs in transport.calls if stage == "review")
        assert all(not item["reader_effect_proven"] for item in workspace["craft_trace"]["effect_observations"])
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT request_payload FROM authority_external_effect WHERE project_id=%s AND capability='model.rereview' ORDER BY created_at", [project])
        payload = uow.cursor.fetchall()[-1][0]
        task = build_provider_task_view("rereview", payload["input"])
        assert task["prose_comparison"]["original"]["text"] == payload["input"]["original_draft"]["text"]
        assert task["craft_review_targets"] and task["cross_chapter_window"]["sources"]
        binding = payload["_production_execution"]["capability_runtime"]
        admission = uow.repositories.asset_documents.require(project_id=project, asset_version_id=binding["provider_admission_asset_version_id"]).content["contract"]
        assert admission["prompt_materialization"]["provider_view"]["component_hashes"]["provider_task_view"] == craft_hash(frozen_provider_task_view(uow, project, payload))


class JointQualityCorrectionTransport(JointCraftTransport):
    def __init__(self):
        super().__init__(False)
        self.quality_calls = 0

    def prepare(self, project, workspace, candidates):
        candidates[:] = [candidate for candidate in candidates if candidate["asset_type"] != "longform_quality_report"]
        return super().prepare(project, workspace, candidates)

    def __call__(self, stage, inputs):
        if stage == "revision" and inputs.get("quality_edit_contract"):
            self.calls.append((stage, deepcopy(inputs)))
            scope = inputs["quality_edit_contract"]
            located = scope["permitted_ranges"][0]
            span = located["evidence_locator"]
            replacement = span["quote"] + "（原地付出代价）"
            return {"resolved_issue_codes": [],
                "edits": [{"quote": span["quote"], "replacement": replacement, "issue_codes": [located["code"]]}]}
        result = super().__call__(stage, inputs)
        if stage == "quality_longform" and inputs["revision"]["chapter"] == 2:
            self.quality_calls += 1
            if self.quality_calls == 1:
                row = next(item for item in result["dimensions"] if item["dimension"] == "timeline_consistency")
                row.update(gate_status="FAILED", score=30, evidence_locations=[{"start": 0, "end": 8, "claim": "Fixture bounded Quality correction location"}],
                    issue_codes=["QUALITY_CAUSAL_SCOPE_FIXTURE"], revision_strategies=["Clarify the local cost without replacing the scene"])
        if stage == "rereview" and inputs["revision"].get("quality_edit_contract"):
            result["quality_resolution_checks"] = [{"observation": item, "status": "SATISFIED", "preservation": "PRESERVED",
                "evidence": {"start": 0, "end": 18, "quote": inputs["revision"]["text"][:18]},
                "reason": "Fixture only: corrected local expression keeps frozen Craft and historical cost."}
                for item in inputs["revision"]["quality_action_observations"]]
        return result


def test_joint_quality_correction_uses_selected_original_frozen_ranges_and_explicit_quality_checks(tmp_path):
    from tests.integration.test_cross_chapter_prose_review_postgres import REPAIRED as CONTINUITY_REPAIRED
    transport = JointQualityCorrectionTransport()
    project, authority, chapter, principal, worker, book, candidates, plans, _ = make_book(tmp_path, transport, prepare_plans=transport.prepare)
    for number in (1, 2):
        plan = plans[number]
        dispatched = authority.submit_chapter(SubmitBookChapterCommand(context_token_budget=128000, book_run_id=book.book_run_id, chapter_number=number,
            title="Quality 双源修订", premise="对既定代价作局部澄清。", chapter_plan_asset_version_id=plan["asset_version_id"],
            chapter_plan_content_hash=plan["content_hash"], context_candidates=tuple(plan if item["asset_type"] == "chapter_plan" else item for item in candidates),
            preparation_report={"stage_context_profile_versions": {"draft": "draft-context-profile-v4"},
                "stage_context_token_budgets": {stage: 64000 for stage in ("memo", "draft", "review", "revision", "rereview")}}), principal=principal)
        for _ in range(len(ChapterNode) * 5):
            tick = chapter.scheduler(principal=worker).tick(project_id=project, root_operation_id=dispatched["chapter_root_operation_id"])
            if tick.saga_status == "SUCCEEDED":
                break
        assert tick.saga_status == "SUCCEEDED", tick
        authority.reconcile_chapter(dispatched["chapter_request_id"])
        authority.accept_chapter(dispatched["chapter_request_id"], principal=principal)
    correction_inputs = next(inputs for stage, inputs in transport.calls if stage == "revision" and inputs.get("quality_edit_contract"))
    after_inputs = next(inputs for stage, inputs in transport.calls if stage == "rereview" and inputs["revision"].get("quality_edit_contract"))
    assert after_inputs["original_draft"]["text"] == correction_inputs["draft"]["text"]
    assert REPAIRED in after_inputs["original_draft"]["text"] and CONTINUITY_REPAIRED in after_inputs["original_draft"]["text"]
    assert after_inputs["review"]["cross_chapter_window"] == correction_inputs["review"]["cross_chapter_window"]
    assert after_inputs["review"]["craft_checks"] == correction_inputs["review"]["craft_checks"]
    task = build_provider_task_view("revision", correction_inputs)
    assert task["quality_targeted_repair"]["permitted_ranges"]
    workspace = chapter.query.require_workspace(project_id=project, root_operation_id=dispatched["chapter_root_operation_id"])
    accepted_id = workspace["acceptance"]["outcome"]["content"]["accepted_draft_asset_version_id"]
    selected = next(item for item in workspace["artifacts"]["candidates"] if item["asset_version_id"] == accepted_id)
    assert "（原地付出代价）" in selected["content"]["text"]
    assert selected["content"]["selected_review"]["quality_resolution_checks"][0]["status"] == "SATISFIED"
    assert transport.quality_calls == 2
