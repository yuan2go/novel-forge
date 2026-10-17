from __future__ import annotations

from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_handler_runtime.contracts import (
    AuthorityHandlerRequest,
    AuthorityInputAsset,
)
from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    read_rejected_structured_completion, read_failed_operation_success, read_retained_generation_stage_success,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    execute_transaction_command,
)
from novel_forge.modules.production_execution.execution_template import (
    verify_template_provenance,
)
from novel_forge.modules.production_execution.rejected_output import read_retained_rejected_output
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .binder import PlanningCapabilityBinding, _identity
from .foundation_generation import FOUNDATION_GENERATORS
from .domain import (
    FrozenPlanningInput,
    PlanningExecutionEvidence,
    PlanningGenerationCandidate,
    canonical_hash,
)

NAME = "story_planning.gateway_result.revalidate"
HANDLER = "novel_forge." + NAME
VERSION = "planning-gateway-result-revalidation.v1"
RETRYABLE_RELEASE_VERSION = "planning-gateway-result-revalidation.v2"
RELEASE_FAILURE_MESSAGE = "CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT: runtime contract differs from Pack execution snapshot: release_sha"


def retryable_release_failure(status, attempt):
    return (status == "FAILED_RETRYABLE" and attempt is not None and attempt[2] == "FAILED_RETRYABLE"
        and isinstance(attempt[3], dict)
        and attempt[3].get("error_code") == "CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT"
        and attempt[3].get("error_message") == RELEASE_FAILURE_MESSAGE)


def literal_null_paths(schema, value, path="$"):
    paths = [path] if schema.get("type") == "null" and value is None else []
    for branch in schema.get("anyOf", []):
        paths.extend(literal_null_paths(branch, value, path))
    if isinstance(value, dict):
        for key, child in schema.get("properties", {}).items():
            if key in value:
                paths.extend(literal_null_paths(child, value[key], path + "." + key))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            paths.extend(literal_null_paths(schema["items"], item, f"{path}[{index}]"))
    return sorted(set(paths))


def retained_output(query, *, project_id, provider, request):
    production = provider["production_execution"]
    result = production["execution_result"]

    def read(reference, kind):
        if not reference.startswith("authority-asset-version:"):
            raise KernelError(
                "PLANNING_GATEWAY_RESULT_EVIDENCE_INVALID",
                "Require original Authority-backed process evidence",
            )
        document = query.require(
            project_id=project_id, asset_version_id=reference.split(":", 1)[1]
        )
        content = document.content
        payload = content.get("payload")
        if (
            document.asset_type != "execution_evidence"
            or content.get("kind") != kind
            or content.get("execution_id") != request["execution_id"]
            or not isinstance(payload, dict)
            or content.get("payload_hash")
            != canonical_hash(payload).removeprefix("sha256:")
        ):
            raise KernelError(
                "PLANNING_GATEWAY_RESULT_EVIDENCE_INVALID",
                "Retain exact process and rejected-output payload digests",
            )
        return document, payload

    process_doc, process = read(result["process_receipt_ref"], "process-receipt")
    raw_doc, metadata = read(result["raw_output_ref"], "rejected-output")
    if (
        process.get("status") != "SUCCEEDED"
        or process.get("returncode") != 0
        or process.get("result_integrity") != "VALID"
        or process.get("operation_id") != request["operation_id"]
        or process.get("attempt_id") != request["attempt_id"]
        or process.get("fencing_token") != request["fencing_token"]
        or not process.get("authority_bound")
        or metadata.get("validation") != "REJECTED"
        or metadata.get("generation_allowed") is not False
        or metadata.get("result_path") != process.get("result_path")
        or metadata.get("input_sha256") != process.get("input_sha256")
        or process.get("input_sha256")
        != provider["capability_runtime"]["provider_view"]["component_hashes"][
            "fully_rendered_prompt"
        ].removeprefix("sha256:")
    ):
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_PROCESS_INVALID",
            "Only an intact successful frozen process can be locally revalidated",
        )
    proof = read_retained_rejected_output(request=request, process=process, metadata=metadata)
    raw = proof.result()
    schema = production["process_evidence"]["output_schema"]
    if canonical_hash(schema) != provider["capability_runtime"]["output_schema_hash"]:
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_SCHEMA_DRIFT",
            "Revalidate only the exact original full Schema",
        )
    paths = literal_null_paths(schema, raw)
    if not paths:
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_FAILURE_NOT_ALLOWED",
            "This recovery corrects only the known literal-null engine rejection",
        )
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        validate_chapter_provider_output_against_schema, validate_native_world_schema_fragment,
    )
    stage = production["process_evidence"]["stage"]
    if stage in {"world_candidates.generate", "world_candidates.evaluate"} and "$schema" not in schema:
        normalized = validate_native_world_schema_fragment(stage, schema, raw, output_schema_ref=production["process_evidence"]["output_schema_version"])
    else:
        normalized = validate_chapter_provider_output_against_schema(stage, schema, raw)
    if normalized != raw:
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_NORMALIZATION_FORBIDDEN",
            "Local recovery must preserve the complete Provider result",
        )
    return raw, paths, process_doc, raw_doc


def recover(application, *, command, operation_id, principal, execution_probe=None):
    application._probe(execution_probe)
    principal.require("story_planning.authority.execute", command.project_id)
    if command.generator_operation_name not in {
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }:
        return None
    if (
        principal.principal_id != command.actor_id
        and principal.principal_type is not PrincipalType.LOCAL_OPERATOR
    ):
        raise PermissionError(
            "Recovery requires the actual source actor or a scoped trusted operator"
        )
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute(
            "SELECT o.status,o.command_payload->'payload',g.input_snapshot,g.version,g.candidate_asset_version_id,o.version FROM authority_operation o JOIN authority_story_planning_generation g USING(operation_id) WHERE o.operation_id=%s AND o.project_id=%s",
            [operation_id, command.project_id],
        )
        source = uow.cursor.fetchone()
        from .application import _command_payload
        uow.cursor.execute("SELECT attempt_id,attempt_number,status,result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [operation_id])
        failed_attempt = uow.cursor.fetchone()
        retryable_release = source is not None and retryable_release_failure(source[0], failed_attempt)

        if (
            not source
            or (source[0] not in {"FAILED_FINAL", "DEAD_LETTER"} and not retryable_release)
            or source[4]
            or source[1] != _command_payload(command)
        ):
            return None
        uow.cursor.execute(
            "SELECT e.external_effect_id,e.request_payload,e.last_error,e.status FROM authority_external_effect e WHERE e.operation_id=%s AND e.status IN ('FAILED_FINAL','SUCCEEDED') AND e.request_payload->>'stage'=%s",
            [operation_id, command.generator_operation_name],
        )
        effects = uow.cursor.fetchall()
        if (
            len(effects) != 1
            or (effects[0][3] != "SUCCEEDED" and effects[0][2]
            .get("production_execution", {})
            .get("process_evidence", {})
            .get("failure_code")
            != "OUTPUT_SCHEMA_FAILURE")
        ):
            return None
        effect_id, payload, _, effect_status = effects[0]
        completed_local = effect_status == "SUCCEEDED"
        if retryable_release and (not completed_local or command.execution_contract_version != "1.21.0"):
            return None
        runtime = payload["_production_execution"]["capability_runtime"]
        template = verify_template_provenance(uow.cursor, runtime["routing_decision"])
        if (
            not template
            or template["mode"] != "CREATIVE_VALIDATION"
            or template["require_literary_qualification"]
        ):
            return None
        uow.cursor.execute(
            "SELECT v.asset_version_id,v.content_hash FROM authority_operation_output_asset output JOIN authority_asset a USING(asset_id) JOIN authority_asset_version v USING(asset_version_id) WHERE output.operation_id=%s AND a.asset_type='model_call_log' AND v.content->>'stage'=%s",
            [operation_id, command.generator_operation_name],
        )
        logs = uow.cursor.fetchall()
        if not completed_local and len(logs) != 1:
            raise KernelError(
                "PLANNING_GATEWAY_RESULT_SOURCE_INVALID",
                "Require the one original native model-call record",
            )
    read_result = read_retained_generation_stage_success if retryable_release else read_failed_operation_success if completed_local else read_rejected_structured_completion
    retained = read_result(
        application.database_url,
        EffectCommandContext(
            operation_id=operation_id,
            project_id=command.project_id,
            actor_id=command.actor_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        ),
        effect_id=effect_id,
    )
    provider = retained["provider_evidence"]
    production = provider["production_execution"]
    request = production["execution_request"]
    if (
        request["external_effect_id"] != effect_id
        or request["operation_id"] != operation_id
        or request["project_id"] != command.project_id
        or request["book_id"] != command.book_id
        or request["stage"] != command.generator_operation_name
        or any(
            runtime[key] != provider["capability_runtime"][key]
            for key in (
                "materialization_hash",
                "provider_request_envelope_hash",
                "provider_admission_asset_version_id",
            )
        )
    ):
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_SCOPE_DRIFT",
            "Retain the exact dispatched scope and runtime",
        )
    query = AuthorityAssetQuery(application.database_url)
    if completed_local:
        result = production["execution_result"]
        if result["outcome"] != "SUCCEEDED" or not result["normalized_output_ref"].startswith("authority-asset-version:"):
            raise KernelError("PLANNING_GATEWAY_RESULT_EVIDENCE_INVALID", "Require verified normalized original output")
        raw_doc = query.require(project_id=command.project_id, asset_version_id=result["normalized_output_ref"].split(":",1)[1])
        process_doc = query.require(project_id=command.project_id, asset_version_id=result["process_receipt_ref"].split(":",1)[1])
        normalized = raw_doc.content
        raw = provider["result"]
        if (raw_doc.asset_type != "execution_evidence" or normalized.get("kind") != "normalized-output"
                or normalized.get("execution_id") != request["execution_id"] or normalized.get("payload") != raw
                or normalized.get("payload_hash") != canonical_hash(raw).removeprefix("sha256:")):
            raise KernelError("PLANNING_GATEWAY_RESULT_EVIDENCE_DRIFT", "Retain the verified original normalized output and digest")
        null_paths = []
        logs = [(raw_doc.asset_version_id, raw_doc.content_hash)]
        with AuthorityUnitOfWork(application.database_url) as uow:
            uow.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [operation_id])
            original_failure = uow.cursor.fetchone()[0]
    else:
        model_log = query.require(project_id=command.project_id, asset_version_id=logs[0][0])
        if model_log.content_hash != logs[0][1] or any(model_log.content.get(key) != value for key, value in provider.items()):
            raise KernelError("PLANNING_GATEWAY_RESULT_EVIDENCE_DRIFT", "Retain the immutable owned model-call evidence for the failed dispatch")
        raw, null_paths, process_doc, raw_doc = retained_output(query, project_id=command.project_id, provider=provider, request=request)
        original_failure = "OUTPUT_SCHEMA_FAILURE"
    snapshot = CapabilityPackRuntimeResolver(
        application.database_url
    ).require_attempt_snapshot(
        attempt_id=request["attempt_id"],
        snapshot_id=runtime["snapshot_id"],
        snapshot_hash=runtime["snapshot_hash"],
    )
    if (
        snapshot.operation_id != operation_id
        or snapshot.execution_fencing_token != request["fencing_token"]
    ):
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_SNAPSHOT_DRIFT",
            "Retain the exact original fenced Pack snapshot",
        )
    frozen = snapshot.execution_snapshot
    if retryable_release and frozen.release_sha == application.commit_sha:
        raise KernelError("PLANNING_GATEWAY_RESULT_RELEASE_DRIFT_INVALID", "Release recovery requires distinct original and current implementation identities")
    context_ref = production["input_manifest"]["context_bundle_version"]
    context = query.require(project_id=command.project_id, asset_version_id=context_ref)
    artifact = next(
        a
        for a in production["input_manifest"]["input_artifacts"]
        if a["asset_version_id"] == context_ref
    )
    if context.content_hash != artifact["content_hash"]:
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_CONTEXT_DRIFT",
            "Retain the exact dispatched Context",
        )
    try:
        candidate_result = raw
        if command.execution_contract_version == "1.21.0" and command.generator_operation_name not in FOUNDATION_GENERATORS:
            from .execution import bind_provider_realization_selectors
            candidate_result = bind_provider_realization_selectors(raw, context.content.get("realization_reference_contract") or {})
        from .result_recovery import validate_raw_result

        validate_raw_result(
            command.generator_operation_name,
            candidate_result,
            generated_title=context.content.get("generated_title_contract") == "generated-book-title.v1",
            work_requirements=command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
            aligned_methods=command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"},
            rfc6901_paths=command.execution_contract_version in {"1.19.0", "1.21.0"},
            narrative_search=bool(command.narrative_search_id) and command.execution_contract_version == "1.21.0",
        )
    except KernelError:
        return None
    inputs = tuple(FrozenPlanningInput(**i) for i in source[2])
    documents = [
        query.require(
            project_id=command.project_id, asset_version_id=i.asset_version_id
        )
        for i in inputs
    ]
    if any(
        d.content_hash != i.content_hash or d.asset_type != i.asset_type
        for i, d in zip(inputs, documents, strict=True)
    ):
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_INPUT_DRIFT",
            "Retain every original input and role",
        )
    selection_hash = context.content["narrative_intelligence"]["selection_digest"]
    binding = PlanningCapabilityBinding(
        binding_id=_identity("planning-capability-binding", request["attempt_id"]),
        operation_id=operation_id,
        attempt_id=request["attempt_id"],
        fencing_token=request["fencing_token"],
        project_id=command.project_id,
        workspace_id=command.workspace_id,
        book_id=command.book_id,
        capability_ref=frozen.capability_ref,
        capability_hash=frozen.capability_hash,
        execution_capability_id=frozen.execution_capability_id,
        execution_capability_hash=frozen.execution_capability_hash,
        input_manifest_ref=request["input_manifest_ref"],
        context_bundle_asset_version_id=context_ref,
        context_bundle_hash=context.content_hash,
        narrative_intelligence_selection_digest=selection_hash,
        commit_authority=frozen.commit_authority,
        capability_pack_attempt_snapshot_id=snapshot.snapshot_id,
        capability_pack_attempt_snapshot_hash=snapshot.snapshot_hash,
    )
    recovery_id = "planning-gateway-revalidation:" + operation_id
    contract_version = RETRYABLE_RELEASE_VERSION if retryable_release else VERSION
    release_proof = ({"source_operation_version": source[5], "source_attempt_id": failed_attempt[0],
        "source_attempt_number": failed_attempt[1], "source_failure_result": dict(failed_attempt[3])} if retryable_release else None)
    provenance = {
        "contract_version": contract_version,
        **({"retryable_release_recovery": release_proof} if retryable_release else {}),
        "source_operation_id": operation_id,
        "external_effect_id": effect_id,
        "recovery_id": recovery_id,
        "source_result_asset_version_id": logs[0][0],
        "source_result_hash": canonical_hash(raw),
        "source_release_sha": frozen.release_sha,
        "target_release_sha": application.commit_sha,
        "operator_id": principal.principal_id,
        "source_pack_snapshot_id": snapshot.snapshot_id,
        "source_pack_snapshot_hash": snapshot.snapshot_hash,
        "source_context_asset_version_id": context_ref,
        "source_context_hash": context.content_hash,
        "original_failure": original_failure,
        "original_gateway_outcome": "SUCCEEDED" if completed_local else "FINAL_FAILURE",
        **({"completed_result_source": "VERIFIED_PROVIDER_COMPLETION"} if completed_local else {}),
        "current_result_validation": "VALID",
        "legacy_literal_null_paths": null_paths,
        "raw_output_receipt": {
            "asset_version_id": raw_doc.asset_version_id,
            "content_hash": raw_doc.content_hash,
        },
        "process_receipt": {
            "asset_version_id": process_doc.asset_version_id,
            "content_hash": process_doc.content_hash,
        },
        "provider_invoked": False,
        "literary_qualification": "NOT_RUN",
        "reason": "Reuse the verified completed original output after bounded execution failure" if completed_local else "Correct known literal-null Schema engine rejection without resending the completed process",
    }
    definition = gateway_result_revalidation_definition(application_build_id=application.application_build_id, commit_sha=application.commit_sha, contract_version=contract_version)
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()

    def materialize(uow, registration_id, checkpoint):
        from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
        if retryable_release:
            uow.cursor.execute("SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s ORDER BY formation_run_id FOR UPDATE", [command.project_id, command.book_id])
            if not uow.cursor.fetchall():
                raise KernelError("PLANNING_GATEWAY_RESULT_CREATION_OWNER_REQUIRED", "Release-result recovery requires the original Creation cancellation boundary")
        require_known_cli_lineage(uow.cursor, project_id=command.project_id, operation_id=operation_id)
        uow.cursor.execute(
            "SELECT status,version FROM authority_operation WHERE operation_id=%s FOR UPDATE",
            [operation_id],
        )
        owner = uow.cursor.fetchone()
        if owner[0] != source[0] or (retryable_release and owner[1] != source[5]):
            raise KernelError(
                "PLANNING_GATEWAY_RESULT_OWNER_DRIFT",
                "Retain the stopped original owner and its release recovery version",
            )
        if retryable_release:
            uow.cursor.execute("SELECT attempt_id,attempt_number,status,result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [operation_id])
            if uow.cursor.fetchone() != failed_attempt:
                raise KernelError("PLANNING_GATEWAY_RESULT_OWNER_DRIFT", "Original latest failed Attempt changed before result admission")
            uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation
                JOIN authority_story_formation_run formation USING(formation_run_id) WHERE formation.project_id=%s AND formation.book_id=%s)
                OR EXISTS(SELECT 1 FROM authority_generation_isolation WHERE operation_id=%s)
                OR EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation WHERE source_operation_id=%s)
                OR EXISTS(SELECT 1 FROM authority_story_planning_generation WHERE repair_of_operation_id=%s)
                OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s)""",
                [command.project_id, command.book_id, operation_id, operation_id, operation_id, operation_id])
            if uow.cursor.fetchone()[0]:
                raise KernelError("PLANNING_GATEWAY_RESULT_SUCCESSION_CONFLICT", "Cancellation, isolation or a registered successor prevents release-result adoption")
        uow.cursor.execute(
            "SELECT candidate_asset_version_id,version FROM authority_story_planning_generation WHERE operation_id=%s FOR UPDATE",
            [operation_id],
        )
        if uow.cursor.fetchone() != (None, source[3]):
            raise KernelError(
                "PLANNING_GATEWAY_RESULT_STALE",
                "Source generation changed before atomic result admission",
            )
        uow.cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND status NOT IN ('SUCCEEDED','FAILED_FINAL')) OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s AND status<>'SETTLED') OR EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND l.status='HELD')",
            [operation_id] * 3,
        )
        if uow.cursor.fetchone()[0]:
            raise KernelError(
                "PLANNING_GATEWAY_RESULT_RECONCILIATION_REQUIRED",
                "No unresolved source call or usage may enter recovery",
            )
        validation = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=registration_id,
                project_id=command.project_id,
                asset_id=recovery_id + ":validation",
                asset_type="planning_gateway_result_revalidation",
                schema_version=contract_version,
                logical_ref=f"planning/gateway_revalidation/{operation_id}/validation",
                category="runs",
                output_key="story_planning.gateway_revalidation",
                role="local_validation",
                content={"evidence": provenance, "raw_result": raw, "locally_bound_result": candidate_result},
                qualification_policy="planning-local-schema-validation-not-certified-v1",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
        )
        reference = "authority-asset-version:" + validation.asset_version_id
        pep = PlanningExecutionEvidence(
            operation_id=operation_id,
            attempt_id=request["attempt_id"],
            fencing_token=request["fencing_token"],
            route_snapshot_id=request["route_snapshot_id"],
            input_manifest_ref=request["input_manifest_ref"],
            output_manifest_ref=reference,
            validation_manifest_ref=reference,
            usage_receipt_ref=production["execution_result"]["usage_receipt_ref"],
            cost_receipt_ref=production["execution_result"]["cost_receipt_ref"],
            external_receipt_ref=effect_id,
            capability_pack_attempt_snapshot_id=snapshot.snapshot_id,
            capability_pack_attempt_snapshot_hash=snapshot.snapshot_hash,
            capability_execution_ref=binding.binding_id,
            capability_execution_hash=binding.binding_hash,
            capability_runtime_binding_ref=snapshot.snapshot_id,
            capability_runtime_binding_hash=snapshot.snapshot_hash,
            commit_authority=frozen.commit_authority,
            fixture_protocol_only=bool(provider.get("fixture_protocol_only", False)),
            real_provider_proven=bool(
                provider["real_model_call"] and not provider.get("fixture_protocol_only", False)
            ),
            context_bundle_asset_version_id=context_ref,
            context_bundle_hash=context.content_hash,
            narrative_intelligence_selection_digest=selection_hash,
        )
        candidate = PlanningGenerationCandidate(
            command.generator_operation_name,
            command.planning_scope,
            command.logical_key,
            candidate_result,
            inputs,
            pep,
            raw,
        )

        class RetainedBinder:
            def execute(self, **kwargs):
                if (
                    kwargs["operation_id"] != operation_id
                    or kwargs["attempt_id"] != request["attempt_id"]
                    or kwargs["fencing_token"] != request["fencing_token"]
                    or kwargs["command"] != command
                ):
                    raise KernelError(
                        "PLANNING_GATEWAY_RESULT_BINDING_DRIFT",
                        "Local validation requires its exact original request",
                    )
                return candidate

        from .application import _PlanningGenerationHandler

        handler_request = AuthorityHandlerRequest(
            operation_id=operation_id,
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            actor_id=command.actor_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            definition_name="story_planning.generate",
            definition_version=command.execution_contract_version,
            command={"payload": source[1]},
            inputs=tuple(
                AuthorityInputAsset(
                    d.asset_version_id, d.asset_type, d.content_hash, d.content
                )
                for d in documents
            ),
            attempt_id=request["attempt_id"],
            fencing_token=request["fencing_token"],
            worker_id="native-local-result-revalidation",
        )
        output = _PlanningGenerationHandler(
            RetainedBinder(), application.database_url
        )._execute(handler_request)
        content = {**output.content, "result_admission_recovery": provenance}
        document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=registration_id,
                project_id=command.project_id,
                asset_id=recovery_id,
                asset_type=output.asset_type,
                schema_version="story-design.authority.v1",
                logical_ref=f"planning/gateway_revalidation/{operation_id}/candidate",
                category="runs",
                output_key=output.output_key,
                role=output.role,
                content=content,
                qualification_policy="planning-revalidated-candidate-only-v1",
                lifecycle="CANDIDATE",
                eligibility="INELIGIBLE",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                causation_id=operation_id,
            )
        )
        uow.cursor.execute(
            "INSERT INTO authority_planning_result_admission(recovery_id,project_id,book_id,source_operation_id,recovery_operation_id,source_result_asset_version_id,candidate_asset_version_id,external_effect_id,source_generation_version,evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                recovery_id,
                command.project_id,
                command.book_id,
                operation_id,
                registration_id,
                logs[0][0],
                document.asset_version_id,
                effect_id,
                source[3],
                Jsonb(provenance),
            ],
        )
        uow.cursor.execute(
            "INSERT INTO authority_story_planning_candidate(candidate_id,generation_id,project_id,book_id,candidate_asset_version_id,content_hash,attempt_id,repair_of_candidate_id) VALUES (%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,''))",
            [
                "planning-candidate:" + document.asset_version_id,
                "planning-generation:" + operation_id,
                command.project_id,
                command.book_id,
                document.asset_version_id,
                document.content_hash,
                request["attempt_id"],
                command.repair_of_candidate_id,
            ],
        )
        uow.cursor.execute(
            "UPDATE authority_story_planning_generation SET candidate_asset_version_id=%s,status='CANDIDATE_MATERIALIZED',version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s",
            [document.asset_version_id, operation_id, source[3]],
        )
        uow.repositories.operation_graph.record_event(
            dict(
                event_id=str(uuid4()),
                audit_id=str(uuid4()),
                outbox_id=str(uuid4()),
                aggregate_type="planning_result_admission",
                aggregate_id=recovery_id,
                operation_id=registration_id,
                project_id=command.project_id,
                event_type=NAME,
                correlation_id=command.correlation_id,
                causation_id=operation_id,
                payload={
                    "operation_id": registration_id,
                    "trace_id": command.trace_id,
                    "candidate_asset_version_id": document.asset_version_id,
                    "provider_invoked": False,
                },
            )
        )
        return {
            "recovery_id": recovery_id,
            "asset_version_id": document.asset_version_id,
            "content_hash": document.content_hash,
            "provider_invoked": False,
        }

    application._probe(execution_probe)
    return execute_transaction_command(
        application.database_url,
        dict(
            definition_name=NAME,
            definition_version=definition["definition_version"],
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            actor_id=principal.principal_id,
            idempotency_scope="book:planning-gateway-revalidation",
            idempotency_key=recovery_id,
            trace_id=command.trace_id,
            span_id=str(uuid4()),
            correlation_id=command.correlation_id,
            causation_id=operation_id,
            causation_operation_id=operation_id,
            input=provenance,
            input_assets=[
                {"asset_version_id": i.asset_version_id, "content_hash": i.content_hash}
                for i in [*documents, process_doc, raw_doc]
            ],
        ),
        context=AdmissionContext(
            principal.principal_id,
            frozenset({"story_planning.authority.execute"}),
            frozenset({HANDLER}),
            application.application_build_id,
            application.commit_sha,
        ),
        handler=materialize,
    )


def gateway_result_revalidation_definition(*, application_build_id: str, commit_sha: str, contract_version: str = VERSION):
    from .result_admission import result_admission_definition

    definition = result_admission_definition(application_build_id=application_build_id, commit_sha=commit_sha)
    definition.update(
        name=NAME,
        handler_key=HANDLER,
        handler_contract_version=contract_version,
        policy={
            "execution_classification": "transaction_command",
            "source_actor_or_scoped_operator_required": True,
            "provider_dispatch_allowed": False,
        },
        idempotency_scope="book:planning-gateway-revalidation",
        concurrency_key_template="book:{book_id}:planning-gateway-revalidation",
        completion_contract={
            **definition["completion_contract"],
            "required_outbox_events": [NAME],
        },
    )
    if contract_version == RETRYABLE_RELEASE_VERSION:
        definition["definition_version"] = "1.1.0"
    elif contract_version != VERSION:
        raise ValueError("Unsupported saved Planning recovery contract")
    return definition


def recover_completed_planning_outputs(application, *, project_id, book_id, principal):
    from .application import _command_from_payload
    principal.require("story_planning.authority.execute", project_id)
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute("""SELECT operation.operation_id,operation.command_payload->'payload'
            FROM authority_operation operation JOIN authority_story_planning_generation generation USING(operation_id)
            WHERE operation.project_id=%s AND generation.book_id=%s
              AND (operation.status IN ('FAILED_FINAL','DEAD_LETTER') OR (
                operation.status='FAILED_RETRYABLE' AND EXISTS(SELECT 1 FROM authority_attempt attempt
                  WHERE attempt.operation_id=operation.operation_id AND attempt.status='FAILED_RETRYABLE'
                    AND attempt.attempt_number=(SELECT max(latest.attempt_number) FROM authority_attempt latest WHERE latest.operation_id=operation.operation_id)
                    AND attempt.result->>'error_code'='CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT'
                    AND attempt.result->>'error_message'='CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT: runtime contract differs from Pack execution snapshot: release_sha')))
              AND generation.candidate_asset_version_id IS NULL
              AND EXISTS(SELECT 1 FROM authority_external_effect effect
                JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
                JOIN authority_external_receipt receipt USING(dispatch_id)
                WHERE effect.operation_id=operation.operation_id AND effect.status='SUCCEEDED'
                  AND effect.request_payload->>'stage'=generation.generator_operation_name
                  AND dispatch.status='SUCCEEDED' AND receipt.status='VERIFIED'
                  AND NOT EXISTS(SELECT 1 FROM authority_generation_isolation isolation WHERE isolation.operation_id=operation.operation_id))
              AND NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation link WHERE link.source_operation_id=operation.operation_id)
              AND NOT EXISTS(SELECT 1 FROM authority_story_planning_generation child WHERE child.repair_of_operation_id=operation.operation_id)
              AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation
                JOIN authority_story_formation_run formation USING(formation_run_id)
                WHERE formation.project_id=generation.project_id AND formation.book_id=generation.book_id)""",[project_id,book_id])
        rows=uow.cursor.fetchall()
    recovered = False
    for operation_id,payload in rows:
        result = recover(application, command=_command_from_payload(payload),operation_id=operation_id,principal=principal)
        recovered = result is not None or recovered
    return recovered
