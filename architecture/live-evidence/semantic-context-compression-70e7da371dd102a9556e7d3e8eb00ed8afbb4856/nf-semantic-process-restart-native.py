from pathlib import Path
import argparse,dataclasses,hashlib,inspect,json,os,subprocess,sys
import psycopg

p=argparse.ArgumentParser();p.add_argument('mode',choices=['checkpoint','resume']);p.add_argument('--journal',required=True);a=p.parse_args();journal=Path(a.journal)
sys.path.insert(0,str(Path.cwd()))
source_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
if a.mode=='checkpoint':
 import tests.integration.test_chapter_model_effects_postgres as recipe
 real_build=recipe.build_production_execution_composition;calls=0
 def checkpoint_build(*args,**kwargs):
  global calls
  calls+=1
  if calls==2:
   frame=inspect.currentframe().f_back;state=frame.f_locals
   assert state['interrupted'] and state['last_stage']=='context_compress'
   with psycopg.connect(os.environ['NOVEL_FORGE_DATABASE_URL']) as c:
    effects=[row[0] for row in c.execute('SELECT to_jsonb(e) FROM authority_external_effect e WHERE project_id=%s ORDER BY created_at',[state['project_id']])]
   assert any(e['capability']=='model.context_compress' and e['status']=='SUCCEEDED' for e in effects)
   assert not any(e['capability']=='model.draft' for e in effects)
   principal=dataclasses.asdict(state['principal']);principal={k:list(v) if isinstance(v,frozenset) else v for k,v in principal.items()}
   data={'source_sha':source_sha,'evidence_class':'NATIVE_CONTROLLED_PROCESS_RESTART_AFTER_SETTLED_COMPRESSION','checkpoint_process_id':os.getpid(),'checkpoint':'AFTER_PROVIDER_SUCCESS_AND_NATIVE_RETRYABLE_FAILURE_BEFORE_NEW_COMPOSITION','root':str(state['settings'].root),'env':state['env'],'principal':principal,'project_id':state['project_id'],'root_operation_id':state['admitted'].root_operation_id,'request_limit':state['request_limit'],'before_effects':effects,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
   journal.parent.mkdir(parents=True,exist_ok=True)
   with journal.open('w') as f:json.dump(data,f,ensure_ascii=False,indent=2,default=str);f.flush();os.fsync(f.fileno())
   print('DURABLE_CHECKPOINT_PROCESS_EXIT',os.getpid(),state['project_id'],flush=True)
   os._exit(75)
  return real_build(*args,**kwargs)
 recipe.build_production_execution_composition=checkpoint_build
 test=recipe.ChapterModelEffectsPostgresTests('test_routed_overflow_prepares_before_router_rejection_and_restarts_from_completed_chunk')
 recipe.ChapterModelEffectsPostgresTests.setUpClass()
 test.test_routed_overflow_prepares_before_router_rejection_and_restarts_from_completed_chunk()
 raise AssertionError('Expected process checkpoint was not reached')
else:
 data=json.loads(journal.read_text());assert data['source_sha']==source_sha and data['checkpoint_process_id']!=os.getpid()
 from dataclasses import replace
 from novel_forge.api.authority_dependencies import build_chapter_authority_application,build_production_execution_composition
 from novel_forge.infrastructure.settings import IndustrialSettings
 from novel_forge.modules.authority_security import Principal,PrincipalType
 from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
 from novel_forge.modules.chapter_authority.orchestrator import ChapterNode
 from novel_forge.modules.chapter_authority import execution_gateway
 from tests.integration.quality_context_routed_support import attach_mock_qualified_router
 from unittest.mock import patch
 calls=[];prompts={}
 def fixture(stage,inputs):
  calls.append(stage)
  output=default_chapter_fixture_response(stage,inputs)
  if stage in {'draft','revision'}:
   for scene in output.get('scene_artifacts',[]):scene['text']+='承诺已经当众立下，归家的退路就此断绝。'
   if isinstance(output.get('text'),str):output['text']+='承诺已经当众立下，归家的退路就此断绝。'
  return output
 materialize=execution_gateway._materialize_production_codex_prompt
 def record(**kw):
  text,evidence=materialize(**kw)
  if kw.get('stage')=='draft':prompts[evidence['fully_rendered_prompt_hash']]=text
  return text,evidence
 settings=IndustrialSettings(root=Path(data['root']),database_url=os.environ['NOVEL_FORGE_DATABASE_URL'])
 execution=build_production_execution_composition(settings,env=data['env'],chapter_fixture_factory=fixture)
 router=attach_mock_qualified_router(execution,os.environ['NOVEL_FORGE_DATABASE_URL']);router.candidates=tuple(replace(x,context_limit=data['request_limit']) for x in router.candidates)
 app=build_chapter_authority_application(settings,execution=execution,env=data['env'])
 v=data['principal'];principal=Principal(v['principal_id'],PrincipalType(v['principal_type']),frozenset(v['permissions']),frozenset(v['project_scope']),v['authentication_source'])
 scheduler=app.scheduler(principal=principal)
 with patch.object(execution_gateway,'_materialize_production_codex_prompt',side_effect=record):
  ticks=[]
  for _ in range(len(ChapterNode)+1):
   tick=scheduler.tick(project_id=data['project_id'],root_operation_id=data['root_operation_id']);ticks.append({'node':tick.node,'status':tick.operation_status})
   assert tick.operation_status=='SUCCEEDED'
   if tick.node==ChapterNode.DRAFT.value:break
  else:raise AssertionError('Native Writer did not complete')
 with psycopg.connect(os.environ['NOVEL_FORGE_DATABASE_URL']) as c:
  c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  after=[row[0] for row in c.execute('SELECT to_jsonb(e) FROM authority_external_effect e WHERE project_id=%s ORDER BY created_at',[data['project_id']])]
  before={e['external_effect_id']:e for e in data['before_effects']}
  assert all(e==before[e['external_effect_id']] for e in after if e['external_effect_id'] in before)
  drafts=[e for e in after if e['capability']=='model.draft'];assert len(drafts)==1 and drafts[0]['status']=='SUCCEEDED'
  assert not any(e['request_hash']==data['before_effects'][-1]['request_hash'] and e['external_effect_id']!=data['before_effects'][-1]['external_effect_id'] for e in after)
  row=c.execute("""SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset o JOIN authority_asset_version v USING(asset_version_id) JOIN authority_operation op USING(operation_id) WHERE op.project_id=%s AND o.output_key='chapter.draft'""",[data['project_id']]).fetchone();assert row
  assert '承诺' in row[2]['text']
  logs=[row[0] for row in c.execute("""SELECT v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='model_call_log'""",[data['project_id']])]
  ledgers=[row[0] for row in c.execute("""SELECT v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='cost_ledger'""",[data['project_id']])]
 assert len(logs)==len(after) and len(ledgers)==len(after)
 payload=drafts[0]['request_payload'];admission=payload['_production_execution']['capability_runtime']['provider_admission'];assert admission['total_reserved']<=admission['applicable_limit']
 projection=payload['input']['_context_capacity_projection'];assert projection['measurement']['after_reserved']<=projection['measurement']['limit']
 artifact=journal.parent
 for name,text in prompts.items():(artifact/('final-request-'+name.split(':')[-1]+'.txt')).write_text(text)
 (artifact/'native-prose-readback.txt').write_text(row[2]['text'])
 result={**{k:v for k,v in data.items() if k not in {'env','principal'}},'status':'PASS','resume_process_id':os.getpid(),'ticks':ticks,'resumed_fixture_calls':calls,'before_effect_ids':list(before),'after_effects':after,'model_call_logs':logs,'cost_ledgers':ledgers,'saved_source_asset_version_id':row[0],'saved_content_hash':row[1],'provider_admission':admission,'projection':projection,'real_provider':'NOT_RUN','unknown_in_flight_call_kill':'NOT_RUN','literary_quality':'NOT_RUN'}
 (artifact/'receipts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
 print('PASS_DISTINCT_NATIVE_PROCESSES',data['checkpoint_process_id'],os.getpid(),'before',len(before),'after',len(after),'writer',len(drafts),flush=True)
