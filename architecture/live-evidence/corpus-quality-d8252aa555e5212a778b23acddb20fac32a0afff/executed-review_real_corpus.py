import os,json,subprocess,time,resource
from pathlib import Path
from types import SimpleNamespace
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.cli.corpus import run_corpus_command
base_dir=Path('/tmp/nf-corpus-wp3c-20260909');root=base_dir/('real-'+os.environ.get('CORPUS_CAMPAIGN','development-4'));summary=json.loads((root/'summary.json').read_text());project=summary['project_id'];workspace=summary['workspace_id']
os.environ['NOVEL_FORGE_DATABASE_URL']=json.loads((base_dir/'sample-environment.json').read_text())['database_url']
os.environ.update(NOVEL_FORGE_APPLICATION_BUILD_ID='corpus-quality-real',NOVEL_FORGE_COMMIT_SHA=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),NOVEL_FORGE_ENVIRONMENT='test',NOVEL_FORGE_MODEL_PROVIDER='mock',NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND='local',NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT=str(root/'objects'),NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE=project,NOVEL_FORGE_CORPUS_CACHE_ROOT=str(root/'cache'),NOVEL_FORGE_CORPUS_LOCAL_ROOTS=json.dumps([str(base_dir/'public')]),NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT=str(root/'git'))
settings=IndustrialSettings(root=root,environment='test',database_url=os.environ['NOVEL_FORGE_DATABASE_URL']);base=dict(project_id=project,workspace_id=workspace,manifest=None,run_key='',job_id='',after='',limit=100,max_stages=30,reason='source-linked verification',edition_id='',processing_id='',compare_to='',decision=None,work_id='',corpus_id='',revision_id='',historical=False)
records=[]
def run(action,**kw):
 start=time.monotonic()
 try:
  result=run_corpus_command(settings,SimpleNamespace(**{**base,'action':action,**kw}));records.append({'action':action,'seconds':time.monotonic()-start,'result':result});return result
 except Exception as exc:
  records.append({'action':action,'seconds':time.monotonic()-start,'error':repr(exc)});raise
 finally:
  (root/'curation-operations.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,default=str))
def decision(action,data,key):
 p=root/(key+'.json');p.write_text(json.dumps(data,ensure_ascii=False,indent=2));return run(action,decision=p,run_key=key)
sg=next(x for x in summary['samples'] if x['key']=='23950-txt');state=run('inspect',edition_id=sg['edition_id'])
classifications={4:('VERSION_WORDING','为皇/践位: observed wording difference; edition authority insufficient'),9:('VERSION_WORDING','暴凶/暴徒: observed wording difference; no silent correction'),16:('TRANSCRIPTION_SUSPECTED','拜师/败师: suspected input error, unresolved without edition facsimile'),18:('TRANSCRIPTION_SUSPECTED','失/矢: suspected wrong character; original preserved'),26:('DISPLAY','挂/掛: glyph variant; both source headings explicitly located'),42:('INSUFFICIENT','板/阪 and absent 口: mixed glyph/wording evidence, retain unresolved'),47:('INSUFFICIENT','missing 降: cannot distinguish abridgement from transcription'),60:('DISPLAY','脩/修: name glyph variant; limited to this title comparison'),74:('TRANSCRIPTION_SUSPECTED','臺/擡: suspected input error, no global glyph cleaning'),80:('VERSION_WORDING','續/繼: equivalent action does not establish same edition'),102:('VERSION_WORDING','戰/占: different wording; cannot resolve from directory alone'),111:('VERSION_WORDING','敗/取: source titles differ, independent edition proof absent'),112:('TRANSCRIPTION_SUSPECTED','鑿/鏖: suspected wrong word, evidence not sufficient for correction'),115:('TRANSCRIPTION_SUSPECTED','纔/讒: suspected wrong character, no silent textual emendation')}
resolutions=[];attributions=[]
for finding in state['assessment']['issues']:
 if finding['code']!='TOC_ENTRY_MISMATCH' or finding.get('resolution'):continue
 chapter=finding['toc_index']+1;classification,reason=classifications[chapter];refs=[finding['toc_evidence'],'sha256:'+sg['acquisition']['sha256'], 'normalized-unit:'+finding['evidence'][0]['content_hash']]
 resolutions.append({'issue_id':finding['issue_id'],'resolution':'CONFIRM_TOC_VARIANT' if classification=='DISPLAY' else 'ANNOTATE_TOC_DIFFERENCE','classification':classification,'evidence_refs':refs,'reason':reason+'; Agent annotation, not independent human.'})
 attributions.append({'chapter':chapter,'expected':finding['expected_title'],'observed':finding['observed_title'],'classification':classification,'decision':'LIMITED_DISPLAY_ACCEPTANCE' if classification=='DISPLAY' else 'UNRESOLVED','reason':reason,'evidence':finding['evidence'],'source_refs':refs})
assert len(attributions)==14
(root/'catalogue-attributions.json').write_text(json.dumps({'catalogue_acquisition':next(r for r in json.loads((base_dir/'public/receipts.json').read_text()) if r['name'].startswith('catalogue-')),'annotation_class':'AGENT_NOT_INDEPENDENT_HUMAN','differences':attributions,'display_resolved':2,'remaining':12,'expanded_cleaning':False},ensure_ascii=False,indent=2))
decision('review',{'action':'review_processing','processing_id':state['processing_id'],'previous_id':state['review']['review_id'] if state['review'] else None,'decisions':resolutions,'reason':'Classify exactly 14 current acquired-source title discrepancies'},'sanguo-title-review')
re=run('reprocess',edition_id=sg['edition_id'],manifest=root/'23950-txt-parser.json',run_key='sanguo-title-review-reprocess');run('run',job_id=re['import_job_id']);sg['processing_id']=run('inspect',edition_id=sg['edition_id'])['processing_id']
hl=next(x for x in summary['samples'] if x['key']=='24264-txt');state=run('inspect',edition_id=hl['edition_id']);units={u['unit_id']:u for u in state['assessment']['units']};raw=(base_dir/'public/24264.txt').read_bytes();decisions=[]
for finding in state['assessment']['issues']:
 if finding['code']!='SHORT_OR_TOC_UNIT' or finding.get('resolution'):continue
 for ev in finding['evidence']:
  loc=ev['locator'];text=raw[loc['original_byte_offset']:loc['original_byte_end']].decode('utf-8');lines=text.splitlines()
  if len(lines)>1 and all(not line.strip(' -') for line in lines[1:]):
   decisions.append({'issue_id':finding['issue_id'],'resolution':'MARK_NON_BODY','reason':'Exact duplicate printed heading followed only by separator lines, source bytes '+str(loc['original_byte_offset'])+':'+str(loc['original_byte_end'])+'; no narrative prose excluded. Agent verified.'})
assert len(decisions)==1
review=decision('review',{'action':'review_processing','processing_id':state['processing_id'],'previous_id':state['review']['review_id'] if state['review'] else None,'decisions':decisions,'reason':'Exclude one verified title-only occurrence; recompute number/title checks'},'honglou-duplicate-heading')
re=run('reprocess',edition_id=hl['edition_id'],manifest=root/'24264-txt-parser.json',run_key='honglou-heading-reprocess');run('run',job_id=re['import_job_id']);state=run('inspect',edition_id=hl['edition_id']);hl['processing_id']=state['processing_id'];assert state['assessment']['chapter_count']==120 and state['assessment']['structure_usable'],state['assessment']['issues']
changes=[]
for number,title in [('23950','三國志演義'),('23962','西遊記'),('24264','紅樓夢')]:
 members=[{'processing_id':x['processing_id'],'relation':'SAME_WORK','evidence_refs':['https://www.gutenberg.org/ebooks/'+number,'sha256:'+x['acquisition']['sha256']]} for x in summary['samples'] if x['key'].startswith(number) and 'processing_id' in x]
 changes.append({'work_key':'gutenberg-'+number,'title':title,'language':'zh','external_ids':{'gutenberg':number},'metadata_evidence':['https://www.gutenberg.org/ebooks/'+number],'members':members})
works=decision('resolve-work',{'action':'resolve_canonical_works','changes':changes,'reason':'Explicit same publisher work identifiers; format variants do not claim independent sites or rights'},'canonical-three')
selection={'action':'revise_curated_corpus','corpus_key':'chinese-classics-research','title':'中文长篇研究子集','purpose':'RESEARCH','filters':{'language':'zh'},'reason':'Retain all reviewed candidates and explicitly select usable subset'}
candidate=decision('curate',selection,'research-candidates');state=run('curated',corpus_id=candidate['corpus_id']);choices=[]
for m,a in zip(state['members'],state['current_availability'],strict=True):
 assert m['processing_id']==a['processing_id'];choices.append({'processing_id':m['processing_id'],'selected':a['available'],'reason':'Eligible acquired chapter structure' if a['available'] else 'Blocked: '+','.join(a['reasons']),'evidence_refs':['processing:'+m['processing_id'],'agent:scoped-catalogue-review']})
frozen=decision('curate',{**selection,'state':'FROZEN','previous_id':candidate['revision_id'],'choices':choices},'research-frozen');assert frozen['selected_count']==2,frozen
compare=run('compare',processing_id=hl['processing_id'],compare_to=next(x['processing_id'] for x in summary['samples'] if x['key']=='24264-epub'))
summary.update(catalogue={'differences':14,'display_resolved':2,'unresolved':12},canonical_works=works,curated=frozen,version_comparison=compare['comparison'],curation_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,real_analysis='NOT_RUN_NO_MODEL_BUDGET',final_processings=[{'edition_id':x['edition_id'],'processing_id':x['processing_id']} for x in summary['samples'] if 'processing_id' in x]);(root/'curation-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str));print(json.dumps({'curated':frozen,'catalogue':summary['catalogue']},ensure_ascii=False))
