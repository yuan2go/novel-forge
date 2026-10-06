from pathlib import Path
p = Path('/tmp/nf-context-router-2cb74ed-evidence/test_native_chain_probe.py')
s = p.read_text().split('\ndef test_unknown_generation')[0]
s = s.replace('from dataclasses import replace', 'from dataclasses import asdict, replace\nfrom datetime import datetime, timezone',1)
s = s.replace('from tests.unit.test_cost_aware_routing import NOW, samples, candidate', 'from tests.unit.test_cost_aware_routing import candidate, task as routing_task')
s = s.replace('from datetime import datetime, timezone\nfrom dataclasses import asdict','')
s = s.replace('from tests.integration.authority_postgres_support import transaction','from tests.integration.authority_postgres_support import DATABASE_URL, transaction')
s = s.replace('@pytest.mark.parametrize("log_order", ["failure_first", "failure_last", "retried"])\n@pytest.mark.parametrize(\n    "terminal,real_flag",\n    [("SUCCEEDED", True), ("FAILED_FINAL", True), ("SUCCEEDED", False)],\n)\ndef test_every_native_fidelity_attempt_and_failed_context_retains_its_denominator(', 'def _assert_native_feedback_chain(')
s = s.replace('    # Synthetic PostgreSQL intent/receipt projection only: OFFLINE, not real qualification.', '    # WHY: synthetic real-call flags exercise native projection; no Provider is invoked.')
s = s.replace("PostgresRoutingRegistry(__import__('tests.integration.authority_postgres_support', fromlist=['DATABASE_URL']).DATABASE_URL,",'PostgresRoutingRegistry(DATABASE_URL,')
s += '''        decision = CostAwareRouter().explain(
            replace(routing_task(), task_type=stage), [model],
            {model.candidate_id: observations}, now=datetime.now(timezone.utc),
        ).to_dict()
        assert decision["status"] == "BLOCKED"
        assert decision["policy"]["quality_metric"] == "DOMAIN_GATE_ACCEPTANCE"
    return ids


@pytest.mark.parametrize("log_order", ["failure_first", "failure_last", "retried"])
@pytest.mark.parametrize("terminal,real_flag", [("SUCCEEDED", True), ("FAILED_FINAL", True), ("SUCCEEDED", False)])
def test_every_native_fidelity_attempt_and_failed_context_retains_its_denominator(scope, terminal, real_flag, log_order):
    _assert_native_feedback_chain(scope, terminal, real_flag, log_order)


@pytest.mark.parametrize("effect_status", ["SUCCEEDED", "UNKNOWN"])
def test_unknown_generation_cannot_reuse_old_positive_gate(scope, effect_status):
    ids = _assert_native_feedback_chain(scope, "SUCCEEDED", True, "failure_first")
    identity = ids[-1]
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE authority_external_effect SET status=%s WHERE external_effect_id=%s", [effect_status, identity])
        cursor.execute("INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,status,payload_hash,evidence) VALUES(%s,%s,3,'UNKNOWN','pending','{}')", [identity + ":unknown", identity])
        outcomes = context_gate_outcomes(cursor, project_id=scope[0], effect_ids=ids)
    assert outcomes.get(identity, {}).get("accepted") is not True
    registry = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=context_gate_outcomes)
    observations = registry.observations(project_id=scope[0], task_type="context_fidelity", candidate=candidate(), producer_contract_hash="sha256:context-native-producer")
    assert all(row.domain_gate_accepted is not True for row in observations)
    # WHY: completing native reconciliation appends a verified generation; the UNKNOWN remains history.
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE authority_external_effect SET status='SUCCEEDED' WHERE external_effect_id=%s", [identity])
        cursor.execute("""INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,status,payload_hash,evidence)
            SELECT %s,external_effect_id,4,'SUCCEEDED',payload_hash,evidence FROM authority_external_effect_dispatch WHERE external_effect_id=%s AND generation=2""", [identity + ":reconciled", identity])
        cursor.execute("""INSERT INTO authority_external_receipt(provider,receipt_id,dispatch_id,payload_hash,payload,status)
            SELECT 'OFFLINE',%s,%s,payload_hash,payload,'VERIFIED' FROM authority_external_receipt WHERE dispatch_id=%s""", [identity + ":reconciled", identity + ":reconciled", identity])
        outcomes = context_gate_outcomes(cursor, project_id=scope[0], effect_ids=ids)
        assert outcomes[identity]["accepted"] is True
        cursor.execute("SELECT status FROM authority_external_effect_dispatch WHERE dispatch_id=%s", [identity + ":unknown"])
        assert cursor.fetchone()[0] == "UNKNOWN"


@pytest.mark.parametrize("drift", ["dispatch_hash", "receipt_hash", "project", "operation", "effect", "source_version", "source_hash", "selected_units"])
def test_native_feedback_identity_drift_cannot_qualify_context(scope, drift):
    ids = _assert_native_feedback_chain(scope, "SUCCEEDED", True, "failure_first")
    identity = ids[-1]
    with transaction() as connection, connection.cursor() as cursor:
        if drift == "dispatch_hash":
            cursor.execute("UPDATE authority_external_effect_dispatch SET payload_hash='sha256:drift' WHERE external_effect_id=%s", [identity])
        elif drift == "receipt_hash":
            cursor.execute("UPDATE authority_external_receipt SET payload_hash='sha256:drift' WHERE dispatch_id=%s", [identity])
        elif drift in {"project", "operation", "effect"}:
            cursor.execute("SELECT evidence FROM authority_external_effect_dispatch WHERE dispatch_id=%s", [identity])
            evidence = cursor.fetchone()[0]
            evidence["production_execution"]["execution_request"][drift + "_id" if drift != "effect" else "external_effect_id"] = "other-identity"
            cursor.execute("UPDATE authority_external_effect_dispatch SET evidence=%s,payload_hash=%s WHERE dispatch_id=%s", [Jsonb(evidence), _hash(evidence), identity])
            cursor.execute("UPDATE authority_external_receipt SET payload=%s,payload_hash=%s WHERE dispatch_id=%s", [Jsonb({"evidence": evidence}), _hash(evidence), identity])
            cursor.execute("""UPDATE authority_asset_version SET content=jsonb_set(content,'{provider_evidence}',%s)
                WHERE content #>> '{provider_evidence,production_execution,execution_request,external_effect_id}'=%s""", [Jsonb(evidence), identity])
        else:
            cursor.execute("SELECT request_payload FROM authority_external_effect WHERE external_effect_id=%s", [identity])
            payload = cursor.fetchone()[0]
            task = payload["input"]["context_compression_task"]
            if drift == "selected_units":
                task["selected_unit_ids"] = ["u0"]
            else:
                task["source_binding"]["asset_version_id" if drift == "source_version" else "content_hash"] = "other-source"
            cursor.execute("UPDATE authority_external_effect SET request_payload=%s,request_hash=%s WHERE external_effect_id=%s", [Jsonb(payload), _hash(payload), identity])
        outcomes = context_gate_outcomes(cursor, project_id=scope[0], effect_ids=ids)
    assert outcomes.get(identity, {}).get("accepted") is not True
    registry = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=context_gate_outcomes)
    observations = registry.observations(project_id=scope[0], task_type="context_fidelity", candidate=candidate(), producer_contract_hash="sha256:context-native-producer")
    assert all(row.domain_gate_accepted is not True for row in observations)
    assert registry.observations(project_id=scope[0], task_type="context_fidelity", candidate=candidate(), producer_contract_hash="sha256:other-producer") == []
    assert registry.observations(project_id=scope[0], task_type="context_fidelity", candidate=candidate(model_revision="other-revision")) == []
'''
Path('tests/integration/test_context_feedback_postgres.py').write_text(s)
