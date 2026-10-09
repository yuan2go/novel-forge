from __future__ import annotations

from dataclasses import replace
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.capability_packs.validation_deployment import install_chapter_validation_pack, install_longform_validation_pack
from novel_forge.modules.production_execution.membership_identity import observe_membership_identity
from novel_forge.modules.production_execution.cost_routing import TASK_TAXONOMY
from novel_forge.modules.production_execution.process_supervisor import PersistentExecutionDirectory
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.unit.test_creative_execution_template import template


class MemoryObjectClient:
    def __init__(self):
        self.objects = {}

    def bucket_exists(self, _bucket):
        return True

    def put_object(self, bucket, key, stream, *, length, metadata=None, **_):
        data = stream.read()
        assert len(data) == length
        self.objects[bucket, key] = (data, metadata or {})
        return SimpleNamespace(etag=hashlib.sha256(data).hexdigest())

    def stat_object(self, bucket, key):
        if (bucket, key) not in self.objects:
            error = RuntimeError("isolated object absent")
            error.code = "NoSuchKey"
            raise error
        data, metadata = self.objects[bucket, key]
        return SimpleNamespace(size=len(data), metadata=metadata)

    def get_object(self, bucket, key):
        response = BytesIO(self.objects[bucket, key][0])
        response.release_conn = lambda: None
        return response


def prepare_native_template(harness, chapter_pack, *, bounded_repairs=False, world_disabled=False, contract_recovery=False):
    actor = replace(harness.compiler, permissions=harness.compiler.permissions | {"book.authority.execute", "agent.authority.admin"})
    value = template(harness.book_ids[0])
    if bounded_repairs:
        value.update(version="creative-execution-template.v2", repair_routing={
            "version": "native-repair-routing.v1", "max_same_route_repairs": 2})
    if world_disabled:
        value.update(version='creative-execution-template.v3',world_future_preparation='DISABLED',repair_routing={
            'version':'native-repair-routing.v1','max_same_route_repairs':2})
    if contract_recovery:
        value.update(version='creative-execution-template.v5', chapter_contract_recovery='KNOWN_SETTLED_CONTRACT_REPAIR',
            world_future_preparation='DISABLED',repair_routing={'version':'native-repair-routing.v2','max_same_route_repairs':2})
    value["allowed_candidates"] = ["codex-cli:gpt-test:high"]
    configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=harness.project_id,
        workspace_id=harness.workspace_id, principal=actor, application_build_id=harness.application_build_id,
        commit_sha=harness.release_sha, idempotency_key=harness.project_id + ":creative-template", trace_id=harness.project_id,
        correlation_id=harness.project_id, content={"policy_version": "creative-e2e.v1", "task_overrides": [], "reason": "controlled process fixture; no real Provider evidence", "execution_templates": [value]})
    install_chapter_validation_pack(DATABASE_URL, repository_root=Path(__file__).resolve().parents[2],
        project_id=harness.project_id, workspace_id=harness.workspace_id, book_id=harness.book_ids[0],
        application_build_id=harness.application_build_id, commit_sha=harness.release_sha,
        compiler=actor, approver=actor, agent_admin=actor, pack_id_override=chapter_pack.pack_id)
    return actor


def install_planning(harness, profile, actor):
    return install_longform_validation_pack(DATABASE_URL, profile=profile, pack_version="1.1.0", agent_generation=1,
        expected_activation_version=0, project_id=harness.project_id, workspace_id=harness.workspace_id,
        book_id=harness.book_ids[0], application_build_id=harness.application_build_id, commit_sha=harness.release_sha,
        compiler=actor, approver=actor, agent_admin=actor, agent_domain="story_planning", agent_scope_type="BOOK")


def controlled_member_environment(root, env, monkeypatch, transport):
    from tests.unit.test_chapter_authority_dependencies import _mixed_router_environment
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver

    values = _mixed_router_environment(root)
    values.pop("DEEPSEEK_API_KEY")
    for key in list(values):
        if key.endswith(("CALL_LIMIT", "TOKEN_LIMIT")) or key == "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL":
            values.pop(key)
    values["NOVEL_FORGE_ROUTER_PROVIDERS"] = "codex-cli"
    values["NOVEL_FORGE_RESOURCE_CONTROL_VERSION"] = "billing-channel-resources.v1"
    values["NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF"] = "member-grant"
    (root / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"account_id": "controlled-fixture-account", "access_token": "not-a-real-token", "refresh_token": "not-a-real-token"}}))
    values["NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF"] = observe_membership_identity(str(root))["account_ref"]
    values["NOVEL_FORGE_CODEX_ROUTER_MODELS"] = json.dumps({"contract_version": "codex-router-models.v1", "models": [{"model": "gpt-test", "reasoning": "high", "role": "PRIMARY", "tasks": list(TASK_TAXONOMY), "context_limit": 512000, "output_limit": 32000}]})
    values.update(NOVEL_FORGE_CODEX_ESCALATION_CONTEXT_LIMIT="512000", NOVEL_FORGE_PROVIDER_MODEL_OUTPUT_LIMIT="32000")
    executable = Path(values["NOVEL_FORGE_CODEX_EXECUTABLE"])
    executable.write_text(f'''#!{sys.executable}
import json,pathlib,sys
if "--version" in sys.argv:
 print("codex-test 1.0")
else:
 sys.stdin.read()
 target=pathlib.Path(sys.argv[sys.argv.index("--output-last-message")+1])
 target.write_bytes(target.with_name("fixture-response.json").read_bytes())
 print(json.dumps({{"type":"thread.started","thread_id":"controlled-fixture"}}))
 print(json.dumps({{"type":"turn.completed","usage":{{"input_tokens":100,"output_tokens":100,"cached_input_tokens":0}}}}))
''')
    values["NOVEL_FORGE_CODEX_EXECUTABLE_SHA256"] = "sha256:" + hashlib.sha256(executable.read_bytes()).hexdigest()
    values = {**env, **values, "NOVEL_FORGE_APPLICATION_BUILD_ID": env["NOVEL_FORGE_APPLICATION_BUILD_ID"], "NOVEL_FORGE_COMMIT_SHA": env["NOVEL_FORGE_COMMIT_SHA"]}
    values.pop("NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE", None)
    object_client = MemoryObjectClient()
    monkeypatch.setattr("novel_forge.storage.object_store.MinioObjectStore", lambda _: SimpleNamespace(client=object_client))
    resolve = PostgresProductionExecutionPayloadResolver.resolve

    def fixture_process_response(resolver, request, admission):
        payload = resolve(resolver, request, admission)
        from novel_forge.storage.authority_uow import AuthorityUnitOfWork
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT request_payload->'input' FROM authority_external_effect WHERE external_effect_id=%s", [request.external_effect_id])
            inputs = uow.cursor.fetchone()[0]
        stage = request.stage
        from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS
        from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
        if stage in FOUNDATION_GENERATORS or stage.endswith(".generate"):
            result = transport.planning(stage, inputs)
        elif stage.startswith("world_"):
            result = transport.planning(stage, inputs)
        else:
            result = transport.chapter(stage, inputs) if stage not in {"agent_session", "retrieval", "retrieval_query_expansion"} else default_chapter_fixture_response(stage, inputs)
        if stage.startswith("quality_"):
            if payload.output_schema_version.endswith(":v5"):
                methods=inputs["quality_context"]["creative_baseline"]["method_requirements"]
                for dimension in result.get("dimensions",[]):
                    if methods.get(dimension['dimension'],{}).get('status') in {'NOT_APPLICABLE','PROHIBITED'}:
                        dimension.update(gate_status='NOT_APPLICABLE',score=None,evidence_locations=[],issue_codes=[],revision_strategies=[])
            for dimension in result.get("dimensions", []):
                for location in dimension.get("evidence_locations", []):
                    quote = inputs["revision"]["text"][location["start"]:location["end"]]
                    location.clear()
                    location["quote"] = quote
                    location["claim"] = "Controlled fixture observation: " + dimension["dimension"]
        if stage == "canon_extraction":
            typed_envelope = "payload_json" in result
            if typed_envelope:
                result = json.loads(result["payload_json"])
            for fact in result["canon_facts"]:
                fact.update(effective_from_chapter=inputs["revision"]["chapter"],
                    supersedes_event_id=None, impact_type="canon_fact")
            for realization in result.get("realization_evidence", []):
                for evidence in realization.get("accepted_prose_evidence", []):
                    evidence["quote"] = inputs["revision"]["text"][:100]
            def nullable(schema):
                kind = schema.get("type", [])
                return "null" in (kind if isinstance(kind, list) else [kind]) or any(nullable(child) for child in schema.get("anyOf", []))
            def project_schema(value, schema):
                if isinstance(value, dict):
                    properties = schema.get("properties", {})
                    if schema.get("additionalProperties") is False:
                        value = {key: item for key, item in value.items() if key in properties}
                    for key in schema.get("required", []):
                        if key not in value and nullable(properties.get(key, {})):
                            value[key] = None
                    return {key: project_schema(item, properties.get(key, {})) for key, item in value.items()}
                if isinstance(value, list):
                    return [project_schema(item, schema.get("items", {})) for item in value]
                return value
            from novel_forge.modules.chapter_authority.provider_output_contracts import inline_shared_canon_schema
            result = project_schema(result, inline_shared_canon_schema(payload.output_schema.get("x-host-payload-schema", payload.output_schema)))
            if typed_envelope:
                result = {"payload_json": json.dumps(result, ensure_ascii=False)}
        if stage in {"review", "rereview"}:
            for collection in ("issues", "resolution_checks", "knowledge_checks"):
                for issue in result.get(collection, []):
                    if isinstance(issue.get("evidence"), dict) and "quote" in issue["evidence"]:
                        issue["evidence"] = {"quote": issue["evidence"]["quote"]}
        if (payload.output_schema and payload.output_schema.get("additionalProperties") is False
                and payload.output_schema_version != "schema:chapter-provider-output:canon_extraction:v25"):
            result = {key: value for key, value in result.items() if key in payload.output_schema["properties"]}
        if payload.output_schema_version == "schema:chapter-provider-output:canon_extraction:v25":
            result = {"output_json": json.dumps(result, ensure_ascii=False, allow_nan=False)}
        layout = PersistentExecutionDirectory(values["NOVEL_FORGE_CODEX_EXECUTION_ROOT"]).prepare(request.execution_id)
        layout.result_path("fixture-response.json").write_text(json.dumps(result, ensure_ascii=False))
        return payload

    monkeypatch.setattr(PostgresProductionExecutionPayloadResolver, "resolve", fixture_process_response)
    return values
