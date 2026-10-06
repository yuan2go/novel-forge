from pathlib import Path
base = Path('tests/integration/test_context_feedback_postgres.py').read_text()
base = base.replace('from tests.unit.test_cost_aware_routing import NOW, samples', '''from tests.unit.test_cost_aware_routing import NOW, samples, candidate
from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
from datetime import datetime, timezone
from dataclasses import asdict''')
base = base.replace('    task = {', '    model = candidate()\n    task = {', 1)
base = base.replace('scope, {"stage": stage, "input": {"context_compression_task": frozen_task}}', '''scope, {"stage": stage, "input": {"context_compression_task": frozen_task},
                "_production_execution": {"capability_runtime": {"routing_decision": {
                    "status": "SELECTED", "selected": {"candidate": asdict(model)},
                    "task": {"producer_contract_hash": "sha256:context-native-producer", "input_hash": _hash(frozen_task)},
                    "policy": {"risk": "HIGH"},
                }}}}''')
base = base.replace('        evidence = {', '''        execution.update({"execution_result": {"outcome": "SUCCEEDED"},
            "route_snapshot": {"reasoning_effort": model.reasoning},
            "process_evidence": {"served_model_identity_hash": "sha256:synthetic-cohort"}})
        evidence = {"provider_id": model.provider, "model_id": model.model,''')
start = base.index('    observations = [')
base = base[:start] + '''    registry = PostgresRoutingRegistry(__import__('tests.integration.authority_postgres_support', fromlist=['DATABASE_URL']).DATABASE_URL,
        outcome_projection=context_gate_outcomes)
    for stage, count in (("context_compress", 1), ("context_fidelity", 2)):
        observations = registry.observations(project_id=scope[0], task_type=stage,
            candidate=model, producer_contract_hash="sha256:context-native-producer")
        assert len(observations) == count
        snapshot = benchmark_snapshot(observations, now=datetime.now(timezone.utc), policy=task_policy(stage))
        assert snapshot["domain_gate_sample_count"] == count, snapshot
        assert snapshot["predicted_quality"] <= 1 / 2
'''
Path('/tmp/nf-context-router-2cb74ed-evidence/test_native_chain_probe.py').write_text(base)
