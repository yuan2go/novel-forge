import pathlib,json,hashlib,datetime
A=pathlib.Path(__file__).parent;E=A/'evidence';E.mkdir(exist_ok=True)
def save(name,d): (E/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,default=str)+'\n')
R=pathlib.Path('/Users/yuan/.local/share/novel-forge/runs/sol40-20261005T112522Z')
rows=[]
for p in sorted(R.glob('codex-executions/*/last-message.json')):
 try:d=json.loads(p.read_text());receipt=json.loads((p.parent/'process-receipt.json').read_text())
 except (ValueError,FileNotFoundError):continue
 if 'scene_artifacts' not in d:continue
 name=p.parent.name
 text='\n\n'.join(x['text'] for x in d['scene_artifacts'])
 (E/(name+'.txt')).write_text(text)
 save(name+'.json',{'source_file':str(p),'output':d,'receipt':receipt,'serialization':'Audit joins with blank lines; original scene separators unknown; do not count as accepted chapter'})
 rows.append({'execution_id':receipt['execution_id'],'operation_id':receipt.get('operation_id'),'input_sha256':receipt.get('input_sha256'),'completed_at':receipt.get('completed_at'),'status':receipt.get('status'),'output_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source_file':str(p),'body_file':name+'.txt','characters_with_punctuation':len(text),'slots':len(d['scene_artifacts']),'kind':'REVISION_OUTPUT' if 'resolved_issue_codes' in d else 'DRAFT_OUTPUT','accepted_status':'UNVERIFIED'})
save('local-prose-index.json',rows)
# Native retained database: all business queries inside one explicit READ ONLY transaction.
try:
 import psycopg
 uri=(R/'database-url.local').read_text().strip()
 with psycopg.connect(uri,connect_timeout=3,options='-c default_transaction_read_only=on -c statement_timeout=15000') as c:
  with c.cursor() as q:
   q.execute('SHOW transaction_read_only');readonly=q.fetchone()[0];assert readonly=='on'
   q.execute("SELECT current_database(),(SELECT oid FROM pg_database WHERE datname=current_database()),version()")
   identity=q.fetchone();save('sol40-database-identity.json',{'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'transaction_read_only':readonly,'identity':identity})
   project='nf-sol40-20261005T112522Z'
   q.execute('SELECT a.asset_type,count(*) FROM authority_asset a JOIN authority_asset_version v USING(asset_id) WHERE a.project_id=%s GROUP BY a.asset_type ORDER BY a.asset_type',[project]);save('sol40-asset-counts.json',q.fetchall())
   q.execute("SELECT a.asset_type,v.asset_version_id,v.content_hash,v.content FROM authority_asset a JOIN authority_asset_version v USING(asset_id) WHERE a.project_id=%s AND a.asset_type=ANY(%s) ORDER BY v.created_at",[project,['draft_chapter','draft_version','revision_candidate','best_draft_candidate','review_report','re_review_report','chapter_plan','chapter_memo','creative_brief','book_design']]);save('sol40-story-assets.json',[dict(zip(['asset_type','asset_version_id','content_hash','content'],row)) for row in q.fetchall()])
   q.execute('SELECT to_jsonb(e) FROM authority_external_effect e JOIN authority_operation o USING(operation_id) WHERE o.project_id=%s ORDER BY e.created_at',[project]);save('sol40-effects.json',[r[0] for r in q.fetchall()])
   q.execute('SELECT to_jsonb(b) FROM authority_book_production b WHERE project_id=%s',[project]);save('sol40-books.json',[r[0] for r in q.fetchall()])
   q.execute('SELECT to_jsonb(d) FROM authority_runtime_deployment d ORDER BY activated_at DESC LIMIT 5');save('sol40-runtime-deployments.json',[r[0] for r in q.fetchall()])
 save('db-query-status.json',{'status':'READ_ONLY_EXPORTED','provider_calls':0})
except Exception as e:
 save('db-query-status.json',{'status':'UNAVAILABLE_OR_PARTIAL','error_type':type(e).__name__,'sqlstate':getattr(e,'sqlstate',None),'provider_calls':0,'note':'No DSN or error text exported; existing files preserve any completed SELECT evidence'})
print(json.dumps({'local_prose_outputs':len(rows),'db_status':json.loads((E/'db-query-status.json').read_text())},ensure_ascii=False))
