import json,hashlib,sys,subprocess
from pathlib import Path
import psycopg
repo=Path('/Users/yuan/.codex/worktrees/creative-input-isolation-01/novel-forge')
sys.path[:0]=[str(repo/'src'),str(repo)]
from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view,build_provider_task_view
root=repo/'.local/evidence/wp-creative-input-isolation-01';root.mkdir(parents=True,exist_ok=True)
cases=['stage-comedy','fantasy-cooking','archive-suspense'];summary=[]
with psycopg.connect('postgresql:///nf_creative_input_isolation_20261008_live') as c:
 for case in cases:
  project='project:input-isolation-01:'+case
  out=root/case;out.mkdir(exist_ok=True)
  def dump(name,data):
   p=out/name;p.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n');return str(p)
  assets=c.execute('select a.asset_type,v.asset_version_id,v.content_hash,v.content from authority_asset a join authority_asset_version v using(asset_id) where a.project_id=%s order by v.created_at',[project]).fetchall()
  dump('assets.json',[dict(zip(['asset_type','asset_version_id','content_hash','content'],r)) for r in assets])
  formation=c.execute('select to_jsonb(r) from authority_story_formation_run r where project_id=%s',[project]).fetchall()
  dump('formation.json',[r[0] for r in formation])
  operations=c.execute('select to_jsonb(o) from authority_operation o where project_id=%s order by created_at',[project]).fetchall()
  dump('operations.json',[r[0] for r in operations])
  effects=c.execute('select to_jsonb(e) from authority_external_effect e where project_id=%s order by created_at',[project]).fetchall()
  dump('effects.json',[r[0] for r in effects])
  exact=[]
  for i,(effect,) in enumerate(effects):
   request=effect['request_payload'];cap=request.get('_production_execution',{}).get('capability_runtime',{})
   if not cap.get('materialization_asset_version_id'):continue
   materialization=c.execute('select content from authority_asset_version where asset_version_id=%s',[cap['materialization_asset_version_id']]).fetchone()[0]['contract']
   admission=c.execute('select content from authority_asset_version where asset_version_id=%s',[cap['provider_admission_asset_version_id']]).fetchone()[0]['contract']
   stage=materialization['stage'];inputs=request.get('input',{})
   command=inputs.get('planning_command')
   if not command:continue
   target={'scope_kind':command['planning_scope'].lower(),'scope_id':command['logical_key'],'project_id':project,'book_id':command['book_id']}
   prompt,evidence=_materialize_production_codex_prompt(target_scope=target,stage=stage,inputs=inputs,materialization=materialization)
   actual='sha256:'+hashlib.sha256(prompt.encode()).hexdigest()
   expected=admission['prompt_materialization']['provider_view']['component_hashes']['fully_rendered_prompt']
   if actual!=expected:raise AssertionError((case,actual,expected))
   path=out/f'request-{i:02}-{stage}.txt';path.write_text(prompt)
   ctx=materialization['context_selection'][0]['content']
   dump(f'context-{i:02}.json',ctx)
   foreign=[item['content'].get('creative_input_selection',{}).get('book_id') for item in ctx.get('input_versions',[]) if item['role']=='creative_brief' and item['content'].get('creative_input_selection',{}).get('book_id')!=command['book_id']]
   others=[other for other in cases if other!=case and 'book:input-isolation-01:'+other in prompt]
   receipts=[r[3]['payload'] for r in assets if r[0]=='execution_evidence' and r[3].get('kind')=='process-receipt' and r[3].get('payload',{}).get('operation_id')==request.get('operation_id')]
   matches=[r for r in receipts if r.get('input_sha256')==actual.split(':',1)[1]]
   if effect['status']=='SUCCEEDED' and not any(r.get('status')=='SUCCEEDED' and r.get('returncode')==0 for r in matches):raise AssertionError(('actual-stdin-receipt-missing',case,stage))
   exact.append({'effect_id':effect['external_effect_id'],'status':effect['status'],'stage':stage,
    'rendered_prompt_sha256':actual,'prompt_admission_hash_match':True,'foreign_book_inputs':foreign,'other_case_in_prompt':others,
    'actual_stdin_receipt_hash_match':bool(matches),'selection_metadata_in_prompt':'creative_input_selection' in prompt,'hidden_test_controls_in_prompt':any(marker in prompt for marker in ['hidden_answer','window-','maximum_ticks','32-call']),
    'request_file':str(path)})
  dump('request-lineage.json',exact)
  candidates=[{'asset_version_id':r[1],'content_hash':r[2],'content':r[3]} for r in assets if r[0]=='planning_generation_candidate']
  dump('candidates.json',candidates)
  summary.append({'case':case,'project_id':project,'book_id':'book:input-isolation-01:'+case,
    'effects':len(effects),'effect_statuses':[r[0]['status'] for r in effects],
    'exact_prompt_checks':exact,'candidate_count':len(candidates),'formation':[(r[0]['lifecycle'],r[0]['current_stage']) for r in formation]})
(root/'live-status.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps([{k:v for k,v in x.items() if k!='exact_prompt_checks'} for x in summary],ensure_ascii=False,indent=2))
