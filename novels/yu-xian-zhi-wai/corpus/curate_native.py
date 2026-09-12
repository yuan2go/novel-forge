from pathlib import Path
import json,os,subprocess
R=Path(__file__).resolve().parent;E=R.parent
ENV=os.environ|json.loads((E/'runtime/local-environment.json').read_text());OUT=R/'native-curation';OUT.mkdir(exist_ok=True)
C={e['id']:e for e in json.loads((R/'catalogue.json').read_text())['entries']}
I={e['id']:e for e in json.loads((R/'native-import-summary.json').read_text())['entries']}
for id,item in I.items():
 stage=next(s['result'] for s in item['stage_results'] if s['result'].get('processing_id'));item.update(stage)
def call(action,key,extra=None,decision=None):
 cmd=['.venv/bin/python','-m','novel_forge.cli.authority','corpus',action,'--project-id','first-novel-pilot-20260912','--workspace-id','first-novel-pilot-workspace','--run-key',key]+(extra or [])
 if decision:
  file=OUT/(key+'-input.json');file.write_text(json.dumps(decision,ensure_ascii=False,indent=2));cmd+=['--decision',str(file)]
 out=subprocess.run(cmd,env=ENV,capture_output=True,text=True);(OUT/(key+'-output.json')).write_text(out.stdout);(OUT/(key+'.stderr')).write_text(out.stderr)
 if out.returncode:raise RuntimeError((key,out.stderr[-3000:]))
 return json.loads(out.stdout)
works={}
for id,e in C.items():works.setdefault(e['work_identity'],[]).append(id)
changes=[]
for work,ids in works.items():
 first=C[ids[0]];professional=ids[0].startswith('hydraulics-')
 changes.append({'work_key':work,'title':'Fluids 2: Basic Hydraulics — Jessy Haid / NWTC (17 acquired section excerpts)' if professional else first['title'],'language':'en','genre_tags':['professional','hydraulics'] if professional else ['fiction','narrative-craft'],'external_ids':{'publisher_work':first['requested_url'].split('/02%3A')[0] if professional else first['work_identity']},'metadata_evidence':[first['requested_url'],first['raw_path']],'members':[{'processing_id':I[id]['processing_id'],'relation':'EXCERPT' if professional else 'SAME_WORK','evidence_refs':[C[id]['requested_url'],'sha256:'+C[id]['sha256']]} for id in ids]})
resolved=call('resolve-work','pilot-canonical-v1',decision={'action':'resolve_canonical_works','changes':changes,'reason':'Native bibliographic grouping: one professional textbook with disjoint section excerpts and three original novels. No rights transfer; page licenses remain independent.'})
work_ids=[r['work_id'] for r in resolved['revisions']]
selections={}
for name,selected in [('canary',['hydraulics-12']),('next',['hydraulics-14','hydraulics-16','railway-children'])]:
 action={'action':'revise_curated_corpus','corpus_key':'first-novel-'+name,'title':'First novel '+name+' source selection','purpose':'PRODUCTION_REFERENCE','filters':{'work_ids':work_ids},'candidate_limit':30,'reason':'Operator source selection only; not knowledge approval or paid-call authorization.'}
 candidate=call('curate','pilot-'+name+'-candidate-v1',decision=action)
 candidate_id=candidate['revision_id']
 view=call('curated','pilot-'+name+'-candidate-inspect-v1',extra=['--revision-id',candidate_id])
 choices=[{'processing_id':I[id]['processing_id'],'selected':id in selected,'reason':'Selected text-only mechanism / continuous original fiction window; evidence and assumptions require Source review' if id in selected else 'Outside first bounded analysis; preserve acquisition. '+('Known psi/kPa contradiction: quarantine.' if id=='hydraulics-09' else 'Visual content or unrelated current scope not qualified for analysis.'),'evidence_refs':[C[id]['requested_url'],C[id]['raw_path']]} for id in I]
 frozen=call('curate','pilot-'+name+'-freeze-v1',decision=action|{'previous_id':candidate_id,'state':'FROZEN','choices':choices})
 selections[name]={'corpus_id':frozen['corpus_id'],'revision_id':frozen['revision_id'],'selected_source_ids':selected,'source_processings':{id:I[id]['processing_id'] for id in selected}}
 print(name,frozen['status'],frozen['selected_count'],flush=True)
 for id in selected:
  call('chapters','pilot-chapters-'+id,extra=['--processing-id',I[id]['processing_id'],'--limit','100'])
(R/'selections.json').write_text(json.dumps(selections,ensure_ascii=False,indent=2))
