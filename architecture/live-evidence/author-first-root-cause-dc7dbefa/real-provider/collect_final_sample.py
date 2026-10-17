import gzip, hashlib, json, shutil, unicodedata, re
from verify_dispatch import _materialize_production_codex_prompt
from pathlib import Path
T=Path('/Volumes/DevSSD/Development/Workspace/task-data/WP-NF-AUTHOR-FIRST-CONTINUATION-AND-RECOVERY-01')
R=Path('/Users/yuan/.codex/worktrees/author-first-continuation/novel-forge/architecture/live-evidence/author-first-root-cause-dc7dbefa/real-provider')
def sha(b): return 'sha256:'+hashlib.sha256(b).hexdigest()
def han(s): return sum(unicodedata.name(c,'').startswith(('CJK UNIFIED IDEOGRAPH','CJK COMPATIBILITY IDEOGRAPH')) for c in s)
def load(p): return json.loads(p.read_text())
def save(p,d): p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def walk(x):
 if isinstance(x,dict):
  yield x
  for v in x.values(): yield from walk(v)
 elif isinstance(x,list):
  for v in x: yield from walk(v)
D=json.load(gzip.open(R/'actual-dispatch-final-e5.json.gz','rt'))
S=json.load(gzip.open(R/'native-checkpoint-20261017T203244Z.json.gz','rt'))
assets={a['version']['asset_version_id']:a['version'] for a in D['assets']}
effects={e['operation_id']:e for e in D['effects']}
receipts={r['dispatch']['external_effect_id']:r for r in D['receipts']}
materials={a['content']['contract']['materialization_hash']:a['content']['contract'] for a in assets.values() if isinstance(a['content'],dict) and isinstance(a['content'].get('contract'),dict) and 'pack_artifacts' in a['content']['contract']}
proof=load(R/'actual-dispatch-final-e5-dispatch.json'); rows={r['operation_id']:r for r in proof['rows']}
full=load(T/'exports/native-working-chapters-01-05.json'); read=load(T/'read-five-effective.stdout.json')
assert full==read and full['publication']=='NOT_AUTHORIZED' and full['accepted_through_chapter']==0
assert sha(full['text'].encode())==full['text_digest']
expected_md=""
for u in full['units']:
 expected_md+=f"# 第{u['chapter']}章 {u['title']}\n\n{u['text']}\n\n"
 expected_md+=f"版本：{u['asset_version_id']}\n\n状态：{u['manuscript_status']}；审读 {u['review_status']}；质量 {u['quality_status']}；选稿 {u['author_selection']}；正式接纳至第{full['accepted_through_chapter']}章\n\n"
 selection=u['working_selection']
 if selection['status']=='SELECTED':
  expected_md+=f"工作稿选用回执：{selection['asset_version_id']}；{selection['content_hash']}；作者认可 {selection['author_selection']}；正式接纳 {selection['formal_acceptance']}\n\n"
assert (T/'exports/native-working-chapters-01-05.md').read_text()==expected_md
units=[]
for n,u in enumerate(full['units'],1):
 assert u['chapter']==n
 first=load(T/f'exports/chapter-{n:02d}-first-draft.json')['units'][0] if n!=3 else u
 effective=load(T/f'exports/chapter-{n:02d}-effective.json')['units'][0]
 assert effective==u
 for v in [first,u]:
  stored=assets[v['asset_version_id']]
  assert v['content_hash']==stored['content_hash'] and v['text']==stored['content']['text']
  assert v['text_hash']==sha(v['text'].encode()) and v['length']['actual']==han(v['text'])
 first_op=first['asset_version_id'].split(':')[1]
 effect=effects[first_op];evidence=receipts[effect['external_effect_id']]['receipt']['payload']['evidence'];runtime=evidence['capability_runtime']
 prompt,_=_materialize_production_codex_prompt(target_scope=evidence['production_execution']['execution_request']['target_scope'],stage=effect['request_payload']['stage'],inputs=effect['request_payload']['input'],materialization=materials[runtime['materialization_hash']],template_render_contract=runtime.get('template_render_contract','opaque-template-substitution.v1'))
 assert sha(prompt.encode())==rows[first_op]['prompt_hash']
 contracts=[json.JSONDecoder().raw_decode(prompt[m.end():])[0] for m in re.finditer(r'"chapter_generation_length":\s*',prompt)]
 assert contracts and all(c['minimum']==4000 and c['maximum']==5000 for c in contracts)
 assert rows[first_op]['effect_status']=='SUCCEEDED'
 count=han(u['text']);body=u['text'];duplicate_title=body.splitlines()[0]==u['title']
 if duplicate_title: body=body[len(u['title']):].lstrip()
 assert 4000<=han(body)<=5000
 units.append({'chapter':n,'title':u['title'], 'first':{k:v for k,v in first.items() if k!='text'},
  'effective':{k:v for k,v in u.items() if k!='text'},'native_text_han':count,'prose_body_han':han(body),
  'leading_title_in_native_text':duplicate_title,'original_and_effective_text_preserved':True,
  'first_writer_operation':first_op,'actual_first_writer_input_hash':rows[first_op]['prompt_hash'],
  'actual_first_writer_length_contracts':contracts,'native_revision_used':n!=3})
assert [u['first']['length']['actual'] for u in units]==[3802,3988,4102,3799,3620]
assert [u['native_text_han'] for u in units]==[4424,4467,4102,4304,4406]
book,=S['tables']['authority_book_production']; design=assets[book['book_design_version']]
assert design['content']['target_chapters']==600
assert book['state']=='PAUSED' and book['version']==39 and book['current_chapter']==5 and book['target_chapter_count']==100
assert book['accepted_through_chapter']==0 and book['active_chapter_number'] is None
packs=[]
for activation in S['tables']['authority_capability_pack_activation']:
 if activation['pack_id'].split('.')[0] not in ['story_planning_pack','chapter_generation_pack']:continue
 deployment,=[x for x in S['tables']['authority_capability_pack_deployment'] if x['deployment_id']==activation['active_deployment_id']]
 compilation,=[x for x in S['tables']['authority_capability_pack_compilation'] if x['compilation_id']==deployment['compilation_id']]
 assert compilation['release_sha']=='e5f1da7d1649610370500d960cad4e06083c69d9'
 packs.append({'activation':activation,'deployment':deployment,'compilation':compilation})
assert len(packs)==2
out=R/'final-exports';out.mkdir(exist_ok=True); export_files=[]
for f in sorted((T/'exports').glob('*')):
 if f.suffix not in ['.json','.md']:continue
 dest=out/f.name
 if dest.exists():assert dest.read_bytes()==f.read_bytes()
 else: shutil.copyfile(f,dest)
 export_files.append({'path':'final-exports/'+f.name,'sha256':sha(dest.read_bytes()),'bytes':dest.stat().st_size})
for f in T.glob('final-real-audits*.log'):shutil.copyfile(f,R/f.name)
for name in ['verify_real_history.py','verify_unknown_isolation.py','check_real_working_sources.py','verify_local_memo.py','collect_final_sample.py']:
 shutil.copyfile(T/'execution-checks'/name,R/name)
argv=load(T/'manuscript-round-05.command.json')['argv'];argv[argv.index('--stop-after-chapter')+1]='6'
report={'status':'PASS_SCOPED_REAL_NATIVE_SAMPLE','evidence_state':'EXECUTABLE','production_proven':False,
 'source_runtime':'MIXED_EXACT_PER_PROCESS_METADATA','manuscript_source_sha':'e5f1da7d1649610370500d960cad4e06083c69d9',
 'book':{k:book[k] for k in ['book_run_id','book_id','project_id','workspace_id','version','state','current_chapter','accepted_through_chapter','target_chapter_count','input_snapshot_id','root_operation_id','saga_id']},
 'book_design':{'asset_version_id':design['asset_version_id'],'content_hash':design['content_hash'],'schema_version':design['schema_version'],'full_book_target':600},
 'delivered_sample_chapters':5,'initial_delivery_window':100,'chapters_not_delivered_in_initial_window':95,'full_book_target':600,
 'unit':'HAN_CHARACTERS_V1','first_draft_han':[u['first']['length']['actual'] for u in units],
 'effective_native_text_han':[u['native_text_han'] for u in units], 'effective_prose_body_han':[u['prose_body_han'] for u in units],
 'effective_native_text_han_total':sum(u['native_text_han'] for u in units),'effective_prose_body_han_total':sum(u['prose_body_han'] for u in units),
 'all_originals_saved':True,'all_effective_versions_saved_read_and_exactly_exported':True,'technical_working_selections':[1,2,4,5],
 'author_selection':'NOT_GRANTED','formal_acceptance':'NOT_GRANTED','quality_status':'NOT_VERIFIED',
 'natural_groups':[[1,4],[5,8]],'actual_cross_group_input':'cross-group-preparation-actual-input.json',
 'actual_dispatch':{k:v for k,v in proof.items() if k!='rows'},'local_memo':'actual-dispatch-final-e5-local-memo.json',
 'book_owner_source_resolution':'actual-book-source-resolution.json','history_preservation':'history-preservation-final-e5.json',
 'unknown_isolation':'unknown-isolation-final.json','packs':packs,'units':units,'exports':export_files,
 'readback_observations':[
  {'chapter':1,'evidence':'先撤人、取回工具、封住旧路；绳索骤紧后许照川改变发力并检查膝伤，行动产生约束。'},
  {'chapter':2,'evidence':'清理后保留仍承力的旧石，并发现湿缝；承接前章损绳和封路，没有重演撤人。'},
  {'chapter':3,'evidence':'宋既明分配缺水下的劳力和水，许照川送水后带回撑木新绳；进展由清理转到资源调配。'},
  {'chapter':4,'evidence':'使用前章带回材料搭成局部作业撑台；手疼改变握法和交接，暂留不平边换取稳固落座，只开小口而未通水。'},
  {'chapter':5,'evidence':'承接已成撑台，更换松散填料、补石收缝；发现表面填实而内有空隙后返工，完成首段转看下游，水仍未开。'},
 ],
 'remaining_prose_issues':['Four of five first Drafts under target; native revisions are effective samples, not first-pass stability.','Chapter5 native text repeats its 5-Han title; preserved exactly, prose body is 4401 Han.','Tools, work procedure, cleanup and rest remain dense/repetitive; cultivation conflict and sustained reader pull are not qualified.'],
 'formal_P0':'NOT_RUN','full_254_matrix':'NOT_RUN','production_qualification':'NOT_RUN','long_form_literary_qualification':'NOT_RUN',
 'transport_root_cause':'Observed CLI network response-body stream decoding failures; network component and 900s duration cause unresolved; token-limit cause NOT_OBSERVED.',
 'resume':{'status':'NOT_RUN_NEXT_STEP','checkpoint_book_version':39,'next_chapter':6,'cwd':'/Users/yuan/.codex/worktrees/author-first-continuation/novel-forge',
  'environment_json':str(T/'runtime.input-only-e5f1da7d.private.json'),'argv':argv,'semantics':'Ordinary manuscript continue resumes same Book and pauses after chapter6; initial delivery window remains100. UNKNOWN reconciliation uses existing owning isolation, never blind resubmission.'},
 'audit_corrections':{'logs':['final-real-audits.log','final-real-audits-02.log','final-real-audits-03.log','final-real-audits-04.log'],
  'timestamp':'All Book fields checked; created_at/updated_at compare timezone-aware identical instants, not serialization text.',
  'pack_lifecycle':'Exactly two original compiled Pack versions became SUPERSEDED through native e5 compilation/activation; all other old asset fields and all1594 content identities unchanged.',
  'old_capture':'Before snapshot did not include Pack compilation table; original version bytes bind old compilation content, final snapshot contains old and successor registration rows.'}}
save(R/'final-sample.json',report)
print('PASS',len(units),'effective chapters;',len(export_files),'exact files;',sum(u['prose_body_han'] for u in units),'prose Han')
