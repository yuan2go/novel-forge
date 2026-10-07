import hashlib
import json
import re
import subprocess
from functools import cache
from pathlib import Path

R=Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge')
O=Path('/tmp/novel-forge-pr133-audit-20261007/implementation')
B='f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609'
S='ad1c229d4b17db45fa14c73dcc6569e8655c82c9'
P='042f44671ad4f7c47eb7cd0b69d1ff226e116aa2'
H='e1bd3aa84728257f44437795cfc2a7fbdcd87274'
T='b3532627648c885bd2aac7c70c3d149b3f1edf98'
I='sha256:f940dcaf98a51fe1ed805f610a84e6f640b6c20af8bebb7df3db813ae1eb65de'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=R)


@cache
def blob(commit,path):
    ref=f'{commit}:{path}'
    if subprocess.run(['git','cat-file','-e',ref],cwd=R,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        return None
    raw=git('show',ref)
    return {'git_blob':git('rev-parse',ref).decode().strip(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


assert git('rev-parse','HEAD').decode().strip()==H
assert git('rev-parse',H+'^{tree}').decode().strip()==T
assert not git('status','--porcelain').strip()
for name in ('source-adjudication.json','published-migration-byte-proof.json','final-candidate-source-coverage.json','proposal-applicability-review.json'):
    p=O/name;old=p.with_name(p.stem+'.candidate-042f446.json')
    if not old.exists():old.write_bytes(p.read_bytes())
d=json.loads((O/'source-adjudication.json').read_text())
original=json.loads((O/'source-adjudication.original-source-verdicts.json').read_text())
protected=('files','commits','overlaps','text_conflicts','migrations','counts','fixed_sources')
assert all(d[k]==original[k] for k in protected)
old_p0_path=O/'p0-integration-final2'/('p0-backend-qualification-'+P+'.json')
old_gov_path=O/'p0-integration-final2'/('pr-governance-'+P+'.json')
old_p0=json.loads(old_p0_path.read_text());old_gov=json.loads(old_gov_path.read_text())
assert old_p0['status']==old_gov['status']=='FAIL'
assert old_p0['cleanup']['status']=='PASS' and old_p0['cleanup']['remaining_resource_count']==0
d.setdefault('candidate_attempt_history',[]).append({
    'candidate_sha':P,'candidate_tree':'2f7dd40de56f5dd9b4b1ac33f5848bb4737562d8',
    'status_at_prior_snapshot':'RUNNING','actual_pr_governance_status':'FAIL','canonical_p0_status':'FAIL',
    'canonical_p0_report':str(old_p0_path),'pr_governance_report':str(old_gov_path),
    'failure_reason':old_p0['failure_reason'],
    'gate_states':[{'gate_id':g['gate_id'],'status':g['status']} for g in old_p0['gates']],
    'migration_compatibility_observed_counts':{'failed':3,'passed':52,'errors':60,'count_source':'parent-observed final2 matrix report'},
    'cleanup':old_p0['cleanup'],
    'prior_scope_passes_not_latest_candidate_qualification':{'backend_nodes_passed':4329,'additional_junit_subtests':1500,'fresh_migrations_passed':169},
    'superseded_by_candidate_sha':H})
f=d['integration_forward_fixes']
index_paths=['src/novel_forge/storage/migrations/versions/v20261007_0166_failed_step_successor.py',
             'src/novel_forge/storage/migrations/versions/v20261007_0168_derived_step_revalidation.py']
legacy='tests/integration/test_authority_legacy_migration_postgres.py'
f['groups'].extend([
    {'id':'unpublished_successor_saga_foreign_key_supporting_indices',
     'rationale':'Final2 compatibility exposed missing supporting saga_id indexes on the new unpublished 0166/0168 successor tables. Exactly one supporting index statement is appended to each; actual foreign keys are validated and unchanged, and trigger bodies, owner/scope/history guards and all published 0000-0159 bodies are unchanged. This repairs query-plan/foreign-key index coverage, not an unvalidated-constraint defect.',
     'paths':[{'path':p,'fixed_main':blob(B,p),'fixed_pr133':blob(S,p),'in_original_132_path_verdicts':False,
               'attribution':'INTEGRATION_FORWARD_MIGRATION_INDEX_FIX','qualification_upgrade':False} for p in index_paths],
     'statement_sha256_reported_by_planning':{'0166':'40597082d03bab001b95d5ee758f5c63fd025929dc82ddbcaafed604bc169693',
                                              '0168':'248bbf6001a0cd05003f39d18e4cd195523c7cb47611d23363cf372a8497a19e'},
     'scope_bound_check':{'status':'PASS','count':2,'seconds':7.04,
                          'log':'/tmp/pr133-planning/test-fk-index-migrations-debug2.log',
                          'scope':'existing native fresh migration chain and policy-completion-index upgrade rollback/replay nodes only',
                          'qualification_upgrade':False}},
    {'id':'legacy_0066_true_ddl_prefix_fixture',
     'rationale':'Existing legacy migration test now uses an owned disposable database at the true 0066 DDL prefix rather than dropping an active constraint and deleting a 0067 ledger row from the current schema. The exact required late release table is materialized by existing governed historical-fixture helper. Original 0067 ambiguity rejection, verified blob, real projection and immutable source assertions remain; this is controlled fixture construction, not production history rewrite.',
     'paths':[{'path':legacy,'fixed_main':blob(B,legacy),'fixed_pr133':blob(S,legacy),'in_original_132_path_verdicts':False,
               'attribution':'INTEGRATION_TRUE_HISTORICAL_DDL_FIXTURE','qualification_upgrade':False}],
     'scope_bound_check':{'status':'PASS','count':1,'seconds':6.58,'log':str(O/'chapter-legacy0066-fixture-attempt2.log'),
                         'scope':'one source migration verified-blob/real-projection historical upgrade node',
                         'retained_previous_failure':str(O/'chapter-legacy0066-fixture-attempt1.log'),'qualification_upgrade':False}},
])
for group in f['groups']:
    for p in group['paths']:
        if 'final_candidate_snapshot' in p:
            p.setdefault('retained_prior_candidate_snapshots',[]).append({'candidate_sha':P,'snapshot':p['final_candidate_snapshot']})
        p['final_candidate_snapshot']=blob(H,p['path']);p['final_candidate_sha']=H
        p['exists_in_final_candidate']=p['final_candidate_snapshot'] is not None
        p['changed_from_fixed_main']=p['final_candidate_snapshot']!=blob(B,p['path'])
    if group['id']=='reviewed_existing_proposal_current_checkpoint':
        group['additional_index_scope_review']={'path':str(O/'proposal-index-scope-review.json'),
            'three_proposals_baseline':'b484551d1d128075b67784c2b4bed489d1119397',
            'implementation_identity':I,'delta':'two supporting indexes only; decisions/work/dates unchanged',
            'prompt_baseline_retained':'578d59b08ef79fdd51836dd9e214913125f38b9d',
            'qualification_upgrade':False}
changed=sorted(git('diff','--name-only',B,H).decode().splitlines())
assert len(changed)==172
orig={p['path'] for p in d['files']};verdicts={p['path']:p['decision'] for p in d['files']}
groups={p:[g['id'] for g in f['groups'] if p in {x['path'] for x in g['paths']}] for p in changed}
assert all(p in orig or groups[p] for p in changed)
coverage={'base_sha':B,'candidate_sha':H,'candidate_tree':T,'implementation_identity':I,
          'changed_path_count':172,'original_pr133_changed_paths_retained_count':len(set(changed)&orig),
          'additional_changed_path_count':len(set(changed)-orig),'unchanged_original_pr133_path_count':len(orig-set(changed)),
          'all_changed_paths_attributed':True,
          'records':[{'path':p,'fixed_main':blob(B,p),'fixed_pr133':blob(S,p),'final_candidate':blob(H,p),
                      'in_original_132_path_verdicts':p in orig,'original_source_decision':verdicts.get(p),
                      'integration_forward_groups':groups[p],'attribution_covered':True} for p in changed],
          'superseded_candidate_sha':P,'superseded_candidate_actual_status':'FAIL',
          'full_applicable_p0':'RUNNING','merge_sha_independent_verification':'NOT_RUN','real_provider':'NOT_RUN'}
(O/'final-candidate-source-coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2)+'\n')
f.update(current_head_sha=H,final_commit_sha=H,final_tree_sha=T,final_implementation_identity=I,
         additional_changed_paths_not_in_original_132=sorted(set(changed)-orig),additional_changed_paths_all_attributed=True,
         final_candidate_coverage={'path':str(O/'final-candidate-source-coverage.json'),'changed_path_count':172,
                                   'original_pr133_changed_count':120,'additional_changed_count':52,'all_attributed':True})
v=d['implementation_verification_status']
v.setdefault('retained_prior_candidate_verification_status',[]).append({
    'candidate_sha':P,'full_applicable_p0':'FAIL','final_pr_governance':'FAIL',
    'prior_recorded_focused_engineering':v.pop('latest_candidate_focused_engineering',None)})
v.update(candidate_sha=H,candidate_tree=T,candidate_implementation_identity=I,
         full_applicable_p0_final_frozen_commit='RUNNING',
         final_pr_governance={'status':'RUNNING','session_id':12128,'log':str(O/'pr-governance-final3.log'),
                              'evidence_directory':str(O/'p0-integration-final3'),'tested_candidate_sha':H,'qualification_upgrade':False},
         directed_complete_migration_compatibility={'status':'RUNNING','session_id':34910,
            'path_count':19,'log':str(O/'migration-compatibility-directed-debug2.log'),'qualification_upgrade':False},
         remaining_implementation='Observe current e1bd3aa complete 19-path directed compatibility and independently running exact-candidate final3 PR governance/P0. Prior final2 FAIL/cleanup PASS remain frozen; current scope passes do not supply final canonical qualification.',
         merge_sha_independent_verification='NOT_RUN',real_provider='NOT_RUN')
proofpath=O/'published-migration-byte-proof.json';proof=json.loads(proofpath.read_text())
assert proof['published_count']==160
for p in proof['files']:
    main=blob(B,p['path']);candidate=blob(H,p['path']);assert main==candidate,p['path']
    p.setdefault('retained_prior_candidate_snapshots',[]).append({'candidate_sha':P,'snapshot':p['final_candidate_snapshot']})
    p['final_candidate_snapshot']=candidate;p['byte_identical']=True
proof.update(candidate_sha=H,candidate_tree=T,all_byte_identical=True)
proofpath.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
d['published_migration_byte_proof'].update(candidate_sha=H,candidate_tree=T)
assert all(d[k]==original[k] for k in protected)
(O/'source-adjudication.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
rpath=O/'proposal-applicability-review.json';r=json.loads(rpath.read_text())
r.setdefault('retained_candidate_projection_history',[]).append(r['final_candidate_projection'])
r['final_candidate_projection'].update(candidate_sha=H,candidate_tree=T,implementation_identity=I,final_p0='RUNNING',
    proposal_index_scope_review=str(O/'proposal-index-scope-review.json'),
    reason='Three proposal source scopes include only the new supporting-index delta and were reviewed at b484551d with f940 identity; remaining decisions/work/dates unchanged. Prompt scope remains exact at 578d59b. No final qualification upgrade.')
for p in r['proposals']:
    text=git('show',H+':'+p['path']).decode();meta=json.loads(re.search(r'<!-- proposal-lifecycle\s*(\{.*?\})\s*-->',text,re.S).group(1))
    p['latest_reviewed_baseline']=meta['reality_baseline'];p['updated_proposal_sha256']=hashlib.sha256(text.encode()).hexdigest()
    assert p['updated_remaining_ids']==[x['id'] for k in ('remaining_decisions','remaining_work') for x in meta[k]]
rpath.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in coverage.items() if k!='records'},ensure_ascii=False,indent=2))
