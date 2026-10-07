from __future__ import annotations

from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.capability_pack_authority.runtime import CapabilityPackRuntimeResolver
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext, execute_transaction_command
from novel_forge.modules.production_execution.execution_template import verify_template_provenance
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .binder import PlanningCapabilityBinding, _identity
from .domain import FrozenPlanningInput, PlanningExecutionEvidence, PlanningGenerationCandidate, build_planning_constraint_envelope, canonical_hash
from .foundation_generation import FOUNDATION_GENERATORS, validate_foundation_payload
from .result_recovery import require_result_repair_source

NAME = "story_planning.result_admission.recover"
HANDLER = "novel_forge." + NAME


def recover(application, *, source_operation_id, project_id, source_asset_version_id, reason, principal):
    from .application import _command_from_payload

    principal.require("story_planning.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR or not str(reason).strip():
        raise PermissionError("Result admission recovery requires a trusted operator and an explicit reason")
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute("""SELECT r.recovery_id,r.recovery_operation_id,r.candidate_asset_version_id,v.content_hash,r.evidence,o.status
            FROM authority_planning_result_admission r JOIN authority_asset_version v ON v.asset_version_id=r.candidate_asset_version_id
            JOIN authority_operation o ON o.operation_id=r.recovery_operation_id
            WHERE r.source_operation_id=%s AND r.project_id=%s""", [source_operation_id,project_id])
        existing = uow.cursor.fetchone()
        if existing:
            if (existing[5] != "SUCCEEDED" or existing[4]["source_result_asset_version_id"] != source_asset_version_id
                    or existing[4]["reason"] != reason or existing[4]["operator_id"] != principal.principal_id
                    or existing[4]["target_release_sha"] != application.commit_sha):
                raise KernelError("PLANNING_RESULT_ADMISSION_IDEMPOTENCY_CONFLICT", "Existing recovery belongs to a different frozen decision")
            return {"recovery_id":existing[0],"operation_id":existing[1],"asset_version_id":existing[2],
                "content_hash":existing[3],"source_operation_id":source_operation_id,"provider_invoked":False,"replayed":True}
        uow.cursor.execute("""SELECT o.command_payload->'payload',g.input_snapshot,g.version
            FROM authority_operation o JOIN authority_story_planning_generation g USING(operation_id)
            WHERE o.operation_id=%s AND o.project_id=%s""", [source_operation_id, project_id])
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("PLANNING_RESULT_ADMISSION_SOURCE_INVALID", source_operation_id)
    command = _command_from_payload(row[0])
    if command.generator_operation_name not in FOUNDATION_GENERATORS or command.world_preparation_request:
        raise KernelError("PLANNING_RESULT_ADMISSION_SCOPE_INVALID", "Result admission supports frozen Foundation results; it cannot replace Planning or world execution authorities")
    retained = require_result_repair_source(application.database_url, command=command, operation_id=source_operation_id,
        source_asset_version_id=source_asset_version_id, require_valid_result=True,
        result_validation_contract_version="1.19.0")
    evidence = retained["execution_evidence"]
    effect_id = evidence["external_receipt_ref"]
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute("SELECT request_payload FROM authority_external_effect WHERE external_effect_id=%s AND operation_id=%s", [effect_id, source_operation_id])
        effect = uow.cursor.fetchone()
        if effect is None:
            raise KernelError("PLANNING_RESULT_ADMISSION_RECEIPT_INVALID", source_operation_id)
        runtime = effect[0]["_production_execution"]["capability_runtime"]
        policy = verify_template_provenance(uow.cursor, runtime["routing_decision"])
        if (not policy or policy["mode"] != "CREATIVE_VALIDATION" or policy["require_literary_qualification"]
                or runtime["routing_decision"]["task"]["project_id"] != project_id or policy["book_id"] != command.book_id
                or runtime["routing_decision"]["status"] != "SELECTED"
                or runtime["routing_decision"]["task"]["operation_id"] != source_operation_id):
            raise KernelError("PLANNING_RESULT_ADMISSION_POLICY_REQUIRED", "Result processing cannot confer strict production qualification")
    snapshot = CapabilityPackRuntimeResolver(application.database_url).require_attempt_snapshot(
        attempt_id=evidence["attempt_id"], snapshot_id=runtime["snapshot_id"], snapshot_hash=runtime["snapshot_hash"])
    if snapshot.operation_id != source_operation_id or snapshot.execution_fencing_token != evidence["fencing_token"]:
        raise KernelError("PLANNING_RESULT_ADMISSION_SNAPSHOT_DRIFT", source_operation_id)
    frozen = snapshot.execution_snapshot
    context = retained["context_content"]
    selection_digest = context["narrative_intelligence"]["selection_digest"]
    binding = PlanningCapabilityBinding(binding_id=_identity("planning-capability-binding", evidence["attempt_id"]),
        operation_id=source_operation_id, attempt_id=evidence["attempt_id"], fencing_token=evidence["fencing_token"],
        project_id=project_id, workspace_id=command.workspace_id, book_id=command.book_id,
        capability_ref=frozen.capability_ref, capability_hash=frozen.capability_hash,
        execution_capability_id=frozen.execution_capability_id, execution_capability_hash=frozen.execution_capability_hash,
        input_manifest_ref=evidence["input_manifest_ref"], context_bundle_asset_version_id=retained["context_asset_version_id"],
        context_bundle_hash=retained["context_hash"], narrative_intelligence_selection_digest=selection_digest,
        commit_authority=frozen.commit_authority, capability_pack_attempt_snapshot_id=snapshot.snapshot_id,
        capability_pack_attempt_snapshot_hash=snapshot.snapshot_hash)
    pep = PlanningExecutionEvidence(**{key: evidence[key] for key in (
        "operation_id", "attempt_id", "fencing_token", "route_snapshot_id", "input_manifest_ref", "output_manifest_ref",
        "validation_manifest_ref", "usage_receipt_ref", "cost_receipt_ref", "external_receipt_ref", "fixture_protocol_only")},
        capability_pack_attempt_snapshot_id=snapshot.snapshot_id, capability_pack_attempt_snapshot_hash=snapshot.snapshot_hash,
        capability_execution_ref=binding.binding_id, capability_execution_hash=binding.binding_hash,
        capability_runtime_binding_ref=snapshot.snapshot_id, capability_runtime_binding_hash=snapshot.snapshot_hash,
        commit_authority=frozen.commit_authority, real_provider_proven=bool(evidence.get("real_model_call") and not evidence["fixture_protocol_only"]),
        context_bundle_asset_version_id=retained["context_asset_version_id"], context_bundle_hash=retained["context_hash"],
        narrative_intelligence_selection_digest=selection_digest)
    inputs = tuple(FrozenPlanningInput(**item) for item in row[1])
    query = AuthorityAssetQuery(application.database_url)
    contents = {}
    for item in inputs:
        document = query.require(project_id=project_id, asset_version_id=item.asset_version_id)
        if document.content_hash != item.content_hash or document.asset_type != item.asset_type:
            raise KernelError("PLANNING_RESULT_ADMISSION_INPUT_DRIFT", item.asset_version_id)
        contents[item.role] = document.content
    selection = context["narrative_intelligence"]
    if selection.get("policy_version") == "knowledge-grounded-selection-v2":
        from .knowledge_translation import validate_knowledge_translations
        validate_knowledge_translations(retained["raw_result"], selection)
    candidate = PlanningGenerationCandidate(command.generator_operation_name, command.planning_scope, command.logical_key,
        retained["raw_result"], inputs, pep)
    envelope = build_planning_constraint_envelope(project_id=project_id, book_id=command.book_id,
        generation_operation_id=source_operation_id, generator_operation_name=command.generator_operation_name,
        frozen_inputs=inputs, input_contents=contents, candidate_payload=candidate.candidate_payload,
        work_requirements=command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.20.0"}, aligned_methods=command.execution_contract_version in {"1.18.0", "1.19.0", "1.20.0"},
        rfc6901_paths=True)
    if envelope.get("author_design"):
        envelope["author_design_projection"] = context["author_design_projection"]
    content = candidate.authority_content(project_id=project_id, book_id=command.book_id, constraint_envelope=envelope)
    if selection.get("policy_version") == "knowledge-grounded-selection-v2":
        content["knowledge_translation_policy_version"] = selection["policy_version"]
    validate_foundation_payload(command.generator_operation_name, content)
    recovery_id = "planning-result-admission:" + canonical_hash([project_id, source_operation_id]).removeprefix("sha256:")
    provenance = {"contract_version": "planning-result-admission.v1", "recovery_id": recovery_id,
        "source_operation_id": source_operation_id, "source_result_asset_version_id": retained["asset_version_id"],
        "source_result_hash": canonical_hash(retained["raw_result"]), "source_context_asset_version_id": retained["context_asset_version_id"],
        "source_context_hash": retained["context_hash"], "external_effect_id": effect_id,
        "source_pack_snapshot_id": snapshot.snapshot_id, "source_pack_snapshot_hash": snapshot.snapshot_hash,
        "source_release_sha": frozen.release_sha, "target_release_sha": application.commit_sha,
        "original_failure": retained["diagnostic"], "current_result_validation": "VALID",
        "result_validation_contract_version": "1.19.0", "provider_invoked": False,
        "literary_qualification": "NOT_RUN", "reason": reason, "operator_id": principal.principal_id}
    content["result_admission_recovery"] = provenance
    definition = result_admission_definition(application_build_id=application.application_build_id, commit_sha=application.commit_sha)
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()

    def materialize(uow, operation_id, checkpoint):
        uow.cursor.execute("SELECT candidate_asset_version_id,version FROM authority_story_planning_generation WHERE operation_id=%s FOR UPDATE", [source_operation_id])
        current = uow.cursor.fetchone()
        if current != (None, row[2]):
            raise KernelError("PLANNING_RESULT_ADMISSION_STALE", "Source generation changed before result admission")
        require_settled_failed_lineage(uow.cursor, source_operation_id=source_operation_id)
        document = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id, project_id=project_id, asset_id=recovery_id, asset_type="planning_generation_candidate",
            schema_version="story-design.authority.v1", logical_ref=f"planning/result_admissions/{source_operation_id}.json",
            category="runs", output_key="story_planning.candidate", role="primary", content=content,
            qualification_policy="planning-result-admission-candidate-only-v1", lifecycle="CANDIDATE", eligibility="INELIGIBLE",
            trace_id=command.trace_id, correlation_id=command.correlation_id, causation_id=source_operation_id))
        uow.cursor.execute("""INSERT INTO authority_planning_result_admission
            (recovery_id,project_id,book_id,source_operation_id,recovery_operation_id,source_result_asset_version_id,
             candidate_asset_version_id,external_effect_id,source_generation_version,evidence)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [recovery_id,project_id,command.book_id,source_operation_id,
                operation_id,retained["asset_version_id"],document.asset_version_id,effect_id,row[2],Jsonb(provenance)])
        uow.cursor.execute("""INSERT INTO authority_story_planning_candidate
            (candidate_id,generation_id,project_id,book_id,candidate_asset_version_id,content_hash,attempt_id,repair_of_candidate_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,''))""", ["planning-candidate:"+document.asset_version_id,
                "planning-generation:"+source_operation_id,project_id,command.book_id,document.asset_version_id,
                document.content_hash,evidence["attempt_id"],command.repair_of_candidate_id])
        uow.cursor.execute("""UPDATE authority_story_planning_generation SET candidate_asset_version_id=%s,
            status='CANDIDATE_MATERIALIZED',version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s""",
            [document.asset_version_id,source_operation_id,row[2]])
        uow.repositories.operation_graph.record_event(dict(event_id=str(uuid4()),audit_id=str(uuid4()),outbox_id=str(uuid4()),
            aggregate_type="planning_result_admission",aggregate_id=recovery_id,operation_id=operation_id,project_id=project_id,
            event_type=NAME,correlation_id=command.correlation_id,causation_id=source_operation_id,
            payload={"operation_id":operation_id,"trace_id":command.trace_id,"source_operation_id":source_operation_id,
                "candidate_asset_version_id":document.asset_version_id,"provider_invoked":False}))
        return {"recovery_id":recovery_id,"asset_version_id":document.asset_version_id,"content_hash":document.content_hash,
            "source_operation_id":source_operation_id,"provider_invoked":False}

    return execute_transaction_command(application.database_url,dict(definition_name=NAME,definition_version="1.0.0",
        project_id=project_id,workspace_id=command.workspace_id,book_id=command.book_id,actor_id=principal.principal_id,
        idempotency_scope="book:planning-result-admission",idempotency_key=recovery_id,trace_id=command.trace_id,span_id=str(uuid4()),
        correlation_id=command.correlation_id,causation_id=source_operation_id,causation_operation_id=source_operation_id,
        input=provenance,input_assets=[{"asset_version_id":retained["asset_version_id"],"content_hash":retained["content_hash"]},
            {"asset_version_id":retained["context_asset_version_id"],"content_hash":retained["context_hash"]},
            *[{"asset_version_id":item.asset_version_id,"content_hash":item.content_hash} for item in inputs]]),
        context=AdmissionContext(principal.principal_id,frozenset({"story_planning.authority.execute"}),frozenset({HANDLER}),
            application.application_build_id,application.commit_sha),handler=materialize)


def require_settled_failed_lineage(cursor, *, source_operation_id):
    cursor.execute("""WITH RECURSIVE lineage AS (
        SELECT operation_id FROM authority_story_planning_generation WHERE operation_id=%s
        UNION ALL SELECT g.operation_id FROM authority_story_planning_generation g JOIN lineage l ON g.repair_of_operation_id=l.operation_id)
        SELECT EXISTS(SELECT 1 FROM lineage JOIN authority_operation o USING(operation_id)
            WHERE o.status<>'FAILED_FINAL') OR EXISTS(SELECT 1 FROM lineage JOIN authority_external_effect e USING(operation_id)
            WHERE e.status<>'SUCCEEDED') OR EXISTS(SELECT 1 FROM lineage JOIN authority_budget_reservation b USING(operation_id)
            WHERE b.status<>'SETTLED') OR EXISTS(SELECT 1 FROM lineage JOIN authority_attempt a USING(operation_id)
            JOIN authority_lease_acquisition l USING(attempt_id) WHERE l.status='HELD')""", [source_operation_id])
    if cursor.fetchone()[0]:
        raise KernelError("PLANNING_RESULT_ADMISSION_RECONCILIATION_REQUIRED", "Live or unresolved source/successor cannot be superseded by retained result admission")


def result_admission_definition(*, application_build_id: str, commit_sha: str):
    from .application import story_planning_generation_definition

    definition = story_planning_generation_definition(application_build_id=application_build_id,commit_sha=commit_sha)
    definition.update(name=NAME,definition_version="1.0.0",command_schema_version="planning-result-admission.command.v1",
        result_schema_version="planning-result-admission.result.v1",command_schema={"type":"object"},input_contract={"type":"object"},
        handler_key=HANDLER,handler_contract_version="planning-result-admission.v1",execution_mode="transactional",
        policy={"execution_classification":"transaction_command","trusted_operator_required":True,"provider_dispatch_allowed":False},
        idempotency_scope="book:planning-result-admission",concurrency_key_template="book:{book_id}:planning-result-admission",
        external_capabilities=[],retry_policy={"max_attempts":1},timeout_policy={"operation_timeout_seconds":30},
        cancellation_policy={"mode":"not_applicable_atomic"},irreversible_effect_policy={"allowed":False},
        completion_contract={"version":"planning-result-admission-completion.v1","required_asset_selectors":[{
            "selector":"planning_generation_candidate","output_key":"story_planning.candidate","role":"primary",
            "lifecycle":"CANDIDATE","eligibility":"INELIGIBLE","governance":"CLEAR"}],
            "required_evidence":["trace","audit"],"required_outbox_events":[NAME]})
    return definition
