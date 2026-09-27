import json,os
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from novel_forge.cli.runtime_inspection import inspect_runtime
from novel_forge.modules.command_kernel.dispatch_control import dispatch_control_status
base=Path('/tmp/novel-forge-real-prose-20260927');old=json.loads((base/'live-inspection.json').read_text());db=os.environ['NOVEL_FORGE_DATABASE_URL']
with psycopg.connect(db,options='-c default_transaction_read_only=on') as c:
    assert c.execute('SELECT current_database()').fetchone()[0]=='novel_forge_REDACTED_PRIVATE_IDENTIFIER_test'
    projects=[r[0] for r in c.execute('SELECT project_id FROM authority_project ORDER BY project_id')]
    books=[r[0] for r in c.execute('SELECT to_jsonb(b) FROM authority_book b')]
    acceptance=c.execute('SELECT count(*) FROM authority_book_chapter_acceptance').fetchone()[0]
    sample_assets=[dict(zip(('asset_type','count'),r)) for r in c.execute("SELECT a.asset_type,count(*) FROM authority_asset a JOIN authority_asset_version v USING(asset_id) WHERE a.project_id='narrative-closure-02-admission-20260927' GROUP BY a.asset_type")]
ledgers=json.loads(json.dumps([inspect_runtime(db,project_id=p,expected_database='novel_forge_REDACTED_PRIVATE_IDENTIFIER_test') for p in projects],default=str))
previous=old['ledgers'][0];current=next(d for d in ledgers if d['project_id']==previous['project_id'])
keys=('book_production','effect_counts','unresolved_effects','budget_reservations','budget_scopes','provider_dispatches')
preserved={k:previous[k]==current[k] for k in keys}
oldbooks={b['book_id']:b for b in old['books']};nowbooks={b['book_id']:b for b in books}
preserved['book_records']=all(nowbooks[k]==v for k,v in oldbooks.items());assert all(preserved.values()),preserved
result={'observed_at':datetime.now(timezone.utc).isoformat(),'read_only':True,'historical_invariants_unchanged':preserved,'books':[{'project_id':b['project_id'],'book_id':b['book_id'],'status':b['status'],'version':b['version']} for b in books], 'accepted_chapters':acceptance,'sampling_assets':sample_assets,'ledgers':ledgers,'controls':{p:dispatch_control_status(db,project_id=p) for p in projects}}
p=base/'live-final.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str));p.chmod(0o600)
print(json.dumps({'historical_invariants_unchanged':preserved,'accepted_chapters':acceptance,'projects':projects,'provider_dispatches':{d['project_id']:d['provider_dispatches'] for d in ledgers}},ensure_ascii=False))
