from pathlib import Path
import json,subprocess
R=Path(__file__).resolve().parent;nf=R.parent/'runtime/nf';selections=json.loads((R/'selections.json').read_text())
for name in ['canary','next']:
 cmd=[str(nf),'corpus','reading-preview','--project-id','first-novel-pilot-20260912','--workspace-id','first-novel-pilot-workspace','--revision-id',selections[name]['revision_id'],'--reading-scopes',str(R/(name+'-reading-scopes.json')),'--intended-use','ABSTRACT_GENERATION','--target-book-id','first-novel-pilot-a','--max-calls','60','--max-tokens','1500000']
 run=subprocess.run(cmd,capture_output=True,text=True);(R/(name+'-reading-preview-final.json')).write_text(run.stdout);(R/(name+'-reading-preview-final.stderr')).write_text(run.stderr)
 if run.returncode:raise RuntimeError((name,run.stderr[-2500:]))
 v=json.loads(run.stdout);print(name,json.dumps(v,ensure_ascii=False)[:1200])

