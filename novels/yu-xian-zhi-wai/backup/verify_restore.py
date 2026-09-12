from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
import json,os,subprocess,uuid,datetime
import psycopg
from psycopg import sql
R=Path(__file__).resolve().parent;E=R.parent;env=os.environ|json.loads((E/'runtime/local-environment.json').read_text());url=urlsplit(env['NOVEL_FORGE_DATABASE_URL']);admin=urlunsplit((url.scheme,url.netloc,'/postgres',url.query,url.fragment));name='nf_pilot_restore_'+uuid.uuid4().hex[:12]+'_test';restore=urlunsplit((url.scheme,url.netloc,'/'+name,url.query,url.fragment));result={'schema_version':'pilot-backup-restore.v1','database':name,'scope':'TEMPORARY_ISOLATED_RESTORE_VALIDATION','status':'FAIL','model_calls':0,'business_database_mutated':False,'restored_database_removed':False}
try:
 with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
 with (R/'corpus-pilot.pgcustom').open('rb') as f:
  p=subprocess.run(['docker','exec','-i','novel-forge-first-novel-pilot-data','pg_restore','-U','novel_forge','-d',name,'--exit-on-error','--no-owner','--no-privileges'],stdin=f,capture_output=True)
 (R/'restore.stderr').write_bytes(p.stderr);assert p.returncode==0,'pg_restore failed; inspect sanitized local stderr'
 def snapshot(dsn):
  with psycopg.connect(dsn) as c:
   c.execute('SET TRANSACTION READ ONLY');return c.execute('SELECT (SELECT count(*) FROM authority_operation),(SELECT count(*) FROM authority_external_effect),(SELECT count(*) FROM authority_asset_version),(SELECT count(*) FROM authority_book),(SELECT count(*) FROM authority_mkaos_knowledge_card)').fetchone()
 original=snapshot(env['NOVEL_FORGE_DATABASE_URL']);cloned=snapshot(restore);assert original==cloned,(original,cloned)
 runenv=env|{'NOVEL_FORGE_DATABASE_URL':restore,'PYTHONPATH':'src:.'}
 command=['.venv/bin/python','-m','novel_forge.cli.authority','corpus','jobs','--project-id','first-novel-pilot-20260912','--run-key-prefix','pilot-materials-','--limit','50']
 p=subprocess.run(command,env=runenv,capture_output=True,text=True);(R/'restored-native-jobs.json').write_text(p.stdout);(R/'restored-native-jobs.stderr').write_text(p.stderr);assert p.returncode==0,p.stderr
 jobs=json.loads(p.stdout)['items'];assert len(jobs)==20 and all(j['status']=='IMPORTED' for j in jobs)
 selection=json.loads((E/'corpus/selections.json').read_text())['canary']
 p=subprocess.run(['.venv/bin/python','-m','novel_forge.cli.authority','corpus','reading-preview','--project-id','first-novel-pilot-20260912','--revision-id',selection['revision_id'],'--reading-scopes',str(E/'corpus/canary-reading-scopes.json'),'--intended-use','ABSTRACT_GENERATION','--target-book-id','first-novel-pilot-a','--max-calls','10','--max-tokens','250000'],env=runenv,capture_output=True,text=True)
 (R/'restored-native-reading-preview.json').write_text(p.stdout);(R/'restored-native-reading-preview.stderr').write_text(p.stderr);assert p.returncode==0,p.stderr
 preview=json.loads(p.stdout);assert preview['prepared_source_checks']['state']=='VERIFIED' and preview['model_calls']==0
 result.update(status='PASS',original_counts=original,restored_counts=cloned,restored_native_imports=len(jobs),restored_source_check=preview['prepared_source_checks'],snapshot_time=datetime.datetime.now(datetime.timezone.utc).isoformat())
finally:
 with psycopg.connect(admin,autocommit=True) as c:
  c.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)));result['restored_database_removed']=True
 (R/'restore-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(result)

