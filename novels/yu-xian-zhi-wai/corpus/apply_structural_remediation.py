from pathlib import Path
import json,os,subprocess
R=Path(__file__).resolve().parent;E=R.parent;OUT=R/'native-remediation';OUT.mkdir(exist_ok=True)
ENV=os.environ|json.loads((E/'runtime/local-environment.json').read_text());BASE=['.venv/bin/python','-m','novel_forge.cli.authority','corpus']
def run(action,key,args):
 cmd=BASE+[action,'--project-id','first-novel-pilot-20260912','--workspace-id','first-novel-pilot-workspace','--run-key',key]+args
 out=subprocess.run(cmd,env=ENV,capture_output=True,text=True);(OUT/(key+'-output.json')).write_text(out.stdout);(OUT/(key+'.stderr')).write_text(out.stderr)
 if out.returncode:raise RuntimeError((key,out.stderr[-2500:]))
 v=json.loads(out.stdout);print(key,v.get('status',v.get('run_status')),flush=True);return v
def reprocess(id,key,edition,profile):
 a=run('reprocess',key,['--edition-id',edition,'--manifest',str(profile)])
 j=a['import_job_id'];run('run',key+'-execute',['--job-id',j,'--max-stages','10'])
 v=run('status',key+'-status',['--job-id',j]);stage=next(s['result'] for s in v['corpus']['stage_results'] if s['result'].get('processing_id'))
 detail=run('inspect',key+'-inspect',['--processing-id',stage['processing_id']]);return stage,OUT/(key+'-inspect-output.json')
summary={}
for id in ['railway-children','thirty-nine-steps']:
 old=json.loads((R/'native-imports'/(id+'-inspect.json')).read_text());rem=R/'structural-remediation'
 run('review',id+'-front-and-license-review-v1',['--decision',str(rem/(id+'-review-v1.json'))])
 stage,inspect=reprocess(id,id+'-nonbody-reprocess-v2',old['edition_id'],rem/(id+'-parser-v2.json'));summary[id]=stage
 (R/'current-fiction-processing.json').write_text(json.dumps(summary,indent=2))
id='study-in-scarlet';old=json.loads((R/'native-imports'/(id+'-inspect.json')).read_text());rem=R/'structural-remediation'
stage,inspect=reprocess(id,id+'-volume-boundaries-v2',old['edition_id'],rem/(id+'-parser-v2.json'))
review=rem/(id+'-review-v2.json')
subprocess.run(['.venv/bin/python',str(rem/'prepare.py'),'--name',id,'--inspect',str(inspect),'--output',str(review)],env=ENV,check=True)
run('review',id+'-front-and-license-review-v2',['--decision',str(review)])
stage,inspect=reprocess(id,id+'-nonbody-reprocess-v3',old['edition_id'],rem/(id+'-parser-v2.json'));summary[id]=stage
(R/'current-fiction-processing.json').write_text(json.dumps(summary,indent=2))
