import json
from pathlib import Path

import pytest

from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
from novel_forge.storage.authority_repositories import definition_hash


@pytest.mark.parametrize("version", ["none", *[f"v{i}" for i in range(1, 7)]])
def test_published_provider_policy_definition_identity_is_immutable(version):
    frozen = json.loads((Path(__file__).parents[1] / "fixtures/provider_routing_main_c621_definition_hashes.json").read_text())
    content = {} if version == "none" else {
        "execution_templates": [{"version": "creative-execution-template." + version}],
    }
    definition = owned_policy_definition(owner="PROVIDER_ROUTING", content=content,
        application_build_id="test", commit_sha="a" * 40)
    assert definition_hash(definition) == frozen["definitions"][version]["hash"]
    assert definition["definition_version"] == frozen["definitions"][version]["definition_version"]


def test_coordinated_template_uses_a_new_policy_definition_identity():
    definition = owned_policy_definition(owner="PROVIDER_ROUTING",
        content={"execution_templates": [{"version": "creative-execution-template.v11"}]},
        application_build_id="test", commit_sha="a" * 40)
    assert definition["definition_version"] == "2.0.0"
    assert definition["command_schema_version"].endswith(".v10")


def test_supervised_source_grant_can_coexist_with_author_book_template():
    template = {"execution_templates": [{"version": "creative-execution-template.v12"}]}
    ordinary = owned_policy_definition(owner="PROVIDER_ROUTING", content=template,
        application_build_id="test", commit_sha="a" * 40)
    combined = owned_policy_definition(owner="PROVIDER_ROUTING",
        content={**template, "author_supervised_authorizations": []},
        application_build_id="test", commit_sha="a" * 40)
    assert ordinary["definition_version"] == "2.1.0"
    assert combined["definition_version"] == "2.2.0"
    assert "expected_policy_hash" in combined["command_schema"]["properties"]
    assert "author_supervised_authorizations" in combined["command_schema"]["properties"]["policy"]["properties"]
