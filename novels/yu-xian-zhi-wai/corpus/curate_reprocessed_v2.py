from pathlib import Path
import json,os,subprocess
R=Path(__file__).resolve().parent; E=R.parent; OUT=R/'native-curation'
ENV=os.environ|json.loads((E/'runtime/local-environment.json').read_text())
def call(action,key,decision=None,extra=None):
 cmd=['.venv/bin/python','-m','novel_forge.cli.authority','corpus',action,'--project-id','first-novel-pilot-20260912','--workspace-id','first-novel-pilot-workspace','--run-key',key]+(extra or [])
 if decision:
  p=OUT/(key+'-input.json'); p.write_text(json.dumps(decision,ensure_ascii=False,indent=2));cmd+=['--decision',str(p)]
 result=subprocess.run(cmd,env=ENV,capture_output=True,text=True);(OUT/(key+'-output.json')).write_text(result.stdout);(OUT/(key+'.stderr')).write_text(result.stderr)
 if result.returncode: raise RuntimeError((key,result.stderr[-2000:]))
 return json.loads(result.stdout)
C={e['id']:e for e in json.loads((R/'catalogue.json').read_text())['entries']}
I={e['id']:e for e in json.loads((R/'native-import-summary.json').read_text())['entries']}
for id,item in I.items(): item.update(next(s['result'] for s in item['stage_results'] if s['result'].get('processing_id')))
current=json.loads((R/'current-fiction-processing.json').read_text())
for id,stage in current.items(): I[id].update(stage)
old=json.loads((OUT/'pilot-canonical-v1-input.json').read_text())
revisions=json.loads((OUT/'pilot-canonical-v1-output.json').read_text())['revisions']
changes=[]
for change,rev in zip(old['changes'],revisions):
 if len(change['members'])!=1:continue
 id=next(id for id,c in C.items() if c['work_identity']==change['work_key'])
 changes.append(change|{'previous_id':rev['revision_id'],'members':[change['members'][0]|{'processing_id':I[id]['processing_id']}]})
resolved=call('resolve-work','pilot-canonical-fiction-v2',decision=old|{'changes':changes,'reason':'Bind existing bibliographic works to native reviewed/reprocessed exact source revisions; preserve original metadata, rights and history.'})
action=json.loads((OUT/'pilot-next-candidate-v1-input.json').read_text())
previous=json.loads((OUT/'pilot-next-candidate-v1-output.json').read_text())['revision_id']
candidate=call('curate','pilot-next-candidate-v2',decision=action|{'previous_id':previous})
call('curated','pilot-next-candidate-inspect-v2',extra=['--revision-id',candidate['revision_id']])
selected=['hydraulics-14','hydraulics-16','railway-children']
choices=[{'processing_id':item['processing_id'],'selected':id in selected,'reason':'Selected bounded text mechanism / continuous original fiction window; not knowledge approval' if id in selected else ('Quarantined text-unit contradiction (psi/kPa); not selected' if id=='hydraulics-09' else 'Outside first bounded analysis; visuals unqualified where present'),'evidence_refs':[C[id]['requested_url'],C[id]['raw_path']]} for id,item in I.items()]
frozen=call('curate','pilot-next-freeze-v2',decision=action|{'previous_id':candidate['revision_id'],'state':'FROZEN','choices':choices})
selections={}
for name,ids,v in [('canary',['hydraulics-12'],json.loads((OUT/'pilot-canary-freeze-v1-output.json').read_text())),('next',selected,frozen)]:
 selections[name]={'corpus_id':v['corpus_id'],'revision_id':v['revision_id'],'selected_source_ids':ids,'source_processings':{id:I[id]['processing_id'] for id in ids}}
 for id in ids:call('chapters','pilot-current-chapters-'+id,extra=['--processing-id',I[id]['processing_id'],'--limit','100'])
(R/'selections.json').write_text(json.dumps(selections,ensure_ascii=False,indent=2))
print(json.dumps({'native_selected':selections,'analysis':'NOT_RUN','knowledge_approval':'NOT_RUN'},indent=2))

