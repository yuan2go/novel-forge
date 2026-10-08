import collections, datetime, hashlib, json, os, pathlib, sys
from psycopg.conninfo import make_conninfo
base=pathlib.Path('/Volumes/DevSSD/Development/Data/novel-runtime/wp-work-adaptation-reader-promise-to-prose-01-20261008')
out=base/'service-recovery/material-provenance-20261009'
env=json.loads((base/'service-recovery/recovery-env.private.json').read_text())
os.environ.update(env);os.environ['NOVEL_FORGE_NO_MODEL_DISPATCH']='1';os.environ['NOVEL_FORGE_EXECUTION_DIAGNOSTICS']='0';sys.path.insert(0,env['NOVEL_FORGE_ROOT']+'/src')
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.modules.production_execution.recovery import AuthorityExecutionRecoveryStore
from novel_forge.cli.runtime_inspection import inspect_runtime
from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.modules.book_authority.creation_runtime import creation_status
p='qid-learning-prose-01';book='book:qinglan-wendao-20261008';formation='story-formation:0a8aa0c2dc447a252fad800a5a31b0663fd6f167087d18bfeb5a980a8afe261d'
principal=build_trusted_principal_resolver().resolve_api_principal();principal.require('book.authority.query',p)
dsn=make_conninfo(env['NOVEL_FORGE_DATABASE_URL'],connect_timeout=5,options='-c default_transaction_read_only=on -c statement_timeout=10000')
q=AuthorityAssetQuery(dsn);st=AuthorityExecutionRecoveryStore(dsn,project_id=p)
def as_time(value):
 return datetime.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=8))).isoformat() if value else None
records=[]
for doc in q.list(project_id=p,asset_type='execution_recovery_session',limit=100):
 z=doc.content['record'];req=z['request'];result=z.get('result') or {};route=q.require(project_id=p,logical_ref=req['route_snapshot_id']).content['contract'];process=z.get('process_receipt') or {}
 usage=st.read_evidence(result['usage_receipt_ref']) if result.get('usage_receipt_ref') else None
 cost=st.read_evidence(result['cost_receipt_ref']) if result.get('cost_receipt_ref') else None
 row={k:req.get(k) for k in ['execution_id','operation_id','external_effect_id','book_id','task_kind','domain','attempt_id','route_snapshot_id']}
 row.update({'recovery_asset_version_id':doc.asset_version_id,'started_cst':as_time(z['started_at']),'completed_cst':as_time(result.get('completed_at') or process.get('completed_at')),'outcome':result.get('outcome'),'process_status':process.get('status'),'returncode':process.get('returncode'),'usage':usage,'accounting_basis':(cost or {}).get('accounting_basis'),'cost_measurement':(cost or {}).get('measurement'),'route':{k:route.get(k) for k in ['backend_id','model_provider','model_id','reasoning_effort','release_sha','prompt_bundle_ref','skill_bundle_ref','output_schema_ref','fallback_trigger','route_change_index']},'receipts':{k:result.get(k) for k in ['usage_receipt_ref','cost_receipt_ref','provider_receipt_ref','output_manifest_ref','validation_report_ref']}})
 records.append(row)
records.sort(key=lambda x:x['started_cst']);byop={r['operation_id']:r for r in records}
selected=[]
for design in q.list(project_id=p,asset_type='book_design',limit=10):
 for binding in design.content['foundation_set']['bindings']:
  d=q.require(project_id=p,asset_version_id=binding['asset_version_id']);e=d.content['execution_evidence'];r=byop[e['operation_id']]
  actual='sha256:'+hashlib.sha256(json.dumps(d.content,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  selected.append({'role':binding['role'],'asset_version_id':d.asset_version_id,'content_hash':d.content_hash,'hash_verified':actual==d.content_hash==binding['content_hash'],'operation_id':e['operation_id'],'started_cst':r['started_cst'],'completed_cst':r['completed_cst'],'usage':r['usage'],'route':r['route'],'frozen_inputs':d.content.get('frozen_inputs'),'selection_receipt':binding['qualification_evidence_asset_version_id']})
candidates=[]
for d in q.list_versions(project_id=p,asset_type='planning_generation_candidate',limit=100):
 if d.content.get('book_id')==book:
  candidates.append({'asset_version_id':d.asset_version_id,'generator_operation_name':d.content.get('generator_operation_name'),'operation_id':(d.content.get('execution_evidence') or {}).get('operation_id'),'frozen_inputs':d.content.get('frozen_inputs'),'lifecycle':d.lifecycle})
logs=q.list(project_id=p,asset_type='model_call_log',limit=100)
log_summary={'count':len(logs),'providers':dict(collections.Counter(d.content.get('provider_id') for d in logs)),'models':dict(collections.Counter(d.content.get('model_id') for d in logs)),'real_provider_true':sum(d.content.get('real_provider_proven') is True for d in logs),'fixture_true':sum(d.content.get('fixture_protocol_only') is True for d in logs)}
other=[]
for typ in ['creative_brief','source_work','source_document','canon_snapshot','reader_contract','production_profile']:
 for d in q.list_versions(project_id=p,asset_type=typ,limit=30):
  other.append({'type':typ,'asset_version_id':d.asset_version_id,'content_hash':d.content_hash,'keys':list(d.content),'small_fields':{k:v for k,v in d.content.items() if k in ['title','schema_version','project_id','book_id','source_type','source_kind','origin','mode','status']},'selection':d.content.get('creative_input_selection'),'execution_evidence':d.content.get('execution_evidence')})
native=inspect_runtime(dsn,project_id=p,expected_database='nf_qidian_learning_20261008_test');creation=creation_status(dsn,project_id=p,formation_run_id=formation,principal=principal)
payload={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'project_id':p,'book_id':book,'read_path':'AuthorityAssetQuery + AuthorityExecutionRecoveryStore.read_evidence + inspect_runtime + creation_status; database read-only; no model dispatch','recovery_point_provenance':json.loads((base/'service-recovery/recovery-provenance.json').read_text()),'runtime':native,'creation':creation,'model_logs':log_summary,'executions':records,'selected_foundations':selected,'planning_candidates':candidates,'other_assets':other}
(out/'provenance.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str))
print('MODEL_LOGS',log_summary)
for r in records: print(r['started_cst'],r['completed_cst'],r['domain'],r['outcome'],r['route']['model_id'],(r['usage'] or {}).get('total_tokens'),r['operation_id'])
print('SELECTED',[(s['role'],s['hash_verified']) for s in selected]);print('OTHER',json.dumps(other,ensure_ascii=False)[:5000]);print('STATUS',creation['author_state']);print('SAVED',str(out/'provenance.json'))
