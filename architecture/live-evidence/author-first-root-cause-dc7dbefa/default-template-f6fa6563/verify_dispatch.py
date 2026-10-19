import gzip,json,hashlib,sys
from pathlib import Path
from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt

def working_sources(x):
 if isinstance(x,dict):
  if str((x.get('projection_policy') or {}).get('version','')).startswith('working-prose-projection'):
   yield from x.get('sources',[])
  for y in x.values(): yield from working_sources(y)
 elif isinstance(x,list):
  for y in x:yield from working_sources(y)

def verify(path):
 d=json.load(gzip.open(path,'rt'));assets={a['version']['asset_version_id']:a['version'] for a in d['assets']}
 materials={a['content']['contract']['materialization_hash']:a['content']['contract'] for a in assets.values() if isinstance(a['content'],dict) and isinstance(a['content'].get('contract'),dict) and 'pack_artifacts' in a['content']['contract']}
 effects={e['external_effect_id']:e for e in d['effects']};rows=[]
 for receipt in d['receipts']:
  r=receipt['receipt']
  ev=(r['payload'].get('evidence') if r else receipt['dispatch'].get('evidence')) or {};runtime=ev.get('capability_runtime') or {};production=ev.get('production_execution') or {}
  effect=effects[receipt['dispatch']['external_effect_id']];req=effect['request_payload'];stage=req.get('stage')
  if stage not in {'chapter_group_plan.generate','chapter_plan.generate','memo','draft'} or not runtime.get('materialization_hash'):continue
  mat=materials[runtime['materialization_hash']]
  prompt,_=_materialize_production_codex_prompt(target_scope=production['execution_request']['target_scope'],stage=stage,inputs=req['input'],materialization=mat,template_render_contract=runtime.get('template_render_contract','opaque-template-substitution.v1'))
  prompt_hash='sha256:'+hashlib.sha256(prompt.encode()).hexdigest()
  assert prompt_hash==runtime['fully_rendered_prompt_hash'],stage
  pref=production['execution_result']['process_receipt_ref'].removeprefix('authority-asset-version:')
  process=assets[pref]['content']['payload'];assert process['input_sha256']==prompt_hash.removeprefix('sha256:')
  bindings=[]
  for source in working_sources(req['input']):
   sid=source['asset_version_id'];h=source['content_hash'];assert assets[sid]['content_hash']==h;assert sid in prompt and h in prompt
   text=assets[sid]['content']['text']
   assert source['text_hash']=='sha256:'+hashlib.sha256(text.encode()).hexdigest()
   assert source['status']=='UNREVIEWED_WORKING_PROSE' and source['character_knowledge']=='NOT_VERIFIED'
   passages=[]
   for passage in source['passages']:
    excerpt=passage['text'];assert text[passage['start']:passage['end']]==excerpt
    assert passage['text_hash']=='sha256:'+hashlib.sha256(excerpt.encode()).hexdigest()
    assert excerpt in prompt or json.dumps(excerpt,ensure_ascii=False)[1:-1] in prompt
    passages.append({'start':passage['start'],'end':passage['end'],'text_hash':passage['text_hash'],'characters':len(excerpt)})
   bindings.append({'asset_version_id':sid,'content_hash':h,'chapter':source['chapter'],'text_hash':source['text_hash'],'passages':passages,'status':source['status'],'character_knowledge':source['character_knowledge']})
  rows.append({'stage':stage,'operation_id':effect['operation_id'],'external_effect_id':effect['external_effect_id'],'effect_status':effect['status'],'verified_remote_result':bool(r),'prompt_hash':prompt_hash,'process_stdin_sha256':process['input_sha256'],'rendered_bytes':len(prompt.encode()),'working_sources':bindings})
 report={'test':d['test'],'source_sha':d['source_sha'],'input':Path(path).name,'status':'PASS','actual_prompt_and_process_stdin_matches':len(rows),'successful_result_inputs':sum(r['verified_remote_result'] for r in rows),'unknown_result_inputs':sum(not r['verified_remote_result'] for r in rows),'working_source_bindings':sum(len(r['working_sources']) for r in rows),'rows':rows}
 out=Path(path).with_name(Path(path).name.removesuffix('.json.gz')+'-dispatch.json');out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(out.name,len(rows),report['working_source_bindings'])
if __name__ == "__main__":
 for arg in sys.argv[1:]:verify(arg)
