from pathlib import Path
import hashlib,json,os,subprocess,sys
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
base=Path(__file__).parent
service=base.parent
config=json.loads((service/'recovery-env.private.json').read_text())
dsn=config['NOVEL_FORGE_DATABASE_URL']
identity=conninfo_to_dict(dsn)
assert identity.get('dbname')=='nf_qidian_learning_20261008_test'
assert identity.get('port')=='55489'
tables=('authority_operation','authority_external_effect','authority_external_effect_dispatch','authority_external_receipt','authority_budget_reservation','authority_book','authority_book_foundation_binding','authority_asset_version','authority_story_planning_generation','authority_book_production','authority_book_chapter_acceptance','authority_book_prose_review_run')
snapshot={}
with psycopg.connect(make_conninfo(dsn,options='-c default_transaction_read_only=on',connect_timeout=5)) as c:
 snapshot['database']=c.execute('SELECT current_database()').fetchone()[0]
 for table in tables:
  rows=c.execute(sql.SQL('SELECT to_jsonb(t) FROM {} t').format(sql.Identifier(table))).fetchall()
  encoded=sorted(json.dumps(row[0],sort_keys=True,separators=(',',':'),default=str) for row in rows)
  snapshot[table]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(encoded).encode()).hexdigest()}
phase=sys.argv[1]
(base/f'ledger-{phase}.json').write_text(json.dumps(snapshot,indent=2)+'\n')
if phase=='before':
 env=dict(os.environ)
 for key,name in [('dbname','PGDATABASE'),('host','PGHOST'),('port','PGPORT'),('user','PGUSER'),('password','PGPASSWORD')]:
  if key in identity: env[name]=identity[key]
 env['PGCONNECT_TIMEOUT']='5'
 env['PGOPTIONS']='-c default_transaction_read_only=on'
 with (base/'backup.log').open('w') as log:
  subprocess.run(['/opt/homebrew/opt/postgresql@16/bin/pg_dump','-Fc','-f',str(base/'before-window-deployment.dump')],env=env,stdout=log,stderr=log,check=True)
 backup=base/'before-window-deployment.dump';backup.chmod(0o600)
 with backup.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
 (base/'backup.json').write_text(json.dumps({'sha256':digest,'bytes':backup.stat().st_size,'database':snapshot['database']},indent=2)+'\n')
 print('Original recovery-point database backup verified:',backup.stat().st_size,'bytes')
else:
 before=json.loads((base/'ledger-before.json').read_text())
 comparison={k:before[k]==snapshot[k] for k in snapshot}
 (base/'ledger-unchanged.json').write_text(json.dumps(comparison,indent=2)+'\n')
 assert all(comparison.values()),comparison
 print('Original business tables unchanged:',len(tables))
