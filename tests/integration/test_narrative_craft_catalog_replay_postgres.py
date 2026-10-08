from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.application import ApproveKnowledgeCandidateCommand
from novel_forge.modules.mkaos_authority.craft import CRAFT_ORIGINAL_POLICY, core_catalog, core_catalog_hash
from novel_forge.modules.mkaos_authority.query import MkaosAuthorityQuery
from tests.integration.authority_postgres_support import DATABASE_URL, transaction
from tests.integration.test_narrative_craft_authoring_postgres import setup_craft


def test_catalog_upgrade_preserves_admitted_execution_approval_and_duplicate_identity(monkeypatch):
    application, command = setup_craft()
    admitted = application.admit_core_craft(command)
    assert admitted["status"] == "READY"
    catalog = core_catalog()
    catalog[0]["prose_realization_guidance"] += " 保持更新后的可迁移说明。"
    monkeypatch.setattr("novel_forge.modules.mkaos_authority.craft_catalog.CORE_CRAFT_MECHANISMS", catalog)
    next_catalog_hash = core_catalog_hash()
    assert next_catalog_hash != command.catalog_hash
    assert application.admit_core_craft(replace(command, catalog_hash=next_catalog_hash))["operation_id"] == admitted["operation_id"]
    authored = application.execute_core_craft(command)
    assert authored["operation_id"] == admitted["operation_id"]
    assert authored["status"] == "SUCCEEDED"
    replay = application.execute_core_craft(command)
    assert replay["asset_version_id"] == authored["asset_version_id"]
    duplicate = application.execute_core_craft(replace(command, catalog_hash=next_catalog_hash))
    assert duplicate["operation_id"] == authored["operation_id"]
    assert duplicate["asset_version_id"] == authored["asset_version_id"]
    assert duplicate["catalog_hash"] == command.catalog_hash
    approval = ApproveKnowledgeCandidateCommand(command.project_id, command.workspace_id,
        authored["asset_version_id"], CRAFT_ORIGINAL_POLICY+":"+command.catalog_hash,
        "Review the persisted original catalog version without a creative-quality claim",
        command.actor_id, "approve:"+command.idempotency_key, command.trace_id, command.correlation_id)
    with pytest.raises(KernelError, match="exact catalog hash"):
        application.admit_approval(replace(approval, policy_version=CRAFT_ORIGINAL_POLICY+":"+next_catalog_hash))
    pending = application.admit_approval(approval)
    catalog[0]["prose_realization_guidance"] += " 再次更新目录中另一机制。"
    approved = application.execute_approval(approval)
    assert approved["operation_id"] == pending["operation_id"]
    assert approved["status"] == "SUCCEEDED"
    card = MkaosAuthorityQuery(DATABASE_URL).list_cards(project_id=command.project_id)[0]
    assert card["content"]["source_policy"]["approval_policy_version"] == CRAFT_ORIGINAL_POLICY+":"+command.catalog_hash
    with transaction() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM authority_mkaos_knowledge_candidate WHERE project_id=%s", [command.project_id])
        assert cursor.fetchone()[0] == 1
    with pytest.raises(KernelError, match="reviewed exact catalog"):
        application.admit_core_craft(replace(command, mechanism_id="attention-relay"))


def test_original_catalog_revision_binds_each_project_predecessor_and_preserves_replay(monkeypatch):
    from copy import deepcopy
    from novel_forge.modules.mkaos_authority.craft import craft_hash
    projects = [setup_craft(), setup_craft()]

    def approve(application, command, authored):
        return application.execute_approval(ApproveKnowledgeCandidateCommand(
            project_id=command.project_id, workspace_id=command.workspace_id,
            candidate_asset_version_id=authored["asset_version_id"],
            policy_version=CRAFT_ORIGINAL_POLICY+":"+command.catalog_hash,
            rationale="Explicit versioned original mechanism governance; no creative-quality claim.",
            actor_id=command.actor_id, idempotency_key="approve:"+authored["asset_version_id"],
            trace_id=command.trace_id, correlation_id=command.correlation_id))

    predecessors = [approve(app, command, app.execute_core_craft(command))["asset_version_id"] for app, command in projects]
    catalog = core_catalog()
    template = next(item for item in catalog if item["mechanism_id"] == projects[0][1].mechanism_id)
    template["version"] += 1
    template["prose_realization_guidance"] += " 保留角色可直说的必要行动信息。"
    assert template["provenance"]["supersedes_card_asset_version_id"] == ""
    monkeypatch.setattr("novel_forge.modules.mkaos_authority.craft_catalog.CORE_CRAFT_MECHANISMS", catalog)
    reviewed_hash = core_catalog_hash()
    template_hash = craft_hash(template)
    app, first = projects[0]
    with pytest.raises(KernelError, match="explicit immediate predecessor"):
        app.admit_core_craft(replace(first, catalog_hash=reviewed_hash))
    with pytest.raises(KernelError, match="preceding active governed version"):
        app.admit_core_craft(replace(first, catalog_hash=reviewed_hash, supersedes_card_asset_version_id=predecessors[1]))
    with pytest.raises(KernelError, match="reviewed exact catalog"):
        app.admit_core_craft(replace(first, catalog_hash="sha256:"+"0"*64, supersedes_card_asset_version_id=predecessors[0]))
    revision_commands = []
    for (application, command), predecessor in zip(projects, predecessors, strict=True):
        revised = replace(command, catalog_hash=reviewed_hash, supersedes_card_asset_version_id=predecessor)
        revision_commands.append(revised)
        authored = application.execute_core_craft(revised)
        approved = approve(application, revised, authored)
        assert approved["status"] == "SUCCEEDED"
        assert application.execute_core_craft(revised)["asset_version_id"] == authored["asset_version_id"]
        assert application.execute_core_craft(command)["replayed"]
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT status FROM authority_mkaos_knowledge_card WHERE asset_version_id=%s", [predecessor])
            assert cursor.fetchone() == ("SUPERSEDED",)
            cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s", [authored["asset_version_id"]])
            candidate = cursor.fetchone()[0]
            assert candidate["original_authoring"]["catalog_hash"] == reviewed_hash
            assert candidate["original_authoring"]["catalog_template_hash"] == template_hash
            bound = deepcopy(template)
            bound["provenance"]["supersedes_card_asset_version_id"] = predecessor
            assert candidate["candidate"]["craft_mechanism"] == bound
            assert candidate["original_authoring"]["mechanism_hash"] == craft_hash(bound)
    with pytest.raises(KernelError, match="preserve the frozen project predecessor"):
        app.admit_core_craft(replace(revision_commands[0], supersedes_card_asset_version_id=predecessors[1]))
    template["prose_realization_guidance"] += " 未升级版本的静默内容修改。"
    with pytest.raises(KernelError, match="immutable Craft"):
        app.admit_core_craft(replace(revision_commands[0], catalog_hash=core_catalog_hash()))
    template["version"] += 2
    current_card = next(card for card in MkaosAuthorityQuery(DATABASE_URL).list_cards(project_id=first.project_id)
        if card["card_status"] == "ACTIVE")
    with pytest.raises(KernelError, match="preceding active governed version"):
        app.admit_core_craft(replace(revision_commands[0], catalog_hash=core_catalog_hash(),
            supersedes_card_asset_version_id=current_card["asset_version_id"]))
    template["version"] = 1
    with pytest.raises(KernelError, match="first versions forbid"):
        app.admit_core_craft(replace(revision_commands[0], catalog_hash=core_catalog_hash()))
    assert app.execute_core_craft(revision_commands[0])["replayed"]


def test_need_driven_catalog_upgrades_legacy_cards_without_changing_frozen_assets(monkeypatch):
    import json
    from pathlib import Path
    from novel_forge.modules.mkaos_authority.craft import craft_hash
    from novel_forge.modules.mkaos_authority.craft_matching import NEED_DRIVEN_SELECTION
    from novel_forge.modules.mkaos_authority.domain import NarrativeIntelligenceNeed

    current_catalog = core_catalog()
    legacy = json.loads((Path(__file__).parents[1] / 'fixtures/narrative_craft/need_driven_legacy.json').read_text())
    monkeypatch.setattr('novel_forge.modules.mkaos_authority.craft_catalog.CORE_CRAFT_MECHANISMS', legacy['mechanisms'])
    application, initial = setup_craft()
    initial = replace(initial, mechanism_id='intentional-gap')
    authored = application.execute_core_craft(initial)
    approved = application.execute_approval(ApproveKnowledgeCandidateCommand(initial.project_id, initial.workspace_id,
        authored['asset_version_id'], CRAFT_ORIGINAL_POLICY+':'+initial.catalog_hash,
        'Exact frozen legacy catalog approval; no reader-quality claim', initial.actor_id,
        'legacy-approve', initial.trace_id, initial.correlation_id))
    predecessor = approved['asset_version_id']
    with transaction() as connection:
        cursor = connection.cursor()
        cursor.execute('SELECT content,content_hash FROM authority_asset_version WHERE asset_version_id=%s', [predecessor])
        frozen_card = cursor.fetchone()
    query = MkaosAuthorityQuery(DATABASE_URL)
    no_need = NarrativeIntelligenceNeed(scope='SCENE', target_stage='chapter_plan.generate', craft_context={'genre':['xuanhuan'], 'pov':['first_person']})
    assert query.resolve_narrative_intelligence(project_id=initial.project_id, need=no_need)['selected'] == []
    needed = replace(no_need, craft_context={'writing_problem':['每个动机和感受都被重复解释']})
    selection = query.resolve_narrative_intelligence(project_id=initial.project_id, need=needed)
    assert selection['craft_selection_policy_version'] == NEED_DRIVEN_SELECTION
    assert selection['selected'][0]['knowledge_card_asset_version_id'] == predecessor
    assert selection['selected'][0]['selected_content']['craft_mechanism'] == frozen_card[0]['abstract_content']['craft_mechanism']

    monkeypatch.setattr('novel_forge.modules.mkaos_authority.craft_catalog.CORE_CRAFT_MECHANISMS', current_catalog)
    revised = replace(initial, catalog_hash=core_catalog_hash(), supersedes_card_asset_version_id=predecessor)
    next_candidate = application.execute_core_craft(revised)
    upgraded = application.execute_approval(ApproveKnowledgeCandidateCommand(initial.project_id, initial.workspace_id,
        next_candidate['asset_version_id'], CRAFT_ORIGINAL_POLICY+':'+revised.catalog_hash,
        'Approve exact need-driven metadata revision preserving semantic constraints', initial.actor_id,
        'upgrade-approve', initial.trace_id, initial.correlation_id))
    assert application.execute_core_craft(initial)['asset_version_id'] == authored['asset_version_id']
    assert application.execute_core_craft(revised)['asset_version_id'] == next_candidate['asset_version_id']
    with transaction() as connection:
        cursor = connection.cursor()
        cursor.execute('SELECT content,content_hash FROM authority_asset_version WHERE asset_version_id=%s', [predecessor])
        assert cursor.fetchone() == frozen_card
        assert craft_hash(frozen_card[0]) == frozen_card[1]
        cursor.execute('SELECT status FROM authority_mkaos_knowledge_card WHERE asset_version_id=%s', [predecessor])
        assert cursor.fetchone() == ('SUPERSEDED',)
    refreshed = query.resolve_narrative_intelligence(project_id=initial.project_id, need=needed)
    assert refreshed['selected'][0]['knowledge_card_asset_version_id'] == upgraded['asset_version_id']
    assert refreshed['selected'][0]['score'] == selection['selected'][0]['score']


def test_new_genesis_cannot_jump_an_admitted_unexecuted_legacy_identity(monkeypatch):
    import json
    from pathlib import Path
    current = core_catalog()
    legacy = json.loads((Path(__file__).parents[1] / 'fixtures/narrative_craft/need_driven_legacy.json').read_text())
    monkeypatch.setattr('novel_forge.modules.mkaos_authority.craft_catalog.CORE_CRAFT_MECHANISMS', legacy['mechanisms'])
    application, command = setup_craft()
    command = replace(command, mechanism_id='intentional-gap')
    frozen = application.admit_core_craft(command)
    monkeypatch.setattr('novel_forge.modules.mkaos_authority.craft_catalog.CORE_CRAFT_MECHANISMS', current)
    with pytest.raises(KernelError, match='earlier admitted mechanism identity'):
        application.admit_core_craft(replace(command, catalog_hash=core_catalog_hash()))
    executed = application.execute_core_craft(command)
    assert executed['operation_id'] == frozen['operation_id']
    assert application.execute_core_craft(command)['asset_version_id'] == executed['asset_version_id']
