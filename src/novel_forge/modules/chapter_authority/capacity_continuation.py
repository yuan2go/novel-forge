from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.capability_pack_authority.domain import canonical_hash
from novel_forge.modules.command_kernel.errors import KernelError


PROJECTION = "chapter-complete-request-capacity.v1"
MARKER = "context_capacity_upgrade"
CAPACITY_ERRORS = frozenset({
    "TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED", "TASK_CONTEXT_COMPRESSION_NOT_AUTHORIZED",
    "TASK_CONTEXT_FIDELITY_RESTORE_EXCEEDS_BUDGET", "PROVIDER_ROUTING_BLOCKED",
    "PROVIDER_CONTEXT_LIMIT_EXCEEDED", "CONTEXT_CAPACITY_EXCEEDED",
    "CHAPTER_PROVIDER_TOKEN_CEILING_INVALID",
    "TASK_CONTEXT_COMPRESSION_NO_PROGRESS", "TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE",
})
_LOCAL_ERRORS = CAPACITY_ERRORS - {"PROVIDER_ROUTING_BLOCKED"}
_NODES = frozenset({"chapter.context.build", "chapter.draft.generate", "chapter.revision.apply"})


def capacity_decision(decision, source):
    task = decision.get("task") or {}
    expected_stage = "draft" if source["definition_name"] == "chapter.draft.generate" else "revision"
    capacity_candidates = [row for row in decision.get("candidates", ())
        if "CONTEXT_CAPACITY_EXCEEDED" in row.get("rejected_reasons", ())
        and set(row["rejected_reasons"]) <= {"CONTEXT_CAPACITY_EXCEEDED", "BUDGET_HARD_LIMIT"}]
    return bool(decision.get("status") == "BLOCKED" and decision.get("selected") is None
        and task.get("operation_id") == source["operation_id"] and task.get("task_type") == expected_stage
        and capacity_candidates and all(task.get("input_tokens", 0) + task.get("output_tokens", 0)
            > row.get("candidate", {}).get("context_limit", 0) > 0 for row in capacity_candidates))


def validate_capacity_pack_pair(original: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    old, new = deepcopy(original["manifest"]), deepcopy(target["manifest"])
    for version in (original, target):
        if (canonical_hash(version["manifest"]) != version["manifest_hash"]
                or canonical_hash(version["artifact_catalog"]) != version["artifact_catalog_hash"]):
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT", "Both immutable Pack manifests and catalogs must verify")
    context = new["context_sources"]
    target_ref = context.get("policy_id")
    methods = {"context-policy:chapter-generation-pack:v3": "shared-rules-and-native-context-contract.v1",
        "context-policy:chapter-generation-pack:v4": "source-unit-dependency-and-final-composition.v2"}
    if (old["identity"]["pack_id"] != new["identity"]["pack_id"]
            or old["context_sources"]["policy_id"] not in {
                "context-policy:chapter-generation-pack:v2", "context-policy:chapter-generation-pack:v3"}
            or target_ref not in methods
            or context.get("capacity_policy") != "complete-request-capacity.v1"
            or context.get("context_substage_method") != methods[target_ref]
            or old["context_sources"]["policy_id"] == target_ref == "context-policy:chapter-generation-pack:v4"):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED", "Activate the same owning Pack with its explicit complete-request policy")
    normalized = deepcopy(new)
    normalized["identity"]["version"] = old["identity"]["version"]
    for key in ("policy_id", "capacity_policy", "context_substage_method"):
        if key in old["context_sources"]:
            normalized["context_sources"][key] = old["context_sources"][key]
        else:
            normalized["context_sources"].pop(key, None)
    expected_tools = deepcopy(old["tool_permissions"])
    allowed_tools = deepcopy(expected_tools)
    allowed_tools.setdefault("external_models", {})["context_substages"] = ["context_compress", "context_fidelity"]
    if new["tool_permissions"] not in (expected_tools, allowed_tools):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT", "Capacity continuation cannot grant other tools or Provider permissions")
    normalized["tool_permissions"] = expected_tools
    if normalized != old:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT", "Workflow, Skills, Prompt, Schema, route and completion contracts must remain exact")
    target_artifacts = {(item["kind"], item["ref"], item["version"]): item for item in target["artifact_catalog"]["artifacts"]}
    original_artifacts = {(item["kind"], item["ref"], item["version"]): item for item in original["artifact_catalog"]["artifacts"]}
    if any(target_artifacts.get(key) != value for key, value in original_artifacts.items()):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT", "Historical artifact bytes and source identities must be retained")
    additions = set(target_artifacts) - set(original_artifacts)
    allowed_additions = {("CONTEXT_POLICY", ref, ref.rsplit(":", 1)[1]) for ref in methods
        if ref <= target_ref}
    if additions - allowed_additions:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT", "Only the complete Context policy may be added")
    policy = target_artifacts.get(("CONTEXT_POLICY", target_ref, target_ref.rsplit(":", 1)[1]))
    source_policy_ref = old["context_sources"]["policy_id"]
    source_policy = original_artifacts.get(("CONTEXT_POLICY", source_policy_ref, source_policy_ref.rsplit(":", 1)[1]))
    expected_policy = {**source_policy["content"], "policy_id": context["policy_id"],
        "capacity_policy": "complete-request-capacity.v1",
        "context_substage_method": context["context_substage_method"], "planning_task_token_budget": 512_000} if source_policy else None
    if (not policy or policy["content"].get("capacity_policy") != "complete-request-capacity.v1"
            or policy["content"].get("context_substage_method") != context["context_substage_method"]
            or policy["content"].get("max_tokens") != 512_000 or policy["content"] != expected_policy):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT", "The actual materialized Context policy must bind the supported request ceiling")
    for kind, ref, version in additions:
        expected_added = {**source_policy["content"], "policy_id": ref, "capacity_policy": "complete-request-capacity.v1",
            "context_substage_method": methods[ref], "planning_task_token_budget": 512_000}
        if target_artifacts[(kind, ref, version)]["content"] != expected_added:
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT", "Each added Context artifact must retain the exact original source policy")
    if set(new["tool_permissions"].get("external_models", {}).get("context_substages") or ()) != {"context_compress", "context_fidelity"}:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED", "Both existing Context substages must be permitted")
    return {"source_manifest_hash": original["manifest_hash"], "target_manifest_hash": target["manifest_hash"],
        "source_context_policy_ref": old["context_sources"]["policy_id"], "target_context_policy_ref": context["policy_id"],
        "target_context_policy_hash": canonical_hash(context)}


def _source_version(cursor, source):
    from novel_forge.storage.capability_pack_authority_repositories import CapabilityPackAuthorityRepository
    cursor.execute("""SELECT snapshot.pack_id,snapshot.pack_version,snapshot.manifest_hash,snapshot.snapshot_id,
            snapshot.snapshot_hash,snapshot.snapshot_payload->>'context_policy_ref'
        FROM authority_attempt_capability_pack_snapshot snapshot
        JOIN authority_operation owner ON owner.operation_id=snapshot.operation_id
        WHERE owner.root_operation_id=%s AND owner.project_id=%s
          AND (owner.operation_id=%s OR (%s='chapter.context.build' AND owner.created_at<=%s))
        ORDER BY (owner.operation_id=%s) DESC,snapshot.created_at DESC""",
        [source["root_operation_id"], source["project_id"], source["operation_id"], source["definition_name"],
         source["created_at"], source["operation_id"]])
    snapshots = cursor.fetchall()
    if not snapshots and source["definition_name"] == "chapter.context.build":
        return _source_activation(cursor, source)
    if not snapshots or len({row[:3] for row in snapshots}) != 1:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN", "The failed step requires one exact original Pack, never repository defaults")
    row = snapshots[0]
    if row[5] != "context-policy:chapter-generation-pack:v2" and source["definition_name"] != "chapter.context.build":
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN", "A complete-request failure cannot borrow a legacy capacity continuation")
    version = CapabilityPackAuthorityRepository(cursor).require_version(row[0], row[1], project_id=source["project_id"])
    if version["manifest_hash"] != row[2]:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT", "The original Attempt Pack identity changed")
    return version, {"snapshot_id": row[3], "snapshot_hash": row[4]}


def _source_activation(cursor, source):
    from novel_forge.storage.capability_pack_authority_repositories import CapabilityPackAuthorityRepository
    cursor.execute("""SELECT to_jsonb(owner),deployment.deployment_id,deployment.pack_id,deployment.pack_version
        FROM authority_operation owner JOIN authority_capability_pack_deployment deployment
          ON deployment.deployment_id=owner.command_payload->>'deployment_id'
        WHERE owner.project_id=%s AND owner.status='SUCCEEDED' AND owner.updated_at<=%s
          AND owner.definition_name=ANY(%s) AND deployment.project_id=%s AND deployment.workspace_id=%s
          AND deployment.book_id=%s AND deployment.workflow_definition_ref='chapter_authority_slice@3.10.0'
        ORDER BY owner.updated_at DESC LIMIT 1""", [source["project_id"], source["created_at"],
            ["capability_pack.deployment.activate", "capability_pack.rollback", "capability_pack.deployment.disable"],
            source["project_id"], source["workspace_id"], source["command_payload"]["book_id"]])
    row = cursor.fetchone()
    if not row or row[0]["definition_name"] == "capability_pack.deployment.disable":
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN", "A local Context without model snapshots requires its exact earlier same-Book activation receipt")
    owner, deployment_id, pack_id, version = row
    cursor.execute("SELECT 1 FROM authority_operation WHERE project_id=%s AND status='SUCCEEDED' AND updated_at<=%s AND definition_name LIKE 'capability_pack.rollout.%%' AND command_payload->>'pack_id'=%s LIMIT 1",
        [source["project_id"], source["created_at"], pack_id])
    if cursor.fetchone():
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN", "A rolled-out historical route requires its actual Attempt snapshot")
    repository = CapabilityPackAuthorityRepository(cursor)
    repository.require_deployment(deployment_id, project_id=source["project_id"])
    original = repository.require_version(pack_id, version, project_id=source["project_id"])
    return original, {"activation_operation_id": owner["operation_id"], "activation_command_hash": canonical_hash(owner["command_payload"]),
        "deployment_id": deployment_id, "source_kind": "PRIOR_SAME_BOOK_ACTIVATION_WITHOUT_MODEL_ATTEMPT"}


def _context_source(cursor, source):
    if source["definition_name"] == "chapter.context.build":
        return None
    cursor.execute("""SELECT to_jsonb(producer),version.asset_version_id,version.content_hash
        FROM authority_operation_output_asset output JOIN authority_operation producer USING(operation_id)
        JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.asset_id=output.asset_id
        JOIN authority_asset asset ON asset.asset_id=version.asset_id
        WHERE producer.root_operation_id=%s AND producer.project_id=%s AND producer.actor_id=%s
          AND producer.definition_name='chapter.context.build' AND producer.status='SUCCEEDED'
          AND output.output_key='chapter.context' AND asset.asset_type='context_bundle'
          AND version.asset_version_id=ANY(%s)""", [source["root_operation_id"], source["project_id"], source["actor_id"],
            [item["asset_version_id"] for item in source["input_asset_snapshot"]]])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN", "The original Context must have one successful same-root native producer")
    producer, version_id, digest = rows[0]
    proof = {"source_operation_id": producer["operation_id"], "asset_version_id": version_id,
        "content_hash": digest, "command_hash": canonical_hash(producer["command_payload"]),
        "input_snapshot": producer["input_asset_snapshot"]}
    _verify_context_sources(cursor, proof, source["project_id"])
    return proof


def _verify_context_sources(cursor, proof, project_id):
    for item in proof["input_snapshot"]:
        cursor.execute("""SELECT version.content_hash,version.content FROM authority_asset_version version
            JOIN authority_asset asset USING(asset_id) WHERE version.asset_version_id=%s AND asset.project_id=%s""",
            [item["asset_version_id"], project_id])
        row = cursor.fetchone()
        if not row or row[0] != item["content_hash"] or canonical_hash(row[1]) != item["content_hash"]:
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Context rebuilding requires every original immutable source, never its old summary")


def build_capacity_upgrade_policy(cursor, source, *, book_run_id, deployment_id, release_sha):
    from novel_forge.storage.capability_pack_authority_repositories import CapabilityPackAuthorityRepository
    from novel_forge.modules.command_kernel.context_transport_recovery import CONTRACT
    from novel_forge.modules.command_kernel.step_successor_v2 import has_domain_outputs

    command = source["command_payload"]
    if (source["definition_name"] not in _NODES or source["definition_version"] != "3.10.0"
            or (command.get("preparation_report") or {}).get(MARKER)
            or source["definition_name"] == "chapter.context.build" and (
                command.get("preparation_report") or {}).get("context_capacity_policy") == "complete-request-capacity.v1"):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN", "Only an original legacy capacity failure may receive this continuation")
    if source["status"] not in {"FAILED_FINAL", "DEAD_LETTER", "FAILED_RETRYABLE"}:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNSAFE", "The original step must retain its recorded capacity failure")
    cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [source["operation_id"]])
    failures = [row[0] for row in cursor.fetchall()]
    if (not failures or set(failures) - CAPACITY_ERRORS
            or source["definition_name"] == "chapter.context.build" and set(failures) - _LOCAL_ERRORS):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN", "Every failed Attempt must have the exact capacity cause")
    retained_effects = require_context_only_receipts(cursor, source)
    if has_domain_outputs(cursor, source["operation_id"]):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNSAFE", "Capacity continuation cannot retain business output from its failed owner")
    for item in source["input_asset_snapshot"]:
        cursor.execute("SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s", [item["asset_version_id"]])
        if cursor.fetchone() != (item["content_hash"],):
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Every original input version must remain hash identical")
    if "PROVIDER_ROUTING_BLOCKED" in failures:
        cursor.execute("""SELECT v.content FROM authority_operation_output_asset output
            JOIN authority_asset asset USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
            WHERE output.operation_id=%s AND asset.asset_type='routing_decision'""", [source["operation_id"]])
        decisions = [row[0] for row in cursor.fetchall()]
        if not decisions or not all(capacity_decision(row, source) for row in decisions):
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN", "Permission or paid-budget denials are not Context capacity proof")
    cursor.execute("""SELECT deployment.pack_id,deployment.pack_version FROM authority_capability_pack_activation activation
        JOIN authority_capability_pack_deployment deployment ON deployment.deployment_id=activation.active_deployment_id
        JOIN authority_capability_pack_compilation compilation USING(compilation_id)
        WHERE activation.project_id=%s AND activation.workspace_id=%s AND activation.book_id=%s
          AND activation.workflow_definition_ref='chapter_authority_slice@3.10.0'
          AND deployment.deployment_id=%s AND deployment.deployment_status='ACTIVE'
          AND compilation.release_sha=%s FOR SHARE OF activation,deployment""",
        [source["project_id"], source["workspace_id"], command["book_id"], deployment_id, release_sha])
    target = cursor.fetchone()
    if not target:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED", "The exact current compiled same-Book Pack must be active")
    original, snapshot = _source_version(cursor, source)
    successor = CapabilityPackAuthorityRepository(cursor).require_version(*target, project_id=source["project_id"])
    pair = validate_capacity_pack_pair(original, successor)
    if retained_effects and pair["target_context_policy_ref"] != "context-policy:chapter-generation-pack:v4":
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNSAFE", "Prior Context calls require the explicit semantic continuation contract")
    context_source = _context_source(cursor, source)
    cursor.execute("SELECT count(*) FROM authority_external_effect effect JOIN authority_operation owner USING(operation_id) WHERE owner.root_operation_id=%s", [source["root_operation_id"]])
    return {"contract_version": CONTRACT, "transport_projection": PROJECTION, "book_run_id": book_run_id,
        "book_id": command["book_id"], "source_operation_id": source["operation_id"], "root_operation_id": source["root_operation_id"],
        "release_sha": release_sha, "target_deployment_id": deployment_id, **pair, "source_pack_snapshot": snapshot,
        "input_snapshot": source["input_asset_snapshot"], "source_command_hash": canonical_hash(command),
        "completion_checks": "UNCHANGED", "source_failure_code": failures[-1],
        "source_retry_disposition": "DETERMINISTIC_CAPACITY_REBUILD",
        **({"context_source": context_source} if context_source else {}),
        "external_call_scope": "MAIN_UNSENT_CONTEXT_EFFECTS_RECONCILED" if retained_effects else "FAILED_STEP_ZERO_CALLS_ONLY",
        **({"retained_context_effects": retained_effects} if retained_effects else {}),
        "root_external_effect_count": cursor.fetchone()[0]}


def require_context_only_receipts(cursor, source):
    from .receipt_recovery import _receipt
    cursor.execute("SELECT external_effect_id,request_hash,request_payload,status,effect_type FROM authority_external_effect WHERE operation_id=%s ORDER BY external_effect_id", [source["operation_id"]])
    retained = []
    for identity, request_hash, payload, status, effect_type in cursor.fetchall():
        if status != "SUCCEEDED" or effect_type != "model.invoke" or payload.get("stage") not in {"context_compress", "context_fidelity"}:
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNSAFE", "Only verified completed Context calls may precede an unsent main step")
        _receipt(cursor, identity, source["project_id"], source_operation_id=source["operation_id"], allow_retryable=True)
        retained.append({"external_effect_id": identity, "request_hash": request_hash, "stage": payload["stage"]})
    cursor.execute("SELECT external_effect_id,status FROM authority_budget_reservation WHERE operation_id=%s", [source["operation_id"]])
    reservations = cursor.fetchall()
    if {row[0] for row in reservations} != {row["external_effect_id"] for row in retained} or any(row[1] != "SETTLED" for row in reservations):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_UNSAFE", "Original Context spend must be reconciled without rewriting usage")
    return retained


def require_capacity_upgrade_source(cursor, source, policy, execution_sha):
    if policy.get("transport_projection") != PROJECTION:
        return False
    if not execution_sha or policy.get("release_sha") != execution_sha:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED", "The continuation must bind this executable release")
    expected = build_capacity_upgrade_policy(cursor, source, book_run_id=policy.get("book_run_id"),
        deployment_id=policy.get("target_deployment_id"), release_sha=execution_sha)
    if dict(policy) != expected:
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "The frozen capacity continuation proof changed")
    from novel_forge.modules.command_kernel.generation_isolation import require_generation_retry_budget
    require_generation_retry_budget(cursor, operation_id=source["operation_id"])
    return True


def capacity_upgrade_command(command, policy):
    if policy.get("transport_projection") != PROJECTION:
        return command
    result = deepcopy(command)
    result.setdefault("preparation_report", {})[MARKER] = {
        "source_operation_id": policy["source_operation_id"], "policy_hash": canonical_hash(policy)}
    return result


def recover_capacity_continuation(authority, book, request, principal):
    from novel_forge.modules.command_kernel.service import AdmissionContext
    from novel_forge.modules.command_kernel.step_successor_v2 import replace_failed_step, _require_reconciled_graph
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    with AuthorityUnitOfWork(authority.database_url) as uow:
        cursor = uow.cursor
        cursor.execute("""SELECT to_jsonb(owner) FROM authority_operation owner
            JOIN authority_saga_step step USING(operation_id)
            WHERE owner.root_operation_id=%s AND owner.project_id=%s AND owner.actor_id=%s
              AND owner.definition_name=ANY(%s) AND owner.definition_version='3.10.0'
              AND owner.status IN ('FAILED_FINAL','DEAD_LETTER','FAILED_RETRYABLE')
              AND owner.command_payload#>'{preparation_report,context_capacity_upgrade}' IS NULL
              AND EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=owner.operation_id
                AND attempt.result->>'error_code'=ANY(%s))
              AND NOT EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=owner.operation_id
                AND COALESCE(attempt.result->>'error_code','')<>ALL(%s))
              AND NOT EXISTS(SELECT 1 FROM authority_saga_step_successor edge
                WHERE edge.predecessor_operation_id=owner.operation_id)
            ORDER BY owner.created_at LIMIT 1""",
            [request["chapter_root_operation_id"], book["project_id"], principal.principal_id,
             sorted(_NODES), sorted(CAPACITY_ERRORS), sorted(CAPACITY_ERRORS)])
        row = cursor.fetchone()
        if not row:
            return False
        source = row[0]
        if source["definition_name"] == "chapter.context.build" and (
                source["command_payload"].get("preparation_report") or {}).get("context_capacity_policy"):
            return False
        cursor.execute("""SELECT deployment.deployment_id FROM authority_capability_pack_activation activation
            JOIN authority_capability_pack_deployment deployment ON deployment.deployment_id=activation.active_deployment_id
            JOIN authority_capability_pack_compilation compilation USING(compilation_id)
            JOIN authority_capability_pack_version version ON version.pack_id=deployment.pack_id AND version.pack_version=deployment.pack_version
            JOIN authority_asset_version manifest ON manifest.asset_version_id=version.manifest_asset_version_id
            WHERE activation.project_id=%s AND activation.workspace_id=%s AND activation.book_id=%s
              AND activation.workflow_definition_ref='chapter_authority_slice@3.10.0'
              AND deployment.deployment_status='ACTIVE' AND compilation.release_sha=%s
              AND manifest.content#>>'{context_sources,capacity_policy}'='complete-request-capacity.v1'""",
            [book["project_id"], book["workspace_id"], book["book_id"], authority.commit_sha])
        deployments = cursor.fetchall()
        if len(deployments) != 1:
            return False
        try:
            _require_reconciled_graph(cursor, root_id=source["root_operation_id"], predecessor_id=source["operation_id"])
            policy = build_capacity_upgrade_policy(cursor, source, book_run_id=book["book_run_id"],
                deployment_id=deployments[0][0], release_sha=authority.commit_sha)
        except KernelError as error:
            if error.code in {"CHAPTER_UNSENT_TRANSPORT_RETRY_REMAINS", "STEP_SUCCESSOR_GRAPH_UNRECONCILED",
                              "EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED", "CHAPTER_CAPACITY_UPGRADE_SOURCE_UNPROVEN"}:
                return False
            if source["definition_name"] != "chapter.context.build" and error.code == "CHAPTER_CAPACITY_UPGRADE_PACK_DRIFT":
                return False
            raise
    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version="3.10.0",
        context=AdmissionContext(principal.principal_id, principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
        policy_evidence=policy, expected_failure_code=policy["source_failure_code"],
        **({"known_receipt_effects": tuple((row["external_effect_id"], row["request_hash"]) for row in policy["retained_context_effects"])} if policy.get("retained_context_effects") else {}))
    return True


def bind_context_capacity_upgrade(request):
    from dataclasses import replace
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier

    declared = (request.command.get("preparation_report") or {}).get(MARKER)
    inherited = [(item, item.content.get("capacity_policy_upgrade")) for item in request.inputs
                 if item.asset_type == "context_bundle" and item.content.get("capacity_policy_upgrade")]
    context_inputs = [item for item in request.inputs if item.asset_type == "context_bundle"]
    recovered_context = None
    if declared is None and not inherited:
        legacy = [item for item in context_inputs if ((item.content.get("context_manifest") or {}).get("task_context_receipt") or {}).get("capacity_admission") == "MATERIAL_TARGET"]
        if len(legacy) != 1:
            return request
        with AuthorityUnitOfWork(request.database_url) as uow:
            rows = uow.cursor.execute("""SELECT edge.policy_evidence,edge.successor_operation_id FROM authority_saga_step_successor edge
                JOIN authority_operation current ON current.operation_id=%s
                  AND current.root_operation_id=edge.policy_evidence->>'root_operation_id'
                WHERE edge.project_id=%s AND edge.policy_evidence->>'transport_projection'=%s
                  AND edge.policy_evidence#>>'{context_source,asset_version_id}'=%s""",
                [request.operation_id, request.project_id, PROJECTION, legacy[0].asset_version_id]).fetchall()
        if not rows:
            return request
        if len(rows) != 1:
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "A retained Context cannot borrow ambiguous capacity continuations")
        recovered_context = legacy[0]
        marker = {"source_operation_id": rows[0][0]["source_operation_id"], "policy_hash": canonical_hash(rows[0][0])}
    else:
        marker = declared if declared is not None else inherited[0][1]
    if not isinstance(marker, Mapping) or not marker.get("source_operation_id") or not marker.get("policy_hash"):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "A capacity override requires its native successor journal")
    with AuthorityUnitOfWork(request.database_url) as uow:
        cursor = uow.cursor
        cursor.execute("""SELECT edge.policy_evidence,edge.successor_operation_id,to_jsonb(source),to_jsonb(successor),to_jsonb(current)
            FROM authority_saga_step_successor edge
            JOIN authority_operation source ON source.operation_id=edge.predecessor_operation_id
            JOIN authority_operation successor ON successor.operation_id=edge.successor_operation_id
            JOIN authority_operation current ON current.operation_id=%s AND current.project_id=edge.project_id
            WHERE edge.predecessor_operation_id=%s AND edge.project_id=%s""",
            [request.operation_id, marker["source_operation_id"], request.project_id])
        row = cursor.fetchone()
        if not row:
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "An unregistered capacity marker grants no authority")
        policy, successor_id, source, successor, current = row
        if (policy.get("transport_projection") != PROJECTION or canonical_hash(policy) != marker["policy_hash"]
                or canonical_hash(source["command_payload"]) != policy["source_command_hash"]
                or source["input_asset_snapshot"] != successor["input_asset_snapshot"]
                or successor["command_payload"] != capacity_upgrade_command(source["command_payload"], policy)
                or current["root_operation_id"] != policy["root_operation_id"]
                or current["actor_id"] != successor["actor_id"] or current["workspace_id"] != successor["workspace_id"]
                or request.command != current["command_payload"]):
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Capacity continuation must retain its exact original command, inputs and owner")
        if request.operation_id != successor_id:
            if recovered_context is not None:
                proof = policy.get("context_source") or {}
                if (recovered_context.asset_version_id != proof.get("asset_version_id")
                        or recovered_context.content_hash != proof.get("content_hash")):
                    raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Downstream Context must retain the original frozen version")
                _verify_context_sources(cursor, proof, request.project_id)
            elif declared is not None or len(inherited) != 1 or inherited[0][1] != {
                    **policy, "policy_hash": marker["policy_hash"], "successor_operation_id": successor_id}:
                raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Only the Context successor may pass this derived contract downstream")
            else:
                context = inherited[0][0]
                cursor.execute("SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s AND asset_version_id=%s AND content_hash=%s AND output_key='chapter.context'",
                    [successor_id, context.asset_version_id, context.content_hash])
                if cursor.fetchone() != (1,):
                    raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "The inherited Context must be the exact native successor output")
        require_live_chapter_frontier(cursor, root_id=policy["root_operation_id"], project_id=request.project_id,
                                      book_run_id=policy["book_run_id"])
        cursor.execute("""SELECT 1 FROM authority_capability_pack_activation activation
            JOIN authority_capability_pack_deployment deployment ON deployment.deployment_id=activation.active_deployment_id
            JOIN authority_capability_pack_compilation compilation USING(compilation_id)
            JOIN authority_capability_pack_version version ON version.pack_id=deployment.pack_id AND version.pack_version=deployment.pack_version
            WHERE activation.project_id=%s AND activation.workspace_id=%s AND activation.book_id=%s
              AND deployment.deployment_id=%s AND deployment.deployment_status='ACTIVE'
              AND compilation.release_sha=%s AND version.manifest_hash=%s""",
            [request.project_id, request.workspace_id, policy["book_id"], policy["target_deployment_id"],
             policy["release_sha"], policy["target_manifest_hash"]])
        if cursor.fetchone() != (1,):
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED", "The upgrade cannot silently adopt a different active Pack")
    return replace(request, capacity_upgrade={**policy, "policy_hash": marker["policy_hash"],
                                             "successor_operation_id": successor_id})


def rebuild_frozen_capacity_context(request, registry):
    from dataclasses import replace
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from .contracts import ChapterInputAsset, ChapterNode

    upgrade = request.capacity_upgrade or {}
    proof = upgrade.get("context_source")
    if not proof:
        return request
    with AuthorityUnitOfWork(request.database_url) as uow:
        cursor = uow.cursor
        producer = cursor.execute("SELECT command_payload,input_asset_snapshot FROM authority_operation WHERE operation_id=%s AND project_id=%s",
            [proof["source_operation_id"], request.project_id]).fetchone()
        if not producer or canonical_hash(producer[0]) != proof["command_hash"] or producer[1] != proof["input_snapshot"]:
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Original Context command and source versions must remain exact")
        _verify_context_sources(cursor, proof, request.project_id)
        inputs = []
        for item in proof["input_snapshot"]:
            asset_type, content = cursor.execute("SELECT asset.asset_type,version.content FROM authority_asset_version version JOIN authority_asset asset USING(asset_id) WHERE version.asset_version_id=%s",
                [item["asset_version_id"]]).fetchone()
            inputs.append(ChapterInputAsset(item["asset_version_id"], asset_type, item["content_hash"], content))
    frozen = replace(request, operation_id=upgrade["successor_operation_id"], command=producer[0], inputs=tuple(inputs))
    rebuilt = registry.require(ChapterNode.CONTEXT).execute(frozen).content
    if ((rebuilt.get("context_manifest") or {}).get("task_context_receipt") or {}).get("compression_trace"):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Context reconstruction must defer compression to complete request admission")
    return replace(request, capacity_context_derivation={"contract_version": "frozen-context-rebuild.v1",
        "source": proof, "policy_hash": upgrade["policy_hash"], "content_hash": canonical_hash(rebuilt), "content": rebuilt})


def require_capacity_upgrade_binding(upgrade, snapshot):
    if upgrade is None:
        return
    if not isinstance(upgrade, Mapping) or not all(upgrade.get(key) for key in (
            "target_deployment_id", "target_manifest_hash", "target_context_policy_ref", "target_context_policy_hash")):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED", "A declared upgrade requires its complete original target binding")
    if (snapshot.deployment_id != upgrade["target_deployment_id"]
            or snapshot.manifest_hash != upgrade["target_manifest_hash"]
            or snapshot.context_policy_ref != upgrade["target_context_policy_ref"]
            or snapshot.context_policy_hash != upgrade["target_context_policy_hash"]):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_TARGET_REQUIRED", "The actual Attempt must execute the exact upgraded Context contract")


def capacity_rebuilt_content(derivation, upgrade, original):
    source = (upgrade or {}).get("context_source")
    if (not source or derivation.get("contract_version") != "frozen-context-rebuild.v1"
            or derivation.get("source") != source or derivation.get("policy_hash") != upgrade.get("policy_hash")
            or original.get("asset_version_id") != source["asset_version_id"]
            or original.get("content_hash") != source["content_hash"]
            or canonical_hash(derivation.get("content")) != derivation.get("content_hash")
            or derivation["content"].get("capacity_policy_upgrade") != upgrade
            or ((derivation["content"].get("context_manifest") or {}).get("task_context_receipt") or {}).get("capacity_admission") != "DEFERRED_COMPLETE_REQUEST"):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "The sent Context derivation must bind the verified original producer and exact rebuilt content")
    return derivation["content"]


def effective_context_content(request, context=None):
    context = context if context is not None else request.require_input("context_bundle")
    derivation = getattr(request, "capacity_context_derivation", None)
    if not derivation:
        return context.content
    return capacity_rebuilt_content(derivation, request.capacity_upgrade,
        {"asset_version_id": context.asset_version_id, "content_hash": context.content_hash})


def bind_retained_capacity_context(request, *, asset_reader):
    marker = (request.command.get("preparation_report") or {}).get(MARKER)
    if not marker:
        return request
    cursor = getattr(asset_reader, "cursor", None)
    if cursor is None:
        database_url = getattr(asset_reader, "database_url", None)
        if database_url:
            from novel_forge.storage.authority_uow import AuthorityUnitOfWork
            with AuthorityUnitOfWork(database_url) as uow:
                return bind_retained_capacity_context(request, asset_reader=uow.repositories.asset_documents)
        raise KernelError("CHAPTER_CAPACITY_RETAINED_CONTEXT_REQUIRED", "Read the original frozen Effect through its owning receipt transaction")
    from dataclasses import replace
    from .receipt_recovery import _receipt

    cursor.execute("""SELECT external_effect_id,request_hash,request_payload FROM authority_external_effect
        WHERE project_id=%s AND operation_id=%s AND effect_type='model.invoke'
          AND request_payload->>'stage'='draft' ORDER BY external_effect_id""", [request.project_id, request.operation_id])
    effects = cursor.fetchall()
    if not effects:
        raise KernelError("CHAPTER_CAPACITY_RETAINED_CONTEXT_REQUIRED", "An upgraded retained Draft requires its original complete model Effect")
    frozen = None
    for effect_id, digest, payload in effects:
        _receipt(cursor, effect_id, request.project_id, source_operation_id=request.operation_id,
                 allow_completed=True, allow_retryable=True)
        upgrade = (payload.get("input") or {}).get("_context_capacity_upgrade")
        derivation = (payload.get("input") or {}).get("_context_capacity_rebuild")
        if (canonical_hash(payload) != digest or not upgrade or not derivation
                or upgrade.get("policy_hash") != marker.get("policy_hash")
                or upgrade.get("source_operation_id") != marker.get("source_operation_id")):
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Retained Context must come from the exact verified original Effect")
        cursor.execute("SELECT policy_evidence,successor_operation_id FROM authority_saga_step_successor WHERE predecessor_operation_id=%s AND project_id=%s",
            [marker["source_operation_id"], request.project_id])
        journal = cursor.fetchone()
        if (not journal or canonical_hash(journal[0]) != marker["policy_hash"]
                or upgrade != {**journal[0], "policy_hash": marker["policy_hash"], "successor_operation_id": journal[1]}
                or journal[1] != request.operation_id):
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Retained Context requires its original native capacity successor")
        candidate = replace(request, capacity_upgrade=upgrade, capacity_context_derivation=derivation)
        effective_context_content(candidate)
        _verify_context_sources(cursor, derivation["source"], request.project_id)
        if frozen is not None and frozen != (upgrade, derivation):
            raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Original Draft Effects cannot disagree on their frozen Context")
        frozen = upgrade, derivation
    return replace(request, capacity_upgrade=frozen[0], capacity_context_derivation=frozen[1])
