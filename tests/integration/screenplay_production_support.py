from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from novel_forge.api.authority_dependencies import build_production_execution_composition
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.edition_application import BookEditionApplication
from novel_forge.modules.book_followup_authority.application import BookFollowupAuthorityApplication
from novel_forge.modules.book_followup_authority.definitions import book_followup_operation_definitions
from novel_forge.modules.book_followup_authority.screenplay import SCREENPLAY_DIMENSIONS, SCREENPLAY_STAGES
from novel_forge.modules.book_followup_authority.screenplay_application import ScreenplayApplication
from novel_forge.modules.book_followup_authority.screenplay_execution import build_screenplay_model_ports
from novel_forge.modules.capability_packs.screenplay_profiles import build_screenplay_pack_profile
from novel_forge.modules.capability_packs.validation_deployment import install_longform_validation_pack
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_repositories import definition_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.capability_pack_postgres_support import ROOT, PACK_PERMISSIONS


def run_screenplay_vertical(database_url, book, revision_id, principal, tmp_path, *, application_build_id, commit_sha, predecessor_source_id="", invocation_key="", run_samples=True):
    principal = replace(principal, permissions=principal.permissions | set(PACK_PERMISSIONS) | {
        "book.authority.execute", "book.authority.query", "agent.authority.admin",
        "mkaos.authority.execute", "mkaos.authority.approve", "mkaos.authority.query",
        *("book.followup:" + stage for stage in SCREENPLAY_STAGES)})
    scope = dict(project_id=book["project_id"], workspace_id=book["workspace_id"],
                 book_run_id=book["book_run_id"], principal=principal)
    edition = BookEditionApplication(database_url, application_build_id=application_build_id, commit_sha=commit_sha)
    manifest = edition.query(**scope, revision_id=revision_id)["revision"]["manifest"]
    from novel_forge.modules.mkaos_authority.application import MkaosAuthorityApplication, ApproveKnowledgeCandidateCommand
    from novel_forge.modules.mkaos_authority.craft_authoring import AuthorCoreCraftCommand
    from novel_forge.modules.mkaos_authority.craft import core_catalog_hash
    knowledge = MkaosAuthorityApplication(database_url, application_build_id=application_build_id, commit_sha=commit_sha)
    catalog = core_catalog_hash()
    authored = knowledge.execute_core_craft(AuthorCoreCraftCommand(project_id=book["project_id"], workspace_id=book["workspace_id"],
        mechanism_id="spatial-anchor", catalog_hash=catalog, actor_id=principal.principal_id,
        idempotency_key="screenplay-craft:" + revision_id, trace_id="screenplay-craft:" + revision_id, correlation_id=book["book_run_id"]), principal=principal)
    knowledge.execute_approval(ApproveKnowledgeCandidateCommand(project_id=book["project_id"], workspace_id=book["workspace_id"],
        candidate_asset_version_id=authored["asset_version_id"], policy_version="repository-original-craft-v1:" + catalog,
        rationale="Scripted protocol approval for exact scene placement of repository-original abstract spatial mechanism; no reader-effect claim.",
        actor_id=principal.principal_id, idempotency_key="screenplay-craft-approve:" + revision_id,
        trace_id="screenplay-craft:" + revision_id, correlation_id=book["book_run_id"]), principal=principal)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT asset_version_id,content_hash FROM authority_mkaos_knowledge_card WHERE project_id=%s AND candidate_asset_version_id=%s",
            [book["project_id"], authored["asset_version_id"]])
        card_id, card_hash = uow.cursor.fetchone()
    selected = [unit["unit_id"] for unit in manifest["units"]]
    joint_story = any("断潮关" in unit["text"] for unit in manifest["units"])
    adaptation_key = "v3-located" if joint_story else "v2"
    plans = []
    for number, unit in enumerate(manifest["units"], 1):
        plans.append({"scene_id": "screenplay-scene-" + str(number), "source_unit_ids": [unit["unit_id"]],
            "location": "证人暂避的廊下", "time": "风雨将至", "participants": ["mara", "ilya"],
            "dramatic_goal": "保护证词并兑现护送证人的承诺；人物只能依据源稿已知内容行动",
            "required_fact_ids": [], "craft_uses": [{"knowledge_card_asset_version_id": card_id, "content_hash": card_hash,
                "role": "PRIMARY", "sequence": 1, "required": True, "adaptation_rationale": "用人物与廊门的相对位置表现护送承诺，保留源稿行动方向与代价。",
                "prerequisite_resolution": "参与人物已在源稿当前场景；只用可见动作呈现既定位置。",
                "intended_reader_effect": "读者能追踪保护者、证人与出口的位置关系。", "abandon_condition": "如需新增空间或事件才能成立，停止使用并新建改编决定。",
                "interference_risk": "额外空间描写可能抢走承诺对白的注意。"}]})
    policy = {"policy_version": "scripted-native-adaptation.v1", "must_preserve": ["源稿证词与保护承诺的因果关系", "未完成的护送承诺"],
        "allowed_changes": ["对白压缩", "内心判断外化为可表演动作"],
        "knowledge_contract": {"reader_allowed_fact_ids": [], "character_known_fact_ids": {"mara": [], "ilya": []}},
        "context_token_budget": 16000, "max_revision_rounds": 1}
    if joint_story:
        source_by_id = {unit["unit_id"]: unit for unit in manifest["units"]}
        located = []
        for plan in plans:
            text = source_by_id[plan["source_unit_ids"][0]]["text"]
            preserving = "保存逃民证词，点亮见证旧渡口的证灯" in text
            delivering = "将已经保存的证词送达断潮关守碑人" in text
            assert preserving != delivering, "Each exact source unit must locate its accepted current action"
            plan["required_fact_ids"] = ["obligation_id=mara:protect-witnesses"]
            plan["time"] = "证灯点亮后" if preserving else "证词送达时"
            plan["location"] = "断潮关渡口檐下" if preserving else "断潮关碑前"
            plan["participants"] = ["mara", "ilya"] if preserving else ["mara"]
            plan["dramatic_goal"] = ("保存证词并明确尚未完成的护送约定" if preserving else
                "交付获准公开的证词，保留尚未完成的护送义务与返回决定")
            use = plan["craft_uses"][0]
            use["adaptation_rationale"] = "用源稿证灯、石阶或关碑的已知位置表现当前行动；不把不同地点的角色移到同场。"
            use["prerequisite_resolution"] = "仅使用所映射正文中已定位的角色、空间和动作。"
            located.append(plan)
            if delivering:
                waiting = deepcopy(plan)
                waiting.update(scene_id=plan["scene_id"] + "-waiting", participants=["ilya"],
                    location="渡口证灯旁", dramatic_goal="沈照依照原约定守灯护人；不获知闻澈尚未传回的消息")
                located.append(waiting)
        plans = located
        policy["policy_version"] = "scripted-native-adaptation.located.v2"
        policy["must_preserve"].append("证词已经送达的先后关系；关碑与渡口分别成场，沈照不得获知未传回的信息")
    definitions = {item["name"]: item for item in book_followup_operation_definitions(application_build_id=application_build_id, commit_sha=commit_sha)}
    env = {"NOVEL_FORGE_ENVIRONMENT": "development", "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_COMMIT_SHA": commit_sha, "NOVEL_FORGE_APPLICATION_BUILD_ID": application_build_id,
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path / "screenplay-objects")}
    with AuthorityUnitOfWork(database_url) as uow:
        for stage in SCREENPLAY_STAGES:
            uow.repositories.definitions.register(definitions[stage])
        uow.commit()
    profiles = {}
    for stage in SCREENPLAY_STAGES:
        pack_id = stage + "_" + revision_id.replace("-", "")[-16:] + "_v2"
        profile = build_screenplay_pack_profile(ROOT, stage=stage, operation_definition_hash=definition_hash(definitions[stage]), pack_id=pack_id)
        profiles[stage] = profile
        install_longform_validation_pack(database_url, profile=profile, pack_version="1.0.0", agent_generation=1,
            expected_activation_version=0, project_id=book["project_id"], workspace_id=book["workspace_id"], book_id=book["book_id"],
            application_build_id=application_build_id, commit_sha=commit_sha,
            compiler=replace(principal, principal_id="screenplay-fixture-compiler"),
            approver=replace(principal, principal_id="screenplay-fixture-approver"),
            agent_admin=replace(principal, principal_id="screenplay-fixture-agent-admin"), agent_domain="book_followup", agent_scope_type="BOOK")
        env["NOVEL_FORGE_" + stage.upper() + "_CAPABILITY_PACK_ID"] = pack_id
    calls = []

    def transport(stage, inputs):
        calls.append({"stage": stage, "inputs": deepcopy(inputs)})
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("""SELECT v.content FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
                WHERE a.project_id=%s AND a.asset_type='screenplay_source_contract' AND v.content->>'source_digest'=%s""",
                [book["project_id"], inputs["source_digest"]])
            source = uow.cursor.fetchone()[0]
            candidate = None
            if inputs.get("candidate_digest"):
                uow.cursor.execute("""SELECT v.content FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
                    WHERE a.project_id=%s AND a.asset_type='screenplay_candidate' AND v.content->>'candidate_digest'=%s""",
                    [book["project_id"], inputs["candidate_digest"]])
                candidate = uow.cursor.fetchone()[0]
        if stage == "screenplay_review":
            revised = candidate["revision_round"] > 0
            return {"schema_version": "screenplay-review.v2", "craft_checks": [{"use_id": use["use_id"], "scene_id": use["scene_id"], "beat_ids": ["guard"],
                    "status": "ACHIEVED" if revised else "UNCERTAIN", "interference": "CLEAR" if revised else "UNCERTAIN",
                    "reason": "Scripted located scene adoption; initial unclear staging is retained as uncertainty before revision."}
                    for use in source["screenplay_craft"]["strategy"]["uses"]], "source_digest": source["source_digest"],
                "candidate_digest": candidate["candidate_digest"], "verdict": "APPROVE" if revised else "REVISE",
                "reviewed_dimensions": list(SCREENPLAY_DIMENSIONS), "findings": [] if revised else [{
                    "finding_id": "dialogue-specificity", "scene_id": candidate["scenes"][0]["scene_id"], "beat_id": "vow",
                    "dimension": "DIALOGUE", "severity": "MAJOR", "description": "对白概括为办好此事，未承接源稿保护证人的具体承诺。",
                    "preservation_requirement": "保留保护证词与尚未完成护送的因果，仅具体化对白。"}],
                "rationale": "Scripted engineering review: checks the exact accepted source and located dialogue revision; not independent literary evidence."}
        scenes = []
        for plan in source["scene_plan"]:
            units = [unit for unit in source["source_units"] if unit["unit_id"] in plan["source_unit_ids"]]
            assert all(unit["text"] for unit in units)
            proofs = {item["unit_id"]: item for item in source["accepted_source_evidence"]["units"]}
            assert all("obligation_id=mara:protect-witnesses" in proofs[unit["unit_id"]]["fact_ids"] for unit in units)
            assert all(proofs[unit["unit_id"]]["acceptance_id"] and unit["source_ranges"] for unit in units)
            names = source.get("character_display", {}).get("scenes", {}).get(plan["scene_id"], {})
            mara, ilya = names.get("mara", "mara"), names.get("ilya", "ilya")
            if source["policy"]["policy_version"] == "scripted-native-adaptation.located.v2":
                assert len(units) == 1
                text = units[0]["text"]
                if plan["participants"] == ["mara", "ilya"]:
                    assert "我答应护你们过断潮关。证词先送出去，人也一个不能少。" in text
                    action = f"{mara}把通关符压在灯底；火沿符角烧起。{ilya}贴着墙根，把三个人移到背风处。"
                    spoken = "我答应护你们过断潮关。证词先送出去，人也一个不能少。"
                    ending = f"{mara}逐字记下证词，沿灯影确认石阶。纸灰从他指间散尽。"
                    speaker = "mara"
                elif plan["participants"] == ["mara"]:
                    assert "证到了，人还没过关。我回去接他们。" in text
                    action = f"{mara}把封好的证词交给守碑人；关碑旁的窄路仅容一人侧身。"
                    spoken = "证到了，人还没过关。我回去接他们。"
                    ending = f"{mara}没有踏进关门。他把独自通行的印记留在碑前，转身返回。"
                    speaker = "mara"
                else:
                    assert plan["participants"] == ["ilya"] and "没有收到闻澈尚未说出的消息" in text
                    action = f"{ilya}守在证灯旁，每隔一刻添一滴油。第二遍钟声响起，她把三个人挪入檐影。"
                    spoken = ""
                    ending = f"{ilya}仍守着灯。关碑处的消息尚未传到渡口。"
                    speaker = ""
                beats = [{"beat_id": "guard", "kind": "ACTION", "character_id": "", "text": action, "fact_ids": []}]
                if spoken:
                    beats.append({"beat_id": "vow", "kind": "DIALOGUE", "character_id": speaker,
                        "text": spoken if stage == "screenplay_revision" else "我会办好这件事。", "fact_ids": []})
                beats.append({"beat_id": "watch", "kind": "ACTION", "character_id": "", "text": ending, "fact_ids": []})
                scenes.append({**{key: deepcopy(plan[key]) for key in ("scene_id", "source_unit_ids", "location", "time", "participants")},
                    "retained_fact_ids": list(plan["required_fact_ids"]), "adaptation_changes": ["对白压缩", "内心判断外化为可表演动作"], "beats": beats})
                continue
            scenes.append({**{key: deepcopy(plan[key]) for key in ("scene_id", "source_unit_ids", "location", "time", "participants")},
                "retained_fact_ids": [], "adaptation_changes": ["对白压缩", "内心判断外化为可表演动作"],
                "beats": [{"beat_id": "guard", "kind": "ACTION", "character_id": "", "text": f"{mara}护住证词，转身挡在证人身前。{ilya}留在廊口，目光仍未放松。", "fact_ids": []},
                    {"beat_id": "vow", "kind": "DIALOGUE", "character_id": "mara", "text": "证词我会送到；在他们抵达安全之处前，护送的承诺还没有完。" if stage == "screenplay_revision" else "我会办好这件事。", "fact_ids": []},
                    {"beat_id": "watch", "kind": "ACTION", "character_id": "", "text": f"{ilya}看向仍在等候的证人，握紧了廊门。", "fact_ids": []}]})
        return {"schema_version": "scene-screenplay.v2", "source_digest": source["source_digest"], "scenes": scenes,
            "craft_realizations": [{"use_id": use["use_id"], "scene_id": use["scene_id"], "decision": "ADOPT", "beat_ids": ["guard"],
                "reason": "以可见护证动作和廊口位置落实批准空间技法；保留源稿因果与知识范围。"} for use in source["screenplay_craft"]["strategy"]["uses"]]}

    settings = IndustrialSettings(root=ROOT, environment="development", storage_authority="postgresql", database_url=database_url)
    execution = build_production_execution_composition(settings, env=env, chapter_fixture_factory=transport)
    execution.gateway.routes = {stage: replace(route, model_context_limit=200000) for stage, route in execution.gateway.routes.items()}
    ports = build_screenplay_model_ports(settings, execution=execution, env=env)
    for model in ports.values():
        model.capability_binder.pack_environment = model.capability_binder.pack_runtime_profile = "validation"
    followup = BookFollowupAuthorityApplication(database_url, application_build_id=application_build_id, commit_sha=commit_sha,
                                               screenplay_model_ports=ports)
    app = ScreenplayApplication(database_url, application_build_id=application_build_id, commit_sha=commit_sha, followup=followup)
    update_task = ""
    if predecessor_source_id:
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("""SELECT v.asset_version_id FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
                WHERE a.project_id=%s AND a.asset_type='screenplay_update_task'
                AND v.content->>'source_asset_version_id'=%s AND v.content->>'replacement_revision_id'=%s""",
                [book["project_id"], predecessor_source_id, revision_id])
            update_task = uow.cursor.fetchone()[0]
    invalid_policy = deepcopy(policy)
    invalid_policy["knowledge_contract"]["character_known_fact_ids"]["ilya"] = ["forged-secret-with-no-native-evidence"]
    with pytest.raises(KernelError, match="SCREENPLAY_KNOWLEDGE_SOURCE_INVALID"):
        app.command(action="prepare", **scope, data={"source_revision_id": revision_id, "selected_unit_ids": selected,
            "scene_plan": plans, "policy": invalid_policy}, idempotency_key="screenplay:forged-knowledge:" + adaptation_key + ":" + revision_id)
    prepared = app.command(action="prepare", **scope, data={"source_revision_id": revision_id, "selected_unit_ids": selected,
        "scene_plan": plans, "policy": policy, "predecessor_source_id": predecessor_source_id, "update_task_asset_version_id": update_task}, idempotency_key="screenplay:prepare:" + adaptation_key + ":" + revision_id)
    source_id = prepared["source_asset_version_id"]
    replayed = app.command(action="prepare", **scope, data={"source_revision_id": revision_id, "selected_unit_ids": selected,
        "scene_plan": plans, "policy": policy, "predecessor_source_id": predecessor_source_id, "update_task_asset_version_id": update_task},
        idempotency_key="screenplay:prepare:" + adaptation_key + ":" + revision_id)
    assert replayed["source_asset_version_id"] == source_id
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND idempotency_scope='book:screenplay' AND idempotency_key=%s",
            [book["project_id"], "screenplay:prepare:" + adaptation_key + ":" + revision_id])
        prepare_snapshot = uow.cursor.fetchone()[0]
    assert {item["asset_version_id"] for item in prepare_snapshot} == {version for version in (revision_id, predecessor_source_id, update_task) if version}
    operations = []

    def invoke(stage, candidate="", review=""):
        admitted = app.admit(stage=stage, project_id=book["project_id"], workspace_id=book["workspace_id"], principal=principal,
            source_asset_version_id=source_id, candidate_asset_version_id=candidate, review_asset_version_id=review,
            idempotency_key="screenplay:" + stage + ":" + revision_id + ":" + candidate + ":" + invocation_key + ":" + adaptation_key)
        result = app.run(project_id=book["project_id"], operation_id=admitted["operation_id"], principal=principal)
        operations.append(result)
        assert result["status"] == "SUCCEEDED", result
        count = len(calls)
        assert app.run(project_id=book["project_id"], operation_id=admitted["operation_id"], principal=principal) == result
        assert len(calls) == count
        assert len(result["outputs"]) == 1
        return result["outputs"][0]

    first = invoke("screenplay_generate")
    review = invoke("screenplay_review", first)
    with pytest.raises(KernelError, match="SCREENPLAY_REVIEW_NOT_APPROVED"):
        app.command(action="accept", **scope, data={"source_asset_version_id": source_id, "candidate_asset_version_id": first,
                    "review_asset_version_id": review}, idempotency_key="screenplay:rejected:" + adaptation_key + ":" + revision_id)
    final = invoke("screenplay_revision", first, review)
    approved = invoke("screenplay_review", final)
    accepted = app.command(action="accept", **scope, data={"source_asset_version_id": source_id,
        "candidate_asset_version_id": final, "review_asset_version_id": approved}, idempotency_key="screenplay:accept:" + adaptation_key + ":" + revision_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE project_id=%s AND idempotency_scope='book:screenplay' AND idempotency_key=%s",
            [book["project_id"], "screenplay:accept:" + adaptation_key + ":" + revision_id])
        accept_snapshot = uow.cursor.fetchone()[0]
    assert {item["asset_version_id"] for item in accept_snapshot} == {source_id, final, approved}
    exported = app.query(project_id=book["project_id"], asset_version_id=accepted["accepted_asset_version_id"], principal=principal)
    output = Path(tmp_path) / ("screenplay-" + revision_id + ".txt")
    output.write_text(exported["text"], encoding="utf-8")
    scopes = []
    with AuthorityUnitOfWork(database_url) as uow:
        from novel_forge.modules.command_kernel.creative_budget_runtime import _business_scope, _effect_identity
        for operation in operations:
            uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE project_id=%s AND operation_id=%s",
                [book["project_id"], operation["operation_id"]])
            effect_id = uow.cursor.fetchone()[0]
            identity = _effect_identity(uow.cursor, effect_id, book["project_id"])
            exact = _business_scope(uow.cursor, identity, project_id=book["project_id"])
            assert exact["scope_sources"][-1]["value"]["source_revision_id"] == revision_id
            assert exact["phase"] == ("REPAIR" if identity["operation_name"] == "screenplay_revision" else exact["origin_phase"])
            forged = deepcopy(identity)
            forged["request_payload"]["input"]["source_digest"] = "forged-source"
            with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN"):
                _business_scope(uow.cursor, forged, project_id=book["project_id"])
            scopes.append(exact)
    sampling = None
    if run_samples:
        from tests.integration.screenplay_sampling_support import run_screenplay_samples
        sampling = run_screenplay_samples(database_url, book=book, principal=principal, app=app, followup=followup,
            ports=ports, profiles=profiles, source_id=source_id, operations=operations,
            application_build_id=application_build_id, commit_sha=commit_sha)
    evidence = {"evidence_class": "SCRIPTED_NATIVE_POSTGRESQL_INTEGRATION", "actual_real_model_calls": 0, "actual_human_evaluations": 0,
        "source_asset_version_id": source_id, "source_revision_id": revision_id, "source_digest": prepared["source_digest"], "sampling": sampling,
        "first_candidate_asset_version_id": first, "first_review_asset_version_id": review, "candidate_asset_version_id": final,
        "review_asset_version_id": approved, **accepted, "command_inputs": {"prepare": prepare_snapshot, "accept": accept_snapshot}, "operations": operations, "business_scopes": scopes, "scripted_calls": calls, "export": str(output)}
    (Path(tmp_path) / ("screenplay-" + revision_id + ".json")).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence
