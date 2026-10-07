import json, hashlib, subprocess
from pathlib import Path
root=Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge');base=Path('/tmp/novel-forge-pr133-audit-20261007');p=base/'implementation/source-adjudication.json';d=json.loads(p.read_text());original=json.loads((base/'implementation/source-adjudication.original-source-verdicts.json').read_text());protected=('files','commits','overlaps','text_conflicts','migrations','counts','fixed_sources')
main=d['fixed_sources']['main'];src=d['fixed_sources']['pr133'];original_paths={x['path'] for x in d['files']}
def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL)
def blob(ref,path):
 try:data=git('show',f'{ref}:{path}')
 except subprocess.CalledProcessError:return None
 return {'git_blob':git('rev-parse',f'{ref}:{path}').decode().strip(),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
def working(path):
 f=root/path
 if not f.exists():return None
 data=f.read_bytes();return {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}
def rec(path):
 before=blob(main,path);now=working(path);changed=now is not None and (before is None or before['sha256']!=now['sha256'])
 return {'path':path,'in_original_132_path_verdicts':path in original_paths,'exists_currently':(root/path).exists(),'fixed_main':before,'fixed_pr133':blob(src,path),'working_snapshot':now,'changed_from_fixed_main':changed,'attribution':'INTEGRATION_FORWARD_FIX' if changed else 'UNCHANGED_REGRESSION_OR_PROTECTION_TARGET','qualification_upgrade':False}
additional=[('canonical_blocked_world_identity','Integration-only correction normalizes the complete immutable World plan through canonical JSON hashing for PostgreSQL JSONB tuple/list representation equivalence. BLOCKED disposition remains mandatory and changing any requirement remains rejected; this correction is not attributed to the original PR133 delta.',['src/novel_forge/modules/story_planning_runtime/world_preparation.py','tests/unit/test_world_causal_preparation.py']),('shared_controlled_provider_fixture_versioning','Integration-only synthetic provider fixture selects Mission v4 and explicit serialization_function only for execution_contract_version 1.19.0; historical requests retain Mission v3. It does not establish actual Provider behavior or qualification.',['tests/integration/synthesis_production_support.py']),('new_native_route_counter_and_fixture_alignment','Additional integration-native receipt construction, cost-router counter semantics and current/frozen bootstrap or applicability fixture references. Existing main-known cases and new identities remain separately testable; no new bypass or proof upgrade.',['src/novel_forge/modules/production_execution/cost_routing.py','src/novel_forge/modules/story_planning_runtime/planning_repair_routing.py','tests/unit/test_cost_aware_routing.py','tests/unit/test_planning_routing_bootstrap.py','tests/unit/test_routing_bootstrap.py','tests/unit/test_work_applicability_binding.py']),('forward_migration_identity_and_history_preflight','Nine historical source migrations receive the new contiguous identities mapped in unchanged original migration evidence. Current runner admits only an exact published prefix before pending DDL; new guard bodies compose main protections. Existing published bodies stay byte-identical.',['src/novel_forge/storage/migrations/runner.py',*['src/novel_forge/storage/migrations/versions/v'+x['new_id']+'.py' for x in d['migrations']]])]
groups=d['integration_forward_fixes']['groups']
for ident,why,paths in additional:
 entry={'id':ident,'rationale':why,'paths':[rec(x) for x in paths]}
 for index,group in enumerate(groups):
  if group['id']==ident:groups[index]=entry;break
 else:groups.append(entry)
# Refresh additive snapshot hashes only. Original source file and commit verdicts remain immutable.
for group in groups:
 for old in group['paths']:
  old['working_snapshot']=working(old['path']);before=old['fixed_main'];now=old['working_snapshot'];old['changed_from_fixed_main']=now is not None and (before is None or before['sha256']!=now['sha256']);old['attribution']='INTEGRATION_FORWARD_FIX' if old['changed_from_fixed_main'] else 'UNCHANGED_REGRESSION_OR_PROTECTION_TARGET'
changed=set(git('diff','--name-only',main).decode().splitlines());mapped={x['path'] for g in groups for x in g['paths']};unmapped=sorted(changed-original_paths-mapped);assert not unmapped,unmapped
d['integration_forward_fixes']['additional_changed_paths_not_in_original_132']=sorted(changed-original_paths)
d['integration_forward_fixes']['additional_changed_paths_all_attributed']=True
assert all(d[k]==original[k] for k in protected)
p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
p=base/'integration-work-package.md';s=p.read_text().replace('原 action/Director 因果证据。','原 action/Director 因果证据；完整 BLOCKED plan 的 canonical JSON identity 允许 JSONB tuple/list 表示差异，任何 requirement 内容变化仍拒绝。');s=s.replace('7. canonical docs、WIRED 拓扑','受控 synthesis fixture 仅按实际 execution_contract_version 1.19 选择 Mission4/serialization_function，历史请求仍为 Mission3；该 fixture 修复与 World canonical identity 修复单独标为 integration-only。\n7. canonical docs、WIRED 拓扑');p.write_text(s)
print(json.dumps({'source_verdicts_unchanged':True,'additional_changed_paths':len(changed-original_paths),'all_attributed':True,'groups':len(groups)}))
