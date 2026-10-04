from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    authorization_hash, load_bootstrap_authorization, validate_reference_evaluation_binding,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .qualification import validate_narrative_qualification, uses_work_requirements


def reference_execution_gate(
    uow: AuthorityUnitOfWork, *, project_id: str, operation_id: str,
) -> dict[str, Any] | None:
    uow.cursor.execute(
        """SELECT command_payload->'payload',status,actor_id FROM authority_operation
           WHERE project_id=%s AND operation_id=%s""", [project_id, operation_id],
    )
    row = uow.cursor.fetchone()
    payload = dict(row[0] or {}) if row else {}
    if not payload.get("reference_evaluation"):
        return None
    snapshot = load_bootstrap_authorization(
        uow.cursor, project_id=project_id, operation_id=operation_id,
    )
    if snapshot is None or row[1] != "EXECUTING" or payload.get("opening_execution_binding"):
        raise KernelError("NARRATIVE_REFERENCE_EXECUTION_GATE_CLOSED",
                          "reference sampling requires a live isolated Kernel Operation and exact grant")
    reference = payload["reference_evaluation"]
    uow.cursor.execute(
        """SELECT EXISTS (
            SELECT 1 FROM authority_operation generation
            JOIN authority_operation_output_asset output ON output.operation_id=generation.operation_id
            JOIN authority_asset_version candidate ON candidate.asset_version_id=output.asset_version_id
              AND candidate.content_hash=output.content_hash
            JOIN authority_asset candidate_asset ON candidate_asset.asset_id=candidate.asset_id
              AND candidate_asset.project_id=generation.project_id
            JOIN authority_asset_version labels ON labels.asset_version_id=%s AND labels.content_hash=%s
              AND labels.governance='CLEAR' AND labels.lifecycle='ACTIVE'
            JOIN authority_asset labels_asset ON labels_asset.asset_id=labels.asset_id
              AND labels_asset.project_id=generation.project_id
            WHERE generation.project_id=%s AND generation.operation_id=%s
              AND generation.status IN ('WAITING_GATE','SUCCEEDED')
              AND generation.actor_id=%s AND generation.actor_id<>%s
              AND candidate.asset_version_id=%s AND candidate.content_hash=%s
              AND candidate.governance='CLEAR'
              AND candidate.content->>'routing_eligibility'='BENCHMARK_ONLY'
              AND COALESCE(generation.command_payload #> '{payload,opening_execution_binding}','{}'::jsonb)='{}'::jsonb
        )""", [reference["asset_version_id"], reference["content_hash"], project_id,
                payload["generation_operation_id"], payload["generation_actor_id"], row[2],
                payload["candidate_asset_version_id"], payload["candidate_content_hash"]],
    )
    if not uow.cursor.fetchone()[0]:
        raise KernelError("NARRATIVE_REFERENCE_EXECUTION_GATE_CLOSED",
                          "reference sampling candidate or label lineage is no longer eligible")
    return {"mode": "REFERENCE_SAMPLING", "execution_authority": "COMMAND_KERNEL",
            "operation_id": operation_id, "project_id": project_id,
            "candidate_asset_version_id": payload["candidate_asset_version_id"],
            "production_qualification_eligible": False}


def reference_command_fields(command: Any) -> dict[str, Any]:
    if not isinstance(command.reference_predecessor_operation_id, str) or (
        command.reference_predecessor_operation_id
        and command.reference_predecessor_operation_id != command.reference_predecessor_operation_id.strip()
    ):
        raise ValueError("reference predecessor requires an exact Operation identity")
    if not command.routing_bootstrap_authorization_id:
        if command.reference_evaluation is not None or command.reference_predecessor_operation_id:
            raise ValueError("reference evaluation requires its explicit authorization")
        return {}
    if command.evaluator_execution_class != "MODEL_PROVIDER":
        raise ValueError("reference sampling requires the governed Provider evaluator")
    validate_reference_evaluation_binding(command.reference_evaluation)
    reference = dict(command.reference_evaluation)
    return {
        "project_id": command.project_id,
        "logical_key": command.candidate_asset_version_id,
        "idempotency_key": command.idempotency_key,
        "input_versions": {
            "candidate": command.candidate_asset_version_id,
            "candidate_content_hash": command.candidate_content_hash,
            "reference": reference["asset_version_id"],
            "reference_content_hash": reference["content_hash"],
        },
        "routing_bootstrap_authorization_id": command.routing_bootstrap_authorization_id,
        "reference_evaluation": reference,
        **({"reference_predecessor_operation_id": command.reference_predecessor_operation_id}
           if command.reference_predecessor_operation_id else {}),
    }


def require_reference_review(
    database_url: str, *, project_id: str, payload: Mapping[str, Any],
    evaluator_actor_id: str,
) -> Mapping[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        return _require_reference_review(uow.cursor, project_id=project_id,
            payload=payload, evaluator_actor_id=evaluator_actor_id)


def _require_reference_review(
    cursor: Any,
    *,
    project_id: str,
    payload: Mapping[str, Any],
    evaluator_actor_id: str,
) -> Mapping[str, Any]:
    reference = payload["reference_evaluation"]
    validate_reference_evaluation_binding(reference)
    cursor.execute(
        """SELECT version.content,version.content_hash,operation.actor_id,
                  operation.operation_id
           FROM authority_asset_version version
           JOIN authority_asset asset USING(asset_id)
           JOIN authority_operation_output_asset output
             ON output.asset_version_id=version.asset_version_id
             AND output.content_hash=version.content_hash
           JOIN authority_operation operation ON operation.operation_id=output.operation_id
             AND operation.project_id=asset.project_id
           WHERE asset.project_id=%s AND version.asset_version_id=%s
             AND asset.asset_type='narrative_design_operator_review'
             AND version.governance='CLEAR' AND version.lifecycle='ACTIVE'
             AND operation.definition_name='story_design.review.author'
             AND operation.status='SUCCEEDED'
             AND NOT EXISTS (SELECT 1 FROM authority_external_effect effect
                 WHERE effect.operation_id=operation.operation_id)
           ORDER BY output.created_at""",
        [project_id, reference["asset_version_id"]],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("NARRATIVE_REFERENCE_PROVENANCE_INVALID",
                          "reference labels require one successful native operator-review author Operation")
    content, digest, author, operation_id = rows[0]
    if (
        digest != reference["content_hash"] or digest != authorization_hash(content)
        or author in {evaluator_actor_id, payload["generation_actor_id"]}
        or operation_id == payload["generation_operation_id"]
        or content.get("contract_version") != "narrative-design-operator-review.v1"
        or content.get("project_id") != project_id
        or content.get("candidate_asset_version_id") != payload["candidate_asset_version_id"]
        or content.get("candidate_content_hash") != payload["candidate_content_hash"]
        or content.get("evaluator_execution_class") != "OPERATOR_REVIEW"
        or any(content.get(key) is not False for key in (
            "provider_evidence_claimed", "human_preference_evidence", "ground_truth_claimed",
        ))
    ):
        raise KernelError("NARRATIVE_REFERENCE_NOT_INDEPENDENT",
                          "reference identity, independent author or non-human evidence boundary differs")
    cursor.execute(
        "SELECT v.content FROM authority_asset_version v JOIN authority_asset a ON a.asset_id=v.asset_id WHERE a.project_id=%s AND v.asset_version_id=%s AND v.content_hash=%s",
        [
            project_id,
            payload["candidate_asset_version_id"],
            payload["candidate_content_hash"],
        ],
    )
    candidate_row = cursor.fetchone()
    if candidate_row is None:
        raise KernelError(
            "NARRATIVE_REFERENCE_TARGET_STALE", "Reference requires the exact candidate"
        )
    work_requirements = uses_work_requirements(candidate_row[0])
    validate_narrative_qualification(
        generator_operation_name=payload["generator_operation_name"],
        value=content.get("evaluation"),
        require_pass=False,
        work_requirements=work_requirements,
    )
    adjudicated = None
    if reference.get("adjudicated_reference"):
        from novel_forge.modules.chapter_quality_authority.reference_sampling import require_adjudicated_reference
        from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject

        native = reference["adjudicated_reference"]
        verdicts = {layer["layer"] + ":" + criterion["criterion"]: criterion["verdict"]
            for layer in content["evaluation"]["evaluations"] for criterion in layer["criteria"]}
        statuses = {"PASS": "PASSED", "FAIL": "FAILED"}
        if any(value not in statuses for value in verdicts.values()):
            raise KernelError("NARRATIVE_REFERENCE_COVERAGE_INCOMPLETE", "trusted calibration requires determinate native criterion labels")
        subject = require_reference_subject(cursor, project_id=project_id,
            binding={"asset_version_id": payload["candidate_asset_version_id"], "content_hash": payload["candidate_content_hash"]},
            allowed_types=frozenset({"planning_generation_candidate"}))
        if (subject["generation_operation_id"] != payload["generation_operation_id"]
            or subject["generation_actor_id"] != payload["generation_actor_id"]):
            raise KernelError("NARRATIVE_REFERENCE_NOT_INDEPENDENT", "trusted reference candidate generation lineage differs")
        adjudicated = require_adjudicated_reference(cursor, project_id=project_id,
            binding={"protocol_version": reference["protocol_version"], "adjudications": native["adjudications"]},
            target_id=payload["candidate_asset_version_id"], target_hash=payload["candidate_content_hash"],
            generators=[payload["generation_actor_id"]], evaluator_actor_id=evaluator_actor_id,
            chapter=native["scope"]["chapter_start"], chapter_end=native["scope"]["chapter_end"], scope_type=native["scope"]["scope_type"],
            expected_dimensions=tuple(verdicts), allowed_statuses=set(statuses.values()))
        if any(label["status"] != statuses[verdicts[label["dimension"]]] for label in adjudicated["labels"]):
            raise KernelError("NARRATIVE_REFERENCE_LABEL_CONFLICT", "operator proxy labels differ from independent native adjudications")
        adjudicated = {**adjudicated, "scope": dict(native["scope"])}
    return {
        "content": content,
        "work_requirements": work_requirements,
        "author_actor_id": author,
        "operation_id": operation_id,
        **({"adjudicated_reference": adjudicated} if adjudicated else {}),
    }


def reference_agreement(
    *,
    payload: Mapping[str, Any],
    reference: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    def verdicts(value: Mapping[str, Any]) -> dict[tuple[str, str], str]:
        validate_narrative_qualification(
            generator_operation_name=payload["generator_operation_name"],
            value=value,
            require_pass=False,
            work_requirements=bool(reference.get("work_requirements")),
        )
        return {(layer["layer"], criterion["criterion"]): criterion["verdict"]
                for layer in value["evaluations"] for criterion in layer["criteria"]}

    expected = verdicts(reference["content"]["evaluation"])
    observed = verdicts(evaluation)
    comparisons = [
        {"layer": layer, "criterion": criterion, "expected": expected[(layer, criterion)],
         "observed": observed[(layer, criterion)],
         "agrees": expected[(layer, criterion)] == observed[(layer, criterion)]}
        for layer, criterion in sorted(expected)
    ]
    return {
        "schema_version": "narrative-reference-agreement.v2" if reference.get("adjudicated_reference") else "narrative-reference-agreement.v1",
        "reference": dict(payload["reference_evaluation"]),
        "reference_operation_id": reference["operation_id"],
        "reference_author_actor_id": reference["author_actor_id"],
        "generator_operation_name": payload["generator_operation_name"],
        "criterion_agreement": comparisons,
        "agreement_rate": sum(item["agrees"] for item in comparisons) / len(comparisons),
        "reference_basis": "ADJUDICATED_SUBJECTIVE_EVIDENCE" if reference.get("adjudicated_reference") else "INDEPENDENT_OPERATOR_PROXY_LABELS",
        **({"adjudicated_reference": reference["adjudicated_reference"]} if reference.get("adjudicated_reference") else {}),
        "ground_truth_claimed": False,
        "human_preference_evidence": False,
        "production_qualification_eligible": False,
    }


def narrative_reference_outcomes(cursor: Any, *, project_id: str, effect_ids: list[str]) -> dict[str, dict[str, Any]]:
    from novel_forge.modules.chapter_quality_authority.reference_sampling import reference_label_classes, reference_provider_result

    if not effect_ids:
        return {}
    cursor.execute("""SELECT effect.external_effect_id,effect.operation_id,attempt.attempt_id,operation.actor_id,
        operation.command_payload->'payload',version.asset_version_id,version.content_hash,version.content,model.content_hash,model.content
        FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id)
        JOIN authority_operation_output_asset output ON output.operation_id=operation.operation_id AND output.role='qualification_evidence'
        JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.content_hash=output.content_hash
        JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=operation.project_id
        JOIN authority_asset_version model ON model.asset_version_id=version.content #>> '{provider_evidence_asset_version_ids,0}'
          AND COALESCE(model.content->'provider_evidence',model.content)
            #>> '{production_execution,execution_request,external_effect_id}'=effect.external_effect_id
        JOIN authority_attempt attempt ON attempt.attempt_id=version.content->>'evaluation_attempt_id'
          AND attempt.operation_id=operation.operation_id AND attempt.status='SUCCEEDED'
        WHERE effect.project_id=%s AND effect.external_effect_id=ANY(%s) AND effect.status='SUCCEEDED'
          AND operation.status='SUCCEEDED' AND operation.definition_name='story_design.semantic_evaluate'
          AND asset.asset_type='narrative_design_evaluation' AND version.governance='CLEAR'
          AND version.content->>'routing_eligibility'='BENCHMARK_ONLY'
          AND version.content->'production_qualification_eligible'='false'::jsonb
        ORDER BY version.created_at,version.asset_version_id""", [project_id, effect_ids])
    outcomes = {}
    for effect_id, operation_id, attempt_id, actor, payload, asset_id, digest, content, model_hash, model in cursor.fetchall():
        if digest != authorization_hash(content) or not payload.get("reference_evaluation", {}).get("adjudicated_reference"):
            continue
        try:
            snapshot = load_bootstrap_authorization(cursor, project_id=project_id, operation_id=operation_id, check_expiry=False)
            grant = snapshot["authorization"] if snapshot else {}
            if grant.get("purpose") != "REFERENCE_EVALUATION" or grant.get("task_type") != "narrative_semantic_evaluation":
                continue
            provider = reference_provider_result(cursor, project_id=project_id, operation_id=operation_id,
                attempt_id=attempt_id, stage="narrative_semantic_evaluation")
            evidence = model.get("provider_evidence") or {}
            native = (evidence.get("production_execution") or {}).get("execution_request") or {}
            if (not provider["real_model_call"] or content.get("evaluation") != provider["result"]
                or model_hash != authorization_hash(model) or model.get("operation_id") != operation_id or model.get("attempt_id") != attempt_id
                or any(native.get(key) != value for key, value in {"project_id": project_id, "operation_id": operation_id,
                    "attempt_id": attempt_id, "external_effect_id": effect_id, "stage": "narrative_semantic_evaluation"}.items())
                or model.get("target_lineage") != {"target_asset_version_id": payload["candidate_asset_version_id"],
                    "target_content_hash": payload["candidate_content_hash"], "generation_operation_id": payload["generation_operation_id"],
                    "generator_operation_name": payload["generator_operation_name"]}
                or content.get("provider_execution", {}).get("provider_evidence_hash") != authorization_hash(evidence)
                or content.get("provider_execution", {}).get("provider_result_hash") != authorization_hash(provider["result"])
                or content.get("provider_evidence_asset_version_ids") != [provider["model_call_asset_version_id"]]
                or content.get("provider_evidence") != [{"asset_version_id": provider["model_call_asset_version_id"],
                    "content_hash": provider["model_call_content_hash"]}]
                or content.get("candidate_asset_version_id") != payload["candidate_asset_version_id"]
                or content.get("candidate_content_hash") != payload["candidate_content_hash"]
                or content.get("generation_operation_id") != payload["generation_operation_id"]):
                continue
            reference = _require_reference_review(cursor, project_id=project_id, payload=payload, evaluator_actor_id=actor)
            agreement = reference_agreement(payload=payload, reference=reference, evaluation=provider["result"])
            if agreement != content.get("reference_evaluation") or not reference.get("adjudicated_reference"):
                continue
            adjudicated = reference["adjudicated_reference"]
            classes = reference_label_classes(cursor, project_id=project_id, reference=adjudicated, stage="narrative_semantic_evaluation")
            if not classes:
                continue
            cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s AND content_hash=%s",
                [payload["candidate_asset_version_id"], payload["candidate_content_hash"]])
            candidate = cursor.fetchone()[0]
        except (KernelError, ValueError, TypeError, KeyError):
            continue
        agreed = all(item["agrees"] for item in agreement["criterion_agreement"])
        outcomes[effect_id] = {"accepted": None, "metric": "REFERENCE_AGREEMENT.v1", "reference_agreed": agreed,
            "generator_assessment": {"target_asset_version_id": adjudicated["target_asset_version_id"],
                "target_content_hash": adjudicated["target_content_hash"], "labels": adjudicated["labels"],
                "protocol_version": payload["reference_evaluation"]["protocol_version"]},
            "reference_label_classes": classes,
            "reference_protocol_hash": authorization_hash({"protocol_version": payload["reference_evaluation"]["protocol_version"],
                "generator_operation_name": payload["generator_operation_name"], "scope_type": adjudicated["scope"]["scope_type"],
                "evaluation_versions": sorted({item["evaluation_version"] for item in adjudicated["labels"]}),
                "dimensions": sorted(item["dimension"] for item in adjudicated["labels"]), "agreement_contract": "narrative-reference-agreement.v2"}),
            "reference_sample_identity": authorization_hash({"task_type": payload["generator_operation_name"], "candidate": candidate["candidate_payload"]}),
            "failure_class": "" if agreed else "QUALITY_FAILURE",
            "evidence_refs": ["asset-version:" + asset_id, "asset-version:" + provider["model_call_asset_version_id"],
                "asset-version:" + payload["reference_evaluation"]["asset_version_id"],
                *("asset-version:" + item["adjudication_asset_version_id"] for item in adjudicated["labels"])]}
    return outcomes
