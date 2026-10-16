import json,os,subprocess,uuid
from pathlib import Path
import psycopg
from psycopg import sql
label='semantic-process-restart-'+subprocess.check_output(['git','rev-parse','--short=8','HEAD'],text=True).strip();reg=Path('/tmp/nf-context-512k-current-resource.json');v=json.loads(reg.read_text());db='nf_p0_'+uuid.uuid4().hex+'_test'
saved=Path('/tmp/nf-context-512k-'+label+'-env.json')
if saved.exists():
 env={**os.environ,**json.loads(saved.read_text())};db=env['NOVEL_FORGE_QUALIFICATION_DATABASE_NAME'];root=Path(env['NOVEL_FORGE_POSTGRES_EVIDENCE_DIR']);assert db in v['additional_databases']
 with psycopg.connect(env['NOVEL_FORGE_DATABASE_URL']) as c:
  assert c.execute('SELECT count(*) FROM authority_external_effect').fetchone()[0]==0
else:
 with psycopg.connect('postgresql://novel_forge:novel_forge@127.0.0.1:55012/postgres',autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {} OWNER novel_forge').format(sql.Identifier(db)))
 v['additional_databases'].append(db);reg.write_text(json.dumps(v));root=Path(v['root'])/label;root.mkdir();env={**os.environ,'NOVEL_FORGE_DATABASE_URL':'postgresql://novel_forge:novel_forge@127.0.0.1:55012/'+db,'NOVEL_FORGE_QUALIFICATION_DATABASE_NAME':db,'NOVEL_FORGE_POSTGRES_EVIDENCE_DIR':str(root)}
 saved.write_text(json.dumps({k:x for k,x in env.items() if k.startswith('NOVEL_FORGE_')}))
subprocess.run(['.venv/bin/python','-c','import os; from novel_forge.storage.migrations import run_migrations; assert run_migrations(os.environ["NOVEL_FORGE_DATABASE_URL"])["ok"]'],env=env,check=True,stdout=subprocess.DEVNULL)
args=['.venv/bin/python','/tmp/nf-semantic-process-restart-native.py'];journal=str(root/'checkpoint.json')
for mode,code in [('checkpoint',75),('resume',0)]:
 print('START',mode,flush=True)
 result=subprocess.run([*args,mode,'--journal',journal],env=env)
 assert result.returncode==code,(mode,result.returncode)
print('NATIVE_PROCESS_RESTART_PASS',flush=True)
