from dataclasses import replace
from copy import deepcopy

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    resolve_provider_budget_failure,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    _hash,
    plan_external_effect,
    prepare_effect_dispatch,
    acquire_effect_dispatch,
    submit_effect_dispatch_result,
    reconcile_external_effect,
    read_succeeded_external_effect,
    accept_external_effect_receipt,
)
from novel_forge.modules.command_kernel.manual_effect_resolution import (
    ExternalEffectManualResolutionCommand,
    resolve_external_effect_manually,
)
from novel_forge.modules.production_execution.contracts import ExecutionRuntimeClass
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
    seed_authority_project_book,
)
from tests.integration.test_cli_effect_reconciliation_postgres import asset
from tests.unit.test_production_execution_gateway import contracts


@pytest.fixture
def isolated_api(request):
    basis = getattr(request, "param", "ACCOUNT_ENTITLEMENT")
    remote_request = identifier("remote")
    gateway = basis == "GATEWAY"
    if gateway:
        basis = "ACCOUNT_ENTITLEMENT"
    project, operation, book, workspace = (
        identifier(x) for x in ("project", "operation", "book", "workspace")
    )
    seed_authority_project_book(
        project_id=project, book_id=book, workspace_id=workspace
    )
    with transaction() as c, c.cursor() as q:
        if not c.execute(
            "SELECT 1 FROM authority_operation_definition WHERE name='story_planning.generate' AND definition_version='1.0.0'"
        ).fetchone():
            insert_definition(q, "story_planning.generate")
        insert_operation(
            q,
            operation_id=operation,
            definition_name="story_planning.generate",
            project_id=project,
            workspace_id=workspace,
            status="EXECUTING",
            command_payload={
                "payload": dict(
                    project_id=project, workspace_id=workspace, book_id=book
                )
            },
        )
        c.execute(
            "UPDATE authority_operation SET actor_id='operator' WHERE operation_id=%s",
            [operation],
        )
        c.execute(
            """INSERT INTO authority_story_planning_generation(generation_id,operation_id,project_id,workspace_id,book_id,
            generator_operation_name,planning_scope,logical_key,input_snapshot,input_snapshot_hash,status)
            VALUES(%s,%s,%s,%s,%s,'chapter_plan.generate','CHAPTER','synthetic','[]',%s,'REJECTED')""",
            [identifier("generation"), operation, project, workspace, book, _hash([])],
        )
    materialization = {
        "contract": {
            "tool_permissions": {
                "default": "DENY",
                "allowed": ["model.provider.invoke"],
            }
        }
    }
    materialization_ref = asset(
        project,
        materialization,
        "capability_materialization",
        "capability-materialization.v1",
    )
    with transaction() as c:
        mat_hash = c.execute(
            "SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s",
            [materialization_ref.split(":", 1)[1]],
        ).fetchone()[0]
    context = EffectCommandContext(
        operation, project, "operator", "trace", "correlation"
    )
    adapter = FakeDeterministicProvider("success")
    if gateway:
        adapter.provider = "production_execution_gateway"
    adapter.capability_profile = {
        **adapter.capability_profile,
        "provider": adapter.provider,
        "supports_usage_receipt": True,
        "supports_cost_receipt": True,
    }
    effect = plan_external_effect(
        DATABASE_URL,
        context,
        effect_type="model.invoke",
        provider=adapter.provider,
        capability="model.test",
        stable_idempotency_key=identifier("effect"),
        request_payload={
            "_production_execution": {
                "book_id": book,
                "route_provider": FakeDeterministicProvider.provider,
                "capability_runtime": {
                    "materialization_asset_version_id": materialization_ref.split(
                        ":", 1
                    )[1],
                    "materialization_content_hash": mat_hash,
                },
            }
        },
        max_attempts=2,
        reversible=False,
        provider_capability_profile=adapter.capability_profile,
    )["external_effect_id"]
    reservation = reserve_provider_budget(
        DATABASE_URL,
        BudgetReservationRequest(
            operation_id=operation,
            project_id=project,
            external_effect_id=effect,
            stable_idempotency_key=identifier("budget"),
            provider=adapter.provider,
            currency="UNKNOWN" if basis == "ACCOUNT_ENTITLEMENT" else "USD",
            estimated_amount=None if basis == "ACCOUNT_ENTITLEMENT" else "1",
            estimated_tokens=1000,
            accounting_basis=basis,
            cost_authorization_ref="synthetic-grant",
        ),
    )
    dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
    lease = acquire_effect_dispatch(
        DATABASE_URL,
        context,
        dispatch_id=dispatch["dispatch_id"],
        worker_id="fixture",
        lease_seconds=30,
    )
    _, _, _, route, manifest, request = contracts(
        backend_id="remote-provider", runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API
    )
    request = replace(
        request,
        project_id=project,
        workspace_id=workspace,
        operation_id=operation,
        external_effect_id=effect,
        book_id=book,
        target_scope={
            **request.target_scope.to_dict(),
            "project_id": project,
            "book_id": book,
        },
    )
    route = replace(route, model_provider=FakeDeterministicProvider.provider)
    production = {
        "execution_request": request.to_dict(),
        "execution_handle": {
            "transport": "REMOTE_PROVIDER_API",
            "provider_request_id": remote_request,
        },
        "route_snapshot": route.to_dict(),
        "input_manifest": manifest.to_dict(),
    }
    submit_effect_dispatch_result(
        DATABASE_URL,
        context,
        dispatch_id=dispatch["dispatch_id"],
        worker_id="fixture",
        fencing_token=lease["fencing_token"],
        outcome="unknown",
        provider_correlation_id=remote_request,
        provider_request_id=remote_request,
        evidence={"production_execution": production},
    )
    resolve_provider_budget_failure(
        DATABASE_URL,
        reservation_id=reservation["reservation_id"],
        project_id=project,
        external_state_unknown=True,
    )
    with transaction() as c:
        c.execute(
            "UPDATE authority_operation SET status='FAILED_FINAL' WHERE operation_id=%s",
            [operation],
        )
        request_hash = c.execute(
            "SELECT request_hash FROM authority_external_effect WHERE external_effect_id=%s",
            [effect],
        ).fetchone()[0]
        proof = dict(
            contract_version="pure-generation-isolation.v1",
            actor_id=context.actor_id,
            remote_outcome="UNKNOWN",
            usage="UNKNOWN",
            business_commit_right="REVOKED",
            activation_right="REVOKED",
            continuation_id="planning-runtime-continuation:" + operation,
            dispatch_ids=[dispatch["dispatch_id"]],
            book_id=book,
            local_execution={
                key: request.to_dict()[key]
                for key in ("execution_id", "attempt_id", "fencing_token")
            },
        )
        c.execute(
            """INSERT INTO authority_generation_isolation(isolation_id,external_effect_id,operation_id,project_id,workspace_id,book_id,
            request_hash,materialization_asset_version_id,proof) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                identifier("isolation"),
                effect,
                operation,
                project,
                workspace,
                book,
                request_hash,
                materialization_ref.split(":", 1)[1],
                Jsonb(proof),
            ],
        )
        version = c.execute(
            "SELECT version FROM authority_operation WHERE operation_id=%s", [operation]
        ).fetchone()[0]
    receipt = dict(
        project_id=project,
        operation_id=operation,
        external_effect_id=effect,
        book_id=book,
        dispatch_id=dispatch["dispatch_id"],
        generation=dispatch["generation"],
        request_hash=request_hash,
        **proof["local_execution"],
        execution_request_hash=_hash(request.to_dict()),
        input_manifest_hash=_hash(production["input_manifest"]),
        provider_id=route.model_provider,
        model_id=route.model_id,
        provider_request_id=remote_request,
        outcome="success",
        result={"objective": "original synthetic result"},
        usage={
            "measurement": "PROVIDER_REPORTED",
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
        },
        cost={"availability": "UNAVAILABLE", "measurement": "UNKNOWN", "amount": None},
    )
    return context, effect, dispatch, receipt, version


def command_for(seeded, receipt=None):
    context, effect, _, original, version = seeded
    receipt = deepcopy(original if receipt is None else receipt)
    source_ref = asset(
        context.project_id,
        {"contract_version": "api-provider-record.v1", **receipt},
        "execution_evidence",
        "api-provider-record.v1",
    )
    ref = asset(
        context.project_id,
        {
            "contract_version": "api-original-receipt.v1",
            **receipt,
            "source_ref": source_ref,
            "verification_basis": "AUTHORIZED_OPERATOR_ATTESTATION",
            "verified_by": context.actor_id,
        },
        "execution_evidence",
        "api-original-receipt.v1",
    )
    return ExternalEffectManualResolutionCommand(
        effect,
        context.operation_id,
        context.project_id,
        context.actor_id,
        "MARK_SUCCEEDED",
        "SYNTHETIC original API receipt",
        {"original_remote_receipt_ref": ref},
        identifier("resolution"),
        version,
        context.trace_id,
        context.correlation_id,
    )


def history(seeded):
    context, effect, dispatch, *_ = seeded
    with transaction() as c:
        return [
            c.execute(query, [identity]).fetchone()[0]
            for query, identity in (
                (
                    "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
                    context.operation_id,
                ),
                (
                    "SELECT to_jsonb(e) FROM authority_external_effect e WHERE external_effect_id=%s",
                    effect,
                ),
                (
                    "SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE dispatch_id=%s",
                    dispatch["dispatch_id"],
                ),
                (
                    "SELECT to_jsonb(i) FROM authority_generation_isolation i WHERE external_effect_id=%s",
                    effect,
                ),
            )
        ]


def test_original_api_receipt_records_and_settles_once_without_old_business_rights(
    isolated_api,
):
    context, effect, _, receipt, _ = isolated_api
    before = history(isolated_api)
    command = command_for(isolated_api)
    first = resolve_external_effect_manually(DATABASE_URL, command)
    assert not first["replayed"] and first["evidence_only"]
    assert first["business_commit_right"] == first["activation_right"] == "REVOKED"
    assert resolve_external_effect_manually(DATABASE_URL, command)["replayed"]
    assert not resolve_external_effect_manually(
        DATABASE_URL, command_for(isolated_api)
    )["replayed"]
    assert history(isolated_api) == before
    with transaction() as c:
        assert c.execute(
            "SELECT status,actual_tokens,settled_amount FROM authority_budget_reservation WHERE external_effect_id=%s",
            [effect],
        ).fetchone() == ("SETTLED", 150, None)
        assert (
            c.execute(
                "SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 1
        )
    with pytest.raises(
        KernelError, match="OPERATION_STATUS_CONFLICT|GENERATION_ATTEMPT_ISOLATED"
    ):
        read_succeeded_external_effect(DATABASE_URL, context, effect_id=effect)
    with pytest.raises(
        KernelError, match="OPERATION_STATUS_CONFLICT|GENERATION_ATTEMPT_ISOLATED"
    ):
        prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
    with pytest.raises(Exception, match="GENERATION_ATTEMPT_ISOLATED"):
        with transaction() as c:
            c.execute(
                "UPDATE authority_external_effect SET status='SUCCEEDED' WHERE external_effect_id=%s",
                [effect],
            )

    with pytest.raises(Exception, match="GENERATION_ATTEMPT_ISOLATED"):
        with transaction() as c:
            c.execute(
                """INSERT INTO authority_operation_output_asset(operation_id,asset_id,asset_version_id,output_key,role,content_hash)
                SELECT %s,asset_id,asset_version_id,'late-primary','primary',content_hash FROM authority_asset_version WHERE asset_version_id=%s""",
                [
                    context.operation_id,
                    command.evidence["original_remote_receipt_ref"].split(":", 1)[1],
                ],
            )
    from novel_forge.modules.command_kernel.external_effect_runtime import (
        read_failed_operation_success,
    )

    with pytest.raises(KernelError, match="GENERATION_ATTEMPT_ISOLATED"):
        read_failed_operation_success(DATABASE_URL, context, effect_id=effect)

    class NeverQuery(FakeDeterministicProvider):
        def query(self, **kwargs):
            raise AssertionError("no external query or dispatch")

    assert reconcile_external_effect(
        DATABASE_URL, context, effect_id=effect, adapter=NeverQuery("success")
    )["evidence_only"]
    changed = deepcopy(receipt)
    changed["usage"]["output_tokens"] += 1
    changed["usage"]["total_tokens"] += 1
    with pytest.raises(KernelError, match="ISOLATED_API_RECEIPT_CONFLICT"):
        resolve_external_effect_manually(
            DATABASE_URL, command_for(isolated_api, changed)
        )
    assert history(isolated_api) == before


@pytest.mark.parametrize(
    "field",
    [
        "project_id",
        "book_id",
        "operation_id",
        "external_effect_id",
        "dispatch_id",
        "generation",
        "request_hash",
        "execution_id",
        "attempt_id",
        "fencing_token",
        "input_manifest_hash",
        "model_id",
        "provider_id",
        "provider_request_id",
    ],
)
def test_foreign_or_changed_original_api_identity_cannot_settle(isolated_api, field):
    _, effect, _, receipt, _ = isolated_api
    changed = deepcopy(receipt)
    changed[field] = "foreign"
    with pytest.raises(KernelError):
        resolve_external_effect_manually(
            DATABASE_URL, command_for(isolated_api, changed)
        )
    with transaction() as c:
        assert (
            c.execute(
                "SELECT status FROM authority_budget_reservation WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == "HELD_UNKNOWN"
        )
        assert (
            c.execute(
                "SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 0
        )


def test_missing_usage_is_evidence_only_then_measured_version_settles(isolated_api):
    _, effect, _, receipt, _ = isolated_api
    changed = deepcopy(receipt)
    changed["usage"] = None
    before = history(isolated_api)
    resolve_external_effect_manually(DATABASE_URL, command_for(isolated_api, changed))
    with transaction() as c:
        assert (
            c.execute(
                "SELECT status FROM authority_budget_reservation WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == "HELD_UNKNOWN"
        )
    resolve_external_effect_manually(DATABASE_URL, command_for(isolated_api))
    with transaction() as c:
        assert c.execute(
            "SELECT status,actual_tokens FROM authority_budget_reservation WHERE external_effect_id=%s",
            [effect],
        ).fetchone() == ("SETTLED", 150)
        assert (
            c.execute(
                "SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 2
        )
    assert history(isolated_api) == before


def test_unsigned_receipt_and_reconciliation_cannot_update_isolated_effect(
    isolated_api,
):
    context, effect, dispatch, receipt, _ = isolated_api
    before = history(isolated_api)
    with pytest.raises(KernelError, match="ISOLATED_API_RECEIPT_INVALID"):
        accept_external_effect_receipt(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            provider=FakeDeterministicProvider.provider,
            receipt_id="late",
            message_id="late",
            payload_hash=_hash(receipt),
            provider_correlation_id=receipt["provider_request_id"],
            generation=1,
            outcome="success",
            evidence=receipt,
        )
    with pytest.raises(KernelError, match="ISOLATED_ORIGINAL_RECEIPT_REQUIRED"):
        reconcile_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            adapter=FakeDeterministicProvider("success"),
        )
    assert history(isolated_api) == before


@pytest.mark.parametrize("isolated_api", ["GATEWAY"], indirect=True)
def test_signed_native_gateway_callback_is_evidence_only_and_replay_does_not_charge(
    isolated_api,
):
    import hashlib
    import hmac
    import json
    from novel_forge.modules.provider_control import (
        ProviderAdapterRegistry,
        ProviderReceipt,
    )
    from novel_forge.modules.provider_control.contracts import (
        capability_profile_from_dict,
    )
    from novel_forge.modules.provider_callback_authority.service import (
        ProviderCallbackAcceptCommand,
        ProviderCallbackAuthorityService,
    )

    context, effect, _, receipt, _ = isolated_api
    before = history(isolated_api)

    class SignedFixture:
        provider = FakeDeterministicProvider.provider
        capability_profile = capability_profile_from_dict(
            {**FakeDeterministicProvider.capability_profile, "supports_callback": True}
        )

        def verify_callback(self, body, headers, *, secret):
            expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, headers["x-signature"]):
                raise ValueError("invalid signature")
            verified = ProviderReceipt(**json.loads(body))
            return replace(
                verified, payload_hash="sha256:" + hashlib.sha256(body).hexdigest()
            )

    registry = ProviderAdapterRegistry()
    registry.register(SignedFixture())
    service = ProviderCallbackAuthorityService(DATABASE_URL, registry)

    def callback(message, evidence, invalid=False):
        body = json.dumps(
            {
                "provider_request_id": receipt["provider_request_id"],
                "receipt_id": message,
                "message_id": message,
                "outcome": "success",
                "payload_hash": "placeholder",
                "evidence": evidence,
            },
            sort_keys=True,
        ).encode()
        secret = "synthetic-callback-secret"
        signature = (
            "invalid"
            if invalid
            else hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        )
        return ProviderCallbackAcceptCommand(
            SignedFixture.provider,
            message,
            body,
            {"x-signature": signature},
            secret,
            context.actor_id,
            "callback-worker",
            context.trace_id,
            context.correlation_id,
        )

    evidence = {key: receipt[key] for key in ("result", "usage", "cost")}
    command = callback("signed-late", evidence)
    assert service.accept(command)["processing_status"] == "PROCESSED"
    assert service.accept(command)["replayed"]
    assert service.accept(callback("signed-late-new-message", evidence))[
        "effect_receipt_replayed"
    ]
    assert history(isolated_api) == before
    changed = deepcopy(evidence)
    changed["result"] = {"objective": "conflicting original response"}
    with pytest.raises(KernelError, match="ISOLATED_API_RECEIPT_CONFLICT"):
        service.accept(callback("conflict-late", changed))
    with pytest.raises(KernelError, match="PROVIDER_CALLBACK_SIGNATURE_INVALID"):
        service.accept(callback("unverified-late", evidence, True))
    with transaction() as c:
        assert (
            c.execute(
                "SELECT actual_tokens FROM authority_budget_reservation WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 150
        )
        assert (
            c.execute(
                "SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 1
        )
    assert history(isolated_api) == before


@pytest.mark.parametrize("isolated_api", ["PRICED"], indirect=True)
@pytest.mark.parametrize("actual_cost", ["0.25", "1.50"])
def test_late_paid_receipt_uses_original_reservation_and_preserves_overrun(
    isolated_api, actual_cost
):
    _, effect, _, receipt, _ = isolated_api
    changed = deepcopy(receipt)
    changed["cost"] = {
        "availability": "AVAILABLE",
        "measurement": "PROVIDER_REPORTED",
        "source": "provider_receipt",
        "provider_billed": True,
        "amount": actual_cost,
        "currency": "USD",
    }
    command = command_for(isolated_api, changed)
    resolve_external_effect_manually(DATABASE_URL, command)
    resolve_external_effect_manually(DATABASE_URL, command)
    with transaction() as c:
        budget = c.execute(
            "SELECT status,actual_tokens,settled_amount,evidence FROM authority_budget_reservation WHERE external_effect_id=%s",
            [effect],
        ).fetchone()
        assert budget[1] == 150
        from decimal import Decimal

        if actual_cost == "1.50":
            assert budget[0] == "HELD_UNKNOWN"
            assert Decimal(budget[3]["actual_amount"]) == Decimal(actual_cost)
        else:
            assert budget[0] == "SETTLED"
            assert budget[2] == Decimal(actual_cost)
        assert (
            c.execute(
                "SELECT count(*) FROM authority_budget_reservation WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 1
        )
        recorded = c.execute(
            "SELECT evidence FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s",
            [effect],
        ).fetchone()[0]
        assert recorded["budget_breach"] == (actual_cost == "1.50")


def test_concurrent_original_receipt_resolutions_share_one_settlement(isolated_api):
    from concurrent.futures import ThreadPoolExecutor

    _, effect, *_ = isolated_api
    commands = [command_for(isolated_api), command_for(isolated_api)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda cmd: resolve_external_effect_manually(DATABASE_URL, cmd),
                commands,
            )
        )
    assert all(result["operation_status"] == "FAILED_FINAL" for result in results)
    with transaction() as c:
        assert (
            c.execute(
                "SELECT actual_tokens FROM authority_budget_reservation WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 150
        )
        assert (
            c.execute(
                "SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("isolated_api", ["PRICED"], indirect=True)
def test_missing_paid_cost_keeps_exposure_until_matching_cost_version(isolated_api):
    _, effect, _, receipt, _ = isolated_api
    resolve_external_effect_manually(DATABASE_URL, command_for(isolated_api))
    with transaction() as c:
        assert (
            c.execute(
                "SELECT status FROM authority_budget_reservation WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == "HELD_UNKNOWN"
        )
    changed = deepcopy(receipt)
    changed["cost"] = {
        "availability": "AVAILABLE",
        "measurement": "PROVIDER_REPORTED",
        "source": "provider_receipt",
        "provider_billed": True,
        "amount": "0.25",
        "currency": "USD",
    }
    resolve_external_effect_manually(DATABASE_URL, command_for(isolated_api, changed))
    with transaction() as c:
        assert c.execute(
            "SELECT status,actual_tokens FROM authority_budget_reservation WHERE external_effect_id=%s",
            [effect],
        ).fetchone() == ("SETTLED", 150)
        assert (
            c.execute(
                "SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s",
                [effect],
            ).fetchone()[0]
            == 2
        )
