from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest

from novel_forge.modules.mkaos_authority.application import MkaosAuthorityApplication, ApproveKnowledgeCandidateCommand
from novel_forge.modules.mkaos_authority.craft import core_catalog_hash
from novel_forge.modules.mkaos_authority.craft_authoring import AuthorCoreCraftCommand
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_core_functional_loops_postgres import RELEASE_SHA, _principal


STORY = {
    "promise": "闻澈按住即将熄灭的证灯，对灯下三名逃民说：‘我答应护你们过断潮关。证词先送出去，人也一个不能少。’",
    "continued": "闻澈把封好的证词交给守碑人，却没有收回同一个承诺：‘证到了，人还没过关。我回去接他们。’",
    "attitudes": {"mara": "闻澈把背后交给沈照，相信她会守住灯下的人。", "ilya": "沈照接过灯，心里仍不赞同闻澈独自赴关的冒险。"},
    "preserve": "保存逃民证词，点亮见证旧渡口的证灯",
    "deliver": "将已经保存的证词送达断潮关守碑人",
    "guard": "守护证灯旁的逃民，不泄露尚未亲见的秘密",
    "escort": "护送逃民抵达不会被阵籍抹去的旧渡口",
    "continuity_marker": "同一个承诺",
    "craft_scene_requirement": "持续交代证灯、石阶与关碑的位置和可见退路，让读者分清证词送达、开始护送与尚未过关。",
    "restart_goals": {"mara": "让仍未安全抵达的逃民亲自越过断潮关"},
    "restart_steps": {"mara": [
        {"step_id": "begin_escort", "action": "回到证灯核对逃民位置和余油，开始护送三人沿已探明石阶前行"},
        {"step_id": "cross_gate", "action": "在重新确认窄路可通行后，带仍在身边的逃民依次过关"},
    ]},
    "world_policy": {"version": "world-production-policy.v3", "context_token_budget": 20000},
    "actor_execution_contract_version": "world-scene-execution.v2",
    "runtime_environment_overrides": {"NOVEL_FORGE_BOOK_DRAFT_CONTEXT_PROFILE_VERSION": "draft-context-profile-v3", "NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET": "20000", "NOVEL_FORGE_BOOK_QUALITY_CONTEXT_TOKEN_BUDGET": "20000"},
    "craft_policy": {"schema_version": "narrative-craft-budget.v4", "max_craft_candidates": 1, "mechanism_usage_types": {"choice-exposes-value": "staged", "spatial-anchor": "staged"}},
}


def foundation_transform(role, result):
    result = deepcopy(result)
    for key, value in {
        "genre": "中文玄幻武侠", "subgenre": "江湖见证与阵籍因果", "target_reader": "重人物选择与承诺代价的中文玄幻读者",
        "core_conflict": "断潮关以阵籍抹去旧渡口，逃民的见证能够延缓抹除，却会暴露他们的位置。",
        "narrative_engine": "每次保存证词都迫使闻澈在公开真相与护送证人之间作有代价的选择。",
        "reader_promise": "人物用能被看见的行动履行承诺；知情与力量都有边界。",
        "ending_direction": "阵籍由共同见证约束，闻澈交出独占真相的权力。",
        "thematic_question": "真相能否在被公开时仍然保护为它作证的人？",
        "why_worth_writing": "写公开真相的代价，以及不把证人当代价的人。",
    }.items():
        if key in result:
            result[key] = value
    for character in result.get("characters", []):
        character["name"] = "闻澈" if character["character_id"] == "mara" else "沈照"
        character["aliases"] = [character["name"]]
        character["desire"] = "护住证人，让旧渡口不再被阵籍抹去"
    return result


STORY["foundation_transform"] = foundation_transform


def settle_joint_unknown(captured, *, scheduler, project_id, root_operation_id):
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.command_kernel.external_effect_adapters import ExternalEffectAdapterError
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, prepare_effect_dispatch
    adapter = captured["chapter_application"]._model_port.adapter
    execute = adapter.execute
    database_url = captured["composition"].authority.database_url
    evidence = {"injection": "SCRIPTED_GATEWAY_RESULT_PERSISTED_BEFORE_EFFECT_RECEIPT_LOSS", "actual_real_model_calls": 0}
    receipt_loss_message = "scripted bridge lost the already produced draft receipt"

    def require_unknown():
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("""SELECT e.external_effect_id,e.operation_id,e.status,o.status,
                b.status,d.dispatch_id,d.generation,d.status FROM authority_external_effect e
                JOIN authority_operation o USING(operation_id)
                JOIN authority_budget_reservation b USING(external_effect_id)
                JOIN authority_external_effect_dispatch d USING(external_effect_id)
                WHERE e.project_id=%s AND o.root_operation_id=%s AND e.stable_idempotency_key=%s""",
                [project_id, root_operation_id, evidence["stable_idempotency_key"]])
            rows = uow.cursor.fetchall()
            assert len(rows) == 1, rows
            row = rows[0]
            assert row[2:5] == ("RECONCILIATION_REQUIRED", "RECONCILIATION_REQUIRED", "HELD_UNKNOWN"), row
            assert row[7] == "UNKNOWN", row
            evidence["unknown"] = dict(zip(("effect_id", "operation_id", "effect_status", "operation_status", "budget_status", "dispatch_id", "generation", "dispatch_status"), row))
        with pytest.raises(KernelError, match="EFFECT_RECONCILIATION_REQUIRED"):
            prepare_effect_dispatch(database_url, EffectCommandContext(operation_id=row[1], project_id=project_id,
                actor_id="joint-proof", trace_id="joint-unknown-proof", correlation_id=root_operation_id), effect_id=row[0])

    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT e.stable_idempotency_key FROM authority_external_effect e
            JOIN authority_operation o USING(operation_id)
            JOIN authority_external_effect_dispatch d USING(external_effect_id)
            WHERE e.project_id=%s AND o.root_operation_id=%s AND e.request_payload->>'stage'='draft'
              AND d.evidence->>'message'=%s AND d.evidence->>'request_sent'='true'
              AND e.status='RECONCILIATION_REQUIRED'""", [project_id, root_operation_id, receipt_loss_message])
        retained = uow.cursor.fetchall()
        assert len(retained) <= 1, retained
    if retained:
        evidence["stable_idempotency_key"] = retained[0][0]
        evidence["recovered_after_process_rebuild"] = True
        require_unknown()

    def lose_receipt(**kwargs):
        result = execute(**kwargs)
        payload = kwargs["request_payload"]
        if payload.get("stage") == "draft" and "stable_idempotency_key" not in evidence:
            assert result.outcome == "success"
            evidence["stable_idempotency_key"] = kwargs["stable_idempotency_key"]
            raise ExternalEffectAdapterError(receipt_loss_message, request_sent=True)
        return result

    with patch.object(adapter, "execute", side_effect=lose_receipt):
        for _ in range(50):
            try:
                tick = scheduler.tick(project_id=project_id, root_operation_id=root_operation_id)
            except KernelError as exc:
                if exc.code != "EFFECT_EXTERNAL_STATE_UNKNOWN" or "unknown" in evidence:
                    raise
                require_unknown()
                continue
            if tick.saga_status == "SUCCEEDED":
                break
        else:
            raise AssertionError("The frozen original Chapter did not recover its exact unknown Effect")
    assert "unknown" in evidence
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT e.status,b.status,count(DISTINCT d.dispatch_id),count(DISTINCT r.external_receipt_id)
            FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id)
            JOIN authority_external_effect_dispatch d USING(external_effect_id)
            LEFT JOIN authority_external_receipt r USING(dispatch_id)
            WHERE e.external_effect_id=%s GROUP BY e.status,b.status""", [evidence["unknown"]["effect_id"]])
        row = uow.cursor.fetchone()
        assert row[:3] == ("SUCCEEDED", "SETTLED", 1) and row[3] >= 1, row
        evidence["reconciled"] = dict(zip(("effect_status", "budget_status", "dispatch_count", "receipt_count"), row))
    return evidence


def approve_joint_craft(project_id, book_id, generic):
    principal = _principal(project_id)
    principal = replace(principal, permissions=principal.permissions | {"mkaos.authority.execute", "mkaos.authority.approve", "mkaos.authority.query"})
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_workspace WHERE project_id=%s", [project_id])
        workspace = uow.cursor.fetchone()[0]
    knowledge = MkaosAuthorityApplication(DATABASE_URL, application_build_id="wp02-native-joint", commit_sha=RELEASE_SHA)
    catalog_hash = core_catalog_hash()
    for mechanism in ("choice-exposes-value", "spatial-anchor"):
        authored = knowledge.execute_core_craft(AuthorCoreCraftCommand(project_id=project_id, workspace_id=workspace,
            mechanism_id=mechanism, catalog_hash=catalog_hash, actor_id=principal.principal_id, idempotency_key="joint:author:" + mechanism,
            trace_id="trace:wp02-joint", correlation_id="correlation:wp02-joint"), principal=principal)
        knowledge.execute_approval(ApproveKnowledgeCandidateCommand(project_id=project_id, workspace_id=workspace,
            candidate_asset_version_id=authored["asset_version_id"], policy_version="repository-original-craft-v1:" + catalog_hash,
            rationale="原创抽象技法用于明确标记的scripted同书工程验证；不主张文学收益。", actor_id=principal.principal_id,
            idempotency_key="joint:approve:" + mechanism, trace_id="trace:wp02-joint", correlation_id="correlation:wp02-joint"), principal=principal)
    return generic


class JointStoryTransport:
    def on_camera_statement(self, event):
        action = event["action"]
        assert event["actor_step"]["action"] == action
        actor = "闻澈" if event["actor_id"] == "mara" else "沈照"
        return f"{actor}在证灯下完成了眼前这一步：{action}。灯焰稳住，渡口的轮廓暂时没有消失。"

    def __call__(self, stage, inputs):
        result = super().__call__(stage, inputs)
        if stage == "draft":
            chapter = int(inputs["plan"]["chapter"])
            for index, scene in enumerate(result["scene_artifacts"]):
                if chapter == 1:
                    scene["text"] = (
                        "断潮关的钟响到第三声，渡口最外侧的石阶少了一截。闻澈把刀横在石缝里，刀尖碰不到昨日的水。"
                        "逃民缩在檐下，谁也不肯先说出自己的名字。阵籍收得走地名，也收得走作证的人。"
                        "沈照把仅剩的灯油倒进证灯：‘再等，连回去的路都会没。’闻澈本可循暗渠独自过关；他把通关符压在灯底，火沿符角烧起，退路便只剩水声。"
                        "他没有催证人。等最年幼的那个开口，他才逐字记下渡口原来的样子。"
                    ) if index == 0 else "证灯照出旧码头的边线。沈照贴着墙根把三个人移到背风处，闻澈沿灯影确认能走的石阶；他只说自己看见的路，没有许诺尚未探明的安全。"
                elif chapter == 2:
                    scene["text"] = (
                        "闻澈抵达关碑前，袖中的证词已被江雾浸软。守碑人伸手要他的证灯，他却先把证词摊在石面上。"
                        "一张通关符能换一个人进去；把逃民的名字写进阵籍，能让渡口多留一夜，也会让追索者找到他们。"
                        "闻澈只交出了获准公开的证词。碑纹停了片刻，给出一条窄得仅容一人侧身通过的路。"
                    ) if index == 0 else "沈照没有收到闻澈尚未说出的消息。她守在灯旁，依照约定每隔一刻添一滴油；远处第二遍钟声响起，她把三个人的位置重新挪到了檐影里。"
                else:
                    scene["text"] = (
                        "闻澈沿先前亲自探过的石阶回到证灯旁。沈照把灯递到他手边，先报了三个人的位置，才给他看只剩浅浅一层的灯油。"
                        "证词已经有人保管，眼前的人却仍困在渡口。闻澈让脚伤最重的先扶住自己，把走得动的安排在灯影里面。"
                        "他等三个人都应声，才离开檐下，向关碑留下的那条窄路挪去。"
                    ) if index == 0 else "沈照守在队伍后面，只传自己听清的话。前方一块石阶在钟声里淡去，她让队伍停住，等闻澈摸清新的落脚处；没人把尚未走完的路称作安全。"
            public = (inputs.get("plan", {}).get("constraint_envelope") or {}).get("world_execution") or {}
            for event in public.get("on_camera_events", []):
                slots = {slot["slot_id"] for slot in inputs["realization_contract"]["slots"] if slot["scene_id"] == event["scene_id"]}
                next(scene for scene in result["scene_artifacts"] if scene["slot_id"] in slots)["text"] += self.on_camera_statement(event)
            result["text"] = "\n\n".join(scene["text"] for scene in result["scene_artifacts"])
        if stage == "revision":
            before = "The protagonist gives up the only safe route home before the witnesses leave."
            chapter = int(inputs["draft"]["chapter"])
            after = ("火光褪去，纸灰从闻澈指间散尽。他等到了证词，也失去了最容易脱身的凭据。" if chapter == 1
                     else "守碑人收起证词，闻澈却没有踏进关门。他把可以独自通行的印记留在碑前，转身去找仍在等他的人。")
            result["text"] = result["text"].replace(before, after)
            for scene in result.get("scene_artifacts", []):
                scene["text"] = scene["text"].replace(before, after)
            for edit in result.get("edits", []):
                edit["replacement"] = edit["replacement"].replace(before, after)
        if stage in {"review", "rereview"}:
            for check in result.get("craft_checks", []):
                check.update(effect_status="UNCERTAIN" if stage == "review" else "ACHIEVED", reason="scripted定位评价：正文中的选择和退路与冻结使用位置一致，不代表真人效果评价。")
                check["phase_transition"].update(status="UNCERTAIN" if stage == "review" else "SUPPORTED", progress="证词得到保存或交付，但护送证人的承诺仍未终结。", reason="按接纳正文定位，同一阶段仍有未满足条件。")
                if check["phase_transition"]["phase"] == "DEVELOPMENT":
                    check["phase_transition"].update(progress="护送从尚未执行的承诺变为正文中已经开始的行动。", reason="仅定位回到证灯、确认人员与开始移动；未认定他们已经安全过关。")
                for side in check["side_effects"]:
                    side.update(status="UNCERTAIN" if stage == "review" else "CLEAR", reason="scripted局部干扰评价；首轮证据不足，修订后重新定位，总体效果待真实评价。")
            for check in result.get("craft_preservation_checks", []):
                check.update(status="PRESERVED", reason="精确位置保留既有承诺和行动结果。")
        if stage == "canon_support":
            for item in inputs["claims"]:
                claim = item["claim"]
                comparison = claim.get("actor_step_execution")
                if comparison:
                    action = comparison["approved_target"]["action"]
                    assert action in comparison["observed_action"]
                    assert action in claim["extraction_evidence"]["quote"]
                    assert comparison["observed_action"] != action
        return result

    def planning(self, stage, inputs):
        result = super().planning(stage, inputs)
        if stage == "world_candidates.evaluate":
            return result
        if stage.endswith("_plan.generate"):
            def bind_cast(value):
                if isinstance(value, dict):
                    return {key: bind_cast(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [bind_cast(item) for item in value]
                return value.replace("protagonist", "mara") if isinstance(value, str) else value
            result = bind_cast(result)
        if stage == "chapter_plan.generate":
            chapter = int(result.get("chapter_number") or result.get("chapter") or 1)
            result["title"] = {1: "证灯未灭", 2: "关碑前的证词"}.get(chapter, "回身的路")
            objective = {1: "闻澈放弃独自脱身的凭据，保存逃民证词；护送承诺仍待后续行动。",
                         2: "闻澈把获准公开的证词送到关碑，确认逃民尚未抵达；沈照只依照自己所知守灯。"}.get(
                             chapter, "闻澈回到证灯核对人员和余油，开始护送仍在等待的逃民，不提前认定成功过关。")
            result.update(objective=objective, premise=objective)
            for scene in result["scene_plan"]:
                scene.update(goal=objective + " " + STORY["craft_scene_requirement"], conflict="保住证词的行动会暴露证人；只允许承担已知风险，不替其他人决定未知后果。",
                             reader_effect="看见选择的代价，并分清证词送达与护送完成。")
        if stage == "chapter_plan.generate" and getattr(self, "joint_future_review", False):
            result["objective"] += " 先核对逃民所在位置与证灯余油，再履行护送承诺；不把证词送达当作人员安全。"
        selection = inputs.get("narrative_intelligence") or (inputs.get("world_preparation") or {}).get("narrative_intelligence") or {}
        selected = selection.get("selected") or []
        if selected:
            result["knowledge_translations"] = []
        for card in selected:
            translation = {"knowledge_card_asset_version_id": card["knowledge_card_asset_version_id"], "content_hash": card["content_hash"],
                "decision": "REJECT", "usage_role": "MECHANISM", "rationale": "上层结构尚未落到具体可观察场景，不提前认定采用。",
                "prerequisite_resolution": "具体章节场景由下层合同核对。", "use_sites": []}
            if stage == "chapter_plan.generate":
                scene = result["scene_plan"][0]
                field = next(key for key, value in scene.items() if isinstance(value, str) and len(value.strip()) >= 8 and not key.endswith(("_id", "_ref")))
                history = card["craft_assessment"]["budget_assessment"].get("accepted_usage_history", [])
                previous = max((row for row in history if row["effect_status"] == "ACHIEVED"),
                               key=lambda row: (row["chapter"], row["use_id"]), default=None)
                began_escort = any("开始护送" in str(event.get("action") or "") for event in (inputs.get("world_preparation") or {}).get("on_camera_events", []))
                advance = previous and previous["usage"]["phase"] == "SETUP" and began_escort
                translation.update(decision="ADAPT", rationale="以已规划行动呈现代价，不能增加结果或越过知情边界。", prerequisite_resolution="现有场景已提供可定位行动和退路。",
                    rejected_scene_ids=[], failure_condition="", use_sites=[{
                    "target_pointer": f"/scene_plan/0/{field}", "realization_excerpt": scene[field], "expected_application": "在证灯、石阶与关碑的行动中呈现承诺代价。",
                    "preservation_requirements": ["保留已批准人物选择、结果与知情边界。"], "verification_checks": ["在正文定位行动及可见后果，不能只定位意图。"],
                    "craft_role": "PRIMARY", "craft_sequence": 1, "intended_reader_effect": "读者能追踪行动代价和承诺尚未完成之处。",
                    "craft_combination": {"narrative_problem": "让承诺成为行动。", "selection_reason": "场景中已有必须承担的行动。", "role_and_order_reason": "先建立位置，再展现代价。", "combined_effect": "选择及退路可追踪。", "interference_risk": "解释性旁白可能削弱动作。", "preservation_constraint": "不改变既定结果和秘密。", "abstain_condition": "场景缺少对应行动时不强行加入。"},
                    "craft_usage": {"instance_id": previous["usage"]["instance_id"] if previous else "", "predecessor_use_id": previous["use_id"] if previous else "", "phase": "DEVELOPMENT" if advance else previous["usage"]["phase"] if previous else "SETUP",
                        "scope_id": selection["need"]["craft_context"]["usage_scope_context"]["arc_plan_version_ids"][0],
                        "transition": {"action": "ADVANCE" if advance else "CONTINUE" if previous else "START", "condition": "护送须在正文中实际开始，不能把规划或交付证词当作人员安全。" if advance else "证人与证词尚未同时安全抵达。", "progress": "开始移动，兑现尚未完成。" if advance else "同阶段展示新的行动代价。"}}}])
                if card["selected_content"]["craft_mechanism"]["mechanism_id"] == "choice-exposes-value":
                    translation.update(decision="REJECT", use_sites=[], rejected_scene_ids=[item["scene_id"] for item in result["scene_plan"]],
                        failure_condition="本次技法使用位置要求持续交代路径和退路，不要求增加价值转变；人物的既定选择仍由原计划保留。",
                        rationale="scripted具体场景采用判断：候选无法满足本次空间辨识用途，请原生选择器在批准范围内重新求解。")
            result["knowledge_translations"].append(translation)
        self.calls[-1]["output"] = result
        return result
