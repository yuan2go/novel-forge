import sys,os,pathlib,json,hashlib,socket,subprocess,builtins,io,re,ast
A=pathlib.Path(__file__).parent;R=A/'main';E=A/'evidence';E.mkdir(exist_ok=True);sys.dont_write_bytecode=True;sys.path.insert(0,str(R/'src'))
def deny(*a,**k):raise RuntimeError('AUDIT_EXTERNAL_IO_BLOCKED')
socket.socket.connect=deny;socket.socket.connect_ex=deny;socket.create_connection=deny;subprocess.Popen=deny;os.system=deny
orig=builtins.open;iorig=io.open
def wrap(fn):
 def f(path,mode='r',*a,**k):
  if isinstance(path,(str,bytes,os.PathLike)) and any(x in mode for x in 'wax+'):
   p=pathlib.Path(path).resolve()
   if A not in p.parents or R==p or R in p.parents:raise RuntimeError('AUDIT_WRITE_BLOCKED')
  return fn(path,mode,*a,**k)
 return f
builtins.open=wrap(orig);io.open=wrap(iorig)
import psycopg
psycopg.connect=deny;psycopg.Connection.connect=deny
from novel_forge.modules.capability_packs.artifacts import default_chapter_artifact_resolver,artifact_content_hash
from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile,build_narrative_evaluation_pack_profile,build_longform_prose_review_pack_profile
from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
from novel_forge.modules.chapter_authority.prompt_methods import project_skill_method
from novel_forge.modules.chapter_authority.chapter_plan_views import qualification_profile_for_plan,build_draft_plan_view
from novel_forge.modules.story_planning_runtime.foundation_generation import foundation_task,foundation_output_schema,FOUNDATION_GENERATORS
from novel_forge.modules.review.diagnostics import prose_repair_diagnoses
from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema
from novel_forge.modules.chapter_authority.realization_composition import compile_realization_contract

def save(n,v): (E/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n')
profiles={};catalog={}
def collect(d,route):
 key=(d['kind'],d['ref'],d['version'],d['content_hash'])
 if key not in catalog:catalog[key]={**d,'catalog_routes':[]}
 catalog[key]['catalog_routes'].append(route)
for a in default_chapter_artifact_resolver(R).artifacts():collect(a.to_dict(),'chapter-resolver')
chapter=json.loads((R/'config/capability_packs/chapter_generation_pack.json').read_text());profiles['chapter']=chapter
for fn in [build_story_planning_pack_profile,build_narrative_evaluation_pack_profile,build_longform_prose_review_pack_profile]:
 p=fn(R,operation_definition_hash='sha256:'+'0'*64);profiles[p.pack_id]=p.manifest
 for a in p.artifact_catalog['artifacts']:collect(a,p.pack_id)
save('current-code-profiles.json',profiles);save('catalog.json',list(catalog.values()))
# current binding identities are code candidates; not installed Pack evidence
bindings=set()
for m in profiles.values():
 for d in m['skill_binding']['skills']:bindings.add(('SKILL',d['skill_ref'],d['version']))
 pb=m['prompt_binding'];bindings.add(('PROMPT_SYSTEM_INSTRUCTION',pb['system_instruction_ref'],pb['system_instruction_version']));bindings.add(('PROMPT_TEMPLATE',pb['template_ref'],pb['template_version']))
corpus={};index=[]
def add(txt,source,status,identity,stage=''):
 h=hashlib.sha256(txt.encode()).hexdigest();corpus.setdefault(h,{'text':txt,'sources':[]})['sources'].append(source)
 index.append({'sha256':h,'source':source,'status':status,'identity':identity,'stage':stage})
for d in catalog.values():
 if isinstance(d['content'],dict) and isinstance(d['content'].get('text'),str):
  current=(d['kind'],d['ref'],d['version']) in bindings
  add(d['content']['text'],d['source_identity'],'CURRENT_CODE_BOUND_DEPLOYMENT_UNVERIFIED' if current else 'CATALOG_ONLY_HISTORICAL_OR_OTHER_STAGE',d['ref']+'@'+d['version'])
for stage in FOUNDATION_GENERATORS:
 save(stage+'.task.json',foundation_task(stage,work_requirements=True,aligned_methods=True,rfc6901_paths=True,narrative_search=stage=='creative.candidates.generate'))
 save(stage+'.schema.json',foundation_output_schema(stage,work_requirements=True,provider_path_constraints=True,rfc6901_paths=True,narrative_search=stage=='creative.candidates.generate'))
for stage in ['memo','draft','review','revision','rereview','quality_structural','quality_commercial','quality_source_originality','quality_longform','quality_platform']:
 save(stage+'.schema.json',chapter_provider_output_schema(stage,work_requirements=True,targeted_revision=stage=='revision',allow_noop_revision=stage=='revision'))
# Reconstruct retained exact requests with frozen materialization; compare raw bytes and receipt inputs.
lineage=[]
B=R/'reports/audits/2026-10-08-creative-input-isolation/evidence'
for case in ['stage-comedy','fantasy-cooking','archive-suspense']:
 assets=json.loads((B/case/'assets.json').read_text());byid={x['asset_version_id']:x['content'] for x in assets}
 effects=json.loads((B/case/'effects.json').read_text())
 for i,e in enumerate(effects):
  req=e['request_payload'];cap=req.get('_production_execution',{}).get('capability_runtime',{})
  if not cap.get('materialization_asset_version_id'):continue
  mat=byid[cap['materialization_asset_version_id']]['contract'];ad=byid[cap['provider_admission_asset_version_id']]['contract'];stage=mat['stage'];ins=req.get('input',{});cmd=ins.get('planning_command')
  if not cmd:continue
  expected=ad['prompt_materialization']['provider_view']['component_hashes']['fully_rendered_prompt']
  target={'scope_kind':cmd['planning_scope'].lower(),'scope_id':cmd['logical_key'],'project_id':cmd['project_id'],'book_id':cmd['book_id']}
  row={'case':case,'effect_id':e['external_effect_id'],'effect_status':e['status'],'stage':stage,'pack_identity':mat.get('pack_identity'),'expected_hash':expected,'materialization_asset_version_id':cap['materialization_asset_version_id'],'frozen_artifacts':{k:{x:v.get(x) for x in ['ref','version','content_hash']} for k,v in mat['pack_artifacts'].items() if isinstance(v,dict)}}
  try:
   prompt,ev=_materialize_production_codex_prompt(target_scope=target,stage=stage,inputs=ins,materialization=mat)
   h='sha256:'+hashlib.sha256(prompt.encode()).hexdigest();row['reassembled_hash']=h;row['exact_hash_match']=h==expected
   receipts=[a['content'].get('payload',{}) for a in assets if a['asset_type']=='execution_evidence' and a['content'].get('kind')=='process-receipt']
   matches=[r for r in receipts if r.get('input_sha256')==h.removeprefix('sha256:')];row['matching_stdin_receipts']=[{k:r.get(k) for k in ['status','input_sha256','operation_id','receipt_id']} for r in matches]
   fname=f'{case}-{i:02}-{stage}.txt';(E/fname).write_text(prompt);row['request_file']=fname
   for tag,txt in re.findall(r'<(system_instruction|governed_skill|required_knowledge|prompt_template|stage_semantic_contract|output_schema|tool_policy)>\n(.*?)\n</\1>',prompt,re.S):
    add(txt,f'{fname}::{tag}','FROZEN_REAL_REQUEST_HASH_VERIFIED' if h==expected else 'FROZEN_REASSEMBLY_DRIFT',tag,stage)
  except Exception as ex:row['assembly_error']=getattr(ex,'code',type(ex).__name__)
  lineage.append(row)
save('retained-request-verification.json',lineage)
for d in catalog.values():
 if d['kind'] in {'SCHEMA','KNOWLEDGE','TOOL_POLICY','CONTEXT_POLICY'}:
  add(json.dumps(d['content'],ensure_ascii=False,indent=2,sort_keys=True),d['source_identity'],'CATALOG_ONLY_SELECTION_MUST_BIND_EXACT_VERSION',d['ref']+'@'+d['version'])
from novel_forge.modules.chapter_authority.prompt_methods import _METHODS
for d in catalog.values():
 if d['kind']=='SKILL' and (d['kind'],d['ref'],d['version']) in bindings and d['ref'] in _METHODS:
  for st in _METHODS[d['ref']]:
   for targeted in ([False,True] if st=='revision' else [False]):
    try:
     txt=project_skill_method(d['content']['text'],ref=d['ref'],version=d['version'],stage=st,targeted=targeted)
     add(txt,d['source_identity'],'CURRENT_CODE_STAGE_PROJECTION_DEPLOYMENT_UNVERIFIED',d['ref']+'@'+d['version'],st+(':targeted' if targeted else ''))
    except Exception as ex:pass
save('instruction-index.json',index)
D=E/'instruction-fulltext';D.mkdir(exist_ok=True)
for h,d in corpus.items():(D/(h+'.txt')).write_text(d['text'])
# bounded synthetic discriminative checks
checks=[]
def check(n,a,e):checks.append({'id':n,'actual':a,'expected':e,'pass':a==e})
check('current_foundation_no_universal_irreversible_cost','Do not invent irreversible costs' in foundation_task('ending.intent.generate',work_requirements=True)['task'],True)
check('current_chapter_profile_no_mandatory_hook','chapter_hook' in qualification_profile_for_plan({'chapter':1,'chapter_contract_schema_version':'chapter-mission-scene.v4'}).required_fields,False)
view=build_draft_plan_view({'chapter':1,'title':'测试','premise':'测试','style_constraints':['本书冷峻'], 'scene_sequence':[], 'source_chapter_plan_asset_version_id':'audit-plan', 'source_chapter_plan_content_hash':'sha256:'+'0'*64},work_requirements=True)
check('current_style_constraints_preserved','本书冷峻' in json.dumps(view,ensure_ascii=False),True)
review={'issues':[{'code':'taste','severity':'minor','judgment_kind':'AESTHETIC_SUGGESTION'},{'code':'goal','severity':'major','judgment_kind':'SEMANTIC_CONFLICT'}]}
check('automatic_revision_filters_aesthetic',[x['code'] for x in prose_repair_diagnoses(review,work_requirements=True)],['goal'])
# Core policy count: simple controlled Scene, source/Knowledge-free slot arithmetic only.
plan={'scene_plan':[{'scene_id':'s1','participants':['p'],'pov_character_id':'p','goal':'争取练功时段','beats':[{'beat_id':'b1'}], 'realization_capabilities':['SKELETON','ACTION','INTERIOR','DESCRIPTION','TRANSITION'],'accessible_knowledge':[],'entry_state':'入场','exit_state':'保持争议'}]}
for policy in ['scene-core-slots.v1','continuous-scene.v1']:
 try:c=compile_realization_contract(plan,{'policies':[]},core_policy=policy,accepted_sources={'by_actor':{}},world_preparation={});save(policy+'.synthetic.json',c)
 except Exception as ex:save(policy+'.synthetic.json',{'code':getattr(ex,'code',type(ex).__name__),'note':'Synthetic lacks mandatory source contracts; no production admission'})
check('continuous_scene_policy_slots',len(json.loads((E/'continuous-scene.v1.synthetic.json').read_text()).get('slots',[])),1)
check('historical_core_slots_count',len(json.loads((E/'scene-core-slots.v1.synthetic.json').read_text()).get('slots',[])),5)
save('offline-checks.json',{'classification':'SYNTHETIC/OFFLINE','checks':checks,'provider_calls':0,'full_P0':'NOT_RUN','literary_causality':'UNVERIFIED'})
print(json.dumps({'catalog':len(catalog),'dedup_texts':len(corpus),'instruction_rows':len(index),'retained_requests':len(lineage),'hash_matches':sum(x.get('exact_hash_match',False) for x in lineage),'checks':checks},ensure_ascii=False))
