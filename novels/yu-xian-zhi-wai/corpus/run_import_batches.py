from pathlib import Path
import json,os,subprocess,sys,time
R=Path(__file__).resolve().parent;E=R.parent
ENV=os.environ|json.loads((E/'runtime/local-environment.json').read_text())
PLAN=json.loads((R/'import-plan.json').read_text())['entries'];LOG=R/'native-imports';LOG.mkdir(exist_ok=True)
BASE=['.venv/bin/python','-m','novel_forge.cli.authority','corpus']
def cli(identity,action,extra):
 cmd=BASE+[action,'--project-id','first-novel-pilot-20260912']+extra
 start=time.monotonic();out=subprocess.run(cmd,env=ENV,capture_output=True,text=True)
 (LOG/(identity+'-'+action+'.json')).write_text(out.stdout)
 (LOG/(identity+'-'+action+'.stderr')).write_text(out.stderr)
 if out.returncode:raise RuntimeError(f'{action} exit {out.returncode}: {out.stderr[-1200:]}')
 return json.loads(out.stdout),time.monotonic()-start
summary=[]
for item in PLAN:
 try:
  admission,_=cli(item['id'],'import',['--workspace-id','first-novel-pilot-workspace','--manifest',item['manifest'],'--run-key',item['run_key']])
  job=admission['import_job_id']
  run,elapsed=cli(item['id'],'run',['--job-id',job,'--max-stages','10'])
  lineage,_=cli(item['id'],'lineage',['--job-id',job,'--limit','50'])
  status,_=cli(item['id'],'status',['--job-id',job])
  summary.append(item|{'import_job_id':job,'operation_id':admission['operation_id'],'admission_replayed':admission['replayed'],'status':status['status'],'effective_status':status.get('effective_status'),'run_seconds':elapsed,'lineage_export':str(LOG/(item['id']+'-lineage.json')),'stage_results':status.get('corpus',{}).get('stage_results',[])})
  print(item['batch_id'],item['id'],status['status'],round(elapsed,2),flush=True)
 except Exception as e:
  summary.append(item|{'status':'OPERATOR_EXECUTION_ERROR','error':str(e)});print(item['id'],'FAILED',str(e),flush=True)
 (R/'native-import-summary.json').write_text(json.dumps({'entries':summary,'authority':'Native PostgreSQL query exports; no model analysis scheduled'},ensure_ascii=False,indent=2))
