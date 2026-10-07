import hashlib
import json
import re
import subprocess
from pathlib import Path

REPO = Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge')
OUT = Path('/tmp/novel-forge-pr133-audit-20261007/implementation')
BASE = 'f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609'
SOURCE = 'ad1c229d4b17db45fa14c73dcc6569e8655c82c9'
HEAD = 'cc85a91b9ccfb3b700b39134c07e7931a3efd8d3'
TREE = '84a0aa0efe2f56f58053291840ddd3484140198c'
IDENTITY = 'sha256:1a8d8a9e564a78593064a8398a3d78cfe2101ffcb1565bf6e69c477e6aa3d499'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO)


def blob(commit, path):
    ref = f'{commit}:{path}'
    exists = subprocess.run(['git', 'cat-file', '-e', ref], cwd=REPO,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not exists:
        return None
    raw = git('show', ref)
    return {'git_blob': git('rev-parse', ref).decode().strip(),
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


assert git('rev-parse', HEAD + '^{tree}').decode().strip() == TREE
assert git('rev-parse', 'HEAD').decode().strip() == HEAD
assert not git('status', '--porcelain').strip()
path = OUT / 'source-adjudication.json'
proofpath = OUT / 'published-migration-byte-proof.json'
for original_path in (path, proofpath):
    retained = original_path.with_name(original_path.stem + '.pre-final-candidate-snapshot.json')
    if not retained.exists():
        retained.write_bytes(original_path.read_bytes())

d = json.loads(path.read_text())
original = json.loads((OUT / 'source-adjudication.original-source-verdicts.json').read_text())
preserved_keys = ('files', 'commits', 'overlaps', 'text_conflicts', 'migrations', 'counts', 'fixed_sources')
for key in preserved_keys:
    assert d[key] == original[key], key

changed = sorted(git('diff', '--name-only', BASE, HEAD).decode().splitlines())
original_paths = {f['path'] for f in d['files']}
f = d['integration_forward_fixes']
proposal_paths = [p for p in changed if p.startswith('architecture/proposals/')]
assert len(proposal_paths) == 4
f['groups'].append({
    'id': 'reviewed_existing_proposal_current_checkpoint',
    'rationale': 'Current-only applicability review of the four existing PARTIALLY_IMPLEMENTED proposals binds the genuinely reviewed implementation checkpoint 578d59b... and its exact declared source/config scope. Native BookEdition implementation resolves retrospective-correction implementation direction; six remaining industrial decisions and current-release/real-editorial qualification remain. Other pending design, real Provider, literary and full P0 work and original decision-free dates remain. This is a checked metadata/prose projection, not PR133 source delta or qualification promotion.',
    'paths': [{'path': p, 'in_original_132_path_verdicts': p in original_paths,
               'fixed_main': blob(BASE, p), 'fixed_pr133': blob(SOURCE, p),
               'attribution': 'INTEGRATION_CURRENT_PROJECTION_REVIEW',
               'qualification_upgrade': False} for p in proposal_paths],
    'focused_check': {'status': 'PASS', 'scope': 'four existing proposal lifecycle records only',
                      'log': str(OUT / 'proposal-reviewed-checkpoint-check.json')},
})
f['groups'].append({
    'id': 'fixed_main_historical_world_classifier_fixture_scope',
    'rationale': 'Controlled legacy World retry/dead-letter fixtures classify only marked historical error objects according to fixed main f9e1ee5...; snapshot original failed attempts, successful effects and SETTLED reservations, then restore current classifier before repair. Current errors remain FINAL_FAILURE. Original history/receipts must be unchanged. This is historical fixture construction, not new runtime policy or a real Provider qualification.',
    'paths': [{'path': 'tests/integration/test_creation_cli_postgres.py',
               'in_original_132_path_verdicts': True,
               'fixed_main': blob(BASE, 'tests/integration/test_creation_cli_postgres.py'),
               'fixed_pr133': blob(SOURCE, 'tests/integration/test_creation_cli_postgres.py'),
               'attribution': 'INTEGRATION_HISTORICAL_FIXTURE_ALIGNMENT',
               'qualification_upgrade': False}],
    'final_candidate_verification': 'RUNNING_PARENT_OWNED_POSTGRES_NODES_NO_PASS_CLAIM',
})
for group in f['groups']:
    for record in group['paths']:
        if 'working_snapshot' in record:
            record['retained_pre_final_working_snapshot'] = record.pop('working_snapshot')
        record['final_candidate_snapshot'] = blob(HEAD, record['path'])
        record['exists_in_final_candidate'] = record['final_candidate_snapshot'] is not None
        record['final_candidate_sha'] = HEAD
        record['changed_from_fixed_main'] = record['final_candidate_snapshot'] != blob(BASE, record['path'])

attributed = {p['path'] for group in f['groups'] for p in group['paths']}
extra = sorted(set(changed) - original_paths)
assert not (set(extra) - attributed)
final_records = []
verdicts = {p['path']: p for p in d['files']}
for p in changed:
    groups = [g['id'] for g in f['groups'] if p in {x['path'] for x in g['paths']}]
    final_records.append({'path': p, 'fixed_main': blob(BASE, p),
                          'fixed_pr133': blob(SOURCE, p), 'final_candidate': blob(HEAD, p),
                          'in_original_132_path_verdicts': p in original_paths,
                          'original_source_decision': verdicts[p]['decision'] if p in verdicts else None,
                          'integration_forward_groups': groups,
                          'attribution_covered': p in original_paths or bool(groups)})
coverage = {'base_sha': BASE, 'candidate_sha': HEAD, 'candidate_tree': TREE,
            'implementation_identity': IDENTITY,
            'changed_path_count': len(changed), 'original_pr133_changed_paths_retained_count': len(set(changed) & original_paths),
            'additional_changed_path_count': len(extra),
            'unchanged_original_pr133_path_count': len(original_paths - set(changed)),
            'all_changed_paths_attributed': all(p['attribution_covered'] for p in final_records),
            'records': final_records, 'full_applicable_p0': 'RUNNING',
            'merge_sha_independent_verification': 'NOT_RUN', 'real_provider': 'NOT_RUN'}
(OUT / 'final-candidate-source-coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + '\n')
f.update(snapshot_kind='FROZEN_CANDIDATE_COMMIT', current_head_sha=HEAD,
         final_commit_sha=HEAD, final_tree_sha=TREE, final_implementation_identity=IDENTITY,
         additional_changed_paths_not_in_original_132=extra,
         additional_changed_paths_all_attributed=True,
         final_candidate_coverage={'path': str(OUT / 'final-candidate-source-coverage.json'),
                                   'changed_path_count': len(changed), 'original_pr133_changed_count': len(set(changed) & original_paths),
                                   'additional_changed_count': len(extra), 'all_attributed': True})
v = d['implementation_verification_status']
v.update(snapshot_kind='FROZEN_CANDIDATE_COMMIT', candidate_sha=HEAD, candidate_tree=TREE,
         candidate_implementation_identity=IDENTITY,
         full_applicable_p0_final_frozen_commit='RUNNING',
         final_pr_governance={'status': 'RUNNING', 'session_id': 92977,
                              'log': str(OUT / 'pr-governance-final.log'),
                              'tested_candidate_sha': HEAD, 'qualification_upgrade': False},
         remaining_implementation='Candidate committed. Observe parent-owned legacy World PostgreSQL nodes and complete canonical PR governance/P0 report; preserve failures and cleanup evidence before any replacement PR or merge validation claim.',
         merge_sha_independent_verification='NOT_RUN', real_provider='NOT_RUN')

published = [p for p in git('ls-tree', '-r', '--name-only', BASE,
                           'src/novel_forge/storage/migrations/versions').decode().splitlines()
             if re.search(r'/v[^/]+\.py$', p)]
assert len(published) == 160
proof = json.loads(proofpath.read_text())
records = {p['path']: p for p in proof['files']}
assert set(records) == set(published)
for p in published:
    assert blob(BASE, p) == blob(HEAD, p), p
    records[p]['final_candidate_snapshot'] = blob(HEAD, p)
    records[p]['byte_identical'] = True
proof.update(candidate_sha=HEAD, candidate_tree=TREE,
             comparison_kind='FIXED_MAIN_VS_FROZEN_CANDIDATE_COMMIT',
             all_byte_identical=True,
             previous_snapshot_retained=str(OUT / 'published-migration-byte-proof.pre-final-candidate-snapshot.json'))
proofpath.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
d['published_migration_byte_proof'].update(candidate_sha=HEAD, candidate_tree=TREE,
                                          comparison_kind='FIXED_MAIN_VS_FROZEN_CANDIDATE_COMMIT')
for key in preserved_keys:
    assert d[key] == original[key], key
path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: v for k, v in coverage.items() if k != 'records'}, ensure_ascii=False, indent=2))
