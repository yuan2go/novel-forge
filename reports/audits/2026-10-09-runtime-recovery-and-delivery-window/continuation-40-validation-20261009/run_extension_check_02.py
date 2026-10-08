import datetime,json,os,pathlib,subprocess,uuid
import psycopg
from psycopg import sql
REPO=pathlib.Path('/Users/yuan/.codex/worktrees/work-adaptation-reader-prose-01/novel-forge')
OUT=pathlib.Path(__file__).parent / "extension-check-02"
OUT.mkdir(exist_ok=True)
PYTHON='/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python'
RUN=uuid.uuid4().hex
ADMIN='host=127.0.0.1 port=55690 user=yuan dbname=postgres connect_timeout=5'
GROUPS={'delivery-window':['tests/integration/test_book_delivery_window_postgres.py'],'cross-chapter-review':['tests/integration/test_cross_chapter_prose_review_postgres.py']}
with psycopg.connect(ADMIN) as c:
 identity=c.execute('SELECT current_database(),inet_server_port(),current_user,pg_postmaster_start_time()').fetchone()
 if identity[:3]!=('postgres',55690,'yuan'): raise RuntimeError('isolated test service identity mismatch')
summary={'run_id':RUN,'baseline_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),'test_service_identity':list(identity),'groups':[],'real_model_calls':0,'original_database_used':False}
(OUT/'results.json').write_text(json.dumps(summary,default=str,indent=2))
for name,files in GROUPS.items():
 database='nf_40_'+name.replace('-','_')+'_'+RUN[:16]+'_test'
 with psycopg.connect(ADMIN,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
 env={k:v for k,v in os.environ.items() if not k.startswith(('NOVEL_FORGE_','OPENAI_','DEEPSEEK_','ANTHROPIC_','CODEX_'))}
 env.update(PYTHONPATH=str(REPO/'src')+':'+str(REPO),NOVEL_FORGE_DATABASE_URL=f'host=127.0.0.1 port=55690 user=yuan dbname={database}')
 command=[PYTHON,'-m','pytest','-q',*files,'--junitxml='+str(OUT/(name+'.xml'))]
 record={'name':name,'database':database,'files':files,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'log':name+'.log','command':command}
 print('START',name,flush=True)
 try:
  with (OUT/(name+'.log')).open('w') as log:
   result=subprocess.run(command,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
  record['exit_code']=result.returncode
 except Exception as exc:record.update(exit_code=None,error=repr(exc))
 finally:
  with psycopg.connect(ADMIN,autocommit=True) as c:
   c.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',[database])
   c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
  record['test_database_removed']=True;record['completed_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
 summary['groups'].append(record);(OUT/'results.json').write_text(json.dumps(summary,default=str,indent=2));print('DONE',name,record.get('exit_code'),flush=True)
 print('\n'.join((OUT/(name+'.log')).read_text().splitlines()[-8:]),flush=True)
