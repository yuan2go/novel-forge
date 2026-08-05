from __future__ import annotations

import pytest

from novel_forge.modules.agent_runtime.bootstrap import (
    LegacyAgentProfileBootstrapAdapter,
)


HASH = "sha256:" + "a" * 64


def test_legacy_profile_is_only_an_explicit_registration_adapter() -> None:
    adapter = LegacyAgentProfileBootstrapAdapter(
        {
            "draft": {
                "agent": "Draft Agent",
                "permission_profile": "candidate-only",
                "allowed_tools": ["request_production_execution"],
                "allowed_write_types": ["draft_candidate"],
                "forbidden": ["commit_asset"],
            }
        }
    )

    payload = adapter.registration_payload(
        agent_id="draft",
        definition_version=1,
        capability_id="prose.chapter.draft",
        capability_version=1,
        execution_capability_id="prose.chapter.draft",
        execution_capability_hash=HASH,
        capability_pack_ref="chapter-generation-pack@1",
        prompt_bundle_ref="prompt:draft@1",
        prompt_bundle_hash=HASH,
        skill_bundle_ref="skill:prose-generation@1",
        skill_bundle_hash=HASH,
        tool_policy_ref="tools:draft@1",
        context_policy_ref="context:draft@1",
    )

    assert adapter.production_registry is False
    assert adapter.fallback_allowed is False
    assert payload["runtime_contract"]["definition_source"] == "BOOTSTRAP_ADAPTER"
    assert payload["legacy_usage"]["silent_fallback"] is False
    assert payload["definition"]["status"] == "CANDIDATE"
    assert payload["capability"]["qualification_status"] == "UNQUALIFIED"


def test_bootstrap_adapter_never_synthesizes_a_missing_profile() -> None:
    adapter = LegacyAgentProfileBootstrapAdapter({})

    with pytest.raises(KeyError, match="does not exist"):
        adapter.registration_payload(
            agent_id="missing",
            definition_version=1,
            capability_id="capability",
            capability_version=1,
            execution_capability_id="execution",
            execution_capability_hash=HASH,
            capability_pack_ref="pack@1",
            prompt_bundle_ref="prompt@1",
            prompt_bundle_hash=HASH,
            skill_bundle_ref="skill@1",
            skill_bundle_hash=HASH,
            tool_policy_ref="tools@1",
            context_policy_ref="context@1",
        )
