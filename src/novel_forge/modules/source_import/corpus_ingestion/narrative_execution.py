from __future__ import annotations

from dataclasses import replace
from uuid import uuid4
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.source_authority.corpus import corpus_hash
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
    analyzer = replace(
        strategy.analyzers[0],
        analyzer_id="bounded-narrative." + strategy.analyzers[0].dimension,
        analyzer_version="1.0.0",
        schema_version="source-narrative-observation.v1",
        prompt_id="source.bounded-narrative",
        prompt_version="1.0.0",
        recommended_scales=("CHAPTER", "CHAPTER_WINDOW"),
    )
    return replace(
        strategy,
        analyzers=(analyzer,),
        profile_id="bounded-narrative." + strategy.profile_id,
        profile_version="1.0.0",
    )


def begin_reading(app, worker, job, plan, scope, strategy, plan_version):
    payload = {
        "import_job_id": job["import_job_id"],
        "reading_parent_operation_id": worker.causation_id,
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
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        require_current_fence(uow, worker)
        _queue(app, uow, worker, job, payload)
        uow.commit()


def _queue(app, uow, worker, job, payload):
    from novel_forge.modules.source_import.application import (
        SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
    )

    key = "narrative-reading:" + corpus_hash(
        {"job": job["import_job_id"], "payload": payload}
    )
    child = app._admit_child(
        definition_name=SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
        project_id=worker.project_id,
        workspace_id=job["workspace_id"],
        actor_id=app.worker_id,
        idempotency_key=key,
        trace_id=worker.trace_id,
        correlation_id=worker.correlation_id,
        causation_id=worker.causation_id,
        parent_operation_id=payload["reading_parent_operation_id"],
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
            "project_id": worker.project_id,
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
        project_id=worker.project_id,
        actor_id=app.worker_id,
        trace_id=worker.trace_id,
        correlation_id=worker.correlation_id,
        causation_id=worker.causation_id,
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
    plan = payload["narrative_reading"]
    targets = [u for u in plan["units"] if u["role"] == "TARGET"]
    index = payload["unit_index"]
    aggregate = index == len(targets)
    units = [] if aggregate else [targets[index]]
    analyzer = AnalyzerContract(
        **{k: v for k, v in payload["analyzer"].items() if k != "fingerprint"}
    )
    scope = ObservationScope(
        scale="CHAPTER_WINDOW" if aggregate else "CHAPTER",
        range_start=targets[0]["ordinal"] if aggregate else units[0]["ordinal"],
        range_end=targets[-1]["ordinal"] if aggregate else units[0]["ordinal"],
        source_document_ids=(payload["source_document_id"],),
        label=plan["identity"]
        + (":synthesis" if aggregate else ":" + units[0]["source_unit_version_id"]),
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
        "dimensions": plan["contract"]["dimensions"],
        "phase": payload["phase"],
        "unit_versions": [u["source_unit_version_id"] for u in units],
        "coverage_claim": "VERIFIED_LOWER_OBSERVATIONS_ONLY"
        if aggregate
        else "EXACT_TARGET_UNIT_TEXT",
        "outside_range": "UNKNOWN",
        "repair_round": payload["repair_round"],
        "prior_issues": payload["prior_issues"],
        "previous_candidate": payload.get("previous_candidate"),
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
            review_target={
                "observation": candidate["observation"],
                "prior_issues": payload["prior_issues"],
            }
            if review
            else None,
        )
    except KernelError as exc:
        if not exc.code.startswith(
            ("NARRATIVE_", "SOURCE_OUTPUT_", "DECONSTRUCTION_FINDING_")
        ):
            raise
        issue = {
            "issue_id": corpus_hash(
                {"operation": worker.causation_id, "error": exc.code}
            ),
            "finding_code": "SCOPE",
            "category": "EVIDENCE",
            "severity": "BLOCKING",
            "reason": exc.code,
            "repair_goal": "Regenerate only this frozen observation and correct the reported evidence contract.",
            "acceptance_condition": "All exact source, reference and coverage checks pass.",
        }
        return _finish_stage(
            app,
            uow=None,
            worker=worker,
            job=job,
            payload=payload,
            result={
                "phase": payload["phase"],
                "validation_error": exc.code,
                "issues": [issue],
            },
            next_payload=_repair(payload, [*payload["prior_issues"], issue]),
            blocked=payload["repair_round"] >= plan["contract"]["max_repairs"],
        )
    curated_provider_gate(app.database_url, worker)
    coverage = {
        "reading_identity": plan["identity"],
        "processing_id": plan["processing_id"],
        "target_units": [u["source_unit_version_id"] for u in units],
        "actual_text_inputs": [
            {k: v for k, v in s.items() if k != "content"} for s in segments
        ],
        "lower_observation_inputs": [i["asset_version_id"] for i in lower],
        "read_mode": "VERIFIED_OBSERVATIONS" if aggregate else "FULL_TARGET_UNIT_TEXT",
        "allowed_context_not_read": [
            u["source_unit_version_id"]
            for u in plan["units"]
            if u["role"] == "ALLOWED_CONTEXT"
        ],
        "execution_asset_version_id": executed["execution_asset_version_id"],
        "understanding_claim": False,
    }
    result = {
        "phase": payload["phase"],
        "processing_id": plan["processing_id"],
        "unit_index": index,
        "repair_round": payload["repair_round"],
        "coverage": coverage,
        **executed,
    }
    if not review:
        next_payload = {**payload, "phase": "REVIEW", "candidate": executed}
        return _finish_stage(app, None, worker, job, payload, result, next_payload)
    issues = reconcile_review(
        executed["review"],
        payload["prior_issues"],
        {f["finding_code"] for f in candidate["observation"]["findings"]},
    )
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
            None if blocked else _repair(payload, issues),
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
            next_payload = {k: v for k, v in payload.items() if k != "candidate"} | {
                "phase": "SYNTHESIZE" if index + 1 == len(targets) else "OBSERVE",
                "unit_index": index + 1,
                "repair_round": 0,
                "prior_issues": [],
                "previous_candidate": None,
                "accepted_observations": accepted,
            }
        result["knowledge_approved"] = False
        result["semantic_evidence"] = "AGENT_REVIEW_ONLY"
        result = _finish_stage(app, uow, worker, job, payload, result, next_payload)
        uow.commit()
        return result


def _repair(payload, issues):
    return {k: v for k, v in payload.items() if k != "candidate"} | {
        "phase": "SYNTHESIZE"
        if payload["unit_index"]
        == len(
            [u for u in payload["narrative_reading"]["units"] if u["role"] == "TARGET"]
        )
        else "OBSERVE",
        "repair_round": payload["repair_round"] + 1,
        "prior_issues": issues,
        "previous_candidate": payload.get("candidate", {}).get(
            "execution_asset_version_id"
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
