from __future__ import annotations

import re

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.production_execution.execution_template import (
    verify_template_provenance,
)
from novel_forge.modules.canon_graph.evidence_localization import (
    localize_provider_quotes,
)
from .model_effects import ModelProviderResult

CONTRACT = "chapter-current-quote-repair.v1"


def receipt(cursor, operation):
    cursor.execute(
        """SELECT e.external_effect_id,e.request_hash,d.dispatch_id,e.request_payload,r.evidence,p.payload->'evidence'
        FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id)
        JOIN authority_external_effect_dispatch d USING(external_effect_id) JOIN authority_external_receipt p USING(dispatch_id)
        WHERE e.operation_id=%s AND e.status='SUCCEEDED' AND r.status='SETTLED'
        AND r.accounting_basis='ACCOUNT_ENTITLEMENT' ORDER BY p.received_at DESC""",
        [operation["operation_id"]],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError(
            "CURRENT_QUOTE_RECOVERY_RECEIPT_REQUIRED",
            "Require one original settled membership result",
        )
    effect, request_hash, dispatch, payload, budget, evidence = rows[0]
    decision = (
        payload.get("_production_execution", {})
        .get("capability_runtime", {})
        .get("routing_decision", {})
    )
    template = verify_template_provenance(cursor, decision)
    if (
        not template
        or template["mode"] != "CREATIVE_VALIDATION"
        or template.get("version") != "creative-execution-template.v10"
        or template.get("chapter_graph_recovery") != "RETAIN_SETTLED_CREATIVE_RESULT"
        or template["require_literary_qualification"]
        or decision.get("task", {}).get("operation_id") != operation["operation_id"]
        or budget.get("cost_authorization_ref") != template["member_authorization_ref"]
    ):
        raise KernelError(
            "CURRENT_QUOTE_RECOVERY_AUTHORIZATION_INVALID",
            "Retain the real original creative membership authorization",
        )
    return {
        "source_effect_id": effect,
        "source_request_hash": request_hash,
        "source_dispatch_id": dispatch,
        "cost_authorization_ref": budget["cost_authorization_ref"],
        "book_id": template["book_id"],
    }, ModelProviderResult.from_evidence(evidence).output


def asset(cursor, project, binding):
    cursor.execute(
        """SELECT a.asset_type,v.content,v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
        WHERE v.asset_version_id=%s AND a.project_id=%s""",
        [binding["asset_version_id"], project],
    )
    row = cursor.fetchone()
    if not row or row[2] != binding["content_hash"]:
        raise KernelError(
            "CURRENT_QUOTE_RECOVERY_INPUT_DRIFT",
            "Retain the exact frozen input identities and hashes",
        )
    return row[0], row[1]


def source_graph(cursor, *, root, saga):
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    from novel_forge.modules.command_kernel.derived_step_revalidation import (
        _settled_graph,
    )
    from novel_forge.modules.command_kernel.step_successor import (
        has_candidate_domain_outputs,
    )

    project = root["project_id"]
    actor = root["actor_id"]
    if (
        root["status"] != "FAILED_FINAL"
        or saga["status"] != "MANUAL_INTERVENTION"
        or root["definition_version"] != "3.9.0"
    ):
        raise KernelError(
            "CURRENT_QUOTE_RECOVERY_FRONTIER_INVALID",
            "Retain the exact failed native unaccepted Chapter",
        )
    cursor.execute(
        """SELECT to_jsonb(o) FROM authority_operation o WHERE o.root_operation_id=%s
        AND o.operation_id<>o.root_operation_id AND o.status IN ('FAILED_FINAL','DEAD_LETTER','CANCELLED') ORDER BY o.created_at""",
        [root["operation_id"]],
    )
    failed = [r[0] for r in cursor.fetchall()]
    if len(failed) != 1 or (
        failed[0]["definition_name"],
        failed[0]["definition_version"],
    ) not in {
        ("chapter.canon.extract", "3.9.24"),
        ("chapter.canon.extract", "3.9.30"),
        ("chapter.canon.extract", "3.9.31"),
        ("chapter.canon.propose_changes", "3.9.23"),
    }:
        raise KernelError(
            "CURRENT_QUOTE_RECOVERY_NOT_APPLICABLE",
            "Only the known current nonliteral quote failure may continue",
        )
    source = failed[0]
    semantic = source["definition_name"] == "chapter.canon.propose_changes"
    match = re.fullmatch(
        re.escape(root["idempotency_key"])
        + (
            r":canon_proposal:quality-correction:(\d+)"
            if semantic
            else r":canon_extraction:quality-correction:(\d+)"
        ),
        source["idempotency_key"],
    )
    if (
        not match
        or source["actor_id"] != actor
        or has_candidate_domain_outputs(cursor, source["operation_id"])
    ):
        raise KernelError(
            "CURRENT_QUOTE_RECOVERY_NOT_APPLICABLE",
            "Keep unrelated or producing Canon recovery ownership",
        )
    generation = int(match[1])
    semantic_proof = None
    derivation = None
    excluded_operations = {source["operation_id"]}
    if semantic:
        from .current_semantic_recovery import semantic_source

        semantic_proof, raw, extraction_op, inputs = semantic_source(cursor, source)
        excluded_operations.add(extraction_op["operation_id"])
        target, candidate = inputs["best_draft_candidate"]
        context, context_doc = inputs["context_bundle"]
    else:
        cursor.execute(
            "SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number",
            [source["operation_id"]],
        )
        attempts = [r[0] for r in cursor.fetchall()]
        if (
            len(attempts) != 1
            or attempts[0]["status"] != "FAILED_FINAL"
            or attempts[0]["result"].get("error_code")
            != "CANON_QUOTE_LOCALIZATION_INVALID"
        ):
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_DIAGNOSTIC_REQUIRED",
                "Require the exact terminal host diagnostic",
            )
        evidence, raw = receipt(cursor, source)
        inputs = {}
        for binding in source["input_asset_snapshot"]:
            kind, doc = asset(cursor, project, binding)
            if kind in inputs:
                raise KernelError(
                    "CURRENT_QUOTE_RECOVERY_INPUT_DRIFT",
                    "Require uniquely typed extraction inputs",
                )
            inputs[kind] = (binding, doc)
        target, candidate = inputs["best_draft_candidate"]
        context, context_doc = inputs["context_bundle"]
        try:
            localize_provider_quotes(
                raw,
                text=candidate["text"],
                target_asset_version_id=target["asset_version_id"],
            )
        except KernelError as error:
            if error.code != "CANON_QUOTE_LOCALIZATION_INVALID":
                raise
            diagnostic = {"code": error.code, "reason": error.message}
        else:
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_NOT_APPLICABLE",
                "Do not regenerate a valid retained quote result",
            )
    if source["definition_version"] == "3.9.31":
        from .canon_reference_recovery import derive_source
        derivation, _ = derive_source(cursor, source, raw=raw, inputs=inputs, evidence=evidence)
    from .quality_length_requirement import freeze_requirement, require_length

    requirement = freeze_requirement(
        context_doc, context_id=context["asset_version_id"]
    )
    rewind = None
    if requirement:
        try:
            require_length(requirement, candidate["text"])
        except KernelError as error:
            cursor.execute(
                "SELECT to_jsonb(o) FROM authority_operation o WHERE o.root_operation_id=%s AND o.idempotency_key=%s",
                [
                    root["operation_id"],
                    root["idempotency_key"]
                    + f":revision:quality-correction:{generation}",
                ],
            )
            revision = cursor.fetchone()
            if (
                not revision
                or revision[0]["status"] != "SUCCEEDED"
                or revision[0]["definition_version"] != "3.9.16"
            ):
                raise
            revision = revision[0]
            revision_evidence, revision_raw = receipt(cursor, revision)
            frozen = {
                kind: (binding, doc)
                for binding in revision["input_asset_snapshot"]
                for kind, doc in [asset(cursor, project, binding)]
                if kind != "revision_task"
            }
            original, original_doc = frozen["best_draft_candidate"]
            require_length(requirement, original_doc["text"])
            cursor.execute(
                "SELECT v.content FROM authority_operation_output_asset o JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND o.role='primary'",
                [revision["operation_id"]],
            )
            revised = cursor.fetchone()[0]
            if (
                revised["text"] != candidate["text"]
                or revised["source_revision_asset_version_id"]
                != original["asset_version_id"]
            ):
                raise KernelError(
                    "CURRENT_QUOTE_RECOVERY_CANDIDATE_DRIFT",
                    "Retain the actual short provisional edit and its selected candidate",
                )
            rewind = {
                "generation": generation,
                "source_operation_id": revision["operation_id"],
                "source_input_snapshot": revision["input_asset_snapshot"],
                **revision_evidence,
                "source_output_hash": snapshot_hash(revision_raw),
                "target_asset_version_id": original["asset_version_id"],
                "short_candidate_asset_version_id": target["asset_version_id"],
                "short_candidate_text_hash": snapshot_hash(candidate["text"]),
                "length_requirement": requirement,
                "diagnostic": {"code": error.code, "reason": error.message},
            }
    cursor.execute(
        """SELECT s.step_key,s.ordinal,s.source_step_snapshot,to_jsonb(o) FROM authority_saga_retained_step s
        JOIN authority_operation o USING(operation_id) WHERE s.saga_id=%s""",
        [saga["saga_id"]],
    )
    refs = {r[0]: (r[1], r[2], r[3]) for r in cursor.fetchall()}
    cursor.execute(
        """SELECT to_jsonb(s),to_jsonb(o) FROM authority_saga_step s JOIN authority_operation o USING(operation_id)
        WHERE s.saga_id=%s""",
        [saga["saga_id"]],
    )
    native = cursor.fetchall()
    for step, op in native:
        if step["step_key"] in refs:
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_STEP_AMBIGUOUS",
                "Retain unique native and inherited steps",
            )
        refs[step["step_key"]] = (step["ordinal"], step, op)
    cursor.execute(
        """SELECT to_jsonb(o) FROM authority_operation o WHERE o.root_operation_id=%s
        AND o.idempotency_key LIKE %s ORDER BY o.created_at,o.operation_id""",
        [root["operation_id"], root["idempotency_key"] + ":%:quality-correction:%"],
    )
    definitions = {node.definition_name: node.value for node in ChapterNode}
    for (op,) in cursor.fetchall():
        parsed = re.fullmatch(
            re.escape(root["idempotency_key"])
            + r":([^:]+):quality-correction:(\d+)(:action-revalidation)?",
            op["idempotency_key"],
        )
        if not parsed or parsed[1] != definitions.get(op["definition_name"]):
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_EXTENSION_INVALID",
                "Preserve unrelated extension recovery ownership",
            )
        gen = int(parsed[2])
        if op["operation_id"] in excluded_operations:
            continue
        if rewind and gen >= generation:
            continue
        key = f"quality-correction:{gen}:{parsed[1]}"
        ordinal = (
            2000
            + (gen - 1) * 100
            + list(ChapterNode).index(
                next(node for node in ChapterNode if node.value == parsed[1])
            )
        )
        refs[key] = (
            ordinal,
            {
                "step_key": key,
                "operation_id": op["operation_id"],
                "saga_id": saga["saga_id"],
                "ordinal": ordinal,
                "compensation_status": "NOT_REQUIRED",
                "reference_source": "native-completed-correction-command.v1",
            },
            op,
        )
    excluded = {
        ChapterNode.PUBLISH_GATE.value,
        ChapterNode.EXPORT.value,
        ChapterNode.FINAL_RELEASE_GATE.value,
    }
    steps = []
    for key, (ordinal, step, op) in sorted(refs.items(), key=lambda row: row[1][0]):
        if key in excluded:
            if (
                key != ChapterNode.PUBLISH_GATE.value
                or op["status"] not in {"ADMITTED", "READY", "FAILED_RETRYABLE"}
                or has_candidate_domain_outputs(cursor, op["operation_id"])
            ):
                raise KernelError(
                    "CURRENT_QUOTE_RECOVERY_DOWNSTREAM_STARTED",
                    "Completed release and export cannot be reopened",
                )
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)",
                [op["operation_id"]],
            )
            if cursor.fetchone()[0]:
                raise KernelError(
                    "CURRENT_QUOTE_RECOVERY_DOWNSTREAM_STARTED",
                    "Retain externally started release ownership",
                )
            continue
        if (
            op["status"] != "SUCCEEDED"
            or op["actor_id"] != actor
            or op["project_id"] != project
            or op["workspace_id"] != root["workspace_id"]
            or step.get("compensation_status") != "NOT_REQUIRED"
        ):
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_STEP_INVALID",
                "Retain only completed uncompensated authorized work",
            )
        cursor.execute(
            """SELECT to_jsonb(o),v.content_hash,v.lifecycle,v.eligibility,v.governance FROM authority_operation_output_asset o
            JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s ORDER BY o.output_key,o.asset_version_id""",
            [op["operation_id"]],
        )
        outputs = cursor.fetchall()
        if not outputs or any(
            row[3:] != ("ELIGIBLE", "CLEAR")
            or row[2] not in {"ACTIVE", "SUPERSEDED"}
            or row[0]["role"] in {"primary", "required_action"}
            and row[2] != "ACTIVE"
            for row in outputs
        ):
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_OUTPUT_INVALID",
                "Retain exact governed output snapshots",
            )
        steps.append(
            {"step": step, "operation": op, "outputs": [list(row) for row in outputs]}
        )
    expected = {node.value for node in ChapterNode} - excluded
    if {
        item["step"]["step_key"]
        for item in steps
        if not item["step"]["step_key"].startswith("quality-correction:")
    } != expected:
        raise KernelError(
            "CURRENT_QUOTE_RECOVERY_STEP_MISSING",
            "Retain all completed initial pre-publication steps",
        )
    for gen in range(1, generation if rewind else generation + 1):
        needed = {
            f"quality-correction:{gen}:{node.value}"
            for node in (
                ChapterNode.REVISION,
                ChapterNode.REREVIEW,
                ChapterNode.BEST_CANDIDATE,
            )
        }
        if gen < generation:
            needed |= {
                f"quality-correction:{gen}:{node.value}"
                for node in (
                    ChapterNode.CANON_EXTRACTION,
                    ChapterNode.CANON_PROPOSAL,
                    ChapterNode.CANON,
                    *tuple(n for n in ChapterNode if n.value.startswith("quality_")),
                    ChapterNode.QUALITY,
                )
            }
        if not needed.issubset({item["step"]["step_key"] for item in steps}):
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_STEP_MISSING",
                "Retain every completed preceding correction pass",
            )
    proof = semantic_proof or {
        "contract_version": "chapter-canon-reference-resolution-revalidation.v1" if derivation else "chapter-canon-reference-contract-repair.v1" if source["definition_version"] == "3.9.30" else CONTRACT,
        "source_operation_id": source["operation_id"],
        "source_attempt": attempts[0],
        **evidence,
        "source_output_hash": snapshot_hash(raw),
        "source_input_snapshot": source["input_asset_snapshot"],
        "target_asset_version_id": target["asset_version_id"],
        "remaining_diagnostic": diagnostic,
        "quality_generation": generation,
        "length_repair": rewind,
        "provider_invoked": derivation is None,
        "strict_certification_eligible": False,
        "completed_work_repeated": False,
    }
    if derivation:
        proof.update(derivation)
    if semantic_proof:
        proof.update(quality_generation=generation, length_repair=None)
    return {
        "root": root,
        "saga": saga,
        "steps": steps,
        "effects": _settled_graph(cursor, root["operation_id"]),
        "retained_result": proof,
    }


def repair_feedback(request, *, stage):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.retained_graph import BINDING

    binding = (request.command.get("preparation_report") or {}).get(BINDING) or {}
    proof = binding.get("retained_result") or {}
    if proof.get("contract_version") not in {CONTRACT, "chapter-canon-reference-contract-repair.v1"}:
        return None
    with AuthorityUnitOfWork(request.database_url) as uow:
        cursor = uow.cursor
        cursor.execute(
            """SELECT j.source_snapshot,j.policy_evidence,o.actor_id FROM authority_graph_continuation j
            JOIN authority_operation o ON o.root_operation_id=j.successor_root_operation_id
            WHERE o.operation_id=%s AND j.contract_version='kernel-retained-graph-continuation.v1' """,
            [request.operation_id],
        )
        row = cursor.fetchone()
        if not row or row[1] != binding or row[0]["root"]["actor_id"] != row[2]:
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_LINEAGE_INVALID",
                "Require the exact native continuation and original actor",
            )
        actual = source_graph(cursor, root=row[0]["root"], saga=row[0]["saga"])
        if actual != row[0] or actual["retained_result"] != proof:
            raise KernelError(
                "CURRENT_QUOTE_RECOVERY_SOURCE_DRIFT",
                "Retain the exact terminal graph and settled result evidence",
            )
        if stage == "revision":
            repair = proof.get("length_repair")
            if not repair:
                return None
            frozen = {
                item["asset_version_id"]: item["content_hash"]
                for item in repair["source_input_snapshot"]
            }
            supplied = {
                item.asset_version_id: item.content_hash for item in request.inputs
            }
            if supplied != frozen:
                raise KernelError(
                    "CURRENT_QUOTE_RECOVERY_INPUT_DRIFT",
                    "Repair only the original quality edit result under its same frozen diagnoses",
                )
            cursor.execute(
                "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
                [repair["source_operation_id"]],
            )
            evidence, raw = receipt(cursor, cursor.fetchone()[0])
            if snapshot_hash(raw) != repair["source_output_hash"]:
                raise KernelError(
                    "CURRENT_QUOTE_RECOVERY_RECEIPT_DRIFT",
                    "Retain the original provisional edit response",
                )
            return {
                "contract_version": "quality-retained-length-repair.v1",
                **evidence,
                "source_output_hash": repair["source_output_hash"],
                "rejected_candidate": raw,
                "length_requirement": repair["length_requirement"],
                "diagnostic": repair["diagnostic"],
                "instruction": "Repair these actual retained edits against the same original target and located diagnoses. Meet the original Han bounds without padding or new events. Preserve successful prior work; new independent review is required.",
            }
        if stage != "canon_extraction":
            return None
        cursor.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [proof["source_operation_id"]],
        )
        original_operation = cursor.fetchone()[0]
        _, raw = receipt(cursor, original_operation)
        target = request.require_input("best_draft_candidate")
        feedback = failed_quote_feedback(
            raw,
            target.content["text"],
            target=target.asset_version_id,
            evidence={
                key: proof[key]
                for key in (
                    "source_effect_id",
                    "source_request_hash",
                    "source_output_hash",
                )
            },
            continuation=True,
        )
        inherited = ((original_operation.get("command_payload", {}).get("preparation_report") or {}).get("retained_graph_continuation") or {}).get("retained_result") or {}
        if proof["contract_version"] == "chapter-canon-reference-contract-repair.v1" and inherited.get("contract_version") == "chapter-current-semantic-repair.v1":
            if inherited["target_asset_version_id"] != target.asset_version_id or inherited["quality_generation"] != proof["quality_generation"]:
                raise KernelError("CURRENT_QUOTE_RECOVERY_INPUT_DRIFT", "Retain the original candidate and independent semantic rejection")
            feedback["independent_negative_assessments"] = inherited["negative_assessments"]
            feedback["semantic_rejection_hash"] = inherited["source_output_hash"]
            feedback["semantic_support"] = "REQUIRES_NEW_INDEPENDENT_REVIEW"
        return feedback


def failed_quote_feedback(raw, candidate, *, target, evidence, continuation=False):
    fields = {}

    def walk(value, path, field):
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key in {"quote", "evidence_quote"}
                    and isinstance(child, str)
                    and child not in candidate
                ):
                    fields.setdefault(field, []).append(
                        {
                            "path": path + "." + key,
                            "provider_quote": child,
                            "literal_check": "FAILED",
                        }
                    )
                walk(child, path + "." + key, field)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path + f"[{index}]", field)

    for field, value in raw.items():
        walk(value, "$." + field, field)
    return {
        "contract_version": "known-settled-quote-repair.v1",
        **evidence,
        "target_asset_version_id": target,
        **({"continuation_contract": CONTRACT} if continuation else {}),
        "full_rejected_output_hash": snapshot_hash(raw),
        "failed_quotes_by_field": fields,
        "semantic_support": "NOT_RUN",
        "instruction": "Extract all Canon fields from the exact current candidate. Quotes must be literal substrings without paraphrase. Full rejected output remains in its original durable receipt. No previous failure is a PASS; independent full support remains required.",
    }


def known_quote_retry(database_url, *, operation_id, attempt_id):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        cursor.execute(
            """SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s
            AND definition_name='chapter.canon.extract' AND definition_version IN ('3.9.29','3.9.30')
            AND definition_snapshot #>> '{policy,known_quote_repair}'='known-settled-quote-repair.v1' """,
            [operation_id],
        )
        row = cursor.fetchone()
        if not row:
            return False
        if ((row[0].get("command_payload") or {}).get("preparation_report") or {}).get(
            "retained_graph_continuation", {}
        ).get("retained_result", {}).get(
            "contract_version"
        ) == "chapter-current-semantic-repair.v1":
            return False
        cursor.execute(
            """SELECT e.request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect e
            JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.operation_id=%s
            AND e.request_payload #>> '{_production_execution,attempt_id}'=%s AND e.status='SUCCEEDED'
            AND r.status='SETTLED' AND r.accounting_basis='ACCOUNT_ENTITLEMENT' AND e.provider='codex-cli' """,
            [operation_id, attempt_id],
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            return False
        template = verify_template_provenance(cursor, rows[0][0])
        return bool(
            template
            and template["version"] == "creative-execution-template.v10"
            and template["mode"] == "CREATIVE_VALIDATION"
            and not template["require_literary_qualification"]
        )


def retry_feedback(request):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    with AuthorityUnitOfWork(request.database_url) as uow:
        cursor = uow.cursor
        cursor.execute(
            """SELECT e.external_effect_id,e.request_hash,r.payload->'evidence' FROM authority_attempt a
            JOIN authority_external_effect e ON e.operation_id=a.operation_id AND e.request_payload #>> '{_production_execution,attempt_id}'=a.attempt_id
            JOIN authority_budget_reservation b USING(external_effect_id) JOIN authority_external_effect_dispatch d USING(external_effect_id)
            JOIN authority_external_receipt r USING(dispatch_id) WHERE a.operation_id=%s AND a.attempt_id<>%s
            AND a.status='FAILED_RETRYABLE' AND a.result->>'error_code'='CANON_QUOTE_LOCALIZATION_INVALID'
            AND e.status='SUCCEEDED' AND b.status='SETTLED' AND b.accounting_basis='ACCOUNT_ENTITLEMENT'
            ORDER BY a.attempt_number DESC,r.received_at DESC LIMIT 1""",
            [request.operation_id, request.attempt_id],
        )
        row = cursor.fetchone()
        if not row:
            return None
        result = ModelProviderResult.from_evidence(row[2])
        target = request.require_input("best_draft_candidate")
        return failed_quote_feedback(
            result.output,
            target.content["text"],
            target=target.asset_version_id,
            evidence={"source_effect_id": row[0], "source_request_hash": row[1]},
            continuation=(
                (request.command.get("preparation_report") or {}).get(
                    "retained_graph_continuation"
                )
                or {}
            )
            .get("retained_result", {})
            .get("contract_version")
            == CONTRACT,
        )
