from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.versioned_policy_repository import VersionedPolicyRepository, policy_hash


OWNER = "CREATIVE_EXPERIMENT_BUDGET"
PHASES = ("SOURCE", "CREATION", "REPAIR")
ALLOCATIONS = dict(zip(PHASES, ("source_allocation", "creation_allocation", "repair_allocation"), strict=True))


def creative_budget_definitions(*, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    return owned_policy_definition(owner=OWNER, content={}, application_build_id=application_build_id, commit_sha=commit_sha)


def configure_creative_budget(*, policy: dict[str, Any], **arguments: Any) -> dict[str, Any]:
    from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
    return configure_owned_policy(owner=OWNER, content=policy, **arguments)


def _contract():
    from novel_forge.modules.command_kernel import creative_budget_contract
    return creative_budget_contract


def _lock(cursor: Any, experiment_id: str) -> None:
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [f"creative-experiment-budget:{experiment_id}"])


def _selected(cursor: Any) -> list[dict[str, Any]]:
    cursor.execute("""SELECT v.project_id,v.content,v.content_hash FROM authority_runtime_policy_selection s
        JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
        WHERE s.owner=%s ORDER BY v.project_id""", [OWNER])
    result = []
    for project_id, content, digest in cursor.fetchall():
        if policy_hash(content) != digest:
            raise KernelError("RUNTIME_POLICY_HASH_MISMATCH", "experiment budget policy integrity failed")
        _contract().validate_policy(content)
        result.append({"project_id": project_id, "policy": content, "policy_hash": digest})
    return result


def _policy_for(cursor: Any, project_id: str, *, required: bool = False) -> dict[str, Any] | None:
    policies = _selected(cursor)
    own = next((row for row in policies if row["project_id"] == project_id), None)
    if own is not None:
        return own
    if required or any(project_id in {a["project_id"] for a in row["policy"]["comparison_budget"]["arms"]} for row in policies):
        raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_REQUIRED", "this experiment participant has no native phase authorization")
    return None


def _arm(plan: dict[str, Any], project_id: str) -> dict[str, Any]:
    return next(a for a in plan["arms"] if a["project_id"] == project_id)


def validate_selection_in_uow(uow: AuthorityUnitOfWork, *, project_id: str, content: dict[str, Any]) -> None:
    _contract().validate_policy(content)
    if content["authorization"]["project_id"] != project_id:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "authorization belongs to another project")
    plan = content["comparison_budget"]
    _lock(uow.cursor, "configuration")
    _lock(uow.cursor, plan["experiment_id"])
    projects = {a["project_id"] for a in plan["arms"]}
    for selected in _selected(uow.cursor):
        prior = selected["policy"]["comparison_budget"]
        overlap = projects & {a["project_id"] for a in prior["arms"]}
        if (overlap or prior["experiment_id"] == plan["experiment_id"]) and prior != plan:
            raise KernelError("CREATIVE_BUDGET_PLAN_IMMUTABLE", "participants and allocations cannot be reassigned by a new grant")
    usage = _usage(uow.cursor, plan, project_id)
    _check_limits(content, usage, phase=None, tokens=0, calls=0)


def _effect_identity(cursor: Any, effect_id: str, project_id: str) -> dict[str, Any]:
    cursor.execute("""SELECT o.definition_name,e.capability,e.request_payload,o.command_payload,
        COALESCE((SELECT a.attempt_number FROM authority_attempt a
            WHERE a.operation_id=o.operation_id AND a.attempt_id=COALESCE(
                e.request_payload #>> '{_production_execution,attempt_id}',
                (SELECT s.attempt_id FROM authority_attempt_capability_pack_snapshot s
                 WHERE s.snapshot_id=e.request_payload #>> '{_production_execution,capability_runtime,snapshot_id}'))),
            CASE WHEN NOT EXISTS(SELECT 1 FROM authority_attempt a WHERE a.operation_id=o.operation_id) THEN 1 END),e.request_hash
        FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
        WHERE e.external_effect_id=%s AND e.project_id=%s AND o.project_id=%s""", [effect_id, project_id, project_id])
    row = cursor.fetchone()
    if row is None:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "Provider effect has no owned operation")
    return dict(zip(("operation_name", "capability", "request_payload", "command_payload", "attempt_no", "request_hash"), row, strict=True))


def _business_scope(cursor: Any, identity: dict[str, Any], *, project_id: str, generation: int = 1) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.creative_budget_scope import classify_business_scope
    if identity["operation_name"] == "story_design.semantic_evaluate":
        request = identity["request_payload"]
        target = (request.get("input") or {}).get("evaluation_target") or {}
        metadata = request.get("_production_execution") or {}
        command = identity["command_payload"]
        command = command.get("payload", command)
        identities = {
            "generation_operation_id": target.get("generation_operation_id"),
            "candidate_asset_version_id": target.get("candidate_asset_version_id"),
            "candidate_content_hash": target.get("candidate_content_hash"),
        }
        if any(not isinstance(value, str) or not value for value in identities.values()) or any(command.get(key) != value for key, value in identities.items()):
            raise KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "semantic review target differs from the admitted exact generation/candidate")
        for key, expected in (("generation_operation_id", identities["generation_operation_id"]), ("target_asset_version_id", identities["candidate_asset_version_id"]), ("target_content_hash", identities["candidate_content_hash"])):
            if metadata.get(key) != expected:
                raise KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "semantic review Provider metadata differs from its exact target")
        cursor.execute("""SELECT operation.definition_name,operation.command_payload,version.content_hash
            FROM authority_operation operation
            JOIN authority_operation_output_asset output ON output.operation_id=operation.operation_id
            JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id
            WHERE operation.project_id=%s AND operation.operation_id=%s AND output.asset_version_id=%s""",
            [project_id, identities["generation_operation_id"], identities["candidate_asset_version_id"]])
        rows = cursor.fetchall()
        if len(rows) != 1 or rows[0][2] != identities["candidate_content_hash"]:
            raise KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "semantic review has no exact owned generation output")
        original = rows[0][1]
        original_payload = original.get("payload", original)
        original_books = {value.get("book_id") for value in (original, original_payload) if value.get("book_id")}
        if original_books != {command.get("book_id")}:
            raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "semantic review origin belongs to another Book")
        identity = {**identity, "evaluation_origin": {
            "definition_name": rows[0][0], "command_payload": original,
            "source_ref": identities,
        }}
    return classify_business_scope(identity, dispatch_generation=generation)


def _phase(identity: dict[str, Any]) -> str:
    try:
        return _contract().classify_phase(identity["operation_name"], identity["capability"], identity["request_payload"], identity["attempt_no"])
    except ValueError as exc:
        raise KernelError("CREATIVE_BUDGET_PHASE_UNKNOWN", str(exc)) from exc


def _empty_usage() -> dict[str, int]:
    return {key: 0 for key in ("calls_used_or_reserved", "conservative_tokens", "recorded_actual_tokens", "unmeasured_reserved_tokens")}


def _usage(cursor: Any, plan: dict[str, Any], project_id: str, *, exclude_reservation: str = "") -> dict[str, Any]:
    from novel_forge.modules.command_kernel.budget_runtime import provider_usage_accounted_sql
    projects = [a["project_id"] for a in plan["arms"]]
    cursor.execute(f"""SELECT reservation_id,external_effect_id,project_id,status,
        estimated_tokens,actual_tokens,evidence,created_at FROM authority_budget_reservation
        WHERE project_id=ANY(%s) AND reservation_id<>%s AND {provider_usage_accounted_sql()}
        ORDER BY created_at,reservation_id""", [projects, exclude_reservation])
    rows = cursor.fetchall()
    usage = {"contract_hash": _contract().contract_hash(plan), "project_id": project_id,
        "book_id": _arm(plan, project_id)["book_id"], "phases": {p: _empty_usage() for p in _contract().budget_phases(plan)},
        "project_total": _empty_usage(), "shared_total": _empty_usage(), "reservation_ids": [],
        "evidence_class": "POSTGRESQL_BUDGET_LEDGER", "creation_opportunity": None}
    seen: set[str] = set()
    for reservation_id, effect_id, owner_project, status, estimate, actual, evidence, _created in rows:
        proof = dict(evidence or {}).get("creative_experiment")
        dispatch_subject = proof["subject_id"] if proof else effect_id
        if dispatch_subject in seen:
            raise KernelError("CREATIVE_BUDGET_LEDGER_AMBIGUOUS", "multiple accounted reservations bind one Provider dispatch")
        seen.add(dispatch_subject)
        if proof:
            if proof["contract_hash"] != usage["contract_hash"]:
                raise KernelError("CREATIVE_BUDGET_PLAN_IMMUTABLE", "historical ledger uses another allocation plan")
            phase = proof["phase"]
            if plan["contract_version"] == _contract().SINGLE_BOOK_VERSION:
                scope = proof.get("business_scope")
                if not isinstance(scope, dict) or scope.get("phase") != phase:
                    raise KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "historical reservation lost its frozen business classification")
        else:
            identity = _effect_identity(cursor, effect_id, owner_project)
            phase = _business_scope(cursor, identity, project_id=owner_project)["phase"] if plan["contract_version"] == _contract().SINGLE_BOOK_VERSION else _phase(identity)
        actual = max(int(actual or 0), int(dict(evidence or {}).get("actual_tokens") or 0))
        counted = actual if status == "SETTLED" else max(actual, int(estimate))
        amounts = {"calls_used_or_reserved": 1, "conservative_tokens": counted,
            "recorded_actual_tokens": actual,
            "unmeasured_reserved_tokens": max(0, counted - actual)}
        totals = [usage["shared_total"]]
        if owner_project == project_id:
            totals += [usage["project_total"], usage["phases"][phase]]
            usage["reservation_ids"].append(reservation_id)
            if phase == "CREATION" and usage["creation_opportunity"] is None:
                usage["creation_opportunity"] = {
                    "first_reservation_id": reservation_id,
                    "policy_hash": proof.get("policy_hash", "") if proof else "",
                    "authorized_cumulative_caps": proof.get("authorization", {}).get("authorized_cumulative_caps", {}) if proof else {},
                }
        for total in totals:
            for key, value in amounts.items():
                total[key] += value
    return usage


def _check_limits(policy: dict[str, Any], usage: dict[str, Any], *, phase: str | None, tokens: int, calls: int) -> None:
    plan = policy["comparison_budget"]
    arm = _arm(plan, usage["project_id"])
    pairs = [("project_total", usage["project_total"], arm["project_total"], calls, tokens),
             ("shared_total", usage["shared_total"], plan["shared_total"], calls, tokens)]
    for candidate in _contract().budget_phases(plan):
        addition = (calls, tokens) if candidate == phase else (0, 0)
        pairs.append((candidate, usage["phases"][candidate], policy["authorization"]["authorized_cumulative_caps"][candidate], *addition))
    for name, used, cap, extra_calls, extra_tokens in pairs:
        if used["calls_used_or_reserved"] + extra_calls > cap["calls"] or used["conservative_tokens"] + extra_tokens > cap["tokens"]:
            raise KernelError("CREATIVE_BUDGET_EXHAUSTED", f"cumulative {name} allocation/authorization does not admit this Provider usage")


def reserve_creative_budget_in_uow(uow: AuthorityUnitOfWork, request: Any) -> dict[str, Any] | None:
    _lock(uow.cursor, "configuration")
    selected = _policy_for(uow.cursor, request.project_id)
    if selected is None:
        return None
    policy = selected["policy"]
    _lock(uow.cursor, policy["comparison_budget"]["experiment_id"])
    selected = _policy_for(uow.cursor, request.project_id, required=True)
    policy = selected["policy"]
    uow.cursor.execute("""SELECT status FROM authority_budget_reservation
        WHERE project_id=%s AND external_effect_id=%s ORDER BY created_at""", [request.project_id, request.external_effect_id])
    previous = [str(row[0]) for row in uow.cursor.fetchall()]
    generation = 0
    subject_id = f"effect:{request.external_effect_id}"
    if previous:
        uow.cursor.execute("""SELECT e.status,d.generation,d.status FROM authority_external_effect e
            LEFT JOIN LATERAL (SELECT generation,status FROM authority_external_effect_dispatch
                WHERE external_effect_id=e.external_effect_id ORDER BY generation DESC LIMIT 1) d ON TRUE
            WHERE e.external_effect_id=%s""", [request.external_effect_id])
        effect_status, last_generation, dispatch_status = uow.cursor.fetchone()
        known_retry = effect_status == "FAILED_RETRYABLE" and dispatch_status == "FAILED_RETRYABLE"
        if any(status not in {"RELEASED", "SETTLED"} for status in previous) or ("SETTLED" in previous and not known_retry):
            raise KernelError("BUDGET_IDEMPOTENCY_CONFLICT", "an active, unknown or successful dispatch cannot obtain another reservation key")
        if last_generation is not None and not known_retry:
            raise KernelError("BUDGET_IDEMPOTENCY_CONFLICT", "the previous dispatch has no retryable terminal receipt")
        generation = int(last_generation or 0) + 1
        subject_id += f":dispatch:{generation}"
    snapshot = VersionedPolicyRepository(uow.cursor, owner=OWNER, project_id=request.project_id).freeze(
        subject_id=subject_id, default=policy, actor_id="command-kernel-budget")
    policy = snapshot["policy"]
    if request.accounting_basis != policy["comparison_budget"]["accounting_basis"] or request.cost_authorization_ref != policy["authorization"]["authorization_ref"]:
        raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_MISMATCH", "Provider route must use this effect's frozen authorization and accounting basis")
    if request.estimated_tokens <= 0:
        raise KernelError("CREATIVE_BUDGET_TOKEN_CEILING_REQUIRED", "experiment dispatch requires a positive observable token reservation")
    identity = _effect_identity(uow.cursor, request.external_effect_id, request.project_id)
    phase = _phase(identity)
    if generation > 1 and phase != "SOURCE":
        phase = "REPAIR"
    business_scope = None
    if policy["comparison_budget"]["contract_version"] == _contract().SINGLE_BOOK_VERSION:
        from novel_forge.modules.command_kernel.creative_budget_scope import require_business_scope
        business_scope = _business_scope(uow.cursor, identity, project_id=request.project_id, generation=max(1, generation))
        require_business_scope(policy, business_scope)
        if request.chapter is not None and business_scope["chapter_number"] != request.chapter:
            raise KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "budget request chapter differs from frozen Provider and Operation scope")
        phase = business_scope["phase"]
    command = dict(identity["command_payload"] or {})
    book_id = (command.get("payload") or {}).get("book_id") or command.get("book_id")
    if phase == "SOURCE":
        from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
        lineage = SourceAuthorityRepository(uow.cursor).catalog_execution_binding(request.project_id, request.operation_id)
        intended = (lineage or {}).get("requested_manifest") or {}
        if intended.get("intended_use") != "ABSTRACT_GENERATION" or intended.get("target_book_id") != policy["authorization"]["book_id"]:
            raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "Source requires the curated consumption lineage for the exact authorized Book and use")
        if business_scope is not None:
            business_scope["scope_sources"].append({"path": "native_curated_consumption", "value": {"intended_use": intended["intended_use"], "target_book_id": intended["target_book_id"]}})
    elif book_id != policy["authorization"]["book_id"]:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "creative Effect must belong to the exact authorized Book")
    usage = _usage(uow.cursor, policy["comparison_budget"], request.project_id)
    _check_limits(policy, usage, phase=phase, tokens=request.estimated_tokens, calls=1)
    return {"owner": OWNER, "policy_version": policy["policy_version"], "policy_hash": snapshot["policy_hash"],
        "contract_hash": _contract().contract_hash(policy["comparison_budget"]), "subject_id": snapshot["subject_id"],
        "authorization": policy["authorization"], "phase": phase,
        **({"business_scope": business_scope} if business_scope is not None else {})}


def check_creative_settlement_in_uow(uow: AuthorityUnitOfWork, row: dict[str, Any], actual_tokens: int) -> None:
    proof = dict(row.get("evidence") or {}).get("creative_experiment")
    if not proof:
        return
    uow.cursor.execute("""SELECT content,content_hash FROM authority_runtime_policy_version
        WHERE owner=%s AND project_id=%s AND policy_version=%s""", [OWNER, row["project_id"], proof["policy_version"]])
    frozen = uow.cursor.fetchone()
    if frozen is None or frozen[1] != proof["policy_hash"] or policy_hash(frozen[0]) != frozen[1]:
        raise KernelError("RUNTIME_POLICY_HASH_MISMATCH", "settlement lost the effect's frozen experiment budget")
    policy = frozen[0]
    _lock(uow.cursor, policy["comparison_budget"]["experiment_id"])
    selected = _policy_for(uow.cursor, row["project_id"], required=True)
    current = selected["policy"]
    if current["comparison_budget"] != policy["comparison_budget"]:
        raise KernelError("CREATIVE_BUDGET_PLAN_IMMUTABLE", "settlement cannot change the frozen allocation plan")
    usage = _usage(uow.cursor, policy["comparison_budget"], row["project_id"], exclude_reservation=row["reservation_id"])
    _check_limits(current, usage, phase=proof["phase"], tokens=actual_tokens, calls=1)


def get_creative_budget(database_url: str, project_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        selected = _policy_for(uow.cursor, project_id, required=True)
        policy = selected["policy"]
        _lock(uow.cursor, policy["comparison_budget"]["experiment_id"])
        selected = _policy_for(uow.cursor, project_id, required=True)
        policy = selected["policy"]
        return {"comparison_budget": policy["comparison_budget"],
            "budget_binding": {"owner": OWNER, "policy_version": policy["policy_version"], "policy_hash": selected["policy_hash"],
                "contract_hash": _contract().contract_hash(policy["comparison_budget"]), "subject_id": f"project:{project_id}",
                "authorization": policy["authorization"]},
            "budget_usage": _usage(uow.cursor, policy["comparison_budget"], project_id)}
