import pytest

from novel_forge.modules.chapter_authority.receipt_recovery import _require_current_receipt_family
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.mark.parametrize("version", ["3.9.0", "3.9.1", "3.9.2", "3.10.1"])
def test_old_paid_draft_cannot_satisfy_new_mandatory_actor_source_contract(version):
    with pytest.raises(KernelError, match="KNOWN_RECEIPT_HISTORICAL_CONTRACT_BLOCKED"):
        _require_current_receipt_family({"definition_name": "chapter.draft.generate", "definition_version": version})


def test_current_paid_draft_retains_current_schema_family():
    _require_current_receipt_family({"definition_name": "chapter.draft.generate", "definition_version": "3.10.0",
        "definition_snapshot": {"policy": {"scene_core_projection": "continuous-scene.v1", "scene_information_flow": "actor-source-scope.v1"}}})


@pytest.mark.parametrize("policy", [{}, {"scene_core_projection": "continuous-scene.v1"},
    {"scene_core_projection": "scene-core-slots.v1", "scene_information_flow": "actor-source-scope.v1"}])
def test_current_version_tag_cannot_replace_frozen_mandatory_policy(policy):
    with pytest.raises(KernelError, match="KNOWN_RECEIPT_HISTORICAL_CONTRACT_BLOCKED"):
        _require_current_receipt_family({"definition_name": "chapter.draft.generate", "definition_version": "3.10.0", "definition_snapshot": {"policy": policy}})
