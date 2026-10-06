from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, subprocess, xml.etree.ElementTree as ET
root=Path('/Users/yuan/.codex/worktrees/context-router-acceptance-2cb74ed/novel-forge')
evidence=Path('/tmp/nf-context-router-2cb74ed-evidence')
python='/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python'
base='2cb74ed135c7a48e1ca72b4d456113dfd3f78dc3'
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
unit_paths=['tests/unit/test_cost_aware_routing.py','tests/unit/test_context_compression_routing.py','tests/unit/test_context_compression_provider.py','tests/unit/test_task_context_admission.py']
pg_paths=['tests/integration/test_quality_context_formal_e2e_postgres.py::test_native_overflow_compression_fidelity_draft_review_and_frozen_resume','tests/integration/test_context_feedback_postgres.py','tests/integration/test_chapter_model_effects_postgres.py::ChapterModelEffectsPostgresTests::test_context_semantic_subeffects_use_frozen_pack_and_durable_kernel_replay']
env='NOVEL_FORGE_DATABASE_URL=postgresql://[REDACTED_USER]:[REDACTED_PASSWORD]@127.0.0.1:54150/nf_context_router_2cb74ed_20261006_test PYTHONPATH=src '
focused=env+python+' -m pytest -q '+' '.join(unit_paths+['tests/unit/test_quality_calibration_v2.py']+pg_paths)+' --junitxml='+str(evidence/'final-commit-focused.xml')
def artifact(name):
    p=evidence/name
    return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} if p.exists() else {'path':str(p),'status':'NOT_YET_PRESENT'}
p0=json.loads((evidence/'p0-final'/f'p0-backend-qualification-{sha}.json').read_text())
v={
 'schema_version':'scoped-context-router-acceptance.v1','generated_at':datetime.now(timezone.utc).isoformat(),
 'baseline':{'repository':'yuan2go/novel-forge','branch':'main','sha':base,'remote_verified_at_start':True},
 'repair':{'sha':sha,'branch':'codex/context-router-acceptance-2cb74ed','worktree':str(root),'working_tree_clean':not subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip(),'implementation_tree_sha':p0['implementation_tree_sha'],'diff':artifact('repair.patch'),'changed_files':subprocess.check_output(['git','diff','--name-only',base,sha],cwd=root,text=True).splitlines(),'published':False},
 'scope':{'context_tasks':['context_compress','context_fidelity'],'risk':'HIGH','quality_metric':'DOMAIN_GATE_ACCEPTANCE','minimum_samples':20,'policy_version':'quality-constrained-routing.v13','real_provider_calls':0,'provider_evidence_class':['SYNTHETIC','MOCK_E2E'],'new_authority':False,'new_admission_entry':False,'new_quality_metric':False,'old_divergent_repair_cherry_picked':False,'production_database_touched':False},
 'baseline_runs':[
  {'status':'PASS','passed':119,'sha':base,'command':'PYTHONPATH=src '+python+' -m pytest -q '+' '.join(unit_paths)+' --junitxml='+str(evidence/'unit.xml'),'artifact':artifact('unit.xml')},
  {'status':'BLOCKED','reason':'PostgreSQL image lacks vector extension; 11 setup errors, no test body executed','artifact':artifact('postgres-baseline.xml')},
  {'status':'PASS','passed':11,'sha':base,'command':env+python+' -m pytest -q '+' '.join(pg_paths)+' --junitxml='+str(evidence/'postgres-baseline-vector.xml'),'artifact':artifact('postgres-baseline-vector.xml')},
  {'status':'FAIL','passed':7,'failed':4,'sha':base,'reason':['retried Context negatives removed from Router domain denominator (2 cases)','latest UNKNOWN generation reused older positive receipt','dispatch hash drift reused positive receipt'],'command':'NOVEL_FORGE_DATABASE_URL=postgresql://[REDACTED_USER]:[REDACTED_PASSWORD]@127.0.0.1:54150/nf_context_router_2cb74ed_20261006_test PYTHONPATH=src:. '+python+' -m pytest -q '+str(evidence/'test_native_chain_probe.py')+' --junitxml='+str(evidence/'baseline-counterexamples-final.xml'),'cwd':'/Volumes/DevSSD/Development/Workspace/projects/novel-forge-context-router-baseline-2cb74ed','artifact':artifact('baseline-counterexamples-final.xml')},
  {'status':'FAIL','failed':19,'sha':base,'reason':'All 19 full-offline failures independently reproduced on untouched baseline','command':python+' '+str(evidence/'reprove_failures.py'),'node_ids':artifact('baseline-failure-nodeids.json'),'artifact':artifact('baseline-full-failures.xml')},
  {'status':'FAIL','sha':base,'reason':'same four stale proposal lifecycles','command':'PYTHONPATH=src '+python+' -m novel_forge.tools.proposal_lifecycle --repo-root .','artifact':artifact('baseline-proposal-lifecycle.log')}
 ],
 'repair_runs':[
  {'status':'PASS','passed':169,'sha':sha,'command':focused,'cwd':str(root),'artifact':artifact('final-commit-focused.xml'),'components':{'four_unit_files':131,'frozen_reference_policy_compatibility':17,'routed_overflow':1,'native_feedback_chain':19,'frozen_effect_replay':1}},
  {'status':'PASS','command':python.replace('/python','/ruff')+' check '+ ' '.join(subprocess.check_output(['git','diff','--name-only',base,sha],cwd=root,text=True).splitlines()[2:]),'note':'Changed Python files were checked; docs/projection excluded from Ruff. git diff --check PASS.'},
  {'status':'FAIL','command':'PYTHONPATH=src '+python+' -m pytest -q tests/architecture tests/unit tests/acceptance --junitxml='+str(evidence/'full-offline.xml'),'passed':4070,'failed':19,'subtests_passed':1499,'source_binding':'DEVELOPMENT_TREE_NOT_EXACT_FINAL_SHA; completion preceded frozen-reference compatibility addition; no same-SHA qualification claim','artifact':artifact('full-offline.xml'),'baseline_reproduction_count':19},
  {'status':'BLOCKED','command':'NOVEL_FORGE_DATABASE_URL=postgresql://[REDACTED_USER]:[REDACTED_PASSWORD]@127.0.0.1:54150/nf_p0_31d1b9f8e4c14c43a935f60895c5b4db_test NOVEL_FORGE_QUALIFICATION_DATABASE_NAME=nf_p0_31d1b9f8e4c14c43a935f60895c5b4db_test NOVEL_FORGE_POSTGRES_EVIDENCE_DIR='+str(evidence/'full-postgres')+' PYTHONPATH=src make PYTHON='+python+' postgres-authority-test','collected':1022,'partial_passed':222,'partial_failed':3,'partial_errors':1,'subtests_passed':53,'reason':'INTERRUPTED after canonical P0 dependency failure; incomplete diagnostic collection cannot qualify. Observed failures preserved and not attributed to baseline.','source_binding':'DEVELOPMENT_TREE_NOT_EXACT_FINAL_SHA; do not merge with final directed results','artifact':artifact('full-postgres/postgresql-pytest.xml'),'collection':artifact('full-postgres/postgresql-pytest-collection.json')},
  {'status':'FAIL','acceptance':'BLOCKED','sha':sha,'command':'P0_PROFILE=local P0_EVIDENCE_DIR='+str(evidence/'p0-final')+' PYTHONPATH=src make PYTHON='+python+' RUFF='+python.replace('/python','/ruff')+' p0-backend-qualification','artifact':artifact('p0-final/'+f'p0-backend-qualification-{sha}.json'),'gates':[{'gate':g['gate_id'],'status':g['status']} for g in p0['gates']],'reason':'static-and-manifests fails at same four baseline proposal lifecycle entries; subsequent dependency stages NOT_RUN'}
 ],
 'native_chain_checks':['failed fidelity then restoration','verified retry failure survives successful generation','mock output excluded from native qualification','latest UNKNOWN excludes old positives','append verified reconciliation without rewriting UNKNOWN dispatch','receipt/dispatch hash mismatch','project/operation/effect drift','source version/hash and selected-unit drift','producer and model revision drift','UNKNOWN native history blocks qualified Router samples','frozen v12 reference policy remains admissible without blob mutation','full rendered request rejects overflow, unknown meter, incomplete coverage, route and serialization drift before transport'],
 'evidence_ceiling':'EXECUTABLE; MOCK_E2E/POSTGRESQL_INTEGRATION_ONLY; NOT QUALIFIED; NOT PRODUCTION_PROVEN',
 'complete_matrix_acceptance':'BLOCKED','real_provider':'NOT_RUN','literary_fidelity_calibration':'NOT_RUN',
 'cleanup':{'status':'PENDING','owned_container_id':'64bccd2a1b5fb965216b629fd044db5970e59ec18cb3d4905ae06c1531d30730','image_digest':'sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b','port':54150,'databases':['nf_context_router_2cb74ed_20261006_test','nf_p0_31d1b9f8e4c14c43a935f60895c5b4db_test']}
}
(evidence/'acceptance-result.json').write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
