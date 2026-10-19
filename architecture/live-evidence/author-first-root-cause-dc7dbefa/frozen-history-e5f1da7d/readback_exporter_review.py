import gzip,hashlib,json,os,subprocess
from pathlib import Path
import psycopg
import pytest

ROOT=Path('/Users/yuan/.codex/worktrees/author-first-review-fix/novel-forge')
OUT=Path('/tmp/nf-author-first-20261017/native-readback')
OUT.mkdir(exist_ok=True)
DB=os.environ['NOVEL_FORGE_DATABASE_URL'].rsplit('/',1)[-1]

def digest(x):
 return 'sha256:'+hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str).encode()).hexdigest()

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
 with psycopg.connect(os.environ['NOVEL_FORGE_DATABASE_URL'], options='-c default_transaction_read_only=on') as c:
  assert c.execute('SELECT current_database()').fetchone()[0] == DB
  started=c.execute('SELECT clock_timestamp()').fetchone()[0]
 source_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 diff=subprocess.check_output(['git','diff','HEAD','--'],cwd=ROOT)
 yield
 with psycopg.connect(os.environ['NOVEL_FORGE_DATABASE_URL'],options='-c default_transaction_read_only=on') as c:
  identity=c.execute('SELECT current_database(),(SELECT system_identifier::text FROM pg_control_system())').fetchone()
  projects=[r[0] for r in c.execute('SELECT DISTINCT project_id FROM authority_operation WHERE created_at >= %s',[started]).fetchall()]
  asset_ids=[r[0] for r in c.execute('SELECT v.asset_version_id FROM authority_asset a JOIN authority_asset_version v USING(asset_id) WHERE a.project_id=ANY(%s)',[projects]).fetchall()]
  assets=[c.execute('SELECT jsonb_build_object(\'asset_type\',a.asset_type,\'asset_id\',a.asset_id,\'version\',to_jsonb(v)) FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s',[asset_id]).fetchone()[0] for asset_id in asset_ids]
  effects=[r[0] for r in c.execute('SELECT to_jsonb(e) FROM authority_external_effect e WHERE project_id=ANY(%s) ORDER BY created_at,external_effect_id',[projects]).fetchall()]
  attempts=[r[0] for r in c.execute('SELECT to_jsonb(a) FROM authority_attempt a JOIN authority_operation o USING(operation_id) WHERE o.project_id=ANY(%s) ORDER BY o.created_at,a.attempt_number',[projects]).fetchall()]
  operations=[r[0] for r in c.execute('SELECT to_jsonb(o) FROM authority_operation o WHERE project_id=ANY(%s) ORDER BY created_at,operation_id',[projects]).fetchall()]
  receipts=[r[0] for r in c.execute('SELECT jsonb_build_object(\'dispatch\',to_jsonb(d),\'receipt\',to_jsonb(r)) FROM authority_external_effect_dispatch d JOIN authority_external_effect e USING(external_effect_id) LEFT JOIN authority_external_receipt r USING(dispatch_id) WHERE e.project_id=ANY(%s) ORDER BY d.created_at,d.dispatch_id',[projects]).fetchall()]
  books=[r[0] for r in c.execute('SELECT to_jsonb(b) FROM authority_book_production b WHERE project_id=ANY(%s)',[projects]).fetchall()]
  requests=[r[0] for r in c.execute('SELECT to_jsonb(r) FROM authority_book_chapter_request r WHERE project_id=ANY(%s)',[projects]).fetchall()]
  deliveries=[r[0] for r in c.execute('SELECT to_jsonb(d) FROM authority_book_manuscript_delivery d JOIN authority_book_production b USING(book_run_id) WHERE b.project_id=ANY(%s)',[projects]).fetchall()]
  migration=[r[0] for r in c.execute('SELECT migration_id FROM nf_schema_migrations ORDER BY applied_at,migration_id').fetchall()]
  validation=[r[0] for r in c.execute('SELECT to_jsonb(v) FROM authority_story_planning_validation_report v WHERE project_id=ANY(%s)',[projects]).fetchall()]
 report={'test':item.nodeid,'started_at':started.isoformat(),'source_sha':source_sha,'working_diff_sha256':'sha256:'+hashlib.sha256(diff).hexdigest(),'evidence_class':'SCRIPTED_NATIVE_POSTGRESQL','database':identity[0],'cluster':identity[1],'projects':projects,'books':books,'chapter_requests':requests,'deliveries':deliveries,'migration_ids':migration,'validation_reports':validation,'assets':assets,'effects':effects,'operations':operations,'attempts':attempts,'receipts':receipts,'formal_qualification':'NOT_RUN','real_provider':'NOT_RUN'}
 name=hashlib.sha256((item.nodeid+'@'+started.isoformat()).encode()).hexdigest()[:16]
 (OUT/(name+'.json.gz')).write_bytes(gzip.compress((json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n').encode(), mtime=0))
 prose=[]
 for asset in assets:
  if asset['asset_type'] in {'draft_version','revision_version','draft_chapter','revision','chapter_revision','best_draft_candidate'}:
   content=asset['version']['content']
   if content.get('text'):prose.append({'asset_type':asset['asset_type'],'asset_version_id':asset['version']['asset_version_id'],'content_hash':asset['version']['content_hash'],'text':content['text'],'text_sha256':'sha256:'+hashlib.sha256(content['text'].encode()).hexdigest()})
 (OUT/(name+'-prose.json')).write_text(json.dumps({'test':item.nodeid,'prose':prose},ensure_ascii=False,indent=2)+'\n')
 item.user_properties.append(('native_postgresql_readback',str(OUT/(name+'.json.gz'))))

@pytest.hookimpl
def pytest_runtest_logreport(report):
 if report.when == 'call' and report.failed:
  name=hashlib.sha256((report.nodeid+str(report.start)).encode()).hexdigest()[:16]
  (OUT/(name+'-failure.txt')).write_text(str(report.longrepr)+'\n')
