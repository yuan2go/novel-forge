import os,json,subprocess,time
from pathlib import Path
from types import SimpleNamespace
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.cli.corpus import run_corpus_command
from bs4 import BeautifulSoup
base_dir=Path('/tmp/nf-corpus-wp3c-20260909');root=base_dir/'real-frozen-d8252aa5';summary=json.loads((root/'curation-summary.json').read_text());project=summary['project_id'];workspace=summary['workspace_id']
os.environ['NOVEL_FORGE_DATABASE_URL']=json.loads((base_dir/'sample-environment.json').read_text())['database_url']
os.environ.update(NOVEL_FORGE_APPLICATION_BUILD_ID='corpus-quality-real',NOVEL_FORGE_COMMIT_SHA=summary['tested_sha'],NOVEL_FORGE_ENVIRONMENT='test',NOVEL_FORGE_MODEL_PROVIDER='mock',NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND='local',NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT=str(root/'objects'),NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE=project,NOVEL_FORGE_CORPUS_CACHE_ROOT=str(root/'cache'),NOVEL_FORGE_CORPUS_LOCAL_ROOTS=json.dumps([str(base_dir/'public')]),NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT=str(root/'git'))
settings=IndustrialSettings(root=root,environment='test',database_url=os.environ['NOVEL_FORGE_DATABASE_URL']);base=dict(project_id=project,workspace_id=workspace,manifest=None,run_key='',job_id='',after='',limit=100,max_stages=20,reason='source-linked verification',edition_id='',processing_id='',compare_to='',decision=None,work_id='',corpus_id='',revision_id='',historical=False)
records=[]
def run(action,**kw):
 start=time.monotonic()
 try:
  result=run_corpus_command(settings,SimpleNamespace(**{**base,'action':action,**kw}));records.append({'action':action,'seconds':time.monotonic()-start,'result':result});return result
 except Exception as exc:
  records.append({'action':action,'seconds':time.monotonic()-start,'error':repr(exc)});raise
 finally:(root/'independent-operations.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,default=str))
def file(name,data):
 p=root/(name+'.json');p.write_text(json.dumps(data,ensure_ascii=False,indent=2));return p
def decide(action,data,key):return run(action,decision=file(key,data),run_key=key)
outcomes=[]
for receipt,number,title,author,chapter in zip(json.loads((base_dir/'public/independent-excerpt-receipts.json').read_text()),['23950','23962'],['三國演義','西遊記'],['羅貫中','吳承恩'],['第一回 宴桃園豪傑三結義 斬黃巾英雄首立功','第一回 靈根育孕源流出 心性修持大道生'],strict=True):
 if receipt['status']!='VERIFIED_ACQUIRED_EXCERPT_ONLY':continue
 parser={'version':'corpus-parser.v3','format':'html','layout':'SINGLE_WORK','html_body_selector':'.mw-parser-output','html_remove_selectors':['script','style','nav','table.ws-header','#headerContainer','.ws-noexport','.licenseContainer','.printfooter'],'constants':{'work_id':'wikisource:'+title,'work_title':title,'author':author,'chapter_id':'1','order':1,'title':chapter},'normalization':{'version':'chinese-longform.v2','segmentation':'EXPLICIT','min_body_chars':80},'completeness':'EXCERPT'}
 manifest={'source':{'kind':'LOCAL','location':str(base_dir/'public'/receipt['file'])},'parser':parser,'purpose':'RESEARCH','rights':{'dataset_license':'Wikisource CC BY-SA / underlying public-domain text; annotations not automatically cleared','scope':'ALL_WORKS_IN_SNAPSHOT','underlying_rights':'PUBLIC_DOMAIN','allowed_purposes':['RESEARCH'],'allowed_uses':['LOCAL_PROCESSING'],'evidence_refs':[receipt['fixed_url'],'sha256:'+receipt['sha256']],'copyright_boundary':'Historical prose excerpt only; no model-analysis or generation authorization from this acquisition.'},'analyze':False}
 admitted=run('import',manifest=file('independent-'+number,manifest),run_key='independent-'+number);run('run',job_id=admitted['import_job_id']);lineage=run('lineage',job_id=admitted['import_job_id']);edition=lineage['editions'][0]['edition_id'];processing=run('inspect',edition_id=edition);assert processing['assessment']['coverage']=='EXCERPT'
 primary=next(x for x in summary['samples'] if x['key']==number+'-txt');comparison=run('compare',processing_id=primary['processing_id'],compare_to=processing['processing_id'])
 work_id=summary['canonical_works']['revisions'][0 if number=='23950' else 1]['work_id'];current=run('work',work_id=work_id);change={k:v for k,v in current['manifest'].items() if k!='decision_reason'};change['previous_id']=current['revision_id'];change['members'].append({'processing_id':processing['processing_id'],'relation':'EXCERPT','evidence_refs':[receipt['fixed_url'],'sha256:'+receipt['sha256']]})
 updated=decide('resolve-work',{'action':'resolve_canonical_works','changes':[change],'reason':'Independent site chapter excerpt; explicit work relation does not assert whole-edition equivalence'},'independent-group-'+number)
 outcomes.append({'source':receipt,'processing_id':processing['processing_id'],'coverage':processing['assessment']['coverage'],'comparison':comparison['comparison'],'work_revision':updated,'whole_independent_edition':'NOT_VERIFIED'})
prior=run('curated',corpus_id=summary['curated']['corpus_id']);assert not prior['analysis_dispatchable']
selection={'action':'revise_curated_corpus','corpus_key':'chinese-classics-research','title':'中文长篇研究子集','purpose':'RESEARCH','previous_id':prior['revision_id'],'filters':{'language':'zh'},'reason':'Refresh exact group revisions; retain unselected independent excerpts and blocked sources'}
candidate=decide('curate',selection,'independent-candidates');state=run('curated',corpus_id=candidate['corpus_id']);selected={x['processing_id'] for x in summary['samples'] if x['key'] in ('23962-txt','24264-txt')};choices=[{'processing_id':m['processing_id'],'selected':m['processing_id'] in selected,'reason':'Retain scoped full-source research sample' if m['processing_id'] in selected else 'Explicitly exclude unresolved structure or excerpt-only acquisition','evidence_refs':['processing:'+m['processing_id']]} for m in state['members']]
frozen=decide('curate',{**selection,'previous_id':candidate['revision_id'],'state':'FROZEN','choices':choices},'independent-frozen');assert frozen['selected_count']==2
(root/'independent-summary.json').write_text(json.dumps({'tested_sha':summary['tested_sha'],'independent_sources':outcomes,'prior_selection_invalidated':True,'curated':frozen,'real_model_calls':0},ensure_ascii=False,indent=2));print('independent excerpts imported and explicitly related; two-member subset frozen')
