from __future__ import annotations

from typing import Any, Mapping
from datetime import datetime, timezone
from decimal import Decimal

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


def require_provider_campaign_entitlement(cursor: Any, *, project_id: str, grant: Mapping[str, Any]) -> None:
    source_research = (grant["task_type"] == "source.deconstruction.observe"
                       and grant["book_id"] == f"source-corpus:{project_id}")
    # WHY: Corpus research uses its exact Source campaign and project budgets; an existing creative allocation still applies.
    selected = _policy_for(cursor, project_id, required=not source_research)
    if selected is None:
        return
    plan = selected["policy"]["comparison_budget"]
    campaign = grant.get("campaign") or {}
    lanes = [lane for lane in plan.get("entitlements", [])
             if lane["provider"] == "codex-cli" and lane["authorization_ref"] == grant.get("cost_authorization_ref")]
    if (plan["contract_version"] not in _contract().PROVIDER_BUDGET_VERSIONS
        or plan["experiment_id"] != campaign.get("campaign_id")
        or plan.get("manifest_hash") != campaign.get("manifest_hash")
        or _arm(plan, project_id)["book_id"] != grant["book_id"]
        or len(lanes) != 1 or grant["maximum_calls"] > lanes[0]["calls"]
        or grant["maximum_tokens"] > lanes[0]["tokens"]
        or datetime.fromisoformat(grant["expires_at"]) > datetime.fromisoformat(plan["expires_at"])):
        raise KernelError("CREATIVE_BUDGET_ENTITLEMENT_MISMATCH", "benchmark entitlement requires the exact frozen whole-campaign authorization")


def _validate_reallocation(plan: dict[str, Any], previous: dict[str, Any], *, project_id: str) -> None:
    prior = previous["comparison_budget"]
    reference = plan.get("previous_policy") or {}
    if (plan["contract_version"] != _contract().PRODUCTION_BOOK_VERSION
        or prior["contract_version"] not in _contract().SINGLE_BOOK_VERSIONS
        or reference != {"policy_version": previous["policy_version"], "policy_hash": policy_hash(previous),
                         "contract_hash": _contract().contract_hash(prior)}):
        raise KernelError("CREATIVE_BUDGET_PREDECESSOR_MISMATCH", "reallocation must append to the exact current native single-book policy")
    if (plan["experiment_id"] != prior["experiment_id"] or plan["accounting_basis"] != prior["accounting_basis"]
        or plan["shared_total"] != prior["shared_total"]
        or {a["project_id"] for a in plan["arms"]} != {project_id}
        or {a["project_id"] for a in prior["arms"]} != {project_id}):
        raise KernelError("CREATIVE_BUDGET_REALLOCATION_SCOPE_MISMATCH", "reallocation must retain the project, lifetime identity and exact cumulative ceiling")


def _lineage_plans(cursor: Any, plan: dict[str, Any], project_id: str) -> dict[str, dict[str, Any]]:
    result = {}
    current = plan
    while True:
        digest = _contract().contract_hash(current)
        if digest in result:
            raise KernelError("CREATIVE_BUDGET_PREDECESSOR_MISMATCH", "budget predecessor lineage contains a cycle")
        result[digest] = current
        monetary_amendment = current["contract_version"] == _contract().PROVIDER_CAMPAIGN_VERSION and "previous_policy" in current
        renewal = current["contract_version"] == _contract().PROVIDER_RENEWAL_VERSION
        if current["contract_version"] != _contract().PRODUCTION_BOOK_VERSION and not monetary_amendment and not renewal:
            return result
        reference = current["previous_policy"]
        cursor.execute("""SELECT content,content_hash FROM authority_runtime_policy_version
            WHERE owner=%s AND project_id=%s AND policy_version=%s""", [OWNER, project_id, reference["policy_version"]])
        row = cursor.fetchone()
        if row is None or row[1] != reference["policy_hash"] or policy_hash(row[0]) != row[1]:
            raise KernelError("CREATIVE_BUDGET_PREDECESSOR_MISMATCH", "budget predecessor native policy is missing or altered")
        _contract().validate_policy(row[0])
        if renewal:
            from .creative_budget_renewal import validate_predecessor
            validate_predecessor(current, row[0], project_id=project_id)
        elif monetary_amendment:
            _validate_campaign_monetary_amendment(current, row[0], project_id=project_id)
        else:
            _validate_reallocation(current, row[0], project_id=project_id)
        current = row[0]["comparison_budget"]


def _validate_campaign_monetary_amendment(plan: dict[str, Any], previous: dict[str, Any], *, project_id: str) -> None:
    prior = previous["comparison_budget"]
    if (prior["contract_version"] != _contract().PROVIDER_CAMPAIGN_VERSION
        or plan.get("previous_policy") != {
            "policy_version": previous["policy_version"], "policy_hash": policy_hash(previous),
            "contract_hash": _contract().contract_hash(prior)}):
        raise KernelError("CREATIVE_BUDGET_PREDECESSOR_MISMATCH", "campaign amendment requires the exact selected predecessor")

    def immutable(value):
        if isinstance(value, dict):
            return {key: immutable(item) for key, item in value.items() if key not in {"priced_usd", "previous_policy"}}
        if isinstance(value, list):
            return [immutable(item) for item in value]
        return value

    if immutable(plan) != immutable(prior) or {arm["project_id"] for arm in plan["arms"]} != {project_id}:
        raise KernelError("CREATIVE_BUDGET_AMENDMENT_SCOPE_MISMATCH", "monetary amendment cannot change participants, manifest, calls, tokens, entitlement, phases or expiry")
    fields = ("project_total", *_contract().allocation_fields(plan).values())
    if (Decimal(plan["shared_total"]["priced_usd"]) <= Decimal(prior["shared_total"]["priced_usd"])
        or any(Decimal(plan["arms"][0][field]["priced_usd"]) < Decimal(prior["arms"][0][field]["priced_usd"]) for field in fields)):
        raise KernelError("CREATIVE_BUDGET_AMENDMENT_SCOPE_MISMATCH", "explicit monetary amendment only adds authorized money without reallocating earlier allowances")


def validate_selection_in_uow(uow: AuthorityUnitOfWork, *, project_id: str, content: dict[str, Any]) -> None:
    _contract().validate_policy(content)
    if content["authorization"]["project_id"] != project_id:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "authorization belongs to another project")
    plan = content["comparison_budget"]
    _lock(uow.cursor, "configuration")
    _lock(uow.cursor, plan["experiment_id"])
    projects = {a["project_id"] for a in plan["arms"]}
    selections = _selected(uow.cursor)
    own = next((row for row in selections if row["project_id"] == project_id), None)
    monetary_amendment = plan["contract_version"] == _contract().PROVIDER_CAMPAIGN_VERSION and "previous_policy" in plan
    renewal = plan["contract_version"] == _contract().PROVIDER_RENEWAL_VERSION
    if renewal and own is not None and own["policy"]["comparison_budget"] == plan and content["authorization"] != own["policy"]["authorization"]:
        raise KernelError("CREATIVE_BUDGET_RENEWAL_INVALID", "A changed renewal authorization requires a new exact predecessor")
    if renewal and (own is None or own["policy"]["comparison_budget"] != plan):
        if own is None:
            raise KernelError("CREATIVE_BUDGET_PREDECESSOR_MISMATCH", "Renewal requires the selected native predecessor")
        from .creative_budget_renewal import validate_predecessor, validate_selection
        validate_predecessor(plan, own["policy"], project_id=project_id)
        prior_usage = _usage(uow.cursor, own["policy"]["comparison_budget"], project_id)
        validate_selection(plan, own["policy"], content, prior_usage)
    if monetary_amendment and (own is None or own["policy"]["comparison_budget"] != plan):
        if own is None:
            raise KernelError("CREATIVE_BUDGET_PREDECESSOR_MISMATCH", "campaign amendment requires an existing selected native policy")
        _validate_campaign_monetary_amendment(plan, own["policy"], project_id=project_id)
        if any(content["authorization"][key] == own["policy"]["authorization"][key] for key in ("authorization_ref", "evidence_hash")):
            raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_MISMATCH", "campaign monetary amendment requires new explicit authorization and evidence")
        if content["authorization"]["business_scope"] != own["policy"]["authorization"]["business_scope"]:
            raise KernelError("CREATIVE_BUDGET_AMENDMENT_SCOPE_MISMATCH", "monetary amendment cannot expand business permissions")
    if plan["contract_version"] == _contract().PRODUCTION_BOOK_VERSION and (own is None or own["policy"]["comparison_budget"] != plan):
        if own is None:
            raise KernelError("CREATIVE_BUDGET_PREDECESSOR_MISMATCH", "production reallocation requires an existing selected native policy")
        _validate_reallocation(plan, own["policy"], project_id=project_id)
        if content["authorization"]["authorization_ref"] == own["policy"]["authorization"]["authorization_ref"]:
            raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_MISMATCH", "reallocation requires a new explicit authorization reference")
    for selected in selections:
        prior = selected["policy"]["comparison_budget"]
        overlap = projects & {a["project_id"] for a in prior["arms"]}
        if (overlap or prior["experiment_id"] == plan["experiment_id"]) and prior != plan:
            if selected is not own or not (plan["contract_version"] == _contract().PRODUCTION_BOOK_VERSION or monetary_amendment or renewal):
                raise KernelError("CREATIVE_BUDGET_PLAN_IMMUTABLE", "participants and allocations require an exact native reallocation predecessor")
    usage = _usage(uow.cursor, plan, project_id)
    _check_limits(content, usage, phase=None, tokens=0, calls=0)


def _effect_identity(cursor: Any, effect_id: str, project_id: str) -> dict[str, Any]:
    cursor.execute("""SELECT o.definition_name,e.capability,e.request_payload,o.command_payload,
        COALESCE((SELECT a.attempt_number FROM authority_attempt a
            WHERE a.operation_id=o.operation_id AND a.attempt_id=COALESCE(
                e.request_payload #>> '{_production_execution,attempt_id}',
                (SELECT s.attempt_id FROM authority_attempt_capability_pack_snapshot s
                 WHERE s.snapshot_id=e.request_payload #>> '{_production_execution,capability_runtime,snapshot_id}'))),
            CASE WHEN NOT EXISTS(SELECT 1 FROM authority_attempt a WHERE a.operation_id=o.operation_id) THEN 1 END),e.request_hash,o.operation_id
        FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
        WHERE e.external_effect_id=%s AND e.project_id=%s AND o.project_id=%s""", [effect_id, project_id, project_id])
    row = cursor.fetchone()
    if row is None:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "Provider effect has no owned operation")
    return dict(zip(("operation_name", "capability", "request_payload", "command_payload", "attempt_no", "request_hash", "operation_id"), row, strict=True))


def _business_scope(cursor: Any, identity: dict[str, Any], *, project_id: str, generation: int = 1,
                    plan: dict[str, Any] | None = None) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.creative_budget_scope import classify_business_scope
    if identity["operation_name"] == "longform.prose_review":
        from novel_forge.modules.book_followup_authority.prose_budget import frozen_prose_budget_scope

        identity = {**identity, "native_prose_scope": frozen_prose_budget_scope(cursor, identity, project_id=project_id)}
    if identity["operation_name"] in {"screenplay_generate", "screenplay_review", "screenplay_revision"}:
        from novel_forge.modules.book_followup_authority.screenplay_budget import frozen_screenplay_budget_scope
        identity = {**identity, "native_screenplay_scope": frozen_screenplay_budget_scope(cursor, identity, project_id=project_id)}
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
    return classify_business_scope(identity, dispatch_generation=generation,
                                   chapter_ranges=_arm(plan, project_id)["chapter_ranges"] if plan is not None else None)


def _phase(identity: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    if plan is not None and plan["contract_version"] == _contract().PAIRED_SAMPLES_VERSION and identity["operation_name"] == "provider.qualification.d0":
        config = identity["command_payload"].get("config") or {}
        if (identity["request_payload"].get("stage") != "d0_qualification"
            or not config.get("capability") or config["capability"] != identity["capability"]):
            raise KernelError("CREATIVE_BUDGET_PHASE_UNKNOWN", "Qualification must bind its native admitted probe capability")
        return "QUALIFICATION"
    try:
        return _contract().classify_phase(identity["operation_name"], identity["capability"], identity["request_payload"], identity["attempt_no"])
    except ValueError as exc:
        raise KernelError("CREATIVE_BUDGET_PHASE_UNKNOWN", str(exc)) from exc


def _campaign_scope(cursor: Any, identity: dict[str, Any], *, plan: dict[str, Any], project_id: str, generation: int) -> dict[str, Any]:
    from .routing_bootstrap import load_bootstrap_authorization

    snapshot = load_bootstrap_authorization(cursor, project_id=project_id,
        operation_id=identity["operation_id"], check_expiry=False)
    command = identity["command_payload"].get("payload", identity["command_payload"])
    source_operation_id = identity["operation_id"]
    if command.get("chapter_sampling") or command.get("world_sampling") or command.get("prose_sampling") or command.get("screenplay_sampling"):
        if snapshot is None:
            raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "sample budget classification requires its native bootstrap authorization")
        source_operation_id = (command.get("chapter_sampling") or command.get("world_sampling") or command.get("prose_sampling") or command["screenplay_sampling"])["source_operation_id"]
        cursor.execute("SELECT definition_name,command_payload FROM authority_operation WHERE project_id=%s AND operation_id=%s",
                       [project_id, source_operation_id])
        origin = cursor.fetchone()
        if not origin:
            raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "sample has no original native task")
        identity = {**identity, "operation_name": origin[0], "command_payload": origin[1], "source_operation_id": source_operation_id}
        if command.get("screenplay_sampling"):
            identity["source_definition_name"] = origin[0]
            identity["operation_name"] = command["generator_operation_name"]
        if (command.get("chapter_sampling") or {}).get("generation_sample") is not None:
            from .routing_bootstrap import CHAPTER_REFERENCE_TASKS

            stage = command["generator_operation_name"]
            identity["operation_name"] = next(name for name, task in CHAPTER_REFERENCE_TASKS.items() if task == stage)
    elif command.get("source_sampling"):
        source_operation_id = command["source_sampling"]["source_operation_id"]
    scope = _business_scope(cursor, identity, project_id=project_id, generation=generation, plan=plan)
    scope["source_operation_id"] = source_operation_id
    if snapshot:
        grant = snapshot["authorization"]
        campaign = grant.get("campaign")
        if not campaign or campaign["campaign_id"] != plan["experiment_id"] or campaign["manifest_hash"] != plan["manifest_hash"]:
            raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "sampling grant differs from the frozen campaign")
        scope["phase"] = "REFERENCE" if grant["purpose"] == "REFERENCE_EVALUATION" else {
            "DEVELOPMENT": "SCREENING", "CALIBRATION": "CALIBRATION", "HOLDOUT": "HOLDOUT",
        }[campaign["partition"]]
        scope["campaign_sample"] = dict(campaign)
    return scope


def _empty_usage() -> dict[str, int]:
    return {key: 0 for key in ("calls_used_or_reserved", "conservative_tokens", "recorded_actual_tokens", "unmeasured_reserved_tokens")}


def _usage(cursor: Any, plan: dict[str, Any], project_id: str, *, exclude_reservation: str = "") -> dict[str, Any]:
    from novel_forge.modules.command_kernel.budget_runtime import provider_usage_accounted_sql
    projects = [a["project_id"] for a in plan["arms"]]
    mixed = plan["contract_version"] in _contract().PROVIDER_BUDGET_VERSIONS
    lineage = _lineage_plans(cursor, plan, project_id)
    cursor.execute(f"""SELECT reservation_id,external_effect_id,project_id,status,
        estimated_tokens,actual_tokens,evidence,created_at,currency,provider,reserved_amount,settled_amount FROM authority_budget_reservation
        WHERE project_id=ANY(%s) AND reservation_id<>%s AND {provider_usage_accounted_sql()}
        ORDER BY created_at,reservation_id""", [projects, exclude_reservation])
    rows = cursor.fetchall()
    usage = {"contract_hash": _contract().contract_hash(plan), "project_id": project_id,
        "book_id": _arm(plan, project_id)["book_id"], "phases": {p: _empty_usage() for p in _contract().budget_phases(plan)},
        "project_total": _empty_usage(), "shared_total": _empty_usage(), "reservation_ids": [],
        "evidence_class": "POSTGRESQL_BUDGET_LEDGER", "creation_opportunity": None}
    if mixed:
        usage.update(entitlements=[], entitlement_usd=None, invoice_status="NOT_VERIFIED")
        for total in [usage["project_total"], usage["shared_total"], *usage["phases"].values()]:
            total.update(priced_usd=Decimal(0), unpriced_calls=0)
    renewal = plan["contract_version"] == _contract().PROVIDER_RENEWAL_VERSION
    if renewal:
        usage["renewal_usage"] = {**_empty_usage(), "priced_usd": Decimal(0), "unpriced_calls": 0}
        carried = set(plan["renewal"]["carry_forward"]["reservation_ids"])
    seen: set[str] = set()
    for reservation_id, effect_id, owner_project, status, estimate, actual, evidence, _created, currency, provider, reserved_amount, settled_amount in rows:
        proof = dict(evidence or {}).get("creative_experiment")
        dispatch_subject = proof["subject_id"] if proof else effect_id
        if dispatch_subject in seen:
            raise KernelError("CREATIVE_BUDGET_LEDGER_AMBIGUOUS", "multiple accounted reservations bind one Provider dispatch")
        seen.add(dispatch_subject)
        if proof:
            if proof["contract_hash"] not in lineage:
                raise KernelError("CREATIVE_BUDGET_PLAN_IMMUTABLE", "historical ledger uses another allocation plan")
            phase = proof["phase"]
            if mixed or plan["contract_version"] in _contract().SINGLE_BOOK_VERSIONS:
                scope = proof.get("business_scope")
                if not isinstance(scope, dict) or scope.get("phase") != phase:
                    raise KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "historical reservation lost its frozen business classification")
        else:
            identity = _effect_identity(cursor, effect_id, owner_project)
            legacy_plan = next(reversed(lineage.values()))
            if mixed:
                phase = _campaign_scope(cursor, identity, plan=plan, project_id=owner_project, generation=1)["phase"]
            else:
                phase = _business_scope(cursor, identity, project_id=owner_project, plan=legacy_plan)["phase"] if plan["contract_version"] in _contract().SINGLE_BOOK_VERSIONS else _phase(identity, plan)
        if phase not in usage["phases"]:
            raise KernelError("CREATIVE_BUDGET_PHASE_UNKNOWN", "historical reservation has an unsupported frozen phase")
        actual = max(int(actual or 0), int(dict(evidence or {}).get("actual_tokens") or 0))
        counted = actual if status == "SETTLED" else max(actual, int(estimate))
        amounts = {"calls_used_or_reserved": 1, "conservative_tokens": counted,
            "recorded_actual_tokens": actual,
            "unmeasured_reserved_tokens": max(0, counted - actual)}
        if mixed:
            evidence = dict(evidence or {})
            basis = evidence.get("accounting_basis", "PRICED")
            if basis == "PRICED":
                money = settled_amount if status == "SETTLED" else reserved_amount
                if currency != "USD" or money is None:
                    raise KernelError("CREATIVE_BUDGET_COST_UNKNOWN", "priced campaign usage requires comparable USD evidence")
                money = max(Decimal(money), Decimal(evidence.get("actual_amount") or 0))
                amounts.update(priced_usd=money, unpriced_calls=0)
            elif basis == "ACCOUNT_ENTITLEMENT":
                if currency != "UNKNOWN" or any(value is not None for value in (reserved_amount, settled_amount)):
                    raise KernelError("CREATIVE_BUDGET_COST_UNKNOWN", "entitlement USD remains unknown")
                amounts.update(priced_usd=Decimal(0), unpriced_calls=1)
                key = (provider, evidence.get("cost_authorization_ref", ""))
                lane = next((lane for lane in usage["entitlements"] if (lane["provider"], lane["authorization_ref"]) == key), None)
                if lane is None:
                    lane = {"provider": key[0], "authorization_ref": key[1], "calls": 0, "tokens": 0}
                    usage["entitlements"].append(lane)
                lane["calls"] += 1
                lane["tokens"] += counted
            else:
                raise KernelError("CREATIVE_BUDGET_COST_UNKNOWN", "campaign usage has an unknown accounting basis")
        totals = [usage["shared_total"]]
        if renewal and reservation_id not in carried:
            totals.append(usage["renewal_usage"])
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
    if mixed:
        for total in [usage["project_total"], usage["shared_total"], *usage["phases"].values()]:
            total["priced_usd"] = str(total["priced_usd"])
    if renewal:
        usage["renewal_usage"]["priced_usd"] = str(usage["renewal_usage"]["priced_usd"])
    return usage


def _check_limits(policy: dict[str, Any], usage: dict[str, Any], *, phase: str | None, tokens: int, calls: int,
                  amount: Decimal | None = None, entitlement: tuple[str, str] | None = None, renewal_addition: bool = True) -> None:
    plan = policy["comparison_budget"]
    arm = _arm(plan, usage["project_id"])
    if plan["contract_version"] == _contract().PROVIDER_RENEWAL_VERSION:
        from .creative_budget_renewal import check_window
        if renewal_addition and calls and phase not in {"DESIGN", "PRODUCTION", "REPAIR"}:
            raise KernelError("CREATIVE_BUDGET_RENEWAL_SCOPE_DENIED", "Production renewal cannot dispatch diagnostics or Source work")
        check_window(plan, usage, calls=calls if renewal_addition else 0, tokens=tokens if renewal_addition else 0,
                     amount=amount if renewal_addition else None)
    pairs = [("project_total", usage["project_total"], arm["project_total"], calls, tokens),
             ("shared_total", usage["shared_total"], plan["shared_total"], calls, tokens)]
    for candidate in _contract().budget_phases(plan):
        addition = (calls, tokens) if candidate == phase else (0, 0)
        pairs.append((candidate, usage["phases"][candidate], policy["authorization"]["authorized_cumulative_caps"][candidate], *addition))
    for name, used, cap, extra_calls, extra_tokens in pairs:
        if used["calls_used_or_reserved"] + extra_calls > cap["calls"] or used["conservative_tokens"] + extra_tokens > cap["tokens"]:
            raise KernelError("CREATIVE_BUDGET_EXHAUSTED", f"cumulative {name} allocation/authorization does not admit this Provider usage")
        if plan["contract_version"] in _contract().PROVIDER_BUDGET_VERSIONS and (
            Decimal(used["priced_usd"]) + ((amount or Decimal(0)) if extra_calls else Decimal(0)) > Decimal(cap["priced_usd"])
        ):
            raise KernelError("CREATIVE_BUDGET_USD_EXHAUSTED", f"cumulative {name} priced USD allowance is exhausted")
    if plan["contract_version"] in _contract().PROVIDER_BUDGET_VERSIONS:
        lanes = {(lane["provider"], lane["authorization_ref"]): lane for lane in plan["entitlements"]}
        used_lanes = {(lane["provider"], lane["authorization_ref"]): lane for lane in usage["entitlements"]}
        for key in {*used_lanes, *((entitlement,) if entitlement is not None else ())}:
            cap = lanes.get(key)
            used = used_lanes.get(key, {"calls": 0, "tokens": 0})
            if cap is None or any(used[field] + (extra if key == entitlement else 0) > cap[field]
                                  for field, extra in (("calls", calls), ("tokens", tokens))):
                raise KernelError("CREATIVE_BUDGET_EXHAUSTED", "the exact campaign entitlement lane is absent or exhausted")


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
    current_policy = selected["policy"]
    mixed = policy["comparison_budget"]["contract_version"] in _contract().PROVIDER_BUDGET_VERSIONS
    if (current_policy["comparison_budget"]["contract_version"] == _contract().PRODUCTION_BOOK_VERSION
        and current_policy["comparison_budget"] != policy["comparison_budget"]):
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "an earlier frozen budget cannot dispatch after its Book allocation was superseded")
    if mixed:
        if datetime.now(timezone.utc) >= datetime.fromisoformat(policy["comparison_budget"]["expires_at"]):
            raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_EXPIRED", "campaign authorization no longer permits new inference")
        if (request.accounting_basis == "PRICED" and (request.currency != "USD" or request.estimated_amount is None)
            or request.accounting_basis == "ACCOUNT_ENTITLEMENT" and (request.currency != "UNKNOWN" or request.estimated_amount is not None)
            or request.accounting_basis not in {"PRICED", "ACCOUNT_ENTITLEMENT"}):
            raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_MISMATCH", "campaign accounting requires priced USD or explicit unknown-cost entitlement")
    elif request.accounting_basis != policy["comparison_budget"]["accounting_basis"] or request.cost_authorization_ref != policy["authorization"]["authorization_ref"]:
        raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_MISMATCH", "Provider route must use this effect's frozen authorization and accounting basis")
    if request.estimated_tokens <= 0:
        raise KernelError("CREATIVE_BUDGET_TOKEN_CEILING_REQUIRED", "experiment dispatch requires a positive observable token reservation")
    identity = _effect_identity(uow.cursor, request.external_effect_id, request.project_id)
    phase = "" if mixed else _phase(identity, policy["comparison_budget"])
    if generation > 1 and phase not in {"SOURCE", "QUALIFICATION"}:
        phase = "REPAIR"
    business_scope = None
    if mixed or policy["comparison_budget"]["contract_version"] in _contract().SINGLE_BOOK_VERSIONS:
        from novel_forge.modules.command_kernel.creative_budget_scope import require_business_scope
        business_scope = (_campaign_scope(uow.cursor, identity, project_id=request.project_id, generation=max(1, generation), plan=policy["comparison_budget"])
                          if mixed else _business_scope(uow.cursor, identity, project_id=request.project_id, generation=max(1, generation), plan=policy["comparison_budget"]))
        require_business_scope(policy, business_scope)
        require_business_scope(current_policy, business_scope)
        if request.chapter is not None and business_scope["chapter_number"] != request.chapter:
            raise KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", "budget request chapter differs from frozen Provider and Operation scope")
        phase = business_scope["phase"]
    command = dict(identity["command_payload"] or {})
    book_id = (command.get("payload") or {}).get("book_id") or command.get("book_id")
    if phase == "SOURCE" or business_scope and business_scope["origin_phase"] == "SOURCE":
        from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
        lineage = SourceAuthorityRepository(uow.cursor).catalog_execution_binding(request.project_id,
            business_scope.get("source_operation_id", request.operation_id) if business_scope else request.operation_id)
        intended = (lineage or {}).get("requested_manifest") or {}
        if intended.get("intended_use") != "ABSTRACT_GENERATION" or intended.get("target_book_id") != policy["authorization"]["book_id"]:
            raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "Source requires the curated consumption lineage for the exact authorized Book and use")
        if business_scope is not None:
            business_scope["scope_sources"].append({"path": "native_curated_consumption", "value": {"intended_use": intended["intended_use"], "target_book_id": intended["target_book_id"]}})
    elif phase != "QUALIFICATION" and book_id != policy["authorization"]["book_id"]:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "creative Effect must belong to the exact authorized Book")
    usage = _usage(uow.cursor, current_policy["comparison_budget"], request.project_id)
    _check_limits(current_policy, usage, phase=phase, tokens=request.estimated_tokens, calls=1,
                  amount=Decimal(request.estimated_amount) if request.estimated_amount is not None else None,
                  entitlement=(request.provider, request.cost_authorization_ref) if mixed and request.accounting_basis == "ACCOUNT_ENTITLEMENT" else None)
    return {"owner": OWNER, "policy_version": policy["policy_version"], "policy_hash": snapshot["policy_hash"],
        "contract_hash": _contract().contract_hash(policy["comparison_budget"]), "subject_id": snapshot["subject_id"],
        "authorization": policy["authorization"], "phase": phase,
        **({"business_scope": business_scope} if business_scope is not None else {})}


def check_creative_settlement_in_uow(uow: AuthorityUnitOfWork, row: dict[str, Any], actual_tokens: int,
                                   *, actual_amount: Decimal | None = None) -> None:
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
    lineage = _lineage_plans(uow.cursor, current["comparison_budget"], row["project_id"])
    if _contract().contract_hash(policy["comparison_budget"]) not in lineage:
        raise KernelError("CREATIVE_BUDGET_PLAN_IMMUTABLE", "settlement cannot change the frozen allocation plan")
    usage = _usage(uow.cursor, current["comparison_budget"], row["project_id"], exclude_reservation=row["reservation_id"])
    mixed = current["comparison_budget"]["contract_version"] in _contract().PROVIDER_BUDGET_VERSIONS
    _check_limits(current, usage, phase=proof["phase"], tokens=actual_tokens, calls=1,
                  renewal_addition=row["reservation_id"] not in current["comparison_budget"].get("renewal", {}).get("carry_forward", {}).get("reservation_ids", []),
                  amount=actual_amount,
                  entitlement=(row["provider"], row["evidence"]["cost_authorization_ref"])
                  if mixed and row["accounting_basis"] == "ACCOUNT_ENTITLEMENT" else None)


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


def assert_creative_budget_dispatch(
    cursor: Any, *, project_id: str, external_effect_id: str, reservation_id: str,
) -> None:
    selected = _policy_for(cursor, project_id)
    if selected is None or selected["policy"]["comparison_budget"]["contract_version"] not in _contract().PROVIDER_BUDGET_VERSIONS:
        return
    policy = selected["policy"]
    plan = policy["comparison_budget"]
    cursor.execute("""SELECT effect.effect_type,budget.status,budget.evidence,budget.provider,
        budget.estimated_tokens,budget.estimated_amount,budget.currency
        FROM authority_external_effect effect LEFT JOIN authority_budget_reservation budget
          ON budget.external_effect_id=effect.external_effect_id AND budget.reservation_id=%s
          AND budget.project_id=effect.project_id
        WHERE effect.project_id=%s AND effect.external_effect_id=%s""",
        [reservation_id, project_id, external_effect_id])
    row = cursor.fetchone()
    if row is not None and row[0] != "model.invoke":
        return
    if row is None or row[1] != "RESERVED":
        raise KernelError("CREATIVE_BUDGET_RESERVATION_REQUIRED", "campaign inference requires its exact live reservation")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(plan["expires_at"]):
        raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_EXPIRED", "campaign authorization expired before send")
    evidence = dict(row[2] or {})
    proof = evidence.get("creative_experiment") or {}
    lineage = _lineage_plans(cursor, plan, project_id)
    if (proof.get("contract_hash") not in lineage or not proof.get("business_scope")
        or proof.get("phase") != proof["business_scope"].get("phase")):
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "campaign reservation lost its frozen phase and plan")
    cursor.execute("""SELECT content,content_hash FROM authority_runtime_policy_version
        WHERE owner=%s AND project_id=%s AND policy_version=%s""", [OWNER, project_id, proof.get("policy_version")])
    frozen = cursor.fetchone()
    if (not frozen or frozen[1] != proof.get("policy_hash") or policy_hash(frozen[0]) != frozen[1]
        or frozen[0]["authorization"] != proof.get("authorization")
        or _contract().contract_hash(frozen[0]["comparison_budget"]) != proof.get("contract_hash")):
        raise KernelError("RUNTIME_POLICY_HASH_MISMATCH", "campaign dispatch policy is missing or altered")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(frozen[0]["comparison_budget"]["expires_at"]):
        raise KernelError("CREATIVE_BUDGET_AUTHORIZATION_EXPIRED", "The exact reservation authorization expired before send")
    from .creative_budget_scope import require_business_scope

    require_business_scope(policy, proof["business_scope"])
    usage = _usage(cursor, plan, project_id, exclude_reservation=reservation_id)
    _check_limits(policy, usage, phase=proof["phase"], tokens=int(row[4]), calls=1, amount=row[5],
        renewal_addition=reservation_id not in plan.get("renewal", {}).get("carry_forward", {}).get("reservation_ids", []),
        entitlement=(row[3], evidence["cost_authorization_ref"])
        if evidence.get("accounting_basis") == "ACCOUNT_ENTITLEMENT" else None)
    if frozen[0]["comparison_budget"].get("renewal") and frozen[0]["comparison_budget"] != plan:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "An earlier renewal reservation requires reconciliation after replacement")
    _check_limits(frozen[0], usage, phase=proof["phase"], tokens=int(row[4]), calls=1, amount=row[5],
        entitlement=(row[3], evidence["cost_authorization_ref"])
        if evidence.get("accounting_basis") == "ACCOUNT_ENTITLEMENT" else None)


def provider_campaign_contract_lineage(cursor: Any, project_id: str) -> tuple[dict[str, Any], ...]:
    cursor.execute("""SELECT v.content,v.content_hash FROM authority_runtime_policy_selection s
        JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
        WHERE s.owner=%s AND s.project_id=%s""", [OWNER, project_id])
    selected = cursor.fetchone()
    if selected is None:
        return ()
    if policy_hash(selected[0]) != selected[1]:
        raise KernelError("RUNTIME_POLICY_HASH_MISMATCH", "campaign policy integrity failed")
    _contract().validate_policy(selected[0])
    plan = selected[0]["comparison_budget"]
    if plan["contract_version"] not in _contract().PROVIDER_BUDGET_VERSIONS:
        return ()
    return tuple({
        "campaign_id": version["experiment_id"], "manifest_hash": version["manifest_hash"],
        "maximum_calls": version["shared_total"]["calls"], "maximum_tokens": version["shared_total"]["tokens"],
        "maximum_amount": version["shared_total"]["priced_usd"], "expires_at": version["expires_at"],
    } for version in _lineage_plans(cursor, plan, project_id).values())
