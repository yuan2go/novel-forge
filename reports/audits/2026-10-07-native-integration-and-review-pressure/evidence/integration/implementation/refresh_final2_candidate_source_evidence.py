import hashlib
import json
import subprocess
from functools import cache
from pathlib import Path

REPO = Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge')
OUT = Path('/tmp/novel-forge-pr133-audit-20261007/implementation')
BASE = 'f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609'
SOURCE = 'ad1c229d4b17db45fa14c73dcc6569e8655c82c9'
PREVIOUS = 'cc85a91b9ccfb3b700b39134c07e7931a3efd8d3'
HEAD = '042f44671ad4f7c47eb7cd0b69d1ff226e116aa2'
TREE = '2f7dd40de56f5dd9b4b1ac33f5848bb4737562d8'
IDENTITY = 'sha256:acd05223f7948cf6ab11a09040067c35992acd421efc6b14dc1896506fb70c85'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO)


@cache
def blob(commit, path):
    ref = f'{commit}:{path}'
    if subprocess.run(['git', 'cat-file', '-e', ref], cwd=REPO,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        return None
    raw = git('show', ref)
    return {'git_blob': git('rev-parse', ref).decode().strip(),
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


assert git('rev-parse', 'HEAD').decode().strip() == HEAD
assert git('rev-parse', HEAD+'^{tree}').decode().strip() == TREE
assert not git('status', '--porcelain').strip()
assert set(git('diff', '--name-only', PREVIOUS, HEAD).decode().splitlines()) == {
    'architecture/reality-evidence.json', 'tests/integration/test_creation_cli_postgres.py'}
for name in ('source-adjudication.json', 'published-migration-byte-proof.json',
             'final-candidate-source-coverage.json', 'proposal-applicability-review.json'):
    p = OUT / name
    retained = p.with_name(p.stem + '.candidate-cc85a91.json')
    if not retained.exists():
        retained.write_bytes(p.read_bytes())

d = json.loads((OUT / 'source-adjudication.json').read_text())
original = json.loads((OUT / 'source-adjudication.original-source-verdicts.json').read_text())
preserved = ('files','commits','overlaps','text_conflicts','migrations','counts','fixed_sources')
assert all(d[k] == original[k] for k in preserved)
old_report = OUT / 'p0-integration-final' / ('pr-governance-'+PREVIOUS+'.json')
interruption_path = OUT / 'p0-integration-final/interruption-observation.json'
old_prgov = json.loads(old_report.read_text())
interruption = json.loads(interruption_path.read_text())
assert old_prgov['status'] == 'FAIL' and interruption['canonical_p0_final_report'] == 'NOT_PRODUCED'
old_attempt = {'candidate_sha': PREVIOUS,
               'candidate_tree': '84a0aa0efe2f56f58053291840ddd3484140198c',
               'status_at_prior_snapshot': 'RUNNING', 'actual_pr_governance_status': 'FAIL',
               'canonical_p0_final_report': 'NOT_PRODUCED',
               'interruption_reason': interruption['reason'],
               'interruption_observation': str(interruption_path),
               'pr_governance_report': str(old_report),
               'owned_postgresql_or_compose_start': 'NOT_RUN',
               'child_group_cleanup': 'PARENT_CONFIRMED_CLEANED',
               'separate_historical_fixture_run': {
                   'status': '1_PASS_1_FAIL', 'seconds': 234.84,
                   'log': '/tmp/pr133-planning/test-creation-historical-world-current.log',
                   'failure': 'DEAD_LETTER historical classifier restoration flag false after successful Book completion; not a retrospective PASS'},
               'superseded_by_candidate_sha': HEAD}
d.setdefault('candidate_attempt_history', []).append(old_attempt)

f = d['integration_forward_fixes']
for group in f['groups']:
    for p in group['paths']:
        p.setdefault('retained_prior_candidate_snapshots', []).append({
            'candidate_sha': PREVIOUS, 'snapshot': p.get('final_candidate_snapshot')})
        p['final_candidate_snapshot'] = blob(HEAD, p['path'])
        p['final_candidate_sha'] = HEAD
        p['exists_in_final_candidate'] = p['final_candidate_snapshot'] is not None
        p['changed_from_fixed_main'] = p['final_candidate_snapshot'] != blob(BASE, p['path'])
    if group['id'] == 'fixed_main_historical_world_classifier_fixture_scope':
        group['rationale'] += ' Final2 corrects only the test boundary: capture the real DEAD_LETTER source after three historical failed attempts and restore current classification at the native result-repair owner boundary before successor mutation. Existing immutable full-row snapshots and all native source/counter/final-Book assertions remain.'
        group['retained_prior_verification'] = old_attempt['separate_historical_fixture_run']
        group['final_candidate_verification'] = {
            'status': 'PASS', 'count': 1, 'seconds': 107.86,
            'candidate_sha': HEAD, 'scope': 'historical DEAD_LETTER-only controlled PostgreSQL fixture',
            'log': '/tmp/pr133-planning/test-creation-historical-deadletter-boundary2.log',
            'qualification_upgrade': False, 'real_provider': 'NOT_RUN'}

changed = sorted(git('diff','--name-only',BASE,HEAD).decode().splitlines())
assert len(changed) == 171
original_paths = {p['path'] for p in d['files']}
extra = sorted(set(changed)-original_paths)
groups = {p: [g['id'] for g in f['groups'] if p in {x['path'] for x in g['paths']}] for p in changed}
assert all(p in original_paths or groups[p] for p in changed)
verdicts = {p['path']:p['decision'] for p in d['files']}
coverage = {'base_sha':BASE,'candidate_sha':HEAD,'candidate_tree':TREE,
            'implementation_identity':IDENTITY,'changed_path_count':171,
            'original_pr133_changed_paths_retained_count':len(set(changed)&original_paths),
            'additional_changed_path_count':len(extra),
            'unchanged_original_pr133_path_count':len(original_paths-set(changed)),
            'all_changed_paths_attributed':True,
            'records':[{'path':p,'fixed_main':blob(BASE,p),'fixed_pr133':blob(SOURCE,p),
                        'final_candidate':blob(HEAD,p),'in_original_132_path_verdicts':p in original_paths,
                        'original_source_decision':verdicts.get(p),'integration_forward_groups':groups[p],
                        'attribution_covered':True} for p in changed],
            'superseded_candidate_sha':PREVIOUS, 'superseded_candidate_actual_status':'FAIL',
            'full_applicable_p0':'RUNNING','merge_sha_independent_verification':'NOT_RUN','real_provider':'NOT_RUN'}
(OUT/'final-candidate-source-coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2)+'\n')
f.update(snapshot_kind='FROZEN_CANDIDATE_COMMIT',current_head_sha=HEAD,final_commit_sha=HEAD,
         final_tree_sha=TREE,final_implementation_identity=IDENTITY,
         additional_changed_paths_not_in_original_132=extra,
         final_candidate_coverage={'path':str(OUT/'final-candidate-source-coverage.json'),
                                   'changed_path_count':171,'original_pr133_changed_count':120,
                                   'additional_changed_count':51,'all_attributed':True})
v=d['implementation_verification_status']
v.update(candidate_sha=HEAD,candidate_tree=TREE,candidate_implementation_identity=IDENTITY,
         full_applicable_p0_final_frozen_commit='RUNNING',
         final_pr_governance={'status':'RUNNING','session_id':15993,
                              'log':str(OUT/'pr-governance-final2.log'),
                              'evidence_directory':str(OUT/'p0-integration-final2'),
                              'tested_candidate_sha':HEAD,'qualification_upgrade':False},
         latest_candidate_focused_engineering={'status':'PASS','count':1287,'seconds':29.24,
                                               'candidate_sha':HEAD,'scope':'PR governance focused fixture/unit paths only',
                                               'log':str(OUT/'pr-governance-final2.log'),'qualification_upgrade':False},
         latest_historical_deadletter_scope={'status':'PASS','count':1,'seconds':107.86,
                                             'candidate_sha':HEAD,'scope':'historical DEAD_LETTER-only PostgreSQL controlled fixture',
                                             'log':'/tmp/pr133-planning/test-creation-historical-deadletter-boundary2.log',
                                             'qualification_upgrade':False},
         remaining_implementation='Observe exact 042f446 final2 canonical P0 and actual final PR governance report/cleanup. cc85 interrupted P0 produced no canonical report and its PR governance is FAIL; it is retained separately, never upgraded by the new run.',
         merge_sha_independent_verification='NOT_RUN',real_provider='NOT_RUN')

proofpath=OUT/'published-migration-byte-proof.json'
proof=json.loads(proofpath.read_text())
assert proof['published_count']==160
for p in proof['files']:
    baseline = blob(BASE,p['path'])
    current = blob(HEAD,p['path'])
    assert baseline == current, p['path']
    p.setdefault('retained_prior_candidate_snapshots',[]).append({'candidate_sha':PREVIOUS,'snapshot':p.get('final_candidate_snapshot')})
    p['final_candidate_snapshot']=current
    p['byte_identical']=True
proof.update(candidate_sha=HEAD,candidate_tree=TREE,all_byte_identical=True,
             comparison_kind='FIXED_MAIN_VS_FROZEN_CANDIDATE_COMMIT')
proofpath.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
d['published_migration_byte_proof'].update(candidate_sha=HEAD,candidate_tree=TREE)
assert all(d[k]==original[k] for k in preserved)
(OUT/'source-adjudication.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
rpath=OUT/'proposal-applicability-review.json'
r=json.loads(rpath.read_text())
r.setdefault('retained_candidate_projection_history',[]).append(r['final_candidate_projection'])
r['final_candidate_projection'].update(candidate_sha=HEAD,candidate_tree=TREE,
                                      implementation_identity=IDENTITY,final_p0='RUNNING')
rpath.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in coverage.items() if k!='records'},ensure_ascii=False,indent=2))
