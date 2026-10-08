from __future__ import annotations

from dataclasses import replace
from uuid import uuid4
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.source_authority.corpus import corpus_hash
from novel_forge.modules.source_authority.curation import require_curated_operation_current
from novel_forge.modules.source_authority.deconstruction import (
    AnalyzerContract,
    ObservationScope,
    ObservationEvidenceSpan,
)
from novel_forge.modules.source_authority.deconstruction_application import (
    CommitDeconstructionObservationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_import_repositories import SourceImportRepository
from .curated_analysis import curated_provider_gate
from .narrative_contracts import reconcile_review


def narrative_strategy(strategy: Any) -> Any:
    from .narrative_contracts import MECHANISM_OBSERVATION_SCHEMA

    professional = strategy.content_type.value in {
        "PROFESSIONAL_KNOWLEDGE",
        "WRITING_THEORY",
        "HISTORY_SOCIAL_SCIENCE",
        "PHILOSOPHY_ESSAY",
        "PLATFORM_RULES",
    }
    analyzer = replace(
        strategy.analyzers[0],
        analyzer_id="bounded-narrative." + strategy.analyzers[0].dimension,
        analyzer_version="2.0.0",
        schema_version=MECHANISM_OBSERVATION_SCHEMA
        if professional
        else "source-narrative-observation.v1",
        prompt_id="source.bounded-mechanism"
        if professional
        else "source.bounded-narrative",
        prompt_version="2.0.0",
        recommended_scales=("CHAPTER", "CHAPTER_WINDOW"),
    )
    return replace(
        strategy,
        analyzers=(analyzer,),
        profile_id="bounded-narrative." + strategy.profile_id,
        profile_version="2.0.0",
    )


def admit_observation_abstraction(app, *, project_id, import_job_id, observation_id, principal):
    principal.require("source.authority.execute", project_id)
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        repository = SourceImportRepository(uow.cursor)
        job = repository.job(project_id=project_id, import_job_id=import_job_id)
        if job["status"] in {"PAUSED", "CANCELLED", "FAILED_FINAL"}:
            raise KernelError("SOURCE_ABSTRACTION_JOB_BLOCKED", "The original job does not permit abstraction")
        uow.cursor.execute(
            """SELECT work.operation_id,operation.command_payload->'payload',version.content
            FROM authority_source_import_work work JOIN authority_operation operation USING(operation_id,project_id)
            JOIN authority_asset_version version ON version.asset_version_id=%s
            JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=work.project_id
            WHERE work.project_id=%s AND work.import_job_id=%s
              AND work.work_kind='DECONSTRUCTION' AND work.status IN ('SUCCEEDED','REUSED')
              AND operation.status='SUCCEEDED' AND asset.asset_type='source_deconstruction_observation'
              AND version.lifecycle='ACTIVE' AND version.governance='CLEAR'
              AND work.result->>'observation_asset_version_id'=version.asset_version_id
              AND work.result#>>'{review,decision}'='ACCEPT_IN_SCOPE'
              AND work.result->>'semantic_evidence'='AGENT_REVIEW_ONLY'
            ORDER BY work.created_at,work.operation_id LIMIT 2 FOR SHARE OF work,operation,version
            """, [observation_id, project_id, import_job_id],
        )
        rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError("SOURCE_APPROVED_OBSERVATION_REQUIRED", "Select one exact active Observation from a completed in-scope Review in this job")
        parent, payload, observation = rows[0]
        if not payload.get("narrative_reading") or not observation["observation"]["findings"]:
            raise KernelError("SOURCE_ABSTRACTION_FINDINGS_REQUIRED", "Only reviewed bounded-reading findings can enter selective abstraction")
        require_curated_operation_current(SourceAuthorityRepository(uow.cursor), project_id, parent)
        child = app._admit_mkaos_from_scope(project_id=project_id,
            parent_operation_id=parent, trace_id=f"trace:selective-abstraction:{observation_id}",
            correlation_id=import_job_id, job=job,
            observation={"observation_asset_version_id": observation_id}, payload=payload)
        uow.commit()
    return {"operation_id": child, "observation_asset_version_id": observation_id,
            "import_job_id": import_job_id, "scope": observation["scope"],
            "whole_job_complete": False, "knowledge_approved": False, "model_calls": 0}


def initial_reading_payload(parent, job, plan, scope, strategy, plan_version):
    return {
        "import_job_id": job["import_job_id"],
        "reading_parent_operation_id": parent,
        "source_document_id": scope.source_document_id,
        "source_transform_id": scope.source_transform_id,
        "analysis_plan_asset_version_id": plan_version,
        "mkaos_capability": strategy.mkaos_capability,
        "abstraction_policy_version": strategy.abstraction_policy_version,
        "narrative_reading": plan,
        "analyzer": strategy.analyzers[0].to_dict(),
        "phase": "OBSERVE",
        "unit_index": 0,
        "repair_round": 0,
        "accepted_observations": [],
        "prior_issues": [],
        "previous_candidate": None,
    }


def begin_reading(app, worker, job, plan, scope, strategy, plan_version):
    payload = initial_reading_payload(
        worker.causation_id, job, plan, scope, strategy, plan_version
    )
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        require_current_fence(uow, worker)
        curated_provider_gate(app.database_url, worker)
        child = _queue(app, uow, worker, job, payload)
        uow.commit()
        return child


def _queue(app, uow, worker, job, payload):
    return _queue_from_scope(app, uow, project_id=worker.project_id,
        causation_id=worker.causation_id, trace_id=worker.trace_id,
        correlation_id=worker.correlation_id, job=job, payload=payload)


def _queue_from_scope(app, uow, *, project_id, causation_id, trace_id, correlation_id, job, payload, causation_operation_id=""):
    from novel_forge.modules.source_import.application import (
        SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
    )

    key = "narrative-reading:" + corpus_hash(
        {"job": job["import_job_id"], "payload": payload}
    )
    child = app._admit_child(
        definition_name=SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
        project_id=project_id,
        workspace_id=job["workspace_id"],
        actor_id=app.worker_id,
        idempotency_key=key,
        trace_id=trace_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        parent_operation_id=payload["reading_parent_operation_id"],
        causation_operation_id=causation_operation_id,
        payload=payload,
        input_assets=(
            {
                "asset_version_id": payload["analysis_plan_asset_version_id"],
                "role": "source_analysis_plan",
            },
        ),
        ready=False,
    )
    SourceImportRepository(uow.cursor).register_work(
        {
            "work_id": str(uuid4()),
            "import_job_id": job["import_job_id"],
            "project_id": project_id,
            "work_kind": "DECONSTRUCTION",
            "stable_key": key,
            "source_path": "reading:" + payload["narrative_reading"]["processing_id"],
            "target_asset_version_id": payload["analysis_plan_asset_version_id"],
            "operation_id": child,
            "status": "PLANNED",
            "result": {},
            "failure": {},
        }
    )
    app._ready_child(
        operation_id=child,
        project_id=project_id,
        actor_id=app.worker_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        reason="frozen bounded Source reading stage ready",
    )
    return child


def _span(value):
    return ObservationEvidenceSpan(
        **{k: v for k, v in value.items() if k != "evidence_span_id"}
    )


def _source_inputs(app, worker, units):
    chunks = {c["asset_version_id"]: c for u in units for c in u["chunks"]}
    with AuthorityUnitOfWork(app.database_url) as uow:
        rows = SourceAuthorityRepository(uow.cursor).catalog_reading_chunk_blobs(
            worker.project_id, list(chunks)
        )
    if len(rows) != len(chunks):
        raise KernelError(
            "READING_SOURCE_MISSING", "frozen chunk or blob is unavailable"
        )
    segments = []
    spans = []
    for row in rows:
        chunk = chunks[row["asset_version_id"]]
        if (
            row["status"] != "AVAILABLE"
            or row["content_hash"] != chunk["content_hash"]
            or row["byte_size"] != chunk["byte_size"]
        ):
            raise KernelError("READING_SOURCE_DRIFT", "frozen chunk identity changed")
        content = app.object_store_reader.read(
            object_key=row["actual_object_key"],
            expected_hash=row["actual_hash"],
            expected_size=row["actual_size"],
        )
        segments.append(
            {
                "source_chunk_asset_version_id": row["asset_version_id"],
                "content": content.decode("utf-8", errors="strict"),
                "content_hash": row["content_hash"],
                "byte_size": row["byte_size"],
            }
        )
        spans.append(
            ObservationEvidenceSpan(
                row["asset_version_id"], 0, row["byte_size"], row["content_hash"]
            )
        )
    from .reading_scope import validate_reading_segments

    validate_reading_segments(units, tuple(segments))
    return tuple(segments), tuple(spans)


def execute_reading(app, worker, payload):
    from .runtime import CorpusIngestionRuntime

    runtime = CorpusIngestionRuntime(app)
    work, job, _ = runtime._load(worker)
    if work["status"] in {"SUCCEEDED", "REUSED"}:
        return work["result"]
    curated_provider_gate(app.database_url, worker)
    from .reading_recovery import require_completed_stage_recovery
    reuse_effect_id = (
        require_completed_stage_recovery(app, worker.project_id, payload)
        if payload.get("completion_recovery") else ""
    )
    plan = payload["narrative_reading"]
    targets = [u for u in plan["units"] if u["role"] == "TARGET"]
    index = payload["unit_index"]
    aggregate = index == len(targets)
    target = None if aggregate else targets[index]
    units = []
    if target is not None:
        position = plan["units"].index(target)
        first = max(0, position - plan["contract"].get("context_before", 0))
        last = position + plan["contract"].get("context_after", 0) + 1
        units = [
            {**unit, "role": "TARGET" if unit == target else "ALLOWED_CONTEXT"}
            for unit in plan["units"][first:last]
        ]
    analyzer = AnalyzerContract(
        **{k: v for k, v in payload["analyzer"].items() if k != "fingerprint"}
    )
    scope = ObservationScope(
        scale="CHAPTER_WINDOW" if aggregate else "CHAPTER",
        range_start=targets[0]["ordinal"] if aggregate else target["ordinal"],
        range_end=targets[-1]["ordinal"] if aggregate else target["ordinal"],
        source_document_ids=(payload["source_document_id"],),
        label=plan["identity"]
        + (":synthesis" if aggregate else ":" + target["source_unit_version_id"]),
    )
    port = app._require_execution_port()
    segments, spans = _source_inputs(app, worker, units) if units else ((), ())
    lower = []
    if aggregate:
        for item in payload["accepted_observations"]:
            document = port.query.require(
                project_id=worker.project_id,
                asset_version_id=item["observation_asset_version_id"],
            )
            lower.append(
                {
                    "asset_version_id": document.asset_version_id,
                    "content_hash": document.content_hash,
                    "observation": document.content["observation"],
                }
            )
    context = {
        "reading_identity": plan["identity"],
        "processing_id": plan["processing_id"],
        "source_transform_id": plan["source_transform_id"],
        "unit_bindings": [
            {
                **{
                    k: u[k]
                    for k in (
                        "source_unit_version_id",
                        "ordinal",
                        "normalized_content_hash",
                        "normalized_byte_start",
                        "normalized_byte_end",
                        "role",
                    )
                },
                "chunk_ranges": [
                    {
                        "source_chunk_asset_version_id": c["asset_version_id"],
                        "byte_start": max(
                            0, u["normalized_byte_start"] - c["source_byte_start"]
                        ),
                        "byte_end": min(
                            c["byte_size"],
                            u["normalized_byte_end"] - c["source_byte_start"],
                        ),
                    }
                    for c in u["chunks"]
                ],
            }
            for u in units
        ],
        "dimensions": plan["contract"]["dimensions"],
        "phase": payload["phase"],
        "unit_versions": [u["source_unit_version_id"] for u in units],
        "ordered_observation_units": [
            {
                "observation_asset_version_id": i["observation_asset_version_id"],
                "source_unit_version_id": i["source_unit_version_id"],
                "ordinal": i["ordinal"],
            }
            for i in payload["accepted_observations"]
        ]
        if aggregate
        else [],
        "coverage_claim": "VERIFIED_LOWER_OBSERVATIONS_ONLY"
        if aggregate
        else "EXACT_TARGET_WITH_DECLARED_SUPPORTING_UNITS",
        "outside_range": "UNKNOWN",
        "repair_round": payload["repair_round"],
        "prior_issues": payload["prior_issues"],
        "previous_candidate": payload.get("previous_candidate"),
        "preserve_requirements": payload.get("preserve_requirements", []),
        "failed_output": payload.get("failed_output"),
    }
    review = payload["phase"] == "REVIEW"
    candidate = payload.get("candidate")
    try:
        executed = port.execute_deconstruction(
            worker=worker,
            analyzer=analyzer,
            scope=scope,
            evidence_spans=spans,
            source_segments=segments,
            input_observations=tuple(lower),
            analysis_plan_asset_version_id=payload["analysis_plan_asset_version_id"],
            narrative_context=context,
            **({"reuse_effect_id": reuse_effect_id} if reuse_effect_id else {}),
            review_target={
                "observation": candidate["observation"],
                "evidence_spans": candidate["evidence_spans"],
                "execution_asset_version_id": candidate["execution_asset_version_id"],
                "prior_issues": payload["prior_issues"],
            }
            if review
            else None,
        )
    except KernelError as exc:
        if payload.get("source_sampling"):
            raise
        if (
            exc.code != "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
            and not exc.code.startswith(
                ("NARRATIVE_", "SOURCE_OUTPUT_", "DECONSTRUCTION_FINDING_")
            )
        ):
            raise
        return _invalid_result(app, worker, job, payload, exc)
    curated_provider_gate(app.database_url, worker)
    if payload.get("source_sampling"):
        from ..sampling import finish_sample

        return finish_sample(app, worker, executed)
    evidence = _input_evidence(app, worker, payload)
    result = {
        "phase": payload["phase"],
        "processing_id": plan["processing_id"],
        "unit_index": index,
        "repair_round": payload["repair_round"],
        "output_validation": "PASSED",
        "semantic_review_status": executed.get("review", {}).get("decision", "PENDING"),
        **evidence,
        **executed,
    }
    if not review:
        next_payload = {**payload, "phase": "REVIEW", "candidate": executed}
        return _finish_stage(app, None, worker, job, payload, result, next_payload)
    try:
        issues = reconcile_review(
            executed["review"],
            payload["prior_issues"],
            {f["finding_code"] for f in candidate["observation"]["findings"]},
        )
    except KernelError as exc:
        return _invalid_result(app, worker, job, payload, exc, result=result)
    result["issues"] = issues
    if executed["review"]["decision"] != "ACCEPT_IN_SCOPE" or any(
        i["severity"] == "BLOCKING" for i in issues
    ):
        blocked = (
            executed["review"]["decision"] == "NEEDS_REVIEW"
            or payload["repair_round"] >= plan["contract"]["max_repairs"]
        )
        return _finish_stage(
            app,
            None,
            worker,
            job,
            payload,
            result,
            None
            if blocked
            else _repair(payload, issues, executed["review"]["preserve_requirements"]),
            blocked=blocked,
        )
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        require_current_fence(uow, worker)
        curated_provider_gate(app.database_url, worker)
        accepted = list(payload["accepted_observations"])
        if candidate["observation"]["findings"]:
            formal = app.source_authority.execute_observation(
                CommitDeconstructionObservationCommand(
                    project_id=worker.project_id,
                    workspace_id=job["workspace_id"],
                    execution_asset_version_id=candidate["execution_asset_version_id"],
                    scope=scope,
                    analyzer=analyzer,
                    observation=candidate["observation"],
                    evidence_spans=tuple(_span(s) for s in candidate["evidence_spans"]),
                    input_observation_asset_version_ids=tuple(
                        i["asset_version_id"] for i in lower
                    ),
                    evidence_class=candidate["evidence_class"],
                    actor_id=app.worker_id,
                    idempotency_key="narrative-observation:"
                    + corpus_hash(
                        {
                            "candidate": candidate["execution_asset_version_id"],
                            "scope": scope.fingerprint,
                        }
                    ),
                    trace_id=worker.trace_id,
                    correlation_id=worker.correlation_id,
                    analysis_plan_asset_version_id=payload[
                        "analysis_plan_asset_version_id"
                    ],
                )
            )
            observation = {
                "observation_id": formal["observation_id"],
                "source_unit_version_id": None
                if aggregate
                else target["source_unit_version_id"],
                "ordinal": index,
                "observation_asset_version_id": formal["asset_version_id"],
                "execution_asset_version_id": candidate["execution_asset_version_id"],
                "evidence_class": candidate["evidence_class"],
            }
            result.update(observation)
            if aggregate:
                app._admit_mkaos_child(worker, job, observation, payload=payload)
            else:
                accepted.append(observation)
        next_payload = None
        if not aggregate and (index + 1 < len(targets) or accepted):
            next_payload = {k: v for k, v in payload.items() if k not in {"candidate", "completion_recovery"}} | {
                "phase": "SYNTHESIZE" if index + 1 == len(targets) else "OBSERVE",
                "unit_index": index + 1,
                "repair_round": 0,
                "prior_issues": [],
                "previous_candidate": None,
                "failed_output": None,
                "preserve_requirements": [],
                "accepted_observations": accepted,
            }
        result["knowledge_approved"] = False
        result["semantic_evidence"] = "AGENT_REVIEW_ONLY"
        result = _finish_stage(app, uow, worker, job, payload, result, next_payload)
        uow.commit()
        return result


def _invalid_result(app, worker, job, payload, error, result=None):
    evidence = _input_evidence(app, worker, payload)
    review = payload["phase"] == "REVIEW"
    issue = {
        "issue_id": corpus_hash(
            {"operation": worker.causation_id, "error": error.code}
        ),
        "finding_code": "SCOPE",
        "category": "EVIDENCE",
        "severity": "BLOCKING",
        "reason": error.code,
        "repair_goal": "Correct the review contract and explicitly account for every prior blocking issue."
        if review
        else "Repair only this frozen observation and its exact evidence contract.",
        "acceptance_condition": "Exact source/identity checks pass and unresolved gates remain blocking.",
    }
    issues = [*payload["prior_issues"], issue]
    blocked = (
        payload["repair_round"]
        >= payload["narrative_reading"]["contract"]["max_repairs"]
    )
    following = (
        None
        if blocked
        else (
            {
                **payload,
                "repair_round": payload["repair_round"] + 1,
                "prior_issues": issues,
            }
            if review
            else _repair(payload, issues)
        )
    )
    confirmed = [
        r for r in evidence["input_receipts"] if r["state"] == "CONFIRMED_RETURNED"
    ]
    if following and confirmed:
        following["failed_output"] = {
            "effect_id": confirmed[-1]["effect_id"],
            "validation_error": error.code,
            "output_validation": "FAILED",
            "semantic_review_status": "NOT_ACCEPTED",
            "reading_identity": payload["narrative_reading"]["identity"],
        }
    return _finish_stage(
        app,
        None,
        worker,
        job,
        payload,
        {
            **(result or {}),
            **evidence,
            "phase": payload["phase"],
            "repair_round": payload["repair_round"],
            "validation_error": error.code,
            "output_validation": "FAILED",
            "semantic_review_status": "NOT_ACCEPTED",
            "issues": issues,
        },
        following,
        blocked=blocked,
    )


def _input_evidence(app, worker, payload):
    from .reading_evidence import receipt_input_evidence

    with AuthorityUnitOfWork(app.database_url) as uow:
        records = SourceImportRepository(uow.cursor).reading_input_records(
            worker.project_id, worker.causation_id
        )
    return receipt_input_evidence(records, payload)


def _repair(payload, issues, preserve_requirements=None):
    return {k: v for k, v in payload.items() if k not in {"candidate", "completion_recovery"}} | {
        "phase": "SYNTHESIZE"
        if payload["unit_index"]
        == len(
            [u for u in payload["narrative_reading"]["units"] if u["role"] == "TARGET"]
        )
        else "OBSERVE",
        "repair_round": payload["repair_round"] + 1,
        "prior_issues": issues,
        "previous_candidate": payload.get("candidate"),
        "preserve_requirements": list(
            preserve_requirements or payload.get("preserve_requirements", [])
        ),
    }


def _finish_stage(
    app, uow, worker, job, payload, result, next_payload, *, blocked=False
):
    if uow is None:
        with AuthorityUnitOfWork(
            app.database_url, coordinate_nested=True
        ) as transaction:
            value = _finish_stage(
                app,
                transaction,
                worker,
                job,
                payload,
                result,
                next_payload,
                blocked=blocked,
            )
            transaction.commit()
            return value
    require_current_fence(uow, worker)
    curated_provider_gate(app.database_url, worker)
    if next_payload and not blocked:
        result["next_operation_id"] = _queue(app, uow, worker, job, next_payload)
    result["phase_status"] = "NEEDS_REVIEW" if blocked else "COMPLETED"
    repository = SourceImportRepository(uow.cursor)
    repository.update_work(
        project_id=worker.project_id,
        operation_id=worker.causation_id,
        expected=("RUNNING", "PLANNED", "QUEUED"),
        status="BLOCKED" if blocked else "SUCCEEDED",
        result=result,
        failure={
            "code": "NARRATIVE_REVIEW_REQUIRED",
            "issues": result.get("issues", []),
        }
        if blocked
        else {},
    )
    app._record_event(
        uow,
        worker,
        aggregate_type="authority_source_import_job",
        aggregate_id=job["import_job_id"],
        event_type="authority.source.analysis.reading_stage_completed",
        payload={
            "phase": payload["phase"],
            "phase_status": result["phase_status"],
            "reading_identity": payload["narrative_reading"]["identity"],
        },
    )
    app._refresh_job(repository, job["import_job_id"], worker.project_id)
    return result
