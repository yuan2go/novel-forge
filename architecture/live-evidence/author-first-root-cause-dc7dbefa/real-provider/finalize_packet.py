import gzip,hashlib,json,shutil,subprocess
from pathlib import Path
T=Path('/Volumes/DevSSD/Development/Workspace/task-data/WP-NF-AUTHOR-FIRST-CONTINUATION-AND-RECOVERY-01')
W=Path('/Users/yuan/.codex/worktrees/author-first-continuation/novel-forge'); R=W/'architecture/live-evidence/author-first-root-cause-dc7dbefa'
def load(p):return json.loads(p.read_text())
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def git(*a,cwd=W):return subprocess.check_output(['git',*a],cwd=cwd)
def sha(b):return 'sha256:'+hashlib.sha256(b).hexdigest()
base='e5f1da7d1649610370500d960cad4e06083c69d9'; docs='ff2049d37d550fd505715e0e6db8d2b4516d6501'
assert git('rev-parse','HEAD').decode().strip()==docs
assert git('diff','--name-only',base,docs).decode().splitlines()==['docs/runtime-operations.md']
def tree(ref,exclude_doc=False):
 return b'\n'.join(row for row in git('ls-tree','-r','--full-tree',ref).splitlines() if b'\tarchitecture/live-evidence/' not in row and (not exclude_doc or not row.endswith(b'\tdocs/runtime-operations.md')))+b'\n'
assert tree(base,True)==tree(docs,True)
fingerprint={'runtime_source_sha':base,'operator_document_sha':docs,'runtime_tree_sha256_excluding_evidence_and_exact_operator_doc':sha(tree(base,True)),
 'excluded_paths':['architecture/live-evidence/','docs/runtime-operations.md'],'all_other_tracked_paths_byte_identical':True,
 'final_non_evidence_baseline_sha':docs,'final_non_evidence_tree_sha256':sha(tree(docs)),
 'only_additional_non_evidence_change':'docs/runtime-operations.md: historical generation retry ceiling is not current policy; stage repair allowance unchanged.'}
save(R/'source-boundary.json',fingerprint)
for source,name in [(T/'execution-checks/final-doc-sync.json','final-doc-sync.json'),(T/'execution-checks/final-doc-sync.log','final-doc-sync.log'),(T/'execution-checks/final-doc-fitness.log','final-doc-fitness.json')]:
 assert load(source)['status']=='PASS' if source.suffix=='.json' or name.endswith('.json') else True
 shutil.copyfile(source,R/'checks'/name)
for f in T.glob('final-sample-collection*.log'):shutil.copyfile(f,R/'real-provider'/f.name)
for f in [T/'execution-checks/finalize_packet.py',T/'execution-checks/collect_final_sample.py']:
 shutil.copyfile(f,R/'real-provider'/f.name)
sample=load(R/'real-provider/final-sample.json'); control=load(R/'real-provider/medium-template-successor.stdout.json')
idx=load(R/'index.json');idx['task_status']='SCOPED_REPAIRS_AND_FIVE_CHAPTER_REAL_NATIVE_SAMPLE_COMPLETED';idx['operator_document_sha']=docs
idx['root_findings']['generation_retry_document']={'classification':'STALE_CURRENT_DOC_CORRECTED_ff2049d3','current_generation_cumulative_ban':False,'frozen_stage_repair_allowances':'UNCHANGED','counter_reset':False}
old=idx['runtime_source_fingerprint'];old['reason']='Historical pre-doc-sync fingerprint retained; current exact runtime/operator-doc boundary is source-boundary.json.'
idx['source_boundary']='source-boundary.json';idx['file_manifest']='file-manifest.json';idx['final_sample']='real-provider/final-sample.json'
r=idx['real_provider'];r.update({'current_stage':'PAUSED_AFTER_FIVE_SAVED_EFFECTIVE_CHAPTERS','completed_real_chapters':5,'unknown_historical_calls':9,'normal_length_real_chapters':5,
 'first_draft_han':sample['first_draft_han'],'effective_han':sample['effective_native_text_han'],'effective_prose_body_han':sample['effective_prose_body_han'],
 'book_version':39,'current_chapter':5,'next_chapter':6,'state':'PAUSED','effective_prose_body_han_total':21698,
 'latest_network_recovery':'real-provider/unknown-isolation-final.json','actual_dispatch_final':'real-provider/actual-dispatch-final-e5-dispatch.json',
 'local_memo_final':'real-provider/actual-dispatch-final-e5-local-memo.json','book_source_resolution_final':'real-provider/actual-book-source-resolution.json',
 'history_preservation':'real-provider/history-preservation-final-e5.json','exports':'real-provider/final-exports/native-working-chapters-01-05.json',
 'template_control_operation_id':control['operation_id'],'template_policy_hash':control['policy_hash'],'template':control['policy']['execution_templates'][0],
 'unresolved_transport':'Five Writer failures have actual stream network/body decoding errors; isolation and native linked successors recovered. Upstream component and approximately900s duration cause remain unresolved; token limit cause NOT_OBSERVED.',
 'sample_boundary':'Five effective chapters, four native revisions; not100 chapters, stable first-pass length or long-form literary qualification.'})
idx['checks']['final_real_audits']={'runtime_source_sha':base,'actual_prompt_process_hash_matches':92,'successful':83,'unknown':9,'working_source_occurrences':116,
 'local_memos':5,'local_memo_source_occurrences':10,'book_owner_source_resolutions':126,'old_asset_versions_preserved':1594,'old_terminal_effects_preserved':59,
 'native_compilation_lifecycle_transitions':2,'unknown_commit_rights_revoked_and_accounting_retained':9,'exact_export_files':20,'chapters':5,'accepted_through_chapter':0,'status':'PASS'}
idx['checks']['final_operator_document']={'source_sha':docs,'documentation':'PASS','architecture_fitness_and_subordinate_manifests':'PASS','raw':'checks/final-doc-sync.json'}
save(R/'index.json',idx)
f=load(R/'failure-classification.json');f['operator_document_sha']=docs
for issue in f['issues']:
 if issue['id']=='B':issue['recheck']='PASS current native Creation Book/cast scope, all five local Memo preparations, 126 same-Book past-chapter source resolutions (116 actual Provider occurrences +10 local Memo); exact version/hash/status verified.';issue['evidence']+=['real-provider/actual-book-source-resolution.json']
 if issue['id']=='D':issue['evidence']+=['real-provider/unknown-isolation-final.json','real-provider/history-preservation-final-e5.json']
 if issue['id']=='E':issue['evidence']+=['real-provider/final-sample.json','real-provider/final-exports/native-working-chapters-01-05.json']
f['real_provider_status']='SCOPED_REAL_NATIVE_SAMPLE_COMPLETE_FIVE_EFFECTIVE_CHAPTERS_CROSS_GROUP_EXPORT_READBACK_ACCEPTED0'
f['real_provider_final_sample']='real-provider/final-sample.json';f['real_provider_network_failures'] +=[
 {'chapter':4,'old_operation':'3a90542e-985a-4fbf-96f6-6170bb6970fb','saved_successor':'d80359d5-5bd4-4f03-82b8-2c16628d1168','evidence':'real-provider/chapter-04-network-recovery-completed.json.gz'},
 {'chapter':5,'old_operations':['6e6a32f7-cd51-4cdc-bbc5-ca51aa04c9cf','cf59d8b5-8b5e-4e3f-b884-66b7e238d2a9'],'saved_successor':'2f10604b-da70-49cd-86d6-c187cb32cfad','evidence':'real-provider/unknown-isolation-final.json'}]
f['remaining_unresolved']=['Five-chapter sample is not100-chapter delivery.','Four first Drafts underlength; native revision passed4000–5000, first-pass stability unqualified.','Actual network transport failures recovered; lower-level network cause unresolved.','Chapter5 duplicate title and procedural repetition remain in exact model manuscripts.','Formal P0/full matrix, production and literary qualification NOT_RUN.']
save(R/'failure-classification.json',f)
original=Path('/Volumes/DevSSD/Development/Workspace/projects/novel-forge');status=git('status','--porcelain=v1','-z',cwd=original)
assert git('rev-parse','HEAD',cwd=original).decode().strip()=='ceb69fa2ff1c56f07005154bb5797616e933e8c2'
assert len(status.split(b'\0'))-1==54
save(R/'workspace-preservation-final.json',{'head':'ceb69fa2ff1c56f07005154bb5797616e933e8c2','branch':git('branch','--show-current',cwd=original).decode().strip(),'status_entries':54,'status_sha256':sha(status),'status':status.decode().split('\0')[:-1],'method':'All mutations used isolated attached worktrees; original checkout was never reset or merged.'})
remote=git('ls-remote','origin','refs/heads/main','refs/heads/codex/wp-nf-author-first-continuation-01').decode()
assert '9f41f0c75108f708a9a77e6c8da89826cf00987e\trefs/heads/main' in remote
pr182=json.loads(subprocess.check_output(['gh','pr','view','182','--json','number,state,mergedAt,mergeCommit'],cwd=W));assert pr182['state']=='MERGED'
pr183=json.loads(subprocess.check_output(['gh','pr','view','183','--json','number,state,isDraft,headRefOid,url'],cwd=W));assert pr183['isDraft'] and pr183['state']=='OPEN'
save(R/'remote-final-before-evidence-push.json',{'ls_remote':remote,'pr182':pr182,'pr183_before_push':pr183,'main_merged_by_task':False})
env=load(T/'runtime.input-only-e5f1da7d.private.json'); secrets={k:v.encode() for k,v in env.items() if any(s in k for s in ['SECRET','PASSWORD','API_KEY','ACCESS_TOKEN']) and isinstance(v,str) and len(v)>=8}
hits=[];count=0
for p in R.rglob('*'):
 if not p.is_file():continue
 data=gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes();count+=1
 for key,value in secrets.items():
  if value in data:hits.append({'path':str(p.relative_to(R)),'environment_key_name':key})
save(R/'checks/private-value-scan.json',{'status':'PASS' if not hits else 'FAIL','files_scanned':count,'configured_private_values_checked':len(secrets),'hits':hits,'actual_secret_values_printed':False,'not_a_general_security_qualification':True})
assert not hits,hits
manifest=[]
for p in sorted(R.rglob('*')):
 if p.is_file() and p.name!='file-manifest.json':manifest.append({'path':str(p.relative_to(R)),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
save(R/'file-manifest.json',{'version':'scoped-evidence-file-manifest.v1','excludes':['file-manifest.json'],'files':manifest})
print('FINAL',len(manifest),'hashed files; private values absent; source/Book/history boundaries PASS')
