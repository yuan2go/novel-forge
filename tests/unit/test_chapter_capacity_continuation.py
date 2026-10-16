from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_forge.modules.capability_pack_authority.domain import canonical_hash
from novel_forge.modules.capability_packs import validation_deployment
from novel_forge.modules.chapter_authority.capacity_continuation import (
    PROJECTION, capacity_decision, capacity_upgrade_command, require_capacity_upgrade_binding,
    validate_capacity_pack_pair, capacity_rebuilt_content, effective_context_content,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.request_capacity import recompose_capacity_context


def versions(monkeypatch, identities=("3.0.4", "3.1.0")):
    monkeypatch.setattr(validation_deployment, "_install_validation_manifest", lambda *args, **kwargs: kwargs)
    result = []
    for version in identities:
        captured = validation_deployment.install_chapter_validation_pack("not-connected",
            repository_root=Path(__file__).resolve().parents[2], project_id="p", workspace_id="w", book_id="b",
            application_build_id="fixture", commit_sha="a" * 40, compiler=None, approver=None, agent_admin=None,
            pack_id_override="same-owner", pack_version_override=version,
            prose_skill_version="prose-generation-v5", prompt_template_version="v15")
        result.append({"manifest": captured["manifest"], "artifact_catalog": captured["artifact_catalog"],
            "manifest_hash": canonical_hash(captured["manifest"]),
            "artifact_catalog_hash": canonical_hash(captured["artifact_catalog"])})
    return result


@pytest.mark.parametrize("source", ["3.0.4", "3.1.0"])
def test_semantic_capacity_upgrade_retains_original_pack_scope_and_old_artifact_bytes(monkeypatch, source):
    old, new = versions(monkeypatch, (source, "3.2.0"))
    proof = validate_capacity_pack_pair(old, new)
    assert proof["target_context_policy_ref"] == "context-policy:chapter-generation-pack:v4"
    assert proof["source_context_policy_ref"] == old["manifest"]["context_sources"]["policy_id"]


def test_first_complete_capacity_contract_reinstalls_with_its_exact_original_hashes(monkeypatch):
    import json
    from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
    root = Path(__file__).resolve().parents[2]
    frozen = json.loads((root / "tests/fixtures/creation_capacity_v3_contract_hashes.json").read_text())
    chapter = versions(monkeypatch, ("3.1.0",))[0]
    assert {key: chapter[key] for key in ("manifest_hash", "artifact_catalog_hash")} == frozen["chapter"]
    planning = build_story_planning_pack_profile(root, operation_definition_hash="sha256:" + "a" * 64,
        event_first_planning=True, complete_request_capacity=True, semantic_context_compression=False)
    assert planning.manifest["identity"]["version"] == "2.17.0"
    assert {"manifest_hash": canonical_hash(planning.manifest), "artifact_catalog_hash": canonical_hash(planning.artifact_catalog)} == frozen["planning"]


def test_actual_historical_and_new_installers_prove_only_capacity_changed(monkeypatch):
    old, new = versions(monkeypatch)
    before = deepcopy(old)
    proof = validate_capacity_pack_pair(old, new)
    assert old == before
    assert proof["source_context_policy_ref"].endswith(":v2")
    assert proof["target_context_policy_ref"].endswith(":v3")
    assert proof["target_context_policy_hash"] == canonical_hash(new["manifest"]["context_sources"])


@pytest.mark.parametrize("change", ["prompt", "skill", "route", "schema", "tool", "catalog"])
def test_signed_different_contract_cannot_borrow_capacity_upgrade(monkeypatch, change):
    old, new = versions(monkeypatch)
    if change == "prompt":
        new["manifest"]["prompt_binding"]["template_version"] = "v13"
    elif change == "skill":
        new["manifest"]["skill_binding"]["skills"][0]["content_hash"] = "sha256:" + "b" * 64
    elif change == "route":
        new["manifest"]["tool_permissions"]["external_models"]["route_policy_ref"] = "another-paid-route"
    elif change == "tool":
        new["manifest"]["tool_permissions"]["tools"].append({"tool_ref": "unrelated.write"})
    elif change == "schema":
        next(item for item in new["artifact_catalog"]["artifacts"] if item["kind"] == "SCHEMA")["content"] = {"type": "string"}
    else:
        new["artifact_catalog"]["artifacts"].append({"kind": "KNOWLEDGE", "ref": "not-authorized", "version": "v1"})
    new["manifest_hash"] = canonical_hash(new["manifest"])
    new["artifact_catalog_hash"] = canonical_hash(new["artifact_catalog"])
    with pytest.raises(KernelError, match="CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT"):
        validate_capacity_pack_pair(old, new)


@pytest.mark.parametrize("change", ["required-refs", "allowed-types", "freshness", "book-binding", "policy-artifact"])
def test_capacity_upgrade_preserves_the_actual_source_and_freshness_contract(monkeypatch, change):
    old, new = versions(monkeypatch)
    sources = new["manifest"]["context_sources"]
    policy = next(item["content"] for item in new["artifact_catalog"]["artifacts"]
                  if item["kind"] == "CONTEXT_POLICY" and item["version"] == "v3")
    if change == "required-refs":
        sources["required_version_refs"] = []
        policy["required_version_refs"] = []
    elif change == "allowed-types":
        sources["allowed_asset_types"] = ["raw_reference_work"]
        policy["allowed_asset_types"] = ["raw_reference_work"]
    elif change == "freshness":
        sources["freshness"]["reject_stale"] = False
    elif change == "book-binding":
        sources["longform_bindings"]["book"] = "optional"
    else:
        policy["required_version_refs"] = []
    new["manifest_hash"] = canonical_hash(new["manifest"])
    new["artifact_catalog_hash"] = canonical_hash(new["artifact_catalog"])
    with pytest.raises(KernelError, match="CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT"):
        validate_capacity_pack_pair(old, new)


def test_successor_adds_proof_without_rewriting_original_command_or_working_sources():
    original = {"book_id": "book", "context_token_budget": 6000,
        "preparation_report": {"working_manuscript": {"snapshot_hash": "original", "sources": [{"chapter": 1}]}}}
    before = deepcopy(original)
    policy = {"transport_projection": PROJECTION, "source_operation_id": "failed-context", "target_deployment_id": "approved"}
    upgraded = capacity_upgrade_command(original, policy)
    assert original == before
    marker = upgraded["preparation_report"].pop("context_capacity_upgrade")
    assert upgraded == original
    assert marker == {"source_operation_id": "failed-context", "policy_hash": canonical_hash(policy)}


@pytest.mark.parametrize("fault", [None, "paid-budget", "permission", "foreign-operation", "not-overflow"])
def test_route_capacity_proof_does_not_override_other_candidate_authorization(fault):
    source = {"operation_id": "failed", "definition_name": "chapter.draft.generate"}
    rejected = ["CONTEXT_CAPACITY_EXCEEDED", "BUDGET_HARD_LIMIT"]
    if fault == "paid-budget":
        rejected = ["BUDGET_HARD_LIMIT"]
    if fault == "permission":
        rejected.append("AUTHORIZATION_MISSING")
    decision = {"status": "BLOCKED", "selected": None,
        "task": {"operation_id": "other" if fault == "foreign-operation" else "failed", "task_type": "draft", "input_tokens": 300, "output_tokens": 100},
        "candidates": [{"rejected_reasons": rejected, "candidate": {"context_limit": 1000 if fault == "not-overflow" else 399}},
            {"rejected_reasons": ["AUTHORIZATION_MISSING"], "candidate": {"context_limit": 1000}}]}
    assert capacity_decision(decision, source) is (fault is None)


@pytest.mark.parametrize("field", [None, "deployment_id", "manifest_hash", "context_policy_ref", "context_policy_hash"])
def test_actual_attempt_must_match_the_approved_capacity_binding(field):
    proof = {"target_deployment_id": "deployment", "target_manifest_hash": "manifest",
        "target_context_policy_ref": "policy", "target_context_policy_hash": "policy-hash"}
    values = {key.removeprefix("target_"): value for key, value in proof.items()}
    if field:
        values[field] = "changed"
        with pytest.raises(KernelError, match="CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED"):
            require_capacity_upgrade_binding(proof, SimpleNamespace(**values))
    else:
        require_capacity_upgrade_binding(proof, SimpleNamespace(**values))


def test_absent_upgrade_does_not_read_a_snapshot_but_empty_declared_upgrade_fails_closed():
    require_capacity_upgrade_binding(None, object())
    with pytest.raises(KernelError, match="CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED"):
        require_capacity_upgrade_binding({}, object())


def test_context_owner_recomposes_exact_frozen_selection_with_a_separate_derivation():
    original = {"context_bundle_id": "original", "segments": [
        {"asset_version_id": "working", "safe_summary": "她以为钥匙已失；读者知道它仍在袖中。", "status": "UNREVIEWED_WORKING_PROSE"}],
        "task_context_receipt": {"task_target_tokens": 6000}, "omitted_ranges": [[0, 17]]}
    before = deepcopy(original)
    proof = {"transport_projection": PROJECTION, "target_context_policy_ref": "context-policy:chapter-generation-pack:v3",
        "source_operation_id": "failed-draft", "policy_hash": "sha256:" + "b" * 64}
    derived, receipt = recompose_capacity_context(original, proof)
    assert original == before
    assert receipt["source_projection_hash"] == canonical_hash(original)
    assert receipt["derived_projection_hash"] == canonical_hash(derived)
    assert derived.pop("request_context_derivation")["source_selection"] == "ORIGINAL_FROZEN_SELECTION"
    assert derived == original


@pytest.mark.parametrize("fault", [None, "old-summary", "source", "policy", "content", "receipt"])
def test_rebuilt_context_is_a_distinct_hash_bound_derivation_not_a_relabelled_old_asset(fault):
    proof = {"asset_version_id": "original-context", "content_hash": "original-hash",
             "input_snapshot": [{"asset_version_id": "original-source", "content_hash": "source-hash"}]}
    upgrade = {"context_source": proof, "policy_hash": "approved-policy"}
    content = {"context_segments": [{"safe_summary": "原始冻结来源，未沿用旧压缩结果。"}],
        "capacity_policy_upgrade": upgrade,
        "context_manifest": {"task_context_receipt": {"capacity_admission": "DEFERRED_COMPLETE_REQUEST"}}}
    derivation = {"contract_version": "frozen-context-rebuild.v1", "source": proof,
                  "policy_hash": "approved-policy", "content": content, "content_hash": canonical_hash(content)}
    original = {"asset_version_id": "original-context", "content_hash": "original-hash"}
    if fault == "old-summary":
        original["asset_version_id"] = "different-source"
    elif fault == "source":
        derivation["source"] = {**proof, "input_snapshot": []}
    elif fault == "policy":
        derivation["policy_hash"] = "unapproved-policy"
    elif fault == "content":
        content["context_segments"] = []
    elif fault == "receipt":
        content["context_manifest"]["task_context_receipt"]["capacity_admission"] = "MATERIAL_TARGET"
        derivation["content_hash"] = canonical_hash(content)
    if fault:
        with pytest.raises(KernelError, match="CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT"):
            capacity_rebuilt_content(derivation, upgrade, original)
    else:
        assert capacity_rebuilt_content(derivation, upgrade, original) is content
        source = SimpleNamespace(**original, content={"context_segments": []})
        request = SimpleNamespace(capacity_upgrade=upgrade, capacity_context_derivation=derivation,
                                  require_input=lambda kind: source)
        assert effective_context_content(request) is content
        assert source.content == {"context_segments": []}


def test_domain_source_resolution_uses_the_same_rebuilt_selection_as_the_provider(monkeypatch):
    from novel_forge.modules.chapter_authority.realization_composition import resolve_accepted_realization_sources
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    source = SimpleNamespace(asset_version_id="context", content_hash="old-hash", content={})
    proof = {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash}
    upgrade = {"context_source": proof, "policy_hash": "approved"}
    rebuilt = {"capacity_policy_upgrade": upgrade, "context_manifest": {
        "task_context_receipt": {"capacity_admission": "DEFERRED_COMPLETE_REQUEST"},
        "accepted_boundary": {"story_state_snapshot_version": "state", "accepted_through_chapter": 1},
        "selected_inputs": [{"asset_version_id": "state", "allowed_use": "generation", "content_digest": "state-hash"}]},
        "production_input_manifest": {"selected_asset_versions": [
            {"asset_version_id": "state", "asset_type": "story_state_snapshot", "content_hash": "state-hash"}]}}
    derivation = {"contract_version": "frozen-context-rebuild.v1", "source": proof, "policy_hash": "approved",
                  "content": rebuilt, "content_hash": canonical_hash(rebuilt)}
    request = SimpleNamespace(project_id="p", command={"book_id": "b"}, database_url="unused",
        capacity_upgrade=upgrade, capacity_context_derivation=derivation,
        require_input=lambda kind: source if kind == "context_bundle" else SimpleNamespace(content={"chapter": 2, "character_participation": []}))
    state = SimpleNamespace(content_hash="state-hash", asset_type="story_state_snapshot", lifecycle="ACTIVE",
        eligibility="ELIGIBLE", governance="CLEAR", content={"contract_version": "story-state-snapshot-v2",
            "accepted_state_only": True, "project_id": "p", "book_id": "b", "accepted_through_chapter": 1, "current_state": {}})
    monkeypatch.setattr(AuthorityAssetQuery, "require", lambda *args, **kwargs: state)
    assert resolve_accepted_realization_sources(request)["asset_version_id"] == "state"
    assert source.content == {}


@pytest.mark.parametrize("fault", [None, "effect-hash", "journal", "unknown"])
def test_native_receipt_request_constructor_restores_the_original_verified_context_without_a_model(monkeypatch, fault):
    from novel_forge.modules.chapter_authority import receipt_recovery
    from novel_forge.modules.chapter_authority.scene_receipt_recovery import draft_receipt_inputs
    from tests.unit.test_retained_draft_current_boundary import fixture

    source, _, reader, assets = fixture()
    context = assets["context"]
    proof = {"asset_version_id": "context", "content_hash": context.content_hash, "input_snapshot": []}
    policy = {"transport_projection": PROJECTION, "source_operation_id": "old-capacity", "context_source": proof}
    policy_hash = canonical_hash(policy)
    upgrade = {**policy, "policy_hash": policy_hash, "successor_operation_id": source["operation_id"]}
    rebuilt = {**deepcopy(context.content), "restored_source": "原始冻结来源，禁止再次摘要旧结果。", "capacity_policy_upgrade": upgrade}
    rebuilt["context_manifest"]["task_context_receipt"] = {"capacity_admission": "DEFERRED_COMPLETE_REQUEST"}
    derivation = {"contract_version": "frozen-context-rebuild.v1", "source": proof, "policy_hash": policy_hash,
                  "content": rebuilt, "content_hash": canonical_hash(rebuilt)}
    source["command_payload"]["preparation_report"] = {"context_capacity_upgrade": {
        "source_operation_id": "old-capacity", "policy_hash": policy_hash}}
    payload = {"stage": "draft", "input": {"_context_capacity_upgrade": upgrade, "_context_capacity_rebuild": derivation}}
    verified = []
    def receipt(*args, **kwargs):
        verified.append(args[1])
        if fault == "unknown":
            raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Original outcome is unresolved")
    monkeypatch.setattr(receipt_recovery, "_receipt", receipt)
    class Cursor:
        def execute(self, query, parameters):
            if "FROM authority_external_effect" in query:
                self.rows = [("effect", "tampered" if fault == "effect-hash" else canonical_hash(payload), payload)]
            elif "FROM authority_saga_step_successor" in query:
                self.rows = [(policy, "foreign" if fault == "journal" else source["operation_id"])]
            else:
                raise AssertionError(query)
        def fetchall(self):
            return self.rows
        def fetchone(self):
            return self.rows[0]
    reader.cursor = Cursor()
    if fault:
        with pytest.raises(KernelError):
            draft_receipt_inputs(source, asset_reader=reader)
    else:
        request = draft_receipt_inputs(source, asset_reader=reader)
        assert effective_context_content(request) == rebuilt
        assert request.require_input("context_bundle").content == context.content
        assert request.capacity_context_derivation == derivation
    assert verified == ["effect"]


@pytest.mark.parametrize('policy,allowed', [('v2', True), ('v3', True), ('v4', False)])
def test_original_draft_snapshot_accepts_only_the_supported_capacity_predecessors(monkeypatch, policy, allowed):
    from novel_forge.modules.chapter_authority.capacity_continuation import _source_version
    from novel_forge.storage.capability_pack_authority_repositories import CapabilityPackAuthorityRepository
    version = {'manifest_hash': 'manifest'}
    monkeypatch.setattr(CapabilityPackAuthorityRepository, 'require_version', lambda *args, **kwargs: version)
    class Cursor:
        def execute(self, *args):
            pass
        def fetchall(self):
            return [('pack', '3.1.0', 'manifest', 'snapshot', 'snapshot-hash', 'context-policy:chapter-generation-pack:' + policy)]
    source = {'root_operation_id': 'root', 'project_id': 'p', 'operation_id': 'draft',
        'definition_name': 'chapter.draft.generate', 'created_at': 'frozen'}
    if allowed:
        assert _source_version(Cursor(), source)[0] == version
    else:
        with pytest.raises(KernelError, match='SOURCE_UNPROVEN'):
            _source_version(Cursor(), source)
