from copy import deepcopy
import json

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
                "choice-exposes-value",
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
            "craft_policy": DEFAULT_CRAFT_POLICY,
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
        sentence = BROKEN if status == "FAILED" else REPAIRED
        start = draft["text"].index(sentence)
        evidence = {"start": start, "end": start + len(sentence), "quote": sentence}
        codes = ["CRAFT_CHOICE_REALIZATION"] if status == "FAILED" else []
        return {
            "use_id": target["use_id"],
            "effect_status": status,
            "evidence": evidence,
            "reason": "Original scripted contrast control; no independent reader measurement.",
            "signals_checked": [
                "Chosen action gives up the existing safe return option"
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
        result = default_chapter_fixture_response(stage, inputs)
        if stage == "draft":
            assert inputs["realization_contract"]["craft_strategy"] == self.strategy
            result["scene_artifacts"][-1]["text"] += " " + BROKEN
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
                        "judgment_kind": "AESTHETIC_SUGGESTION",
                        "confidence": "MEDIUM",
                        "interpretation": "UNCERTAIN",
                        "lineage_code": None,
                        "supporting_evidence": [],
                        "evidence": {
                            **check["evidence"],
                            "asset_version_id": inputs[
                                "target_candidate_asset_version_id"
                            ],
                            "text_hash": prose_hash(draft["text"]),
                        },
                        "violated_constraint": "Adopted choice effect",
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
            draft, issue = inputs["draft"], inputs["review"]["issues"][0]
            artifacts = deepcopy(draft["scene_artifacts"])
            artifacts[-1]["text"] = artifacts[-1]["text"].replace(BROKEN, REPAIRED)
            result = {
                "text": draft["text"].replace(BROKEN, REPAIRED),
                "scene_artifacts": artifacts,
                "resolved_issue_codes": [issue["code"]],
                "edits": [
                    {
                        **{
                            key: issue["evidence_locator"][key]
                            for key in ("start", "end", "quote")
                        },
                        "replacement": REPAIRED,
                        "issue_codes": [issue["code"]],
                    }
                ],
            }
        elif stage == "rereview":
            check = self.check(inputs["revision"], "ACHIEVED")
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


@pytest.mark.parametrize("receipt_loss", [False, True])
def test_native_craft_card_chapter_provider_targeted_repair_acceptance_and_receipt_replay(
    tmp_path, receipt_loss
):
    transport = CraftTransport(receipt_loss)
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
        context_candidates=tuple(
            plan if item["asset_type"] == "chapter_plan" else item
            for item in candidates
        ),
        preparation_report={
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
    authority.accept_chapter(dispatched["chapter_request_id"], principal=principal)
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
        REPAIRED in accepted["content"]["text"]
        and BROKEN not in accepted["content"]["text"]
    )
    checks = workspace["craft_trace"]["effect_observations"]
    assert any(check["effect_status"] == "FAILED" for check in checks)
    assert any(
        check["effect_status"] == "ACHIEVED" and check["accepted_lineage"]
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
        assert binding["output_schema_ref"].endswith(":narrative-craft-v1")
        admission = uow.repositories.asset_documents.require(
            project_id=project,
            asset_version_id=binding["provider_admission_asset_version_id"],
        ).content["contract"]
        assert admission["prompt_materialization"]["provider_view"]["component_hashes"][
            "provider_task_view"
        ] == craft_hash(build_provider_task_view("review", effect[1]["input"]))
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
            task_view = build_provider_task_view(stage, payload["input"])
            assert admitted["prompt_materialization"]["provider_view"][
                "component_hashes"
            ]["provider_task_view"] == craft_hash(task_view)
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
