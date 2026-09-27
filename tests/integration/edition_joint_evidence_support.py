import json

from novel_forge.modules.mkaos_authority.runtime_usage import list_accepted_craft_usage
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.world_preparation_repositories import WorldPreparationRepository


def require_joint_accepted_evidence(captured, *, source_run, validation_run, tmp_path):
    authority = captured["composition"].authority
    book = authority.require(validation_run)
    evidence = {"actual_real_model_calls": 0, "actual_human_evaluations": 0,
                "reader_effect_proven": False, "craft": {}, "actor_intents": {}, "manuscripts": {}}
    for run in (source_run, validation_run):
        uses = sorted(list_accepted_craft_usage(authority.database_url, project_id=book["project_id"],
            book_id=book["book_id"], book_run_id=run), key=lambda use: use["chapter"])
        assert [use["chapter"] for use in uses] == [1, 2, 3]
        assert [use["usage"]["transition"]["action"] for use in uses] == ["START", "CONTINUE", "ADVANCE"]
        assert [use["usage"]["phase"] for use in uses] == ["SETUP", "SETUP", "DEVELOPMENT"]
        assert len({use["usage"]["instance_id"] for use in uses}) == 1
        for previous, current in zip(uses, uses[1:]):
            assert current["usage"]["accepted_predecessor"]["use_id"] == previous["use_id"]
            assert current["usage"]["accepted_predecessor"]["acceptance_id"] == previous["acceptance_id"]
        assert all(use["phase_transition"]["status"] == "SUPPORTED" and use["effect_status"] == "ACHIEVED" for use in uses)
        assert all(use["usage_basis"] == "ACCEPTED_PROSE_REVIEW" and use["reader_effect_proven"] is False for use in uses)
        evidence["craft"][run] = uses
        with AuthorityUnitOfWork(authority.database_url) as uow:
            intents = {chapter: WorldPreparationRepository(uow.cursor).actor_intent_sources(project_id=book["project_id"],
                book_run_id=run, through_chapter=chapter, actor_ids=["mara", "ilya"]) for chapter in (1, 2, 3)}
            manuscripts = []
            for use in uses:
                draft = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=use["accepted_draft_asset_version_id"])
                assert draft.content_hash == use["accepted_draft_content_hash"]
                assert "闻澈" in draft.content["text"] and "证灯" in draft.content["text"]
                manuscripts.append({"chapter": use["chapter"], "acceptance_id": use["acceptance_id"],
                    "asset_version_id": draft.asset_version_id, "content_hash": draft.content_hash, "text": draft.content["text"]})
        first, second, third = (intents[n]["mara"] for n in (1, 2, 3))
        for chapter, manuscript in enumerate(manuscripts, 1):
            accepted_intent = intents[chapter]["mara"]
            state = accepted_intent["state"]
            step = next(item for item in state["steps"] if item["step_id"] == state["selected_step_id"])
            completion = step["completion"]
            assert completion["execution_contract_version"] == "world-scene-execution.v2"
            assert step["action"] in manuscript["text"]
            assert step["action"] in completion["observed_action"]
            assert completion["observed_action"] in manuscript["text"]
            with AuthorityUnitOfWork(authority.database_url) as uow:
                outcome = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=accepted_intent["outcome_ref"]["asset_version_id"])
                assert outcome.content_hash == accepted_intent["outcome_ref"]["content_hash"]
                event = next(item for item in outcome.content["state_events"] if item["event_id"] == completion["event_id"])
            observed = event["mutation"]["payload"]
            comparison = observed["actor_step_execution"]
            assert comparison["approved_target"]["proposal_ref"] == accepted_intent["proposal_ref"]
            assert comparison["approved_target"]["step_id"] == step["step_id"]
            assert comparison["observed_action"] == completion["observed_action"]
            assert observed["grounded_claim_id"] == completion["grounded_claim_id"]
            assert step["action"] in event["evidence"]["quote"]
        assert first["state"]["intent_id"] == second["state"]["intent_id"]
        assert first["state"]["steps"][1]["status"] == "PLANNED"
        assert second["state"]["accepted_predecessor"]["acceptance_id"] == first["acceptance_id"]
        assert second["state"]["status"] == "COMPLETED"
        assert third["state"]["intent_id"] != second["state"]["intent_id"]
        assert third["state"]["accepted_predecessor"]["acceptance_id"] == second["acceptance_id"]
        third_steps = {step["step_id"]: step for step in third["state"]["steps"]}
        assert third_steps["begin_escort"]["status"] == "COMPLETED"
        assert third_steps["begin_escort"]["completion"]["acceptance_id"] == third["acceptance_id"]
        assert third_steps["cross_gate"]["status"] == "PLANNED" and third_steps["cross_gate"]["completion"] is None
        assert all(intents[n]["ilya"]["state"]["steps"][0]["status"] == "PLANNED" for n in (1, 2, 3))
        assert len({intents[n]["ilya"]["state"]["intent_id"] for n in (1, 2, 3)}) == 1
        assert "开始护送" in manuscripts[2]["text"]
        evidence["actor_intents"][run] = intents
        evidence["manuscripts"][run] = manuscripts
    assert evidence["craft"][source_run][0]["acceptance_id"] == evidence["craft"][validation_run][0]["acceptance_id"]
    assert evidence["craft"][source_run][1]["acceptance_id"] != evidence["craft"][validation_run][1]["acceptance_id"]
    translations = [{"input_selection": call["input"].get("narrative_intelligence"),
                     "knowledge_translations": call.get("output", {}).get("knowledge_translations", [])}
                    for call in captured["transport"].calls if call["stage"] == "chapter_plan.generate"]
    assert any(item["decision"] == "REJECT" and item.get("failure_condition") for call in translations for item in call["knowledge_translations"])
    with AuthorityUnitOfWork(authority.database_url) as uow:
        uow.cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content->'narrative_intelligence'
            FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s AND v.content ? 'narrative_intelligence' ORDER BY v.created_at""", [book["project_id"]])
        evidence["selection_contexts"] = [dict(zip(("asset_version_id", "content_hash", "selection"), row)) for row in uow.cursor.fetchall()]
    evidence["reselection_receipts"] = require_reselection_receipts(authority.database_url, book=book, contexts=evidence["selection_contexts"])
    assert evidence["reselection_receipts"]
    evidence["planning_translations"] = translations
    (tmp_path / "joint-accepted-craft-and-intents.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
    for label, run in (("original", source_run), ("edition", validation_run)):
        (tmp_path / f"joint-{label}-manuscript.txt").write_text("\n\n".join(f"第{row['chapter']}章\n{row['text']}" for row in evidence["manuscripts"][run]))
    return evidence


def require_reselection_receipts(database_url, *, book, contexts):
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_failed_operation_success
    from novel_forge.modules.mkaos_authority.craft_selection import _hash
    receipts = {}
    for context in contexts:
        selection = context["selection"]
        history = selection.get("need", {}).get("craft_context", {}).get("reselection", {}).get("history", [])
        for entry in history:
            assert entry["failure_class"] == "BUSINESS_REJECT" and entry["error_code"] == "CRAFT_CONCRETE_REJECTED"
            with AuthorityUnitOfWork(database_url) as uow:
                source = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=entry["source_asset_version_id"])
                assert source.content_hash == entry["source_content_hash"]
                raw = source.content["raw_result"]
                assert _hash(raw) == entry["result_hash"]
                assert source.content["diagnostic"]["error_code"] == "CRAFT_CONCRETE_REJECTED"
                uow.cursor.execute("""SELECT parent.status,child.operation_id,child.repair_result_asset_version_id,
                    parent_generation.input_snapshot_hash,child.input_snapshot_hash,child_op.causation_operation_id
                    FROM authority_story_planning_generation child JOIN authority_operation parent ON parent.operation_id=child.repair_of_operation_id
                    JOIN authority_story_planning_generation parent_generation ON parent_generation.operation_id=parent.operation_id
                    JOIN authority_operation child_op ON child_op.operation_id=child.operation_id
                    JOIN authority_operation_output_asset output ON output.operation_id=parent.operation_id AND output.asset_version_id=child.repair_result_asset_version_id
                    WHERE parent.operation_id=%s AND parent.project_id=%s AND child.book_id=%s""",
                    [entry["source_operation_id"], book["project_id"], book["book_id"]])
                rows = uow.cursor.fetchall()
                assert len(rows) == 1
                status, child, source_id, parent_hash, child_hash, causation = rows[0]
                assert status == "FAILED_FINAL" and source_id == source.asset_version_id
                assert parent_hash == child_hash and causation == entry["source_operation_id"]
            receipt = read_failed_operation_success(database_url, EffectCommandContext(operation_id=entry["source_operation_id"],
                project_id=book["project_id"], actor_id="scripted-joint-evidence", trace_id="joint-reselection-proof", correlation_id=child),
                effect_id=entry["execution_evidence"]["external_receipt_ref"])
            assert receipt is not None and receipt["provider_evidence"]["result"] == raw and receipt["budget_reservation_status"] == "SETTLED"
            rejected = {item["knowledge_card_asset_version_id"] for item in raw["knowledge_translations"] if item["decision"] == "REJECT"}
            assert rejected == {item["knowledge_card_asset_version_id"] for item in entry["exclusions"]}
            assert rejected.isdisjoint({item["knowledge_card_asset_version_id"] for item in selection["selected"]})
            receipts[entry["source_asset_version_id"]] = {"source_operation_id": entry["source_operation_id"], "repair_operation_id": child,
                "source_asset_version_id": source.asset_version_id, "source_content_hash": source.content_hash, "raw_result": raw,
                "history_entry": entry, "replacement_context_asset_version_id": context["asset_version_id"], "replacement_selection_digest": selection["selection_digest"],
                "frozen_input_snapshot_hash": child_hash, "provider_effect_status": "SUCCEEDED", "budget_status": "SETTLED"}
    return list(receipts.values())
